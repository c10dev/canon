"""상태 변경안 누락 검사 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

import re

from .mock import responds
from .schema import AuditItem, AuditReport


@responds(AuditReport)
def _audit(prompt: str, hint: dict) -> AuditReport:
    """hint: text(n화 본문). 본문 첫 문장을 장소 이동 누락으로, 본문에 없는 문장 하나를 소지품 누락으로 낸다(버려지는지 보게)."""
    first = next((s for s in re.split(r"(?<=[.!?])\s+", hint.get("text", "")) if s.strip()), "")
    if not first:
        return AuditReport()
    return AuditReport(items=[AuditItem(kind="장소 이동", missing="인물이 다른 곳으로 옮겼는데 위치가 그대로예요", quote=first),
                              AuditItem(kind="소지품", missing="열쇠를 얻었어요", quote="본문에 없는 문장이다.")])
