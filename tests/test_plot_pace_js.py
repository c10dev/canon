"""플롯 화면의 관계 속도 경고(static/plot.js pacePlot)가 pace.plot_warnings 와 같은지 node 로 맞춰 본다. node 가 있을 때만 돈다."""
from canon import pace

from .jsvm import dump, needs_node, run_js
from .test_pace import _name, _plot, _set
from .test_storylines import _short
from .test_timeline import _play

FILES = ["app.js", "home.js", "plot.js"]


def same(p, ns):
    want = {str(n): pace.plot_warnings(p, n) for n in ns}
    got = run_js(FILES, "Object.fromEntries(data.ns.map((n) => [String(n), pacePlot(data.p, n)]))", {"p": dump(p), "ns": ns})
    assert got == want
    return want


@needs_node
def test_plot_pace_matches_python():
    p = _play(_short(8), 1, 1)
    _set(p, "적대", -0.6)
    hero, ally = _name(p, "hero"), _name(p, "ally")
    _plot(p, 2, f"{hero}와 {ally}는 서로를 용서하고 친구가 된다.")
    _plot(p, 3, f"{hero}와 {ally}가 화해한다. {hero}는 {ally}에게 등을 돌린다.")
    _plot(p, 4, f"{hero}는 {ally}와 결별하고 원수가 된다.")
    got = same(p, [2, 3, 4])
    assert got["2"] and not got["4"]
    p.state_of("hero").emotional_state = f"겉: {ally}에게 웃음 / 속: {ally}를 경계"
    assert same(p, [2])["2"] == []
    p.characters[0].name = "야마이 렌"  # 띄어 쓴 이름
    same(p, [2, 3])


@needs_node
def test_plot_todos_show_pace():
    p = _play(_short(8), 1, 1)
    _set(p, "적대", -0.6)
    _plot(p, 2, f"{_name(p, 'hero')}와 {_name(p, 'ally')}는 친구가 된다.")
    todos = run_js(FILES, "plotTodos(data.p, 1, 8)", {"p": dump(p)})
    assert any(t["kind"] == "pace" and t["n"] == 2 for t in todos)
