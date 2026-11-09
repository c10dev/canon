"""쓰기 재료 조율의 조율 메모 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import CoordDraft


@responds(CoordDraft)
def _coord(prompt: str, hint: dict) -> CoordDraft:
    """hint: events(플롯 사건 수). 사건마다 '무엇이 바뀌는가' 한 줄."""
    k = int(hint.get("events") or 3)
    return CoordDraft(summary="이 화에서 주인공은 숨긴 것을 들키고, 먼저 말하기로 정한다.",
                      events=[f"사건 {i + 1}에서 주인공의 마음이 한 칸 움직인다." for i in range(k)],
                      ending_hook="말하지 못한 한마디가 남는다.")
