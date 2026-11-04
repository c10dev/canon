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
