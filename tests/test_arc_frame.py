"""부 · 아크 기획의 이야기 틀 (docs/webnovel/specs/04-arc-frame.md): 틀별 응답 형식, 빈 칸이 새지 않음, 얻는 성장 · 공략 대상 칸 (mock LLM).
틀별 요청 글은 tests/test_frame.py 의 test_frame_changes_only_arc_planning 과 tests/test_prompt_registry.py 스냅샷이 본다.
실행: python -m pytest tests/test_arc_frame.py"""
import json

from canon import pipeline, prompts
from canon.schema import (ArcEdit, ArcProposal, ChatScope, HeatArcProposal, PlotAgentStep, PlotRevision, Project, SerialConversion,
                          SerialRebuild, StoryArc, framed)

from .jsvm import needs_node, run_js
from .test_serial import LLM, _plan_arc, _serial

FORMATS = (ArcProposal, HeatArcProposal, PlotRevision, PlotAgentStep, SerialConversion, SerialRebuild)


def _arc_schema(model) -> dict:
    s = model.model_json_schema()
    return {**s.get("$defs", {}), model.__name__: s}


def test_drama_formats_are_the_same_classes():
    p = _serial()
    assert prompts.arc_axes(p) == (False, False)
    assert all(prompts.arc_schema(p, m) is m for m in FORMATS)
    for m in (StoryArc, ArcEdit):  # 저장 모델은 새 칸을 응답 형식에 넣지 않는다
        props = m.model_json_schema()["properties"]
        assert "gain" not in props and "focus" not in props


def test_webnovel_and_harem_formats():
    p = _serial()
    p.meta.frame = "webnovel"
    assert prompts.arc_axes(p) == (True, False)
    defs = _arc_schema(prompts.arc_schema(p, ArcProposal))
    arc = defs["StoryArc"]["properties"]
    assert "gain" in arc and "focus" not in arc and "짧은 고구마" in arc["conflict"]["description"]
    p.meta.genres = ["harem"]
    edit = _arc_schema(prompts.arc_schema(p, PlotAgentStep))["ArcEdit"]["properties"]
    assert "gain" in edit and "focus" in edit
    assert issubclass(prompts.arc_schema(p, HeatArcProposal), HeatArcProposal)
    p.meta.form = "short"  # 단편은 아크를 기획하지 않는다
    assert prompts.arc_axes(p) == (False, False)


def test_empty_fields_do_not_leak():
    a = StoryArc(number=1, title="t", start_ep=1, end_ep=5, goal="g")
    assert "gain" not in a.model_dump() and "focus" not in json.loads(a.model_dump_json())
    assert "gain" not in ArcEdit().model_dump()
    old = Project.model_validate({"story_arcs": [{"number": 1, "title": "t", "start_ep": 1, "end_ep": 5, "goal": "g"}]})
    assert old.story_arcs[0].gain == "" and old.story_arcs[0].focus == ""
    a.gain, a.focus = "검술 해금", "ally"
    back = Project.model_validate_json(Project(story_arcs=[a]).model_dump_json()).story_arcs[0]
    assert (back.gain, back.focus) == ("검술 해금", "ally")


def test_next_arc_webnovel_harem():
    p = _serial()
    p.meta.frame, p.meta.genres = "webnovel", ["harem"]
    prop = pipeline.plan_next_arc(LLM, p)
    assert (prop.arc.gain, prop.arc.focus) == ("새 기술 해금", "ally")
    a = pipeline.apply_arc(p, prop)
    assert isinstance(a, StoryArc)
    assert (p.story_arcs[-1].gain, p.story_arcs[-1].focus) == ("새 기술 해금", "ally")
    ask = prompts.next_arc_prompt(p, pipeline.next_arc_start(p), 12, "")
    assert '"gain": "새 기술 해금"' in ask and "보상 루프 한 바퀴" in ask and "공략 대상" in ask  # 직전 아크 덤프와 틀 줄
    assert "같은 모양의 갈등" not in ask


def test_unknown_focus_is_cleared():
    p = _serial()
    p.meta.genres = ["harem"]
    prop = pipeline.plan_next_arc(LLM, p)
    prop.arc.focus = "nobody"
    assert pipeline.clean_arc(p, prop).arc.focus == ""


def test_plot_chat_keeps_fields_the_frame_did_not_ask():
    """드라마 틀 작품(틀을 되돌린 작품)의 아크에 적힌 성장 · 공략 대상은 플롯 대화의 아크 칸 변경이 지우지 않는다."""
    p = _serial()
    _plan_arc(p)
    a2 = _plan_arc(p)
    a2.gain, a2.focus = "검술 해금", "ally"
    rev = pipeline.revise_plot(LLM, p, "갈등을 바꿔 줘", ChatScope(target=f"arc:{a2.number}"))
    assert rev.arc.conflict == "옛 동료의 배신" and (rev.arc.gain, rev.arc.focus) == ("검술 해금", "ally")
    pipeline.apply_revision(p, rev, False, [], arc=True, target=f"arc:{a2.number}")
    assert (p.story_arcs[1].conflict, p.story_arcs[1].gain, p.story_arcs[1].focus) == ("옛 동료의 배신", "검술 해금", "ally")


def test_plot_chat_next_arc_keeps_draft_fields():
    """드라마 틀에서 작가가 다음 아크 초안에 적은 성장 · 공략 대상은 플롯 대화가 초안을 고쳐도 남는다 (응답 형식이 묻지 않는 칸)."""
    p = _serial()
    _plan_arc(p)
    draft = pipeline.plan_next_arc(LLM, p)
    draft.arc.gain, draft.arc.focus = "검술 해금", "ally"
    rev = pipeline.revise_plot(LLM, p, "갈등을 더 아프게", ChatScope(target="next", draft=draft))
    assert rev.arc.conflict == "옛 동료의 배신" and (rev.arc.gain, rev.arc.focus) == ("검술 해금", "ally")


def test_framed_values_validate_as_stored_models():
    m = framed(ArcProposal, True, True)
    got = m.model_validate({"arc": {"number": 1, "title": "t", "start_ep": 1, "end_ep": 9, "goal": "g", "gain": "레벨업", "focus": "ally"}})
    assert isinstance(got, ArcProposal) and ArcProposal.model_validate(got.model_dump()).arc.gain == "레벨업"


@needs_node
def test_arc_card_shows_frame_fields_only_when_asked():
    a = StoryArc(number=1, title="t", start_ep=1, end_ep=9, goal="g").model_dump()
    expr = """(() => { const out = {}; for (const [k, meta, arc] of data.cases) { S.project = { ...data.p, meta, story_arcs: [arc] };
        out[k] = arcFrameInputs(arc, 'story_arcs.0'); } return out; })()"""
    cases = [["drama", {"frame": "drama", "genres": []}, a], ["web", {"frame": "webnovel", "genres": []}, a],
             ["harem", {"frame": "drama", "genres": ["harem"]}, a], ["kept", {"frame": "drama", "genres": []}, {**a, "gain": "해금"}]]
    got = run_js(["app.js"], expr, {"cases": cases, "p": Project().model_dump()})
    assert got["drama"] == ""  # 드라마 틀 · 빈 칸이면 늘 보이는 칸이 늘지 않는다
    assert "얻는 성장" in got["web"] and "공략 대상" not in got["web"]
    assert "공략 대상" in got["harem"] and "얻는 성장" not in got["harem"]
    assert "얻는 성장" in got["kept"]  # 틀을 되돌려도 적힌 값은 보인다


def test_filled_fields_reach_only_planning_requests():
    """값이 찬 gain · focus 는 부 · 아크 기획과 아크 분석 요청에만 들어간다. 화별 플롯 · 본문 쓰기 · 검수의 '지금 부와 아크'(structure_text)에는 넣지 않는다 (일감 6 이 정한다)."""
    from . import test_prompt_registry as reg

    p = reg._web(reg._long)
    for a in p.story_arcs:
        a.gain, a.focus = "검술 해금 표지", "ally"
    got = {**reg._requests(p), **reg._arc_requests(p)}
    assert sorted(k for k, v in got.items() if "검술 해금 표지" in v) == ["brief:agent_plot", "brief:arc", "impact", "plot_chat:arc", "plot_chat:next", "recap"]


def test_framed_instances_save_and_reload(tmp_path, monkeypatch, client):
    """틀별 판으로 받은 아크 · 플롯 대화 변경안 · 에이전트 단계가 경고 없이 저장되고 다시 읽힌다 (mock 이 판으로 낸다)."""
    import warnings

    from canon import store

    from .test_agent import _say, _session

    p = _serial()
    p.meta.frame, p.meta.genres = "webnovel", ["harem"]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        prop = pipeline.plan_next_arc(LLM, p)
        assert type(prop) is not ArcProposal and type(prop.arc) is not StoryArc  # 판
        a = pipeline.apply_arc(p, prop)
        assert type(a) is StoryArc
        _plan_arc(p)
        rev = pipeline.revise_plot(LLM, p, "갈등을 바꿔 줘", ChatScope(target="arc:1"))
        assert type(rev) is not PlotRevision
        pipeline.apply_revision(p, rev, False, [], arc=True, target="arc:1")
        pipeline.record_chat(p, "plot", "갈등을 바꿔 줘", rev, ChatScope(target="arc:1"))
        store.save("fw", p)
        back = store.load("fw")
        assert (back.story_arcs[0].gain, back.story_arcs[0].focus, back.story_arcs[0].conflict) == ("새 기술 해금", "ally", "옛 동료의 배신")
        sid = _session(client, name="fw", target="arc:2")
        t = _say(client, sid, "갈등을 바꿔 줘", name="fw")
        arc = t["approval"]["revision"]["arc"]  # 아크 칸 변경은 승인을 기다린다. 세션에 저장된 변경안이 두 칸을 가진다
        assert t["end"] == "wait" and (arc["conflict"], arc["gain"], arc["focus"]) == ("옛 동료의 배신", "새 기술 해금", "ally")
