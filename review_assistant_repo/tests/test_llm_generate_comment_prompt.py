from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_settings(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM", "true")
    monkeypatch.setenv("ENABLE_LLM_COMMENT_GENERATION", "true")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_generate_comment_prompt_includes_roles_and_source_kind(monkeypatch):
    from app.config import get_settings
    from app.llm.client import LLMClient

    get_settings.cache_clear()
    captured: list[dict] = []

    def fake_chat(self, messages, temperature=0.2):
        captured.extend(messages)
        from app.llm.types import LLMCallResult

        return LLMCallResult(ok=True, text="USE_TEMPLATE", provider="openai", model="x")

    monkeypatch.setattr(LLMClient, "_chat", fake_chat)

    client = LLMClient()
    ctx = {
        "title": "T",
        "description": "D",
        "template": "Шаблон",
        "evidence": [],
        "style_profile": {
            "code": "practicum_review_requirements_v1",
            "alert_policy": {"colors": {"danger": {"emoji": "❌"}}},
            "guardrails": ["Не писать расплывчатые замечания без конкретного действия."],
        },
        "retrieval_examples": [
            {
                "text": "Пример текста",
                "author_role": "middle_reviewer",
                "source_kind": "project_training",
                "source_project": "proj_x",
                "source_notebook": "a.ipynb",
                "section_name": "eda",
                "student_context": "код выше",
            }
        ],
    }
    out = client.generate_comment(ctx)
    assert out == "Шаблон"
    assert captured
    body = captured[0]["content"]
    assert "middle_reviewer" in body
    assert "project_training" in body
    assert "eda" in body
    assert "proj_x" in body
    assert "Пример текста" in body
    assert "practicum_review_requirements_v1" in body
    assert "Не писать расплывчатые замечания" in body


def test_practicum_review_requirements_profile_loads():
    from app.utils.config_loader import list_style_profiles, load_style_profile

    assert "practicum_review_requirements_v1" in list_style_profiles()
    profile = load_style_profile("practicum_review_requirements_v1")
    assert profile["alert_policy"]["colors"]["danger"]["meaning"].startswith("Грубая ошибка")
    assert profile["final_comment"]["required"] is True
