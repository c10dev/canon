"""CoralBricks 백엔드 (canon/coral.py). 실제 서버를 부르지 않고 요청 본문과 설정 · 사용량 연결만 본다."""
import pytest

from canon import coral, settings, usage
from canon.llm import BadKey, LocalLLM, MissingKey, make_llm
from pydantic import BaseModel


class Pick(BaseModel):
    pick: str


def _fake(monkeypatch, sent, reply='{"pick": "사과"}'):
    def request(self, method, path, body=None, timeout=None):
        sent.append((method, path, body, self.base_url, self.api_key))
        if path == "/models":
            return {"data": [{"id": "coralbricks/deepseek-v4.1-flash"}, {"id": "coralbricks/deepseek-v4.1-flash-value"}]}
        return {"choices": [{"finish_reason": "stop", "message": {"content": reply}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 40}}}
    monkeypatch.setattr(LocalLLM, "_request", request)


def test_no_key_is_missing_key(monkeypatch):
    monkeypatch.delenv("CORAL_API_KEY", raising=False)
    with pytest.raises(MissingKey, match="CoralBricks API 키가 없어요"):
        make_llm("coralbricks")


def test_request_goes_to_coral_with_key_model_effort(monkeypatch):
    monkeypatch.setenv("CORAL_API_KEY", "cb_test_key")
    monkeypatch.setenv("CANON_CORAL_MODEL", "coralbricks/deepseek-v4.1-flash-value")
    sent = []
    _fake(monkeypatch, sent)
    llm = make_llm("coralbricks", effort="high")
    assert isinstance(llm, coral.CoralLLM) and usage.backend_of(llm) == "coralbricks"
    assert llm.json("시스템", "고르세요", Pick).pick == "사과"
    _, path, body, url, key = sent[-1]
    assert (path, url, key) == ("/chat/completions", coral.BASE_URL, "cb_test_key")
    assert body["model"] == "deepseek-v4.1-flash-value"  # 앞머리를 뗀 이름 (가격표 이름)
    assert body["reasoning_effort"] == "high" and body["response_format"]["type"] == "json_schema"
    assert "min_p" not in body
    assert llm.last_usage["cached_tokens"] == 40
    assert llm.models() == ["deepseek-v4.1-flash", "deepseek-v4.1-flash-value"]


def test_effort_is_not_sent_when_empty(monkeypatch):
    monkeypatch.setenv("CORAL_API_KEY", "cb_test_key")
    sent = []
    _fake(monkeypatch, sent, reply="본문")
    llm = make_llm("coralbricks", "deepseek-v4.1-flash")
    assert llm.text("시스템", "쓰세요") == "본문"
    assert "reasoning_effort" not in sent[-1][2] and sent[-1][2]["model"] == coral.DEFAULT_MODEL


def test_busy_429_waits_and_retries(monkeypatch):
    monkeypatch.setenv("CORAL_API_KEY", "cb_test_key")
    calls, slept = [], []
    monkeypatch.setattr(coral.time, "sleep", slept.append)

    def request(self, method, path, body=None, timeout=None):
        calls.append(path)
        if len(calls) < 3:
            raise RuntimeError('로컬 서버 오류 429 (u): {"error":{"code":"concurrency_limit"}}')
        return {"choices": [{"finish_reason": "stop", "message": {"content": "본문"}}], "usage": None}
    monkeypatch.setattr(LocalLLM, "_request", request)
    assert make_llm("coralbricks").text("시스템", "쓰세요") == "본문"
    assert len(calls) == 3 and slept == list(coral.BUSY_WAITS[:2])
    # 잔액 없음은 기다리지 않는다
    calls.clear()
    slept.clear()

    def broke(self, method, path, body=None, timeout=None):
        calls.append(path)
        raise RuntimeError('로컬 서버 오류 429 (u): {"error":{"code":"insufficient_credits"}}')
    monkeypatch.setattr(LocalLLM, "_request", broke)
    with pytest.raises(RuntimeError, match="잔액"):
        make_llm("coralbricks").text("시스템", "쓰세요")
    assert len(calls) == 1 and not slept


def test_errors_become_coral_hints():
    assert isinstance(coral.explain(RuntimeError("로컬 서버 오류 401 (u): invalid_api_key")), BadKey)
    card = coral.explain(RuntimeError('로컬 서버 오류 403 (u): {"error":{"reason":"card_required"}}'))
    assert not isinstance(card, BadKey) and "카드" in str(card)
    assert "잔액" in str(coral.explain(RuntimeError("로컬 서버 오류 429 (u): insufficient_credits")))
    other = str(coral.explain(RuntimeError("로컬 서버에 연결하지 못했어요 (u): x")))
    assert "CoralBricks" in other and "로컬 서버" not in other


def test_settings_and_prices(monkeypatch):
    monkeypatch.delenv("CORAL_API_KEY", raising=False)
    monkeypatch.delenv("CANON_CORAL_MODEL", raising=False)
    assert "coralbricks" in settings.PROVIDERS and settings.provider_effort("coralbricks", "max") == "max"
    settings.update(coral_api_key="cb_abcdefgh1234", coral_model="deepseek-v4.1-flash-value")
    pub = settings.public()
    assert pub["coral_key_hint"] == "…1234" and pub["coral_key_source"] == "file" and "cb_abcdefgh1234" not in str(pub)
    assert pub["coral_model"] == "deepseek-v4.1-flash-value"
    monkeypatch.setenv("CANON_LLM", "gemini")
    monkeypatch.setenv("CANON_LLM_NAME", "coralbricks")
    monkeypatch.delenv("CANON_MODEL_NAME", raising=False)
    assert usage.stage_llm("name") == ("coralbricks", "deepseek-v4.1-flash-value")
    assert settings.stage_view(None)["name"]["model"] == "deepseek-v4.1-flash-value"
    settings.update(clear_coral_key=True, coral_model="")
    assert settings.public()["coral_key_source"] == "none" and usage.stage_llm("name")[1] == coral.DEFAULT_MODEL
    # 가격: Value 는 이름이 더 긴 줄을 찾고, 캐시 쓰기 요금과 배치 할인이 없다
    p = usage.rate("deepseek-v4.1-flash-value", table=usage.DEFAULT_PRICES)
    assert (p.input, p.output, p.cached) == (0.005, 0.57, 0.003)
    assert usage.cost(p, 1_000_000, 0, batch=True) == pytest.approx(0.005)
    row = {"backend": "coralbricks", "model": "deepseek-v4.1-flash", "at": "2026-11-10T00:00:00", "in": 1_000_000, "out": 1_000_000, "cached": 500_000}
    assert usage.row_cost(row, usage.DEFAULT_PRICES)[0] == pytest.approx(0.095 + 0.004 + 0.6)
