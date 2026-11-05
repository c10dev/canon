"""작업 끝 알림의 계산(static/notify.js notifyPrefs · notifyGroup · notifyEvent · notifyWays · notifyTitle)을 node 로 맞춰 본다. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

FILES = ["app.js", "hub.js", "notify.js", "setup.js"]  # josa 는 setup.js


def job(id, status, kind="write", ep=3, project="demo", **kw):
    return {"id": id, "status": status, "kind": kind, "ep": ep, "project": project, "label": f"{ep}화 본문", "done": 0, "total": 1, **kw}


def event(j, old=None):
    return run_js(FILES, "notifyEvent(data.j, data.old || undefined)", {"j": j, "old": old})


@needs_node
def test_prefs_fill_defaults_and_survive_bad_values():
    got = run_js(FILES, "[notifyPrefs(null), notifyPrefs('{나쁜'), notifyPrefs('{\"on\":true,\"kinds\":{\"other\":true,\"write\":false,\"zzz\":1}}')]", {})
    off, bad, mine = got
    assert off == bad == {"on": False, "kinds": {"write": True, "rewrite": True, "check": True, "state": True, "auto": True, "other": False}}
    assert mine["on"] is True and mine["kinds"]["other"] is True and mine["kinds"]["write"] is False and "zzz" not in mine["kinds"]


@needs_node
def test_groups():
    got = run_js(FILES, "data.js.map(notifyGroup)", {"js": [
        job("a", "done"),
        job("b", "done", result={"candidate": True}),
        job("c", "error", label="3화 서술 다듬기"),
        job("d", "done", kind="check"), job("e", "done", kind="fixes"), job("f", "done", kind="state"),
        job("g", "running", kind="auto", ep=None), job("h", "done", kind="plots", ep=None),
    ]})
    assert got == ["write", "rewrite", "rewrite", "check", "check", "state", "auto", "other"]


@needs_node
def test_events_when_job_ends():
    # 본문 쓰기가 끝났다: 결과 화면 링크와 함께
    ev = event(job("a", "done"), job("a", "running"))
    assert ev["group"] == "write" and ev["body"] == "3화 본문을 다 썼어요." and ev["href"] == "#/p/demo/write/3" and not ev["err"]
    # 처음 본 작업이 이미 끝나 있어도(폴링 사이에 시작해 끝남) 알린다
    assert event(job("a", "done"))["body"] == "3화 본문을 다 썼어요."
    # 다시 생성
    assert event(job("b", "done", label="3화 새 판", result={"candidate": True}), job("b", "running"))["body"] == "3화 새 판이 왔어요. 비교하고 골라 주세요."
    assert event(job("b", "done", label="3화 서술 다듬기", result={"candidate": True}))["body"].startswith("3화 다듬은 판이 왔어요")
    # 실패
    ev = event(job("c", "error", error="연결이 끊겼어요"), job("c", "running"))
    assert ev["err"] and ev["body"] == "3화 본문을 끝내지 못했어요: 연결이 끊겼어요"
    # 상태 변경안은 화면 말풍선 글을 쓴다
    assert event(job("s", "done", kind="state", label="3화 상태 변경안"))["body"] == "3화 상태 변경안이 도착했어요."
    # 이미 끝난 것으로 본 작업 · 도는 작업 · 멈춘 작업은 알리지 않는다
    assert event(job("a", "done"), job("a", "done")) is None
    assert event(job("a", "running"), job("a", "running")) is None
    assert event(job("a", "cancelled"), job("a", "running")) is None
    # 플레이 화면이 따로 보이는 작업은 알리지 않는다
    assert event(job("p", "done", kind="play_turn")) is None


@needs_node
def test_autorun_episode_and_halt():
    run = job("u", "running", kind="auto", ep=None, label="자동 집필 (6화까지)", step_ep=2)
    ev = event(run, {**run, "step_ep": 1})
    assert ev["group"] == "auto" and ev["body"] == "자동 집필이 2화를 반영했어요." and ev["toast"] and ev["href"] == "#/p/demo/auto"
    assert ev["tag"] == "u:2"
    # 처음 본 실행이나 바뀌지 않은 화는 알리지 않는다
    assert event(run) is None and event(run, run) is None
    # 검토가 필요해 멈췄다: 화면 말풍선과 같은 글
    halt = {**run, "status": "done", "note": "2화는 검토가 필요해 멈췄어요", "result": {"status": "review"}}
    assert event(halt, run)["body"] == "자동 집필 · 검토가 필요해요: 2화는 검토가 필요해 멈췄어요"
    # 마지막 화 반영과 끝이 한 번에 보이면 끝 알림 하나
    last = {**run, "status": "done", "step_ep": 3, "note": "3화까지 모두 반영했어요", "result": {"status": "done"}}
    assert event(last, run)["body"] == "자동 집필: 3화까지 모두 반영했어요"


@needs_node
def test_ways():
    got = run_js(FILES, """(() => {
      const on = notifyPrefs({ on: true });
      const ev = { group: 'write', toast: false };
      const step = { group: 'auto', toast: true };
      const hidden = { visible: false, permission: 'granted' };
      return {
        off: notifyWays(ev, notifyPrefs({}), hidden),
        kindOff: notifyWays({ group: 'other' }, on, hidden),
        none: notifyWays(null, on, hidden),
        hidden: notifyWays(ev, on, hidden),
        denied: notifyWays(ev, on, { visible: false, permission: 'denied' }),
        insecure: notifyWays(ev, on, { visible: false, permission: 'unsupported' }),
        visible: notifyWays(ev, on, { visible: true, permission: 'granted' }),
        stepVisible: notifyWays(step, on, { visible: true, permission: 'granted' }),
        titles: [notifyTitle('3화 · 등대', 0), notifyTitle('3화 · 등대', 2)],
      };
    })()""", {})
    assert got["off"] == ["title"]  # 알림을 꺼 두어도 탭 제목에는 끝난 수를 붙인다
    assert got["kindOff"] == got["none"] == []
    assert got["hidden"] == ["system", "title"]
    assert got["denied"] == got["insecure"] == ["title"]
    assert got["visible"] == []  # 보고 있으면 화면 말풍선이 이미 알린다
    assert got["stepVisible"] == ["toast"]  # 자동 집필 화별 반영은 말풍선이 따로 없다
    assert got["titles"] == ["3화 · 등대", "(2) 3화 · 등대"]
