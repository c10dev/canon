"""장면 연출 AI(일감 03)와 검수 연결(04): 초안 · 뽑기 → 비교 → 적용 · 적용 취소, 이름 정리와 막기, 규칙 지적, 검수 때 함께 뽑기.
mock LLM. 실행: python -m pytest tests"""
import threading
import time

import pytest

from canon import cancel, findings, pipeline, prompts, stage
from canon.llm import Interrupted
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


def _plan(p: Project, *events: int) -> None:
    """사건마다 빈 계획 장면을 붙인다. 검수 때 함께 뽑기는 계획 장면이 있는 사건만 뽑는다."""
    ep = p.episode(1)
    for i in events:
        ep.stage.append(StageScene(id=f"p{i}", event=i, event_text=ep.plot.events[i], role="plan", source="plot"))


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


class EmptyFirst(Counting):
    """첫 StageDraft 응답만 박자를 비운다 (03 측정: 12회 중 1회)."""

    def json(self, system, prompt, schema, hint=None):
        out = super().json(system, prompt, schema, hint)
        if schema is StageDraft and len(self.calls) == 1:
            out.beats = []
        return out


def test_extract_asks_again_once_when_beats_empty():
    p = _project()
    llm = EmptyFirst()
    prop = pipeline.extract_stage(llm, p, 1, 0)
    assert llm.calls == ["StageDraft", "StageDraft"] and prop.scene.beats  # 한 번 다시 물어 박자를 받는다

    class AlwaysEmpty(Counting):
        def json(self, system, prompt, schema, hint=None):
            out = super().json(system, prompt, schema, hint)
            out.beats = []
            return out

    llm = AlwaysEmpty()
    assert pipeline.extract_stage(llm, p, 1, 0).scene.beats == [] and len(llm.calls) == 2  # 두 번째도 비면 그대로 둔다
    llm = Counting()
    pipeline.extract_stage(llm, p, 1, 0)
    assert len(llm.calls) == 1  # 박자가 있으면 다시 묻지 않는다


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
    ], new_anchors=[])
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


def test_rule_findings_merge_keep_and_recheck_without_llm():
    p = _project()
    _bad_text_scene(p)
    r = pipeline.apply_check(p, ConsistencyReport(episode=1))
    ep = p.episode(1)
    assert r.stage and r.added == 1
    f = ep.findings[0]
    assert (f.origin, f.type, f.severity, f.stage_event, f.stage_beat) == ("rule", "동선", "low", 1, 1)
    assert f.current_quote == "도윤이 하린의 어깨를 잡았다." and "거리" in f.description
    findings.set_status(ep, f.id, "kept", "연출이 이게 맞아요", "t")
    r2 = pipeline.apply_check(p, ConsistencyReport(episode=1))
    assert r2.kept_again == 1 and ep.findings[0].status == "kept" and len(ep.findings) == 1
    # 검수 모델이 같은 문장을 짚으면 규칙 지적은 넣지 않고, 출처가 다른 옛 지적과 섞지 않는다
    ai = ConsistencyReport(episode=1, issues=[{"type": "동선", "description": "AI", "source_quote": "", "current_quote": "도윤이 하린의 어깨를 잡았다."}])
    pipeline.apply_check(p, ai)
    assert [(x.origin, x.description) for x in ep.findings] == [("rule", f.description), ("ai", "AI")]
    # 규칙 지적의 다시 검수는 LLM 없이 판정만
    findings.set_status(ep, f.id, "open", None, "t")
    assert pipeline.recheck_finding(NoLLM(), p, 1, f.id).resolved is False
    ep.stage[0].beats[0].bodies[0].contacts = []
    res = pipeline.recheck_finding(NoLLM(), p, 1, f.id)
    assert res.resolved is True and res.new_issues == []


def test_plan_only_beats_stay_off_the_session():
    p = _project()
    s = _bad_text_scene(p, quote="")  # 인용 없는 박자 (쓰기 전 연출과 같다)
    s.beats[0].note = "도윤이 손을 뻗는다"
    assert stage.episode_issues(p, p.episode(1)) == []
    assert stage.check(p, p.episode(1), s, stage.room_of(p, s))["violations"]  # 장면 연출 화면에는 보인다


def test_check_extracts_only_when_on_and_text_changed():
    p = _project()
    llm = Counting()
    p.settings.stage_extract = False
    pipeline.apply_check(p, pipeline.check_episode(llm, p, 1))
    assert llm.calls == ["ConsistencyReport"] and p.episode(1).stage == []  # 끄면 뽑기 호출이 없다
    p.settings.stage_extract = True
    llm.calls.clear()
    pipeline.check_episode(llm, p, 1)
    assert llm.calls == ["ConsistencyReport"]  # 계획 장면이 없으면 뽑지 않는다 (장면 연출 화면 버튼으로)
    _plan(p, 0, 1)
    llm.calls.clear()
    rep = pipeline.check_episode(llm, p, 1)
    assert llm.calls == ["ConsistencyReport", "StageDraft", "StageDraft"]  # 계획 장면이 있는 사건마다 하나
    pipeline.apply_check(p, rep)
    assert [s.role for s in p.episode(1).stage] == ["plan", "plan", "text", "text"] and len(p.rooms) == 2
    llm.calls.clear()
    pipeline.apply_check(p, pipeline.check_episode(llm, p, 1))
    assert llm.calls == ["ConsistencyReport"]  # 본문이 그대로면 다시 뽑지 않는다


def test_check_extracts_only_planned_events():
    p = _project()
    _plan(p, 1)
    llm = Counting()
    rep = pipeline.check_episode(llm, p, 1)
    assert llm.calls == ["ConsistencyReport", "StageDraft"] and [x.event for x in rep._stage] == [1]


class Gate(MockLLM):
    """장면 뽑기 호출을 붙잡아 동시에 몇 개가 들어오는지 잰다."""
    def __init__(self, hold: int):
        self.hold, self.now, self.most, self.lock, self.go = hold, 0, 0, threading.Lock(), threading.Event()

    def json(self, system, prompt, schema, hint=None):
        if schema is StageDraft:
            with self.lock:
                self.now += 1
                self.most = max(self.most, self.now)
                if self.now >= self.hold:
                    self.go.set()
            self.go.wait(5)
            with self.lock:
                self.now -= 1
        return super().json(system, prompt, schema, hint)


def test_check_extracts_events_at_the_same_time_up_to_the_limit():
    p = _project()
    p.episode(1).plot.events += ["도윤이 앉는다", "하린이 돌아선다", "둘이 나간다"]
    _plan(p, 0, 1, 2, 3, 4)
    llm = Gate(pipeline.STAGE_EXTRACT_WORKERS)
    t = time.perf_counter()
    auto, held = pipeline.stage_extract_all(llm, p, 1)
    assert time.perf_counter() - t < 4  # 차례로 불렀으면 첫 호출이 5초를 기다린다
    assert llm.most == pipeline.STAGE_EXTRACT_WORKERS  # 동시 호출 수 상한
    assert [x.event for x in auto] == [0, 1, 2, 3, 4] and held == []  # 결과는 사건 차례


def test_check_extract_passes_context_and_stops_on_cancel():
    p = _project()
    _plan(p, 0, 1)
    seen = []

    class See(MockLLM):
        def json(self, system, prompt, schema, hint=None):
            seen.append(cancel.current.get())
            return super().json(system, prompt, schema, hint)

    ev = threading.Event()
    tok = cancel.current.set(ev)
    try:
        pipeline.stage_extract_all(See(), p, 1)
        assert seen == [ev, ev]  # 스레드에도 작업 정보(contextvars)가 간다
        ev.set()
        seen.clear()
        with pytest.raises(cancel.Cancelled):
            pipeline.stage_extract_all(See(), p, 1)
        assert seen == []  # 멈춘 뒤에는 부르지 않는다
    finally:
        cancel.current.reset(tok)


def test_check_extract_raises_batch_interrupt_but_skips_other_failures():
    p = _project()
    _plan(p, 0, 1)

    class Fail(MockLLM):
        def __init__(self, err):
            self.err = err

        def json(self, system, prompt, schema, hint=None):
            if schema is StageDraft and hint["event"] == 0:
                raise self.err
            return super().json(system, prompt, schema, hint)

    auto, _ = pipeline.stage_extract_all(Fail(RuntimeError("x")), p, 1)
    assert [x.event for x in auto] == [1]  # 한 사건이 실패해도 잇는다
    with pytest.raises(Interrupted):  # 자동 집필 배치의 멈춤 · 일시정지는 올린다
        pipeline.stage_extract_all(Fail(Interrupted(cancelled=False)), p, 1)


def test_check_does_not_overwrite_author_text_scene():
    p = _project()
    s = _bad_text_scene(p)
    s.basis = "old"
    s2 = s.model_copy(deep=True)
    s2.beats[0].note = "작가가 고침"
    stage.save_scene(p, p.episode(1), s2, None)
    assert p.episode(1).stage[0].source == "manual"  # 작가가 손본 본문 장면
    _plan(p, 0, 1)
    rep = pipeline.check_episode(MockLLM(), p, 1)
    assert [x.event for x in rep._stage_held] == [1] and [x.event for x in rep._stage] == [0]
    pipeline.apply_check(p, rep)
    kept = stage.scenes_of(p.episode(1), 1)[1]
    assert kept.beats[0].note == "작가가 고침" and kept.prev is None
    assert any(f.origin == "rule" for f in p.episode(1).findings)  # 작가 장면도 판정한다


def test_motion_fixes_drop_added_sentences():
    p = _project()
    ep = p.episode(1)
    _bad_text_scene(p)
    pipeline.apply_check(p, ConsistencyReport(episode=1))
    fd = ep.findings[0]
    fs = FixSet(options=[FixOption(label="낱말", text="도윤이 다가가 하린의 어깨를 잡았다."),
                         FixOption(label="문장", text="도윤이 창가로 걸어갔다. 그리고 하린의 어깨를 잡았다.")])
    assert [o.label for o in pipeline.clean_fixes(ep, fd, fs)] == ["낱말"]


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
    assert v["proposals"][0]["moves"] == [] and "at_ref 를 그 기준점으로 바꿉니다" in prompts.stage_draft_prompt(store.load("sa"), 1, 1)
    assert client.post("/api/projects/sa/jobs", json={"kind": "stage_extract", "ep": 1, "event": 9}).status_code == 400
    v = client.post("/api/projects/sa/stage/1/apply", json={"event": 1, "role": "plan"}).json()
    assert v["proposals"] == [] and v["scenes"][0]["scene"]["source"] == "plot" and len(v["rooms"]) == 1
    assert client.post("/api/projects/sa/stage/1/apply", json={"event": 1, "role": "plan"}).status_code == 400
    v = client.post(f"/api/projects/sa/stage/1/{v['made']}/undo").json()
    assert v["scenes"] == []
    assert client.put("/api/projects/sa/stage-extract", json={"on": False}).json()["settings"]["stage_extract"] is False
