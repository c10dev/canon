"""단편을 장편 연재로 바꾸기: 이어 쓰기 전환 (CLI convert, 웹 convert 작업). canon/pipeline.py 에서 옮겼다.

pipeline 이 맨 끝에서 이 모듈을 불러 여기서 정한 이름(EXPORTS)을 pipeline 에도 둔다 (pipeline.<이름> 으로 부르는 코드가 그대로 돈다)."""
from __future__ import annotations

from . import prompts
from .llm import LLM
from .schema import Conversion, Episode, Part, Project, SerialConversion, StoryArc
from .pipeline import (  # pipeline 의 공용 도우미
    ARC_MIN,
    LOCKED,
    validate_parts,
    validate_story_arcs,
)

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
        raise ValueError("이미 장편 연재 작품이에요")
    if p.episodes and not p.arc:
        raise ValueError("기승전결 구조 없이 플롯만 있는 작품은 전환할 수 없어요. 구조를 먼저 저장하세요")
    lo, hi = convert_range(p)
    if not lo <= total <= hi:
        raise ValueError(f"장편 총 화수는 {lo}~{hi}화로 정하세요 (단편 {short_end(p)}화 뒤에 아크가 하나 이상 들어가야 해요)")


def propose_conversion(llm: LLM, p: Project, total: int, ending: str = "", note: str = "") -> SerialConversion:
    """단편을 장편으로 늘리는 계획을 제안한다. 저장하지 않는다."""
    if ending not in ("", "keep", "reopen"):
        raise ValueError(f"모르는 결말 처리예요: {ending}")
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

    prop.parts = _clean_parts(prop.parts, total, [prop.arc] if end else [], notes)

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

    prop.tiers = _clean_tiers(p, prop.tiers, notes)

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
        notes.append(f"본문이 있거나 단편 범위 밖인 화({sorted(set(dropped))})의 플롯 변경안은 뺐어요.")
    prop.episodes = [keep[n] for n in sorted(keep)]
    if last_text and prop.ending == "reopen" and not (prop.foreshadows or prop.facts or prop.episodes):
        notes.append("결말을 다시 열 장치(떡밥, 사실, 플롯 수정)가 없어요. 다시 제안받거나 전환한 뒤 인과율에서 더하세요.")
    if notes:
        prop.reply = (prop.reply.rstrip() + "\n\n※ " + " ".join(notes)).strip()
    return prop


def _clean_parts(parts: list[Part], total: int, arcs: list[StoryArc], notes: list[str]) -> list[Part]:
    """번호와 양 끝을 맞춘다. 빈틈이 있거나 아크가 부 경계를 넘으면 빼고 이유를 notes 에 남긴다."""
    parts = sorted(parts, key=lambda x: x.start_ep)
    for i, x in enumerate(parts, 1):
        x.number, x.summary = i, ""
    if parts:
        parts[0].start_ep = 1
        parts[-1].end_ep = total  # 마지막 부가 총 화수와 조금 어긋나는 것은 맞춰 준다
    try:
        validate_parts(parts, total)
        for a in arcs:
            x = next((x for x in parts if x.start_ep <= a.start_ep <= x.end_ep), None)
            if x and a.end_ep > x.end_ep:
                raise ValueError(f"{x.number}부가 {x.end_ep}화에서 끝나 아크 {a.number}({a.end_ep}화까지)을 품지 못해요")
    except ValueError as e:
        notes.append(f"부 구성이 맞지 않아 뺐어요: {e}. 전환한 뒤 부 구성을 다시 제안받으세요.")
        parts = []
    return parts


def _clean_tiers(p: Project, tiers: list, notes: list[str]) -> list:
    tier = {c.id: c.tier for c in p.characters}
    tiers = [t for t in {t.id: t for t in tiers}.values() if t.id in tier and t.tier != tier[t.id]]
    after = tier | {t.id: t.tier for t in tiers}
    if not any(v == "main" for v in after.values()) and tiers:
        notes.append("주역이 한 명도 남지 않아 비중 조정을 뺐어요.")
        tiers = []
    return tiers


def _stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def ep_list(nums: list[int], most: int = 4) -> str:
    """화 번호를 '1, 3~5화' 처럼 잇는다. 묶음이 많으면 '49~60, 62화 등 14화' 처럼 줄인다."""
    runs: list[list[int]] = []
    for n in sorted(set(nums)):
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    text = ", ".join(f"{a}~{b}" if a != b else f"{a}" for a, b in runs[:most])
    return f"{text}화 등 {len(set(nums))}화" if len(runs) > most else f"{text}화"


def undo_blockers(p: Project, backup: Project | None) -> list[str]:
    """전환을 되돌리면 잃는 것이 있으면 그 이유. 비면 되돌려도 된다."""
    if p.conversion is None:
        return ["단편에서 전환한 작품이 아니에요"]
    if backup is None:
        return ["전환 전 백업(before-serial.json)이 없어요"]
    out = []
    eps = undo_blocker_eps(p, backup)
    if eps["applied"]:
        out.append(f"전환한 뒤 상태를 반영한 화가 있어요 ({ep_list(eps['applied'])})")
    if eps["changed"]:
        out.append(f"전환한 뒤 쓰거나 고친 본문이 있어요 ({ep_list(eps['changed'])})")
    return out


def undo_blocker_eps(p: Project, backup: Project) -> dict[str, list[int]]:
    """되돌리기를 막는 화 번호. applied: 전환한 뒤 상태를 반영한 화, changed: 전환한 뒤 쓰거나 고친 본문이 있는 화."""
    assert p.conversion is not None
    applied = sorted({d.episode for d in p.history[p.conversion.history:]})
    if p.conversion.mode == "rebuild":  # 재구성은 화 번호가 바뀌므로 옛 본문 어느 것과도 같지 않은 본문을 찾는다
        texts = {e.text for e in backup.episodes}
        changed = [e.plot.number for e in p.episodes if e.text and e.text not in texts]
    else:
        old = {e.plot.number: e.text for e in backup.episodes}
        changed = [e.plot.number for e in p.episodes if e.text and old.get(e.plot.number) != e.text]
    return {"applied": applied, "changed": changed}


def undo_conversion(p: Project, backup: Project) -> Project:
    """전환 전 작품을 돌려준다. 잃는 것이 있으면 막는다."""
    why = undo_blockers(p, backup)
    if why:
        raise ValueError("되돌릴 수 없어요: " + " / ".join(why))
    return backup.model_copy(deep=True, update={"conversion": None, "archive": None})


EXPORTS = (
    "BACKUP_TAG",
    "CONVERT_MAX",
    "_clean_parts",
    "_clean_tiers",
    "_stamp",
    "apply_conversion",
    "check_convertible",
    "clean_conversion",
    "convert_range",
    "ep_list",
    "propose_conversion",
    "short_end",
    "undo_blocker_eps",
    "undo_blockers",
    "undo_conversion",
)
