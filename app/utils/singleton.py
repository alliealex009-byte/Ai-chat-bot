"""Ensure only one RIA polling process runs (advisory file lock; released automatically on exit)."""
from __future__ import annotations

import os
from pathlib import Path


class AlreadyRunning(RuntimeError):
    pass


class SingleInstance:
    def __init__(self, path: str = "data/ria.lock"):
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> None:
        import fcntl  # Linux only (target is Ubuntu)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "w")
        try:
            fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            raise AlreadyRunning(
                f"Another RIA instance holds {self.path}. Only ONE Telegram polling process may run."
            )
        self._fh.write(str(os.getpid()))
        self._fh.flush()

    def release(self) -> None:
        if self._fh:
            try:
                import fcntl

                fcntl.flock(self._fh, fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
