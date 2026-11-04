"""저장 전 백업(project.prev.json · backups/), 화면 저장 기록 읽기, 세 자리 본문 파일 이름, 사용량 기록 이어 읽기."""
import json
import os

import pytest

from canon import store, usage
from canon.schema import Episode, EpisodePlot, Meta, Project


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    return tmp_path


def _ep(n: int) -> Episode:
    return Episode(plot=EpisodePlot(number=n, act="기", title=f"{n}화", summary="", events=[], characters=[], emotional_shift="",
                                    ending_hook=""), text=f"{n}화 본문")


def _proj(n_eps: int = 0) -> Project:
    p = Project(meta=Meta(title="백업", target_episodes=max(n_eps, 10)))
    for n in range(1, n_eps + 1):
        p.episodes.append(_ep(n))
    return p


def test_mark_fields_are_last():
    assert list(Project.model_fields)[-2:] == ["edit_rev", "saved_by"]


def test_prev_and_hourly_backup_keep_old_content(home):
    p = _proj()
    store.save("b", p)
    p.meta.logline = "둘째"
    store.save("b", p)
    p.meta.logline = "셋째"
    store.save("b", p)
    prev = json.loads((home / "b" / "project.prev.json").read_text(encoding="utf-8"))
    assert prev["meta"]["logline"] == "둘째"
    got = store.backups("b")
    assert len(got) == 1  # 같은 시간에는 첫 저장 직전 판 하나
    assert json.loads(got[0].read_text(encoding="utf-8"))["meta"]["logline"] == ""
    assert os.stat(home / "b" / "project.json").st_ino != os.stat(home / "b" / "project.prev.json").st_ino


def test_backup_keeps_only_recent(home, monkeypatch):
    monkeypatch.setattr(store, "BACKUP_KEEP", 2)
    p = _proj()
    store.save("b", p)
    bdir = home / "b" / "backups"
    bdir.mkdir()
    for h in ("20200101-01", "20200101-02", "20200101-03"):
        (bdir / f"project.{h}.json").write_text("{}")
    store.save("b", p)
    assert [f.name for f in store.backups("b")][-1].startswith("project.2")
    assert len(store.backups("b")) == 2


def test_saved_mark_falls_back_to_whole_file(home, tmp_path):
    f = tmp_path / "old.json"
    f.write_text(json.dumps({"saved_by": "tab-1", "edit_rev": 7, "meta": {}, "pad": "x" * 9000}), encoding="utf-8")
    assert store._saved_mark(f) == (7, "tab-1")


def test_three_digit_episode_files_replace_two_digit(home):
    p = _proj(3)
    store.save("e", p)
    d = home / "e" / "episodes"
    assert sorted(f.name for f in d.glob("*.md")) == ["01.md", "02.md", "03.md"]
    (d / "note.md").write_text("작가 메모")
    for n in range(4, 101):
        p.episodes.append(_ep(n))
    store.save("e", p)
    names = sorted(f.name for f in d.glob("*.md"))
    assert names[0] == "001.md" and names[-2] == "100.md" and "01.md" not in names and "note.md" in names
    assert len(names) == 101


def test_usage_read_picks_up_appended_lines(tmp_path):
    f = tmp_path / "u.jsonl"
    f.write_text(json.dumps({"n": 1}) + "\n" + '{"n": 2', encoding="utf-8")  # 둘째 줄은 쓰는 중
    assert usage.read(f) == [{"n": 1}]
    with f.open("a", encoding="utf-8") as fh:
        fh.write("}\n" + json.dumps({"n": 3}) + "\n")
    assert usage.read(f) == [{"n": 1}, {"n": 2}, {"n": 3}]
    f.write_text(json.dumps({"n": 9}) + "\n", encoding="utf-8")  # 새 파일로 바뀜
    assert usage.read(f) == [{"n": 9}]



def test_snapshots_live_in_their_own_files(home):
    from canon.schema import Snapshot
    p = _proj()
    p.snapshots = [Snapshot(episode=0, facts=["처음"]), Snapshot(episode=1, facts=["하나"])]
    store.save("s", p)
    raw = (home / "s" / "project.json").read_text(encoding="utf-8")
    assert raw.startswith('{"snapshot_files":[') and '"facts":["처음"]' not in raw
    files = sorted(f.name for f in (home / "s" / "snapshots").glob("*.json"))
    assert len(files) == 2
    store._views.clear()
    assert [s.facts for s in store.load("s").snapshots] == [["처음"], ["하나"]]
    mtimes = {f.name: f.stat().st_mtime_ns for f in (home / "s" / "snapshots").glob("*.json")}
    p.snapshots[1] = Snapshot(episode=1, facts=["바뀜"])
    store.save("s", p)
    store.save("s", p)
    now = {f.name: f.stat().st_mtime_ns for f in (home / "s" / "snapshots").glob("*.json")}
    zero = next(k for k in mtimes if k.startswith("0-"))
    assert now[zero] == mtimes[zero]  # 바뀌지 않은 스냅샷은 다시 쓰지 않는다
    # 옛 1화 파일은 직전 판(prev)이나 백업이 적고 있으면 남고, 아무도 적지 않으면 지운다
    store._views.clear()
    assert [s.facts for s in store.load("s").snapshots] == [["처음"], ["바뀜"]]
    assert all(f in now for f in store._snap_refs(home / "s" / "project.prev.json"))


def test_old_inline_snapshots_still_load(home):
    from canon.schema import Snapshot
    p = _proj()
    p.snapshots = [Snapshot(episode=0, facts=["옛"])]
    (home / "o").mkdir()
    (home / "o" / "project.json").write_text(p.model_dump_json(), encoding="utf-8")
    assert store.load("o").snapshots[0].facts == ["옛"]
    store.save("o", store.load("o"))
    store._views.clear()
    assert store.load("o").snapshots[0].facts == ["옛"]
    assert (home / "o" / "project.json").read_text(encoding="utf-8").startswith('{"snapshot_files":')


def test_snapshot_changed_in_place_is_written(home):
    from canon.schema import Snapshot
    p = _proj()
    p.snapshots = [Snapshot(episode=0, facts=["처음"])]
    store.save("m", p)
    p.snapshots[0].facts.append("더함")  # 저장한 객체를 그 자리에서 고친다
    store.save("m", p)
    store._views.clear()
    assert store.load("m").snapshots[0].facts == ["처음", "더함"]
