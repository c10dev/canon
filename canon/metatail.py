"""본문 앞뒤에 섞인 작업 설명(메타 코멘트) 찾기. LLM 호출 없음.

쓰기 모델이 본문 끝에 "마지막으로 짚어 둘 것이 있습니다. 스타일 프로필은 …" 같은 작가에게 하는 말을 붙이거나,
앞에 "네, 25화 본문입니다." 같은 머리말을 붙이는 일이 있다 (2026-10-31 블록 시험, Claude Code 쓰기 25화).
본문 대신 거절 · 되묻기 응답이 오기도 한다 (치한-자동 20화의 이전 판 둘). 쓰기 지시(`prompts._WRITER`)가 본문만 내라고 해도 생긴다.

떼는 것은 확실할 때만이다. 작가물(작가 · 편집자가 나오는 이야기)이나 편지 · 시스템 창 · 이야기꾼의 맺음말도 존댓말과
'원고 · 다음 화 · 원하시면' 같은 말을 쓰기 때문이다 (2026-10-31 적대적 검토).
- 판단은 따옴표 · 줄표 대사와 대괄호 시스템 글을 뺀 서술만 본다.
- 확실한 메타(`split` 이 뗌): 앞이나 뒤에서 이어진 문단 가운데 Canon 작업 낱말(`STRONG`: 스타일 프로필 · 플롯 · 본문을 … 처럼
  이야기 속에서 거의 안 쓰는 말)이 있고 존댓말 문장이 반 넘는 문단, 'n화 본문입니다' 같은 머리말, '작가 메모' 머리와 그 뒤 목록,
  한글이 거의 없는 영어 메모. 본문 서술이 원래 존댓말인 작품에서는 작업 낱말이 둘 넘어야 한다.
- 덜 확실한 것(`warnings`): 흔한 말(`SOFT`: 원고 · 다음 화 · 원하시면 …)만 있는 앞뒤 문단, 구분선 뒤의 꼬리. 떼지 않고 검수 화면에 알린다.
- 응답 전체가 메타(`whole`): 존댓말 문단에 작업 낱말 · 거절 말이 있는 문단이 둘 넘고 30% 넘거나, 짧은 응답이 거절 · 되묻기 말로 끝날 때.
"""
from __future__ import annotations

import re

# 이야기 속에서 거의 쓰지 않는 Canon 작업 낱말과 작가에게 하는 말
STRONG = (
    "스타일 프로필", "예시 문단", "플롯", "프롬프트", "큐 시트", "스토리보드", "작업지시서", "요구사항", "지시사항", "지시에 따라",
    "서술 시점", "시점 인물", "본문을", "본문은", "본문만", "본문입니다", "본문이에요", "본문에서", "요청하신", "요청대로", "말씀하신",
    "짚어 둘", "써 드렸", "작성해 드", "작성했습니다", "반영했습니다", "반영하였습니다",
)
STRONG_RX = re.compile(r"\d+\s*화\s*(?:본문|원고)|\d+\s*화(?:를|의)?\s*(?:마칩니다|마무리했|작성)|이상으로\s*\d*\s*화")
# 이야기에도 나오는 말: 앞뒤 문단에 있으면 알리기만 한다
SOFT = (
    "분량", "글자 수", "자 내외", "이번 화", "다음 화", "회차", "본문", "원고", "초안", "원하시면", "필요하시면", "말씀해 주",
    "작가님", "독자분", "수정했", "반영했", "고쳐 드", "써 드릴", "참고로 ", "이상으로",
)
REFUSE = ("쓸 수 없습니다", "쓰기 어렵습니다", "작성할 수 없", "작성하기 어렵", "도와드릴 수 없", "제공할 수 없", "죄송하지만", "죄송합니다만",
          "콘텐츠 정책", "쓰지 않겠습니다", "드릴까요", "할까요?", "원하시는 방향")
_MEMO_HEAD = re.compile(r"^\s*(?:#{1,6}\s*|\*\*|__)\s*(?:작가\s*(?:메모|노트|의\s*말)|메모|참고|변경\s*사항|수정\s*사항|노트|notes?)\b", re.I)
_LIST = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_POLITE = re.compile(r"(?:습니다|ㅂ니다|입니다|십시오|세요|어요|아요|해요|예요|이에요|에요|죠|게요|까요|니다)[.!?…~\s)）\]*_]*$")
_PROTECTED = re.compile(r"^\s*[\"“「『'‘\[【<〈《—―–]")  # 대사 · 시스템 창으로 시작하는 문단은 보지 않는다
_INNER_QUOTE = re.compile(r"[\"“][^\"”]*[\"”]|「[^」]*」|『[^』]*』|‘[^’]*’|\[[^\]]*\]|【[^】]*】")
_RULE = re.compile(r"^\s*(?:[-*_=]\s*){3,}$")
_PREAMBLE = re.compile(r"^\s*(?:네[,.!]?\s*|알겠습니다[.!]?\s*|물론입니다[.!]?\s*)?(?:다음은|아래는|요청하신)?\s*\d+\s*화(?:\s*본문|\s*원고)?\s*(?:입니다|이에요|예요|:)")
_ENGLISH_META = re.compile(r"\b(?:note|here is|here's|chapter|episode|word count|as requested|let me know|pov|draft)\b", re.I)
_SENT = re.compile(r"(?<=[.!?…])\s+")
_DECOR = re.compile(r"^[\s#*_>]+|[\s*_]+$")


def _paras(text: str) -> tuple[list[str], str]:
    """(문단들, 잇는 글). 빈 줄이 없는 글은 줄마다 문단으로 본다."""
    text = text.replace("\r\n", "\n").strip()
    paras = [x for x in re.split(r"\n\s*\n", text) if x.strip()]
    if len(paras) <= 2 and text.count("\n") >= 3:
        return [x for x in text.split("\n") if x.strip()], "\n"
    return paras, "\n\n"


def _narration(para: str) -> str:
    """판단에 쓸 서술: 문단 안 대사 · 대괄호 글을 빼고 앞뒤 마크다운 꾸밈을 벗긴다."""
    return _DECOR.sub("", _INNER_QUOTE.sub(" ", para)).strip()


def _sentences(text: str) -> list[str]:
    return [s for s in _SENT.split(text.strip()) if re.search(r"[가-힣]", s)]


def _polite_share(para: str) -> float:
    ss = _sentences(_narration(para))
    return sum(bool(_POLITE.search(s)) for s in ss) / len(ss) if ss else 0.0


def _strong(para: str) -> int:
    t = _narration(para)
    return sum(w in t for w in STRONG) + len(STRONG_RX.findall(t))


def _soft(para: str) -> int:
    t = _narration(para)
    return sum(w in t for w in SOFT)


def _hangul(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum("가" <= c <= "힣" for c in letters) / len(letters) if letters else 0.0


def polite_body(paras: list[str]) -> bool:
    """본문 서술이 원래 존댓말인지: 대사를 뺀 서술 문장 가운데 존댓말 끝이 30% 넘으면."""
    ss = [s for p in paras if not _PROTECTED.match(p) for s in _sentences(_narration(p))]
    return bool(ss) and sum(bool(_POLITE.search(s)) for s in ss) / len(ss) > 0.3


def _sure(para: str, polite: bool) -> bool:
    if _PROTECTED.match(para) or _RULE.match(para):
        return False
    if _PREAMBLE.match(_DECOR.sub("", para)) and len(_sentences(_narration(para))) <= 2:
        return True
    if _MEMO_HEAD.match(para):
        return True
    if _hangul(para) < 0.2 and _ENGLISH_META.search(para):
        return True
    hits = _strong(para)
    if not hits or _polite_share(para) <= 0.5:
        return False
    return hits >= 2 if polite else True


def split(text: str) -> tuple[str, list[str]]:
    """(본문, 뗀 문단들). 앞과 뒤에서 이어진 확실한 메타 문단만 뗀다. 메타 문단 바로 안쪽의 구분선, '작가 메모' 머리 뒤의 목록도 함께 뗀다."""
    paras, sep = _paras(text)
    if len(paras) < 3:
        return text, []
    polite = polite_body(paras[1:-1])
    head = 0
    while head < len(paras) - 2 and _sure(paras[head], polite):
        head += 1
    if head and _RULE.match(paras[head]):
        head += 1
    tail = len(paras)
    memo = next((k for k in range(max(head + 1, len(paras) - 6), len(paras)) if _MEMO_HEAD.match(paras[k])), None)
    if memo is not None and all(_LIST.match(x) or _sure(x, polite) or _soft(x) for x in paras[memo + 1:]):
        tail = memo
    while tail - 1 > head + 1 and _sure(paras[tail - 1], polite):
        tail -= 1
    if tail < len(paras) and tail - 1 > head and _RULE.match(paras[tail - 1]):
        tail -= 1
    if head == 0 and tail == len(paras):
        return text, []
    return sep.join(paras[head:tail]), paras[:head] + paras[tail:]


def warnings(text: str) -> list[str]:
    """떼지 않은 앞뒤 두 문단 가운데 작업 설명일 수 있는 것 (검수 화면 문체 경고). 확실한 것은 쓰기 때 이미 뗀다."""
    paras, _ = _paras(text)
    if len(paras) < 3:
        return []
    out = []
    edge = set(range(2)) | set(range(len(paras) - 2, len(paras)))
    for k in sorted(edge):
        para = paras[k]
        if _PROTECTED.match(para):
            continue
        after_rule = k > 0 and _RULE.match(paras[k - 1]) and k >= len(paras) - 2
        if _strong(para) or _soft(para) or after_rule:
            out.append(para.strip())
    return list(dict.fromkeys(out))


def whole(text: str) -> bool:
    """응답 전체가 본문이 아니라 작업 설명 · 거절 · 되묻기인지.
    - 존댓말 문단(대사 뺀 서술 기준)에 작업 낱말이나 거절 말이 든 문단이 둘 넘고 서술 문단의 30% 넘으면
    - 또는 짧은 응답(800자 미만 · 서술 문단 셋 이하 · 대사 없음)이 존댓말이고 거절 · 되묻기 말을 담으면
    실제 작품 본문 303개에서는 하나도 걸리지 않았다 (2026-10-31)."""
    paras, _ = _paras(text)
    plain = [p for p in paras if not _PROTECTED.match(p)]
    if not plain:
        return False
    refuse = lambda p: any(w in _narration(p) for w in REFUSE)  # noqa: E731
    meta = [p for p in plain if _polite_share(p) > 0.5 and (_strong(p) or refuse(p))]
    if len(meta) >= 2 and len(meta) / len(plain) > 0.3:
        return True
    short = len(text.strip()) < 800 and len(plain) <= 3 and len(plain) == len(paras)
    return short and sum(_polite_share(p) > 0.5 for p in plain) * 2 > len(plain) and any(refuse(p) for p in plain)
