"""빈 응답 · 차단 · 공급자 오류의 화면 문구 (llm.explain_error, ERROR_TABLE)와 하루 한도 429 (llm.is_hard_quota, QuotaSpent).
실제 API 대신 google-genai 의 오류 객체와 가짜 Gemini 응답을 쓴다."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from canon import autorun, jobs, llm, usage
from canon.llm import EmptyResponse, GeminiLLM, QuotaSpent, RateLimited, explain_error, is_hard_quota, is_rate_limit


def api_error(code, message, status="", details=None):
    from google.genai import errors

    body = {"code": code, "message": message, "status": status}
    if details is not None:
        body["details"] = details
    return errors.APIError(code, {"error": body})


# 실제 Gemini API 의 하루 한도 429 모양 (google.rpc.QuotaFailure 와 RetryInfo). 메시지는 분당 한도와 같다
def per_day():
    return api_error(429, "You exceeded your current quota, please check your plan and billing details.", "RESOURCE_EXHAUSTED", [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
            {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
             "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "250"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}])


def per_minute():
    return api_error(429, "You exceeded your current quota, please check your plan and billing details.", "RESOURCE_EXHAUSTED", [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
            {"quotaMetric": "generativelanguage.googleapis.com/generate_content_paid_tier_input_token_count",
             "quotaId": "GenerateContentPaidTierInputTokensPerModelPerMinute", "quotaValue": "2000000"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12s"}])


# 사용량 기록에 남은 Vertex AI 429 (2026-11, 44번). 기다리면 풀린다
VERTEX_429 = "Resource exhausted. Please try again later. Please refer to https://cloud.google.com/vertex-ai/generative-ai/docs/error-code-429 for more details."


def test_hard_quota_is_narrow():
    assert is_hard_quota(per_day()) and is_rate_limit(per_day())
    assert not is_hard_quota(per_minute())
    assert not is_hard_quota(api_error(429, VERTEX_429, "RESOURCE_EXHAUSTED"))
    assert is_hard_quota(api_error(429, "Your prepayment credits are depleted. Please go to AI Studio to manage billing.",
                                   "RESOURCE_EXHAUSTED"))
    assert not is_hard_quota(RuntimeError("503 과부하"))
    assert llm.retry_delay(per_day()) == 37  # 같은 details 읽기(_details)를 쓴다


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)

    def generate_content(self, model, contents, config):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return reply(r) if isinstance(r, str) else r


def fake_gemini(replies):
    g = GeminiLLM.__new__(GeminiLLM)
    g.client = SimpleNamespace(models=FakeModels(replies))
    g.model, g.last_usage, g.last_attempts, g.last_raw = "gemini-4-argon", None, 0, ""
    return g


@pytest.fixture
def pauses(monkeypatch, tmp_path):
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    out = []
    monkeypatch.setattr(llm, "_pause", out.append)
    return out


def test_hard_quota_stops_without_waiting(pauses):
    g = fake_gemini([per_day(), "본문"])
    with pytest.raises(QuotaSpent) as e:
        g.text("s", "p")
    assert pauses == [] and g.client.models.replies == ["본문"]
    assert str(e.value).startswith(llm.QUOTA_HINT) and usage.BILLING_URL in str(e.value)
    assert explain_error(per_day()) == e.value.message  # 표의 첫 줄과 같은 글


def test_minute_quota_still_waits(pauses):
    g = fake_gemini([per_minute(), "본문"])
    assert g.text("s", "p") == "본문" and pauses == [12]
    g = fake_gemini([per_minute() for _ in range(len(llm.RATE_WAITS) + 1)])
    with pytest.raises(RateLimited):
        g.text("s", "p")


def reply(text="", finish=None, block=None, thought=0, message=None):
    meta = SimpleNamespace(prompt_token_count=1000, candidates_token_count=0, thoughts_token_count=thought,
                           cached_content_token_count=0)
    cands = [SimpleNamespace(finish_reason=finish)] if finish else []
    fb = SimpleNamespace(block_reason=block, block_reason_message=message) if block else None
    return SimpleNamespace(text=text, usage_metadata=meta, candidates=cands, prompt_feedback=fb)


def test_empty_response_carries_reasons(pauses):
    from google.genai import types

    g = fake_gemini([reply(finish=types.FinishReason.MAX_TOKENS, thought=8123)])
    with pytest.raises(EmptyResponse) as e:
        g.text("s", "p")
    x = e.value
    assert isinstance(x, RuntimeError) and str(x).startswith("Gemini 응답이 비었어요")
    assert (x.finish, x.block, x.thought) == ("MAX_TOKENS", "", 8123) and g.last_finish == "MAX_TOKENS"
    assert not llm.is_transient(x) and not is_rate_limit(x)  # 다시 부르지 않는다
    assert "생각만 8,123토큰" in explain_error(x)

    g = fake_gemini([reply(block=types.BlockedReason.PROHIBITED_CONTENT, message="blocked")])
    with pytest.raises(EmptyResponse) as e:
        g.text("s", "p")
    assert e.value.block == "PROHIBITED_CONTENT" and e.value.finish == ""
    assert explain_error(e.value).startswith("AI 안전 필터가 막았어요")


@pytest.mark.parametrize("err, start", [
    (EmptyResponse("SAFETY"), "AI 안전 필터가 막았어요. 표현을 누그러뜨리거나 쓰기 단계 모델을 바꿔 보세요"),
    (EmptyResponse("", "SAFETY"), "AI 안전 필터가 막았어요"),
    (EmptyResponse("PROHIBITED_CONTENT"), "AI 안전 필터가 막았어요"),
    (EmptyResponse("RECITATION"), "AI가 기존 글과 너무 비슷해 멈췄어요"),
    (EmptyResponse("MAX_TOKENS", thought=4000), "AI가 생각만 4,000토큰 쓰고"),
    (api_error(400, "The input token count (1300000) exceeds the maximum number of tokens allowed (1048576).", "INVALID_ARGUMENT"),
     "입력이 모델이 받을 수 있는 길이를 넘었어요"),
    (RuntimeError("로컬 서버 오류 400 (http://x/v1/chat/completions): the request exceeds the available context size"),
     "입력이 모델이 받을 수 있는 길이를 넘었어요"),
    (api_error(400, "User location is not supported for the API use.", "FAILED_PRECONDITION"), "지금 있는 지역에서는 Gemini API를"),
])
def test_table_rows(err, start):
    assert explain_error(err).startswith(start)


def test_no_broad_patterns():
    """넓은 낱말('blocked', '400')로 다른 줄에 빨려 들지 않는다."""
    blocked = api_error(403, "Requests to this API generativelanguage.googleapis.com method "
                        "google.ai.generativelanguage.v1beta.GenerativeService.GenerateContent are blocked.", "PERMISSION_DENIED")
    assert explain_error(blocked).startswith("AI 서비스가 오류를 돌려줬어요 (403): Requests to this API")
    bad = api_error(400, "Invalid value at 'generation_config.max_output_tokens'", "INVALID_ARGUMENT")
    assert explain_error(bad) == "AI 서비스가 오류를 돌려줬어요 (400): Invalid value at 'generation_config.max_output_tokens'"
    assert explain_error(EmptyResponse("MAX_TOKENS")).startswith("Gemini 응답이 비었어요: 끝난 이유 MAX_TOKENS")  # 생각 없이 끊김
    assert explain_error(EmptyResponse("STOP")) == "Gemini 응답이 비었어요: 끝난 이유 STOP"


def test_fallback_keeps_korean_and_cuts_foreign():
    long_ko = "다시 요청해도 모델 응답이 StyleProfile 형식과 맞지 않아요: " + "가" * 300
    assert explain_error(RuntimeError(long_ko)) == long_ko  # Canon 이 낸 한국어 오류는 자르지 않는다
    assert explain_error(RateLimited(90)).startswith(llm.RATE_HINT)
    text = explain_error(api_error(500, "x" * 400, "INTERNAL"))
    assert text == f"AI 서비스가 오류를 돌려줬어요 (500): {'x' * llm.FOREIGN_CUT}…"
    assert explain_error(AttributeError("'NoneType' object has no attribute 'text'")) == \
        "오류가 났어요: 'NoneType' object has no attribute 'text'"
    assert explain_error(KeyError()) == "KeyError"


def test_job_and_web_show_explained(monkeypatch):
    job = jobs.start("등대", "write", 1, "쓰기", lambda j: (_ for _ in ()).throw(EmptyResponse("RECITATION")))
    for _ in range(200):
        if job.status != "running":
            break
        import time
        time.sleep(0.01)
    assert job.status == "error" and job.error.startswith("AI가 기존 글과 너무 비슷해")

    from canon import web

    r = asyncio.run(web._server_error(None, EmptyResponse("SAFETY")))
    assert r.status_code == 500 and json.loads(r.body)["detail"].startswith("AI 안전 필터가 막았어요")


def test_autorun_quota_halt(tmp_path, monkeypatch):
    import contextlib
    import io

    from canon import store
    from canon.cli import main

    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(autorun, "_controls", {})
    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "3", "-y"])
        main(["arc", "demo", "-y"])
        main(["plot", "demo"])
        main(["confirm", "demo", "all"])

    def spent(*a, **kw):
        raise QuotaSpent() from per_day()

    from canon import pipeline

    monkeypatch.setattr(pipeline, "write_episode", spent)  # 본문 쓰기 호출에서 하루 한도에 걸린다
    run = autorun.start("demo", 1, False, autorun.Policy(hand_pick_opening=False), foreground=True)
    assert run.status == "paused" and run.halt == "quota" and run.ep == 1  # 화면의 갈 곳 버튼은 ep 가 있어야 보인다
    assert run.reasons[0].startswith(llm.QUOTA_HINT) and "이어 가세요" in run.reasons[1]
    jobs.draining.clear()
