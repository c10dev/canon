"""장면 연출 3D 야외 틀: 차 옆(car_side) · 야외 빈터(outdoor) (docs/stage/3d/specs/rooms/car_side.md · outdoor.md).

판정 규칙: 야외(RoomSpec.open)는 벽 · 천장을 짚지 않는다, 막(Box.barrier)으로 갈린 두 사람은 몸 겹침을 보지 않는다,
손은 막을 지나 닿지 않는다(손 · 손목은 받는 사람 어깨까지 길을 본다). 장면 시험은 tests/stage3d_scenes/*car_side* · *outdoor*. LLM 호출 없음.
"""
import dataclasses
import re
from pathlib import Path

from canon import stage
from canon import stage3d as s3
from canon.schema import StageBody, StageScene, StageSpot
from canon.stage3d import body as b3, furniture, judge as j3
from tests.test_stage3d_wire import project


def _id(room, name):
    return next(a.id for a in room.anchors if a.name == name)


def _scene(room, start, beats=()):
    return StageScene(id="s", room=room.id, cast=[x.who for x in start], start=list(start), beats=list(beats))


def test_vehicle_kinds_registered():
    assert {"vehicle", "landmark", "ground"} <= set(stage.ANCHOR_KINDS) and set(stage.ANCHOR_KINDS) <= set(furniture.KINDS)
    assert stage.vocab()["kinds"] == stage.ANCHOR_KINDS
    assert all(b.barrier for b in furniture.KINDS["vehicle"].boxes)
    assert not any(b.solid for b in furniture.KINDS["ground"].boxes)


def test_stage_js_kinds_match():
    js = (Path(__file__).parents[1] / "canon/static/stage.js").read_text()
    body = re.search(r"const kinds = \{([^}]*)\}", js).group(1)
    assert dict(re.findall(r"(\w+): '([^']*)'", body)) == stage.ANCHOR_KINDS


def test_open_rooms():
    rs = s3.room_specs()
    assert rs["car_side"].open and rs["outdoor"].open
    assert not any(rs[t].open for t in stage.ROOMS if t not in ("car_side", "outdoor"))


def test_open_skips_ceiling_and_walls(monkeypatch):
    """같은 장면에 천장 1.5m 를 주면 닫힌 방은 천장 · 벽을 짚고, 야외는 짚지 않는다."""
    room = stage.make_room("outdoor", "r1")
    sc = _scene(room, [StageBody(who="h", at=StageSpot(ref=_id(room, "바위"), rel="front"), posture="stand"),
                       StageBody(who="d", at=StageSpot(ref=_id(room, "큰 나무"), rel="front"), posture="stand")],
                [{"bodies": [{"who": "d", "at": {"ref": _id(room, "길"), "rel": "left"}, "posture": "lie", "facing": "w"}]}])  # 땅 왼쪽 끝에 머리를 바깥으로 눕는다
    p = project()
    for open_, want in ((False, {("headroom", "h"), ("furniture_overlap", "d")}), (True, set())):
        spec = dataclasses.replace(s3.room_specs()["outdoor"], ceiling=1.5, open=open_)
        fr = b3.frames(sc, room, p, rooms={"outdoor": spec})
        got = {(v.rule, v.who) for v in j3.judge3d(sc, room, p, frames=fr, flat=[])}
        assert got == want, got


def test_barrier_parts_two_people():
    """차체 옆판을 사이에 둔 두 사람은 갈린다, 같은 쪽 두 사람은 아니다."""
    room = stage.make_room("car_side", "r1")
    fr = b3.frames(_scene(room, [StageBody(who="d", at=StageSpot(ref=_id(room, "운전석 창"), rel="front"), posture="stand")]), room)
    spec = s3.posture_specs()["stand"]
    inside, outside, beside = (b3._placed(spec, x, y, 0.0, 0.0) for x, y in ((4.35, 2.65), (3.6, 2.65), (3.6, 3.2)))
    assert j3._parted(inside, outside, fr)
    assert not j3._parted(outside, beside, fr)
    no_wall = dataclasses.replace(fr, solids=[dataclasses.replace(s, barrier=False) for s in fr.solids])
    assert not j3._parted(inside, outside, no_wall)


def test_car_side_shapes():
    room = stage.make_room("car_side", "r1")
    spec = s3.room_specs()["car_side"]
    by = {a.name: a for a in room.anchors}
    body = [s for s in furniture.solids(room, spec) if s.anchor == by["차체"].id]
    sides = [s.box for s in body if s.barrier and s.box[5] < 2]  # 운전석 칸 옆판 둘
    assert sorted(round(b[0], 2) for b in sides) == [3.9, 6.0]
    win = furniture.solids(room, spec)
    sill = max(b[5] for b in sides)
    assert all(s.box[2] == sill and not s.solid for s in win if s.anchor == by["운전석 창"].id)  # 창은 옆판 바로 위로 열려 있다
    assert furniture.surface(by["운전석"], spec, "seat") == 1.05


def test_car_side_window_hand_needs_window():
    """창밖에 선 사람이 앉은 사람 손에 물건을 건네면 지나고, 발목을 잡으면 옆판에 막힌다."""
    room = stage.make_room("car_side", "r1")
    p = project()

    def rules(part):
        sc = _scene(room, [StageBody(who="h", at=StageSpot(ref=_id(room, "운전석"), rel="on"), posture="chair", facing="w"),
                           StageBody(who="d", at=StageSpot(ref=_id(room, "운전석 창"), rel="front"), posture="stand", facing="#" + _id(room, "운전석 창"))],
                    [{"bodies": [{"who": "d", "contacts": [{"id": "c1", "by": "right", "to": "h", "part": part, "act": "hold"}]}]}])
        return [(v.rule, v.who) for v in j3.judge3d(sc, room, p)]

    assert rules("hand_l") == []
    assert rules("wrist_l") == []
    assert rules("ankle_l") == [("reach3d", "d")]


def test_frames_dict_says_open():
    room = stage.make_room("outdoor", "r1")
    sc = _scene(room, [StageBody(who="d", at=StageSpot(ref=_id(room, "길"), rel="on"), posture="stand")])
    d = b3.frames(sc, room).to_dict()
    assert d["open"] is True and all("barrier" in s for s in d["solids"])
    assert b3.frames(sc, stage.make_room("bedroom", "r2")).to_dict()["open"] is False


def test_outside_ok_scenes_clean_in_2d_too():
    """야외 틀의 ok 장면은 평면 판정까지 합쳐도 지적이 없다 (창 너머로 건네는 손은 쥔 것을 놓으며 닿는다)."""
    from tests.test_stage3d_wire import load
    scenes = sorted((Path(__file__).with_name("stage3d_scenes")).glob("ok_*"))
    outside = [s for s in scenes if "car_side" in s.stem or "outdoor" in s.stem]
    assert len(outside) == 2
    for path in outside:
        sc, room, _ = load(path)
        assert stage.judge_all(sc, room, project()) == [], path.stem
