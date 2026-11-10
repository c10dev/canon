"""다른 이름 채우기 (docs/context/specs/04-key-suggest.md): 인물 · 이야기 요소가 본문에서 불리는 다른 이름을 AI 가 제안하고 작가가 고른다.

- targets 가 작업이 받을 항목을 고른다. 열쇠는 'c:<인물 id>' · 'e:<요소 id>' 다. 'c:' · 'e:' · 빈 글은 다른 이름이 빈 항목을 ALIAS_BATCH 개까지.
- material 이 항목마다 재료 단락을 고른다: 쓴 화 본문에서 이름 · 다른 이름이 맞은 단락과 그 앞뒤를 최근 화부터 ALIAS_SAMPLE 자까지.
  이름이 본문에 없는 요소는 context.recall 로 설명과 겹치는 단락을 찾는다.
- clean 이 AI 제안을 정리하고(근거 단락에 글자로 없는 말 등을 뺀다) hits 가 최근 쓴 화에서 찾히는 화 수와 겹치는 항목을 센다.
- 맞춤 판정은 context.name_pattern(인물) · elements.terms(요소)를 그대로 쓴다. 여기서 판정을 따로 만들지 않는다.
LLM 을 부르지 않는다 (호출은 pipeline.suggest_aliases). 저장하지 않는다: 작가가 고른 말을 칸에 넣고 작품 저장으로 저장한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import context, elements, metrics
from .schema import AliasHit, AliasIdea, AliasSuggestion, Character, Episode, Project, StoryElement

ALIAS_BATCH = 10  # 한 번 부를 때 항목 수. 근거 없는 처음 값 (실호출 응답 크기를 보고 고친다)
ALIAS_SAMPLE = 3000  # 항목 하나의 재료 단락 글자 예산. 근거 없는 처음 값
ALIAS_MAX_LEN = 12  # 다른 이름 하나의 최대 글자 수. 근거 없는 처음 값
ALIAS_HIT_EPS = 30  # 화 수 세기가 보는 최근 쓴 화 수. 근거 없는 처음 값
ALIAS_MIN_LEN = 2  # 한 글자 말은 받지 않는다 (elements.terms 와 같은 규칙)
QUOTES = "\"'“”‘’「」『』《》〈〉«»`"


@dataclass
class Item:
    """제안을 받을 항목 하나. passages · cut 은 material 이 채운다."""
    key: str
    name: str
    aliases: list[str]
    line: str
    calls: list[str] = field(default_factory=list)
    passages: list[tuple[int, str]] = field(default_factory=list)
    cut: int = 0

    @property
    def text(self) -> str:
        return "\n".join(para for _, para in self.passages)


def _char(p: Project, cid: str) -> Character | None:
    return next((c for c in p.characters if c.id == cid), None)


def _el(p: Project, eid: str) -> StoryElement | None:
    return next((x for x in p.elements if x.id == eid), None)


def find(p: Project, key: str) -> Character | StoryElement | None:
    kind, _, oid = key.partition(":")
    if kind == "c":
        return _char(p, oid)
    if kind == "e":
        return _el(p, oid)
    return None


def _calls(p: Project, cid: str) -> list[str]:
    """그 인물을 부르는 호칭 (Project.address_forms 에서 listener 가 그 인물인 줄). AI 가 고를 씨앗으로만 쓴다."""
    out: list[str] = []
    for a in p.address_forms:
        x = a.calls.strip()
        if a.listener == cid and x and x not in out:
            out.append(x)
    return out


def item(p: Project, key: str) -> Item | None:
    o = find(p, key)
    if isinstance(o, Character):
        line = " / ".join(x for x in (o.name, o.role, o.personality.strip()[:80]) if x)
        return Item(key=key, name=o.name, aliases=list(o.aliases), line=line, calls=_calls(p, o.id))
    if isinstance(o, StoryElement):
        return Item(key=key, name=o.name, aliases=list(o.aliases), line=elements.describe(p, o).splitlines()[0])
    return None


def targets(p: Project, target: str = "") -> list[Item]:
    """작업이 받을 항목. 'c:<id>' · 'e:<id>' 는 그 항목 하나, 'c:' · 'e:' · 빈 글은 다른 이름이 빈 항목을 ALIAS_BATCH 개까지 (인물 먼저).
    이름이 빈 항목은 받지 않는다. 고를 항목이 없으면 KeyError · ValueError."""
    kind, _, oid = target.partition(":")
    if oid:
        it = item(p, target)
        if it is None:
            raise KeyError(f"항목이 없어요: {target}. 새로 더한 항목이면 저장한 뒤 다시 하세요")
        if not it.name.strip():
            raise ValueError("이름을 먼저 적어 주세요")
        return [it]
    keys = []
    if kind in ("", "c"):
        keys += [f"c:{c.id}" for c in p.characters if c.name.strip() and not c.aliases]
    if kind in ("", "e"):
        keys += [f"e:{x.id}" for x in p.elements if x.name.strip() and not x.aliases]
    if not keys:
        raise ValueError("다른 이름이 빈 항목이 없어요")
    return [it for k in keys[:ALIAS_BATCH] if (it := item(p, k))]


def written(p: Project) -> list[Episode]:
    """본문이 있는 쓴 화 (written · finalized), 화 순서."""
    return sorted((e for e in p.episodes if e.text.strip() and e.status in ("written", "finalized")), key=lambda e: e.plot.number)


def _matcher(o: Character | StoryElement):
    """이 항목이 글에 나오는지 보는 함수. 인물은 context.name_pattern, 요소는 elements.terms (부분 문자열)."""
    if isinstance(o, Character):
        pat = context.name_pattern(o)
        return (lambda t: bool(pat.search(t))) if pat else (lambda t: False)
    terms = elements.terms(o)
    return lambda t: any(x in t for x in terms)


def _alias_matcher(o: Character | StoryElement, alias: str):
    """제안한 다른 이름 하나만으로 찾는 함수. 인물은 이름 없이 그 말만 넣은 사본의 name_pattern 이다 (같은 꼴 규칙)."""
    if isinstance(o, Character):
        return _matcher(o.model_copy(update={"name": "", "aliases": [alias]}))
    return _matcher(StoryElement(id="", name=alias))


def material(p: Project, it: Item) -> tuple[list[tuple[int, str]], int]:
    """재료 단락 [(화, 단락)] 화 순서와, 예산을 넘어 뺀 맞은 단락 수. it.passages · it.cut 에도 넣는다."""
    o = find(p, it.key)
    if o is None:
        return [], 0
    hit = _matcher(o)
    picked: list[tuple[int, int, str]] = []
    used, cut = 0, 0
    for e in reversed(written(p)):
        paras = context._paragraphs(e.text)
        want: list[int] = []
        for k, para in enumerate(paras):
            if hit(para):
                want += [i for i in (k - 1, k, k + 1) if 0 <= i < len(paras) and i not in want]
        for k in sorted(want):
            if any(m == e.plot.number and j == k for m, j, _ in picked):
                continue
            if used + len(paras[k]) > ALIAS_SAMPLE:
                cut += hit(paras[k])
                continue
            picked.append((e.plot.number, k, paras[k]))
            used += len(paras[k])
    if not picked and isinstance(o, StoryElement) and (eps := written(p)):
        done = {e.plot.number for e in eps}
        skip = {e.plot.number for e in p.episodes if e.text and e.plot.number not in done}
        found = context.recall(p, eps[-1].plot.number + 1, f"{o.name}\n{o.description}", ALIAS_SAMPLE, skip)
        picked = [(m, k, para) for m, paras in found for k, para in enumerate(paras)]
    picked.sort(key=lambda x: (x[0], x[1]))
    it.passages, it.cut = [(m, para) for m, _, para in picked], cut
    return it.passages, cut


def _norm(s: str) -> str:
    return s.strip().strip(QUOTES).strip()


def _own_forms(o: Character | StoryElement) -> set[str]:
    """그 항목의 이름 꼴과 이미 있는 다른 이름. 인물은 metrics.name_forms(성 뗀 이름)를 함께 넣는다."""
    if isinstance(o, Character):  # context.name_pattern 이 찾는 꼴과 같게: 성 뗀 이름, 띄어 쓴 이름의 첫 낱말(2자 이상)
        words = o.name.split()
        first = [words[0]] if len(words) > 1 and len(words[0]) >= 2 else []
        return {*metrics.name_forms(o.name), *first, *(a.strip() for a in o.aliases)}
    return {o.name.strip(), *(a.strip() for a in o.aliases)}


def _covered(o: Character | StoryElement, own: set[str], a: str) -> bool:
    """a 가 이름 · 다른 이름으로 이미 찾히는 말인가. 인물은 name_pattern 처럼 두 글자 이상 꼴로 시작하면('경수 씨' · '하린이'),
    요소는 elements.terms 처럼 두 글자 이상 꼴을 품으면 그 꼴이 먼저 맞는다. 찾는 범위가 늘지 않아 칩으로 내지 않는다
    (2026-11-10 실호출: 인물 제안 대부분이 이름 + 호칭 · 조사였고 이름 없이 찾은 화가 0 이었다)."""
    forms = [f for f in own if len(f) >= ALIAS_MIN_LEN]
    if isinstance(o, Character):
        return any(a.startswith(f) for f in forms)
    return any(f in a for f in forms)


def clean(p: Project, s: AliasSuggestion, material_text: dict[str, str] | None = None) -> AliasSuggestion:
    """AI 제안을 정리한다 (LLM 없음). material_text 는 항목 열쇠 → 재료 단락 글. 주지 않으면 지금 작품으로 다시 고른다.
    뺀다: 두 글자보다 짧은 말, ALIAS_MAX_LEN 자를 넘는 말, 그 항목의 이름 · 이미 있는 다른 이름과 같은 말, 항목 안에서 겹치는 말,
    이름 · 다른 이름을 품어 이미 찾히는 말('경수 씨' · '하린이'), 재료 단락에 글자로 없는 말, 없는(요청하지 않은) 항목을 가리키는 제안. 조사는 떼지 않는다. 뺀 수는 notices 에 적는다."""
    if material_text is None:
        material_text = {}
        for x in s.items:
            it = item(p, x.target.strip())
            if it is not None:
                material(p, it)
                material_text[it.key] = it.text
    merged: dict[str, list] = {}
    reasons: dict[str, str] = {}
    missing = short = same = nobasis = covered = 0
    for x in s.items:
        key = x.target.strip()
        o = find(p, key)
        if o is None or key not in material_text:
            missing += 1
            continue
        own, out = _own_forms(o), merged.setdefault(key, [])
        for a in x.aliases:
            a = _norm(a)
            if len(a) < ALIAS_MIN_LEN or len(a) > ALIAS_MAX_LEN:
                short += 1
            elif a in own or a in out:
                same += 1
            elif _covered(o, own, a):
                covered += 1
            elif a not in material_text[key]:
                nobasis += 1
            else:
                out.append(a)
        if x.reason.strip() and not reasons.get(key):
            reasons[key] = x.reason.strip()
    items = [AliasIdea(target=k, aliases=v, reason=reasons.get(k, "")) for k, v in merged.items() if v]
    notes = list(s.notices)
    if nobasis:
        notes.append(f"근거가 없어 뺀 말이 {nobasis}개 있어요")
    if same:
        notes.append(f"이름이나 이미 있는 다른 이름과 같아 뺀 말이 {same}개 있어요")
    if covered:
        notes.append(f"이름을 품고 있어 이름으로 이미 찾히는 말 {covered}개는 뺐어요")
    if short:
        notes.append(f"두 글자보다 짧거나 {ALIAS_MAX_LEN}자를 넘어 뺀 말이 {short}개 있어요")
    if missing:
        notes.append(f"목록에 없는 항목을 가리킨 제안 {missing}개는 뺐어요")
    return AliasSuggestion(items=items, notices=notes)


def _names(o: Character | StoryElement) -> list[str]:
    """겹침을 볼 이름 꼴: 두 글자 이상인 이름 꼴과 다른 이름."""
    return [x for x in _own_forms(o) if len(x) >= ALIAS_MIN_LEN]


def clash(p: Project, key: str, alias: str) -> str:
    """alias 가 다른 항목의 이름 · 다른 이름과 같거나 서로 품으면 그 항목 이름. 없으면 빈 글."""
    for o in [*p.characters, *p.elements]:
        k = f"{'c' if isinstance(o, Character) else 'e'}:{o.id}"
        if k == key:
            continue
        if any(alias in x or x in alias for x in _names(o)):
            return o.name or o.id
    return ""


def hits(p: Project, s: AliasSuggestion) -> AliasSuggestion:
    """제안한 다른 이름마다 최근 ALIAS_HIT_EPS 개 쓴 화에서 찾히는 화, 이름 · 지금 다른 이름으로는 안 찾히는 화, 겹치는 항목을 센다.
    LLM 을 부르지 않는다. s 를 고쳐 돌려준다."""
    recent = written(p)[-ALIAS_HIT_EPS:]
    s.recent = len(recent)
    for x in s.items:
        o = find(p, x.target)
        if o is None:
            x.hits = []
            continue
        now = _matcher(o)
        found = {e.plot.number for e in recent if now(e.text)}
        out = []
        for a in x.aliases:
            m = _alias_matcher(o, a)
            eps = [e.plot.number for e in recent if m(e.text)]
            out.append(AliasHit(alias=a, episodes=eps, only=[n for n in eps if n not in found], clash=clash(p, x.target, a)))
        x.hits = out
    return s
