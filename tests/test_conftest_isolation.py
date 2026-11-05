"""tests/conftest.py 가 CANON_HOME 없이도 시험을 임시 폴더에 가두는지 본다.

진짜 저장소 대신 임시 폴더에 가짜 저장소(tests/conftest.py 사본 + 탐침 시험)를 만들고,
그 저장소 루트를 지금 폴더로 두어 pytest 를 따로 띄운다. 실패해도 실제 projects/ 는 건드리지 않는다.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent

PROBE = '''
def test_probe():
    from canon import settings, store, usage
    from canon.schema import Meta, Project

    class LocalLLM:
        model = "probe"

    store.save("probe", Project(meta=Meta(title="격리")))
    usage.record(LocalLLM(), {"prompt_tokens": 1})
    settings._write({"probe": True})
    assert usage.log_path().exists()
'''


# 앞 시험이 채운 store · web 캐시를 다음 시험이 보지 않는다 (conftest._fresh_caches). 같은 프로세스에서 차례로 돈다
CACHE_PROBE = '''
def test_a_fill():
    from canon import store, web

    store._views["x"] = None
    web._cards["x"] = None
    web._json_views[("x", "y")] = None


def test_b_empty():
    from canon import store, web

    assert store._views == {} and web._cards == {} and web._json_views == {}
'''


def _run(tmp_path, probe=PROBE, **env):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    shutil.copy(TESTS / "conftest.py", repo / "tests" / "conftest.py")
    (repo / "tests" / "test_probe.py").write_text(probe, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("CANON_", "PYTEST_"))}
    clean.update(PYTHONPATH=str(TESTS.parent), HOME=str(home), CANON_LLM="mock", **env)
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "tests"]
    r = subprocess.run(cmd, cwd=repo, env=clean, capture_output=True, text=True, timeout=120)
    return r, repo, home


def test_without_canon_home_nothing_lands_in_repo(tmp_path):
    r, repo, home = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 passed" in r.stdout
    assert not (repo / "projects").exists()
    assert not (home / ".canon").exists()


def test_stray_usage_path_is_ignored(tmp_path):
    stray = tmp_path / "real-usage.jsonl"
    r, repo, _ = _run(tmp_path, CANON_USAGE=str(stray))
    assert r.returncode == 0, r.stdout + r.stderr
    assert not stray.exists()


def test_repo_projects_folder_is_refused(tmp_path):
    real = tmp_path / "repo" / "projects"
    r, repo, _ = _run(tmp_path, CANON_HOME=str(real))
    assert r.returncode != 0
    assert "실제 작품 폴더" in r.stdout + r.stderr
    assert not (real / "probe").exists()


def test_caches_are_cleared_between_tests(tmp_path):
    r, _, _ = _run(tmp_path, probe=CACHE_PROBE)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2 passed" in r.stdout


def test_no_test_reloads_store_or_web():
    """importlib.reload(store) · reload(web) 는 한 번에 1~2.5초가 든다. 시험은 store.ROOT 를 monkeypatch 로 바꾼다."""
    pat = re.compile(r"reload\((?:canon\.)?(?:st|store|web|library)\)")
    hits = [f"{f.name}:{i}" for f in TESTS.glob("test_*.py") if f.name != Path(__file__).name
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if pat.search(line)]
    assert hits == []
