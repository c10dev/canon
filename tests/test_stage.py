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


def test_place_uses_previous_spot_when_ref_faces_me():
    # 목업 5박자: 하린은 책상 앞에서 '@도윤 앞'으로, 도윤은 하린을 향한다 (PR #159 댓글)
    room = _room()
    s = StageScene(id="s", cast=["h", "d"], start=[
        StageBody(who="h", at=StageSpot(ref=_a(room, "책상"), rel="front")),
        StageBody(who="d", at=StageSpot(ref=_a(room, "침대"), rel="right"), facing="@h"),
    ], beats=[StageBeat(bodies=[StageBody(who="h", at=StageSpot(ref="@d", rel="front"))])])
    before, after = stage.layouts(room, s)
    d = after["d"]
    # 하린은 앞 박자 자리 쪽(도윤에게서 본 방향)으로 한 걸음 거리에 선다
    want = math.atan2(before["h"][1] - d[1], before["h"][0] - d[0])
    assert math.atan2(after["h"][1] - d[1], after["h"][0] - d[0]) == pytest.approx(want)
    assert math.dist(after["h"], d) == pytest.approx(stage.BODY * 2 + 0.05)
    # 앞 박자가 없으면 예전처럼 아래를 본다고 친다
    alone = stage.place(room, stage.state_at(s, 1), s.cast)
    assert alone["h"][0] == pytest.approx(d[0]) and alone["h"][1] > d[1]
    # judge 도 같은 좌표를 쓴다: 한 걸음 앞이면 손이 닿는다
    s.beats.append(StageBeat(bodies=[StageBody(who="d", contacts=[StageContact(id="c1", by="right", to="h", part="wrist_l", act="hold")])]))
    assert _rules(s, room) == []


def test_seats_face_their_furniture():
    # 의자 · 자리의 앞(rot)이 마주 보는 가구 가운데 쪽을 향한다
    pairs = {"bedroom": [("의자", "책상")], "living": [("소파", "탁자")], "office": [("의자", "책상"), ("손님 의자", "책상")],
             "classroom": [("앞자리", "교탁"), ("뒷자리", "교탁"), ("창가 자리", "교탁")], "car": [("운전석", "앞유리"), ("조수석", "앞유리")],
             "carriage": [("앞좌석", "뒷좌석"), ("뒷좌석", "앞좌석")]}
    for key, rows in pairs.items():
        room = stage.make_room(key, "r")
        by = {a.name: a for a in room.anchors}
        for seat, thing in rows:
            a, b = by[seat], by[thing]
            fx, fy = stage._front(a.rot)
            dx, dy = b.x + b.w / 2 - (a.x + a.w / 2), b.y + b.h / 2 - (a.y + a.h / 2)
            assert fx * dx + fy * dy > 0.7 * math.hypot(dx, dy), (key, seat)


def test_violation_names_contact():
    room = _room()
    s = _scene(room, [
        # 문 앞 도윤이 한 박자에 두 접촉을 시작하는데 의자에 앉은 하린 접촉만 닿지 않는다 (다른 사람 x 는 바로 앞)
        StageBeat(bodies=[StageBody(who="x", at=StageSpot(ref="@d", rel="front")),
                          StageBody(who="d", contacts=[
                              StageContact(id="c1", by="right", to="h", part="wrist_l", act="hold"),
                              StageContact(id="c2", by="left", to="x", part="hand_r", act="hold")])]),
        StageBeat(bodies=[StageBody(who="d", ends=["c1"], contacts=[StageContact(id="c3", by="left", to="x", part="shoulder_r", act="press")])]),
    ])
    s.cast.append("x")
    got = [(v.beat, v.rule, v.contact) for v in stage.judge(s, room, _project())]
    assert (1, "reach", "c1") in got and all(c != "c2" for _, _, c in got)
    assert (2, "hand_busy", "c3") in got


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
    byrule = {v.rule: v.contact for v in stage.judge(s, room, _project())}
    assert byrule["reach"] == "c1" and byrule["hand_busy"] == "c2" and byrule["handoff"] == ""
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
    assert [v.contact for v in stage.judge(s, room, _project())] == ["c1"]


def test_unknown_hand_is_not_judged():
    room = _room()
    s = _scene(room, [StageBeat(bodies=[StageBody(who="h", contacts=[StageContact(id="c1", by="right", to="d", part="hand_l", act="hold")])])],
               h={"right": "?", "at": StageSpot(ref="@d", rel="front"), "posture": "stand"})
    assert [r for r in _rules(s, room) if r[1] == "hand_busy"] == []


def test_carried_person_may_move():
    room = _room()
    # 도윤이 선 채로 업어야(받침 접촉) 업힌 하린이 옮겨질 수 있다
    carry = StageBody(who="d", contacts=[StageContact(id="c1", by="both", to="h", part="back", act="carry")])
    s = _scene(room, [StageBeat(bodies=[carry, StageBody(who="h", posture="held", at=StageSpot(ref="@d", rel="on"))])])
    assert _rules(s, room) == []
    s = _scene(room, [StageBeat(bodies=[StageBody(who="h", posture="held", at=StageSpot(ref="@d", rel="on"))])])
    assert _rules(s, room) == [(1, "move_posture", "h")]


def test_across_and_against():
    room = _room()
    desk = next(a for a in room.anchors if a.name == "책상")
    door = next(a for a in room.anchors if a.name == "문")
    assert stage._anchor_point(desk, "across") == stage._anchor_point(desk, "back")
    # 문(앞쪽이 위)에 기대면 문 앞보다 가깝게 붙는다
    assert stage._anchor_point(door, "against")[1] > stage._anchor_point(door, "front")[1]
    st = stage.state_at(StageScene(id="s", cast=["a", "b", "c"], start=[
        StageBody(who="a", at=StageSpot(ref=next(a.id for a in room.anchors if a.name == "침대"), rel="right"), facing="e"),
        StageBody(who="b", at=StageSpot(ref="@a", rel="across")),
        StageBody(who="c", at=StageSpot(ref="@a", rel="against")),
    ]), 0)
    pos = stage.place(room, st)
    assert pos["b"][0] - pos["a"][0] == pytest.approx(stage.ACROSS)
    assert pos["c"][0] - pos["a"][0] == pytest.approx(stage.BODY * 2)


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
    assert stage.stale(s, "  ") == []  # 쓰기 전 연출


def test_old_project_reads_and_vocab():
    p = Project.model_validate_json('{"episodes": [{"plot": {"number": 1, "act": "기", "title": "a", "summary": "", "events": [],'
                                    ' "characters": [], "emotional_shift": "", "ending_hook": ""}}]}')
    assert p.rooms == [] and p.episodes[0].stage == [] and p.settings.stage_extract is True  # 검수 때 함께 뽑기는 기본으로 켠다
    v = stage.vocab()
    assert len(v["postures"]) == 12 and v["parts"]["wrist_l"]["label"] == "왼 손목" and "bedroom" in v["rooms"]
    assert v["parts"]["forearm_r"]["label"] == "오른 아래팔" and v["acts"]["carry"]["support"] and not v["acts"]["hold"]["support"]
    assert v["rels"]["across"] == "맞은편" and v["rels"]["against"] == "기대어 맞닿음"


# ---------- 계획 · 본문 장면 (일감 07) ----------

def _ep_plan_project():
    p = _project()
    plot = EpisodePlot(number=1, act="기", title="t", summary="", events=["도윤이 찾아온다", "하린이 붙잡는다"], characters=["h", "d"],
                       emotional_shift="", ending_hook="")
    p.episodes = [Episode(plot=plot)]
    return p, p.episodes[0]


def _plan(room):
    bed, desk = _a(room, "침대"), _a(room, "책상")
    return _scene(room, [
        StageBeat(note="도윤이 침대 옆으로 간다", bodies=[StageBody(who="d", at=StageSpot(ref=bed, rel="right"), posture="walk")]),
        StageBeat(note="하린이 일어나 손목을 잡는다", bodies=[StageBody(who="h", at=StageSpot(ref=bed, rel="front"), posture="stand", contacts=[
            StageContact(id="c1", by="right", to="d", part="wrist_l", act="hold")])]),
        StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref=desk, rel="front"))]),
    ])


def test_old_scene_reads_as_plan_and_one_per_role():
    s = StageScene.model_validate({"id": "s1", "event": 0})
    assert s.role == "plan"
    p, e = _ep_plan_project()
    room = stage.new_room(p, "bedroom")
    a = stage.new_scene(p, e, 1, room)
    with pytest.raises(ValueError, match="이미 계획 장면"):
        stage.new_scene(p, e, 1, room)
    b = stage.new_scene(p, e, 1, room, "text")
    assert (a.role, b.role, b.source) == ("plan", "text", "text")
    assert stage.scenes_of(e, 1) == (a, b) and stage.scenes_of(e, 0) == (None, None)
    with pytest.raises(ValueError, match="이미 본문 장면"):
        stage.save_scene(p, e, b.model_copy(update={"id": "s9"}), None)
    with pytest.raises(ValueError, match="이미 계획 장면"):  # 본문 장면을 계획으로 바꿔도 계획을 덮지 않는다
        stage.save_scene(p, e, b.model_copy(update={"role": "plan"}), None)
    stage.save_scene(p, e, b, None)
    assert [(s.id, s.role) for s in e.stage] == [(a.id, "plan"), (b.id, "text")]
    with pytest.raises(ValueError):
        stage.new_scene(p, e, 0, room, "draft")


def test_diff_same_and_regrouped_beats():
    room = _room()
    plan = _plan(room)
    assert stage.diff(plan, plan, room) == []
    # 본문은 박자를 다르게 나눴다: 도윤이 걸어가며 하린이 일어나고(한 박자), 손목을 잡고, 쓸데없는 박자가 끼고, 책상으로
    bed, desk = _a(room, "침대"), _a(room, "책상")
    text = _scene(room, [
        StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref=bed, rel="beside"), posture="walk"),
                          StageBody(who="h", at=StageSpot(ref=bed, rel="front"), posture="stand")]),
        StageBeat(bodies=[StageBody(who="h", contacts=[StageContact(id="x", by="left", to="d", part="wrist_l", act="grip")])]),
        StageBeat(bodies=[StageBody(who="h", facing="n")]),
        StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref=desk, rel="left"))]),
    ], h={"left": "?", "right": "?"})
    match, gaps = stage.align(plan, text, room)
    assert gaps == [] and match == [0, 1, 2, 4]  # 관계 말 · 손 · 동작 이름 차이는 견주지 않는다


def test_diff_finds_spot_posture_contact():
    room = _room()
    p = _project()
    plan = _plan(room)
    bed, door = _a(room, "침대"), _a(room, "문")
    text = _scene(room, [
        StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref=bed, rel="right"), posture="walk")]),
        # 하린이 앉은 채 침대 앞으로 (자세가 다름), 접촉 없음, 도윤은 책상 대신 문 앞으로
        StageBeat(bodies=[StageBody(who="h", at=StageSpot(ref=bed, rel="front"), posture="kneel")]),
        StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref=door, rel="front"))]),
    ])
    gaps = stage.diff(plan, text, room, p)
    assert sorted((g.plan_beat, g.field, g.who) for g in gaps) == [(2, "contact", "h"), (2, "posture", "h"), (3, "at", "d")]
    by = {g.field: g for g in gaps}
    assert by["at"].plan == "책상 앞" and by["at"].actual == "문 앞" and "도윤 자리가 계획과 달라요" in by["at"].text and by["at"].text_beat == 3
    assert by["posture"].actual == "무릎 꿇기" and by["contact"].contact == "c1" and "하린 오른손 → 도윤 왼 손목" in by["contact"].text
    # 차례가 뒤바뀌면 다르다: 계획은 침대 옆 → 책상, 본문은 책상 → 침대 옆
    swapped = _scene(room, [StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref=_a(room, "책상"), rel="front"))]),
                            StageBeat(bodies=[StageBody(who="d", at=StageSpot(ref=bed, rel="right"))])])
    plan2 = _scene(room, [plan.beats[0], plan.beats[2]])
    assert [(g.plan_beat, g.field) for g in stage.diff(plan2, swapped, room)] == [(2, "at")]


def test_view_pairs_plan_and_text():
    p, e = _ep_plan_project()
    room = stage.new_room(p, "bedroom")
    a = stage.new_scene(p, e, 0, room)
    assert stage.view(p, 1)["scenes"][0]["gaps"] == [] and stage.view(p, 1)["scenes"][0]["pair"] is None
    b = stage.new_scene(p, e, 0, room, "text")
    b.start[0].posture = "chair"
    rows = stage.view(p, 1)["scenes"]
    assert [r["pair"] for r in rows] == [b.id, a.id] and rows[0]["gaps"] == rows[1]["gaps"]
    assert rows[0]["gaps"][0]["field"] == "posture" and rows[0]["match"] == [0]


def test_template_front_spots_clear():
    # 기준점 앞자리(front)는 다른 가구 위(몸 여유 0.15m)에 떨어지지 않는다. 책상에 붙여 둔 의자의 앞은 그 책상이라 뺀다
    allowed = {("bedroom", "의자", "책상"), ("office", "의자", "책상")}
    for key in stage.ROOMS:
        room = stage.make_room(key, "r")
        for a in room.anchors:
            x, y = stage._anchor_point(a, "front")
            x, y = min(max(x, stage.BODY), room.w - stage.BODY), min(max(y, stage.BODY), room.h - stage.BODY)
            for o in room.anchors:
                if o is a or o.kind in ("door", "window"):
                    continue
                if o.x - 0.15 < x < o.x + o.w + 0.15 and o.y - 0.15 < y < o.y + o.h + 0.15:
                    assert (key, a.name, o.name) in allowed, (key, a.name, o.name)
