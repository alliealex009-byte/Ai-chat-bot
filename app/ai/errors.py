"""AI-layer exceptions and result type."""
from __future__ import annotations

from dataclasses import dataclass


class AIError(Exception):
    """Base error. Message is safe to log but NOT shown to users."""


class AIUnavailable(AIError):
    """Provider cannot be reached (connection refused, DNS, 5xx, model loading)."""


class AITimeout(AIError):
    """Provider took too long."""


class AIModelMissing(AIError):
    """Configured model is not installed. Never auto-switch models."""


class AIBudgetExceeded(AIError):
    """Configured spending limit for a paid provider was reached."""


@dataclass
class ChatResult:
    text: str
    provider: str  # "ollama" | "hf_replica" | "openrouter"
    model: str
    latency_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
