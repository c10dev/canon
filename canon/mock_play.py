"""플레이 모드 가짜 응답 (CANON_LLM=mock). mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import responds
from .schema import PlayBeat, PlayChoice, PlayScene, StoryTime

# 행동에 이 낱말이 들어 있으면 이야기가 끝나는 구간을 낸다 (결말 흐름 시험용)
MOCK_ENDING_WORD = "끝낸다"
MOCK_PARTS = ("아침", "낮", "저녁")


def decides(n: int) -> bool:
    """짝수 번째 구간만 결정 장면으로 끝난다. 홀수 구간은 결정 없이 다음 구간으로 흐른다."""
    return n % 2 == 0


@responds(PlayScene)
def _scene(prompt: str, hint: dict) -> PlayScene:
    """hint: number(구간 Episode 번호), action(플레이어 행동, 흐름 · 첫 구간은 빈 값), luck(-2~2), day(지난 구간이 끝난 날수), unit."""
    n = hint.get("number", 0)
    action = (hint.get("action") or "").strip().rstrip(".")  # 첫 구간 행동은 출생 실마리 문장이라 마침표로 끝날 수 있다
    luck = hint.get("luck", 0)
    day = hint.get("day", 0)
    mood = {-2: "모든 것이 어긋났다.", -1: "일이 조금 꼬였다.", 0: "별일은 없었다.", 1: "운이 따랐다.", 2: "놀랄 만큼 잘 풀렸다."}.get(luck, "")
    step = 1 if hint.get("unit", "day") == "day" else 0
    lines = [f"{action}." if action else "눈을 떴다.", f"바람이 불었다. {mood}", f"(mock {n}구간)"]
    beats = [PlayBeat(time=StoryTime(day=day + (i + 1) * step if day or step else 0, part=MOCK_PARTS[i]), text=x)
             for i, x in enumerate(lines)]
    if MOCK_ENDING_WORD in action:
        return PlayScene(beats=beats, text="이야기는 여기서 끝났다.", ending="플레이어가 이야기를 끝냈다")
    if not decides(n):
        return PlayScene(beats=beats)
    return PlayScene(beats=beats, text="\"이제 어떻게 할래?\"", lean=2, choices=[
        PlayChoice(text="등대로 간다"),
        PlayChoice(text="시장 사람에게 말을 건다"),
        PlayChoice(text="집으로 돌아가 쉰다"),
    ])
