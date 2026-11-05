"""모든 시험의 공통 격리.

canon.store 는 import 때 CANON_HOME 으로 저장 위치(store.ROOT)를 정한다. 값이 없으면 지금 폴더의 projects/ 다.
그래서 시험 모듈이 canon 을 불러오기 전에, 이 파일이 저장 위치 · 사용량 기록 · 설정 파일을 임시 폴더로 돌린다.
이미 값이 있으면(CI, AGENTS.md 의 'CANON_HOME=$(mktemp -d)') 그 값을 쓴다.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _isolate() -> None:
    # 작품 폴더 밖 저장 위치를 직접 정하는 변수는 지운다. 그러면 모두 store.ROOT 아래를 따른다
    for name in ("CANON_REFS", "CANON_STUDIO", "CANON_STYLES", "CANON_USAGE"):
        os.environ.pop(name, None)
    if not os.environ.get("CANON_HOME"):
        home = tempfile.mkdtemp(prefix="canon-test-")
        os.environ["CANON_HOME"] = home
        # pytest-xdist 일꾼은 이 환경을 물려받아 같은 폴더를 쓴다. 폴더를 만든 프로세스만 끝날 때 지운다
        owner = os.getpid()
        atexit.register(lambda: os.getpid() == owner and shutil.rmtree(home, ignore_errors=True))
    # 사용자의 설정 파일(~/.canon/config.json)을 읽거나 쓰지 않게
    os.environ["CANON_CONFIG"] = str(Path(os.environ["CANON_HOME"]) / ".config.json")


_isolate()


def pytest_sessionstart(session) -> None:
    from canon import store

    root = store.ROOT.resolve()
    real = (REPO / "projects").resolve()
    if root == real or real in root.parents:
        raise pytest.UsageError(f"시험이 실제 작품 폴더({real})를 쓰려고 해요. CANON_HOME 을 임시 폴더로 두세요.")
