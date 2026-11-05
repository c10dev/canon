"""tests/conftest.py 가 CANON_HOME 없이도 시험을 임시 폴더에 가두는지 본다.

진짜 저장소 대신 임시 폴더에 가짜 저장소(tests/conftest.py 사본 + 탐침 시험)를 만들고,
그 저장소 루트를 지금 폴더로 두어 pytest 를 따로 띄운다. 실패해도 실제 projects/ 는 건드리지 않는다.
"""
import os
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


def _run(tmp_path, **env):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    shutil.copy(TESTS / "conftest.py", repo / "tests" / "conftest.py")
    (repo / "tests" / "test_probe.py").write_text(PROBE, encoding="utf-8")
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
