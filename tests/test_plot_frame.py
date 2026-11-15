"""화별 플롯의 이야기 틀 (docs/webnovel/specs/06-plot-frame.md): 틀별 규칙 줄, 이 화의 사이다(EpisodePlot.reward) 칸, 묻지 않은 칸 지키기 (mock LLM).
틀별 요청 글은 tests/test_frame.py 의 test_frame_changes_only_logline_arc_and_plot_planning 과 tests/test_prompt_registry.py 스냅샷이 본다.
실행: python -m pytest tests/test_plot_frame.py"""
import json

from canon import opening, pipeline, prompts
from canon.schema import (ChatScope, EpisodeDraft, EpisodePlot, ImpactReport, OpeningPlots, PlotAgentStep, PlotBatch, PlotRevision,
                          Project, framed)

from .jsvm import needs_node, run_js
from .test_serial import LLM, _plan_arc, _serial

FORMATS = (PlotBatch, EpisodeDraft, PlotRevision, PlotAgentStep, ImpactReport, OpeningPlots)


def _episode_props(model) -> dict:
    return model.model_json_schema()["$defs"]["EpisodePlot"]["properties"]


def _rules(p) -> str:
    return prompts.plot_rules(p, opening=True)


def test_drama_rules_and_formats_unchanged():
    p = _serial()
    assert all(prompts.arc_schema(p, m) is m for m in FORMATS)
    assert "reward" not in EpisodePlot.model_json_schema()["properties"]
    text = _rules(p)
    assert prompts.PLOT_VARIETY[False] in text and prompts.PLOT_REWARD not in text and prompts.PLOT_HAREM not in text


def test_webnovel_serial_rules_and_formats():
    p = _serial()
    p.meta.frame = "webnovel"
    text = _rules(p)
    assert prompts.PLOT_VARIETY[True] in text and prompts.PLOT_VARIETY[False] not in text
    assert prompts.PLOT_REWARD in text and prompts.PLOT_GAIN in text and prompts.PLOT_HAREM not in text
    assert "주인공의 잘못된 선택" not in text and "너무 깔끔하게 정리하지 않습니다" not in text
    for m in FORMATS:
        assert "reward" in _episode_props(prompts.arc_schema(p, m)), m.__name__


def test_harem_alone_adds_only_the_relation_line():
    """하렘 요소는 틀과 따로 간다: 드라마 틀 장편에도 관계 줄만 더하고, 사이다 줄과 reward 칸은 없다."""
    p = _serial()
    p.meta.genres = [*p.meta.genres, "harem"]
    text = _rules(p)
    assert prompts.PLOT_HAREM in text and prompts.PLOT_VARIETY[False] in text and prompts.PLOT_REWARD not in text
    assert "reward" not in _episode_props(prompts.arc_schema(p, PlotBatch))


def test_short_stays_the_same_in_both_axes():
    """단편은 웹소설 틀 · 하렘 요소를 골라도 화별 플롯 규칙 · 초반 규칙 · 판정 항목 · 응답 형식이 그대로다 (정할 것 1)."""
    from . import test_prompt_registry as reg

    base = reg._short()
    base.meta.genres = [*base.meta.genres, "harem"]  # 하렘 장르의 초반 박자(일감 2)는 두 판이 같게
    p = base.model_copy(deep=True)
    p.meta.frame = "webnovel"
    assert _rules(p) == _rules(base) and prompts.PLOT_HAREM not in _rules(p)
    assert prompts.opening_rules(p, 1) == prompts.opening_rules(base, 1)
    assert prompts.hook_guide(p) == prompts.HOOK_GUIDE
    assert all(prompts.arc_schema(p, m) is m for m in FORMATS)


def test_opening_and_hook_lines():
    p = _serial()
    assert prompts.OPENING_LEAD[False] in prompts.opening_rules(p, 1)
    p.meta.frame = "webnovel"
    assert prompts.OPENING_LEAD[True] in prompts.opening_rules(p, 1) and prompts.OPENING_LEAD[False] not in prompts.opening_rules(p, 1)
    guide = prompts.hook_guide(p)
    assert list(guide) == list(prompts.HOOK_GUIDE) and guide["걸린 것"] == prompts.HOOK_WEB_STAKE  # 항목 이름(HookAspect)은 그대로


def test_empty_reward_does_not_leak():
    e = EpisodePlot(number=1, act="기", title="t", summary="s", events=["a"], characters=[], emotional_shift="", ending_hook="")
    assert "reward" not in e.model_dump() and "reward" not in json.loads(e.model_dump_json())
    old = Project.model_validate({"episodes": [{"plot": e.model_dump()}]})
    assert old.episodes[0].plot.reward == ""
    e.reward = "첫 응징"
    back = Project.model_validate_json(Project(episodes=[{"plot": e}]).model_dump_json()).episodes[0].plot
    assert back.reward == "첫 응징"
    got = framed(PlotBatch, True).model_validate({"episodes": [{**e.model_dump(), "reward": "레벨업"}]})
    assert isinstance(got, PlotBatch) and PlotBatch.model_validate(got.model_dump()).episodes[0].reward == "레벨업"


def test_mock_fills_reward_only_for_webnovel():
    p = _serial()
    a = _plan_arc(p)
    batch = pipeline.draft_plots(LLM, p, a.start_ep, a.start_ep + 1)
    assert all(not e.reward for e in batch.episodes)
    p = _serial()
    p.meta.frame = "webnovel"
    a = _plan_arc(p)
    batch = pipeline.draft_plots(LLM, p, a.start_ep, a.start_ep + 1)
    assert type(batch) is not PlotBatch and all(e.reward for e in batch.episodes)


def test_arc_gain_and_focus_reach_plot_drafts_only_on_their_axis():
    """정할 것 5: 장편 화별 플롯 초안의 '지금 부와 아크'에 축이 켜진 칸만 넣는다. 본문 쓰기에는 넣지 않는다."""
    p = _serial()
    a = _plan_arc(p)
    a.gain, a.focus = "검술 해금 표지", "ally"
    n = a.start_ep
    assert "검술 해금 표지" not in prompts.plot_prompt(p, n, n) and '"focus"' not in prompts.structure_text(p, n, plan=True)
    p.meta.frame = "webnovel"
    text = prompts.plot_prompt(p, n, n)
    assert "검술 해금 표지" in text and '"focus"' not in prompts.structure_text(p, n, plan=True)
    p.meta.genres = [*p.meta.genres, "harem"]
    assert '"focus": "ally"' in prompts.structure_text(p, n, plan=True)
    assert "검술 해금 표지" not in prompts.structure_text(p, n)  # 쓰기 · 검수 · 스토리보드 쪽


def _drama_with_reward():
    """웹소설 틀로 플롯을 받은 뒤 틀을 드라마식으로 되돌린 장편. 아크 첫 화에 사이다가 적혀 있다."""
    p = _serial()
    p.meta.frame = "webnovel"
    a = _plan_arc(p)
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, a.start_ep, a.end_ep))
    p.meta.frame = "drama"
    p.episode(a.start_ep).plot.reward = "작가가 적은 사이다"
    return p, a


def test_unasked_reward_survives_redraft_and_plot_chat():
    p, a = _drama_with_reward()
    n = a.start_ep
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, n, n))
    assert p.episode(n).plot.reward == "작가가 적은 사이다"
    rev = PlotRevision(reply="", episodes=[p.episode(n).plot.model_copy(update={"summary": "고친 요약", "reward": ""})])
    pipeline.apply_revision(p, rev, False, [n])
    assert (p.episode(n).plot.summary, p.episode(n).plot.reward) == ("고친 요약", "작가가 적은 사이다")
    p.meta.frame = "webnovel"  # 묻는 틀이면 AI 답(빈 칸)을 따른다
    pipeline.apply_revision(p, rev, False, [n])
    assert p.episode(n).plot.reward == ""


def test_unasked_reward_survives_opening_option():
    from canon.schema import Episode

    p = Project()
    p.meta.title, p.meta.target_episodes = "단편", 6
    pipeline.apply_setup(p, pipeline.suggest_setup(LLM, p))
    p.arc = pipeline.plan_arc(LLM, p).acts
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, 1, 6))
    p.episodes[0] = Episode(plot=p.episode(1).plot.model_copy(update={"reward": "첫 응징"}))
    out = opening.suggest_openings(LLM, p, 1)
    opening.apply_opening(p, 1, out.options[0].plot)
    assert p.episode(1).plot.reward == "첫 응징"


def test_plot_chat_on_webnovel_saves_reward(tmp_path, monkeypatch):
    """웹소설 틀 판으로 받은 플롯 대화 변경안의 사이다가 경고 없이 저장되고 다시 읽힌다."""
    import warnings

    from canon import store

    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _serial()
    p.meta.frame = "webnovel"
    a = _plan_arc(p)
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, a.start_ep, a.end_ep))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        rev = pipeline.revise_plot(LLM, p, f"{a.start_ep}화를 더 짧게", ChatScope(target=f"arc:{a.number}"))
        assert type(rev) is not PlotRevision
        pipeline.apply_revision(p, rev, False, [e.number for e in rev.episodes])
        store.save("pw", p)
        back = store.load("pw")
    assert all(e.plot.reward for e in back.episodes if a.start_ep <= e.plot.number <= a.end_ep)


@needs_node
def test_reward_field_shows_only_when_asked():
    expr = """(() => { const out = {}; for (const [k, meta, form, plot] of data.cases) { S.project = { ...data.p, meta: { ...data.p.meta, ...meta, form } };
        out[k] = rewardOn({ plot }); } return out; })()"""
    plot = {"number": 1, "title": "t"}
    cases = [["drama", {"frame": "drama"}, "serial", plot], ["web", {"frame": "webnovel"}, "serial", plot],
             ["short_web", {"frame": "webnovel"}, "short", plot], ["kept", {"frame": "drama"}, "serial", {**plot, "reward": "첫 응징"}]]
    got = run_js(["app.js", "home.js", "plot.js"], expr, {"cases": cases, "p": Project().model_dump()})
    assert got == {"drama": False, "web": True, "short_web": False, "kept": True}
