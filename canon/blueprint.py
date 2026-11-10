"""설계도: 작가가 먼저 정하는 계획 층 (관계 이정표 · 접촉 사다리). 설계 문서는 docs/blueprint/.

여기는 데이터 규칙만 둔다: 빈 id 채우기, 저장 검사, 계획 칸, 화 번호 옮기기.
LLM 을 부르지 않는다. 계획값이라 관계 수치(Tie)나 플롯을 바꾸지 않는다.
"""
from __future__ import annotations

from typing import Callable, Iterator, Optional

from . import dynamics
from .schema import ContactLadder, ContactReach, ContactRung, Milestone, Project, StateDelta

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


def rung_text(p: Project, lad: ContactLadder, r: ContactRung) -> str:
    """사다리 칸 한 줄: '2. 손목 잡기 (맨살 · 오른 손목 · 잡다 · 신도림역 · 지훈 주도 · 메모)'. 부위 · 동작은 장면 연출의 이름으로."""
    from .stage import ACTS, PARTS
    names = {c.id: c.name or c.id for c in p.characters}
    places = {el.id: el.name for el in p.elements}
    bits = [r.layer, ", ".join(PARTS[x].label if x in PARTS else x for x in r.parts), ", ".join(ACTS[x].label if x in ACTS else x for x in r.acts),
            ", ".join(places.get(x, x) for x in r.places), f"{names.get(r.lead, r.lead)} 주도" if r.lead else "", r.note]
    detail = " · ".join(b for b in bits if b)
    return f"{lad.rungs.index(r) + 1}. {r.label or '이름 없는 칸'}" + (f" ({detail})" if detail else "")


def _rng(x: Ranged) -> str:
    return f"{x.from_ep}화" if x.from_ep == x.to_ep else f"{x.from_ep}~{x.to_ep}화"


def plan_lines(p: Project, ids: set[str] | None, start: int, end: int) -> list[str]:
    """기획 프롬프트의 설계도 줄 (docs/blueprint/specs/04-plan-prompt.md). 화 범위를 적은 줄만, start~end 에 걸친 것과 그 뒤 첫 것.
    ids 가 있으면 두 인물이 모두 ids 에 든 줄만. 이정표는 방향마다, 사다리는 쌍마다 지금 칸 · 이 범위에서 처음 닿는 칸 · 다음 칸."""
    names = {c.id: c.name or c.id for c in p.characters}

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
            out.append(f"- {who} {_rng(m)}{' (이 범위 뒤)' if m is after else ''}: {what}{tail}")
    for lad in p.blueprint.ladders:
        if not inside(lad.a, lad.b):
            continue
        who = f"{names.get(lad.a, lad.a)} ↔ {names.get(lad.b, lad.b)}"
        now = planned_rung(lad, start - 1)
        if now:
            out.append(f"- {who} 지금까지 닿은 칸: {rung_text(p, lad, now)}")
        for r in lad.rungs:
            if start <= r.from_ep <= end:
                out.append(f"- {who} {_rng(r)}에 처음 닿는 칸: {rung_text(p, lad, r)}")
        nxt = next((r for r in lad.rungs if r.from_ep > end), None)
        if nxt:
            out.append(f"- {who} 다음 칸 (이 범위 뒤 {_rng(nxt)}): {rung_text(p, lad, nxt)}")
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


def apply_picks(p: Project, a: str, b: str, milestones: list, rungs: list) -> None:
    """작가가 고른 제안 줄을 설계도에 더한다. 이정표는 뒤에 붙이고, 사다리 칸은 그 쌍 사다리에 처음 닿는 화 차례로 끼운다.
    범위를 비운 칸(정하지 않음)은 자리를 지킨다. 더한 뒤 check 로 검사해 어긋나면 ValueError 이고 아무것도 바꾸지 않는다."""
    q = p.model_copy(deep=True)
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
    check(q, p)
    p.blueprint = q.blueprint


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
    names = {c.id: c.name or c.id for c in p.characters}
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
