"""문체 라이브러리. 문체(스타일 프로필 + 분석한 원문)를 작품과 따로 저장해 여러 작품에서 다시 쓴다.

항목 하나가 <CANON_HOME>/.styles/<id>.json 파일 하나다 (CANON_STYLES 로 경로 변경).
작품에 적용하면 프로필과 기준 지표를 project.json 으로 복사하고 style_id · style_version 으로 출처만 기억한다.
그래서 라이브러리를 고쳐도 쓰고 있는 작품의 문체는 사용자가 다시 적용하기 전까지 바뀌지 않는다.
프로필이나 기준 지표가 바뀔 때마다 버전(StyleVersion)을 남겨 바뀐 칸을 비교하고 되돌릴 수 있다.
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
from .schema import Project, StyleEntry, StyleProfile, StyleVersion

ID_RE = re.compile(r"^[0-9a-f]{8,32}$")
VERSION_KEEP = 30  # 항목마다 남기는 버전 수

FIELD_LABELS = {
    "narration_pov": "시점", "tense": "시제", "sentence_rhythm": "문장 리듬", "description_density": "묘사 밀도",
    "dialogue_ratio": "대사 비율", "dialogue_style": "대사 방식", "inner_monologue": "내면 독백", "pacing": "전개 속도",
    "scene_transition": "장면 전환", "vocabulary": "어휘", "dos": "지킬 것", "donts": "피할 것",
    "banned_phrases": "금지 표현", "markers": "문체 표지", "devices": "가끔 쓰는 장치", "sample_passages": "대표 문단",
}


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
    e = StyleEntry.model_validate_json(path.read_text(encoding="utf-8"))
    if not e.versions:  # 버전 기록 전에 만든 항목: 지금 상태를 1번으로 보고, 다음 저장 때 함께 남긴다
        e.version = 1
        e.versions = [StyleVersion(number=1, at=e.updated_at, note="버전 기록을 시작한 상태",
                                   profile=e.profile.model_copy(deep=True), baseline=e.baseline)]
    return e


def save(e: StyleEntry, note: str = "") -> StyleEntry:
    """저장한다. 프로필이나 기준 지표가 마지막 버전과 다르면 새 버전을 남긴다 (note 가 비면 바뀐 칸 이름)."""
    e.name = e.name.strip()
    if not e.name:
        raise ValueError("문체 이름을 입력하세요")
    e.created_at = e.created_at or _now()
    e.updated_at = _now()
    _snapshot(e, note)
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
           baseline: Optional[metrics.StyleMetrics] = None, note: str = "처음 만듦") -> StyleEntry:
    sample = sample.strip()
    if sample:
        baseline = metrics.measure(sample)
    _fill_rates(profile, sample)
    e = StyleEntry(id=uuid.uuid4().hex[:12], name=name, source=source, notes=notes,
                   sample=sample, profile=profile, baseline=baseline)
    return save(e, note)


def update(sid: str, name: str, profile: StyleProfile, sample: str, source: str = "", notes: str = "",
           note: str = "") -> StyleEntry:
    """사용자가 고친 항목을 저장한다. 원문이 바뀌면 기준 지표를 다시 잰다. note 는 이번 버전 메모."""
    e = load(sid)
    sample = sample.strip()
    if sample != e.sample:
        e.baseline = metrics.measure(sample) if sample else None
    _fill_rates(profile, sample)
    e.name, e.profile, e.sample, e.source, e.notes = name, profile, sample, source, notes
    return save(e, note)


# ---------- 버전 ----------

def _snapshot(e: StyleEntry, note: str) -> bool:
    last = e.versions[-1] if e.versions else None
    if last and last.profile == e.profile and last.baseline == e.baseline:
        return False
    if not note:
        names = [c["label"] for c in diff(last.profile, e.profile)] if last else []
        if last and last.baseline != e.baseline:
            names.append("기준 지표")
        note = f"{', '.join(names)} 고침" if names else "고침"
    e.version = max([e.version] + [v.number for v in e.versions]) + 1
    e.versions = (e.versions + [StyleVersion(number=e.version, at=_now(), note=note.strip()[:200],
                                             profile=e.profile.model_copy(deep=True), baseline=e.baseline)])[-VERSION_KEEP:]
    return True


def _item(x) -> str:
    """목록 칸 한 줄을 비교 · 표시용 글로. 표지는 '글자 (쓰임)', 장치는 '이름 (상황, N화에 한 번)'."""
    if isinstance(x, str):
        return x
    if hasattr(x, "cues"):
        info = [i for i in (x.when, f"{x.every}화에 한 번" if x.every else "", "/".join(x.cues)) if i]
        return x.name + (f" ({', '.join(info)})" if info else "")
    return x.text + (f" ({x.note})" if x.note else "")


def diff(a: StyleProfile, b: StyleProfile) -> list[dict]:
    """a → b 에서 바뀐 칸. 글 칸은 before/after, 목록 칸은 added/removed 를 준다."""
    out = []
    for key, label in FIELD_LABELS.items():
        x, y = getattr(a, key), getattr(b, key)
        if x == y:
            continue
        if isinstance(x, list):
            xs, ys = [_item(i) for i in x], [_item(i) for i in y]
            out.append({"key": key, "label": label, "added": [i for i in ys if i not in xs],
                        "removed": [i for i in xs if i not in ys]})
        else:
            out.append({"key": key, "label": label, "before": x, "after": y})
    return out


def versions(e: StyleEntry) -> list[dict]:
    """버전 목록 (최근 것 먼저). 버전마다 바로 앞 버전과 비교한 바뀐 칸을 붙인다."""
    out = []
    for i, v in enumerate(e.versions):
        prev = e.versions[i - 1] if i else None
        changes = diff(prev.profile, v.profile) if prev else []
        out.append({"number": v.number, "at": v.at, "note": v.note, "current": v.number == e.version,
                    "baseline_changed": bool(prev) and prev.baseline != v.baseline, "changes": changes})
    return out[::-1]


def restore(sid: str, number: int) -> StyleEntry:
    """예전 버전의 프로필과 기준 지표로 되돌린다. 기록은 지우지 않고 되돌린 상태를 새 버전으로 남긴다."""
    e = load(sid)
    v = next((x for x in e.versions if x.number == number), None)
    if v is None:
        raise KeyError(f"{number}번 버전이 없습니다 (최근 {VERSION_KEEP}개만 남깁니다)")
    if v.profile == e.profile and v.baseline == e.baseline:
        raise ValueError("지금 문체와 같은 버전입니다")
    e.profile = v.profile.model_copy(deep=True)
    e.baseline = v.baseline.model_copy() if v.baseline else None
    return save(e, f"{number}번 버전으로 되돌림")


def _fill_rates(profile: StyleProfile, sample: str) -> None:
    """사용자가 손으로 더한 표지처럼 빈도가 비어 있으면 원문에서 센다."""
    for m in profile.markers:
        if sample and not m.per_1k:
            m.per_1k = metrics.marker_rate(sample, m.text)


def delete(sid: str) -> None:
    """항목을 지운다. 이 문체를 적용한 작품은 복사해 둔 프로필을 그대로 쓴다."""
    path = _path(sid)
    if not path.exists():
        raise KeyError(f"문체 라이브러리에 없는 항목입니다: {sid}")
    path.unlink()


def duplicate(sid: str) -> StyleEntry:
    e = load(sid)
    return create(f"{e.name} 사본", e.profile.model_copy(deep=True), e.sample, e.source, e.notes, e.baseline,
                  note=f"'{e.name}' {e.version}번 버전에서 복제")


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
        "version": e.version, "used_by": used_by(e.id),
    }


def apply(p: Project, e: StyleEntry) -> None:
    """라이브러리 문체를 작품에 복사한다. 지금 작품의 문체는 덮어쓴다."""
    p.style = e.profile.model_copy(deep=True)
    p.style_baseline = e.baseline.model_copy() if e.baseline else None
    p.style_id = e.id
    p.style_version = e.version


def from_project(p: Project, name: str, sample: str = "", source: str = "", notes: str = "") -> StyleEntry:
    """작품의 지금 문체를 새 항목으로 저장하고 작품을 그 항목에 연결한다. 원문이 없으면 작품의 기준 지표를 쓴다."""
    e = create(name, p.style.model_copy(deep=True), sample, source, notes, p.style_baseline,
               note=f"작품 '{p.meta.title or name}' 에서 만듦")
    p.style_id, p.style_version = e.id, e.version
    return e


def push_project(p: Project, note: str = "") -> StyleEntry:
    """작품에서 고친 문체를 연결된 라이브러리 항목의 새 버전으로 올린다. 원문과 기준 지표는 항목의 것을 유지한다.
    작품의 style_version 이 바뀌므로 부른 쪽이 작품을 저장한다."""
    if not p.style_id:
        raise ValueError("이 작품은 라이브러리 문체에 연결돼 있지 않습니다")
    e = load(p.style_id)
    e.profile = p.style.model_copy(deep=True)
    e = save(e, note or f"작품 '{p.meta.title or '제목 없음'}' 에서 올림")
    p.style_version = e.version
    return e


def link_state(p: Project) -> dict:
    """작품 문체와 라이브러리 항목의 관계. state: none | missing | same | changed"""
    if not p.style_id:
        return {"state": "none"}
    if not exists(p.style_id):
        return {"state": "missing", "id": p.style_id}
    e = load(p.style_id)
    return {"state": "same" if e.profile == p.style else "changed", "id": e.id, "name": e.name,
            "updated_at": e.updated_at, "version": e.version, "applied": p.style_version}
