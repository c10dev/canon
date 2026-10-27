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
