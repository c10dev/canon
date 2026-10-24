"""사용량 기록과 비용 추정 (canon/usage.py) 테스트. 실제 API 대신 가짜 Gemini 클라이언트를 쓴다."""
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())

from canon import autorun, jobs, store, usage  # noqa: E402
from canon.llm import BatchLLM, GeminiLLM, SchemaMismatch, get_llm  # noqa: E402
from canon.schema import StyleProfile  # noqa: E402


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)

    def generate_content(self, model, contents, config):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        meta = SimpleNamespace(prompt_token_count=1000, candidates_token_count=200, thoughts_token_count=50,
                               cached_content_token_count=400)
        return SimpleNamespace(text=r, usage_metadata=meta, candidates=[])


def fake_gemini(replies, model="gemini-4-argon"):
    llm = GeminiLLM.__new__(GeminiLLM)
    llm.client = SimpleNamespace(models=FakeModels(replies))
    llm.model, llm.last_usage, llm.last_attempts, llm.last_raw = model, None, 0, ""
    return llm


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("CANON_USAGE", raising=False)
    return tmp_path


def test_records_calls_with_scope_and_cost():
    llm = fake_gemini(["본문", RuntimeError("503 과부하")])
    llm.stage = "write"
    with usage.scope(project="등대", episode=3, source="web", task="write"):
        assert llm.text("s", "p") == "본문"
        with pytest.raises(RuntimeError):
            llm.text("s", "p")
    rows = usage.read()
    assert [r["ok"] for r in rows] == [True, False]
    r = rows[0]
    assert (r["project"], r["episode"], r["stage"], r["model"], r["backend"]) == ("등대", 3, "write", "gemini-4-argon", "gemini")
    assert (r["in"], r["out"], r["thought"], r["cached"]) == (1000, 200, 50, 400)
    assert "503" in rows[1]["error"]
    s = usage.summary(30)
    # 600 입력 × $2 + 400 캐시 × $0.1 + 250 출력 × $10 (100만 토큰당)
    assert s["total"]["cost"] == pytest.approx((600 * 2 + 400 * 0.1 + 250 * 10) / 1e6)
    assert s["total"]["failed"] == 1
    assert s["by_episode"][0]["episode"] == 3
    assert s["by_stage"][0]["stage"] == "write"
    # 최근 호출 목록은 limit 까지만, 실패 목록의 전체 수는 따로 준다
    short = usage.summary(30, limit=1)
    assert len(short["recent"]) == 1 and short["total"]["calls"] == 2 and short["trouble_total"] == 1


def test_schema_retry_is_recorded_as_failed_then_retry():
    good = StyleProfile().model_dump_json()
    llm = fake_gemini(["{\"narration\": 3", good])
    assert isinstance(llm.json("s", "p", StyleProfile), StyleProfile)
    rows = usage.read()
    assert [(r["ok"], r["attempt"]) for r in rows] == [(False, 1), (True, 2)]
    assert "형식" in rows[0]["error"]
    t = usage.summary(30)["total"]
    assert t["retries"] == 1 and t["failed"] == 1 and t["wasted"] > 0

    llm = fake_gemini(["{", "{"])
    with pytest.raises(SchemaMismatch):
        llm.json("s", "p", StyleProfile)


def test_mock_is_not_recorded(monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    get_llm("write").text("s", "p")
    assert usage.read() == []


def test_batch_cost_and_savings():
    class Inner:
        model = "gemini-4-argon"

        def batch_submit(self, *a, **k):
            return "b1"

        def batch_poll(self, name):
            self.last_usage = {"prompt_tokens": 1_000_000, "completion_tokens": 100_000}
            return "본문"

    inner = Inner()
    Inner.__name__ = "GeminiLLM"  # 기록은 백엔드를 클래스 이름으로 가린다
    b = BatchLLM(inner, "1:write", {}, lambda: None, lambda s: "", interval=0)
    assert b.text("s", "p") == "본문"
    t = usage.summary(30)["total"]
    assert t["batch"] == 1
    assert t["cost"] == pytest.approx(1.0 + 0.5)  # 배치 입력 $1, 출력 $5
    assert t["saved"] == pytest.approx(1.5)


def test_price_dates_and_prefix():
    assert usage.rate("gemini-4-argon", "2026-11-30").input == 2.0
    assert usage.rate("gemini-4-argon", "2026-12-01").input == 4.0
    assert usage.rate("models/gemini-3.8-flash-001", "2026-10-22").output == 3.75
    assert usage.rate("gpt-unknown") is None


def test_custom_prices_override_defaults_and_estimate_uses_them(monkeypatch):
    rows = [usage.Price.model_validate(r) for r in usage.price_table()["rows"]]
    usage.save_prices(rows)  # 기본값 그대로면 설정 파일에 남기지 않는다
    assert usage.custom_models() == set()
    rows = [r for r in rows if r.model != "gemini-4-argon"] + [usage.Price(model="gemini-4-argon", input=1, output=1)]
    usage.save_prices(rows)
    assert usage.custom_models() == {"gemini-4-argon"}
    assert usage.rate("gemini-4-argon", "2027-01-01").output == 1  # 사용자 줄이 예고된 인상 줄까지 대신한다
    monkeypatch.setenv("CANON_LLM", "gemini")
    assert autorun.stage_cost("write", 1e6, 1e6, False) == pytest.approx(2.0)
    assert autorun.stage_cost("write", 1e6, 1e6, True) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        usage.save_prices([usage.Price(model="x", since="12월", input=1, output=1)])


def test_local_is_free_and_unknown_model_flagged():
    at = "2026-10-22T10:00:00+09:00"
    assert usage.row_cost({"backend": "local", "model": "gemma-4-31b", "in": 10, "out": 10, "at": at}, usage.prices())[0] == 0.0
    assert usage.row_cost({"backend": "gemini", "model": "gemini-9", "in": 10, "out": 10, "at": at}, usage.prices())[0] is None


def test_jobs_thread_keeps_scope():
    seen = {}

    def fn(job):
        seen.update(usage.context())

    with usage.scope(project="등대", episode=2, task="write"):
        job = jobs.start("등대", "usage-test", 2, "t", fn)
    import time
    for _ in range(100):
        if job.status != "running":
            break
        time.sleep(0.01)
    assert seen["project"] == "등대" and seen["episode"] == 2
