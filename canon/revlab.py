"""역설계 실험: 작가가 넣은 소설(사람이 쓴 글)을 거꾸로 화별 플롯 · 스토리보드 · 큐 시트 · 이야기 줄기로 푼다.

사람 글의 구조를 Canon 의 표현으로 적어 보고, 그 표현으로 같은 화를 다시 써서(되돌려 쓰기) Canon 의 큐 시트가 사람 글의 구조를
얼마나 담는지 잰다. 작품(project.json)에는 넣지 않고 실험 파일 <CANON_HOME>/.revlab/<번호>.json 에 둔다 (문체 라이브러리처럼 작품 밖).

- 나누기(split): 'n화' 제목 줄 → '===' 줄 → 빈 줄 세 개 넘게 → 한 화. 화면의 미리보기(static/revlab.js revSplit)와 같은 규칙.
- 역설계(pipeline.reverse_episode, plan 단계): 화마다 한 번. 큐 경계는 원문 글자 그대로의 시작 인용(RevCue.start)으로 받아
  Canon 이 원문에서 찾고(locate), 큐 글자 수는 그 경계로 잰다. 핵심 대사는 원문에 글자 그대로(공백 · 따옴표 · 문장부호 빼고) 있는 것만
  남긴다(keep_lines). 화가 둘 넘으면 이야기 줄기를 한 번 더 묻는다(pipeline.reverse_lines).
- 되돌려 쓰기(run_write, write 단계): 역설계한 재료로 만든 작품 사본(world)에서 큐 시트 실험의 '큐 시트를 주고 한 번에' 조건
  (pipeline.write_scored)으로 같은 화를 쓴다. 원문과 블라인드 비교, cue.score 지표 비교.
AI 호출 전에 비용 추정(estimate)을 보여 주고 작가가 눌러야 돈다. 인물 id 는 인물 이름이다.
"""
from __future__ import annotations

import random
import re
from datetime import date
from pathlib import Path

from . import cancel, cue, pipeline, prompts, store, usage
from .context import CHARS_PER_TOKEN
from .schema import (Act, AddressForm, BoardHandover, BoardScene, BoardTime, Character, CueLine, CueSheet, CueSheetDraft, CueTake, Episode, EpisodePlot, Meta, Project,
                     Relationship, RevBound, RevCastSaved, RevEpisode, RevEpisodeDraft, RevLab, RevLineSet, RevPerson, RevTake, Storyboard,
                     StoryboardDraft, StyleProfile, WorldSetting,
                     Storyline)

# 화를 나눈 규칙 (화면 이름)
SPLITS: dict[str, str] = {"heading": "'n화' 제목 줄", "mark": "'===' 줄", "blank": "빈 줄 세 개 넘게", "one": "한 화"}
HEAD_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:제\s*)?(\d{1,4})\s*화(?:\s*[.:：\-—)]\s*|\s+|$)(.*)$")
HEAD_MAX = 60  # 제목 줄로 보는 가장 긴 줄
MARK_RE = re.compile(r"^\s*={3,}\s*$")
BLANK_RE = re.compile(r"\n(?:[ \t]*\n){3,}")
PREFACE_MIN = 200  # 첫 제목 줄 앞의 글이 이만큼 넘으면 화 하나로 본다 (짧으면 작품 제목 · 작가 줄)
MAX_EPISODES = 30
MAX_CHARS = 300_000
MIN_CHARS = 200  # 한 화가 이보다 짧으면 역설계하지 않는다
FACTS_MAX = 8
PREV_TAIL = 1500  # 역설계 요청에 넣는 직전 화 끝 글자 수
QUOTE_MIN = 2  # 시작 인용이 이보다 짧으면(공백 빼고) 찾지 않는다. 짧은 인용도 앞 큐 뒤에서만 찾아 흔한 말에 덜 걸린다
PARSE_OUT_TOKENS = 3000  # 화 하나 역설계 응답 토큰 추정 (큐 8개 · 장면 4개 안팎의 JSON)
LINES_OUT_TOKENS = 800
LINES_IN_CHARS = 400  # 이야기 줄기 요청에 화마다 들어가는 글자 수 추정
JOBS = ".revlab"  # 작업 목록의 project 자리 (작품 폴더는 점으로 시작하지 않아 겹치지 않는다). 화면은 '역설계 실험'으로 보인다
SIDES = {"original": "원문", "rewrite": "되돌려 쓴 글"}
TAKES = {"plain": "되돌려 쓴 글", "style": "되돌려 쓴 글 (문체 넣음)"}  # RevEpisode.take · take_style
STYLE_CHARS = 30_000  # 문체 역설계에 넣는 원문 앞부분 글자 수
STYLE_OUT_TOKENS = 2500
FIRST_RE = re.compile(r"(\d{1,4})\s*화")  # 실험 이름에서 첫 화 번호를 짐작한다 (글에 제목 줄이 없을 때)


# ---------- 나누기 ----------

def _norm(text: str) -> str:
    return text.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")


def split(text: str) -> dict:
    """글을 화로 나눈다: {how, first, preface, episodes: [{head, text}]}. first 는 첫 화 번호(제목 줄이 있으면 그 번호, 없으면 1).
    빈 화는 뺀다. 제목 줄 앞의 짧은 글은 preface 로 남기고 역설계하지 않는다."""
    t = _norm(text)
    lines = t.split("\n")
    heads = [i for i, ln in enumerate(lines) if len(ln) <= HEAD_MAX and HEAD_RE.match(ln)]
    preface, first = "", 1
    if heads:
        how = "heading"
        first = int(HEAD_RE.match(lines[heads[0]]).group(1)) or 1
        before = "\n".join(lines[:heads[0]]).strip()
        eps = [{"head": lines[h].strip(), "text": "\n".join(lines[h + 1:(heads[k + 1] if k + 1 < len(heads) else len(lines))]).strip()}
               for k, h in enumerate(heads)]
        if len(before) >= PREFACE_MIN:
            eps.insert(0, {"head": "", "text": before})
            first = max(first - 1, 1)
        else:
            preface = before
    elif any(MARK_RE.match(ln) for ln in lines):
        how, eps, cur = "mark", [], []
        for ln in lines + ["==="]:
            if MARK_RE.match(ln):
                eps.append({"head": "", "text": "\n".join(cur).strip()})
                cur = []
            else:
                cur.append(ln)
    elif BLANK_RE.search(t):
        how = "blank"
        eps = [{"head": "", "text": x.strip()} for x in BLANK_RE.split(t)]
    else:
        how = "one"
        eps = [{"head": "", "text": t.strip()}]
    return {"how": how, "first": first, "preface": preface, "episodes": [e for e in eps if e["text"]]}


def check_text(text: str) -> dict:
    """나눈 결과를 받기 전에 크기를 본다. 너무 크거나 비었으면 해요체 오류."""
    if len(text) > MAX_CHARS:
        raise ValueError(f"글이 너무 길어요 ({len(text):,}자). {MAX_CHARS:,}자까지 넣을 수 있어요")
    s = split(text)
    if not s["episodes"]:
        raise ValueError("글이 비었어요. 소설 본문을 붙여 넣으세요")
    if len(s["episodes"]) > MAX_EPISODES:
        raise ValueError(f"{len(s['episodes'])}화로 나뉘었어요. 한 실험에 {MAX_EPISODES}화까지 넣을 수 있어요")
    return s


# ---------- 저장 ----------

def _dir() -> Path:
    return store.ROOT / ".revlab"


def _path(lab_id: int) -> Path:
    return _dir() / f"{lab_id}.json"


def ids() -> list[int]:
    d = _dir()
    return sorted(int(x.stem) for x in d.glob("*.json") if x.stem.isdigit()) if d.exists() else []


def load(lab_id: int) -> RevLab:
    path = _path(lab_id)
    if not path.exists():
        raise FileNotFoundError(f"역설계 실험이 없어요: {lab_id}")
    return RevLab.model_validate_json(path.read_text(encoding="utf-8"))


def save(lab: RevLab) -> Path:
    import os
    import threading

    path = _path(lab.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(lab.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def remove(lab_id: int) -> None:
    _path(lab_id).unlink(missing_ok=True)


def lock_key(lab_id: int) -> str:
    """jobs.project_lock 열쇠. 작품 이름과 겹치지 않는다 (작품 폴더는 점으로 시작하지 않는다)."""
    return f".revlab/{lab_id}"


def with_lock(lab_id: int, fn) -> RevLab:
    """실험 파일을 읽어 fn 으로 고치고 저장한다. 작업과 화면 저장이 섞이지 않게 잠근다."""
    from . import jobs

    with jobs.project_lock(lock_key(lab_id)):
        lab = load(lab_id)
        fn(lab)
        save(lab)
    return lab


def guess_first(title: str, text: str) -> int:
    """첫 화 번호 짐작: 글에 'n화' 제목 줄이 있으면 그 번호, 없으면 실험 이름의 'n화', 그것도 없으면 1.
    화면의 revGuessFirst 와 같은 규칙. 1~3화로 잡히면 되돌려 쓰기에 초반 규칙이 붙는다 (prompts.opening_rules)."""
    s = split(text)
    if s["how"] == "heading":
        return s["first"]
    m = FIRST_RE.search(title or "")
    return int(m.group(1)) or 1 if m else 1


def _check_first(first: int) -> int:
    if not 1 <= first <= 9999:
        raise ValueError("첫 화 번호는 1~9999 사이로 적어요")
    return first


def create(title: str, text: str, first: int | None = None) -> RevLab:
    """새 실험. 글을 나눠 화마다 원문만 넣는다 (AI 를 부르지 않는다). first 를 비우면 guess_first 로 짐작한다."""
    from . import jobs

    s = check_text(text)
    first = _check_first(first) if first else guess_first(title, text)
    with jobs.project_lock(".revlab"):
        lab = RevLab(id=(max(ids(), default=0) + 1), title=title.strip(), created=pipeline._now(), split=s["how"], preface=s["preface"],
                     episodes=[RevEpisode(number=first + i, head=e["head"], text=e["text"]) for i, e in enumerate(s["episodes"])])
        save(lab)
    return lab


def renumber(lab: RevLab, first: int) -> None:
    """첫 화 번호를 바꾼다. 화 번호를 품은 칸(화 · 플롯 번호, 줄기의 갈라진 화 · 합류한 화)을 함께 옮긴다."""
    if not lab.episodes:
        return
    delta = _check_first(first) - lab.episodes[0].number
    if not delta:
        return
    for e in lab.episodes:
        e.number += delta
        if e.plot:
            e.plot.number += delta
    for x in lab.lines:
        x.branch_ep = x.branch_ep + delta if x.branch_ep else 0
        x.join_ep = x.join_ep + delta if x.join_ep else 0


def replace_text(lab: RevLab, title: str, text: str | None, first: int | None = None) -> None:
    """제목을 바꾸고, 글을 주면 다시 나눈다(역설계 결과를 모두 지운다). first 를 주면 첫 화 번호를 바꾼다."""
    lab.title = title.strip()
    if text is not None:
        s = check_text(text)
        start = _check_first(first) if first else guess_first(title, text)
        lab.split, lab.preface = s["how"], s["preface"]
        lab.episodes = [RevEpisode(number=start + i, head=e["head"], text=e["text"]) for i, e in enumerate(s["episodes"])]
        lab.cast, lab.main, lab.lines, lab.lines_at = [], "", [], ""
        lab.style, lab.style_model, lab.style_at = None, "", ""
    elif first:
        renumber(lab, first)


def append_text(lab: RevLab, text: str) -> list[int]:
    """글을 나눠 마지막 화 뒤에 잇는다. 앞 화의 역설계 결과 · 인물 · 줄기 · 문체는 그대로 둔다. 새 화 번호는 제목 줄 번호와 상관없이
    마지막 화 + 1 부터 센다. 첫 제목 줄 앞의 짧은 글은 버린다 (실험의 앞머리는 바꾸지 않는다). 이야기 줄기는 새 화까지 역설계하면
    다시 묻는다 (wants_lines). 이은 화 번호를 낸다."""
    s = check_text(text)
    have = sum(len(e.text) for e in lab.episodes)
    if have + len(text) > MAX_CHARS:
        raise ValueError(f"이으면 {have + len(text):,}자예요. 한 실험에 {MAX_CHARS:,}자까지 넣을 수 있어요")
    if len(lab.episodes) + len(s["episodes"]) > MAX_EPISODES:
        raise ValueError(f"이으면 {len(lab.episodes) + len(s['episodes'])}화예요. 한 실험에 {MAX_EPISODES}화까지 넣을 수 있어요")
    start = lab.episodes[-1].number + 1 if lab.episodes else s["first"]
    added = [RevEpisode(number=start + i, head=e["head"], text=e["text"]) for i, e in enumerate(s["episodes"])]
    lab.episodes += added
    return [e.number for e in added]


def edit_episode(lab: RevLab, number: int, head: str, text: str) -> bool:
    """화 하나의 제목 줄과 글을 고친다. 글이 바뀌면 그 화의 역설계 결과 · 경계 · 되돌려 쓴 판을 지운다(원문에 맞춰 잰 값이라서).
    인물 · 줄기 · 문체와 다른 화는 그대로 둔다. 결과를 지웠으면 참."""
    e = episode(lab, number)
    text = _norm(text).strip()
    if not text:
        raise ValueError("글이 비었어요. 화를 빼려면 지우기를 쓰세요")
    total = sum(len(x.text) for x in lab.episodes) - len(e.text) + len(text)
    if total > MAX_CHARS:
        raise ValueError(f"고치면 {total:,}자예요. 한 실험에 {MAX_CHARS:,}자까지 넣을 수 있어요")
    e.head = head.strip()[:HEAD_MAX]
    if text == e.text:
        return False
    cleared = e.plot is not None or e.take is not None or e.take_style is not None
    lab.episodes[lab.episodes.index(e)] = RevEpisode(number=e.number, head=e.head, text=text)
    return cleared


def drop_episode(lab: RevLab, number: int) -> None:
    """화 하나를 뺀다. 뒤 화 번호를 하나씩 당겨 번호가 비지 않게 한다(화 · 플롯 번호, 줄기의 갈라진 화 · 합류한 화).
    인물 · 문체는 그대로 둔다. 마지막 남은 화는 빼지 않는다 (실험을 지운다)."""
    e = episode(lab, number)
    if len(lab.episodes) == 1:
        raise ValueError("남은 화가 하나라 뺄 수 없어요. 실험을 지우세요")
    lab.episodes.remove(e)
    for x in lab.episodes:
        if x.number > number:
            x.number -= 1
            if x.plot:
                x.plot.number -= 1
    last = lab.episodes[-1].number

    def move(n: int) -> int:
        return 0 if not n else min(n - 1 if n > number else n, last)
    for s in lab.lines:
        s.branch_ep, s.join_ep = move(s.branch_ep), move(s.join_ep)


def episode(lab: RevLab, number: int) -> RevEpisode:
    for e in lab.episodes:
        if e.number == number:
            return e
    raise KeyError(f"{number}화가 없어요")


# ---------- 경계 재기 · 핵심 대사 확인 (LLM 없음) ----------

_QUOTES = "\"'“”‘’「」『』"


def _pattern(quote: str) -> re.Pattern | None:
    """시작 인용 → 원문 찾기 패턴: 공백은 아무 공백이나, 따옴표는 아무 따옴표나. 말줄임으로 끝난 인용은 그 앞까지."""
    q = re.sub(r"(?:…|\.{3})+$", "", quote.strip()).strip()
    if len(re.sub(r"\s", "", q)) < QUOTE_MIN:
        return None
    out = []
    for ch in q:
        if ch.isspace():
            if out and out[-1] != r"\s+":
                out.append(r"\s+")
        elif ch in _QUOTES:
            out.append(f"[{re.escape(_QUOTES)}]")
        else:
            out.append(re.escape(ch))
    return re.compile("".join(out))


def locate(text: str, starts: list[str]) -> list[RevBound]:
    """큐마다 원문 자리 [start, end). 첫 큐는 늘 원문 처음에서 시작한다. 다음 큐 시작 인용은 앞 큐 시작 뒤에서 차례로 찾는다.
    못 찾은 큐는 found 거짓, 길이 0 (앞 큐가 다음으로 찾은 큐 앞까지 늘어난다)."""
    if not starts:
        return []
    pos: list[int | None] = [0]
    last = 0
    for q in starts[1:]:
        pat = _pattern(q)
        m = pat.search(text, last + 1) if pat else None
        if m:
            last = m.start()
            pos.append(last)
        else:
            pos.append(None)
    out = []
    for i, s in enumerate(pos):
        nxt = next((x for x in pos[i + 1:] if x is not None), len(text))
        if s is None:
            out.append(RevBound(start=nxt, end=nxt, found=False, quote=starts[i]))
        else:
            out.append(RevBound(start=s, end=nxt, found=True, quote=starts[i]))
    return out


def measured(text: str, b: RevBound) -> int:
    """큐 구간의 글자 수 (앞뒤 공백 빼고, 공백 포함). metrics.measure 의 chars 와 같은 셈."""
    return len(text[b.start:b.end].strip())


def keep_lines(text: str, lines: list[CueLine]) -> tuple[list[CueLine], list[str]]:
    """원문에 글자 그대로(공백 · 따옴표 · 문장부호 빼고, cue.line_hits 와 같은 셈) 있는 핵심 대사만 남긴다. (남긴 것, 뺀 대사)."""
    flat = cue._flat(text)
    keep, drop = [], []
    for x in lines:
        t = x.text.strip().strip(_QUOTES).strip()
        if not t:
            continue
        f = cue._flat(t)
        if len(f) >= 2 and f in flat:
            keep.append(CueLine(speaker=x.speaker.strip(), text=t))
        else:
            drop.append(t)
    return keep[:cue.MAX_LINES], drop


def parts(e: RevEpisode) -> list[str]:
    """큐마다 원문 조각. 경계가 큐 수와 맞지 않으면 빈 목록."""
    if not e.sheet or len(e.bounds) != len(e.sheet.cues):
        return []
    return [e.text[b.start:b.end].strip() for b in e.bounds]


# ---------- 역설계 결과 넣기 ----------

def _act(lab: RevLab, number: int) -> str:
    """화 자리로 고른 구간 이름 (작품 사본의 기승전결 하나에 맞춘다). 실험에서는 쓰지 않는 칸이라 고르는 규칙만 있으면 된다."""
    k = [e.number for e in lab.episodes].index(number)
    return "기승전결"[min(3, k * 4 // max(len(lab.episodes), 1))]


def merge_cast(lab: RevLab, people: list[RevPerson]) -> None:
    """화에서 나온 인물을 실험 인물 목록에 더한다. 이름이 같으면 빈 칸만 채운다."""
    by = {c.name: c for c in lab.cast}
    for x in people:
        name = x.name.strip()
        if not name:
            continue
        if name in by:
            old = by[name]
            old.role = old.role or x.role.strip()
            old.personality = old.personality or x.personality.strip()
            old.speech = old.speech or x.speech.strip()
        else:
            by[name] = RevCastSaved(name=name, role=x.role.strip(), personality=x.personality.strip(), speech=x.speech.strip())
            lab.cast.append(by[name])


def apply_episode(lab: RevLab, number: int, d: RevEpisodeDraft, model: str = "") -> RevEpisode:
    """역설계 응답을 정리해 화에 넣는다: 큐 경계를 원문에서 찾고 글자 수를 재고, 원문에 없는 핵심 대사를 뺀다.
    되돌려 쓴 본문과 블라인드 비교는 지운다 (재료가 바뀌었다)."""
    e = episode(lab, number)
    names = [x.name.strip() for x in d.cast if x.name.strip()]
    board = pipeline.clean_storyboard(StoryboardDraft(scenes=[BoardScene(**x.model_dump()) for x in d.scenes],
                                                      time=BoardTime(**d.board_time.model_dump()),
                                                      handover=[BoardHandover(**x.model_dump()) for x in d.handover]))
    k = len(board.scenes)
    cues_in = [c for c in d.cues if c.start.strip() or c.beat.strip()][:cue.MAX_CUES]
    bounds = locate(e.text, [c.start for c in cues_in])
    dropped: list[str] = []
    cues = []
    for c, b in zip(cues_in, bounds):
        lines, drop = keep_lines(e.text, c.lines)
        dropped += drop
        cues.append(dict(scene=c.scene if 0 <= c.scene <= k else 0, function=c.function, tension=min(max(c.tension, 1), 5),
                         tempo=c.tempo, voice=c.voice, beat=c.beat.strip(), lines=lines, exit=c.exit.strip(), length=measured(e.text, b)))
    e.sheet = CueSheet(key=d.key.strip(), cadence=d.cadence, cues=cues, made_at=pipeline._now(), made_by="ai")
    e.bounds, e.dropped = bounds, dropped
    e.storyboard = Storyboard(**board.model_dump(), made_at=pipeline._now(), made_by="ai")
    e.plot = EpisodePlot(number=number, act=_act(lab, number), title=d.title.strip() or re.sub(HEAD_RE, r"\2", e.head).strip(),
                         summary=d.summary.strip(), events=d.events, characters=list(dict.fromkeys(names)),
                         emotional_shift=d.emotional_shift.strip(), ending_hook=d.ending_hook.strip(), opening=d.opening.strip(), time=d.time.strip())
    e.threads = list(dict.fromkeys(t.strip() for t in d.threads if t.strip()))
    e.setting = d.setting.strip()
    e.facts = list(dict.fromkeys(f.strip() for f in d.facts if f.strip()))[:FACTS_MAX]
    who = set(names) | {c.name for c in lab.cast}
    e.ties = [Relationship(a=t.a.strip(), b=t.b.strip(), type=t.type.strip() or "관계", description=t.description.strip())
              for t in d.ties if t.a.strip() in who and t.b.strip() in who and t.a.strip() != t.b.strip()]
    e.addresses = [AddressForm(speaker=x.speaker.strip(), listener=x.listener.strip(), calls=x.calls.strip(), speech=x.speech.strip())
                   for x in d.addresses if x.speaker.strip() in who and x.listener.strip() in who and x.speaker.strip() != x.listener.strip()
                   and (x.calls.strip() or x.speech.strip())]
    e.model, e.made_at = model, pipeline._now()
    e.take, e.take_style, e.blind_take, e.blind, e.picked = None, None, "", [], ""
    merge_cast(lab, d.cast)
    return e


def apply_lines(lab: RevLab, d: RevLineSet) -> None:
    """이야기 줄기를 넣고 화의 플롯에 줄기 id 를 붙인다. 실험에 없는 화 번호는 뺀다. 갈라진 화 · 합류한 화는 붙인 화에서 센다."""
    have = {e.number for e in lab.episodes}
    lab.main = d.main.strip()
    lab.lines = []
    for i, x in enumerate([x for x in d.lines if x.title.strip() or x.goal.strip()][:4], 1):
        eps = sorted({n for n in x.episodes if n in have})
        th = sorted({n for n in x.threads if n in have} - set(eps))
        seen = eps + th
        lab.lines.append(Storyline(id=f"sl-{i:02d}", kind=x.kind, title=x.title.strip(), focus=[f.strip() for f in x.focus if f.strip()],
                                   when=x.when.strip(), goal=x.goal.strip(), branch_ep=min(seen) if seen else 0,
                                   join_ep=max(seen) if seen and x.rejoin.strip() else 0, rejoin=x.rejoin.strip()))
        for e in lab.episodes:
            if not e.plot:
                continue
            if e.number in eps and not e.plot.storyline:
                e.plot.storyline = lab.lines[-1].id
            elif e.number in th and lab.lines[-1].id not in e.plot.threads:
                e.plot.threads.append(lab.lines[-1].id)
    lab.lines_at = pipeline._now()


def set_sheet(lab: RevLab, number: int, d: CueSheetDraft) -> RevEpisode:
    """작가가 고친 큐 시트. 큐 수가 바뀌면 원문 경계를 지운다 (어느 큐가 어디인지 모른다). 글자 수는 작가가 적은 값 그대로."""
    e = episode(lab, number)
    if e.sheet is None:
        raise ValueError(f"{number}화는 아직 역설계하지 않았어요")
    d = CueSheetDraft(**d.model_dump(include=set(CueSheetDraft.model_fields)))
    for c in d.cues:
        c.tension = min(max(c.tension, 1), 5)
        c.length = max(c.length, 0)
        c.lines = [CueLine(speaker=x.speaker.strip(), text=x.text.strip()) for x in c.lines if x.text.strip()][:cue.MAX_LINES]
    if not d.cues:
        raise ValueError("큐가 하나도 없어요")
    if len(d.cues) != len(e.bounds):
        e.bounds = []
    e.sheet = CueSheet(**d.model_dump(), made_at=pipeline._now(), made_by="both" if e.sheet.made_by != "author" else "author")
    return e


# ---------- 되돌려 쓰기 ----------

def context_upto(lab: RevLab, number: int) -> dict:
    """number 화까지 읽은 배경 · 사실 · 관계 · 호칭. 뒤 화가 앞 화 값을 덮는다 (같은 두 인물 · 같은 방향)."""
    setting, facts, ties, addresses = "", [], {}, {}
    for x in lab.episodes:
        if x.number > number:
            break
        setting = x.setting or setting
        facts += [f for f in x.facts if f not in facts]
        ties.update({frozenset((t.a, t.b)): t for t in x.ties})
        addresses.update({(a.speaker, a.listener): a for a in x.addresses})
    return {"setting": setting, "facts": facts, "ties": list(ties.values()), "addresses": list(addresses.values())}


def world(lab: RevLab, number: int, use_style: bool = False) -> Project:
    """역설계한 재료로 만든 작품 사본: number 화 앞은 원문을 본문으로 반영한 화, number 화는 플롯 · 스토리보드를 확정한 화.
    인물은 실험 인물 목록(id 는 이름: 몫 · 성격 · 말투), 배경 · 사실 · 관계 · 호칭은 number 화까지 읽은 것(context_upto).
    문체 프로필은 use_style 이고 역설계한 문체가 있을 때만 넣는다. 예시 문단은 늘 비운다 (원문 문장을 주면 베낀다). 저장하지 않는다."""
    e = episode(lab, number)
    if e.plot is None or e.sheet is None:
        raise ValueError(f"{number}화를 먼저 역설계하세요")
    eps = []
    for x in lab.episodes:
        if x.number > number:
            break
        plot = (x.plot or EpisodePlot(number=x.number, act=_act(lab, x.number), title=x.head, summary="", events=[], characters=[],
                                      emotional_shift="", ending_hook="")).model_copy(deep=True)
        if x.number < number:
            eps.append(Episode(plot=plot, status="finalized", text=x.text, summary=plot.summary))
        else:
            eps.append(Episode(plot=plot, status="confirmed", storyboard=x.storyboard.model_copy(deep=True) if x.storyboard else None))
    size = max(round(len(e.text) / 100) * 100, 100)
    cast = [Character(id=c.name, name=c.name, role=c.role or "인물", personality=c.personality, speech_style=c.speech) for c in lab.cast]
    ctx = context_upto(lab, number)
    style = StyleProfile()
    if use_style:
        if lab.style is None:
            raise ValueError("문체 프로필을 먼저 역설계하세요")
        style = lab.style.model_copy(deep=True)
        style.sample_passages = []
    first, last = lab.episodes[0].number, lab.episodes[-1].number
    return Project(meta=Meta(title=lab.title or "역설계 실험", target_episodes=len(lab.episodes), words_per_episode=size),
                   world=WorldSetting(setting=ctx["setting"]), characters=cast, episodes=eps, facts=ctx["facts"],
                   relationships=[t.model_copy() for t in ctx["ties"]], address_forms=[a.model_copy() for a in ctx["addresses"]],
                   style=style, storylines=[s.model_copy(deep=True) for s in lab.lines],
                   arc=[Act(name=a, start_ep=first, end_ep=last, goal="") for a in "기"])


def run_write(lab_id: int, llm, number: int, use_style: bool = False) -> RevEpisode:
    """역설계한 재료로 number 화를 한 번에 다시 쓴다 (큐 시트 실험의 조건 score). use_style 이면 문체 프로필을 넣고 take_style 에,
    아니면 take 에 둔다. 블라인드 비교는 방금 쓴 글과 원문으로 새로 섞는다."""
    from . import research

    lab = load(lab_id)
    e = episode(lab, number)
    q = world(lab, number, use_style)
    if not e.sheet.cues:
        raise ValueError("큐 시트에 큐가 없어요")
    cancel.check()
    text, sent = pipeline.write_scored(llm, q, number, e.sheet)
    take = RevTake(text=text, style=use_style, prompt_chars=sent, sheet_basis=cue.basis(e.sheet), model=research._model_name(llm),
                   at=pipeline._now())
    cancel.check()

    def put(lab: RevLab) -> None:
        x = episode(lab, number)
        if use_style:
            x.take_style = take
        else:
            x.take = take
        x.blind_take, x.blind, x.picked = "style" if use_style else "plain", random.sample(list(SIDES), 2), ""
    return episode(with_lock(lab_id, put), number)


def blind_of(e: RevEpisode) -> RevTake | None:
    """블라인드 비교에 들어간 되돌려 쓴 글."""
    return e.take_style if e.blind_take == "style" else e.take


def run_style(lab_id: int, llm) -> StyleProfile:
    """원문 앞부분(STYLE_CHARS)으로 문체 프로필을 만든다 (pipeline.analyze_style, plan 단계). 예시 문단은 비우고 저장한다."""
    from . import research

    sample = style_sample(load(lab_id))
    cancel.check()
    prof = pipeline.analyze_style(llm, sample)
    prof.sample_passages = []
    cancel.check()

    def put(lab: RevLab) -> None:
        lab.style, lab.style_model, lab.style_at = prof, research._model_name(llm), pipeline._now()
    with_lock(lab_id, put)
    return prof


def style_sample(lab: RevLab) -> str:
    text = "\n\n".join(e.text for e in lab.episodes)[:STYLE_CHARS].strip()
    if len(text) < MIN_CHARS:
        raise ValueError(f"원문이 {MIN_CHARS}자보다 짧아 문체를 역설계하지 않아요")
    return text


def pick(lab: RevLab, number: int, choice: int) -> str:
    """블라인드 비교에서 고른다: 1 · 2 (보인 차례), 0 이면 건너뛰기. 고른 쪽(original · rewrite · skip)."""
    e = episode(lab, number)
    if not blind_of(e) or len(e.blind) != 2:
        raise ValueError(f"{number}화는 되돌려 쓴 글이 없어요")
    if choice not in (0, 1, 2):
        raise ValueError("1, 2 가운데 고르거나 건너뛰세요")
    e.picked = e.blind[choice - 1] if choice else "skip"
    return e.picked


def compare(lab: RevLab, e: RevEpisode) -> list[dict]:
    """원문과 되돌려 쓴 글의 지표 (cue.score). 원문은 큐 경계로 나눠 큐마다 분량 · 템포 · 편성도 잰다."""
    if not e.sheet:
        return []
    q = world(lab, e.number)
    now = cue.basis(e.sheet)
    sides = [("original", "원문", e.text, now)] + [(k, TAKES[k], t.text, t.sheet_basis)
                                                   for k, t in (("plain", e.take), ("style", e.take_style)) if t]
    rows = []
    for key, label, text, basis in sides:
        s = cue.score(q, e.sheet, CueTake(condition=key, text=text, parts=parts(e) if key == "original" else [], sheet_basis=basis))
        s["label"], s["stale"] = label, basis != now
        rows.append(s)
    return rows


# ---------- 비용 추정과 역설계 실행 ----------

def choose(lab: RevLab, numbers: list[int] | None) -> list[int]:
    have = [e.number for e in lab.episodes]
    out = [n for n in (numbers or have)]
    bad = [n for n in out if n not in have]
    if bad:
        raise ValueError(f"실험에 없는 화예요: {', '.join(map(str, bad))}")
    if not out:
        raise ValueError("화를 하나 넘게 고르세요")
    short = [n for n in out if len(episode(lab, n).text.strip()) < MIN_CHARS]
    if short:
        raise ValueError(f"{', '.join(map(str, short))}화는 {MIN_CHARS}자보다 짧아 역설계하지 않아요")
    return sorted(out)


def wants_lines(lab: RevLab, numbers: list[int]) -> bool:
    """이야기 줄기를 물을지: 화가 둘 넘고, 고른 화를 역설계하면 모든 화가 역설계된다."""
    return len(lab.episodes) > 1 and all(e.plot is not None or e.number in numbers for e in lab.episodes)


def estimate(lab: RevLab, kind: str, numbers: list[int] | None = None, model: str = "", use_style: bool = False) -> dict:
    """AI 호출 수와 비용 추정. kind: parse(역설계, plan 단계) · write(되돌려 쓰기, write 단계) · style(문체 역설계, plan 단계).
    캐시와 생각 토큰은 넣지 않는다."""
    from . import settings

    if kind not in ("parse", "write", "style"):
        raise ValueError(f"모르는 추정이에요: {kind}")
    nums = choose(lab, numbers) if kind != "style" else []
    stage = "write" if kind == "write" else "plan"
    model = model or settings.stage_model(stage)[0] or settings.model()[0]
    price = usage.rate(model, date.today().isoformat())
    rows = []
    if kind == "style":
        tin = (len(prompts.SYSTEM_PLANNER) + len(prompts.style_prompt(style_sample(lab)))) / CHARS_PER_TOKEN
        rows.append({"label": "문체 프로필", "calls": 1, "input_tokens": round(tin), "output_tokens": STYLE_OUT_TOKENS,
                     "usd": round(usage.cost(price, tin, STYLE_OUT_TOKENS, 0, False), 3) if price else None})
    for n in nums:
        if kind == "parse":
            tin = (len(prompts.SYSTEM_REVERSE) + len(prompts.rev_prompt(lab, n))) / CHARS_PER_TOKEN
            tout = PARSE_OUT_TOKENS
        else:
            q = world(lab, n, use_style)
            tin = (len(prompts.writer_system(q)) + len(prompts.cue_score_prompt(q, n, episode(lab, n).sheet))) / CHARS_PER_TOKEN
            tout = len(episode(lab, n).text) / CHARS_PER_TOKEN
        rows.append({"label": f"{n}화", "calls": 1, "input_tokens": round(tin), "output_tokens": round(tout),
                     "usd": round(usage.cost(price, tin, tout, 0, False), 3) if price else None})
    if kind == "parse" and wants_lines(lab, nums):
        tin = (len(prompts.SYSTEM_REVERSE) + 600 + LINES_IN_CHARS * len(lab.episodes)) / CHARS_PER_TOKEN
        rows.append({"label": "이야기 줄기", "calls": 1, "input_tokens": round(tin), "output_tokens": LINES_OUT_TOKENS,
                     "usd": round(usage.cost(price, tin, LINES_OUT_TOKENS, 0, False), 3) if price else None})
    total = sum(r["usd"] or 0 for r in rows)
    note = ("입력은 실제 요청 글자 수를 글자당 토큰 추정값으로 나눠 셌어요. 출력은 화마다 "
            + {"parse": f"약 {PARSE_OUT_TOKENS:,}토큰으로 잡았어요.", "write": "원문 분량만큼 잡았어요.",
               "style": f"약 {STYLE_OUT_TOKENS:,}토큰으로 잡았어요 (원문 앞 {STYLE_CHARS:,}자까지 넣어요)."}[kind]
            + " 캐시와 생각 토큰은 넣지 않았어요.")
    return {"kind": kind, "model": model, "priced": price is not None, "calls": len(rows), "rows": rows,
            "usd": round(total, 3) if price else None, "note": note}


def run_parse(lab_id: int, llm, numbers: list[int] | None = None, progress=None) -> dict:
    """고른 화를 차례로 역설계하고(앞 화 결과가 다음 화 요청에 들어간다), 모든 화가 역설계되면 이야기 줄기를 묻는다.
    화마다 저장해 뒤 화가 실패해도 앞 화 결과는 남는다. progress(done, total, note)."""
    from . import research

    lab = load(lab_id)
    nums = choose(lab, numbers)
    lines = wants_lines(lab, nums)
    total = len(nums) + lines
    model = research._model_name(llm)
    for i, n in enumerate(nums):
        cancel.check()
        if progress:
            progress(i, total, f"{n}화 역설계")
        d = pipeline.reverse_episode(llm, load(lab_id), n)
        cancel.check()
        with_lock(lab_id, lambda lab: apply_episode(lab, n, d, model))
    if lines:
        cancel.check()
        if progress:
            progress(len(nums), total, "이야기 줄기")
        d = pipeline.reverse_lines(llm, load(lab_id))
        cancel.check()
        with_lock(lab_id, lambda lab: apply_lines(lab, d))
    lab = load(lab_id)
    return {"episodes": len(nums), "cues": sum(len(episode(lab, n).sheet.cues) for n in nums if episode(lab, n).sheet),
            "lines": len(lab.lines) if lines else None}


# ---------- 화면 값 ----------

def _updated(lab_id: int) -> str:
    """실험 파일을 마지막으로 저장한 때 (가려 읽기 고르기처럼 시각 칸이 없는 고침도 잡는다)."""
    from datetime import datetime, timezone

    path = _path(lab_id)
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds") if path.exists() else ""


def summary(lab: RevLab) -> dict:
    """목록 · 머리 값. steps 는 화마다 단계 판정에 드는 값만 (화면 revLabLite · revSteps · revNext 가 쓴다, 원문은 보내지 않는다)."""
    done = [e for e in lab.episodes if e.sheet]
    steps = [{"number": e.number, "head": e.head, "chars": len(e.text), "sheet": bool(e.sheet),
              "takes": int(bool(e.take)) + int(bool(e.take_style)), "picked": e.picked,
              "blind": not e.picked and len(e.blind) == 2 and blind_of(e) is not None} for e in lab.episodes]
    return {"id": lab.id, "title": lab.title, "created": lab.created, "updated": _updated(lab.id) or lab.created,
            "episodes": len(lab.episodes), "done": len(done), "chars": sum(len(e.text) for e in lab.episodes),
            "first": lab.episodes[0].number if lab.episodes else 1,
            "rewrites": sum(1 for e in lab.episodes if e.take or e.take_style), "cast_count": len(lab.cast),
            "has_style": lab.style is not None, "steps": steps}


def listing() -> list[dict]:
    """실험 목록, 최근에 고친 차례."""
    out = []
    for i in ids():
        try:
            out.append(summary(load(i)))
        except ValueError:
            continue  # 깨진 파일은 목록에서 뺀다
    return sorted(out, key=lambda x: (x["updated"], x["id"]), reverse=True)


def _ep_view(lab: RevLab, e: RevEpisode) -> dict:
    """화 하나의 화면 값. 블라인드 비교를 고르기 전에는 어느 쪽이 원문인지 알 수 있는 값(차례, 되돌려 쓴 글 본문 · 지표)을 뺀다."""
    out = e.model_dump(exclude={"take", "take_style", "blind", "blind_take"})
    out["chars"] = len(e.text)
    out["missing"] = [i + 1 for i, b in enumerate(e.bounds) if not b.found]
    out["bounds_ok"] = bool(e.sheet) and len(e.bounds) == len(e.sheet.cues)
    now = cue.basis(e.sheet) if e.sheet else ""
    out["takes"] = []
    for key, t in (("plain", e.take), ("style", e.take_style)):
        if t:  # 블라인드에 든 글의 본문은 고른 뒤에만 보인다
            show = bool(e.picked) or key != (e.blind_take or "plain")
            out["takes"].append({"mode": key, "label": TAKES[key], "model": t.model, "at": t.at, "prompt_chars": t.prompt_chars,
                                 "stale": t.sheet_basis != now, **({"text": t.text} if show else {})})
    b = blind_of(e)
    out["blind_texts"] = [e.text if side == "original" else b.text for side in e.blind] if b and not e.picked and len(e.blind) == 2 else []
    if e.picked:
        out["blind"], out["blind_take"] = e.blind, e.blind_take or "plain"
    hide = "" if e.picked else (e.blind_take or "plain") if b else ""
    out["scores"] = [r for r in (compare(lab, e) if e.sheet else []) if r["condition"] != hide]  # 고르기 전에는 블라인드에 든 글의 지표를 뺀다
    return out


def view(lab: RevLab) -> dict:
    """실험 화면 값: 화마다 원문 · 역설계 결과 · 경계 · 되돌려 쓰기, 이야기 줄기, 인물."""
    return {**summary(lab), "split": lab.split, "split_label": SPLITS.get(lab.split, lab.split), "preface": lab.preface,
            "cast": [c.model_dump() for c in lab.cast], "main": lab.main, "lines": [x.model_dump() for x in lab.lines], "lines_at": lab.lines_at,
            "context": [{"number": e.number, **{k: [x.model_dump() for x in v] if k in ("ties", "addresses") else v
                                                 for k, v in context_upto(lab, e.number).items()}} for e in lab.episodes if e.sheet][-1:],
            "style": lab.style.model_dump(exclude={"sample_passages"}) if lab.style else None, "style_model": lab.style_model,
            "style_at": lab.style_at, "items": [_ep_view(lab, e) for e in lab.episodes]}


def labels() -> dict:
    return {"splits": [{"key": k, "label": v} for k, v in SPLITS.items()], "max_episodes": MAX_EPISODES, "max_chars": MAX_CHARS,
            "min_chars": MIN_CHARS, "preface_min": PREFACE_MIN, "head_max": HEAD_MAX}

