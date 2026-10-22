"""관계 역학: 승인된 사건(StoryEvent)으로 방향 관계(Tie)를 계산한다.

LLM 은 본문에서 사건만 뽑고, 수치 변화는 여기의 결정적인 수식이 정한다.
같은 사건은 항상 같은 변화를 낳으므로, 초기 상태 + 사건 로그를 재생하면 어느 화의 상태든 다시 만들 수 있다.

- 온기: 사건 충격 + 포화(끝으로 갈수록 덜 움직임) + 상호성(상대 온기 쪽으로 끌림)
- 신뢰: 베타 분포. 긍정 증거는 α, 부정 증거는 β 에 쌓이고 화가 바뀌면 조금씩 잊힌다
- 긴장: 저장하지 않고 온기, 비대칭, 목표 충돌, 비밀, 원한, 불균형 삼각관계, 불신으로 계산
- 단계: 값으로 목표 단계를 정하되 한 화에 한 칸만 이동

설계 배경은 DESIGN.md 의 '관계 역학' 절과 연구 보고서 참고.
"""
from __future__ import annotations

import math
from collections import deque
from itertools import combinations
from typing import Iterable, Optional

from .schema import ModelParams, Project, RelStage, Secret, Snapshot, StoryEvent, Tie

# 사건 종류별 효과 (강도 1당). 받는 쪽(target)이 행위자(actor)를 보는 간선에 적용한다.
# warmth: 온기 변화, trust: +면 긍정 증거 / -면 부정 증거, grievance: 원한 변화, status: 받는 쪽 서열 변화
EFFECTS: dict[str, dict[str, float]] = {
    "도움":       {"warmth": 0.06, "trust": 1.0, "grievance": -0.05, "status": 0.0},
    "희생":       {"warmth": 0.12, "trust": 2.0, "grievance": -0.10, "status": 0.0},
    "약속이행":   {"warmth": 0.03, "trust": 1.2, "grievance": -0.05, "status": 0.0},
    "칭찬":       {"warmth": 0.05, "trust": 0.3, "grievance": 0.0, "status": 0.03},
    "진심고백":   {"warmth": 0.10, "trust": 0.8, "grievance": -0.10, "status": 0.0},
    "사과":       {"warmth": 0.04, "trust": 0.5, "grievance": -0.25, "status": 0.03},
    "공동경험":   {"warmth": 0.05, "trust": 0.5, "grievance": 0.0, "status": 0.0},
    "거짓말발각": {"warmth": -0.08, "trust": -1.5, "grievance": 0.20, "status": 0.0},
    "배신":       {"warmth": -0.12, "trust": -2.0, "grievance": 0.30, "status": 0.0},
    "모욕":       {"warmth": -0.10, "trust": -0.5, "grievance": 0.20, "status": -0.05},
    "위협":       {"warmth": -0.10, "trust": -1.0, "grievance": 0.15, "status": -0.08},
    "거절":       {"warmth": -0.06, "trust": 0.0, "grievance": 0.10, "status": 0.0},
    "경쟁승리":   {"warmth": -0.03, "trust": 0.0, "grievance": 0.05, "status": -0.06},
    "비밀폭로":   {"warmth": -0.08, "trust": -1.0, "grievance": 0.20, "status": 0.0},
}
SYMMETRIC = {"공동경험"}  # 양쪽 모두 같은 효과를 받는 사건

# 한 화에 한 칸만 움직일 수 있는 단계 그래프
STAGE_EDGES: dict[str, tuple[str, ...]] = {
    "낯섦": ("경계", "호감"),
    "경계": ("낯섦", "호감", "적대"),
    "호감": ("낯섦", "경계", "신뢰", "균열"),
    "신뢰": ("호감", "균열", "화해"),
    "균열": ("호감", "신뢰", "적대", "화해"),
    "적대": ("경계", "균열", "화해"),
    "화해": ("호감", "신뢰", "균열", "적대"),
}


def clip(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


# ---------- 간선 찾기와 초기화 ----------

def find_tie(ties: list[Tie], source: str, target: str) -> Optional[Tie]:
    return next((t for t in ties if t.source == source and t.target == target), None)


def get_tie(ties: list[Tie], source: str, target: str) -> Tie:
    t = find_tie(ties, source, target)
    if t is None:
        t = Tie(source=source, target=target)
        ties.append(t)
    return t


def seed_ties(p: Project) -> None:
    """설정 단계의 Relationship(affinity) 에서 아직 없는 방향 간선을 만든다. 기존 project.json 이전에도 쓴다."""
    for r in p.relationships:
        for s, t in ((r.a, r.b), (r.b, r.a)):
            if find_tie(p.ties, s, t):
                continue
            w = clip(r.affinity / 5)
            m = 0.5 + r.affinity / 20  # 0.25 ~ 0.75, 증거 2개 분량
            tie = Tie(source=s, target=t, warmth=w, trust_pos=1 + 2 * m, trust_neg=1 + 2 * (1 - m), familiarity=0.3)
            tie.stage = target_stage(tie, "낯섦")
            p.ties.append(tie)


# ---------- 사건 적용 ----------

def _shift_warmth(t: Tie, d: float) -> None:
    sign = 1 if d > 0 else -1
    t.warmth = clip(t.warmth + d * (1 - t.warmth * sign) / 2)


def _hit(ties: list[Tie], params: ModelParams, viewer: str, other: str, eff: dict[str, float], k: float) -> None:
    t = get_tie(ties, viewer, other)
    _shift_warmth(t, eff["warmth"] * k)
    back = find_tie(ties, other, viewer)
    if back is not None:
        t.warmth = clip(t.warmth + params.reciprocity * (back.warmth - t.warmth))
    if eff["trust"] > 0:
        t.trust_pos += eff["trust"] * k
    elif eff["trust"] < 0:
        t.trust_neg += -eff["trust"] * k
    t.grievance = clip(t.grievance + eff["grievance"] * k, 0, 1)
    t.status = clip(t.status + eff["status"] * k)


def _set_trust(t: Tie, m: float) -> None:
    """증거량은 유지하고 평균만 m 으로 맞춘다."""
    n = max(t.trust_pos + t.trust_neg, 2.0)
    m = clip(m, 0.01, 0.99)
    t.trust_pos, t.trust_neg = n * m, n * (1 - m)


def apply_event(ties: list[Tie], secrets: list[Secret], params: ModelParams, e: StoryEvent) -> None:
    if e.kind == "수동보정":
        t = get_tie(ties, e.actor, e.target)  # actor 가 target 을 보는 간선을 직접 고친다
        if e.set_warmth is not None:
            t.warmth = clip(e.set_warmth)
        if e.set_trust is not None:
            _set_trust(t, e.set_trust)
        return
    eff = EFFECTS[e.kind]
    k = max(1, min(3, e.intensity))
    _hit(ties, params, e.target, e.actor, eff, k)
    if e.kind in SYMMETRIC:
        _hit(ties, params, e.actor, e.target, eff, k)
    for w in e.witnesses:
        if w not in (e.actor, e.target):
            _hit(ties, params, w, e.actor, eff, k * params.witness_factor)
    if e.reveals_secret:
        for s in secrets:
            if s.id == e.reveals_secret:
                knowers = {e.actor, e.target, *e.witnesses}
                s.hidden_from = [c for c in s.hidden_from if c not in knowers]


def meet(ties: list[Tie], params: ModelParams, cast: Iterable[str]) -> None:
    """같은 화에 등장한 인물 사이의 친숙도를 올린다 (이미 있는 간선만)."""
    ids = set(cast)
    for t in ties:
        if t.source in ids and t.target in ids:
            t.familiarity = clip(t.familiarity + params.familiarity_step * (1 - t.familiarity), 0, 1)


def end_episode(ties: list[Tie], params: ModelParams) -> None:
    """화가 바뀔 때: 신뢰 증거가 무정보 사전분포 Beta(1,1) 쪽으로 조금 잊히고 원한이 조금 풀린다."""
    g = params.trust_decay
    for t in ties:
        t.trust_pos = 1 + g * (t.trust_pos - 1)
        t.trust_neg = 1 + g * (t.trust_neg - 1)
        t.grievance *= params.grievance_decay


# ---------- 계산 값 ----------

def pair_warmth(ties: list[Tie], a: str, b: str) -> Optional[float]:
    ab, ba = find_tie(ties, a, b), find_tie(ties, b, a)
    vals = [t.warmth for t in (ab, ba) if t]
    return sum(vals) / len(vals) if vals else None


def _sign(v: Optional[float]) -> int:
    if v is None or abs(v) < 0.15:
        return 0
    return 1 if v > 0 else -1


def unbalanced_triads(ties: list[Tie]) -> list[tuple[str, str, str]]:
    """세 쌍의 부호 곱이 음수인 삼각관계 (구조 균형 이론)."""
    people = sorted({t.source for t in ties} | {t.target for t in ties})
    out = []
    for a, b, c in combinations(people, 3):
        signs = [_sign(pair_warmth(ties, x, y)) for x, y in ((a, b), (b, c), (c, a))]
        if 0 not in signs and signs[0] * signs[1] * signs[2] < 0:
            out.append((a, b, c))
    return out


def secret_load(secrets: list[Secret], a: str, b: str) -> float:
    load = sum(s.weight for s in secrets if (s.owner == a and b in s.hidden_from) or (s.owner == b and a in s.hidden_from))
    return min(1.0, load)


def tension(p: Project, a: str, b: str, triads: Optional[list[tuple[str, str, str]]] = None) -> float:
    """쌍의 긴장도 0~10."""
    q = p.params
    ab, ba = find_tie(p.ties, a, b), find_tie(p.ties, b, a)
    ties = [t for t in (ab, ba) if t]
    if not ties:
        return 0.0
    wb = sum(t.warmth for t in ties) / len(ties)
    asym = abs(ab.warmth - ba.warmth) if ab and ba else 0.0
    rel = next((r for r in p.relationships if {r.a, r.b} == {a, b}), None)
    goal = rel.goal_conflict if rel else 0.0
    griev = max(t.grievance for t in ties)
    distrust = max((1 - t.trust) * t.familiarity for t in ties)
    triads = unbalanced_triads(p.ties) if triads is None else triads
    n_triads = sum(1 for tri in triads if a in tri and b in tri)
    x = (q.tension_bias + q.w_dislike * max(0.0, -wb) + q.w_asymmetry * asym + q.w_goal * goal
         + q.w_secret * secret_load(p.secrets, a, b) + q.w_grievance * griev + q.w_triad * n_triads
         + q.w_distrust * distrust)
    return 10 * _sig(x)


def target_stage(t: Tie, prev: str) -> RelStage:
    if t.warmth <= -0.5:
        return "적대"
    if t.grievance >= 0.5 and t.warmth > -0.5:
        return "균열"
    if prev in ("균열", "적대") and t.grievance < 0.3 and t.warmth > 0.2:
        return "화해"
    if t.trust >= 0.7 and t.warmth >= 0.4:
        return "신뢰"
    if t.warmth >= 0.2:
        return "호감"
    if t.warmth <= -0.2 or t.trust < 0.35:
        return "경계"
    return "낯섦" if t.familiarity < 0.3 else prev  # type: ignore[return-value]


def step_stage(prev: str, goal: str) -> RelStage:
    """prev 에서 goal 로 가는 최단 경로의 첫 칸 (한 화에 한 칸)."""
    if prev == goal:
        return prev  # type: ignore[return-value]
    seen, q = {prev: None}, deque([prev])
    while q:
        cur = q.popleft()
        for nxt in STAGE_EDGES[cur]:
            if nxt not in seen:
                seen[nxt] = cur
                if nxt == goal:
                    while seen[nxt] != prev:
                        nxt = seen[nxt]
                    return nxt  # type: ignore[return-value]
                q.append(nxt)
    return goal  # type: ignore[return-value]


def sync_relationships(p: Project) -> None:
    """Tie 에서 계산한 값을 쌍 단위 Relationship(affinity, tension)에 반영한다. 기존 프롬프트·화면 호환용."""
    triads = unbalanced_triads(p.ties)
    for r in p.relationships:
        w = pair_warmth(p.ties, r.a, r.b)
        if w is not None:
            r.affinity = round(w * 5)
            r.tension = round(tension(p, r.a, r.b, triads))


# ---------- 화 단위 반영과 재생 ----------

def take_snapshot(p: Project, n: int) -> None:
    snap = Snapshot(
        episode=n,
        states=[s.model_copy(deep=True) for s in p.states],
        relationships=[r.model_copy(deep=True) for r in p.relationships],
        ties=[t.model_copy(deep=True) for t in p.ties],
        secrets=[s.model_copy(deep=True) for s in p.secrets],
        facts=list(p.facts),
        foreshadows=[f.model_copy(deep=True) for f in p.foreshadows],
    )
    p.snapshots = [s for s in p.snapshots if s.episode != n] + [snap]
    p.snapshots.sort(key=lambda s: s.episode)


def ensure_initial(p: Project) -> None:
    """1화 시작 전 상태(스냅샷 0)를 만든다. 첫 상태 반영 때 한 번만."""
    seed_ties(p)
    if p.snapshot(0) is None:
        take_snapshot(p, 0)


def run_episode(p: Project, n: int, events: list[StoryEvent], cast: Iterable[str]) -> None:
    """n화의 사건을 적용하고 화를 마감한다. 수동보정은 감쇠 뒤에 적용한다."""
    prev_stage = {(t.source, t.target): t.stage for t in p.ties}
    for e in events:
        if e.kind != "수동보정":
            apply_event(p.ties, p.secrets, p.params, e)
    meet(p.ties, p.params, cast)
    end_episode(p.ties, p.params)
    for t in p.ties:
        t.stage = step_stage(prev_stage.get((t.source, t.target), "낯섦"), target_stage(t, t.stage))
    for e in events:
        if e.kind == "수동보정":
            apply_event(p.ties, p.secrets, p.params, e)
    sync_relationships(p)


def replay(p: Project) -> list[Tie]:
    """스냅샷 0 + 사건 로그로 현재 간선을 다시 계산한다. 계수를 바꾼 뒤 recalc 에 쓴다."""
    base = p.snapshot(0)
    if base is None:
        return [t.model_copy(deep=True) for t in p.ties]
    sim = Project(
        relationships=[r.model_copy(deep=True) for r in base.relationships],
        ties=[t.model_copy(deep=True) for t in base.ties],
        secrets=[s.model_copy(deep=True) for s in base.secrets],
        params=p.params,
    )
    added = {s.id for s in base.secrets}
    for ep in p.episodes:
        n = ep.plot.number
        if ep.status != "finalized":
            continue
        delta = next((d for d in p.history if d.episode == n), None)
        for s in delta.secrets_added if delta else []:
            if s.id not in added:
                sim.secrets.append(s.model_copy(deep=True))
                added.add(s.id)
        run_episode(sim, n, [e for e in p.events if e.episode == n], ep.plot.characters)
    return sim.ties


# ---------- 숫자를 말로 ----------
# 프롬프트에는 숫자 대신 구간 표현을 넣는다. CLI 는 settings.show_numbers 로 숫자 보기를 고른다.

def _band(v: float, cuts: list[float], words: list[str]) -> str:
    for cut, word in zip(cuts, words):
        if v < cut:
            return word
    return words[-1]


def warmth_word(w: float) -> str:
    return _band(w, [-0.6, -0.2, 0.2, 0.6], ["적대한다", "반감이 있다", "무덤덤하다", "호감이 있다", "깊이 아낀다"])


def trust_word(m: float) -> str:
    return _band(m, [0.3, 0.5, 0.7], ["믿지 않는다", "의심하고 있다", "대체로 믿는다", "굳게 믿는다"])


def evidence_word(n: float) -> str:
    return _band(n, [4, 10], ["아직 판단 근거가 적다", "어느 정도 겪어 본 판단이다", "오래 쌓은 판단이라 쉽게 바뀌지 않는다"])


def tension_word(t: float) -> str:
    return _band(t, [3, 5, 7], ["낮음", "보통", "높음", "매우 높음"])


def _previous(p: Project) -> tuple[Optional[Snapshot], int]:
    """직전 스냅샷과 마지막 반영 화. 추세 표시에 쓴다."""
    eps = sorted(s.episode for s in p.snapshots)
    if len(eps) < 2:
        return None, eps[-1] if eps else 0
    return p.snapshot(eps[-2]), eps[-1]


def describe_relations(p: Project, ids: Optional[Iterable[str]] = None, numbers: bool = False) -> str:
    ids = set(ids) if ids is not None else {c.id for c in p.characters} | {t.source for t in p.ties}
    name = {c.id: c.name for c in p.characters}
    nm = lambda cid: name.get(cid, cid)  # noqa: E731
    prev, last = _previous(p)
    triads = unbalanced_triads(p.ties)
    lines: list[str] = []

    for t in sorted(p.ties, key=lambda t: (t.source, t.target)):
        if t.source not in ids or t.target not in ids:
            continue
        old = find_tie(prev.ties, t.source, t.target) if prev else None
        dw = t.warmth - old.warmth if old else 0.0
        if numbers:
            trend = f"({dw:+.2f})" if old and abs(dw) >= 0.01 else ""
            lines.append(
                f"{nm(t.source)} → {nm(t.target)}: 온기 {t.warmth:.2f}{trend} 신뢰 {t.trust:.2f}[증거 {t.evidence:.1f}] "
                f"원한 {t.grievance:.2f} 서열 {t.status:+.2f} 친숙 {t.familiarity:.2f} 단계 {t.stage}"
            )
            continue
        trend = f"({last}화에 크게 {'식음' if dw < 0 else '깊어짐'})" if abs(dw) >= 0.15 else ""
        text = f"{nm(t.source)} → {nm(t.target)}: {warmth_word(t.warmth)}{trend}. 신뢰: {trust_word(t.trust)}. {evidence_word(t.evidence)}."
        if t.grievance >= 0.3:
            text += " 풀리지 않은 원한이 있다."
        lines.append(text + f" 단계: {t.stage}")

    for r in p.relationships:
        if r.a not in ids or r.b not in ids:
            continue
        cur = tension(p, r.a, r.b, triads)
        if numbers:
            lines.append(f"{nm(r.a)} ↔ {nm(r.b)} ({r.type}): 긴장 {cur:.1f}/10 목표충돌 {r.goal_conflict:.2f}")
            continue
        old_rel = next((x for x in prev.relationships if {x.a, x.b} == {r.a, r.b}), None) if prev else None
        trend = ""
        if old_rel and abs(round(cur) - old_rel.tension) >= 1:
            trend = f", {last}화에 {'상승' if round(cur) > old_rel.tension else '하락'}"
        desc = f" {r.description}" if r.description else ""
        lines.append(f"{nm(r.a)} ↔ {nm(r.b)} ({r.type}){desc} 긴장: {tension_word(cur)} ({round(cur)}/10{trend})")

    for a, b, c in triads:
        if {a, b, c} <= ids:
            pos = [(x, y) for x, y in ((a, b), (b, c), (c, a)) if _sign(pair_warmth(p.ties, x, y)) > 0]
            neg = [(x, y) for x, y in ((a, b), (b, c), (c, a)) if _sign(pair_warmth(p.ties, x, y)) < 0]
            desc = ", ".join(f"{nm(x)}·{nm(y)} 가까움" for x, y in pos) + " / " + ", ".join(f"{nm(x)}·{nm(y)} 적대" for x, y in neg)
            lines.append(f"불안정한 구도 {nm(a)}·{nm(b)}·{nm(c)}: {desc}. 누군가 편을 바꾸거나, 화해하거나, 관계 하나가 끊어지는 쪽으로 압력이 있다.")

    for s in p.secrets:
        hidden = [h for h in s.hidden_from if h in ids]
        if s.owner in ids and hidden:
            lines.append(f"숨긴 비밀 ({nm(s.owner)}): {s.content} · 아직 모르는 인물: {', '.join(nm(h) for h in hidden)}")
    return "\n".join(lines)
