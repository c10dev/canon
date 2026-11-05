"""작품 저장의 프로세스 사이 잠금(.lock 의 flock)과 막 쓴 스냅샷 파일을 지키는 유예 시간."""
import os
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from canon import store
from canon.schema import Meta, Project, Snapshot


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    return tmp_path


def _proj(fact: str = "처음") -> Project:
    p = Project(meta=Meta(title="잠금"))
    p.snapshots = [Snapshot(episode=0, facts=[fact])]
    return p


def test_save_waits_for_lock_held_by_other_process(home):
    store.save("s", _proj())
    root = os.path.dirname(os.path.dirname(os.path.abspath(store.__file__)))
    code = textwrap.dedent(f"""
        import fcntl, os, sys, time
        fd = os.open({str(home / "s" / ".lock")!r}, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        print("held", flush=True)
        sys.stdin.readline()
    """)
    proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=root)
    try:
        assert proc.stdout.readline().strip() == "held"
        done = threading.Event()
        t = threading.Thread(target=lambda: (store.save("s", _proj("둘")), done.set()))
        t.start()
        assert not done.wait(0.3)  # 다른 프로세스가 잠금을 쥐고 있는 동안은 저장하지 않는다
        proc.stdin.write("\n")
        proc.stdin.flush()
        assert done.wait(5)
        t.join()
    finally:
        proc.kill()
        proc.wait()
    store._views.clear()
    assert store.load("s").snapshots[0].facts == ["둘"]


def test_lock_is_reentrant_in_one_thread(home):
    d = home / "r"
    with store._disk_lock(d), store._disk_lock(d):
        store.save("r", _proj())  # 잠금을 쥔 스레드가 다시 저장해도 멈추지 않는다
    assert (d / "project.json").exists()


def test_other_process_save_cannot_drop_snapshot_written_mid_save(home, monkeypatch):
    """이쪽이 새 스냅샷 파일을 쓰고 project.json 을 바꾸기 전에 다른 프로세스가 저장하려 하면 기다린다.
    잠금이 없으면 그 저장이 이쪽의 새 파일을 지우고, 이쪽 project.json 은 없는 파일을 가리킨다."""
    store.save("c", _proj())
    root = os.path.dirname(os.path.dirname(os.path.abspath(store.__file__)))
    code = textwrap.dedent(f"""
        from pathlib import Path
        from canon import store
        from canon.schema import Meta, Project, Snapshot
        store.ROOT = Path({str(home)!r})
        store.SNAP_GRACE = -1.0  # 유예 시간 없이 잠금만으로 지키는지 본다
        p = Project(meta=Meta(title="잠금"))
        p.snapshots = [Snapshot(episode=0, facts=["자식"])]
        print("ready", flush=True)
        store.save("c", p)
    """)
    write = store._write_snapshots
    child: list[subprocess.Popen] = []

    def write_then_race(d, p):
        refs = write(d, p)
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=root, stdout=subprocess.PIPE, text=True)
        child.append(proc)
        assert proc.stdout.readline().strip() == "ready"  # 자식이 저장을 부르기 직전이다
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait(1.0)  # 잠금 때문에 이쪽 저장이 끝날 때까지 기다린다
        return refs

    monkeypatch.setattr(store, "_write_snapshots", write_then_race)
    store.save("c", _proj("부모"))
    assert child[0].wait(30) == 0
    p = store.read_disk(home / "c" / "project.json")
    assert p.snapshots[0].facts == ["자식"]  # 자식이 부모 다음에 저장했다
    prev = store.read_disk(home / "c" / "project.prev.json")
    assert prev.snapshots[0].facts == ["부모"]  # 부모가 쓴 스냅샷 파일이 남아 있다


def test_drop_old_snapshots_keeps_recent_orphans(home, monkeypatch):
    store.save("g", _proj())
    sdir = home / "g" / "snapshots"
    fresh = sdir / "0-fresh.json"
    stale = sdir / "0-stale.json"
    for f in (fresh, stale):
        f.write_text(Snapshot(episode=0).model_dump_json(), encoding="utf-8")
    old = time.time() - store.SNAP_GRACE - 5
    os.utime(stale, (old, old))
    store._drop_old_snapshots(home / "g")
    assert fresh.exists()  # 아직 아무 판도 적지 않았지만 막 쓴 파일이다 (다른 프로세스가 곧 적을 수 있다)
    assert not stale.exists()
