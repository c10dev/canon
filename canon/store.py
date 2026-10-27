"""JSON 파일 저장소. projects/<이름>/project.json 하나에 모든 상태를 보관하고,
본문은 읽기 편하도록 episodes/NN.md 로도 내보낸다."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from contextvars import ContextVar
from pathlib import Path

from . import cancel
from .dynamics import seed_ties
from .schema import BranchInfo, Project

ROOT = Path(os.environ.get("CANON_HOME", "projects"))

# 지금 저장하는 화면(브라우저 탭) id. 웹 요청이 정하고, 백그라운드 작업 · 자동 집필 · CLI 는 빈 값이다.
# 화면이 저장하면 Project.edit_rev 를 올리고 saved_by 에 남긴다. 빈 값이면 디스크의 두 값을 그대로 둔다
writer: ContextVar[str] = ContextVar("writer", default="")


def project_dir(name: str) -> Path:
    return ROOT / name


def exists(name: str) -> bool:
    return (project_dir(name) / "project.json").exists()


def load(name: str) -> Project:
    path = project_dir(name) / "project.json"
    if not path.exists():
        raise FileNotFoundError(f"프로젝트가 없어요: {path}")
    p = Project.model_validate_json(path.read_text(encoding="utf-8"))
    seed_ties(p)  # 관계 역학 이전의 project.json 은 affinity 로 방향 관계를 만든다
    return p


_MARK = re.compile(r'"edit_rev":\s*(\d+),\s*"saved_by":\s*("(?:[^"\\]|\\.)*")')


def _saved_mark(path: Path) -> tuple[int, str]:
    """디스크 작품의 (edit_rev, saved_by). 두 칸은 Project 의 마지막 필드라 파일 끝만 읽는다 (장편도 저장마다 전체를 읽지 않게)."""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 4096))
        tail = f.read().decode("utf-8", errors="ignore")
    m = _MARK.search(tail)
    return (int(m.group(1)), json.loads(m.group(2))) if m else (0, "")


# ---------- 검토를 기다리는 AI 결과와 실패한 작업 ----------
# projects/<이름>/pending.json. 작업 결과(제안)는 화면 메모리에만 있어 새로고침 · 다른 기기에서 사라졌다.
# 작업이 끝나면 여기에 남기고, 화면이 반영하거나 버리면 지운다. 작품 데이터(project.json)는 바꾸지 않는다.
# { "results": { "<kind>:<ep>": {...} }, "failures": { "<kind>:<ep>": {...} } }

_pending_lock = threading.Lock()


def _pending_path(name: str) -> Path:
    return project_dir(name) / "pending.json"


def load_pending(name: str) -> dict:
    path = _pending_path(name)
    try:
        d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:  # 깨진 파일은 없는 것으로 본다 (다시 받으면 된다)
        d = {}
    return {"results": d.get("results", {}), "failures": d.get("failures", {})}


def edit_pending(name: str, fn) -> dict:
    """pending.json 을 읽어 fn(d) 로 고치고 저장한다."""
    cancel.check()
    with _pending_lock:
        d = load_pending(name)
        fn(d)
        path = _pending_path(name)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return d


def save(name: str, p: Project) -> Path:
    cancel.check()  # 멈춘 작업은 저장하지 않는다
    d = project_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "project.json"
    if path.exists():
        rev, by = _saved_mark(path)
        if writer.get():
            p.edit_rev, p.saved_by = rev + 1, writer.get()
        else:  # 작업이 오래전에 읽은 사본을 저장해도 화면 저장 기록은 디스크 것을 잇는다
            p.edit_rev, p.saved_by = rev, by
        shutil.copy(path, d / "project.prev.json")  # 직전 버전 하나는 남겨 둔다
    # 다른 스레드(자동 집필, 백그라운드 작업)가 쓰는 도중에 읽어도 빈 파일을 보지 않게 바꿔치기로 쓴다
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(p.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)

    ep_dir = d / "episodes"
    for ep in p.episodes:
        if ep.text:
            ep_dir.mkdir(exist_ok=True)
            (ep_dir / f"{ep.plot.number:02d}.md").write_text(
                f"# {ep.plot.number}화. {ep.plot.title}\n\n{ep.text}\n", encoding="utf-8"
            )
    return path


# ---------- 갈래 정보 (canon/branches.py) ----------
# projects/<이름>/branch.json. project.json 밖에 둬서 화면이 작품을 통째로 저장해도 덮지 않는다.

def _branch_path(name: str) -> Path:
    return project_dir(name) / "branch.json"


def load_branch(name: str) -> BranchInfo | None:
    """갈래 정보. 파일이 없거나 깨졌으면 갈래가 없는 작품으로 본다."""
    path = _branch_path(name)
    if not path.exists():
        return None
    try:
        return BranchInfo.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def save_branch(name: str, b: BranchInfo) -> Path:
    path = _branch_path(name)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(b.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def drop_branch(name: str) -> None:
    _branch_path(name).unlink(missing_ok=True)


def backup_path(name: str, tag: str) -> Path:
    return project_dir(name) / f"{tag}.json"


def save_backup(name: str, tag: str, p: Project) -> Path:
    """되돌리기용으로 작품 전체를 따로 남긴다 (예: 단편 → 장편 전환 직전, tag='before-serial')."""
    path = backup_path(name, tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(p.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_backup(name: str, tag: str) -> Project | None:
    path = backup_path(name, tag)
    if not path.exists():
        return None
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


def drop_backup(name: str, tag: str) -> None:
    backup_path(name, tag).unlink(missing_ok=True)
