"""인물 표지: 반영한 화 본문에서 작가가 거둔 말버릇 · 버릇 · 외모 특징 (docs/webnovel/specs/10-marks.md).

표지는 기록이다. 어떤 요청에도 넣지 않고(Character._prompt_view, prompts.cast_view), 인물 설정 칸을 바꾸지 않는다.
작가가 집필 화면에서 고른 구절로만 더하고, 인물 화면에서 고치고 지운다. 화면 저장은 표지를 덮지 않는다(keep).
LLM 을 부르지 않는다.
"""
from __future__ import annotations

import uuid

from . import elements
from .schema import Character, CharMark, Project

KINDS = ("말버릇", "버릇", "외모")
TEXT_MAX = 200  # 표지는 한 줄 기록이다
QUOTE_MAX = 400


def _char(p: Project, cid: str) -> Character:
    c = next((c for c in p.characters if c.id == cid), None)
    if c is None:
        raise KeyError(f"인물이 없어요: {cid}")
    return c


def _mark(c: Character, mid: str) -> CharMark:
    m = next((m for m in c.marks if m.id == mid), None)
    if m is None:
        raise KeyError(f"{c.name}의 표지가 없어요: {mid}")
    return m


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"표지 갈래는 {' · '.join(KINDS)} 가운데 하나예요")
    return kind


def _text(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > TEXT_MAX:
        raise ValueError(f"표지 글은 {TEXT_MAX}자까지 적을 수 있어요")
    return text


def found(p: Project, m: CharMark) -> bool:
    """근거 구절이 거둔 화의 지금 본문에 있는지. 공백 · 줄바꿈 차이는 봐준다 (elements.find, 화면 cast.js castMarkFound 와 같은 규칙)."""
    e = next((e for e in p.episodes if e.plot.number == m.episode), None)
    return bool(e and elements.find(e.text, m.quote))


def add(p: Project, cid: str, kind: str, text: str, n: int, quote: str) -> CharMark:
    """n 화 본문의 quote 를 근거로 표지를 더한다. 반영한 화만 받는다. text 가 비면 구절을 그대로 쓴다."""
    c = _char(p, cid)
    kind = _kind(kind)
    e = p.episode(n)
    if e.status != "finalized":
        raise ValueError("반영한 화에서만 표지를 거둘 수 있어요")
    quote = quote.strip()
    if not quote:
        raise ValueError("근거가 될 본문 구절을 골라 주세요")
    if len(quote) > QUOTE_MAX:
        raise ValueError(f"근거 구절은 {QUOTE_MAX}자까지 고를 수 있어요")
    at = elements.find(e.text, quote)
    if at is None:
        raise ValueError(f"고른 구절이 {n}화 본문에 없어요. 본문을 저장한 뒤 다시 골라 주세요")
    quote = e.text[at[0]:at[1]]  # 본문의 글 그대로 (화면이 includes 로 찾게)
    have = {m.id for m in c.marks}
    mid = f"m{uuid.uuid4().hex[:8]}"
    while mid in have:
        mid = f"m{uuid.uuid4().hex[:8]}"
    m = CharMark(id=mid, kind=kind, text=_text(text) or _text(quote[:TEXT_MAX]), episode=n, quote=quote)
    c.marks.append(m)
    return m


def edit(p: Project, cid: str, mid: str, kind: str, text: str) -> CharMark:
    """갈래와 글만 고친다. 거둔 화와 근거 구절은 그대로 (근거를 바꾸려면 지우고 다시 거둔다)."""
    m = _mark(_char(p, cid), mid)
    text = _text(text)
    if not text:
        raise ValueError("표지 글을 적어 주세요")
    m.kind, m.text = _kind(kind), text
    return m


def remove(p: Project, cid: str, mid: str) -> None:
    c = _char(p, cid)
    _mark(c, mid)
    c.marks = [m for m in c.marks if m.id != mid]


def keep(disk: Project, p: Project) -> None:
    """화면 저장(web._put_locked)이 표지를 고치지 않게 디스크의 표지를 인물 id 로 둔다. 디스크에 없는 인물은 표지가 없다."""
    have = {c.id: c.marks for c in [*disk.characters, *disk.cast_candidates]}
    for c in [*p.characters, *p.cast_candidates]:
        c.marks = [m.model_copy() for m in have.get(c.id, [])]


def move(p: Project, f) -> int:
    """화 끼워 넣기 · 빼기 (renumber.move_points): 거둔 화를 한 화 번호처럼 옮긴다. 뺀 화를 가리키는 표지도 지우지 않는다.
    반영한 화는 옮길 수 없는 화(renumber.last_fixed)라 실제로 바뀌는 일은 드물다. 고친 수를 돌려준다."""
    changed = 0
    for c in [*p.characters, *p.cast_candidates]:
        for m in c.marks:
            ep = f(m.episode) if m.episode else m.episode
            changed += ep != m.episode
            m.episode = ep
    return changed


def lines(p: Project, c: Character) -> list[str]:
    """명령줄 cast 출력의 표지 줄."""
    return [f"[{m.kind}] {m.text} ({m.episode}화)" + ("" if found(p, m) else " (본문에서 못 찾음)") for m in c.marks]
