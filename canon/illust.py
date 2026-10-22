"""삽화 프롬프트: AI 가 본문 장면을 태그로 옮긴 원안(IllustDraft)을 NovelAI 에 붙여 넣을 프롬프트로 조립한다.

LLM 을 부르지 않는다. 인물 외형은 작가가 저장한 외형 태그(Project.visuals)를 매번 그대로 넣어 화가 바뀌어도
같은 얼굴이 나오게 하고, 인물 수 태그 · 등급 · 품질 태그는 규칙으로 붙인다.

NovelAI 규칙 (docs.novelai.net, 2026-10 기준)
- V4 이상은 기본 프롬프트(장면, 화풍) + 인물 프롬프트(인물마다 한 칸)로 나눈다. 인물 수(2girls, 1boy)는 기본 프롬프트에,
  인물 칸에는 숫자 없이 girl / boy / other 만 쓴다. 인물끼리 주고받는 행동은 source#, target#, mutual# 을 붙인다.
- 인물 칸을 쓰지 않을 때는 기본 프롬프트와 인물을 | 로 나눠 한 칸에 넣을 수 있다 (V4 이상).
- 태그 순서: 인물 수 → 인물 → 작품 → 나머지. 품질 태그는 'Add Quality Tags' 를 켜면 NovelAI 가 끝에 붙인다.
- 부정 프롬프트(Undesired Content)는 UC 프리셋이 기본으로 켜져 있다.
"""
from __future__ import annotations

import re

from .schema import CharacterVisual, IllustCharacter, IllustCharPrompt, IllustDraft, Illustration, Project

# id → (이름, 'Add Quality Tags' 가 붙이는 태그, 인물 칸 최대 수, 영어 문장 설명을 넣을지)
MODELS: dict[str, tuple[str, str, int, bool]] = {
    "v5-full": ("NAI Diffusion V5 Full", "very aesthetic, masterpiece, no text", 22, True),
    "v5-curated": ("NAI Diffusion V5 Curated", "very aesthetic, masterpiece, no text", 22, True),
    "v4.5-full": ("NAI Diffusion V4.5 Full", "location, very aesthetic, masterpiece, no text", 6, False),
    "v4.5-curated": ("NAI Diffusion V4.5 Curated", "location, masterpiece, no text", 6, False),
    "v4-full": ("NAI Diffusion V4 Full", "no text, best quality, very aesthetic, absurdres", 6, False),
    "v4-curated": ("NAI Diffusion V4 Curated", "amazing quality, very aesthetic, absurdres", 6, False),
    "v3": ("NAI Diffusion Anime V3", "best quality, amazing quality, very aesthetic, absurdres", 0, False),
}
DEFAULT_MODEL = "v4.5-full"

# UC 프리셋을 끈 사람을 위한 짧은 기본 부정 태그
BASIC_NEGATIVE = ["lowres", "artistic error", "worst quality", "bad quality", "jpeg artifacts", "bad anatomy", "bad hands",
                  "extra digits", "fewer digits", "text", "watermark", "signature"]

RATINGS = ("general", "sensitive", "questionable", "explicit")
SAFE_RATINGS = ("general", "sensitive")  # 성인물이 아닌 작품에서 쓸 수 있는 등급
POSITIONS = {"left": "왼쪽", "center": "가운데", "right": "오른쪽"}
KEEP = 20  # 화마다 남기는 삽화 프롬프트 수

_COUNT = re.compile(r"^(\d+\+?|multiple|no)\s*(girls?|boys?|others?|humans)$")
_HANGUL = re.compile(r"[ㄱ-ㆎ가-힣]")
_SUBJECT = {"girl", "boy", "other"}


def model_info(mid: str) -> tuple[str, str, int, bool]:
    return MODELS.get(mid) or MODELS[DEFAULT_MODEL]


def clean(tags: list[str]) -> list[str]:
    """태그 정리: 쉼표로 나누고, 소문자, 낱말 사이 밑줄은 띄어쓰기, 한글 태그와 겹치는 것은 뺀다.
    인물 수와 등급 태그는 프로그램이 붙이므로 뺀다. 가중치 문법(1.2::tag ::)은 그대로 둔다."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        for t in str(raw).split(","):
            t = t.strip().strip(".")
            if "::" not in t:
                t = t.lower()
                t = re.sub(r"(?<=[a-z0-9])_(?=[a-z0-9(])", " ", t)
                t = re.sub(r"\s+", " ", t)
            if not t or _HANGUL.search(t) or _COUNT.match(t) or t.startswith("rating:") or t in _SUBJECT:
                continue
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


def subject_of(p: Project, cid: str) -> str:
    """저장된 외형의 subject, 없으면 성별로 정한다."""
    v = p.visual(cid)
    if v and v.subject:
        return v.subject
    c = next((c for c in p.characters if c.id == cid), None)
    g = (c.gender if c else "").strip()
    if g.startswith("여") or g.lower() in ("f", "female", "woman", "girl"):
        return "girl"
    if g.startswith("남") or g.lower() in ("m", "male", "man", "boy"):
        return "boy"
    return "other"


def counts(subjects: list[str]) -> list[str]:
    """인물 수 태그 (1girl, 2boys, no humans)."""
    if not subjects:
        return ["no humans"]
    out = []
    for s in ("girl", "boy", "other"):
        k = subjects.count(s)
        if k:
            out.append(f"{k if k < 6 else '6+'}{s}{'s' if k > 1 else ''}")
    return out


def rating_for(p: Project, rating: str) -> str:
    r = rating if rating in RATINGS else "general"
    if not p.meta.adult and r not in SAFE_RATINGS:
        return "sensitive"
    return r


def join(tags: list[str]) -> str:
    return ", ".join(t for t in tags if t)


def _char_tags(p: Project, ch: IllustCharacter, missing: list[str]) -> tuple[str, list[str], list[str]]:
    """인물 하나의 (subject, 태그, 부정 태그). 저장된 외형이 있으면 그것을, 없으면 AI 태그를 쓴다."""
    v: CharacterVisual | None = p.visual(ch.id) if ch.id else None
    known = ch.id and any(c.id == ch.id for c in p.characters)
    subject = subject_of(p, ch.id) if known else ch.subject
    if v and v.look:
        look = v.look
    else:
        look = ch.look
        if known and ch.look:
            missing.append(ch.id)
    outfit = ch.outfit or (v.outfit if v else [])
    tags = clean(look) + clean(outfit) + clean(ch.expression) + clean(ch.action)
    return subject, tags, clean(v.negative) if v else []


def assemble(p: Project, ill: Illustration, model: str | None = None) -> Illustration:
    """draft 와 지금 저장된 외형 태그 · 설정으로 프롬프트를 (다시) 조립한다. ill 을 고쳐 돌려준다."""
    mid = model if model in MODELS else (ill.model if ill.model in MODELS else (p.illust.model if p.illust.model in MODELS else DEFAULT_MODEL))
    name_, quality, max_chars, caption_ok = MODELS[mid]
    d: IllustDraft = ill.draft
    s = p.illust
    notes: list[str] = []
    missing: list[str] = []
    names = {c.id: c.name for c in p.characters}

    chars = [c for c in d.characters if c.id or c.subject]
    built = [(c, *_char_tags(p, c, missing)) for c in chars]
    rating = rating_for(p, d.rating)
    if rating != d.rating:
        notes.append(f"성인물이 아닌 작품이라 등급을 {d.rating} 에서 {rating} 로 낮췄어요")

    head = counts([b[1] for b in built])
    scene = clean(s.style) + clean(d.setting) + clean(d.composition) + clean(d.lighting) + clean(d.mood)
    tail = [f"rating:{rating}"] + (["nsfw"] if rating == "explicit" else [])
    if s.quality:
        tail += [t.strip() for t in quality.split(",")]
    caption = d.caption.strip().rstrip(".") if caption_ok and d.caption.strip() else ""

    multi = max_chars > 0
    if multi and len(built) > max_chars:
        notes.append(f"{name_} 는 인물 칸이 {max_chars}개까지라 뒤의 {len(built) - max_chars}명은 인물 수에만 넣었어요")
    cps: list[IllustCharPrompt] = []
    if multi:
        for c, subject, tags, neg in built[:max_chars]:
            cps.append(IllustCharPrompt(id=c.id, name=names.get(c.id, ""), prompt=join([subject] + tags), negative=join(neg),
                                        position=POSITIONS.get(c.position.strip().lower(), "")))
        base = join(head + scene + ([caption] if caption else []) + tail)
        combined = " | ".join([base] + [cp.prompt for cp in cps])
    else:  # V3: 인물 칸이 없어 한 줄에 모두 넣는다. 인물이 둘 이상이면 특징이 섞이기 쉽다
        flat = [t for _, _, tags, _ in built for t in tags]
        base = join(head + flat + scene + tail)
        combined = base
        if len(built) > 1:
            notes.append("V3 는 인물을 나눠 적을 수 없어 외형이 섞일 수 있어요. V4 이상을 권해요")

    neg = clean(BASIC_NEGATIVE if s.basic_negative else []) + clean(s.negative) + clean(d.negative)
    if rating in SAFE_RATINGS:
        neg = ["nsfw"] + [t for t in neg if t != "nsfw"]
    if not multi:
        neg += [t for _, _, _, cn in built for t in cn if t not in neg]

    ill.model, ill.base, ill.characters, ill.negative, ill.combined = mid, base, cps, join(neg), combined
    ill.rating, ill.missing_look = rating, sorted(set(missing), key=missing.index)
    ill.notes = notes
    return ill


def models() -> list[dict]:
    return [{"id": k, "label": v[0], "quality": v[1], "max_chars": v[2], "caption": v[3]} for k, v in MODELS.items()]
