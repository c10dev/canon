"""본문을 다른 곳(웹소설 플랫폼, 블로그, 원고 파일)에 붙여 넣기 좋게 다듬는다. LLM 을 부르지 않는다.

글 내용은 바꾸지 않고 줄바꿈, 공백, 마크다운 흔적만 정리한다. 화면 복사(텍스트와 HTML 두 형식)와
.txt 내려받기, CLI export 가 모두 이 함수를 쓴다.
"""
from __future__ import annotations

import html
import re

from .schema import Project

# id → (화면 이름, 설명)
FORMATS: dict[str, tuple[str, str]] = {
    "blank": ("문단 사이 빈 줄", "웹소설 플랫폼처럼 문단마다 빈 줄을 하나 둔다"),
    "compact": ("빈 줄 없이", "문단 간격을 편집기가 넣는 블로그 · 카페용. 문단마다 줄바꿈 하나"),
    "indent": ("첫 줄 들여쓰기", "원고 · 공모전용. 문단 첫머리를 한 칸 들이고 빈 줄 없이"),
    "raw": ("원문 그대로", "Canon 에 저장된 본문 그대로"),
}

_ZERO_WIDTH = re.compile(r"[​-‍⁠﻿]")
_MD_LINE = re.compile(r"^\s*#{1,6}\s+")  # 마크다운 제목 표시. 장면 구분(***, ---)은 글이라 남긴다
_MD_INLINE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")


def clean_line(line: str) -> str:
    line = _ZERO_WIDTH.sub("", line).replace(" ", " ").replace("\t", " ")
    line = _MD_LINE.sub("", line)
    line = _MD_INLINE.sub(lambda m: m.group(1) or m.group(2), line)
    return re.sub(r" {2,}", " ", line).strip()


def paragraphs(text: str) -> list[list[str]]:
    """문단 목록. 문단은 줄 목록이다. 빈 줄로 나누고, 빈 줄이 하나도 없으면 줄마다 문단으로 본다."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [clean_line(x) for x in text.split("\n")]
    if "" not in lines[1:-1] or not any(lines):
        return [[x] for x in lines if x]
    out: list[list[str]] = []
    cur: list[str] = []
    for x in lines:
        if x:
            cur.append(x)
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def format_text(text: str, fmt: str = "blank") -> str:
    if fmt not in FORMATS:
        raise ValueError(f"모르는 형식이에요: {fmt} ({' | '.join(FORMATS)})")
    if fmt == "raw":
        return text.strip()
    paras = paragraphs(text)
    if fmt == "indent":
        return "\n".join("　" + "\n".join(p) for p in paras)
    sep = "\n\n" if fmt == "blank" else "\n"
    return sep.join("\n".join(p) for p in paras)


def format_html(text: str, fmt: str = "blank") -> str:
    """서식 있는 편집기(블로그, 플랫폼 에디터)에 붙여 넣을 때 쓰는 HTML. 문단은 <p>, 빈 줄은 빈 <p>."""
    if fmt == "raw":
        return "".join(f"<p>{html.escape(x) or '<br>'}</p>" for x in text.strip().split("\n"))
    paras = paragraphs(text)
    lead = "　" if fmt == "indent" else ""
    blocks = [f"<p>{lead}{'<br>'.join(html.escape(x) for x in p)}</p>" for p in paras]
    return ("<p><br></p>" if fmt == "blank" else "").join(blocks)


def title_line(p: Project, n: int) -> str:
    t = p.episode(n).plot.title.strip()
    return f"{n}화. {t}" if t else f"{n}화"


def export(p: Project, numbers: list[int], fmt: str = "blank", title: bool = True,
           drafts: dict[int, str] | None = None) -> dict:
    """화들을 하나의 글로 잇는다. drafts 는 저장 전 화면의 본문(화 번호 → 글). 본문이 없는 화는 건너뛴다.
    {'text', 'html', 'episodes', 'filename'} 를 돌려준다."""
    drafts = drafts or {}
    texts, htmls, used = [], [], []
    for n in sorted(set(numbers)):
        body = drafts.get(n, p.episode(n).text)
        if not body.strip():
            continue
        t, h = format_text(body, fmt), format_html(body, fmt)
        if title or len(numbers) > 1:  # 여러 화를 이을 때는 화 구분이 필요해 제목을 늘 넣는다
            head = title_line(p, n)
            t = f"{head}\n\n{t}"
            h = f"<p><strong>{html.escape(head)}</strong></p><p><br></p>{h}"
        texts.append(t)
        htmls.append(h)
        used.append(n)
    if not used:
        raise ValueError("본문이 있는 화가 없어요")
    name = re.sub(r'[\\/:*?"<>|]', "", p.meta.title).strip() or "canon"
    span = f"{used[0]}화" if len(used) == 1 else f"{used[0]}-{used[-1]}화"
    return {"text": "\n\n\n".join(texts) + "\n", "html": "<p><br></p><p><br></p>".join(htmls), "episodes": used,
            "filename": f"{name} {span}.txt"}
