"""프롬프트 크기 관리: 블록 재기, 장편 블록 예산, 관련 자료 고르기, 옛 본문 단락 찾기. LLM 을 부르지 않는다.

장편은 화가 쌓일수록 사실 · 상태 · 비밀 · 줄거리가 늘어난다. 입력이 길어지면 필요한 정보를 다 넣어도 품질이 떨어지고,
같은 인물에 대한 비슷한 문장이 서로 방해물이 된다 (장편 입력 토큰 진단, 2026-10). 그래서 장편 프롬프트는
블록마다 글자 예산(BUDGET)을 두고, 넘치면 이번 화와 덜 관련된 것부터 뺀 뒤 몇 개를 뺐는지 적는다.
저장된 데이터는 그대로 두고 프롬프트에 넣는 보기만 고른다. 단편(form="short") 경로는 쓰지 않는다.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

from . import elements
from .schema import Character, Foreshadow, Project, Secret

CHARS_PER_TOKEN = 1.7  # 토크나이저가 없을 때 한국어 추정값 (gemma 실측 1.6~1.9)

# 장편 블록 예산 (글자). 넘치면 우선순위가 낮은 것부터 뺀다.
BUDGET = {
    "facts": 3_500,         # 본문 쓰기 · 부분 수정의 확정 사실
    "story_past": 6_000,    # 끝난 부와 아크의 접은 줄거리
    "story_arc": 6_000,     # 이번 아크의 화별 요약
    "check_facts": 6_000,   # 검수의 확정 사실
    "check_recall": 24_000,  # 검수: 옛 화에서 찾아 넣는 단락
    "impact_facts": 8_000,  # 인과율 영향 분석의 확정 사실
    "impact_text": 90_000,  # 인과율 영향 분석: 이미 쓴 본문
    "secrets": 2_500,       # 본문 쓰기의 관계 블록에 붙는 숨긴 비밀
    "state_secrets": 6_000,  # 상태 변경안 · 검수의 비밀 목록
    "places": 3_000,        # 기획 · 검수 · 상태 변경안에 넣는 본문 · 플롯에서 나온 장소
}
FACTS_RECENT = 30  # 최근 사실은 예산과 상관없이 넣는다
CHECK_RECENT = 3  # 검수에 원문 그대로 넣는 직전 화 수
FORESHADOW_CAP = 25  # 본문 쓰기에 넣는 열린 복선 수
PLAN_FORESHADOW_CAP = 60  # 다음 아크 기획에 넣는 열린 복선 수


def est_tokens(text: str) -> int:
    return round(len(text) / CHARS_PER_TOKEN)


# ---------- 블록 재기 ----------

_HEAD = re.compile(r"^(#{1,3} [^\n]{1,60}|\[[^\]\n]{1,40}\][^\n]{0,40})$", re.M)
_HEAD_TAIL = re.compile(r"[\s(:]*$")


def _label(head: str) -> str:
    """머리글을 기록용 이름으로: 기호와 괄호 설명을 뗀다."""
    h = head.strip().lstrip("#").strip()
    if h.startswith("["):
        h = h[1:h.index("]")] if "]" in h else h[1:]
    h = re.sub(r"\s*\(.*$", "", h)
    h = re.sub(r"\d+화", "N화", h)
    return _HEAD_TAIL.sub("", h)[:24] or "(머리)"


def blocks(text: str, top: int = 12) -> list[list]:
    """프롬프트를 머리글('# ...', '[...]')로 나눠 블록별 글자 수. 큰 것부터 top 개, 나머지는 '그 밖' 하나로."""
    sizes: Counter = Counter()
    last, name = 0, "(머리)"
    for m in _HEAD.finditer(text):
        sizes[name] += m.start() - last
        name, last = _label(m.group(1)), m.start()
    sizes[name] += len(text) - last
    rows = [[k, v] for k, v in sizes.most_common() if v > 0]
    if len(rows) > top:
        rest = sum(v for _, v in rows[top - 1:])
        rows = rows[:top - 1] + [["그 밖", rest]]
    return rows


# ---------- 글 조각 ----------

_HANGUL = re.compile(r"[가-힣]+")


def grams(text: str) -> set[str]:
    """띄어쓰기를 무시한 한글 3글자 조각. 조사와 띄어쓰기가 달라도 같은 말을 찾는다."""
    s = "".join(_HANGUL.findall(text))
    return {s[i:i + 3] for i in range(len(s) - 2)}


def first_sentence(text: str, limit: int = 90) -> str:
    t = " ".join(text.split())
    m = re.search(r"(.+?[.!?。])(\s|$)", t)
    s = m.group(1) if m else t
    return s if len(s) <= limit else s[:limit - 1] + "…"


# ---------- 확정 사실 ----------

def names_of(p: Project, ids: Iterable[str]) -> tuple[list[str], list[str]]:
    """(주역 이름, 그 밖 인물 이름)."""
    ids = set(ids)
    main = [c.name for c in p.characters if c.id in ids and c.tier == "main" and c.name]
    other = [c.name for c in p.characters if c.id in ids and c.tier != "main" and c.name]
    return main, other


def query_terms(p: Project, n: int) -> list[str]:
    """n화와 관련된 고유한 말: 이번 화에 걸린 이야기 요소의 이름과 별칭, 플롯에 나온 장소."""
    try:
        e = p.episode(n)
    except KeyError:
        return []
    plot = elements.plot_text(e)
    out = [t for el in elements.for_episode(p, n) for t in elements.terms(el)]
    out += [loc for loc in p.world.locations if loc and loc in plot + e.text]
    return list(dict.fromkeys(out))


def pick_places(p: Project, text: str, budget: int) -> tuple[list[str], int]:
    """이미 있는 장소 이름을 예산(글자)만큼. text 에 나오는 이름 먼저, 그다음 설정 장소 칸, 최근에 처음 나온 곳. (이름들, 뺀 수)"""
    from . import naming

    names = naming.known_places(p)
    found = {t: el.found_ep for el in p.elements if el.kind == "장소" for t in [el.name, *el.aliases]}
    ranked = sorted(names, key=lambda x: (x not in text, found.get(x, 0) > 0, -found.get(x, 0)))
    out, used = [], 0
    for x in ranked:
        if used + len(x) + 2 <= budget:
            out.append(x)
            used += len(x) + 2
    return out, len(names) - len(out)


def pick_facts(p: Project, ids: set[str], query: str, budget: int, terms: Iterable[str] = ()) -> tuple[list[str], int]:
    """확정 사실을 이번 화와 관련된 순서로 예산만큼. 최근 FACTS_RECENT 개는 늘 넣는다.
    관련: 조연 · 단역 이름(3) > 이야기 요소 · 장소(2) > 주역 이름(1), 같으면 query 와 겹치는 글 조각이 많은 것, 그다음 최근 것.
    아무것도 겹치지 않는 옛 사실은 넣지 않는다. 고른 사실은 원래 순서로 돌려준다."""
    facts = p.facts
    main, other = names_of(p, ids)
    terms = [t for t in terms if t]
    q = grams(query)
    recent = set(range(max(0, len(facts) - FACTS_RECENT), len(facts)))
    scored = []
    for i, f in enumerate(facts):
        if i in recent:
            continue
        s = 3 * any(nm in f for nm in other) + 2 * any(t in f for t in terms) + any(nm in f for nm in main)
        if not s:
            continue
        g = grams(f)
        overlap = len(g & q) / (len(g) or 1)
        scored.append((s, overlap, i))
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    keep = set(recent)
    used = sum(len(facts[i]) + 3 for i in recent)
    for _, _, i in scored:
        cost = len(facts[i]) + 3
        if used + cost > budget:
            continue
        keep.add(i)
        used += cost
    return [facts[i] for i in sorted(keep)], len(facts) - len(keep)


# ---------- 복선 ----------

def foreshadow_rank(p: Project, f: Foreshadow, n: int) -> int:
    """작을수록 먼저. 회수 예정이 지남 > 이번 아크에서 회수 > 이번 아크 안에 회수 예정 > 작품 단위 > 부 단위 > 이번 아크에 심음 > 그 밖 최근."""
    arc = p.arc_for(n)
    end = arc.end_ep if arc else n
    if f.due_ep is not None and f.due_ep <= n:
        return 0
    if arc is not None and f.id in arc.payoffs:
        return 1
    if f.due_ep is not None and f.due_ep <= end:
        return 2
    if f.scope == "series":
        return 3
    if f.scope == "part":
        return 4
    if arc is not None and f.planted_ep >= arc.start_ep:
        return 5
    return 6


def rank_foreshadows(p: Project, fs: list[Foreshadow], n: int, cap: int) -> list[Foreshadow]:
    """순위대로 cap 개를 고르고 심은 순서로 돌려준다. 같은 순위면 작품 · 부 단위는 오래된 것, 나머지는 최근 것이 먼저.
    예전처럼 뒤에서 자르면 끝까지 갈 오래된 큰 떡밥이 먼저 빠진다."""
    def key(f: Foreshadow) -> tuple:
        r = foreshadow_rank(p, f, n)
        return (r, f.planted_ep if r in (3, 4) else -f.planted_ep)
    picked = sorted(fs, key=key)[:cap]
    return sorted(picked, key=lambda f: f.planted_ep)


# ---------- 비밀, 관계 볼 인물 ----------

def open_secrets(p: Project, ids: set[str] | None = None) -> list[Secret]:
    """아직 누군가 모르는 비밀. ids 를 주면 그 인물이 갖고 있거나 그 인물이 모르는 것만."""
    return [s for s in p.secrets if s.hidden_from
            and (ids is None or s.owner in ids or set(s.hidden_from) & ids)]


def pick_secrets(p: Project, ids: set[str], query: str, budget: int) -> tuple[list[Secret], int]:
    """open_secrets(ids) 중 이번 화와 관련된 순서로 예산만큼. (고른 것, 뺀 수)
    관련: query 와 겹치는 글 조각 비율, 조연 · 단역이 얽힘, 무게, 같으면 나중에 생긴 것. 고른 것은 원래 순서로."""
    cand = open_secrets(p, ids)
    main = {c.id for c in p.characters if c.tier == "main"}
    q = grams(query)

    def score(i: int, s: Secret) -> tuple:
        g = grams(s.content)
        overlap = len(g & q) / (len(g) or 1)
        side = bool(({s.owner} | set(s.hidden_from)) & ids - main)
        return (-(3 * overlap + side + s.weight), -i)

    order = sorted(range(len(cand)), key=lambda i: score(i, cand[i]))
    keep, used = set(), 0
    for i in order:
        cost = len(cand[i].content) + 60
        if used + cost > budget:
            continue
        keep.add(i)
        used += cost
    return [cand[i] for i in sorted(keep)], len(cand) - len(keep)


PLAN_RECENT = 20  # 기획 프롬프트: 최근 몇 화 플롯에 나온 인물까지 관계를 본다


def planning_cast(p: Project, n: int) -> set[str]:
    """기획 프롬프트에서 관계를 볼 인물: 주역, 직전 아크와 지금 아크의 주요 인물, 최근 PLAN_RECENT 화와 이후 플롯에 나온 인물.
    조연을 다 넣으면 300화쯤에 관계 블록만 2만 자가 넘는다."""
    ids = {c.id for c in p.characters if c.tier == "main"}
    arcs = sorted((a for a in p.story_arcs if a.start_ep < n + 30), key=lambda a: a.start_ep)[-2:]
    for a in arcs:
        ids |= set(a.cast)
    for e in p.episodes:
        if e.plot.number >= n - PLAN_RECENT:
            ids |= set(e.plot.characters)
    return ids


def episode_cast(p: Project, n: int) -> set[str]:
    """이번 화 등장 인물과 주역."""
    try:
        cast = set(p.episode(n).plot.characters)
    except KeyError:
        cast = set()
    return cast | {c.id for c in p.characters if c.tier == "main"}


# ---------- 옛 본문 단락 찾기 ----------

PARA_MAX = 700  # 단락 하나의 최대 글자. 넘으면 문장 경계에서 나눈다
COMMON = 0.3  # 이보다 많은 단락에 나오는 조각은 흔한 말로 보고 셈에서 뺀다


def _paragraphs(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        while len(para) > PARA_MAX:
            cut = max(para.rfind(".", 0, PARA_MAX), para.rfind("\n", 0, PARA_MAX))
            cut = cut + 1 if cut > PARA_MAX // 3 else PARA_MAX
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            out.append(para)
    return out


class PassageIndex:
    """n화 앞 본문(skip 화 제외)의 단락과 글 조각 빈도. 질문 여러 개를 같은 색인으로 찾을 때(두 걸음 검수) 한 번만 만든다."""

    def __init__(self, p: Project, n: int, skip: set[int] = frozenset()):
        self.paras: list[tuple[int, int, str, set[str]]] = []
        for e in sorted(p.episodes, key=lambda e: e.plot.number):
            m = e.plot.number
            if m >= n or m in skip or not e.text:
                continue
            for k, para in enumerate(_paragraphs(e.text)):
                self.paras.append((m, k, para, grams(para)))
        self.df: Counter = Counter()
        for *_, g in self.paras:
            self.df.update(g)

    def find(self, query: str, budget: int, terms: Iterable[str] = ()) -> list[tuple[int, list[str]]]:
        """query 와 겹치는 단락을 예산만큼. [(화, [단락...])] 화 순서.
        점수는 겹치는 글 조각의 희소도(idf) 합을 단락 길이로 누른 값, terms(조연 이름, 이야기 요소, 장소)가 있으면 더 준다."""
        if not self.paras or budget <= 0:
            return []
        df, total = self.df, len(self.paras)
        q = {g for g in grams(query) if df[g] and df[g] <= COMMON * total}
        idf = {g: math.log(1 + total / df[g]) for g in q}
        terms = [t for t in terms if t]
        scored = []
        for m, k, para, g in self.paras:
            s = sum(idf[x] for x in g & q) / math.sqrt(1 + len(g) / 120)
            s += sum(4.0 for t in terms if t in para)
            if s > 0:
                scored.append((s, m, k, para))
        scored.sort(key=lambda x: -x[0])
        picked: dict[int, list[tuple[int, str]]] = {}
        used = 0
        for s, m, k, para in scored:
            if used + len(para) > budget:
                continue
            picked.setdefault(m, []).append((k, para))
            used += len(para)
        return [(m, [para for _, para in sorted(picked[m])]) for m in sorted(picked)]


def recall(p: Project, n: int, query: str, budget: int, skip: set[int], terms: Iterable[str] = ()) -> list[tuple[int, list[str]]]:
    """n화 앞의 본문(skip 화 제외)에서 query 와 겹치는 단락을 예산만큼 찾는다. [(화, [단락...])] 화 순서."""
    return PassageIndex(p, n, skip).find(query, budget, terms)


_COUNT = re.compile(r"\d|하루|이틀|사흘|나흘|닷새|엿새|이레|열흘|보름|일주일|[한두세네]\s?달|"
                    r"(?:[한두세네]|다섯|여섯|일곱|여덟|아홉|열|스물|서른|마흔|쉰|예순|일흔|여든|아흔)\s?(?:살|해|명|번|시간)")


def has_count(text: str) -> bool:
    """기간 · 나이 · 인원 · 횟수 같은 셈이 들어 있는지. '사흘'과 '일주일'처럼 글 조각은 안 겹쳐도 같은 거리를 묻는 문장을 잇는다."""
    return bool(_COUNT.search(text))


def related_lines(lines: list[str], query: str, budget: int) -> list[str]:
    """query 와 글 조각이 많이 겹치는 줄을 예산만큼, 원래 순서로. 겹치는 것이 없으면 넣지 않는다.
    query 에 셈(기간, 나이, 인원)이 있으면 셈이 있는 줄을 한 조각 더 겹친 것으로 본다."""
    q, count = grams(query), has_count(query)
    scored = []
    for i, line in enumerate(lines):
        g = grams(line)
        hit = len(g & q)
        if hit:
            hit += count and has_count(line)
            scored.append((hit / math.sqrt(len(g) or 1), i))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    keep, used = [], 0
    for _, i in scored:
        cost = len(lines[i]) + 3
        if used + cost <= budget:
            keep.append(i)
            used += cost
    return [lines[i] for i in sorted(keep)]


def related_facts(p: Project, query: str, budget: int) -> list[str]:
    """query 와 겹치는 확정 사실 (related_lines)."""
    return related_lines(p.facts, query, budget)


def characters_by_ids(p: Project, ids: set[str]) -> list[Character]:
    return [c for c in p.characters if c.id in ids]
