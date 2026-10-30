"""아크 · 부 · 플롯 대화형 수립 테스트 (mock LLM). 실행: python -m pytest tests"""
import pytest

from canon import pipeline, prompts
from canon.mock import MockLLM
from canon.schema import ArcProposal, ChatScope, StoryArc

from .test_serial import LLM, _plan_arc, _serial
from .test_web import client  # noqa: F401  (pytest fixture)


def _three_arcs():
    p = _serial()
    a1, a2, a3 = _plan_arc(p), _plan_arc(p), _plan_arc(p)
    for n in range(a1.start_ep, a1.end_ep + 1):
        p.episode(n).status = "finalized"
    return p, a1, a2, a3


def test_chat_targets_the_arc_picked_on_screen():
    p, a1, a2, a3 = _three_arcs()
    assert pipeline.chat_target(p, "") == ("arc:2", a2)  # 고르지 않으면 본문이 없는 첫 아크
    rev = pipeline.revise_plot(LLM, p, "결말을 비극으로", ChatScope(target="arc:3"))
    assert rev.acts and rev.acts[0].start_ep == a3.start_ep
    pipeline.apply_revision(p, rev, True, [], target="arc:3")
    assert p.story_arcs[2].acts[-1].goal == "비극으로 끝난다"
    assert p.story_arcs[1].acts[-1].goal != "비극으로 끝난다"
    with pytest.raises(ValueError, match="아크 9"):
        pipeline.chat_target(p, "arc:9")


def test_arc_fields_and_last_arc_end():
    p, a1, a2, a3 = _three_arcs()
    old = a3.end_ep
    rev = pipeline.revise_plot(LLM, p, f"갈등을 바꾸고 끝 화 {old + 4}", ChatScope(target="arc:3"))
    assert rev.arc.conflict == "옛 동료의 배신" and rev.arc.end_ep == old + 4
    assert rev.acts[-1].end_ep == old + 4  # 끝 화만 바꿔도 구간을 새 범위에 맞춰 함께 낸다
    done = pipeline.apply_revision(p, rev, False, [], arc=True, target="arc:3")
    assert done == ["arc", "acts"]  # 끝 화가 바뀌면 구조도 함께 들어간다
    assert (p.story_arcs[2].conflict, p.story_arcs[2].end_ep, p.planned_until()) == ("옛 동료의 배신", old + 4, old + 4)

    # 가운데 아크는 끝 화를 바꿀 수 없다: 칸만 남고 끝 화는 빠진다
    rev = pipeline.revise_plot(LLM, p, f"갈등을 바꾸고 끝 화 {a2.end_ep + 2}", ChatScope(target="arc:2"))
    assert rev.arc.conflict == "옛 동료의 배신" and rev.arc.end_ep == 0 and not rev.acts
    assert "다음 아크가 이어져" in rev.reply

    # 줄이면 확정한 화가 빠지는 끝 화도 뺀다
    rev = pipeline.revise_plot(LLM, p, f"끝 화 {a3.start_ep + 4}", ChatScope(target="arc:3"))
    assert rev.arc.end_ep == 0 and "빠져" in rev.reply


def test_next_arc_made_and_refined_by_chat():
    p, a1, a2, a3 = _three_arcs()
    start = p.planned_until() + 1
    rev = pipeline.revise_plot(LLM, p, "15화짜리 시험 아크를 짜 줘", ChatScope(target="next"))
    assert (rev.arc.title, rev.arc.end_ep) == ("대화로 짠 아크", start + 14)
    assert rev.acts[0].start_ep == start and rev.acts[-1].end_ep == start + 14
    assert [c.id for c in rev.new_characters] == ["rival9"]  # 아크의 새 인물은 화에 나오지 않아도 남긴다
    assert pipeline.apply_revision(p, rev, True, [], arc=True, target="next") == []  # 작품은 바꾸지 않는다

    # 화면은 이 안을 초안으로 놓고, 다시 대화로 고친다
    fields = rev.arc.model_dump(exclude={"end_ep"})
    draft = ArcProposal(arc=StoryArc(number=4, start_ep=start, end_ep=rev.arc.end_ep, acts=rev.acts, **fields),
                        new_characters=rev.new_characters)
    rev2 = pipeline.revise_plot(LLM, p, "갈등을 더 아프게", ChatScope(target="next", draft=draft))
    assert rev2.arc.conflict == "옛 동료의 배신" and rev2.arc.title == "대화로 짠 아크" and rev2.arc.end_ep == start + 14
    same = pipeline.revise_plot(LLM, p, "그대로 둬", ChatScope(target="next", draft=draft))
    assert not same.arc.title and not same.acts  # 초안과 같으면 변경안이 아니다
    draft.arc.conflict = rev2.arc.conflict
    a4 = pipeline.apply_arc(p, draft)
    assert (a4.number, a4.start_ep, a4.conflict) == (4, start, "옛 동료의 배신")
    assert any(c.id == "rival9" for c in p.cast_candidates) and not any(c.id == "rival9" for c in p.characters)  # 후보로


def test_parts_changed_by_chat_keep_summaries():
    p, *_ = _three_arcs()
    p.parts[1].summary = "2부 요약"
    rev = pipeline.revise_plot(LLM, p, "부 구성에서 1부 목표를 고쳐 줘", ChatScope(target="arc:2"))
    assert len(rev.parts) == 3 and all(not x.summary for x in rev.parts)
    assert pipeline.apply_revision(p, rev, False, [], parts=True, target="arc:2") == ["parts"]
    assert p.parts[0].goal.endswith("(대화로 고침)") and p.parts[1].summary == "2부 요약"


def test_options_mode_returns_directions_only():
    p, *_ = _three_arcs()
    scope = ChatScope(target="arc:2", mode="options", act="승")
    rev = pipeline.revise_plot(LLM, p, "다음 전개 방향을 몇 가지 보여 줘", scope)
    assert [x.title for x in rev.options] == ["배신", "추격", "고백"]
    assert not (rev.acts or rev.episodes or rev.arc.title or rev.parts)  # 방향만 받는다
    reply = pipeline.record_chat(p, "plot", "다음 전개 방향을 몇 가지 보여 줘", rev, scope)
    asked = p.chat("plot").messages[-2]
    assert reply.revision is not None and reply.target == "arc:2" and asked.mode == "options"
    assert asked.where.startswith("아크 2") and "승 구간" in asked.where
    line = prompts._chat_line(reply)
    assert "방향 안: 1. 배신" in line
    pr = prompts.plot_chat_prompt(p, "2안으로 가자", ChatScope(target="arc:2", episode=15))
    assert "[작가가 보고 있는 곳] 아크 2" in pr and "15화" in pr and "[방향 여러 안 요청]" in pr


def test_short_story_chat_can_start_structure():
    from canon.schema import Project

    p = Project()
    p.meta.title, p.meta.target_episodes = "등대", 10
    pipeline.apply_setup(p, pipeline.suggest_setup(LLM, p))
    rev = pipeline.revise_plot(LLM, p, "비극으로 끝나는 구조를 같이 짜자")
    assert len(rev.acts) == 4 and not rev.arc.title and not rev.parts
    assert "아직 구조가 없습니다" in prompts.plot_chat_prompt(p, "x")
    pipeline.apply_revision(p, rev, True, [])
    assert [a.name for a in p.arc] == ["기", "승", "전", "결"]


class _Spy(MockLLM):
    def __init__(self):
        self.prompts = []

    def json(self, system, prompt, schema, hint=None):
        self.prompts.append(prompt)
        return super().json(system, prompt, schema, hint)


def test_request_note_reaches_planning_prompts():
    spy = _Spy()
    p = _serial()
    pipeline.plan_series(spy, p, "3부는 바다로")
    a = _plan_arc(p)
    pipeline.draft_plots(spy, p, a.start_ep, a.start_ep + 1, "1화에 바로 싸움")
    assert spy.prompts[0].rstrip().endswith("작가의 요청을 먼저 따릅니다.") and "3부는 바다로" in spy.prompts[0]
    assert "1화에 바로 싸움" in spy.prompts[1]
    assert prompts.request_block("") == ""


def test_web_chat_target_and_draft_apply(client):  # noqa: F811
    client.post("/api/projects", json={"name": "tw", "meta": {"title": "탑", "form": "serial", "target_episodes": 300}})
    s = client.post("/api/projects/tw/suggest").json()
    client.post("/api/projects/tw/suggest/apply", json=s)
    p = client.post("/api/projects/tw/chat/plot", json={"message": "12화짜리 첫 아크", "target": "next"}).json()
    m = p["chats"][0]["messages"]
    assert m[-1]["target"] == "next" and m[-1]["revision"]["arc"]["end_ep"] == 12
    assert m[-2]["where"].startswith("다음 아크 기획")
    i = len(m) - 1
    assert client.post(f"/api/projects/tw/chat/plot/{i}/apply", json={}).status_code == 400
    p = client.post(f"/api/projects/tw/chat/plot/{i}/apply", json={"draft": ["arc"]}).json()
    assert p["story_arcs"] == [] and p["chats"][0]["messages"][-1]["applied"] == ["arc"]
    # 초안을 적용한 뒤 그 아크를 골라 아크 칸을 고친다
    rev = p["chats"][0]["messages"][-1]["revision"]
    arc = {**{k: v for k, v in rev["arc"].items() if k != "end_ep"}, "number": 1, "start_ep": 1, "end_ep": 12, "acts": rev["acts"]}
    p = client.post("/api/projects/tw/arcs/apply", json={"arc": arc, "new_characters": rev["new_characters"]}).json()
    p = client.post("/api/projects/tw/chat/plot", json={"message": "갈등을 바꿔 줘", "target": "arc:1", "act": "승"}).json()
    i = len(p["chats"][0]["messages"]) - 1
    p = client.post(f"/api/projects/tw/chat/plot/{i}/apply", json={"arc": True}).json()
    assert p["story_arcs"][0]["conflict"] == "옛 동료의 배신"
    assert client.post("/api/projects/tw/chat/plot", json={"message": "x", "target": "arc:7"}).status_code == 400
