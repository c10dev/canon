"""상태 규칙 (효과 y, docs/context/specs/07-rules.md): 조건이 맞으면 상태 변경을 제안한다. LLM 을 부르지 않는다.

규칙은 상태를 바로 쓰지 않는다. 상태 변경안(StateDelta)에 '규칙 제안'(rule_proposals)을 채우고, 상태 승인 화면이 기본으로 체크한 채
'규칙' 표시로 보인다. 작가가 반영해야(또는 자동 집필 · -y 가 정책대로 반영해야) 데이터에 들어간다.

- 조건 판정은 context.holds 한 곳이다. 규칙은 n화 변경안을 흉내 반영한 복사본의 지금 값(context.view_now)으로 본다.
- 제안할 수 있는 것은 상태창 값 바꾸기(stat)와 복선 회수(resolve)뿐이다. 관계 수치는 조건에서 읽기만 한다.
- 반영 뒤 값이 지금 값과 같은 제안은 만들지 않는다. 규칙끼리 잇따라 걸리지 않는다(한 번만 계산).
- 같은 스탯을 둘 이상의 규칙이 바꾸면 목록 뒤 규칙을 남기고 경고를 단다. AI 제안도 그 스탯을 바꾸면 경고를 단다.
- 반영(apply_delta)은 features.APPLY_LAST 훅이다. 체크를 푼 제안(rule_off)은 반영하지 않고 dismissed.rule_proposals 에 남긴다.
"""
from __future__ import annotations

from . import context, statwin
from .schema import Project, RuleProposal, StateDelta, StateRule, StatValue

AI_TOO = "AI 제안도 이 스탯을 바꿔요. 규칙 제안이 나중에 적용돼요."
RULE_TOO = "앞 규칙 「{}」도 이 스탯을 바꾸자고 했어요. 목록 뒤 규칙을 남겨요."


def fill_ids(rules: list[StateRule]) -> None:
    """빈 id 와 겹친 id 에 r<N> 꼴 새 id 를 붙인다."""
    seen: set[str] = set()
    n = 1
    for r in rules:
        if r.id and r.id not in seen:
            seen.add(r.id)
            continue
        while f"r{n}" in seen or any(x.id == f"r{n}" for x in rules):
            n += 1
        r.id = f"r{n}"
        seen.add(r.id)


def simulate(p: Project, d: StateDelta) -> Project:
    """p 를 깊은 복사해 규칙 제안을 뺀 d 를 반영한 복사본. p · d 는 바꾸지 않는다 (web.preview 의 흉내 반영과 같은 길)."""
    from . import pipeline  # pipeline 이 features → 이 모듈을 부른다
    sim = p.model_copy(deep=True)
    pipeline.apply_delta(sim, d.model_copy(deep=True, update={"rule_proposals": [], "rule_off": []}))
    return sim


def propose(p: Project, d: StateDelta, n: int | None = None) -> list[RuleProposal]:
    """d 를 흉내 반영한 뒤 켠 규칙의 제안 목록. 규칙이 없으면 흉내 반영도 하지 않는다. 저장하지 않는다."""
    n = d.episode if n is None else n
    if not any(r.on and r.changes for r in p.state_rules):
        return []
    return propose_on(simulate(p, d), d, n)


def _stat_value(p: Project, cid: str, name: str) -> str | None:
    s = p.state_of(cid)
    if s is None:
        return None
    v = next((x for x in s.stats if x.name == name), None)
    return v.value if v else ""


def propose_on(sim: Project, d: StateDelta, n: int) -> list[RuleProposal]:
    """이미 흉내 반영한 복사본 sim 에서 켠 규칙의 조건을 보고 제안을 만든다. d 는 AI 제안(같은 스탯 경고)만 본다."""
    view = context.view_now(sim)
    ai_stats = {(u.character_id, x.name.strip()) for u in d.character_updates for x in u.stats if x.name.strip()}
    out: list[RuleProposal] = []
    at: dict[tuple, int] = {}  # 대상 → out 의 차례 (뒤 규칙이 앞 규칙을 덮는다)
    for r in sim.state_rules:
        if not r.on or not r.changes or not context.all_hold(sim, n, r.when, view):
            continue
        for ch in r.changes:
            if ch.kind == "stat":
                cid, name = ch.character_id, ch.stat.strip()
                cur = _stat_value(sim, cid, name) if name else None
                if cur is None:  # 상태가 없는 인물 · 빈 항목 이름 (statwin.merge 는 CharacterState 를 받는다)
                    continue
                new = statwin.resolve(cur, ch.value) if ch.value.strip() else ""
                if new == cur:  # 반영해도 값이 같으면 제안하지 않는다 (같은 값을 거듭 제안하지 않음)
                    continue
                target = ("stat", cid, name)
                prop = RuleProposal(kind="stat", character_id=cid, stat=name, value=ch.value.strip(), rule_id=r.id, rule_name=r.name,
                                    key=f"{r.id}:stat:{cid}:{name}", before=cur, after=new,
                                    warning=AI_TOO if (cid, name) in ai_stats else "")
            else:
                f = next((x for x in sim.foreshadows if x.id == ch.foreshadow_id), None)
                if f is None or f.status == "resolved" or f.planted_ep > n:
                    continue
                target = ("resolve", f.id)
                prop = RuleProposal(kind="resolve", foreshadow_id=f.id, rule_id=r.id, rule_name=r.name,
                                    key=f"{r.id}:resolve:{f.id}", before="열림", after="회수")
            if target in at:
                old = out[at[target]]
                if prop.kind == "stat":
                    prop.warning = " ".join(x for x in (prop.warning, RULE_TOO.format(old.rule_name or old.rule_id)) if x)
                out[at[target]] = prop
            else:
                at[target] = len(out)
                out.append(prop)
    return out


def refill(p: Project, d: StateDelta) -> list[RuleProposal]:
    """d.rule_proposals 를 지금 규칙 · 상태로 다시 채운다. 옛 제안은 버린다 (extract_state · parse_state · 자동 집필 · -y)."""
    d.rule_proposals = propose(p, d)
    return d.rule_proposals


def apply_delta(p: Project, d: StateDelta) -> None:
    """반영 훅 (features.APPLY_LAST): 체크한 규칙 제안을 반영한다. 상태창은 statwin.merge(source="rule"), 복선은 이번 화 회수.
    체크를 푼 제안은 d.dismissed.rule_proposals 로 옮기고, 기록(d.rule_proposals)에는 반영한 것만 남긴다."""
    off = set(d.rule_off)
    gone = {x.key for x in d.dismissed.rule_proposals}  # 화면(pickedDelta)이 이미 빼 둔 것과 겹치지 않게 key 로 센다
    keep: list[RuleProposal] = []

    def dismiss(x: RuleProposal) -> None:
        if x.key not in gone:
            gone.add(x.key)
            d.dismissed.rule_proposals.append(x)

    for x in d.rule_proposals:
        if x.key in off:
            dismiss(x)
            continue
        if x.kind == "stat":
            s = p.state_of(x.character_id)
            if s is None:
                dismiss(x)
                continue
            statwin.merge(p, s, [StatValue(name=x.stat, value=x.value)], d.episode, source="rule")
        else:
            f = next((f for f in p.foreshadows if f.id == x.foreshadow_id), None)
            if f is None or f.status == "resolved" or f.planted_ep > d.episode:
                dismiss(x)
                continue
            f.status, f.payoff_ep = "resolved", d.episode
        keep.append(x)
    d.rule_proposals, d.rule_off = keep, []


def resolved_ids(d: StateDelta) -> list[str]:
    """규칙 제안이 회수하는 복선 id (자동 집필 멈춤 검사 · 반영 취소)."""
    return [x.foreshadow_id for x in d.rule_proposals if x.kind == "resolve" and x.key not in set(d.rule_off)]


def describe(p: Project, x: RuleProposal) -> str:
    """제안 한 줄: '규칙 「기절」: 서윤 상태 정상 → 기절' (명령줄 · 작업 기록)."""
    head = f"규칙 「{x.rule_name or x.rule_id}」"
    if x.kind == "stat":
        who = next((c.name or c.id for c in p.characters if c.id == x.character_id), x.character_id)
        return f"{head}: {who} {x.stat} {x.before or '(없음)'} → {x.after or '(지움)'}"
    f = next((f for f in p.foreshadows if f.id == x.foreshadow_id), None)
    return f"{head}: 복선 회수 — {f.description if f else x.foreshadow_id}"
