"""기능 모듈이 상태 변경안의 수명 주기(정리 → 반영 → 되돌리기)에 끼어드는 자리. LLM 호출 없음.

pipeline.clean_delta · apply_delta · revert 가 아래 목록을 차례로 부른다. 상태를 가진 기능을 더할 때는 pipeline 을 고치지 않고
그 기능 모듈에 훅 함수를 두고 여기 목록에 넣는다. 목록 순서가 부르는 순서다. 앞 훅이 바꾼 값을 뒤 훅이 읽을 수 있으니
순서를 바꿀 때는 두 훅이 같은 칸을 읽고 쓰는지 본다 (예: 장소 정리 뒤에 이동 거리 경고).

훅 모양:
- 정리 (p, d) -> 경고 목록 또는 None. 변경안 d 를 고쳐도 된다. 돌려준 경고는 d.warnings 끝에 겹치지 않게 붙는다.
  한 인물에 대한 경고는 (글, 인물 id) 로 돌려준다. id 는 d.warn_to 의 같은 차례에 들어가 상태 승인 화면이 그 인물 줄에 붙인다.
- 반영 (p, d) -> None.
- 되돌리기 (p, n, snap) -> None. snap 은 되돌아갈 n화 스냅샷.
"""
from __future__ import annotations

from typing import Callable

from . import address, attire, blueprint, cast, charlog, context, elements, foreshadows, knows, naming, offscreen, pace, stateedit, statwin, timeline
from .maps import travel
from .schema import FactNear, Project, Snapshot, StateDelta

# 정리 훅이 돌려주는 경고 한 줄: 글, 또는 (글, 그 경고가 다루는 인물 id)
Warn = str | tuple[str, str]


def _untag_facts(p: Project, d: StateDelta) -> None:
    """프롬프트가 장편 사실 줄 앞에 붙인 '(n화)' 표시(prompts.fact_rows)를 새 사실이 따라 적었으면 뗀다. 빈 사실은 뺀다. 단편은 표시를 붙이지 않아 그대로 둔다."""
    if not p.serial:
        return
    d.new_facts = [f for f in (context.FACT_TAG.sub("", x).strip() for x in d.new_facts) if f]


def _near_facts(p: Project, d: StateDelta) -> None:
    """새 사실 가운데 이미 있는 확정 사실과 비슷한 것(context.near_fact)을 d.fact_near 에 적는다. 경고는 내지 않는다.
    상태 승인 화면은 이 사실을 기본으로 체크하지 않고, 사람 검토 없는 반영은 뺀다(_hold_near_facts). 장편만 본다(단편 경로는 그대로)."""
    if not p.serial:
        d.fact_near = []
        return
    d.fact_near = [FactNear(fact=f, like=like) for f in dict.fromkeys(d.new_facts) if f not in p.facts and (like := context.near_fact(f, p.facts))]


def _hold_near_facts(p: Project, d: StateDelta) -> int:
    """HOLD 훅 (자동 집필 · run -y · 플레이): 비슷한 새 사실은 반영하지 않고 d.dismissed 로 옮긴다.
    반영 기록의 '빼 둔 항목'에서 작가가 나중에 확정 사실로 넣는다(pipeline.take_dismissed_fact). 인물 화면에 남기는 칸이 아니라 0 을 센다."""
    near = {x.fact for x in d.fact_near} if p.serial else set()
    gone = [f for f in d.new_facts if f in near]
    if not gone:
        return 0
    d.new_facts = [f for f in d.new_facts if f not in near]
    d.dismissed.new_facts += [f for f in gone if f not in d.dismissed.new_facts]
    d.warn_to += [""] * (len(d.warnings) - len(d.warn_to))  # 경고와 같은 차례를 지킨다 (features.clean)
    for f in gone:
        d.warn_to.append("")
        d.warnings.append(f"확정 사실: 이미 있는 사실과 비슷해 자동 반영에서 뺐어요: {f}")
    return 0


def _clean_places(p: Project, d: StateDelta) -> list[str]:
    """새 장소는 본문에 나오고 아직 없는 것만 남기고, 이미 있는 장소와 비슷한 이름은 경고로."""
    d.new_places, warns = elements.clean_places(p, d.new_places, p.episode(d.episode).text)
    return warns


def _new_cast_gaps(p: Project, d: StateDelta) -> list[Warn]:
    """새 인물 가운데 말투가 빈 인물. 상태 변경안은 본문에서 드러난 것만 적어 말투가 비기 쉽고, 비면 다음 화부터 기본 말투로 흐른다."""
    return [(f"새 인물 {c.name or c.id}의 말투(speech_style)가 비었어요. 반영한 뒤 인물 화면에서 채워 주세요.", c.id)
            for c in d.new_characters if not c.speech_style.strip() and c.id not in {x.id for x in p.characters}]


def _new_cast_known(p: Project, d: StateDelta) -> list[Warn]:
    """새 인물에 이미 있는 인물 id 가 온 것. 반영할 때 새 인물에서 빼고(pipeline.apply_delta) 기록에 남지 않게 한다."""
    have = {c.id for c in p.characters}
    return [(f"새 인물 {c.name or c.id}({c.id}): 이미 있는 인물이라 반영해도 새로 더하지 않아요.", c.id)
            for c in d.new_characters if c.id in have]


def _new_cast_names(p: Project, d: StateDelta) -> list[str]:
    """새 인물 이름이 이미 있는 인물 · 후보와 같거나 헷갈리면, 한 화에 새 인물이 너무 많으면 알린다 (naming.new_cast_warnings)."""
    return naming.new_cast_warnings(p, d.new_characters)


def _add_places(p: Project, d: StateDelta) -> None:
    elements.add_places(p, d.new_places, d.episode, "본문")


def _unregister_places(p: Project, n: int, snap: Snapshot) -> None:
    elements.unregister_places(p, n)  # 뒤 반영이 본문에서 등록한 장소


def _revert_two(hook: Callable[[Project, int], None]) -> Callable[[Project, int, Snapshot], None]:
    return lambda p, n, snap: hook(p, n)


def _revert_timeline(p: Project, n: int, snap: Snapshot) -> None:
    timeline.revert(p, n, snap.deadlines)


# 상태 변경안 정리 (pipeline.clean_delta)
CLEAN: tuple[Callable[[Project, StateDelta], list[Warn] | None], ...] = (
    foreshadows.clean_delta,   # 복선 문장을 본문에 맞춘다
    foreshadows.resolved_warnings,  # 이미 회수한 복선을 또 회수함 (반영이 뺀다)
    timeline.clean_delta,
    charlog.clean_delta,
    address.clean_delta,       # 호칭 · 말씨 바뀜: 있는 인물 사이의 지금 값과 다른 칸만
    blueprint.clean_delta,     # 닿은 사다리 칸: 목록에 있고 아직 닿지 않은 칸만
    knows.clean_delta,         # 프롬프트가 아는 정보 앞에 붙인 '(n화)' 표시를 뗀다
    _untag_facts,              # 프롬프트가 사실 줄 앞에 붙인 '(n화)' 표시를 뗀다 (비슷한 사실 보기 전에)
    attire.clean_delta,        # 차림의 '가방' · '옷'처럼 종류를 모르는 물건
    _clean_places,
    _new_cast_gaps,            # 말투가 빈 새 인물
    _new_cast_known,           # 새 인물에 온 이미 있는 인물 id
    _new_cast_names,           # 새 인물 이름 점검 · 한 화의 새 인물 수
    cast.clean_delta,          # 본문에 나와 변경안이 다룬 인물을 그 화 등장 인물에 붙일 목록 (경고 없음)
    pace.clean_delta,          # 관계 유형 · 감정 글이 반영 뒤 관계 단계와 반대인지, 한 쌍의 결정적 사건 남발 (등장 인물 붙이기 뒤)
    _near_facts,               # 이미 있는 확정 사실과 비슷한 새 사실 (경고 없음, 기본 체크 풀기)
    travel.delta_warnings,     # 지도 거리와 작품 속 시간으로 보아 너무 빨리 옮겨 간 인물 (장소 정리 뒤)
    statwin.window_warnings,   # 본문 상태창이 반영할 값과 다름
    statwin.range_warnings,    # '지금/한도' 수치가 0 아래거나 한도 위
)

# 반영 (pipeline.apply_delta): 새 인물을 더한 직후. 작가가 고른 설정 바꾸기 · 호칭 제안만 온다 (자동 집필은 hold 로 미리 뺀다)
APPLY_FIRST: tuple[Callable[[Project, StateDelta], None], ...] = (charlog.apply_delta, address.apply_delta, _add_places)
# 반영: 상태 · 관계 · 사실 · 복선을 반영한 뒤, 반영 기록과 스냅샷 전
APPLY_LAST: tuple[Callable[[Project, StateDelta], None], ...] = (
    foreshadows.apply_delta, timeline.apply_delta, cast.apply_delta,
    offscreen.apply_delta,  # 다시 나온 인물의 화면 밖 근황을 비운다 (등장 인물 붙이기 뒤)
    blueprint.apply_delta,  # 작가가 고른 닿은 사다리 칸 기록
)

# 되돌리기 (pipeline.revert): 스냅샷으로 상태를 덮기 전
REVERT_FIRST: tuple[Callable[[Project, int, Snapshot], None], ...] = (_unregister_places, _revert_two(cast.revert))
# 되돌리기: 스냅샷으로 덮고 반영 기록을 자른 뒤
REVERT_LAST: tuple[Callable[[Project, int, Snapshot], None], ...] = (
    _revert_two(foreshadows.revert), _revert_two(statwin.revert), _revert_timeline, _revert_two(charlog.revert), _revert_two(address.revert), _revert_two(knows.revert),
    _revert_two(stateedit.revert), _revert_two(blueprint.revert))
# 사람 검토 없이 반영하기 전 (자동 집필 · run -y · 플레이): 작가가 골라야 바뀌는 제안을 빼서 남겨 둔다. 남긴 개수를 센다
HOLD: tuple[Callable[[Project, StateDelta], int], ...] = (charlog.hold, address.hold, blueprint.hold, pace.hold, _hold_near_facts)


def align_warn_to(d: StateDelta) -> None:
    """d.warn_to 를 d.warnings 와 같은 길이로 맞춘다. 훅이 d.warnings 에 바로 붙인 경고(charlog)와 AI 경고는 대상이 "" 다."""
    d.warn_to = (d.warn_to + [""] * len(d.warnings))[:len(d.warnings)]


def clean(p: Project, d: StateDelta) -> None:
    warns: list[Warn] = []
    for hook in CLEAN:
        warns += hook(p, d) or []
    align_warn_to(d)
    for w in warns:
        text, to = (w, "") if isinstance(w, str) else w
        if text not in d.warnings:
            d.warnings.append(text)
            d.warn_to.append(to)


def apply(hooks: tuple[Callable[[Project, StateDelta], None], ...], p: Project, d: StateDelta) -> None:
    for hook in hooks:
        hook(p, d)


def revert(hooks: tuple[Callable[[Project, int, Snapshot], None], ...], p: Project, n: int, snap: Snapshot) -> None:
    for hook in hooks:
        hook(p, n, snap)


def hold(p: Project, d: StateDelta) -> int:
    """HOLD 훅을 차례로 부르고 남긴 개수를 더한다."""
    return sum(h(p, d) for h in HOLD)
