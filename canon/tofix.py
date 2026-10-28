"""고칠 곳: 작가가 본문 문장에 '나중에 고칠 곳' 표시와 메모를 달고, 화를 가로질러 모아 본다.

표시(ToFix)는 Episode.to_fix 에 둔다. 본문은 바꾸지 않고 프롬프트에도 넣지 않는다.
자동 집필이 도는 동안에도 달 수 있다. 웹은 작품 잠금(jobs.project_lock) 안에서 최신 project.json 을 읽어 고치고,
화면이 작품 전체를 저장할 때는 디스크의 표시를 지킨다(web._save). 그래서 자동 집필의 저장과 서로 덮지 않는다.
본문이 바뀌어 표시한 글을 찾지 못하면 표시는 그대로 두고 '찾지 못함'으로 보인다. LLM 을 부르지 않는다.
"""
from __future__ import annotations

from typing import Optional

from .schema import Episode, Project, ToFix

MAX_QUOTE = 1000  # 표시할 수 있는 가장 긴 글. 넘으면 문장 몇 개로 줄여 고른다
MAX_NOTE = 500
STATUS = {"open": "남음", "done": "고침"}


def spot(text: str, quote: str, start: int = 0) -> Optional[tuple[int, int]]:
    """본문에서 quote 가 있는 자리 (start 에 가장 가까운 것). 없으면 None. static/tofix.js 의 tofixSpot 과 같은 규칙."""
    q = (quote or "").strip()
    if not q:
        return None
    best = -1
    i = text.find(q)
    while i != -1:
        if best == -1 or abs(i - start) < abs(best - start):
            best = i
        i = text.find(q, i + 1)
    return None if best == -1 else (best, best + len(q))


def find(ep: Episode, mid: str) -> ToFix:
    for m in ep.to_fix:
        if m.id == mid:
            return m
    raise KeyError(f"{ep.plot.number}화에 그 고칠 곳이 없어요")


def _new_id(ep: Episode) -> str:
    nums = [int(m.id[1:]) for m in ep.to_fix if m.id[1:].isdigit()]
    return f"x{max(nums, default=0) + 1}"


def _note(note: str) -> str:
    note = (note or "").strip()
    if len(note) > MAX_NOTE:
        raise ValueError(f"메모는 {MAX_NOTE}자까지 적을 수 있어요")
    return note


def add(ep: Episode, quote: str, note: str, start: int, at: str) -> ToFix:
    """저장된 본문의 글에 표시를 단다. 같은 자리에 남은 표시가 있으면 새로 달지 않고 메모만 바꾼다."""
    quote = (quote or "").strip()
    if not quote:
        raise ValueError("표시할 글을 골라 주세요")
    if len(quote) > MAX_QUOTE:
        raise ValueError(f"{MAX_QUOTE:,}자까지 표시할 수 있어요. 문장 몇 개로 줄여 골라 주세요")
    note = _note(note)
    where = spot(ep.text, quote, start)
    if where is None:
        raise ValueError(f"{ep.plot.number}화 저장된 본문에서 그 글을 찾지 못했어요. 본문을 저장한 뒤 다시 표시하세요")
    for m in ep.to_fix:
        if m.status == "open" and m.quote == quote and spot(ep.text, m.quote, m.start) == where:
            if note:
                m.note = note
            return m
    m = ToFix(id=_new_id(ep), quote=quote, note=note, start=where[0], at=at)
    ep.to_fix.append(m)
    return m


def update(ep: Episode, mid: str, at: str, note: Optional[str] = None, status: Optional[str] = None) -> ToFix:
    """메모나 처리 상태(open · done)를 바꾼다. 넘기지 않은 칸은 그대로."""
    m = find(ep, mid)
    if note is not None:
        m.note = _note(note)
    if status is not None:
        if status not in STATUS:
            raise ValueError(f"알 수 없는 상태예요: {status}")
        if status != m.status:
            m.status = status
            m.done_at = at if status == "done" else ""
    if m.status == "open" and (where := spot(ep.text, m.quote, m.start)):
        m.start = where[0]  # 본문 앞쪽을 고쳐 자리가 밀렸으면 지금 자리로
    return m


def remove(ep: Episode, mid: str) -> None:
    m = find(ep, mid)
    ep.to_fix.remove(m)


def open_marks(ep: Episode) -> list[ToFix]:
    return [m for m in ep.to_fix if m.status == "open"]


def collect(p: Project, status: str = "open") -> list[dict]:
    """화 순서로 모은 표시. status 는 open · done · all. found 는 지금 본문에서 그 글을 찾았는지."""
    out = []
    for e in sorted(p.episodes, key=lambda x: x.plot.number):
        for m in e.to_fix:
            if status != "all" and m.status != status:
                continue
            out.append({"ep": e.plot.number, "title": e.plot.title, "mark": m,
                        "found": spot(e.text, m.quote, m.start) is not None})
    return out
