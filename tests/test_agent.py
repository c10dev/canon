"""대화 에이전트 테스트 (mock LLM). 실행: python -m pytest tests"""
from .test_arc_chat import _three_arcs
from .test_plot_chat import _project
from .test_web import _wait, client  # noqa: F401  (pytest fixture)


def _session(client, name="lh", **kw):
    r = client.post(f"/api/projects/{name}/sessions", json={"topic": "plot", **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _say(client, sid, message, name="lh", **kw):
    r = client.post(f"/api/projects/{name}/sessions/{sid}/turns", json={"message": message, **kw})
    assert r.status_code == 200, r.text
    assert _wait(client, r.json()["id"])["status"] == "done"
    return _turn(client, sid, name)


def _turn(client, sid, name="lh", t=-1):
    out = client.get(f"/api/projects/{name}/sessions?topic=plot").json()
    s = next(x for x in out["sessions"] if x["id"] == sid)
    return s["turns"][t]


def _ep(client, n, name="lh"):
    return client.get(f"/api/projects/{name}").json()["episodes"][n - 1]


def test_draft_episode_is_written_at_once_and_undone(client):
    before = _project(client)
    sid = _session(client)
    t = _say(client, sid, "3화 전개가 너무 빨라")
    assert [s["kind"] for s in t["steps"]] == ["read", "write"] and t["end"] == "done"
    assert t["steps"][0]["result"] == ""  # 끝난 턴은 단계 결과를 지운다
    assert [i["key"] for i in t["writes"][0]["items"]] == ["3"]
    assert _ep(client, 3)["plot"]["summary"].endswith("(천천히)")

    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={}).json()
    assert r["restored"] == ["3화 플롯"] and r["kept"] == []
    assert r["project"]["episodes"][2]["plot"] == before["episodes"][2]["plot"]
    assert _turn(client, sid)["writes"][0]["items"][0]["state"] == "reverted"
    assert client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={}).status_code == 400  # 되돌릴 것이 없다


def test_confirmed_episode_asks_and_approval_continues(client):
    _project(client)
    client.post("/api/projects/lh/episodes/3/confirm")
    plot = _ep(client, 3)["plot"]
    sid = _session(client)
    t = _say(client, sid, "3화 전개가 너무 빨라")
    assert t["end"] == "wait" and t["approval"]["keys"] == ["3"] and t["approval"]["kinds"] == ["confirmed"]
    assert t["steps"][-1]["kind"] == "wait" and _ep(client, 3)["plot"] == plot  # 묻는 동안은 그대로

    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True, "remember": True})
    assert r.status_code == 200, r.text
    assert r.json()["project"]["episodes"][2]["status"] == "draft"  # 확정한 화를 바꾸면 초안으로 돌아간다
    assert _wait(client, r.json()["job"]["id"])["status"] == "done"
    t = _turn(client, sid)
    assert t["end"] == "done" and t["approval"]["state"] == "approved" and t["reply"] == "작가의 답대로 마쳤어요."
    s = client.get("/api/projects/lh/sessions").json()["sessions"][0]
    assert s["auto_kinds"] == ["confirmed"]  # 이 세션에서는 확정한 화도 묻지 않는다


def test_denied_approval_writes_nothing(client):
    _project(client)
    client.post("/api/projects/lh/episodes/3/confirm")
    plot = _ep(client, 3)["plot"]
    sid = _session(client)
    _say(client, sid, "3화 전개가 너무 빨라")
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": False}).json()
    _wait(client, r["job"]["id"])
    t = _turn(client, sid)
    assert t["approval"]["state"] == "denied" and t["writes"] == [] and t["end"] == "done"
    assert _ep(client, 3)["plot"] == plot and _ep(client, 3)["status"] == "confirmed"


def test_written_episode_is_blocked(client):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    client.post("/api/projects/lh/episodes/1/write")
    plot = _ep(client, 1)["plot"]
    sid = _session(client)
    t = _say(client, sid, "1화 바꿔 줘")
    block = [s for s in t["steps"] if s["kind"] == "block"]
    assert block and "본문이 있음" in block[0]["why"] and t["writes"] == []
    assert _ep(client, 1)["plot"] == plot


def test_modes(client):
    _project(client)
    client.post("/api/projects/lh/episodes/4/confirm")
    sid = _session(client)
    client.patch(f"/api/projects/lh/sessions/{sid}", json={"mode": "ask"})
    t = _say(client, sid, "3화 전개가 너무 빨라")
    assert t["end"] == "wait" and t["approval"]["kinds"] == ["draft"]  # 물어보기는 초안도 묻는다

    sid2 = _session(client)
    client.patch(f"/api/projects/lh/sessions/{sid2}", json={"mode": "all"})
    t = _say(client, sid2, "4화 전개가 너무 빨라")
    assert t["end"] == "done" and [i["key"] for i in t["writes"][0]["items"]] == ["4"]  # 모두 자동은 확정한 화도 쓴다
    assert client.patch(f"/api/projects/lh/sessions/{sid2}", json={"mode": "x"}).status_code == 400


def test_new_turn_while_waiting_drops_the_approval(client):
    _project(client)
    client.post("/api/projects/lh/episodes/3/confirm")
    sid = _session(client)
    _say(client, sid, "3화 전개가 너무 빨라")
    _say(client, sid, "괜찮아, 그냥 둬?")
    first = _turn(client, sid, t=0)
    assert first["approval"]["state"] == "denied" and first["steps"][-1]["kind"] == "note"


def test_step_cap_and_continue(client):
    _project(client)
    sid = _session(client)
    t = _say(client, sid, "끝없이 읽어 줘")
    assert t["end"] == "cap" and len(t["steps"]) == 8
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/continue")
    assert r.status_code == 200, r.text
    _wait(client, r.json()["id"])
    assert len(_turn(client, sid)["steps"]) == 16


def test_options_mode_asks_without_writing(client):
    _project(client)
    sid = _session(client)
    t = _say(client, sid, "갈등을 어떻게 잡을지 모르겠어", mode="options")
    assert t["end"] == "ask" and len(t["ask"]["options"]) == 3 and t["writes"] == []


def test_undo_keeps_reedited_episode(client):
    _project(client)
    sid = _session(client)
    _say(client, sid, "3화 전개가 너무 빨라")
    p = client.get("/api/projects/lh").json()
    p["episodes"][2]["plot"]["title"] = "작가가 다시 고친 제목"
    client.put("/api/projects/lh", json=p)
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={"write": 0, "key": "3"}).json()
    assert r["restored"] == [] and r["kept"] == ["3화 플롯"] and "다시 고침" in r["reasons"][0]
    item = _turn(client, sid)["writes"][0]["items"][0]
    assert item["state"] == "kept" and "다시 고침" in item["reason"]


def test_screen_save_keeps_sessions_and_legacy_chat_shows(client):
    p = _project(client)  # 대화 세션이 없을 때 받은 작품
    client.post("/api/projects/lh/chat/plot", json={"message": "3화 전개가 너무 빨라"})  # 옛 단발 대화
    sid = _session(client, target="")
    _say(client, sid, "4화 전개가 너무 빨라")
    out = client.get("/api/projects/lh/sessions").json()
    assert out["legacy"] == 2 and out["model"] and out["max_steps"] == 8
    p["meta"]["title"] = "등대 2"
    client.put("/api/projects/lh", json=p)
    out = client.get("/api/projects/lh/sessions").json()
    assert [s["id"] for s in out["sessions"]] == [sid]
    assert out["sessions"][0]["title"] == "4화 전개가 너무 빨라"


def test_stopped_turn_saves_nothing(client, monkeypatch):
    _project(client)
    sid = _session(client)
    monkeypatch.setenv("CANON_MOCK_DELAY", "0.3")
    r = client.post("/api/projects/lh/sessions/{}/turns".format(sid), json={"message": "3화 전개가 너무 빨라"}).json()
    client.post(f"/api/jobs/{r['id']}/stop")
    import time
    time.sleep(0.5)
    monkeypatch.setenv("CANON_MOCK_DELAY", "0")
    t = _turn(client, sid)
    assert t["end"] == "stopped" and t["writes"] == []
    assert not _ep(client, 3)["plot"]["summary"].endswith("(천천히)")
    assert client.post(f"/api/projects/lh/sessions/{sid}/turns/0/continue").status_code == 200  # 멈춘 턴은 이어 할 수 있다


def test_next_arc_goes_to_draft_without_changing_the_project(client):
    from canon import store

    p, a1, a2, a3 = _three_arcs()
    store.save("sr", p)
    arcs = [a.model_dump() for a in store.load("sr").story_arcs]
    sid = _session(client, name="sr", target="next")
    t = _say(client, sid, "15화짜리로 짜 줘", name="sr")
    keys = [i["key"] for w in t["writes"] for i in w["items"]]
    assert keys == ["draft"] and t["writes"][0]["revision"]["arc"]["title"] == "대화로 짠 아크"
    assert [a.model_dump() for a in store.load("sr").story_arcs] == arcs  # 다음 아크 초안은 화면에만 놓인다
