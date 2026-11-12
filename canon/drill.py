"""지시 연습: 레퍼런스 원고의 한 대목을 가려 두고, 작가가 AI에게 줄 지시를 적어 두 판을 쓰게 한 뒤 줄마다 되짚는다 (docs/drill).

판 하나가 <CANON_HOME>/.drill/<id>.json 하나다 (CANON_DRILL 로 경로 변경, 문단 연습장처럼 작품 밖). 작품(project.json)에는 쓰지 않는다.
쓰기는 문단 연습장을 그대로 쓴다: 지시를 상황 카드(SceneCard)로 옮겨 pipeline.draft_paragraph 로 쓰고 studio.measure 로 잰다.
원문 대목(source)은 쓰기 요청에 넣지 않는다. 사실 뽑기(pipeline.drill_facts)와 되짚기(pipeline.drill_review)에만 넣는다.
이 모듈은 LLM 을 부르지 않는다.
"""
from __future__ import annotations

import os
import random
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import library, metrics, refdigest, refs, store, studio
from .schema import (DrillAttempt, DrillBrief, DrillFacts, DrillGap, DrillInvented, DrillLine, DrillPerson, DrillReview, DrillRound,
                     DrillVerdict, SceneCard, StudioPerson)

ID_RE = re.compile(r"^[0-9a-f]{8,32}$")
PASSAGE = 900  # 대목 하나의 글자 수 어림 (줄 경계에서 자른다)
PASSAGE_MIN = 450  # 화 끝에 이보다 짧게 남으면 앞 대목에 붙인다
LEAD_MAX = 3000  # 사실 뽑기에 함께 넣는 그 화 앞부분 글자 수
DIALOGUE = (0.15, 0.75)  # 도구가 대목을 고를 때 먼저 보는 대사 비율 범위 (서술만 · 대사만인 대목은 뒤로)
METHOD_MAX = 5  # 쓰는 방식 줄 수 상한 (세 물음을 합쳐)
LINE_MAX = 200  # 지시 한 줄
EVENTS_MAX = 8
PEOPLE_MAX = 6
JUDGED_MAX = 12  # 되짚는 줄 수 상한
INVENTED_MAX = 4
GAPS_MAX = 3
QUOTE_MIN = 4  # 인용으로 보는 가장 짧은 글자 수 (공백 · 문장부호 빼고)
TITLE_MAX = 60

# 층: id → (화면 이름, 뜻). 순서가 화면 순서다. 프롬프트(prompts.drill_review_prompt)도 이 글을 쓴다
LAYERS: dict[str, tuple[str, str]] = {
    "background": ("배경 정보", "인물의 과거 · 사정 · 속마음처럼 장면이 시작하기 전에 이미 정해진 것"),
    "event": ("사건", "이 장면에서 누가 무엇을 하거나 말하는지"),
    "change": ("바뀌는 것", "장면 안에서 무엇이 무엇으로 바뀌는지, 누가 무엇을 알게 되는지"),
    "withhold": ("가릴 것", "글자로 쓰지 않고 독자가 짐작하게 둘 것"),
    "manner": ("방식", "말투 · 속도 · 거리 · 어조처럼 어떻게 쓰는지"),
    "action": ("동작", "손 · 몸 · 물건의 자리까지 정한 구체적인 동작"),
    "ban": ("금지", "하지 않을 것"),
}
RESULTS = {"applied": "반영됨", "overdone": "과하게 풀림", "ignored": "무시됨", "unsure": "판정 못 함"}
# 지시 칸: id → 화면 이름. 앞 여섯은 사실 · 일어나는 일, 뒤 셋은 쓰는 방식이다
BOXES = {"people": "인물", "pov": "시점 인물", "place": "장소", "time": "때", "before": "직전 상황", "events": "일어나는 일",
         "change": "바뀌는 것", "avoid": "하지 않는 것", "manner": "방식"}
METHOD = ("change", "avoid", "manner")
# AI가 판정하지 않은 줄에 붙이는 층: 적은 칸으로 어림한다 (그 밖의 사실 칸은 배경 정보)
BOX_LAYER = {"change": "change", "avoid": "ban", "manner": "manner", "events": "event"}
FACT_LINES = ("people", "before", "events")  # 여러 줄 칸
FACT_ONE = ("pov", "place", "time")  # 한 줄 칸


def layers() -> list[dict]:
    return [{"id": k, "label": v[0], "rule": v[1]} for k, v in LAYERS.items()]


# ---------- 저장 ----------

def root() -> Path:
    return Path(os.environ.get("CANON_DRILL") or store.ROOT / ".drill")


def _path(did: str) -> Path:
    if not ID_RE.match(did):
        raise KeyError(f"지시 연습에 없는 판이에요: {did}")
    return root() / f"{did}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load(did: str) -> DrillRound:
    path = _path(did)
    if not path.exists():
        raise KeyError(f"지시 연습에 없는 판이에요: {did}")
    return DrillRound.model_validate_json(path.read_text(encoding="utf-8"))


def save(r: DrillRound) -> DrillRound:
    r.created_at = r.created_at or _now()
    r.updated_at = _now()
    path = _path(r.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    store.write_atomic(path, r.model_dump_json(indent=2))
    return r


def rounds() -> list[DrillRound]:
    d = root()
    if not d.exists():
        return []
    out = []
    for f in d.glob("*.json"):
        try:
            out.append(DrillRound.model_validate_json(f.read_text(encoding="utf-8")))
        except ValueError:
            continue  # 깨진 파일은 목록에서 뺀다 (지우지 않는다)
    return sorted(out, key=lambda r: r.created_at, reverse=True)


def delete(did: str) -> None:
    path = _path(did)
    if not path.exists():
        raise KeyError(f"지시 연습에 없는 판이에요: {did}")
    path.unlink()


# ---------- 문제: 원고의 화를 대목으로 나누고 하나를 고른다 ----------

def passages(text: str) -> list[dict]:
    """화 글을 줄 경계에서 약 PASSAGE 자 대목으로 나눈다 [{start, end, text}] (글자 자리). 같은 글이면 같은 결과다.
    끝에 PASSAGE_MIN 자보다 짧게 남으면 앞 대목에 붙인다."""
    cuts, start, size, pos = [], 0, 0, 0
    for line in text.split("\n"):
        size += len(line.strip())
        pos += len(line) + 1
        if size >= PASSAGE:
            cuts.append((start, min(pos, len(text))))
            start, size = pos, 0
    if start < len(text) and text[start:].strip():
        if cuts and size < PASSAGE_MIN:
            cuts[-1] = (cuts[-1][0], len(text))
        else:
            cuts.append((start, len(text)))
    return [{"start": a, "end": b, "text": text[a:b].strip()} for a, b in cuts if text[a:b].strip()]


def _episodes(rid: str) -> list[dict]:
    """쓸 수 있는 화 [{order, label, text, kind, tension}]. 화 카드가 없는 화는 kind 가 빈 글, tension 이 0 이다."""
    b = refs.load(rid)
    try:
        chosen = refs.pick(b, [e.order for e in b.eps])
    except ValueError:
        return []
    try:
        cards = {x.basis: x.digest for x in refdigest.load(rid).items}
    except (KeyError, ValueError):
        cards = {}
    out = []
    for c in chosen:
        g = cards.get(refdigest.basis(c["text"]))
        out.append({"order": c["order"], "label": c["label"], "text": c["text"], "kind": g.kind if g else "", "tension": g.tension if g else 0})
    return out


def sources() -> list[dict]:
    """문제를 낼 수 있는 원고 [{id, name, eps}] (원문 없음)."""
    return [{"id": b.id, "name": b.name, "eps": len(b.eps)} for b in refs.entries() if b.eps]


def episodes(rid: str) -> list[dict]:
    """원고의 화 목록 (원문 없음): 차례 · 이름 · 글자 수 · 대목 수 · 화 카드의 성격 · 긴장."""
    return [{"order": e["order"], "label": e["label"], "chars": len(e["text"]), "parts": len(passages(e["text"])), "kind": e["kind"],
             "tension": e["tension"]} for e in _episodes(rid)]


def pick(rid: str, order: int = 0, part: int = 0, kind: str = "", tension: int = 0, rng: Optional[random.Random] = None) -> dict:
    """대목 하나를 고른다 {order, label, part, parts, text, lead}. order · part 가 0 이면 도구가 고른다:
    화는 화 카드의 성격(kind) · 긴장(tension 이상)에 맞는 것 가운데, 대목은 대사 비율이 DIALOGUE 안인 것 가운데 무작위."""
    rng = rng or random.Random()
    eps = _episodes(rid)
    if not eps:
        raise ValueError("이 원고에는 쓸 수 있는 화가 없어요")
    if order:
        ep = next((e for e in eps if e["order"] == order), None)
        if ep is None:
            raise KeyError(f"{order}번째 화가 없어요")
    else:
        pool = [e for e in eps if (not kind or e["kind"] == kind) and e["tension"] >= tension]
        if not pool:
            raise ValueError("고른 성격 · 긴장에 맞는 화가 없어요. 조건을 풀거나 레퍼런스 원고에서 화 카드를 먼저 읽히세요")
        ep = rng.choice(pool)
    ps = passages(ep["text"])
    if not ps:
        raise ValueError("그 화에는 글이 없어요")
    if part:
        if not 1 <= part <= len(ps):
            raise KeyError(f"{part}번째 대목이 없어요")
        i = part - 1
    else:
        mixed = [k for k, x in enumerate(ps) if DIALOGUE[0] <= metrics.measure(x["text"], []).dialogue_ratio <= DIALOGUE[1]]
        i = rng.choice(mixed or list(range(len(ps))))
    x = ps[i]
    return {"order": ep["order"], "label": ep["label"], "part": i + 1, "parts": len(ps), "text": x["text"],
            "lead": ep["text"][max(0, x["start"] - LEAD_MAX):x["start"]].strip()}


def create(rid: str, order: int = 0, part: int = 0, kind: str = "", tension: int = 0, style_id: str = "",
           rng: Optional[random.Random] = None) -> DrillRound:
    """새 판을 만든다. 원문 대목과 앞부분을 판 파일에 옮겨 두므로 원고를 고치거나 지워도 판은 남는다."""
    b = refs.load(rid)
    if style_id and not library.exists(style_id):
        raise ValueError("고른 문체를 문체 라이브러리에서 찾지 못했어요. 다른 문체를 고르세요")
    x = pick(rid, order, part, kind, tension, rng)
    title = f"{b.name} {x['label'] or str(x['order']) + '번째 화'} · 대목 {x['part']}/{x['parts']}"
    return save(DrillRound(id=uuid.uuid4().hex[:12], title=title[:TITLE_MAX], ref_id=b.id, ref_name=b.name, order=x["order"], ep_label=x["label"],
                           part=x["part"], parts=x["parts"], source=x["text"], lead=x["lead"], style_id=style_id))


# ---------- 사실 (AI가 뽑은 것) 과 지시 (작가가 적은 것) ----------

def _lines(text: str) -> list[str]:
    return [x.strip()[:LINE_MAX] for x in text.split("\n") if x.strip()]


def _copied(text: str, *sources: str) -> bool:
    """원문(대목 · 그 화의 앞부분)과 refs.OVERLAP_MIN 자 넘게 같은 구절이 있다."""
    return any(h["kind"] == "quote" for h in refs.overlap(text, [s for s in sources if s]))


def clean_facts(f: DrillFacts, source: str, lead: str = "") -> DrillFacts:
    """앞뒤 공백을 떼고 빈 줄을 뺀다. 원문 문장을 옮긴 줄은 버린다 (쓰기 요청에 원문이 새지 않게). 일어나는 일이 남지 않으면 막는다.
    사실 뽑기 요청에는 대목 앞의 글(lead)도 들어가므로 그 글과도 견준다."""
    ok = lambda t: bool(t.strip()) and not _copied(t.strip(), source, lead)  # noqa: E731
    people = [DrillPerson(name=p.name.strip(), note=p.note.strip()[:LINE_MAX] if ok(p.note) else "") for p in f.people if p.name.strip()]
    events = [e.strip()[:LINE_MAX] for e in f.events if ok(e)]
    if not events:
        raise ValueError("AI가 일어나는 일을 뽑지 못했어요. 다시 해 보세요")
    one = lambda t: " ".join(t.split())[:LINE_MAX] if ok(t) else ""  # noqa: E731
    return DrillFacts(people=people[:PEOPLE_MAX], pov=one(f.pov), place=one(f.place), time=one(f.time), before=one(f.before), events=events[:EVENTS_MAX])


def facts_brief(f: Optional[DrillFacts]) -> DrillBrief:
    """AI가 뽑은 사실을 지시 칸 모양으로. 쓰는 방식은 비어 있다."""
    if f is None:
        return DrillBrief()
    return DrillBrief(people="\n".join(f"{p.name}: {p.note}" if p.note else p.name for p in f.people), pov=f.pov, place=f.place, time=f.time,
                      before=f.before, events="\n".join(f.events))


def set_facts(r: DrillRound, f: DrillFacts, model: str = "") -> None:
    """뽑은 사실을 남긴다. 작가가 사실 · 일어나는 일 칸을 아직 고치지 않았으면 그 칸도 새 값으로 채운다 (쓰는 방식은 그대로)."""
    old = facts_brief(r.facts)
    fresh = all(getattr(r.brief, k) in ("", getattr(old, k)) for k in (*FACT_LINES, *FACT_ONE))
    r.facts, r.facts_model = clean_facts(f, r.source, r.lead), model
    if fresh:
        new = facts_brief(r.facts)
        r.brief = new.model_copy(update={k: getattr(r.brief, k) for k in METHOD})


def clean_brief(b: DrillBrief) -> DrillBrief:
    """칸마다 빈 줄을 빼고 줄을 다듬는다. 쓰는 방식이 METHOD_MAX 줄을 넘으면 막는다."""
    out = DrillBrief(**{k: "\n".join(_lines(getattr(b, k))) for k in (*FACT_LINES, *METHOD)},
                     **{k: " ".join(getattr(b, k).split())[:LINE_MAX] for k in FACT_ONE})
    n = len(method_lines(out))
    if n > METHOD_MAX:
        raise ValueError(f"쓰는 방식은 {METHOD_MAX}줄까지예요. 지금 {n}줄이에요")
    return out


def method_lines(b: DrillBrief) -> list[tuple[str, str]]:
    """쓰는 방식의 줄 [(칸, 글)]."""
    return [(k, x) for k in METHOD for x in _lines(getattr(b, k))]


def can_write(r: DrillRound, b: DrillBrief) -> None:
    """쓸 수 있는 지시인지 본다: 일어나는 일이 있고, 쓰는 방식이 한 줄은 있고, 원문 문장(대목 · 앞부분)이 들어 있지 않다."""
    if not _lines(b.events):
        raise ValueError("일어나는 일을 한 줄은 적으세요")
    if not method_lines(b):
        raise ValueError("쓰는 방식을 한 줄은 적으세요. 비우면 두 판이 같아요")
    for k in BOXES:
        if _copied(getattr(b, k), r.source, r.lead):
            raise ValueError(f"'{BOXES[k]}' 칸에 원문 문장이 그대로 들어 있어요. 자기 말로 바꿔 적으세요")


def _people(text: str) -> list[StudioPerson]:
    out = []
    for line in _lines(text):
        m = re.match(r"(?:[-·*]\s*)?([^:：]+)[:：]\s*(.*)$", line)
        out.append(StudioPerson(name=(m.group(1) if m else line).strip(), note=m.group(2).strip() if m else ""))
    return out[:PEOPLE_MAX]


def card_of(r: DrillRound, b: DrillBrief, bare: bool = False) -> SceneCard:
    """지시를 문단 연습장 상황 카드로 옮긴다 (docs/drill 정한 것 12). bare 면 쓰는 방식을 비운다. 원문은 넣지 않는다.
    직전 상황과 일어나는 일은 '무슨 일'에, 쓰는 방식은 '더 지킬 것'에 줄마다 물음 이름을 붙여 넣는다."""
    events = "\n".join(f"{i}. {x}" for i, x in enumerate(_lines(b.events), 1))
    action = (f"직전 상황: {' '.join(_lines(b.before))}\n" if b.before.strip() else "") + f"일어나는 일 (이 차례대로):\n{events}"
    extra = "" if bare else "\n- ".join(f"{BOXES[k]}: {x}" for k, x in method_lines(b))
    lo, hi = studio.LENGTH
    return studio.clean_card(SceneCard(people=_people(b.people), pov=b.pov, place=b.place, time=b.time, action=action, extra=extra,
                                       length=max(lo, min(hi, round(len(r.source) / 50) * 50)), style_id=r.style_id))


def brief_text(b: DrillBrief) -> str:
    """되짚기 요청에 넣는 사실 · 일어나는 일 글 (두 판에 함께 준 것)."""
    rows = [f"{BOXES[k]}: {getattr(b, k)}" for k in FACT_ONE if getattr(b, k)]
    people = "\n".join(f"- {x}" for x in _lines(b.people)) or "- 없음"
    events = "\n".join(f"{i}. {x}" for i, x in enumerate(_lines(b.events), 1)) or "없음"
    return "\n".join([*rows, f"인물:\n{people}", f"직전 상황: {' '.join(_lines(b.before)) or '없음'}", f"일어나는 일:\n{events}"])


def author_lines(b: DrillBrief, base: Optional[DrillBrief] = None) -> list[DrillLine]:
    """되짚을 줄: AI가 뽑은 것(base)과 다른 사실 · 일어나는 일 줄, 그리고 쓰는 방식의 모든 줄. 번호는 1부터.
    쓰는 방식 줄을 먼저 챙기고 남는 자리(JUDGED_MAX)에 사실 줄을 넣는다. 화면 차례는 사실 → 쓰는 방식이다."""
    base = base or DrillBrief()
    method = method_lines(b)[:METHOD_MAX]
    facts = []
    for k in FACT_ONE:
        v = getattr(b, k).strip()
        if v and v != getattr(base, k).strip():
            facts.append((k, v))
    for k in FACT_LINES:
        seen = set(_lines(getattr(base, k)))
        facts += [(k, x) for x in _lines(getattr(b, k)) if x not in seen]
    rows = facts[:JUDGED_MAX - len(method)] + method
    return [DrillLine(no=i, box=k, text=x) for i, (k, x) in enumerate(rows, 1)]


# ---------- 시도와 되짚기 ----------

def find(r: DrillRound, no: int) -> DrillAttempt:
    a = next((x for x in r.attempts if x.no == no), None)
    if a is None:
        raise KeyError(f"{no}번 시도가 없어요")
    return a


def add_attempt(r: DrillRound, b: DrillBrief, with_text: str, bare_text: str, model: str = "") -> DrillAttempt:
    a = DrillAttempt(no=max((x.no for x in r.attempts), default=0) + 1, brief=b.model_copy(deep=True), with_text=with_text.strip(),
                     bare_text=bare_text.strip(), model=model, at=_now())
    r.attempts.append(a)
    return a


_DROP = re.compile(r"[\s\"'“”‘’「」『』…⋯·.,!?~\-—]+")


def _flat(t: str) -> str:
    """인용을 견주는 꼴: 공백 · 따옴표 · 줄임표 · 문장부호를 뺀다 (모델이 ⋯ 를 … 로, 굽은 따옴표를 곧은 따옴표로 바꿔 적는다)."""
    return _DROP.sub("", t)


def quoted(quote: str, text: str) -> bool:
    """quote 가 text 에 글자 그대로(공백 · 문장부호 빼고) 있다. QUOTE_MIN 자보다 짧으면 인용으로 보지 않는다."""
    q = _flat(quote)
    return len(q) >= QUOTE_MIN and q in _flat(text)


def set_review(r: DrillRound, no: int, rv: DrillReview, model: str = "") -> DrillAttempt:
    """되짚기 결과를 시도에 남긴다. 본문에 없는 인용은 버리고 수를 센다 (dropped).
    근거가 있어야 하는 판정(반영됨 · 과하게 풀림, 어긴 금지 줄)이 근거를 잃으면 '판정 못 함'(unsure)으로 바꾼다.
    AI가 빠뜨린 줄도 '판정 못 함'으로 남기고 층은 적은 칸으로 어림한다 (BOX_LAYER). 지어낸 사실 · 놓친 것은 인용이 본문에 있는 것만 남긴다."""
    a = find(r, no)
    lines = {x.no: x for x in author_lines(a.brief, facts_brief(r.facts))}
    got: dict[int, DrillVerdict] = {}
    dropped = 0
    for v in rv.lines:
        line = lines.get(v.no)
        if line is None or v.no in got:
            continue
        q = v.quote.strip() if quoted(v.quote, a.with_text) else ""
        bq = v.bare_quote.strip() if quoted(v.bare_quote, a.bare_text) else ""
        dropped += bool(v.quote.strip() and not q) + bool(v.bare_quote.strip() and not bq)
        need = v.result in ("applied", "overdone") or v.layer == "ban"
        result = "unsure" if need and not (q or bq) else v.result
        got[v.no] = DrillVerdict(no=v.no, box=line.box, text=line.text, layer=v.layer, result=result, quote=q, bare_quote=bq, in_bare=v.in_bare,
                                 same_as=v.same_as if v.same_as in lines and v.same_as < v.no else 0, why=v.why.strip()[:LINE_MAX])
    a.verdicts = [got.get(n) or DrillVerdict(no=n, box=x.box, text=x.text, layer=BOX_LAYER.get(x.box, "background"), why="AI가 이 줄을 판정하지 않았어요")
                  for n, x in lines.items()]
    invented = []
    for x in rv.invented:
        if quoted(x.quote, a.with_text if x.side == "with" else a.bare_text):
            invented.append(DrillInvented(side=x.side, quote=x.quote.strip(), what=x.what.strip()[:LINE_MAX]))
        else:
            dropped += 1
    gaps = []
    for g in rv.gaps:
        if g.what.strip() and quoted(g.quote, r.source):
            gaps.append(DrillGap(what=g.what.strip()[:LINE_MAX], quote=g.quote.strip()))
        else:
            dropped += 1
    a.invented, a.gaps, a.dropped = invented[:INVENTED_MAX], gaps[:GAPS_MAX], dropped
    a.review_model, a.reviewed_at = model, _now()
    return a


# ---------- 화면 ----------

def style_name(r: DrillRound) -> str:
    return library.load(r.style_id).name if r.style_id and library.exists(r.style_id) else ""


def stage(r: DrillRound) -> str:
    """판이 어디까지 왔나: facts(사실을 뽑기 전) · brief(지시를 적는 중) · written(두 판을 씀) · reviewed(되짚음)."""
    if r.attempts:
        return "reviewed" if r.attempts[-1].reviewed_at else "written"
    return "brief" if r.facts else "facts"


def view(r: DrillRound) -> dict:
    """화면에 보내는 판. 원문 대목은 두 판을 쓴 뒤에만 싣고, 앞부분(lead)은 싣지 않는다. 판마다 문단 지표(studio.measure)를 붙인다."""
    shown = bool(r.attempts)
    card = SceneCard(length=max(studio.LENGTH[0], min(studio.LENGTH[1], len(r.source))), style_id=r.style_id if style_name(r) else "")
    st = studio.style_of(card)
    m = lambda t: studio.measure(t, card, st)  # noqa: E731
    base = facts_brief(r.facts)
    out = r.model_dump(exclude={"source", "lead"})
    return {**out, "source": r.source if shown else "", "source_chars": len(r.source), "revealed": shown, "stage": stage(r),
            "style_name": style_name(r), "base": base.model_dump(), "lines": [x.model_dump() for x in author_lines(r.brief, base)],
            "method_lines": len(method_lines(r.brief)),
            "measures": {str(a.no): {"with": m(a.with_text), "bare": m(a.bare_text)} for a in r.attempts},
            "source_measure": m(r.source) if shown else None}


def summary(r: DrillRound) -> dict:
    a = r.attempts[-1] if r.attempts else None
    return {"id": r.id, "title": r.title, "stage": stage(r), "style_name": style_name(r), "lines": len(a.verdicts) if a else 0,
            "results": {k: sum(v.result == k for v in a.verdicts) for k in RESULTS} if a else {}, "created_at": r.created_at,
            "updated_at": r.updated_at}
