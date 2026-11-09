"""저장 전 백업(project.prev.json · backups/), 화면 저장 기록 읽기, 세 자리 본문 파일 이름, 사용량 기록 이어 읽기."""
import json
import os
import shutil

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
    monkeypatch.setattr(store, "BACKUP_HOURS", 2)
    p = _proj()
    store.save("b", p)
    bdir = home / "b" / "backups"
    bdir.mkdir()
    for h in ("20200101-01", "20200101-02", "20200101-03"):
        (bdir / f"project.{h}.json").write_text("{}")
    (bdir / "before-restore.20200101-010101.json").write_text("{}")  # 시간별이 아닌 파일은 보관 규칙 밖이다
    store.save("b", p)
    assert [f.name for f in store.backups("b")][-1].startswith("project.2")
    assert len(store.backups("b")) == 2  # 2020년은 14일보다 오래돼 최근 2개만 남는다
    assert (bdir / "before-restore.20200101-010101.json").exists()


def test_backup_prune_keeps_hours_then_one_per_day():
    from datetime import datetime, timedelta
    now = datetime(2026, 11, 5, 12)
    names = [f"project.{now - timedelta(hours=h):%Y%m%d-%H}.json" for h in range(0, 24 * 20, 3)]
    gone = set(store.backup_prune(names, now))
    kept = sorted(set(names) - gone)
    hourly = sorted(names)[-store.BACKUP_HOURS:]
    assert set(hourly) <= set(kept)  # 최근 24개는 모두
    older = [n for n in kept if n not in hourly]
    days = [n[8:16] for n in older]
    assert len(days) == len(set(days))  # 그 전은 하루에 하나
    assert all(n == max(x for x in names if x[8:16] == n[8:16] and x not in hourly) for n in older)  # 그날 마지막 것
    assert min(days) == f"{now - timedelta(days=store.BACKUP_DAYS - 1):%Y%m%d}"  # 14일 안만
    assert store.backup_prune(["project.prev.json", "before-restore.20200101-010101.json"], now) == []


def _with_snaps(home, name):
    from canon.schema import Snapshot
    p = _proj(2)
    p.episodes[0].status = "finalized"
    p.snapshots = [Snapshot(episode=0, facts=["처음"]), Snapshot(episode=1, facts=["하나"])]
    store.save(name, p)
    return p


def test_restore_hourly_backup_with_snapshots(home):
    from canon.schema import Snapshot
    p = _with_snaps(home, "r")
    p.meta.logline = "나중"
    p.snapshots = [Snapshot(episode=0, facts=["바뀜"])]
    p.episodes[0].status = "draft"
    store.save("r", p)  # 첫 판이 시간별 백업으로 남는다
    rows = store.backup_list("r")
    hourly = next(r for r in rows if r["kind"] == "hourly")
    assert hourly["episodes"] == 2 and hourly["finalized"] == 1 and hourly["id"].startswith("backups/project.")
    got = store.restore_backup("r", hourly["id"])
    assert [s.facts for s in got.snapshots] == [["처음"], ["하나"]] and got.meta.logline == ""
    store._views.clear()
    assert store.load("r").meta.logline == "" and store.load("r").episodes[0].status == "finalized"
    # 되돌리기 직전 판이 남고, 그 판의 스냅샷 파일도 지워지지 않아 다시 되돌릴 수 있다
    pre = next(r for r in store.backup_list("r") if r["kind"] == "restore")
    store._drop_old_snapshots(home / "r")
    store.restore_backup("r", pre["id"])
    store._views.clear()
    back = store.load("r")
    assert back.meta.logline == "나중" and [s.facts for s in back.snapshots] == [["바뀜"]]


def test_backup_list_has_prev_and_before_delete(home):
    p = _with_snaps(home, "l")
    store.save("l", p)
    store.save_backup("l", "before-delete-2", p)
    rows = store.backup_list("l")
    kinds = {r["kind"] for r in rows}
    assert {"prev", "hourly", "delete"} <= kinds
    assert next(r for r in rows if r["kind"] == "delete")["ep"] == 2
    assert rows == sorted(rows, key=lambda r: r["at"], reverse=True)
    store.restore_backup("l", "before-delete-2.json")  # 스냅샷이 안에 든 판도 되돌린다
    assert [s.facts for s in store.load("l").snapshots] == [["처음"], ["하나"]]
    for bad in ("../x/project.json", "project.json", "backups/../project.json", "pending.json"):
        with pytest.raises(FileNotFoundError):
            store.restore_backup("l", bad)


def test_web_backups_list_and_restore(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import web
    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _proj(1)
    store.save("w", p)
    p.meta.logline = "나중"
    store.save("w", p)
    c = TestClient(web.app)
    rows = c.get("/api/projects/w/backups").json()
    prev = next(r for r in rows if r["kind"] == "prev")
    assert c.post("/api/projects/w/backups/restore", json={"id": "../w/project.json"}).status_code == 404
    r = c.post("/api/projects/w/backups/restore", json={"id": prev["id"]})
    assert r.status_code == 200 and r.json()["meta"]["logline"] == ""
    assert store.load("w").meta.logline == ""
    assert any(x["kind"] == "restore" for x in c.get("/api/projects/w/backups").json())
    store.edit_pending("w", lambda d: d["results"].update({"state:1": {"ep": 1}}))
    r = c.post("/api/projects/w/backups/restore", json={"id": prev["id"]})
    assert r.status_code == 400 and "1화" in r.json()["detail"]  # 검토를 기다리는 결과가 옛 판에 들어가지 않게 막는다
    assert c.get("/api/projects/nope/backups").status_code == 404


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


def _orphan_backup(home, name, monkeypatch):
    """백업 하나만 적는 스냅샷 파일을 만들고 SNAP_GRACE 를 0 으로 둔다. (작품 폴더, 백업 경로, 그 파일 이름) 을 돌려준다."""
    from canon.schema import Snapshot
    p = _with_snaps(home, name)
    d = home / name
    (d / store.BACKUP_DIR).mkdir(exist_ok=True)
    bak = d / store.BACKUP_DIR / "before-restore.20260101-000000.json"
    shutil.copy(d / "project.json", bak)  # 지금 스냅샷 파일들을 적는 백업
    only = set(store._snap_refs(bak))
    p.snapshots = [Snapshot(episode=0, facts=["새것"])]
    store.save(name, p)
    store.save(name, p)  # project.json · prev 가 모두 새 스냅샷만 적는다
    for f in (d / store.BACKUP_DIR).glob("project.*.json"):
        f.unlink()  # 시간별 백업도 첫 판을 적으므로 지워 bak 하나만 남긴다
    only -= set(store._snap_refs(d / "project.json")) | set(store._snap_refs(d / "project.prev.json"))
    assert only  # 백업만 적는 파일이 있다
    monkeypatch.setattr(store, "SNAP_GRACE", 0.0)
    return d, bak, only


def test_drop_old_snapshots_skips_when_backup_unreadable(home, monkeypatch, caplog):
    d, bak, only = _orphan_backup(home, "u", monkeypatch)
    real_open = type(bak).open

    def fail_open(self, *a, **k):  # root 로 돌면 chmod 0 이 듣지 않으므로 읽기를 바꿔 실패를 만든다
        if self == bak:
            raise PermissionError(13, "Permission denied")
        return real_open(self, *a, **k)

    monkeypatch.setattr(type(bak), "open", fail_open)
    with caplog.at_level("WARNING", logger="canon"):
        store._drop_old_snapshots(d)
    assert all((d / "snapshots" / f).exists() for f in only)  # 읽지 못한 백업이 적은 파일을 지우지 않는다
    assert "스냅샷 정리를 건너뛰었어요" in caplog.text
    monkeypatch.setattr(type(bak), "open", real_open)
    assert [s.facts for s in store.read_disk(bak, home=d).snapshots] == [["처음"], ["하나"]]
    store._drop_old_snapshots(d)  # 다시 읽히면 백업이 적은 파일은 남고 정리는 그대로 돈다
    assert all((d / "snapshots" / f).exists() for f in only)


@pytest.mark.parametrize("body", ["", "\x00\x00garbage", '{"snapshot_files":["0-a.json"', '{"snapshot_files":["0-a.json",1]}'])
def test_drop_old_snapshots_skips_on_broken_head(home, monkeypatch, body):
    d, bak, only = _orphan_backup(home, "b", monkeypatch)
    bak.write_text(body, encoding="utf-8")  # 백업이 깨졌다 (빈 파일 · 손상 · 64KB 안에서 닫히지 않는 목록)
    store._drop_old_snapshots(d)
    assert all((d / "snapshots" / f).exists() for f in only)  # 깨진 판을 옛 모양으로 보고 지우지 않는다


@pytest.mark.parametrize("body", ["", "[1, 2]"])
def test_drop_old_snapshots_ignores_stray_backup_file(home, monkeypatch, body):
    d, bak, only = _orphan_backup(home, "s", monkeypatch)
    bak.unlink()  # 백업이 적던 파일은 이제 아무 판도 적지 않는다
    (d / store.BACKUP_DIR / "notes.json").write_text(body, encoding="utf-8")  # Canon 이 쓰지 않은 파일 (빈 파일 · 배열)
    store._drop_old_snapshots(d)
    assert not any((d / "snapshots" / f).exists() for f in only)  # 낯선 파일 때문에 정리가 멈추지 않는다
    assert (d / store.BACKUP_DIR / "notes.json").exists()


def test_snap_refs_tells_old_missing_and_unreadable(home):
    f = home / "x.json"
    assert store._snap_refs(f) == []  # 없는 판은 아무것도 적지 않는다
    f.write_text('{"meta":{}}', encoding="utf-8")
    assert store._snap_refs(f) is None  # 옛 모양
    f.write_text('{"snapshot_files":["0-a.json"],"meta":{}}', encoding="utf-8")
    assert store._snap_refs(f) == ["0-a.json"]
    for body in ["", "garbage", '{"snapshot_files":["0-a.json"' + " " * 70000 + "]}", '{"snapshot_files":[1]}']:
        f.write_text(body, encoding="utf-8")
        with pytest.raises(store.SnapRefsUnreadable):
            store._snap_refs(f)


def test_drop_old_snapshots_keeps_prev_refs_in_project_named_backups(home, monkeypatch):
    """작품 폴더 이름이 backups 여도 읽지 못한 project.prev.json 을 낯선 백업 파일로 넘기지 않는다."""
    from canon.schema import Snapshot
    d = home / "backups"
    p = _with_snaps(home, "backups")
    p.snapshots = [Snapshot(episode=0, facts=["새것"])]
    store.save("backups", p)  # project.json 은 새 스냅샷, prev 는 첫 판을 적는다
    for f in (d / store.BACKUP_DIR).glob("*.json"):
        f.unlink()
    only = set(store._snap_refs(d / "project.prev.json")) - set(store._snap_refs(d / "project.json"))
    assert only
    (d / "project.prev.json").write_text("", encoding="utf-8")  # prev 가 깨졌다
    monkeypatch.setattr(store, "SNAP_GRACE", 0.0)
    store._drop_old_snapshots(d)
    assert all((d / "snapshots" / f).exists() for f in only)
