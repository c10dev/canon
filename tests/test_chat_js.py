"""플롯 대화(static/chat.js)가 고르는 아크가 pipeline.chat_target · focus_arc 와 같은지:
아크를 고르지 않았을 때 비교 기준 아크(revBase), 'arc:N' 대상의 아크(plotTargetArc). node 가 있을 때만 돈다."""
import pytest

from canon import pipeline
from canon.schema import Project, StoryArc

from .jsvm import dump, episode, needs_node, run_js


def _arc(n: int, start: int, end: int) -> StoryArc:
    return StoryArc(number=n, title=f"아크{n}", start_ep=start, end_ep=end, goal="")


def _projects() -> list[Project]:
    out = [Project()]  # 단편
    p = Project(episodes=[episode(n) for n in range(1, 13)], story_arcs=[_arc(2, 5, 8), _arc(1, 1, 4), _arc(3, 9, 12)])
    p.meta.form, p.meta.target_episodes = "serial", 30
    out.append(p.model_copy(deep=True))  # 아무것도 안 씀 → 첫 아크
    for n in range(1, 5):
        p.episodes[n - 1].status = "finalized"
    out.append(p.model_copy(deep=True))  # 아크 1 끝 → 아크 2
    p.episodes[4].status, p.episodes[5].status = "written", "confirmed"
    out.append(p.model_copy(deep=True))  # 확정은 아직 고칠 수 있다
    for e in p.episodes:
        e.status = "written"
    out.append(p.model_copy(deep=True))  # 모두 씀 → 마지막 아크
    p.episodes = p.episodes[:6]
    out.append(p.model_copy(deep=True))  # 플롯이 없는 화는 고칠 수 있는 화
    p.story_arcs = []
    out.append(p)  # 아크 없음
    return out


def _server(p: Project, target: str):
    try:
        name, a = pipeline.chat_target(p, target)
    except ValueError:
        return None
    return a.number if a else name or None


@needs_node
def test_focus_and_target_arc_match_server():
    ps = _projects()
    expr = """data.map((p) => { S.project = p; const b = revBase({ target: '' });
      return [b.arc ? b.arc.number : null, [1, 2, 3, 4].map((n) => (plotTargetArc('arc:' + n) || {}).number || null)]; })"""
    got = run_js(["app.js", "chat.js"], expr, [dump(p) for p in ps])
    for p, (focus, picked) in zip(ps, got):
        a = pipeline.focus_arc(p) if p.serial else None
        assert focus == (a.number if a else None)
        if p.serial:
            assert picked == [_server(p, f"arc:{n}") for n in [1, 2, 3, 4]]
            assert (focus or "next") == _server(p, "")
    assert [f for f, _ in got] == [None, 1, 2, 2, 3, 2, None]


@needs_node
@pytest.mark.xfail(strict=True, reason="어긋남: chat_target 은 대상 글의 앞뒤 빈칸 · '+3' · 전각 숫자도 아크 번호로 읽고 plotTargetArc 는 읽지 않는다 "
                   "(화면이 만드는 'arc:N' 에는 나오지 않는다)")
def test_target_parsing_edge_matches_server():
    p = _projects()[1]
    targets = [" arc:2 ", "arc:+2", "arc:２", "arc: 2"]
    got = run_js(["app.js", "chat.js"], "S.project = data.p; data.t.map((t) => (plotTargetArc(t) || {}).number || null)",
                 {"p": dump(p), "t": targets})
    assert got == [_server(p, t) for t in targets]
