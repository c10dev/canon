"""장면 연출 계산 (canon/stage.py): 방 틀, 위치, 규칙 판정, 막기, 사건 찾기. 실행: python -m pytest tests"""
import math

import pytest

from canon import stage
from canon.schema import Character, Episode, EpisodePlot, Project, StageBeat, StageBody, StageContact, StageScene, StageSpot


def _project(minor: bool = False) -> Project:
    return Project(characters=[
        Character(id="h", name="하린", role="주인공", age="16" if minor else "27"),
        Character(id="d", name="도윤", role="조연", age="29"),
    ])


def _room():
    return stage.make_room("bedroom", "r1", "하린의 방")


def _a(room, name):
    return next(a.id for a in room.anchors if a.name == name)


def _scene(room, beats, **start):
    s = StageScene(id="s1", room=room.id, cast=["h", "d"], start=[
        StageBody(who="h", at=StageSpot(ref=_a(room, "의자"), rel="on"), posture="chair", facing="@d", left="", right="펜"),
        StageBody(who="d", at=StageSpot(ref=_a(room, "문"), rel="front"), posture="stand", facing="@h", left="", right=""),
    ], beats=beats)
    for who, kw in start.items():
        next(b for b in s.start if b.who == who).__dict__.update(kw)
    return s


def _rules(scene, room, p=None):
    return [(v.beat, v.rule, v.who) for v in stage.judge(scene, room, p or _project())]


def test_templates_keep_anchors_inside():
    for key in stage.ROOMS:
        room = stage.make_room(key, "r")
        assert room.anchors, key
        for a in room.anchors:
            assert 0 <= a.x and a.x + a.w <= room.w + 1e-9 and 0 <= a.y and a.y + a.h <= room.h + 1e-9, (key, a.name)
    assert stage.make_room("없는 틀", "r").template == "empty"


def test_place_anchor_relations_and_spread():
    room = _room()
    bed, door = _a(room, "침대"), _a(room, "문")
    st = stage.state_at(StageScene(id="s", cast=["a", "b", "c"], start=[
        StageBody(who="a", at=StageSpot(ref=door, rel="front")),
        StageBody(who="b", at=StageSpot(ref=bed, rel="on")),
        StageBody(who="c", at=StageSpot(ref=bed, rel="on")),
    ]), 0)
    pos = stage.place(room, st, ["a", "b", "c"])
    # 문은 아래 벽에 있고 앞쪽이 방 안(위)이다
    assert pos["a"][1] < 3.1
    # 침대 위 두 사람은 0.5m 간격으로 편다
    assert math.dist(pos["b"], pos["c"]) == pytest.approx(stage.SPREAD)
    for x, y in pos.values():
        assert stage.BODY <= x <= room.w - stage.BODY and stage.BODY <= y <= room.h - stage.BODY


def test_place_person_relations_and_cycle():
    room = _room()
    st = stage.state_at(StageScene(id="s", cast=["a", "b"], start=[
        StageBody(who="a", at=StageSpot(ref=_a(room, "침대"), rel="right"), facing="e"),
        StageBody(who="b", at=StageSpot(ref="@a", rel="front")),
    ]), 0)
    pos = stage.place(room, st)
    # a 가 오른쪽(e)을 보니 a 앞은 오른쪽
    assert pos["b"][0] > pos["a"][0] and pos["b"][1] == pytest.approx(pos["a"][1])
    loop = stage.state_at(StageScene(id="s", cast=["a", "b"], start=[
        StageBody(who="a", at=StageSpot(ref="@b", rel="front")),
        StageBody(who="b", at=StageSpot(ref="@a", rel="front")),
    ]), 0)
    assert set(stage.place(room, loop)) == {"a", "b"}


def test_clean_scene_has_no_violations():
    room = _room()
    s = _scene(room, [
        StageBeat(quote="하린은 의자를 돌려 그를 보았다.", bodies=[StageBody(who="h", facing="@d")]),
        StageBeat(quote="도윤은 침대 옆까지 걸어왔다.", bodies=[StageBody(who="d", at=StageSpot(ref=_a(room, "침대"), rel="right"), posture="walk")]),
        StageBeat(quote="하린이 펜을 놓고 일어섰다.", bodies=[StageBody(who="h", at=StageSpot(ref="@d", rel="front"), posture="stand", right="")]),
        StageBeat(quote="도윤이 그녀의 손목을 잡았다.", bodies=[StageBody(who="d", contacts=[StageContact(id="c1", by="right", to="h", part="wrist_l", act="hold")])]),
    ])
    assert _rules(s, room) == []


def test_rules_each_fire():
    room = _room()
    desk, bed = _a(room, "책상"), _a(room, "침대")
    s = _scene(room, [
        # 1. 앉은 채 자리를 옮긴다 → move_posture
        StageBeat(bodies=[StageBody(who="h", at=StageSpot(ref=desk, rel="front"))]),
        # 2. 도윤이 침대 오른쪽에서 멀리 있는 하린을 잡는다 → reach
        StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref=bed, rel="right"), contacts=[StageContact(id="c1", by="right", to="h", part="wrist_l", act="hold")])]),
        # 3. 하린이 펜을 쥔 오른손으로 또 접촉 → hand_busy
        StageBeat(bodies=[StageBody(who="h", posture="stand", at=StageSpot(ref="@d", rel="front"), contacts=[StageContact(id="c2", by="right", to="d", part="shoulder_l", act="hold")])]),
        # 4. 오른손 펜을 놓지 않고 왼손으로 쥔다 → handoff
        StageBeat(bodies=[StageBody(who="h", left="펜")]),
    ])
    got = _rules(s, room)
    assert (1, "move_posture", "h") in got
    assert (2, "reach", "d") in got
    assert (3, "hand_busy", "h") in got
    assert (4, "handoff", "h") in got
    v = next(v for v in stage.judge(s, room, _project()) if v.rule == "handoff")
    assert v.cause == 0 and "펜" in v.text


def test_behind_front():
    room = _room()
    s = _scene(room, [
        # 도윤이 하린 등 뒤로 가서 뺨을 만진다. 하린은 책상을 본다
        StageBeat(bodies=[StageBody(who="h", posture="stand", facing="#" + _a(room, "책상"))]),
        StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref="@h", rel="back"), contacts=[StageContact(id="c1", by="right", to="h", part="cheek_l", act="stroke")])]),
        # 등에 손을 대는 것은 괜찮다
        StageBeat(bodies=[StageBody(who="d", ends=["c1"], contacts=[StageContact(id="c2", by="right", to="h", part="back", act="pat")])]),
    ])
    assert _rules(s, room) == [(2, "behind_front", "d")]


def test_unknown_hand_is_not_judged():
    room = _room()
    s = _scene(room, [StageBeat(bodies=[StageBody(who="h", contacts=[StageContact(id="c1", by="right", to="d", part="hand_l", act="hold")])])],
               h={"right": "?", "at": StageSpot(ref="@d", rel="front"), "posture": "stand"})
    assert [r for r in _rules(s, room) if r[1] == "hand_busy"] == []


def test_carried_person_may_move():
    room = _room()
    s = _scene(room, [StageBeat(bodies=[StageBody(who="h", posture="held", at=StageSpot(ref="@d", rel="on"))])])
    assert _rules(s, room) == []


def test_blocked_only_sexual_with_minor():
    caress = StageContact(id="c", by="right", to="h", part="chest", act="stroke")
    push = StageContact(id="c", by="right", to="h", part="chest", act="push")
    kiss = StageContact(id="c", by="lips", to="h", part="lips", act="kiss")
    assert stage.is_sexual(caress) and not stage.is_sexual(push) and not stage.is_sexual(kiss)
    assert stage.blocked(caress, "d", _project(minor=True))
    assert not stage.blocked(caress, "d", _project(minor=False))
    assert not stage.blocked(push, "d", _project(minor=True))


def test_clean_scene_moves_unknowns_and_drops_blocked():
    room = _room()
    s = _scene(room, [StageBeat(bodies=[
        StageBody(who="d", posture="물구나무", contacts=[
            StageContact(id="", by="right", to="h", part="chest", act="caress"),
            StageContact(id="", by="right", to="h", part="없는 부위", act="hold"),
            StageContact(id="", by="left", to="h", part="hand_r", act="hold"),
        ]),
        StageBody(who="x", at=StageSpot(ref="없는 기준점", rel="on")),
    ])])
    assert stage.clean_scene(s, room, _project(minor=True)) == 1
    d = s.beats[0].bodies[0]
    assert d.posture == "" and "물구나무" in d.memo and "없는 부위" in d.memo
    assert [(c.id, c.part) for c in d.contacts] == [("c1", "hand_r")]
    assert s.beats[0].bodies[1].at is None and "x" in s.cast
    # 성인이면 같은 접촉을 남긴다
    s2 = _scene(room, [StageBeat(bodies=[StageBody(who="d", contacts=[StageContact(id="", by="right", to="h", part="chest", act="caress")])])])
    assert stage.clean_scene(s2, room, _project()) == 0 and len(s2.beats[0].bodies[0].contacts) == 1


def test_find_event_and_stale():
    plot = EpisodePlot(number=1, act="기", title="t", summary="", events=["도윤이 찾아온다", "하린이 붙잡는다"], characters=[],
                       emotional_shift="", ending_hook="")
    ep = Episode(plot=plot, text="하린은 의자를 돌려 그를 보았다.\n도윤이 웃었다.")
    assert stage.find_event(ep, StageScene(id="s", event=0, event_text="하린이 붙잡는다")) == (1, False)
    assert stage.find_event(ep, StageScene(id="s", event=1, event_text="바뀐 사건")) == (1, True)
    assert stage.find_event(ep, StageScene(id="s", event=5, event_text="바뀐 사건")) == (None, True)
    s = StageScene(id="s", beats=[StageBeat(quote="하린은 의자를 돌려  그를 보았다."), StageBeat(quote="없는 문장."), StageBeat()])
    assert stage.stale(s, ep.text) == [2]


def test_old_project_reads_and_vocab():
    p = Project.model_validate_json('{"episodes": [{"plot": {"number": 1, "act": "기", "title": "a", "summary": "", "events": [],'
                                    ' "characters": [], "emotional_shift": "", "ending_hook": ""}}]}')
    assert p.rooms == [] and p.episodes[0].stage == [] and p.settings.stage_extract is False
    v = stage.vocab()
    assert len(v["postures"]) == 12 and v["parts"]["wrist_l"]["label"] == "왼 손목" and "bedroom" in v["rooms"]
