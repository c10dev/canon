"""프롬프트 관리 페이지의 실험 판 (docs/context/specs/12-prompt-catalog.md, 정할 것 1 (나)).

조각(prompts.PIECES) 글을 고친 판을 작품 밖 <CANON_HOME>/.promptsets/<id>.json 에 둔다 (CANON_PROMPTSETS 로 경로 변경).
판은 프롬프트 관리 페이지의 견본, 프롬프트 놀이터(promptlab.load_prompt), 놀이터의 원래 판 대 실험 판 블라인드에서만 끼운다.
실제 집필 · 자동 집필 · 작업지시서 요청은 이 모듈을 부르지 않는다 (tests/test_promptset.py 가 본다). 이긴 판은 에이전트가 prompts.py 로 옮기는 PR 로 넣는다.

끼우기(apply)는 조립한 요청에서 그 조각의 견본 글(prompts.piece_text)을 찾아 바꾼 글로 한 번 바꾼다. 요청 함수는 그대로라 블록 차례도 그대로다.
LLM 을 부르지 않는다."""
from __future__ import annotations

import os
import secrets
from datetime import datetime
from pathlib import Path

from . import prompts, store
from .schema import Project, PromptSet, PromptSetChange

MAX_CHANGES = 40  # 판 하나에서 바꾸는 조각 수
TEXT_MAX = 20_000  # 바꾼 글 하나의 글자 수 (가장 긴 상수 조각보다 넉넉히)
NAME_MAX = 60
NOTE_MAX = 400
ID_LEN = 12
# 끼울 수 없는 조각: 보내기 직전 줄(백엔드가 붙임)과 요청 전체를 만드는 함수 조각
FIXED_PLACES = ("send",)


def root() -> Path:
    return Path(os.environ.get("CANON_PROMPTSETS") or store.ROOT / ".promptsets")


def _path(sid: str) -> Path:
    if not (len(sid) == ID_LEN and all(c in "0123456789abcdef" for c in sid)):
        raise KeyError(f"실험 판을 찾을 수 없어요: {sid}")
    return root() / f"{sid}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load(sid: str) -> PromptSet:
    path = _path(sid)
    if not path.exists():
        raise KeyError(f"실험 판을 찾을 수 없어요: {sid}")
    return PromptSet.model_validate_json(path.read_text(encoding="utf-8"))


def save(ps: PromptSet) -> PromptSet:
    ps.updated_at = _now()
    root().mkdir(parents=True, exist_ok=True)
    store.write_atomic(_path(ps.id), ps.model_dump_json(indent=1))
    return ps


def sets() -> list[PromptSet]:
    """고친 때 최근 것부터. 읽지 못하는 파일은 건너뛴다."""
    out = []
    for f in root().glob("*.json") if root().exists() else []:
        try:
            out.append(PromptSet.model_validate_json(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return sorted(out, key=lambda x: x.updated_at, reverse=True)


def view_kind(kind: str) -> str:
    """조립 보기가 있는 갈래만 받는다. 없으면 ValueError."""
    k = prompts.KINDS.get(kind)
    if k is None or not k.view:
        raise ValueError(f"조립 보기가 있는 갈래만 고를 수 있어요: {kind}")
    return kind


def clean_changes(changes: list[PromptSetChange]) -> list[PromptSetChange]:
    """같은 조각은 마지막 글 하나만, 끼울 수 없는 조각은 막고, MAX_CHANGES 개 · TEXT_MAX 자까지."""
    out: dict[str, PromptSetChange] = {}
    for c in changes:
        pc = prompts.PIECES.get(c.piece)
        if pc is not None and (pc.place in FIXED_PLACES or c.piece.endswith("_req")):
            raise ValueError(f"'{pc.title}' 조각은 실험 판에서 바꿀 수 없어요")
        if len(c.text) > TEXT_MAX:
            raise ValueError(f"바꾼 글은 {TEXT_MAX:,}자까지예요")
        out[c.piece] = PromptSetChange(piece=c.piece, text=c.text)
    if len(out) > MAX_CHANGES:
        raise ValueError(f"한 판에서 바꾸는 조각은 {MAX_CHANGES}개까지예요")
    return list(out.values())


def create(name: str = "", kind: str = "episode") -> PromptSet:
    now = _now()
    ps = PromptSet(id=secrets.token_hex(ID_LEN // 2), name=(name.strip() or "새 실험 판")[:NAME_MAX], kind=view_kind(kind),
                   created_at=now)
    return save(ps)


def update(sid: str, name: str, kind: str, changes: list[PromptSetChange], note: str) -> PromptSet:
    ps = load(sid)
    ps.name = (name.strip() or ps.name)[:NAME_MAX]
    ps.kind = view_kind(kind)
    ps.changes = clean_changes(changes)
    ps.note = note[:NOTE_MAX]
    return save(ps)


def delete(sid: str) -> None:
    load(sid)
    _path(sid).unlink()


def duplicate(sid: str) -> PromptSet:
    src = load(sid)
    ps = create(f"{src.name} 사본"[:NAME_MAX], src.kind)
    ps.changes, ps.note = list(src.changes), src.note
    return save(ps)


def apply(p: Project, n: int, kind: str, system: str, prompt: str, ps: PromptSet) -> tuple[str, str, list[dict]]:
    """조립한 (시스템, 요청)에 판을 끼운 (시스템, 요청, 조각마다 결과). 작품을 바꾸지 않는다.
    결과 state: applied(바꿈) · same(글이 같음) · absent(이 견본 요청에 그 조각 글이 없음) · missing(코드에서 사라진 조각, 끼우지 않음)."""
    rows = []
    swaps: list[tuple[str, str]] = []
    for c in ps.changes:
        pc = prompts.PIECES.get(c.piece)
        if pc is None:
            rows.append({"piece": c.piece, "title": c.piece, "state": "missing", "original": "", "text": c.text})
            continue
        original = prompts.piece_text(p, n, c.piece, kind, prompt)
        here = bool(original) and (original in system or original in prompt)
        state = "absent" if not here else "same" if c.text == original else "applied"
        rows.append({"piece": c.piece, "title": pc.title, "state": state, "original": original, "text": c.text})
        if state == "applied":
            swaps.append((original, c.text))
    for old, new in swaps:  # 견본 글은 판을 끼우기 전 요청에서 찾았다. 앞 바꿈이 그 글을 지웠으면 그 조각은 '없음'으로 바꾼다
        if old in system:
            system = system.replace(old, new, 1)
        elif old in prompt:
            prompt = prompt.replace(old, new, 1)
        else:
            next(r for r in rows if r["original"] == old and r["state"] == "applied")["state"] = "absent"
    return system, prompt, rows
