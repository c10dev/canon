"""생성 파이프라인. 각 단계는 Project 를 받아 제안을 만들고, 반영은 호출자가 승인 후 한다."""
from __future__ import annotations

from . import dynamics, metrics, prompts
from .llm import LLM
from .schema import (
    ArcPlan,
    CharacterState,
    ChatMessage,
    ConsistencyReport,
    Episode,
    PlotBatch,
    PlotRevision,
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


# ---------- 3-1. 대화로 구조와 플롯 다듬기 ----------

LOCKED = ("written", "finalized")  # 본문이 있어 플롯을 바꿀 수 없는 상태
CHAT_KEEP = 200  # 화면별로 남겨 두는 대화 수


def revise_plot(llm: LLM, p: Project, message: str) -> PlotRevision:
    """작가의 말에 대한 답과 변경안을 만든다. 저장하지 않는다. 쓸 수 없는 부분은 빼고 답에 이유를 덧붙인다."""
    message = message.strip()
    if not message:
        raise ValueError("메시지가 비었습니다")
    rev = llm.json(
        prompts.SYSTEM_PLOT_CHAT, prompts.plot_chat_prompt(p, message), PlotRevision,
        hint={"message": message, "arc": p.arc, "episodes": [e.plot for e in p.episodes], "total": p.meta.target_episodes},
    )
    return clean_revision(p, rev)


def clean_revision(p: Project, rev: PlotRevision) -> PlotRevision:
    notes: list[str] = []
    total = rev.total_episodes if rev.total_episodes and rev.total_episodes != p.meta.target_episodes else 0
    if total and not 1 <= total <= 100:
        notes.append(f"총 화수 {total}화는 쓸 수 없어 뺐습니다.")
        total = 0
    rev.total_episodes = total
    acts = sorted(rev.acts, key=lambda a: a.start_ep)
    if acts and [a.model_dump() for a in acts] == [a.model_dump() for a in p.arc] and not total:
        acts = []
    if acts:
        try:
            validate_arc(ArcPlan(acts=acts), total or p.meta.target_episodes)
        except ValueError as e:
            notes.append(f"구조 변경안이 맞지 않아 뺐습니다: {e}")
            acts = []
    if total and not acts:
        notes.append("화수를 바꾸려면 구조도 함께 바꿔야 해서 화수 변경을 뺐습니다.")
        rev.total_episodes = total = 0
    rev.acts = acts
    arc = acts or p.arc
    last = total or p.meta.target_episodes
    status = {e.plot.number: e.status for e in p.episodes}
    current = {e.plot.number: e.plot.model_dump() for e in p.episodes}
    keep, seen = [], set()
    for e in rev.episodes:
        n = e.number
        if n in seen or not 1 <= n <= last:
            notes.append(f"{n}화 변경안은 범위를 벗어나 뺐습니다.")
            continue
        if status.get(n) in LOCKED:
            notes.append(f"{n}화는 본문이 있어 플롯 변경안을 뺐습니다.")
            continue
        act = next((a for a in arc if a.start_ep <= n <= a.end_ep), None)
        if act:
            e.act = act.name
        if current.get(n) == e.model_dump():
            continue
        seen.add(n)
        keep.append(e)
    rev.episodes = sorted(keep, key=lambda e: e.number)
    if notes:
        rev.reply = rev.reply.rstrip() + "\n\n※ " + " ".join(notes)
    return rev


def record_chat(p: Project, topic: str, message: str, rev: PlotRevision) -> ChatMessage:
    """작가의 말과 AI 답을 대화 기록에 남긴다."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    chat = p.chat(topic)
    reply = ChatMessage(role="assistant", text=rev.reply, revision=rev, at=now)
    if not (rev.acts or rev.episodes):
        reply.revision = None
    chat.messages += [ChatMessage(role="user", text=message.strip(), at=now), reply]
    chat.messages = chat.messages[-CHAT_KEEP:]
    return reply


def apply_revision(p: Project, rev: PlotRevision, acts: bool, episodes: list[int]) -> list[str]:
    """변경안에서 고른 부분만 반영한다. 본문이 있는 화는 바꾸지 않고, 확정된 화를 바꾸면 초안으로 돌린다.
    반영한 부분 이름('acts', 화 번호)을 돌려준다."""
    total = p.meta.target_episodes
    arc = p.arc
    applied: list[str] = []
    if acts and rev.acts:
        total = rev.total_episodes or total
        validate_arc(ArcPlan(acts=rev.acts), total)
        arc = [a.model_copy(deep=True) for a in rev.acts]
    by_no = {e.plot.number: e for e in p.episodes}
    cut = [n for n in by_no if n > total]
    stuck = [n for n in cut if by_no[n].status != "draft"]
    if stuck:
        raise ValueError(f"{total}화로 줄이면 확정됐거나 본문이 있는 화({stuck})가 빠집니다. 먼저 초안으로 되돌리세요")
    picked = {e.number: e for e in rev.episodes if e.number in set(episodes)}
    for n, plot in picked.items():
        if n > total:
            raise ValueError(f"{n}화는 총 {total}화 밖입니다. 구조 변경을 함께 고르세요")
        cur = by_no.get(n)
        if cur and cur.status in LOCKED:
            raise ValueError(f"{n}화는 본문이 있어 플롯을 바꿀 수 없습니다")
    if acts and rev.acts:
        p.arc = arc
        p.meta.target_episodes = total
        for n in cut:
            del by_no[n]
        applied.append("acts")
    for n, plot in picked.items():
        by_no[n] = Episode(plot=plot.model_copy(deep=True))  # 확정된 화도 내용이 바뀌면 다시 확정한다
        applied.append(str(n))
    p.episodes = [by_no[k] for k in sorted(by_no)]
    for e in p.episodes:
        act = next((a for a in p.arc if a.start_ep <= e.plot.number <= a.end_ep), None)
        if act and e.status not in LOCKED:
            e.plot.act = act.name
    return applied


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
