"""반영 뒤 지금 상태 고치기: 작가가 인물의 지금 상태(감정 · 목표 · 위치 · 차림)를 상태 반영 뒤에도 고치고 기록한다.

인물의 가변 상태(CharacterState)는 상태 변경안을 승인해 반영하는 것이 기본이다. 반영한 값이 본문과 어긋나거나
작가가 다음 화 전에 바로잡고 싶을 때 인물 화면에서 고친다. 고친 것은 마지막으로 반영한 화(statwin.last_done)의
작가 기록(Project.state_log)으로 남기고, 그 화 스냅샷도 맞춘다 (statwin.set_stats 와 같은 방식).
같은 화 뒤에 같은 칸을 여러 번 고치면 한 기록으로 합치고, 반영 값으로 돌아오면 기록을 지운다.
그래서 '기록이 있다'는 '마지막 반영 값과 다르다'와 같다. 화면은 그때만 '직접 고침'과 되돌리기 단추를 보인다.

- 1화를 반영하기 전에는 1화 시작 전(0화) 상태를 고친다. 기록은 0화로 남기고, 스냅샷 0 은 있을 때만 맞춘다 (첫 반영이 만든다).
- 화 되돌리기(pipeline.revert)는 n화 뒤 기록을 자르기만 한다. 상태는 n화 스냅샷에서 돌아오고, n화 기록의 수정은 그 스냅샷에 이미 들어 있다.
  n화 뒤 작가 기록을 n화로 옮겨 지금 값을 두지 않는다: 지금 상태는 그 화 시점에만 맞아서, 남기면 뒤 화 상태가 앞 화 프롬프트에 들어간다.
- 아는 정보(knows) · 메모 · 상태창 수치(statwin) · 관계 수치(수동보정 사건)는 다루지 않는다.
LLM 을 부르지 않는다.
"""
from __future__ import annotations

from . import dynamics
from .schema import CharacterState, Project, StateRecord
from .statwin import last_done

# 고칠 수 있는 칸. 화면 이름은 인물 카드(static/cast.js 의 SHEET_STATE)와 같다
FIELDS: dict[str, str] = {"emotional_state": "감정", "current_goal": "목표", "location": "위치", "attire": "차림"}


def _state(p: Project, cid: str) -> CharacterState:
    s = p.state_of(cid)
    if s is None:
        s = CharacterState(character_id=cid)
        p.states.append(s)
    return s


def set_state(p: Project, cid: str, values: dict[str, str | None]) -> list[StateRecord]:
    """작가가 지금 상태의 칸을 고친다. values 에 없거나 None 인 칸은 그대로 둔다. 빈 글이면 칸을 비운다.
    새로 남기거나 고친 기록을 돌려준다."""
    if not any(c.id == cid for c in p.characters):
        raise KeyError(f"없는 인물이에요: {cid}")
    bad = [f for f in values if f not in FIELDS]
    if bad:
        raise ValueError(f"고칠 수 없는 칸이에요: {', '.join(bad)}")
    n = last_done(p)
    st = _state(p, cid)
    out: list[StateRecord] = []
    for f, v in values.items():
        if v is None:
            continue
        before, after = getattr(st, f), v.strip()
        if before == after:
            continue
        setattr(st, f, after)
        last = next((r for r in reversed(p.state_log) if r.character_id == cid and r.field == f), None)
        if last is not None and last.episode == n:
            last.after = after
            if last.after == last.before:
                p.state_log.remove(last)
            else:
                out.append(last)
            continue
        rec = StateRecord(episode=n, character_id=cid, field=f, before=before, after=after)  # type: ignore[arg-type]
        p.state_log.append(rec)
        out.append(rec)
    if p.snapshot(n) is not None:
        dynamics.take_snapshot(p, n)
    return out


def edited(p: Project, cid: str) -> list[StateRecord]:
    """마지막 반영 값과 다른 칸의 기록. 명령줄 · 시험이 쓴다 (화면은 작품의 state_log 를 바로 읽는다)."""
    n = last_done(p)
    return [r for r in p.state_log if r.character_id == cid and r.episode == n]


def revert(p: Project, n: int) -> None:
    """pipeline.revert 뒤에 부른다 (features.REVERT_LAST). n화 뒤 기록을 자르고, 지워진 인물의 기록도 뺀다."""
    ids = {c.id for c in p.characters}
    p.state_log = [r for r in p.state_log if r.episode <= n and r.character_id in ids]
