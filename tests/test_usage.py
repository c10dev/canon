"""사용량 기록과 비용 추정 (canon/usage.py) 테스트. 실제 API 대신 가짜 Gemini 클라이언트를 쓴다."""
import contextvars
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
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
        self.configs = [*getattr(self, "configs", []), config]
        r = self.replies.pop(0)
        if callable(r):
            r = r()
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


def test_summary_groups_by_task_and_effort_with_cache_rate():
    """작업 · 추론 강도로도 묶고, 묶음마다 캐시 비율(캐시 / 입력)과 호출당 평균 시간을 준다."""
    import json
    from datetime import datetime
    now = datetime.now().isoformat(timespec="seconds")
    base = {"at": now, "project": "지하철", "backend": "gemini", "model": "gemini-4-argon", "out": 10, "ok": True}
    rows = [
        {**base, "stage": "revise", "task": "fixes", "effort": "high", "in": 1000, "cached": 200, "seconds": 10.0},
        {**base, "stage": "revise", "task": "fixes", "effort": "high", "in": 1000, "cached": 0, "seconds": 20.0},
        {**base, "stage": "write", "task": "write", "in": 2000, "cached": 1000, "seconds": 3.0},
        {**base, "stage": "check", "in": 0, "cached": 0, "seconds": 1.0},
    ]
    usage.log_path().parent.mkdir(parents=True, exist_ok=True)
    usage.log_path().write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    s = usage.summary(30)
    task = {r["task"]: r for r in s["by_task"]}
    assert set(task) == {"fixes", "write", ""}
    assert task["fixes"]["in"] == 2000 and task["fixes"]["cache_rate"] == pytest.approx(0.1)
    assert task["fixes"]["seconds_avg"] == pytest.approx(15.0)
    assert task["write"]["cache_rate"] == pytest.approx(0.5)
    assert task[""]["cache_rate"] == 0.0  # 입력이 없으면 0
    effort = {r["effort"]: r for r in s["by_effort"]}
    assert set(effort) == {"high", "기본"}  # 정하지 않은 호출은 '기본'
    assert effort["high"]["calls"] == 2 and effort["기본"]["calls"] == 2
    assert s["total"]["cache_rate"] == pytest.approx(1200 / 4000)
    assert s["total"]["seconds_avg"] == pytest.approx(8.5)
    assert all("cache_rate" in r and "seconds_avg" in r for k in ("by_stage", "by_model", "by_day") for r in s[k])


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


ONE_CALL = (600 * 2 + 400 * 0.1 + 250 * 10) / 1e6  # fake_gemini 한 번: 입력 600 + 캐시 400 + 출력·생각 250 (gemini-4-argon)


def test_collect_sums_every_call_including_threads():
    good = StyleProfile().model_dump_json()
    llm = fake_gemini(["{\"narration\": 3", good, "본문", "본문"])
    with usage.collect() as rows:
        llm.json("s", "p", StyleProfile)  # 형식 고치기 재시도로 두 번 부른다
        with ThreadPoolExecutor(1) as pool:  # 검수의 동작 검사처럼 다른 스레드에서 부른 것도 모인다
            pool.submit(contextvars.copy_context().run, llm.text, "s", "p").result()
    assert len(rows) == 3
    tin, tout, cost = usage.totals(rows)
    assert (tin, tout) == (3000, 750)
    assert cost == pytest.approx(3 * ONE_CALL)  # 캐시 할인도 사용량 화면과 같게 든다
    assert usage.summary(30)["total"]["cost"] == pytest.approx(cost)
    llm.text("s", "p")  # collect 밖의 호출은 더하지 않는다
    assert len(rows) == 3


def test_autorun_stage_counts_retry_tokens(monkeypatch):
    good = StyleProfile().model_dump_json()
    llm = fake_gemini(["{\"narration\": 3", good])
    monkeypatch.setattr(autorun, "get_llm", lambda stage: llm)
    store.project_dir("등대").mkdir(parents=True, exist_ok=True)
    runner = autorun.Runner(autorun.Control("등대", autorun.Run(target=1)))
    out, info = runner.call("check", 1, lambda m: m.json("s", "p", StyleProfile))
    assert isinstance(out, StyleProfile)
    assert (info["tokens_in"], info["tokens_out"], info["calls"]) == (2000, 500, 2)
    assert (runner.run.tokens_in, runner.run.tokens_out) == (2000, 500)
    assert runner.run.cost == pytest.approx(round(2 * ONE_CALL, 4))
    assert {r["source"] for r in usage.read()} == {"autorun"}


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


def _rows(backend, model, slope, intercept, n=30, **extra):
    return [{"backend": backend, "model": model, "ok": True, "chars": 2_000 + 1_000 * i,
             "in": round(slope * (2_000 + 1_000 * i) + intercept), **extra} for i in range(n)]


def test_token_rate_defaults_by_backend_and_model():
    opus = usage.token_rate("claude", "claude-opus-5-5", rows=[])
    assert (opus.slope, opus.intercept, opus.source) == (1.035, 3805, "default")
    assert usage.token_rate("claude", "sonnet", rows=[]).slope == 0.995  # Claude Code 별칭도 고른다
    assert usage.token_rate("claude", "", rows=[]).slope == 1.035  # 기본 모델은 이름을 몰라 Opus 로 본다
    assert usage.token_rate("claude-api", "claude-opus-5-5", rows=[]).intercept == 0
    assert usage.token_rate("gemini", "models/gemini-3.8-flash-001", rows=[]).slope == 0.599
    assert usage.token_rate("gemini", "gemini-4-argon", rows=[]).slope == 0.568
    assert usage.token_rate("", "gemini-4-argon", rows=[]).slope == 0.568  # 백엔드를 모르면 모델 이름으로
    local = usage.token_rate("local", "gemma-4-31b", rows=[])
    assert local.source == "fallback" and local.slope == pytest.approx(1 / 1.7) and local.intercept == 0
    assert usage.est_input(10_000, opus) == pytest.approx(10_350 + 3805)
    assert usage.est_output(10_000, opus) == pytest.approx(10_350)


def test_token_rate_refines_from_recent_rows():
    rows = _rows("gemini", "gemini-4-argon", 0.7, 900)
    r = usage.token_rate("gemini", "gemini-4-argon", rows=rows)
    assert r.source == "measured" and r.rows == 30
    assert r.slope == pytest.approx(0.7, abs=1e-3) and r.intercept == pytest.approx(900, abs=2)
    assert usage.token_rate("gemini", "gemini-3.8-flash", rows=rows).source == "default"  # 다른 모델 기록은 보지 않는다
    assert usage.token_rate("gemini", "gemini-4-argon", rows=rows[:usage.REFINE_MIN - 1]).source == "default"  # 줄이 적으면 기본값
    failed = [{**x, "ok": False} for x in rows]
    assert usage.token_rate("gemini", "gemini-4-argon", rows=failed).source == "default"
    flat = [{**x, "chars": 5_000} for x in rows]  # 글자 수가 모두 같으면 직선을 긋지 않는다
    assert usage.token_rate("gemini", "gemini-4-argon", rows=flat).source == "default"
    wild = _rows("gemini", "gemini-4-argon", 9.0, 0)  # 말이 안 되는 기울기는 버린다
    assert usage.token_rate("gemini", "gemini-4-argon", rows=wild).source == "default"
    neg = _rows("gemini", "gemini-4-argon", 0.8, -500)  # 붙는 토큰이 음수면 원점을 지나는 비율
    r = usage.token_rate("gemini", "gemini-4-argon", rows=neg)
    assert r.intercept == 0
    assert r.slope == pytest.approx(sum(x["in"] for x in neg) / sum(x["chars"] for x in neg), abs=1e-3)


def test_token_rate_skips_doubled_claude_rows():
    good = _rows("claude", "claude-opus-5-5", 1.0, 3000, cached=0)
    doubled = _rows("claude", "claude-opus-5-5", 2.0, 6000)
    for x in doubled:
        x["cached"] = x["in"] // 2  # 캐시 읽기를 입력에 두 번 센 기록
    r = usage.token_rate("claude", "claude-opus-5-5", rows=good + doubled)
    assert r.source == "measured" and r.rows == 30 and r.slope == pytest.approx(1.0, abs=1e-3)
    assert usage.token_rate("claude", "claude-opus-5-5", rows=doubled).source == "default"
    # 앞부분을 시스템 프롬프트로 옮겨 캐시가 입력 대부분인 정상 기록은 남긴다
    hits = _rows("claude", "claude-opus-5-5", 1.0, 3000)
    for x in hits:
        x["cached"] = round(x["in"] * 0.85)
    r = usage.token_rate("claude", "claude-opus-5-5", rows=hits)
    assert r.source == "measured" and r.rows == 30 and r.slope == pytest.approx(1.0, abs=1e-3)


def test_token_rate_matches_claude_code_aliases():
    """Claude Code 기록에는 실제로 답한 모델 이름이 남는다. 설정의 별칭(opus)이나 빈 기본 모델도 그 기록으로 다시 잰다."""
    rows = _rows("claude", "claude-opus-5-5", 1.1, 2500) + _rows("claude", "claude-sonnet-5-5", 0.9, 5000, n=5)
    alias = usage.token_rate("claude", "opus", rows=rows)
    assert alias.source == "measured" and alias.rows == 30 and alias.slope == pytest.approx(1.1, abs=1e-3)
    default = usage.token_rate("claude", "", rows=rows)  # 기본 모델은 최근 기록에 가장 많은 모델로 본다
    assert default.source == "measured" and default.slope == pytest.approx(1.1, abs=1e-3)
    assert usage.token_rate("claude", "sonnet", rows=rows).source == "default"  # Sonnet 기록은 5줄뿐
    assert usage.token_rate("gemini", "flash", rows=_rows("gemini", "gemini-3.8-flash", 0.7, 900)).source == "default"


def test_est_input_counts_system_prompt_once():
    """붙는 토큰에 시스템 프롬프트가 이미 들어 있다. 붙는 토큰을 모르는 백엔드만 시스템 프롬프트를 기울기로 센다."""
    opus = usage.token_rate("claude", "claude-opus-5-5", rows=[])
    assert usage.est_input(10_000, opus, 1_200) == pytest.approx(10_350 + 3805)
    assert usage.est_input(10_000, opus, 8_000) == pytest.approx(10_350 + 8_280)  # 시스템 프롬프트가 더 길면 그것을 센다
    assert usage.est_input(10_000, opus, 1_200, calls=3) == pytest.approx(10_350 + 3 * 3805)
    api = usage.token_rate("claude-api", "claude-opus-5-5", rows=[])
    assert usage.est_input(10_000, api, 1_000) == pytest.approx(10_350 + 1_035)


def test_token_rate_reads_usage_log(home):
    import json

    path = home / ".usage" / "usage.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in _rows("gemini", "gemini-4-argon", 0.65, 1200)), encoding="utf-8")
    r = usage.token_rate("gemini", "gemini-4-argon")
    assert r.source == "measured" and r.slope == pytest.approx(0.65, abs=1e-3)


def test_stage_rate_follows_stage_backend(monkeypatch):
    monkeypatch.setenv("CANON_LLM", "gemini")
    monkeypatch.setenv("CANON_MODEL", "gemini-4-argon")
    monkeypatch.setenv("CANON_LLM_STATE", "claude")
    monkeypatch.setenv("CANON_MODEL_STATE", "claude-sonnet-5-5")
    monkeypatch.setenv("CANON_LLM_CHECK", "claude-api")
    monkeypatch.delenv("CANON_CLAUDE_MODEL", raising=False)
    assert usage.stage_llm("write") == ("gemini", "gemini-4-argon")
    assert usage.stage_llm("state") == ("claude", "claude-sonnet-5-5")
    assert usage.stage_llm("check")[0] == "claude-api" and usage.stage_llm("check")[1].startswith("claude-")
    assert usage.stage_rate("write").slope == 0.568 and usage.stage_rate("state").slope == 0.995


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


def _limited():
    from google.genai import errors

    return errors.ClientError(429, {"error": {"code": 429, "message": "Resource exhausted. Please try again later.",
                                              "status": "RESOURCE_EXHAUSTED"}})


@pytest.fixture
def pauses(monkeypatch):
    from canon import llm as llm_mod

    out = []
    monkeypatch.setattr(llm_mod, "_pause", out.append)
    return out


def test_rate_limit_waits_and_calls_again(pauses):
    """429 가 두 번 나도 기다려 다시 불러 받는다. 실패한 두 번은 실패로, 받은 한 번은 성공으로 남는다."""
    llm = fake_gemini([_limited(), _limited(), "본문"])
    assert llm.text("s", "p") == "본문"
    assert pauses == [30, 60]
    rows = usage.read()
    assert [r["ok"] for r in rows] == [False, False, True]
    assert rows[0]["error"].startswith("요청 한도 (429)")

    good = StyleProfile().model_dump_json()
    llm = fake_gemini([_limited(), good])
    assert isinstance(llm.json("s", "p", StyleProfile), StyleProfile) and llm.last_attempts == 1


def test_retry_wait_is_told_to_job_line(pauses):
    """요청 한도로 기다리거나 응답 지연으로 다시 부르면 작업 진행 줄(cancel.say → Job.retry)에 알리고, 받으면 비운다."""
    from canon import cancel

    said = []
    tok = cancel.notice.set(said.append)
    try:
        assert fake_gemini([_limited(), _limited(), "본문"]).text("s", "p") == "본문"
        assert said == ["AI 요청 한도에 걸려 30초 기다려요 (1/3)", "AI 요청 한도에 걸려 60초 기다려요 (2/3)", ""]
        said.clear()
        assert fake_gemini([_timed_out(), "본문"]).text("s", "p") == "본문"
        assert said == ["AI 응답이 늦어 다시 불러요", ""]
        said.clear()
        assert fake_gemini(["본문"]).text("s", "p") == "본문"
        assert said == []  # 다시 부르지 않은 호출은 진행 줄을 건드리지 않는다
    finally:
        cancel.notice.reset(tok)


def test_bad_key_is_korean_and_not_retried(pauses):
    """키가 틀리면(400 API_KEY_INVALID, 403) 다시 부르지 않고 영어 원문 대신 설정 안내(BadKey)를 낸다."""
    from google.genai import errors

    from canon.llm import KEY_HINT, BadKey

    bad = errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                             "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}})
    denied = errors.ClientError(403, {"error": {"code": 403, "message": "Permission denied", "status": "PERMISSION_DENIED"}})
    for e in (bad, denied):
        llm = fake_gemini([e, "본문"])
        with pytest.raises(BadKey) as got:
            llm.text("s", "p")
        assert str(got.value) == KEY_HINT and "API 키" in KEY_HINT
        assert pauses == [] and llm.client.models.replies == ["본문"]
    from canon.llm import VERTEX_HINT

    llm = fake_gemini([denied])
    llm.vertex = True  # Vertex 는 키가 아니라 서비스 계정 권한을 말한다
    with pytest.raises(BadKey) as got:
        llm.text("s", "p")
    assert str(got.value) == VERTEX_HINT


def test_bad_key_web_answer():
    """웹은 BadKey 를 code bad_key 와 한국어 안내로 돌려준다 (화면이 설정을 열지 묻는다)."""
    import asyncio
    import json as _json

    from canon import web
    from canon.llm import KEY_HINT, BadKey

    r = asyncio.run(web._bad_key(None, BadKey(KEY_HINT)))
    assert r.status_code == 400 and _json.loads(r.body) == {"detail": KEY_HINT, "code": "bad_key"}


def test_job_public_has_retry():
    from canon import jobs

    job = jobs.Job(id="x", project="p", kind="write", ep=1, label="1화 집필")
    job.say("AI 응답이 늦어 다시 불러요")
    assert job.public()["retry"] == "AI 응답이 늦어 다시 불러요"
    # 다른 스레드(함께 부르는 검수 뽑기)가 비워도 이 스레드의 사정은 남는다
    import threading as _t
    w = _t.Thread(target=lambda: (job.say("AI 요청 한도에 걸려 30초 기다려요 (1/3)"), job.say("")))
    w.start()
    w.join()
    assert job.retry == "AI 응답이 늦어 다시 불러요"
    job.say("")
    assert job.retry == "" and job.retries == {}


def test_rate_limit_gives_up_with_clear_message(pauses):
    """끝내 429 면 5분 안에서 기다린 뒤 해요체 안내로 멈춘다. 웹 작업 오류도 같은 글이다."""
    from canon.llm import RATE_HINT, RATE_WAITS, RateLimited

    assert sum(RATE_WAITS) <= 300
    llm = fake_gemini([_limited() for _ in range(len(RATE_WAITS) + 1)])
    with pytest.raises(RateLimited) as e:
        llm.text("s", "p")
    assert pauses == list(RATE_WAITS) and llm.client.models.replies == []
    assert str(e.value).startswith(RATE_HINT) and "다시 시도해 주세요" in str(e.value)
    assert [r["ok"] for r in usage.read()] == [False] * (len(RATE_WAITS) + 1)

    pauses.clear()
    llm = fake_gemini([_limited() for _ in range(len(RATE_WAITS) + 1)])
    job = jobs.start("등대", "write", 1, "쓰기", lambda j: llm.text("s", "p"))
    for _ in range(200):
        if job.status != "running":
            break
        import time
        time.sleep(0.01)
    assert job.status == "error" and job.error.startswith(RATE_HINT)


def test_rate_limit_stops_when_job_is_stopped(monkeypatch):
    """기다리는 동안 작업을 멈추면 다시 부르지 않는다."""
    import threading

    from canon import cancel
    from canon import llm as llm_mod

    stop = threading.Event()
    monkeypatch.setattr(llm_mod, "_pause", lambda s: stop.set())
    llm = fake_gemini([_limited(), "본문"])
    token = cancel.current.set(stop)
    try:
        with pytest.raises(cancel.Cancelled):
            llm.text("s", "p")
    finally:
        cancel.current.reset(token)
    assert llm.client.models.replies == ["본문"]


def _timed_out():
    import httpx

    return httpx.ReadTimeout("The read operation timed out")


def test_timeout_is_set_on_each_request(monkeypatch):
    """요청마다 SDK 의 응답 시간 한도(밀리초)를 준다. 기본 10분, CANON_GEMINI_TIMEOUT(초)로 바꾼다."""
    from canon.llm import GEMINI_TIMEOUT, gemini_timeout

    assert GEMINI_TIMEOUT == 600
    monkeypatch.delenv("CANON_GEMINI_TIMEOUT", raising=False)
    llm = fake_gemini(["본문"])
    llm.text("s", "p")
    assert llm.client.models.configs[0].http_options.timeout == 600_000
    monkeypatch.setenv("CANON_GEMINI_TIMEOUT", "90")
    llm = fake_gemini(["본문"])
    llm.text("s", "p")
    assert llm.client.models.configs[0].http_options.timeout == 90_000
    for bad in ("0", "-5", "abc"):
        monkeypatch.setenv("CANON_GEMINI_TIMEOUT", bad)
        assert gemini_timeout() == GEMINI_TIMEOUT


def test_timeout_calls_once_more(pauses):
    """응답 시간을 한 번 넘기면 기다리지 않고 한 번 더 부른다. 넘긴 시도는 실패로 남는다."""
    llm = fake_gemini([_timed_out(), "본문"])
    assert llm.text("s", "p") == "본문"
    assert pauses == [] and llm.client.models.replies == []
    rows = usage.read()
    assert [r["ok"] for r in rows] == [False, True]
    assert rows[0]["error"].startswith("응답 시간 초과")


def test_server_deadline_counts_as_timeout(pauses):
    """서버가 시간 한도를 먼저 넘겨 504 DEADLINE_EXCEEDED 를 돌려줘도 한 번 더 부른다 (2026-11-04 플롯 대화 한 단계)."""
    from google.genai import errors

    late = errors.ServerError(504, {"error": {"code": 504, "message": "Deadline expired before operation could complete.",
                                              "status": "DEADLINE_EXCEEDED"}})
    llm = fake_gemini([late, "본문"])
    assert llm.text("s", "p") == "본문"
    assert usage.read()[0]["error"].startswith("응답 시간 초과")


def _overloaded(code=503, status="UNAVAILABLE"):
    from google.genai import errors

    return errors.ServerError(code, {"error": {"code": code, "message": "The model is overloaded. Please try again later.",
                                               "status": status}})


def test_server_overload_waits_and_calls_again(pauses):
    """503 UNAVAILABLE · 500 INTERNAL 은 SERVER_WAITS 만큼 기다려 다시 부른다. 실패한 시도는 '서버 오류'로 남는다."""
    from canon.llm import SERVER_WAITS

    llm = fake_gemini([_overloaded(), _overloaded(500, "INTERNAL"), "본문"])
    assert llm.text("s", "p") == "본문"
    assert pauses == list(SERVER_WAITS[:2])
    rows = usage.read()
    assert [r["ok"] for r in rows] == [False, False, True]
    assert rows[0]["error"].startswith("서버 오류 (503)") and rows[1]["error"].startswith("서버 오류 (500)")


def test_server_overload_gives_up_with_clear_message(pauses):
    """끝내 503 이면 해요체 안내 ServerBusy 로 멈춘다. 429 와 따로 센다. 400 같은 다른 오류는 다시 부르지 않는다."""
    from google.genai import errors

    from canon.llm import RATE_WAITS, SERVER_HINT, SERVER_WAITS, ServerBusy

    llm = fake_gemini([_overloaded() for _ in range(len(SERVER_WAITS) + 1)] + ["본문"])
    with pytest.raises(ServerBusy) as e:
        llm.text("s", "p")
    assert str(e.value).startswith(SERVER_HINT) and "(503)" in str(e.value) and "다시 시도해 주세요" in str(e.value)
    assert pauses == list(SERVER_WAITS) and llm.client.models.replies == ["본문"]

    pauses.clear()
    llm = fake_gemini([_overloaded(), _limited(), _overloaded(), "본문"])
    assert llm.text("s", "p") == "본문"
    assert pauses == [SERVER_WAITS[0], RATE_WAITS[0], SERVER_WAITS[1]]

    pauses.clear()
    bad = errors.ClientError(400, {"error": {"code": 400, "message": "bad", "status": "INVALID_ARGUMENT"}})
    llm = fake_gemini([bad, "본문"])
    with pytest.raises(errors.ClientError):
        llm.text("s", "p")
    assert pauses == []


def test_rate_limit_uses_server_retry_delay(pauses):
    """429 의 RetryInfo.retryDelay 가 있으면 그 값(올림)을 기다린다. RATE_WAITS 의 가장 긴 값을 넘지 않는다."""
    from google.genai import errors

    from canon.llm import RATE_WAITS, retry_delay

    def limited(delay):
        return errors.ClientError(429, {"error": {"code": 429, "message": "Resource exhausted.", "status": "RESOURCE_EXHAUSTED",
                                                  "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                                               "retryDelay": delay}]}})

    assert retry_delay(limited("37s")) == 37 and retry_delay(_limited()) is None
    assert retry_delay(limited({"seconds": 4, "nanos": 500_000_000})) == 4.5
    assert retry_delay(limited("abc")) is None
    llm = fake_gemini([limited("7.2s"), limited("900s"), _limited(), "본문"])
    assert llm.text("s", "p") == "본문"
    assert pauses == [8, max(RATE_WAITS), RATE_WAITS[2]]


def test_timeout_twice_gives_clear_message(pauses):
    """두 번 다 넘기면 해요체 안내로 멈춘다. 웹 작업 오류도 같은 글이다."""
    from canon.llm import TIMEOUT_HINT, TimedOut

    llm = fake_gemini([_timed_out(), _timed_out(), "본문"])
    with pytest.raises(TimedOut) as e:
        llm.text("s", "p")
    assert str(e.value).startswith(TIMEOUT_HINT) and "다시 시도해 주세요" in str(e.value)
    assert llm.client.models.replies == ["본문"] and pauses == []
    rows = usage.read()
    assert [r["ok"] for r in rows] == [False, False]
    assert all(r["error"].startswith("응답 시간 초과") for r in rows)

    llm = fake_gemini([_timed_out(), _timed_out()])
    job = jobs.start("등대", "write", 1, "쓰기", lambda j: llm.text("s", "p"))
    for _ in range(200):
        if job.status != "running":
            break
        import time
        time.sleep(0.01)
    assert job.status == "error" and job.error.startswith(TIMEOUT_HINT)


def test_timeout_stops_when_job_is_stopped():
    """시간 초과 뒤 작업을 멈췄으면 다시 부르지 않는다."""
    import threading

    from canon import cancel

    stop = threading.Event()

    def timeout_then_stop():
        stop.set()
        return _timed_out()

    llm = fake_gemini([timeout_then_stop, "본문"])
    token = cancel.current.set(stop)
    try:
        with pytest.raises(cancel.Cancelled):
            llm.text("s", "p")
    finally:
        cancel.current.reset(token)
    assert llm.client.models.replies == ["본문"]


def test_timeout_and_rate_limit_together(pauses):
    """429 와 시간 초과는 따로 센다: 429 한 번, 시간 초과 한 번이 섞여도 받는다."""
    llm = fake_gemini([_limited(), _timed_out(), "본문"])
    assert llm.text("s", "p") == "본문"
    assert pauses == [30]
    assert [r["error"].split(" ")[0] for r in usage.read()[:2]] == ["요청", "응답"]


def test_other_errors_are_not_retried(pauses):
    from google.genai import errors

    llm = fake_gemini([errors.ClientError(400, {"error": {"code": 400, "message": "bad", "status": "INVALID_ARGUMENT"}})])
    with pytest.raises(errors.ClientError):
        llm.text("s", "p")
    assert pauses == []

    llm = fake_gemini([RuntimeError("503 과부하"), "본문"])
    with pytest.raises(RuntimeError, match="503"):
        llm.text("s", "p")
    assert pauses == [] and llm.client.models.replies == ["본문"]


def test_old_rows_read_and_cache_rate_drops_resent(home):
    old = {"at": "2026-11-01T10:00:00+09:00", "backend": "claude", "model": "x", "in": 1000, "out": 10, "cached": 200, "ok": True}
    new = {**old, "in": 2000, "cached": 1200, "turns": 2, "resent": 1000, "stop": "end_turn"}
    path = usage.log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in (old, new)) + "\n", encoding="utf-8")
    t = usage.summary(0)["total"]
    assert (t["in"], t["cached"], t["resent"]) == (3000, 1400, 1000)  # 비용 칸(in · cached)은 그대로 더한다
    assert t["cache_rate"] == pytest.approx(400 / 2000)  # 다시 보낸 입력은 입력과 캐시 양쪽에서 뺀다
    assert usage.cache_rate([old]) == pytest.approx(0.2)
    assert usage.cache_rate([]) is None
    from fastapi.testclient import TestClient
    from canon.web import app
    assert TestClient(app).get("/api/usage?days=0").json()["total"]["resent"] == 1000  # 응답 모델이 칸을 지우지 않는다

    # 캐시가 없는 줄의 resent 가 다른 줄의 캐시를 지우지 않는다 (cache_rate 와 같게 줄마다 자른다)
    odd = {**old, "in": 4000, "cached": 0, "turns": 2, "resent": 2000}
    path.unlink()  # 읽기 캐시는 같은 파일의 늘어난 끝만 읽으므로 새 파일로 쓴다
    path.write_text("\n".join(json.dumps(r) for r in (old, odd)) + "\n", encoding="utf-8")
    usage._read_cache.clear()
    t = usage.summary(0)["total"]
    assert t["cache_rate"] == pytest.approx(usage.cache_rate([old, odd])) == pytest.approx(200 / 5000)


# ---------- 출력 글자 수 · 끝난 이유 · 버린 까닭 (개선 22) ----------

def test_gemini_row_carries_stop_and_out_chars():
    """Gemini 응답의 끝난 이유(stop)와 응답 전체 글자 수(out_chars)를 줄에 싣는다. last_usage 는 토큰 수만 둔다."""
    llm = fake_gemini(["본문 다섯자"])
    reason = SimpleNamespace(name="MAX_TOKENS")
    gen = llm.client.models.generate_content

    def with_reason(model, contents, config):
        r = gen(model, contents, config)
        return SimpleNamespace(**{**vars(r), "candidates": [SimpleNamespace(finish_reason=reason)]})

    llm.client.models.generate_content = with_reason
    llm.text("s", "p")
    row = usage.read()[-1]
    assert (row["stop"], row["out_chars"]) == ("MAX_TOKENS", 6)
    assert usage.is_cut(row)
    assert "stop" not in llm.last_usage and "out_chars" not in llm.last_usage


def test_hold_defers_file_write_and_discard_marks_last_row():
    """hold() 안의 줄은 끝날 때 파일에 쓴다. discard 는 마지막 줄에 까닭을 달고, collect() 에도 같은 값이 보인다."""
    llm = fake_gemini(["a", "b"])
    with usage.collect() as got:
        with usage.hold() as rows:
            llm.text("s", "p")
            with usage.hold() as inner:  # 겹쳐 열면 안쪽 줄은 바깥 목록으로 넘긴다
                llm.text("s", "p")
            assert len(inner) == 1 and len(rows) == 2
            assert usage.read() == []  # 아직 파일에 쓰지 않았다
            usage.discard(rows, "thought")
            usage.discard(rows, "meta")  # 이미 단 까닭은 두고 바꾸지 않는다
    saved = usage.read()
    assert [r.get("discarded") for r in saved] == [None, "thought"]
    assert got[-1]["discarded"] == "thought"
    usage.discard([], "cut")  # 줄이 없으면 아무것도 하지 않는다


def test_scope_target_reaches_row_but_other_keys_do_not():
    """scope 로 넣은 키 가운데 목표 분량(target)만 줄에 싣는다 (usage.SCOPED)."""
    llm = fake_gemini(["a"])
    with usage.scope(target=3000, cache_note="hit"):
        llm.text("s", "p")
    row = usage.read()[-1]
    assert row["target"] == 3000 and "cache_note" not in row


def _project():
    from canon.schema import Episode, EpisodePlot, Project
    p = Project()
    p.meta.words_per_episode = 20
    p.episodes = [Episode(plot=EpisodePlot(number=1, act="기", title="t", summary="s", events=["e"], characters=[],
                                           emotional_shift="", ending_hook=""), status="confirmed")]
    return p


def test_write_marks_discarded_rows_and_target():
    """본문 쓰기가 버린 응답(영어 생각 과정 · 작업 설명)은 그 호출의 줄 자체에 까닭을 단다. 채택한 줄은 낭비로 세지 않는다."""
    from canon import pipeline
    body = "바람이 불었다. 서윤은 등대 앞에 섰다."
    llm = fake_gemini(["Let me think about this chapter first.", "죄송하지만 이 장면은 쓸 수 없습니다. 다른 방향으로 쓸까요?", body])
    llm.stage = "write"
    p = _project()
    assert pipeline._write(llm, p, 1, "쓰기") == body
    rows = usage.read()
    assert [r.get("discarded") for r in rows] == ["thought", "meta", None]
    assert all(r["target"] == 20 and r["attempt"] == 1 for r in rows)
    s = usage.summary(30)
    assert s["total"]["discarded"] == 2 and s["trouble_total"] == 2
    assert s["total"]["wasted"] == pytest.approx(2 * usage.row_cost(rows[0], usage.prices())[0])
    # 분량 달성률은 버리지 않은 줄만: 본문 글자 수 / 목표 20자
    assert s["total"]["len_calls"] == 1 and s["total"]["len_ratio"] == pytest.approx(round(len(body) / 20, 3))


def test_cue_write_target_is_cue_length():
    """큐마다 쓰기는 그 큐의 분량을 목표로 싣는다."""
    from canon import pipeline
    from canon.schema import Cue, CueSheet
    body = "바람이 불었다. 서윤은 등대 앞에 섰다."
    llm = fake_gemini([body, body])
    llm.stage = "write"
    sheet = CueSheet(cues=[Cue(beat="a", length=700), Cue(beat="b", length=300)])
    pipeline.play_cues(llm, _project(), 1, sheet)
    assert [r["target"] for r in usage.read()] == [700, 300]


def test_summary_len_ratio_and_cut_by_effort_skip_old_rows():
    """추론 강도 묶음마다 분량 달성률(len_ratio)과 끊김(cut) · 버림(discarded) 수를 준다. 칸이 없는 옛 줄은 건너뛴다."""
    from datetime import datetime
    now = datetime.now().isoformat(timespec="seconds")
    base = {"at": now, "project": "등대", "stage": "write", "backend": "gemini", "model": "gemini-4-argon",
            "in": 100, "out": 10, "ok": True, "effort": "high"}
    rows = [
        {**base, "target": 1000, "out_chars": 900, "stop": "STOP"},
        {**base, "target": 1000, "out_chars": 1300, "stop": "STOP"},
        {**base, "target": 1000, "out_chars": 400, "stop": "MAX_TOKENS", "discarded": "cut"},  # 버린 줄은 달성률에서 뺀다
        {**base, "stop": "max_tokens", "ok": False, "error": "끊김"},  # Claude API 끊김
        {**base, "effort": "low", "target": 1000},  # 응답 글자 수가 없는 줄
        {**base, "effort": "low"},  # 옛 줄
    ]
    path = usage.log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    s = usage.summary(30)
    eff = {b["effort"]: b for b in s["by_effort"]}
    assert eff["high"]["len_ratio"] == pytest.approx(1.1) and eff["high"]["len_calls"] == 2
    assert (eff["high"]["cut"], eff["high"]["discarded"]) == (2, 1)
    assert eff["low"]["len_ratio"] is None and eff["low"]["cut"] == 0
    assert s["total"]["cut"] == 2
