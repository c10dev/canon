"""단편을 씨앗으로 장편 앞부분을 다시 짜는 재구성 (웹 rebuild 작업). canon/pipeline.py 에서 옮겼다.

pipeline 이 맨 끝에서 이 모듈을 불러 여기서 정한 이름(EXPORTS)을 pipeline 에도 둔다 (pipeline.<이름> 으로 부르는 코드가 그대로 돈다)."""
from __future__ import annotations

from . import charlog, prompts, statwin, storylines
from .llm import LLM
from .schema import ArcPlan, Conversion, Episode, EpisodePlot, Project, RebuildEpisode, Rework, SerialRebuild, ShortArchive, TextEdit
from .pipeline import (  # pipeline 의 공용 도우미
    ARC_MIN,
    _editable,
    record_typed,
    validate_arc,
    validate_story_arcs,
)
from .serialize import _clean_parts
from .serialize import _clean_tiers
from .serialize import _stamp
from .serialize import check_convertible
from .serialize import short_end

# 단편을 씨앗으로 장편 앞부분(아크 몇 개)을 다시 짠다. 새 화마다 옛 화를 그대로 두기(keep), 조금 고치기(revise),
# 재료로 새로 쓰기(rewrite), 새 화(new) 중 하나로 쓴다. 화 번호가 바뀌므로 상태 · 관계는 1화 시작 전으로 돌리고
# 새 순서대로 다시 반영한다. 그대로 둔 화는 옛 상태 변경안을 번호만 바꿔 다시 쓴다 (carried_delta).

REBUILD_MAX_SPAN = 120  # 한 번에 다시 짜는 앞부분 화수 상한 (지도 한 줄이 짧아 이 정도는 한 번에 받는다)


def rebuild_span(p: Project) -> tuple[int, int, int]:
    """재구성할 앞부분 화수의 (최소, 기본, 최대). 옛 화 하나가 보통 새 2~4화가 된다."""
    old = max(len(p.episodes), short_end(p), 1)
    return max(old, ARC_MIN), min(max(old * 3, ARC_MIN * 2), REBUILD_MAX_SPAN), REBUILD_MAX_SPAN


def check_rebuild(p: Project, total: int, span: int = 0, ending_at: str = "") -> int:
    """재구성할 수 있는지 보고 앞부분 화수를 돌려준다 (0 이면 기본값)."""
    if ending_at not in ("", "arc", "part", "series"):
        raise ValueError(f"모르는 결말 위치예요: {ending_at}")
    check_convertible(p, total)
    if not p.episodes:
        raise ValueError("재구성할 단편 화가 없어요. 이어 쓰기로 전환하세요")
    lo, default, hi = rebuild_span(p)
    span = span or default
    if not lo <= span <= min(hi, total):
        raise ValueError(f"다시 짤 앞부분은 {lo}~{min(hi, total)}화로 정하세요")
    return span


def propose_rebuild(llm: LLM, p: Project, total: int, span: int = 0, ending_at: str = "", note: str = "") -> SerialRebuild:
    """단편을 씨앗으로 장편 앞부분을 다시 짠다. 저장하지 않는다."""
    span = check_rebuild(p, total, span, ending_at)
    prop = llm.json(
        prompts.SYSTEM_PLANNER, prompts.rebuild_prompt(p, total, span, ending_at, note), SerialRebuild,
        hint={"total": total, "span": span, "ending_at": ending_at, "old": [(e.plot.number, bool(e.text)) for e in p.episodes]},
    )
    if ending_at:
        prop.ending_at = ending_at  # type: ignore[assignment]
    return clean_rebuild(p, prop, total)


def clean_rebuild(p: Project, prop: SerialRebuild, total: int = 0) -> SerialRebuild:
    """아크가 1화부터 이어지는지 보고, 지도를 1화부터 마지막 아크 끝까지 맞춘다. 쓸 수 없는 부분은 고치거나 빼고 reply 에 적는다."""
    total = total or prop.total_episodes
    check_convertible(p, total)
    prop.total_episodes = total
    notes: list[str] = []
    known = {c.id for c in p.characters}
    arcs = sorted(prop.arcs, key=lambda a: a.start_ep)
    if not arcs:
        raise ValueError("재구성 제안에 아크가 없어요. 다시 제안받으세요")
    expected = 1
    for i, a in enumerate(arcs, 1):
        a.number, a.summary, a.payoffs = i, "", []
        if a.start_ep != expected:
            raise ValueError(f"아크 {i}가 {a.start_ep}화에서 시작해요 ({expected}화부터여야 해요). 다시 제안받으세요")
        validate_arc(ArcPlan(acts=a.acts), a.end_ep, a.start_ep)
        a.acts = sorted(a.acts, key=lambda x: x.start_ep)
        a.cast = [c for c in dict.fromkeys(a.cast) if c in known]
        expected = a.end_ep + 1
    last = expected - 1
    if last > total:
        raise ValueError(f"아크가 {last}화까지 있어 총 {total}화를 넘어요")
    prop.arcs = arcs
    prop.parts = _clean_parts(prop.parts, total, arcs, notes)

    old = {e.plot.number: e for e in p.episodes}
    by_no = {}
    for x in prop.episodes:
        if 1 <= x.number <= last and x.number not in by_no:
            by_no[x.number] = x
    missing = [n for n in range(1, last + 1) if n not in by_no]
    for n in missing:
        by_no[n] = RebuildEpisode(number=n, title=f"{n}화", summary="", use="new")
    if missing:
        notes.append(f"지도에 없던 {missing}화는 새 화로 채웠어요. 플롯 초안에서 채우세요.")
    taken: set[int] = set()
    changed = []
    for n in sorted(by_no):
        x = by_no[n]
        x.sources = [s for s in dict.fromkeys(x.sources) if s in old]
        before = x.use
        if x.use in ("keep", "revise"):
            src = x.sources[0] if len(x.sources) == 1 else None
            if src is None or not old[src].text or src in taken:
                x.use = "rewrite" if x.sources else "new"  # 본문을 그대로 쓸 수 있는 건 옛 화 하나, 한 번뿐이다
            else:
                taken.add(src)
        if x.use == "rewrite" and not x.sources:
            x.use = "new"
        if x.use != before:
            changed.append(n)
    if changed:
        notes.append(f"{changed}화는 옛 본문을 그대로 쓸 수 없어(옛 화가 여럿이거나, 본문이 없거나, 이미 다른 화에 씀) 쓰는 방식을 바꿨어요.")
    kept = [(n, by_no[n].sources[0]) for n in sorted(by_no) if by_no[n].use in ("keep", "revise")]
    if any(a[1] > b[1] for a, b in zip(kept, kept[1:])):
        notes.append("그대로 두거나 다듬는 옛 화의 순서가 바뀐 곳이 있어요. 앞뒤 연결을 검수에서 확인하세요.")
    prop.episodes = [by_no[n] for n in sorted(by_no)]
    used = {s for x in prop.episodes for s in x.sources}
    prop.dropped = sorted((set(prop.dropped) & set(old) - used) | (set(old) - used))

    seen = {f.id for f in p.foreshadows}
    fs = []
    for f in prop.foreshadows:
        if not f.id or f.id in seen or not f.description.strip():
            continue
        seen.add(f.id)
        fs.append(f.model_copy(update={
            "status": "open", "payoff_ep": None, "planted_ep": min(max(f.planted_ep, 1), last),
            "scope": f.scope if f.scope != "arc" else "part",
            "due_ep": f.due_ep if f.due_ep and f.planted_ep < f.due_ep <= total else None,
        }))
    prop.foreshadows = fs
    prop.tiers = _clean_tiers(p, prop.tiers, notes)
    if notes:
        prop.reply = (prop.reply.rstrip() + "\n\n※ " + " ".join(notes)).strip()
    return prop


def _old_to_new(m: list[RebuildEpisode]) -> dict[int, int]:
    """옛 화 → 그 옛 화를 쓰는 첫 새 화. 본문을 그대로 쓰는 화를 먼저 본다."""
    out: dict[int, int] = {}
    for x in sorted(m, key=lambda x: (x.use not in ("keep", "revise"), x.number)):
        for s in x.sources:
            out.setdefault(s, x.number)
    return out


def _remap(old: int, mapping: dict[int, int]) -> int:
    """옛 화 번호를 새 화 번호로. 그 화가 빠졌으면 뒤로 가장 가까운 쓰인 옛 화를 쓴다. 없으면 0."""
    if old <= 0:
        return old
    for o in sorted(k for k in mapping if k >= old):
        return mapping[o]
    return 0


def apply_rebuild(p: Project, prop: SerialRebuild, at: str = "") -> tuple[Project, list[str]]:
    """재구성을 반영한다. 전환 전 작품(백업할 것)과, 옮기지 못해 작가가 볼 것의 목록을 돌려준다."""
    prop = clean_rebuild(p, prop.model_copy(deep=True))
    validate_story_arcs(p.model_copy(update={  # 바꾸기 전에 장편 구조가 맞는지 먼저 본다
        "meta": p.meta.model_copy(update={"form": "serial", "target_episodes": prop.total_episodes}),
        "arc": [], "story_arcs": prop.arcs, "parts": prop.parts}))
    before = p.model_copy(deep=True)
    notes: list[str] = []
    archive = ShortArchive(episodes=[e.model_copy(deep=True) for e in p.episodes], arc=[a.model_copy() for a in p.arc],
                           history=[d.model_copy(deep=True) for d in p.history], map=prop.episodes, dropped=prop.dropped)
    mapping = _old_to_new(prop.episodes)

    # 상태 · 관계는 1화 시작 전으로 (화 번호가 바뀌어 옛 반영 기록을 그대로 둘 수 없다)
    snap = p.snapshot(0)
    if snap is not None:
        p.states = [s.model_copy(deep=True) for s in snap.states]
        p.relationships = [r.model_copy(deep=True) for r in snap.relationships]
        p.ties = [t.model_copy(deep=True) for t in snap.ties]
        p.secrets = [s.model_copy(deep=True) for s in snap.secrets]
        p.facts = list(snap.facts)
        p.foreshadows = [f.model_copy(deep=True) for f in snap.foreshadows]
        p.snapshots = [snap]
    p.events, p.history = [], []
    p.foreshadow_clues = []  # 화 번호가 바뀌어 걸어 둔 문장 자리도 맞지 않는다
    statwin.revert(p, 0)
    charlog.revert(p, 0)  # 그대로 둔 화는 옛 변경안을 다시 반영하며 설정 바꾸기도 새 화 번호로 다시 들어간다
    p.timeline.deadlines = []  # 그대로 둔 화는 옛 변경안을 다시 반영하며 기한도 새 화 번호로 생긴다
    p.foreshadows += prop.foreshadows
    tiers = {t.id: t.tier for t in prop.tiers}
    for c in p.characters:
        c.tier = tiers.get(c.id, c.tier)

    p.meta.form, p.meta.target_episodes = "serial", prop.total_episodes
    p.arc, p.story_arcs, p.parts = [], prop.arcs, prop.parts
    eps = []
    for x in prop.episodes:
        act = p.act_for(x.number)
        src = archive.source(x.sources[0]) if x.sources else None
        if x.use in ("keep", "revise") and src is not None:
            plot = src.plot.model_copy(deep=True, update={"number": x.number, "act": act.name if act else src.plot.act})
            eps.append(Episode(plot=plot, text=src.text, status="written", written_by=src.written_by, meta_cut=src.meta_cut))
        else:
            chars = list(dict.fromkeys(c for s in x.sources if archive.source(s) for c in archive.source(s).plot.characters))
            eps.append(Episode(plot=EpisodePlot(number=x.number, act=act.name if act else "기", title=x.title, summary=x.summary,
                                                events=[], characters=chars, emotional_shift="", ending_hook="")))
    p.episodes = eps
    for e in p.episodes:
        storylines.clean_plot(p, e)

    for el in p.elements:
        moved = {"since_ep": _remap(el.since_ep, mapping), "reveal_ep": _remap(el.reveal_ep, mapping),
                 "episodes": sorted({_remap(n, mapping) for n in el.episodes} - {0})}
        lost = (el.since_ep > 0 and not moved["since_ep"]) or (el.reveal_ep > 0 and not moved["reveal_ep"]) \
            or len(moved["episodes"]) < len(set(el.episodes))
        for k, v in moved.items():
            setattr(el, k, v)
        el.added_after = 0
        if lost:
            notes.append(f"인과율 요소 '{el.name}'의 화 번호 일부를 새 화로 옮기지 못했어요")
    for sl in p.storylines:
        b, j = _remap(sl.branch_ep, mapping), _remap(sl.join_ep, mapping)
        if (sl.branch_ep and not b) or (sl.join_ep and not j):
            notes.append(f"이야기 줄기 '{sl.title}'의 갈라지는 화 · 합류하는 화를 새 화로 옮기지 못했어요")
        sl.branch_ep, sl.join_ep = b, j
    if archive.dropped:
        notes.append(f"쓰지 않는 옛 화: {', '.join(map(str, archive.dropped))}화 (원고는 보관함에 남아요)")
    p.archive = archive
    p.conversion = Conversion(at=at or _stamp(), from_total=before.meta.target_episodes, arc_end=0,
                              ending=prop.ending_at, history=0, mode="rebuild", notes=notes)
    return before, notes




def propose_rework(llm: LLM, p: Project, n: int) -> Rework:
    """'다듬기'로 고른 화의 옛 본문을 새 자리에 맞게 고친다. 저장하지 않는다."""
    x = p.archive.entry(n) if p.archive else None
    ep = _editable(p, n)
    if x is None or x.use != "revise":
        raise ValueError(f"{n}화는 재구성에서 다듬기로 고른 화가 아니에요")
    rw = llm.json(prompts.writer_system(p), prompts.rework_prompt(p, n), Rework, hint={"episode": n, "text": ep.text})
    rw.text = rw.text.strip()
    if not rw.text or rw.text == ep.text:
        raise ValueError("고친 본문이 원문과 같아요. 다듬을 것을 지도에 적고 다시 받으세요")
    return rw


def accept_rework(p: Project, n: int, text: str, proposed: str = "") -> TextEdit | None:
    """다듬은 본문을 넣는다. proposed 는 AI 가 낸 글로, 작가가 손봤으면 수정 기록에 함께 남긴다."""
    ep = _editable(p, n)
    x = p.archive.entry(n) if p.archive else None
    if x is None or x.use != "revise":
        raise ValueError(f"{n}화는 재구성에서 다듬기로 고른 화가 아니에요")
    new = text.strip()
    if not new:
        raise ValueError("본문이 비었어요")
    old = ep.text
    ep.text = new
    edit = record_typed(p, n, old, new)
    if edit is not None:
        edit.source, edit.instruction = "ai", x.note or "재구성 다듬기"
        edit.proposed = proposed.strip() if proposed.strip() and proposed.strip() != new else ""
    return edit


EXPORTS = (
    "REBUILD_MAX_SPAN",
    "_old_to_new",
    "_remap",
    "accept_rework",
    "apply_rebuild",
    "check_rebuild",
    "clean_rebuild",
    "propose_rebuild",
    "propose_rework",
    "rebuild_span",
)
