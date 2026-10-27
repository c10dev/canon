"""장편 스냅샷 모두 남기기 (Settings.keep_snapshots) 테스트: 기본은 지금처럼 0화 · 아크 끝 · 최근 20화만 남기고,
켜면 화별 스냅샷을 지우지 않는지. 반영 경로, 웹 설정, 명령줄 snapshots 도 본다.

    python -m pytest tests/test_keep_snapshots.py
"""
import contextlib
import io
import os
import tempfile

os.environ.setdefault("CANON_LLM", "mock")
os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())

from canon import pipeline, store  # noqa: E402
from canon.cli import _ep_runs, main  # noqa: E402
from canon.mock import MockLLM  # noqa: E402
from canon.schema import Project, Snapshot, StoryArc  # noqa: E402

LLM = MockLLM()


def _serial_with_snapshots(last: int) -> Project:
    p = Project()
    p.meta.form = "serial"
    p.story_arcs = [StoryArc(number=1, title="첫 아크", start_ep=1, end_ep=10, goal="g")]
    p.snapshots = [Snapshot(episode=n) for n in range(last + 1)]
    return p


def test_default_is_off_and_old_files_read():
    assert Project().settings.keep_snapshots is False
    assert Project.model_validate({"settings": {"show_numbers": True}}).settings.keep_snapshots is False  # 예전 project.json


def test_prune_keeps_start_arc_end_and_recent_by_default():
    p = _serial_with_snapshots(40)
    pipeline.prune_snapshots(p)
    kept = sorted(s.episode for s in p.snapshots)
    assert kept == [0, 10] + list(range(41 - pipeline.SNAPSHOT_KEEP, 41))


def test_prune_keeps_everything_when_on():
    p = _serial_with_snapshots(40)
    p.settings.keep_snapshots = True
    pipeline.prune_snapshots(p)
    assert sorted(s.episode for s in p.snapshots) == list(range(41))


def _serial_project() -> Project:
    p = Project()
    p.meta.title, p.meta.form, p.meta.target_episodes = "탑", "serial", 300
    pipeline.apply_setup(p, pipeline.suggest_setup(LLM, p))
    pipeline.apply_series(p, pipeline.plan_series(LLM, p))
    return p


def _finish_arcs(p: Project, until: int) -> None:
    """아크를 짜고 화를 반영하기를 until 화를 넘을 때까지 되풀이한다."""
    while not any(e.status == "finalized" and e.plot.number >= until for e in p.episodes):
        a = pipeline.apply_arc(p, pipeline.plan_next_arc(LLM, p, 0))
        pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, a.start_ep, a.end_ep))
        for n in range(a.start_ep, a.end_ep + 1):
            e = p.episode(n)
            e.status, e.text = "written", "본문"
            pipeline.apply_delta(p, pipeline.extract_state(LLM, p, n))


def test_apply_delta_keeps_every_snapshot_when_on():
    off, on = _serial_project(), _serial_project()
    on.settings.keep_snapshots = True
    _finish_arcs(off, 30)
    _finish_arcs(on, 30)
    done = sorted(e.plot.number for e in on.episodes if e.status == "finalized")
    assert sorted(s.episode for s in on.snapshots) == [0] + done  # 반영한 화마다 하나씩, 지우지 않음
    assert len(off.snapshots) <= 1 + len(off.story_arcs) + pipeline.SNAPSHOT_KEEP < len(on.snapshots)
    # 켜 두면 아무 화로나 되돌릴 수 있다
    pipeline.revert(on, 5)
    assert max(e.plot.number for e in on.episodes if e.status == "finalized") == 5


def test_turning_off_prunes_at_next_apply():
    p = _serial_project()
    p.settings.keep_snapshots = True
    _finish_arcs(p, 30)
    p.settings.keep_snapshots = False
    a = pipeline.apply_arc(p, pipeline.plan_next_arc(LLM, p, 0))
    pipeline.apply_plots(p, pipeline.draft_plots(LLM, p, a.start_ep, a.end_ep))
    e = p.episode(a.start_ep)
    e.status, e.text = "written", "본문"
    pipeline.apply_delta(p, pipeline.extract_state(LLM, p, a.start_ep))
    assert len(p.snapshots) <= 1 + len(p.story_arcs) + pipeline.SNAPSHOT_KEEP


def test_ep_runs():
    assert _ep_runs([0, 20, 40, 60, 62, 63, 64, 81]) == "0, 20, 40, 60, 62~64, 81화"
    assert _ep_runs([]) == "없음"


def test_web_and_cli_toggle(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from canon import web

    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
    c = TestClient(web.app)
    r = c.put("/api/projects/demo/keep-snapshots", json={"on": True})
    assert r.status_code == 200 and r.json()["settings"]["keep_snapshots"] is True
    assert store.load("demo").settings.keep_snapshots is True

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["snapshots", "demo", "--no-keep"])
    assert store.load("demo").settings.keep_snapshots is False
    assert "스냅샷" in out.getvalue() and "단편은 스냅샷을 지우지 않아요" in out.getvalue()
    p = store.load("demo")
    p.meta.form = "serial"
    store.save("demo", p)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["snapshots", "demo"])
    assert f"최근 {pipeline.SNAPSHOT_KEEP}화만 남겨요" in out.getvalue()
    assert store.load("demo").settings.keep_snapshots is False  # 보기만 하면 바꾸지 않는다
