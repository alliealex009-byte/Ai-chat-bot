"""Configuration loaded from environment / .env and validated with Pydantic."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    return val.strip()


def _bool(name: str, default: bool = False) -> bool:
    val = _env(name)
    if val is None:
        return default
    return val.lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    # Telegram
    telegram_bot_token: str = Field(min_length=10)
    admin_user_ids: list[int] = Field(default_factory=list)

    # Ollama
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "gemma3:4b"
    ai_temperature: float = Field(0.8, ge=0.0, le=2.0)
    ai_top_p: float = Field(0.92, gt=0.0, le=1.0)
    ai_repeat_penalty: float = Field(1.15, ge=1.0, le=2.0)
    vision_enabled: bool = True  # Ria can react to photos (local Gemma 3 vision; photos are never stored)
    human_reactions: bool = True  # sometimes react to your message with an emoji
    human_bubbles: bool = True  # sometimes send two short messages instead of one
    ai_max_tokens: int = Field(60, ge=16, le=2048)
    ai_max_tokens_long: int = Field(500, ge=16, le=4096)
    ai_context_length: int = Field(4096, ge=512, le=32768)
    ai_num_threads: int = Field(8, ge=1, le=64)
    ollama_keep_alive: str = "30m"
    ollama_timeout_seconds: float = Field(120.0, gt=1)
    ollama_connect_timeout_seconds: float = Field(5.0, gt=0)
    ollama_retries: int = Field(1, ge=0, le=5)

    # Mode / fallback
    ai_mode: str = "local"
    enable_api_fallback: bool = False
    openrouter_api_key: Optional[str] = None
    openrouter_model: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = Field(45.0, gt=1)
    openrouter_retries: int = Field(1, ge=0, le=5)
    openrouter_daily_request_limit: int = Field(200, ge=0)
    openrouter_daily_token_limit: int = Field(100_000, ge=0)

    # MongoDB
    mongo_uri: Optional[str] = None
    mongo_host: str = "127.0.0.1"
    mongo_port: int = 27018
    mongo_user: str = "ria_admin"
    mongo_password: Optional[str] = None
    mongo_auth_source: str = "admin"
    mongo_db_name: str = "ria_database"
    mongo_max_pool_size: int = Field(20, ge=1)
    mongo_timeout_ms: int = Field(5000, ge=500)

    # Conversation / memory
    history_messages: int = Field(8, ge=2, le=60)
    history_char_budget: int = Field(2400, ge=500)
    max_input_chars: int = Field(2000, ge=50)
    conversation_retention_days: int = Field(0, ge=0)  # 0 = keep chats forever (memory + training data)
    max_stored_messages_per_user: int = Field(50000, ge=10)
    memory_enabled: bool = True
    memory_extract_every_n_messages: int = Field(4, ge=2)
    summary_every_n_messages: int = Field(10, ge=4)
    max_memories_per_user: int = Field(50, ge=5)
    memories_in_prompt: int = Field(8, ge=0, le=30)
    cleanup_interval_minutes: int = Field(60, ge=5)

    # Concurrency / limits
    max_concurrent_inference: int = Field(2, ge=1, le=16)
    max_queue_size: int = Field(30, ge=1)
    max_queued_per_user: int = Field(1, ge=1)
    queue_wait_timeout_seconds: float = Field(150.0, gt=1)
    user_rate_limit_messages: int = Field(8, ge=1)
    user_rate_limit_window_seconds: int = Field(60, ge=1)
    global_rate_limit_messages: int = Field(120, ge=1)
    global_rate_limit_window_seconds: int = Field(60, ge=1)
    dedupe_cache_size: int = Field(5000, ge=100)

    # HTTP API (served to the Hugging Face Space through nginx + HTTPS)
    api_enabled: bool = True
    api_host: str = "127.0.0.1"
    api_port: int = Field(8000, ge=1, le=65535)
    api_token: Optional[str] = None  # service token the HF Space sends as Bearer
    api_rate_limit_per_minute: int = Field(30, ge=1)
    api_global_rate_limit_per_minute: int = Field(300, ge=1)
    api_link_code_ttl_seconds: int = Field(600, ge=60)
    api_session_ttl_days: int = Field(30, ge=1)
    api_cors_origins: list[str] = Field(default_factory=list)

    # Optional Hugging Face inference replica (Ollama gemma3:4b on the Space). Off by default.
    hf_replica_enabled: bool = False
    hf_replica_url: Optional[str] = None
    hf_replica_token: Optional[str] = None
    hf_replica_timeout_seconds: float = Field(60.0, gt=1)
    hf_replica_health_interval_seconds: int = Field(60, ge=10)

    # Ops
    log_level: str = "INFO"
    log_dir: str = "logs"
    log_message_content: bool = False
    default_language: str = "hinglish"

    # Owner panel: access is by NUMERIC Telegram id and ONLY for OWNER_USER_IDS (admins do NOT get it)
    owner_user_ids: list[int] = Field(default_factory=list)
    owner_name: str = "AAKASH"
    owner_username: str = "Advik_prakashh"
    group_rate_limit_messages: int = Field(12, ge=1)
    secretary_pause_minutes: int = Field(10, ge=0)  # stay quiet this long after the account owner writes in a chat
    secretary_notify_owner: bool = True  # DM the account owner each message Ria handled for them
    promoter_url: str = ""   # "Promoter" button on /start; empty -> owner's @username link
    updates_url: str = ""    # "Updates" button on /start; empty -> button hidden

    @field_validator("ai_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        v = v.lower()
        if v not in {"local", "hybrid"}:
            raise ValueError("AI_MODE must be 'local' or 'hybrid'")
        return v

    @field_validator("ollama_base_url")
    @classmethod
    def _ollama_url(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def _level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("invalid LOG_LEVEL")
        return v

    @field_validator("default_language")
    @classmethod
    def _lang(cls, v: str) -> str:
        v = v.lower()
        if v not in {"hinglish", "hindi", "english"}:
            raise ValueError("DEFAULT_LANGUAGE must be hinglish, hindi or english")
        return v

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.api_fallback_active and not (self.openrouter_api_key and self.openrouter_model):
            raise ValueError(
                "API fallback enabled but OPENROUTER_API_KEY / OPENROUTER_MODEL are not set"
            )
        if not self.mongo_uri and not self.mongo_password:
            raise ValueError("Set MONGO_URI or MONGO_PASSWORD in .env")
        if self.api_enabled and (not self.api_token or len(self.api_token) < 32):
            raise ValueError(
                "API_TOKEN must be at least 32 characters when API_ENABLED=true "
                "(generate: openssl rand -hex 32)"
            )
        if self.hf_replica_enabled and not (self.hf_replica_url and self.hf_replica_token):
            raise ValueError("HF replica enabled but HF_REPLICA_URL / HF_REPLICA_TOKEN missing")
        if self.hf_replica_url and not self.hf_replica_url.startswith("https://"):
            raise ValueError("HF_REPLICA_URL must use https://")
        return self

    @property
    def owner_ids(self) -> set[int]:
        return set(self.owner_user_ids)

    @property
    def api_fallback_active(self) -> bool:
        return self.enable_api_fallback or self.ai_mode == "hybrid"

    @property
    def effective_mongo_uri(self) -> str:
        if self.mongo_uri:
            return self.mongo_uri
        return (
            f"mongodb://{quote_plus(self.mongo_user)}:{quote_plus(self.mongo_password or '')}"
            f"@{self.mongo_host}:{self.mongo_port}/?authSource={self.mongo_auth_source}"
        )

    def secrets(self) -> list[str]:
        out = [
            self.telegram_bot_token,
            self.openrouter_api_key,
            self.mongo_password,
            self.api_token,
            self.hf_replica_token,
        ]
        if self.mongo_uri:
            out.append(self.mongo_uri)
        return [s for s in out if s]


def load_settings(env_file: Optional[str] = None) -> Settings:
    load_dotenv(env_file or BASE_DIR / ".env", override=False)
    admins = [
        int(x) for x in (_env("ADMIN_USER_IDS", "") or "").replace(" ", "").split(",") if x.isdigit()
    ]
    raw = dict(
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN", ""),
        admin_user_ids=admins,
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=_env("OLLAMA_MODEL", "gemma3:4b"),
        ai_temperature=_env("AI_TEMPERATURE", "0.8"),
        ai_top_p=_env("AI_TOP_P", "0.92"),
        ai_repeat_penalty=_env("AI_REPEAT_PENALTY", "1.15"),
        human_bubbles=_bool("HUMAN_BUBBLES", True),
        human_reactions=_bool("HUMAN_REACTIONS", True),
        vision_enabled=_bool("VISION_ENABLED", True),
        ai_max_tokens=_env("AI_MAX_TOKENS", "60"),
        ai_max_tokens_long=_env("AI_MAX_TOKENS_LONG", "500"),
        ai_context_length=_env("AI_CONTEXT_LENGTH", "4096"),
        ai_num_threads=_env("AI_NUM_THREADS", "8"),
        ollama_keep_alive=_env("OLLAMA_KEEP_ALIVE", "30m"),
        ollama_timeout_seconds=_env("OLLAMA_TIMEOUT_SECONDS", "120"),
        ollama_retries=_env("OLLAMA_RETRIES", "1"),
        ai_mode=_env("AI_MODE", "local"),
        enable_api_fallback=_bool("ENABLE_API_FALLBACK", False),
        openrouter_api_key=_env("OPENROUTER_API_KEY"),
        openrouter_model=_env("OPENROUTER_MODEL"),
        openrouter_daily_request_limit=_env("OPENROUTER_DAILY_REQUEST_LIMIT", "200"),
        openrouter_daily_token_limit=_env("OPENROUTER_DAILY_TOKEN_LIMIT", "100000"),
        mongo_uri=_env("MONGO_URI") or _env("MONGO_URL"),  # MONGO_URL accepted as alias
        mongo_host=_env("MONGO_HOST", "127.0.0.1"),
        mongo_port=_env("MONGO_PORT", "27018"),
        mongo_user=_env("MONGO_USER", "ria_admin"),
        mongo_password=_env("MONGO_PASSWORD"),
        mongo_auth_source=_env("MONGO_AUTH_SOURCE", "admin"),
        mongo_db_name=_env("MONGO_DB_NAME", "ria_database"),
        mongo_max_pool_size=_env("MONGO_MAX_POOL_SIZE", "20"),
        history_messages=_env("HISTORY_MESSAGES", "8"),
        history_char_budget=_env("HISTORY_CHAR_BUDGET", "2400"),
        max_input_chars=_env("MAX_INPUT_CHARS", "2000"),
        conversation_retention_days=_env("CONVERSATION_RETENTION_DAYS", "0"),
        max_stored_messages_per_user=_env("MAX_STORED_MESSAGES_PER_USER", "50000"),
        memory_enabled=_bool("MEMORY_ENABLED", True),
        memory_extract_every_n_messages=_env("MEMORY_EXTRACT_EVERY_N_MESSAGES", "4"),
        summary_every_n_messages=_env("SUMMARY_EVERY_N_MESSAGES", "10"),
        max_memories_per_user=_env("MAX_MEMORIES_PER_USER", "50"),
        memories_in_prompt=_env("MEMORIES_IN_PROMPT", "8"),
        cleanup_interval_minutes=_env("CLEANUP_INTERVAL_MINUTES", "60"),
        max_concurrent_inference=_env("MAX_CONCURRENT_INFERENCE", "2"),
        max_queue_size=_env("MAX_QUEUE_SIZE", "30"),
        max_queued_per_user=_env("MAX_QUEUED_PER_USER", "1"),
        queue_wait_timeout_seconds=_env("QUEUE_WAIT_TIMEOUT_SECONDS", "150"),
        user_rate_limit_messages=_env("USER_RATE_LIMIT_MESSAGES", "8"),
        user_rate_limit_window_seconds=_env("USER_RATE_LIMIT_WINDOW_SECONDS", "60"),
        global_rate_limit_messages=_env("GLOBAL_RATE_LIMIT_MESSAGES", "120"),
        global_rate_limit_window_seconds=_env("GLOBAL_RATE_LIMIT_WINDOW_SECONDS", "60"),
        log_level=_env("LOG_LEVEL", "INFO"),
        log_dir=_env("LOG_DIR", "logs"),
        log_message_content=_bool("LOG_MESSAGE_CONTENT", False),
        api_enabled=_bool("API_ENABLED", True),
        api_host=_env("API_HOST", "127.0.0.1"),
        api_port=_env("API_PORT", "8000"),
        api_token=_env("API_TOKEN"),
        api_rate_limit_per_minute=_env("API_RATE_LIMIT_PER_MINUTE", "30"),
        api_global_rate_limit_per_minute=_env("API_GLOBAL_RATE_LIMIT_PER_MINUTE", "300"),
        api_link_code_ttl_seconds=_env("API_LINK_CODE_TTL_SECONDS", "600"),
        api_session_ttl_days=_env("API_SESSION_TTL_DAYS", "30"),
        api_cors_origins=[
            o.strip() for o in (_env("API_CORS_ORIGINS", "") or "").split(",") if o.strip()
        ],
        hf_replica_enabled=_bool("HF_REPLICA_ENABLED", False),
        hf_replica_url=_env("HF_REPLICA_URL"),
        hf_replica_token=_env("HF_REPLICA_TOKEN"),
        hf_replica_timeout_seconds=_env("HF_REPLICA_TIMEOUT_SECONDS", "60"),
        hf_replica_health_interval_seconds=_env("HF_REPLICA_HEALTH_INTERVAL_SECONDS", "60"),
        default_language=_env("DEFAULT_LANGUAGE", "hinglish"),
        owner_user_ids=[int(x) for x in (_env("OWNER_USER_IDS", "") or "").replace(" ", "").split(",") if x.isdigit()],
        owner_name=_env("OWNER_NAME", "AAKASH"),
        owner_username=_env("OWNER_USERNAME", "Advik_prakashh"),
        group_rate_limit_messages=_env("GROUP_RATE_LIMIT_MESSAGES", "12"),
        secretary_pause_minutes=_env("SECRETARY_PAUSE_MINUTES", "10"),
        secretary_notify_owner=_env("SECRETARY_NOTIFY_OWNER", "true"),
        promoter_url=_env("PROMOTER_URL", ""),
        updates_url=_env("UPDATES_URL", ""),
    )
    return Settings(**raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
