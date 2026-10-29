"""큐 시트 집필 실험 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록하고, 큐 쓰기 본문은 mock.text 가 text_for 로 묻는다."""
from __future__ import annotations

import re

from .mock import responds
from .schema import Cue, CueLine, CueSheetDraft


@responds(CueSheetDraft)
def _sheet(prompt: str, hint: dict) -> CueSheetDraft:
    """hint: events(플롯 사건 수), characters(플롯 인물 id), scenes(스토리보드 장면 수), size(화 분량).
    사건마다 큐 하나(4개 넘게), 안정 → 쌓기 → 긴장. 첫 인물이 둘째 큐와 마지막 큐에서 핵심 대사를 한다."""
    k = max(int(hint.get("events") or 3), 4)
    size = int(hint.get("size") or 5000)
    who = (hint.get("characters") or ["hero"])[0]
    scenes = int(hint.get("scenes") or 0)
    cues = []
    for i in range(k):
        fn = "T" if i == 0 else "D" if i >= k - 2 else "S"
        lines = [CueLine(speaker=who, text="여기서 멈추면 아무것도 안 바뀌어")] if i == 1 else \
            [CueLine(speaker=who, text="문을 연 건 내가 아니야")] if i == k - 1 else []
        cues.append(Cue(scene=min(i + 1, scenes) if scenes else 0, function=fn, tension=min(2 + i, 5),
                        tempo={"T": "slow", "S": "mid", "D": "fast"}[fn], voice="dialogue" if lines else "action",
                        beat=f"큐 {i + 1}에서 바뀌는 일", lines=lines, exit=f"큐 {i + 1}이 끝난 자리", length=size // k))
    return CueSheetDraft(key="억눌린 불안", cadence="half", cues=cues)


def text_for(prompt: str) -> str | None:
    """큐 시트가 든 쓰기 요청이면 가짜 본문. 큐 하나를 쓰는 요청이면 그 큐의 핵심 대사만, 한 번에 쓰는 요청이면 모든 핵심 대사를 넣는다."""
    if "# 이번 화 큐 시트" not in prompt:
        return None
    sheet = prompt.split("# 이번 화 큐 시트", 1)[1].split("\n핵심 대사는", 1)[0]
    m = re.search(r"\n큐 (\d+) 본문만 씁니다\.\s*$", prompt)
    if m:
        k = int(m.group(1))
        part = re.search(rf"\n{k}\. \[(.*?)(?=\n\d+\. \[|\Z)", sheet, re.S)
        said = re.findall(r"«(.+?)»", part.group(0) if part else "")
        body = f"서윤은 큐 {k}의 자리에서 숨을 골랐다. 바람이 등대 유리를 두드렸다."
        return body + "".join(f"\n\n\"{x}\"" for x in said) + "\n\n그는 다음 걸음을 옮겼고, 발밑의 모래가 조금 무너졌다."
    said = re.findall(r"«(.+?)»", sheet)
    return "바람이 불었다. 서윤은 등대 앞에 섰다." + "".join(f"\n\n\"{x}\"" for x in said) + "\n\n(mock 큐 시트 본문)"
