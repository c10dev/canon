"""아는 정보 접기 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import KnowsFold, KnowsFoldSet

MOCK_FOLD = "접은 줄: 등대 열쇠는 둘이다"  # 인물마다 첫 줄


@responds(KnowsFoldSet)
def _fold(prompt: str, hint: dict) -> KnowsFoldSet:
    """hint: arc(아크 번호), ids(접을 인물 id). 인물마다 두 줄, 둘째 줄에는 정리가 떼야 할 화 표시를 붙인다."""
    return KnowsFoldSet(folds=[KnowsFold(character_id=cid, lines=[MOCK_FOLD, f"(3화) {cid}는 아크 {hint['arc']}의 비밀을 안다"])
                               for cid in hint.get("ids") or []])
