"""확정 사실이 들어온 화 (context.facts_learned): 반영 기록으로 셈, 장편 사실 줄 앞 '(n화)', 상태 변경안이 따라 적은 표시 떼기,
검수 · 인과율 요청에는 붙이지 않음, 작품 홈의 'n화' 링크. 실행: python -m pytest tests"""
from canon import context, pipeline, prompts
from canon.schema import StateDelta

from .jsvm import needs_node, run_js
from .test_char_context import _long
from .test_storylines import _short
from .test_timeline import _play


def _serial_with_fact():
    p = _long()
    n = max(e.plot.number for e in p.episodes if e.status == "finalized")
    rec = next(h for h in reversed(p.history) if h.episode == n)
    rec.new_facts.append("등대 계단은 백십 칸이다")
    p.facts += ["등대 계단은 백십 칸이다", "작가가 직접 적은 사실이다"]
    return p, n


def test_facts_learned_from_history():
    p = _play(_short(8), 1, 2)
    p.history[0].new_facts.append("가")
    p.history[1].new_facts.append("가")  # 먼저 들어온 화
    p.history[1].new_facts.append("나")
    eps = context.facts_learned(p)
    assert eps["가"] == 1 and eps["나"] == 2 and "없는 사실" not in eps


def test_serial_prompts_tag_facts_but_check_does_not():
    p, n = _serial_with_fact()
    write = prompts.episode_prompt(p, n + 1)
    assert f"- ({n}화) 등대 계단은 백십 칸이다" in write and "- 작가가 직접 적은 사실이다" in write  # 기록에 없으면 붙이지 않는다
    assert f"- ({n}화) 등대 계단은 백십 칸이다" in prompts.state_prompt(p, n)
    check = prompts.check_prompt(p, n)
    assert "- 등대 계단은 백십 칸이다" in check and f"({n}화) 등대 계단" not in check


def test_short_prompts_do_not_tag():
    p = _play(_short(8), 1, 2)
    p.history[0].new_facts.append("등대 계단은 백십 칸이다")
    p.facts.append("등대 계단은 백십 칸이다")
    assert "- 등대 계단은 백십 칸이다" in prompts.episode_prompt(p, 3) and "(1화) 등대" not in prompts.episode_prompt(p, 3)


def test_clean_strips_tags_from_new_facts():
    p = _play(_short(8), 1, 2)
    d = StateDelta(episode=2, summary="", new_facts=["(12화) 등대 계단은 백십 칸이다", " (3화)  ", "(요약) 그대로 둔다"])
    pipeline.clean_delta(p, d)
    assert d.new_facts == ["등대 계단은 백십 칸이다", "(요약) 그대로 둔다"]


def test_impact_facts_untagged():
    from canon.schema import StoryElement
    p, n = _serial_with_fact()
    out = prompts.impact_prompt(p, StoryElement(id="e1", kind="장소", name="등대", description="바닷가 등대"), set())
    assert "- 등대 계단은 백십 칸이다" in out and f"({n}화) 등대 계단" not in out  # 인과율 rep.new_facts 는 CLEAN 을 거치지 않는다


@needs_node
def test_home_links_fact_episode():
    p = {"history": [{"episode": 3, "new_facts": ["가", "constructor"]}, {"episode": 1, "new_facts": ["가"]}]}
    assert run_js(["app.js", "home.js"], "factsLearned(data)", p) == {"가": 1, "constructor": 3}
