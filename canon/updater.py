"""코드 자동 업데이트. 저장소가 git 클론일 때 origin/main 의 새 커밋을 받아 온다.

사용자 데이터(projects/, ~/.canon/config.json)는 git 이 추적하지 않으므로 건드리지 않는다.
안전하게 받을 수 없으면(main 이 아님, 고친 파일이 있음, fast-forward 불가) 받지 않고 이유만 돌려준다.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BRANCH = "main"
LOCK = "requirements.lock"  # 버전을 고정한 의존성 목록. 있으면 requirements.txt 대신 이것을 설치한다

# serve 가 자동 업데이트를 돌리는 동안 True. wake 를 세우면 간격을 기다리지 않고 바로 확인한다
# (main 에 머지되면 GitHub Actions 가 POST /api/update/check 로 깨운다, .github/workflows/notify-server.yml)
watching = False
wake = threading.Event()


@dataclass
class Result:
    updated: bool
    message: str
    old: str = ""  # 받기 전 커밋 (7자리)
    new: str = ""  # 받으려던 커밋 (7자리)
    rolled_back: bool = False


def _git(repo: Path, *args: str, timeout: float = 60) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout, check=True
    )
    return out.stdout.strip()


def update(repo: Path = REPO, install: bool = True, smoke: bool = True, start: bool = True) -> Result:
    """origin/main 을 받아 fast-forward 한다. 의존성이 바뀌었으면 설치한다.
    smoke 면 새 코드로 웹 서버 모듈을 불러 보고, 불러지지 않으면 이전 커밋으로 돌린다.
    start 면 새 코드로 임시 서버를 띄워 / 가 200 인지 보고, 아니면 이전 커밋으로 돌린다.
    받거나 되돌렸으면 기록 파일에 한 줄 남긴다."""
    r = _update(repo, install, smoke, start)
    record(r)
    return r


def _roll_back(repo: Path, old: str, new: str, message: str) -> Result:
    _git(repo, "reset", "--keep", old)
    return Result(False, message, old[:7], new[:7], rolled_back=True)


def _update(repo: Path, install: bool, smoke: bool, start: bool) -> Result:
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

    if install and {"requirements.txt", LOCK} & set(changed):
        reqs = repo / LOCK if (repo / LOCK).exists() else repo / "requirements.txt"
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(reqs)],
                capture_output=True, text=True, timeout=600, check=True,
            )
        except (OSError, subprocess.SubprocessError) as e:
            return _roll_back(repo, old, new, f"의존성 설치에 실패해 이전 버전으로 돌렸어요: {_reason(e)}")
    if smoke and (err := _smoke(repo)):
        return _roll_back(repo, old, new, f"새 코드를 불러오지 못해 이전 버전으로 돌렸어요: {err}")
    if start and (err := _start_check(repo)):
        return _roll_back(repo, old, new, f"새 코드로 서버를 띄우지 못해 이전 버전으로 돌렸어요: {err}")
    log = _git(repo, "log", "--format=%s", f"{old}..{new}").splitlines()
    return Result(True, f"{len(log)}개 커밋을 받았어요: " + " / ".join(log[:3]), old[:7], new[:7])


# 다시 시작하기 전에 새 코드가 불러지는지 본다. 불러지지 않는 코드로 execv 하면 systemd 가 같은 코드로 재시작만 되풀이한다
SMOKE_MODULE = "canon.web"


def _smoke(repo: Path, module: str = SMOKE_MODULE) -> str:
    """새 프로세스에서 module 을 불러 본다. 성공하면 빈 문자열, 실패하면 마지막 오류 줄."""
    if not (repo / Path(*module.split("."))).with_suffix(".py").exists():
        return ""  # 이 저장소에 그 모듈이 없다 (시험용 저장소)
    try:
        subprocess.run([sys.executable, "-c", f"import {module}"], cwd=repo, capture_output=True, text=True,
                       timeout=120, check=True)
    except (OSError, subprocess.SubprocessError) as e:
        return _reason(e)
    return ""


def _start_check(repo: Path, timeout: float = 60) -> str:
    """새 코드로 임시 서버를 띄워 GET / 가 200 인지 본다. 성공하면 빈 글자, 실패하면 이유 한 줄."""
    if not (repo / "canon" / "web.py").exists():
        return ""  # 이 저장소에 웹 서버가 없다 (시험용 저장소)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    tmp = tempfile.mkdtemp(prefix="canon-start-check-")
    # 빈 데이터 폴더로 띄워서 실제 작품과 설정을 읽지 않고, 이어 갈 실행도 없다
    env = {**os.environ, "CANON_HOME": tmp, "CANON_CONFIG": os.path.join(tmp, "config.json"),
           "CANON_LLM": "mock", "CANON_NO_BROWSER": "1"}
    # 오류 출력은 파일로 받는다. 파이프로 받고 읽지 않으면 로그가 쌓여 서버가 멈출 수 있다
    err_path = os.path.join(tmp, "stderr.log")
    with open(err_path, "w", encoding="utf-8") as err_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "canon", "serve", "--host", "127.0.0.1", "--port", str(port),
             "--no-browser", "--no-update"],
            cwd=repo, env=env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=err_file,
        )
    try:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if (code := proc.poll()) is not None:
                tail = Path(err_path).read_text(encoding="utf-8", errors="replace").strip().splitlines()
                return f"종료 코드 {code}: {tail[-1] if tail else ''}".rstrip(": ")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as resp:
                    if resp.status == 200:
                        return ""
            except OSError:
                pass
            time.sleep(0.5)
        return f"{timeout:g}초 안에 / 가 200 을 주지 않음"
    finally:
        _stop(proc)
        shutil.rmtree(tmp, ignore_errors=True)


def _stop(proc: subprocess.Popen) -> None:
    """임시 서버와 그 자식 프로세스를 끝낸다. 5초 안에 안 끝나면 강제로 끝낸다."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            break
        try:
            proc.wait(5)
            break
        except subprocess.TimeoutExpired:
            continue
    proc.wait()


def _log_path() -> Path:
    """갱신 기록 파일. 설정 파일(CANON_CONFIG)과 같은 폴더에 둔다."""
    config = os.environ.get("CANON_CONFIG")
    folder = Path(config).expanduser().parent if config else Path("~/.canon").expanduser()
    return folder / "update-log.jsonl"


def record(r: Result) -> None:
    """받았거나 되돌렸을 때만 기록 파일에 한 줄 덧붙인다. 기록에 실패해도 서버는 멈추지 않는다."""
    if not (r.updated or r.rolled_back):
        return
    line = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "updated": r.updated,
            "rolled_back": r.rolled_back, "old": r.old, "new": r.new, "message": r.message}
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


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
