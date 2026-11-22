"""Logging setup with secret redaction."""
from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable

_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")
_URI_CRED_RE = re.compile(r"(mongodb(?:\+srv)?://[^:/\s]+:)([^@\s]+)(@)")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]{8,}")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")


class RedactingFilter(logging.Filter):
    """Masks configured secrets and common secret patterns in log records."""

    def __init__(self, secrets: Iterable[str] = ()):
        super().__init__()
        self._secrets = sorted({s for s in secrets if s and len(s) >= 6}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, "***")
        text = _URI_CRED_RE.sub(r"\1***\3", text)
        text = _TOKEN_RE.sub("***", text)
        text = _BEARER_RE.sub(r"\1***", text)
        text = _SK_RE.sub("***", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        record.msg = self.redact(msg)
        record.args = None
        if record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        return True


def setup_logging(level: str = "INFO", log_dir: str = "logs", secrets: Iterable[str] = ()) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    redactor = RedactingFilter(secrets)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.addFilter(redactor)
    root.addHandler(sh)

    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            Path(log_dir) / "ria.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        fh.addFilter(redactor)
        root.addHandler(fh)
    except OSError:
        root.warning("Could not create log directory %s; logging to stdout only", log_dir)

    # httpx/telegram libs log full URLs containing the bot token at INFO.
    for noisy in ("httpx", "httpcore", "telegram", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
