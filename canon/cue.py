"""큐 시트 집필 실험: 한 화를 악보처럼 큐(연주 단위)로 나누고, 진행과 핵심 대사를 먼저 정한 뒤 본문을 쓴다.

큐마다 화성 기능(T 안정 · S 쌓기 · D 긴장), 긴장도 1~5, 템포, 편성(대사 · 행동 · 묘사 · 속생각), 일어나는 일,
핵심 대사, 끝 상태, 목표 글자 수를 정한다. 화 끝은 종지(정격 · 반 · 기만)로 정한다. 큐 시트는 AI 가 만들거나(pipeline.make_cue_sheet)
스토리보드 · 플롯에서 AI 없이 뼈대를 만들고(from_board) 작가가 고친다.

조건(CONDITIONS)마다 같은 화를 쓴다: 지금 방식 한 번에 · 큐 시트를 주고 한 번에 · 큐마다 이어 쓰기.
반영이 끝난 화는 작품 사본을 그 화를 쓰기 직전으로 되돌려(pipeline.revert) 쓴다. 작품에는 저장하지 않고
실험 파일(cuelab/<화>.json, store.load_cuelab), 실험 기록(research/log.jsonl, kind cue), 블라인드 비교본(compare/<화>, kind cue)에 남긴다.

채점은 LLM 을 부르지 않는다: 핵심 대사가 글자 그대로 들어갔는지, 같은 문장 되풀이, 큐 이음매에서 앞 큐 끝을 다시 말하는지,
마지막이 아닌 큐가 여운 문장이나 정지 장면(서 있거나 바라보는 한 줄)으로 닫히는지, 줄표로 문장을 잘라 끝내는지, 큐마다 목표 분량 · 템포 · 편성을 지켰는지.

집필 경로: 두 화 블라인드 읽기에서 '큐 시트를 주고 한 번에 쓰기'가 두 번 모두 1위라(DESIGN.md) 그 방식만 집필에 넣었다.
화에 붙인 큐 시트(Episode.cue_sheet)는 쓰기 프롬프트 끝에 들어간다(prompts.episode_prompt). 켜기는 on, 낡음은 stale,
넣기는 set_episode, 화면 값은 ep_view. 큐마다 쓰기는 실험에만 있다.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date

from . import board, cancel, metrics, pipeline, prompts, research, store, usage
from .context import CHARS_PER_TOKEN
from .schema import Cue, CueLab, CueLine, CueSheet, CueSheetDraft, CueTake, Project, StoryboardDraft

CONDITIONS: dict[str, str] = {"oneshot": "한 번에 (지금 방식)", "score": "큐 시트를 주고 한 번에", "cues": "큐마다 이어 쓰기"}
ABOUT: dict[str, str] = {
    "oneshot": "지금 집필과 같은 요청으로 한 번에 써요. 큐 시트를 넣지 않아요.",
    "score": "지금 요청 뒤에 큐 시트를 붙여 한 번에 써요. 설계만의 효과를 봐요.",
    "cues": "큐 시트의 큐를 하나씩 차례로 써서 이어 붙여요. 요청 수가 큐 수만큼 늘어요.",
}
NEEDS_SHEET = {"score", "cues"}
MAX_CUES = 12
MAX_LINES = 3
SEAM_OVERLAP = 0.5  # 다음 큐 첫 문장의 글자 3-gram 중 이만큼이 앞 큐 끝 300자에 있으면 되풀이 이음매로 본다
CLOSING_LEN = 12  # metrics._short_ending_ratio 와 같은 짧은 끝 문장 기준
# 정지 장면 끝: 인물이 서 있거나 바라보는 한 줄로 큐를 맺는 버릇 (실제 모델 실험에서 큐 6개 중 5개가 이렇게 끝났다)
# 줄표 · 말줄임으로 자른 끝: 정지 장면을 막자 큐 6개 중 5개를 '——'로 잘랐다 (원래 본문은 0개)
CUT_END = re.compile(r"(?:—|―|–|-{2,}|…|\.{3})[\"”’」』]?$")
STILL_END = re.compile(r"(?:보았다|봤다|보고 있었다|[서아어] 있었다|고 있었다|입을 다물었다|숨을 죽였다|말이 없었다)[.。…]*$")
DIALOGUE_VOICE = 0.35  # 편성이 대사인 큐는 대사 비율이 이 이상이어야 맞음


# ---------- 시험할 화 ----------

def _prev_done(p: Project, n: int) -> bool:
    return all(e.status == "finalized" for e in p.episodes if e.plot.number < n)


def _needs_revert(p: Project, n: int) -> bool:
    return any(e.status == "finalized" for e in p.episodes if e.plot.number >= n)


def candidates(p: Project) -> list[dict]:
    """시험할 수 있는 화: 플롯이 확정됐고, 앞 화가 모두 반영됐거나 직전 화 스냅샷으로 되돌릴 수 있는 화."""
    out = []
    for e in sorted(p.episodes, key=lambda x: x.plot.number):
        n = e.plot.number
        if e.status == "draft":
            continue
        if _needs_revert(p, n):
            if p.snapshot(n - 1) is None:
                continue
        elif not _prev_done(p, n):
            continue
        out.append({"episode": n, "title": e.plot.title, "written": bool(e.text.strip()), "board": e.storyboard is not None})
    return out


def before(p: Project, n: int) -> Project:
    """n화를 쓰기 직전 상태의 사본. 반영이 끝난 화면 직전 화 스냅샷으로 되돌린다. 작품은 그대로다."""
    q = p.model_copy(deep=True)
    if _needs_revert(q, n):
        pipeline.revert(q, n - 1)
    q.episode(n).cue_sheet = None  # 조건마다 실험 파일의 시트만 쓴다 (oneshot 에 화의 큐 시트가 들어가지 않게)
    return q


def check_episode(p: Project, n: int) -> None:
    if n not in {c["episode"] for c in candidates(p)}:
        raise ValueError(f"{n}화는 시험할 수 없어요. 플롯을 확정하고 앞 화를 반영한 화만 시험해요")


# ---------- 큐 시트 ----------

def _default_shape(k: int, i: int) -> tuple[str, int, str]:
    """AI 없이 만드는 뼈대의 자리별 기능 · 긴장도 · 템포: 처음은 안정, 뒤 두 큐는 긴장, 나머지는 쌓기. 긴장도는 2에서 5로 오른다."""
    fn = "T" if i == 0 and k > 2 else "D" if i >= k - 2 else "S"
    tension = 2 + round(3 * i / (k - 1)) if k > 1 else 3
    return fn, tension, {"T": "slow", "S": "mid", "D": "fast"}[fn]


def from_board(p: Project, n: int) -> CueSheet:
    """AI 없이 만드는 뼈대: 스토리보드가 있으면 장면마다, 없으면 플롯 사건마다 큐 하나. 화 끝은 반종지."""
    ep = p.episode(n)
    b = ep.storyboard
    rows: list[tuple[int, str, str]] = []  # (장면, 일, 끝)
    if b and b.scenes:
        for k, sc in enumerate(b.scenes, 1):
            beat = " → ".join(x.strip() for x in (sc.goal, sc.turn) if x.strip())
            rows.append((k, beat, sc.end_state.strip()))
    else:
        rows = [(0, ev, "") for ev in ep.plot.events]
    rows = rows[:MAX_CUES] or [(0, ep.plot.title or f"{n}화", "")]
    k = len(rows)
    size = round(p.meta.words_per_episode / k)
    cues = []
    for i, (scene, beat, end) in enumerate(rows):
        fn, tension, tempo = _default_shape(k, i)
        cues.append(Cue(scene=scene, function=fn, tension=tension, tempo=tempo, voice="description" if i == 0 else "action",
                        beat=beat, exit=end, length=size))
    if ep.plot.ending_hook.strip():
        cues[-1].exit = cues[-1].exit or ep.plot.ending_hook.strip()
    return CueSheet(key=ep.plot.emotional_shift.strip(), cadence="half", cues=cues, made_at=pipeline._now(), made_by="board")


def clean(p: Project, d: CueSheetDraft) -> CueSheetDraft:
    """빈 큐 · 빈 대사를 빼고 값 범위를 맞춘다. 목표 글자 수가 비었거나 합이 크게 어긋나면 화 분량에 맞춰 나눈다."""
    n_scenes = 0
    d.cues = [c for c in d.cues if c.beat.strip() or any(x.text.strip() for x in c.lines)][:MAX_CUES]
    for c in d.cues:
        c.tension = min(max(c.tension, 1), 5)
        c.lines = [CueLine(speaker=x.speaker.strip(), text=x.text.strip().strip('"“”「」『』')) for x in c.lines if x.text.strip()][:MAX_LINES]
        c.length = max(c.length, 0)
        c.scene = max(c.scene, 0)
        n_scenes = max(n_scenes, c.scene)
    size = p.meta.words_per_episode
    total = sum(c.length for c in d.cues)
    if d.cues and (total == 0 or not size * 0.5 <= total <= size * 1.5):
        even = round(size / len(d.cues))
        for c in d.cues:
            c.length = round(c.length * size / total) if total else even
    d.key = d.key.strip()
    return d


def basis(sheet: CueSheet) -> str:
    """큐 시트 내용의 지문. 만든 때 · 만든 이는 넣지 않는다 (고치지 않고 다시 저장해도 같다)."""
    raw = CueSheetDraft(**sheet.model_dump(include=set(CueSheetDraft.model_fields))).model_dump_json()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def set_sheet(lab: CueLab, d: CueSheetDraft, p: Project, by: str = "author") -> CueSheet:
    """큐 시트를 넣는다. 작가가 AI · 뼈대 시트를 고치면 made_by 는 both."""
    old = lab.sheet
    made_by = by if by != "author" else ("both" if old and old.made_by != "author" else "author")
    draft = clean(p, CueSheetDraft(**d.model_dump(include=set(CueSheetDraft.model_fields))))
    lab.sheet = CueSheet(**draft.model_dump(), made_at=pipeline._now(), made_by=made_by)
    return lab.sheet


# ---------- 집필 경로: 화에 붙인 큐 시트 ----------

def on(p: Project) -> bool:
    """이 작품이 화마다 큐 시트를 쓰는지. 작가가 정하지 않았으면 장편 켬 · 단편 끔 (스토리보드와 같은 규칙, board.on)."""
    v = p.settings.cue_sheet
    return p.serial if v is None else v


def ep_basis(p: Project, n: int) -> str:
    """화의 큐 시트를 만든 입력의 지문: 스토리보드 입력(board.basis)과 스토리보드 내용."""
    b = p.episode(n).storyboard
    raw = board.basis(p, n) + "\x1f" + (StoryboardDraft(**b.model_dump(include=set(StoryboardDraft.model_fields))).model_dump_json() if b else "")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def stale(p: Project, n: int) -> bool:
    """본문을 쓰기 전인데 큐 시트를 만든 뒤 입력(직전 화 본문, 플롯, 인물 상태, 스토리보드)이 바뀌었다."""
    e = p.episode(n)
    s = e.cue_sheet
    return bool(s and s.basis and not e.text and s.basis != ep_basis(p, n))


def set_episode(p: Project, n: int, d: CueSheetDraft | None, by: str = "author") -> None:
    """화에 큐 시트를 넣거나 지운다(d=None). 작가가 저장하면 지금 입력을 보고 고친 것으로 보아 지문을 지금 값으로 둔다.
    AI · 뼈대 시트를 작가가 고치면 made_by 는 both. 본문을 쓴 뒤에도 고칠 수 있다 (다시 생성이 그대로 쓴다)."""
    ep = p.episode(n)
    if d is None:
        ep.cue_sheet = None
        return
    old = ep.cue_sheet
    made_by = by if by != "author" else ("both" if old and old.made_by != "author" else "author")
    draft = clean(p, CueSheetDraft(**d.model_dump(include=set(CueSheetDraft.model_fields))))
    if not draft.cues:
        raise ValueError("큐가 하나도 없어요. 일어나는 일이나 핵심 대사를 적은 큐가 있어야 해요")
    ep.cue_sheet = CueSheet(**draft.model_dump(), made_at=pipeline._now(), made_by=made_by, basis=ep_basis(p, n))


def ep_view(p: Project, n: int) -> dict:
    """집필 화면 값: 켜짐, 낡음, 본문이 있으면 핵심 대사가 들어간 수와 빠진 대사."""
    e = p.episode(n)
    s = e.cue_sheet
    out = {"on": on(p), "stale": stale(p, n), "hit": 0, "total": 0, "missed": []}
    if s and e.text:
        out["hit"], out["total"], out["missed"] = line_hits(s, e.text)
    return out


# ---------- 채점 (LLM 없음) ----------

def _flat(s: str) -> str:
    """대사 맞추기용: 공백 · 따옴표 · 끝 문장부호를 지운다."""
    return re.sub(r"[\s\"'“”‘’「」『』.,!?…~·]", "", s)


def line_hits(sheet: CueSheet, text: str) -> tuple[int, int, list[str]]:
    """핵심 대사가 글자 그대로(공백 · 따옴표 · 문장부호는 빼고) 들어간 수: (들어감, 전체, 빠진 대사)."""
    flat = _flat(text)
    lines = [x.text for c in sheet.cues for x in c.lines if x.text.strip()]
    missed = [x for x in lines if _flat(x) not in flat]
    return len(lines) - len(missed), len(lines), missed


def repeats(text: str, min_len: int = 10) -> list[str]:
    """두 번 넘게 나온 문장 (min_len 자 이상)."""
    seen: dict[str, int] = {}
    for s in metrics.sentences(text):
        if len(s) >= min_len:
            seen[s] = seen.get(s, 0) + 1
    return [s for s, k in seen.items() if k > 1]


def _grams(s: str) -> set[str]:
    s = re.sub(r"\s", "", s)
    return {s[i:i + 3] for i in range(len(s) - 2)}


def seams(parts: list[str]) -> list[dict]:
    """큐 이음매마다: 다음 큐 첫 문장이 앞 큐 끝 300자를 얼마나 되풀이하는지(overlap), 되풀이로 보는지(repeat)."""
    out = []
    for k in range(1, len(parts)):
        first = next(iter(metrics.sentences(parts[k])), "")
        a, b = _grams(first), _grams(parts[k - 1][-300:])
        ov = round(len(a & b) / len(a), 2) if a else 0.0
        out.append({"after": k, "first": first[:80], "overlap": ov, "repeat": len(first) >= 8 and ov >= SEAM_OVERLAP})
    return out


def closing(parts: list[str]) -> list[int]:
    """마지막이 아닌 큐 가운데 대사가 아닌 짧은 끝 문장(여운을 노린 닫기)으로 끝난 큐 번호."""
    out = []
    for k, t in enumerate(parts[:-1], 1):
        sents = metrics.sentences(t)
        if len(sents) >= 2 and len(sents[-1]) <= CLOSING_LEN and not re.fullmatch(r"[\"“「『].*", sents[-1]):
            out.append(k)
    return out


def still(parts: list[str]) -> list[int]:
    """마지막이 아닌 큐 가운데 서 있거나 바라보는 정지 장면 서술 문장으로 끝난 큐 번호 (STILL_END)."""
    out = []
    for k, t in enumerate(parts[:-1], 1):
        last = next(iter(reversed(metrics.sentences(t))), "")
        if last and not re.match(r"[\"“「『]", last) and STILL_END.search(last):
            out.append(k)
    return out


def cut(parts: list[str]) -> list[int]:
    """마지막이 아닌 큐 가운데 줄표나 말줄임으로 문장을 잘라 끝낸 큐 번호 (CUT_END)."""
    return [k for k, t in enumerate(parts[:-1], 1) if CUT_END.search(t.rstrip())]


def cue_rows(sheet: CueSheet, parts: list[str]) -> list[dict]:
    """큐마다 목표와 실제: 글자 수, 문장 길이 평균, 대사 비율, 편성 맞음."""
    rows = []
    for k, (c, t) in enumerate(zip(sheet.cues, parts), 1):
        m = metrics.measure(t)
        voice_ok = m.dialogue_ratio >= DIALOGUE_VOICE if c.voice == "dialogue" else m.dialogue_ratio < DIALOGUE_VOICE if c.voice in ("description", "interior") else None
        rows.append({"cue": k, "function": c.function, "tension": c.tension, "tempo": c.tempo, "voice": c.voice,
                     "target": c.length, "chars": m.chars, "fit": round(m.chars / c.length, 2) if c.length else None,
                     "sentence_len": m.sentence_len_mean, "dialogue_ratio": m.dialogue_ratio, "voice_ok": voice_ok})
    return rows


def tempo_order(rows: list[dict]) -> bool | None:
    """빠른 큐의 문장이 느린 큐보다 짧은지. 느린 큐와 빠른 큐가 모두 있을 때만 판정한다."""
    by: dict[str, list[float]] = {}
    for r in rows:
        if r["sentence_len"]:
            by.setdefault(r["tempo"], []).append(r["sentence_len"])
    if not by.get("slow") or not by.get("fast"):
        return None
    return sum(by["fast"]) / len(by["fast"]) < sum(by["slow"]) / len(by["slow"])


def score(p: Project, sheet: CueSheet | None, take: CueTake) -> dict:
    """본문 하나 채점. 큐 시트가 없으면 핵심 대사 · 큐별 칸은 비운다."""
    m = metrics.measure(take.text, p.style.banned_phrases)
    out = {"condition": take.condition, "label": CONDITIONS.get(take.condition, take.condition), "chars": m.chars,
           "calls": take.calls, "prompt_tokens": round(take.prompt_chars / CHARS_PER_TOKEN),
           "sentence_len": m.sentence_len_mean, "dialogue_ratio": m.dialogue_ratio, "mattr": m.mattr,
           "ai_patterns": len(m.ai_pattern_hits), "short_endings": m.short_ending_ratio,
           "repeats": repeats(take.text), "lines_hit": None, "lines_total": 0, "missed": [],
           "seams": [], "closing": [], "still": [], "cut": [], "rows": [], "tempo_order": None,
           "stale": bool(sheet and take.condition in NEEDS_SHEET and take.sheet_basis != basis(sheet)), "at": take.at}
    if sheet:
        hit, total, missed = line_hits(sheet, take.text)
        out.update(lines_hit=hit, lines_total=total, missed=missed)
    if take.parts and sheet and len(take.parts) == len(sheet.cues):
        rows = cue_rows(sheet, take.parts)
        out.update(seams=seams(take.parts), closing=closing(take.parts), still=still(take.parts), cut=cut(take.parts), rows=rows, tempo_order=tempo_order(rows))
    return out


def view(name: str, p: Project, n: int) -> dict:
    """화면 값: 큐 시트, 조건마다 본문과 채점."""
    lab = store.load_cuelab(name, n)
    ep = p.episode(n)
    return {"episode": n, "title": ep.plot.title, "board": ep.storyboard is not None, "sheet": lab.sheet.model_dump() if lab.sheet else None,
            "takes": [{**t.model_dump(), "score": score(p, lab.sheet, t)} for t in lab.takes],
            "model": lab.model, "run_at": lab.run_at}


# ---------- 비용 추정과 실행 ----------

def _cue_prompt_chars(q: Project, n: int, sheet: CueSheet) -> int:
    """큐마다 쓰기의 요청 글자 수 합. 앞 큐 본문 자리는 목표 글자 수로 채워 잰다."""
    fake = ["가" * c.length for c in sheet.cues]
    sys = len(prompts.writer_system(q))
    return sum(sys + len(prompts.cue_play_prompt(q, n, sheet, fake[:k])) for k in range(len(sheet.cues)))


def prompt_chars(q: Project, n: int, cond: str, sheet: CueSheet | None) -> int:
    sys = len(prompts.writer_system(q))
    if cond == "oneshot":
        return sys + len(prompts.episode_prompt(q, n))
    if sheet is None:
        raise ValueError("큐 시트를 먼저 만드세요")
    if cond == "score":
        return sys + len(prompts.cue_score_prompt(q, n, sheet))
    return _cue_prompt_chars(q, n, sheet)


def _conds(conditions: list[str] | None) -> list[str]:
    conds = [c for c in (conditions or list(CONDITIONS))]
    bad = [c for c in conds if c not in CONDITIONS]
    if bad:
        raise ValueError(f"알 수 없는 조건이에요: {', '.join(bad)}")
    if not conds:
        raise ValueError("조건을 하나 넘게 고르세요")
    return conds


def estimate(p: Project, n: int, sheet: CueSheet | None, conditions: list[str] | None = None, model: str = "") -> dict:
    """쓰기 호출 수와 비용 추정. 캐시는 넣지 않는다 (큐마다 쓰기는 앞 요청을 통째로 품어 캐시가 맞으면 입력 값이 크게 준다)."""
    from . import settings

    conds = _conds(conditions)
    check_episode(p, n)
    q = before(p, n)
    model = model or settings.stage_model("write")[0] or settings.model()[0]
    price = usage.rate(model, date.today().isoformat())
    out_tokens = p.meta.words_per_episode / CHARS_PER_TOKEN
    rows, total = [], 0.0
    for cond in conds:
        tin = prompt_chars(q, n, cond, sheet) / CHARS_PER_TOKEN
        calls = len(sheet.cues) if cond == "cues" and sheet else 1
        c = usage.cost(price, tin, out_tokens, 0, False) if price else None
        total += c or 0
        rows.append({"condition": cond, "label": CONDITIONS[cond], "calls": calls, "input_tokens": round(tin),
                     "output_tokens": round(out_tokens), "usd": round(c, 3) if c is not None else None})
    return {"model": model, "priced": price is not None, "calls": sum(r["calls"] for r in rows),
            "usd": round(total, 3) if price else None, "rows": rows,
            "note": "입력은 실제 요청 글자 수, 출력은 화당 분량을 글자당 토큰 추정값으로 나눠 셌어요. 캐시와 생각 토큰은 넣지 않았어요."}


def run(name: str, p: Project, llm, n: int, conditions: list[str] | None = None, progress=None) -> dict:
    """조건마다 n화를 써서 실험 파일에 넣고, 블라인드 비교본과 실험 기록을 남긴다. progress(done, total, note)."""
    conds = _conds(conditions)
    check_episode(p, n)
    lab = store.load_cuelab(name, n)
    sheet = lab.sheet
    if sheet is None and NEEDS_SHEET & set(conds):
        raise ValueError("큐 시트를 먼저 만드세요")
    if sheet is not None and not sheet.cues and NEEDS_SHEET & set(conds):
        raise ValueError("큐 시트에 큐가 없어요")
    q = before(p, n)
    steps = {"oneshot": 1, "score": 1, "cues": len(sheet.cues) if sheet else 0}
    total, done = sum(steps[c] for c in conds), 0
    takes: list[CueTake] = []
    for cond in conds:
        cancel.check()
        if progress:
            progress(done, total, CONDITIONS[cond])
        now = pipeline._now()
        if cond == "oneshot":
            text = pipeline.write_episode(llm, q, n, use_board=True)
            take = CueTake(condition=cond, text=text, prompt_chars=prompt_chars(q, n, cond, None), at=now)
        elif cond == "score":
            text, sent = pipeline.write_scored(llm, q, n, sheet)
            take = CueTake(condition=cond, text=text, prompt_chars=sent, sheet_basis=basis(sheet), at=now)
        else:
            base = done

            def step(k: int, kk: int) -> None:
                if progress:
                    progress(base + k - 1, total, f"{CONDITIONS[cond]} · 큐 {k}/{kk}")
            parts, sent = pipeline.play_cues(llm, q, n, sheet, progress=step)
            take = CueTake(condition=cond, text="\n\n".join(parts), parts=parts, calls=len(parts), prompt_chars=sent,
                           sheet_basis=basis(sheet), at=now)
        takes.append(take)
        done += steps[cond]
        with_lock(name, n, lambda lab: _keep(lab, [take], research._model_name(llm)))  # 뒤 조건이 실패해도 쓴 본문은 남긴다
    if len(takes) > 1:
        research.save_compare(name, n, {t.condition: t.text for t in takes}, kind="cue")
    rows = [{k: v for k, v in score(p, sheet, t).items() if k not in ("rows", "seams")} for t in takes]
    return research.record(name, "cue", {"episode": n, "conditions": conds, "cues": len(sheet.cues) if sheet else 0,
                                         "model": research._model_name(llm), "summary": rows})


def _keep(lab: CueLab, takes: list[CueTake], model: str) -> None:
    keep = {t.condition for t in takes}
    lab.takes = [t for t in lab.takes if t.condition not in keep] + takes
    lab.takes.sort(key=lambda t: list(CONDITIONS).index(t.condition) if t.condition in CONDITIONS else 99)
    lab.model, lab.run_at = model, pipeline._now()


def with_lock(name: str, n: int, fn) -> CueLab:
    """실험 파일을 읽어 fn 으로 고치고 저장한다. 작품 잠금 안에서 해 화면 저장과 섞이지 않게 한다."""
    from . import jobs

    with jobs.project_lock(name):
        lab = store.load_cuelab(name, n)
        fn(lab)
        store.save_cuelab(name, lab)
    return lab
