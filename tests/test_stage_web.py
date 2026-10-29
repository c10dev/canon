"""장면 연출 웹 (web.py 의 …/stage): 새 장면, 저장 · 막기, 판정만, 지우기, 작품 전체 저장이 장면을 지키는지. 실행: python -m pytest tests"""
from canon.schema import Character, Meta, Project

from .jsvm import episode
from .test_web import client  # noqa: F401  (pytest fixture)


def _make(minor: bool = False):
    from canon import store

    p = Project(meta=Meta(title="방", target_episodes=3), characters=[
        Character(id="h", name="하린", role="주인공", age="16" if minor else "27"),
        Character(id="d", name="도윤", role="조연", age="29"),
    ], episodes=[episode(1, plot={"title": "첫 화", "events": ["도윤이 찾아온다", "하린이 붙잡는다"], "characters": ["h", "d"]})])
    store.save("st", p)


def test_new_save_check_delete(client):
    _make()
    assert client.get("/api/projects/st/stage/9").status_code == 400
    v = client.post("/api/projects/st/stage/1", json={"event": 1, "template": "bedroom", "room_name": "하린의 방"}).json()
    sid = v["made"]
    row = v["scenes"][0]
    assert row["event"] == 1 and not row["event_changed"] and row["scene"]["cast"] == ["h", "d"]
    assert v["rooms"][0]["name"] == "하린의 방" and v["vocab"]["postures"]["stand"]["label"] == "서기"
    door = next(a["id"] for a in v["rooms"][0]["anchors"] if a["kind"] == "door")
    assert all(b["at"] == {"ref": door, "rel": "front"} for b in row["scene"]["start"])
    assert client.post("/api/projects/st/stage/1", json={"event": 5, "template": "bedroom"}).status_code == 400

    scene = row["scene"]
    bed = next(a["id"] for a in v["rooms"][0]["anchors"] if a["name"] == "침대")
    scene["beats"] = [{"quote": "", "note": "도윤이 침대 옆으로", "bodies": [
        {"who": "d", "at": {"ref": bed, "rel": "right"}, "posture": "walk", "contacts": [
            {"id": "c1", "by": "right", "to": "h", "part": "wrist_l", "act": "hold"}]}]}]
    # 저장 없이 판정: 문 앞의 하린은 멀어서 닿지 않는다
    ck = client.post("/api/projects/st/stage/1/check", json={"scene": scene}).json()
    assert [x["rule"] for x in ck["violations"]] == ["reach"] and ck["dropped"] == 0
    assert client.get("/api/projects/st/stage/1").json()["scenes"][0]["scene"]["beats"] == []

    v = client.put(f"/api/projects/st/stage/1/{sid}", json={"scene": scene}).json()
    assert v["dropped"] == 0 and v["scenes"][0]["violations"][0]["rule"] == "reach"
    assert client.put("/api/projects/st/stage/1/other", json={"scene": scene}).status_code == 400

    # 같은 방을 쓰는 두 번째 장면
    v = client.post("/api/projects/st/stage/1", json={"event": 0, "room": v["rooms"][0]["id"]}).json()
    assert len(v["rooms"]) == 1 and len(v["scenes"]) == 2
    v = client.delete(f"/api/projects/st/stage/1/{sid}").json()
    assert [x["event"] for x in v["scenes"]] == [0]


def test_minor_contact_dropped_on_save(client):
    _make(minor=True)
    v = client.post("/api/projects/st/stage/1", json={"event": 0, "template": "bedroom"}).json()
    scene = v["scenes"][0]["scene"]
    scene["start"][1]["contacts"] = [{"id": "c1", "by": "right", "to": "h", "part": "chest", "act": "caress"},
                                     {"id": "c2", "by": "left", "to": "h", "part": "hand_r", "act": "hold"}]
    assert client.post("/api/projects/st/stage/1/check", json={"scene": scene}).json()["dropped"] == 1
    v = client.put(f"/api/projects/st/stage/1/{scene['id']}", json={"scene": scene}).json()
    assert v["dropped"] == 1 and v["minors"] == ["h"]
    assert [c["id"] for c in v["scenes"][0]["scene"]["start"][1]["contacts"]] == ["c2"]


def test_whole_save_keeps_stage_and_autorun_blocks(client, monkeypatch):
    from canon import autorun

    _make()
    stale = client.get("/api/projects/st").json()
    v = client.post("/api/projects/st/stage/1", json={"event": 0, "template": "office"}).json()
    # 장면을 만들기 전에 읽은 작품을 통째로 저장해도 장면과 방은 남는다
    p = client.put("/api/projects/st", json=stale).json()
    assert len(p["episodes"][0]["stage"]) == 1 and len(p["rooms"]) == 1
    monkeypatch.setattr(autorun, "active", lambda name: True)
    scene = v["scenes"][0]["scene"]
    r = client.put(f"/api/projects/st/stage/1/{scene['id']}", json={"scene": scene})
    assert r.status_code == 400 and "자동 집필" in r.json()["detail"]
    assert client.get("/api/projects/st/stage/1").status_code == 200
