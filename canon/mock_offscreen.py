"""화면 밖 근황 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import OffscreenLine, OffscreenSet

MOCK_AWAY = "북문 밖 대장간을 혼자 지키며 주문을 받아 왔다."  # 인물마다 같은 근황


@responds(OffscreenSet)
def _offscreen(prompt: str, hint: dict) -> OffscreenSet:
    """hint: ids(근황을 물은 인물 id). 인물마다 한 줄, 그리고 정리가 떼야 할 묻지 않은 인물 한 줄."""
    lines = [OffscreenLine(character_id=cid, text=f"  {MOCK_AWAY}  ", kind="daily") for cid in hint.get("ids") or []]
    return OffscreenSet(lines=lines + [OffscreenLine(character_id="nobody", text="묻지 않은 인물", kind="hook")])
