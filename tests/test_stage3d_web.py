"""장면 연출 3D 보기 값 (web.py 의 …/stage/{n}/{sid}/frames): 응답 모양, 빠진 모듈, 저장 안 한 장면, 없는 장면.
자세 · 장소 모듈은 가짜 등록부(canon/stage3d/fake.py)로 바꾼다. 실행: python -m pytest tests"""
import pytest

from canon.stage3d import fake, postures, rooms

from .test_stage_web import _make
from .test_web import client  # noqa: F401  (pytest fixture)


@pytest.fixture
def fake_reg(monkeypatch):
    monkeypatch.setattr(postures, "load", lambda: fake.POSTURES)
    monkeypatch.setattr(rooms, "load", lambda: fake.ROOMS)


def _scene(client):
    _make()
    v = client.post("/api/projects/st/stage/1", json={"event": 0, "template": "bedroom"}).json()
    scene = v["scenes"][0]["scene"]
    bed = next(a["id"] for a in v["rooms"][0]["anchors"] if a["name"] == "침대")
    scene["beats"] = [{"quote": "", "note": "", "bodies": [
        {"who": "d", "at": {"ref": "@h", "rel": "front"}, "posture": "walk", "contacts": [
            {"id": "c1", "by": "right", "to": "h", "part": "wrist_l", "act": "hold"}]},
        {"who": "h", "at": {"ref": bed, "rel": "on"}, "posture": "chair"}]}]
    client.put(f"/api/projects/st/stage/1/{scene['id']}", json={"scene": scene})
    return scene


def test_frames_shape(client, fake_reg):
    scene = _scene(client)
    r = client.get(f"/api/projects/st/stage/1/{scene['id']}/frames").json()
    assert set(r) == {"frames", "violations3d", "missing"}
    fr = r["frames"]
    assert fr["ceiling"] == 2.4 and fr["solids"] and len(fr["beats"]) == 2
    assert all(len(s["box"]) == 6 for s in fr["solids"])
    start, one = fr["beats"]
    assert start["bodies"]["h"]["posture"] == "stand" and start["bodies"]["h"]["missing"] is None
    assert len(start["bodies"]["h"]["joints"]) == 19 and len(start["bodies"]["h"]["joints"]["head"]) == 3
    # 걷기는 가짜 등록부에 없다: 관절 없이 '모듈 없음'
    assert one["bodies"]["d"] == {"posture": "walk", "missing": "walk", "attach": None, "joints": None}
    assert one["bodies"]["h"]["posture"] == "chair" and one["bodies"]["h"]["joints"]
    assert "walk" in r["missing"]["postures"] and r["missing"]["rooms"] == []
    assert r["violations3d"] == []  # 자세가 다 없으면 3D 판정을 내지 않는다


def test_frames_missing_rooms_and_draft(client, monkeypatch):
    monkeypatch.setattr(postures, "load", lambda: {})
    monkeypatch.setattr(rooms, "load", lambda: {})
    scene = _scene(client)
    r = client.get(f"/api/projects/st/stage/1/{scene['id']}/frames").json()
    assert "bedroom" in r["missing"]["rooms"] and "stand" in r["missing"]["postures"]
    assert r["frames"]["solids"]  # 장소 모듈이 없어도 종류 기본값 상자
    assert all(b["joints"] is None for beat in r["frames"]["beats"] for b in beat["bodies"].values())

    # 저장하지 않은 장면: 박자를 하나 더한 것을 그린다. 저장된 장면은 그대로
    scene["beats"].append({"quote": "", "note": "", "bodies": []})
    d = client.post(f"/api/projects/st/stage/1/{scene['id']}/frames", json={"scene": scene}).json()
    assert len(d["frames"]["beats"]) == 3
    assert len(client.get(f"/api/projects/st/stage/1/{scene['id']}/frames").json()["frames"]["beats"]) == 2
    assert client.post("/api/projects/st/stage/1/other/frames", json={"scene": scene}).status_code == 400


def test_frames_judge_only_when_complete(client, monkeypatch, fake_reg):
    import sys
    import types

    from canon import stage, stage3d

    scene = _scene(client)
    judge = types.ModuleType("canon.stage3d.judge")
    judge.judge3d = lambda sc, room, p: [stage.Violation(beat=1, cause=1, who="h", rule="headroom", text="머리가 천장에 닿아요")]
    monkeypatch.setitem(sys.modules, "canon.stage3d.judge", judge)
    monkeypatch.setattr(stage3d, "judge", judge, raising=False)
    url = f"/api/projects/st/stage/1/{scene['id']}/frames"
    assert client.get(url).json()["violations3d"] == []
    monkeypatch.setattr(stage3d, "complete", lambda: True)
    assert [v["rule"] for v in client.get(url).json()["violations3d"]] == ["headroom"]


def test_frames_404(client, fake_reg):
    _make()
    assert client.get("/api/projects/st/stage/1/nope/frames").status_code == 404
    assert client.get("/api/projects/st/stage/9/nope/frames").status_code == 400
