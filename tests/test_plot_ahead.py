"""화별 플롯 초안이 범위 안 · 바로 뒤의 이미 정해진 화를 보는지 (mock LLM). 실행: python -m pytest tests"""
from canon import context, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Project
from tests.test_serial import _plan_arc, _serial

L = MockLLM()
HEAD = "[이미 정해진 화"


def _mark(p: Project, numbers, status="confirmed"):
    for n in numbers:
        e = p.episode(n)
        e.status = status
        e.plot.summary = f"정해진화표지{n}끝"


def _short() -> Project:
    p = Project()
    p.meta.title, p.meta.target_episodes = "단편", 10
    pipeline.apply_setup(p, pipeline.suggest_setup(L, p))
    p.arc = pipeline.plan_arc(L, p).acts
    pipeline.apply_plots(p, pipeline.draft_plots(L, p, 1, 10))
    return p


def test_short_sees_fixed_inside_and_after():
    p = _short()
    _mark(p, [5, 7, 8, 9, 10])
    p.episode(9).status = "written"
    text = prompts.plot_prompt(p, 3, 6)
    block = text[text.index(HEAD):text.index("요구사항:")]
    for n in (5, 7, 8, 9):
        assert f"정해진화표지{n}끝" in block
    assert "정해진화표지10끝" not in text  # 범위 뒤 세 화까지만
    rules = text[text.index("요구사항:"):]
    assert "5화는 이미 정해진 화라 고쳐 쓰지 않습니다" in rules
    assert "6화 뒤의 정해진 화는 episodes 에 넣지 않습니다" in rules


def test_short_without_fixed_has_no_block():
    p = _short()
    assert HEAD not in prompts.plot_prompt(p, 3, 6)


def test_draft_keeps_fixed_and_drafts_around_it():
    p = _short()
    _mark(p, [5])
    before = p.episode(5).plot.model_copy()
    pipeline.apply_plots(p, pipeline.draft_plots(L, p, 3, 6))
    assert p.episode(5).plot == before


def test_one_episode_draft_is_unchanged():
    """한 화 초안은 바로 뒤 화를 따로 넣으므로 이 블록을 붙이지 않는다."""
    p = _short()
    _mark(p, [5, 6])
    assert HEAD not in prompts.episode_plot_prompt(p, 4)
    assert HEAD not in prompts.episode_plot_prompt(p, 4, fit_next=False)


def test_serial_sees_fixed_inside_and_after():
    p = _serial()
    a, b = _plan_arc(p), _plan_arc(p)
    assert b.end_ep - b.start_ep >= 3
    for n in range(a.start_ep, a.end_ep + 1):
        p.episode(n).status = "draft"
    mid = a.start_ep + 2
    _mark(p, [mid, *range(b.start_ep, b.end_ep + 1)])
    text = prompts.plot_prompt(p, a.start_ep, a.end_ep)
    block = text[text.index(HEAD):text.index("요구사항:")]
    for n in (mid, b.start_ep, b.start_ep + 1, b.start_ep + 2):
        assert f"정해진화표지{n}끝" in block
    assert f"정해진화표지{b.start_ep + 3}끝" not in text
    assert "길어서 뺐습니다" not in block
    assert f"{mid}화는 이미 정해진 화라 고쳐 쓰지 않습니다" in text


def test_serial_budget_drops_far_ones_and_says_how_many(monkeypatch):
    p = _serial()
    a, b = _plan_arc(p), _plan_arc(p)
    for n in range(a.start_ep, a.end_ep + 1):
        p.episode(n).status = "draft"
    _mark(p, [a.start_ep + 2, *range(b.start_ep, b.end_ep + 1)])
    two = sum(len(prompts.dump(p.episode(n).plot)) for n in (a.start_ep + 2, b.start_ep))
    monkeypatch.setitem(context.BUDGET, "plan_fixed", two)
    text = prompts.plot_prompt(p, a.start_ep, a.end_ep)
    block = text[text.index(HEAD):text.index("요구사항:")]
    assert "그 밖에 2개는 길어서 뺐습니다" in block
    # 초안 화(마지막 a.end_ep)에 가까운 바로 뒤 화와, 범위 안 정해진 화가 남는다
    assert f"정해진화표지{b.start_ep}끝" in block
    assert f"정해진화표지{a.start_ep + 2}끝" in block
    assert f"정해진화표지{b.start_ep + 2}끝" not in block
