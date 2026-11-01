"""자동 집필 (canon/autorun.py) 테스트. mock LLM 과 mock 배치로 돈다."""
import contextlib
import io
import json
import os
import tempfile
import time

import pytest

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())  # 다른 테스트 파일보다 먼저 store 를 불러와도 저장소를 더럽히지 않게

from canon import autorun, jobs, mock, pipeline, store  # noqa: E402
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
    assert any("다시 써요" in e.message for e in run.log)


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
    events = len(store.load(demo).episode(1).plot.events)  # 검수 때 함께 뽑기: 사건마다 본문 장면 뽑기도 배치로 보낸다
    assert len(mock.BATCHES) == count + 2 + events  # 본문은 기다리던 작업을 받아 오고, 검수 · 장면 뽑기와 상태만 새로 보냈다


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
    run = autorun.load_run(demo)
    assert run.status == "done" and run.restarts == 1
    assert any(e.step == "restart" for e in run.log)  # 화면이 다시 시작한 것을 알 수 있게 남긴다


def test_estimate(demo, monkeypatch):
    p = store.load(demo)
    monkeypatch.setenv("CANON_LLM", "gemini")
    events = sum(len(p.episode(n).plot.events) for n in range(1, 7))
    stage = autorun.estimate(p, 6, False, Policy())  # 검수 때 함께 뽑기(기본 켬): 사건마다 검수 호출 하나 더
    assert stage["calls"]["check"] == 6 + events
    p.settings.stage_extract = False
    assert stage["cost"] > autorun.estimate(p, 6, False, Policy())["cost"]
    off = autorun.estimate(p, 6, False, Policy())
    on = autorun.estimate(p, 6, True, Policy())
    assert off["episodes"] == 6 and off["calls"] == {"plan": 0, "write": 6, "check": 6, "state": 6}  # 단편은 스토리보드가 기본으로 꺼짐
    assert off["cost"] > 0 and on["cost"] == pytest.approx(off["cost"] / 2, abs=0.01)
    assert off["batch_rounds"] == 0 and on["batch_rounds"] == 12
    no_check = autorun.estimate(p, 6, False, Policy(check=False))
    assert no_check["calls"]["check"] == 0 and no_check["cost"] < off["cost"]
    monkeypatch.setenv("CANON_LLM_WRITE", "local")
    assert autorun.estimate(p, 6, True, Policy())["batch_rounds"] == 6  # 본문은 로컬이라 배치 없음


def test_serial_estimate_sizes_old_passages_without_search(demo, monkeypatch):
    """장편 추정은 검수의 옛 단락을 찾지 않고(context.recall) 예산 크기로 센다. 찾아서 잰 길이와 거의 같다."""
    from canon import context, prompts

    p = store.load(demo)
    p.meta.form = "serial"
    p.settings.stage_extract = False
    monkeypatch.setitem(context.BUDGET, "check_recall", 400)
    sim = p.model_copy(deep=True)
    for e in sim.episodes:  # 화마다 다른 낱말이 섞인 본문이라야 옛 단락이 찾아진다 (실제 작품처럼)
        m = e.plot.number
        e.text = "\n\n".join(f"{m}화 {k}번째 장면에서 등대 불빛이 바다{k}를 비추고 서윤은 밧줄{m}을 감았다." for k in range(12))
    assert prompts.check_recall(sim, 6)[1]  # 찾아서 넣는 옛 단락이 있다
    searched = [len(prompts.check_prompt(sim, n)) for n in range(1, 7)]
    sized = [len(prompts.check_prompt(sim, n, sized=True)) for n in range(1, 7)]
    assert sized[:context.CHECK_RECENT + 1] == searched[:context.CHECK_RECENT + 1]  # 직전 화 밖의 옛 화가 없으면 똑같다
    assert all(abs(a - b) <= 0.05 * b for a, b in zip(sized, searched))

    def boom(*a, **k):
        raise AssertionError("추정에서 옛 단락을 찾았어요")

    monkeypatch.setattr(context, "recall", boom)
    assert autorun.estimate(p, 6, False, Policy())["calls"]["check"] == 6


def test_web_api(demo, monkeypatch):
    from fastapi.testclient import TestClient

    from canon import web

    c = TestClient(web.app)
    assert c.get("/api/projects/demo/auto").json()["run"] is None
    assert c.put("/api/projects/demo/stage-extract", json={"on": False}).json()["settings"]["stage_extract"] is False
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

    # 앱: 검토 대기 변경안을 검토를 기다리는 결과로 옮기면 상태 승인 화면이 작업 결과처럼 읽는다
    assert c.post("/api/projects/demo/auto/review").status_code == 200
    rec = c.get("/api/projects/demo/pending").json()["results"]["state:2"]
    assert rec["result"] == r["pending"] and rec["base"] == r["pending_text"] and rec["kind"] == "state"

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
    assert c.post("/api/projects/demo/auto/review").status_code == 400  # 검토 대기가 없다


def test_batch_schema_mismatch_is_repaired(demo):
    mock.BAD_JSON[:] = ["StateDelta"]  # 실제 배치에서 본 것처럼 summary 가 빠지고 항목이 문자열
    count = len(mock.BATCHES)
    run = autorun.start(demo, 1, True, Policy(), foreground=True)
    assert run.status == "done" and run.applied == [1]
    events = len(store.load(demo).episode(1).plot.events)  # 검수 때 함께 뽑기: 사건마다 본문 장면 뽑기
    assert len(mock.BATCHES) == count + 4 + events  # 본문, 검수, 상태, 상태 고쳐 받기, 장면 뽑기
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


def test_revert_removes_characters_added_by_reverted_apply_and_redo_edit(demo):
    """반영 취소는 그 반영이 더한 인물도 되돌린다. 수정 취소한 부분 수정은 다시 넣을 수 있다."""
    from fastapi.testclient import TestClient

    from canon import pipeline, web
    from canon.schema import Selection

    c = TestClient(web.app)
    c.put("/api/projects/demo/episodes/1/text", json={"text": "1화 본문. 바람이 불었다."})
    p = store.load(demo)
    e = pipeline.edit_text(p, 1, Selection(start=0, text="1화 본문."), "1화 고친 본문.")
    pipeline.undo_edit(p, 1, e.id)
    assert p.episode(1).text.startswith("1화 본문.")
    pipeline.redo_edit(p, 1, e.id)
    assert p.episode(1).text.startswith("1화 고친 본문.") and not p.episode(1).edits[-1].undone
    store.save(demo, p)

    delta = {"episode": 1, "summary": "1화 요약", "new_characters": [{"id": "courier", "name": "배달꾼", "role": "조연"}]}
    assert c.post("/api/projects/demo/episodes/1/apply", json=delta).status_code == 200
    assert "courier" in {x["id"] for x in c.get("/api/projects/demo").json()["characters"]}
    p = c.post("/api/projects/demo/revert/0").json()
    assert "courier" not in {x["id"] for x in p["characters"]} and p["episodes"][0]["status"] == "written"


def test_batch_poll_transient_error_keeps_name():
    """배치 조회가 잠깐 실패하면 이름을 버리지 않고 다시 묻는다. 확실히 끝난 배치(BatchGone)만 버린다."""
    from canon import llm

    class Flaky:
        label, model = "x", "m"

        def __init__(self, fails):
            self.fails = fails

        def batch_submit(self, *a, **k):
            return "b1"

        def batch_poll(self, name):
            if self.fails:
                self.fails -= 1
                raise ConnectionError("잠깐 끊김")
            return "결과"

    names = {}
    b = llm.BatchLLM(Flaky(2), "slot", names, lambda: None, lambda s: "")
    assert b.text("s", "p") == "결과" and names == {}
    names = {}
    b = llm.BatchLLM(Flaky(99), "slot", names, lambda: None, lambda s: "")
    with pytest.raises(RuntimeError, match="다시 붙어요"):
        b.text("s", "p")
    assert names == {"slot": "b1"}  # 이어 가면 같은 배치에 다시 붙는다


def test_halt_kind_and_policy_change_while_paused(demo):
    p = store.load(demo)
    p.episode(1).status = "draft"
    store.save(demo, p)
    run = autorun.start(demo, 1, False, Policy(), foreground=True)
    assert run.status == "paused" and run.halt == "plot_draft"
    assert "'초안 플롯도 자동으로 확정하고 쓰기'" in run.reasons[0]  # 정책 칸 이름 그대로
    run = autorun.set_policy(demo, Policy(confirm_plots=True))
    assert run.status == "paused" and autorun.load_run(demo).policy.confirm_plots
    assert any("승인 정책을 바꿨어요" in e.message for e in autorun.load_run(demo).log)
    run = autorun.resume(demo, foreground=True)
    assert run.status == "done" and run.halt == ""
    with pytest.raises(ValueError):
        autorun.set_policy(demo, Policy())  # 끝난 실행은 새로 시작할 때 정한다


def test_user_saves_text_while_writing(demo, monkeypatch):
    real = autorun.pipeline.write_episode

    def write(llm, p, n, **kw):
        q = store.load(demo)  # AI가 쓰는 사이 작가가 본문을 직접 저장했다
        q.episode(n).text, q.episode(n).status = "작가가 쓴 본문", "written"
        store.save(demo, q)
        return real(llm, p, n, **kw)

    monkeypatch.setattr(autorun.pipeline, "write_episode", write)
    run = autorun.start(demo, 1, False, Policy(), foreground=True)
    assert run.status == "paused" and run.halt == "changed"
    assert "직접 저장" in run.reasons[0] and "written" not in run.log[-1].message
    assert store.load(demo).episode(1).text == "작가가 쓴 본문"


def test_revert_updates_run(demo):
    from fastapi.testclient import TestClient

    from canon import web

    run = autorun.start(demo, 3, False, Policy(max_issues=5), foreground=True)
    assert run.status == "done" and run.applied == [1, 2, 3]
    c = TestClient(web.app)
    assert c.post("/api/projects/demo/revert/2").status_code == 200
    run = autorun.load_run(demo)
    assert run.applied == [1, 2] and run.status == "paused" and run.halt == "reverted"  # 2화 반영 직후로 = 3화부터 취소
    assert run.log[-1].message == "3화부터 반영을 취소했어요"
    # 멈춘 실행의 정책은 이어 가기 전에 바꿀 수 있다
    r = c.put("/api/projects/demo/auto/policy", json={"check": False, "hand_pick_opening": False}).json()
    assert r["run"]["status"] == "paused" and r["run"]["policy"]["check"] is False


def test_save_keeps_plot_of_written_episode(demo):
    """본문이 있는 화의 플롯은 화면이 보낸 작품 전체 저장에서도 서버 것을 둔다. 줄기 표시와 아직 안 쓴 화의 플롯은 받는다."""
    from urllib.parse import unquote

    from fastapi.testclient import TestClient

    from canon import web
    from canon.schema import Storyline

    c = TestClient(web.app)
    p = store.load(demo)
    p.storylines.append(Storyline(id="past", kind="과거 회상", title="등대지기의 과거", branch_ep=1, join_ep=2))
    store.save(demo, p)
    c.put(f"/api/projects/{demo}/episodes/1/text", json={"text": "1화 본문"})
    before = store.load(demo).episode(1).plot
    sent = c.get(f"/api/projects/{demo}").json()
    sent["episodes"][0]["plot"]["title"] = "바뀐 제목"
    sent["episodes"][0]["plot"]["storyline"] = "past"
    sent["episodes"][1]["plot"]["title"] = "2화 새 제목"
    r = c.put(f"/api/projects/{demo}", json=sent)
    assert r.status_code == 200, r.text
    p = store.load(demo)
    assert p.episode(1).plot.title == before.title and p.episode(1).plot.storyline == "past"
    assert p.episode(2).plot.title == "2화 새 제목"
    assert json.loads(unquote(r.headers["X-Canon-Kept"])) == [{"field": "plot", "ep": 1, "why": "locked"}]
    # 지운 인물은 본문이 있는 화의 등장 인물에서도 뺀다
    old = p.model_copy(deep=True)
    gone = p.episode(1).plot.characters[0]
    p.characters = [x for x in p.characters if x.id != gone]
    p.episode(1).plot.characters.remove(gone)
    assert pipeline.keep_locked_plots(old, p) == [] and gone not in p.episode(1).plot.characters
