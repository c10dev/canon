"""레퍼런스 설정 메모 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import RefBeatsDraft, RefSetupDraft


@responds(RefSetupDraft)
def _setup_note(prompt: str, hint: dict) -> RefSetupDraft:
    """이름 없이 역할로만 적은 구도. 재료가 화 카드인지 원문인지를 톤 줄에 적는다."""
    cards = hint.get("mode") == "cards"
    return RefSetupDraft(
        logline_shape="(가짜) 사라진 사람을 찾는 외지인이 입을 닫은 마을에서 진실을 밝히려 하지만 마을의 오랜 약속이 막는다",
        world_rules=["(가짜) 비밀을 지키는 쪽이 힘을 가진다", "(가짜) 바깥사람은 기록에 닿지 못한다"],
        cast=["(가짜) 진실을 좇는 외지인 주인공", "(가짜) 사정을 알면서 말을 아끼는 조력자", "(가짜) 약속을 지키려는 마을의 어른"],
        relations=["(가짜) 경계하던 사이가 뒤에 같은 편이 된다", "(가짜) 보호자와 지켜지는 사람의 자리가 뒤바뀐다"],
        conflict="(가짜) 진실을 드러내려는 쪽과 묻어 두려는 쪽이 같은 사람을 아낀다.",
        tone=f"(가짜) 차분하고 눅눅한 긴장 ({'화 카드로' if cards else '원문으로'} 만듦)")


@responds(RefBeatsDraft)
def _beats_note(prompt: str, hint: dict) -> RefBeatsDraft:
    """이름 없이 대목이 하는 일로만 적은 박자."""
    cards = hint.get("mode") == "cards"
    return RefBeatsDraft(
        pattern=f"(가짜) 조용한 관찰로 열고 작은 어긋남이 걸린 채 물음으로 끊는다 ({'화 카드로' if cards else '원문으로'} 만듦)",
        beats=["(가짜) 낯선 흔적을 발견하며 연다", "(가짜) 아는 사람이 말을 아낀다", "(가짜) 단서 하나가 방향을 바꾼다", "(가짜) 답 대신 더 큰 물음이 남는다"],
        hooks=["(가짜) 문 앞에서 끊는다", "(가짜) 새 사실이 드러난 직후에 끊는다"],
        pacing="(가짜) 느슨한 화 둘 뒤에 팽팽한 화 하나가 온다.")
