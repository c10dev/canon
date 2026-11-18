"""보는 눈 모으기(docs/trail 일감 8-2) 테스트 (mock LLM): 상태 변경안 요청의 블록과 규칙, 정리, 반영, 되돌리기, hold 안 함, mock. 실행: python -m pytest tests"""
from canon import charviews, context, features, pipeline, prompts
from canon.schema import CharView, Project, StateDelta, ViewChange

from .test_storylines import _short
from .test_timeline import LLM, _play


def _vc(viewer="hero", target="ally", verdict="믿어도 되는 사람", surface=""):
    return ViewChange(viewer=viewer, target=target, verdict=verdict, surface=surface)


def _p() -> Project:
    return _play(_short(8), 1, 1)


def test_state_prompt_has_rule_always_and_block_only_with_views(monkeypatch):
    p = _p()
    s = prompts.state_prompt(p, 2)
    assert "- views 에는" in s and "\n[지금 보는 눈 (" not in s
    p.views = [CharView(viewer="hero", target="ally", episode=1, verdict="수상함"),
               CharView(viewer="hero", target="ally", episode=2, verdict="믿음직", surface="대단해요"),
               CharView(viewer="ally", target="hero", episode=1, verdict="철없음")]
    s = prompts.state_prompt(p, 2)
    assert "\n[지금 보는 눈 (" in s and "'믿음직' (겉으로는 '대단해요')" in s and "수상함" not in s
    assert s.index("서윤 → 도현: 2화") < s.index("도현 → 서윤: 1화")  # 최근 화가 먼저
    monkeypatch.setitem(context.BUDGET, "plan_views", 40)
    assert "(그 밖 1줄 생략)" in prompts.state_prompt(p, 2)


def test_clean_delta():
    p = _p()
    p.views = [CharView(viewer="hero", target="ally", episode=1, verdict="수상함")]
    new = p.characters[0].model_copy(update={"id": "newbie", "name": "새사람"})
    d = StateDelta(episode=2, summary="", new_characters=[new], views=[
        _vc("ghost", "ally"), _vc("hero", "hero"), _vc(verdict="  "),
        _vc(verdict=" 수상함 "),  # 최근 평가와 같다
        _vc("ally", "hero", "첫째"), _vc("ally", "hero", " 둘째 ", " 겉 "),  # 같은 방향은 뒤의 것만
        _vc("hero", "newbie", "새 인물도 받는다"),
    ])
    assert charviews.clean_delta(p, d) == []
    assert [(x.viewer, x.target, x.verdict, x.surface) for x in d.views] == [("ally", "hero", "둘째", "겉"), ("hero", "newbie", "새 인물도 받는다", "")]
    d = StateDelta(episode=2, summary="")
    d.views = [_vc("hero", "ally", "1"), _vc("ally", "hero", "2")]
    p.characters.append(p.characters[0].model_copy(update={"id": "c3", "name": "셋"}))
    p.characters.append(p.characters[0].model_copy(update={"id": "c4", "name": "넷"}))
    d.views += [_vc("c3", "hero", "3"), _vc("c4", "hero", "4"), _vc("c4", "ally", "5")]
    charviews.clean_delta(p, d)
    assert [x.verdict for x in d.views] == ["1", "2", "3", "4"]


def test_apply_delta_adds_and_skips_same():
    p = _p()
    p.views = [CharView(viewer="hero", target="ally", episode=1, verdict="수상함")]
    d = StateDelta(episode=2, summary="", views=[_vc(verdict="수상함"), _vc("ally", "hero", "철없음", "대단해요"), _vc("ghost", "hero")])
    charviews.apply_delta(p, d)
    assert [(v.viewer, v.episode, v.verdict, v.surface) for v in p.views] == [("hero", 1, "수상함", ""), ("ally", 2, "철없음", "대단해요")]


def test_pipeline_apply_and_revert():
    p = _p()
    d = StateDelta(episode=2, summary="", views=[_vc()])
    pipeline.apply_delta(p, d)
    assert [(v.episode, v.verdict) for v in p.views] == [(2, "믿어도 되는 사람")]
    pipeline.revert(p, 1)
    assert p.views == []


def test_hold_keeps_views():
    p = _p()
    d = StateDelta(episode=2, summary="", views=[_vc()])
    features.hold(p, d)
    assert len(d.views) == 1


def test_mock_state_has_one_view_on_episode_two():
    p = _p()
    p.episode(2).text, p.episode(2).status = "서윤은 도현을 보았다.", "written"
    d = pipeline.extract_state(LLM, p, 2)
    assert [(v.viewer, v.target, v.verdict) for v in d.views] == [("hero", "ally", "믿어도 되는 사람")]
    assert pipeline.extract_state(LLM, p, 1).views == []
