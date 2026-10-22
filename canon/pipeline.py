"""생성 파이프라인. 각 단계는 Project 를 받아 제안을 만들고, 반영은 호출자가 승인 후 한다."""
from __future__ import annotations

from . import dynamics, metrics, prompts
from .llm import LLM
from .schema import (
    ArcPlan,
    CharacterState,
    ConsistencyReport,
    Episode,
    PlotBatch,
    Project,
    SetupSuggestion,
    StateDelta,
    StoryEvent,
    StyleProfile,
)


# ---------- 1. 설정 도우미 ----------

def suggest_setup(llm: LLM, p: Project) -> SetupSuggestion:
    return llm.json(prompts.SYSTEM_PLANNER, prompts.setup_prompt(p), SetupSuggestion)


def apply_setup(p: Project, s: SetupSuggestion) -> None:
    """기존 입력은 유지하고 빈칸만 채운다."""
    p.meta.theme = p.meta.theme or s.theme
    p.meta.tone = p.meta.tone or s.tone
    for field, value in s.world.model_dump().items():
        if not getattr(p.world, field):
            setattr(p.world, field, value)
    known = {c.id for c in p.characters}
    p.characters += [c for c in s.characters if c.id not in known]
    pairs = {frozenset((r.a, r.b)) for r in p.relationships}
    p.relationships += [r for r in s.relationships if frozenset((r.a, r.b)) not in pairs]
    _init_states(p)
    dynamics.seed_ties(p)


def _init_states(p: Project) -> None:
    have = {s.character_id for s in p.states}
    for c in p.characters:
        if c.id not in have:
            p.states.append(CharacterState(character_id=c.id, current_goal=c.goal))


# ---------- 2. 스타일 레퍼런스 ----------

def analyze_style(llm: LLM, sample: str) -> StyleProfile:
    return llm.json(prompts.SYSTEM_PLANNER, prompts.style_prompt(sample), StyleProfile)


# ---------- 3. 기승전결 + 화별 플롯 ----------

def plan_arc(llm: LLM, p: Project) -> ArcPlan:
    plan = llm.json(prompts.SYSTEM_PLANNER, prompts.arc_prompt(p), ArcPlan, hint={"total": p.meta.target_episodes})
    validate_arc(plan, p.meta.target_episodes)
    return plan


def validate_arc(plan: ArcPlan, total: int) -> None:
    acts = sorted(plan.acts, key=lambda a: a.start_ep)
    if [a.name for a in acts] != ["기", "승", "전", "결"]:
        raise ValueError(f"기승전결 순서가 아닙니다: {[a.name for a in acts]}")
    expected = 1
    for a in acts:
        if a.start_ep != expected or a.end_ep < a.start_ep:
            raise ValueError(f"{a.name} 구간 범위 오류: {a.start_ep}~{a.end_ep}")
        expected = a.end_ep + 1
    if expected != total + 1:
        raise ValueError(f"구간이 {expected - 1}화에서 끝납니다 (목표 {total}화)")


def draft_plots(llm: LLM, p: Project, start: int, end: int) -> PlotBatch:
    if not p.arc:
        raise ValueError("기승전결 구조(arc)를 먼저 만드세요")
    batch = llm.json(
        prompts.SYSTEM_PLANNER, prompts.plot_prompt(p, start, end), PlotBatch,
        hint={"start": start, "end": end, "arc": p.arc},
    )
    numbers = [e.number for e in batch.episodes]
    if numbers != list(range(start, end + 1)):
        raise ValueError(f"요청한 화({start}~{end})와 생성된 화({numbers})가 다릅니다")
    return batch


def apply_plots(p: Project, batch: PlotBatch) -> None:
    """확정되지 않은(draft) 화만 덮어쓴다."""
    by_no = {e.plot.number: e for e in p.episodes}
    for plot in batch.episodes:
        cur = by_no.get(plot.number)
        if cur and cur.status != "draft":
            continue
        by_no[plot.number] = Episode(plot=plot)
    p.episodes = [by_no[k] for k in sorted(by_no)]


# ---------- 4. 본문 생성 ----------

def write_episode(llm: LLM, p: Project, n: int) -> str:
    ep = p.episode(n)
    if ep.status == "draft":
        raise ValueError(f"{n}화 플롯이 아직 확정되지 않았습니다 (confirm 먼저)")
    unfinished = [e.plot.number for e in p.episodes if e.plot.number < n and e.status != "finalized"]
    if unfinished:
        raise ValueError(f"이전 화의 상태 갱신이 끝나지 않았습니다: {unfinished}")
    return llm.text(prompts.SYSTEM_WRITER, prompts.episode_prompt(p, n))


# ---------- 5. 검수 (모순 찾기, 문체 지표) ----------

def check_episode(llm: LLM, p: Project, n: int) -> ConsistencyReport:
    if not p.episode(n).text:
        raise ValueError(f"{n}화 본문이 없습니다")
    report = llm.json(prompts.SYSTEM_CHECKER, prompts.check_prompt(p, n), ConsistencyReport, hint={"episode": n})
    report.episode = n
    return report


def apply_check(p: Project, r: ConsistencyReport) -> None:
    """검수 결과는 참고용 경고라 승인 없이 화에 붙여 둔다. 다시 검수하면 덮어쓴다."""
    p.episode(r.episode).issues = r.issues


def style_baseline(p: Project) -> metrics.StyleMetrics:
    """레퍼런스 원문 전체로 잰 값이 없으면(예전 프로젝트) 발췌 문단으로 잰다."""
    return p.style_baseline or metrics.measure("\n\n".join(p.style.sample_passages))


def style_drift(p: Project, n: int) -> tuple[metrics.StyleMetrics, list[str]]:
    cur = metrics.measure(p.episode(n).text, p.style.banned_phrases)
    return cur, metrics.drift(style_baseline(p), cur)


# ---------- 6. 상태 갱신 ----------

def extract_state(llm: LLM, p: Project, n: int) -> StateDelta:
    if not p.episode(n).text:
        raise ValueError(f"{n}화 본문이 없습니다")
    delta = llm.json(prompts.SYSTEM_EDITOR, prompts.state_prompt(p, n), StateDelta, hint={"episode": n})
    delta.episode = n
    return delta


def apply_delta(p: Project, d: StateDelta) -> None:
    ep = p.episode(d.episode)
    dynamics.ensure_initial(p)
    ep.summary = d.summary
    ep.status = "finalized"

    for upd in d.character_updates:
        cur = p.state_of(upd.character_id)
        if cur is None:
            p.states.append(upd)
            continue
        for field in ("emotional_state", "current_goal", "location", "notes"):
            if getattr(upd, field):
                setattr(cur, field, getattr(upd, field))
        cur.knows += [k for k in upd.knows if k not in cur.knows]

    for upd in d.relationship_updates:
        key = frozenset((upd.a, upd.b))
        for r in p.relationships:
            if frozenset((r.a, r.b)) == key:
                r.type, r.description = upd.type or r.type, upd.description or r.description
                if not d.events:  # 사건 없이 수치만 온 예전 형식: 양방향 온기를 affinity 에 맞춘다
                    r.affinity, r.tension = upd.affinity, upd.tension
                    for s, t in ((r.a, r.b), (r.b, r.a)):
                        dynamics.get_tie(p.ties, s, t).warmth = dynamics.clip(upd.affinity / 5)
                break
        else:
            p.relationships.append(upd)
            dynamics.seed_ties(p)

    known_secrets = {s.id for s in p.secrets}
    p.secrets += [s for s in d.secrets_added if s.id not in known_secrets]
    events = [e.model_copy(update={"episode": d.episode}) for e in d.events if e.kind != "수동보정"]
    dynamics.run_episode(p, d.episode, events, ep.plot.characters)
    p.events += events

    p.facts += [f for f in d.new_facts if f not in p.facts]
    known = {f.id for f in p.foreshadows}
    p.foreshadows += [f for f in d.foreshadow_planted if f.id not in known]
    for f in p.foreshadows:
        if f.id in d.foreshadow_resolved:
            f.status, f.payoff_ep = "resolved", d.episode
    p.history.append(d)
    dynamics.take_snapshot(p, d.episode)


def adjust_tie(p: Project, source: str, target: str, warmth: float | None, trust: float | None) -> None:
    """사용자가 관계 수치를 직접 고친다. 마지막으로 확정된 화의 수동보정 사건으로 기록한다."""
    done = [e.plot.number for e in p.episodes if e.status == "finalized"]
    n = max(done, default=0)
    dynamics.ensure_initial(p)
    e = StoryEvent(episode=n, actor=source, target=target, kind="수동보정", set_warmth=warmth, set_trust=trust)
    dynamics.apply_event(p.ties, p.secrets, p.params, e)
    dynamics.sync_relationships(p)
    p.events.append(e)
    dynamics.take_snapshot(p, n)


def revert(p: Project, n: int) -> None:
    """n화 상태 반영 직후로 되돌린다. 이후 화의 본문은 남기고 상태 반영만 취소한다."""
    snap = p.snapshot(n)
    if snap is None:
        raise ValueError(f"{n}화 스냅샷이 없습니다 (있는 화: {[s.episode for s in p.snapshots]})")
    p.states = [s.model_copy(deep=True) for s in snap.states]
    p.relationships = [r.model_copy(deep=True) for r in snap.relationships]
    p.ties = [t.model_copy(deep=True) for t in snap.ties]
    p.secrets = [s.model_copy(deep=True) for s in snap.secrets]
    p.facts = list(snap.facts)
    p.foreshadows = [f.model_copy(deep=True) for f in snap.foreshadows]
    p.events = [e for e in p.events if e.episode <= n]
    p.history = [d for d in p.history if d.episode <= n]
    p.snapshots = [s for s in p.snapshots if s.episode <= n]
    for ep in p.episodes:
        if ep.plot.number > n and ep.status == "finalized":
            ep.status, ep.summary = "written", ""


def recalc(p: Project) -> None:
    """계수(params)를 바꾼 뒤 사건 로그를 처음부터 다시 재생해 현재 관계를 다시 계산한다."""
    p.ties = dynamics.replay(p)
    dynamics.sync_relationships(p)
