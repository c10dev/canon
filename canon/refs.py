"""레퍼런스 원고: 작가가 넣은 다른 소설 원고(txt)를 화 표시('1화' · '제1화' · '[1화]' · 'EP.1' …)로 화 단위로 나눠 작품 밖에 둔다.

원고 하나가 <CANON_HOME>/.refs/<id>/ 폴더 하나다 (CANON_REFS 로 경로 변경). source.txt 에 정규화한 원문 전체를,
ref.json(RefBook)에 경계(줄 번호)와 화별 지표를 둔다. 경계를 다시 고쳐도 원문은 바뀌지 않고, 화 글은 읽을 때 잘라 낸다.
작품에는 연결하지 않는다. 쓸 때 결과물(문체 라이브러리 항목 · 역설계 실험)을 만들고 그 결과물만 작품에 들어간다.

나누기 규칙(split)은 이곳 하나다. 역설계 실험(revlab.split)도 이 함수를 부른다. 설계는 docs/refs/README.md.
- 화 표시 줄 → 기호 줄('===' · '***' · '---') → 빈 줄 셋 넘게 → 한 화
- 화 표시 줄은 단위(화 · 회 · 편 · 장 · 話 · EP · Chapter)마다 모아 번호 줄기가 가장 긴 단위를 고른다
- 번호 줄기(가장 긴 증가 수열) 밖의 줄은 '본문 속 언급 같음'으로 보고 끈다. 지우지 않고 작가가 다시 켤 수 있다
"""
from __future__ import annotations

import bisect
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import metrics, store
from .schema import RefBook, RefCut, RefEp, RefFile

ID_RE = re.compile(r"^[0-9a-f]{8,32}$")
HEAD_MAX = 80  # 화 표시로 보는 가장 긴 줄 (공통 머리 · 제목 포함)
MAX_CHARS = 10_000_000
MAX_CUTS = 3000
SHORT_CHARS = 300  # 이보다 짧은 화는 '아주 짧음'
LONG_TIMES = 3  # 평균의 이 배수를 넘으면 '아주 김'
DUP_GAP = 200  # 같은 번호 화 표시 사이 글이 이보다 짧으면 반복 머리 (목차 줄 · 제목 한 번 더)
TOC_GAP = 50  # 화 표시 사이 글이 이보다 짧은 줄이 TOC_RUN 개 넘게 이어지면 목차
TOC_RUN = 10
RUN_MIN = 3  # 번호가 다시 시작한 뒤 이만큼 이어 올라야 새 줄기로 본다
RUN_STEP = 3  # 새 줄기에서 다음 번호까지 허락하는 건너뜀 (번호 빠짐 몇 개)
COMMON_MIN = 3  # 숫자 앞 글이 같은 화 표시 줄이 이만큼 있으면 공통 머리로 본다
TAIL_FROM = 0.6  # 작가의 말 줄은 화의 이 비율 뒤에 있을 때만 뗀다
SAMPLE_MAX = 30_000  # 문체 만들기에 넘기는 원문 글자 수 (revlab.STYLE_CHARS 와 같은 값)

RULES: dict[str, str] = {"heading": "화 표시 줄", "mark": "기호 줄", "blank": "빈 줄 셋 넘게", "one": "한 화", "custom": "직접 패턴"}
KINDS: dict[str, str] = {"main": "본편", "prologue": "프롤로그", "side": "외전", "epilogue": "에필로그", "skip": "제외"}
FLAGS: dict[str, str] = {"gap": "번호 빠짐", "dup": "번호 겹침", "back": "번호 거꾸로", "mention": "본문 속 언급 같음",
                         "short": "아주 짧음", "long": "아주 김", "toc": "목차", "restart": "번호 다시 시작"}
WARN = {"gap", "dup", "back", "mention", "short", "long", "restart"}  # 확인할 것으로 세는 표시

# 단위 차례: 줄기 길이가 같으면 앞 단위를 고른다
SUFFIX_UNITS = ["화", "회", "편", "話", "장"]
PREFIX_UNITS = {"ep": "EP", "episode": "EP", "chapter": "Chapter", "ch": "Chapter"}
UNIT_ORDER = ["화", "회", "편", "話", "EP", "Chapter", "장"]
_OPEN = r"[\s#\[【〈《<(\-=*]*"
_CLOSE = r"[\]】〉》>)]*"
_SEP = r"(?:\s*[.:：\-—)]\s*|\s+|$)"
SUFFIX_RE = re.compile(rf"^{_OPEN}(?P<pre>.*?)(?:[제第]\s*)?(?<!\d)(?P<num>\d{{1,5}})(?:\s*-\s*(?P<sub>\d{{1,2}}))?\s*(?P<unit>화|회|편|話|장)"
                       rf"(?:\s*\(\s*(?P<part>\d{{1,2}})\s*\)|\s*(?P<half>[상중하])(?=\W|$))?\s*{_CLOSE}{_SEP}(?P<title>.*)$")
PREFIX_RE = re.compile(rf"^{_OPEN}(?P<pre>.*?)(?P<unit>episode|chapter|ep|ch)\s*\.?\s*(?P<num>\d{{1,4}})(?:\s*-\s*(?P<sub>\d{{1,2}}))?\s*{_CLOSE}{_SEP}(?P<title>.*)$",
                       re.IGNORECASE)
SPECIAL = {"프롤로그": "prologue", "서장": "prologue", "prologue": "prologue", "에필로그": "epilogue", "종장": "epilogue",
           "epilogue": "epilogue", "외전": "side", "번외": "side", "완결 후기": "skip", "완결후기": "skip", "후기": "skip"}
SPECIAL_RE = re.compile(rf"^{_OPEN}(?P<pre>.*?)(?P<word>완결\s*후기|프롤로그|에필로그|서장|종장|외전|번외|후기|prologue|epilogue)"
                        rf"(?:\s*(?P<num>\d{{1,3}}))?\s*{_CLOSE}{_SEP}(?P<title>.*)$", re.IGNORECASE)
SIDE_RE = re.compile(r"(외전|번외)")
TAIL_RE = re.compile(r"^[\s\[【〈<(\-=*]*(?:작가의\s*말|작가\s*후기|공지|author'?s\s*note)\s*[\]】〉>)]*\s*[:：]?\s*$", re.IGNORECASE)
MARK_RE = re.compile(r"^\s*(?:={3,}|\*{3,}|-{3,}|(?:\*\s*){3,})\s*$")
BLANK_RUN = 3  # 빈 줄이 이만큼 넘게 이어지면 경계 (revlab 의 '빈 줄 세 개 넘게')


def _norm(text: str) -> str:
    return text.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")


def lines_of(text: str) -> list[str]:
    return _norm(text).split("\n")


# ---------- 화 표시 후보 ----------

def _key(pre: str) -> str:
    """숫자 앞 글을 비교하는 열쇠: 꾸밈 · 공백을 빼고 숫자는 '#' 으로 ('1부 ' 와 '2부 ' 는 같은 머리)."""
    return re.sub(r"\d+", "#", re.sub(r"[\s\[\]【】〈〉《》<>()#\-=*.:：]+", "", pre))


PAIRS = {"]": "[", "】": "【", "〉": "〈", "》": "《", ">": "<", ")": "("}


def _title(t: str) -> str:
    """제목에서 화 표시 전체를 감싼 괄호의 닫는 쪽을 뗀다 ('< EP.1 : 시작 >' → '시작'). 제목 안에서 열린 괄호는 둔다."""
    t = t.strip()
    while t and t[-1] in PAIRS and t.count(PAIRS[t[-1]]) < t.count(t[-1]):
        t = t[:-1].rstrip()
    return t


def _special(c: dict) -> dict:
    """번호 화 표시의 제목이 특수 화 이름뿐이면('EP.0 : 프롤로그') 그 종류로 본다. 0화면 이름표도 그 이름이다."""
    word = re.sub(r"\s+", " ", c["title"]).lower()
    kind = SPECIAL.get(word, SPECIAL.get(word.replace(" ", "")))
    if kind and c["kind"] == "main":
        c["kind"] = kind
        if not c["num"]:
            c["word"] = c["title"]
    return c


def _parse(line: str) -> Optional[dict]:
    """줄 하나를 화 표시 후보로 읽는다. 아니면 None. 값: unit · num · sub · title · kind · pre(공통 머리 비교용)."""
    if not line.strip() or len(line) > HEAD_MAX:
        return None
    m = SUFFIX_RE.match(line)
    if m:
        pre = m.group("pre")
        side = bool(SIDE_RE.search(pre))
        sub = m.group("sub") or m.group("part") or m.group("half") or ""
        return _special({"unit": m.group("unit"), "num": int(m.group("num")), "sub": sub, "title": _title(m.group("title")),
                         "kind": "side" if side else "main", "pre": SIDE_RE.sub("", pre)})
    m = PREFIX_RE.match(line)
    if m and not m.group("pre").strip()[-1:].isalpha():  # 'deep 3' 같은 영어 낱말 끝은 아니다
        return _special({"unit": PREFIX_UNITS[m.group("unit").lower()], "num": int(m.group("num")), "sub": m.group("sub") or "",
                         "title": _title(m.group("title")), "kind": "main", "pre": m.group("pre")})
    m = SPECIAL_RE.match(line)
    if m:
        word = re.sub(r"\s+", " ", m.group("word").lower())
        kind = SPECIAL.get(word, SPECIAL.get(word.replace(" ", ""), "side"))
        return {"unit": "", "num": int(m.group("num")) if m.group("num") else 0, "sub": "", "title": _title(m.group("title")),
                "kind": kind, "pre": m.group("pre"), "word": m.group("word")}
    return None


def _custom_re(example: str) -> re.Pattern:
    """예시 한 줄('[제12화] 제목')에서 꼴을 만든다: 첫 숫자 자리 앞 글 + 숫자 + 숫자 바로 뒤 붙은 글 + 제목."""
    m = re.search(r"\d+", example or "")
    if not m:
        raise ValueError("예시 줄에 화 번호(숫자)가 없어요")
    before = example[:m.start()].strip()
    after = re.match(r"\S*", example[m.end():]).group(0)
    return re.compile(rf"^\s*{re.escape(before)}\s*(?P<num>\d{{1,4}})\s*{re.escape(after)}{_SEP}(?P<title>.*)$")


def _lis(keys: list[tuple]) -> set[int]:
    """가장 긴 (엄격히) 증가하는 수열에 드는 자리들."""
    tails, tail_at, prev = [], [], [-1] * len(keys)
    for i, k in enumerate(keys):
        j = bisect.bisect_left(tails, k)
        if j == len(tails):
            tails.append(k)
            tail_at.append(i)
        else:
            tails[j], tail_at[j] = k, i
        prev[i] = tail_at[j - 1] if j else -1
    out, i = set(), tail_at[-1] if tail_at else -1
    while i >= 0:
        out.add(i)
        i = prev[i]
    return out


def _runs(cs: list[dict]) -> list[list[dict]]:
    """번호가 처음부터 다시 시작하는 자리(2부 1화, 한 파일에 이은 2권)에서 줄을 나눈다.
    번호가 앞 두 줄보다 작거나 같고, 그 줄부터 RUN_MIN 개 넘게 번호가 이어 오르면 새 줄기다.
    앞 두 줄을 보는 것은 3화 본문 속 '9화' 한 줄 뒤의 4화를 새 줄기로 잘못 보지 않게 하려는 것이다.
    이어 오르지 않는 줄은 앞 줄기에 남아 번호 줄기 밖(본문 속 언급)이 된다."""
    out: list[list[dict]] = [[]]
    for i, c in enumerate(cs):
        last = out[-1][-1] if out[-1] else None
        before = out[-1][-2] if len(out[-1]) > 1 else None
        if last is not None and c["num"] < last["num"] and (before is None or c["num"] <= before["num"]):
            k, prev = 1, c["num"]
            for x in cs[i + 1:]:
                if not prev < x["num"] <= prev + RUN_STEP:
                    break
                k, prev = k + 1, x["num"]
            if k >= RUN_MIN:
                out.append([])
        out[-1].append(c)
    return out


def _chain_len(cs: list[dict]) -> int:
    return sum(len(_lis([(c["num"], _sub_key(c["sub"])) for c in run])) for run in _runs(cs))


def _sub_key(sub: str) -> int:
    return {"상": 1, "중": 2, "하": 3}.get(sub, int(sub) if sub.isdigit() else 0)


def candidates(lines: list[str], rule: str = "heading", example: str = "", unit: str = "") -> dict:
    """화 표시 후보 줄 [{line, unit, num, sub, title, kind, head}] 과 단위별 수. unit 을 주면 그 단위만 (규칙 칩)."""
    if rule == "custom":
        pat = _custom_re(example)
        found = []
        for i, ln in enumerate(lines):
            m = pat.match(ln) if ln.strip() and len(ln) <= HEAD_MAX else None
            if m:
                found.append(_special({"line": i, "unit": "custom", "num": int(m.group("num")), "sub": "", "title": _title(m.group("title")),
                                       "kind": "main", "head": ln.strip()}))
        return {"cuts": found, "unit": "custom", "alts": [], "common_head": ""}
    raw = []
    for i, ln in enumerate(lines):
        c = _parse(ln)
        if c:
            c["line"], c["head"] = i, ln.strip()
            raw.append(c)
    # 숫자 앞 글: 비었거나 COMMON_MIN 번 넘게 같은 것만 받는다 (본문 속 '영화 3편 봤다' 같은 줄은 머리가 하나뿐이다)
    counts: dict[str, int] = {}
    for c in raw:
        counts[_key(c["pre"])] = counts.get(_key(c["pre"]), 0) + 1
    raw = [c for c in raw if not _key(c["pre"]) or counts[_key(c["pre"])] >= COMMON_MIN]
    heads = sorted(((n, k) for k, n in counts.items() if k and n >= COMMON_MIN), reverse=True)
    common = next((c["pre"].strip() for c in raw if heads and _key(c["pre"]) == heads[0][1]), "")
    # 단위 고르기: 단위마다 본편 번호 줄기 길이
    by_unit: dict[str, list[dict]] = {}
    for c in raw:
        if c["unit"]:
            by_unit.setdefault(c["unit"], []).append(c)
    chain_len = {u: _chain_len([c for c in cs if c["kind"] == "main"]) for u, cs in by_unit.items()}
    order = sorted(by_unit, key=lambda u: (-chain_len[u], UNIT_ORDER.index(u)))
    pick = unit if unit in by_unit else (order[0] if order else "")
    alts = [{"unit": u, "count": len(by_unit[u])} for u in order if u != pick]
    cuts = [c for c in raw if c["unit"] == pick or not c["unit"]]
    return {"cuts": cuts, "unit": pick, "alts": alts, "common_head": common if any(_key(c["pre"]) for c in cuts) else ""}


# ---------- 나누기 ----------

def _label(c: dict) -> str:
    if c.get("word"):
        word = c["word"].strip()
        return f"{word} {c['num']}" if c["num"] else word
    if c["kind"] == "side":
        return f"외전 {c['num']}" + (f"-{c['sub']}" if c["sub"] else "")
    return str(c["num"]) + (f"-{c['sub']}" if c["sub"] else "")


def _mark(cuts: list[dict], files: list[int]) -> None:
    """번호 줄기 · 반복 머리 · 목차 · 빠짐 · 겹침 · 거꾸로 표시. on 을 정한다."""
    for c in cuts:
        c.setdefault("flags", [])
        c.setdefault("on", True)
    # 목차: 화 표시 사이가 TOC_GAP 자보다 짧은 줄이 TOC_RUN 개 넘게 이어지고, 그 번호들이 뒤에서 다시 나온다
    # (번호가 다시 나오지 않으면 아주 짧은 화들이다)
    run: list[dict] = []
    for k, c in enumerate(cuts + [None]):
        if c is not None and run and c["gap_before"] < TOC_GAP:
            run.append(c)
            continue
        if len(run) > TOC_RUN:
            later = {(x["kind"], x["num"]) for x in cuts[k:]}
            again = sum(1 for x in run if (x["kind"], x["num"]) in later)
            if again >= len(run) * 0.8:
                for x in run:
                    if (x["kind"], x["num"]) in later or x["kind"] == "main":  # 목차 바로 뒤 프롤로그처럼 다시 나오지 않는 특수 화는 남긴다
                        x["on"], x["flags"] = False, x["flags"] + ["toc"]
        run = [c] if c is not None else []
    # 반복 머리: 같은 번호 · 같은 종류가 DUP_GAP 자 안에 또 나오면 앞 줄부터 뒷줄까지를 한 머리로 묶는다
    live = [c for c in cuts if c["on"]]
    for a, b in zip(live, live[1:]):
        if a["on"] and a["kind"] == b["kind"] and a["num"] == b["num"] and a["sub"] == b["sub"] and b["gap_before"] < DUP_GAP:
            b["on"], b["merged_into"] = False, a["line"]
            a["body"] = b["line"] + 1
            if not a["title"]:
                a["title"] = b["title"]
            a["head"] = b["head"] if len(b["head"]) > len(a["head"]) else a["head"]
    # 번호 줄기: 파일마다 · 종류(본편 · 외전)마다
    bounds = sorted(set([0] + files))
    seg_of = lambda line: bisect.bisect_right(bounds, line) - 1  # noqa: E731
    groups: dict[tuple, list[dict]] = {}
    for c in cuts:
        if c["on"] and c["kind"] in ("main", "side") and c["num"]:
            groups.setdefault((seg_of(c["line"]), c["kind"]), []).append(c)
    for (seg, _), all_cs in groups.items():
        for r, cs in enumerate(_runs(all_cs)):  # 줄기마다 따로 잰다. 한 줄기로 재면 다시 시작한 뒤 화가 모두 꺼져 앞 마지막 화에 붙었다
            chain = _lis([(c["num"], _sub_key(c["sub"])) for c in cs])
            if len(cs) >= 3:
                for i, c in enumerate(cs):
                    if i not in chain:
                        c["on"], c["flags"] = False, c["flags"] + ["mention"]
            kept = [c for c in cs if c["on"]]
            if kept and r:
                kept[0]["flags"].append("restart")
            elif seg and kept and kept[0]["num"] == 1 and any(x["num"] > 1 for g in groups.values() for x in g if seg_of(x["line"]) < seg):
                kept[0]["flags"].append("restart")
            for a, b in zip(kept, kept[1:]):
                if b["num"] == a["num"] and b["sub"] == a["sub"]:
                    a["flags"].append("dup")
                    b["flags"].append("dup")
                elif b["num"] < a["num"]:
                    b["flags"].append("back")
                elif b["num"] > a["num"] + 1:
                    b["flags"].append("gap")
                    b["gap"] = [a["num"] + 1, b["num"] - 1]


def _gaps(lines: list[str], cuts: list[dict]) -> None:
    """화 표시 앞 글 글자 수 (목차 · 반복 머리 판정용)."""
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln) + 1)
    prev = None
    for c in cuts:
        c["gap_before"] = 10 ** 9 if prev is None else starts[c["line"]] - starts[prev["line"] + 1]
        prev = c


def _rule_cuts(lines: list[str], rule: str) -> list[dict]:
    """화 표시가 없을 때의 경계: 기호 줄은 그 줄에서(본문은 다음 줄), 빈 줄 셋 넘게는 다음 글 줄에서."""
    cuts = [{"line": 0, "body": 0, "head": "", "label": "", "title": "", "kind": "main", "num": 0, "sub": "", "on": True, "flags": []}]
    if rule == "mark":
        cuts += [{"line": i, "body": i + 1, "head": "", "label": "", "title": "", "kind": "main", "num": 0, "sub": "", "on": True, "flags": []}
                 for i, ln in enumerate(lines) if MARK_RE.match(ln)]
    elif rule == "blank":
        blank = 0
        for i, ln in enumerate(lines):
            if not ln.strip():
                blank += 1
                continue
            if blank > BLANK_RUN - 1 and i:  # 빈 줄 셋 넘게 = 줄바꿈 넷 넘게 (revlab 의 '\n(\s*\n){3,}')
                cuts.append({"line": i, "body": i, "head": "", "label": "", "title": "", "kind": "main", "num": 0, "sub": "", "on": True, "flags": []})
            blank = 0
    return cuts


def detect(text: str, rule: str = "", example: str = "", unit: str = "", files: Optional[list[int]] = None) -> dict:
    """원문 → 경계 후보 (저장하지 않는다). rule 을 비우면 순서대로 고른다: 화 표시 줄 → 기호 줄 → 빈 줄 셋 넘게 → 한 화.
    값: {rule, unit, alts, common_head, lines, cuts: [{line, body, head, label, num, sub, title, kind, on, flags, gap?}]}.
    cuts 에는 끈 후보(본문 속 언급 · 목차 · 반복 머리)도 들어 있다. 첫 켠 경계 앞 글은 머리 글이다."""
    lines = lines_of(text)
    files = files or []
    rules = [rule] if rule else ["heading", "mark", "blank", "one"]
    for r in rules:
        if r in ("heading", "custom"):
            got = candidates(lines, r, example, unit)
            cuts = got["cuts"]
            if not cuts and not rule:
                continue
            for c in cuts:
                c["body"] = c["line"] + 1
                c["label"] = _label(c)
            _gaps(lines, cuts)
            _mark(cuts, files)
            for c in cuts:
                for k in ("gap_before", "pre", "word", "unit"):
                    c.pop(k, None)
            return {"rule": r, "unit": got["unit"], "alts": got["alts"], "common_head": got["common_head"], "lines": len(lines), "cuts": cuts}
        if r == "mark" and (rule or any(MARK_RE.match(ln) for ln in lines)):
            return {"rule": "mark", "unit": "", "alts": [], "common_head": "", "lines": len(lines), "cuts": _rule_cuts(lines, "mark")}
        if r == "blank" and (rule or len(_rule_cuts(lines, "blank")) > 1):
            return {"rule": "blank", "unit": "", "alts": [], "common_head": "", "lines": len(lines), "cuts": _rule_cuts(lines, "blank")}
        if r == "one":
            break
    return {"rule": "one", "unit": "", "alts": [], "common_head": "", "lines": len(lines), "cuts": _rule_cuts(lines, "one")}


def _tail(body: list[str]) -> int:
    """화 끝의 작가의 말이 시작하는 줄 (body 안 자리). 없으면 len(body)."""
    total = sum(len(x) + 1 for x in body)
    at = 0
    for i, ln in enumerate(body):
        if at >= total * TAIL_FROM and TAIL_RE.match(ln):
            return i
        at += len(ln) + 1
    return len(body)


def assemble(lines: list[str], cuts: list, strip_tails: bool = True) -> list[dict]:
    """켠 경계(줄 번호 차례)로 화를 잘라 낸다: [{cut, text, tail_cut}]. cut 은 cuts 의 자리. 빈 화도 남긴다(부른 쪽이 거른다)."""
    on = [(i, c) for i, c in enumerate(cuts) if _get(c, "on", True)]
    on.sort(key=lambda x: _get(x[1], "line"))
    out = []
    for k, (i, c) in enumerate(on):
        end = _get(on[k + 1][1], "line") if k + 1 < len(on) else len(lines)
        body = lines[max(_get(c, "body"), _get(c, "line")):end]
        cut = _tail(body) if strip_tails else len(body)
        text = "\n".join(body[:cut]).strip()
        out.append({"cut": i, "text": text, "tail_cut": len("\n".join(body[cut:]).strip())})
    return out


def _get(c, key: str, default=None):
    return c.get(key, default) if isinstance(c, dict) else getattr(c, key, default)


def preview(text: str, rule: str = "", example: str = "", unit: str = "", strip_tails: bool = True,
            files: Optional[list[int]] = None) -> dict:
    """화면 미리보기: detect 에 화별 글자 수 · 짧음 · 김 · 머리 글 · 수를 더한다. 원문은 돌려주지 않는다."""
    if len(text) > MAX_CHARS:
        raise ValueError(f"글이 너무 길어요 ({len(text):,}자). {MAX_CHARS:,}자까지 넣을 수 있어요")
    d = detect(text, rule, example, unit, files)
    lines = lines_of(text)
    if len([c for c in d["cuts"] if c["on"]]) > MAX_CUTS:
        raise ValueError(f"화가 너무 많아요. {MAX_CUTS:,}화까지 넣을 수 있어요")
    eps = assemble(lines, d["cuts"], strip_tails)
    for e in eps:
        c = d["cuts"][e["cut"]]
        c["chars"], c["tail_cut"] = len(e["text"]), e["tail_cut"]
    lens = [len(e["text"]) for e in eps if d["cuts"][e["cut"]]["kind"] != "skip"]
    avg = sum(lens) / len(lens) if lens else 0
    for c in d["cuts"]:
        if not c["on"]:
            continue
        if c.get("chars", 0) < SHORT_CHARS and c["kind"] != "skip":
            c["flags"].append("short")
        elif len(lens) > 3 and c.get("chars", 0) > avg * LONG_TIMES:
            c["flags"].append("long")
    first = min((c["line"] for c in d["cuts"] if c["on"]), default=0)
    d["preface_end"] = first
    d["preface_chars"] = len("\n".join(lines[:first]).strip())
    kinds = {k: 0 for k in KINDS}
    for e in eps:
        kinds[d["cuts"][e["cut"]]["kind"]] += 1
    d["counts"] = {**kinds, "warn": sum(1 for c in d["cuts"] if c["on"] and WARN & set(c["flags"])), "off": sum(1 for c in d["cuts"] if not c["on"])}
    d["chars"] = len(text)
    return d


def split(text: str) -> dict:
    """역설계 실험용 나누기 (revlab.split): {how, first, preface, episodes: [{head, text}]}. 켠 경계만 쓰고 빈 화는 뺀다.
    머리 글(첫 경계 앞)은 preface 로 돌려준다. 번호는 첫 본편 경계의 번호(없으면 1)."""
    d = detect(text)
    lines = lines_of(text)
    on = [c for c in d["cuts"] if c["on"]]
    eps = [{"head": d["cuts"][e["cut"]]["head"], "text": e["text"]} for e in assemble(lines, d["cuts"], strip_tails=False)]
    first = next((c["num"] for c in on if c["kind"] == "main" and c["num"]), 0) or 1 if d["rule"] in ("heading", "custom") else 1
    preface = "\n".join(lines[:on[0]["line"]]).strip() if on and d["rule"] in ("heading", "custom") else ""
    return {"how": d["rule"], "first": first, "preface": preface, "episodes": [e for e in eps if e["text"]]}


# ---------- 저장 ----------

def root() -> Path:
    return Path(os.environ.get("CANON_REFS") or store.ROOT / ".refs")


def _dir(rid: str) -> Path:
    if not ID_RE.match(rid or ""):
        raise KeyError(f"레퍼런스 원고에 없는 항목이에요: {rid}")
    return root() / rid


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def exists(rid: str) -> bool:
    return bool(ID_RE.match(rid or "")) and (root() / rid / "ref.json").exists()


def load(rid: str) -> RefBook:
    f = _dir(rid) / "ref.json"
    if not f.exists():
        raise KeyError(f"레퍼런스 원고에 없는 항목이에요: {rid}")
    return RefBook.model_validate_json(f.read_text(encoding="utf-8"))


def source(rid: str) -> list[str]:
    return (_dir(rid) / "source.txt").read_text(encoding="utf-8").split("\n")


def _write(b: RefBook, text: Optional[str] = None) -> RefBook:
    d = _dir(b.id)
    d.mkdir(parents=True, exist_ok=True)
    if text is not None:
        (d / "source.txt").write_text(text, encoding="utf-8")
    b.updated_at = _now()
    (d / "ref.json").write_text(b.model_dump_json(indent=2), encoding="utf-8")
    return b


def _check_cuts(cuts: list[RefCut], n_lines: int) -> list[RefCut]:
    cuts = sorted(cuts, key=lambda c: c.line)
    if len(cuts) > MAX_CUTS:
        raise ValueError(f"화가 너무 많아요. {MAX_CUTS:,}화까지 넣을 수 있어요")
    seen = set()
    for c in cuts:
        if not 0 <= c.line < max(n_lines, 1) or c.line in seen:
            raise ValueError(f"경계 줄 번호가 맞지 않아요: {c.line + 1}번째 줄")
        if c.kind not in KINDS:
            raise ValueError(f"화 종류가 맞지 않아요: {c.kind}")
        c.body = min(max(c.body, c.line), n_lines)
        seen.add(c.line)
    return cuts


def _measure(lines: list[str], b: RefBook) -> None:
    """켠 경계로 화를 잘라 화별 지표를 잰다 (AI 없음)."""
    b.eps = []
    for k, e in enumerate(assemble(lines, b.cuts, b.strip_tails)):
        m = metrics.measure(e["text"])
        b.eps.append(RefEp(order=k + 1, chars=len(e["text"]), tail_cut=e["tail_cut"], sentences=m.sentences,
                           sentence_len=round(m.sentence_len_mean, 1), paragraph_len=round(m.paragraph_len_mean, 1),
                           dialogue=round(m.dialogue_ratio, 3)))


def create(name: str, text: str, cuts: list[RefCut], source_note: str = "", notes: str = "", rights: bool = False,
           encoding: str = "utf-8", rule: str = "heading", example: str = "", unit: str = "", common_head: str = "",
           strip_tails: bool = True, files: Optional[list[RefFile]] = None) -> RefBook:
    """새 원고. 원문은 정규화해 source.txt 로, 경계와 화별 지표는 ref.json 으로."""
    name = name.strip()
    if not name:
        raise ValueError("원고 이름을 입력하세요")
    if not rights:
        raise ValueError("쓸 권리가 있는 원고인지 확인해 주세요")
    text = _norm(text)
    if not text.strip():
        raise ValueError("글이 비었어요. 원고 txt를 넣으세요")
    if len(text) > MAX_CHARS:
        raise ValueError(f"글이 너무 길어요 ({len(text):,}자). {MAX_CHARS:,}자까지 넣을 수 있어요")
    lines = text.split("\n")
    if not cuts:
        cuts = [RefCut(line=0, body=0)]
    b = RefBook(id=uuid.uuid4().hex[:12], name=name, source=source_note, notes=notes, rights=True, encoding=encoding,
                rule=rule if rule in RULES else "heading", rule_example=example, unit=unit, common_head=common_head,
                strip_tails=strip_tails, cuts=_check_cuts(cuts, len(lines)), files=files or [], chars=len(text), lines=len(lines),
                created_at=_now())
    _measure(lines, b)
    return _write(b, text)


def update(rid: str, name: Optional[str] = None, source_note: Optional[str] = None, notes: Optional[str] = None,
           cuts: Optional[list[RefCut]] = None, strip_tails: Optional[bool] = None, rule: Optional[str] = None,
           example: Optional[str] = None, unit: Optional[str] = None) -> RefBook:
    """이름 · 출처 · 메모 · 경계 고치기. 경계나 작가의 말 떼기가 바뀌면 지표를 다시 잰다. 원문은 바꾸지 않는다."""
    b = load(rid)
    if name is not None:
        if not name.strip():
            raise ValueError("원고 이름을 입력하세요")
        b.name = name.strip()
    if source_note is not None:
        b.source = source_note
    if notes is not None:
        b.notes = notes
    if rule is not None and rule in RULES:
        b.rule = rule
    if example is not None:
        b.rule_example = example
    if unit is not None:
        b.unit = unit
    if cuts is not None or (strip_tails is not None and strip_tails != b.strip_tails):
        lines = source(rid)
        if cuts is not None:
            b.cuts = _check_cuts(cuts or [RefCut(line=0, body=0)], len(lines))
        if strip_tails is not None:
            b.strip_tails = strip_tails
        _measure(lines, b)
    return _write(b)


def delete(rid: str) -> None:
    d = _dir(rid)
    if not (d / "ref.json").exists():
        raise KeyError(f"레퍼런스 원고에 없는 항목이에요: {rid}")
    shutil.rmtree(d)


def entries() -> list[RefBook]:
    d = root()
    if not d.exists():
        return []
    out = []
    for f in d.glob("*/ref.json"):
        try:
            out.append(RefBook.model_validate_json(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return sorted(out, key=lambda b: b.updated_at, reverse=True)


def summary(b: RefBook) -> dict:
    kinds = {k: 0 for k in KINDS}
    for c in b.cuts:
        kinds[c.kind] += 1
    return {"id": b.id, "name": b.name, "source": b.source, "notes": b.notes, "chars": b.chars, "episodes": len(b.eps),
            "kinds": kinds, "made": len(b.made), "created_at": b.created_at, "updated_at": b.updated_at}


def label(c: RefCut) -> str:
    """화면 이름: '12화' · '외전 3' · '프롤로그'. 번호가 없으면 빈 글."""
    if not c.label:
        return ""
    return f"{c.label}화" if re.fullmatch(r"\d+(?:-\S+)?", c.label) else c.label


def episodes(b: RefBook) -> list[dict]:
    """화 목록 (원문 없음): 차례 · 이름 · 제목 · 종류 · 지표."""
    on = sorted(b.cuts, key=lambda c: c.line)
    out = []
    for c, e in zip(on, b.eps):
        out.append({"order": e.order, "label": label(c), "title": c.title, "kind": c.kind, "line": c.line, "head": c.head,
                    **e.model_dump(exclude={"order"})})
    return out


def episode_text(rid: str, order: int) -> str:
    b = load(rid)
    eps = assemble(source(rid), b.cuts, b.strip_tails)
    if not 1 <= order <= len(eps):
        raise KeyError(f"{order}번째 화가 없어요")
    return eps[order - 1]["text"]


def text_range(rid: str, start: int, end: int) -> dict:
    lines = source(rid)
    start, end = max(0, start), min(len(lines), max(start, end))
    return {"start": start, "end": end, "total": len(lines), "lines": lines[start:end]}


def pick(b: RefBook, orders: list[int]) -> list[dict]:
    """고른 차례의 화 [{order, label, head, text}] (제외 화는 뺀다)."""
    lines = source(b.id)
    want = set(orders)
    on = sorted(b.cuts, key=lambda c: c.line)
    out = []
    for k, e in enumerate(assemble(lines, b.cuts, b.strip_tails)):
        c = on[k]
        if k + 1 in want and c.kind != "skip" and e["text"]:
            out.append({"order": k + 1, "label": label(c), "head": c.head, "text": e["text"], "num": c.label})
    if not out:
        raise ValueError("고른 화가 없어요")
    return out


def span(chosen: list[dict]) -> str:
    """'1~10화' · '3화' · '외전 1' 처럼 고른 화 범위 이름."""
    names = [c["label"] or f"{c['order']}번째" for c in chosen]
    return names[0] if len(names) == 1 else f"{names[0]}~{names[-1]}" if names[0].endswith("화") and names[-1].endswith("화") else f"{names[0]} 외 {len(names) - 1}화"


def sample(rid: str, orders: list[int]) -> dict:
    """문체 만들기에 넣을 원문: 고른 화를 이어 SAMPLE_MAX 자까지. 출처 이름도 준다."""
    b = load(rid)
    chosen = pick(b, orders)
    text = "\n\n".join(c["text"] for c in chosen)
    cut = len(text) > SAMPLE_MAX
    return {"text": text[:SAMPLE_MAX].strip(), "cut": cut, "chars": len(text), "source": f"{b.name} {span(chosen)}".strip(),
            "name": b.name}


def made(rid: str, kind: str, ref_id: str, eps: str) -> None:
    from .schema import RefMade
    b = load(rid)
    b.made.append(RefMade(kind=kind, id=ref_id, at=_now(), eps=eps))
    _write(b)


def _sent(b: RefBook, chosen: list[dict]) -> list[dict]:
    """역설계 실험에 넘길 화: 화 표시 줄 · 글 · 출처(RevSource)."""
    from . import revlab
    from .schema import RevSource
    return [{"head": c["head"], "text": c["text"],
             "source": RevSource(ref=b.id, order=c["order"], label=c["num"], basis=revlab._basis(c["text"].strip()))} for c in chosen]


def to_revlab(rid: str, orders: list[int]) -> int:
    """고른 화로 역설계 실험을 만든다. 나눈 화와 화 표시 줄을 그대로 넘기고, 첫 화 번호는 원고 번호를 쓴다."""
    from . import revlab
    b = load(rid)
    chosen = pick(b, orders)
    first = int(chosen[0]["num"]) if chosen[0]["num"].isdigit() else None
    lab = revlab.create_episodes(f"{b.name} {span(chosen)}", _sent(b, chosen), first)
    made(rid, "revlab", str(lab.id), span(chosen))
    return lab.id


def to_lab(rid: str, orders: list[int], lab_id: int) -> tuple:
    """고른 화를 있는 역설계 실험의 마지막 화 뒤에 잇는다 (revlab.append_episodes). 이미 그 실험에 있는 화는 뺀다.
    (실험, {"added": 이은 화 번호, "skipped": 뺀 수})."""
    from . import revlab
    b = load(rid)
    chosen = pick(b, orders)
    out: dict = {}

    def put(lab) -> None:
        out["added"], out["skipped"] = revlab.append_episodes(lab, _sent(b, chosen))
    lab = revlab.with_lock(lab_id, put)
    made(rid, "revlab", str(lab_id), span(chosen))
    return lab, out


def texts(rid: str) -> dict[int, str] | None:
    """원고의 화 차례 → 지금 글 (역설계 실험 화면이 원고가 바뀌었는지 본다). 원고가 없으면 None."""
    try:
        b = load(rid)
    except KeyError:
        return None
    on = sorted(b.cuts, key=lambda c: c.line)
    return {k + 1: e["text"].strip() for k, e in enumerate(assemble(source(rid), b.cuts, b.strip_tails)) if on[k].kind != "skip"}


def compare(rid: str, p) -> dict:
    """원고 지표와 작품의 본문 있는 화 지표 (읽기만, 작품에 쓰지 않는다)."""
    b = load(rid)
    mine = []
    for ep in p.episodes:
        if ep.text.strip():
            m = metrics.measure(ep.text)
            mine.append({"chars": len(ep.text.strip()), "sentence_len": m.sentence_len_mean, "dialogue": m.dialogue_ratio,
                         "paragraph_len": m.paragraph_len_mean})
    theirs = [e.model_dump() for e, c in zip(b.eps, sorted(b.cuts, key=lambda c: c.line)) if c.kind != "skip" and e.chars]
    return {"ref": _stats(theirs), "project": _stats(mine), "project_eps": len(mine)}


def _stats(rows: list[dict]) -> dict:
    out = {}
    for k in ("chars", "sentence_len", "dialogue", "paragraph_len"):
        xs = sorted(r[k] for r in rows)
        out[k] = {"mean": round(sum(xs) / len(xs), 3), "min": xs[0], "max": xs[-1], "median": xs[len(xs) // 2]} if xs else None
    return out


def labels() -> dict:
    from . import revlab
    return {"rules": [{"key": k, "label": v} for k, v in RULES.items()], "kinds": [{"key": k, "label": v} for k, v in KINDS.items()],
            "flags": FLAGS, "warn": sorted(WARN), "max_chars": MAX_CHARS, "max_cuts": MAX_CUTS, "sample_max": SAMPLE_MAX,
            "units": UNIT_ORDER, "revlab_max_chars": revlab.MAX_CHARS}
