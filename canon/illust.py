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

from . import cast, elements, findings, metrics
from .context import grams
from .schema import CharacterState, CharacterVisual, IllustCharacter, IllustCharPrompt, IllustDraft, Illustration, Project

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
_HANGUL = re.compile(r"[ㄱ-ㆎ가-힣\u3040-\u30ff\u3400-\u9fff]")  # 한글 · 가나 · 한자 (AI 가 fluorescent照明 처럼 섞어 씀)
_SUBJECT = {"girl", "boy", "other"}

# 나이대 태그. 이미 있으면 프로그램이 붙이지 않는다
_AGE_TAG = re.compile(r"(^|[\s:])(child|loli|shota|teen|teenage|adult|mature (female|male)|old (woman|man)|elderly|aged (up|down)|young (adult|female|male|woman|man)|milf)\b")
# 어려 보이게 그려지는 나이 태그 (WAI-illustrious 실측 2026-11-11: young adult 를 넣은 남자는 10대로 그려짐)
YOUNG_TAGS = {"young adult", "young female", "young male", "young woman", "young man"}
YOUNG_NOTE = "{name}의 저장된 외형 태그 {tag}은(는) 그림이 어려 보이게 해요. 20대 초는 adult 를 권해요"
# AI 원안 검사: 칸 이름으로 시작하는 원소는 여러 칸을 한 원소에 붙여 쓴 깨진 출력이다
_FIELD_LEAK = re.compile(r"^(lighting|mood|setting|composition|negative|rating|expression|outfit|look|position)\s")
LONG_TAG = 5  # 낱말이 이만큼 넘으면 태그 하나가 아니다


def model_info(mid: str) -> tuple[str, str, int, bool]:
    return MODELS.get(mid) or MODELS[DEFAULT_MODEL]


def clean(tags: list[str]) -> list[str]:
    """태그 정리: 쉼표로 나누고, 소문자, 낱말 사이 밑줄은 띄어쓰기, 한글 · 가나 · 한자가 든 태그와 겹치는 것은 뺀다.
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


def age_tag(age: str, subject: str) -> str:
    """나이 칸으로 붙일 나이대 태그 (NovelAI 문법). 나이를 모르거나 미성년(cast.is_minor_age)이면 빈 글.
    19~25 adult, 26~39 0.6::mature female::, 40~59 mature female, 60 넘으면 old woman (남성은 male · man).
    mature female 을 그대로 넣으면 30대로 그려지고 체형도 커져 20대 후반은 가중치를 낮춘다 (WAI-illustrious 실측 2026-11-11)."""
    if cast.is_minor_age(age):
        return ""
    m = re.search(r"\d+", age or "")
    if not m:
        return ""
    n = int(m.group())
    sex = {"girl": ("female", "woman"), "boy": ("male", "man")}.get(subject)
    if n <= 25 or not sex:
        return "adult"
    if n < 40:
        return f"0.6::mature {sex[0]}::"
    return f"mature {sex[0]}" if n < 60 else f"old {sex[1]}"


def check_draft(d: IllustDraft) -> list[str]:
    """AI 원안의 깨진 태그를 뺀다: 칸 이름으로 시작하는 원소(lighting fluorescent light ...), 낱말이 LONG_TAG 개 넘는 원소,
    left · center · right 가 아닌 position. d 를 고치고 알릴 것을 돌려준다."""
    dropped: list[str] = []

    def keep(tags: list[str]) -> list[str]:
        out = []
        for t in tags:
            low = re.sub(r"^(source|target|mutual)#", "", str(t).strip().lower())
            if _FIELD_LEAK.match(low) or len(low.split()) > LONG_TAG:
                dropped.append(str(t))
            else:
                out.append(t)
        return out

    for f in ("setting", "lighting", "composition", "mood", "negative"):
        setattr(d, f, keep(getattr(d, f)))
    bad_pos = 0
    for c in d.characters:
        for f in ("look", "outfit", "expression", "action"):
            setattr(c, f, keep(getattr(c, f)))
        if c.position.strip().lower() not in ("", *POSITIONS):
            c.position, bad_pos = "", bad_pos + 1
    notes = []
    if dropped:
        shown = ", ".join(t[:40] for t in dropped[:3])
        notes.append(f"AI 원안에서 형식이 깨진 태그 {len(dropped)}개를 뺐어요: {shown}")
    if bad_pos:
        notes.append(f"AI가 적은 인물 자리 {bad_pos}개가 왼쪽 · 가운데 · 오른쪽이 아니라 비웠어요")
    return notes


def join(tags: list[str]) -> str:
    return ", ".join(t for t in tags if t)


def _char_tags(p: Project, ch: IllustCharacter, missing: list[str], notes: list[str]) -> tuple[str, list[str], list[str]]:
    """인물 하나의 (subject, 태그, 부정 태그). 저장된 외형이 있으면 그것을, 없으면 AI 태그를 쓴다.
    나이 칸이 있는 인물은 외형에 나이대 태그가 없으면 age_tag 를 붙인다. AI 가 적은 young adult 같은 태그는 그때 뺀다.
    작가가 저장한 외형은 바꾸지 않고, 어려 보이게 하는 태그가 있으면 notes 에 알린다."""
    v: CharacterVisual | None = p.visual(ch.id) if ch.id else None
    c = next((c for c in p.characters if c.id == ch.id), None) if ch.id else None
    subject = subject_of(p, ch.id) if c else ch.subject
    saved = bool(v and v.look)
    if saved:
        look = clean(v.look)
        young = [t for t in look if t in YOUNG_TAGS]
        if young:
            notes.append(YOUNG_NOTE.format(name=c.name if c else ch.id, tag=young[0]))
    else:
        look = clean(ch.look)
        if c and ch.look:
            missing.append(ch.id)
    add = age_tag(c.age, subject) if c else ""
    if add and not saved:
        look = [t for t in look if t not in YOUNG_TAGS]
    if add and not any(_AGE_TAG.search(t) for t in look):
        look = look + [add]
    outfit = ch.outfit or (v.outfit if v else [])
    tags = look + clean(outfit) + clean(ch.expression) + clean(ch.action)
    return subject, tags, clean(v.negative) if v else []


def states_at(p: Project, n: int) -> tuple[list[CharacterState], str]:
    """n화 삽화에 넣을 인물 상태(차림 · 위치)와 알릴 것. n화가 시작할 때, 곧 n-1화를 반영한 뒤의 상태를 쓴다.
    반영이 n-1화까지면 지금 상태, 더 뒤까지 반영했으면 n-1화 스냅샷, 지워졌으면 n-1화 이하 가장 가까운 스냅샷(그 화를 알린다).
    장편은 스냅샷을 0화 · 아크 끝 · 최근 20화만 남긴다(pipeline.prune_snapshots). 맞는 스냅샷이 없으면 지금 상태를 쓰고 알린다."""
    last = max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)
    if last <= n - 1:
        return p.states, ""
    snaps = [s for s in p.snapshots if s.episode <= n - 1]
    if snaps:
        snap = max(snaps, key=lambda s: s.episode)
        old = f"{n - 1}화 스냅샷이 지워져 {snap.episode}화 반영 뒤 차림 · 위치를 썼어요" if snap.episode < n - 1 else ""
        return snap.states, old
    return p.states, f"{n}화보다 뒤 상태({last}화 반영 뒤)의 차림 · 위치를 썼어요"


QUOTE_MIN_GRAMS = 8  # 이보다 글 조각(한글 3글자)이 적은 짧은 인용은 비슷한 문장으로 바꾸지 않고, 본문에 그대로 있을 때만 둔다
QUOTE_FIXED = "AI가 옮긴 장면 인용이 본문과 조금 달라 본문 원문으로 바꿨어요"
QUOTE_DROPPED = "AI가 옮긴 장면 인용을 본문에서 찾지 못해 비웠어요"


def match_quote(text: str, quote: str) -> tuple[str, str]:
    """AI 가 옮긴 장면 인용(IllustDraft.quote)을 본문 범위 text 와 대조한다. (맞춘 인용, 알릴 것).
    그대로 있으면 둔다(띄어쓰기 · 줄바꿈 차이는 원문으로). 없으면 연속 1~3문장 창과 견준다:
    따옴표 · 문장 부호만 다른 창(findings.in_text), 다음은 같은 문장으로 보는 창(findings.same_quote) 가운데 길이가 가장 가까운 것.
    맞는 창이 없거나 짧은 인용이면 비운다."""
    q = quote.strip()
    if not q:
        return "", ""
    hit = elements.find(text, q)
    if hit:
        return text[hit[0]:hit[1]], ""
    sents = metrics.sentences(text)
    windows = [" ".join(sents[i:i + k]) for k in (1, 2, 3) for i in range(len(sents) - k + 1)]
    pick = min((w for w in windows if findings.in_text(w, q)), key=len, default="")
    size = len(grams(q))
    if not pick and size >= QUOTE_MIN_GRAMS:
        near = [w for w in windows if 2 * len(grams(w)) >= size and findings.same_quote(w, q)]
        pick = min(near, key=lambda w: abs(len(w) - len(q)), default="")
    if not pick:
        return "", QUOTE_DROPPED
    span = elements.find(text, pick)
    return (text[span[0]:span[1]] if span else pick), QUOTE_FIXED


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
    built = [(c, *_char_tags(p, c, missing, notes)) for c in chars]
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
    ill.notes = list(ill.draft_notes) + notes
    return ill


def models() -> list[dict]:
    return [{"id": k, "label": v[0], "quality": v[1], "max_chars": v[2], "caption": v[3]} for k, v in MODELS.items()]
