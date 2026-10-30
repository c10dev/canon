"""장면 연출 3D 자세 묶음 P1: 서기 · 걷기 · 뛰기 · 기대 서기 (docs/stage/3d/specs/postures/).

명세서 '시험' 줄의 수치를 본다. 계약 검사는 tests/test_stage3d_contract.py 가 등록부를 훑어 한다. LLM 호출 없음.
"""
import math

import pytest

from canon import stage
from canon import stage3d as s3
from canon.schema import StageBody, StageScene, StageSpot
from canon.stage3d import body as bd
from canon.stage3d import furniture
from canon.stage3d.postures import lean, run, stand, walk

P1 = {"stand": stand, "walk": walk, "run": run, "lean": lean}
# 마디가 이어져 늘 겹치는 캡슐 짝: 자기 몸 겹침에서 뺀다
JOINED = {frozenset(p) for p in [("head", "torso"), ("torso", "pelvis"), ("torso", "upper_arm_l"), ("torso", "upper_arm_r"),
                                  ("upper_arm_l", "forearm_l"), ("upper_arm_r", "forearm_r"), ("pelvis", "thigh_l"), ("pelvis", "thigh_r"),
                                  ("thigh_l", "shin_l"), ("thigh_r", "shin_r"), ("shin_l", "foot_l"), ("shin_r", "foot_r")]}


def feet(b: bd.Body) -> tuple[float, float]:
    """두 발 높이 (발목 · 발끝 가운데 낮은 쪽), 낮은 발이 먼저."""
    j = b.joints()
    h = [min(j["ankle_" + s][2], j["toe_" + s][2]) for s in ("l", "r")]
    return min(h), max(h)


def self_overlap(b: bd.Body) -> float:
    caps = b.capsules()
    return max((bd.penetration(a, c) for i, a in enumerate(caps) for c in caps[i + 1:]
                if frozenset((a.segment, c.segment)) not in JOINED), default=0.0)


@pytest.mark.parametrize("pid", sorted(P1))
def test_registered_and_contract(pid):
    specs = s3.posture_specs()
    assert specs[pid] is P1[pid].POSTURE
    assert pid not in s3.missing()["postures"]
    assert specs[pid].id == pid and pid in stage.POSTURES  # 나머지 계약 검사는 test_stage3d_contract 가 등록부를 훑어 한다


@pytest.mark.parametrize("pid", sorted(P1))
def test_no_self_overlap(pid):
    assert self_overlap(s3.pose(P1[pid].POSTURE, 0, 0)) <= 0.03


@pytest.mark.parametrize("pid", sorted(P1))
def test_deterministic(pid):
    a, b = s3.pose(P1[pid].POSTURE, 1, 2, 0.3), s3.pose(P1[pid].POSTURE, 1, 2, 0.3)
    assert a.joints() == b.joints()


def test_spec_fields():
    assert stand.POSTURE.surface == ("floor", "top") and stand.POSTURE.reach == bd.Reach(30, 45)
    assert walk.POSTURE.surface == ("floor",) and walk.POSTURE.reach == bd.Reach(20, 30)
    assert run.POSTURE.surface == ("floor",) and run.POSTURE.reach == bd.Reach(15, 20)
    assert lean.POSTURE.surface == ("back_support",) and lean.POSTURE.reach == bd.Reach(10, 30)
    assert lean.POSTURE.place_hook is not None
    assert all(P1[p].POSTURE.place_hook is None for p in ("stand", "walk", "run"))


# ---------- 서기 ----------

def test_stand_height_and_feet():
    b = s3.pose(stand.POSTURE, 0, 0)
    assert b.head_top() == pytest.approx(1.72, abs=0.02)
    lo, hi = feet(b)
    assert abs(lo) <= 0.02 and abs(hi) <= 0.02


def _scene(who_at: StageSpot, posture: str, facing: str = "") -> StageScene:
    return StageScene(id="s1", cast=["h"], start=[StageBody(who="h", at=who_at, posture=posture, facing=facing)])


def test_stand_on_bed_top():
    room = stage.make_room("bedroom", "r1")
    bed = next(a for a in room.anchors if a.kind == "bed")
    f = s3.frames(_scene(StageSpot(ref=bed.id, rel="on"), "stand"), room, rooms={})
    b = f.beats[0].bodies["h"].body
    assert feet(b)[0] == pytest.approx(0.5, abs=0.02)
    assert b.head_top() == pytest.approx(2.22, abs=0.03)


def test_stand_reach():
    """0.75m 앞 높이 1.0m 는 숙이고 닿는다. 1.0m 앞 바닥(0.05m)은 숙여도 모자란다 (무릎을 굽혀야 한다).
    명세서는 '1.0m 앞 높이 1.0m 는 틈 0' 이지만 마디 길이와 숙임 30° 로는 0.75m 까지 닿는다 (1.0m 는 틈 0.2m)."""
    b = s3.pose(stand.POSTURE, 0, 0)  # 앞이 +y
    assert s3.reach_to(b, "r", (0.0, 0.75, 1.0)) <= 0.01
    assert b.lean <= stand.POSTURE.reach.lean + 1e-6
    b = s3.pose(stand.POSTURE, 0, 0)
    assert s3.reach_to(b, "r", (0.0, 1.0, 0.05)) > 0.05
    assert b.lean == pytest.approx(stand.POSTURE.reach.lean, abs=1e-6)


# ---------- 걷기 · 뛰기 ----------

def test_walk_feet_and_pelvis():
    b = s3.pose(walk.POSTURE, 0, 0)
    lo, hi = feet(b)
    assert abs(lo) <= 0.02 and hi <= 0.10
    assert walk.POSTURE.angles.pelvis_h == pytest.approx(stand.POSTURE.angles.pelvis_h - 0.02)
    j = b.joints()
    assert j["ankle_l"][1] < 0 < j["ankle_r"][1]  # 왼발 뒤 · 오른발 앞
    assert j["hand_l"][1] > 0 > j["hand_r"][1]    # 팔은 다리와 엇갈린다


def test_run_feet_and_arms():
    b = s3.pose(run.POSTURE, 0, 0)
    lo, _ = feet(b)
    assert 0 <= lo <= 0.05
    caps = {c.segment: c for c in b.capsules()}
    for s in ("l", "r"):  # 팔꿈치 85° 아래팔이 몸통에 닿지 않는다
        assert bd.penetration(caps["forearm_" + s], caps["torso"]) == 0
    assert s3.pose(run.POSTURE, 0, 0).joints()["pelvis"][2] < s3.pose(walk.POSTURE, 0, 0).joints()["pelvis"][2]


def test_reach_margins_shrink_with_speed():
    r = [P1[p].POSTURE.reach for p in ("stand", "walk", "run")]
    assert r[0].lean > r[1].lean > r[2].lean and r[0].twist > r[1].twist > r[2].twist


# ---------- 기대 서기 ----------

def _ctx(room, xy, facing="", at=None, yaw=None) -> bd.PlaceCtx:
    now = stage.Now(at=at, posture="lean", facing=facing)
    if yaw is None:
        v = stage.facing_vec(facing, xy, room, {"h": xy}) or (0.0, 1.0)
        yaw = math.atan2(v[0], v[1])
    return bd.PlaceCtx("h", now, {"h": now}, {"h": xy}, xy, yaw, 0.0, room, None, furniture.solids(room), {})


def _back_gap(b: bd.Body, n: tuple[float, float], plane: float, axis: int) -> float:
    """윗몸 캡슐 겉에서 면까지 가장 가까운 거리 (법선 n 쪽이 방 안)."""
    sign = n[axis]
    caps = [c for c in b.capsules() if c.segment in lean._UPPER]
    return min(min((c.a[axis] - plane) * sign, (c.b[axis] - plane) * sign) - c.r for c in caps)


def test_lean_against_door():
    room = stage.make_room("empty", "r1")  # 문은 아래 벽, 앞이 위(rot 180)
    door = room.anchors[0]
    for facing in ("", "n", "@x"):
        f = s3.frames(_scene(StageSpot(ref=door.id, rel="against"), "lean", facing), room, rooms={})
        b = f.beats[0].bodies["h"].body
        assert b.yaw == pytest.approx(math.pi)  # 몸 앞이 위 (0, -1): 문을 등진다
        gap = _back_gap(b, (0.0, -1.0), door.y, 1)
        assert 0 <= gap <= 0.05, (facing, gap)
        j = b.joints()
        assert j["ankle_r"][1] > j["ankle_l"][1]  # 오른발이 왼발보다 문 쪽 (굽혀 올린다)


def test_lean_against_door_facing_it():
    """문을 보고 기대면 등을 대지 않고 그 자리에 둔다 (판정이 짚는다)."""
    room = stage.make_room("empty", "r1")
    door = room.anchors[0]
    ctx = _ctx(room, stage._anchor_point(door, "against"), facing="s", at=StageSpot(ref=door.id, rel="against"))
    assert lean.find_back(ctx) is None
    p = lean.place(ctx)
    assert (p.x, p.y, p.yaw) == (ctx.xy[0], ctx.xy[1], ctx.yaw)


def test_lean_finds_room_wall():
    room = stage.make_room("empty", "r1")  # 4 × 3, 문은 아래 벽
    ctx = _ctx(room, (0.3, 1.5), facing="e")  # 왼쪽 벽 앞 0.3m, 오른쪽을 본다
    face = lean.find_back(ctx)
    assert face is not None and face[0] == (1.0, 0.0)
    p = lean.place(ctx)
    assert p.x == pytest.approx(lean.BACK + lean.GAP) and p.y == pytest.approx(1.5)
    assert p.yaw == pytest.approx(math.pi / 2)
    b = s3.pose(lean.POSTURE, p.x, p.y, p.yaw)
    assert 0 <= _back_gap(b, (1.0, 0.0), 0.0, 0) <= 0.05
    j = b.joints()
    assert j["ankle_r"][0] < j["ankle_l"][0]  # 오른발이 벽 쪽


def test_lean_wall_rules():
    room = stage.make_room("empty", "r1")
    assert lean.find_back(_ctx(room, (2.0, 1.5))) is None                # 방 가운데: 못 찾는다
    assert lean.find_back(_ctx(room, (0.3, 1.5), facing="w")) is None    # 벽을 본다
    assert lean.find_back(_ctx(room, (0.3, 1.5), facing="ne")) is not None  # 벽 반대쪽 ±90° 안
    # 향함을 모르면 가장 가까운 면을 등진다
    face = lean.find_back(_ctx(room, (3.8, 1.5)))
    assert face is not None and face[0] == (-1.0, 0.0)


def test_lean_finds_furniture():
    """기준점이 아니어도 등 뒤의 높은 가구를 찾는다. 낮은 가구는 기댈 면이 아니다."""
    room = stage.make_room("bedroom", "r1")
    desk = next(a for a in room.anchors if a.kind == "desk")  # 판 0.75m
    ctx = _ctx(room, (desk.x + desk.w / 2, desk.y + desk.h + 0.3), facing="s")
    face = lean.find_back(ctx)
    assert face is not None and face[0] == (0.0, 1.0)
    assert face[1] == pytest.approx(0.3)
    bed = next(a for a in room.anchors if a.kind == "bed")  # 옆면은 매트리스 0.5m 뿐
    assert lean.find_back(_ctx(room, (bed.x + bed.w + 0.3, bed.y + 1.0), facing="e")) is None


def test_lean_without_support_in_frames():
    room = stage.make_room("empty", "r1")
    scene = StageScene(id="s1", cast=["h", "d"], start=[
        StageBody(who="d", at=StageSpot(ref=room.anchors[0].id, rel="front"), facing="n"),
        StageBody(who="h", at=StageSpot(ref="@d", rel="front"), posture="lean")])
    f = s3.frames(scene, room, rooms={})
    b = f.beats[0].bodies["h"].body
    x, y = f.beats[0].pos["h"]
    assert (b.x, b.y) == pytest.approx((x, y))  # 그 자리 그대로
