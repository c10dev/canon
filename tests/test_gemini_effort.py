"""Gemini 추론 강도: 단계 설정(stage_efforts)을 thinking_level 로 넘기고, 받지 않는 값은 가까운 값으로 바꾼다."""
from types import SimpleNamespace

import pytest

from canon import settings, usage
from canon.llm import GeminiLLM, get_llm, make_llm


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("CANON_USAGE", str(tmp_path / "usage.jsonl"))
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-key-0000")
    monkeypatch.setenv("CANON_LLM", "gemini")
    for k in ("CANON_GEMINI_AUTH", "GOOGLE_GENAI_USE_VERTEXAI", "CANON_EFFORT_WRITE", "CANON_EFFORT_PLAN", "CANON_LLM_CHECK"):
        monkeypatch.delenv(k, raising=False)


def test_provider_effort_maps_to_what_each_backend_takes():
    assert settings.provider_effort("gemini", "medium") == "medium"
    assert settings.provider_effort("gemini", "xhigh") == "high" and settings.provider_effort("gemini", "max") == "high"
    assert settings.provider_effort("gemini", "") == "" and settings.provider_effort("gemini", "huge") == ""
    assert settings.provider_effort("claude", "max") == "max" and settings.provider_effort("claude-api", "low") == "low"
    assert settings.provider_effort("local", "high") == "" and settings.provider_effort("mock", "high") == ""


def test_stage_effort_reaches_gemini_and_the_settings_view():
    assert get_llm("write").effort == ""  # 정하지 않으면 모델 기본값
    settings.update(stage_efforts={"write": "high", "plan": "max"})
    assert get_llm("write").effort == "high"
    assert get_llm("revise").effort == "high"  # 부분 수정은 같은 백엔드인 본문 쓰기를 따른다
    assert get_llm("plan").effort == "high"  # Claude 에서 고른 최대는 Gemini 에서 높음
    pub = settings.public()
    assert pub["stages"]["plan"]["effort"] == "high" and pub["stage_effort_settings"]["plan"] == "max"
    assert pub["gemini_efforts"] == ["low", "medium", "high"]
    assert make_llm("gemini", effort="huge").effort == ""


def test_effort_does_not_follow_a_parent_on_another_backend(monkeypatch):
    monkeypatch.setenv("CANON_LLM_CHECK", "claude")
    settings.update(stage_efforts={"check": "xhigh"})
    assert settings.stage_view(None)["check"]["effort"] == "xhigh"
    assert get_llm("plan").effort == ""  # 검수 강도가 계획 단계에 번지지 않는다


def _fake(effort: str) -> tuple[GeminiLLM, list]:
    llm = object.__new__(GeminiLLM)
    seen = []

    def generate(model, contents, config):
        seen.append(config)
        u = SimpleNamespace(prompt_token_count=10, candidates_token_count=3, thoughts_token_count=40 if effort else 0,
                            cached_content_token_count=0)
        return SimpleNamespace(text="답", usage_metadata=u, candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))])
    llm.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    llm.model, llm.effort = "gemini-4-argon", effort
    return llm, seen


def test_thinking_level_is_sent_and_recorded():
    llm, seen = _fake("high")
    assert llm.text("", "요청") == "답"
    assert seen[-1].thinking_config.thinking_level.value == "HIGH"
    row = usage.read()[-1]
    assert row["effort"] == "high" and row["thought"] == 40
    llm, seen = _fake("")
    llm.text("", "요청")
    assert seen[-1].thinking_config is None  # 정하지 않으면 보내지 않는다 (모델 기본값)
    assert "effort" not in usage.read()[-1]


def test_batch_request_carries_the_thinking_level():
    llm = object.__new__(GeminiLLM)
    sent = []
    llm.client = SimpleNamespace(batches=SimpleNamespace(create=lambda **k: sent.append(k) or SimpleNamespace(name="b1")))
    llm.model, llm.effort = "gemini-4-argon", "medium"
    assert llm.batch_submit("시스템", "요청", None, "라벨") == "b1"
    assert sent[-1]["src"][0]["config"]["thinking_config"] == {"thinking_level": "MEDIUM"}
    llm.effort = ""
    llm.batch_submit("시스템", "요청", None, "라벨")
    assert "thinking_config" not in sent[-1]["src"][0]["config"]
