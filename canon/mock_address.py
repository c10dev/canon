"""본문에서 호칭 찾기 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

import re

from .mock import responds
from .schema import AddressChange, AddressFind

MOCK_MADE_UP_QUOTE = "지어낸 대사예요"  # 재료에 없는 대사. address.clean_found 가 빼야 한다
_LINE = re.compile(r'["“]([^"“”]+)["”]')
_CALL = re.compile(r"([가-힣]{1,6})[,!?]")


@responds(AddressFind)
def _address(prompt: str, hint: dict) -> AddressFind:
    """hint: material('speaker>listener' → 재료 글). 방향마다 재료의 첫 따옴표 대사를 quote 로, 그 대사의 첫 호격 낱말(쉼표 · 느낌표 · 물음표 앞)을
    calls 로 낸다. 호격이 없으면 '이름' 을 낸다. 재료에 없는 대사 하나와 묻지 않은 방향 하나를 덧붙인다 (정리가 빼는지 보려고)."""
    items = []
    for key, text in (hint.get("material") or {}).items():
        speaker, _, listener = key.partition(">")
        m = _LINE.search(text)
        if not m:
            continue
        line = m.group(1).strip()
        call = _CALL.search(line)
        items.append(AddressChange(speaker=speaker, listener=listener, calls=call.group(1) if call else "이름", speech="해체(반말)",
                                   reason="재료의 첫 대사에서 이렇게 불렀어요.", quote=line))
        items.append(AddressChange(speaker=speaker, listener=listener, calls="지어낸 부름", quote=MOCK_MADE_UP_QUOTE))
    return AddressFind(items=items + [AddressChange(speaker="nobody", listener="ghost", calls="없는 쌍", quote="없는 쌍")])
