"""오래 나오지 않은 인물의 화면 밖 근황 (CharacterState.offscreen). 장편 전용. LLM 을 부르지 않는다 (제안은 pipeline.plan_offscreen).

장편에서 조연이 수십 화 빠졌다가 돌아오면 쓰기 프롬프트에는 마지막으로 나온 화 요약 한 문장만 들어가고(prompts.return_lines),
그동안 무엇을 했는지는 본문 모델이 그 자리에서 지어낸다. 다음 아크를 기획하기 전에 context.RETURN_GAP 화 넘게 나오지 않은 인물(targets)의
근황을 AI 가 제안하고, 작가가 인물마다 골라 적용하면(apply) offscreen 에 시점 화(offscreen_ep)와 함께 둔다.

- 쓰기: 그 인물이 다시 나오는 화의 '오랜만에 다시 나오는 인물' 줄에 시점 화와 함께 붙는다 (prompts.return_lines).
  아크 중간에 돌아오면 근황이 낡았을 수 있어 시점 화를 늘 함께 보인다.
- 다음 아크 기획: 근황이 있는 인물을 한 줄씩 넣는다 (listed, OFFSCREEN_MAX 명까지, 넘으면 뺀 수를 적는다).
- 그 인물이 나온 화를 반영하면 비운다 (반영 훅 apply_delta). 반영 취소는 스냅샷이 상태와 함께 되돌린다.

notes 와의 차이: notes 는 상태 변경안이 화마다 고치는 메모이고 인물 현재 상태 칸으로 늘 프롬프트에 들어간다.
offscreen 은 작가가 고른 공백기 이야기라 상태 변경안 응답 형식에 없고(SkipJsonSchema), 상태 칸 직렬화에서도 빠진다.
"""
from __future__ import annotations

from . import context
from .schema import CharacterState, OffscreenLine, OffscreenSet, Project, StateDelta

OFFSCREEN_MAX = 8  # 한 번에 근황을 묻는 인물 수와 다음 아크 기획에 넣는 근황 수
TEXT_MAX = 200  # 근황 한 줄의 글자
_TIER = {"main": 0, "support": 1, "minor": 2}


def start(p: Project) -> int:
    """다음 아크가 시작하는 화 (pipeline.next_arc_start 와 같다)."""
    return p.planned_until() + 1


def targets(p: Project, n: int | None = None) -> tuple[dict[str, int], int]:
    """n화(기본: 다음 아크 시작 화) 앞에서 RETURN_GAP 화 넘게 나오지 않은 인물 {id: 마지막으로 나온 화}와 수가 넘쳐 뺀 인물 수.
    나온 적 없는 인물, '넣지 않음' 인물, n화 앞 아직 본문이 없는 플롯(이미 기획한 화)에 든 인물은 뺀다.
    주역 → 조연 → 단역, 같은 비중이면 최근에 나온 인물부터 OFFSCREEN_MAX 명."""
    n = n or start(p)
    planned = {cid for e in p.episodes if e.plot.number < n and not e.text for cid in e.plot.characters}
    ids = {c.id for c in p.characters} - context.off_ids(p) - planned
    gap = {cid: m for cid, m in context.last_seen(p, ids, n).items() if n - m >= context.RETURN_GAP}
    tier = {c.id: _TIER.get(c.tier, 3) for c in p.characters}
    order = sorted(gap, key=lambda cid: (tier[cid], -gap[cid], cid))
    return {cid: gap[cid] for cid in order[:OFFSCREEN_MAX]}, max(0, len(order) - OFFSCREEN_MAX)


def _trim(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= TEXT_MAX else text[:TEXT_MAX - 1] + "…"


def clean(p: Project, s: OffscreenSet, want: dict[str, int] | None = None) -> OffscreenSet:
    """제안을 다듬는다: want(기본 targets) 인물만, 인물마다 첫 줄 하나, 공백을 줄이고 TEXT_MAX 자까지, 빈 줄은 뺀다."""
    want = want if want is not None else targets(p)[0]
    out: dict[str, OffscreenLine] = {}
    for x in s.lines:
        text = _trim(x.text)
        if x.character_id in want and text and x.character_id not in out:
            out[x.character_id] = OffscreenLine(character_id=x.character_id, text=text, kind=x.kind)
    return OffscreenSet(lines=[out[cid] for cid in want if cid in out])


def apply(p: Project, s: OffscreenSet, at: int | None = None) -> int:
    """작가가 고르고 고친 근황을 저장한다. at 은 시점 화 (기본: 다음 아크 시작 화 바로 앞 화). 저장한 인물 수.
    상태가 없는 인물은 빈 상태를 만든다. 없는 인물 id 와 빈 줄은 건너뛴다."""
    at = at if at is not None else start(p) - 1
    have = {c.id for c in p.characters}
    done = 0
    for x in s.lines:
        text = _trim(x.text)
        if x.character_id not in have or not text:
            continue
        st = p.state_of(x.character_id)
        if st is None:
            st = CharacterState(character_id=x.character_id)
            p.states.append(st)
        st.offscreen, st.offscreen_ep = text, at
        done += 1
    return done


def clear(p: Project, cid: str) -> bool:
    """인물 cid 의 근황을 지운다. 지울 근황이 없었으면 False."""
    st = p.state_of(cid)
    if st is None or not st.offscreen:
        return False
    st.offscreen, st.offscreen_ep = "", 0
    return True


def listed(p: Project) -> tuple[list[CharacterState], int]:
    """근황이 있는 인물 상태 (시점 화가 늦은 것부터 OFFSCREEN_MAX 명)와 넘쳐 뺀 수. '넣지 않음' 인물은 뺀다."""
    off = context.off_ids(p)
    have = {c.id for c in p.characters}
    rows = sorted((s for s in p.states if s.offscreen and s.character_id in have and s.character_id not in off),
                  key=lambda s: -s.offscreen_ep)
    return rows[:OFFSCREEN_MAX], max(0, len(rows) - OFFSCREEN_MAX)


def apply_delta(p: Project, d: StateDelta) -> None:
    """반영 훅 (features.APPLY_LAST): 이번 화에 나온 인물(플롯 인물, 본문에 이름이 나옴, 상태 변경안이 다룸)의 근황을 비운다.
    context.last_seen 과 같은 규칙으로 본다. 등장 인물 붙이기(cast.apply_delta) 뒤에 부른다."""
    ep = p.episode(d.episode)
    touched = {u.character_id for u in d.character_updates}
    by_id = {c.id: c for c in p.characters}
    for s in p.states:
        if not s.offscreen:
            continue
        c = by_id.get(s.character_id)
        pat = context.name_pattern(c) if c else None
        if s.character_id in ep.plot.characters or s.character_id in touched or (pat and pat.search(ep.text)):
            s.offscreen, s.offscreen_ep = "", 0
