"""자동 집필 (canon/autorun.py) 테스트. mock LLM 과 mock 배치로 돈다."""
import contextlib
import io
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
    assert autorun.review_reasons(p, d, None, autorun.Policy()) == []
    issue = ConsistencyIssue(type="말투", description="x", source_quote="a", current_quote="b")
    report = ConsistencyReport(episode=1, issues=[issue])
    assert "검수" in autorun.review_reasons(p, d, report, autorun.Policy())[0]
    assert autorun.review_reasons(p, d, report, autorun.Policy(max_issues=1)) == []
    big = mock.MockLLM().json("", "", StateDelta, {"episode": 1})
    assert any("관계가 크게" in r for r in autorun.review_reasons(p, big, None, autorun.Policy(max_shift=0.1)))
    assert autorun.review_reasons(p, big, None, autorun.Policy(max_shift=0)) == []
    d.character_updates = [big.character_updates[0].model_copy(update={"character_id": "ghost"})]
    assert "설정에 없는 인물" in autorun.review_reasons(p, d, None, autorun.Policy(max_shift=0))[0]


def test_full_run_with_review_stop(demo):
    run = autorun.start(demo, 4, True, autorun.Policy(), foreground=True)
    # mock 은 2화 검수에서 말투 문제를 낸다
    assert run.status == "review" and run.ep == 2 and run.pending is not None
    p = store.load(demo)
    assert p.episode(1).status == "finalized" and p.episode(1).auto
    assert p.episode(2).status == "written" and p.episode(2).issues
    with pytest.raises(ValueError):
        autorun.resume(demo, foreground=True)  # 검토 대기 중인데 아무것도 고르지 않았다
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
    autorun.start(demo, 3, False, autorun.Policy(), foreground=True)
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
    run = autorun.start(demo, 1, False, autorun.Policy(), foreground=True)
    assert run.status == "paused" and "초안" in run.reasons[0]
    run = autorun.start(demo, 1, False, autorun.Policy(confirm_plots=True), foreground=True)
    assert run.status == "done"


def test_review_every_and_rewrite(demo):
    run = autorun.start(demo, 6, False, autorun.Policy(max_issues=5, review_every=1), foreground=True)
    assert run.status == "paused" and run.applied == [1]
    run = autorun.start(demo, 3, False, autorun.Policy(), foreground=True)
    assert run.status == "review" and run.ep == 2
    run = autorun.resume(demo, rewrite=True, foreground=True)
    assert run.status == "review" and run.ep == 2  # mock 은 다시 써도 같은 문제를 낸다
    assert any("다시 씁니다" in e.message for e in run.log)


def test_pause_keeps_batch_and_resume_reattaches(demo, monkeypatch):
    monkeypatch.setenv("CANON_MOCK_BATCH_POLLS", "100000")
    autorun.start(demo, 1, True, autorun.Policy())
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
    autorun.start(demo, 1, True, autorun.Policy())
    wait_until(lambda: autorun.get_run(demo).batches)
    name = list(autorun.get_run(demo).batches.values())[0]
    autorun.request(demo, "stop")
    wait_until(idle(demo))
    run = autorun.load_run(demo)
    assert run.status == "stopped" and run.batches == {} and mock.BATCHES[name]["cancelled"]


def test_server_restart_resumes(demo, monkeypatch):
    monkeypatch.setenv("CANON_MOCK_BATCH_POLLS", "100000")
    autorun.start(demo, 1, True, autorun.Policy())
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
    off = autorun.estimate(p, 6, False, autorun.Policy())
    on = autorun.estimate(p, 6, True, autorun.Policy())
    assert off["episodes"] == 6 and off["calls"] == {"write": 6, "check": 6, "state": 6}
    assert off["cost"] > 0 and on["cost"] == pytest.approx(off["cost"] / 2, abs=0.01)
    assert off["batch_rounds"] == 0 and on["batch_rounds"] == 12
    no_check = autorun.estimate(p, 6, False, autorun.Policy(check=False))
    assert no_check["calls"]["check"] == 0 and no_check["cost"] < off["cost"]
    monkeypatch.setenv("CANON_LLM_WRITE", "local")
    assert autorun.estimate(p, 6, True, autorun.Policy())["batch_rounds"] == 6  # 본문은 로컬이라 배치 없음


def test_web_api(demo, monkeypatch):
    from fastapi.testclient import TestClient

    from canon import web

    c = TestClient(web.app)
    assert c.get("/api/projects/demo/auto").json()["run"] is None
    est = c.post("/api/projects/demo/auto/estimate", json={"target": 3, "batch": True}).json()
    assert est["episodes"] == 3 and est["batch_rounds"] == 6

    monkeypatch.setenv("CANON_MOCK_BATCH_POLLS", "100000")
    r = c.post("/api/projects/demo/auto/start", json={"target": 3, "batch": True}).json()
    assert r["active"] and r["run"]["status"] == "running"
    assert c.post("/api/projects/demo/auto/start", json={"target": 3}).status_code == 400  # 이미 돈다
    assert c.post("/api/projects/demo/jobs", json={"kind": "write", "ep": 1}).status_code == 400
    wait_until(lambda: autorun.get_run("demo").batches)

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
