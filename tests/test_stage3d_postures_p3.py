"""장면 연출 3D 자세 모듈 P3: 눕기 · 옆으로 눕기 · 엎드리기 · 안기거나 업히기 (docs/stage/3d/specs/postures/).

받치는 사람의 서기는 가짜 자세(fake.POSTURES)를 쓴다. 장소는 가짜 장소(종류 기본값)로 돈다. LLM 호출 없음.
"""
import math

import pytest

from canon import stage
from canon import stage3d as s3
from canon.schema import StageBody, StageContact, StageScene, StageSpot
from canon.stage3d import fake
from canon.stage3d.postures import _lying, held, lie, prone, side

from tests.test_stage3d_contract import check_posture

P3 = ("lie", "side", "prone", "held")
SPECS = {**fake.POSTURES, **{k: s3.posture_specs()[k] for k in P3}}


def run(room, start, cast=None):
    sc = StageScene(id="s", room=room.id, cast=cast or [b.who for b in start], start=start)
    return s3.frames(sc, room, postures=SPECS, rooms=fake.ROOMS).beats[0]


def body(who, ref, rel, posture, facing="", contacts=()):
    return StageBody(who=who, at=StageSpot(ref=ref, rel=rel), posture=posture, facing=facing, left="", right="",
                     contacts=list(contacts))


def anchor(room, name):
    return next(a for a in room.anchors if a.name == name)


def joints(fr, who):
    return fr.bodies[who].body.joints()


# ---------- 계약 ----------

@pytest.mark.parametrize("name", P3)
def test_contract(name):
    spec = s3.posture_specs()[name]
    check_posture(name, spec)
    assert spec.place_hook is not None
    assert spec.reach == (s3.Reach(0, 20) if name == "held" else s3.Reach(0, 0))
    assert spec.surface == (("carrier",) if name == "held" else ("lie", "floor"))


# ---------- 눕기 ----------

@pytest.mark.parametrize("name", ["lie", "side", "prone"])
def test_on_bed_inside_and_head_at_headboard(name):
    room = stage.make_room("bedroom", "r1")
    bed = anchor(room, "침대")
    fr = run(room, [body("a", bed.id, "on", name, facing="n")])
    j = joints(fr, "a")
    top = 0.45 if name == "side" else 0.25
    for k, v in j.items():
        assert bed.x <= v[0] <= bed.x + bed.w and bed.y <= v[1] <= bed.y + bed.h, (k, v)
        assert 0.5 - 0.01 <= v[2] <= 0.5 + top, (k, v)
    # 침대 rot 0: 앞이 +y, 머리판은 뒤(y 가 작은 쪽)
    assert j["head"][1] - bed.y < 0.4
    assert j["head"][1] < j["pelvis"][1] < j["ankle_l"][1]


def test_lie_face_up_prone_face_down():
    room = stage.make_room("empty", "r1")
    a = run(room, [StageBody(who="a", at=StageSpot(ref="a1", rel="front"), posture="lie", facing="e")])
    b = run(room, [StageBody(who="a", at=StageSpot(ref="a1", rel="front"), posture="prone", facing="e")])
    la, lb = a.bodies["a"].body, b.bodies["a"].body
    assert la.part_point("chest")[2] > la.part_point("back")[2]
    assert lb.part_point("chest")[2] < lb.part_point("back")[2]
    for v in list(lb.joints().values()):
        assert 0 <= v[2] <= 0.25


@pytest.mark.parametrize("name", ["lie", "prone"])
@pytest.mark.parametrize("facing,vec", [("e", (1, 0)), ("n", (0, -1)), ("sw", (-0.707, 0.707))])
def test_floor_head_toward_facing(name, facing, vec):
    room = stage.make_room("empty", "r1")
    fr = run(room, [body("a", "a1", "front", name, facing=facing)])
    hd = _lying.head_dir(fr.bodies["a"].body)
    assert hd[0] * vec[0] + hd[1] * vec[1] > 0.99
    assert fr.bodies["a"].body.joints()["pelvis"][:2] == pytest.approx(fr.pos["a"])  # 골반은 stage.place 좌표


@pytest.mark.parametrize("name", ["lie", "side", "prone"])
def test_floor_inside_room(name):
    room = stage.make_room("empty", "r1")
    sc_room = room.model_copy(update={"anchors": room.anchors + [room.anchors[0].model_copy(update={"id": "mid", "x": 1.8, "y": 1.3, "w": 0.4, "h": 0.4, "kind": "other"})]})
    fr = run(sc_room, [body("a", "mid", "front", name, facing="w")])
    for v in joints(fr, "a").values():
        assert 0 <= v[0] <= room.w and 0 <= v[1] <= room.h
        assert -0.02 <= v[2] <= 0.45


def test_sofa_long_side_and_clear_of_armrest():
    """소파(rot 180, 가로가 긴 쪽)는 몸축이 가로, 머리는 팔걸이 안쪽."""
    room = stage.make_room("living", "r1")
    sofa = anchor(room, "소파")
    j = joints(run(room, [body("a", sofa.id, "on", "lie")]), "a")
    assert abs(j["head"][0] - j["ankle_l"][0]) > 1.2 and abs(j["head"][1] - j["ankle_l"][1]) < 0.15
    arm = 0.1 * sofa.w
    xs = [v[0] for v in j.values()]
    assert min(xs) >= sofa.x + arm - 0.05 and max(xs) <= sofa.x + sofa.w - arm + 0.05
    assert all(sofa.y - 0.02 <= v[1] <= sofa.y + sofa.h - 0.9 * 0.25 + 0.02 for v in j.values())  # 등받이 앞


# ---------- 옆으로 눕기 ----------

def test_side_roll_choice():
    head = (0.0, -1.0)  # 머리가 위쪽(평면 -y)
    left, right = (head[1], -head[0]), (-head[1], head[0])  # 몸축의 왼쪽 · 오른쪽 (01 계약: 왼쪽은 (fy, -fx))
    assert side.roll_for(head, left) == 90  # 오른쪽이 아래면 몸 앞이 몸축 왼쪽
    assert side.roll_for(head, right) == -90
    assert side.roll_for(head, head) == 90  # 나란하면 오른쪽이 아래 (정할 것 1)


@pytest.mark.parametrize("facing,vec", [("e", (1, 0)), ("n", (0, -1)), ("w", (-1, 0))])
def test_side_floor_front_toward_facing(facing, vec):
    room = stage.make_room("empty", "r1")
    b = run(room, [body("a", "a1", "front", "side", facing=facing)]).bodies["a"].body
    fd = _lying.face_dir(b)
    assert fd[0] * vec[0] + fd[1] * vec[1] > 0.99
    assert b.angles.roll == 90


def test_side_roll_on_fk_is_left_of_axis():
    """roll +90 의 몸 앞은 FK 로도 몸축 왼쪽이다 (roll_for 의 부호 확인)."""
    b = s3.pose(side.ANGLES, 0, 0, yaw=0.7)
    hd, fd = _lying.head_dir(b), _lying.face_dir(b)
    assert side.roll_for(hd, fd) == 90


def test_side_on_bed_front_toward_facing_right_of_axis():
    room = stage.make_room("bedroom", "r1")
    bed = anchor(room, "침대")
    b = run(room, [body("a", bed.id, "on", "side", facing="e")]).bodies["a"].body  # 머리가 -y, 동쪽은 몸축 오른쪽
    fd = _lying.face_dir(b)
    assert fd[0] > 0.9
    assert b.angles.roll == -90 and b.angles.knee == side.ANGLES.knee[::-1]  # 왼쪽이 아래, 위쪽 다리가 더 굽음


def test_spoon_behind_on_bed_facing_right_of_axis():
    """향함이 몸축 오른쪽(동쪽)이어도 두 사람 모두 roll -90 으로 같은 쪽을 본다."""
    room = stage.make_room("bedroom", "r1")
    bed = anchor(room, "침대")
    fr = run(room, [body("a", bed.id, "on", "side", facing="e"), body("b", "@a", "back", "side", facing="e")])
    a, b = fr.bodies["a"].body, fr.bodies["b"].body
    assert _lying.face_dir(a)[0] > 0.9 and _lying.face_dir(b)[0] > 0.9
    assert math.dist(a.part_point("back"), b.part_point("chest")) < 0.15


def test_prone_head_only_turns_sideways():
    room = stage.make_room("empty", "r1")
    fr = run(room, [body("a", "a1", "front", "prone", facing="n"), body("b", "a1", "front", "stand")])
    look = fr.bodies["a"].body.head_rot
    assert look[1][2] == pytest.approx(0, abs=1e-9) and look[2][1] == pytest.approx(0, abs=1e-9)  # 위아래(x 축) 돌림 없음


def test_spoon_behind_on_bed():
    """뒤에서 안는 사람: 같은 침대, 같은 쪽 향함. 앞사람 등과 뒷사람 가슴이 0.15m 안.
    향함은 몸축 왼쪽(서쪽)이다. 오른쪽은 아래 시험."""
    room = stage.make_room("bedroom", "r1")
    bed = anchor(room, "침대")
    fr = run(room, [body("a", bed.id, "on", "side", facing="w"),
                    body("b", "@a", "back", "side", facing="w")])
    a, b = fr.bodies["a"].body, fr.bodies["b"].body
    assert b.base == pytest.approx(a.base)
    assert _lying.head_dir(a) == pytest.approx(_lying.head_dir(b))
    gap = math.dist(a.part_point("back"), b.part_point("chest"))
    assert gap < 0.15
    for v in b.joints().values():
        assert bed.x <= v[0] <= bed.x + bed.w and 0.49 <= v[2] <= 0.95


# ---------- 안기거나 업히기 ----------

def test_piggyback_hangs_behind_carrier():
    room = stage.make_room("empty", "r1")
    fr = run(room, [body("d", "a1", "front", "stand", facing="n",
                         contacts=[StageContact(id="c1", by="both", to="h", part="knee_l", act="carry")]),
                    body("h", "@d", "back", "held", facing="@d",
                         contacts=[StageContact(id="c2", by="both", to="d", part="chest", act="hold")])])
    d, h = fr.bodies["d"].body, fr.bodies["h"]
    assert h.attach == "d"
    dp, hp = d.joints()["pelvis"], h.body.joints()["pelvis"]
    f = (math.sin(d.yaw), math.cos(d.yaw))
    ahead = (hp[0] - dp[0]) * f[0] + (hp[1] - dp[1]) * f[1]
    assert ahead == pytest.approx(-0.30, abs=0.02)
    assert hp[2] - dp[2] == pytest.approx(0.12, abs=0.02)
    assert h.body.yaw == pytest.approx(d.yaw, abs=1e-6)  # 같은 방향
    c2 = next(c for c in fr.contacts if c.id == "c2")
    assert c2.hands == ["l", "r"] and c2.gap <= 0.05  # 업힌 두 팔이 업은 가슴에 닿는다
    c1 = next(c for c in fr.contacts if c.id == "c1")
    assert c1.points[1] == pytest.approx(h.body.part_point("knee_l"))  # 업은 손은 업힌 무릎으로


def test_carried_in_arms_faces_carrier():
    room = stage.make_room("empty", "r1")
    fr = run(room, [body("d", "a1", "front", "stand", facing="e",
                         contacts=[StageContact(id="c1", by="both", to="h", part="back", act="hug")]),
                    body("h", "@d", "front", "held")])
    d, h = fr.bodies["d"].body, fr.bodies["h"]
    assert h.attach == "d"
    diff = math.degrees(abs(math.atan2(math.sin(h.body.yaw - d.yaw), math.cos(h.body.yaw - d.yaw))))
    assert diff == pytest.approx(180, abs=5)
    dp, hp = d.joints()["pelvis"], h.body.joints()["pelvis"]
    f = (math.sin(d.yaw), math.cos(d.yaw))
    assert (hp[0] - dp[0]) * f[0] + (hp[1] - dp[1]) * f[1] == pytest.approx(0.25, abs=0.02)
    assert hp[2] - dp[2] == pytest.approx(0.12, abs=0.02)


def test_support_contact_wins_over_spot():
    """받침 접촉을 하는 선 사람이 먼저다. 자리 @인물 은 그다음."""
    room = stage.make_room("empty", "r1")
    fr = run(room, [body("d", "a1", "front", "stand", facing="n",
                         contacts=[StageContact(id="c1", by="both", to="h", part="knee_l", act="carry")]),
                    body("e", "a1", "back", "stand"),
                    body("h", "@e", "beside", "held")])
    assert fr.bodies["h"].attach == "d"
    fr = run(room, [body("e", "a1", "back", "stand"), body("h", "@e", "back", "held")])
    assert fr.bodies["h"].attach == "e"


def test_sitting_supporter_contact_does_not_count():
    """받침 접촉이어도 선 자세가 아니면 받치는 사람으로 보지 않는다 (자리가 그 사람이 아니면)."""
    room = stage.make_room("bedroom", "r1")
    chair = anchor(room, "의자")
    fr = run(room, [body("d", chair.id, "on", "chair",
                         contacts=[StageContact(id="c1", by="both", to="h", part="back", act="hug")]),
                    body("h", "a1", "front", "held")])
    assert fr.bodies["h"].attach is None


def test_no_supporter_stays_unattached():
    room = stage.make_room("empty", "r1")
    fr = run(room, [body("h", "a1", "front", "held", facing="n")])
    h = fr.bodies["h"]
    assert h.attach is None
    p = h.body.joints()["pelvis"]
    assert p[:2] == pytest.approx(fr.pos["h"]) and p[2] == pytest.approx(held.ANGLES.pelvis_h)


def test_carrier_walking_still_carries():
    room = stage.make_room("empty", "r1")
    specs = dict(SPECS, walk=fake.POSTURES["stand"].__class__("walk", fake.POSTURES["stand"].angles, ("floor",)))
    sc = StageScene(id="s", room="r1", cast=["d", "h"], start=[
        body("d", "a1", "front", "walk", facing="n", contacts=[StageContact(id="c1", by="both", to="h", part="knee_l", act="carry")]),
        body("h", "@d", "back", "held")])
    fr = s3.frames(sc, room, postures=specs, rooms=fake.ROOMS).beats[0]
    assert fr.bodies["h"].attach == "d"


def test_deterministic():
    room = stage.make_room("bedroom", "r1")
    bed = anchor(room, "침대")
    sc = StageScene(id="s", room="r1", cast=["a", "b", "d", "h"], start=[
        body("a", bed.id, "on", "lie"), body("b", bed.id, "on", "prone"),
        body("d", "a5", "front", "stand", contacts=[StageContact(id="c1", by="both", to="h", part="knee_l", act="carry")]),
        body("h", "@d", "back", "held")])
    one = s3.frames(sc, room, postures=SPECS, rooms=fake.ROOMS).to_dict()
    assert s3.frames(sc, room, postures=SPECS, rooms=fake.ROOMS).to_dict() == one
