"""붙은 기준점 (docs/stage/specs/09-attach.md): 부모 기준 좌표 풀기, 방 넓히기, 옛 방 짐작, 정리, AI 부분 구역, 3D 모양, 브라우저 같은 규칙.
실행: python -m pytest tests"""
import pytest

from canon import stage
from canon.schema import Character, DraftAnchor, Meta, Project, StageAnchor, StageBody, StageRoom, StageScene, StageSpot
from canon.stage3d import furniture

from .jsvm import STATIC, dump, needs_node, run_js


def _room(*anchors: StageAnchor, w: float = 10.0, h: float = 8.0) -> StageRoom:
    return StageRoom(id="r", name="방", template="empty", w=w, h=h, anchors=list(anchors), attached=True)


def _car(rot: int) -> StageAnchor:
    w, h = (2.0, 6.0) if rot in (0, 180) else (6.0, 2.0)
    return StageAnchor(id="car", name="트럭", kind="vehicle", x=2.0, y=1.0, w=w, h=h, rot=rot)


def _box(a: StageAnchor) -> tuple:
    return (round(a.x, 3), round(a.y, 3), round(a.w, 3), round(a.h, 3), a.rot)


@pytest.mark.parametrize("rot, want", [
    # 짐칸: 트럭 안 뒤 끝(지역 y -2), 폭 2 · 깊이 2. 앞쪽(지역 rot 180)은 뒤 끝 바깥
    (0, (2.0, 1.0, 2.0, 2.0, 180)),
    (90, (6.0, 1.0, 2.0, 2.0, 270)),
    (180, (2.0, 5.0, 2.0, 2.0, 0)),
    (270, (2.0, 1.0, 2.0, 2.0, 90)),
])
def test_resolve_follows_parent_rotation(rot, want):
    bed = StageAnchor(id="bed", name="짐칸", kind="other", parent="car", face="inside", x=0, y=-2.0, w=2.0, h=2.0, rot=180)
    w = stage.resolve(_room(_car(rot), bed))
    assert _box(w.anchors[1]) == want
    assert stage.resolve(w) is w  # 푼 방은 다시 풀지 않는다


def test_resolve_faces_and_chain():
    car = _car(0)  # 앞 +y, 오른쪽(앞에서 바라본 오른쪽) +x
    win = StageAnchor(id="win", name="창", kind="window", parent="car", face="right", x=9.0, y=1.5, w=0.1, h=0.8, rot=270)
    ladder = StageAnchor(id="lad", name="사다리", kind="other", parent="car", face="back", x=0.3, y=0, w=0.5, h=0.2)
    box = StageAnchor(id="box", name="짐", kind="other", parent="bed", face="top", x=0, y=0, w=0.5, h=0.5)
    bed = StageAnchor(id="bed", name="짐칸", kind="other", parent="car", face="inside", x=0, y=-2.0, w=2.0, h=2.0)
    a = {x.id: x for x in stage.resolve(_room(car, win, ladder, box, bed)).anchors}
    assert _box(a["win"]) == (3.9, 5.1, 0.1, 0.8, 270)  # 창은 차 오른쪽(+x) 안쪽 테두리
    assert _box(a["lad"]) == (3.05, 0.8, 0.5, 0.2, 0)   # 사다리는 뒷면 바깥에 맞닿음
    assert _box(a["box"]) == (2.75, 1.75, 0.5, 0.5, 0)  # 짐칸 위 짐: 사슬을 따라 푼다


def test_resolve_bad_parent_reads_as_root_and_clean_detaches():
    a = StageAnchor(id="a", name="가", kind="other", parent="b", face="inside", x=1, y=1)
    b = StageAnchor(id="b", name="나", kind="other", parent="a", face="inside", x=2, y=2)
    c = StageAnchor(id="c", name="다", kind="other", parent="zz", face="inside", x=3, y=3)
    d = StageAnchor(id="d", name="라", kind="other", parent="room", face="inside", x=4, y=4)
    room = _room(a, b, c, d)
    stage.resolve(room)  # 고리여도 멈춘다
    assert stage.clean_room(room) == 3
    assert [(x.parent, x.face) for x in room.anchors] in ([("", ""), ("a", "inside"), ("", ""), ("", "")], [("b", "inside"), ("", ""), ("", ""), ("", "")])


def test_wall_child_stays_on_wall_when_room_grows():
    door = StageAnchor(id="d", name="철문", kind="door", parent="room", face="s", x=1.6, y=2.9, w=0.8, h=0.1, rot=180)
    room = _room(door, w=4.0, h=3.0)
    room.h = 11.15  # 아래로 넓힘
    stage.shift_room(room, 1.4, 5.35)  # 왼쪽 · 위로도 넓힘
    room.w += 1.4
    w = stage.resolve(room).anchors[0]
    assert (w.x, w.y + w.h) == (pytest.approx(3.0), pytest.approx(11.15))


def test_shift_moves_roots_and_walls_not_children():
    car, bed = _car(0), StageAnchor(id="bed", name="짐칸", kind="other", parent="car", face="inside", x=0, y=-2.0, w=2.0, h=2.0)
    door = StageAnchor(id="d", name="문", kind="door", parent="room", face="n", x=5, y=0, w=0.8, h=0.1)
    room = _room(car, bed, door)
    stage.shift_room(room, 1.0, 2.0)
    assert (room.anchors[0].x, room.anchors[0].y) == (3.0, 3.0) and (room.anchors[1].x, room.anchors[1].y) == (0, -2.0)
    assert room.anchors[2].x == 6.0


def test_templates_attach_and_keep_world_coordinates():
    for key, (_, w, h, rows) in stage.ROOMS.items():
        room = stage.make_room(key, "r")
        world = stage.resolve(room)
        for a, row in zip(world.anchors, rows):
            assert (round(a.x, 3), round(a.y, 3), a.w, a.h, a.rot) == (row[2], row[3], row[4], row[5], row[6]), (key, a.name)
    side = {a.name: a for a in stage.make_room("car_side", "r").anchors}
    body = side["차체"].id
    assert {n: (side[n].parent, side[n].face) for n in ("운전석", "조수석", "운전석 창", "조수석 창")} == {
        "운전석": (body, "inside"), "조수석": (body, "inside"), "운전석 창": (body, "front"), "조수석 창": (body, "back")}
    bedroom = {a.name: a for a in stage.make_room("bedroom", "r").anchors}
    assert bedroom["문"].parent == "room" and bedroom["의자"].parent == ""  # 책상 곁 의자는 붙이지 않는다


def test_old_room_guessed_once_and_detached_stays_detached():
    raw = {"id": "r", "name": "방", "w": 4.0, "h": 3.0, "anchors": [
        {"id": "a1", "name": "문", "kind": "door", "x": 1.6, "y": 2.9, "w": 0.8, "h": 0.1, "rot": 180}]}
    room = StageRoom.model_validate(raw)  # 옛 project.json: 붙은 칸 없음
    assert room.attached and (room.anchors[0].parent, room.anchors[0].face) == ("room", "s")
    room.anchors[0].parent, room.anchors[0].face = "", ""  # 작가가 뗐다
    again = StageRoom.model_validate(room.model_dump())
    assert again.anchors[0].parent == ""


def test_part_zone_fills_back_end_and_person_stands_outside():
    """15화(2026-10-30): 정비차 짐칸이 트럭 뒤 1.35m 에 따로 떠 있었다. part 면 트럭 안 뒤 끝에 붙는다."""
    room = stage.make_room("empty", "r1")
    room, adds, _, _ = stage.place_anchors(room, [
        DraftAnchor(name="정비차", kind="vehicle", near="문", rel="back"),
        DraftAnchor(name="정비차 짐칸", kind="other", near="정비차", rel="back", part=True)])
    truck, bed = (x.anchor for x in adds)
    assert (bed.parent, bed.face) == (truck.id, "inside") and adds[1].where == "정비차 안 뒤 끝"
    w = {a.name: a for a in stage.resolve(room).anchors}
    t, b = w["정비차"], w["정비차 짐칸"]
    assert (b.w, b.h) == (t.w, 2.0) and t.x <= b.x and b.x + b.w <= t.x + t.w and t.y <= b.y and b.y + b.h <= t.y + t.h
    px, py = stage._anchor_point(b, "front")
    assert not (t.x < px < t.x + t.w and t.y < py < t.y + t.h)  # 짐칸 앞에 선 사람은 트럭 밖
    assert furniture.shape(b, stage.resolve(room)).boxes[0].solid is False  # 짐칸은 테두리만


def test_part_without_flag_keeps_old_placement():
    room = stage.make_room("empty", "r1")
    room, adds, _, _ = stage.place_anchors(room, [
        DraftAnchor(name="정비차", kind="vehicle", near="문", rel="back"),
        DraftAnchor(name="정비차 짐칸", kind="other", near="정비차", rel="back")])
    assert adds[1].anchor.parent == "" and adds[1].where == "정비차 뒤"


def test_grow_keeps_wall_door_on_wall():
    """15화(2026-10-30): AI 가 방을 아래로 넓히자 아래 벽 철문이 마당 한가운데 섰다."""
    room = stage.make_room("empty", "r1")  # 4×3, 문은 아래 벽
    grown, adds, dx, dy = stage.place_anchors(room, [
        DraftAnchor(name="캠핑카", kind="vehicle", near="문", rel="back"),
        DraftAnchor(name="정비차", kind="vehicle", near="캠핑카", rel="left")])
    for r in (grown, stage.grow_room(room, adds, dx, dy, grown.w, grown.h)[0]):
        door = stage.resolve(r).anchors[0]
        assert door.y + door.h == pytest.approx(r.h)


def test_zone_has_no_overlap_violation_and_seat_is_solid():
    p = Project(meta=Meta(title="t"), characters=[Character(id="h", name="건우", role="주인공", age="30")])
    car = _car(0)
    seat = StageAnchor(id="s", name="운전석", kind="seat", parent="car", face="inside", x=0.5, y=1.6, w=0.7, h=0.7, sit=True)
    bed = StageAnchor(id="bed", name="짐칸", kind="other", parent="car", face="inside", x=0, y=-2.0, w=2.0, h=2.0)
    room = _room(car, seat, bed)
    sc = StageScene(id="x", cast=["h"], room="r", start=[StageBody(who="h", at=StageSpot(ref="bed", rel="front"), posture="stand", left="", right="")])
    assert stage.judge(sc, room, p) == []
    w = stage.resolve(room)
    assert furniture.shape(w.anchors[1], w).boxes[0].solid and len(furniture.shape(w.anchors[0], w).boxes) == 5


def test_top_child_sits_on_parent_top():
    desk = StageAnchor(id="desk", name="책상", kind="desk", x=1, y=1, w=1.2, h=0.6)
    lamp = StageAnchor(id="lamp", name="스탠드", kind="other", parent="desk", face="top", x=0, y=0, w=0.2, h=0.2)
    sol = [s for s in furniture.solids(_room(desk, lamp)) if s.anchor == "lamp"]
    assert sol[0].box[2] == pytest.approx(0.75)


@needs_node
def test_js_resolve_matches_server():
    import re
    files = re.findall(r'src="/static/([a-z]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))
    rooms = [stage.make_room(k, "r") for k in stage.ROOMS]
    for rot in (0, 90, 180, 270):
        rooms.append(_room(_car(rot),
                           StageAnchor(id="bed", name="짐칸", kind="other", parent="car", face="inside", x=0.3, y=-2.0, w=2.0, h=2.0, rot=180),
                           StageAnchor(id="win", name="창", kind="window", parent="car", face="left", x=0, y=1.5, w=0.1, h=0.8, rot=90),
                           StageAnchor(id="box", name="짐", kind="other", parent="bed", face="top", x=0.2, y=0.1, w=0.5, h=0.5),
                           StageAnchor(id="d", name="문", kind="door", parent="room", face="e", x=7, y=3, w=0.1, h=0.8)))
    got = run_js(files, "data.rooms.map((r) => stageResolve(r).anchors.map((a) => [a.x, a.y, a.w, a.h, a.rot]))", {"rooms": [dump(r) for r in rooms]})
    for g, r in zip(got, rooms):
        want = [[a.x, a.y, a.w, a.h, a.rot] for a in stage.resolve(r).anchors]
        for gx, wx in zip(g, want):
            assert gx == pytest.approx(wx, abs=1e-9), r.name


@needs_node
def test_js_attach_drag_turn_and_drop_note():
    import re
    files = re.findall(r'src="/static/([a-z]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))
    bed = StageAnchor(id="bed", name="짐칸", kind="other", x=2.0, y=5.0, w=2.0, h=2.0)
    room = _room(_car(0), bed)
    got = run_js(files, """(() => {
      const r = data.room;
      const on = stageAttach(r, 'bed', 'car|inside');
      r.anchors[1] = on;
      const w0 = stageResolve(r).anchors[1];
      const moved = stageDragTo(r, 'bed', 9, 9);  // 부모 안에서만
      const car = r.anchors[0]; stageTurn(car);
      const w1 = stageResolve(r).anchors[1];
      const opts = stageAttachOptions(r, 'car').map((x) => x[0]);
      const off = stageAttach(r, 'bed', '');
      return { on: [on.parent, on.face, on.x, on.y], w0: [w0.x, w0.y], moved, w1: [w1.x, w1.y, w1.w, w1.h], car: [car.x, car.y, car.w, car.h, car.rot],
               opts: opts.includes('bed|inside'), note: stgDropNote(r, 'car'), off: [off.parent, off.x, off.y] };
    })()""", {"room": dump(room)})
    assert got["on"] == ["car", "inside", 0, 2] and got["w0"] == [2, 5]
    assert got["moved"] == {"x": 0, "y": 2}  # 끌어도 트럭 밖으로 나가지 않는다
    # 트럭을 돌리면(앞 +y → -x) 앞 끝에 붙은 짐칸도 함께 돌아 -x 끝으로 간다
    assert got["car"] == [0, 3, 6, 2, 90] and got["w1"] == pytest.approx([0, 3, 2, 2])
    assert got["opts"] is False and "짐칸도 함께 빠져요" in got["note"]
    assert got["off"][0] == "" and got["off"][1:] == pytest.approx([0, 3])
