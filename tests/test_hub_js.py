"""알림 버튼 · 창의 상태 계산(static/hub.js hubState · hubAgo)을 node 로 맞춰 본다. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

FILES = ["app.js", "hub.js"]


def state(**kw):
    base = {"jobs": [], "pending": {"name": "demo", "results": {}, "failures": {}}, "notes": [], "offline": False,
            "seenAt": 0, "seenJobs": [], "name": "demo"}
    expr = """(() => { const s = hubState(data);
      return { face: s.face, label: s.label, aria: s.aria, badge: s.badge, red: s.red, unseen: s.unseen,
               attention: s.attention.map((a) => [a.type, a.label || (a.job && a.job.id) || (a.fail && a.fail.key) || '']),
               running: s.running.map((j) => j.id), finished: s.finished.map((j) => j.id),
               recent: s.recent.length, older: s.older.length }; })()"""
    return run_js(FILES, expr, {**base, **kw})


def job(id, status, kind="write", ep=3, project="demo", **kw):
    return {"id": id, "status": status, "kind": kind, "ep": ep, "project": project, "label": f"{ep}화 본문", "done": 0, "total": 1, **kw}


@needs_node
def test_hub_button_faces():
    # 보일 것이 없으면 버튼을 그리지 않는다
    assert state()["face"] == "none"

    # 진행 중: 수와 함께, 실패가 같이 있으면 빨간 배지
    s = state(jobs=[job("a", "running"), job("b", "running", ep=4), job("c", "error", ep=5)])
    assert (s["face"], s["label"], s["badge"], s["red"]) == ("running", "AI 2", 1, True)
    assert s["aria"] == "알림: AI 작업 2개 진행 중, 확인할 것 1개"

    # 도는 작업 없이 실패만: 확인 n
    s = state(jobs=[job("c", "error")])
    assert (s["face"], s["label"], s["badge"]) == ("attention", "확인 1", 0)

    # 검토를 기다리는 결과만: 주황 '결과 n', 이름은 그 결과가 보이는 화면을 따른다
    s = state(pending={"name": "demo", "results": {"state:4": {"key": "state:4", "kind": "state", "ep": 4}}, "failures": {}})
    assert (s["face"], s["label"], s["red"]) == ("result", "결과 1", False)
    assert s["attention"] == [["result", "4화 상태 변경안"]]

    # 다른 작품의 pending 은 세지 않는다
    s = state(pending={"name": "other", "results": {"state:4": {"key": "state:4", "kind": "state", "ep": 4}}, "failures": {}})
    assert s["face"] == "none"

    # 끝난 작업: 창에서 보기 전까지 '끝남', 본 뒤에는 버튼이 사라진다
    s = state(jobs=[job("d", "done"), job("e", "cancelled", ep=6)])
    assert (s["face"], s["label"], s["finished"]) == ("done", "끝남 2", ["d", "e"])
    assert state(jobs=[job("d", "done")], seenJobs=["d"])["face"] == "none"

    # 새 알림만: 창을 연 뒤의 알림만 센다
    notes = [{"at": 2000, "msg": "저장했어요", "err": False}, {"at": 1000, "msg": "적용했어요", "err": False}]
    s = state(notes=notes, seenAt=1500)
    assert (s["face"], s["unseen"]) == ("note", 1)
    assert state(notes=notes, seenAt=3000)["face"] == "none"

    # 서버 연결이 끊기면 다른 무엇보다 먼저 알린다
    assert state(offline=True, jobs=[job("a", "running")])["face"] == "offline"


@needs_node
def test_hub_attention_order_and_dedupe():
    auto = job("z", "done", kind="auto", ep=None, result={"status": "review"}, note="3화에서 멈춤")
    paused_err = job("y", "done", kind="auto", ep=None, result={"status": "error"})
    s = state(
        jobs=[job("c", "error", kind="state", ep=5), auto],
        pending={"name": "demo", "results": {"arc:": {"key": "arc:", "kind": "arc", "ep": None}, "x:1": {"key": "x:1", "kind": "write", "ep": 1}},
                 "failures": {"state:5": {"key": "state:5", "kind": "state", "ep": 5, "label": "5화 상태", "error": "형식"},
                              "check:2": {"key": "check:2", "kind": "check", "ep": 2, "label": "2화 검수", "error": "키 없음"}}},
    )
    # 순서: 실패한 작업 → 사람을 기다리는 자동 집필 → 지난 시도 실패 → 검토 대기 결과.
    # 목록에 실패로 남은 작업(state:5)은 지난 시도 실패로 겹치지 않고, 이름이 없는 결과 종류(write)는 뺀다
    assert s["attention"] == [["job", "c"], ["auto", "z"], ["fail", "check:2"], ["result", "기승전결 구조 제안"]]
    # 검토 대기 자동 집필은 끝난 작업으로 접히지 않는다
    assert s["finished"] == []
    # 오류로 멈춘 자동 집필은 빨강
    assert state(jobs=[paused_err])["red"] is True
    assert state(jobs=[auto])["red"] is False


@needs_node
def test_hub_recent_notes_and_ago():
    notes = [{"at": i, "msg": f"알림 {i}", "err": False} for i in range(8, 0, -1)]
    s = state(notes=notes)
    assert (s["recent"], s["older"]) == (5, 3)
    got = run_js(FILES, "[0, 59e3, 60e3, 3599e3, 3600e3, 86399e3].map((d) => hubAgo(1e9, 1e9 + d))", {})
    assert got == ["방금", "방금", "1분 전", "59분 전", "1시간 전", "23시간 전"]
