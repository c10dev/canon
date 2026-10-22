"""문체 라이브러리. 문체(스타일 프로필 + 분석한 원문)를 작품과 따로 저장해 여러 작품에서 다시 쓴다.

항목 하나가 <CANON_HOME>/.styles/<id>.json 파일 하나다 (CANON_STYLES 로 경로 변경).
작품에 적용하면 프로필과 기준 지표를 project.json 으로 복사하고 style_id 로 출처만 기억한다.
그래서 라이브러리를 고쳐도 쓰고 있는 작품의 문체는 사용자가 다시 적용하기 전까지 바뀌지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import metrics, store
from .schema import Project, StyleEntry, StyleProfile

ID_RE = re.compile(r"^[0-9a-f]{8,32}$")


def root() -> Path:
    return Path(os.environ.get("CANON_STYLES") or store.ROOT / ".styles")


def _path(sid: str) -> Path:
    if not ID_RE.match(sid):
        raise KeyError(f"문체 라이브러리에 없는 항목입니다: {sid}")
    return root() / f"{sid}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def exists(sid: str) -> bool:
    return bool(ID_RE.match(sid)) and _path(sid).exists()


def load(sid: str) -> StyleEntry:
    path = _path(sid)
    if not path.exists():
        raise KeyError(f"문체 라이브러리에 없는 항목입니다: {sid}")
    return StyleEntry.model_validate_json(path.read_text(encoding="utf-8"))


def save(e: StyleEntry) -> StyleEntry:
    e.name = e.name.strip()
    if not e.name:
        raise ValueError("문체 이름을 입력하세요")
    e.created_at = e.created_at or _now()
    e.updated_at = _now()
    path = _path(e.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(e.model_dump_json(indent=2), encoding="utf-8")
    return e


def entries() -> list[StyleEntry]:
    d = root()
    if not d.exists():
        return []
    out = []
    for f in d.glob("*.json"):
        try:
            out.append(StyleEntry.model_validate_json(f.read_text(encoding="utf-8")))
        except ValueError:
            continue  # 손으로 고치다 깨진 파일은 목록에서만 빠진다
    return sorted(out, key=lambda e: e.updated_at, reverse=True)


def create(name: str, profile: StyleProfile, sample: str = "", source: str = "", notes: str = "",
           baseline: Optional[metrics.StyleMetrics] = None) -> StyleEntry:
    sample = sample.strip()
    if sample:
        baseline = metrics.measure(sample)
    e = StyleEntry(id=uuid.uuid4().hex[:12], name=name, source=source, notes=notes,
                   sample=sample, profile=profile, baseline=baseline)
    return save(e)


def update(sid: str, name: str, profile: StyleProfile, sample: str, source: str = "", notes: str = "") -> StyleEntry:
    """사용자가 고친 항목을 저장한다. 원문이 바뀌면 기준 지표를 다시 잰다."""
    e = load(sid)
    sample = sample.strip()
    if sample != e.sample:
        e.baseline = metrics.measure(sample) if sample else None
    e.name, e.profile, e.sample, e.source, e.notes = name, profile, sample, source, notes
    return save(e)


def delete(sid: str) -> None:
    """항목을 지운다. 이 문체를 적용한 작품은 복사해 둔 프로필을 그대로 쓴다."""
    path = _path(sid)
    if not path.exists():
        raise KeyError(f"문체 라이브러리에 없는 항목입니다: {sid}")
    path.unlink()


def duplicate(sid: str) -> StyleEntry:
    e = load(sid)
    return create(f"{e.name} 사본", e.profile.model_copy(deep=True), e.sample, e.source, e.notes, e.baseline)


def used_by(sid: str) -> list[str]:
    """이 항목을 적용한 작품 폴더 이름들."""
    out = []
    if store.ROOT.exists():
        for d in sorted(store.ROOT.iterdir()):
            f = d / "project.json"
            if not f.exists():
                continue
            try:
                if json.loads(f.read_text(encoding="utf-8")).get("style_id") == sid:
                    out.append(d.name)
            except (OSError, ValueError):
                continue
    return out


def summary(e: StyleEntry) -> dict:
    return {
        "id": e.id, "name": e.name, "source": e.source, "notes": e.notes,
        "narration_pov": e.profile.narration_pov, "tense": e.profile.tense,
        "passages": len(e.profile.sample_passages), "rules": len(e.profile.dos) + len(e.profile.donts),
        "sample_chars": len(e.sample), "created_at": e.created_at, "updated_at": e.updated_at,
        "used_by": used_by(e.id),
    }


def apply(p: Project, e: StyleEntry) -> None:
    """라이브러리 문체를 작품에 복사한다. 지금 작품의 문체는 덮어쓴다."""
    p.style = e.profile.model_copy(deep=True)
    p.style_baseline = e.baseline.model_copy() if e.baseline else None
    p.style_id = e.id


def from_project(p: Project, name: str, sample: str = "", source: str = "", notes: str = "") -> StyleEntry:
    """작품의 지금 문체를 새 항목으로 저장하고 작품을 그 항목에 연결한다. 원문이 없으면 작품의 기준 지표를 쓴다."""
    e = create(name, p.style.model_copy(deep=True), sample, source, notes, p.style_baseline)
    p.style_id = e.id
    return e


def push_project(p: Project) -> StyleEntry:
    """작품에서 고친 문체로 연결된 라이브러리 항목을 갱신한다. 원문과 기준 지표는 항목의 것을 유지한다."""
    if not p.style_id:
        raise ValueError("이 작품은 라이브러리 문체에 연결돼 있지 않습니다")
    e = load(p.style_id)
    e.profile = p.style.model_copy(deep=True)
    return save(e)


def link_state(p: Project) -> dict:
    """작품 문체와 라이브러리 항목의 관계. state: none | missing | same | changed"""
    if not p.style_id:
        return {"state": "none"}
    if not exists(p.style_id):
        return {"state": "missing", "id": p.style_id}
    e = load(p.style_id)
    return {"state": "same" if e.profile == p.style else "changed", "id": e.id, "name": e.name,
            "updated_at": e.updated_at}
