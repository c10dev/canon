"""무작위 출생 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import BirthSketch


@responds(BirthSketch)
def _sketch(prompt: str, hint: dict) -> BirthSketch:
    """hint: name, place (birth.roll 이 굴린 값)."""
    name = hint.get("name") or "이름 없는 아이"
    place = hint.get("place") or "바닷가 마을"
    return BirthSketch(
        appearance="햇볕에 그을린 얼굴, 손에 굳은살",
        personality="말수가 적고 고집이 세다",
        background=f"{name}은(는) {place}에서 어부의 막내로 태어났다. 어머니는 일찍 떠났다. 열 살부터 그물을 손질했다.",
        goal="이 마을을 떠나 넓은 곳을 본다",
        speech_style="짧게 끊어 말하고 반말을 쓴다",
        opening=f"{place}의 새벽, {name}이(가) 젖은 그물을 걷고 있다.",
    )
