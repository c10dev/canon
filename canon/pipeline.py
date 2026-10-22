"""생성 파이프라인. 각 단계는 Project 를 받아 제안을 만들고, 반영은 호출자가 승인 후 한다."""
from __future__ import annotations

from . import dynamics, elements, metrics, naming, prompts, storylines
from .llm import LLM, dump
from .schema import (
    Act,
    Conversion,
    ArcPlan,
    ArcProposal,
    Character,
    CharacterState,
    ChatMessage,
    ConsistencyReport,
    ElementImpact,
    Episode,
    ImpactReport,
    NameOptions,
    PassageRevision,
    PlotBatch,
    PlotRevision,
    Project,
    Recap,
    SerialConversion,
    Selection,
    SeriesPlan,
    SetupSuggestion,
    StateDelta,
    StoryArc,
    StoryEvent,
    Storyline,
    StorylineProposal,
    StyleProfile,
    TextEdit,
)


# ---------- 1. 설정 도우미 ----------

def suggest_setup(llm: LLM, p: Project) -> SetupSuggestion:
    return llm.json(prompts.SYSTEM_PLANNER, prompts.setup_prompt(p), SetupSuggestion)


def name_candidates(p: Project, character: str = "", place_kind: str = "", n: int = 8,
                    style: str | None = None) -> list[naming.Candidate]:
    """코드만으로 뽑는 후보 (LLM 호출 없음). character 는 인물 id, 비우면 지명."""
    if character:
        c = next((x for x in p.characters if x.id == character), None)
        if c is None:
            raise KeyError(f"인물 {character} 이 없습니다")
        return naming.character_candidates(p, c, n, style)
    return naming.location_candidates(p, n, place_kind, style)


def suggest_names(llm: LLM, p: Project, character: str = "", place_kind: str = "", n: int = 5,
                  style: str | None = None) -> tuple[list[naming.Candidate], NameOptions]:
    """코드가 후보를 넓게 뽑고, AI 가 대상에 맞는 것을 골라 이유를 붙인다. 반영은 작가가 한다."""
    cands = name_candidates(p, character, place_kind, n * 3, style)
    if character:
        c = next(x for x in p.characters if x.id == character)
        target = "인물 " + dump(c.model_dump(include={"id", "role", "age", "gender", "personality", "background", "goal", "wound"}))
    else:
        target = f"장소 ({place_kind or '종류 자유'}). 이야기에서 쓸 만한 곳으로."
    opts = llm.json(prompts.SYSTEM_NAMER, prompts.naming_prompt(p, target, cands, n), NameOptions,
                    hint={"candidates": [x.name for x in cands], "n": n})
    return cands, opts


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
    profile = llm.json(prompts.SYSTEM_PLANNER, prompts.style_prompt(sample), StyleProfile)
    count_markers(profile, sample)
    return profile


def count_markers(profile: StyleProfile, sample: str) -> None:
    """표지마다 원문 1,000자당 횟수를 센다. 모델이 적은 빈도는 믿지 않는다. 원문에 없는 표지는 뺀다."""
    keep = []
    for m in profile.markers:
        if metrics.marker_count(sample, m.text):
            m.per_1k = metrics.marker_rate(sample, m.text)
            keep.append(m)
    profile.markers = keep


# ---------- 3. 기승전결 + 화별 플롯 ----------

def plan_arc(llm: LLM, p: Project) -> ArcPlan:
    plan = llm.json(prompts.SYSTEM_PLANNER, prompts.arc_prompt(p), ArcPlan, hint={"total": p.meta.target_episodes})
    validate_arc(plan, p.meta.target_episodes)
    return plan


def validate_arc(plan: ArcPlan, total: int, start: int = 1) -> None:
    """기승전결 네 구간이 start 화부터 total 화까지 빈틈없이 이어지는지 본다. 장편 아크는 start 가 아크 첫 화다."""
    acts = sorted(plan.acts, key=lambda a: a.start_ep)
    if [a.name for a in acts] != ["기", "승", "전", "결"]:
        raise ValueError(f"기승전결 순서가 아닙니다: {[a.name for a in acts]}")
    expected = start
    for a in acts:
        if a.start_ep != expected or a.end_ep < a.start_ep:
            raise ValueError(f"{a.name} 구간 범위 오류: {a.start_ep}~{a.end_ep}")
        expected = a.end_ep + 1
    if expected != total + 1:
        raise ValueError(f"구간이 {expected - 1}화에서 끝납니다 (목표 {total}화)")


def draft_plots(llm: LLM, p: Project, start: int, end: int) -> PlotBatch:
    beats = p.beats()
    if not beats:
        raise ValueError("다음 아크를 먼저 기획하세요" if p.serial else "기승전결 구조(arc)를 먼저 만드세요")
    if p.serial and end > p.planned_until():
        raise ValueError(f"{p.planned_until()}화까지만 아크가 있습니다. {end}화까지 쓰려면 다음 아크를 먼저 기획하세요")
    batch = llm.json(
        prompts.SYSTEM_PLANNER, prompts.plot_prompt(p, start, end), PlotBatch,
        hint={"start": start, "end": end, "arc": beats},
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
        act = p.act_for(plot.number)
        if act:
            plot.act = act.name
        if cur and (cur.plot.storyline or cur.plot.threads) and not (plot.storyline or plot.threads):
            plot.storyline, plot.threads = cur.plot.storyline, list(cur.plot.threads)  # 작가가 붙인 줄기는 AI 초안이 지우지 않는다
        by_no[plot.number] = Episode(plot=plot)
        storylines.clean_plot(p, by_no[plot.number])
    p.episodes = [by_no[k] for k in sorted(by_no)]


# ---------- 3-0. 장편 연재: 부 구성과 굴러가는 아크 기획 ----------

ARC_MIN, ARC_MAX = 4, 60  # 아크 하나의 화수 범위. 아크 안에 기승전결 네 구간이 들어가야 해서 최소 4화
OLD_FORESHADOW = 50  # 이 화수보다 오래 열린 복선은 다음 아크 기획 때 따로 표시한다


def validate_parts(parts: list, total: int) -> None:
    parts = sorted(parts, key=lambda x: x.start_ep)
    expected = 1
    for i, x in enumerate(parts, 1):
        if x.number != i:
            raise ValueError(f"부 번호가 1부터 차례대로가 아닙니다: {[y.number for y in parts]}")
        if x.start_ep != expected or x.end_ep < x.start_ep:
            raise ValueError(f"{x.number}부 범위 오류: {x.start_ep}~{x.end_ep}")
        expected = x.end_ep + 1
    if parts and expected != total + 1:
        raise ValueError(f"부 구성이 {expected - 1}화에서 끝납니다 (목표 {total}화)")


def validate_story_arcs(p: Project) -> None:
    """아크가 1화부터 빈틈없이 이어지고, 아크 안 기승전결이 맞고, 부 경계를 넘지 않는지 본다."""
    expected = 1
    for i, s in enumerate(sorted(p.story_arcs, key=lambda s: s.start_ep), 1):
        if s.number != i:
            raise ValueError(f"아크 번호가 1부터 차례대로가 아닙니다 ({s.number})")
        if s.start_ep != expected or s.end_ep < s.start_ep:
            raise ValueError(f"아크 {s.number} 범위 오류: {s.start_ep}~{s.end_ep} ({expected}화부터여야 합니다)")
        validate_arc(ArcPlan(acts=s.acts), s.end_ep, s.start_ep)
        part = p.part_for(s.start_ep)
        if p.parts and (part is None or s.end_ep > part.end_ep):
            raise ValueError(f"아크 {s.number}({s.start_ep}~{s.end_ep}화)가 부 경계를 넘습니다")
        expected = s.end_ep + 1
    if p.story_arcs and expected - 1 > p.meta.target_episodes:
        raise ValueError(f"아크가 총 화수({p.meta.target_episodes}화)를 넘습니다")


def plan_series(llm: LLM, p: Project) -> SeriesPlan:
    total = p.meta.target_episodes
    plan = llm.json(prompts.SYSTEM_PLANNER, prompts.series_prompt(p), SeriesPlan, hint={"total": total})
    for x in plan.parts:
        x.summary = ""
    validate_parts(plan.parts, total)
    return plan


def apply_series(p: Project, plan: SeriesPlan) -> None:
    """부 구성을 바꾼다. 이미 끝난 부의 요약은 범위가 같으면 남긴다. 기존 아크가 새 부 경계를 넘으면 막는다."""
    validate_parts(plan.parts, p.meta.target_episodes)
    old = {(x.start_ep, x.end_ep): x.summary for x in p.parts}
    before = p.parts
    p.parts = [x.model_copy(deep=True, update={"summary": x.summary or old.get((x.start_ep, x.end_ep), "")})
               for x in sorted(plan.parts, key=lambda x: x.start_ep)]
    try:
        validate_story_arcs(p)
    except ValueError:
        p.parts = before
        raise


def next_arc_start(p: Project) -> int:
    return p.planned_until() + 1


def plan_next_arc(llm: LLM, p: Project, length: int = 0, note: str = "") -> ArcProposal:
    """지금까지 쓴 내용을 보고 다음 아크 하나를 제안한다. 저장하지 않는다."""
    if not p.serial:
        raise ValueError("장편 연재(form=serial) 작품에서만 아크를 기획합니다")
    start = next_arc_start(p)
    if start > p.meta.target_episodes:
        raise ValueError(f"총 {p.meta.target_episodes}화까지 아크가 모두 있습니다. 더 쓰려면 총 화수를 늘리세요")
    length = length or p.meta.arc_length
    part = p.part_for(start)
    limit = part.end_ep if part else p.meta.target_episodes
    prop = llm.json(
        prompts.SYSTEM_PLANNER, prompts.next_arc_prompt(p, start, length, note), ArcProposal,
        hint={"start": start, "length": length, "limit": limit, "number": len(p.story_arcs) + 1},
    )
    return clean_arc(p, prop)


def clean_arc(p: Project, prop: ArcProposal) -> ArcProposal:
    """아크 번호와 시작 화를 맞추고 범위를 검사한다. 고칠 수 없는 오류는 그대로 알린다."""
    a = prop.arc
    a.number, a.summary = len(p.story_arcs) + 1, ""
    start = next_arc_start(p)
    if a.start_ep != start:
        raise ValueError(f"아크가 {a.start_ep}화에서 시작합니다 ({start}화부터여야 합니다)")
    size = a.end_ep - a.start_ep + 1
    if not ARC_MIN <= size <= ARC_MAX:
        raise ValueError(f"아크 길이 {size}화는 쓸 수 없습니다 ({ARC_MIN}~{ARC_MAX}화)")
    part = p.part_for(start)
    limit = part.end_ep if part else p.meta.target_episodes
    if a.end_ep > limit:
        raise ValueError(f"아크가 {a.end_ep}화에서 끝나 {'부' if part else '작품'} 끝({limit}화)을 넘습니다")
    validate_arc(ArcPlan(acts=a.acts), a.end_ep, a.start_ep)
    if 0 < limit - a.end_ep < ARC_MIN:  # 남는 화로는 아크를 만들 수 없으니 결 구간을 부 끝까지 늘린다
        last = max(a.acts, key=lambda x: x.start_ep)
        last.end_ep = a.end_ep = limit
        prop.reply = (prop.reply.rstrip() + f"\n\n※ {'부' if part else '작품'} 끝까지 {ARC_MIN}화가 안 남아 아크를 {limit}화까지 늘렸습니다.").strip()
    known = {c.id for c in p.characters}
    prop.new_characters = [c for c in prop.new_characters if c.id not in known]
    ids = known | {c.id for c in prop.new_characters}
    a.cast = [c for c in a.cast if c in ids]
    open_fs = {f.id for f in p.foreshadows if f.status == "open"}
    a.payoffs = [f for f in a.payoffs if f in open_fs]
    return prop


def _add_characters(p: Project, chars: list[Character], first_ep: int) -> None:
    """새 인물을 붙인다. 주역으로 올리는 것은 작가가 정하므로 조연으로 들인다."""
    known = {c.id for c in p.characters}
    for c in chars:
        if c.id in known:
            continue
        p.characters.append(c.model_copy(update={
            "tier": "support" if c.tier == "main" else c.tier,
            "first_ep": c.first_ep or first_ep,
        }))
        known.add(c.id)
    _init_states(p)


def apply_arc(p: Project, prop: ArcProposal) -> StoryArc:
    """제안된 다음 아크를 붙인다. 새 인물과 복선 회수 예정 화도 함께 반영한다."""
    prop = clean_arc(p, prop.model_copy(deep=True))
    a = prop.arc
    p.story_arcs.append(a)
    try:
        validate_story_arcs(p)
    except ValueError:
        p.story_arcs.pop()
        raise
    _add_characters(p, prop.new_characters, a.start_ep)
    for f in p.foreshadows:
        if f.id in a.payoffs and f.status == "open":
            f.due_ep = a.end_ep
    return a


def remove_last_arc(p: Project) -> StoryArc:
    """마지막 아크를 지운다 (다시 기획하려고). 확정했거나 본문이 있는 화가 있으면 막는다."""
    if not p.story_arcs:
        raise ValueError("지울 아크가 없습니다")
    a = max(p.story_arcs, key=lambda s: s.start_ep)
    eps = [e for e in p.episodes if a.start_ep <= e.plot.number <= a.end_ep]
    stuck = [e.plot.number for e in eps if e.status != "draft"]
    if stuck:
        raise ValueError(f"아크 {a.number}에 확정했거나 본문이 있는 화({stuck})가 있어 지울 수 없습니다")
    p.story_arcs.remove(a)
    p.episodes = [e for e in p.episodes if e not in eps]
    return a


def arc_finished(p: Project, a: StoryArc) -> bool:
    nums = {e.plot.number for e in p.episodes if e.status == "finalized"}
    return all(n in nums for n in range(a.start_ep, a.end_ep + 1))


def recap(llm: LLM, p: Project, kind: str, number: int) -> Recap:
    """끝난 아크(kind='arc')나 부(kind='part')의 요약을 제안한다. 화별 요약(작가가 승인한 것)으로 만든다."""
    target = _recap_target(p, kind, number)
    if not arc_finished(p, target):
        raise ValueError(f"{'아크' if kind == 'arc' else '부'} {number}의 모든 화가 상태 반영까지 끝나야 요약합니다")
    return llm.json(prompts.SYSTEM_EDITOR, prompts.recap_prompt(p, kind, number), Recap, hint={"kind": kind, "number": number})


def apply_recap(p: Project, kind: str, number: int, summary: str) -> None:
    _recap_target(p, kind, number).summary = summary.strip()


def _recap_target(p: Project, kind: str, number: int):
    items = p.story_arcs if kind == "arc" else p.parts if kind == "part" else None
    if items is None:
        raise ValueError(f"모르는 요약 단위입니다: {kind}")
    hit = next((x for x in items if x.number == number), None)
    if hit is None:
        raise ValueError(f"{'아크' if kind == 'arc' else '부'} {number}이(가) 없습니다")
    return hit


def pending_recaps(p: Project) -> list[tuple[str, int]]:
    """모든 화가 끝났는데 요약이 없는 아크와 부."""
    out = [("arc", a.number) for a in p.story_arcs if not a.summary and arc_finished(p, a)]
    out += [("part", x.number) for x in p.parts if not x.summary and arc_finished(p, x)]
    return out


# ---------- 3-0'. 단편 → 장편 전환 ----------
# 단편 전체가 아크 1이 된다. 이미 쓴 화의 구조는 바꿀 수 없어서 기승전결을 그대로 옮기고,
# 그 뒤를 부 구성과 장기 떡밥으로 늘린다. 되돌리기용 백업은 호출자가 store.save_backup 으로 남긴다.

CONVERT_MAX = 1000  # 전환할 때 고를 수 있는 총 화수 상한
BACKUP_TAG = "before-serial"


def short_end(p: Project) -> int:
    """아크 1이 될 단편의 마지막 화. 구조가 없으면 0."""
    return max((a.end_ep for a in p.arc), default=0)


def convert_range(p: Project) -> tuple[int, int]:
    end = short_end(p)
    return max(end + ARC_MIN, ARC_MIN * 2), CONVERT_MAX


def check_convertible(p: Project, total: int) -> None:
    if p.serial:
        raise ValueError("이미 장편 연재 작품입니다")
    if p.episodes and not p.arc:
        raise ValueError("기승전결 구조 없이 플롯만 있는 작품은 전환할 수 없습니다. 구조를 먼저 저장하세요")
    lo, hi = convert_range(p)
    if not lo <= total <= hi:
        raise ValueError(f"장편 총 화수는 {lo}~{hi}화로 정하세요 (단편 {short_end(p)}화 뒤에 아크가 하나 이상 들어가야 합니다)")


def propose_conversion(llm: LLM, p: Project, total: int, ending: str = "", note: str = "") -> SerialConversion:
    """단편을 장편으로 늘리는 계획을 제안한다. 저장하지 않는다."""
    if ending not in ("", "keep", "reopen"):
        raise ValueError(f"모르는 결말 처리입니다: {ending}")
    check_convertible(p, total)
    prop = llm.json(
        prompts.SYSTEM_PLANNER, prompts.convert_prompt(p, total, ending, note), SerialConversion,
        hint={"total": total, "end": short_end(p), "ending": ending, "characters": [c.id for c in p.characters],
              "open": [f.id for f in p.foreshadows if f.status == "open"],
              "unlocked": [e.plot for e in p.episodes if e.status not in LOCKED]},
    )
    if ending:
        prop.ending = ending  # type: ignore[assignment]
    return clean_conversion(p, prop, total)


def clean_conversion(p: Project, prop: SerialConversion, total: int = 0) -> SerialConversion:
    """번호와 범위를 맞추고 쓸 수 없는 부분을 뺀다. 뺀 이유는 reply 에 덧붙인다."""
    total = total or prop.total_episodes
    check_convertible(p, total)
    prop.total_episodes = total
    notes: list[str] = []
    end = short_end(p)
    known = {c.id for c in p.characters}
    a = prop.arc
    a.number, a.start_ep, a.end_ep, a.payoffs = 1, 1, end or 1, []
    a.acts = [x.model_copy(deep=True) for x in p.arc]
    a.cast = [c for c in dict.fromkeys(a.cast) if c in known]
    finished = bool(end) and all(any(e.plot.number == n and e.status == "finalized" for e in p.episodes)
                                 for n in range(1, end + 1))
    if not finished:
        a.summary = ""
    a.summary = a.summary.strip()

    parts = sorted(prop.parts, key=lambda x: x.start_ep)
    for i, x in enumerate(parts, 1):
        x.number, x.summary = i, ""
    if parts:
        parts[0].start_ep = 1
        parts[-1].end_ep = total  # 마지막 부가 총 화수와 조금 어긋나는 것은 맞춰 준다
    try:
        validate_parts(parts, total)
        if parts and end and parts[0].end_ep < end:
            raise ValueError(f"1부가 {parts[0].end_ep}화에서 끝나 아크 1({end}화까지)을 품지 못합니다")
    except ValueError as e:
        notes.append(f"부 구성이 맞지 않아 뺐습니다: {e}. 전환한 뒤 부 구성을 다시 제안받으세요.")
        parts = []
    prop.parts = parts

    seen = {f.id for f in p.foreshadows}
    last_text = max((e.plot.number for e in p.episodes if e.status in LOCKED), default=0)
    fs = []
    for f in prop.foreshadows:
        if not f.id or f.id in seen or not f.description.strip():
            continue
        seen.add(f.id)
        fs.append(f.model_copy(update={
            "status": "open", "payoff_ep": None,
            "planted_ep": min(max(f.planted_ep, 1), end or 1),
            "scope": f.scope if f.scope != "arc" else "part",
            "due_ep": f.due_ep if f.due_ep and end < f.due_ep <= total else None,
        }))
    prop.foreshadows = fs
    opened = {f.id: f for f in p.foreshadows if f.status == "open"}
    prop.scopes = [s for s in {s.id: s for s in prop.scopes}.values() if s.id in opened and s.scope != opened[s.id].scope]
    prop.facts = [f.strip() for f in dict.fromkeys(prop.facts) if f.strip() and f.strip() not in p.facts]

    tier = {c.id: c.tier for c in p.characters}
    tiers = [t for t in {t.id: t for t in prop.tiers}.values() if t.id in tier and t.tier != tier[t.id]]
    after = tier | {t.id: t.tier for t in tiers}
    if not any(v == "main" for v in after.values()) and tiers:
        notes.append("주역이 한 명도 남지 않아 비중 조정을 뺐습니다.")
        tiers = []
    prop.tiers = tiers

    status = {e.plot.number: e.status for e in p.episodes}
    current = {e.plot.number: e.plot.model_dump() for e in p.episodes}
    keep, dropped = {}, []
    for e in prop.episodes:
        n = e.number
        if not 1 <= n <= end or status.get(n) in LOCKED:
            dropped.append(n)
            continue
        act = p.act_for(n)
        if act:
            e.act = act.name
        if current.get(n) != e.model_dump():
            keep[n] = e
    if dropped:
        notes.append(f"본문이 있거나 단편 범위 밖인 화({sorted(set(dropped))})의 플롯 변경안은 뺐습니다.")
    prop.episodes = [keep[n] for n in sorted(keep)]
    if last_text and prop.ending == "reopen" and not (prop.foreshadows or prop.facts or prop.episodes):
        notes.append("결말을 다시 열 장치(떡밥, 사실, 플롯 수정)가 없습니다. 다시 제안받거나 전환한 뒤 인과율에서 더하세요.")
    if notes:
        prop.reply = (prop.reply.rstrip() + "\n\n※ " + " ".join(notes)).strip()
    return prop


def apply_conversion(p: Project, prop: SerialConversion, at: str = "") -> Project:
    """전환 제안을 반영한다. 화면에서 빼고 보낸 항목은 반영하지 않는다. 전환 전 작품(백업할 것)을 돌려준다."""
    prop = clean_conversion(p, prop.model_copy(deep=True))
    before = p.model_copy(deep=True)
    end = short_end(p)
    try:
        p.meta.form, p.meta.target_episodes = "serial", prop.total_episodes
        p.story_arcs = [prop.arc] if end else []
        p.parts = prop.parts
        p.arc = []
        validate_story_arcs(p)
    except ValueError:
        for k in ("meta", "story_arcs", "parts", "arc"):
            setattr(p, k, getattr(before, k))
        raise
    tiers = {t.id: t.tier for t in prop.tiers}
    for c in p.characters:
        c.tier = tiers.get(c.id, c.tier)
    scopes = {s.id: s.scope for s in prop.scopes}
    for f in p.foreshadows:
        f.scope = scopes.get(f.id, f.scope)
    p.foreshadows += prop.foreshadows
    p.facts += prop.facts
    by_no = {e.plot.number: e for e in p.episodes}
    for plot in prop.episodes:
        by_no[plot.number] = Episode(plot=plot.model_copy(deep=True))  # 확정된 화도 내용이 바뀌면 다시 확정한다
    p.episodes = [by_no[k] for k in sorted(by_no)]
    if not at:
        from datetime import datetime, timezone

        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    p.conversion = Conversion(at=at, from_total=before.meta.target_episodes, arc_end=end,
                              ending=prop.ending, history=len(p.history))
    return before


def undo_blockers(p: Project, backup: Project | None) -> list[str]:
    """전환을 되돌리면 잃는 것이 있으면 그 이유. 비면 되돌려도 된다."""
    if p.conversion is None:
        return ["단편에서 전환한 작품이 아닙니다"]
    if backup is None:
        return ["전환 전 백업(before-serial.json)이 없습니다"]
    out = []
    if len(p.history) > p.conversion.history:
        out.append(f"전환한 뒤 상태를 반영한 화가 있습니다 ({[d.episode for d in p.history[p.conversion.history:]]}화)")
    old = {e.plot.number: e.text for e in backup.episodes}
    changed = [e.plot.number for e in p.episodes if e.text and old.get(e.plot.number) != e.text]
    if changed:
        out.append(f"전환한 뒤 쓰거나 고친 본문이 있습니다 ({changed}화)")
    return out


def undo_conversion(p: Project, backup: Project) -> Project:
    """전환 전 작품을 돌려준다. 잃는 것이 있으면 막는다."""
    why = undo_blockers(p, backup)
    if why:
        raise ValueError("되돌릴 수 없습니다: " + " / ".join(why))
    return backup.model_copy(deep=True, update={"conversion": None})


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
        hint={"message": message, "arc": (focus_arc(p).acts if p.serial and p.story_arcs else p.arc),
              "episodes": [e.plot for e in p.episodes], "total": p.meta.target_episodes, "serial": p.serial},
    )
    return clean_revision(p, rev)


def focus_arc(p: Project) -> StoryArc | None:
    """장편 플롯 대화가 구조를 고치는 아크: 아직 본문이 없는 화가 있는 첫 아크, 없으면 마지막 아크."""
    status = {e.plot.number: e.status for e in p.episodes}
    arcs = sorted(p.story_arcs, key=lambda s: s.start_ep)
    for a in arcs:
        if any(status.get(n, "draft") not in LOCKED for n in range(a.start_ep, a.end_ep + 1)):
            return a
    return arcs[-1] if arcs else None


def clean_revision(p: Project, rev: PlotRevision) -> PlotRevision:
    notes: list[str] = []
    if p.serial and rev.total_episodes:
        notes.append("장편은 총 화수를 부 구성에서 바꿔서 화수 변경을 뺐습니다.")
        rev.total_episodes = 0
    total = rev.total_episodes if rev.total_episodes and rev.total_episodes != p.meta.target_episodes else 0
    if total and not 1 <= total <= 100:
        notes.append(f"총 화수 {total}화는 쓸 수 없어 뺐습니다.")
        total = 0
    rev.total_episodes = total
    focus = focus_arc(p) if p.serial else None
    current_acts = focus.acts if focus else p.arc
    acts = sorted(rev.acts, key=lambda a: a.start_ep)
    if acts and [a.model_dump() for a in acts] == [a.model_dump() for a in current_acts] and not total:
        acts = []
    if acts and p.serial and focus is None:
        notes.append("아직 아크가 없어 구조 변경을 뺐습니다.")
        acts = []
    if acts:
        try:
            if focus:
                validate_arc(ArcPlan(acts=acts), focus.end_ep, focus.start_ep)
            else:
                validate_arc(ArcPlan(acts=acts), total or p.meta.target_episodes)
        except ValueError as e:
            notes.append(f"구조 변경안이 맞지 않아 뺐습니다: {e}")
            acts = []
    if total and not acts:
        notes.append("화수를 바꾸려면 구조도 함께 바꿔야 해서 화수 변경을 뺐습니다.")
        rev.total_episodes = total = 0
    rev.acts = acts
    if focus:
        arc = [a for a in p.beats() if not focus.start_ep <= a.start_ep <= focus.end_ep] + acts if acts else p.beats()
        last = p.planned_until()
    else:
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
        cur = current.get(n)
        if cur and (cur["storyline"] or cur["threads"]) and not (e.storyline or e.threads):
            e.storyline, e.threads = cur["storyline"], list(cur["threads"])  # 작가가 붙인 줄기는 AI 가 빠뜨려도 지키기
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
    focus = focus_arc(p) if p.serial else None
    if acts and rev.acts:
        if focus:
            validate_arc(ArcPlan(acts=rev.acts), focus.end_ep, focus.start_ep)
        else:
            total = rev.total_episodes or total
            validate_arc(ArcPlan(acts=rev.acts), total)
        arc = [a.model_copy(deep=True) for a in rev.acts]
    if p.serial:
        total = p.planned_until()
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
        if focus:
            focus.acts = arc
        else:
            p.arc = arc
            p.meta.target_episodes = total
        for n in cut:
            del by_no[n]
        applied.append("acts")
    for n, plot in picked.items():
        by_no[n] = Episode(plot=plot.model_copy(deep=True))  # 확정된 화도 내용이 바뀌면 다시 확정한다
        storylines.clean_plot(p, by_no[n])
        applied.append(str(n))
    p.episodes = [by_no[k] for k in sorted(by_no)]
    for e in p.episodes:
        act = p.act_for(e.plot.number)
        if act and e.status not in LOCKED:
            e.plot.act = act.name
    return applied


# ---------- 3-2. 이야기 줄기: 메인에서 갈라지는 서브플롯 · 회상 · 외전 ----------

def suggest_storyline(llm: LLM, p: Project, note: str = "", kind: str = "") -> StorylineProposal:
    """이야기 줄기 하나와 그 줄기가 들어갈 화를 제안한다. 저장하지 않는다."""
    prop = llm.json(prompts.SYSTEM_PLANNER, prompts.storyline_prompt(p, note, kind), StorylineProposal,
                    hint={"note": note, "kind": kind, "episodes": [e.plot.number for e in p.episodes],
                          "characters": [c.id for c in p.characters], "id": storylines.new_id(p)})
    return clean_storyline(p, prop)


def clean_storyline(p: Project, prop: StorylineProposal) -> StorylineProposal:
    """id 를 새로 매기고, 없는 인물과 없는 화, 본문이 있는 화를 뺀다. 뺀 이유는 reply 끝에 붙인다."""
    s = prop.storyline
    s.id = storylines.new_id(p)
    ids = {c.id for c in p.characters}
    notes = []
    gone = [c for c in s.focus if c not in ids]
    if gone:
        s.focus = [c for c in s.focus if c in ids]
        notes.append(f"없는 인물({', '.join(gone)})은 중심 인물에서 뺐어요.")
    have = {e.plot.number: e for e in p.episodes}
    locked = sorted({n for n in prop.episodes + prop.threads if n in have and have[n].text})
    missing = sorted({n for n in prop.episodes + prop.threads if n not in have})
    prop.episodes = sorted({n for n in prop.episodes if n in have and not have[n].text})
    prop.threads = sorted({n for n in prop.threads if n in have and not have[n].text and n not in prop.episodes})
    if locked:
        notes.append(f"본문이 있는 화({', '.join(map(str, locked))})는 붙이지 않았어요. 필요하면 직접 표시하세요.")
    if missing:
        notes.append(f"아직 플롯이 없는 화({', '.join(map(str, missing))})는 뺐어요. 플롯을 만든 뒤 붙이세요.")
    total = p.meta.target_episodes
    s.branch_ep = s.branch_ep if 0 < s.branch_ep <= total else 0
    s.join_ep = s.join_ep if 0 < s.join_ep <= total and s.join_ep >= s.branch_ep else 0
    if notes:
        prop.reply = (prop.reply + " " + " ".join(notes)).strip()
    return prop


def apply_storyline(p: Project, prop: StorylineProposal, episodes: list[int] | None = None,
                    threads: list[int] | None = None) -> Storyline:
    """줄기를 더하고 고른 화에 붙인다. 플롯 내용은 바꾸지 않으므로 확정된 화도 확정 상태를 지킨다."""
    s = prop.storyline.model_copy(deep=True)
    if not s.id or p.storyline(s.id):
        s.id = storylines.new_id(p)
    if not s.title.strip():
        raise ValueError("줄기 이름을 적으세요")
    episodes = prop.episodes if episodes is None else episodes
    threads = prop.threads if threads is None else threads
    have = {e.plot.number for e in p.episodes}
    missing = sorted({n for n in episodes + threads if n not in have})
    if missing:
        raise ValueError(f"플롯이 없는 화({', '.join(map(str, missing))})에는 줄기를 붙일 수 없습니다. 플롯을 먼저 만드세요")
    p.storylines.append(s)
    for n in episodes:
        storylines.tag(p, n, s.id, "main")
    for n in threads:
        storylines.tag(p, n, s.id, "thread")
    return s


def validate_storylines(p: Project) -> None:
    """줄기 id 가 겹치지 않고, 화에 붙은 줄기가 모두 있는지 본다 (화면 저장용)."""
    ids = [s.id for s in p.storylines]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup or "" in ids:
        raise ValueError(f"이야기 줄기 id 가 비었거나 겹칩니다: {', '.join(dup) or '빈 id'}")
    for e in p.episodes:
        bad = [x for x in [e.plot.storyline, *e.plot.threads] if x and x not in ids]
        if bad:
            raise ValueError(f"{e.plot.number}화에 없는 이야기 줄기가 붙어 있습니다: {', '.join(bad)}")


def remove_storyline(p: Project, sid: str) -> None:
    """줄기를 지우고 붙은 화를 메인으로 되돌린다. 본문은 그대로다."""
    storylines.get(p, sid)
    storylines.untag_all(p, sid)
    p.storylines = [s for s in p.storylines if s.id != sid]


# ---------- 3-3. 인과율: 새 요소가 닿는 곳 ----------

def analyze_impact(llm: LLM, p: Project, eid: str) -> ImpactReport:
    """요소 하나의 영향 보고서를 만든다. 저장하지 않는다. 근거를 찾을 수 없는 지적은 뺀다."""
    el = elements.get(p, eid)
    if not el.name.strip() or not el.description.strip():
        raise ValueError("요소의 이름과 설명을 먼저 적으세요")
    linked = {lk.episode for lk in elements.links(p, el)}
    rep = llm.json(
        prompts.SYSTEM_IMPACT, prompts.impact_prompt(p, el, linked), ImpactReport,
        hint={"element": el, "episodes": p.episodes},
    )
    return clean_impact(p, rep)


def _quoted(p: Project, target: str, n: int, quote: str) -> bool:
    """지적의 인용이 실제로 그 자리에 있는가."""
    if target == "본문":
        e = next((e for e in p.episodes if e.plot.number == n), None)
        return bool(e and elements.find(e.text, quote))
    if target == "플롯":
        e = next((e for e in p.episodes if e.plot.number == n), None)
        return bool(e and elements.find(elements.plot_text(e), quote))
    if target == "확정 사실":
        return bool(elements.find("\n".join(p.facts), quote))
    setting = p.model_dump(include={"meta": True, "world": True, "characters": True, "relationships": True, "secrets": True,
                                    "elements": {"__all__": {"name", "aliases", "description"}},
                                    "parts": True, "story_arcs": {"__all__": {"title", "goal", "conflict", "payoff", "summary"}}})
    return bool(elements.find("\n".join(_strings(setting)), quote))


def _strings(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        v = v.values()
    return [s for x in v for s in _strings(x)] if isinstance(v, (list, tuple, type({}.values()))) else []


def clean_impact(p: Project, rep: ImpactReport) -> ImpactReport:
    notes: list[str] = []
    keep = [c for c in rep.conflicts if _quoted(p, c.target, c.episode, c.quote)]
    if len(keep) < len(rep.conflicts):
        notes.append(f"원문에서 인용을 찾지 못한 지적 {len(rep.conflicts) - len(keep)}개는 뺐습니다.")
    rep.conflicts = keep
    patches, seen = [], set()
    for t in rep.patches:
        e = next((e for e in p.episodes if e.plot.number == t.episode), None)
        if not e or not e.text or not elements.find(e.text, t.quote):
            notes.append(f"{t.episode}화 본문에서 '{t.quote[:20]}' 문장을 찾지 못해 그 수정안은 뺐습니다.")
            continue
        if t.replacement.strip() == t.quote.strip() or (t.episode, t.quote) in seen:
            continue
        seen.add((t.episode, t.quote))
        patches.append(t)
    rep.patches = patches
    rep.new_facts = [f for f in dict.fromkeys(x.strip() for x in rep.new_facts) if f and f not in p.facts]
    rev = clean_revision(p, PlotRevision(reply=rep.summary, episodes=rep.episodes))
    rep.summary, rep.episodes = rev.reply, rev.episodes
    if notes:
        rep.summary = rep.summary.rstrip() + "\n\n※ " + " ".join(notes)
    return rep


def record_impact(p: Project, eid: str, rep: ImpactReport) -> None:
    el = elements.get(p, eid)
    el.impact = ElementImpact(report=rep, basis=elements.basis(el), at=elements.now())


def apply_impact(p: Project, eid: str, episodes: list[int], patches: list[int], facts: list[int]) -> list[str]:
    """영향 보고서에서 고른 부분만 반영한다. 플롯은 apply_revision 규칙을 따르고(본문 있는 화는 그대로,
    확정된 화는 초안으로), 본문 수정은 인용한 문장이 지금 본문에 그대로 있을 때만 바꾼다."""
    el = elements.get(p, eid)
    imp = el.impact
    if imp is None:
        raise ValueError("영향 분석을 먼저 하세요")
    if imp.outcome:
        raise ValueError("이미 처리한 영향 분석입니다. 다시 분석하세요")
    rep = imp.report
    if not (episodes or patches or facts):
        raise ValueError("반영할 부분을 고르세요")
    texts: dict[int, str] = {}
    for i in patches:
        if not 0 <= i < len(rep.patches):
            raise ValueError(f"본문 수정안 {i} 이 없습니다")
        t = rep.patches[i]
        ep = p.episode(t.episode)
        cur = texts.get(t.episode, ep.text)
        span = elements.find(cur, t.quote)
        if span is None:
            raise ValueError(f"{t.episode}화 본문이 그 사이 바뀌어 '{t.quote[:20]}' 문장을 찾을 수 없습니다. 다시 분석하세요")
        texts[t.episode] = cur[:span[0]] + t.replacement.strip() + cur[span[1]:]
    applied: list[str] = []
    if episodes:
        done = apply_revision(p, PlotRevision(reply="", episodes=rep.episodes), False, episodes)
        applied += [f"ep:{n}" for n in done]
    for n, text in texts.items():
        p.episode(n).text = text  # 상태 반영이 끝난 화도 작가가 고르면 고친다. 요약과 인물 상태는 그대로 둔다
    applied += [f"patch:{i}" for i in patches]
    for i in facts:
        if 0 <= i < len(rep.new_facts) and rep.new_facts[i] not in p.facts:
            p.facts.append(rep.new_facts[i])
            applied.append(f"fact:{i}")
    imp.outcome, imp.applied = "applied", applied
    return applied


def dismiss_impact(p: Project, eid: str) -> None:
    imp = elements.get(p, eid).impact
    if imp and not imp.outcome:
        imp.outcome = "dismissed"


# ---------- 4. 본문 생성 ----------
# 본문의 글자 중 한글이 이보다 적으면 모델이 생각 과정이나 다른 언어를 낸 것으로 보고 다시 쓴다.
# 연구에서 Gemini 4 Argon 이 92번 중 1번 영어 생각 과정을 본문으로 냈다.
HANGUL_MIN = 0.8
WRITE_TRIES = 3


def write_episode(llm: LLM, p: Project, n: int) -> str:
    ep = p.episode(n)
    if ep.status == "draft":
        raise ValueError(f"{n}화 플롯이 아직 확정되지 않았습니다 (confirm 먼저)")
    unfinished = [e.plot.number for e in p.episodes if e.plot.number < n and e.status != "finalized"]
    if unfinished:
        raise ValueError(f"이전 화의 상태 갱신이 끝나지 않았습니다: {unfinished}")
    system, prompt = prompts.writer_system(p), prompts.episode_prompt(p, n)
    for _ in range(WRITE_TRIES):
        text = llm.text(system, prompt)
        if metrics.hangul_ratio(text) >= HANGUL_MIN:
            return text
    raise ValueError(f"{n}화 본문 대신 다른 글(영어로 된 생각 과정 등)이 {WRITE_TRIES}번 나왔습니다. 다시 시도해 주세요")


def compare_drafts(llms: dict[str, LLM], p: Project, n: int) -> dict[str, str]:
    """같은 화를 여러 백엔드로 쓴다. 프롬프트는 write_episode 와 같다. 저장은 호출자가 한다."""
    return {name: write_episode(llm, p, n) for name, llm in llms.items()}


def adopt_draft(p: Project, n: int, text: str) -> None:
    """비교에서 고른 본문을 그 화의 본문으로 쓴다. 상태 반영이 끝난 화는 되돌린 뒤에만 바꾼다."""
    ep = p.episode(n)
    if ep.status == "finalized":
        raise ValueError(f"{n}화는 상태 반영이 끝났습니다. 바꾸려면 revert {n - 1} 후 다시 하세요")
    ep.text, ep.status = text, "written"


# ---------- 4-1. 본문 부분 수정 ----------
# 작가가 본문에서 고른 부분을 직접 고치거나 AI 후보로 바꾼다. 고칠 때마다 전후 쌍을 Episode.edits 에 남겨
# 되돌릴 수 있게 하고, 나중에 선호 · 미세 조정 자료로 꺼낼 수 있게 한다 (cli edits --jsonl).

EDIT_KEEP = 50  # 화마다 남기는 수정 기록 수


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _editable(p: Project, n: int) -> Episode:
    ep = p.episode(n)
    if ep.status == "finalized":
        raise ValueError(f"{n}화는 상태 반영까지 끝나 본문을 바꿀 수 없습니다. 바꾸려면 {n - 1}화 반영 직후로 되돌리세요")
    if not ep.text:
        raise ValueError(f"{n}화 본문이 없습니다")
    return ep


def locate(text: str, quote: str, start: int) -> int:
    """quote 가 있는 자리. 본문이 앞에서 바뀌어 위치가 밀렸으면 start 에서 가장 가까운 같은 글을 찾는다."""
    if not quote:
        raise ValueError("고른 부분이 비었습니다")
    if text[start:start + len(quote)] == quote:
        return start
    found, i = [], text.find(quote)
    while i != -1:
        found.append(i)
        i = text.find(quote, i + 1)
    if not found:
        raise ValueError("고른 부분을 본문에서 찾을 수 없습니다. 그사이 본문이 바뀌었을 수 있어요. 다시 골라 주세요")
    return min(found, key=lambda x: abs(x - start))


def _record(ep: Episode, edit: TextEdit) -> TextEdit:
    nums = [int(e.id[1:]) for e in ep.edits if e.id[1:].isdigit()]
    edit.id = f"e{max(nums, default=0) + 1}"
    edit.at = edit.at or _now()
    ep.edits = (ep.edits + [edit])[-EDIT_KEEP:]
    return edit


def edit_text(p: Project, n: int, sel: Selection, after: str, source: str = "manual", instruction: str = "",
              preset: str = "", proposed: str = "", rejected: list[str] | None = None) -> TextEdit:
    """고른 부분(sel)을 after 로 바꾸고 기록을 남긴다."""
    ep = _editable(p, n)
    at = locate(ep.text, sel.text, sel.start)
    if after == sel.text:
        raise ValueError("바뀐 내용이 없습니다")
    ep.text = ep.text[:at] + after + ep.text[at + len(sel.text):]
    return _record(ep, TextEdit(id="", source=source, start=at, before=sel.text, after=after, instruction=instruction,  # type: ignore[arg-type]
                                preset=preset, proposed=proposed if proposed != after else "", rejected=list(rejected or [])))


def record_typed(p: Project, n: int, old: str, new: str) -> TextEdit | None:
    """본문을 통째로 고쳐 저장했을 때 앞뒤가 같은 부분을 빼고 바뀐 곳만 기록한다. 처음 쓰거나 지운 것은 기록하지 않는다."""
    if not old or not new or old == new:
        return None
    a = 0
    while a < min(len(old), len(new)) and old[a] == new[a]:
        a += 1
    b = 0
    while b < min(len(old), len(new)) - a and old[-1 - b] == new[-1 - b]:
        b += 1
    return _record(p.episode(n), TextEdit(id="", source="typed", start=a, before=old[a:len(old) - b], after=new[a:len(new) - b]))


def undo_edit(p: Project, n: int, eid: str) -> TextEdit:
    """수정 하나를 되돌린다. 그 뒤에 같은 자리를 또 고쳤으면 찾지 못해 되돌릴 수 없다."""
    ep = _editable(p, n)
    edit = next((e for e in ep.edits if e.id == eid), None)
    if edit is None:
        raise KeyError(f"수정 기록이 없습니다: {eid}")
    if edit.undone:
        raise ValueError("이미 되돌린 수정입니다")
    if edit.after:
        at = locate(ep.text, edit.after, edit.start)
    elif edit.start <= len(ep.text):  # 지우기만 한 수정은 그 자리에 다시 넣는다
        at = edit.start
    else:
        raise ValueError("되돌릴 자리를 찾을 수 없습니다")
    ep.text = ep.text[:at] + edit.before + ep.text[at + len(edit.after):]
    edit.undone = True
    return edit


def revise_passage(llm: LLM, p: Project, n: int, sel: Selection, message: str = "", preset: str = "") -> PassageRevision:
    """고른 부분의 고친 후보를 만든다. 저장하지 않는다. 원문과 같거나 겹치는 후보는 뺀다."""
    if preset and preset not in prompts.PASSAGE_PRESETS:
        raise ValueError(f"모르는 빠른 요청입니다: {preset}")
    if not message.strip() and not preset:
        raise ValueError("무엇을 바꿀지 적거나 빠른 요청을 고르세요")
    ep = _editable(p, n)
    sel = Selection(start=locate(ep.text, sel.text, sel.start), text=sel.text)
    rev = llm.json(prompts.reviser_system(p), prompts.passage_prompt(p, n, sel, message, preset), PassageRevision,
                   hint={"selection": sel.text, "preset": preset, "message": message})
    keep, seen = [], {sel.text.strip()}
    for c in rev.candidates:
        c.text = c.text.strip().replace("【고칠 부분】", "").replace("【여기까지】", "")
        if c.text and c.text not in seen:
            seen.add(c.text)
            keep.append(c)
    rev.candidates = keep[:3]
    if not keep:
        rev.reply = rev.reply.rstrip() + "\n\n※ 원문과 다른 후보가 없었어요. 요청을 조금 더 구체적으로 적어 주세요."
    return rev


def record_passage(p: Project, n: int, sel: Selection, message: str, preset: str, rev: PassageRevision) -> ChatMessage:
    """작가의 요청과 AI 후보를 그 화의 부분 수정 대화('text:<화>')에 남긴다."""
    now = _now()
    chat = p.chat(f"text:{n}")
    label = prompts.PASSAGE_PRESETS[preset][0] if preset in prompts.PASSAGE_PRESETS else ""
    user = ChatMessage(role="user", text=message.strip() or label, selection=sel, preset=preset, at=now)
    reply = ChatMessage(role="assistant", text=rev.reply, passage=rev if rev.candidates else None, selection=sel,
                        preset=preset, at=now)
    chat.messages += [user, reply]
    chat.messages = chat.messages[-CHAT_KEEP:]
    return reply


def apply_passage(p: Project, n: int, i: int, k: int, text: str | None = None) -> TextEdit:
    """부분 수정 대화의 i 번째 메시지에서 k 번째 후보를 본문에 넣는다. text 를 주면 작가가 손본 글을 넣는다."""
    msgs = p.chat(f"text:{n}").messages
    if not 0 <= i < len(msgs) or msgs[i].passage is None or msgs[i].selection is None:
        raise KeyError("후보가 있는 메시지가 아닙니다")
    m = msgs[i]
    if m.outcome:
        raise ValueError("이미 처리한 후보입니다")
    cands = m.passage.candidates
    if not 0 <= k < len(cands):
        raise ValueError("후보 번호가 맞지 않습니다")
    user = next((x for x in reversed(msgs[:i]) if x.role == "user"), None)
    after = (text if text is not None else cands[k].text).strip()
    if not after:
        raise ValueError("넣을 글이 비었습니다")
    edit = edit_text(p, n, m.selection, after, "ai", instruction=user.text if user else "", preset=m.preset,
                     proposed=cands[k].text, rejected=[c.text for j, c in enumerate(cands) if j != k])
    m.outcome, m.applied = "applied", [str(k)]
    return edit


# ---------- 5. 검수 (모순 찾기, 문체 지표) ----------

def check_episode(llm: LLM, p: Project, n: int) -> ConsistencyReport:
    if not p.episode(n).text:
        raise ValueError(f"{n}화 본문이 없습니다")
    report = llm.json(prompts.SYSTEM_CHECKER, prompts.check_prompt(p, n), ConsistencyReport, hint={"episode": n})
    report.episode = n
    return report


def apply_check(p: Project, r: ConsistencyReport) -> None:
    """검수 결과는 참고용 경고라 승인 없이 화에 붙여 둔다. 다시 검수하면 덮어쓴다."""
    ep = p.episode(r.episode)
    ep.issues, ep.checked_at = r.issues, _now()


def style_baseline(p: Project) -> metrics.StyleMetrics:
    """레퍼런스 원문 전체로 잰 값이 없으면(예전 프로젝트) 발췌 문단으로 잰다."""
    return p.style_baseline or metrics.measure("\n\n".join(p.style.sample_passages))


def style_drift(p: Project, n: int) -> tuple[metrics.StyleMetrics, list[str]]:
    """이번 화 문체 지표와 경고. 기준값과의 차이, 문체 거리, 표지 빈도, 예시 문단 베끼기를 본다."""
    text = p.episode(n).text
    base = style_baseline(p)
    cur = metrics.measure(text, p.style.banned_phrases)
    cur.style_distance = metrics.style_distance(base, text)
    warns = metrics.drift(base, cur)
    marks = metrics.marker_warnings(p.style.markers, text)
    if marks:
        warns.append(f"문체 표지: {', '.join(marks)}")
    copied = metrics.copied_sentences(text, p.style.sample_passages)
    if copied:
        quotes = ", ".join(f"'{s[:30]}{'…' if len(s) > 30 else ''}'" for s in copied[:3])
        warns.append(f"예시 문단을 옮긴 문장 {len(copied)}개: {quotes}")
    return cur, warns


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
    _add_characters(p, d.new_characters, d.episode)
    ep.auto = False  # 자동 집필은 반영한 뒤 True 로 표시한다

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
    if p.serial:
        prune_snapshots(p)


SNAPSHOT_KEEP = 20  # 장편에서 남기는 최근 스냅샷 수. 시작점과 아크가 끝난 화는 늘 남긴다


def prune_snapshots(p: Project) -> None:
    """장편은 화마다 상태 전체를 복사하면 project.json 이 너무 커진다. 관계는 사건 로그로 다시 계산할 수 있다."""
    ends = {a.end_ep for a in p.story_arcs}
    recent = sorted(s.episode for s in p.snapshots)[-SNAPSHOT_KEEP:]
    keep = {0, *ends, *recent}
    p.snapshots = [s for s in p.snapshots if s.episode in keep]


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
            ep.status, ep.summary, ep.auto = "written", "", False


def recalc(p: Project) -> None:
    """계수(params)를 바꾼 뒤 사건 로그를 처음부터 다시 재생해 현재 관계를 다시 계산한다."""
    p.ties = dynamics.replay(p)
    dynamics.sync_relationships(p)
