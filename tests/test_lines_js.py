"""이야기 줄기 화면(static/lines.js)의 lineEpisodes · lineSpan · tagEp 가 storylines.episodes_of · span · tag 와 같은지.
node 가 있을 때만 돈다."""
import pytest

from canon import storylines
from canon.schema import Project, Storyline

from .jsvm import dump, episode, needs_node, run_js


def _project() -> Project:
    eps = [episode(n) for n in range(1, 9)]
    eps[1].plot.storyline = "sl-a"
    eps[2].plot.storyline, eps[2].plot.threads = "sl-a", ["sl-b"]
    eps[4].plot.threads = ["sl-b", "sl-a"]
    eps[6].plot.storyline = "sl-c"
    eps.reverse()  # 화 순서가 섞여 있어도 화 번호 순으로 센다
    lines = [Storyline(id="sl-a"), Storyline(id="sl-b", branch_ep=1, join_ep=7), Storyline(id="sl-c", branch_ep=5),
             Storyline(id="sl-d"), Storyline(id="sl-e", branch_ep=2, join_ep=4)]
    return Project(episodes=eps, storylines=lines)


@needs_node
def test_line_span_and_episodes_match_server():
    p = _project()
    got = run_js(["app.js", "lines.js"], "S.project = data; P().storylines.map((s) => [lineEpisodes(s.id).map((x) => [x.n, x.role]), lineSpan(s)])", dump(p))
    for s, (eps, span) in zip(p.storylines, got):
        assert [tuple(x) for x in eps] == storylines.episodes_of(p, s.id), s.id
        assert tuple(span) == storylines.span(p, s), s.id


@needs_node
def test_tag_matches_server():
    steps = [(4, "sl-a", "main"), (4, "sl-b", "thread"), (4, "sl-a", "thread"), (3, "sl-b", "main"), (5, "sl-a", "thread"),
             (5, "", "main"), (6, "sl-c", "thread"), (6, "sl-c", "thread"), (6, "sl-c", "main")]
    expr = "S.project = data.project; data.steps.forEach(([n, id, role]) => tagEp(n, id, role)); P().episodes.map((e) => [e.plot.number, e.plot.storyline, e.plot.threads])"
    p = _project()
    got = run_js(["app.js", "lines.js"], expr, {"project": dump(p), "steps": steps})
    for n, sid, role in steps:
        storylines.tag(p, n, sid, role)
    assert got == [[e.plot.number, e.plot.storyline, e.plot.threads] for e in p.episodes]


@needs_node
@pytest.mark.xfail(strict=True, reason="어긋남: 붙은 화 없이 갈라지는 화만 있으면 lineSpan 은 끝을 -Infinity 로, "
                   "합류 화만 있으면 [0, 0] 으로 낸다. storylines.span 은 (갈라짐, 0) · (0, 합류)")
def test_line_span_without_episodes_matches_server():
    p = Project(storylines=[Storyline(id="sl-x", branch_ep=3), Storyline(id="sl-y", join_ep=6)])
    got = run_js(["app.js", "lines.js"], "S.project = data; P().storylines.map((s) => String(lineSpan(s)))", dump(p))
    assert got == [",".join(map(str, storylines.span(p, s))) for s in p.storylines]


@needs_node
def test_line_order_and_todo():
    """노선도 줄 차례(lineOrder): 범위 시작 차례, 범위가 없으면 뒤, 갈라짐 · 합류가 없는 외전은 본편 밖.
    손볼 것(lineTodo): 갈라짐이 합류보다 뒤 · 총 화수보다 뒤 · 범위 밖에 붙은 화 · 합류 화 없이 열림(외전은 빼고)."""
    eps = [episode(n) for n in range(1, 13)]
    eps[6].plot.storyline = "late"                    # 7화
    eps[1].plot.threads = ["early"]                   # 2화 장면
    eps[9].plot.threads = ["early"]                   # 10화: 합류(8화) 뒤
    eps[3].plot.threads = ["side"]                    # 4화: 외전 장면
    lines = [Storyline(id="late", kind="인물 이야기", branch_ep=6),            # 열림
             Storyline(id="early", branch_ep=3, join_ep=8),                   # 2화는 갈라짐 앞, 10화는 합류 뒤
             Storyline(id="side", kind="외전"),                               # 본편 밖
             Storyline(id="none"),                                            # 범위 없음 → 뒤
             Storyline(id="bad", branch_ep=9, join_ep=5),                     # 갈라짐이 합류보다 뒤
             Storyline(id="far", kind="외전", branch_ep=11, join_ep=40)]      # 외전이지만 갈라짐이 있어 안쪽, 총 화수 뒤
    p = Project(episodes=eps, storylines=lines)
    p.meta.target_episodes = 12
    out = run_js(["app.js", "lines.js"], "S.project = data; ({ order: lineOrder(P()), todo: lineTodo(P()).map((t) => [t.id, t.kind, t.text]) })", dump(p))
    assert out["order"] == {"inside": ["early", "late", "bad", "far", "none"], "outside": ["side"]}
    assert out["todo"] == [
        ["late", "open", "6화에 갈라졌는데 합류하는 화가 없어요. 끝까지 열어 둘 줄기면 그대로 둬도 돼요."],
        ["early", "outside", "합류하는 화(8화) 뒤에 붙은 화가 있어요: 2, 10화"],
        ["bad", "order", "갈라지는 화(9화)가 합류하는 화(5화)보다 뒤예요."],
        ["far", "late", "합류하는 화가 총 화수(12화)보다 뒤예요."],
    ]
