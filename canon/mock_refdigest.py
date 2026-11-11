"""레퍼런스 화 카드 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

import re
from collections import Counter

from .mock import responds
from .schema import RefDigest

FAIL_MARK = "[[읽기 실패]]"  # 원문에 이 글이 있으면 빈 사건 줄을 낸다 (실패한 화를 건너뛰는지 보는 시험용)


@responds(RefDigest)
def _digest(prompt: str, hint: dict) -> RefDigest:
    """문단을 네 묶음으로 나눠 묶음마다 첫 문장을 사건 줄로. 인물은 '…은/는 ' 앞에 두 번 넘게 나온 두세 글자 낱말."""
    text = prompt.split("\n[원문]\n", 1)[-1]
    if FAIL_MARK in text:
        return RefDigest(events=[], cast=[], place="", ending="", kind="", tension=1, hook="")
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    step = max(1, len(paras) // 4)
    firsts = [re.split(r"(?<=[.!?])\s", p, maxsplit=1)[0][:60] for p in paras[::step][:4]]
    cast = [w for w, k in Counter(re.findall(r"([가-힣]{2,3})(?:은|는) ", text)).most_common() if k >= 2][:3]
    talk = sum(len(m) for m in re.findall(r"[\"“][^\"”]*[\"”]", text)) / max(1, len(text))
    return RefDigest(events=[f"(가짜) {x}" for x in firsts] or ["(가짜) 한 화"], cast=cast, place="(가짜) 장소",
                     ending=f"(가짜) {paras[-1][:40]}" if paras else "", kind="대화" if talk > 0.3 else "일상",
                     tension=min(5, 1 + len(text) // 1500), hook="여운")
