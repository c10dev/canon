"""로그라인 다섯 칸을 한 문장으로 합치고, 형식을 점검한다. LLM 호출 없음.

웹 화면(canon/static/app.js 의 composeLogline, loglineChecks, toneText)도 같은 규칙으로 계산한다.
규칙을 바꾸면 두 곳을 함께 고친다.
"""
from __future__ import annotations

from .schema import LoglineParts, ToneDials

HANGUL_FIRST, HANGUL_LAST = 0xAC00, 0xD7A3


def _jong(ch: str) -> int:
    """한글 음절의 받침 번호. 0 은 받침 없음, -1 은 한글이 아님."""
    code = ord(ch)
    if not HANGUL_FIRST <= code <= HANGUL_LAST:
        return -1
    return (code - HANGUL_FIRST) % 28


def josa(word: str, with_final: str, without_final: str) -> str:
    """앞말 받침에 맞는 조사. '서윤' + 이/가 → 이, '서진이' → 가. 한글이 아니면 '이(가)'."""
    w = word.strip()
    if not w:
        return ""
    j = _jong(w[-1])
    if j < 0:
        return f"{with_final}({without_final})"
    return with_final if j else without_final


def compose(p: LoglineParts) -> str:
    """다섯 칸을 '{누가}이/가 {무엇 때문에} {목표}. 하지만 {막는 것}. {걸린 것}.' 으로 합친다. 빈 칸은 건너뛴다.

    목표와 막는 것을 '~지만'으로 잇지 않는 것은 만든다(만들다)와 그린다(그리다)처럼
    어간을 사전 없이 가를 수 없어서다.
    """
    who, why, goal, block, stake = (x.strip().rstrip(".") for x in (p.who, p.why, p.goal, p.block, p.stake))
    out = ""
    if who:
        out += who + josa(who, "이", "가") + " "
    if why:
        out += why + " "
    if goal:
        out += goal + "."
    if block:
        out += (" 하지만 " if out else "") + block + "."
    if stake:
        out += " " + stake + "."
    return out.strip()


def is_empty(p: LoglineParts) -> bool:
    return not any(x.strip() for x in (p.who, p.why, p.goal, p.block, p.stake))


def checks(p: LoglineParts) -> list[tuple[bool, str]]:
    """형식 점검. 참고용 경고이며 다음 단계로 넘어가는 것을 막지 않는다."""
    n = len(compose(p))
    return [
        (len(p.who.split()) > 1, "주인공에게 이름 말고 특징이 있다"),
        (bool(p.why.strip()), "이야기를 시작하게 만드는 일이 있다"),
        (p.goal.strip().endswith("다"), "목표가 눈에 보이는 행동이다 ('~한다'로 끝남)"),
        (bool(p.block.strip()), "목표를 막는 사람이나 힘이 있다"),
        (40 <= n <= 150, "길이가 40~150자 사이다"),
    ]


# 다이얼 값 1~4 마다 (이어지는 말, 끝맺는 말)
TONE_WORDS = {
    "dark": (("밝고", "밝다"), ("조금 밝고", "조금 밝다"), ("조금 어둡고", "조금 어둡다"), ("어둡고", "어둡다")),
    "serious": (("가볍고", "가볍다"), ("조금 가볍고", "조금 가볍다"), ("조금 진지하고", "조금 진지하다"), ("진지하고", "진지하다")),
    "slow": (("호흡이 빠르다", "호흡이 빠르다"), ("호흡이 조금 빠르다", "호흡이 조금 빠르다"),
             ("호흡이 조금 느리다", "호흡이 조금 느리다"), ("호흡이 느리다", "호흡이 느리다")),
}


def tone_text(d: ToneDials) -> str:
    """톤 다이얼을 문장으로. 고르지 않은 다이얼은 뺀다. 예: '조금 어둡고 진지하고 호흡이 느리다'."""
    words = [TONE_WORDS[k][v - 1] for k, v in (("dark", d.dark), ("serious", d.serious), ("slow", d.slow)) if 1 <= v <= 4]
    return " ".join(w[1] if i == len(words) - 1 else w[0] for i, w in enumerate(words))
