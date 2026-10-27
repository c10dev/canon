"""기능 모듈이 상태 변경안의 수명 주기(정리 → 반영 → 되돌리기)에 끼어드는 자리. LLM 호출 없음.

pipeline.clean_delta · apply_delta · revert 가 아래 목록을 차례로 부른다. 상태를 가진 기능을 더할 때는 pipeline 을 고치지 않고
그 기능 모듈에 훅 함수를 두고 여기 목록에 넣는다. 목록 순서가 부르는 순서다. 앞 훅이 바꾼 값을 뒤 훅이 읽을 수 있으니
순서를 바꿀 때는 두 훅이 같은 칸을 읽고 쓰는지 본다 (예: 장소 정리 뒤에 이동 거리 경고).

훅 모양:
- 정리 (p, d) -> 경고 목록 또는 None. 변경안 d 를 고쳐도 된다. 돌려준 경고는 d.warnings 끝에 겹치지 않게 붙는다.
- 반영 (p, d) -> None.
- 되돌리기 (p, n, snap) -> None. snap 은 되돌아갈 n화 스냅샷.
"""
from __future__ import annotations

from typing import Callable

from . import charlog, elements, foreshadows, statwin, timeline, travel
from .schema import Project, Snapshot, StateDelta


def _clean_places(p: Project, d: StateDelta) -> list[str]:
    """새 장소는 본문에 나오고 아직 없는 것만 남기고, 이미 있는 장소와 비슷한 이름은 경고로."""
    d.new_places, warns = elements.clean_places(p, d.new_places, p.episode(d.episode).text)
    return warns


def _add_places(p: Project, d: StateDelta) -> None:
    elements.add_places(p, d.new_places, d.episode, "본문")


def _unregister_places(p: Project, n: int, snap: Snapshot) -> None:
    elements.unregister_places(p, n)  # 뒤 반영이 본문에서 등록한 장소


def _revert_two(hook: Callable[[Project, int], None]) -> Callable[[Project, int, Snapshot], None]:
    return lambda p, n, snap: hook(p, n)


def _revert_timeline(p: Project, n: int, snap: Snapshot) -> None:
    timeline.revert(p, n, snap.deadlines)


# 상태 변경안 정리 (pipeline.clean_delta)
CLEAN: tuple[Callable[[Project, StateDelta], list[str] | None], ...] = (
    foreshadows.clean_delta,   # 복선 문장을 본문에 맞춘다
    timeline.clean_delta,
    charlog.clean_delta,
    _clean_places,
    travel.delta_warnings,     # 지도 거리와 작품 속 시간으로 보아 너무 빨리 옮겨 간 인물 (장소 정리 뒤)
    statwin.window_warnings,   # 본문 상태창이 반영할 값과 다름
)

# 반영 (pipeline.apply_delta): 새 인물을 더한 직후. 작가가 고른 설정 바꾸기 제안만 온다 (자동 집필은 charlog.hold 로 미리 뺀다)
APPLY_FIRST: tuple[Callable[[Project, StateDelta], None], ...] = (charlog.apply_delta, _add_places)
# 반영: 상태 · 관계 · 사실 · 복선을 반영한 뒤, 반영 기록과 스냅샷 전
APPLY_LAST: tuple[Callable[[Project, StateDelta], None], ...] = (foreshadows.apply_delta, timeline.apply_delta)

# 되돌리기 (pipeline.revert): 스냅샷으로 상태를 덮기 전
REVERT_FIRST: tuple[Callable[[Project, int, Snapshot], None], ...] = (_unregister_places,)
# 되돌리기: 스냅샷으로 덮고 반영 기록을 자른 뒤
REVERT_LAST: tuple[Callable[[Project, int, Snapshot], None], ...] = (
    _revert_two(foreshadows.revert), _revert_two(statwin.revert), _revert_timeline, _revert_two(charlog.revert))


def clean(p: Project, d: StateDelta) -> None:
    warns: list[str] = []
    for hook in CLEAN:
        warns += hook(p, d) or []
    d.warnings += [w for w in warns if w not in d.warnings]


def apply(hooks: tuple[Callable[[Project, StateDelta], None], ...], p: Project, d: StateDelta) -> None:
    for hook in hooks:
        hook(p, d)


def revert(hooks: tuple[Callable[[Project, int, Snapshot], None], ...], p: Project, n: int, snap: Snapshot) -> None:
    for hook in hooks:
        hook(p, n, snap)
