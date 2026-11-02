"""문단 연습장: 한 문단짜리 장면을 상황 카드(SceneCard)로 AI 에게 여러 안 쓰게 하거나 작가가 직접 써 보고, 문단 지표로 견준다.

작품(project.json)에는 넣지 않고 세션 파일 <CANON_HOME>/.studio/<id>.json 에 둔다 (CANON_STUDIO 로 경로 변경, 문체 라이브러리처럼 작품 밖).
문체는 문체 라이브러리 항목을 고르면 그 프로필을 프롬프트에 넣고, 고르지 않으면 기본 문체 규칙만 쓴다.
한 문단은 화 하나보다 훨씬 짧아 화 단위 지표(어휘 다양도 · 문체 거리 · 화당 상한)는 쓰지 않고, 개수로 센다(measure).
AI 호출은 pipeline.draft_paragraph (write 단계). 이 모듈은 LLM 을 부르지 않는다.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import library, metrics, store
from .schema import (ParagraphAnatomy, Project, ReaderCheck, SceneCard, SceneVariant, StudioCandidate, StudioPerson, StudioSession, StudioTry,
                     StyleProfile)

ID_RE = re.compile(r"^[0-9a-f]{8,32}$")
LENGTH = (100, 1200)  # 목표 글자 수 범위
LENGTH_SLACK = 0.35  # 목표 글자 수에서 이만큼 벗어나면 길이 확인이 걸린다
MAX_TRIES = 40  # 세션마다 남기는 시도. 저절로 지우지 않고, 차면 작가가 지울 시도를 고른다
DRAFTS = (1, 4)  # AI 에게 한 번에 받는 안 수 범위
TEXT_MAX = 4000  # 시도 하나 · 출발 글의 글자 수 상한 (문단 연습이라 길게 받지 않는다)
TITLE_MAX = 60
REF_MAX = 120  # 본보기 문단 출처 한 줄
CV_MIN_SENTENCES = 4  # 문장 길이 변화폭은 문장이 이만큼은 있어야 잰다
BEATS_MAX = 10  # 카드의 문장 차례 칸 수
VARIANTS = (2, 5)  # 상황 바꿔 보기에서 한 번에 받는 상황 수
LINE_MAX = 200  # 가릴 것 · 감각 전환 한 줄

# 문장 박자: id → (화면 이름, 프롬프트 지시). 순서가 화면 고르기 순서다
BEATS: dict[str, tuple[str, str]] = {
    "setup": ("깔기", "누가 어디서 무엇을 하는지 자리를 잡는다"),
    "trigger": ("계기", "자세 · 소리 · 움직임이 바뀌어 시선이나 주의가 열린다"),
    "focus": ("초점", "한 가지를 가까이 크게 보여 준다. 여럿을 늘어놓지 않는다"),
    "imagine": ("가정", "시점 인물이 사실이 아니라 '~면 ~할 것 같다' 같은 상상으로 넘어간다. 본 것을 다른 감각으로 옮겨도 된다"),
    "react": ("반응", "시점 인물의 몸이나 행동이 반응한다. 감정 이름은 쓰지 않는다"),
    "cut": ("끊기", "짧은 문장으로 끊고 넘긴다. 정리하거나 교훈을 말하지 않는다"),
    "line": ("대사", "한 인물의 짧은 대사 한마디"),
}

# 가정 문장 표지: 시점 인물이 사실에서 상상으로 넘어가는 말 ('가정 문장 하나' 연습). 대사 밖 서술에서만 센다
IMAGINE_RE = re.compile(r"것\s*같|듯(?:이|한|했|하|싶)|마치|느낌|모양이었|싶었|싶다|지도 몰|지도 모르|라면|다면")

# 감정 이름: 대사 밖 서술에 나오면 '감정 이름 없이' 연습에 걸린다. 쇠맛 패턴 '감정 이름 서술'보다 넓게 낱말만 본다
EMOTION_WORDS = ["슬픔", "슬펐다", "슬퍼졌다", "불안", "두려움", "두려웠다", "공포", "기쁨", "기뻤다", "설렘", "설렜다", "외로움", "외로웠다",
                 "분노", "화가 났다", "서러움", "서러웠다", "안도", "죄책감", "긴장감", "허탈", "절망", "행복했다", "그리움", "그리웠다"]


@dataclass(frozen=True)
class Drill:
    label: str
    rule: str  # 프롬프트에 넣는 지시
    check: Optional[Callable[[str, metrics.StyleMetrics, dict], tuple[bool, str]]] = None  # (지켰나, 까닭). 없으면 작가가 읽고 판단


def _narration(text: str) -> str:
    return metrics._QUOTE.sub(" ", text)


def _check_show(text: str, m: metrics.StyleMetrics, counts: dict) -> tuple[bool, str]:
    words = [w for w in EMOTION_WORDS if w in _narration(text)]
    named = counts.get("감정 이름 서술", 0)
    if not words and not named:
        return True, "서술에 감정 이름이 없어요"
    return False, f"서술에 감정 이름이 있어요: {', '.join(words) or '감정 이름 서술'}"


def _check_no_dialogue(text: str, m: metrics.StyleMetrics, counts: dict) -> tuple[bool, str]:
    return (True, "대사가 없어요") if m.dialogue_ratio == 0 else (False, f"대사가 {round(m.dialogue_ratio * 100)}% 있어요")


def _check_dialogue(text: str, m: metrics.StyleMetrics, counts: dict) -> tuple[bool, str]:
    pct = round(m.dialogue_ratio * 100)
    return (pct >= 50, f"대사가 {pct}%예요" + ("" if pct >= 50 else " (절반 넘게 바라요)"))


def _check_rhythm(text: str, m: metrics.StyleMetrics, counts: dict) -> tuple[bool, str]:
    if m.sentences < CV_MIN_SENTENCES:
        return False, f"문장이 {m.sentences}개라 리듬을 재기에 짧아요 ({CV_MIN_SENTENCES}개 넘게)"
    cv = round(m.sentence_len_cv, 2)
    return (cv >= 0.5, f"문장 길이 변화폭 {cv}" + ("" if cv >= 0.5 else " (0.5 넘게 바라요)"))


def _check_three(text: str, m: metrics.StyleMetrics, counts: dict) -> tuple[bool, str]:
    return (m.sentences <= 3, f"{m.sentences}문장이에요")


def _check_imagine(text: str, m: metrics.StyleMetrics, counts: dict) -> tuple[bool, str]:
    hits = IMAGINE_RE.findall(_narration(text))
    return (bool(hits), f"가정 표지 {len(hits)}개 ({', '.join(dict.fromkeys(hits))})" if hits else "'~것 같다' · '마치' · '~라면' 같은 가정 표지가 서술에 없어요")


def _check_less_ai(text: str, m: metrics.StyleMetrics, counts: dict) -> tuple[bool, str]:
    found = [f"{k} {v}회" for k, v in counts.items() if v] + m.cliche_hits
    return (not found, "쇠맛 패턴 · 상투 표현이 없어요" if not found else f"걸린 것: {', '.join(found)}")


# 연습 종류. 화면(static/studio.js)은 GET /api/studio 의 drills 로 받는다
DRILLS: dict[str, Drill] = {
    "show": Drill("감정 이름 없이", "서술에 감정 이름(슬픔, 불안, 설렘 같은 말)을 쓰지 않고 행동, 사물, 몸의 반응으로 보여 줍니다.", _check_show),
    "senses": Drill("소리 · 냄새 · 촉감으로", "보이는 것보다 소리, 냄새, 촉감 가운데 하나를 중심으로 장면을 세웁니다."),
    "no_dialogue": Drill("대사 없이", "따옴표 대사를 쓰지 않습니다. 말은 행동과 서술로만 전합니다.", _check_no_dialogue),
    "dialogue": Drill("대사로 끌고 가기", "대사가 장면을 끌고 갑니다. 서술은 대사 사이에 짧은 행동 한 줄씩만 둡니다.", _check_dialogue),
    "rhythm": Drill("긴 문장 · 짧은 문장 섞기", "아주 짧은 문장과 긴 문장을 섞어 리듬을 만듭니다. 길이가 비슷한 문장을 셋 넘게 잇지 않습니다.", _check_rhythm),
    "three": Drill("세 문장 안에", "세 문장 안에 끝냅니다. 목표 글자 수보다 이 제약이 먼저입니다.", _check_three),
    "less_ai": Drill("쇠맛 없이", "감정 이름, 정리하는 문장, 번역투, 셋씩 나열, 여운을 노린 짧은 끝 문장을 쓰지 않고 구체적인 행동과 사물로 씁니다.", _check_less_ai),
    "imagine": Drill("가정 문장 하나", "시점 인물이 본 것에서 '~면 ~할 것 같다' 같은 상상으로 넘어가는 문장을 하나 넣습니다. 상상은 사실로 확인해 주지 않습니다.", _check_imagine),
    "blocking": Drill("자리 · 자세 분명히", "인물마다 어디에 있고 어느 쪽을 보며 손에 무엇을 들었는지 그릴 수 있게 씁니다. 자리를 바꾸면 바꾸는 행동을 씁니다."),
}


def drills() -> list[dict]:
    return [{"id": k, "label": d.label, "rule": d.rule, "auto": d.check is not None} for k, d in DRILLS.items()]


def beats() -> list[dict]:
    return [{"id": k, "label": v[0], "rule": v[1]} for k, v in BEATS.items()]


# ---------- 저장 ----------

def root() -> Path:
    return Path(os.environ.get("CANON_STUDIO") or store.ROOT / ".studio")


def _path(sid: str) -> Path:
    if not ID_RE.match(sid):
        raise KeyError(f"문단 연습장에 없는 세션이에요: {sid}")
    return root() / f"{sid}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load(sid: str) -> StudioSession:
    path = _path(sid)
    if not path.exists():
        raise KeyError(f"문단 연습장에 없는 세션이에요: {sid}")
    return StudioSession.model_validate_json(path.read_text(encoding="utf-8"))


def save(s: StudioSession) -> StudioSession:
    s.created_at = s.created_at or _now()
    s.updated_at = _now()
    path = _path(s.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(s.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)
    return s


def sessions() -> list[StudioSession]:
    d = root()
    if not d.exists():
        return []
    out = []
    for f in d.glob("*.json"):
        try:
            out.append(StudioSession.model_validate_json(f.read_text(encoding="utf-8")))
        except ValueError:
            continue  # 깨진 파일은 목록에서 뺀다 (지우지 않는다)
    return sorted(out, key=lambda s: s.updated_at, reverse=True)


def clean_card(card: SceneCard) -> SceneCard:
    """앞뒤 공백을 떼고, 빈 인물 · 모르는 연습 · 범위 밖 길이를 고친다. 없는 문체 항목은 막는다."""
    c = card.model_copy(deep=True)
    for k in ("pov", "place", "time", "action", "aim", "extra", "style_id", "withhold", "sense"):
        setattr(c, k, getattr(c, k).strip())
    c.source = c.source.strip()[:TEXT_MAX]
    c.model = c.model.strip()[:TEXT_MAX]
    c.beats = [b for b in c.beats if b in BEATS][:BEATS_MAX]
    c.withhold = c.withhold.strip()[:LINE_MAX]
    c.sense = c.sense.strip()[:LINE_MAX]
    c.show_model = bool(c.show_model and c.model)
    c.ref = c.ref.strip()[:REF_MAX]
    c.people = [x.model_copy(update={"name": x.name.strip(), "note": x.note.strip(), "speech": x.speech.strip()})
                for x in c.people if x.name.strip() or x.note.strip() or x.speech.strip()]
    c.drills = [d for d in dict.fromkeys(c.drills) if d in DRILLS]
    c.length = max(LENGTH[0], min(LENGTH[1], int(c.length or 0) or 400))
    if c.style_id and not library.exists(c.style_id):
        raise ValueError("고른 문체를 문체 라이브러리에서 찾지 못했어요. 다른 문체를 고르세요")
    return c


def title_of(card: SceneCard) -> str:
    """제목이 비었을 때 카드로 짓는다: 무슨 일, 없으면 장소, 없으면 '새 연습'."""
    base = card.action or card.place or (card.source[:30] if card.source else "") or (card.model[:30] if card.model else "") or "새 연습"
    return base[:TITLE_MAX]


def create(card: SceneCard, title: str = "") -> StudioSession:
    c = clean_card(card)
    return save(StudioSession(id=uuid.uuid4().hex[:12], title=(title.strip() or title_of(c))[:TITLE_MAX], card=c))


def update(sid: str, card: SceneCard, title: str = "") -> StudioSession:
    """title 이 비었거나, 카드로 지은 제목을 그대로 보냈으면 새 카드로 다시 짓는다 (작가가 적은 제목만 남는다)."""
    s = load(sid)
    auto = s.title == title_of(s.card)[:TITLE_MAX]
    s.card = clean_card(card)
    title = title.strip()
    s.title = (title if title and not (auto and title == s.title) else title_of(s.card))[:TITLE_MAX]
    return save(s)


def delete(sid: str) -> None:
    path = _path(sid)
    if not path.exists():
        raise KeyError(f"문단 연습장에 없는 세션이에요: {sid}")
    path.unlink()


def duplicate(sid: str) -> StudioSession:
    """카드만 복사한 새 세션 (같은 상황을 한 칸만 바꿔 다시 써 볼 때). 시도는 옮기지 않는다."""
    s = load(sid)
    return save(StudioSession(id=uuid.uuid4().hex[:12], title=f"{s.title} 사본"[:TITLE_MAX], card=s.card.model_copy(deep=True)))


# ---------- 시도 ----------

def _next_no(s: StudioSession) -> int:
    return max((t.no for t in s.tries), default=0) + 1


def room(s: StudioSession, more: int = 1) -> None:
    if len(s.tries) + more > MAX_TRIES:
        raise ValueError(f"시도는 세션마다 {MAX_TRIES}개까지 남겨요. 지울 시도를 고르거나 세션을 복제해 새로 시작하세요")


def find(s: StudioSession, no: int) -> StudioTry:
    t = next((x for x in s.tries if x.no == no), None)
    if t is None:
        raise KeyError(f"{no}번 시도가 없어요")
    return t


def add_ai(s: StudioSession, cands: list[StudioCandidate], model: str = "") -> list[StudioTry]:
    room(s, len(cands))
    now, out = _now(), []
    for c in cands:
        t = StudioTry(no=_next_no(s), by="ai", text=c.text, note=c.note.strip(), model=model, at=now)
        s.tries.append(t)
        out.append(t)
    return out


def _text(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("글을 적으세요")
    if len(text) > TEXT_MAX:
        raise ValueError(f"문단 연습은 {TEXT_MAX:,}자까지 받아요")
    return text


def add_author(s: StudioSession, text: str, base: int = 0) -> StudioTry:
    """작가가 쓴 글. base 를 주면 그 시도를 고쳐 쓴 것으로 남긴다 (같은 글이면 막는다)."""
    text = _text(text)
    if base:
        if find(s, base).text.strip() == text:
            raise ValueError("고친 곳이 없어요")
    room(s)
    t = StudioTry(no=_next_no(s), by="author", text=text, base=base, at=_now())
    s.tries.append(t)
    return t


def edit(s: StudioSession, no: int, text: Optional[str] = None, star: Optional[bool] = None) -> StudioTry:
    """작가 글만 고칠 수 있다. AI 안은 고쳐 쓰기(add_author 의 base)로 새 시도를 만든다. 고르기(star)는 모두 된다."""
    t = find(s, no)
    if text is not None:
        if t.by != "author":
            raise ValueError("AI 안은 고치지 않고 고쳐 쓴 글을 새 시도로 남겨요")
        new = _text(text)
        if new != t.text:
            t.reader = None  # 독자 질문은 고치기 전 글을 본 것
        t.text = new
    if star is not None:
        t.star = star
    return t


def remove(s: StudioSession, no: int) -> None:
    find(s, no)
    s.tries = [t for t in s.tries if t.no != no]
    for t in s.tries:  # 지운 시도를 고쳐 쓴 글은 처음부터 쓴 글로 본다
        if t.base == no:
            t.base = 0


# ---------- 문체와 프롬프트 재료 ----------

def style_of(card: SceneCard) -> Optional[StyleProfile]:
    if not card.style_id or not library.exists(card.style_id):
        return None
    return library.load(card.style_id).profile


def style_name(card: SceneCard) -> str:
    if not card.style_id:
        return ""
    return library.load(card.style_id).name if library.exists(card.style_id) else ""


def world(card: SceneCard) -> Project:
    """프롬프트 함수(prompts.style_block 등)가 읽는 작품 모양. 문체만 채운 저장하지 않는 사본이다."""
    st = style_of(card)
    return Project(style=st.model_copy(deep=True)) if st else Project()


def can_draft(card: SceneCard) -> None:
    if not (card.action or card.source or card.place or card.people):
        raise ValueError("무슨 일이 일어나는지 적거나, 인물 · 장소를 적거나, 고쳐 쓸 출발 글을 넣으세요")


# ---------- 문단 지표 ----------

def measure(text: str, card: SceneCard, style: Optional[StyleProfile] = None) -> dict:
    """문단 하나의 지표. 비율 대신 개수로 센다. 화면에 그대로 보낸다 (저장하지 않음, 같은 글이면 같은 값)."""
    banned = [x for x in (style.banned_phrases if style else []) if x.strip()]
    m = metrics.measure(text, banned)
    counts = metrics.pattern_counts(text)
    hits = [{"kind": sp.kind, "name": sp.name, "quote": sp.quote} for sp in metrics.pattern_spans(text, banned)]
    marks = [{"text": mk.text, "count": metrics.marker_count(text, mk.text)} for mk in (style.markers if style else []) if mk.text.strip()]
    checks = []
    if "three" not in card.drills:
        lo, hi = round(card.length * (1 - LENGTH_SLACK)), round(card.length * (1 + LENGTH_SLACK))
        ok = lo <= m.chars <= hi
        checks.append({"id": "length", "label": "길이", "ok": ok,
                       "why": f"{m.chars:,}자" + ("" if ok else f" (목표 {card.length:,}자, {lo:,}~{hi:,}자를 바라요)")})
    for k in card.drills:
        d = DRILLS[k]
        if d.check is None:
            checks.append({"id": k, "label": d.label, "ok": None, "why": "읽고 판단해요"})
        else:
            ok, why = d.check(text, m, counts)
            checks.append({"id": k, "label": d.label, "ok": ok, "why": why})
    copied = metrics.copied_sentences(text, [card.model]) if card.model and text.strip() != card.model.strip() else []
    return {
        "copied": copied,
        "chars": m.chars, "sentences": m.sentences, "sentence_len_mean": round(m.sentence_len_mean, 1),
        "sentence_len_cv": round(m.sentence_len_cv, 2) if m.sentences >= CV_MIN_SENTENCES else None,
        "dialogue_pct": round(m.dialogue_ratio * 100), "hits": hits, "markers": marks, "checks": checks,
    }


def view(s: StudioSession) -> dict:
    """화면에 보내는 세션: 시도마다 지표, 문체 이름, 뜯어보기가 지금 본보기 것인지."""
    st = style_of(s.card)
    return {**s.model_dump(), "style_name": style_name(s.card), "anatomy_stale": bool(s.anatomy) and s.anatomy_of != model_basis(s.card),
            "measures": {str(t.no): measure(t.text, s.card, st) for t in s.tries},
            "model_measure": measure(s.card.model, s.card, st) if s.card.model else None}


def summary(s: StudioSession) -> dict:
    return {"id": s.id, "title": s.title, "tries": len(s.tries), "authored": sum(t.by == "author" for t in s.tries),
            "starred": sum(t.star for t in s.tries), "style_name": style_name(s.card), "drills": s.card.drills,
            "created_at": s.created_at, "updated_at": s.updated_at}


# ---------- 구조: 본보기 뜯어보기 · 상황 바꿔 보기 · 독자 질문 ----------

def model_basis(card: SceneCard) -> str:
    return hashlib.sha1(card.model.strip().encode()).hexdigest()[:12] if card.model.strip() else ""


def _flat(t: str) -> str:
    return re.sub(r"\s+", "", t)


def clean_anatomy(a: ParagraphAnatomy, model: str) -> ParagraphAnatomy:
    """본보기에 글자 그대로(공백 빼고) 있는 문장 인용만 남기고 본보기 차례로 놓는다. 한 줄 칸은 다듬는다.
    남는 줄이 없으면 막는다 (AI 가 문장을 지어냈다)."""
    flat = _flat(model)
    seen, rows = set(), []
    for x in a.lines:
        q = _flat(x.quote)
        at = flat.find(q) if len(q) >= 2 else -1
        if at < 0 or at in seen or x.beat not in BEATS:
            continue
        seen.add(at)
        rows.append((at, x.model_copy(update={"quote": x.quote.strip(), "note": x.note.strip()})))
    if not rows:
        raise ValueError("AI가 본보기에 없는 문장을 적었어요. 다시 해 보세요")
    return ParagraphAnatomy(lines=[x for _, x in sorted(rows, key=lambda r: r[0])][:BEATS_MAX], withhold=a.withhold.strip()[:LINE_MAX],
                            sense=a.sense.strip()[:LINE_MAX], reader=a.reader.strip()[:LINE_MAX])


def set_anatomy(s: StudioSession, a: ParagraphAnatomy) -> None:
    s.anatomy = clean_anatomy(a, s.card.model)
    s.anatomy_of = model_basis(s.card)


def apply_anatomy(s: StudioSession) -> None:
    """뜯어본 박자 차례 · 가릴 것 · 감각 전환을 카드에 적용한다 (작가가 누른다). 빈 칸은 지금 값을 둔다."""
    a = s.anatomy
    if not a:
        raise ValueError("먼저 본보기를 뜯어보세요")
    s.card.beats = [x.beat for x in a.lines][:BEATS_MAX]
    s.card.withhold = a.withhold or s.card.withhold
    s.card.sense = a.sense or s.card.sense


def can_vary(card: SceneCard) -> None:
    if not (card.beats or card.model or card.action):
        raise ValueError("문장 차례를 고르거나, 본보기를 넣거나, 무슨 일을 적으세요")


def clean_variants(vs: list[SceneVariant], card: SceneCard) -> list[SceneVariant]:
    """빈 상황 · 겹치는 상황 · 지금 카드와 같은 장소+일을 뺀다. 시점 인물이 인물 목록에 없으면 비운다."""
    out, seen = [], {(card.place.strip(), card.action.strip())}
    for v in vs:
        v = v.model_copy(update={k: getattr(v, k).strip() for k in ("place", "time", "action", "pov", "why")})
        v.people = [p.model_copy(update={"name": p.name.strip(), "note": p.note.strip()}) for p in v.people if p.name.strip()][:3]
        key = (v.place, v.action)
        if not v.action or key in seen:
            continue
        seen.add(key)
        if v.pov not in [p.name for p in v.people]:
            v.pov = ""
        out.append(v)
    if not out:
        raise ValueError("AI가 쓸 만한 상황을 내지 않았어요. 다시 해 보세요")
    return out[:VARIANTS[1]]


def from_variant(sid: str, i: int) -> StudioSession:
    """고른 상황으로 새 세션을 만든다. 구조(문장 차례 · 가릴 것 · 감각 전환) · 연습 · 문체 · 본보기는 그대로, 상황 칸과 인물만 바꾼다.
    출발 글은 옛 상황 글이라 비운다. 원래 세션은 그대로 둔다."""
    s = load(sid)
    if not 0 <= i < len(s.variants):
        raise KeyError(f"{i + 1}번 상황이 없어요")
    v = s.variants[i]
    c = s.card.model_copy(deep=True, update={"place": v.place, "time": v.time, "action": v.action, "pov": v.pov, "aim": "", "source": "",
                                             "people": [StudioPerson(name=p.name, note=p.note) for p in v.people]})
    out = StudioSession(id=uuid.uuid4().hex[:12], title=(v.action or title_of(c))[:TITLE_MAX], card=clean_card(c))
    if s.anatomy and s.anatomy_of == model_basis(c):
        out.anatomy, out.anatomy_of = s.anatomy.model_copy(deep=True), s.anatomy_of
    return save(out)


def set_reader(s: StudioSession, no: int, r: ReaderCheck) -> StudioTry:
    """독자 질문 결과를 시도에 남긴다. '적혀 있음'인데 인용이 본문에 없으면 인용을 비운다 (지어낸 인용을 보이지 않게)."""
    t = find(s, no)
    flat = _flat(t.text)
    gaps = []
    for g in r.gaps:
        g = g.model_copy(update={"imagined": g.imagined.strip(), "quote": g.quote.strip()})
        if not g.imagined:
            continue
        if not g.written or (g.quote and _flat(g.quote) not in flat):
            g.quote = ""
        gaps.append(g)
    t.reader = ReaderCheck(gaps=gaps[:6])
    return t
