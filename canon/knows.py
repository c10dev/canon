"""인물이 아는 정보(CharacterState.knows): 알게 된 화와 아크 요약 뒤 접기. LLM 을 부르지 않는다 (접기 제안은 pipeline.fold_knows).

knows 는 반영마다 뒤에 붙기만 해서 장편에서 끝없이 는다. 실제 장편 83화에서 주인공 하나가 300개였고, 쓰기 프롬프트에는
인물마다 20개(context.KNOWS_KEEP)만 들어가 93%가 빠졌다 (2026-10-30 인물 진단). 빠지는 것은 이번 화와 글자가 겹치지 않는 옛 정보라,
글자는 달라도 뒤 화 행동의 기준인 것(정체, 약속, 위험)이 사라진다.

- 알게 된 화(learned): 반영 기록(history)의 character_updates.knows 를 따라가 줄마다 처음 들어온 화를 센다. 저장하지 않는다.
  장편 프롬프트는 고른 줄 앞에 '(n화)'를 붙인다(view). 상태 변경안이 이 표시를 따라 적으면 정리(clean_delta)가 뗀다.
- 접기: 아크 요약이 있는 아크에서, 그 아크 끝까지 알게 된 줄 가운데 최근 KNOWS_RECENT 개를 뺀 것이 KNOWS_KEEP 개를 넘는 인물만
  AI 가 몇 줄(FOLD_LINES)로 접자고 제안한다. 작가가 인물마다 골라 적용하면 그 줄을 knows 에서 빼고 CharacterState.knows_folded 에 둔다(apply_fold).
  기록(Project.knows_folds)으로 마지막 접기를 되돌린다(undo_fold). 반영 취소로 스냅샷이 접기 전으로 돌아가면 기록을 지운다(revert).
  프롬프트는 접은 줄을 늘 knows 앞에 넣는다.
"""
from __future__ import annotations

import re

from . import context
from .schema import CharacterState, KnowsFold, KnowsFoldRecord, KnowsFoldSet, Project, StateDelta, StoryArc

FOLD_LINES = 8  # 인물 하나를 접은 뒤 남길 줄 수
FOLD_LINE_MAX = 120  # 접은 줄 하나의 글자
FOLD_MIN = 12  # 접을 줄이 이보다 적으면 접지 않는다 (몇 줄로 줄여도 얻는 것이 없다)
_TAG = re.compile(r"^\s*\((?:\d+화(?:까지 요약)?|요약)\)\s*")  # view 가 붙이는 표시


def learned(p: Project) -> dict[str, dict[str, int]]:
    """{인물 id: {아는 정보: 처음 들어온 화}}. 반영 기록에 없는 줄(설정 단계 상태, 작가가 직접 적은 것)은 0."""
    out: dict[str, dict[str, int]] = {}
    for d in sorted(p.history, key=lambda d: d.episode):
        for u in d.character_updates:
            seen = out.setdefault(u.character_id, {})
            for k in u.knows:
                seen.setdefault(k, d.episode)
    return out


def view(p: Project, s: CharacterState, picked: list[str], eps: dict[str, int] | None = None) -> list[str]:
    """프롬프트에 넣는 knows: 접은 줄(앞) + 고른 줄 앞에 알게 된 화."""
    eps = eps if eps is not None else learned(p).get(s.character_id, {})
    upto = max((r.arc for r in p.knows_folds if r.character_id == s.character_id and r.after == s.knows_folded), default=0)
    arc = next((a for a in p.story_arcs if a.number == upto), None)
    head = f"({arc.end_ep}화까지 요약) " if arc else "(요약) "
    return [head + x for x in s.knows_folded] + [f"({eps[k]}화) {k}" if eps.get(k) else k for k in picked]


def clean_delta(p: Project, d: StateDelta) -> None:
    """정리 훅 (features.CLEAN): 프롬프트가 붙인 '(n화)' 표시를 상태 변경안이 따라 적었으면 뗀다."""
    for u in d.character_updates:
        u.knows = [k for k in (_TAG.sub("", x).strip() for x in u.knows) if k]


# ---------- 접기 ----------

def _arc(p: Project, number: int) -> StoryArc:
    a = next((x for x in p.story_arcs if x.number == number), None)
    if a is None:
        raise ValueError(f"아크 {number}이(가) 없어요")
    return a


def targets(p: Project, number: int) -> dict[str, list[str]]:
    """아크 number 에서 접을 줄: 인물마다 그 아크 끝까지 알게 된 줄 가운데 맨 뒤 KNOWS_RECENT 개(프롬프트에 늘 들어간다)를 뺀 것.
    knows 가 KNOWS_KEEP 개 이하인 인물(접지 않아도 다 들어간다)과 접을 줄이 FOLD_MIN 개보다 적은 인물은 뺀다.
    요약이 없는 아크는 접지 않는다 (요약으로 줄거리를 접은 뒤에 아는 정보도 접는다)."""
    a = _arc(p, number)
    if not a.summary:
        raise ValueError(f"아크 {number} 요약을 먼저 저장하세요")
    eps = learned(p)
    out = {}
    for s in p.states:
        if len(s.knows) <= context.KNOWS_KEEP:
            continue
        when = eps.get(s.character_id, {})
        recent = set(s.knows[-context.KNOWS_RECENT:])
        old = [k for k in s.knows if when.get(k, 0) <= a.end_ep and k not in recent]
        if len(old) >= FOLD_MIN:
            out[s.character_id] = old
    return out


def clean_fold(p: Project, number: int, fs: KnowsFoldSet) -> KnowsFoldSet:
    """접을 줄이 있는 인물만, 줄은 앞뒤 공백 · 표시를 떼고 겹치지 않게 FOLD_LINES 개 · FOLD_LINE_MAX 자까지."""
    want = targets(p, number)
    out: dict[str, KnowsFold] = {}
    for f in fs.folds:
        if f.character_id not in want:
            continue
        lines = []
        for x in f.lines:
            x = _TAG.sub("", x).strip()
            if x and x not in lines:
                lines.append(x if len(x) <= FOLD_LINE_MAX else x[:FOLD_LINE_MAX - 1] + "…")
        if lines:
            out[f.character_id] = KnowsFold(character_id=f.character_id, lines=lines[:FOLD_LINES])
    return KnowsFoldSet(folds=list(out.values()))


def apply_fold(p: Project, number: int, fs: KnowsFoldSet) -> list[KnowsFoldRecord]:
    """작가가 고른 인물의 접기를 적용한다. 접은 줄을 knows 에서 빼고 knows_folded 를 바꾼 뒤 기록한다."""
    fs = clean_fold(p, number, fs)
    want = targets(p, number)
    recs = []
    for f in fs.folds:
        s = p.state_of(f.character_id)
        if s is None:
            continue
        gone = set(want[f.character_id])
        rec = KnowsFoldRecord(arc=number, character_id=f.character_id, removed=[k for k in s.knows if k in gone],
                              before=list(s.knows_folded), after=list(f.lines))
        s.knows = [k for k in s.knows if k not in gone]
        s.knows_folded = list(f.lines)
        p.knows_folds.append(rec)
        recs.append(rec)
    return recs


def undo_fold(p: Project, number: int) -> int:
    """아크 number 의 접기를 되돌린다. 인물마다 마지막 접기만 되돌릴 수 있다. 되돌린 인물 수."""
    recs = [r for r in p.knows_folds if r.arc == number]
    if not recs:
        raise ValueError(f"아크 {number}에서 접은 아는 정보가 없어요")
    for r in recs:
        if any(x.character_id == r.character_id and x.arc > number for x in p.knows_folds):
            raise ValueError(f"아크 {number} 뒤에 다시 접은 인물이 있어요. 뒤 아크의 접기부터 되돌리세요")
    for r in recs:
        s = p.state_of(r.character_id)
        if s is not None:
            s.knows = r.removed + [k for k in s.knows if k not in set(r.removed)]
            s.knows_folded = list(r.before)
    p.knows_folds = [r for r in p.knows_folds if r.arc != number]
    return len(recs)


def revert(p: Project, n: int) -> None:
    """되돌리기 훅 (features.REVERT_LAST): 스냅샷이 접기 전 상태로 돌아갔으면(지금 접은 줄이 기록과 다름) 그 기록을 지운다."""
    keep = []
    for cid in dict.fromkeys(r.character_id for r in p.knows_folds):
        s = p.state_of(cid)
        recs = [r for r in p.knows_folds if r.character_id == cid]
        cut = next((i for i in range(len(recs) - 1, -1, -1) if s is not None and recs[i].after == s.knows_folded), -1)
        keep += recs[:cut + 1]  # 지금 접은 줄과 같은 기록까지 남긴다. 그 뒤 기록은 스냅샷이 되돌린 접기다
    p.knows_folds = [r for r in p.knows_folds if r in keep]
