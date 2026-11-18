"""보는 눈 기획 블록(docs/trail 일감 8-3) 테스트 (mock LLM): 줄 고르기, 쌍 차례, 예산, 요청에 들어가는 자리. 실행: python -m pytest tests"""
from canon import charviews, context, prompts
from canon.schema import CharView, Project

from .test_serial import _plan_arc, _serial
from .test_storylines import _short

MARK = "[인물이 서로를 보는 눈"


def _v(viewer, target, episode, verdict="평가", surface=""):
    return CharView(viewer=viewer, target=target, episode=episode, verdict=verdict, surface=surface)


def _cast(p: Project, n=3) -> list[str]:
    while len(p.characters) < n:
        p.characters.append(p.characters[0].model_copy(update={"id": f"x{len(p.characters)}", "name": f"엑스{len(p.characters)}", "tier": "minor"}))
    return [c.id for c in p.characters[:n]]


def _all_plan_requests(p, arc):
    return [prompts.serial_plot_prompt(p, arc.start_ep, arc.end_ep), prompts.next_arc_prompt(p, arc.start_ep, 0, "")]


def test_no_views_no_block():
    s = _short(8)
    assert MARK not in prompts.plot_prompt(s, 1, 8) and MARK not in "".join(prompts.plot_chat_parts(s, None))
    from canon.schema import ChatScope
    assert MARK not in "".join(prompts.plot_chat_parts(_serial(40), ChatScope()))
    p = _serial(40)
    arc = _plan_arc(p)
    assert all(MARK not in t for t in _all_plan_requests(p, arc))
    assert charviews.plan_block(p, None) == ""


def test_first_plus_last_three():
    p = _short(8)
    a, b, _ = _cast(p)
    p.views = [_v(a, b, e, f"평가{e}") for e in (1, 3, 5, 7, 9)]
    line = charviews.plan_lines(p, None)[0][0]
    pos = [line.index(f"{e}화 ") for e in (1, 5, 7, 9)]
    assert pos == sorted(pos) and "3화" not in line
    p.views = p.views[:3]
    line = charviews.plan_lines(p, None)[0][0]
    assert line.count("화 '") == 3 and all(f"{e}화" in line for e in (1, 3, 5))


def test_surface_follows_its_verdict():
    p = _short(8)
    a, b, _ = _cast(p)
    p.views = [_v(a, b, 1, "수상함", "대단해요"), _v(a, b, 2, "믿음직")]
    line = charviews.plan_lines(p, None)[0][0]
    assert "1화 '수상함' (겉으로는 '대단해요') / 2화 '믿음직'" in line


def test_pair_order_core_first_then_recent():
    p = _short(8)
    a, b, c = _cast(p)
    for x in p.characters:
        x.tier = "main" if x.id in (a, b) else "minor"
    p.views = [_v(a, c, 9), _v(a, b, 2), _v(b, a, 4)]
    lines, _ = charviews.plan_lines(p, None)
    names = {x.id: x.name for x in p.characters}
    assert [ln.split(":")[0] for ln in lines] == [f"{names[b]} → {names[a]}", f"{names[a]} → {names[b]}", f"{names[a]} → {names[c]}"]


def test_ids_and_deleted_characters_filter_pairs():
    p = _short(8)
    a, b, c = _cast(p)
    p.views = [_v(a, b, 1), _v(a, c, 1), _v("ghost", a, 1), _v(a, "ghost", 1)]
    assert len(charviews.plan_lines(p, None)[0]) == 2
    lines, _ = charviews.plan_lines(p, {a, b})
    assert len(lines) == 1 and "→" in lines[0]


def test_budget_drops_later_pairs(monkeypatch):
    p = _short(8)
    a, b, c = _cast(p)
    p.views = [_v(a, b, 3), _v(b, a, 2), _v(a, c, 1)]
    one = len(charviews.plan_lines(p, None)[0][0]) + 1
    monkeypatch.setitem(context.BUDGET, "plan_views", one + 5)
    lines, cut = charviews.plan_lines(p, None)
    names = {x.id: x.name for x in p.characters}
    assert len(lines) == 1 and cut == [f"{names[b]} → {names[a]}", f"{names[a]} → {names[c]}"]
    assert "(그 밖 2쌍 생략)" in charviews.plan_block(p, None)


def test_serial_placement_and_write_check_exclusion():
    p = _serial(40)
    arc = _plan_arc(p)
    a, b = p.characters[0].id, p.characters[1].id
    p.views = [_v(a, b, 1, "믿음직")]
    for t in _all_plan_requests(p, arc):
        assert MARK in t
    plot = prompts.serial_plot_prompt(p, arc.start_ep, arc.end_ep)
    i = plot.index(MARK)
    assert i < plot.index("[이야기 요소")
    if "[지금 관계 단계" in plot:
        assert plot.index("[지금 관계 단계") < i
    assert plot.index("[관계]") < i
    assert MARK not in prompts.episode_prompt(p, 1)
    assert MARK not in prompts.check_prompt(p, 1)


def test_short_plot_and_chat_have_block():
    p = _short(8)
    a, b, _ = _cast(p)
    p.views = [_v(a, b, 1, "믿음직")]
    for t in (prompts.plot_prompt(p, 1, 8), "".join(prompts.plot_chat_parts(p, None))):
        assert t.index("[관계]") < t.index(MARK) < t.index("[이야기 요소")
    assert MARK not in prompts.state_prompt(p, 2)


def test_serial_plot_chat_has_block():
    from canon.schema import ChatScope
    p = _serial(40)
    a, b, _ = _cast(p)
    p.views = [_v(a, b, 1, "믿음직")]
    t = "".join(prompts.plot_chat_parts(p, ChatScope()))
    assert t.index("[관계]") < t.index(MARK)
