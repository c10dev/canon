"""복선 판정 가짜 응답 (CANON_LLM=mock, blocktrial 의 fs_ 조건). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import ForeshadowBreak, ForeshadowBreaks


@responds(ForeshadowBreaks)
def _foreshadow_judge(prompt: str, hint: dict) -> ForeshadowBreaks:
    """hint: ids(판정에 넣은 복선 id), pays(이번 화 회수 id), text(본문).
    본문에 회수하지 않을 복선 id 가 그대로 나오면 '미리 회수' 하나로 센다. 시험이 판정 결과의 개수를 볼 수 있게 하는 정도다."""
    text, pays = hint.get("text", ""), set(hint.get("pays", []))
    out = []
    for fid in hint.get("ids", []):
        if fid and fid not in pays and fid in text:
            line = next((s for s in text.splitlines() if fid in s), fid)
            out.append(ForeshadowBreak(foreshadow=fid, quote=line.strip(), reason="회수하기로 하지 않은 복선을 본문이 드러내요", kind="미리 회수"))
    return ForeshadowBreaks(items=out)
