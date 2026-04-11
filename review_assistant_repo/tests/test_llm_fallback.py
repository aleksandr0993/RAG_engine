from app.llm.client import LLMClient
from app.llm.service import LLMService


def test_llm_classify_disabled_returns_unknown(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("ENABLE_LLM", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    client = LLMClient()
    assert not client.enabled
    res = client.classify_text("task", "hello", {})
    assert res.label == "unknown"
    assert res.confidence <= 0.3


def test_llm_service_semantic_off(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_SEMANTIC_CHECKS", "false")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    svc = LLMService()
    r = svc.classify_text("t", "x", {})
    assert r.label == "unknown"
    assert r.confidence == 0.0
