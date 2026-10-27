"""화 끼워 넣기 화면(static/insert.js)의 lastFixed 가 renumber.last_fixed 와 같은 화를 고르는지. node 가 있을 때만 돈다."""
from canon import renumber
from canon.schema import Project, Snapshot, StateDelta, StoryEvent, TextVersion

from .jsvm import dump, episode, needs_node, run_js


def _cases() -> list[Project]:
    out = [Project()]
    p = Project(episodes=[episode(n) for n in range(1, 6)])
    out.append(p.model_copy(deep=True))  # 플롯만 있음
    p.episodes[1].text = "본문"
    out.append(p.model_copy(deep=True))  # 본문만 (상태는 draft)
    p.episodes[2].status = "written"
    p.episodes[3].status = "confirmed"  # 확정은 옮길 수 있다
    out.append(p.model_copy(deep=True))
    p.episodes[3].candidate = TextVersion(id="v1", text="새 판")
    out.append(p.model_copy(deep=True))
    p.episodes[4].status = "finalized"
    out.append(p.model_copy(deep=True))
    q = Project(episodes=[episode(n) for n in range(1, 4)])
    q.history = [StateDelta(episode=6, summary="")]
    out.append(q.model_copy(deep=True))  # 플롯보다 뒤 화의 기록
    q.history, q.snapshots = [], [Snapshot(episode=0), Snapshot(episode=2)]
    out.append(q.model_copy(deep=True))
    q.snapshots, q.events = [], [StoryEvent(episode=7, actor="a", target="b", kind="도움")]
    out.append(q)
    return out


@needs_node
def test_last_fixed_matches_server():
    cases = _cases()
    got = run_js(["app.js", "insert.js"], "data.map((p) => { S.project = p; return lastFixed(); })", [dump(p) for p in cases])
    assert got == [renumber.last_fixed(p) for p in cases]
    assert len(set(got)) > 3  # 여러 갈래를 실제로 지난다
