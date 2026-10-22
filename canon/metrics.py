"""문체 지표. LLM 호출 없이 본문을 수치로 재서 레퍼런스 문체와의 차이를 찾는다.

같은 본문이면 항상 같은 값이 나오므로 화별 문체 표류를 비교하는 기준으로 쓴다.
경고 기준(THRESHOLDS)은 출발점일 뿐이고, 실제 작품으로 재 보며 조정해야 한다.
"""
from __future__ import annotations

import re
from collections import Counter
from statistics import mean, pstdev
from typing import Optional

from pydantic import BaseModel, Field

# 한국어 소설 생성에서 자주 보이는 상투 표현. 작품별 금지 표현은 StyleProfile.banned_phrases 에 더한다.
DEFAULT_CLICHES = [
    "숨을 내쉬었다",
    "한숨을 내쉬었다",
    "입꼬리가 올라갔다",
    "입꼬리를 올렸다",
    "심장이 쿵",
    "가슴이 먹먹",
    "눈빛이 흔들렸다",
    "침묵이 흘렀다",
    "정적이 흘렀다",
    "묘한 감정",
    "알 수 없는 감정",
    "마치 시간이 멈춘 것",
    "주먹을 꽉 쥐었다",
    "입술을 깨물었다",
    "고개를 끄덕였다",
]

_SENT_END = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…][\"'”’」』)])\s+|\n+")
_QUOTE = re.compile(r"[\"“][^\"”]*[\"”]|「[^」]*」|『[^』]*』")
_HANGUL_BASE, _JONG_SS = 0xAC00, 20  # 받침 ㅆ 의 종성 번호


class StyleMetrics(BaseModel):
    chars: int = 0
    sentences: int = 0
    sentence_len_mean: float = Field(0, description="문장 평균 글자 수")
    sentence_len_cv: float = Field(0, description="문장 길이 변동계수 (표준편차/평균). 낮을수록 리듬이 단조롭다")
    paragraph_len_mean: float = Field(0, description="문단 평균 글자 수")
    dialogue_ratio: float = Field(0, description="따옴표 안 글자 비율")
    past_tense_ratio: Optional[float] = Field(None, description="'~다' 로 끝나는 서술 문장 중 과거형(받침 ㅆ + 다) 비율")
    mattr: Optional[float] = Field(None, description="어절 기준 이동 창 어휘 다양도 (창 100). 100어절 미만이면 재지 않음")
    repeated_phrases: list[str] = Field(default_factory=list, description="한 화 안에서 3번 이상 나온 3어절 구")
    cliche_hits: list[str] = Field(default_factory=list, description="상투·금지 표현 적중")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_END.split(text) if s.strip()]


def _is_past(sentence: str) -> bool | None:
    s = sentence.rstrip(".!?…\"'”’ ")
    if len(s) < 2 or s[-1] != "다":
        return None
    code = ord(s[-2]) - _HANGUL_BASE
    return 0 <= code < 11172 and code % 28 == _JONG_SS


def _mattr(words: list[str], window: int = 100) -> Optional[float]:
    if len(words) < window:
        return None  # 짧은 글의 어휘 비율은 긴 글과 비교할 수 없다
    counts = Counter(words[:window])
    total = len(counts)
    for i in range(window, len(words)):
        out, inn = words[i - window], words[i]
        counts[out] -= 1
        if counts[out] == 0:
            del counts[out]
        counts[inn] += 1
        total += len(counts)
    return total / ((len(words) - window + 1) * window)


def _repeated(words: list[str], n: int = 3, min_count: int = 3) -> list[str]:
    grams = Counter(" ".join(words[i:i + n]) for i in range(len(words) - n + 1))
    return [g for g, c in grams.most_common(10) if c >= min_count]


def measure(text: str, banned: list[str] | None = None) -> StyleMetrics:
    text = text.strip()
    if not text:
        return StyleMetrics()
    sents = sentences(text)
    lens = [len(s) for s in sents]
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    narration = [s for s in sents if not _QUOTE.fullmatch(s)]
    tense = [t for t in (_is_past(s) for s in narration) if t is not None]
    quoted = sum(len(m) for m in _QUOTE.findall(text))
    words = re.findall(r"[^\s\"'“”‘’「」『』.,!?…]+", text)
    phrases = list(dict.fromkeys(DEFAULT_CLICHES + (banned or [])))
    avg = mean(lens)
    return StyleMetrics(
        chars=len(text),
        sentences=len(sents),
        sentence_len_mean=round(avg, 1),
        sentence_len_cv=round(pstdev(lens) / avg, 2) if avg else 0,
        paragraph_len_mean=round(mean(len(p.strip()) for p in paras), 1),
        dialogue_ratio=round(quoted / len(text), 2),
        past_tense_ratio=round(sum(tense) / len(tense), 2) if tense else None,
        mattr=None if (v := _mattr(words)) is None else round(v, 3),
        repeated_phrases=_repeated(words),
        cliche_hits=[p for p in phrases if p in text],
    )


# 기준값과 비교할 지표: (설명, 허용 차이, 상대값 여부)
THRESHOLDS: dict[str, tuple[str, float, bool]] = {
    "sentence_len_mean": ("문장 평균 길이", 0.3, True),
    "sentence_len_cv": ("문장 길이 변화폭", 0.35, True),
    "paragraph_len_mean": ("문단 평균 길이", 0.5, True),
    "dialogue_ratio": ("대사 비율", 0.15, False),
    "past_tense_ratio": ("과거형 서술 비율", 0.2, False),
    "mattr": ("어휘 다양도", 0.08, False),
}


def drift(base: StyleMetrics, cur: StyleMetrics) -> list[str]:
    """기준(레퍼런스) 대비 허용 범위를 벗어난 지표를 경고 문장으로 돌려준다."""
    out = []
    for key, (label, limit, relative) in THRESHOLDS.items():
        b, c = getattr(base, key), getattr(cur, key)
        if not b or c is None:
            continue
        diff = (c - b) / b if relative else c - b
        if abs(diff) > limit:
            shown = f"{diff:+.0%}" if relative else f"{diff:+.2f}"
            out.append(f"{label}: 기준 {b} → {c} ({shown})")
    if cur.repeated_phrases:
        out.append(f"반복 구: {', '.join(cur.repeated_phrases[:5])}")
    if cur.cliche_hits:
        out.append(f"상투·금지 표현: {', '.join(cur.cliche_hits)}")
    return out
