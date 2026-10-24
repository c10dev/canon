"""자동 집필 (canon/autorun.py) 테스트. mock LLM 과 mock 배치로 돈다."""
import contextlib
import io
import json
import os
import tempfile
import time

import pytest

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())  # 다른 테스트 파일보다 먼저 store 를 불러와도 저장소를 더럽히지 않게

from canon import autorun, jobs, mock, store  # noqa: E402
from canon.cli import main  # noqa: E402
from canon.schema import ConsistencyIssue, ConsistencyReport, StateDelta  # noqa: E402


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("CANON_BATCH_POLL", "0.01")
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(autorun, "_controls", {})
    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
        main(["arc", "demo", "-y"])
        main(["plot", "demo"])
        main(["confirm", "demo", "all"])
    yield "demo"
    jobs.draining.clear()


def Policy(**kw):
    """1~3화에서 멈추는 기본 정책은 따로 시험하고, 나머지 시험은 꺼 둔 채로 돈다."""
    return autorun.Policy(**{"hand_pick_opening": False, **kw})


def wait_until(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("시간 안에 끝나지 않았습니다")


def idle(name):
    return lambda: not autorun.active(name)


def test_policy_reasons(demo):
    p = store.load(demo)
    d = StateDelta(episode=1, summary="s")
    assert autorun.review_reasons(p, d, None, Policy()) == []
    issue = ConsistencyIssue(type="말투", description="x", source_quote="a", current_quote="b")
    report = ConsistencyReport(episode=1, issues=[issue])
    assert "검수" in autorun.review_reasons(p, d, report, Policy())[0]
    assert autorun.review_reasons(p, d, report, Policy(max_issues=1)) == []
    big = mock.MockLLM().json("", "", StateDelta, {"episode": 1})
    assert any("관계가 크게" in r for r in autorun.review_reasons(p, big, None, Policy(max_shift=0.1)))
    assert autorun.review_reasons(p, big, None, Policy(max_shift=0)) == []
    d.character_updates = [big.character_updates[0].model_copy(update={"character_id": "ghost"})]
    assert "설정에 없는 인물" in autorun.review_reasons(p, d, None, Policy(max_shift=0))[0]


def test_full_run_with_review_stop(demo):
    run = autorun.start(demo, 4, True, Policy(), foreground=True)
    # mock 은 2화 검수에서 말투 문제를 낸다
    assert run.status == "review" and run.ep == 2 and run.pending is not None
    p = store.load(demo)
    assert p.episode(1).status == "finalized" and p.episode(1).auto
    assert p.episode(2).status == "written" and p.episode(2).issues
    with pytest.raises(ValueError):
        autorun.resume(demo, foreground=True)  # 검토 대기 중인데 아무것도 고르지 않았다
    assert run.pending_text == p.episode(2).text
    # 변경안을 만든 뒤 본문을 고쳤으면 옛 변경안을 그대로 반영하지 않는다
    p.episode(2).text = "작가가 고친 2화 본문"
    store.save(demo, p)
    with pytest.raises(ValueError, match="본문을 고쳤어요"):
        autorun.resume(demo, approve=True, foreground=True)
    p.episode(2).text = run.pending_text
    store.save(demo, p)
    run = autorun.resume(demo, approve=True, foreground=True)
    assert run.status == "done"
    p = store.load(demo)
    assert [e.status for e in p.episodes[:4]] == ["finalized"] * 4
    assert p.episode(5).status == "confirmed"  # 목표 밖은 건드리지 않는다
    assert [e.auto for e in p.episodes[:4]] == [True, False, True, True]  # 2화는 사용자가 승인
    assert {s.episode for s in p.snapshots} >= {0, 1, 2, 3, 4}
    assert any(e.batch for e in run.log)
    assert any("자동으로 반영" in e.message for e in run.log)


def test_user_applies_in_review_screen_then_resume(demo):
    autorun.start(demo, 3, False, Policy(), foreground=True)
    run = autorun.get_run(demo)
    from canon import pipeline

    p = store.load(demo)
    pipeline.apply_delta(p, run.pending)  # 검토 화면에서 반영한 것과 같다
    store.save(demo, p)
    assert autorun.resume(demo, foreground=True).status == "done"


def test_draft_plot_pauses_or_confirms(demo):
    p = store.load(demo)
    p.episode(1).status = "draft"
    store.save(demo, p)
    run = autorun.start(demo, 1, False, Policy(), foreground=True)
    assert run.status == "paused" and "초안" in run.reasons[0]
    run = autorun.start(demo, 1, False, Policy(confirm_plots=True), foreground=True)
    assert run.status == "done"


def test_review_every_and_rewrite(demo):
    run = autorun.start(demo, 6, False, Policy(max_issues=5, review_every=1), foreground=True)
    assert run.status == "paused" and run.applied == [1]
    run = autorun.start(demo, 3, False, Policy(), foreground=True)
    assert run.status == "review" and run.ep == 2
    before = store.load(demo).episode(2).text
    run = autorun.resume(demo, rewrite=True, foreground=True)
    assert run.status == "review" and run.ep == 2  # mock 은 다시 써도 같은 문제를 낸다
    assert store.load(demo).episode(2).versions[-1].text == before  # 지운 본문은 이전 판으로 남는다
    assert any("다시 씁니다" in e.message for e in run.log)


def test_pause_keeps_batch_and_resume_reattaches(demo, monkeypatch):
    monkeypatch.setenv("CANON_MOCK_BATCH_POLLS", "100000")
    autorun.start(demo, 1, True, Policy())
    wait_until(lambda: autorun.get_run(demo).batches)
    name = list(autorun.get_run(demo).batches.values())[0]
    autorun.request(demo, "pause")
    wait_until(idle(demo))
    run = autorun.load_run(demo)
    assert run.status == "paused" and run.batches == {"1:write": name}
    mock.BATCHES[name]["polls"] = 0  # 배치가 끝났다
    count = len(mock.BATCHES)
    monkeypatch.setenv("CANON_MOCK_BATCH_POLLS", "0")
    autorun.resume(demo)
    wait_until(idle(demo))
    assert autorun.load_run(demo).status == "done"
    assert len(mock.BATCHES) == count + 2  # 본문은 기다리던 작업을 받아 오고, 검수와 상태만 새로 보냈다


def test_stop_cancels_batch(demo, monkeypatch):
    monkeypatch.setenv("CANON_MOCK_BATCH_POLLS", "100000")
    autorun.start(demo, 1, True, Policy())
    wait_until(lambda: autorun.get_run(demo).batches)
    name = list(autorun.get_run(demo).batches.values())[0]
    autorun.request(demo, "stop")
    wait_until(idle(demo))
    run = autorun.load_run(demo)
    assert run.status == "stopped" and run.batches == {} and mock.BATCHES[name]["cancelled"]


def test_server_restart_resumes(demo, monkeypatch):
    monkeypatch.setenv("CANON_MOCK_BATCH_POLLS", "100000")
    autorun.start(demo, 1, True, Policy())
    wait_until(lambda: autorun.get_run(demo).batches)
    jobs.draining.set()  # 자동 업데이트가 다시 시작하려 한다
    autorun._controls[demo].wake.set()
    wait_until(idle(demo))
    assert autorun.load_run(demo).status == "running"  # 다시 시작한 서버가 이어 가도록 남겨 둔다
    jobs.draining.clear()
    monkeypatch.setattr(autorun, "_controls", {})  # 새 프로세스
    for b in mock.BATCHES.values():
        b["polls"] = 0
    monkeypatch.setenv("CANON_MOCK_BATCH_POLLS", "0")
    assert autorun.resume_all() == [demo]
    wait_until(idle(demo))
    assert autorun.load_run(demo).status == "done"


def test_estimate(demo, monkeypatch):
    p = store.load(demo)
    monkeypatch.setenv("CANON_LLM", "gemini")
    off = autorun.estimate(p, 6, False, Policy())
    on = autorun.estimate(p, 6, True, Policy())
    assert off["episodes"] == 6 and off["calls"] == {"write": 6, "check": 6, "state": 6}
    assert off["cost"] > 0 and on["cost"] == pytest.approx(off["cost"] / 2, abs=0.01)
    assert off["batch_rounds"] == 0 and on["batch_rounds"] == 12
    no_check = autorun.estimate(p, 6, False, Policy(check=False))
    assert no_check["calls"]["check"] == 0 and no_check["cost"] < off["cost"]
    monkeypatch.setenv("CANON_LLM_WRITE", "local")
    assert autorun.estimate(p, 6, True, Policy())["batch_rounds"] == 6  # 본문은 로컬이라 배치 없음


def test_web_api(demo, monkeypatch):
    from fastapi.testclient import TestClient

    from canon import web

    c = TestClient(web.app)
    assert c.get("/api/projects/demo/auto").json()["run"] is None
    est = c.post("/api/projects/demo/auto/estimate", json={"target": 3, "batch": True}).json()
    assert est["episodes"] == 3 and est["batch_rounds"] == 6

    monkeypatch.setenv("CANON_MOCK_BATCH_POLLS", "100000")
    r = c.post("/api/projects/demo/auto/start", json={"target": 3, "batch": True, "policy": {"hand_pick_opening": False}}).json()
    assert r["active"] and r["run"]["status"] == "running"
    assert c.post("/api/projects/demo/auto/start", json={"target": 3}).status_code == 400  # 이미 돈다
    assert c.post("/api/projects/demo/jobs", json={"kind": "write", "ep": 1}).status_code == 400
    wait_until(lambda: autorun.get_run("demo").batches)
    # 자동 집필이 도는 동안 본문 직접 저장은 막는다 (작업이 쓰는 본문과 서로 덮지 않게)
    assert c.put("/api/projects/demo/episodes/1/text", json={"text": "손으로 쓴 본문"}).status_code == 400

    # 화면이 오래된 작품 전체를 저장해도 자동 집필이 쓴 진행 상태와 본문은 지킨다
    stale = c.get("/api/projects/demo").json()
    stale["meta"]["title"] = "새 제목"
    stale["facts"] = ["화면에서 덮으려던 사실"]
    monkeypatch.setenv("CANON_MOCK_BATCH_POLLS", "0")
    for b in mock.BATCHES.values():
        b["polls"] = 0
    wait_until(lambda: store.load("demo").episode(1).status == "finalized")
    c.put("/api/projects/demo", json=stale)
    p = store.load("demo")
    assert p.meta.title == "새 제목" and p.episode(1).status == "finalized" and "화면에서 덮으려던 사실" not in p.facts

    c.put("/api/projects/demo/auto/batch", json={"batch": False})
    wait_until(idle("demo"))
    r = c.get("/api/projects/demo/auto").json()["run"]
    assert r["status"] == "review" and r["ep"] == 2 and r["pending"] and not r["batch"]

    # 검토 화면에서 반영하면 pending 은 더 보이지 않고, 이어 가면 끝난다
    d = r["pending"]
    c.post("/api/projects/demo/episodes/2/apply", json=d)
    assert c.get("/api/projects/demo/auto").json()["run"]["pending"] is None
    c.post("/api/projects/demo/auto/resume", json={})
    wait_until(idle("demo"))
    assert c.get("/api/projects/demo/auto").json()["run"]["status"] == "done"

    p = c.post("/api/projects/demo/revert/2").json()
    assert [e["status"] for e in p["episodes"][:3]] == ["finalized", "finalized", "written"]
    assert not p["episodes"][2]["auto"]
    assert c.post("/api/projects/demo/auto/pause").status_code == 200


def test_batch_schema_mismatch_is_repaired(demo):
    mock.BAD_JSON[:] = ["StateDelta"]  # 실제 배치에서 본 것처럼 summary 가 빠지고 항목이 문자열
    count = len(mock.BATCHES)
    run = autorun.start(demo, 1, True, Policy(), foreground=True)
    assert run.status == "done" and run.applied == [1]
    assert len(mock.BATCHES) == count + 4  # 본문, 검수, 상태, 상태 고쳐 받기
    assert any(e.level == "warn" and "형식과 맞지 않아" in e.message for e in run.log)
    assert not run.batches


def test_batch_schema_mismatch_twice_pauses_and_keeps_text(demo):
    mock.BAD_JSON[:] = ["StateDelta", "StateDelta"]
    run = autorun.start(demo, 2, True, Policy(), foreground=True)
    assert run.status == "paused" and run.ep == 1 and "형식에 맞지 않아" in run.log[-1].message
    assert "StateDelta" in run.reasons[0] and "본문은 그대로" in run.reasons[1]
    p = store.load(demo)
    text = p.episode(1).text
    assert p.episode(1).status == "written" and text
    run = autorun.resume(demo, foreground=True)  # 본문은 다시 쓰지 않고 상태 변경안만 새로 받는다
    assert run.status == "review" and run.ep == 2
    assert store.load(demo).episode(1).text == text and store.load(demo).episode(1).status == "finalized"


def test_batch_fix_slot_reattaches_after_restart():
    from canon.llm import BatchLLM, SchemaMismatch

    m = mock.MockLLM()
    good = m.batch_submit("", "", StateDelta, "t", hint={"episode": 3})
    names = {"3:state:fix": good}  # 고쳐 받기를 기다리던 중에 서버가 다시 시작했다
    count = len(mock.BATCHES)
    b = BatchLLM(m, "3:state", names, lambda: None, lambda s: "", interval=0)
    assert b.json("", "", StateDelta, {"episode": 3}).episode == 3
    assert len(mock.BATCHES) == count and names == {} and b.last_attempts == 2

    mock.BAD_JSON[:] = ["StateDelta", "StateDelta"]
    with pytest.raises(SchemaMismatch) as e:
        BatchLLM(m, "4:state", names, lambda: None, lambda s: "", interval=0).json("", "", StateDelta, {"episode": 4})
    assert "summary" in e.value.brief and names == {}


def test_gemini_json_retries_with_error():
    from canon.llm import GeminiLLM, SchemaMismatch

    good = StateDelta(episode=1, summary="s").model_dump_json()
    bad = '{"episode": 1, "character_updates": ["cecilia: emotional_state=분노"]}'
    from types import SimpleNamespace

    llm = object.__new__(GeminiLLM)
    asks = []
    replies = [bad, good]

    def generate(model, contents, config):
        asks.append(contents)
        return SimpleNamespace(text=replies.pop(0), usage_metadata=None, candidates=[])
    llm.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    llm.model = "gemini-4-argon"
    assert llm.json("", "원래 요청", StateDelta).summary == "s" and llm.last_attempts == 2
    assert asks[0] == "원래 요청" and asks[1].startswith("원래 요청") and "틀린 곳" in asks[1] and bad in asks[1]
    replies[:] = [bad, bad]
    with pytest.raises(SchemaMismatch):
        llm.json("", "원래 요청", StateDelta)


def test_opening_episodes_stop_for_hand_pick(demo):
    """기본 정책은 1~3화를 쓰고 검수한 뒤 반영하기 전에 멈춘다. 이어 가면 4화부터는 정책대로 반영한다."""
    run = autorun.start(demo, 4, False, autorun.Policy(max_issues=5), foreground=True)
    assert run.status == "review" and run.ep == 1 and "초반" in run.reasons[0]
    assert store.load(demo).episode(1).status == "written"
    for n in (2, 3):
        run = autorun.resume(demo, approve=True, foreground=True)
        assert run.status == "review" and run.ep == n
    run = autorun.resume(demo, approve=True, foreground=True)
    assert run.status == "done"
    p = store.load(demo)
    assert [e.auto for e in p.episodes[:4]] == [False, False, False, True]


def test_stale_save_keeps_characters_added_by_apply(demo):
    """승인한 변경안이 더한 인물은 그 반영 전에 읽은 화면이 작품 전체를 저장해도 남긴다."""
    from fastapi.testclient import TestClient

    from canon import web

    c = TestClient(web.app)
    c.put("/api/projects/demo/episodes/1/text", json={"text": "1화 본문"})
    stale = c.get("/api/projects/demo").json()
    stale["meta"]["title"] = "새 제목"
    delta = {"episode": 1, "summary": "1화 요약", "new_characters": [{"id": "courier", "name": "배달꾼", "role": "조연"}]}
    assert c.post("/api/projects/demo/episodes/1/apply", json=delta).status_code == 200
    r = c.put("/api/projects/demo", json=stale)
    p = store.load("demo")
    assert p.meta.title == "새 제목"
    assert "courier" in {x.id for x in p.characters}
    # 화면에 무엇을 서버 것으로 두었는지 알린다
    from urllib.parse import unquote
    assert {"field": "character", "name": "배달꾼"} in json.loads(unquote(r.headers["X-Canon-Kept"]))
    # 오래되지 않은 화면의 저장은 아무것도 버리지 않는다
    assert "X-Canon-Kept" not in c.put("/api/projects/demo", json=c.get("/api/projects/demo").json()).headers
    assert p.episode(1).status == "finalized"
