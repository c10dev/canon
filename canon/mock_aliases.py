"""다른 이름 제안 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

import re

from .mock import responds
from .schema import AliasIdea, AliasSuggestion

MOCK_PREFER = ("꼬맹이", "마력핵", "흑탑", "대장님")  # 재료 단락에 있으면 먼저 고르는 말 (시험 원고에 심는다)
MOCK_MADE_UP = "지어낸별명"  # 재료에 없는 말. aliases.clean 의 근거 검사가 빼야 한다


@responds(AliasSuggestion)
def _aliases(prompt: str, hint: dict) -> AliasSuggestion:
    """hint: material(항목 열쇠 → 재료 단락 글). 항목마다 재료 단락에 글자 그대로 있는 말 하나와 지어낸 말 하나를 낸다.
    MOCK_PREFER 의 말이 있으면 그 말을, 없으면 재료의 첫 한글 낱말(2~4자)을 고른다. 재료가 비면 지어낸 말만 낸다."""
    items = []
    for key, text in (hint.get("material") or {}).items():
        found = [w for w in MOCK_PREFER if w in text] or re.findall(r"[가-힣]{2,4}", text)[:1]
        items.append(AliasIdea(target=key, aliases=[f" '{w}' " for w in found[:1]] + [MOCK_MADE_UP], reason="본문에서 이렇게 불렸어요."))
    return AliasSuggestion(items=items + [AliasIdea(target="c:nobody", aliases=["없는인물"], reason="")])
