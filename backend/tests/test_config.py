import pytest

from app.config import load_settings


def test_load_settings_from_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://gw.local/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")
    s = load_settings()
    assert s.llm_base_url == "http://gw.local/v1"


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "x")
    monkeypatch.setenv("LLM_MODEL", "m")
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        load_settings()
