"""코드 자동 업데이트. 저장소가 git 클론일 때 origin/main 의 새 커밋을 받아 온다.

사용자 데이터(projects/, ~/.canon/config.json)는 git 이 추적하지 않으므로 건드리지 않는다.
안전하게 받을 수 없으면(main 이 아님, 고친 파일이 있음, fast-forward 불가) 받지 않고 이유만 돌려준다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BRANCH = "main"


@dataclass
class Result:
    updated: bool
    message: str


def _git(repo: Path, *args: str, timeout: float = 60) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout, check=True
    )
    return out.stdout.strip()


def update(repo: Path = REPO, install: bool = True) -> Result:
    """origin/main 을 받아 fast-forward 한다. 의존성이 바뀌었으면 설치한다."""
    if not (repo / ".git").exists():
        return Result(False, "git 저장소가 아니라 자동 업데이트를 건너뛰어요")
    try:
        if _git(repo, "rev-parse", "--abbrev-ref", "HEAD") != BRANCH:
            return Result(False, f"{BRANCH} 브랜치가 아니라 자동 업데이트를 건너뛰어요")
        if _git(repo, "status", "--porcelain", "--untracked-files=no"):
            return Result(False, "고친 파일이 있어 자동 업데이트를 건너뛰어요")
        _git(repo, "fetch", "--quiet", "origin", BRANCH)
        old, new = _git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", f"origin/{BRANCH}")
        if old == new:
            return Result(False, "최신 버전이에요")
        if _git(repo, "merge-base", old, new) != old:
            return Result(False, "로컬 커밋이 있어 자동 업데이트를 건너뛰어요 (git pull 로 직접 합치세요)")
        changed = _git(repo, "diff", "--name-only", old, new).splitlines()
        _git(repo, "merge", "--ff-only", "--quiet", new)
    except (OSError, subprocess.SubprocessError) as e:
        return Result(False, f"업데이트 확인 실패: {_reason(e)}")

    if install and "requirements.txt" in changed:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(repo / "requirements.txt")],
                capture_output=True, text=True, timeout=600, check=True,
            )
        except (OSError, subprocess.SubprocessError) as e:
            _git(repo, "reset", "--keep", old)
            return Result(False, f"의존성 설치에 실패해 이전 버전으로 돌렸어요: {_reason(e)}")
    log = _git(repo, "log", "--format=%s", f"{old}..{new}").splitlines()
    return Result(True, f"{len(log)}개 커밋을 받았어요: " + " / ".join(log[:3]))


def _reason(e: Exception) -> str:
    text = str(e)
    if isinstance(e, subprocess.CalledProcessError):
        text = (e.stderr or e.stdout or "").strip() or text
    return text.splitlines()[-1]


def restart(no_browser: bool = False) -> None:
    """같은 명령으로 프로세스를 다시 띄워 새 코드를 읽는다. systemd 에서도 PID 가 유지된다."""
    if no_browser:
        os.environ["CANON_NO_BROWSER"] = "1"
    os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])
