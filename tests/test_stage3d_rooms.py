"""장면 연출 3D 장소 모듈 7개 시험 (docs/stage/3d/specs/03-room.md, specs/rooms/<틀>.md).

자세 모듈이 아직 없어도 돌게 01 의 시험용 가짜 자세(fake.POSTURES)를 쓴다. 판정(04)을 기다리지 않고 penetration() 으로 잰다. LLM 호출 없음.
"""
import pytest

from canon import stage
from canon import stage3d as s3
from canon.schema import StageAnchor, StageBody, StageScene, StageSpot
from canon.stage3d import fake, furniture
from tests.test_stage3d_contract import check_room

TOL = 0.05       # 몸 · 가구 문턱 (README 정할 것 5)
BODY_TOL = 0.03  # 몸 · 몸 문턱
BODY_R = 0.15    # 선 사람 반폭: 2D 자리가 다른 가구 평면에 걸치는지 볼 때

SEAT = {"bedroom": {"침대": 0.5, "의자": 0.45}, "living": {"소파": 0.42}, "office": {"의자": 0.45, "손님 의자": 0.45},
        "classroom": {"앞자리": 0.43, "뒷자리": 0.43, "창가 자리": 0.43}, "car": {"운전석": 0.30, "조수석": 0.30, "뒷좌석": 0.30},
        "carriage": {"앞좌석": 0.45, "뒷좌석": 0.45}, "empty": {}}
LIE = {"bedroom": {"침대": 0.5}, "living": {"소파": 0.42}, "car": {"뒷좌석": 0.30}}
CEILING = {"bedroom": 2.4, "living": 2.4, "classroom": 3.0, "office": 2.6, "car": 1.15, "carriage": 1.6, "empty": 2.4}


def spec(t):
    return s3.room_specs()[t]


def anchor(room, name):
    return next(a for a in room.anchors if a.name == name)


def seat_facing(room, ref):
    """기준점 앞쪽을 보는 8방향 (앉은 사람은 좌석 앞을 본다)."""
    a = next(a for a in room.anchors if a.id == ref)
    v = stage._front(a.rot)
    return min(stage.FACINGS, key=lambda k: (stage._FACING_VEC[k][0] - v[0]) ** 2 + (stage._FACING_VEC[k][1] - v[1]) ** 2)


def frame(room, people, postures=fake.POSTURES):
    """people: [(who, ref, rel, posture, facing)] → 시작 상태 한 박자. on 에 향함을 비우면 기준점 앞을 본다."""
    sc = StageScene(id="s", room=room.id, cast=[p[0] for p in people],
                    start=[StageBody(who=w, at=StageSpot(ref=ref, rel=rel), posture=pz,
                                     facing=f or (seat_facing(room, ref) if rel == "on" else f)) for w, ref, rel, pz, f in people])
    return s3.frames(sc, room, postures=postures)


def body(fr, who="a"):
    return fr.beats[0].bodies[who].body


def hits(fr, who="a", skip=()):
    """(깊이, 몸 캡슐, 기준점 id) 중 문턱을 넘는 것."""
    return [(round(d, 3), c.segment, s.anchor) for c in s3.capsules(body(fr, who)) for s in fr.solids
            if s.solid and s.anchor not in skip and (d := s3.penetration(c, s)) > TOL]


def crowded(room, xy):
    """2D 자리가 걸치는 다른 기준점 id: 틀의 평면 배치 문제라 3D 장소 모듈이 고칠 수 없다."""
    x, y = xy
    return {a.id for a in room.anchors
            if a.x - BODY_R < x < a.x + a.w + BODY_R and a.y - BODY_R < y < a.y + a.h + BODY_R}


def head_dir(a: StageAnchor, f: s3.Furniture):
    fx, fy = stage._front(a.rot)
    return {"back": (-fx, -fy), "right": (fy, -fx), "left": (-fy, fx)}[f.head]


def lie_along(room, a, f):
    """가짜 눕기는 Furniture.head 를 모르니, 머리가 head 쪽으로 가는 향함을 골라 눕힌다."""
    hx, hy = head_dir(a, f)
    for fc in ("n", "e", "s", "w"):
        fr = frame(room, [("a", a.id, "on", "lie", fc)])
        j = body(fr).joints()
        if (j["head"][0] - j["pelvis"][0]) * hx + (j["head"][1] - j["pelvis"][1]) * hy > 0.5:
            return fr
    raise AssertionError("머리가 head 쪽으로 가는 향함이 없어요")


# ---------- 등록부 · 계약 ----------

def test_registry_has_seven():
    assert set(s3.room_specs()) == set(stage.ROOMS)
    assert s3.missing()["rooms"] == []


@pytest.mark.parametrize("t", sorted(stage.ROOMS))
def test_contract_and_ceiling(t):
    check_room(t, spec(t))
    assert spec(t).ceiling == CEILING[t]


@pytest.mark.parametrize("t", sorted(stage.ROOMS))
def test_every_anchor_has_shape(t):
    """틀의 기준점마다 3D 모양이 있다 (이름 덮어쓰기 또는 종류 기본값)."""
    room = stage.make_room(t, "r1")
    sol = furniture.solids(room, spec(t))
    for a in room.anchors:
        f = furniture.lookup(a, spec(t))
        assert f is spec(t).anchors.get(a.name) or f is s3.KINDS[a.kind], a.name
        assert any(s.anchor == a.id for s in sol), a.name


@pytest.mark.parametrize("t", sorted(stage.ROOMS))
def test_seat_and_lie_heights(t):
    room = stage.make_room(t, "r1")
    seats = {a.name: furniture.surface(a, spec(t), "seat") for a in room.anchors if a.sit}
    lies = {a.name: furniture.surface(a, spec(t), "lie") for a in room.anchors if a.lie}
    assert seats == pytest.approx(SEAT[t])
    assert lies == pytest.approx(LIE.get(t, {}))


@pytest.mark.parametrize("t", sorted(stage.ROOMS))
def test_renamed_anchor_falls_back_to_kind(t):
    room = stage.make_room(t, "r1")
    for a in room.anchors:
        renamed = a.model_copy(update={"name": "큰 " + a.name})
        assert furniture.lookup(renamed, spec(t)) is s3.KINDS[a.kind]
    extra = StageAnchor(id="x", name="화분", kind="other", x=0, y=0, w=0.4, h=0.4)
    assert furniture.top(furniture.lookup(extra, spec(t))) == pytest.approx(0.8)


@pytest.mark.parametrize("t", sorted(stage.ROOMS))
def test_furniture_inside_room(t):
    room = stage.make_room(t, "r1")
    for s in furniture.solids(room, spec(t)):
        x0, y0, z0, x1, y1, z1 = s.box
        assert -1e-6 <= x0 and x1 <= room.w + 1e-6 and -1e-6 <= y0 and y1 <= room.h + 1e-6, (s.anchor, s.box)
        assert 0 <= z0 < z1 <= spec(t).ceiling, (s.anchor, s.box)


# ---------- 빈자리 시험 (03-room.md) ----------

@pytest.mark.parametrize("t", sorted(stage.ROOMS))
def test_stand_in_front_is_clear(t):
    """기준점 앞에 선 사람은 가구에 5cm 넘게 파고들지 않는다. 2D 자리가 다른 가구 평면에 걸치면 그 가구는 빼고 본다."""
    room = stage.make_room(t, "r1")
    for a in room.anchors:
        fr = frame(room, [("a", a.id, "front", "stand", "")])
        assert hits(fr, skip=crowded(room, fr.beats[0].pos["a"])) == [], a.name


@pytest.mark.parametrize("t", sorted(stage.ROOMS))
def test_sit_and_lie_on_are_clear(t):
    """앉는 · 눕는 기준점 on 에 둔 사람은 그 기준점 밖 가구에 파고들지 않는다."""
    room = stage.make_room(t, "r1")
    for a in room.anchors:
        f = furniture.lookup(a, spec(t))
        if a.sit:
            fr = frame(room, [("a", a.id, "on", "chair", "")])
            assert body(fr).joints()["pelvis"][2] >= f.seat - 0.02, a.name
            assert hits(fr, skip={a.id}) == [], a.name
        if a.lie and t != "car":  # 차 뒷좌석은 다리가 좌석 밖으로 나가는 것이 맞다 (아래 시험)
            assert hits(lie_along(room, a, f), skip={a.id}) == [], a.name


def test_empty_room_every_kind():
    """빈 방에 종류마다 기준점 하나씩 더해도 빈자리 시험을 통과한다 (종류 기본값의 시험대)."""
    room = stage.make_room("empty", "r1")
    kinds = ["bed", "chair", "sofa", "desk", "table", "seat", "wall", "other"]
    room.anchors += [StageAnchor(id=f"k{i}", name=k, kind=k, x=0.2 + (i % 4) * 0.95, y=0.2 if i < 4 else 1.6, w=0.6, h=0.5,
                                 rot=0, sit=k in ("bed", "chair", "sofa", "seat"), lie=k in ("bed", "sofa"))
                     for i, k in enumerate(kinds)]
    for a in room.anchors:
        fr = frame(room, [("a", a.id, "front", "stand", "")])
        assert hits(fr, skip=crowded(room, fr.beats[0].pos["a"])) == [], a.name
        if a.sit:
            assert hits(frame(room, [("a", a.id, "on", "chair", "")]), skip={a.id}) == [], a.name


# ---------- 틀마다 ----------

def test_bedroom_head_at_headboard():
    room = stage.make_room("bedroom", "r1")
    a = anchor(room, "침대")
    f = furniture.lookup(a, spec("bedroom"))
    hx, hy = head_dir(a, f)
    board = max((s for s in furniture.solids(room, spec("bedroom")) if s.anchor == a.id), key=lambda s: s.box[5]).box
    cx, cy = a.x + a.w / 2, a.y + a.h / 2
    assert ((board[0] + board[3]) / 2 - cx) * hx + ((board[1] + board[4]) / 2 - cy) * hy > 0.8  # 머리판이 머리 쪽 끝
    j = body(lie_along(room, a, f)).joints()
    assert j["head"][1] < j["pelvis"][1]  # 침대 rot 0: 머리는 위쪽 벽(머리판)


def test_living_lie_on_sofa_inside():
    room = stage.make_room("living", "r1")
    a = anchor(room, "소파")
    b = body(lie_along(room, a, furniture.lookup(a, spec("living"))))
    for v in b.joints().values():
        assert a.x - 0.02 <= v[0] <= a.x + a.w + 0.02 and a.y - 0.02 <= v[1] <= a.y + a.h + 0.02, v


def test_living_overrides():
    room = stage.make_room("living", "r1")
    assert furniture.top(furniture.lookup(anchor(room, "탁자"), spec("living"))) == pytest.approx(0.45)
    tv = [s.box for s in furniture.solids(room, spec("living")) if s.anchor == anchor(room, "텔레비전").id]
    assert max(b[5] for b in tv) == pytest.approx(1.1)


def test_living_floor_sit_at_table():
    if "floor" not in s3.posture_specs():
        pytest.skip("바닥에 앉기 자세 모듈(P2)이 아직 없어요")
    room = stage.make_room("living", "r1")
    fr = frame(room, [("a", anchor(room, "탁자").id, "front", "floor", "n")], postures=s3.posture_specs())
    assert [h for h in hits(fr) if h[2] == anchor(room, "탁자").id] == []


def test_classroom_knees_under_desk():
    room = stage.make_room("classroom", "r1")
    for name in ("앞자리", "뒷자리", "창가 자리"):
        a = anchor(room, name)
        fr = frame(room, [("a", a.id, "on", "chair", "")])
        j = body(fr).joints()
        desk = [s for s in fr.solids if s.anchor == a.id and s.box[2] == pytest.approx(0.68)]
        assert len(desk) == 1
        x0, y0, _, x1, y1, _ = desk[0].box
        for k in ("knee_l", "knee_r"):  # 넓적다리가 판 아래로 들어간다
            mx, my = (j["pelvis"][0] + j[k][0]) / 2, (j["pelvis"][1] + j[k][1]) / 2
            assert x0 <= mx <= x1 and y0 <= my <= y1, (name, k)
        assert max(j["knee_l"][2], j["knee_r"][2]) < 0.68
        assert hits(fr) == [], name  # 자기 자리 상자까지 넣어도 겹침이 없다


def test_classroom_stand_at_lectern():
    room = stage.make_room("classroom", "r1")
    assert hits(frame(room, [("a", anchor(room, "교탁").id, "front", "stand", "n")])) == []


def test_office_two_chairs_knees():
    room = stage.make_room("office", "r1")
    fr = frame(room, [("a", anchor(room, "의자").id, "on", "chair", ""), ("b", anchor(room, "손님 의자").id, "on", "chair", "")])
    deep = max(s3.penetration(c, d) for c in s3.capsules(body(fr, "a")) for d in s3.capsules(body(fr, "b")))
    assert deep <= BODY_TOL
    for w in ("a", "b"):
        assert hits(fr, w, skip={anchor(room, "의자").id, anchor(room, "손님 의자").id}) == []


def test_office_lean_on_shelf():
    if "lean" not in s3.posture_specs():
        pytest.skip("기대 서기 자세 모듈(P1)이 아직 없어요")
    room = stage.make_room("office", "r1")
    a = anchor(room, "책장")
    fr = frame(room, [("a", a.id, "against", "lean", "")], postures=s3.posture_specs())
    assert hits(fr, skip={a.id}) == []


def test_car_ceiling():
    room = stage.make_room("car", "r1")
    a = anchor(room, "운전석")
    assert body(frame(room, [("a", a.id, "on", "stand", "")])).head_top() > spec("car").ceiling  # headroom 이 짚을 것
    assert body(frame(room, [("a", a.id, "on", "chair", "")])).head_top() <= spec("car").ceiling + TOL  # 앉은 머리는 허용 안


def test_car_rear_lie_too_short():
    """뒷좌석(1.5m)에 누우면 몸이 좌석 밖으로 나간다: 판정 no_support('누울 자리가 짧아요')의 재료."""
    room = stage.make_room("car", "r1")
    a = anchor(room, "뒷좌석")
    js = body(lie_along(room, a, furniture.lookup(a, spec("car")))).joints().values()
    assert max(v[0] for v in js) - min(v[0] for v in js) > a.w or min(v[0] for v in js) < a.x or max(v[0] for v in js) > a.x + a.w


def test_carriage_facing_seats():
    room = stage.make_room("carriage", "r1")
    fr = frame(room, [("a", anchor(room, "앞좌석").id, "on", "chair", ""), ("b", anchor(room, "뒷좌석").id, "on", "chair", "")])
    deep = max(s3.penetration(c, d) for c in s3.capsules(body(fr, "a")) for d in s3.capsules(body(fr, "b")))
    assert deep <= BODY_TOL
    mid = StageScene(id="s", room="r1", cast=["c"], start=[StageBody(who="c", at=StageSpot(ref="a3", rel="front"), posture="stand")])
    assert body(s3.frames(mid, room, postures=fake.POSTURES), "c").head_top() > spec("carriage").ceiling
