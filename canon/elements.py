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

from . import naming
from .schema import Episode, NewPlace, Project, StoryElement

KINDS = ["세계 규칙", "장소", "물건", "세력", "인물 특징", "과거 사건", "예정 사건", "기타"]
SNIPPET = 60  # 관련 화 지도에서 언급 앞뒤로 보여 줄 글자 수


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(p: Project, eid: str) -> StoryElement:
    for el in p.elements:
        if el.id == eid:
            return el
    raise KeyError(f"요소가 없어요: {eid}")


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
    if el.found_in:
        parts.append(f"{el.found_ep}화 {el.found_in}에 처음 나옴")
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
    if short(el):  # 본문 · 플롯에서 처음 나와 등록된 장소는 한 줄로
        return f"{line} ({el.found_ep}화에 처음 나옴)"
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
    """검수용: n화 시점에 이미 사실인 요소 전부. 본문 · 플롯에서 나온 장소는 장편이면 예산까지 (n화에 나오는 곳 먼저)."""
    e = p.episode(n)
    return _block(p, [el for el in p.elements if el.context != "off" and exists_at(el, n)], e.text + "\n" + plot_text(e), n)


def plan_block(p: Project) -> str:
    """기획용(구조, 화별 플롯, 플롯 대화): 시점과 함께 모든 요소. 본문 · 플롯에서 나온 장소는 장편이면 예산까지 (최근에 나온 곳 먼저)."""
    return _block(p, [el for el in p.elements if el.context != "off"], "")


def _block(p: Project, els: list[StoryElement], text: str, n: int | None = None) -> str:
    own = [describe(p, el, n) for el in els if not el.found_in]
    return "\n".join(own + found_lines(p, [el for el in els if el.found_in], text, n))


def found_lines(p: Project, els: list[StoryElement], text: str, n: int | None = None) -> list[str]:
    """처음 나와 등록된 장소 줄. 단편은 모두, 장편은 context.BUDGET['places'] 글자까지 넣고 뺀 수를 적는다.
    text 에 이름이 나오는 곳 먼저, 그다음 최근에 처음 나온 곳. 넣는 줄은 원래 순서로."""
    if not p.serial:
        return [describe(p, el, n) for el in els]
    from .context import BUDGET  # context 가 이 모듈을 부른다

    ranked = sorted(range(len(els)), key=lambda i: (not any(t in text for t in terms(els[i])), -els[i].found_ep))
    keep, used = set(), 0
    for i in ranked:
        size = len(describe(p, els[i], n)) + 1
        if used + size <= BUDGET["places"]:
            keep.add(i)
            used += size
    out = [describe(p, els[i], n) for i in sorted(keep)]
    if len(keep) < len(els):
        out.append(f"- (본문에서 나온 장소 {len(els) - len(keep)}곳은 덜 관련돼 뺐다)")
    return out


# ---------- 본문 · 플롯에서 처음 나온 장소 ----------
# 상태 변경안(StateDelta.new_places)과 AI 플롯(PlotBatch.new_places)이 낸 새 장소를 '장소' 요소로 등록한다.
# 이야기 안에서는 처음부터 있던 곳이라 since_ep 는 0, 처음 나온 화는 found_ep 에 적고, 관련 있는 화에만 프롬프트에 넣는다.
# 본문에서 나온 장소는 그 화 반영을 취소하면 빠진다 (unregister_places). 플롯에서 나온 장소는 화를 확정할 때 등록한다.

def short(el: StoryElement) -> bool:
    """한 줄로 줄여 쓸 요소: 처음 나와 등록된 뒤 작가가 시점이나 관련 인물을 더하지 않았다."""
    return bool(el.found_in) and el.since_ep <= 0 and not el.characters and not el.episodes and not el.reveal_ep


def known_names(p: Project) -> set[str]:
    """새 장소와 겹치면 안 되는 이름(비교용 키): 장소 전부와 다른 이야기 요소의 이름 · 다른 이름."""
    out = {naming.place_key(x) for x in naming.known_places(p)}
    out |= {naming.place_key(t) for el in p.elements for t in [el.name, *el.aliases]}
    return {x for x in out if x}


def mentioned(x: NewPlace, text: str) -> bool:
    return any(t.strip() and t.strip() in text for t in [x.name, *x.aliases])


def clean_places(p: Project, places: list[NewPlace], text: str | None = None) -> tuple[list[NewPlace], list[str]]:
    """이미 있는 이름, 같은 목록 안에서 겹친 이름, 두 글자가 안 되는 이름을 뺀다. text 를 주면 그 글에 나오지 않는 장소도 뺀다.
    이미 있는 장소와 비슷한 이름(naming.similar_place)은 경고로 돌려준다."""
    have, near = known_names(p), naming.known_places(p)
    out, warns = [], []
    for x in places:
        name = x.name.strip()
        k = naming.place_key(name)
        if len(k) < 2 or k in have or (text is not None and not mentioned(x, text)):
            continue
        aliases = [a.strip() for a in x.aliases if a.strip() and naming.place_key(a) not in have | {k}]
        out.append(x.model_copy(update={"name": name, "kind": x.kind.strip(), "description": x.description.strip(),
                                        "aliases": list(dict.fromkeys(aliases))}))
        have |= {k, *(naming.place_key(a) for a in aliases)}
        other = naming.similar_place(name, near)
        if other:
            warns.append(naming.similar_warning(name, other))
    return out, warns


def add_places(p: Project, places: list[NewPlace], n: int, found_in: str) -> list[str]:
    """새 장소를 '장소' 요소로 등록하고 이름을 돌려준다. 그새 같은 이름이 생겼으면 뺀다."""
    places, _ = clean_places(p, places)
    for x in places:
        desc = x.description
        if x.kind and x.kind not in desc:
            desc = f"{x.kind}. {desc}".strip()
        p.elements.append(StoryElement(id=new_id(p), kind="장소", name=x.name, aliases=x.aliases, description=desc,
                                       created_at=now(), found_in=found_in, found_ep=n))
    return [x.name for x in places]


def unregister_places(p: Project, n: int) -> list[str]:
    """n화 뒤 반영이 본문에서 등록한 장소를 뺀다. 작가가 시점이나 관련 인물을 더한 장소와,
    아직 안 쓴 화 플롯에 나오는 장소는 남기고 '플롯에서 나옴'으로 돌린다. 뺀 이름을 돌려준다."""
    later = [e for e in p.episodes if not e.text]
    gone, keep = [], []
    for el in p.elements:
        if el.found_in != "본문" or el.found_ep <= n:
            keep.append(el)
            continue
        plots = [e.plot.number for e in later if any(t in plot_text(e) for t in terms(el))]
        if plots or not short(el):
            el.found_in, el.found_ep = ("플롯", min(plots)) if plots else (el.found_in, el.found_ep)
            keep.append(el)
        else:
            gone.append(el.name)
    p.elements = keep
    return gone


def sync_place_candidates(p: Project) -> None:
    """등록됐거나 이제 어느 화 플롯에도 나오지 않는 장소 후보는 지운다 (인물 후보와 같은 규칙)."""
    have = known_names(p)
    plots = "\n".join(plot_text(e) for e in p.episodes)
    out, seen = [], set()
    for x in p.place_candidates:
        k = naming.place_key(x.name)
        if k not in have and k not in seen and mentioned(x, plots):
            out.append(x)
            seen.add(k)
    p.place_candidates = out


def add_place_candidates(p: Project, places: list[NewPlace], plots_text: str) -> None:
    """AI 플롯이 지은 새 장소를 후보로 둔다. 고른 플롯에 나오지 않거나 이미 후보인 장소는 뺀다."""
    places, _ = clean_places(p, places, plots_text)
    have = {naming.place_key(x.name) for x in p.place_candidates}
    p.place_candidates += [x for x in places if naming.place_key(x.name) not in have]
    sync_place_candidates(p)


def register_place_candidates(p: Project, n: int) -> list[str]:
    """n화 플롯에 나오는 장소 후보를 등록한다 (화 확정 때). 등록한 이름을 돌려준다."""
    text = plot_text(p.episode(n))
    done = add_places(p, [x for x in p.place_candidates if mentioned(x, text)], n, "플롯")
    sync_place_candidates(p)
    return done


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
