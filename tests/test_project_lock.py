"""jobs.project_lock 의 프로세스 사이 잠금(작품 폴더 .edit.lock 의 flock)."""
import os
import subprocess
import sys
import textwrap
import threading

import pytest

from canon import jobs, store
from canon.schema import Meta, Project


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    store.save("w", Project(meta=Meta(title="잠금")))
    return tmp_path


def _hold(path) -> subprocess.Popen:
    """자식 프로세스가 path 에 flock 을 쥐고, 표준 입력에 한 줄이 올 때까지 놓지 않는다."""
    code = textwrap.dedent(f"""
        import fcntl, os, sys
        fd = os.open({str(path)!r}, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        print("held", flush=True)
        sys.stdin.readline()
    """)
    proc = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


def _free(proc: subprocess.Popen) -> None:
    proc.stdin.write("\n")
    proc.stdin.flush()
    proc.wait(5)


def test_waits_while_other_process_holds_lock(home):
    proc = _hold(home / "w" / jobs.EDIT_LOCK)
    try:
        done = threading.Event()

        def edit():
            with jobs.project_lock("w"):
                done.set()

        t = threading.Thread(target=edit)
        t.start()
        assert not done.wait(0.3)  # 다른 프로세스가 작품을 고치는 동안은 들어가지 않는다
        _free(proc)
        assert done.wait(5)
        t.join()
    finally:
        proc.kill()
        proc.wait()


def test_gives_up_after_limit_and_frees_thread_lock(home, monkeypatch):
    monkeypatch.setattr(jobs, "LOCK_WAIT", 0.2)
    proc = _hold(home / "w" / jobs.EDIT_LOCK)
    try:
        with pytest.raises(jobs.Locked, match="잠시 뒤 다시 시도하세요"):
            with jobs.project_lock("w"):
                pass
        _free(proc)
    finally:
        proc.kill()
        proc.wait()
    with jobs.project_lock("w"):  # 기다리다 포기해도 프로세스 안 잠금은 풀려 있다
        pass


def test_child_process_waits_for_parent(home):
    """이쪽이 잠금을 쥔 동안 다른 프로세스의 project_lock 은 기다리다 상한을 넘기면 Locked 를 낸다."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(jobs.__file__)))
    code = textwrap.dedent(f"""
        from pathlib import Path
        from canon import jobs, store
        store.ROOT = Path({str(home)!r})
        jobs.LOCK_WAIT = 0.2
        try:
            with jobs.project_lock("w"):
                print("got")
        except jobs.Locked:
            print("locked")
    """)
    with jobs.project_lock("w"):
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root, timeout=30)
    assert out.stdout.strip() == "locked", out.stderr
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root, timeout=30)
    assert out.stdout.strip() == "got", out.stderr


def test_save_inside_lock_does_not_block(home):
    p = store.load("w")
    p.meta.title = "고침"
    with jobs.project_lock("w"):
        store.save("w", p)  # store.save 의 .lock 과 다른 파일이라 같은 스레드에서 막히지 않는다
    store._views.clear()
    assert store.load("w").meta.title == "고침"


def test_dot_keys_and_missing_projects_make_no_folder(home):
    with jobs.project_lock(".revlab/1"), jobs.project_lock("none"):
        pass
    assert not (home / ".revlab").exists()
    assert not (home / "none").exists()
