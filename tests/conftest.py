"""모든 시험의 공통 격리.

canon.store 는 import 때 CANON_HOME 으로 저장 위치(store.ROOT)를 정한다. 값이 없으면 지금 폴더의 projects/ 다.
그래서 시험 모듈이 canon 을 불러오기 전에, 이 파일이 저장 위치 · 사용량 기록 · 설정 파일을 임시 폴더로 돌린다.
이미 값이 있으면(CI, AGENTS.md 의 'CANON_HOME=$(mktemp -d)') 그 값을 쓴다.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _isolate() -> None:
    # 작품 폴더 밖 저장 위치를 직접 정하는 변수는 지운다. 그러면 모두 store.ROOT 아래를 따른다
    for name in ("CANON_PROMPTLAB", "CANON_REFS", "CANON_RULES", "CANON_STUDIO", "CANON_STYLES", "CANON_USAGE"):
        os.environ.pop(name, None)
    if not os.environ.get("CANON_HOME"):
        home = tempfile.mkdtemp(prefix="canon-test-")
        os.environ["CANON_HOME"] = home
        # pytest-xdist 일꾼은 이 환경을 물려받아 같은 폴더를 쓴다. 폴더를 만든 프로세스만 끝날 때 지운다
        owner = os.getpid()
        atexit.register(lambda: os.getpid() == owner and shutil.rmtree(home, ignore_errors=True))
    # 사용자의 설정 파일(~/.canon/config.json)을 읽거나 쓰지 않게
    os.environ["CANON_CONFIG"] = str(Path(os.environ["CANON_HOME"]) / ".config.json")
    # TestClient 는 Host 를 testserver 로 보낸다. 웹 서버의 Host 검사(web._host_allowed)가 받게 더한다
    os.environ["CANON_ALLOWED_HOSTS"] = "testserver"


_isolate()


def pytest_sessionstart(session) -> None:
    from canon import store

    root = store.ROOT.resolve()
    real = (REPO / "projects").resolve()
    if root == real or real in root.parents:
        raise pytest.UsageError(f"시험이 실제 작품 폴더({real})를 쓰려고 해요. CANON_HOME 을 임시 폴더로 두세요.")


@pytest.fixture(autouse=True)
def _fresh_jobs(monkeypatch):
    """작업 목록(jobs._jobs)은 프로세스 전역이다. 앞 시험이 같은 작품 이름(예: demo)으로 돌린 작업이 남으면
    그 작업이 맡은 화(owned_episodes, OWN_GRACE 30초)가 다음 시험의 화면 저장을 막는다. 시험마다 빈 목록으로 시작한다."""
    from canon import jobs

    monkeypatch.setattr(jobs, "_jobs", {})


@pytest.fixture(autouse=True)
def _fresh_caches(monkeypatch):
    """store · web 의 모듈 전역 캐시를 시험마다 비운다.

    예전 시험은 importlib.reload(store) · reload(web) 로 이것을 비웠다. reload 한 번에 1~2.5초가 든다.
    canon 은 store.ROOT 를 요청 · 호출 때 읽으므로, 저장 위치는 monkeypatch.setattr(store, "ROOT", tmp_path) 로 바꾼다.
    """
    from canon import store

    for cache in (store._views, store._snap_written, store._md_written, store._preset_seen, store._brief_seen):
        cache.clear()
    from canon import settings

    settings._backups.clear()  # 깨진 설정 파일 보관본 경로
    web = sys.modules.get("canon.web")
    if web is not None:
        for cache in (web._cards, web._rests, web._json_views):
            cache.clear()
        monkeypatch.setattr(web, "_claude_seen", None)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """mock LLM 과 tmp_path 저장 위치로 띄운 웹 앱의 TestClient. web 을 다시 불러오지 않는다."""
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from fastapi.testclient import TestClient

    from canon import store, web

    # 따로 둔 MonkeyPatch 라서, 시험이 monkeypatch.undo() 를 불러도 store.ROOT 는 남는다
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(store, "ROOT", tmp_path)
        yield TestClient(web.app)
