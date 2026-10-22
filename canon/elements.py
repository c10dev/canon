"""인과율: 작가가 언제든 더하는 이야기 요소(요소, 특징, 설정, 사건)와 그 요소가 닿는 화.

LLM 을 부르지 않는 부분만 둔다. 이름·별칭·관련 인물로 관련 화 지도를 그리고(links),
화마다 프롬프트에 넣을 요소를 고르고(for_episode), 사람이 읽는 한 줄 설명을 만든다(describe).
영향 분석(AI)과 반영은 pipeline.analyze_impact / apply_impact 가 맡는다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from pydantic import BaseModel

from .schema import Episode, Project, StoryElement

KINDS = ["세계 규칙", "장소", "물건", "세력", "인물 특징", "과거 사건", "예정 사건", "기타"]
SNIPPET = 60  # 관련 화 지도에서 언급 앞뒤로 보여 줄 글자 수


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(p: Project, eid: str) -> StoryElement:
    for el in p.elements:
        if el.id == eid:
            return el
    raise KeyError(f"요소가 없습니다: {eid}")


def new_id(p: Project) -> str:
    have = {el.id for el in p.elements}
    n = len(p.elements) + 1
    while f"el-{n:02d}" in have:
        n += 1
    return f"el-{n:02d}"


def last_written(p: Project) -> int:
    return max((e.plot.number for e in p.episodes if e.text), default=0)


def stamp(p: Project) -> None:
    """새로 더한 요소에 만든 때와, 그때 본문이 있던 마지막 화를 적는다."""
    for el in p.elements:
        if not el.created_at:
            el.created_at = now()
            el.added_after = last_written(p)


def basis(el: StoryElement) -> str:
    """영향 분석에 쓰인 요소 내용. 지금 내용과 다르면 분석이 지난 것이다.
    화면(causal.js 의 elBasis)도 같은 모양으로 만들어 비교하므로 순서와 형식을 함께 고친다."""
    return json.dumps([el.kind, el.name, el.aliases, el.description, el.characters, el.since_ep, el.episodes, el.reveal_ep],
                      ensure_ascii=False, separators=(",", ":"))


def stale(el: StoryElement) -> bool:
    return bool(el.impact) and el.impact.basis != basis(el)


def terms(el: StoryElement) -> list[str]:
    """언급을 찾을 말. 한 글자 말은 너무 흔해서 뺀다."""
    out = []
    for t in [el.name, *el.aliases]:
        t = t.strip()
        if len(t) >= 2 and t not in out:
            out.append(t)
    return out


def plot_text(e: Episode) -> str:
    pl = e.plot
    return "\n".join([pl.title, pl.summary, *pl.events, pl.emotional_shift, pl.ending_hook, *pl.foreshadow_plant])


# ---------- 시점 ----------

def exists_at(el: StoryElement, n: int) -> bool:
    """n화 시점에 이미 사실인가. since_ep 0 은 처음부터."""
    return el.since_ep <= n


def timing(el: StoryElement) -> str:
    parts = ["처음부터 사실" if el.since_ep <= 0 else f"{el.since_ep}화부터 생김"]
    if el.episodes:
        parts.append("나올 화 " + ", ".join(f"{n}화" for n in sorted(el.episodes)))
    if el.reveal_ep:
        parts.append(f"{el.reveal_ep}화에 독자에게 드러남")
    return " / ".join(parts)


def describe(p: Project, el: StoryElement, n: int | None = None) -> str:
    """프롬프트에 넣는 한 줄. n 을 주면 그 화 기준으로 숨길지 알려 준다."""
    names = {c.id: c.name for c in p.characters}
    alias = f" (다른 이름: {', '.join(el.aliases)})" if el.aliases else ""
    line = f"- [{el.kind}] {el.name}{alias}: {el.description.strip()}"
    if el.characters:
        line += f"\n  관련 인물: {', '.join(names.get(c, c) for c in el.characters)}"
    line += f"\n  시점: {timing(el)}"
    if n is not None and el.reveal_ep and n < el.reveal_ep:
        line += f"\n  ※ {el.reveal_ep}화 전이므로 아직 드러내지 않는다. 독자가 나중에 돌아보면 알 만한 암시만 쓸 수 있다."
    elif n is not None and n in el.episodes:
        line += "\n  ※ 이번 화에 나와야 한다."
    return line


# ---------- 화별로 넣을 요소 ----------

def relevant(el: StoryElement, e: Episode) -> bool:
    if el.context == "off" or not exists_at(el, e.plot.number):
        return False
    if el.context == "always" or e.plot.number in el.episodes:
        return True
    if set(el.characters) & set(e.plot.characters):
        return True
    text = plot_text(e)
    return any(t in text for t in terms(el))


def for_episode(p: Project, n: int) -> list[StoryElement]:
    e = p.episode(n)
    return [el for el in p.elements if relevant(el, e)]


def episode_block(p: Project, n: int) -> str:
    """본문 쓰기 컨텍스트에 넣는 블록. 넣을 요소가 없으면 빈 문자열."""
    return "\n".join(describe(p, el, n) for el in for_episode(p, n))


def active_block(p: Project, n: int) -> str:
    """검수용: n화 시점에 이미 사실인 요소 전부."""
    return "\n".join(describe(p, el, n) for el in p.elements if el.context != "off" and exists_at(el, n))


def plan_block(p: Project) -> str:
    """기획용(구조, 화별 플롯, 플롯 대화): 시점과 함께 모든 요소."""
    return "\n".join(describe(p, el) for el in p.elements if el.context != "off")


# ---------- 관련 화 지도 (AI 없이) ----------

class Link(BaseModel):
    episode: int
    status: str
    where: list[str]       # 본문, 플롯, 요약
    terms: list[str]       # 찾은 말
    characters: list[str]  # 겹치는 관련 인물 id
    planned: bool          # 나올 화로 적어 둔 화
    snippet: str = ""


def _snippet(text: str, term: str) -> str:
    i = text.find(term)
    if i < 0:
        return ""
    a, b = max(0, i - SNIPPET), min(len(text), i + len(term) + SNIPPET)
    s = re.sub(r"\s+", " ", text[a:b]).strip()
    return ("…" if a else "") + s + ("…" if b < len(text) else "")


def links(p: Project, el: StoryElement) -> list[Link]:
    ts = terms(el)
    out = []
    for e in p.episodes:
        n = e.plot.number
        where, found, snip = [], [], ""
        for label, text in (("본문", e.text), ("플롯", plot_text(e)), ("요약", e.summary)):
            hit = [t for t in ts if text and t in text]
            if hit:
                where.append(label)
                found += [t for t in hit if t not in found]
                snip = snip or _snippet(text, hit[0])
        chars = [c for c in el.characters if c in e.plot.characters]
        planned = n in el.episodes
        if where or chars or planned:
            out.append(Link(episode=n, status=e.status, where=where, terms=found, characters=chars, planned=planned, snippet=snip))
    return out


# ---------- 인용 찾기 ----------

def find(text: str, quote: str) -> tuple[int, int] | None:
    """quote 를 text 에서 찾는다. 공백과 줄바꿈 차이는 봐준다. 못 찾으면 None."""
    quote = quote.strip()
    if not quote or not text:
        return None
    i = text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    words = quote.split()
    m = re.search(r"\s+".join(map(re.escape, words)), text)
    return (m.start(), m.end()) if m else None
