"""압력으로 다시 쓰기 (docs/webnovel/specs/11-pressure.md 11b): 버릇 문장 · 대사 예시를 빼는 글 계산. LLM 을 부르지 않는다.
AI 는 압력 문장과 버릇 문장(글자 그대로)만 고르고, 남는 글은 작가가 쓴 글 그대로다. 저장하지 않는다."""
from __future__ import annotations

import re

from . import elements, metrics
from .schema import Character, PressureProposal, PressureRewrite

CALLED = ("라고", "이라고", "라 부", "라부", "로 부", "으로 부", "하고 부")  # 따옴표 뒤가 이렇게 이어지면 호칭이다
LABEL = re.compile(r"(?<![가-힣A-Za-z])[(\[（]?[ \t]*(?:예시|예|대사)[ \t]*(?:[:：]|\))[ \t]*$")
SEP = "[,，·/、]"
GONE = "\x00"  # 지운 자리 표시 (정리가 끝나면 모두 지운다)


def lines(style: str) -> list[tuple[int, int]]:
    """말투 글의 대사 예시 자리 (따옴표 포함, 앞에서부터). 따옴표 규칙은 metrics.SPEECH_QUOTE 와 같다.
    바로 앞 8자 안에 metrics.SPEECH_HABIT('말버릇' · '입버릇')이 있으면 뺀다 (metrics.speech_examples 와 같은 규칙).
    닫는 따옴표 바로 뒤가 (공백 0~1개 뒤) '라고' · '이라고' · '라 부' · '라부' · '로 부' · '으로 부' · '하고 부' 로 시작하면 호칭이라 뺀다."""
    out = []
    style = style or ""
    for m in metrics.SPEECH_QUOTE.finditer(style):
        if any(w in style[max(0, m.start() - 8):m.start()] for w in metrics.SPEECH_HABIT):
            continue
        rest = style[m.end():]
        if rest[:1].isspace():
            rest = rest[1:]
        if rest.startswith(CALLED):
            continue
        if style[m.start():m.end()].strip(" \t\"“”「」『』'‘’"):
            out.append((m.start(), m.end()))
    return out


def cut(text: str, spans: list[tuple[int, int]]) -> str:
    """spans 를 지운 글. spans 가 없으면 text 를 그대로 돌려준다(strip 도 하지 않음).
    - 지운 자리 바로 앞(공백 무시)에 '예:' · '예시:' · '예)' · '대사:' 같은 이름표가 있으면 함께 지운다 ('(예:' 의 여는 괄호 포함).
    - 지운 뒤 남은 빈 괄호 '( )' · '(, )' · '[ ]' 는 지운다.
    - 쉼표 · 가운뎃점 · 빗금만 남은 이음('"a", "b"' 를 둘 다 지운 뒤의 ', ')은 지운다.
    - 줄 안의 겹빈칸은 하나로, 문장부호 앞 빈칸은 지운다, 빈 줄이 된 줄은 지운다, 앞뒤 빈칸은 strip."""
    if not spans:
        return text
    ext = []
    for a, b in sorted(spans):
        m = LABEL.search(text[:a])
        ext.append((m.start() if m else a, b))
    merged: list[list[int]] = []
    for a, b in sorted(ext):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out, at = [], 0
    for a, b in merged:
        out.append(text[at:a])
        out.append(GONE)
        at = b
    out.append(text[at:])
    t = "".join(out).replace("\r", "")
    t = re.sub(rf"[(\[（][ \t,，·/、]*{GONE}[ \t{GONE},，·/、]*[)\]）]", GONE, t)  # 빈 괄호
    t = re.sub(rf"{GONE}(?:[ \t]*{SEP}[ \t]*{GONE})+", GONE, t)  # 지운 것끼리 남은 이음
    t = re.sub(rf"(^|[\s(\[（]){GONE}[ \t]*{SEP}+[ \t]*", rf"\1{GONE}", t, flags=re.M)  # 앞에 남은 이음
    t = re.sub(rf"[ \t]*{SEP}+[ \t]*{GONE}(?=[ \t]*(?:[)\]）]|$))", GONE, t, flags=re.M)  # 뒤에 남은 이음
    rows = []
    for line in t.split("\n"):
        if GONE not in line:
            rows.append(line)
            continue
        line = line.replace(GONE, "")
        line = re.sub(r"(?<=\S)[ \t]{2,}", " ", line)
        line = re.sub(r"[ \t]+(?=[.,!?;:)\]。，、…])", "", line).rstrip()
        if line.strip():
            rows.append(line)
    return "\n".join(rows).strip()


def proposal(c: Character, s: PressureRewrite) -> PressureProposal:
    """AI 응답을 화면 제안으로. 버릇 문장마다 elements.find(c.personality, h) 로 자리를 찾고 못 찾으면 dropped += 1.
    찾은 자리끼리 겹치면 하나만 쓴다. habits 에는 찾은 자리의 원문 글을 넣는다.
    대사 예시는 lines(c.speech_style). pressure · note 는 strip. *_before 에는 c 의 지금 값."""
    spans: list[tuple[int, int]] = []
    dropped = 0
    for h in s.habits:
        if not h.strip():
            continue
        r = elements.find(c.personality, h)
        if r is None:
            dropped += 1
        elif not any(r[0] < b and a < r[1] for a, b in spans):
            spans.append(r)
    spans.sort()
    ex = lines(c.speech_style)
    return PressureProposal(
        pressure=s.pressure.strip(), pressure_before=c.pressure,
        personality=cut(c.personality, spans), personality_before=c.personality,
        habits=[c.personality[a:b] for a, b in spans],
        speech_style=cut(c.speech_style, ex), speech_before=c.speech_style,
        lines=[c.speech_style[a:b] for a, b in ex],
        dropped=dropped, note=s.note.strip())
