"""고친 곳만 다시 보기 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import FixRecheckItem, FixRecheckReport


@responds(FixRecheckReport)
def _fix_recheck(prompt: str, hint: dict) -> FixRecheckReport:
    """hint: items(지적 id · 지적한 문장), text(지금 본문). 지적한 문장이 본문에서 바뀌었으면 풀린 것으로 본다 (이 지적만 다시 검수 가짜 응답과 같다)."""
    text = hint.get("text", "")
    out = []
    for x in hint.get("items", []):
        gone = x["quote"].strip() not in text
        out.append(FixRecheckItem(id=x["id"], resolved=gone, reason="문장이 바뀌어 어긋남이 풀렸어요" if gone else "문장이 그대로예요"))
    return FixRecheckReport(results=out)
