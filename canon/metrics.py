"""문체 지표. LLM 호출 없이 본문을 수치로 재서 레퍼런스 문체와의 차이를 찾는다.

같은 본문이면 항상 같은 값이 나오므로 화별 문체 표류를 비교하는 기준으로 쓴다.
경고 기준(THRESHOLDS)은 출발점일 뿐이고, 실제 작품으로 재 보며 조정해야 한다.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from statistics import mean, median, pstdev
from typing import Optional

from pydantic import BaseModel, Field

from .style_background import FEATURES

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
    "눈동자가 흔들렸다",
    "숨을 삼켰다",
    "숨을 들이켰다",
    "침을 꿀꺽",
    "심장이 철렁",
    "심장이 내려앉",
    "형언할 수 없는",
    "공기가 무거워",
    "짧은 침묵",
]

# 쇠맛 패턴: 한 번은 괜찮지만 자주 반복되면 AI 글티가 나는 구문. (이름, 정규식, 화당 상한)
# 근거와 상한 설정 이유는 PR 설명과 DESIGN.md 참고. 상한은 실제 작품으로 재 보며 조정한다.
AI_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    ("부정 후 재정의", re.compile(r"(?:단순한|그저|한낱)\s*\S+?(?:이|가)?\s+아니(?:었|였)다|\S+(?:이|가)\s+아니라\s+\S+?(?:이었|였)다"), 1),
    ("셋씩 나열", re.compile(r"[^,.\n\"“”]{1,20}(?:고|며),\s*[^,.\n\"“”]{1,20}(?:고|며),\s*[^,.\n\"“”]+"), 2),
    ("감정 이름 서술", re.compile(
        r"(?:분노|슬픔|불안감?|두려움|공포|안도감?|죄책감|서러움|외로움|허탈감|절망감?|기쁨)(?:이|가|을|를|은|는|에)?\s*"
        r"(?:\S+\s+)?(?:느꼈다|느껴졌다|밀려왔다|밀려들었다|차올랐다|치밀었다|휩싸였다|사로잡혔다|번졌다)"), 3),
    ("번역투", re.compile(r"(?:을|를)\s통해|에\s있어(?:서)?\s|하게\s되었다|하게\s됐다|하는\s중이었다|에\s의해"), 3),
    ("서식 흔적", re.compile(r"—|\*\*|^#", re.M), 0),
]

_PRONOUN = re.compile(r"(?<![가-힣])그(?:녀)?(?:는|가|의|를|에게)(?![가-힣])")

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
    comma_sentence_ratio: Optional[float] = Field(None, description="서술 문장 중 쉼표가 있는 문장 비율. AI 한국어 글은 사람보다 높다")
    short_ending_ratio: Optional[float] = Field(None, description="두 문장 이상 서술 문단 중 12자 이하 짧은 문장으로 끝나는 비율 (여운 연출 남발)")
    pronoun_per_1k: Optional[float] = Field(None, description="1,000자당 '그는/그녀의' 류 대명사 수 (번역투)")
    ai_pattern_hits: list[str] = Field(default_factory=list, description="화당 상한을 넘은 쇠맛 패턴 (이름 n회, 상한 m)")
    pattern_per_1k: dict[str, float] = Field(default_factory=dict, description="쇠맛 패턴별 1,000자당 횟수. 기준값에 있으면 원문이 원래 쓰는 만큼은 경고하지 않는다")
    style_centroid: list[float] = Field(default_factory=list, description="2,000자 조각 3개 이상일 때 어절 끝 특징의 정규화 중심 (문체 거리 기준)")
    style_spread: Optional[float] = Field(None, description="원문 조각들이 서로의 중심에서 떨어진 거리의 중앙값. 문체 거리 1.0 의 기준")
    style_distance: Optional[float] = Field(None, description="기준 원문 대비 문체 거리 (style_spread 의 몇 배). 비교할 때만 채운다")


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


def _short_ending_ratio(paras: list[str]) -> Optional[float]:
    ends = []
    for para in paras:
        sents = sentences(para)
        if len(sents) >= 2 and not _QUOTE.fullmatch(sents[-1]):
            ends.append(len(sents[-1]) <= 12)
    return round(sum(ends) / len(ends), 2) if ends else None


def pattern_counts(text: str) -> dict[str, int]:
    return {name: len(rx.findall(text)) for name, rx, _ in AI_PATTERNS}


def _over_cap(text: str) -> list[str]:
    counts = pattern_counts(text)
    return [f"{name} {counts[name]}회 (상한 {cap})" for name, _, cap in AI_PATTERNS if counts[name] > cap]


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
        comma_sentence_ratio=round(sum("," in s for s in narration) / len(narration), 2) if narration else None,
        short_ending_ratio=_short_ending_ratio(paras),
        pronoun_per_1k=round(len(_PRONOUN.findall(text)) * 1000 / len(text), 1),
        ai_pattern_hits=_over_cap(text),
        pattern_per_1k={k: round(v * 1000 / len(text), 2) for k, v in pattern_counts(text).items()},
        **_style_reference(text),
    )


# ---------- 문체 거리 ----------
# 어절 끝 1~2음절(조사와 어미) 빈도로 잰다. 문체 반영도 연구에서 작가 8명을 가장 안정적으로 가른 특징이다.
# 특징마다 style_background 의 평균과 표준편차로 정규화하고, 원문 2,000자 조각들의 중심까지 코사인 거리를 잰 뒤
# 원문 조각들끼리의 거리(style_spread)로 나눈다. 1.0 이면 원문의 다른 대목만큼 가깝다.
STYLE_CHUNK = 2000
STYLE_MIN_CHUNKS = 3  # 원문이 6,000자보다 짧으면 기준을 만들지 않는다 (2만 자 이상이면 안정적)
# 연구 코퍼스(원문 2만 자 기준)에서 같은 작가의 다른 작품은 중앙값 1.2 (열에 아홉은 1.4 이하), 다른 작가 글은 1.4,
# 문체 자료 없이 쓴 AI 글은 1.3, 프로필과 예시 문단을 넣고 쓴 AI 글은 1.1 안팎이었다. 1.5 를 넘으면 경고한다.
# 같은 작가인지 가르는 힘은 중간 정도라(작품 단위 AUC 0.8 안팎) 한 화의 값보다 화별 흐름으로 본다.
STYLE_DISTANCE_WARN = 1.5


def style_chunks(text: str, size: int = STYLE_CHUNK) -> list[str]:
    out, cur = [], ""
    for para in re.split(r"\n+", text):
        para = para.strip()
        if not para:
            continue
        cur = f"{cur}\n\n{para}" if cur else para
        if len(cur) >= size:
            out.append(cur)
            cur = ""
    return out


def _suffix_z(text: str) -> list[float]:
    c: Counter[str] = Counter()
    for w in re.findall(r"[가-힣]+", text):
        c["1:" + w[-1]] += 1
        if len(w) >= 2:
            c["2:" + w[-2:]] += 1
    n = sum(c.values()) or 1
    return [(c[k] / n - mu) / sd for k, mu, sd in FEATURES]


def _cos_dist(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return 1 - dot / (na * nb) if na and nb else 1.0


def _center(rows: list[list[float]]) -> list[float]:
    return [mean(col) for col in zip(*rows)]


def _style_reference(text: str) -> dict:
    zs = [_suffix_z(c) for c in style_chunks(text)]
    if len(zs) < STYLE_MIN_CHUNKS:
        return {}
    spread = median(_cos_dist(zs[i], _center(zs[:i] + zs[i + 1:])) for i in range(len(zs)))
    return {"style_centroid": [round(x, 4) for x in _center(zs)], "style_spread": round(spread, 4)}


def style_distance(base: StyleMetrics, text: str) -> Optional[float]:
    """기준 원문 대비 문체 거리. 기준에 중심이 없으면(짧은 원문, 예전 기준값) None."""
    if not base.style_centroid or not base.style_spread or len(base.style_centroid) != len(FEATURES) or not text.strip():
        return None
    return round(_cos_dist(_suffix_z(text), base.style_centroid) / base.style_spread, 2)


# ---------- 문체 표지와 베끼기 ----------

def _marker(marker: str) -> str:
    return marker.strip().strip("~-…").strip()


def marker_count(text: str, marker: str) -> int:
    m = _marker(marker)
    return text.count(m) if m else 0


def marker_rate(text: str, marker: str) -> float:
    """표지의 1,000자당 횟수."""
    return round(marker_count(text, marker) * 1000 / len(text), 2) if text else 0.0


def marker_warnings(markers: list, text: str) -> list[str]:
    """원문 빈도(per_1k)가 있는 표지가 이번 본문에서 크게 넘치거나 빠졌는지. markers 는 StyleMarker 목록."""
    out = []
    for mk in markers:
        if not _marker(mk.text) or not mk.per_1k:
            continue
        expected = mk.per_1k * len(text) / 1000
        got = marker_count(text, mk.text)
        if (got >= 3 and got > expected * 2.5) or (expected >= 3 and got < expected / 3):
            out.append(f"'{_marker(mk.text)}' {got}회 (원문 빈도면 {expected:.0f}회 안팎)")
    return out


DEVICE_HITS = 2  # 장치를 알아보는 글자가 한 화에 합쳐 이만큼 나오면 그 장치를 쓴 화로 본다


def device_hits(text: str, cues: list[str]) -> int:
    """가끔 쓰는 장치(StyleDevice)의 알아보는 글자가 본문에 나온 횟수 합."""
    return sum(marker_count(text, c) for c in cues)


def device_used(text: str, cues: list[str]) -> bool:
    return bool(text) and device_hits(text, cues) >= DEVICE_HITS


def device_last(episodes: list, cues: list[str], before: int) -> int:
    """before 화 앞에서 장치를 마지막으로 쓴 화 번호. 없으면 0. episodes 는 Episode 목록."""
    return max((e.plot.number for e in episodes if e.plot.number < before and device_used(e.text, cues)), default=0)


def device_warnings(devices: list, episodes: list, n: int, text: str) -> list[str]:
    """이번 화(n)가 장치를 썼는데 최소 간격 안에 또 쓴 경우. devices 는 StyleDevice 목록."""
    out = []
    for d in devices:
        if not d.cues or not device_used(text, d.cues):
            continue
        last = device_last(episodes, d.cues, n)
        if d.every and last and n - last < d.every:
            out.append(f"'{d.name}' {last}화에 이어 또 씀 ({d.every}화에 한 번까지)")
    return out


COPY_SPAN = 12  # 예시 문단과 이만큼(공백 빼고 글자 수) 똑같이 이어지면 베낀 것으로 본다. 연구에서 문체 자료 없이 쓴 글은 한 번도 걸리지 않았다


def copied_sentences(text: str, passages: list[str], span: int = COPY_SPAN) -> list[str]:
    """예시 문단에서 옮겨 온 문장: 공백을 뺀 글자가 span 자 이상 그대로 겹치는 문장.
    문장 통째 복사와 첫 문장 틀만 바꿔 쓴 것을 함께 잡는다. 문체 예시는 따라 할 것이지 베낄 것이 아니다."""
    grams = set()
    for p in passages:
        q = re.sub(r"\s+", "", p)
        grams.update(q[i:i + span] for i in range(len(q) - span + 1))
    if not grams:
        return []
    out = []
    for s in sentences(text):
        q = re.sub(r"\s+", "", s)
        if any(q[i:i + span] in grams for i in range(len(q) - span + 1)):
            out.append(s)
    return list(dict.fromkeys(out))


def hangul_ratio(text: str) -> float:
    """글자 중 한글 비율. 본문 대신 영어 생각 과정이 나온 응답을 거른다."""
    letters = [c for c in text if c.isalpha()]
    return sum("가" <= c <= "힣" for c in letters) / len(letters) if letters else 0.0


# 기준값과 비교할 지표: (설명, 허용 차이, 상대값 여부)
THRESHOLDS: dict[str, tuple[str, float, bool]] = {
    "sentence_len_mean": ("문장 평균 길이", 0.3, True),
    "sentence_len_cv": ("문장 길이 변화폭", 0.35, True),
    "paragraph_len_mean": ("문단 평균 길이", 0.5, True),
    "dialogue_ratio": ("대사 비율", 0.15, False),
    "past_tense_ratio": ("과거형 서술 비율", 0.2, False),
    "mattr": ("어휘 다양도", 0.08, False),
    "comma_sentence_ratio": ("쉼표 문장 비율", 0.15, False),
    "short_ending_ratio": ("짧은 문장으로 끝나는 문단 비율", 0.2, False),
    "pronoun_per_1k": ("대명사 밀도(1,000자당)", 3.0, False),
}
# 쇠맛 지표는 기준보다 높을 때만 문제라서 낮아진 쪽은 경고하지 않는다.
UPPER_ONLY = {"comma_sentence_ratio", "short_ending_ratio", "pronoun_per_1k"}


def drift(base: StyleMetrics, cur: StyleMetrics) -> list[str]:
    """기준(레퍼런스) 대비 허용 범위를 벗어난 지표를 경고 문장으로 돌려준다."""
    out = []
    for key, (label, limit, relative) in THRESHOLDS.items():
        b, c = getattr(base, key), getattr(cur, key)
        if b is None or c is None or (relative and not b):
            continue
        diff = (c - b) / b if relative else c - b
        if diff > limit or (diff < -limit and key not in UPPER_ONLY):
            shown = f"{diff:+.0%}" if relative else f"{diff:+.2f}"
            out.append(f"{label}: 기준 {b} → {c} ({shown})")
    if cur.repeated_phrases:
        out.append(f"반복 구: {', '.join(cur.repeated_phrases[:5])}")
    if cur.cliche_hits:
        out.append(f"상투·금지 표현: {', '.join(cur.cliche_hits)}")
    hits = _over_base_cap(base, cur) if cur.pattern_per_1k else cur.ai_pattern_hits
    if hits:
        out.append(f"쇠맛 패턴: {', '.join(hits)}")
    if cur.style_distance is not None and cur.style_distance > STYLE_DISTANCE_WARN:
        out.append(f"문체 거리: {cur.style_distance} (원문 대목끼리 1.0, {STYLE_DISTANCE_WARN} 넘으면 다른 작가 글 수준)")
    return out


def _over_base_cap(base: StyleMetrics, cur: StyleMetrics) -> list[str]:
    """화당 상한을 넘은 쇠맛 패턴. 원문(기준값)이 원래 그 패턴을 쓰면 원문 빈도의 1.5배까지는 봐준다."""
    out = []
    for name, _, cap in AI_PATTERNS:
        n = round(cur.pattern_per_1k.get(name, 0) * cur.chars / 1000)
        allowed = max(cap, math.ceil(base.pattern_per_1k.get(name, 0) * cur.chars / 1000 * 1.5))
        if n > allowed:
            out.append(f"{name} {n}회 (상한 {allowed})")
    return out


# ---------- 초반 1~3화 지표 ----------
# 독자가 계속 읽을지 정하는 화에서 설명 덤프, 늦은 주인공, 프롤로그 투 시작과 끝을 LLM 없이 찾는다.
# 경고 기준은 작법 안내의 경험칙에서 잡은 출발점이고, 실제 작품으로 재 보며 조정한다.

OPENING_CLICHES = [  # 첫 두 문장에 나오면 흔한 시작
    ("눈을 뜨는 시작", re.compile(r"눈을\s*(?:떴|뜨)")),
    ("알람 · 기상", re.compile(r"알람|자명종|잠에서\s*깨")),
    ("평범한 자기소개", re.compile(r"평범한")),
    ("'그날' 시작", re.compile(r"(?<![가-힣])그날(?:은|도|,|\s)")),
    ("날씨 · 하늘", re.compile(r"햇살|햇빛|하늘(?:은|이)|비가\s*(?:내리|오)|바람이\s*불")),
    ("'어느 날' 시작", re.compile(r"어느\s*날")),
]
ENDING_CLICHES = [  # 마지막 문단에 나오면 앞날을 해설하는 끝
    ("'몰랐다'", re.compile(r"(?:몰랐다|알지\s*못했다|상상도\s*못)")),
    ("'시작이었다'", re.compile(r"시작(?:이었다|일\s*줄|에\s*불과)")),
    ("운명 · 서막", re.compile(r"운명|서막|폭풍\s*전야|돌이킬\s*수\s*없")),
]
_BACKSTORY = re.compile(r"\d+\s*년\s*전|몇\s*년\s*전|오래전|그\s*시절|어릴\s*적|었었다|였었다|이\s*세계(?:에서|의|는)|이\s*대륙|라고\s*불렸다|라\s*불리는|불리는\s*곳")
_STATUS_LINE = re.compile(r"^\s*[\[【<〈].*[\]】>〉]\s*$", re.M)

OPENING_LIMITS = {
    "first_dialogue_at": 1500,   # 첫 대사까지 글자
    "hero_at": 1000,             # 주인공 이름까지 글자
    "longest_narration": 800,    # 앞 3분의 1에서 대사 없이 이어지는 서술
    "backstory_hits": 3,         # 앞 3분의 1의 회상 · 설명 표지
    "lore_per_1k": 4.0,          # 앞 2,000자의 설정어 밀도
    "named_characters": 5,       # 1화에 이름이 나오는 인물
    "status_ratio": 0.1,         # 상태창 같은 괄호 블록 줄 비율
    "head_dialogue_drop": 0.15,  # 앞 3분의 1 대사 비율이 문체 기준보다 이만큼 낮으면
}


class OpeningMetrics(BaseModel):
    chars: int = 0
    first_dialogue_at: Optional[int] = Field(None, description="첫 대사(따옴표)가 나오는 글자 위치. 대사가 없으면 None")
    head_dialogue_ratio: float = Field(0, description="앞 3분의 1의 대사 비율")
    hero_at: Optional[int] = Field(None, description="주인공 이름이 처음 나오는 글자 위치. 안 나오면 None")
    named: list[str] = Field(default_factory=list, description="이름이 나온 인물 (처음 나온 순서)")
    lore_per_1k: float = Field(0, description="앞 2,000자에서 세계관 장소 · 이야기 요소 이름이 나온 횟수 (1,000자당)")
    longest_narration: int = Field(0, description="앞 3분의 1에서 대사 없이 이어지는 가장 긴 서술 (글자)")
    backstory_hits: int = Field(0, description="앞 3분의 1의 회상 · 설명 표지 수 ('~년 전', '~었었다', '이 세계에서는')")
    opening_cliches: list[str] = Field(default_factory=list, description="첫 두 문장에서 찾은 흔한 시작")
    ending_cliches: list[str] = Field(default_factory=list, description="마지막 문단에서 찾은 앞날 해설")
    status_ratio: float = Field(0, description="상태창처럼 괄호로 감싼 줄의 글자 비율")


def _given(name: str) -> list[str]:
    """'강서윤' → ['강서윤', '서윤']. 한글 세 글자 이름은 성을 뗀 이름으로도 부르니까."""
    name = name.strip()
    out = [name] if name else []
    if len(name) == 3 and all("가" <= ch <= "힣" for ch in name):
        out.append(name[1:])
    return out


def _first_at(text: str, names: list[str]) -> Optional[int]:
    hits = [i for i in (text.find(x) for x in names if x) if i >= 0]
    return min(hits) if hits else None


def measure_opening(text: str, characters: list[str], hero: str = "", lore: list[str] | None = None) -> OpeningMetrics:
    """characters: 설정의 인물 이름, hero: 주인공 이름, lore: 세계관 장소 · 이야기 요소 이름 (두 글자 이상만 센다)."""
    text = text.strip()
    if not text:
        return OpeningMetrics()
    head = text[: max(1, len(text) // 3)]
    q = _QUOTE.search(text)
    quoted = sum(len(m) for m in _QUOTE.findall(head))
    found = sorted(((_first_at(text, _given(c)), c) for c in characters if c.strip()), key=lambda x: (x[0] is None, x[0] or 0))
    early = text[:2000]
    terms = [t.strip() for t in (lore or []) if len(t.strip()) >= 2]
    lore_hits = sum(early.count(t) for t in dict.fromkeys(terms))
    run, longest = 0, 0
    for para in re.split(r"\n\s*\n|\n", head):
        if not para.strip():
            continue
        if _QUOTE.search(para):
            run = 0
        else:
            run += len(para.strip())
            longest = max(longest, run)
    sents = sentences(text)
    first2 = " ".join(sents[:2])
    paras = [x for x in re.split(r"\n\s*\n", text) if x.strip()]
    last = paras[-1] if paras else ""
    status = sum(len(m) for m in _STATUS_LINE.findall(text))
    return OpeningMetrics(
        chars=len(text),
        first_dialogue_at=q.start() if q else None,
        head_dialogue_ratio=round(quoted / len(head), 2),
        hero_at=_first_at(text, _given(hero)) if hero else None,
        named=[c for at, c in found if at is not None],
        lore_per_1k=round(lore_hits * 1000 / max(len(early), 1000), 1),  # 아주 짧은 글이 튀지 않게
        longest_narration=longest,
        backstory_hits=len(_BACKSTORY.findall(head)),
        opening_cliches=[name for name, rx in OPENING_CLICHES if rx.search(first2)],
        ending_cliches=[name for name, rx in ENDING_CLICHES if rx.search(last)],
        status_ratio=round(status / len(text), 2),
    )


def opening_warnings(m: OpeningMetrics, n: int, base_dialogue: Optional[float] = None, hero: str = "") -> list[str]:
    """초반 지표에서 기준을 넘은 것을 경고 문장으로. n 은 화 번호 (인물 수는 1화만 본다)."""
    if not m.chars:
        return []
    L = OPENING_LIMITS
    out = []
    if m.first_dialogue_at is None:
        out.append("대사가 한 줄도 없어요. 초반에는 주인공의 목소리가 들려야 해요")
    elif m.first_dialogue_at > L["first_dialogue_at"]:
        out.append(f"첫 대사가 {m.first_dialogue_at:,}자 뒤에 나와요 (기준 {L['first_dialogue_at']:,}자)")
    if base_dialogue is not None and m.head_dialogue_ratio < base_dialogue - L["head_dialogue_drop"]:
        out.append(f"앞 3분의 1 대사 비율 {m.head_dialogue_ratio} (문체 기준 {base_dialogue})")
    if hero:
        if m.hero_at is None:
            out.append(f"주인공 {hero}의 이름이 나오지 않아요")
        elif m.hero_at > L["hero_at"]:
            out.append(f"주인공 {hero}의 이름이 {m.hero_at:,}자 뒤에 처음 나와요 (기준 {L['hero_at']:,}자)")
    if n == 1 and len(m.named) > L["named_characters"]:
        out.append(f"1화에 이름이 나온 인물이 {len(m.named)}명이에요 (기준 {L['named_characters']}명): {', '.join(m.named)}")
    if m.lore_per_1k > L["lore_per_1k"]:
        out.append(f"앞 2,000자에 설정어가 1,000자당 {m.lore_per_1k}번 나와요. 설정 설명이 몰렸는지 보세요")
    if m.longest_narration > L["longest_narration"]:
        out.append(f"앞부분에 대사 없이 {m.longest_narration:,}자가 이어져요 (기준 {L['longest_narration']}자)")
    if m.backstory_hits >= L["backstory_hits"]:
        out.append(f"앞부분에 회상 · 설명 표지가 {m.backstory_hits}번 있어요 ('~년 전', '~었었다', '이 세계에서는' 등)")
    if m.opening_cliches:
        out.append(f"흔한 시작: {', '.join(m.opening_cliches)}")
    if m.ending_cliches:
        out.append(f"끝 문단의 앞날 해설: {', '.join(m.ending_cliches)}")
    if m.status_ratio > L["status_ratio"]:
        out.append(f"상태창 같은 괄호 블록이 본문의 {m.status_ratio:.0%}예요")
    return out
