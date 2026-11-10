"""설계도: 작가가 먼저 정하는 계획 층 (관계 이정표 · 접촉 사다리). 설계 문서는 docs/blueprint/.

여기는 데이터 규칙만 둔다: 빈 id 채우기, 저장 검사, 계획 칸, 화 번호 옮기기.
LLM 을 부르지 않는다. 계획값이라 관계 수치(Tie)나 플롯을 바꾸지 않는다.
"""
from __future__ import annotations

from typing import Callable, Iterator, Optional

from . import dynamics
from .schema import ContactLadder, ContactRung, Milestone, Project

Ranged = Milestone | ContactRung


def _ranged(p: Project) -> Iterator[Ranged]:
    yield from p.blueprint.milestones
    for lad in p.blueprint.ladders:
        yield from lad.rungs


def fill_ids(p: Project) -> None:
    """빈 id 를 채운다. 있는 id 는 바꾸지 않는다 (이정표 ms-<k>, 사다리 칸 cr-<k>)."""
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
    return out


def check(p: Project, before: Project | None = None) -> None:
    """저장 검사 (화면 저장용). 모르는 값을 지우지 않고 ValueError 로 거절한다. 빈 id 는 먼저 채운다.
    before(디스크 것)에서 이미 끊겨 있던 인물 · 장소 참조는 막지 않는다 (다른 라우트가 지운 옛 데이터)."""
    from .stage import ACTS, PARTS  # stage 는 board · cast 를 불러 renumber 와 돌지 않게 늦게 부른다
    fill_ids(p)
    names = {c.id: c.name or c.id for c in p.characters}
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


def ladder(p: Project, a: str, b: str) -> Optional[ContactLadder]:
    """a · b 쌍의 사다리 (차례 상관없음)."""
    return next((x for x in p.blueprint.ladders if {x.a, x.b} == {a, b}), None)


def planned_rung(lad: ContactLadder, n: int) -> Optional[ContactRung]:
    """n 화에 계획상 닿아 있는 가장 높은 칸: 처음 닿는 화가 있고 n 화 이하인 칸 가운데 차례가 가장 뒤인 칸."""
    return next((r for r in reversed(lad.rungs) if 0 < r.from_ep <= n), None)


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
    names = {c.id: c.name or c.id for c in p.characters}
    for x in _ranged(p):
        if not x.from_ep:
            continue
        lo, hi = remap_one(x.from_ep), remap_one(x.to_ep)
        if not lo or not hi:
            x.from_ep = x.to_ep = 0
            label = (f"관계 이정표 {names.get(x.source, x.source)} → {names.get(x.target, x.target)}" if isinstance(x, Milestone)
                     else f"접촉 사다리 칸 '{x.label or x.id}'")
            lost.append(label)
        else:
            x.from_ep, x.to_ep = lo, max(hi, lo)
    return [f"설계도의 {x} 화 범위를 새 화로 옮기지 못해 비웠어요" for x in lost]


def warning_rows(p: Project) -> list[tuple[str, str, str]]:
    """관계 이정표 경고 (막지 않음, docs/blueprint/specs/02-milestone-warn.md): (보는 인물 id, 보이는 인물 id, 글).
    단계와 화 범위를 모두 적은 이정표만 본다.
    이웃한 두 이정표 사이 칸이 모자람, 범위가 겹치는데 단계가 다름, 지금 단계에서 다음 이정표까지 칸이 모자람."""
    names = {c.id: c.name or c.id for c in p.characters}
    last = max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)
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
    """warning_rows 의 글만."""
    return [w for _, _, w in warning_rows(p)]
