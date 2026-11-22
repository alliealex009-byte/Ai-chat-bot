import asyncio

import pytest

from app.services.limiter import DedupeCache, SlidingWindowLimiter
from app.services.queue import InferenceQueue, QueueClosed, QueueFull, QueueTimeout, UserBusy
from app.tg.utils import split_message


def test_user_rate_limit_and_window():
    t = [0.0]
    lim = SlidingWindowLimiter(3, 10, clock=lambda: t[0])
    assert all(lim.allow("u1") for _ in range(3))
    assert not lim.allow("u1")
    assert lim.allow("u2")  # other users unaffected
    assert 0 < lim.retry_after("u1") <= 10
    t[0] = 11
    assert lim.allow("u1")


def test_limiter_gc_drops_idle_keys():
    t = [0.0]
    lim = SlidingWindowLimiter(1, 5, clock=lambda: t[0])
    lim.allow("a")
    t[0] = 100
    lim.gc()
    assert not lim._events


def test_global_limit():
    lim = SlidingWindowLimiter(2, 60)
    assert lim.allow() and lim.allow() and not lim.allow()


def test_dedupe_bounded_lru():
    d = DedupeCache(3)
    assert not d.seen(1) and d.seen(1)
    for i in (2, 3, 4):
        d.seen(i)
    assert not d.seen(1)  # evicted


def test_split_message_respects_limit_and_content():
    text = ("Hello world. " * 600).strip()
    parts = split_message(text, 1000)
    assert all(len(p) <= 1000 for p in parts) and len(parts) > 1
    assert " ".join(parts).replace("  ", " ").count("Hello world.") == 600
    assert split_message("short") == ["short"] and split_message("   ") == []
    assert all(len(p) <= 100 for p in split_message("x" * 450, 100))  # no spaces: hard cut


async def test_queue_bounds_concurrency():
    q = InferenceQueue(concurrency=2, max_size=20, per_user=1, wait_timeout=30)
    q.start()
    running = peak = 0

    async def job():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return "ok"

    res = await asyncio.gather(*(q.submit(i, job) for i in range(8)))
    assert res == ["ok"] * 8 and peak == 2
    await q.shutdown(1)


async def test_queue_full_rejects_immediately():
    q = InferenceQueue(concurrency=1, max_size=1, per_user=1, wait_timeout=30)
    q.start()
    gate = asyncio.Event()

    async def slow():
        await gate.wait()
        return 1

    t1 = asyncio.create_task(q.submit(1, slow))
    await asyncio.sleep(0.01)          # job 1 running
    t2 = asyncio.create_task(q.submit(2, slow))
    await asyncio.sleep(0.01)          # job 2 waiting (queue now full)
    with pytest.raises(QueueFull):
        await q.submit(3, slow)
    assert q.stats()["rejected"] == 1
    gate.set()
    await asyncio.gather(t1, t2)
    await q.shutdown(1)


async def test_one_user_cannot_monopolise():
    q = InferenceQueue(concurrency=2, max_size=10, per_user=1, wait_timeout=30)
    q.start()
    gate = asyncio.Event()

    async def slow():
        await gate.wait()

    t = asyncio.create_task(q.submit(7, slow))
    await asyncio.sleep(0.01)
    with pytest.raises(UserBusy):
        await q.submit(7, slow)
    # a different user still gets served while user 7 is busy
    other = asyncio.create_task(q.submit(8, slow))
    await asyncio.sleep(0.01)
    assert q.active == 2
    gate.set()
    await asyncio.gather(t, other)
    assert q.user_pending(7) == 0
    await q.shutdown(1)


async def test_queue_wait_timeout_and_error_propagation():
    q = InferenceQueue(concurrency=1, max_size=5, per_user=1, wait_timeout=0.05)
    q.start()

    async def slow():
        await asyncio.sleep(0.2)

    async def boom():
        raise ValueError("x")

    first = asyncio.create_task(q.submit(1, slow))
    await asyncio.sleep(0.01)
    with pytest.raises(QueueTimeout):
        await q.submit(2, slow)
    await first
    with pytest.raises(ValueError):
        await q.submit(3, boom)
    assert q.stats()["failed"] == 1 and q.stats()["timed_out"] == 1
    await q.shutdown(1)


async def test_shutdown_rejects_new_work():
    q = InferenceQueue(1, 5, 1, 30)
    q.start()
    await q.shutdown(1)

    async def j():
        return 1

    with pytest.raises(QueueClosed):
        await q.submit(1, j)
