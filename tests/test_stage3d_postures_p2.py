"""장면 연출 3D 자세 묶음 P2: 의자에 앉기 · 바닥에 앉기 · 쪼그려 앉기 · 무릎 꿇기 (docs/stage/3d/specs/postures/).

각 자세 명세서의 '시험' 줄과 계약 시험. 장소 모듈 없이 가구 종류 기본값(furniture.KINDS)으로 돈다. LLM 호출 없음.
"""
import math

import pytest

from canon import stage3d as s3
from canon.schema import StageAnchor, StageBody, StageRoom, StageScene, StageSpot
from canon.stage3d import fake
from canon.stage3d.postures import chair, floor, kneel, squat
from tests.test_stage3d_contract import check_posture

P2 = {"chair": chair, "floor": floor, "squat": squat, "kneel": kneel}


def frame(anchor, posture, rel="on", facing="", extra=None):
    """방 하나에 기준점 하나(와 더 놓을 것), 인물 하나. 시작 상태의 몸."""
    room = StageRoom(id="r1", name="방", w=4, h=4, anchors=[anchor] + (extra or []))
    at = StageSpot(ref=anchor.id, rel=rel) if anchor.id else None
    sc = StageScene(id="s", room="r1", cast=["a"], start=[StageBody(who="a", at=at, posture=posture, facing=facing)])
    fr = s3.frames(sc, room, rooms={})
    return fr, fr.beats[0].bodies["a"].body


def seat(kind="chair", rot=0, h=None, sit=True, lie=False):
    a = StageAnchor(id="a1", name="자리", kind=kind, x=1.5, y=1.5, w=0.5, h=0.5, rot=rot, sit=sit, lie=lie)
    return a, h


def feet(b):
    j = b.joints()
    return [j["ankle_l"][2], j["ankle_r"][2]]


def foot_bottom(b):
    return min(min(c.a[2], c.b[2]) - c.r for c in b.capsules() if c.segment.startswith("foot"))


# ---------- 계약 ----------

@pytest.mark.parametrize("name", sorted(P2))
def test_contract(name):
    spec = P2[name].POSTURE
    check_posture(name, spec)
    assert s3.posture_specs()[name] is spec  # 등록부가 폴더에서 찾는다


def test_surfaces_and_reach():
    assert chair.POSTURE.surface == ("seat",) and chair.POSTURE.feet_to_floor
    assert floor.POSTURE.surface == ("floor", "lie", "top")
    assert squat.POSTURE.surface == ("floor", "top")
    assert kneel.POSTURE.surface == ("floor", "lie", "top")
    assert [(P2[n].POSTURE.reach.lean, P2[n].POSTURE.reach.twist) for n in ("chair", "floor", "squat", "kneel")] == \
        [(30, 40), (35, 45), (20, 30), (30, 40)]


# ---------- 의자에 앉기 ----------

@pytest.mark.parametrize("kind,h", [("sofa", 0.42), ("chair", 0.45), ("bed", 0.5)])
def test_chair_pelvis_on_seat(kind, h):
    _, b = frame(StageAnchor(id="a1", name="자리", kind=kind, x=1.5, y=1.5, w=0.6, h=0.6, sit=True), "chair")
    assert b.base == pytest.approx(h)
    assert b.joints()["pelvis"][2] == pytest.approx(h + 0.08, abs=0.001)


@pytest.mark.parametrize("kind", ["sofa", "chair"])
def test_chair_feet_on_floor(kind):
    _, b = frame(StageAnchor(id="a1", name="자리", kind=kind, x=1.5, y=1.5, w=0.6, h=0.6, sit=True), "chair")
    assert feet(b) == pytest.approx([0, 0], abs=0.03)


def test_chair_bed_edge_feet_on_floor():
    # 0.5m(침대)는 무릎만으로 발이 닿지 않는다: 엉덩 굽힘을 줄여 넓적다리를 앞으로 기울이고 발을 바닥과 나란히 둔다
    _, b = frame(StageAnchor(id="a1", name="침대", kind="bed", x=1.0, y=1.0, w=1.4, h=2.0, sit=True, lie=True), "chair")
    j = b.joints()
    assert feet(b) == pytest.approx([0, 0], abs=0.03)
    assert b.hip[0] < chair.ANGLES.hip[0]
    assert j["toe_l"][2] == pytest.approx(j["ankle_l"][2], abs=0.02)  # 발바닥이 바닥과 나란히


def test_chair_high_seat_dangles():
    # 0.75m(책상 윗면)는 엉덩을 30° 줄여도 닿지 않는다: 발끝을 펴서 바닥 쪽으로 늘어뜨린다
    _, b = frame(StageAnchor(id="a1", name="책상", kind="desk", x=1.5, y=1.5, w=1.0, h=0.5), "chair")
    j = b.joints()
    assert j["ankle_l"][2] > 0.05
    assert b.ankle[0] > 0 and j["toe_l"][2] < j["ankle_l"][2]


def test_chair_low_seat_stretches_legs():
    spec = s3.RoomSpec("car", 1.2, {"운전석": s3.Furniture((s3.Box(0, 1, 0, 1, 0, 0.3),), seat=0.3)})
    room = StageRoom(id="r1", name="차", template="car", anchors=[
        StageAnchor(id="a1", name="운전석", kind="seat", x=1, y=1, w=0.5, h=0.5, sit=True)])
    sc = StageScene(id="s", room="r1", cast=["a"], start=[StageBody(who="a", at=StageSpot(ref="a1", rel="on"), posture="chair")])
    b = s3.frames(sc, room, rooms={"car": spec}).beats[0].bodies["a"].body
    assert feet(b) == pytest.approx([0, 0], abs=0.01)
    assert b.knee[0] < 87


def test_chair_thigh_not_in_seat():
    fr, b = frame(StageAnchor(id="a1", name="의자", kind="chair", x=1.5, y=1.5, w=0.5, h=0.5, sit=True), "chair")
    seat_box = [s for s in fr.solids if s.box[5] == pytest.approx(0.45)][0]
    caps = {c.segment: c for c in b.capsules()}
    for s in ("l", "r"):
        assert s3.penetration(caps["thigh_" + s], seat_box) <= 0.03


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_chair_back_toward_backrest(rot):
    a = StageAnchor(id="a1", name="의자", kind="chair", x=1.5, y=1.5, w=0.5, h=0.5, rot=rot, sit=True)
    fx, fy = {0: (0, 1), 90: (-1, 0), 180: (0, -1), 270: (1, 0)}[rot]
    facing = {0: "s", 90: "w", 180: "n", 270: "e"}[rot]
    _, b = frame(a, "chair", facing=facing)
    p = b.joints()["pelvis"]
    cx, cy = 1.75, 1.75
    assert (p[0] - cx) * fx + (p[1] - cy) * fy == pytest.approx(-0.13, abs=0.001)  # 등받이 쪽으로 0.13m


def test_chair_sideways_drops_shift():
    # 기준점 앞쪽(아래)과 반대(위)를 보면 등받이에 등이 닿지 않는다: 옮기지 않는다
    _, b = frame(StageAnchor(id="a1", name="소파", kind="sofa", x=1.5, y=1.5, w=0.5, h=0.5, sit=True), "chair", facing="n")
    p = b.joints()["pelvis"]
    assert p[:2] == pytest.approx((1.75, 1.75), abs=0.001)
    # 옆(90°)은 그대로 옮긴다
    _, b = frame(StageAnchor(id="a1", name="소파", kind="sofa", x=1.5, y=1.5, w=0.5, h=0.5, sit=True), "chair", facing="e")
    assert b.joints()["pelvis"][0] == pytest.approx(1.75 - 0.13, abs=0.001)


def test_chair_off_seat_in_air():
    # 기준점 앞(on 아님): 허공의 0.45m 에 앉고 판정 no_support 가 짚는다
    _, b = frame(StageAnchor(id="a1", name="의자", kind="chair", x=1.5, y=1.5, w=0.5, h=0.5, sit=True), "chair", rel="front")
    assert b.base == pytest.approx(0.45)
    assert min(v[2] for v in b.joints().values()) >= -0.02
    assert feet(b) == pytest.approx([0, 0], abs=0.03)


def test_chair_on_desk_without_sit():
    # 앉기 거짓인 책상 위: 윗면(0.75m)에 걸터앉고 발을 늘어뜨린다. 판정 no_support 가 짚는다
    _, b = frame(StageAnchor(id="a1", name="책상", kind="desk", x=1.5, y=1.5, w=1.0, h=0.5), "chair")
    assert b.base == pytest.approx(0.75)
    assert b.joints()["pelvis"][2] == pytest.approx(0.83, abs=0.001)
    assert min(v[2] for v in b.joints().values()) > 0


def test_chair_without_spot():
    room = StageRoom(id="r1", name="방")
    sc = StageScene(id="s", room="r1", cast=["a"], start=[StageBody(who="a", posture="chair")])
    fr = s3.frames(sc, room, rooms={})
    assert "a" not in fr.beats[0].bodies  # 자리를 모르면 stage.place 가 빼므로 놓지 않는다


# ---------- 바닥에 앉기 ----------

@pytest.mark.parametrize("base", [0.0, 0.5])
def test_floor_heights(base):
    b = s3.pose(floor.POSTURE, 0, 0, 0, base)
    j = b.joints()
    assert j["pelvis"][2] == pytest.approx(base + 0.12, abs=0.001)
    for s in ("l", "r"):
        assert 0 <= j["knee_" + s][2] - base <= 0.25
        assert j["ankle_" + s][2] >= base and j["toe_" + s][2] >= base
    assert min(v[2] for v in j.values()) >= base - 0.02


def test_floor_cross_legged():
    """양반다리: 무릎은 몸 밖으로 벌어지고, 두 발목은 몸 가운데(골반 폭 안)로 들어와 앞뒤로 엇갈린다."""
    j = s3.pose(floor.POSTURE, 0, 0).joints()
    for s in ("l", "r"):
        assert abs(j["knee_" + s][0]) > 0.25
        assert abs(j["ankle_" + s][0]) < 0.12
    assert j["ankle_l"][0] < 0 < j["ankle_r"][0]  # 왼발은 오른쪽으로, 오른발은 왼쪽으로 건너간다
    assert abs(j["ankle_l"][1] - j["ankle_r"][1]) > 0.15


def test_floor_shins_apart():
    caps = {c.segment: c for c in s3.pose(floor.POSTURE, 0, 0).capsules()}
    assert s3.penetration(caps["shin_l"], caps["shin_r"]) <= 0.03
    assert s3.penetration(caps["foot_l"], caps["foot_r"]) <= 0.03


def test_floor_on_bed():
    _, b = frame(StageAnchor(id="a1", name="침대", kind="bed", x=1.0, y=1.0, w=1.4, h=2.0, sit=True, lie=True), "floor")
    assert b.base == pytest.approx(0.5)
    assert b.joints()["pelvis"][2] == pytest.approx(0.62, abs=0.001)


def test_floor_without_spot_is_floor():
    _, b = frame(StageAnchor(id="a1", name="책상", kind="desk", x=1.5, y=1.5, w=1.0, h=0.5), "floor", rel="front")
    assert b.base == 0


# ---------- 쪼그려 앉기 ----------

def test_squat_foot_on_floor():
    b = s3.pose(squat.POSTURE, 0, 0)
    j = b.joints()
    assert foot_bottom(b) == pytest.approx(0, abs=0.02)
    assert j["ankle_l"][2] == pytest.approx(j["toe_l"][2], abs=0.02)  # 뒤꿈치를 들지 않는다 (명세 정할 것 1)
    assert min(v[2] for v in b.joints().values()) >= -0.02


def test_squat_self_overlap_only_at_knee():
    b = s3.pose(squat.POSTURE, 0, 0)
    caps, j = {c.segment: c for c in b.capsules()}, b.joints()
    # 같은 다리의 넓적다리 · 정강이는 무릎 0.2m 밖에서 닿지 않는다 (무릎 둘레 겹침은 자기 몸 겹침에서 뺀다)
    for s in ("l", "r"):
        th, sh = caps["thigh_" + s], caps["shin_" + s]
        for t in (0.5, 0.75, 1.0):
            p = s3.body.add(sh.a, s3.body.mul(s3.body.sub(sh.b, sh.a), t))
            assert s3.body.dist(p, j["knee_" + s]) > 0.2
            assert s3.penetration(s3.Capsule("p", p, p, sh.r), th) == 0
        assert s3.penetration(caps["foot_" + s], th) == 0
    for a, c in [("thigh_l", "thigh_r"), ("shin_l", "shin_r"), ("foot_l", "foot_r")]:
        assert s3.penetration(caps[a], caps[c]) <= 0.03, (a, c)


def test_squat_reaches_floor_ahead():
    # 명세의 1.0m 는 숙임 20° 로 닿지 않는다(틈 0.2m). 닿는 끝은 골반 앞 약 0.7m 다. 서면 같은 점에 0.7m 넘게 모자란다
    target = (0, 0.7, 0.05)
    b = s3.pose(squat.POSTURE, 0, 0)
    assert s3.reach_to(b, "r", target) < 0.01
    st = s3.pose(fake.POSTURES["stand"].angles, 0, 0)
    assert s3.reach_to(st, "r", target, reach=squat.POSTURE.reach) > 0.5


# ---------- 무릎 꿇기 ----------

@pytest.mark.parametrize("base", [0.0, 0.5])
def test_kneel_knee_and_toe_on_surface(base):
    b = s3.pose(kneel.POSTURE, 0, 0, 0, base)
    j = b.joints()
    for s in ("l", "r"):
        assert b.part_point("knee_" + s)[2] == pytest.approx(base, abs=0.02)
        assert j["toe_" + s][2] == pytest.approx(base, abs=0.02)


def test_kneel_thigh_vertical():
    j = s3.pose(kneel.POSTURE, 0, 0).joints()
    for s in ("l", "r"):
        d = [j["knee_" + s][i] - j["hip_" + s][i] for i in range(3)]
        tilt = math.degrees(math.acos(-d[2] / math.sqrt(sum(v * v for v in d))))
        assert tilt <= 5


def test_kneel_on_bed():
    _, b = frame(StageAnchor(id="a1", name="침대", kind="bed", x=1.0, y=1.0, w=1.4, h=2.0, sit=True, lie=True), "kneel")
    assert b.base == pytest.approx(0.5)
