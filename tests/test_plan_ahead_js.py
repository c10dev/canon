"""다음 아크 기획 앞 경고(static/plot.js planAhead)가 pipeline.plan_ahead 와 같은지 node 로 맞춰 본다. node 가 있을 때만 돈다."""
from canon import pipeline
from canon.schema import Project

from .jsvm import dump, needs_node, run_js
from .test_serial import _finish, _plan_arc, _serial

FILES = ["app.js", "home.js", "plot.js"]


def same(p: Project):
    want = pipeline.plan_ahead(p)
    got = run_js(FILES, "planAhead(data.p)", {"p": dump(p)})
    assert got == want
    return want


@needs_node
def test_plan_ahead_matches_python():
    p = _serial()
    assert same(p)["notes"] == []
    a1 = _plan_arc(p)
    same(p)
    _finish(p, a1)
    _plan_arc(p)
    a3 = _plan_arc(p)
    got = same(p)  # 요약 없는 아크 1, 본문 없는 아크 2개
    assert got["recaps"] == [["arc", 1]] and got["unwritten_arcs"] == 2 and len(got["notes"]) == 2
    p.episode(a3.start_ep).text = "조금 씀"
    pipeline.apply_recap(p, "arc", 1, "요약")
    assert same(p)["notes"] == []


@needs_node
def test_plan_ahead_matches_python_for_short_work():
    same(Project())
