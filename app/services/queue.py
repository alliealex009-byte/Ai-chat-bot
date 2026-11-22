"""Bounded inference queue.

* At most `concurrency` inferences run at once (protects the 8-vCPU / 16 GB box).
* At most `max_size` jobs wait; extra jobs are rejected immediately (reliability over acceptance).
* At most `per_user` jobs (waiting + running) per user, so one user cannot monopolise the model.
* Jobs that waited longer than `wait_timeout` are dropped instead of run.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)


class QueueFull(Exception):
    pass


class UserBusy(Exception):
    pass


class QueueTimeout(Exception):
    pass


class QueueClosed(Exception):
    pass


@dataclass
class _Job:
    user_id: int
    fn: Callable[[], Awaitable[Any]]
    future: "asyncio.Future[Any]"
    enqueued: float = field(default_factory=time.monotonic)


class InferenceQueue:
    def __init__(self, concurrency: int = 2, max_size: int = 30, per_user: int = 1, wait_timeout: float = 150.0):
        self.concurrency = concurrency
        self.max_size = max_size
        self.per_user = per_user
        self.wait_timeout = wait_timeout
        self._q: "asyncio.Queue[_Job]" = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._per_user: dict[int, int] = defaultdict(int)
        self._closed = False
        self.active = 0
        self.processed = 0
        self.rejected = 0
        self.failed = 0
        self.timed_out = 0
        self._wait_total = 0.0

    def start(self) -> None:
        for i in range(self.concurrency):
            self._workers.append(asyncio.create_task(self._worker(), name=f"inference-worker-{i}"))

    @property
    def size(self) -> int:
        return self._q.qsize()

    def stats(self) -> dict:
        return {
            "queued": self.size,
            "active": self.active,
            "concurrency": self.concurrency,
            "max_size": self.max_size,
            "processed": self.processed,
            "rejected": self.rejected,
            "failed": self.failed,
            "timed_out": self.timed_out,
            "avg_wait_ms": int(1000 * self._wait_total / self.processed) if self.processed else 0,
        }

    def user_pending(self, user_id: int) -> int:
        return self._per_user.get(user_id, 0)

    async def submit(self, user_id: int, fn: Callable[[], Awaitable[Any]]) -> Any:
        """Queue `fn` and wait for its result. Raises QueueFull / UserBusy / QueueTimeout / QueueClosed."""
        if self._closed:
            raise QueueClosed()
        if self._per_user[user_id] >= self.per_user:
            self.rejected += 1
            raise UserBusy()
        if self.size >= self.max_size:
            self.rejected += 1
            raise QueueFull()
        loop = asyncio.get_running_loop()
        job = _Job(user_id=user_id, fn=fn, future=loop.create_future())
        self._per_user[user_id] += 1
        self._q.put_nowait(job)
        try:
            return await job.future
        finally:
            self._per_user[user_id] -= 1
            if self._per_user[user_id] <= 0:
                self._per_user.pop(user_id, None)

    async def _worker(self) -> None:
        while True:
            job = await self._q.get()
            try:
                if job.future.done():  # caller went away (cancelled)
                    continue
                waited = time.monotonic() - job.enqueued
                if waited > self.wait_timeout:
                    self.timed_out += 1
                    job.future.set_exception(QueueTimeout())
                    continue
                self.active += 1
                try:
                    result = await job.fn()
                    self._wait_total += waited
                    self.processed += 1
                    if not job.future.done():
                        job.future.set_result(result)
                except asyncio.CancelledError:
                    if not job.future.done():
                        job.future.cancel()
                    raise
                except Exception as e:  # noqa: BLE001 - propagate to the submitter
                    self.failed += 1
                    if not job.future.done():
                        job.future.set_exception(e)
                finally:
                    self.active -= 1
            finally:
                self._q.task_done()

    async def shutdown(self, drain_timeout: float = 20.0) -> None:
        """Stop accepting work, let running jobs finish (bounded), then cancel workers."""
        self._closed = True
        try:
            await asyncio.wait_for(self._q.join(), timeout=drain_timeout)
        except asyncio.TimeoutError:
            log.warning("Queue did not drain in %.0fs; cancelling remaining jobs", drain_timeout)
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        while not self._q.empty():
            job = self._q.get_nowait()
            if not job.future.done():
                job.future.set_exception(QueueClosed())
