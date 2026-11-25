import pytest
from pydantic import ValidationError

from app.config import load_settings
from tests.fakes import make_settings

ENV = {"TELEGRAM_BOT_TOKEN": "123456:ABCDEF_test_token_value_1234567890", "MONGO_PASSWORD": "p@ss/word",
       "API_TOKEN": "b" * 40}


def _load(monkeypatch, tmp_path, **extra):
    for k, v in {**ENV, **extra}.items():
        monkeypatch.setenv(k, v)
    return load_settings(str(tmp_path / "none.env"))


def test_defaults_use_gemma_and_local_only(monkeypatch, tmp_path):
    s = _load(monkeypatch, tmp_path)
    assert s.ollama_model == "gemma3:4b"
    assert s.ollama_base_url == "http://127.0.0.1:11434"
    assert s.ai_mode == "local" and not s.enable_api_fallback and not s.api_fallback_active
    assert not s.hf_replica_enabled
    assert (s.ai_temperature, s.ai_top_p, s.ai_max_tokens, s.ai_context_length) == (0.8, 0.92, 60, 4096)
    assert s.mongo_db_name == "ria_database" and s.mongo_port == 27018


def test_mongo_uri_escapes_password(monkeypatch, tmp_path):
    s = _load(monkeypatch, tmp_path)
    assert "p%40ss%2Fword" in s.effective_mongo_uri
    assert s.effective_mongo_uri.startswith("mongodb://ria_admin:") and "127.0.0.1:27018" in s.effective_mongo_uri


def test_missing_token_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("MONGO_PASSWORD", "x")
    with pytest.raises(ValidationError):
        load_settings(str(tmp_path / "none.env"))


def test_short_api_token_rejected(monkeypatch, tmp_path):
    with pytest.raises(ValidationError):
        _load(monkeypatch, tmp_path, API_TOKEN="short")


def test_fallback_requires_key_and_model(monkeypatch, tmp_path):
    with pytest.raises(ValidationError):
        _load(monkeypatch, tmp_path, ENABLE_API_FALLBACK="true")
    s = _load(monkeypatch, tmp_path, ENABLE_API_FALLBACK="true", OPENROUTER_API_KEY="sk-or-xxxxxxxxxxxxxxxxxxxx",
              OPENROUTER_MODEL="some/model")
    assert s.api_fallback_active


def test_replica_requires_https_and_token(monkeypatch, tmp_path):
    with pytest.raises(ValidationError):
        _load(monkeypatch, tmp_path, HF_REPLICA_ENABLED="true")
    with pytest.raises(ValidationError):
        _load(monkeypatch, tmp_path, HF_REPLICA_ENABLED="true", HF_REPLICA_URL="http://x.hf.space", HF_REPLICA_TOKEN="t")


def test_invalid_values_rejected(monkeypatch, tmp_path):
    with pytest.raises(ValidationError):
        _load(monkeypatch, tmp_path, AI_MODE="cloud")
    with pytest.raises(ValidationError):
        _load(monkeypatch, tmp_path, AI_TEMPERATURE="5")


def test_secrets_listed_for_redaction():
    s = make_settings()
    assert s.telegram_bot_token in s.secrets() and s.api_token in s.secrets()


def test_mongo_url_alias_is_accepted(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABCDEF_test_token_value_1234567890")
    monkeypatch.setenv("API_TOKEN", "c" * 40)
    monkeypatch.setenv("MONGO_URL", "mongodb://u:p@127.0.0.1:27018/?authSource=admin")
    s = load_settings(str(tmp_path / "none.env"))
    assert s.effective_mongo_uri == "mongodb://u:p@127.0.0.1:27018/?authSource=admin"
