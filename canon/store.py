"""JSON 파일 저장소. projects/<이름>/project.json 하나에 모든 상태를 보관하고,
본문은 읽기 편하도록 episodes/NN.md 로도 내보낸다."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .schema import Project

ROOT = Path(os.environ.get("CANON_HOME", "projects"))


def project_dir(name: str) -> Path:
    return ROOT / name


def exists(name: str) -> bool:
    return (project_dir(name) / "project.json").exists()


def load(name: str) -> Project:
    path = project_dir(name) / "project.json"
    if not path.exists():
        raise FileNotFoundError(f"프로젝트가 없습니다: {path}")
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


def save(name: str, p: Project) -> Path:
    d = project_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "project.json"
    if path.exists():
        shutil.copy(path, d / "project.prev.json")  # 직전 버전 하나는 남겨 둔다
    path.write_text(p.model_dump_json(indent=2), encoding="utf-8")

    ep_dir = d / "episodes"
    for ep in p.episodes:
        if ep.text:
            ep_dir.mkdir(exist_ok=True)
            (ep_dir / f"{ep.plot.number:02d}.md").write_text(
                f"# {ep.plot.number}화. {ep.plot.title}\n\n{ep.text}\n", encoding="utf-8"
            )
    return path
