"""장면 연출 AI(일감 03): 초안 · 뽑기 → 비교 → 적용 · 적용 취소, 이름 정리와 막기.
mock LLM. 실행: python -m pytest tests"""
import time

import pytest

from canon import findings, pipeline, stage
from canon.mock import MockLLM
from canon.schema import (Character, ConsistencyReport, DraftBeat, DraftBody, DraftContact, FixOption, FixSet, Meta, Project,
                          StageBeat, StageBody, StageContact, StageDraft, StageScene, StageSpot)

from .jsvm import episode
from .test_web import client  # noqa: F401  (pytest fixture)

TEXT = "도윤이 문을 열었다. 하린은 창가에 서 있었다. 도윤이 하린의 어깨를 잡았다."


def _project(minor: bool = False, text: str = TEXT) -> Project:
    return Project(meta=Meta(title="방", target_episodes=3), characters=[
        Character(id="h", name="하린", role="주인공", age="16" if minor else "27"),
        Character(id="d", name="도윤", role="조연", age="29"),
    ], episodes=[episode(1, text=text, status="written",
                         plot={"title": "첫 화", "events": ["도윤이 찾아온다", "하린이 붙잡는다"], "characters": ["h", "d"]})])


class Counting(MockLLM):
    def __init__(self):
        self.calls = []

    def json(self, system, prompt, schema, hint=None):
        self.calls.append(schema.__name__)
        return super().json(system, prompt, schema, hint)


class NoLLM:
    def json(self, *a, **k):
        raise AssertionError("LLM 을 부르면 안 돼요")


def test_draft_apply_undo_roundtrip():
    p = _project()
    prop = pipeline.draft_stage(MockLLM(), p, 1, 0)
    assert prop.role == "plan" and prop.scene.source == "plot" and prop.room is not None  # 방이 없으면 AI 가 고른 틀로 새 방
    assert prop.scene.cast == ["h", "d"] and prop.scene.beats[0].note
    assert all(b.left == "" and b.right == "" for b in prop.scene.start)  # 계획의 시작 손은 빈손
    s = pipeline.apply_stage(p, prop)
    assert [r.id for r in p.rooms] == [s.room] and s.prev is not None and s.prev.id == ""
    # 다시 받아 적용하면 앞 장면을 prev 에 남기고, 적용 취소는 그 장면으로 되돌린다
    again = pipeline.draft_stage(MockLLM(), p, 1, 0)
    assert again.room is None  # 같은 사건 장면의 방을 다시 쓴다
    again.scene.beats.append(StageBeat(note="더한 박자"))
    s2 = pipeline.apply_stage(p, again)
    assert s2.id == s.id and len(s2.beats) == 2 and s2.prev.beats == s.beats
    back = pipeline.undo_stage(p, 1, s.id)
    assert back is not None and len(back.beats) == 1 and back.prev is None
    with pytest.raises(ValueError):
        pipeline.undo_stage(p, 1, s.id)  # 적용 취소는 한 번
    # 처음 적용한 장면을 다시 적용 취소하면 장면이 빠진다
    s3 = pipeline.apply_stage(p, pipeline.draft_stage(MockLLM(), p, 1, 1))
    assert pipeline.undo_stage(p, 1, s3.id) is None and stage.scenes_of(p.episode(1), 1) == (None, None)


def test_extract_keeps_plan_and_marks_unknown_hands():
    p = _project()
    plan = pipeline.apply_stage(p, pipeline.draft_stage(MockLLM(), p, 1, 0))
    prop = pipeline.extract_stage(MockLLM(), p, 1, 0)
    assert prop.role == "text" and prop.scene.basis == pipeline.text_basis(TEXT) and prop.scene.room == plan.room
    assert all(b.left == "?" and b.right == "?" for b in prop.scene.start)  # 본문이 말하기 전까지 손은 모름
    assert prop.scene.beats[0].quote == "도윤이 문을 열었다."
    text = pipeline.apply_stage(p, prop)
    assert stage.scenes_of(p.episode(1), 0) == (plan, text)  # 본문 장면은 계획을 덮지 않는다


def test_from_draft_names_memos_and_minor_block():
    p = _project(minor=True)
    ep = p.episode(1)
    room = stage.make_room("bedroom", "r1")
    d = StageDraft(cast=["하린", "도윤", "유령"], start=[
        DraftBody(name="하린", at_ref="침대", at_rel="on", posture="lie", facing="도윤", left="빈손", right="휴대폰"),
        DraftBody(name="도윤", at_ref="부엌", at_rel="front", posture="stand", facing="침대"),
    ], beats=[
        DraftBeat(quote="도윤이 다가왔다.", bodies=[DraftBody(name="도윤", at_ref="하린", at_rel="front", posture="walk"),
                                                 DraftBody(name="유령", posture="stand")]),
        DraftBeat(quote="입을 맞췄다.", bodies=[DraftBody(name="도윤", contacts=[
            DraftContact(by="lips", to="하린", part="chest", act="kiss"),
            DraftContact(by="right", to="하린", part="hand_l", act="hold")])]),
        DraftBeat(quote="손을 놓았다.", bodies=[DraftBody(name="도윤", ends=[{"to": "하린", "part": "hand_l"}])]),
    ])
    s, dropped, notes = stage.from_draft(d, p, ep, 0, room, "text")
    assert s.cast == ["h", "d"] and dropped == 1  # 미성년이 낀 성적 접촉은 뺀다
    assert any("유령" in x for x in notes) and "유령" in s.beats[0].note
    h = next(b for b in s.start if b.who == "h")
    dy = next(b for b in s.start if b.who == "d")
    assert h.at.ref == _a(room, "침대") and h.facing == "@d" and h.left == "" and h.right == "휴대폰"
    assert dy.at is None and "부엌" in dy.memo and dy.facing == f"#{_a(room, '침대')}" and dy.left == "?"
    assert s.beats[0].bodies[0].at.ref == "@h"
    kept = s.beats[1].bodies[0].contacts
    assert [(c.part, c.act) for c in kept] == [("hand_l", "hold")]
    assert s.beats[2].bodies[0].ends == [kept[0].id]  # 끝난 접촉은 대상 · 부위로 찾는다


def _a(room, name):
    return next(a.id for a in room.anchors if a.name == name)


def _bad_text_scene(p: Project, quote: str = "도윤이 하린의 어깨를 잡았다.") -> StageScene:
    """창가의 하린과 문 앞의 도윤: 다가가지 않고 손이 닿는다 (거리 규칙)."""
    room = stage.new_room(p, "bedroom")
    s = StageScene(id="t1", event=1, event_text="하린이 붙잡는다", room=room.id, cast=["h", "d"], role="text", source="text",
                   basis=pipeline.text_basis(p.episode(1).text), start=[
                       StageBody(who="h", at=StageSpot(ref=_a(room, "창"), rel="front"), posture="stand", left="?", right="?"),
                       StageBody(who="d", at=StageSpot(ref=_a(room, "문"), rel="front"), posture="stand", left="?", right="?")],
                   beats=[StageBeat(quote=quote, bodies=[StageBody(who="d", contacts=[
                       StageContact(id="c1", by="right", to="h", part="shoulder_l", act="hold")])])])
    p.episode(1).stage.append(s)
    return s


def test_web_draft_job_compare_apply_undo(client):
    from canon import jobs, store

    store.save("sa", _project())
    r = client.post("/api/projects/sa/jobs", json={"kind": "stage_draft", "ep": 1, "event": 1}).json()
    assert r["kind"] == "stage_draft"
    for _ in range(200):
        if not any(j.status == "running" for j in jobs.listing("sa")):
            break
        time.sleep(0.02)
    v = client.get("/api/projects/sa/stage/1").json()
    assert v["scenes"] == [] and [(x["event"], x["role"]) for x in v["proposals"]] == [(1, "plan")]
    assert v["proposals"][0]["violations"] == []
    assert client.post("/api/projects/sa/jobs", json={"kind": "stage_extract", "ep": 1, "event": 9}).status_code == 400
    v = client.post("/api/projects/sa/stage/1/apply", json={"event": 1, "role": "plan"}).json()
    assert v["proposals"] == [] and v["scenes"][0]["scene"]["source"] == "plot" and len(v["rooms"]) == 1
    assert client.post("/api/projects/sa/stage/1/apply", json={"event": 1, "role": "plan"}).status_code == 400
    v = client.post(f"/api/projects/sa/stage/1/{v['made']}/undo").json()
    assert v["scenes"] == []
