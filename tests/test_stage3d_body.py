"""장면 연출 3D 뼈대 계약 (docs/stage/3d/specs/01-body.md). 가짜 자세 · 장소로 돈다. LLM 호출 없음."""
import json
import math
import time

import pytest

from canon import stage
from canon import stage3d as s3
from canon.schema import StageAnchor, StageBeat, StageBody, StageContact, StageScene, StageSpot
from canon.stage3d import body as bd, fake, furniture
from canon.stage3d.body import Angles, Reach


def close(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# ---------- FK ----------

def test_standing_height():
    b = s3.pose(Angles(), 1.0, 2.0)
    assert b.head_top() == pytest.approx(1.72, abs=0.02)
    assert min(v[2] for v in b.joints().values()) == pytest.approx(0.0, abs=0.02)
    assert set(b.joints()) == set(s3.JOINTS)


def test_fk_hip_knee_90():
    j = s3.pose(Angles(hip=(90, 90), knee=(90, 90)), 0, 0).joints()
    d = [j["ankle_l"][i] - j["hip_l"][i] for i in range(3)]
    assert d == pytest.approx([0, 0.44, -0.46], abs=0.005)  # 앞(+y) 0.44, 아래 0.46


def test_left_is_left_and_yaw_turns_front():
    # 향함 (0, 1) 이면 왼쪽은 (fy, -fx) = (1, 0)
    j = s3.pose(Angles(), 0, 0).joints()
    assert j["shoulder_l"][0] > j["shoulder_r"][0]
    # 오른쪽(+x)을 보면 발끝도 +x 쪽
    j = s3.pose(Angles(), 0, 0, yaw=math.pi / 2).joints()
    assert j["toe_l"][0] - j["ankle_l"][0] == pytest.approx(0.17, abs=0.01)


def test_shift_moves_along_facing():
    a = s3.pose(Angles(shift=-0.13), 0, 0).joints()["pelvis"]
    assert a[:2] == pytest.approx((0, -0.13))


# ---------- IK ----------

def shoulder(b, side):
    return b.joints()["shoulder_" + side]


def test_ik_reaches_inside():
    b = s3.pose(Angles(), 0, 0)
    for side in ("l", "r"):
        sh = shoulder(b, side)
        t = (sh[0], sh[1] + 0.4, sh[2] - 0.1)
        assert s3.reach_to(b, side, t, reach=Reach(0, 0)) < 0.01
        assert bd.dist(b.joints()["hand_" + side], t) < 0.01


def test_ik_outside_straight_arm():
    b = s3.pose(Angles(), 0, 0)
    sh = shoulder(b, "l")
    t = (sh[0], sh[1] + 1.0, sh[2])
    gap = s3.reach_to(b, "l", t, reach=Reach(0, 0))
    assert gap > 0.3
    assert bd.dist(b.joints()["hand_l"], sh) == pytest.approx(s3.ARM, abs=0.005)
    assert gap == pytest.approx(1.0 - s3.ARM, abs=0.01)


@pytest.mark.parametrize("pole", [None, (0, 1, 0), (0, 0, 1), (1, 0, 0)])
@pytest.mark.parametrize("side", ["l", "r"])
def test_ik_elbow_toward_pole(side, pole):
    # pole 은 몸통 좌표 (+x 바깥, +y 위, +z 앞). 향함 (0, 1) 이면 바깥 좌표로 (sx·px, pz, py)
    b = s3.pose(Angles(), 0, 0)
    sh = shoulder(b, side)
    t = (sh[0], sh[1] + 0.35, sh[2] - 0.2)
    s3.reach_to(b, side, t, pole=pole, reach=Reach(0, 0))
    p = pole or bd.DEFAULT_POLE
    sx = 1 if side == "l" else -1
    pw = (sx * p[0], p[2], p[1])
    axis = bd.unit(bd.sub(t, sh))
    e = bd.sub(b.joints()["elbow_" + side], sh)
    e_perp = bd.sub(e, bd.mul(axis, bd.dot(e, axis)))
    p_perp = bd.sub(pw, bd.mul(axis, bd.dot(pw, axis)))
    assert bd.dot(e_perp, p_perp) > 0  # 팔꿈치가 pole 쪽 반공간에 (시안 첫판은 반대였다)


def test_lean_closes_small_gap():
    b = s3.pose(Angles(), 0, 0)
    sh = shoulder(b, "l")
    # 어깨에서 0.75m (팔보다 0.1m 멀다), 앞 아래
    t = (sh[0], sh[1] + math.sqrt(0.75 ** 2 - 0.48 ** 2), sh[2] - 0.48)
    assert bd.dist(sh, t) == pytest.approx(s3.ARM + 0.1, abs=0.001)
    gap = s3.reach_to(b, "l", t, reach=Reach(lean=30, twist=45))
    assert gap < 0.01
    assert 0 < b.lean <= 30 + 1e-6


def test_lean_capped():
    b = s3.pose(Angles(), 0, 0)
    sh = shoulder(b, "l")
    gap = s3.reach_to(b, "l", (sh[0], sh[1] + 0.5, 0.0), reach=Reach(lean=10, twist=0))
    assert gap > 0
    assert b.lean <= 10 + 1e-6


def test_lying_does_not_lean():
    b = s3.pose(fake.POSTURES["lie"], 0, 0)
    gap = s3.reach_to(b, "l", (0, 2.0, 1.0))
    assert gap > 0
    assert b.lean == 0
    assert b.twist == 0


# ---------- 부위 점 · 캡슐 ----------

def test_part_points_cover_parts():
    assert set(s3.PART_POINTS) == set(stage.PARTS)
    assert set(s3.PART_SEGMENT) == set(stage.PARTS)
    assert set(s3.PART_SEGMENT.values()) <= set(s3.SEGMENTS)
    b = s3.pose(Angles(), 0, 0)
    for pid in stage.PARTS:
        assert len(b.part_point(pid)) == 3
    assert b.part_point("cheek_l")[0] > b.part_point("cheek_r")[0]  # 쌍은 바깥이 뒤집힌다
    assert b.part_point("chest")[1] > b.part_point("back")[1]       # 가슴은 앞(+y), 등은 뒤
    assert s3.PART_SEGMENT["wrist_r"] == "forearm_r"


def test_capsules_one_per_segment():
    caps = s3.capsules(s3.pose(Angles(), 0, 0))
    assert [c.segment for c in caps] == list(s3.SEGMENTS)
    feet = [c for c in caps if c.segment.startswith("foot")]
    assert all(min(c.a[2], c.b[2]) - c.r == pytest.approx(0, abs=0.01) for c in feet)  # 발바닥이 바닥에


# ---------- 가구 ----------

@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_solids_backrest_behind(rot):
    room = stage.make_room("empty", "r1")
    room.anchors = [StageAnchor(id="a1", name="의자", kind="chair", x=1.0, y=1.0, w=0.5, h=0.6, rot=rot, sit=True)]
    sol = furniture.solids(room)
    assert [s.anchor for s in sol] == ["a1", "a1"]
    back = sol[1].box
    fx, fy = stage._front(rot)
    c = (1.25, 1.3)
    bc = ((back[0] + back[3]) / 2, (back[1] + back[4]) / 2)
    assert (bc[0] - c[0]) * fx + (bc[1] - c[1]) * fy < -0.1  # 등받이는 앞의 반대쪽
    seat = sol[0].box
    assert close(seat[:2] + seat[3:5], (1.0, 1.0, 1.5, 1.6), 1e-9)  # 평면 자리는 rot 과 상관없이 기준점 자리


def test_lookup_name_then_kind_then_other():
    a = StageAnchor(id="a1", name="침대", kind="bed", sit=True, lie=True)
    spec = s3.RoomSpec("bedroom", anchors={"침대": fake.BLOCK})
    assert furniture.lookup(a, spec) is fake.BLOCK
    assert furniture.lookup(a.model_copy(update={"name": "큰 침대"}), spec) is s3.KINDS["bed"]
    assert furniture.lookup(a.model_copy(update={"kind": "lamp"}), None) is s3.KINDS["other"]
    assert s3.KINDS["other"].boxes[0].z1 == 0.8
    assert furniture.surface(a, None, "lie") == 0.5
    assert furniture.surface(a.model_copy(update={"sit": False}), None, "seat") is None
    assert furniture.surface(StageAnchor(id="d", name="책상", kind="desk"), None, "top") == 0.75


# ---------- 겹침 ----------

def test_penetration():
    ball = s3.Capsule("head", (0, 0, 0.5), (0, 0, 0.5), 0.1)
    assert s3.penetration(ball, (1, 1, 1, 2, 2, 2)) == 0
    lying = s3.Capsule("torso", (0, 0, 1.0), (0, 1, 1.0), 0.1)  # 선분이 상자 윗면 위에
    assert s3.penetration(lying, (-1, -1, 0, 1, 2, 1.0)) == pytest.approx(0.1, abs=1e-6)
    assert s3.penetration(lying, s3.Solid("a", (-1, -1, 0, 1, 2, 0.95))) == pytest.approx(0.05, abs=1e-6)
    inside = s3.Capsule("torso", (0, 0, 0.5), (0, 0, 0.6), 0.1)
    assert s3.penetration(inside, (-0.3, -0.3, 0, 0.3, 0.3, 1)) == pytest.approx(0.4, abs=1e-6)
    a = s3.Capsule("thigh_l", (0, 0, 0), (0, 1, 0), 0.1)
    assert s3.penetration(a, s3.Capsule("thigh_r", (0.15, 0, 0), (0.15, 1, 0), 0.1)) == pytest.approx(0.05)
    assert s3.penetration(a, s3.Capsule("thigh_r", (0.5, 0, 0), (0.5, 1, 0), 0.1)) == 0
    crossed = s3.Capsule("x", (-1, 0.5, 0.05), (1, 0.5, 0.05), 0.02)
    assert s3.penetration(a, crossed) == pytest.approx(0.07)


# ---------- frames ----------

def scene_two():
    """하린이 의자에 앉고 도윤이 문 앞에 섰다가 다가와 손목을 잡는다. 지수는 가짜 등록부에 없는 '옆으로 눕기'."""
    room = stage.make_room("bedroom", "r1")
    sc = StageScene(id="s1", room="r1", cast=["h", "d", "j"], start=[
        StageBody(who="h", at=StageSpot(ref="a3", rel="on"), posture="chair", facing="#a2", left="", right=""),
        StageBody(who="d", at=StageSpot(ref="a5", rel="front"), posture="stand", facing="@h", left="", right=""),
        StageBody(who="j", at=StageSpot(ref="a1", rel="on"), posture="side", facing="n", left="", right=""),
    ], beats=[
        StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref="@h", rel="front"))]),
        StageBeat(bodies=[StageBody(who="d", contacts=[StageContact(id="c1", by="right", to="h", part="wrist_l", act="hold")])]),
        StageBeat(bodies=[StageBody(who="h", contacts=[StageContact(id="c2", by="both", to="d", part="back", act="hug")])]),
    ])
    return sc, room


def test_frames_shape():
    sc, room = scene_two()
    before = (sc.model_dump(), room.model_dump())
    fr = s3.frames(sc, room, postures=fake.POSTURES, rooms=fake.ROOMS)
    assert (sc.model_dump(), room.model_dump()) == before  # 장면 · 방을 바꾸지 않는다
    d = fr.to_dict()
    json.dumps(d)
    assert set(d) == {"ceiling", "solids", "beats"}
    assert d["ceiling"] == 2.4
    assert {"anchor", "box", "solid"} == set(d["solids"][0]) and len(d["solids"][0]["box"]) == 6
    assert [b["k"] for b in d["beats"]] == [0, 1, 2, 3]
    b0 = d["beats"][0]
    assert set(b0) == {"k", "bodies", "contacts"}
    h = b0["bodies"]["h"]
    assert set(h) == {"posture", "missing", "attach", "joints"}
    assert set(h["joints"]) == set(s3.JOINTS)
    assert h["joints"]["pelvis"][2] == pytest.approx(0.45 + 0.08, abs=0.001)  # 의자 앉는 면 위
    assert b0["bodies"]["j"] == {"posture": "side", "missing": "side", "attach": None, "joints": None}
    c = d["beats"][2]["contacts"]
    assert len(c) == 1 and set(c[0]) == {"id", "who", "to", "part", "hands", "gap", "points"}
    assert c[0]["hands"] == ["r"] and c[0]["gap"] >= 0 and len(c[0]["points"]) == 2
    hug = [x for x in d["beats"][3]["contacts"] if x["id"] == "c2"][0]
    assert hug["hands"] == ["l", "r"] and len(hug["points"]) == 4
    assert s3.frames(sc, room, postures=fake.POSTURES, rooms=fake.ROOMS).to_dict() == d  # 같은 입력이면 같은 결과


def test_frames_same_plan_as_stage_place():
    sc, room = scene_two()
    fr = s3.frames(sc, room, postures=fake.POSTURES, rooms=fake.ROOMS)
    for b in fr.beats:
        assert b.pos == stage.place(room, stage.state_at(sc, b.k), sc.cast)
        d = b.bodies["d"].body.joints()["pelvis"]
        assert d[:2] == pytest.approx(b.pos["d"])  # 서기는 옮김 없음


def test_frames_registry_monkeypatch(monkeypatch):
    from canon.stage3d import postures, rooms
    monkeypatch.setattr(postures, "load", lambda: fake.POSTURES)
    monkeypatch.setattr(rooms, "load", lambda: {"bedroom": s3.RoomSpec("bedroom", 2.1)})
    sc, room = scene_two()
    fr = s3.frames(sc, room)
    assert fr.ceiling == 2.1 and fr.beats[0].bodies["h"].body is not None
    assert s3.missing() == {"postures": [k for k in stage.POSTURES if k not in fake.POSTURES], "rooms": [k for k in stage.ROOMS if k != "bedroom"]}
    assert not s3.complete()


def test_top_only_on_and_lie_surface():
    room = stage.make_room("bedroom", "r1")
    for rel, posture, base in (("on", "stand", 0.5), ("in", "stand", 0.0), ("on", "lie", 0.5), ("front", "chair", 0.0)):
        sc = StageScene(id="s", room="r1", cast=["a"], start=[StageBody(who="a", at=StageSpot(ref="a1", rel=rel), posture=posture, facing="s")])
        b = s3.frames(sc, room, postures=fake.POSTURES, rooms=fake.ROOMS).beats[0].bodies["a"].body
        assert b.base == pytest.approx(base), (rel, posture)


def test_feet_to_floor_low_seat():
    room = stage.make_room("car", "r1")
    spec = s3.RoomSpec("car", 1.2, {"운전석": s3.Furniture((s3.Box(0, 1, 0, 1, 0, 0.3),), seat=0.3)})
    sc = StageScene(id="s", room="r1", cast=["a"], start=[StageBody(who="a", at=StageSpot(ref="a1", rel="on"), posture="chair", facing="n")])
    b = s3.frames(sc, room, postures=fake.POSTURES, rooms={"car": spec}).beats[0].bodies["a"].body
    j = b.joints()
    assert j["ankle_l"][2] == pytest.approx(0, abs=0.01) and j["ankle_r"][2] == pytest.approx(0, abs=0.01)
    assert b.knee[0] < 90  # 발을 앞으로 뻗는다


def test_place_hook_and_attach():
    def hang(ctx: s3.PlaceCtx) -> s3.Placement:
        ref = ctx.now.at.ref[1:]
        p = ctx.bodies[ref].joints()["pelvis"]
        return s3.Placement(p[0], p[1] - 0.3, ctx.bodies[ref].yaw, p[2] + 0.12 - 1.05, attach=ref)

    held = s3.PostureSpec("held", Angles(1.05, hip=(75, 75), knee=(85, 85)), ("carrier",), place_hook=hang)
    room = stage.make_room("empty", "r1")
    sc = StageScene(id="s", room="r1", cast=["b", "a"], start=[
        StageBody(who="b", at=StageSpot(ref="@a", rel="back"), posture="held", facing="s"),
        StageBody(who="a", at=StageSpot(ref="a1", rel="front"), posture="stand", facing="s"),
    ], beats=[StageBeat(bodies=[StageBody(who="a", contacts=[StageContact(id="c1", by="both", to="b", part="thigh_l", act="carry")])])])
    fr = s3.frames(sc, room, postures={**fake.POSTURES, "held": held}, rooms=fake.ROOMS)
    b = fr.beats[1].bodies["b"]
    assert b.attach == "a"
    pa, pb = fr.beats[1].bodies["a"].body.joints()["pelvis"], b.body.joints()["pelvis"]
    assert pb[2] - pa[2] == pytest.approx(0.12, abs=0.001)
    c = fr.beats[1].contacts[0]
    assert c.hands == ["l", "r"]
    assert c.points[1] == pytest.approx(b.body.part_point("knee_l"))  # 업은 손은 업힌 무릎으로


def test_frames_speed():
    room = stage.make_room("living", "r1")
    cast = ["a", "b", "c", "d"]
    start = [StageBody(who=w, at=StageSpot(ref=f"a{i + 1}", rel="front"), posture="stand", facing="s") for i, w in enumerate(cast)]
    beats = []
    for k in range(20):
        w, o = cast[k % 4], cast[(k + 1) % 4]
        beats.append(StageBeat(bodies=[StageBody(who=w, at=StageSpot(ref="@" + o, rel="front"), facing="@" + o,
                                                 contacts=[StageContact(id=f"c{k}", by="right", to=o, part="hand_l", act="hold")],
                                                 ends=[f"c{k - 4}"] if k >= 4 else [])]))
    sc = StageScene(id="s", room="r1", cast=cast, start=start, beats=beats)
    s3.frames(sc, room, postures=fake.POSTURES, rooms=fake.ROOMS)
    t = time.perf_counter()
    s3.frames(sc, room, postures=fake.POSTURES, rooms=fake.ROOMS)
    took = time.perf_counter() - t
    print(f"frames 4명 · 20박자: {took * 1000:.1f}ms")
    assert took < 0.5  # 제안값은 50ms. 느린 CI 를 위해 넉넉히 두고 실제 값은 위에 찍는다
