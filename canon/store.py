"""JSON 파일 저장소. projects/<이름>/project.json 하나에 모든 상태를 보관하고,
본문은 읽기 편하도록 episodes/NN.md 로도 내보낸다."""
from __future__ import annotations

import json
import os
import shutil
import threading
from contextvars import ContextVar
from pathlib import Path

from .dynamics import seed_ties
from .schema import Project

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
        raise FileNotFoundError(f"프로젝트가 없습니다: {path}")
    p = Project.model_validate_json(path.read_text(encoding="utf-8"))
    seed_ties(p)  # 관계 역학 이전의 project.json 은 affinity 로 방향 관계를 만든다
    return p


def save(name: str, p: Project) -> Path:
    d = project_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "project.json"
    if path.exists():
        disk = json.loads(path.read_text(encoding="utf-8"))
        if writer.get():
            p.edit_rev, p.saved_by = disk.get("edit_rev", 0) + 1, writer.get()
        else:  # 작업이 오래전에 읽은 사본을 저장해도 화면 저장 기록은 디스크 것을 잇는다
            p.edit_rev, p.saved_by = disk.get("edit_rev", 0), disk.get("saved_by", "")
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
