"""장면 연출 3D 판정 (docs/stage/3d/specs/04-judge.md). 가짜 자세 · 장소 등록부로 돈다. LLM 호출 없음."""
import time

import pytest

from canon import stage
from canon import stage3d as s3
from canon.schema import Character, Project, StageAnchor, StageBeat, StageBody, StageContact, StageRoom, StageScene, StageSpot
from canon.stage3d import fake, judge as j3, postures, rooms


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch):
    monkeypatch.setattr(postures, "load", lambda: fake.POSTURES)
    monkeypatch.setattr(rooms, "load", lambda: fake.ROOMS)


P = Project(characters=[Character(id="h", name="하린", role="주인공", age="27"), Character(id="d", name="도윤", role="조연", age="29")])
MAT = dict(id="m", name="자리", kind="window", x=1.8, y=1.3, w=0.4, h=0.4)    # 단단하지 않은 표지: 방 가운데 (2.0, 1.5)
SIDE = dict(id="m2", name="옆", kind="window", x=2.38, y=1.98, w=0.4, h=0.4)  # 누운 하린의 오른 뺨에서 평면 0.5m


def room(*anchors, template="empty", w=4.0, h=3.0):
    return StageRoom(id="r", name="방", template=template, w=w, h=h, anchors=[StageAnchor(**a) for a in anchors])


def at(ref, rel="on"):
    return StageSpot(ref=ref, rel=rel)


def body(who, **kw):
    return StageBody(who=who, **kw)


def touch(cid, part, by="right", to="h", act="stroke"):
    return StageContact(id=cid, by=by, to=to, part=part, act=act)


def judge(start, beats=(), rm=None, cast=("h", "d"), **kw):
    sc = StageScene(id="s", room="r", cast=list(cast), start=list(start), beats=list(beats))
    return j3.judge3d(sc, rm or room(MAT, SIDE), P, **kw)


def rules(vs):
    return [(v.beat, v.who, v.rule) for v in vs]


def cheek(posture):
    """하린은 바닥에 눕고, 도윤이 그 뺨 옆에서 손을 뻗는다."""
    return judge([body("h", at=at("m"), posture="lie", facing="n"), body("d", at=at("m2"), posture=posture, facing="w")],
                 [StageBeat(bodies=[body("d", contacts=[touch("c1", "cheek_r")])])])


# ---------- reach3d ----------

def test_reach3d_standing_to_lying_cheek():
    vs = cheek("stand")
    assert rules(vs) == [(1, "d", "reach3d")]
    v = vs[0]
    assert v.cause == 0 and "손이" in v.text and "모자라요" in v.text and "'눕기'" in v.text
    assert getattr(v, "contact", "c1") == "c1"


def test_reach3d_squatting_passes():
    assert cheek("squat") == []


def test_reach3d_skips_contact_2d_flagged():
    far = room(dict(id="a", name="왼쪽", kind="window", x=0.2, y=1.3, w=0.4, h=0.4),
               dict(id="b", name="오른쪽", kind="window", x=3.4, y=1.3, w=0.4, h=0.4))
    start = [body("h", at=at("a"), posture="stand", facing="e"), body("d", at=at("b"), posture="stand", facing="w")]
    beats = [StageBeat(bodies=[body("d", contacts=[touch("c1", "hand_l", act="hold")])])]
    sc = StageScene(id="s", room="r", cast=["h", "d"], start=start, beats=beats)
    assert [v.rule for v in stage.judge(sc, far, P)] == ["reach"]
    assert judge(start, beats, far) == []                      # 2D 를 스스로 부른다
    assert judge(start, beats, far, flat=stage.judge(sc, far, P)) == []
    assert rules(judge(start, beats, far, flat=[])) == [(1, "d", "reach3d")]  # 2D 결과가 없으면 3D 가 짚는다


def test_reach3d_rechecks_when_posture_changes():
    # 쪼그려 앉아 누운 하린의 손목을 잡고, 놓지 않은 채 일어선다
    vs = judge([body("h", at=at("m"), posture="lie", facing="n"), body("d", at=at("m2"), posture="squat", facing="w")],
               [StageBeat(bodies=[body("d", contacts=[touch("c1", "cheek_r", act="hold")])]),
                StageBeat(bodies=[body("d", posture="stand")])])
    assert rules(vs) == [(2, "d", "reach3d")]
    assert vs[0].cause == 2


# ---------- body_overlap ----------

def test_body_overlap_same_spot():
    vs = judge([body("d", at=at("m"), posture="stand", facing="s"), body("h", at=at("@d"), posture="stand", facing="s")],
               [StageBeat(bodies=[body("h", facing="n")])])
    assert rules(vs) == [(1, "h", "body_overlap")]
    assert "하린과 도윤이" in vs[0].text and "겹쳐요" in vs[0].text


def test_body_overlap_holding_hands_passes():
    vs = judge([body("d", at=at("m"), posture="stand", facing="s"), body("h", at=at("@d", "beside"), posture="stand", facing="s")],
               [StageBeat(bodies=[body("d", contacts=[touch("c1", "hand_l", by="right", act="hold")])])])
    assert vs == []


def test_overlap_reported_once_while_nothing_moves():
    start = [body("d", at=at("m"), posture="stand", facing="s"), body("h", at=at("@d"), posture="stand", facing="s")]
    vs = judge(start, [StageBeat(bodies=[body("h", left="책")]), StageBeat(bodies=[body("h", right="펜")])])
    assert rules(vs) == [(1, "h", "body_overlap")] and vs[0].cause == 0


# ---------- furniture_overlap ----------

def bedroom_one(rel, posture, name):
    rm = stage.make_room("bedroom", "r")
    ref = next(a.id for a in rm.anchors if a.name == name)
    sc = StageScene(id="s", room="r", cast=["h"], start=[body("h", at=at(ref, rel), posture=posture, facing="s")],
                    beats=[StageBeat(bodies=[body("h", left="")])])
    return j3.judge3d(sc, rm, P)


def test_furniture_stand_on_desk_passes():
    # 책상 윗면(0.75m)에 서면 머리(2.47m)가 천장(2.4m)에 닿지만 다리는 책상을 뚫지 않는다
    assert rules(bedroom_one("on", "stand", "책상")) == [(1, "h", "headroom")]


def test_furniture_stand_in_desk_flagged():
    vs = bedroom_one("in", "stand", "책상")
    assert rules(vs) == [(1, "h", "furniture_overlap")]
    assert "책상에" in vs[0].text and "파고들어요" in vs[0].text


def test_furniture_chair_on_chair_passes():
    assert bedroom_one("on", "chair", "의자") == []


def test_furniture_wall():
    rm = room(dict(id="w", name="구석", kind="window", x=0.0, y=1.3, w=0.1, h=0.4))
    vs = judge([body("h", at=at("w"), posture="lie", facing="e")], [StageBeat(bodies=[body("h", left="")])], rm, cast=("h",))
    assert rules(vs) == [(1, "h", "furniture_overlap")] and "벽에" in vs[0].text


# ---------- no_support ----------

def test_no_support_chair_in_middle():
    vs = judge([body("h", at=at("m"), posture="chair", facing="s")], [StageBeat(bodies=[body("h", left="")])], cast=("h",))
    assert rules(vs) == [(1, "h", "no_support")] and "앉을 곳" in vs[0].text


def test_no_support_carrier_and_back(monkeypatch):
    extra = {"held": s3.PostureSpec("held", fake.POSTURES["stand"].angles, ("carrier",)),
             "lean": s3.PostureSpec("lean", fake.POSTURES["stand"].angles, ("back_support",))}
    monkeypatch.setattr(postures, "load", lambda: {**fake.POSTURES, **extra})
    vs = judge([body("h", at=at("m"), posture="held", facing="s"), body("d", at=at("m2"), posture="lean", facing="s")],
               [StageBeat(bodies=[body("h", left="")])])
    assert [(v.who, v.rule) for v in vs] == [("d", "no_support"), ("h", "no_support")]


# ---------- headroom ----------

def test_headroom_low_ceiling(monkeypatch):
    monkeypatch.setattr(rooms, "load", lambda: {"empty": fake.box_room(1.15)})
    vs = judge([body("h", at=at("m"), posture="stand", facing="s")], [StageBeat(bodies=[body("h", left="")])], cast=("h",))
    assert rules(vs) == [(1, "h", "headroom")] and "천장" in vs[0].text


def test_headroom_normal_ceiling_passes():
    assert judge([body("h", at=at("m"), posture="stand", facing="s")], [StageBeat(bodies=[body("h", left="")])], cast=("h",)) == []


# ---------- 순서 · 켜기 · 속도 ----------

def test_order_and_deterministic(monkeypatch):
    monkeypatch.setattr(rooms, "load", lambda: {"empty": fake.box_room(1.15)})
    start = [body("d", at=at("m"), posture="stand", facing="s"), body("h", at=at("@d"), posture="stand", facing="s")]
    beats = [StageBeat(bodies=[body("h", left="")]), StageBeat(bodies=[body("d", posture="chair")])]
    a, b = judge(start, beats), judge(start, beats)
    assert a == b
    assert [(v.beat, v.rule) for v in a] == sorted((v.beat, v.rule) for v in a)
    assert {v.rule for v in a} == {"body_overlap", "headroom", "no_support"}
    assert set(j3.RULES3D).isdisjoint(stage.RULES)


def test_judge_if_ready_off_until_complete(monkeypatch):
    sc = StageScene(id="s", room="r", cast=["h", "d"], start=[body("d", at=at("m"), posture="stand", facing="s"),
                                                             body("h", at=at("@d"), posture="stand", facing="s")],
                    beats=[StageBeat(bodies=[body("h", left="")])])
    rm = room(MAT, SIDE)
    assert not j3.enabled() and j3.judge_if_ready(sc, rm, P) == []
    full = {k: fake.POSTURES.get(k) or s3.PostureSpec(k, fake.POSTURES["stand"].angles, ("floor",)) for k in stage.POSTURES}
    monkeypatch.setattr(postures, "load", lambda: full)
    assert j3.enabled()
    assert rules(j3.judge_if_ready(sc, rm, P)) == [(1, "h", "body_overlap")]


def test_missing_posture_not_judged(monkeypatch):
    monkeypatch.setattr(postures, "load", lambda: {})
    assert judge([body("d", at=at("m"), posture="stand", facing="s"), body("h", at=at("@d"), posture="stand", facing="s")],
                 [StageBeat(bodies=[body("h", left="")])]) == []


def test_speed():
    rm = stage.make_room("living", "r")
    cast = ["a", "b", "c", "d"]
    start = [body(w, at=at(f"a{i + 1}", "front"), posture="stand", facing="s") for i, w in enumerate(cast)]
    beats = []
    for k in range(20):
        w, o = cast[k % 4], cast[(k + 1) % 4]
        beats.append(StageBeat(bodies=[body(w, at=at("@" + o, "front"), facing="@" + o,
                                            contacts=[StageContact(id=f"c{k}", by="right", to=o, part="hand_l", act="hold")],
                                            ends=[f"c{k - 4}"] if k >= 4 else [])]))
    sc = StageScene(id="s", room="r", cast=cast, start=start, beats=beats)
    fr = s3.frames(sc, rm, P)
    t = time.perf_counter()
    j3.judge3d(sc, rm, P, frames=fr)
    assert time.perf_counter() - t < 0.2


def test_contact_field_when_violation_has_it(monkeypatch):
    # 일감 1-1(PR #163)이 Violation.contact 를 더하면 접촉 id 로 잇고 빼기도 id 로 한다
    class V(stage.Violation):
        contact: str = ""

    monkeypatch.setattr(stage, "Violation", V)
    vs = cheek("stand")
    assert vs[0].contact == "c1"
    start = [body("h", at=at("m"), posture="lie", facing="n"), body("d", at=at("m2"), posture="stand", facing="w")]
    beats = [StageBeat(bodies=[body("d", contacts=[touch("c1", "cheek_r")])])]
    flagged = V(beat=1, cause=0, who="d", rule="reach", text="", contact="c1")
    assert judge(start, beats, flat=[flagged]) == []
    other = V(beat=1, cause=0, who="d", rule="reach", text="", contact="c9")
    assert rules(judge(start, beats, flat=[other])) == [(1, "d", "reach3d")]
