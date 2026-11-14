"""설계도: 작가가 먼저 정하는 계획 층 (관계 이정표 · 접촉 사다리 · 능력 일정). 설계 문서는 docs/blueprint/.

여기는 데이터 규칙만 둔다: 빈 id 채우기, 저장 검사, 계획 칸, 화 번호 옮기기.
LLM 을 부르지 않는다. 계획값이라 관계 수치(Tie)나 플롯을 바꾸지 않는다.
"""
from __future__ import annotations

import re
from typing import Callable, Iterator, NamedTuple, Optional

from . import abilities, dynamics, logline, statwin
from .schema import Ability, AbilityPlan, ContactLadder, ContactReach, ContactRung, Milestone, Project, StateDelta

Ranged = Milestone | ContactRung | AbilityPlan


def char_names(p: Project) -> dict[str, str]:
    """인물 id → 보이는 이름 (이름이 비면 id). 경고 · 프롬프트 줄이 같이 쓴다."""
    return {c.id: c.name or c.id for c in p.characters}


def last_done(p: Project) -> int:
    """마지막으로 반영(finalized)한 화. 없으면 0. 경고 · 능력 실제 대조 · 설계도 보기 API 가 같이 쓴다."""
    return max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)


def _ranged(p: Project) -> Iterator[Ranged]:
    yield from p.blueprint.milestones
    for lad in p.blueprint.ladders:
        yield from lad.rungs
    yield from p.blueprint.ability_plans


def fill_ids(p: Project) -> None:
    """빈 id 를 채운다. 있는 id 는 바꾸지 않는다 (이정표 ms-<k>, 사다리 칸 cr-<k>, 능력 일정 ap-<k>)."""
    have = {x.id for x in _ranged(p) if x.id}

    def mint(prefix: str) -> str:
        k = 1
        while f"{prefix}-{k}" in have:
            k += 1
        have.add(f"{prefix}-{k}")
        return f"{prefix}-{k}"
    for m in p.blueprint.milestones:
        m.id = m.id.strip() or mint("ms")
    for lad in p.blueprint.ladders:
        for r in lad.rungs:
            r.id = r.id.strip() or mint("cr")
    for x in p.blueprint.ability_plans:
        x.id = x.id.strip() or mint("ap")


def _range_error(x: Ranged, what: str) -> Optional[str]:
    if (x.from_ep > 0) != (x.to_ep > 0):
        return f"{what}의 화 범위가 한쪽만 적혀 있어요. 처음 화와 끝 화를 함께 적거나 둘 다 비우세요"
    if x.from_ep < 0 or x.to_ep < 0:
        return f"{what}의 화 번호가 0보다 작아요"
    if x.to_ep < x.from_ep:
        return f"{what}의 끝 화({x.to_ep}화)가 처음 화({x.from_ep}화)보다 앞이에요"
    return None


def _broken(p: Project) -> set[tuple[str, str]]:
    """없는 인물 · 장소를 가리키는 참조 (종류, id)."""
    chars = {c.id for c in p.characters}
    places = {el.id for el in p.elements if el.kind == "장소"}
    out = set()
    for m in p.blueprint.milestones:
        out |= {("인물", x) for x in (m.source, m.target) if x not in chars}
    for lad in p.blueprint.ladders:
        out |= {("인물", x) for x in (lad.a, lad.b) if x not in chars}
        for r in lad.rungs:
            out |= {("장소", x) for x in r.places if x not in places}
    out |= {("인물", x.character) for x in p.blueprint.ability_plans if x.character not in chars}
    return out


def check(p: Project, before: Project | None = None) -> None:
    """저장 검사 (화면 저장용). 모르는 값을 지우지 않고 ValueError 로 거절한다. 빈 id 는 먼저 채운다.
    before(디스크 것)에서 이미 끊겨 있던 인물 · 장소 참조는 막지 않는다 (다른 라우트가 지운 옛 데이터)."""
    from .stage import ACTS, PARTS  # stage 는 board · cast 를 불러 renumber 와 돌지 않게 늦게 부른다
    fill_ids(p)
    names = char_names(p)
    places = {el.id: el for el in p.elements}
    old = _broken(before) if before else set()

    def who(x: str) -> str:
        return names.get(x, x)

    ids = [x.id for x in _ranged(p)]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        raise ValueError(f"설계도 id가 겹쳐요: {', '.join(dup)}")
    for kind, x in sorted(_broken(p) - old):
        if kind == "인물":
            raise ValueError(f"설계도가 없는 인물({x})을 가리켜요. 인물 id를 되돌리거나 그 줄을 지우세요")
        el = places.get(x)
        why = f"'{el.name}'은 장소가 아니에요" if el else "없는 요소예요"
        raise ValueError(f"접촉 사다리의 장소 {x}: {why}. 인과율 '장소' 요소를 고르세요")
    for m in p.blueprint.milestones:
        what = f"관계 이정표 {who(m.source)} → {who(m.target)}"
        if m.source == m.target:
            raise ValueError(f"{what}가 같은 인물끼리예요")
        if err := _range_error(m, what):
            raise ValueError(err)
    seen: set[frozenset] = set()
    for lad in p.blueprint.ladders:
        pair = f"{who(lad.a)} ↔ {who(lad.b)}"
        if lad.a == lad.b:
            raise ValueError(f"접촉 사다리 {pair}가 같은 인물끼리예요")
        k = frozenset((lad.a, lad.b))
        if k in seen:
            raise ValueError(f"접촉 사다리 {pair}가 두 번 있어요. 하나로 합치세요")
        seen.add(k)
        last = 0
        for i, r in enumerate(lad.rungs, 1):
            what = f"접촉 사다리 {pair}의 {i}번째 칸({r.label or r.id})"
            if bad := [x for x in r.parts if x not in PARTS]:
                raise ValueError(f"{what}에 모르는 부위가 있어요: {', '.join(bad)}")
            if bad := [x for x in r.acts if x not in ACTS]:
                raise ValueError(f"{what}에 모르는 동작이 있어요: {', '.join(bad)}")
            if r.lead and r.lead not in (lad.a, lad.b):
                raise ValueError(f"{what}의 주도 인물({who(r.lead)})이 이 쌍에 없어요")
            if err := _range_error(r, what):
                raise ValueError(err)
            if r.from_ep:
                if r.from_ep < last:
                    raise ValueError(f"{what}의 처음 닿는 화({r.from_ep}화)가 앞 칸({last}화)보다 빨라요. 칸 차례를 바꾸거나 화를 고치세요")
                last = r.from_ep
    same: set[tuple[str, str, str, str]] = set()
    for x in p.blueprint.ability_plans:
        _tidy(x)
        if not x.ability:
            raise ValueError(f"성장 일정 {who(x.character)}의 능력 이름이 비었어요")
        what = f"성장 일정 {who(x.character)}의 {ability_text(x)}"
        if x.stat and not x.grade:
            raise ValueError(f"{what}: 상태창 수치 줄은 닿을 값을 적어 주세요")
        if err := _range_error(x, what):
            raise ValueError(err)
        k = _same_plan(x)
        if k in same:
            raise ValueError(f"{what}가 두 줄 있어요. 하나로 합치세요")
        same.add(k)


def ladder(p: Project, a: str, b: str) -> Optional[ContactLadder]:
    """a · b 쌍의 사다리 (차례 상관없음)."""
    return next((x for x in p.blueprint.ladders if {x.a, x.b} == {a, b}), None)


def planned_rung(lad: ContactLadder, n: int) -> Optional[ContactRung]:
    """n 화에 계획상 닿아 있는 가장 높은 칸: 처음 닿는 화가 있고 n 화 이하인 칸 가운데 차례가 가장 뒤인 칸."""
    return next((r for r in reversed(lad.rungs) if 0 < r.from_ep <= n), None)


BODY_LAYERS = ("옷 안", "맨살")  # 몸이 드러나는 겹 (docs/blueprint/specs/09-body.md)


def exposed(p: Project, n: int) -> set[str]:
    """n 화 플롯 인물끼리, 처음 닿는 화가 n 화 이하인 사다리 칸 가운데 옷 안 · 맨살 겹이 하나라도 있는 쌍의 두 인물 id.
    한 번 그 겹에 닿으면 뒤 칸이 옷 위여도 그 뒤 화까지 이어진다. 신체 프로필을 요청에 넣을지 고르는 재료다 (cast.body_cast)."""
    who = set(p.episode(n).plot.characters)
    out: set[str] = set()
    for lad in p.blueprint.ladders:
        if lad.a in who and lad.b in who and any(r.layer in BODY_LAYERS for r in lad.rungs if 0 < r.from_ep <= n):
            out |= {lad.a, lad.b}
    return out


def move(p: Project, f: Callable[[int], int], gone: int = 0) -> int:
    """화 끼워 넣기 · 빼기 (renumber.move_points). f 는 한 화 번호를 옮기는 함수, gone 은 빼는 화.
    범위의 끝 화가 빠지면 범위가 한 칸 준다. 범위가 그 한 화뿐이면 그 자리에 온 다음 화를 가리킨다. 고친 줄 수를 돌려준다."""
    changed = 0
    for x in _ranged(p):
        before = (x.from_ep, x.to_ep)
        lo, hi = f(x.from_ep) if x.from_ep else 0, f(x.to_ep) if x.to_ep else 0
        if gone and x.to_ep == gone and x.from_ep < gone:
            hi = gone - 1
        x.from_ep, x.to_ep = lo, max(hi, lo) if hi else hi
        changed += before != (x.from_ep, x.to_ep)
    return changed


def remap(p: Project, remap_one: Callable[[int], int]) -> list[str]:
    """재구성(reshape)의 화 지도로 옮긴다. 옮기지 못한 범위는 비우고(0) 그 줄을 알림 글로 돌려준다."""
    lost = []
    names = char_names(p)
    for x in _ranged(p):
        if not x.from_ep:
            continue
        lo, hi = remap_one(x.from_ep), remap_one(x.to_ep)
        if not lo or not hi:
            x.from_ep = x.to_ep = 0
            label = (f"관계 이정표 {names.get(x.source, x.source)} → {names.get(x.target, x.target)}" if isinstance(x, Milestone)
                     else f"성장 일정 {names.get(x.character, x.character)}의 {ability_text(x)}" if isinstance(x, AbilityPlan)
                     else f"접촉 사다리 칸 '{x.label or x.id}'")
            lost.append(label)
        else:
            x.from_ep, x.to_ep = lo, max(hi, lo)
    return [f"설계도의 {x} 화 범위를 새 화로 옮기지 못해 비웠어요" for x in lost]


def warning_rows(p: Project) -> list[tuple[str, str, str]]:
    """관계 이정표 경고 (막지 않음, docs/blueprint/specs/02-milestone-warn.md): (보는 인물 id, 보이는 인물 id, 글).
    단계와 화 범위를 모두 적은 이정표만 본다.
    이웃한 두 이정표 사이 칸이 모자람, 범위가 겹치는데 단계가 다름, 지금 단계에서 다음 이정표까지 칸이 모자람."""
    names = char_names(p)
    last = last_done(p)
    by_dir: dict[tuple[str, str], list[Milestone]] = {}
    for m in p.blueprint.milestones:
        if m.stage and m.from_ep > 0:
            by_dir.setdefault((m.source, m.target), []).append(m)
    out = []
    for (s, t), ms in by_dir.items():
        ms.sort(key=lambda m: (m.from_ep, m.to_ep))
        who = f"{names.get(s, s)} → {names.get(t, t)}"
        for x, y in zip(ms, ms[1:]):
            if y.from_ep <= x.to_ep and x.stage != y.stage:
                out.append((s, t, f"관계 이정표 {who}: {x.from_ep}~{x.to_ep}화({x.stage})와 {y.from_ep}~{y.to_ep}화({y.stage})의 범위가 겹쳐요."))
                continue
            need, room = dynamics.stage_steps(x.stage, (y.stage,)), y.to_ep - x.from_ep
            if need > room:
                out.append((s, t, f"관계 이정표 {who}: {x.stage}에서 {y.stage}까지 {need}칸인데 {x.from_ep}화부터 {y.to_ep}화까지 {room}화뿐이에요(한 화에 한 칸)."))
        tie = dynamics.find_tie(p.ties, s, t)
        nxt = next((m for m in ms if m.to_ep > last), None)
        if tie and nxt and tie.stage != nxt.stage:
            need, room = dynamics.stage_steps(tie.stage, (nxt.stage,)), nxt.to_ep - last
            if need > room:
                out.append((s, t, f"관계 이정표 {who}: 지금 {tie.stage}에서 {nxt.to_ep}화까지 {nxt.stage}에 닿으려면 {need}칸인데 {room}화 남았어요(한 화에 한 칸)."))
    return out


def warnings(p: Project) -> list[str]:
    """warning_rows 와 ability_warning_rows 의 글만."""
    return [w for _, _, w in warning_rows(p)] + [w for _, w in ability_warning_rows(p)]


def pair_key(a: str, b: str) -> str:
    """쌍 키: 두 인물 id 를 정렬해 '~' 로 잇는다 (화면 bpKey 와 같다)."""
    return "~".join(sorted((a, b)))


class First(NamedTuple):
    """처음 닿는 줄 (docs/blueprint/specs/11-whole.md 정할 것 4): 한 방향이 한 단계에, 한 쌍이 한 겹에 처음 닿는 이정표 · 사다리 칸.
    axis 는 '단계' 나 '겹'이다. 뒤에 인물 사다리 같은 축을 더할 수 있게 글로 둔다. who 는 단계면 (보는, 보이는), 겹이면 (a, b)."""
    pair: str
    axis: str
    value: str
    from_ep: int
    to_ep: int
    id: str
    who: tuple[str, str]


def firsts(milestones: list, ladders: list) -> list[First]:
    """처음 닿는 줄들. 화 범위와 단계(겹)를 모두 적은 줄만 센다. 같은 방향 · 같은 단계(같은 쌍 · 같은 겹)에서 첫 화가 가장 이른 줄이 처음이다.
    이정표는 방향마다 뽑는다(같은 쌍의 두 방향은 몰림이 아니다). 제안 줄과 이미 적은 줄을 섞어 넣을 수 있게 설계도가 아니라 목록을 받는다."""
    best: dict[tuple, First] = {}

    def keep(k: tuple, f: First) -> None:
        if k not in best or (f.from_ep, f.to_ep) < (best[k].from_ep, best[k].to_ep):
            best[k] = f
    for m in milestones:
        if m.stage and m.from_ep > 0 and m.source != m.target:
            keep(("단계", m.source, m.target, m.stage), First(pair_key(m.source, m.target), "단계", m.stage, m.from_ep, m.to_ep or m.from_ep, m.id, (m.source, m.target)))
    for lad in ladders:
        for r in lad.rungs:
            if r.layer and r.from_ep > 0:
                keep(("겹", pair_key(lad.a, lad.b), r.layer), First(pair_key(lad.a, lad.b), "겹", r.layer, r.from_ep, r.to_ep or r.from_ep, r.id, (lad.a, lad.b)))
    return sorted(best.values(), key=lambda f: (f.from_ep, f.to_ep, f.pair, f.axis, f.value))


def crowd_pairs(fs: list[First]) -> list[tuple[First, First]]:
    """몰린 두 줄: 서로 다른 쌍이 같은 축 · 같은 값에 처음 닿는 줄의 화 범위가 한 화라도 겹친다(끝 화가 같은 화도 겹침). 막지 않는다."""
    out = []
    for i, x in enumerate(fs):
        for y in fs[i + 1:]:
            if x.pair != y.pair and x.axis == y.axis and x.value == y.value and x.from_ep <= y.to_ep and y.from_ep <= x.to_ep:
                out.append((x, y))
    return out


def crowd_rows(p: Project, fs: list[First], keep: Callable[[First, First], bool] | None = None) -> list[tuple[str, str, str]]:
    """몰림 글 (두 쌍 키, 글). 제안 카드(11b)에만 쓴다. 늘 보이는 warning_rows 에는 넣지 않는다(작가가 일부러 둔 동시 장면이 있어서다).
    같은 두 쌍 · 같은 축 · 같은 값은 한 줄로 줄인다. keep 이 있으면 그 두 줄이 참인 몰림만 글로 쓴다."""
    names = char_names(p)

    def who(f: First) -> str:
        s, t = (names.get(x, x) for x in f.who)
        return f"{s} → {t}" if f.axis == "단계" else f"{s} ↔ {t}"
    out, seen = [], set()
    for x, y in crowd_pairs(fs):
        k = (*sorted((x.pair, y.pair)), x.axis, x.value)
        if k in seen or (keep and not keep(x, y)):
            continue
        seen.add(k)
        what = f"{x.value} 단계" if x.axis == "단계" else f"{x.value} 겹"
        out.append((x.pair, y.pair, f"{who(x)}({rng_text(x)})와 {who(y)}({rng_text(y)})가 같은 화 범위에 {what}에 처음 닿아요."))
    return out


def rung_text(p: Project, lad: ContactLadder, r: ContactRung) -> str:
    """사다리 칸 한 줄: '2. 손목 잡기 (맨살 · 오른 손목 · 잡다 · 신도림역 · 지훈 주도 · 메모)'. 부위 · 동작은 장면 연출의 이름으로."""
    from .stage import ACTS, PARTS
    names = char_names(p)
    places = {el.id: el.name for el in p.elements}
    bits = [r.layer, ", ".join(PARTS[x].label if x in PARTS else x for x in r.parts), ", ".join(ACTS[x].label if x in ACTS else x for x in r.acts),
            ", ".join(places.get(x, x) for x in r.places), f"{names.get(r.lead, r.lead)} 주도" if r.lead else "", r.note]
    detail = " · ".join(b for b in bits if b)
    return f"{lad.rungs.index(r) + 1}. {r.label or '이름 없는 칸'}" + (f" ({detail})" if detail else "")


def rng_text(x: Ranged) -> str:
    """화 범위 글: '5화' · '5~8화'. 프롬프트 줄(prompts)도 이 글을 쓴다."""
    return f"{x.from_ep}화" if x.from_ep == x.to_ep else f"{x.from_ep}~{x.to_ep}화"


def plan_lines(p: Project, ids: set[str] | None, start: int, end: int) -> list[str]:
    """기획 프롬프트의 설계도 줄 (docs/blueprint/specs/04-plan-prompt.md). 화 범위를 적은 줄만, start~end 에 걸친 것과 그 뒤 첫 것.
    ids 가 있으면 두 인물이 모두 ids 에 든 줄만. 이정표는 방향마다, 사다리는 쌍마다 지금 칸 · 이 범위에서 처음 닿는 칸 · 다음 칸."""
    names = char_names(p)

    def inside(a: str, b: str) -> bool:
        return ids is None or (a in ids and b in ids)
    out = []
    dirs: dict[tuple[str, str], list[Milestone]] = {}
    for m in p.blueprint.milestones:
        if m.from_ep > 0 and inside(m.source, m.target):
            dirs.setdefault((m.source, m.target), []).append(m)
    for (s, t), ms in dirs.items():
        ms.sort(key=lambda m: (m.from_ep, m.to_ep))
        who = f"{names.get(s, s)} → {names.get(t, t)}"
        here = [m for m in ms if m.from_ep <= end and m.to_ep >= start]
        after = next((m for m in ms if m.from_ep > end), None)
        for m in here + ([after] if after else []):
            what = " · ".join(x for x in (m.stage, m.label) if x) or "이정표"
            tail = f" (계기: {m.trigger})" if m.trigger else ""
            out.append(f"- {who} {rng_text(m)}{' (이 범위 뒤)' if m is after else ''}: {what}{tail}")
    for lad in p.blueprint.ladders:
        if not inside(lad.a, lad.b):
            continue
        who = f"{names.get(lad.a, lad.a)} ↔ {names.get(lad.b, lad.b)}"
        now = planned_rung(lad, start - 1)
        if now:
            out.append(f"- {who} 지금까지 닿은 칸: {rung_text(p, lad, now)}")
        for r in lad.rungs:
            if start <= r.from_ep <= end:
                out.append(f"- {who} {rng_text(r)}에 처음 닿는 칸: {rung_text(p, lad, r)}")
        nxt = next((r for r in lad.rungs if r.from_ep > end), None)
        if nxt:
            out.append(f"- {who} 다음 칸 (이 범위 뒤 {rng_text(nxt)}): {rung_text(p, lad, nxt)}")
    return out


# ---------- 지금 플롯에서 거꾸로 뽑기 (docs/blueprint/specs/05-extract.md) ----------

def extract_range(p: Project, arc: int) -> tuple[int, int]:
    """뽑을 화 범위. 장편은 아크 번호의 범위, 단편(또는 0)은 플롯이 있는 첫 화부터 마지막 화까지."""
    if p.serial and arc:
        a = next((x for x in p.story_arcs if x.number == arc), None)
        if a is None:
            raise ValueError(f"아크 {arc}가 없어요")
        return a.start_ep, a.end_ep
    eps = [e.plot.number for e in p.episodes]
    if not eps:
        raise ValueError("플롯이 있는 화가 없어요")
    return min(eps), max(eps)


def draft_range(p: Project, part: int) -> tuple[int, int]:
    """AI 로 짤 화 범위. 장편은 부 번호의 범위(부가 없으면 작품 전체), 단편 · 0 은 1화부터 작품 화수까지."""
    if p.serial and part:
        x = next((x for x in p.parts if x.number == part), None)
        if x is None:
            raise ValueError(f"{part}부가 없어요")
        return x.start_ep, x.end_ep
    return 1, max(p.meta.target_episodes, 1)


def _clip(x, start: int, end: int) -> bool:
    """제안 줄의 화 범위를 start~end 로 자른다. 범위 밖이면 False."""
    lo, hi = (x.from_ep or 0), (x.to_ep or x.from_ep or 0)
    if lo <= 0 or lo > end or hi < start:
        return False
    x.from_ep, x.to_ep = max(lo, start), min(max(hi, lo), end)
    return True


def clean_proposal(p: Project, prop, a: str, b: str, start: int, end: int):
    """AI 제안 정리 (BlueprintProposal): 두 인물 사이 줄만, 화 범위는 start~end 로 자르고, 모르는 부위 · 동작 · 장소 id 와 쌍 밖 주도 인물은 뺀다.
    근거는 범위 안 화만 세 개까지 남긴다. 이정표는 화 차례, 사다리 칸은 처음 닿는 화 차례로 놓는다. 작가 데이터가 아니라 AI 제안이라 지운다."""
    from .stage import ACTS, PARTS
    places = {el.id for el in p.elements if el.kind == "장소"}
    pair = {a, b}

    def ev(x) -> None:
        x.evidence = [e for e in x.evidence if start <= e.episode <= end and e.quote.strip()][:3]
    ms = []
    for m in prop.milestones:
        if {m.source, m.target} == pair and m.source != m.target and _clip(m, start, end):
            ev(m)
            ms.append(m)
    rungs = []
    for r in prop.rungs:
        if not _clip(r, start, end):
            continue
        r.parts = list(dict.fromkeys(x for x in r.parts if x in PARTS))
        r.acts = list(dict.fromkeys(x for x in r.acts if x in ACTS))
        r.places = list(dict.fromkeys(x for x in r.places if x in places))
        r.lead = r.lead if r.lead in pair else ""
        ev(r)
        rungs.append(r)
    prop.milestones = sorted(ms, key=lambda m: (m.from_ep, m.to_ep))
    prop.rungs = sorted(rungs, key=lambda r: (r.from_ep, r.to_ep))
    return prop


def add_picks(q: Project, a: str, b: str, milestones: list, rungs: list) -> None:
    """q 에 제안 줄을 검사 없이 더한다. 이정표는 뒤에 붙이고, 사다리 칸은 그 쌍 사다리에 처음 닿는 화 차례로 끼운다. 범위를 비운 칸은 자리를 지킨다."""
    for m in milestones:
        q.blueprint.milestones.append(Milestone(source=m.source, target=m.target, from_ep=m.from_ep, to_ep=m.to_ep,
                                                stage=m.stage, label=m.label, trigger=m.trigger))
    if rungs:
        lad = ladder(q, a, b)
        if lad is None:
            lad = ContactLadder(a=a, b=b)
            q.blueprint.ladders.append(lad)
        for r in rungs:
            new = ContactRung(label=r.label, parts=r.parts, acts=r.acts, layer=r.layer, places=r.places, lead=r.lead,
                              note=r.note, from_ep=r.from_ep, to_ep=r.to_ep)
            at = next((i for i, x in enumerate(lad.rungs) if x.from_ep > new.from_ep), len(lad.rungs))
            lad.rungs.insert(at, new)


def apply_picks(p: Project, a: str, b: str, milestones: list, rungs: list) -> None:
    """작가가 고른 제안 줄을 설계도에 더한다 (add_picks). 더한 뒤 check 로 검사해 어긋나면 ValueError 이고 아무것도 바꾸지 않는다."""
    q = p.model_copy(deep=True)
    add_picks(q, a, b, milestones, rungs)
    check(q, p)
    p.blueprint = q.blueprint


# ---------- 작품 전체 짜기 (docs/blueprint/specs/11-whole.md 의 11b) ----------

def whole_pairs(p: Project, picks: list[str] | None = None) -> list[tuple[str, str]]:
    """짤 쌍 (a, b). 기본은 관계 목록의 모든 쌍(관계의 차례와 a · b 차례)이다. picks(쌍 키 목록)가 있으면 그 쌍만 고른다.
    관계 목록에 없는 쌍도 두 인물이 있으면 받는다. 같은 쌍은 한 번만."""
    chars = {c.id for c in p.characters}
    order: list[tuple[str, str]] = []
    for r in p.relationships:
        if r.a in chars and r.b in chars and r.a != r.b and pair_key(r.a, r.b) not in {pair_key(*x) for x in order}:
            order.append((r.a, r.b))
    if not picks:
        return order
    out: list[tuple[str, str]] = []
    for k in picks:
        a, _, b = str(k).partition("~")
        if a in chars and b in chars and a != b and pair_key(a, b) not in {pair_key(*x) for x in out}:
            out.append(next((x for x in order if pair_key(*x) == pair_key(a, b)), (a, b)))
    return out


def stage_before(p: Project, s: str, t: str, n: int) -> str:
    """s → t 방향이 n 화까지 계획상 닿은 단계: 단계를 적고 범위 끝 화가 n 화 이하인 이정표 가운데 가장 늦은 것. 없으면 빈 글.
    2부를 짤 때 1부 끝 단계를 모르면 AI 가 낯섦부터 다시 짜서 넣는다 (정할 것 10, 이 일감의 프롬프트에만)."""
    done = [m for m in p.blueprint.milestones if m.source == s and m.target == t and m.stage and 0 < m.from_ep and (m.to_ep or m.from_ep) <= n]
    return max(done, key=lambda m: (m.to_ep or m.from_ep, m.from_ep)).stage if done else ""


def whole_have_lines(p: Project, pairs: list[tuple[str, str]], start: int, end: int) -> list[str]:
    """작품 전체 짜기 요청의 '이미 적은 설계도' 줄: 쌍마다 범위 앞 단계(방향마다 한 줄, start-1 화까지)와 기획 줄(plan_lines)."""
    names = char_names(p)
    out = []
    for a, b in pairs:
        if start > 1:
            for s, t in ((a, b), (b, a)):
                st = stage_before(p, s, t, start - 1)
                if st:
                    out.append(f"- {names.get(s, s)} → {names.get(t, t)}: {start - 1}화까지 계획상 {st}")
        out += plan_lines(p, {a, b}, start, end)
    return out


def clean_set(p: Project, prop, pairs: list[tuple[str, str]], start: int, end: int):
    """작품 전체 짜기 제안 정리 (BlueprintPlanSet): 고른 쌍의 항목만 남기고 같은 쌍이 두 번 오면 줄을 합친다. 쌍마다 clean_proposal 을 부른다.
    쌍 차례는 pairs 차례이고 a · b 도 pairs 의 것으로 맞춘다. 능력 줄은 고른 쌍의 인물만 clean_abilities 로 정리한다.
    편성은 범위를 자르고 고른 쌍 키만 남긴다. 작가 데이터가 아니라 AI 제안이라 지운다."""
    from .schema import BlueprintProposal, PairDraft
    want = {pair_key(a, b): (a, b) for a, b in pairs}
    merged: dict[str, PairDraft] = {}
    for x in prop.pairs:
        k = pair_key(x.a, x.b)
        if k not in want or x.a == x.b:
            continue
        if k in merged:
            merged[k].milestones += x.milestones
            merged[k].rungs += x.rungs
        else:
            merged[k] = PairDraft(a=want[k][0], b=want[k][1], milestones=list(x.milestones), rungs=list(x.rungs))
    out = []
    for k, (a, b) in want.items():
        if k not in merged:
            continue
        one = clean_proposal(p, BlueprintProposal(milestones=merged[k].milestones, rungs=merged[k].rungs), a, b, start, end)
        out.append(PairDraft(a=a, b=b, milestones=one.milestones, rungs=one.rungs))
    prop.pairs = out
    prop.abilities = clean_abilities(p, prop.abilities, {c for ab in pairs for c in ab}, start, end)
    prop.codex = clean_codex(p, prop.codex, prop.abilities)
    spots = []
    for sp in prop.spotlight:
        if _clip(sp, start, end):
            sp.focus = list(dict.fromkeys(pair_key(*str(k).partition("~")[::2]) for k in sp.focus if pair_key(*str(k).partition("~")[::2]) in want))
            sp.note = sp.note.strip()
            spots.append(sp)
    prop.spotlight = sorted(spots, key=lambda sp: (sp.from_ep, sp.to_ep))
    return prop


def apply_set(p: Project, pairs: list, abilities_rows: list, codex: list = ()) -> list[str]:
    """작품 전체 짜기에서 작가가 고른 줄을 한 사본에 모두 더한 뒤 check 를 한 번 부른다. 어긋나면 ValueError 이고 아무것도 바꾸지 않는다.
    pairs 는 PairDraft(쌍마다 고른 이정표 · 칸), abilities_rows 는 고른 AbilityDraft, codex 는 고른 도감 초안이다(13 과 같이 도감에 만든다). 만든 도감 항목 id 를 돌려준다."""
    q = p.model_copy(deep=True)
    made = add_codex(q, list(codex))
    for x in pairs:
        add_picks(q, x.a, x.b, x.milestones, x.rungs)
    add_abilities(q, abilities_rows)
    check(q, p)
    p.blueprint, p.abilities = q.blueprint, q.abilities
    return made


NEW = "+"  # 제안 줄의 임시 id 머리 (몰림 · 맞물림 계산에서 이미 적은 줄과 가른다)


def _with_proposal(p: Project, prop) -> tuple[list[Milestone], list[ContactLadder], list[AbilityPlan]]:
    """이미 적은 줄과 제안 줄을 한데 모은 목록. 제안 줄은 id 가 '+' 로 시작한다."""
    ms = list(p.blueprint.milestones)
    lads = {pair_key(x.a, x.b): ContactLadder(a=x.a, b=x.b, rungs=list(x.rungs)) for x in p.blueprint.ladders}
    for i, x in enumerate(prop.pairs):
        for j, m in enumerate(x.milestones):
            ms.append(Milestone(id=f"{NEW}ms-{i}-{j}", source=m.source, target=m.target, from_ep=m.from_ep, to_ep=m.to_ep, stage=m.stage, label=m.label, trigger=m.trigger))
        lad = lads.setdefault(pair_key(x.a, x.b), ContactLadder(a=x.a, b=x.b))
        lad.rungs += [ContactRung(id=f"{NEW}cr-{i}-{j}", label=r.label, layer=r.layer, note=r.note, from_ep=r.from_ep, to_ep=r.to_ep) for j, r in enumerate(x.rungs)]
    plans = list(p.blueprint.ability_plans) + [AbilityPlan(id=f"{NEW}ap-{i}", character=x.character, ability=x.ability, stat=x.stat, grade=x.grade, from_ep=x.from_ep, to_ep=x.to_ep)
                                               for i, x in enumerate(prop.abilities)]
    return ms, list(lads.values()), plans


def proposal_firsts(p: Project, prop) -> list[First]:
    """제안 카드의 전체 띠: 이미 적은 줄과 제안 줄을 함께 본 처음 닿는 줄. 제안 줄은 id 가 '+' 로 시작한다."""
    ms, lads, _ = _with_proposal(p, prop)
    return firsts(ms, lads)


def proposal_crowd(p: Project, prop) -> list[tuple[str, str, str]]:
    """제안 카드의 몰림 글: 제안 줄끼리, 그리고 제안 줄과 이미 적은 줄 사이만 (이미 적은 줄끼리는 개요의 전체 띠가 보인다, 정할 것 5)."""
    return crowd_rows(p, proposal_firsts(p, prop), lambda x, y: x.id.startswith(NEW) or y.id.startswith(NEW))


def proposal_mesh(p: Project, prop) -> list[tuple[str, str]]:
    """능력 맞물림 경고 (쌍 키, 글, 막지 않음): 이정표 라벨 · 계기, 사다리 칸 이름 · 메모에 능력 이름(도감의 다른 이름 포함)이 나오는데
    그 능력의 첫 화가 그 줄의 첫 화보다 뒤다. 한쪽이라도 제안 줄인 것만 알린다."""
    ms, lads, plans = _with_proposal(p, prop)
    names = char_names(p)
    first: dict[str, tuple[int, AbilityPlan, list[str]]] = {}
    for x in plans:
        if x.from_ep <= 0 or x.stat:  # 상태창 수치 줄('레벨')은 이름이 거의 모든 줄에 나와 견주지 않는다
            continue
        k = abilities.key(x.ability)
        a = abilities.find(p, x.ability)
        words = [w for w in {x.ability, *(a.aliases if a else [])} if len(_squash(w)) >= 2]
        if k not in first or x.from_ep < first[k][0]:
            first[k] = (x.from_ep, x, words)
    rows: list[tuple[str, str, int, str, str]] = []
    for m in ms:
        rows.append((pair_key(m.source, m.target), f"{names.get(m.source, m.source)} → {names.get(m.target, m.target)} '{m.label or m.stage}'", m.from_ep, m.id, f"{m.label} {m.trigger}"))
    for lad in lads:
        for r in lad.rungs:
            rows.append((pair_key(lad.a, lad.b), f"{names.get(lad.a, lad.a)} ↔ {names.get(lad.b, lad.b)} 칸 '{r.label}'", r.from_ep, r.id, f"{r.label} {r.note}"))
    out = []
    for key, what, ep, rid, text in rows:
        if ep <= 0:
            continue
        body = _squash(text)
        for got, x, words in first.values():
            if got > ep and any(_squash(w) in body for w in words) and (rid.startswith(NEW) or x.id.startswith(NEW)):
                out.append((key, f"{what}({ep}화~)에 능력 '{x.ability}' 이름이 나오는데 성장 일정은 {rng_text(x)}에 얻어요."))
    return out


# ---------- 본문에서 실제로 닿은 칸 (docs/blueprint/specs/07-contact.md) ----------

def reached(p: Project, lad: ContactLadder) -> dict[str, int]:
    """이 사다리에서 본문에 닿은 칸 id → 처음 닿은 화 (승인한 기록 Project.contact_log). 지워진 칸의 기록은 뺀다."""
    ids = {r.id for r in lad.rungs}
    out: dict[str, int] = {}
    for x in p.contact_log:
        if {x.a, x.b} == {lad.a, lad.b} and x.rung in ids:
            out[x.rung] = min(out.get(x.rung, x.episode), x.episode)
    return out


def actual_rung(p: Project, lad: ContactLadder) -> Optional[ContactRung]:
    """본문에서 실제로 닿은 칸 가운데 차례가 가장 뒤인 칸. 없으면 None."""
    got = reached(p, lad)
    return next((r for r in reversed(lad.rungs) if r.id in got), None)


def open_rungs(p: Project, ids: set[str]) -> list[tuple[ContactLadder, ContactRung]]:
    """상태 변경안이 고를 수 있는 칸: 두 인물이 모두 ids 에 든 사다리에서 아직 본문에 닿지 않은 칸."""
    out = []
    for lad in p.blueprint.ladders:
        if lad.a in ids and lad.b in ids:
            got = reached(p, lad)
            out += [(lad, r) for r in lad.rungs if r.id and r.id not in got]
    return out


def state_rule(p: Project, n: int) -> str:
    """상태 변경안 요구사항: n 화 플롯 인물끼리 아직 닿지 않은 사다리 칸 목록과 contacts 적는 법. 칸이 없으면 빈 글 (지금 프롬프트와 같다)."""
    try:
        who = set(p.episode(n).plot.characters)
    except KeyError:
        return ""
    picks = open_rungs(p, who)
    if not picks:
        return ""
    names = char_names(p)
    lines = "\n".join(f"  {r.id}: {names.get(lad.a, lad.a)}({lad.a}) ↔ {names.get(lad.b, lad.b)}({lad.b}) {rung_text(p, lad, r)}" for lad, r in picks)
    return ("\n- contacts 에는 이번 화 본문에서 두 인물이 아래 접촉 사다리 칸에 처음 닿았을 때만 그 칸 id(rung)와 두 인물 id(a, b), 본문 문장 그대로(quote)를 적습니다. "
            "목록에 없는 칸은 적지 않고, 닿지 않았으면 비웁니다.\n" + lines)


def clean_delta(p: Project, d: StateDelta) -> None:
    """상태 변경안 정리 훅 (features.CLEAN): 목록에 있는 칸만, 두 인물은 그 사다리의 쌍으로 맞추고, 이미 닿은 칸과 겹친 칸은 뺀다. 화 번호를 채운다."""
    out: list[ContactReach] = []
    for x in d.contacts:
        lad = next((lad for lad in p.blueprint.ladders if any(r.id == x.rung for r in lad.rungs)), None)
        if lad is None or {x.a, x.b} != {lad.a, lad.b} or x.rung in reached(p, lad) or any(y.rung == x.rung for y in out):
            continue
        out.append(x.model_copy(update={"a": lad.a, "b": lad.b, "quote": x.quote.strip(), "episode": d.episode}))
    d.contacts = out


def apply_delta(p: Project, d: StateDelta) -> None:
    """반영 훅 (features.APPLY_LAST): 작가가 고른 닿은 칸을 기록한다. 자동 집필 · -y 는 그 전에 hold 로 뺀다."""
    for x in d.contacts:
        if not any(y.rung == x.rung and {y.a, y.b} == {x.a, x.b} for y in p.contact_log):
            p.contact_log.append(x.model_copy(update={"episode": d.episode}))


def hold(p: Project, d: StateDelta) -> int:
    """사람 검토 없이 반영하기 전 (features.HOLD): 닿은 칸 제안을 반영하지 않고 남겨 둔다 (2026-11-10 사용자 결정). 남긴 개수."""
    held = [x.model_copy(update={"episode": d.episode}) for x in d.contacts]
    d.contacts = []
    p.contact_held = [x for x in p.contact_held if x.episode != d.episode] + held
    return len(held)


def take_held(p: Project, i: int) -> None:
    """남겨 둔 닿은 칸 제안 하나를 기록한다 (그 화의 기록). 칸이 없어졌거나 이미 닿았으면 기록 없이 지운다."""
    if not 0 <= i < len(p.contact_held):
        raise ValueError("남겨 둔 닿은 칸 제안이 없어요. 화면을 새로 고쳐 보세요")
    x = p.contact_held.pop(i)
    d = StateDelta(episode=x.episode, summary="", contacts=[x])
    clean_delta(p, d)
    apply_delta(p, d)


def drop_held(p: Project, i: int) -> None:
    if not 0 <= i < len(p.contact_held):
        raise ValueError("남겨 둔 닿은 칸 제안이 없어요. 화면을 새로 고쳐 보세요")
    p.contact_held.pop(i)


def revert(p: Project, n: int) -> None:
    """반영 취소 훅 (features.REVERT_LAST): n 화 뒤의 닿은 칸 기록과 남겨 둔 제안을 지운다."""
    p.contact_log = [x for x in p.contact_log if x.episode <= n]
    p.contact_held = [x for x in p.contact_held if x.episode <= n]


# ---------- 능력 일정 (docs/blueprint/specs/10-ability.md) ----------

def ability_text(x: AbilityPlan) -> str:
    """일정 줄의 능력 이름과 등급: '화염구 Lv3'. 상태창 수치 줄은 항목 이름과 닿을 값: '레벨 15'."""
    return f"{x.ability} {x.grade}".strip()


def _tidy(x) -> None:
    """저장 · AI 제안 정리가 같이 쓰는 칸 다듬기 (AbilityPlan · AbilityDraft).
    도감 항목 줄은 이름 칸에 적은 등급 꼬리를 등급 칸이 비었으면 그리로 옮긴다. 상태창 수치 줄(stat)은 꼬리를 떼지 않고 이름을 항목 이름으로 맞춘다."""
    x.stat, x.grade, x.condition = (x.stat or "").strip(), (x.grade or "").strip(), (x.condition or "").strip()
    if x.stat:
        x.ability = x.stat
        return
    name, tail = abilities.split(x.ability or "")
    x.ability, x.grade = name, x.grade or tail


def _verb(x: AbilityPlan, plain: str, stat: str) -> str:
    """경고 · 기획 줄의 동사: 도감 항목 줄은 '얻', 상태창 수치 줄은 '닿'."""
    return stat if x.stat else plain


def _grade_key(g: str) -> str:
    """등급 견주는 열쇠: 괄호 · 빈칸을 뗀다 ('(초급)' = '초급')."""
    return re.sub(r"[\s()\[\]（）]", "", g).casefold()


_NUM_GRADE = re.compile(r"(\D*)(\d+)(\D*)")


def _plan_ability(p: Project, x: AbilityPlan) -> Ability:
    """일정 줄이 가리키는 도감 항목. 도감에 없으면 이름만 가진 임시 항목 (저장하지 않는다)."""
    return abilities.find(p, x.ability) or Ability(id="", name=x.ability)


def _grade_ok(a: Ability, want: str, have: str) -> bool:
    """가진 등급 have 가 계획 등급 want 에 닿았는지. 같은 말, 도감 등급 목록의 차례, 숫자만 다른 등급의 숫자로 본다."""
    w, h = _grade_key(want), _grade_key(have)
    if not w or w == h:
        return True
    order = [_grade_key(g.grade) for g in a.grades]
    if w in order and h in order:
        return order.index(h) >= order.index(w)
    mw, mh = _NUM_GRADE.fullmatch(w), _NUM_GRADE.fullmatch(h)
    return bool(mw and mh and (mw[1], mw[3]) == (mh[1], mh[3]) and int(mh[2]) >= int(mw[2]))


def _affix(s: str) -> str:
    return re.sub(r"[\s.]", "", s).casefold()


def stat_ok(want: str, have: str) -> bool:
    """상태창 수치 값 have 가 계획 값 want 에 닿았는지. 둘 다 수(statwin._amount: '1,200골드' · 'Lv15' · '12.5')면 크기로 견준다.
    want 에 앞 표지 · 단위가 있으면 have 와 같아야 하고('Lv15' 는 'Lv' 끼리), 없으면 수만 본다('15' 는 'Lv15' 에도 닿음).
    수가 아닌 값('D급', 한도가 붙은 '80/100')은 같은 말일 때만 (_grade_key). 빈 have 는 닿지 않았다."""
    if not have.strip():
        return False
    w, h = statwin._amount(want), statwin._amount(have)
    if w and h:
        same = all(not _affix(w[i]) or _affix(w[i]) == _affix(h[i]) for i in (0, 4))
        return same and h[2] >= w[2]
    return bool(_grade_key(want)) and _grade_key(want) == _grade_key(have)


def stat_names(p: Project, cid: str) -> list[str]:
    """인물 하나의 상태창 수치 항목 이름: 지금 상태창 차례, 그 뒤 기록에만 있는 이름. 도감과 잇는 목록 항목(abilities.list_stats)과 인벤토리는 뺀다.
    설계도 화면의 항목 고르기 · AI 제안 정리 · 경고가 같이 쓴다."""
    lists = abilities.list_stats(p)
    st = p.state_of(cid)
    names = [s.name for s in (st.stats if st else [])] + [r.name for r in p.stat_log if r.character_id == cid]
    return [n for n in dict.fromkeys(names) if n not in lists and not any(w in n for w in statwin.INVENTORY)]


def _stat_got(p: Project, x: AbilityPlan) -> Optional[int]:
    for r in p.stat_log:
        if r.character_id == x.character and r.name == x.stat and stat_ok(x.grade, r.value):
            return r.episode
    st = p.state_of(x.character)
    if st and any(s.name == x.stat and stat_ok(x.grade, s.value) for s in st.stats):
        return 0
    return None


def got_ep(p: Project, x: AbilityPlan) -> Optional[int]:
    """일정 줄의 능력(등급)에 실제로 처음 닿은 화. 상태창 기록(stat_log)에서 계산한다. 1화 전에 정한 값은 0.
    기록 없이 지금 상태창에만 있으면 0 (시작 때로 본다). 아직이면 None.
    상태창 수치 줄(stat)은 그 항목 값이 닿을 값에 처음 닿은 화다 (stat_ok)."""
    if x.stat:
        return _stat_got(p, x)
    a = _plan_ability(p, x)
    for h in abilities.history(p, x.character, a):
        if h["item"] and _grade_ok(a, x.grade, abilities.split(h["item"])[1]):
            return h["episode"]
    if any(o["character_id"] == x.character and _grade_ok(a, x.grade, o["grade"]) for o in abilities.owners(p, a)):
        return 0
    return None


def tracked(p: Project, cid: str) -> bool:
    """이 인물의 실제를 셀 수 있는지: 상태창 값이나 상태창 기록이 하나라도 있다. 없으면 얻은 화를 알 수 없다 (got_ep 가 늘 None)."""
    return any(s.character_id == cid and s.stats for s in p.states) or any(r.character_id == cid for r in p.stat_log)




def ability_states(p: Project) -> list[dict]:
    """일정 줄마다 계획 대 실제: [{id, got, state, linked}]. got 은 얻은 화(없으면 None), linked 는 도감 항목이 있는지.
    state: 얻음(범위 안) · 앞섬(범위보다 먼저) · 늦음(범위 뒤) · 지남(범위 끝 화까지 반영했는데 기록에 없음) · 예정 · 미정(화 범위 없음)
    · 모름(범위 끝 화까지 반영했지만 그 인물에 상태창이 없어 셀 수 없음, tracked)."""
    last = last_done(p)
    out = []
    for x in p.blueprint.ability_plans:
        got = got_ep(p, x)
        if x.from_ep <= 0:
            state = "얻음" if got is not None else "미정"
        elif got is None:
            state = "예정" if x.to_ep > last else "지남" if tracked(p, x.character) else "모름"
        else:
            state = "앞섬" if got < x.from_ep else "늦음" if got > x.to_ep else "얻음"
        out.append({"id": x.id, "got": got, "state": state, "linked": bool(x.stat) or abilities.find(p, x.ability) is not None})
    return out


def ability_warning_rows(p: Project) -> list[tuple[str, str]]:
    """성장 일정 경고 (막지 않음): (인물 id, 글). 범위를 지나도록 얻지 못함, 범위보다 먼저 · 늦게 얻음, 도감에 없는 이름.
    상태창 수치 줄은 '닿'으로 적고 도감 경고를 내지 않는다. 도감 항목 줄의 이름이 그 인물의 상태창 수치 항목 이름이면 도감 경고 대신 항목으로 고르라고 알린다 (옛 줄)."""
    names = char_names(p)
    last = last_done(p)
    out = []
    for x, s in zip(p.blueprint.ability_plans, ability_states(p)):
        what = f"성장 일정 {names.get(x.character, x.character)}의 {ability_text(x)}"
        v = _verb(x, "얻", "닿")
        when = ("시작 때부터 닿아 있어요" if x.stat else "시작 때부터 가지고 있어요") if s["got"] == 0 else f"{s['got']}화에 {_verb(x, '얻었어요', '닿았어요')}"
        if s["state"] == "지남":
            out.append((x.character, f"{what}: {rng_text(x)}에 {v}기로 했는데 {last}화까지 반영한 상태창 기록에 없어요."))
        elif s["state"] == "앞섬":
            out.append((x.character, f"{what}: {when}. 설계도는 {rng_text(x)}에 {v}기로 했어요."))
        elif s["state"] == "늦음":
            out.append((x.character, f"{what}: {when}. 설계도는 {rng_text(x)}까지 {v}기로 했어요."))
        if s["linked"]:
            continue
        if x.ability in stat_names(p, x.character):
            out.append((x.character, f"{what}: '{x.ability}'{logline.josa(x.ability, '은', '는')} 상태창 수치 항목이에요. 줄을 고쳐 상태창 항목으로 고르면 값으로 셀 수 있어요."))
        else:
            out.append((x.character, f"{what}: '{x.ability}'{logline.josa(x.ability, '은', '는')} 스킬 도감에 없는 이름이에요. 도감에 항목을 만들면 효과 · 대가가 프롬프트에 들어가요."))
    return out


def _open_plans(p: Project, ids: set[str] | None) -> list[AbilityPlan]:
    """화 범위를 적었고 아직 얻지 못한 줄 (ids 가 있으면 그 인물만), 처음 화 차례.
    상태창이 없는 인물(tracked 아님)은 얻었는지 알 수 없으므로, 범위 끝 화까지 반영한 줄은 얻은 것으로 보고 뺀다 (같은 능력을 또 얻게 하지 않는다)."""
    last = last_done(p)
    rows = [x for x in p.blueprint.ability_plans if x.from_ep > 0 and (ids is None or x.character in ids) and got_ep(p, x) is None
            and (x.to_ep > last or tracked(p, x.character))]
    return sorted(rows, key=lambda x: (x.from_ep, x.to_ep))


def ability_line(p: Project, x: AbilityPlan, when: str = "") -> str:
    """프롬프트의 일정 한 줄 몸: '채현우 빙결 중급 (조건: …)'. when 을 주면 괄호 안 앞에 적는다: '(5~6화 · 조건: …)'."""
    name = next((c.name or c.id for c in p.characters if c.id == x.character), x.character)
    tail = " · ".join(b for b in (when, f"조건: {x.condition}" if x.condition else "") if b)
    return f"{name} {ability_text(x)}" + (f" ({tail})" if tail else "")


def ability_plan_lines(p: Project, ids: set[str] | None, start: int, end: int) -> list[str]:
    """기획 프롬프트의 능력 일정 줄: 아직 얻지 못한 줄 가운데 start 앞의 것, start~end 에 걸친 것, 인물마다 그 뒤 첫 것.
    start 앞의 줄은 범위 끝 화까지 반영했으면 '얻지 못함', 아직 반영하지 않은 화면 '앞 화에서 얻을 예정'으로 적는다 (같은 능력을 이 범위에 또 넣지 않게)."""
    out, after = [], set()
    last = last_done(p)
    for x in _open_plans(p, ids):
        v = _verb(x, "얻", "닿")
        if x.to_ep < start and x.to_ep <= last:
            out.append(f"- {rng_text(x)}에 {v}기로 했으나 아직 {v}지 못함: {ability_line(p, x)}")
        elif x.to_ep < start:
            out.append(f"- 앞 화({rng_text(x)})에서 {_verb(x, '얻을', '닿을')} 예정: {ability_line(p, x)}")
        elif x.from_ep <= end:
            out.append(f"- {rng_text(x)}에 {v}음: {ability_line(p, x)}")
        elif x.character not in after:
            after.add(x.character)
            out.append(f"- {rng_text(x)}에 {v}음 (이 범위 뒤): {ability_line(p, x)}")
    return out


def _plot_cast(p: Project, n: int) -> set[str]:
    try:
        return set(p.episode(n).plot.characters)
    except KeyError:
        return set()


def ability_due(p: Project, n: int) -> list[AbilityPlan]:
    """n 화 플롯 인물의 줄 가운데 n 화가 얻는 범위이고 아직 얻지 못한 것."""
    return [x for x in _open_plans(p, _plot_cast(p, n)) if x.from_ep <= n <= x.to_ep]


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _plot_text(p: Project, n: int) -> Optional[str]:
    """n 화 플롯 칸과 화 · 아크 연출 지시를 이어 붙이고 공백을 지운 글. 쓰기 줄의 '플롯에 나왔다'는 이 글에서 찾는다. 그 화가 없으면 None."""
    e = next((x for x in p.episodes if x.plot.number == n), None)
    if e is None:
        return None
    arc = p.arc_for(n) if p.serial else None
    pl = e.plot
    return _squash("\n".join([pl.title, pl.summary, *pl.events, pl.opening, pl.emotional_shift, pl.ending_hook, e.direction, arc.direction if arc else ""]))


def ability_in_plot(p: Project, n: int) -> list[AbilityPlan]:
    """ability_due 가운데 능력 이름(도감의 다른 이름 포함)이 n 화 플롯이나 연출 지시에 그대로 나온 줄. 쓰기 요청은 이 줄만 받는다.
    범위 안 모든 화에 넣으면 범위 첫 화로 앞당기기 쉽다 (신체 특징 줄 cast.body_cast 와 같은 조건)."""
    text = _plot_text(p, n)
    if text is None:
        return []
    return [x for x in ability_due(p, n) if (_stat_in(x, text) if x.stat else any(_squash(t) in text for t in abilities.terms(_plan_ability(p, x)) if _squash(t)))]


def _stat_in(x: AbilityPlan, text: str) -> bool:
    """상태창 수치 줄이 공백을 지운 글 text 에 나왔는지: 항목 이름과 닿을 값(수면 그 수, 'Lv15' → '15')이 함께 나온다.
    '레벨' 같은 이름만으로는 거의 모든 플롯에 걸려서 값도 본다."""
    a = statwin._amount(x.grade)
    value = statwin._fmt(a[2]) if a else _squash(x.grade)
    return _squash(x.stat) in text and bool(value) and value in text


def _label_words(p: Project, label: str) -> list[str]:
    """칸 이름의 낱말 (두 글자 이상, 겹치면 한 번). 인물 이름으로 시작하는 낱말은 뺀다: 그 쌍은 견주는 화마다 플롯에 나온다."""
    names = [w for c in p.characters for w in {_squash(c.name), *(_squash(x) for x in c.name.split())} if len(w) >= 2]
    words = [w.casefold() for w in re.findall(r"[^\W_]+", label)]
    return list(dict.fromkeys(w for w in words if len(w) >= 2 and not any(w.startswith(x) for x in names)))


def rung_in_text(p: Project, r: ContactRung, text: str) -> bool:
    """칸이 공백을 지운 글 text 에 나왔는지: 칸 이름이 그대로 나오거나, 칸 이름의 낱말 가운데 절반 넘게 나온다.
    부위 · 동작 이름은 보지 않는다 (2026-11-11 실측: 부위 이름은 칸과 무관한 화의 28~42% 에 나오고, 동작 이름은 기본형이라 플롯의 활용형과 맞지 않는다)."""
    label = _squash(r.label)
    if not label:
        return False
    if label in text:
        return True
    words = _label_words(p, r.label)
    return bool(words) and sum(w in text for w in words) * 2 > len(words)


def rungs_in_plot(p: Project, n: int) -> list[tuple[ContactLadder, ContactRung]]:
    """n 화 플롯 인물끼리의 사다리 칸 가운데 n 화가 처음 닿는 범위이고 그 칸이 n 화 플롯이나 연출 지시에 나온 것 (rung_in_text). 쓰기 요청은 이 칸만 받는다.
    범위 안 모든 화에 넣으면 범위 첫 화로 앞당기기 쉽다 (ability_in_plot 과 같은 글). 상한 대조는 스토리보드 · 검수가 맡는다."""
    text = _plot_text(p, n)
    if text is None:
        return []
    who = _plot_cast(p, n)
    return [(lad, r) for lad in p.blueprint.ladders if lad.a in who and lad.b in who
            for r in lad.rungs if 0 < r.from_ep <= n <= r.to_ep and rung_in_text(p, r, text)]


def ability_next(p: Project, n: int, per: int = 1) -> list[AbilityPlan]:
    """n 화 플롯 인물마다 n 화 뒤에 얻기로 한 줄 per 개까지 (가까운 것부터)."""
    seen: dict[str, int] = {}
    out = []
    for x in _open_plans(p, _plot_cast(p, n)):
        if x.from_ep > n and seen.get(x.character, 0) < per:
            seen[x.character] = seen.get(x.character, 0) + 1
            out.append(x)
    return out


def ability_state_rule(p: Project, n: int) -> str:
    """상태 변경안 요구사항 한 줄: n 화 플롯 인물의 줄 가운데 처음 화가 n 화 이하이고 아직 얻지 못한 능력의 이름.
    실제는 상태창 조각 이름으로 계산하므로, 얻었을 때 그 이름 그대로 적게 한다. 범위 뒤 줄은 넣지 않는다 (앞당김 방지). 상태창이 없으면 빈 글."""
    if not statwin.enabled(p):
        return ""
    rows = [x for x in _open_plans(p, _plot_cast(p, n)) if x.from_ep <= n]
    names = char_names(p)

    def say(xs: list[AbilityPlan]) -> str:
        return "; ".join(f"{names.get(x.character, x.character)}({x.character}) {ability_text(x)}" for x in xs) + "."
    listed, stats = [x for x in rows if not x.stat], [x for x in rows if x.stat]
    out = ""
    if listed:
        out += ("\n- 설계도의 능력 일정에 아래 능력이 있습니다. 이번 화 본문에서 그 인물이 이 능력을 얻었거나 이 등급에 올랐을 때만 stats 의 목록 항목에 이 이름 그대로 적습니다. "
                "본문에 없으면 적지 않습니다: " + say(listed))
    if stats:
        out += ("\n- 설계도의 능력 일정에 아래 상태창 수치가 있습니다. 이번 화 본문에서 그 인물의 값이 오르면 stats 의 그 항목 값을 바꿉니다. "
                "본문에 없으면 바꾸지 않습니다: " + say(stats))
    return out


def ability_delta_warnings(p: Project, d: StateDelta) -> list[tuple[str, str]]:
    """상태 변경안 경고 (features.CLEAN, 막지 않음): 반영하면 일정의 능력을 화 범위보다 먼저 얻게 됨. 항목은 (경고 글, 인물 id)."""
    rows = [x for x in _open_plans(p, None) if x.from_ep > d.episode]
    if not rows:
        return []
    after = statwin.after_delta(p, d)
    names = char_names(p)
    lists = abilities.list_stats(p)
    out = []
    for x in rows:
        mine = after.get(x.character, {})
        if x.stat:
            hit = stat_ok(x.grade, mine.get(x.stat, ""))
        else:
            a = _plan_ability(p, x)
            ks = {abilities.key(t) for t in abilities.terms(a)}
            hit = any(abilities.key(piece) in ks and _grade_ok(a, x.grade, abilities.split(piece)[1])
                      for name, piece in abilities.list_pieces(p, mine, lists) if not a.stat or name == a.stat)
        if hit:
            v = _verb(x, "얻", "닿")
            out.append((f"{names.get(x.character, x.character)}의 {ability_text(x)}: 설계도는 {rng_text(x)}에 {v}기로 했어요. "
                        f"이 변경안을 반영하면 {d.episode}화에 {_verb(x, '얻어요', '닿아요')}.", x.character))
    return out


# ---------- 능력 일정을 AI 로 짜기 · 거꾸로 뽑기 (docs/blueprint/specs/12-ability-ai.md) ----------

def _same_plan(x) -> tuple[str, str, str, str]:
    """check 가 '두 줄'로 보는 열쇠: 인물, 상태창 수치 항목(도감 항목 줄은 빈 글), 능력 이름, 등급. 화면 blueprint.js 의 bpAbSame · bpAbUnique 와 같다."""
    return x.character, abilities.key(x.stat or ""), abilities.key(x.ability), _grade_key(x.grade)


def clean_abilities(p: Project, rows: list, ids: set[str], start: int, end: int) -> list:
    """AI 가 제안한 능력 일정 줄(AbilityDraft) 정리: ids 에 든 인물의 줄만, 화 범위는 start~end 로 자른다.
    능력 칸의 등급 꼬리는 저장 규칙(check)대로 떼어 등급 칸으로 옮긴다. 그 뒤 이미 적은 줄 · 앞 제안 줄과 같은 인물 · 능력 · 등급인 줄을 뺀다
    (하나라도 남으면 apply_abilities 의 check 가 통째로 거절한다). 근거는 범위 안 화만 세 개까지. 인물(ids 차례 없이 인물 id) · 화 차례로 놓는다.
    작가 데이터가 아니라 AI 제안이라 지운다. 작품 전체 짜기(11b)도 이 함수를 부른다."""
    chars = {c.id for c in p.characters} & set(ids)
    seen = {_same_plan(x) for x in p.blueprint.ability_plans}
    out = []
    for x in rows:
        _tidy(x)
        if x.character not in chars or not x.ability or not _clip(x, start, end) or _same_plan(x) in seen:
            continue
        if x.stat and (not x.grade or x.stat not in stat_names(p, x.character)):  # 그 인물의 상태창에 없는 항목, 값이 빈 수치 줄
            continue
        seen.add(_same_plan(x))
        x.evidence = [e for e in x.evidence if start <= e.episode <= end and e.quote.strip()][:3]
        out.append(x)
    order = {c.id: i for i, c in enumerate(p.characters)}
    return sorted(out, key=lambda x: (order[x.character], x.from_ep, x.to_ep))


def clean_codex(p: Project, codex: list, rows: list) -> list:
    """AI 가 능력 일정 줄과 함께 낸 도감 초안(AbilityCodexDraft) 정리: 남은 줄(rows)의 능력 이름인 것만, 이미 도감에 있는 이름(다른 이름 포함)은 뺀다.
    이름의 등급 꼬리는 떼고, 같은 이름은 앞의 것 하나만, 등급 이름이 빈 등급은 뺀다. 작가 데이터가 아니라 AI 제안이라 지운다 (docs/blueprint/specs/13-ability-codex.md).
    어느 인물의 상태창 목록에 이미 그 조각이 있으면 stat 을 그 항목 이름으로 바꾼다. 도감 항목의 stat 이 다르면 상태창 조각과 잇지 않아서다(abilities.owners)."""
    want = {abilities.key(x.ability) for x in rows if not x.stat}  # 상태창 수치 줄은 도감 초안을 받지 않는다
    lists = abilities.list_stats(p)
    where = {abilities.key(abilities.split(piece)[0]): stat for st in p.states
             for stat, piece in abilities.list_pieces(p, {s.name: s.value for s in st.stats}, lists)}
    seen, out = set(), []
    for c in codex:
        c.name = abilities.split(c.name or "")[0]
        k = abilities.key(c.name)
        if not c.name or k not in want or k in seen or abilities.find(p, c.name) is not None:
            continue
        seen.add(k)
        c.stat, c.description, c.effect, c.cost = where.get(k, c.stat.strip()), c.description.strip(), c.effect.strip(), c.cost.strip()
        c.grades = [g for g in c.grades if g.grade.strip()]
        out.append(c)
    return out


def add_codex(p: Project, codex: list) -> list[str]:
    """고른 도감 초안을 p 의 스킬 도감에 AI 가 만든 항목(source="ai")으로 더한다. 그새 도감에 생긴 이름은 건너뛴다. 만든 항목 id 목록을 돌려준다.
    이름이 다른 항목과 겹치면 abilities.upsert 가 ValueError 를 낸다."""
    made = []
    for c in codex:
        if abilities.find(p, c.name) is None:
            a = abilities.upsert(p, Ability(id="", name=c.name, stat=c.stat, description=c.description, effect=c.effect, cost=c.cost,
                                             grades=c.grades, source="ai"))
            made.append(a.id)
    return made


def add_abilities(p: Project, rows: list) -> None:
    """고른 능력 일정 줄을 p 에 그대로 더한다 (검사 없음). 여러 묶음을 한 사본에 더하고 check 를 한 번 부르는 쪽(apply_abilities, 11b 의 apply_set)이 쓴다."""
    for x in rows:
        p.blueprint.ability_plans.append(AbilityPlan(character=x.character, ability=x.ability, stat=x.stat, grade=x.grade, condition=x.condition,
                                                     from_ep=x.from_ep, to_ep=x.to_ep))


def apply_abilities(p: Project, rows: list, codex: list = ()) -> list[str]:
    """작가가 고른 능력 일정 제안 줄을 설계도에 더하고, 고른 도감 초안(codex)을 스킬 도감에 만든다. 이미 적은 줄과 도감 항목은 고치지 않는다.
    더한 뒤 check 로 검사해 어긋나면 ValueError 이고 아무것도 바꾸지 않는다. 만든 도감 항목 id 목록을 돌려준다.
    실제 기록(Project.stat_log · 상태창)은 건드리지 않는다."""
    q = p.model_copy(deep=True)
    made = add_codex(q, list(codex))
    add_abilities(q, rows)
    check(q, p)
    p.blueprint, p.abilities = q.blueprint, q.abilities
    return made


def ability_have_lines(p: Project, ids: set[str] | None, start: int = 0, end: int = 0) -> list[str]:
    """AI 제안 요청의 '이미 적은 능력 일정' 줄: ids 인물의 모든 줄 (얻은 줄도 넣는다. ability_plan_lines 는 얻은 줄을 빼서 AI 가 다시 제안한다).
    start~end 에 걸친 줄이 맨 앞, 그다음 범위에서 가까운 줄, 화 범위를 비운 줄이 맨 뒤다. 예산으로 자를 때 받는 범위의 줄이 남게 하려는 차례다."""
    def far(x: AbilityPlan) -> int:
        return 0 if not start or (x.from_ep <= end and x.to_ep >= start) else min(abs(x.from_ep - end), abs(start - x.to_ep))
    rows = [x for x in p.blueprint.ability_plans if ids is None or x.character in ids]
    rows.sort(key=lambda x: (x.from_ep <= 0, far(x), x.from_ep, x.to_ep))
    return [f"- {ability_line(p, x, rng_text(x) if x.from_ep > 0 else '화 정하지 않음')}" for x in rows]


def ability_owned_lines(p: Project, ids: set[str] | None) -> list[str]:
    """AI 제안 요청의 '지금 상태창의 능력' 줄: ids 인물이 지금 가진 목록 항목 조각 (abilities.list_pieces). 이름을 이 조각 그대로 쓰게 하려는 재료다
    (실제 얻은 화 got_ep 는 조각 이름으로 잇는다)."""
    lists = abilities.list_stats(p)
    names = char_names(p)
    out = []
    for st in p.states:
        if ids is not None and st.character_id not in ids:
            continue
        pieces = [piece for _, piece in abilities.list_pieces(p, {s.name: s.value for s in st.stats}, lists)]
        if pieces:
            out.append(f"- {names.get(st.character_id, st.character_id)}: {', '.join(pieces)}")
    return out


def ability_stat_lines(p: Project, ids: set[str] | None) -> list[str]:
    """AI 제안 요청의 '지금 상태창의 수치' 줄: ids 인물의 상태창 수치 항목과 지금 값 (stat_names, 값이 빈 항목은 뺀다).
    레벨 같은 수치 성장 줄의 stat 이름과 값의 꼴을 이 줄 그대로 쓰게 하려는 재료다 (docs/blueprint/specs/14-growth-stat.md)."""
    names = char_names(p)
    out = []
    for st in p.states:
        if ids is not None and st.character_id not in ids:
            continue
        keep = set(stat_names(p, st.character_id))
        rows = [f"{s.name} {s.value}" for s in st.stats if s.name in keep and s.value.strip()]
        if rows:
            out.append(f"- {names.get(st.character_id, st.character_id)}: {', '.join(rows)}")
    return out
