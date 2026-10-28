"""플레이 모드 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import PlayChoice, PlayScene

# 행동에 이 낱말이 들어 있으면 이야기가 끝나는 장면을 낸다 (결말 흐름 시험용)
MOCK_ENDING_WORD = "끝낸다"


@responds(PlayScene)
def _scene(prompt: str, hint: dict) -> PlayScene:
    """hint: number(턴 Episode 번호), action(플레이어 행동, 첫 턴은 빈 값), luck(-2~2)."""
    n = hint.get("number", 0)
    action = (hint.get("action") or "").strip()
    head = f"{action.rstrip('.')}. " if action else "눈을 떴다. "  # 첫 턴 행동은 출생 실마리 문장이라 마침표로 끝날 수 있다
    luck = hint.get("luck", 0)
    mood = {-2: "모든 것이 어긋났다.", -1: "일이 조금 꼬였다.", 0: "별일은 없었다.", 1: "운이 따랐다.", 2: "놀랄 만큼 잘 풀렸다."}.get(luck, "")
    text = f"{head}바람이 불었다. {mood}\n\n\"이제 어떻게 할래?\"\n\n(mock {n}턴 장면)"
    if MOCK_ENDING_WORD in action:
        return PlayScene(text=text + "\n\n이야기는 여기서 끝났다.", choices=[], ending="플레이어가 이야기를 끝냈다")
    return PlayScene(text=text, choices=[
        PlayChoice(text="등대로 간다"),
        PlayChoice(text="시장 사람에게 말을 건다"),
        PlayChoice(text="집으로 돌아가 쉰다"),
        PlayChoice(text="사흘 뒤로", skip="사흘"),
    ])
