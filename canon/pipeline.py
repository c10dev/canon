"""생성 파이프라인. 각 단계는 Project 를 받아 제안을 만들고, 반영은 호출자가 승인 후 한다."""
from __future__ import annotations

from . import dynamics, elements, illust, metrics, naming, prompts, renumber, setupchat, storylines
from .judge import Judge, Question
from .llm import LLM, dump
from . import charlog, features, findings, foreshadows, statwin, timeline
from .schema import (
    Act,
    ArcEdit,
    ArcPlan,
    ClaimSet,
    ArcProposal,
    ArcUndo,
    Character,
    CharacterState,
    CharacterVisual,
    ChatMessage,
    ChatScope,
    CheckRound,
    CheckSource,
    ConsistencyReport,
    SceneCheck,
    Conversion,
    ElementImpact,
    Episode,
    EpisodeDraft,
    EpisodePlot,
    ForeshadowDue,
    HookReport,
    IllustDraft,
    Illustration,
    ImpactReport,
    LookSuggestion,
    MapSpec,
    MapSuggestion,
    BodySuggestion,
    StatInitSuggestion,
    StatWindowSuggestion,
    PlaceSort,
    VoiceSuggestion,
    NameOptions,
    OpeningPlots,
    Part,
    PassageRevision,
    PlotBatch,
    PlotRevision,
    PlotUndo,
    Project,
    RebuildEpisode,
    Recap,
    Rework,
    Selection,
    SerialConversion,
    SerialRebuild,
    SeriesPlan,
    SetupRevision,
    SetupSuggestion,
    ShortArchive,
    StateDelta,
    StoryArc,
    StoryEvent,
    Storyline,
    StoryTime,
    StorylineProposal,
    EditPair,
    StyleDevice,
    StyleLearning,
    StyleRevision,
    StyleExample,
    StyleSample,
    StyleMarker,
    StyleProfile,
    StyleRuleSuggestion,
    RewriteRequest,
    TextEdit,
    TextVersion,
)


# ---------- 1. 설정 도우미 ----------

def suggest_setup(llm: LLM, p: Project) -> SetupSuggestion:
    s = llm.json(prompts.SYSTEM_PLANNER, prompts.setup_prompt(p), SetupSuggestion)
    for c in s.characters:  # 서술 말투는 작가가 정하거나 서술 말투 제안으로만 채운다
        c.narration_voice = ""
    return s


def revise_setup(llm: LLM, p: Project, message: str, mode: str = "") -> SetupRevision:
    """설정 도우미 대화: 작가의 말로 설정 변경안이나 방향 여러 안(mode 'options')을 만든다. 저장하지 않는다.
    정리 · 적용 · 적용 취소는 canon/setupchat.py."""
    if not message.strip():
        raise ValueError("바라는 것을 적어 주세요")
    rev = llm.json(prompts.SYSTEM_SETUP_CHAT, prompts.setup_chat_prompt(p, message, mode), SetupRevision,
                   hint={"message": message, "mode": mode,
                         "project": p.model_dump(include={"meta", "world", "characters", "relationships"})})
    return setupchat.clean(p, rev, mode)


def name_candidates(p: Project, character: str = "", place_kind: str = "", n: int = 8,
                    style: str | None = None) -> list[naming.Candidate]:
    """코드만으로 뽑는 후보 (LLM 호출 없음). character 는 인물 id, 비우면 지명."""
    if character:
        c = next((x for x in p.characters if x.id == character), None)
        if c is None:
            raise KeyError(f"없는 인물이에요: {character}")
        return naming.character_candidates(p, c, n, style)
    return naming.location_candidates(p, n, place_kind, style)


def suggest_names(llm: LLM, p: Project, character: str = "", place_kind: str = "", n: int = 5,
                  style: str | None = None) -> tuple[list[naming.Candidate], NameOptions]:
    """코드가 후보를 넓게 뽑고, AI 가 대상에 맞는 것을 골라 이유를 붙인다. 반영은 작가가 한다."""
    cands = name_candidates(p, character, place_kind, n * 3, style)
    if character:
        c = next(x for x in p.characters if x.id == character)
        target = "인물 " + dump(c.model_dump(include={"id", "role", "age", "gender", "personality", "background", "goal", "wound"}))
    else:
        target = f"장소 ({place_kind or '종류 자유'}). 이야기에서 쓸 만한 곳으로."
    opts = llm.json(prompts.SYSTEM_NAMER, prompts.naming_prompt(p, target, cands, n), NameOptions,
                    hint={"candidates": [x.name for x in cands], "n": n})
    return cands, opts


def require_previous(p: Project, n: int) -> None:
    """이전 화가 모두 반영(finalized)돼야 n화를 쓰거나 반영한다. 인물 상태가 화 순서대로 쌓이게 하는 규칙이다."""
    unfinished = [e.plot.number for e in p.episodes if e.plot.number < n and e.status != "finalized"]
    if unfinished:
        raise ValueError(f"이전 화({', '.join(map(str, unfinished))}화)의 상태 반영이 끝나지 않았어요")


def apply_setup(p: Project, s: SetupSuggestion) -> None:
    """기존 입력은 유지하고 빈칸만 채운다. 제안 인물의 id 가 이미 있는 인물과 겹쳐도 이름이 다르면 다른 인물로 보고
    새 id 를 붙여 넣고, 그 인물의 관계도 새 id 로 잇는다. 양쪽 인물이 없는 관계는 넣지 않는다."""
    p.meta.theme = p.meta.theme or s.theme
    p.meta.tone = p.meta.tone or s.tone
    for field, value in s.world.model_dump().items():
        if not getattr(p.world, field):
            setattr(p.world, field, value)
    known = {c.id: c for c in p.characters}
    remap: dict[str, str] = {}
    for c in s.characters:
        old = known.get(c.id)
        if old is not None and (not c.name.strip() or old.name.strip() == c.name.strip()):
            continue  # 같은 인물
        if old is not None:
            k = 2
            while f"{c.id}{k}" in known:
                k += 1
            remap[c.id] = f"{c.id}{k}"
            c = c.model_copy(update={"id": remap[c.id]})
        p.characters.append(c)
        known[c.id] = c
    pairs = {frozenset((r.a, r.b)) for r in p.relationships}
    for r in s.relationships:
        r = r.model_copy(update={"a": remap.get(r.a, r.a), "b": remap.get(r.b, r.b)})
        if r.a in known and r.b in known and r.a != r.b and frozenset((r.a, r.b)) not in pairs:
            p.relationships.append(r)
            pairs.add(frozenset((r.a, r.b)))
    _init_states(p)
    dynamics.seed_ties(p)


def _init_states(p: Project) -> None:
    have = {s.character_id for s in p.states}
    for c in p.characters:
        if c.id not in have:
            p.states.append(CharacterState(character_id=c.id, current_goal=c.goal))


# ---------- 2. 스타일 레퍼런스 ----------

def analyze_style(llm: LLM, sample: str) -> StyleProfile:
    profile = llm.json(prompts.SYSTEM_PLANNER, prompts.style_prompt(sample), StyleProfile)
    count_markers(profile, sample)
    return profile


def count_markers(profile: StyleProfile, sample: str) -> None:
    """표지마다 원문 1,000자당 횟수를 센다. 모델이 적은 빈도는 믿지 않는다. 원문에 없는 표지는 뺀다."""
    keep = []
    for m in profile.markers:
        if metrics.marker_count(sample, m.text):
            m.per_1k = metrics.marker_rate(sample, m.text)
            keep.append(m)
    profile.markers = keep
    for d in profile.devices:  # 장치를 알아보는 글자도 원문에 있는 것만
        d.cues = [c for c in d.cues if metrics.marker_count(sample, c)]
        d.every = max(0, d.every)


# ---------- 2-1. 내 수정에서 배우기 ----------
# 작가가 본문을 고친 기록(TextEdit)에서 되풀이되는 고침을 찾아 규칙 후보로 낸다. 후보마다 근거 수정을 프로그램이
# 확인하고(있는 수정인지, 금지 표현이 고치기 전에만 있는지), 작가가 고른 것만 작품 문체에 넣는다.

LEARN_MIN = 5          # 쓸 수 있는 수정이 이보다 적으면 돌리지 않는다
LEARN_LIMIT = 60       # 프롬프트에 넣는 최근 수정 수
LEARN_SUPPORT = 2      # 후보마다 확인된 근거 수정 최소
LEARN_MAX_CHARS = 1500  # 이보다 긴 고침은 내용을 다시 쓴 것으로 보고 뺀다
LEARN_SKIP_PRESETS = {"blocking"}  # 문체가 아니라 동선 · 설정을 맞춘 고침
LEARN_KEEP = 8
RULE_LIMIT = 20  # 지킬 것 + 피할 것이 이보다 많으면 반영할 때 알린다


def learnable_edits(p: Project) -> list[tuple[str, TextEdit]]:
    """학습에 쓸 수정 기록 ('화:id', 수정), 오래된 것부터. 되돌린 것, 동선 맞추기, 새로 써 넣기만 한 것,
    너무 긴 고침, 손대지 않고 넣은 유일한 AI 후보는 뺀다."""
    out = []
    for ep in sorted(p.episodes, key=lambda e: e.plot.number):
        for e in ep.edits:
            if e.undone or e.preset in LEARN_SKIP_PRESETS or not e.before.strip():
                continue
            if max(len(e.before), len(e.after)) > LEARN_MAX_CHARS:
                continue
            if e.source == "ai" and not e.proposed and not e.rejected:
                continue
            out.append((f"{ep.plot.number}:{e.id}", e))
    return out[-LEARN_LIMIT:]


def edit_stats(p: Project) -> dict:
    total = sum(len(ep.edits) for ep in p.episodes)
    usable = learnable_edits(p)
    by: dict[str, int] = {}
    for _, e in usable:
        by[e.source] = by.get(e.source, 0) + 1
    return {"total": total, "usable": len(usable), "min": LEARN_MIN, "by_source": by}


def learn_style(llm: LLM, p: Project) -> StyleLearning:
    """수정 기록에서 문체 규칙 후보를 찾는다. 저장하지 않는다."""
    edits = learnable_edits(p)
    if len(edits) < LEARN_MIN:
        raise ValueError(f"쓸 수 있는 수정 기록이 {len(edits)}건이라 너무 적어요. 본문을 {LEARN_MIN}건 이상 고친 뒤에 해 주세요 "
                         "(되돌린 수정, 동선 맞추기, 새로 써 넣기만 한 것은 빼고 세어요)")
    r = llm.json(prompts.SYSTEM_STYLE_EDITOR, prompts.learn_prompt(p, edits), StyleLearning,
                 hint={"edits": [(ref, e.before, e.after) for ref, e in edits]})
    check_learning(p, r, dict(edits))
    r.edits_used, r.at = len(edits), _now()
    return r


def _gone(text: str, e: TextEdit) -> bool:
    """작가가 지운 표현인지: 고치기 전 글이나 버린 후보에 있고 고친 뒤 글에는 없다."""
    return text not in e.after and (text in e.before or text in e.proposed or any(text in r for r in e.rejected))


def _rules(st: StyleProfile) -> list[str]:
    return st.dos + st.donts + st.banned_phrases + [m.text for m in st.markers] + [d.name for d in st.devices]


def check_learning(p: Project, r: StyleLearning, by_ref: dict[str, TextEdit]) -> None:
    """근거를 확인할 수 없는 후보, 지금 규칙과 같은 후보를 뺀다. 근거 쌍을 붙인다."""
    st, keep, seen = p.style, [], set()
    for s in r.suggestions:
        s.text = s.text.strip()
        if s.kind in ("banned", "marker"):
            s.text = s.text.strip("'\"‘’“”")
        if not s.text or (s.kind, s.text) in seen:
            continue
        refs = [x for x in dict.fromkeys(x.strip().strip("[]") for x in s.evidence) if x in by_ref]
        if s.kind == "banned":
            refs = [x for x in refs if _gone(s.text, by_ref[x])]
            if s.text in st.banned_phrases:
                continue
        elif s.kind == "marker":
            refs = [x for x in refs if metrics.marker_count(by_ref[x].after, s.text)]
            if any(m.text == s.text for m in st.markers):
                continue
        elif s.kind == "device":
            s.cues = [c.strip() for c in s.cues if c.strip()][:3]
            s.cues = [c for c in s.cues if any(_gone(c, by_ref[x]) or c in by_ref[x].before for x in refs)]
            s.every = max(0, s.every)
            if any(d.name == s.text for d in st.devices):
                continue
        elif s.text in (st.dos if s.kind == "do" else st.donts):
            continue
        if s.replaces.strip() not in _rules(st):
            s.replaces = ""
        if len(refs) < LEARN_SUPPORT:
            continue
        s.evidence = refs
        s.pairs = [EditPair(ref=x, before=prompts._clip(by_ref[x].before, 300), after=prompts._clip(by_ref[x].after, 300))
                   for x in refs[:4]]
        s.applied = False
        seen.add((s.kind, s.text))
        keep.append(s)
    r.suggestions = keep[:LEARN_KEEP]


def _own_text(p: Project) -> str:
    return "\n\n".join(e.text for e in p.episodes if e.text)


def apply_learning(p: Project, picks: list[int]) -> tuple[list[StyleRuleSuggestion], list[str]]:
    """고른 후보를 작품 문체에 넣는다. (넣은 후보, 알림) 을 돌려준다."""
    r = p.style_learning
    if r is None:
        raise ValueError("먼저 수정 기록에서 규칙을 찾으세요")
    picks = sorted(set(picks))
    if not picks:
        raise ValueError("넣을 후보를 고르세요")
    if any(not 0 <= i < len(r.suggestions) for i in picks):
        raise ValueError("후보 번호가 맞지 않아요")
    st, done = p.style, []
    for i in picks:
        s = r.suggestions[i]
        if s.applied:
            continue
        if s.replaces:
            st.dos = [x for x in st.dos if x != s.replaces]
            st.donts = [x for x in st.donts if x != s.replaces]
            st.banned_phrases = [x for x in st.banned_phrases if x != s.replaces]
            st.markers = [m for m in st.markers if m.text != s.replaces]
            st.devices = [d for d in st.devices if d.name != s.replaces]
        if s.kind == "do":
            st.dos.append(s.text)
        elif s.kind == "dont":
            st.donts.append(s.text)
        elif s.kind == "banned":
            st.banned_phrases.append(s.text)
        elif s.kind == "marker":
            st.markers.append(StyleMarker(text=s.text, note=s.note, per_1k=metrics.marker_rate(_own_text(p), s.text)))
        else:
            st.devices.append(StyleDevice(name=s.text, when=s.note, cues=s.cues, every=s.every))
        s.applied = True
        done.append(s)
    notes = []
    if len(st.dos) + len(st.donts) > RULE_LIMIT:
        notes.append(f"지킬 것 · 피할 것이 {len(st.dos) + len(st.donts)}개예요. {RULE_LIMIT}개가 넘으면 프롬프트가 길어지고 "
                     "규칙끼리 부딪히기 쉬우니 비슷한 것을 합쳐 주세요")
    return done, notes


# ---------- 2-2. 대화로 문체 다듬기 ----------
# 작가가 문체 화면에서 말하면 AI 가 프로필에서 바꿀 칸과 시험 문단을 낸다(대화 'style'). 프로그램이 지금 값과 같은 칸,
# 모르는 칸을 빼고, 작가가 고른 칸만 작품 문체에 넣는다. 적용하기 전 문체를 메시지에 남겨 그 변경안 단위로 취소할 수 있다.

STYLE_TEXT_KEYS = ("narration_pov", "tense", "sentence_rhythm", "description_density", "dialogue_ratio", "dialogue_style",
                   "inner_monologue", "pacing", "scene_transition", "vocabulary")
STYLE_LIST_KEYS = ("dos", "donts", "banned_phrases")
STYLE_KEYS = STYLE_TEXT_KEYS + STYLE_LIST_KEYS + ("markers", "devices")
STYLE_RECENT = 3  # 문체 대화에 지표와 경고를 넣는 최근 화 수


def style_chat_recent(p: Project) -> list[str]:
    """최근 쓴 화의 문체 지표와 경고 줄. 문체 대화 프롬프트가 쓴다 (LLM 없음)."""
    eps = sorted((e for e in p.episodes if e.text.strip()), key=lambda e: e.plot.number)[-STYLE_RECENT:]
    if not eps:
        return []
    base = style_baseline(p)
    out = [f"기준: 문장 평균 {base.sentence_len_mean:.1f}자, 대사 비율 {base.dialogue_ratio:.0%}"] if base.chars else []
    for e in eps:
        cur, warns = style_drift(p, e.plot.number)
        out.append(f"{e.plot.number}화: 문장 평균 {cur.sentence_len_mean:.1f}자, 대사 비율 {cur.dialogue_ratio:.0%}"
                   + (f" / 경고: {' · '.join(warns[:6])}" if warns else " / 경고 없음"))
    return out


def style_value(e):
    """StyleEdit 이 칸에 넣을 값."""
    if e.key in STYLE_TEXT_KEYS:
        return e.text
    if e.key in STYLE_LIST_KEYS:
        return e.items
    return e.markers if e.key == "markers" else e.devices


def _style_same(key: str, a, b) -> bool:
    if key == "markers":  # 빈도는 프로그램이 세므로 글자와 쓰임만 본다
        return [(m.text, m.note) for m in a] == [(m.text, m.note) for m in b]
    if key == "devices":
        return [d.model_dump() for d in a] == [d.model_dump() for d in b]
    return a == b


def clean_style_revision(p: Project, rev: StyleRevision, ref_text: str = "") -> StyleRevision:
    """모르는 칸, 지금 값과 같은 칸을 빼고 값을 다듬는다. 같은 칸이 두 번이면 뒤의 것을 쓴다.
    ref_text 는 참고한 화 본문: 시험 문단의 원래 대목이 거기 없으면 비운다."""
    st, keep = p.style, {}
    for e in rev.edits:
        if e.key not in STYLE_KEYS:
            continue
        if e.key in STYLE_TEXT_KEYS:
            e.text = e.text.strip()
        elif e.key in STYLE_LIST_KEYS:
            items = [x.strip() for x in e.items]
            if e.key == "banned_phrases":
                items = [x.strip("'\"‘’“”") for x in items]
            e.items = list(dict.fromkeys(x for x in items if x))
        elif e.key == "markers":
            now = {m.text: m.per_1k for m in st.markers}
            seen, ms = set(), []
            for m in e.markers:
                m.text, m.note = m.text.strip().strip("'\"‘’“”"), m.note.strip()
                if m.text and m.text not in seen:
                    seen.add(m.text)
                    m.per_1k = now.get(m.text, 0)  # 모델이 적은 빈도는 믿지 않는다. 새 표지는 적용할 때 센다
                    ms.append(m)
            e.markers = ms
        else:
            ds, seen = [], set()
            for d in e.devices:
                d.name, d.when, d.example = d.name.strip(), d.when.strip(), d.example.strip()
                d.cues = [c.strip() for c in d.cues if c.strip()][:3]
                d.every = max(0, d.every)
                if d.name and d.name not in seen:
                    seen.add(d.name)
                    ds.append(d)
            e.devices = ds
        # 다른 자리에 적은 값은 지운다 (칸 종류에 맞는 자리 하나만 남긴다)
        payload = {"text": "", "items": [], "markers": [], "devices": []}
        slot = "text" if e.key in STYLE_TEXT_KEYS else "items" if e.key in STYLE_LIST_KEYS else e.key
        for k, v in payload.items():
            if k != slot:
                setattr(e, k, v)
        e.why = e.why.strip()
        if _style_same(e.key, getattr(st, e.key), style_value(e)):
            keep.pop(e.key, None)
            continue
        keep[e.key] = e
    rev.edits = [keep[k] for k in STYLE_KEYS if k in keep]
    rev.preview_source = rev.preview_source.strip()
    if rev.preview_source and rev.preview_source not in ref_text:
        rev.preview_source = ""
    rev.preview = rev.preview.strip()
    if not rev.edits:
        rev.preview_source = rev.preview = ""
    return rev


def revise_style(llm: LLM, p: Project, message: str, episode: int = 0) -> StyleRevision:
    """작가의 말로 문체 변경안을 만든다. 저장하지 않는다. episode 는 참고할 화 (본문이 있어야 한다)."""
    if not message.strip():
        raise ValueError("바라는 것을 적어 주세요")
    ref = ""
    if episode:
        ep = next((e for e in p.episodes if e.plot.number == episode), None)
        if ep is None or not ep.text.strip():
            raise ValueError(f"{episode}화에 본문이 없어요. 본문이 있는 화를 참고로 고르세요")
        ref = ep.text
    rev = llm.json(prompts.SYSTEM_STYLE_COACH, prompts.style_chat_prompt(p, message, episode, style_chat_recent(p)), StyleRevision,
                   hint={"message": message, "style": p.style.model_dump(), "ref": ref[:prompts.STYLE_REF_LIMIT]})
    return clean_style_revision(p, rev, ref)


def record_style_chat(p: Project, message: str, episode: int, rev: StyleRevision) -> ChatMessage:
    """작가의 말과 AI 답을 문체 대화('style')에 남긴다."""
    now = _now()
    chat = p.chat("style")
    reply = ChatMessage(role="assistant", text=rev.reply, style=rev if rev.has_changes() else None, at=now)
    asked = ChatMessage(role="user", text=message.strip(), episode=episode, where=f"{episode}화 참고" if episode else "", at=now)
    chat.messages += [asked, reply]
    chat.messages = chat.messages[-CHAT_KEEP:]
    return reply


def _style_message(p: Project, i: int) -> ChatMessage:
    msgs = p.chat("style").messages
    if not 0 <= i < len(msgs) or msgs[i].style is None:
        raise KeyError("문체 변경안이 있는 메시지가 아니에요")
    return msgs[i]


def _marker_source(p: Project) -> str:
    """새 표지의 빈도를 셀 글: 연결된 라이브러리 원문, 없으면 이 작품 본문."""
    from . import library

    if p.style_id and library.exists(p.style_id):
        sample = library.load(p.style_id).sample
        if sample:
            return sample
    return _own_text(p)


def apply_style_chat(p: Project, i: int, keys: list[str]) -> list[str]:
    """i 번째 메시지의 문체 변경안에서 고른 칸만 작품 문체에 넣는다. 적용하기 전 문체를 메시지에 남긴다. 넣은 칸 이름을 돌려준다."""
    m = _style_message(p, i)
    if m.outcome:
        raise ValueError("이미 처리한 변경안이에요")
    picked = [e for e in m.style.edits if e.key in set(keys)]
    if not picked:
        raise ValueError("적용할 칸을 고르세요")
    m.style_before = p.style.model_copy(deep=True)
    src = None
    for e in picked:
        value = [x.model_copy(deep=True) for x in style_value(e)] if e.key in ("markers", "devices") else \
            list(style_value(e)) if e.key in STYLE_LIST_KEYS else style_value(e)
        if e.key == "markers":
            for mk in value:
                if not mk.per_1k:
                    src = _marker_source(p) if src is None else src
                    mk.per_1k = metrics.marker_rate(src, mk.text)
        setattr(p.style, e.key, value)
    m.applied, m.outcome = [e.key for e in picked], "applied"
    if m.style.preview and len(picked) == len(m.style.edits):  # 시험 문단이 그린 문체가 그대로 들어갔으면 예시 칸으로 옮긴다
        asked = p.chat("style").messages[i - 1] if i else None
        p.style_example = StyleExample(text=m.style.preview, source=m.style.preview_source,
                                       episode=asked.episode if asked and m.style.preview_source else 0,
                                       by="chat", profile=p.style.model_copy(deep=True), at=_now())
    return m.applied


def undo_style_chat(p: Project, i: int) -> tuple[list[str], list[str]]:
    """적용한 문체 변경안을 취소한다. 그 뒤에 다시 고친 칸은 건드리지 않는다. (되돌린 칸, 그대로 둔 칸) 을 돌려준다.
    변경안은 다시 고를 수 있게 연다."""
    m = _style_message(p, i)
    if m.outcome != "applied" or m.style_before is None:
        raise ValueError("적용한 변경안이 아니에요")
    by = {e.key: e for e in m.style.edits}
    done, kept = [], []
    for k in m.applied:
        now = getattr(p.style, k)
        if k in by and _style_same(k, now, style_value(by[k])):
            setattr(p.style, k, getattr(m.style_before, k))
            done.append(k)
        else:
            kept.append(k)
    m.outcome, m.applied, m.style_before = "", [], None
    return done, kept


def style_example(llm: LLM, p: Project, scene: str = "", episode: int = 0) -> StyleExample:
    """지금 문체로 예시 글을 쓴다 (write 단계). 저장하지 않는다. episode 를 주면 그 화 한 대목을 고쳐 쓴다."""
    ref = ""
    if episode:
        ep = next((e for e in p.episodes if e.plot.number == episode), None)
        if ep is None or not ep.text.strip():
            raise ValueError(f"{episode}화에 본문이 없어요. 본문이 있는 화를 고르세요")
        ref = ep.text
    if library_blank(p.style):
        raise ValueError("문체가 비어 있어요. 문체 분석을 하거나 스타일 프로필을 채운 뒤 예시를 써 볼 수 있어요")
    r = llm.json(prompts.writer_system(p), prompts.style_example_prompt(p, scene.strip(), episode), StyleSample,
                 hint={"scene": scene, "ref": ref[:prompts.STYLE_REF_LIMIT]})
    text = r.text.strip()
    if not text:
        raise ValueError("AI가 예시 글을 내지 않았어요. 다시 해 보세요")
    source = r.source.strip()
    return StyleExample(text=text, source=source if source and source in ref else "", episode=episode if ref else 0,
                        scene=scene.strip(), by="example", profile=p.style.model_copy(deep=True), at=_now())


def library_blank(st: StyleProfile) -> bool:
    from . import library

    return library.blank(st)


# ---------- 3. 기승전결 + 화별 플롯 ----------

def plan_arc(llm: LLM, p: Project, note: str = "") -> ArcPlan:
    """note: 작가가 바라는 것 (비우면 AI 가 정한다)."""
    plan = llm.json(prompts.SYSTEM_PLANNER, prompts.arc_prompt(p) + prompts.request_block(note), ArcPlan,
                    hint={"total": p.meta.target_episodes, "note": note})
    fit_arc(plan, p.meta.target_episodes)
    return plan


ACT_NAMES = ["기", "승", "전", "결"]
SHARE_BELOW = 4  # 이보다 짧은 작품은 네 구간이 한 화씩 갖지 못하므로 이웃 구간이 한 화를 함께 쓴다


def act_order(a: Act) -> tuple[int, int]:
    """시작 화, 같으면 기승전결 순서. 짧은 작품에서 두 구간이 같은 화에서 시작해도 순서가 흔들리지 않는다."""
    return a.start_ep, ACT_NAMES.index(a.name) if a.name in ACT_NAMES else len(ACT_NAMES)


def act_ranges(total: int, start: int = 1, weights: list[float] | None = None) -> list[tuple[int, int]]:
    """start~total 화를 기승전결 네 구간으로 나눈다. weights 는 구간별 비중(AI 가 낸 길이 등)이고 없으면 기본 비율.
    4화보다 짧으면 정해진 틀을 쓴다: 3화는 기1 · 승2 · 전결3, 2화는 기승1 · 전결2, 1화는 네 구간 모두 1화."""
    size = total - start + 1
    if size < 1:
        raise ValueError(f"구간을 나눌 화가 없어요 ({start}~{total}화)")
    if size < SHARE_BELOW:
        idx = {1: [0, 0, 0, 0], 2: [0, 0, 1, 1], 3: [0, 1, 2, 2]}[size]
        return [(start + k, start + k) for k in idx]
    w = [max(float(x), 0.01) for x in (weights or [0.18, 0.38, 0.26, 0.18])]
    raw = [x / sum(w) * size for x in w]
    lens = [max(1, int(r)) for r in raw]
    while sum(lens) < size:  # 버림으로 모자란 화는 소수점이 큰 구간부터 준다
        k = max(range(4), key=lambda i: raw[i] - lens[i])
        lens[k] += 1
    while sum(lens) > size:  # 최소 1화를 채우느라 넘친 화는 가장 긴 구간에서 뺀다
        k = max(range(4), key=lambda i: lens[i])
        lens[k] -= 1
    out, a = [], start
    for n in lens:
        out.append((a, a + n - 1))
        a += n
    return out


def fit_arc(plan: ArcPlan, total: int, start: int = 1) -> bool:
    """AI 가 낸 구간 범위가 맞지 않으면(겹침, 빈틈, 화수 불일치) 목표와 전환점은 두고 범위만 고친다.
    AI 가 정한 구간 길이의 비율은 살린다. 고쳤으면 True. 구간 이름부터 틀리면 고치지 않고 오류를 낸다."""
    try:
        validate_arc(plan, total, start)
        return False
    except ValueError:
        pass
    if sorted(a.name for a in plan.acts) != sorted(ACT_NAMES):
        raise ValueError(f"기승전결 네 구간이 아니에요: {[a.name for a in plan.acts]}")
    acts = sorted(plan.acts, key=lambda a: ACT_NAMES.index(a.name))
    weights = [max(1, a.end_ep - a.start_ep + 1) for a in acts]
    for a, (s, e) in zip(acts, act_ranges(total, start, weights)):
        a.start_ep, a.end_ep = s, e
    plan.acts = acts
    validate_arc(plan, total, start)
    return True


def validate_arc(plan: ArcPlan, total: int, start: int = 1) -> None:
    """기승전결 네 구간이 start 화부터 total 화까지 빈틈없이 이어지는지 본다. 장편 아크는 start 가 아크 첫 화다.
    4화보다 짧으면 구간이 앞 구간의 마지막 화에서 시작해도 된다(한 화에 두 구간)."""
    acts = sorted(plan.acts, key=act_order)
    if [a.name for a in acts] != ACT_NAMES:
        raise ValueError(f"기승전결 순서가 아니에요: {[a.name for a in acts]}")
    share = total - start + 1 < SHARE_BELOW
    expected = start
    for i, a in enumerate(acts):
        shared = share and i > 0 and a.start_ep == expected - 1
        if (a.start_ep != expected and not shared) or a.end_ep < a.start_ep:
            hint = " 4화보다 짧으면 이웃 구간끼리 한 화를 함께 쓸 수 있어요" if share else ""
            raise ValueError(f"{a.name} 구간 범위 오류: {a.start_ep}~{a.end_ep}화 ({expected}화부터여야 해요){hint}")
        expected = a.end_ep + 1
    if expected != total + 1:
        raise ValueError(f"구간이 {expected - 1}화에서 끝나요 (목표 {total}화)")


def draft_plots(llm: LLM, p: Project, start: int, end: int, note: str = "") -> PlotBatch:
    beats = p.beats()
    if not beats:
        raise ValueError("다음 아크를 먼저 기획하세요" if p.serial else "기승전결 구조(arc)를 먼저 만드세요")
    if p.serial and end > p.planned_until():
        raise ValueError(f"{p.planned_until()}화까지만 아크가 있어요. {end}화까지 쓰려면 다음 아크를 먼저 기획하세요")
    batch = llm.json(
        prompts.SYSTEM_PLANNER, prompts.plot_prompt(p, start, end) + prompts.request_block(note), PlotBatch,
        hint={"start": start, "end": end, "arc": beats, "note": note},
    )
    numbers = [e.number for e in batch.episodes]
    if numbers != list(range(start, end + 1)):
        raise ValueError(f"요청한 화({start}~{end})와 생성된 화({numbers})가 달라요")
    return batch


def apply_plots(p: Project, batch: PlotBatch) -> None:
    """확정되지 않은(draft) 화만 덮어쓴다. 새 인물은 덮어쓴 화에 나오는 것만 후보로 둔다."""
    by_no = {e.plot.number: e for e in p.episodes}
    applied: list[EpisodePlot] = []
    for plot in batch.episodes:
        cur = by_no.get(plot.number)
        if cur and cur.status != "draft":
            continue
        act = p.act_for(plot.number)  # 짧은 작품에서 한 화에 여러 구간이면 첫 구간
        if act:
            plot.act = act.name
        if cur and (cur.plot.storyline or cur.plot.threads) and not (plot.storyline or plot.threads):
            plot.storyline, plot.threads = cur.plot.storyline, list(cur.plot.threads)  # 작가가 붙인 줄기는 AI 초안이 지우지 않는다
        by_no[plot.number] = Episode(plot=plot)
        storylines.clean_plot(p, by_no[plot.number])
        applied.append(plot)
    p.episodes = [by_no[k] for k in sorted(by_no)]
    add_candidates(p, clean_new_characters(p, batch.new_characters, applied))
    elements.add_place_candidates(p, batch.new_places, plots_text(applied))


def plots_text(plots: list[EpisodePlot]) -> str:
    return "\n".join(elements.plot_text(Episode(plot=x)) for x in plots)


# ---------- 3'. 플롯이 데려온 새 인물 ----------
# AI 플롯 초안과 플롯 대화가 낸 새 인물은 바로 인물 설정에 넣지 않고 후보(Project.cast_candidates)로 둔다.
# 작가가 플롯 편집기에서 등록하거나, 그 인물이 나오는 화를 확정하면 조연 · 단역으로 등록된다.

def clean_new_characters(p: Project, chars: list[Character], plots: list[EpisodePlot]) -> list[Character]:
    """이미 있는 인물, 고른 플롯에 나오지 않는 인물은 빼고, 주역은 조연으로 내린다 (주역은 작가가 정한다)."""
    known = {c.id for c in p.characters}
    used = {c for e in plots for c in e.characters}
    out: list[Character] = []
    for c in chars:
        if not c.id or c.id in known or c.id not in used or any(x.id == c.id for x in out):
            continue
        out.append(c.model_copy(update={"tier": "support" if c.tier == "main" else c.tier, "first_ep": 0}))
    return out


def add_candidates(p: Project, chars: list[Character]) -> None:
    """후보를 더한다. 같은 id 의 후보가 이미 있으면 앞 플롯이 쓰고 있으니 그대로 둔다."""
    have = {c.id for c in p.cast_candidates}
    p.cast_candidates += [c for c in chars if c.id not in have]
    sync_candidates(p)


def sync_candidates(p: Project) -> None:
    """등록됐거나 이제 어느 화 플롯에도 나오지 않는 인물 · 장소 후보는 지운다."""
    known = {c.id for c in p.characters}
    used = {c for e in p.episodes for c in e.plot.characters}
    p.cast_candidates = [c for c in p.cast_candidates if c.id not in known and c.id in used]
    elements.sync_place_candidates(p)


def register_candidates(p: Project, ids: list[str] | None = None, episode: int | None = None) -> list[str]:
    """후보를 인물로 등록한다. ids 를 주면 그 후보만, episode 를 주면 그 화에 나오는 후보만.
    처음 나오는 화가 first_ep 가 된다. 등록한 id 를 돌려준다."""
    if episode is not None:
        cast = set(p.episode(episode).plot.characters)
        ids = [c.id for c in p.cast_candidates if c.id in cast and (ids is None or c.id in ids)]
    want = set(ids if ids is not None else [c.id for c in p.cast_candidates])
    done = []
    for c in [c for c in p.cast_candidates if c.id in want]:
        first = min((e.plot.number for e in p.episodes if c.id in e.plot.characters), default=0)
        _add_characters(p, [c], first)
        done.append(c.id)
    sync_candidates(p)
    return done


def confirm_plot(p: Project, n: int) -> list[str]:
    """초안 화를 확정한다. 그 화에 나오는 새 인물 후보와 새 장소 후보도 함께 등록하고, 등록한 인물 id 를 돌려준다."""
    ep = p.episode(n)
    if ep.status != "draft":
        return []
    ep.status = "confirmed"
    elements.register_place_candidates(p, n)
    return register_candidates(p, episode=n)


# ---------- 3-0. 장편 연재: 부 구성과 굴러가는 아크 기획 ----------

ARC_MIN, ARC_MAX = 4, 60  # 아크 하나의 화수 범위. 아크 안에 기승전결 네 구간이 들어가야 해서 최소 4화
OLD_FORESHADOW = 50  # 이 화수보다 오래 열린 복선은 다음 아크 기획 때 따로 표시한다


def validate_parts(parts: list, total: int) -> None:
    parts = sorted(parts, key=lambda x: x.start_ep)
    expected = 1
    for i, x in enumerate(parts, 1):
        if x.number != i:
            raise ValueError(f"부 번호가 1부터 차례대로가 아니에요: {[y.number for y in parts]}")
        if x.start_ep != expected or x.end_ep < x.start_ep:
            raise ValueError(f"{x.number}부 범위 오류: {x.start_ep}~{x.end_ep}")
        expected = x.end_ep + 1
    if parts and expected != total + 1:
        raise ValueError(f"부 구성이 {expected - 1}화에서 끝나요 (목표 {total}화)")


def validate_story_arcs(p: Project) -> None:
    """아크가 1화부터 빈틈없이 이어지고, 아크 안 기승전결이 맞고, 부 경계를 넘지 않는지 본다."""
    expected = 1
    for i, s in enumerate(sorted(p.story_arcs, key=lambda s: s.start_ep), 1):
        if s.number != i:
            raise ValueError(f"아크 번호가 1부터 차례대로가 아니에요 ({s.number})")
        if s.start_ep != expected or s.end_ep < s.start_ep:
            raise ValueError(f"아크 {s.number} 범위 오류: {s.start_ep}~{s.end_ep} ({expected}화부터여야 해요)")
        try:
            validate_arc(ArcPlan(acts=s.acts), s.end_ep, s.start_ep)
        except ValueError as e:  # 어느 아크의 구간인지 밝힌다
            raise ValueError(f"아크 {s.number}({s.start_ep}~{s.end_ep}화) 구간: {e}") from None
        part = p.part_for(s.start_ep)
        if p.parts and (part is None or s.end_ep > part.end_ep):
            raise ValueError(f"아크 {s.number}({s.start_ep}~{s.end_ep}화)가 부 경계를 넘어요")
        expected = s.end_ep + 1
    if p.story_arcs and expected - 1 > p.meta.target_episodes:
        raise ValueError(f"아크가 총 화수({p.meta.target_episodes}화)를 넘어요")


def plan_series(llm: LLM, p: Project, note: str = "") -> SeriesPlan:
    total = p.meta.target_episodes
    plan = llm.json(prompts.SYSTEM_PLANNER, prompts.series_prompt(p) + prompts.request_block(note), SeriesPlan,
                    hint={"total": total, "note": note})
    for x in plan.parts:
        x.summary = ""
    validate_parts(plan.parts, total)
    return plan


def apply_series(p: Project, plan: SeriesPlan) -> None:
    """부 구성을 바꾼다. 이미 끝난 부의 요약은 범위가 같으면 남긴다. 기존 아크가 새 부 경계를 넘으면 막는다."""
    validate_parts(plan.parts, p.meta.target_episodes)
    old = {(x.start_ep, x.end_ep): x.summary for x in p.parts}
    before = p.parts
    p.parts = [x.model_copy(deep=True, update={"summary": x.summary or old.get((x.start_ep, x.end_ep), "")})
               for x in sorted(plan.parts, key=lambda x: x.start_ep)]
    try:
        validate_story_arcs(p)
    except ValueError:
        p.parts = before
        raise


def next_arc_start(p: Project) -> int:
    return p.planned_until() + 1


def plan_next_arc(llm: LLM, p: Project, length: int = 0, note: str = "") -> ArcProposal:
    """지금까지 쓴 내용을 보고 다음 아크 하나를 제안한다. 저장하지 않는다."""
    if not p.serial:
        raise ValueError("장편 연재(form=serial) 작품에서만 아크를 기획해요")
    start = next_arc_start(p)
    if start > p.meta.target_episodes:
        raise ValueError(f"총 {p.meta.target_episodes}화까지 아크가 모두 있어요. 더 쓰려면 총 화수를 늘리세요")
    length = length or p.meta.arc_length
    part = p.part_for(start)
    limit = part.end_ep if part else p.meta.target_episodes
    prop = llm.json(
        prompts.SYSTEM_PLANNER, prompts.next_arc_prompt(p, start, length, note), ArcProposal,
        hint={"start": start, "length": length, "limit": limit, "number": len(p.story_arcs) + 1},
    )
    return clean_arc(p, prop)


def clean_arc(p: Project, prop: ArcProposal) -> ArcProposal:
    """아크 번호와 시작 화를 맞추고 범위를 검사한다. 고칠 수 없는 오류는 그대로 알린다."""
    a = prop.arc
    a.number, a.summary = len(p.story_arcs) + 1, ""
    start = next_arc_start(p)
    if a.start_ep != start:
        raise ValueError(f"아크가 {a.start_ep}화에서 시작해요 ({start}화부터여야 해요)")
    size = a.end_ep - a.start_ep + 1
    if not ARC_MIN <= size <= ARC_MAX:
        raise ValueError(f"아크 길이 {size}화는 쓸 수 없어요 ({ARC_MIN}~{ARC_MAX}화)")
    part = p.part_for(start)
    limit = part.end_ep if part else p.meta.target_episodes
    if a.end_ep > limit:
        raise ValueError(f"아크가 {a.end_ep}화에서 끝나 {'부' if part else '작품'} 끝({limit}화)을 넘어요")
    plan = ArcPlan(acts=a.acts)
    fit_arc(plan, a.end_ep, a.start_ep)  # 구간 범위가 어긋났으면 비율을 살려 고친다
    a.acts = plan.acts
    if 0 < limit - a.end_ep < ARC_MIN:  # 남는 화로는 아크를 만들 수 없으니 결 구간을 부 끝까지 늘린다
        last = max(a.acts, key=lambda x: x.start_ep)
        last.end_ep = a.end_ep = limit
        prop.reply = (prop.reply.rstrip() + f"\n\n※ {'부' if part else '작품'} 끝까지 {ARC_MIN}화가 안 남아 아크를 {limit}화까지 늘렸어요.").strip()
    known = {c.id for c in p.characters}
    prop.new_characters = [c for c in prop.new_characters if c.id not in known]
    ids = known | {c.id for c in prop.new_characters}
    a.cast = [c for c in a.cast if c in ids]
    open_fs = {f.id for f in p.foreshadows if f.status == "open"}
    a.payoffs = [f for f in a.payoffs if f in open_fs]
    return prop


def _add_characters(p: Project, chars: list[Character], first_ep: int) -> None:
    """새 인물을 붙인다. 주역으로 올리는 것은 작가가 정하므로 조연으로 들인다."""
    known = {c.id for c in p.characters}
    for c in chars:
        if c.id in known:
            continue
        p.characters.append(c.model_copy(update={
            "tier": "support" if c.tier == "main" else c.tier,
            "first_ep": c.first_ep or first_ep,
        }))
        known.add(c.id)
    _init_states(p)


def apply_arc(p: Project, prop: ArcProposal) -> StoryArc:
    """제안된 다음 아크를 붙인다. 새 인물과 복선 회수 예정 화도 함께 반영한다."""
    prop = clean_arc(p, prop.model_copy(deep=True))
    a = prop.arc
    p.story_arcs.append(a)
    try:
        validate_story_arcs(p)
    except ValueError:
        p.story_arcs.pop()
        raise
    known = {c.id for c in p.characters}
    _add_characters(p, prop.new_characters, a.start_ep)
    undo = ArcUndo(number=a.number, characters=[c.id for c in p.characters if c.id not in known])
    for f in p.foreshadows:
        if f.id in a.payoffs and f.status == "open":
            undo.foreshadows.append(f.id)
            undo.due_before.append(f.due_ep)
            f.due_ep = a.end_ep
    p.arc_undo = [u for u in p.arc_undo if u.number != a.number] + [undo]
    return a


def remove_last_arc(p: Project) -> StoryArc:
    """마지막 아크를 지운다 (다시 기획하려고). 확정했거나 본문이 있는 화가 있으면 막는다."""
    if not p.story_arcs:
        raise ValueError("지울 아크가 없어요")
    a = max(p.story_arcs, key=lambda s: s.start_ep)
    eps = [e for e in p.episodes if a.start_ep <= e.plot.number <= a.end_ep]
    stuck = [e.plot.number for e in eps if e.status != "draft"]
    if stuck:
        raise ValueError(f"아크 {a.number}에 확정했거나 본문이 있는 화({stuck})가 있어 지울 수 없어요")
    p.story_arcs.remove(a)
    p.episodes = [e for e in p.episodes if e not in eps]
    # 이 아크를 붙일 때 더한 인물(다른 화에 나오지 않는 것만)과 바꾼 복선 회수 예정 화를 되돌린다
    undo = next((u for u in p.arc_undo if u.number == a.number), None)
    if undo:
        used = {c for e in p.episodes for c in e.plot.characters}
        gone = {cid for cid in undo.characters if cid not in used}
        p.characters = [c for c in p.characters if c.id not in gone]
        p.states = [s for s in p.states if s.character_id not in gone]
        due = dict(zip(undo.foreshadows, undo.due_before))
        for f in p.foreshadows:
            if f.id in due and f.due_ep == a.end_ep:
                f.due_ep = due[f.id]
        p.arc_undo = [u for u in p.arc_undo if u is not undo]
    return a


def arc_finished(p: Project, a: StoryArc) -> bool:
    nums = {e.plot.number for e in p.episodes if e.status == "finalized"}
    return all(n in nums for n in range(a.start_ep, a.end_ep + 1))


def recap(llm: LLM, p: Project, kind: str, number: int) -> Recap:
    """끝난 아크(kind='arc')나 부(kind='part')의 요약을 제안한다. 화별 요약(작가가 승인한 것)으로 만든다."""
    target = _recap_target(p, kind, number)
    if not arc_finished(p, target):
        raise ValueError(f"{'아크' if kind == 'arc' else '부'} {number}의 모든 화가 상태 반영까지 끝나야 요약해요")
    return llm.json(prompts.SYSTEM_EDITOR, prompts.recap_prompt(p, kind, number), Recap, hint={"kind": kind, "number": number})


def apply_recap(p: Project, kind: str, number: int, summary: str) -> None:
    _recap_target(p, kind, number).summary = summary.strip()


def _recap_target(p: Project, kind: str, number: int):
    items = p.story_arcs if kind == "arc" else p.parts if kind == "part" else None
    if items is None:
        raise ValueError(f"모르는 요약 단위예요: {kind}")
    hit = next((x for x in items if x.number == number), None)
    if hit is None:
        raise ValueError(f"{'아크' if kind == 'arc' else '부'} {number}이(가) 없어요")
    return hit


def pending_recaps(p: Project) -> list[tuple[str, int]]:
    """모든 화가 끝났는데 요약이 없는 아크와 부. 요약이 있는 부의 아크는 부 요약이 대신 들어가므로(prompts.story_so_far) 빼 둔다."""
    summed = [x for x in p.parts if x.summary]
    out = [("arc", a.number) for a in p.story_arcs if not a.summary and arc_finished(p, a)
           and not any(x.start_ep <= a.start_ep <= x.end_ep for x in summed)]
    out += [("part", x.number) for x in p.parts if not x.summary and arc_finished(p, x)]
    return out


# ---------- 3-0'. 단편 → 장편 전환 ----------
# 단편 전체가 아크 1이 된다. 이미 쓴 화의 구조는 바꿀 수 없어서 기승전결을 그대로 옮기고,
# 그 뒤를 부 구성과 장기 떡밥으로 늘린다. 되돌리기용 백업은 호출자가 store.save_backup 으로 남긴다.

CONVERT_MAX = 1000  # 전환할 때 고를 수 있는 총 화수 상한
BACKUP_TAG = "before-serial"


def short_end(p: Project) -> int:
    """아크 1이 될 단편의 마지막 화. 구조가 없으면 0."""
    return max((a.end_ep for a in p.arc), default=0)


def convert_range(p: Project) -> tuple[int, int]:
    end = short_end(p)
    return max(end + ARC_MIN, ARC_MIN * 2), CONVERT_MAX


def check_convertible(p: Project, total: int) -> None:
    if p.serial:
        raise ValueError("이미 장편 연재 작품이에요")
    if p.episodes and not p.arc:
        raise ValueError("기승전결 구조 없이 플롯만 있는 작품은 전환할 수 없어요. 구조를 먼저 저장하세요")
    lo, hi = convert_range(p)
    if not lo <= total <= hi:
        raise ValueError(f"장편 총 화수는 {lo}~{hi}화로 정하세요 (단편 {short_end(p)}화 뒤에 아크가 하나 이상 들어가야 해요)")


def propose_conversion(llm: LLM, p: Project, total: int, ending: str = "", note: str = "") -> SerialConversion:
    """단편을 장편으로 늘리는 계획을 제안한다. 저장하지 않는다."""
    if ending not in ("", "keep", "reopen"):
        raise ValueError(f"모르는 결말 처리예요: {ending}")
    check_convertible(p, total)
    prop = llm.json(
        prompts.SYSTEM_PLANNER, prompts.convert_prompt(p, total, ending, note), SerialConversion,
        hint={"total": total, "end": short_end(p), "ending": ending, "characters": [c.id for c in p.characters],
              "open": [f.id for f in p.foreshadows if f.status == "open"],
              "unlocked": [e.plot for e in p.episodes if e.status not in LOCKED]},
    )
    if ending:
        prop.ending = ending  # type: ignore[assignment]
    return clean_conversion(p, prop, total)


def clean_conversion(p: Project, prop: SerialConversion, total: int = 0) -> SerialConversion:
    """번호와 범위를 맞추고 쓸 수 없는 부분을 뺀다. 뺀 이유는 reply 에 덧붙인다."""
    total = total or prop.total_episodes
    check_convertible(p, total)
    prop.total_episodes = total
    notes: list[str] = []
    end = short_end(p)
    known = {c.id for c in p.characters}
    a = prop.arc
    a.number, a.start_ep, a.end_ep, a.payoffs = 1, 1, end or 1, []
    a.acts = [x.model_copy(deep=True) for x in p.arc]
    a.cast = [c for c in dict.fromkeys(a.cast) if c in known]
    finished = bool(end) and all(any(e.plot.number == n and e.status == "finalized" for e in p.episodes)
                                 for n in range(1, end + 1))
    if not finished:
        a.summary = ""
    a.summary = a.summary.strip()

    prop.parts = _clean_parts(prop.parts, total, [prop.arc] if end else [], notes)

    seen = {f.id for f in p.foreshadows}
    last_text = max((e.plot.number for e in p.episodes if e.status in LOCKED), default=0)
    fs = []
    for f in prop.foreshadows:
        if not f.id or f.id in seen or not f.description.strip():
            continue
        seen.add(f.id)
        fs.append(f.model_copy(update={
            "status": "open", "payoff_ep": None,
            "planted_ep": min(max(f.planted_ep, 1), end or 1),
            "scope": f.scope if f.scope != "arc" else "part",
            "due_ep": f.due_ep if f.due_ep and end < f.due_ep <= total else None,
        }))
    prop.foreshadows = fs
    opened = {f.id: f for f in p.foreshadows if f.status == "open"}
    prop.scopes = [s for s in {s.id: s for s in prop.scopes}.values() if s.id in opened and s.scope != opened[s.id].scope]
    prop.facts = [f.strip() for f in dict.fromkeys(prop.facts) if f.strip() and f.strip() not in p.facts]

    prop.tiers = _clean_tiers(p, prop.tiers, notes)

    status = {e.plot.number: e.status for e in p.episodes}
    current = {e.plot.number: e.plot.model_dump() for e in p.episodes}
    keep, dropped = {}, []
    for e in prop.episodes:
        n = e.number
        if not 1 <= n <= end or status.get(n) in LOCKED:
            dropped.append(n)
            continue
        act = p.act_for(n)
        if act:
            e.act = act.name
        if current.get(n) != e.model_dump():
            keep[n] = e
    if dropped:
        notes.append(f"본문이 있거나 단편 범위 밖인 화({sorted(set(dropped))})의 플롯 변경안은 뺐어요.")
    prop.episodes = [keep[n] for n in sorted(keep)]
    if last_text and prop.ending == "reopen" and not (prop.foreshadows or prop.facts or prop.episodes):
        notes.append("결말을 다시 열 장치(떡밥, 사실, 플롯 수정)가 없어요. 다시 제안받거나 전환한 뒤 인과율에서 더하세요.")
    if notes:
        prop.reply = (prop.reply.rstrip() + "\n\n※ " + " ".join(notes)).strip()
    return prop


def _clean_parts(parts: list[Part], total: int, arcs: list[StoryArc], notes: list[str]) -> list[Part]:
    """번호와 양 끝을 맞춘다. 빈틈이 있거나 아크가 부 경계를 넘으면 빼고 이유를 notes 에 남긴다."""
    parts = sorted(parts, key=lambda x: x.start_ep)
    for i, x in enumerate(parts, 1):
        x.number, x.summary = i, ""
    if parts:
        parts[0].start_ep = 1
        parts[-1].end_ep = total  # 마지막 부가 총 화수와 조금 어긋나는 것은 맞춰 준다
    try:
        validate_parts(parts, total)
        for a in arcs:
            x = next((x for x in parts if x.start_ep <= a.start_ep <= x.end_ep), None)
            if x and a.end_ep > x.end_ep:
                raise ValueError(f"{x.number}부가 {x.end_ep}화에서 끝나 아크 {a.number}({a.end_ep}화까지)을 품지 못해요")
    except ValueError as e:
        notes.append(f"부 구성이 맞지 않아 뺐어요: {e}. 전환한 뒤 부 구성을 다시 제안받으세요.")
        parts = []
    return parts


def _clean_tiers(p: Project, tiers: list, notes: list[str]) -> list:
    tier = {c.id: c.tier for c in p.characters}
    tiers = [t for t in {t.id: t for t in tiers}.values() if t.id in tier and t.tier != tier[t.id]]
    after = tier | {t.id: t.tier for t in tiers}
    if not any(v == "main" for v in after.values()) and tiers:
        notes.append("주역이 한 명도 남지 않아 비중 조정을 뺐어요.")
        tiers = []
    return tiers


def _stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def apply_conversion(p: Project, prop: SerialConversion, at: str = "") -> Project:
    """전환 제안을 반영한다. 화면에서 빼고 보낸 항목은 반영하지 않는다. 전환 전 작품(백업할 것)을 돌려준다."""
    prop = clean_conversion(p, prop.model_copy(deep=True))
    before = p.model_copy(deep=True)
    end = short_end(p)
    try:
        p.meta.form, p.meta.target_episodes = "serial", prop.total_episodes
        p.story_arcs = [prop.arc] if end else []
        p.parts = prop.parts
        p.arc = []
        validate_story_arcs(p)
    except ValueError:
        for k in ("meta", "story_arcs", "parts", "arc"):
            setattr(p, k, getattr(before, k))
        raise
    tiers = {t.id: t.tier for t in prop.tiers}
    for c in p.characters:
        c.tier = tiers.get(c.id, c.tier)
    scopes = {s.id: s.scope for s in prop.scopes}
    for f in p.foreshadows:
        f.scope = scopes.get(f.id, f.scope)
    p.foreshadows += prop.foreshadows
    p.facts += prop.facts
    by_no = {e.plot.number: e for e in p.episodes}
    for plot in prop.episodes:
        by_no[plot.number] = Episode(plot=plot.model_copy(deep=True))  # 확정된 화도 내용이 바뀌면 다시 확정한다
    p.episodes = [by_no[k] for k in sorted(by_no)]
    if not at:
        from datetime import datetime, timezone

        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    p.conversion = Conversion(at=at, from_total=before.meta.target_episodes, arc_end=end,
                              ending=prop.ending, history=len(p.history))
    return before


def ep_list(nums: list[int], most: int = 4) -> str:
    """화 번호를 '1, 3~5화' 처럼 잇는다. 묶음이 많으면 '49~60, 62화 등 14화' 처럼 줄인다."""
    runs: list[list[int]] = []
    for n in sorted(set(nums)):
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    text = ", ".join(f"{a}~{b}" if a != b else f"{a}" for a, b in runs[:most])
    return f"{text}화 등 {len(set(nums))}화" if len(runs) > most else f"{text}화"


def undo_blockers(p: Project, backup: Project | None) -> list[str]:
    """전환을 되돌리면 잃는 것이 있으면 그 이유. 비면 되돌려도 된다."""
    if p.conversion is None:
        return ["단편에서 전환한 작품이 아니에요"]
    if backup is None:
        return ["전환 전 백업(before-serial.json)이 없어요"]
    out = []
    eps = undo_blocker_eps(p, backup)
    if eps["applied"]:
        out.append(f"전환한 뒤 상태를 반영한 화가 있어요 ({ep_list(eps['applied'])})")
    if eps["changed"]:
        out.append(f"전환한 뒤 쓰거나 고친 본문이 있어요 ({ep_list(eps['changed'])})")
    return out


def undo_blocker_eps(p: Project, backup: Project) -> dict[str, list[int]]:
    """되돌리기를 막는 화 번호. applied: 전환한 뒤 상태를 반영한 화, changed: 전환한 뒤 쓰거나 고친 본문이 있는 화."""
    assert p.conversion is not None
    applied = sorted({d.episode for d in p.history[p.conversion.history:]})
    if p.conversion.mode == "rebuild":  # 재구성은 화 번호가 바뀌므로 옛 본문 어느 것과도 같지 않은 본문을 찾는다
        texts = {e.text for e in backup.episodes}
        changed = [e.plot.number for e in p.episodes if e.text and e.text not in texts]
    else:
        old = {e.plot.number: e.text for e in backup.episodes}
        changed = [e.plot.number for e in p.episodes if e.text and old.get(e.plot.number) != e.text]
    return {"applied": applied, "changed": changed}


def undo_conversion(p: Project, backup: Project) -> Project:
    """전환 전 작품을 돌려준다. 잃는 것이 있으면 막는다."""
    why = undo_blockers(p, backup)
    if why:
        raise ValueError("되돌릴 수 없어요: " + " / ".join(why))
    return backup.model_copy(deep=True, update={"conversion": None, "archive": None})


# ---------- 3-0''. 단편 → 장편 재구성 ----------
# 단편을 씨앗으로 장편 앞부분(아크 몇 개)을 다시 짠다. 새 화마다 옛 화를 그대로 두기(keep), 조금 고치기(revise),
# 재료로 새로 쓰기(rewrite), 새 화(new) 중 하나로 쓴다. 화 번호가 바뀌므로 상태 · 관계는 1화 시작 전으로 돌리고
# 새 순서대로 다시 반영한다. 그대로 둔 화는 옛 상태 변경안을 번호만 바꿔 다시 쓴다 (carried_delta).

REBUILD_MAX_SPAN = 120  # 한 번에 다시 짜는 앞부분 화수 상한 (지도 한 줄이 짧아 이 정도는 한 번에 받는다)


def rebuild_span(p: Project) -> tuple[int, int, int]:
    """재구성할 앞부분 화수의 (최소, 기본, 최대). 옛 화 하나가 보통 새 2~4화가 된다."""
    old = max(len(p.episodes), short_end(p), 1)
    return max(old, ARC_MIN), min(max(old * 3, ARC_MIN * 2), REBUILD_MAX_SPAN), REBUILD_MAX_SPAN


def check_rebuild(p: Project, total: int, span: int = 0, ending_at: str = "") -> int:
    """재구성할 수 있는지 보고 앞부분 화수를 돌려준다 (0 이면 기본값)."""
    if ending_at not in ("", "arc", "part", "series"):
        raise ValueError(f"모르는 결말 위치예요: {ending_at}")
    check_convertible(p, total)
    if not p.episodes:
        raise ValueError("재구성할 단편 화가 없어요. 이어 쓰기로 전환하세요")
    lo, default, hi = rebuild_span(p)
    span = span or default
    if not lo <= span <= min(hi, total):
        raise ValueError(f"다시 짤 앞부분은 {lo}~{min(hi, total)}화로 정하세요")
    return span


def propose_rebuild(llm: LLM, p: Project, total: int, span: int = 0, ending_at: str = "", note: str = "") -> SerialRebuild:
    """단편을 씨앗으로 장편 앞부분을 다시 짠다. 저장하지 않는다."""
    span = check_rebuild(p, total, span, ending_at)
    prop = llm.json(
        prompts.SYSTEM_PLANNER, prompts.rebuild_prompt(p, total, span, ending_at, note), SerialRebuild,
        hint={"total": total, "span": span, "ending_at": ending_at, "old": [(e.plot.number, bool(e.text)) for e in p.episodes]},
    )
    if ending_at:
        prop.ending_at = ending_at  # type: ignore[assignment]
    return clean_rebuild(p, prop, total)


def clean_rebuild(p: Project, prop: SerialRebuild, total: int = 0) -> SerialRebuild:
    """아크가 1화부터 이어지는지 보고, 지도를 1화부터 마지막 아크 끝까지 맞춘다. 쓸 수 없는 부분은 고치거나 빼고 reply 에 적는다."""
    total = total or prop.total_episodes
    check_convertible(p, total)
    prop.total_episodes = total
    notes: list[str] = []
    known = {c.id for c in p.characters}
    arcs = sorted(prop.arcs, key=lambda a: a.start_ep)
    if not arcs:
        raise ValueError("재구성 제안에 아크가 없어요. 다시 제안받으세요")
    expected = 1
    for i, a in enumerate(arcs, 1):
        a.number, a.summary, a.payoffs = i, "", []
        if a.start_ep != expected:
            raise ValueError(f"아크 {i}가 {a.start_ep}화에서 시작해요 ({expected}화부터여야 해요). 다시 제안받으세요")
        validate_arc(ArcPlan(acts=a.acts), a.end_ep, a.start_ep)
        a.acts = sorted(a.acts, key=lambda x: x.start_ep)
        a.cast = [c for c in dict.fromkeys(a.cast) if c in known]
        expected = a.end_ep + 1
    last = expected - 1
    if last > total:
        raise ValueError(f"아크가 {last}화까지 있어 총 {total}화를 넘어요")
    prop.arcs = arcs
    prop.parts = _clean_parts(prop.parts, total, arcs, notes)

    old = {e.plot.number: e for e in p.episodes}
    by_no = {}
    for x in prop.episodes:
        if 1 <= x.number <= last and x.number not in by_no:
            by_no[x.number] = x
    missing = [n for n in range(1, last + 1) if n not in by_no]
    for n in missing:
        by_no[n] = RebuildEpisode(number=n, title=f"{n}화", summary="", use="new")
    if missing:
        notes.append(f"지도에 없던 {missing}화는 새 화로 채웠어요. 플롯 초안에서 채우세요.")
    taken: set[int] = set()
    changed = []
    for n in sorted(by_no):
        x = by_no[n]
        x.sources = [s for s in dict.fromkeys(x.sources) if s in old]
        before = x.use
        if x.use in ("keep", "revise"):
            src = x.sources[0] if len(x.sources) == 1 else None
            if src is None or not old[src].text or src in taken:
                x.use = "rewrite" if x.sources else "new"  # 본문을 그대로 쓸 수 있는 건 옛 화 하나, 한 번뿐이다
            else:
                taken.add(src)
        if x.use == "rewrite" and not x.sources:
            x.use = "new"
        if x.use != before:
            changed.append(n)
    if changed:
        notes.append(f"{changed}화는 옛 본문을 그대로 쓸 수 없어(옛 화가 여럿이거나, 본문이 없거나, 이미 다른 화에 씀) 쓰는 방식을 바꿨어요.")
    kept = [(n, by_no[n].sources[0]) for n in sorted(by_no) if by_no[n].use in ("keep", "revise")]
    if any(a[1] > b[1] for a, b in zip(kept, kept[1:])):
        notes.append("그대로 두거나 다듬는 옛 화의 순서가 바뀐 곳이 있어요. 앞뒤 연결을 검수에서 확인하세요.")
    prop.episodes = [by_no[n] for n in sorted(by_no)]
    used = {s for x in prop.episodes for s in x.sources}
    prop.dropped = sorted((set(prop.dropped) & set(old) - used) | (set(old) - used))

    seen = {f.id for f in p.foreshadows}
    fs = []
    for f in prop.foreshadows:
        if not f.id or f.id in seen or not f.description.strip():
            continue
        seen.add(f.id)
        fs.append(f.model_copy(update={
            "status": "open", "payoff_ep": None, "planted_ep": min(max(f.planted_ep, 1), last),
            "scope": f.scope if f.scope != "arc" else "part",
            "due_ep": f.due_ep if f.due_ep and f.planted_ep < f.due_ep <= total else None,
        }))
    prop.foreshadows = fs
    prop.tiers = _clean_tiers(p, prop.tiers, notes)
    if notes:
        prop.reply = (prop.reply.rstrip() + "\n\n※ " + " ".join(notes)).strip()
    return prop


def _old_to_new(m: list[RebuildEpisode]) -> dict[int, int]:
    """옛 화 → 그 옛 화를 쓰는 첫 새 화. 본문을 그대로 쓰는 화를 먼저 본다."""
    out: dict[int, int] = {}
    for x in sorted(m, key=lambda x: (x.use not in ("keep", "revise"), x.number)):
        for s in x.sources:
            out.setdefault(s, x.number)
    return out


def _remap(old: int, mapping: dict[int, int]) -> int:
    """옛 화 번호를 새 화 번호로. 그 화가 빠졌으면 뒤로 가장 가까운 쓰인 옛 화를 쓴다. 없으면 0."""
    if old <= 0:
        return old
    for o in sorted(k for k in mapping if k >= old):
        return mapping[o]
    return 0


def apply_rebuild(p: Project, prop: SerialRebuild, at: str = "") -> tuple[Project, list[str]]:
    """재구성을 반영한다. 전환 전 작품(백업할 것)과, 옮기지 못해 작가가 볼 것의 목록을 돌려준다."""
    prop = clean_rebuild(p, prop.model_copy(deep=True))
    validate_story_arcs(p.model_copy(update={  # 바꾸기 전에 장편 구조가 맞는지 먼저 본다
        "meta": p.meta.model_copy(update={"form": "serial", "target_episodes": prop.total_episodes}),
        "arc": [], "story_arcs": prop.arcs, "parts": prop.parts}))
    before = p.model_copy(deep=True)
    notes: list[str] = []
    archive = ShortArchive(episodes=[e.model_copy(deep=True) for e in p.episodes], arc=[a.model_copy() for a in p.arc],
                           history=[d.model_copy(deep=True) for d in p.history], map=prop.episodes, dropped=prop.dropped)
    mapping = _old_to_new(prop.episodes)

    # 상태 · 관계는 1화 시작 전으로 (화 번호가 바뀌어 옛 반영 기록을 그대로 둘 수 없다)
    snap = p.snapshot(0)
    if snap is not None:
        p.states = [s.model_copy(deep=True) for s in snap.states]
        p.relationships = [r.model_copy(deep=True) for r in snap.relationships]
        p.ties = [t.model_copy(deep=True) for t in snap.ties]
        p.secrets = [s.model_copy(deep=True) for s in snap.secrets]
        p.facts = list(snap.facts)
        p.foreshadows = [f.model_copy(deep=True) for f in snap.foreshadows]
        p.snapshots = [snap]
    p.events, p.history = [], []
    p.foreshadow_clues = []  # 화 번호가 바뀌어 걸어 둔 문장 자리도 맞지 않는다
    statwin.revert(p, 0)
    charlog.revert(p, 0)  # 그대로 둔 화는 옛 변경안을 다시 반영하며 설정 바꾸기도 새 화 번호로 다시 들어간다
    p.timeline.deadlines = []  # 그대로 둔 화는 옛 변경안을 다시 반영하며 기한도 새 화 번호로 생긴다
    p.foreshadows += prop.foreshadows
    tiers = {t.id: t.tier for t in prop.tiers}
    for c in p.characters:
        c.tier = tiers.get(c.id, c.tier)

    p.meta.form, p.meta.target_episodes = "serial", prop.total_episodes
    p.arc, p.story_arcs, p.parts = [], prop.arcs, prop.parts
    eps = []
    for x in prop.episodes:
        act = p.act_for(x.number)
        src = archive.source(x.sources[0]) if x.sources else None
        if x.use in ("keep", "revise") and src is not None:
            plot = src.plot.model_copy(deep=True, update={"number": x.number, "act": act.name if act else src.plot.act})
            eps.append(Episode(plot=plot, text=src.text, status="written"))
        else:
            chars = list(dict.fromkeys(c for s in x.sources if archive.source(s) for c in archive.source(s).plot.characters))
            eps.append(Episode(plot=EpisodePlot(number=x.number, act=act.name if act else "기", title=x.title, summary=x.summary,
                                                events=[], characters=chars, emotional_shift="", ending_hook="")))
    p.episodes = eps
    for e in p.episodes:
        storylines.clean_plot(p, e)

    for el in p.elements:
        moved = {"since_ep": _remap(el.since_ep, mapping), "reveal_ep": _remap(el.reveal_ep, mapping),
                 "episodes": sorted({_remap(n, mapping) for n in el.episodes} - {0})}
        lost = (el.since_ep > 0 and not moved["since_ep"]) or (el.reveal_ep > 0 and not moved["reveal_ep"]) \
            or len(moved["episodes"]) < len(set(el.episodes))
        for k, v in moved.items():
            setattr(el, k, v)
        el.added_after = 0
        if lost:
            notes.append(f"인과율 요소 '{el.name}'의 화 번호 일부를 새 화로 옮기지 못했어요")
    for sl in p.storylines:
        b, j = _remap(sl.branch_ep, mapping), _remap(sl.join_ep, mapping)
        if (sl.branch_ep and not b) or (sl.join_ep and not j):
            notes.append(f"이야기 줄기 '{sl.title}'의 갈라지는 화 · 합류하는 화를 새 화로 옮기지 못했어요")
        sl.branch_ep, sl.join_ep = b, j
    if archive.dropped:
        notes.append(f"쓰지 않는 옛 화: {', '.join(map(str, archive.dropped))}화 (원고는 보관함에 남아요)")
    p.archive = archive
    p.conversion = Conversion(at=at or _stamp(), from_total=before.meta.target_episodes, arc_end=0,
                              ending=prop.ending_at, history=0, mode="rebuild", notes=notes)
    return before, notes


def carried_delta(p: Project, n: int) -> StateDelta | None:
    """그대로 둔 화(keep)는 본문이 옛 화와 같으면 옛 상태 변경안을 번호만 바꿔 다시 쓴다. AI 를 부르지 않는다."""
    if p.archive is None:
        return None
    x = p.archive.entry(n)
    if x is None or x.use not in ("keep", "revise") or len(x.sources) != 1:
        return None
    src = p.archive.source(x.sources[0])
    old = next((d for d in reversed(p.archive.history) if d.episode == x.sources[0]), None)
    if src is None or old is None or src.text != p.episode(n).text:
        return None
    d = old.model_copy(deep=True, update={"episode": n})
    for e in d.events:
        e.episode = n
    for f in d.foreshadow_planted:
        f.planted_ep = n
    d.warnings = [f"단편 {x.sources[0]}화 때 승인한 변경안을 다시 써요. 앞 화가 바뀌었으니 확인하고 반영하세요."] + d.warnings
    return d


def propose_rework(llm: LLM, p: Project, n: int) -> Rework:
    """'다듬기'로 고른 화의 옛 본문을 새 자리에 맞게 고친다. 저장하지 않는다."""
    x = p.archive.entry(n) if p.archive else None
    ep = _editable(p, n)
    if x is None or x.use != "revise":
        raise ValueError(f"{n}화는 재구성에서 다듬기로 고른 화가 아니에요")
    rw = llm.json(prompts.writer_system(p), prompts.rework_prompt(p, n), Rework, hint={"episode": n, "text": ep.text})
    rw.text = rw.text.strip()
    if not rw.text or rw.text == ep.text:
        raise ValueError("고친 본문이 원문과 같아요. 다듬을 것을 지도에 적고 다시 받으세요")
    return rw


def accept_rework(p: Project, n: int, text: str, proposed: str = "") -> TextEdit | None:
    """다듬은 본문을 넣는다. proposed 는 AI 가 낸 글로, 작가가 손봤으면 수정 기록에 함께 남긴다."""
    ep = _editable(p, n)
    x = p.archive.entry(n) if p.archive else None
    if x is None or x.use != "revise":
        raise ValueError(f"{n}화는 재구성에서 다듬기로 고른 화가 아니에요")
    new = text.strip()
    if not new:
        raise ValueError("본문이 비었어요")
    old = ep.text
    ep.text = new
    edit = record_typed(p, n, old, new)
    if edit is not None:
        edit.source, edit.instruction = "ai", x.note or "재구성 다듬기"
        edit.proposed = proposed.strip() if proposed.strip() and proposed.strip() != new else ""
    return edit


# ---------- 3-1. 대화로 구조와 플롯 다듬기 ----------

LOCKED = ("written", "finalized")  # 본문이 있어 플롯을 바꿀 수 없는 상태
CHAT_KEEP = 200  # 화면별로 남겨 두는 대화 수


def revise_plot(llm: LLM, p: Project, message: str, scope: ChatScope | None = None) -> PlotRevision:
    """작가의 말에 대한 답과 변경안을 만든다. 저장하지 않는다. 쓸 수 없는 부분은 빼고 답에 이유를 덧붙인다.
    scope 는 화면이 알려 주는 대상(고른 아크, 다음 아크 초안)과 보고 있는 구간 · 화, 방향 여러 안 모드다."""
    message = message.strip()
    if not message:
        raise ValueError("메시지가 비었어요")
    scope = scope or ChatScope()
    target, focus = chat_target(p, scope.target)
    scope = scope.model_copy(update={"target": target})
    if target == "next" and scope.draft is not None and scope.draft.arc.start_ep != next_arc_start(p):
        scope.draft = None  # 그 사이 아크가 붙어 초안 자리가 맞지 않는다
    rev = llm.json(
        prompts.SYSTEM_PLOT_CHAT, prompts.plot_chat_prompt(p, message, scope), PlotRevision,
        hint={"message": message, "arc": (focus.acts if focus else scope.draft.arc.acts if scope.draft else [] if p.serial else p.arc),
              "episodes": [e.plot for e in p.episodes], "total": p.meta.target_episodes, "serial": p.serial,
              "target": target, "focus": focus, "draft": scope.draft, "mode": scope.mode, "parts": p.parts,
              "start": next_arc_start(p) if p.serial else 0, "limit": chat_next_limit(p) if p.serial else 0},
    )
    return clean_revision(p, rev, scope)


def focus_arc(p: Project) -> StoryArc | None:
    """장편 플롯 대화가 따로 고르지 않았을 때 고치는 아크: 아직 본문이 없는 화가 있는 첫 아크, 없으면 마지막 아크."""
    status = {e.plot.number: e.status for e in p.episodes}
    arcs = sorted(p.story_arcs, key=lambda s: s.start_ep)
    for a in arcs:
        if any(status.get(n, "draft") not in LOCKED for n in range(a.start_ep, a.end_ep + 1)):
            return a
    return arcs[-1] if arcs else None


def chat_target(p: Project, target: str = "") -> tuple[str, StoryArc | None]:
    """플롯 대화가 겨냥하는 곳과 그 아크. 돌려주는 이름은 기록에 남길 실제 대상이다:
    단편은 늘 '' (작품 전체), 장편은 'arc:N' 이나 'next' (다음 아크 기획). 비우면 focus_arc, 아크가 없으면 다음 아크."""
    if not p.serial:
        return "", None
    target = (target or "").strip()
    if target.startswith("arc:"):
        try:
            number = int(target[4:])
        except ValueError:
            raise ValueError(f"모르는 대화 대상이에요: {target}") from None
        a = next((x for x in p.story_arcs if x.number == number), None)
        if a is None:
            raise ValueError(f"아크 {number}이(가) 없어요. 아크를 다시 고르세요")
        return f"arc:{a.number}", a
    if target not in ("", "next"):
        raise ValueError(f"모르는 대화 대상이에요: {target}")
    a = focus_arc(p) if target == "" else None
    if a:
        return f"arc:{a.number}", a
    if next_arc_start(p) > p.meta.target_episodes:
        raise ValueError(f"총 {p.meta.target_episodes}화까지 아크가 모두 있어요. 고칠 아크를 고르세요")
    return "next", None


def chat_next_limit(p: Project) -> int:
    """다음 아크가 끝날 수 있는 마지막 화: 그 화가 든 부의 끝, 부가 없으면 작품 끝."""
    part = p.part_for(next_arc_start(p))
    return part.end_ep if part else p.meta.target_episodes


def chat_where(p: Project, scope: ChatScope) -> str:
    """작가가 보낼 때 보고 있던 곳 한 줄 (예: 아크 3 (25~40화) · 승 구간 (28~33화) · 30화 「시험장」)."""
    target, focus = chat_target(p, scope.target)
    out = []
    if focus:
        out.append(f"아크 {focus.number} ({focus.start_ep}~{focus.end_ep}화)")
    elif target == "next":
        out.append(f"다음 아크 기획 ({next_arc_start(p)}화부터)")
    acts = focus.acts if focus else [] if p.serial else p.arc
    act = next((a for a in acts if a.name == scope.act), None)
    if act:
        out.append(f"{act.name} 구간 ({act.start_ep}~{act.end_ep}화)")
    e = next((x for x in p.episodes if x.plot.number == scope.episode), None) if scope.episode else None
    if e:
        out.append(f"{e.plot.number}화" + (f" 「{e.plot.title}」" if e.plot.title else ""))
    return " · ".join(out)


ARC_EDIT_FIELDS = ("title", "goal", "conflict", "payoff", "cast", "payoffs", "pov")


def arc_end_problem(p: Project, a: StoryArc, end: int) -> str:
    """아크 a 의 끝 화를 end 로 바꿀 수 없는 까닭. 바꿀 수 있으면 빈 글."""
    if a.start_ep != max(x.start_ep for x in p.story_arcs):
        return f"아크 {a.number} 뒤에 다음 아크가 이어져 끝 화는 바꾸지 않았어요."
    size = end - a.start_ep + 1
    if not ARC_MIN <= size <= ARC_MAX:
        return f"아크 길이 {size}화는 쓸 수 없어 끝 화는 그대로 뒀어요 ({ARC_MIN}~{ARC_MAX}화)."
    part = p.part_for(a.start_ep)
    limit = part.end_ep if part else p.meta.target_episodes
    if end > limit:
        return f"{end}화는 {'부' if part else '작품'} 끝({limit}화)을 넘어 끝 화는 그대로 뒀어요."
    stuck = [e.plot.number for e in p.episodes if end < e.plot.number <= a.end_ep and e.status != "draft"]
    if stuck:
        return f"{end}화로 줄이면 확정했거나 본문이 있는 화({stuck})가 빠져 끝 화는 그대로 뒀어요."
    return ""


def _clean_arc_edit(p: Project, rev: PlotRevision, a: StoryArc, notes: list[str]) -> int:
    """이미 있는 아크의 칸 변경안을 다듬고, 변경안을 적용했을 때의 끝 화를 돌려준다."""
    e = rev.arc
    if not e.title.strip():
        rev.arc = ArcEdit()
        return a.end_ep
    end = e.end_ep or a.end_ep
    if end != a.end_ep and (why := arc_end_problem(p, a, end)):
        notes.append(why)
        end = a.end_ep
    e.end_ep = end if end != a.end_ep else 0
    known = {c.id for c in p.characters} | {c.id for c in p.cast_candidates}
    e.cast = [c for c in dict.fromkeys(e.cast) if c in known]
    open_fs = {f.id for f in p.foreshadows if f.status == "open"} | set(a.payoffs)
    e.payoffs = [f for f in dict.fromkeys(e.payoffs) if f in open_fs]
    if not e.end_ep and all(getattr(e, k) == getattr(a, k) for k in ARC_EDIT_FIELDS):
        rev.arc = ArcEdit()
    return end


def _clean_next_arc(p: Project, rev: PlotRevision, draft: ArcProposal | None, notes: list[str]) -> None:
    """다음 아크 안: 아크 칸과 구조를 한 덩어리(제안 ArcProposal)로 맞춘다. 칸이 비면 지금 초안의 칸을 쓴다."""
    if not rev.arc.title.strip() and not rev.acts:
        rev.arc, rev.acts = ArcEdit(), []
        return
    base = draft.arc if draft else None
    fields = rev.arc if rev.arc.title.strip() else (ArcEdit(**base.model_dump(include=set(ARC_EDIT_FIELDS))) if base else None)
    if fields is None:
        notes.append("다음 아크의 제목과 목표가 없어 구조 변경안을 뺐어요.")
        rev.arc, rev.acts = ArcEdit(), []
        return
    start = next_arc_start(p)
    end = rev.arc.end_ep or (base.end_ep if base else 0)
    if not end:
        size = max(rev.acts, key=lambda x: x.end_ep).end_ep - start + 1 if rev.acts else p.meta.arc_length
        end = start + max(size, ARC_MIN) - 1
    end = min(end, chat_next_limit(p))
    acts = rev.acts or (base.acts if base else [])  # 끝 화만 바뀌면 clean_arc 가 구간 비율을 살려 맞춘다
    if not acts:
        acts = [Act(name=n, start_ep=s, end_ep=t, goal="") for n, (s, t) in zip(ACT_NAMES, act_ranges(end, start))]
    arc = StoryArc(number=len(p.story_arcs) + 1, start_ep=start, end_ep=end, acts=[x.model_copy(deep=True) for x in acts],
                   **fields.model_dump(include=set(ARC_EDIT_FIELDS)))
    chars = {c.id: c for c in (draft.new_characters if draft else [])} | {c.id: c for c in rev.new_characters}
    try:
        prop = clean_arc(p, ArcProposal(arc=arc, new_characters=list(chars.values())))
    except ValueError as e:
        notes.append(f"다음 아크 안이 맞지 않아 뺐어요: {e}")
        rev.arc, rev.acts = ArcEdit(), []
        return
    if prop.reply:
        notes.append(prop.reply.replace("※", "").strip())
    rev.arc = ArcEdit(**prop.arc.model_dump(include=set(ARC_EDIT_FIELDS)), end_ep=prop.arc.end_ep)
    rev.acts = prop.arc.acts
    rev.new_characters = prop.new_characters
    if base and rev.arc.model_dump() == ArcEdit(**base.model_dump(include=set(ARC_EDIT_FIELDS)), end_ep=base.end_ep).model_dump() \
            and [x.model_dump() for x in rev.acts] == [x.model_dump() for x in base.acts]:
        rev.arc, rev.acts = ArcEdit(), []


def _clean_parts_edit(p: Project, rev: PlotRevision, notes: list[str]) -> None:
    if not rev.parts:
        return
    parts = sorted(rev.parts, key=lambda x: x.start_ep)
    for i, x in enumerate(parts, 1):
        x.number, x.summary = i, ""
    rev.parts = parts
    if [x.model_dump(exclude={"summary"}) for x in parts] == [x.model_dump(exclude={"summary"}) for x in p.parts]:
        rev.parts = []
        return
    try:
        apply_series(p.model_copy(deep=True), SeriesPlan(parts=parts))
    except ValueError as e:
        notes.append(f"부 구성 변경안이 맞지 않아 뺐어요: {e}")
        rev.parts = []


def clean_revision(p: Project, rev: PlotRevision, scope: ChatScope | None = None) -> PlotRevision:
    scope = scope or ChatScope()
    notes: list[str] = []
    target, focus = chat_target(p, scope.target)
    if scope.mode == "options":  # 방향만 받는다. 변경안은 작가가 방향을 고른 뒤 따로 만든다
        rev.options = [x for x in rev.options if x.title.strip()][:4]
        rev.total_episodes, rev.acts, rev.episodes, rev.arc, rev.parts = 0, [], [], ArcEdit(), []
        rev.new_characters, rev.new_places = [], []
        return rev
    rev.options = []
    if not p.serial:
        rev.arc, rev.parts = ArcEdit(), []
    if p.serial and rev.total_episodes:
        notes.append("장편은 총 화수를 설정 도우미에서 바꿔서 화수 변경을 뺐어요.")
        rev.total_episodes = 0
    total = rev.total_episodes if rev.total_episodes and rev.total_episodes != p.meta.target_episodes else 0
    if total and not 1 <= total <= 100:
        notes.append(f"총 화수 {total}화는 쓸 수 없어 뺐어요.")
        total = 0
    rev.total_episodes = total
    _clean_parts_edit(p, rev, notes)
    last = total or p.meta.target_episodes
    arc = p.arc
    if target == "next":
        _clean_next_arc(p, rev, scope.draft, notes)
        arc, last = p.beats(), p.planned_until()
    else:
        end = _clean_arc_edit(p, rev, focus, notes) if focus else 0
        current_acts = focus.acts if focus else p.arc
        acts = sorted(rev.acts, key=act_order)
        if focus and end != focus.end_ep and not acts:
            plan = ArcPlan(acts=[x.model_copy(deep=True) for x in focus.acts])
            fit_arc(plan, end, focus.start_ep)  # 끝 화만 바꾸면 구간 비율을 살려 새 범위에 맞춘다
            acts = plan.acts
        if acts and [a.model_dump() for a in acts] == [a.model_dump() for a in current_acts] and not total:
            acts = []
        if acts:
            try:
                if focus and end != focus.end_ep:
                    plan = ArcPlan(acts=acts)
                    fit_arc(plan, end, focus.start_ep)  # 끝 화가 바뀌면 AI 가 낸 구간 비율을 새 범위에 맞춘다
                    acts = plan.acts
                elif focus:
                    validate_arc(ArcPlan(acts=acts), focus.end_ep, focus.start_ep)
                else:
                    validate_arc(ArcPlan(acts=acts), total or p.meta.target_episodes)
            except ValueError as e:
                notes.append(f"구조 변경안이 맞지 않아 뺐어요: {e}")
                acts = []
                if focus and end != focus.end_ep:
                    notes.append("끝 화 변경도 구조와 함께여야 해서 뺐어요.")
                    rev.arc.end_ep, end = 0, focus.end_ep
                    if all(getattr(rev.arc, k) == getattr(focus, k) for k in ARC_EDIT_FIELDS):
                        rev.arc = ArcEdit()
        if total and not acts:
            notes.append("화수를 바꾸려면 구조도 함께 바꿔야 해서 화수 변경을 뺐어요.")
            rev.total_episodes = total = 0
            last = p.meta.target_episodes
        rev.acts = acts
        if focus:
            arc = [a for a in p.beats() if not focus.start_ep <= a.start_ep <= focus.end_ep] + (acts or focus.acts)
            last = end if focus.end_ep == p.planned_until() else p.planned_until()
        else:
            arc = acts or p.arc
    status = {e.plot.number: e.status for e in p.episodes}
    current = {e.plot.number: e.plot.model_dump() for e in p.episodes}
    keep, seen = [], set()
    for e in rev.episodes:
        n = e.number
        if n in seen or not 1 <= n <= last:
            notes.append(f"{n}화 변경안은 범위를 벗어나 뺐어요.")
            continue
        if status.get(n) in LOCKED:
            notes.append(f"{n}화는 본문이 있어 플롯 변경안을 뺐어요.")
            continue
        act = next((a for a in arc if a.start_ep <= n <= a.end_ep), None)
        if act:
            e.act = act.name
        cur = current.get(n)
        if cur and (cur["storyline"] or cur["threads"]) and not (e.storyline or e.threads):
            e.storyline, e.threads = cur["storyline"], list(cur["threads"])  # 작가가 붙인 줄기는 AI 가 빠뜨려도 지키기
        if current.get(n) == e.model_dump():
            continue
        seen.add(n)
        keep.append(e)
    rev.episodes = sorted(keep, key=lambda e: e.number)
    arc_chars = rev.new_characters if target == "next" and rev.arc.title else []
    rev.new_characters = arc_chars + [c for c in clean_new_characters(p, rev.new_characters, rev.episodes)
                                      if c.id not in {x.id for x in arc_chars}]
    rev.new_places, _ = elements.clean_places(p, rev.new_places, plots_text(rev.episodes))
    if notes:
        rev.reply = rev.reply.rstrip() + "\n\n※ " + " ".join(notes)
    return rev


def record_chat(p: Project, topic: str, message: str, rev: PlotRevision, scope: ChatScope | None = None) -> ChatMessage:
    """작가의 말과 AI 답을 대화 기록에 남긴다. 대상(아크 · 다음 아크)과 보던 곳도 함께 남겨 반영과 다음 대화에 쓴다."""
    from datetime import datetime, timezone

    scope = scope or ChatScope()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    chat = p.chat(topic)
    target, _ = chat_target(p, scope.target)
    reply = ChatMessage(role="assistant", text=rev.reply, revision=rev, at=now, target=target, mode=scope.mode)
    if not (rev.has_changes() or rev.options):
        reply.revision = None
    asked = ChatMessage(role="user", text=message.strip(), at=now, where=chat_where(p, scope), mode=scope.mode)
    chat.messages += [asked, reply]
    chat.messages = chat.messages[-CHAT_KEEP:]
    return reply


def apply_revision(p: Project, rev: PlotRevision, acts: bool, episodes: list[int], *,
                   arc: bool = False, parts: bool = False, target: str = "") -> list[str]:
    """변경안에서 고른 부분만 반영한다. 본문이 있는 화는 바꾸지 않고, 확정된 화를 바꾸면 초안으로 돌린다.
    target 은 변경안을 만들 때의 대상(ChatMessage.target). 다음 아크('next')의 아크 칸과 구조는 화면의 초안에 들어가므로
    여기서는 부 구성과 화만 반영한다. 반영한 부분 이름('parts', 'arc', 'acts', 화 번호)을 돌려준다."""
    target, focus = chat_target(p, target)
    applied: list[str] = []
    if target == "next":
        acts = arc = False
    if focus and rev.arc.end_ep and (arc or acts):
        acts = arc = True  # 끝 화가 바뀌면 구간 범위도 함께 바뀐다
    if parts and rev.parts:
        apply_series(p, SeriesPlan(parts=rev.parts))
        applied.append("parts")
    total = p.meta.target_episodes
    new_arc = p.arc
    end = focus.end_ep if focus else 0
    if focus and arc and rev.arc.title:
        if rev.arc.end_ep and (why := arc_end_problem(p, focus, rev.arc.end_ep)):
            raise ValueError(why.replace("그대로 뒀어요", "바꿀 수 없어요").replace("바꾸지 않았어요", "바꿀 수 없어요"))
        end = rev.arc.end_ep or focus.end_ep
    if acts and rev.acts:
        if focus:
            validate_arc(ArcPlan(acts=rev.acts), end, focus.start_ep)
        else:
            total = rev.total_episodes or total
            validate_arc(ArcPlan(acts=rev.acts), total)
        new_arc = [a.model_copy(deep=True) for a in rev.acts]
    if p.serial:  # 마지막 아크의 끝 화를 바꾸면 기획한 화도 따라 늘거나 준다
        total = end if focus and focus.end_ep == p.planned_until() else p.planned_until()
    by_no = {e.plot.number: e for e in p.episodes}
    cut = [n for n in by_no if n > total]
    stuck = [n for n in cut if by_no[n].status != "draft"]
    if stuck:
        raise ValueError(f"{total}화로 줄이면 확정됐거나 본문이 있는 화({stuck})가 빠져요. 먼저 초안으로 되돌리세요")
    picked = {e.number: e for e in rev.episodes if e.number in set(episodes)}
    for n, plot in picked.items():
        if n > total:
            raise ValueError(f"{n}화는 총 {total}화 밖이에요. 구조 변경을 함께 고르세요")
        cur = by_no.get(n)
        if cur and cur.status in LOCKED:
            raise ValueError(f"{n}화는 본문이 있어 플롯을 바꿀 수 없어요")
    if focus and arc and rev.arc.title:
        old_end = focus.end_ep
        for k in ARC_EDIT_FIELDS:
            setattr(focus, k, list(getattr(rev.arc, k)) if isinstance(getattr(rev.arc, k), list) else getattr(rev.arc, k))
        focus.end_ep = end
        for f in p.foreshadows:  # 새로 회수하기로 한 복선과 끝 화를 따라가던 회수 예정 화를 맞춘다
            if f.id in focus.payoffs and f.status == "open" and f.due_ep in (0, old_end):
                f.due_ep = end
        applied.append("arc")
    if acts and rev.acts:
        if focus:
            focus.acts = new_arc
        else:
            p.arc = new_arc
            p.meta.target_episodes = total
        applied.append("acts")
    if "acts" in applied or "arc" in applied:
        for n in cut:
            del by_no[n]
    if focus and "arc" in applied:
        validate_story_arcs(p)
    for n, plot in picked.items():
        by_no[n] = Episode(plot=plot.model_copy(deep=True))  # 확정된 화도 내용이 바뀌면 다시 확정한다
        storylines.clean_plot(p, by_no[n])
        applied.append(str(n))
    p.episodes = [by_no[k] for k in sorted(by_no)]
    add_candidates(p, clean_new_characters(p, rev.new_characters, list(picked.values())))
    elements.add_place_candidates(p, rev.new_places, plots_text(list(picked.values())))
    for e in p.episodes:
        act = p.act_for(e.plot.number)
        if act and e.status not in LOCKED:
            e.plot.act = act.name
    return applied



def _plot_message(p: Project, i: int, topic: str = "plot") -> ChatMessage:
    msgs = p.chat(topic).messages
    if not 0 <= i < len(msgs) or msgs[i].revision is None:
        raise KeyError("변경안이 있는 메시지가 아니에요")
    return msgs[i]


def _plot_undo_state(p: Project, target: str) -> PlotUndo:
    """플롯 대화 적용 취소에 쓸 지금 값. 화는 호출자가 채운다."""
    _, focus = chat_target(p, target)
    return PlotUndo(target_episodes=p.meta.target_episodes, acts=[a.model_copy(deep=True) for a in p.arc],
                    arc=focus.model_copy(deep=True) if focus else None, parts=[x.model_copy(deep=True) for x in p.parts],
                    foreshadows=[ForeshadowDue(id=f.id, due_ep=f.due_ep) for f in p.foreshadows if f.status == "open"])


def apply_plot_chat(p: Project, i: int, acts: bool, episodes: list[int], *, arc: bool = False, parts: bool = False,
                    draft: list[str] | None = None, topic: str = "plot") -> list[str]:
    """i 번째 플롯 대화 변경안에서 고른 부분만 반영한다 (apply_revision). 적용 전 값과 적용 직후 값을 메시지에 남겨
    적용 취소(undo_plot_chat)에 쓴다. draft 는 다음 아크 변경안에서 화면의 초안에 넣은 부분('arc')으로, 작품은 바꾸지 않고 기록만 한다.
    적용한 부분 이름을 돌려준다."""
    m = _plot_message(p, i, topic)
    if m.outcome:
        raise ValueError("이미 처리한 변경안이에요")
    drafted = [x for x in draft or [] if x == "arc"] if m.target == "next" and m.revision.arc.title else []
    if not (acts or episodes or arc or parts or drafted):
        raise ValueError("적용할 부분을 고르세요")
    target, _ = chat_target(p, m.target)  # 대상이 없던 옛 변경안도 적용 전과 뒤를 같은 아크로 잰다
    old = {e.plot.number: e.model_copy(deep=True) for e in p.episodes}
    before = _plot_undo_state(p, target)
    done = apply_revision(p, m.revision, acts, episodes, arc=arc, parts=parts, target=target)
    after = _plot_undo_state(p, target)
    now = {e.plot.number for e in p.episodes}
    touched = {int(x) for x in done if x.isdigit()}
    before.episodes = [old[n] for n in sorted(old) if n in touched or n not in now]  # 바꾼 화와 줄이며 뺀 화
    after.episodes = [e.model_copy(deep=True) for e in p.episodes if e.plot.number in touched]
    m.applied, m.outcome = drafted + done, "applied"
    m.plot_before, m.plot_after = (before, after) if done else (None, None)
    return m.applied


def _same_plot(a: EpisodePlot, b: EpisodePlot) -> bool:
    """구간 이름(act)은 구조를 따라 바뀌므로 빼고 비교한다."""
    return a.model_dump(exclude={"act"}) == b.model_dump(exclude={"act"})


def _arc_same(a: StoryArc, ref: StoryArc, part: str) -> bool:
    if part == "acts":
        return a.acts == ref.acts
    return a.end_ep == ref.end_ep and all(getattr(a, k) == getattr(ref, k) for k in ARC_EDIT_FIELDS)


def undo_plot_chat(p: Project, i: int, topic: str = "plot") -> tuple[list[str], list[str], list[str]]:
    """적용한 플롯 변경안을 취소한다. 적용한 부분마다 지금 값이 적용 직후 값과 같을 때만 적용 전으로 돌린다.
    그 뒤에 작가가 다시 고쳤거나 다시 확정한 화, 본문을 쓴 화, 남은 화가 있어 줄일 수 없는 구조는 그대로 둔다.
    (되돌린 부분, 그대로 둔 부분, 그대로 둔 까닭) 을 돌려준다. 변경안은 다시 고를 수 있게 연다."""
    m = _plot_message(p, i, topic)
    before, after = m.plot_before, m.plot_after
    if m.outcome != "applied" or before is None or after is None:
        raise ValueError("적용을 취소할 수 있는 변경안이 아니에요")
    old = {e.plot.number: e for e in before.episodes}
    new = {e.plot.number: e for e in after.episodes}
    by_no = {e.plot.number: e for e in p.episodes}
    done: list[str] = []
    kept: list[str] = []
    why: list[str] = []

    def keep(part: str, reason: str) -> None:
        kept.append(part)
        why.append(reason)

    def bring_back_cut() -> None:  # 구조를 줄이며 뺀 화를 다시 넣는다 (그 자리에 다른 화가 생겼으면 그대로)
        for n, e in old.items():
            if n not in new and n not in by_no:
                by_no[n] = e.model_copy(deep=True)

    for x in [x for x in m.applied if x.isdigit()]:
        n = int(x)
        cur, aft = by_no.get(n), new.get(n)
        if cur is None:
            if n in old:
                keep(x, "그 뒤에 빠짐")
            else:
                done.append(x)  # 더했던 새 화가 이미 없다
        elif cur.status in LOCKED:
            keep(x, "본문을 씀")
        elif cur.status != "draft":
            keep(x, "적용 뒤 다시 확정함")
        elif aft is None or not _same_plot(cur.plot, aft.plot):
            keep(x, "적용 뒤 다시 고침")
        else:
            if n in old:
                by_no[n] = old[n].model_copy(deep=True)
            else:
                del by_no[n]
            done.append(x)

    struct = [x for x in ("arc", "acts") if x in m.applied]
    if before.arc is not None and after.arc is not None and struct:
        a = next((x for x in p.story_arcs if x.number == before.arc.number), None)
        linked = after.arc.end_ep != before.arc.end_ep  # 끝 화가 바뀌면 칸과 구간을 함께 돌린다
        for group in [struct] if linked else [[x] for x in struct]:
            if a is None:
                for x in group:
                    keep(x, f"아크 {before.arc.number}이(가) 없어짐")
                continue
            if not all(_arc_same(a, after.arc, x) for x in group):
                for x in group:
                    keep(x, "적용 뒤 다시 고침")
                continue
            left = sorted(n for n in by_no if before.arc.end_ep < n <= after.arc.end_ep) if linked else []
            if left:
                for x in group:
                    keep(x, f"늘린 범위에 남은 화가 있음 ({left[0]}~{left[-1]}화)")
                continue
            keep_arc = a.model_copy(deep=True)
            if "arc" in group:
                for k in ARC_EDIT_FIELDS:
                    v = getattr(before.arc, k)
                    setattr(a, k, list(v) if isinstance(v, list) else v)
                a.end_ep = before.arc.end_ep
            if "acts" in group:
                a.acts = [x.model_copy(deep=True) for x in before.arc.acts]
            try:
                validate_story_arcs(p)
            except ValueError as e:
                for k, v in keep_arc:
                    setattr(a, k, v)
                for x in group:
                    keep(x, f"지금 아크 범위와 맞지 않음: {e}")
                continue
            if "arc" in group:
                due = {d.id: d.due_ep for d in after.foreshadows}
                for d in before.foreshadows:
                    f = next((y for y in p.foreshadows if y.id == d.id), None)
                    if f and d.id in due and due[d.id] != d.due_ep and f.due_ep == due[d.id]:
                        f.due_ep = d.due_ep
            if linked:
                bring_back_cut()
            done += group
    elif "acts" in m.applied and before.arc is None:
        if p.arc != after.acts or p.meta.target_episodes != after.target_episodes:
            keep("acts", "적용 뒤 다시 고침")
        elif left := sorted(n for n in by_no if n > before.target_episodes):
            keep("acts", f"총 {before.target_episodes}화 밖에 남은 화가 있음 ({left[0]}~{left[-1]}화)")
        else:
            p.arc = [x.model_copy(deep=True) for x in before.acts]
            p.meta.target_episodes = before.target_episodes
            bring_back_cut()
            done.append("acts")

    if "parts" in m.applied:
        if p.parts != after.parts:
            keep("parts", "적용 뒤 다시 고침")
        else:
            cur_parts = p.parts
            p.parts = [x.model_copy(deep=True) for x in before.parts]
            try:
                validate_story_arcs(p)
                done.append("parts")
            except ValueError as e:
                p.parts = cur_parts
                keep("parts", f"지금 아크 범위와 맞지 않음: {e}")

    p.episodes = [by_no[k] for k in sorted(by_no)]
    for e in p.episodes:
        act = p.act_for(e.plot.number)
        if act and e.status not in LOCKED:
            e.plot.act = act.name
    sync_candidates(p)
    m.outcome, m.applied, m.plot_before, m.plot_after = "", [], None, None
    return done, kept, why

# ---------- 3-2. 이야기 줄기: 메인에서 갈라지는 서브플롯 · 회상 · 외전 ----------

def suggest_storyline(llm: LLM, p: Project, note: str = "", kind: str = "") -> StorylineProposal:
    """이야기 줄기 하나와 그 줄기가 들어갈 화를 제안한다. 저장하지 않는다."""
    prop = llm.json(prompts.SYSTEM_PLANNER, prompts.storyline_prompt(p, note, kind), StorylineProposal,
                    hint={"note": note, "kind": kind, "episodes": [e.plot.number for e in p.episodes],
                          "characters": [c.id for c in p.characters], "id": storylines.new_id(p)})
    return clean_storyline(p, prop)


def clean_storyline(p: Project, prop: StorylineProposal) -> StorylineProposal:
    """id 를 새로 매기고, 없는 인물과 없는 화, 본문이 있는 화를 뺀다. 뺀 이유는 reply 끝에 붙인다."""
    s = prop.storyline
    s.id = storylines.new_id(p)
    ids = {c.id for c in p.characters}
    notes = []
    gone = [c for c in s.focus if c not in ids]
    if gone:
        s.focus = [c for c in s.focus if c in ids]
        notes.append(f"없는 인물({', '.join(gone)})은 중심 인물에서 뺐어요.")
    have = {e.plot.number: e for e in p.episodes}
    locked = sorted({n for n in prop.episodes + prop.threads if n in have and have[n].text})
    missing = sorted({n for n in prop.episodes + prop.threads if n not in have})
    prop.episodes = sorted({n for n in prop.episodes if n in have and not have[n].text})
    prop.threads = sorted({n for n in prop.threads if n in have and not have[n].text and n not in prop.episodes})
    if locked:
        notes.append(f"본문이 있는 화({', '.join(map(str, locked))})는 붙이지 않았어요. 필요하면 직접 표시하세요.")
    if missing:
        notes.append(f"아직 플롯이 없는 화({', '.join(map(str, missing))})는 뺐어요. 플롯을 만든 뒤 붙이세요.")
    total = p.meta.target_episodes
    s.branch_ep = s.branch_ep if 0 < s.branch_ep <= total else 0
    s.join_ep = s.join_ep if 0 < s.join_ep <= total and s.join_ep >= s.branch_ep else 0
    if notes:
        prop.reply = (prop.reply + " " + " ".join(notes)).strip()
    return prop


def apply_storyline(p: Project, prop: StorylineProposal, episodes: list[int] | None = None,
                    threads: list[int] | None = None) -> Storyline:
    """줄기를 더하고 고른 화에 붙인다. 플롯 내용은 바꾸지 않으므로 확정된 화도 확정 상태를 지킨다."""
    s = prop.storyline.model_copy(deep=True)
    if not s.id or p.storyline(s.id):
        s.id = storylines.new_id(p)
    if not s.title.strip():
        raise ValueError("줄기 이름을 적으세요")
    episodes = prop.episodes if episodes is None else episodes
    threads = prop.threads if threads is None else threads
    have = {e.plot.number for e in p.episodes}
    missing = sorted({n for n in episodes + threads if n not in have})
    if missing:
        raise ValueError(f"플롯이 없는 화({', '.join(map(str, missing))})에는 줄기를 붙일 수 없어요. 플롯을 먼저 만드세요")
    p.storylines.append(s)
    for n in episodes:
        storylines.tag(p, n, s.id, "main")
    for n in threads:
        storylines.tag(p, n, s.id, "thread")
    return s


def validate_storylines(p: Project) -> None:
    """줄기 id 가 겹치지 않고, 화에 붙은 줄기가 모두 있는지 본다 (화면 저장용)."""
    ids = [s.id for s in p.storylines]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup or "" in ids:
        raise ValueError(f"이야기 줄기 id가 비었거나 겹쳐요: {', '.join(dup) or '빈 id'}")
    for e in p.episodes:
        bad = [x for x in [e.plot.storyline, *e.plot.threads] if x and x not in ids]
        if bad:
            raise ValueError(f"{e.plot.number}화에 없는 이야기 줄기가 붙어 있어요: {', '.join(bad)}")


def validate_relationships(p: Project) -> None:
    """관계는 서로 다른 두 인물 사이에 한 쌍씩만 둔다 (화면 저장용). 겹치면 관계 계산이 한쪽만 쓴다."""
    seen: dict[frozenset, int] = {}
    names = {c.id: c.name or c.id for c in p.characters}
    for i, r in enumerate(p.relationships, 1):
        who = f"{names.get(r.a, r.a)} ↔ {names.get(r.b, r.b)}"
        if r.a == r.b:
            raise ValueError(f"{i}번째 관계({who})가 같은 인물끼리예요. 인물 B를 바꾸거나 지우세요")
        k = frozenset((r.a, r.b))
        if k in seen:
            raise ValueError(f"{who} 관계가 {seen[k]}번째와 {i}번째에 두 번 있어요. 하나를 지우세요")
        seen[k] = i


def validate_characters(p: Project, before: Project | None = None) -> None:
    """인물 id 는 관계 · 상태 · 플롯이 인물을 찾는 열쇠라 비거나 겹치면 안 된다 (화면 저장용).
    관계가 없는 인물을 가리키게 되는 저장도 받지 않는다. id 를 바꾸면 그렇게 된다.
    before(디스크 것)에서 이미 끊겨 있던 관계는 옛 데이터라 막지 않는다."""
    seen: set[str] = set()
    for i, c in enumerate(p.characters, 1):
        if not c.id.strip():
            raise ValueError(f"{i}번째 인물({c.name or '이름 없음'})의 id가 비었어요")
        if c.id in seen:
            raise ValueError(f"인물 id '{c.id}'가 두 인물에 겹쳐요. 한 인물에 하나씩 둬요")
        seen.add(c.id)
    known_before = {c.id for c in before.characters} if before else set()
    old = {(r.a, r.b) for r in before.relationships if r.a not in known_before or r.b not in known_before} if before else set()
    for r in p.relationships:
        missing = [x for x in (r.a, r.b) if x not in seen]
        if missing and (r.a, r.b) not in old:
            raise ValueError(f"관계 {r.a} ↔ {r.b}가 없는 인물({', '.join(missing)})을 가리켜요. "
                             "인물 id를 바꾸면 관계와 상태가 끊겨요. id를 되돌리거나 그 관계를 지우세요")


def remove_storyline(p: Project, sid: str) -> None:
    """줄기를 지우고 붙은 화를 메인으로 되돌린다. 본문은 그대로다."""
    storylines.get(p, sid)
    storylines.untag_all(p, sid)
    p.storylines = [s for s in p.storylines if s.id != sid]


# ---------- 3-3. 인과율: 새 요소가 닿는 곳 ----------

def analyze_impact(llm: LLM, p: Project, eid: str) -> ImpactReport:
    """요소 하나의 영향 보고서를 만든다. 저장하지 않는다. 근거를 찾을 수 없는 지적은 뺀다."""
    el = elements.get(p, eid)
    if not el.name.strip() or not el.description.strip():
        raise ValueError("요소의 이름과 설명을 먼저 적으세요")
    linked = {lk.episode for lk in elements.links(p, el)}
    rep = llm.json(
        prompts.SYSTEM_IMPACT, prompts.impact_prompt(p, el, linked), ImpactReport,
        hint={"element": el, "episodes": p.episodes},
    )
    return clean_impact(p, rep)


def _quoted(p: Project, target: str, n: int, quote: str) -> bool:
    """지적의 인용이 실제로 그 자리에 있는가."""
    if target == "본문":
        e = next((e for e in p.episodes if e.plot.number == n), None)
        return bool(e and elements.find(e.text, quote))
    if target == "플롯":
        e = next((e for e in p.episodes if e.plot.number == n), None)
        return bool(e and elements.find(elements.plot_text(e), quote))
    if target == "확정 사실":
        return bool(elements.find("\n".join(p.facts), quote))
    setting = p.model_dump(include={"meta": True, "world": True, "characters": True, "relationships": True, "secrets": True,
                                    "elements": {"__all__": {"name", "aliases", "description"}},
                                    "parts": True, "story_arcs": {"__all__": {"title", "goal", "conflict", "payoff", "summary"}}})
    return bool(elements.find("\n".join(_strings(setting)), quote))


def _strings(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        v = v.values()
    return [s for x in v for s in _strings(x)] if isinstance(v, (list, tuple, type({}.values()))) else []


def clean_impact(p: Project, rep: ImpactReport) -> ImpactReport:
    notes: list[str] = []
    keep = [c for c in rep.conflicts if _quoted(p, c.target, c.episode, c.quote)]
    if len(keep) < len(rep.conflicts):
        notes.append(f"원문에서 인용을 찾지 못한 지적 {len(rep.conflicts) - len(keep)}개는 뺐어요.")
    rep.conflicts = keep
    patches, seen = [], set()
    for t in rep.patches:
        e = next((e for e in p.episodes if e.plot.number == t.episode), None)
        if not e or not e.text or not elements.find(e.text, t.quote):
            notes.append(f"{t.episode}화 본문에서 '{t.quote[:20]}' 문장을 찾지 못해 그 수정안은 뺐어요.")
            continue
        if t.replacement.strip() == t.quote.strip() or (t.episode, t.quote) in seen:
            continue
        seen.add((t.episode, t.quote))
        patches.append(t)
    rep.patches = patches
    rep.new_facts = [f for f in dict.fromkeys(x.strip() for x in rep.new_facts) if f and f not in p.facts]
    rev = clean_revision(p, PlotRevision(reply=rep.summary, episodes=rep.episodes))
    rep.summary, rep.episodes = rev.reply, rev.episodes
    if notes:
        rep.summary = rep.summary.rstrip() + "\n\n※ " + " ".join(notes)
    return rep


def record_impact(p: Project, eid: str, rep: ImpactReport) -> None:
    el = elements.get(p, eid)
    el.impact = ElementImpact(report=rep, basis=elements.basis(el), at=elements.now())


def apply_impact(p: Project, eid: str, episodes: list[int], patches: list[int], facts: list[int]) -> list[str]:
    """영향 보고서에서 고른 부분만 반영한다. 플롯은 apply_revision 규칙을 따르고(본문 있는 화는 그대로,
    확정된 화는 초안으로), 본문 수정은 인용한 문장이 지금 본문에 그대로 있을 때만 바꾼다."""
    el = elements.get(p, eid)
    imp = el.impact
    if imp is None:
        raise ValueError("영향 분석을 먼저 하세요")
    if imp.outcome:
        raise ValueError("이미 처리한 영향 분석이에요. 다시 분석하세요")
    rep = imp.report
    if not (episodes or patches or facts):
        raise ValueError("반영할 부분을 고르세요")
    texts: dict[int, str] = {}
    records: list[tuple[int, TextEdit]] = []
    for i in patches:
        if not 0 <= i < len(rep.patches):
            raise ValueError(f"없는 본문 수정안이에요: {i}")
        t = rep.patches[i]
        ep = p.episode(t.episode)
        cur = texts.get(t.episode, ep.text)
        span = elements.find(cur, t.quote)
        if span is None:
            raise ValueError(f"{t.episode}화 본문이 그 사이 바뀌어 '{t.quote[:20]}' 문장을 찾을 수 없어요. 다시 분석하세요")
        texts[t.episode] = cur[:span[0]] + t.replacement.strip() + cur[span[1]:]
        # 집필 화면 수정 기록에 남겨 무엇을 바꿨는지 보고 취소할 수 있게 한다
        records.append((t.episode, TextEdit(id="", source="impact", start=span[0], before=cur[span[0]:span[1]],
                                            after=t.replacement.strip(), instruction=f"인과율 · {el.name}")))
    applied: list[str] = []
    if episodes:
        done = apply_revision(p, PlotRevision(reply="", episodes=rep.episodes), False, episodes)
        applied += [f"ep:{n}" for n in done]
    for n, text in texts.items():
        p.episode(n).text = text  # 상태 반영이 끝난 화도 작가가 고르면 고친다. 요약과 인물 상태는 그대로 둔다
    for n, rec in records:
        _record(p.episode(n), rec)
    applied += [f"patch:{i}" for i in patches]
    for i in facts:
        if 0 <= i < len(rep.new_facts) and rep.new_facts[i] not in p.facts:
            p.facts.append(rep.new_facts[i])
            applied.append(f"fact:{i}")
    imp.outcome, imp.applied = "applied", applied
    return applied


def dismiss_impact(p: Project, eid: str) -> None:
    imp = elements.get(p, eid).impact
    if imp and not imp.outcome:
        imp.outcome = "dismissed"


# ---------- 3-4. 화 끼워 넣기 · 빼기 ----------
# 아직 안 쓴 화 앞에 외전이나 새 화를 넣거나, 안 쓴 화를 뺀다. 뒤 화는 플롯과 확정 상태를 그대로 둔 채 번호만 옮기고,
# 화 번호를 품은 곳(구간 · 아크 · 부 범위, 총 화수, 복선, 인과율 요소, 이야기 줄기, 인물 첫 등장 화)도 함께 옮긴다 (renumber.py).
# 본문이 있거나 상태를 반영한 화는 번호를 바꾸지 않는다: 본문 파일, 스냅샷, 사건 로그까지 바꿔야 해서다.

def insert_range(p: Project) -> tuple[int, int]:
    """새 화를 넣을 수 있는 자리 (그 화 앞에 넣는다). 처음 > 끝이면 넣을 수 없다."""
    last = max((e.plot.number for e in p.episodes), default=0)
    return renumber.last_fixed(p) + 1, last + 1


def _ranges_text(p: Project) -> dict[str, tuple[int, int]]:
    out = {f"아크 {s.number} {s.title}".strip(): (s.start_ep, s.end_ep) for s in p.story_arcs}
    out.update({f"{x.number}부 {x.title}".strip(): (x.start_ep, x.end_ep) for x in p.parts})
    if not p.serial:
        out.update({f"{a.name} 구간": (a.start_ep, a.end_ep) for a in p.arc})
    return out


def _renumber_notes(before: Project, after: Project, counts: dict[str, int]) -> list[str]:
    notes = []
    old, new = _ranges_text(before), _ranges_text(after)
    grown = [f"{k} {old[k][0]}~{old[k][1]}화 → {new[k][0]}~{new[k][1]}화" for k in old
             if k in new and old[k][1] - old[k][0] != new[k][1] - new[k][0]]
    moved = sum(1 for k in old if k in new and old[k] != new[k]) - len(grown)
    if grown:
        notes.append(", ".join(grown) + (f" (뒤 범위 {moved}개는 한 칸씩 옮김)." if moved > 0 else "."))
    if before.meta.target_episodes != after.meta.target_episodes:
        notes.append(f"총 화수 {before.meta.target_episodes}화 → {after.meta.target_episodes}화.")
    labels = {"foreshadows": "복선", "elements": "인과율 요소", "storylines": "이야기 줄기", "characters": "인물 첫 등장 화"}
    also = [f"{labels[k]} {v}개" for k, v in counts.items() if v]
    if also:
        notes.append(" · ".join(also) + "의 화 번호도 함께 옮겼어요.")
    return notes


def _check_renumbered(q: Project) -> None:
    """옮긴 뒤 구조가 맞는지 본다. 한 화를 함께 쓰던 짧은 작품의 구간은 비율을 살려 다시 나눈다."""
    if q.serial:
        for s in q.story_arcs:
            plan = ArcPlan(acts=s.acts)
            fit_arc(plan, s.end_ep, s.start_ep)
            s.acts = plan.acts
        if q.parts:
            validate_parts(q.parts, q.meta.target_episodes)
        validate_story_arcs(q)
    elif q.arc:
        plan = ArcPlan(acts=q.arc)
        fit_arc(plan, q.meta.target_episodes)
        q.arc = plan.acts
    for e in q.episodes:
        act = q.act_for(e.plot.number)
        if act and e.status not in LOCKED:
            e.plot.act = act.name


def _renumbered(p: Project, change) -> list[str]:
    """복사본에서 change(q) 로 번호를 옮기고 구조를 확인한 뒤에만 p 에 반영한다. 반영한 내용 설명을 돌려준다."""
    q = p.model_copy(deep=True)
    fresh = {el.id for el in q.elements if el.impact and not elements.stale(el)}
    counts = change(q)
    for el in q.elements:
        if el.id in fresh:  # 번호만 옮긴 분석은 지난 것으로 보지 않는다
            el.impact.basis = elements.basis(el)  # type: ignore[union-attr]
    _check_renumbered(q)
    notes = _renumber_notes(p, q, counts)
    for f in Project.model_fields:
        setattr(p, f, getattr(q, f))
    return notes


def insert_episode(p: Project, at: int, title: str = "", summary: str = "", storyline: str = "") -> list[str]:
    """at 화 자리에 빈 플롯(제목 · 요약만)의 새 화를 넣고, 지금 at 화부터 뒤 화를 한 칸씩 민다.
    새 화는 바로 뒤 화가 든 구간 · 아크 · 부에 들어가고, 맨 끝에 붙이면 마지막 범위가 늘어난다. 반영한 내용 설명을 돌려준다."""
    lo, hi = insert_range(p)
    if not lo <= at <= hi:
        if at < lo:
            raise ValueError(f"{at}화 앞에는 넣을 수 없어요. {lo - 1}화까지는 본문이 있거나 상태를 반영해 번호를 옮기지 않아요. "
                             f"{lo}화부터 넣을 수 있어요")
        raise ValueError(f"{at}화 자리가 없어요. {hi}화(마지막 화 뒤)까지 넣을 수 있어요")
    if storyline:
        storylines.get(p, storyline)
    if p.serial and not p.story_arcs:
        raise ValueError("아크가 없어 새 화가 들어갈 자리가 없어요. 다음 아크를 먼저 기획하세요")
    moved = [e.plot.number for e in p.episodes if e.plot.number >= at]

    def change(q: Project) -> dict[str, int]:
        counts = renumber.move_points(q, renumber.point_insert(at))
        if q.serial:
            renumber.shift_ranges(q.story_arcs, at)
            renumber.shift_ranges(q.parts, at)
        renumber.shift_ranges(q.beats(), at)
        if at <= q.meta.target_episodes + 1:
            q.meta.target_episodes += 1
        prev = next((e.plot.act for e in reversed(q.episodes) if e.plot.number < at), "기")
        act = q.act_for(at)
        plot = EpisodePlot(number=at, act=act.name if act else prev, title=title.strip(), summary=summary.strip(),
                           events=[], characters=[], emotional_shift="", ending_hook="", storyline=storyline)
        q.episodes = sorted([*q.episodes, Episode(plot=plot)], key=lambda e: e.plot.number)
        return counts

    notes = _renumbered(p, change)
    head = f"{at}화에 새 화를 넣었어요."
    if moved:
        head += f" 원래 {moved[0]}~{moved[-1]}화는 {moved[0] + 1}~{moved[-1] + 1}화가 됐어요 (확정 상태 그대로)."
    return [head, *notes]


def remove_episode(p: Project, n: int) -> list[str]:
    """아직 안 쓴 n 화를 빼고 뒤 화를 한 칸씩 당긴다. n 화를 가리키던 복선 · 요소 · 줄기 번호는 그 자리에 온 다음 화를 가리킨다."""
    ep = p.episode(n)
    lo, _ = insert_range(p)
    if n < lo:
        raise ValueError(f"{n}화는 뺄 수 없어요. {lo - 1}화까지는 본문이 있거나 상태를 반영해 번호를 옮기지 않아요")
    moved = [e.plot.number for e in p.episodes if e.plot.number > n]

    def change(q: Project) -> dict[str, int]:
        q.episodes = [e for e in q.episodes if e.plot.number != n]
        counts = renumber.move_points(q, renumber.point_remove(n), gone=n)
        empty = []
        if q.serial:
            empty += [f"아크 {s.number}" for s in renumber.shrink_ranges(q.story_arcs, n)]
            empty += [f"{x.number}부" for x in renumber.shrink_ranges(q.parts, n)]
        empty += [f"{a.name} 구간" for a in renumber.shrink_ranges(q.beats(), n)]
        if empty:
            raise ValueError(f"{n}화를 빼면 {', '.join(empty)}이(가) 비어요. 구간이나 아크 범위를 먼저 늘리세요")
        if n <= q.meta.target_episodes:
            q.meta.target_episodes -= 1
        sync_candidates(q)
        return counts

    notes = _renumbered(p, change)
    head = f"{n}화 '{ep.plot.title or '제목 없음'}'을(를) 뺐어요."
    if moved:
        head += f" 원래 {moved[0]}~{moved[-1]}화는 {moved[0] - 1}~{moved[-1] - 1}화가 됐어요."
    return [head, *notes]


def delete_last(p: Project, n: int, keep_plot: bool = False) -> list[str]:
    """본문이 있거나 상태를 반영한 마지막 n 화를 지운다: n 화부터 반영을 취소하고(revert), 본문 · 수정 기록 · 이전 판 · 삽화 ·
    검수 결과를 비운 뒤 화를 뺀다(remove_episode). keep_plot 이면 빼지 않고 확정된 플롯으로 남겨 다시 쓸 수 있게 한다.
    중간 화는 뒤 화가 그 화 위에 쌓여 있어 지우지 않는다. 중간에 막히면 아무것도 바꾸지 않는다. 반영한 내용 설명을 돌려준다."""
    q = p.model_copy(deep=True)
    notes = _delete_last(q, n, keep_plot)
    for f in Project.model_fields:
        setattr(p, f, getattr(q, f))
    return notes


def _delete_last(p: Project, n: int, keep_plot: bool) -> list[str]:
    ep = p.episode(n)
    last = renumber.last_fixed(p)
    if n != last:
        if n < last:
            raise ValueError(f"{n}화는 뒤에 본문이 있거나 반영한 화({last}화까지)가 있어 지울 수 없어요. 마지막 화부터 지우세요")
        raise ValueError(f"{n}화는 본문도 반영도 없어요. 플롯을 빼려면 화 빼기를 쓰세요")
    notes = []
    applied = ep.status == "finalized" or any(x.episode >= n for x in [*p.history, *p.snapshots, *p.events])
    if applied:
        if p.snapshot(n - 1) is None:
            raise ValueError(f"{n - 1}화 스냅샷이 없어 {n}화 반영을 취소할 수 없어요")
        added = [c.name or c.id for d in p.history if d.episode >= n for c in d.new_characters]
        revert(p, n - 1)
        notes.append(f"{n}화 상태 반영을 취소했어요 ({f'{n - 1}화 반영 직후' if n > 1 else '1화 시작 전'}로)."
                     + (f" 그 반영이 더한 인물({', '.join(added)})도 빠졌어요." if added else ""))
    chars = len(ep.text)
    ep.text, ep.status, ep.summary, ep.auto, ep.final_text = "", "confirmed", "", False, ""
    ep.edits, ep.hook, ep.illustrations = [], None, []
    findings.clear(ep)
    ep.candidate, ep.versions, ep.made_by, ep.time = None, [], None, StoryTime()
    p.foreshadow_clues = [c for c in p.foreshadow_clues if c.episode != n]  # 지운 본문 문장에 건 복선 근거
    p.chats = [c for c in p.chats if c.topic != f"text:{n}"]
    if chars:
        notes.append(f"본문 {chars:,}자와 수정 기록 · 이전 판 · 삽화 프롬프트를 지웠어요.")
    if keep_plot:
        return [*notes, f"{n}화 '{ep.plot.title or '제목 없음'}' 플롯은 확정된 채로 남겼어요."]
    try:
        return [*notes, *remove_episode(p, n)]
    except ValueError as e:
        raise ValueError(f"{e}. 플롯을 남기고 본문만 지울 수는 있어요") from e


def draft_episode(llm: LLM, p: Project, n: int, fit_next: bool = True) -> PlotBatch:
    """초안인 n 화 하나의 플롯을 앞뒤 화에 맞춰 AI 로 채운다. 작가가 적어 둔 제목 · 요약 · 줄기는 살린다. 저장하지 않는다.
    fit_next=False 면 뒤 화에 맞추지 않고 작가가 적은 것대로 마무리한다. 뒤 화와 어긋난 점은 EpisodeDraft.next_gap 에
    담겨 오고, apply_draft 가 뒤 화에 '다시 맞추기' 표시로 남긴다."""
    e = p.episode(n)
    if e.status != "draft":
        raise ValueError(f"{n}화는 확정된 화라 AI 초안으로 바꾸지 않아요. 초안으로 되돌린 뒤 하세요")
    beats = p.beats()
    if not beats:
        raise ValueError("다음 아크를 먼저 기획하세요" if p.serial else "기승전결 구조(arc)를 먼저 만드세요")
    free = not fit_next and any(x.plot.number == n + 1 for x in p.episodes)
    batch = llm.json(prompts.SYSTEM_PLANNER, prompts.episode_plot_prompt(p, n, fit_next), EpisodeDraft if free else PlotBatch,
                     hint={"start": n, "end": n, "arc": beats, "free": free})
    pick = [x for x in batch.episodes if x.number == n] or batch.episodes[:1]
    if not pick:
        raise ValueError(f"{n}화 플롯을 받지 못했어요")
    plot = pick[0]
    plot.number = n
    if e.plot.title.strip():
        plot.title = e.plot.title  # 작가가 붙인 제목은 그대로
    if e.plot.storyline and not plot.storyline:
        plot.storyline = e.plot.storyline
    batch.episodes = [plot]
    return batch


def apply_draft(p: Project, batch: PlotBatch) -> int | None:
    """draft_episode 결과를 반영한다. 뒤 화와 어긋난 점이 있으면 뒤 화에 표시하고 그 화 번호를 돌려준다."""
    apply_plots(p, batch)
    gap = getattr(batch, "next_gap", "").strip()
    if not gap or not batch.episodes:
        return None
    nxt = next((x for x in p.episodes if x.plot.number == batch.episodes[0].number + 1), None)
    if nxt is None:
        return None
    nxt.realign = gap
    return nxt.plot.number


def reopen_impact(p: Project, eid: str) -> None:
    """버린 영향 분석을 다시 검토할 수 있게 한다. 반영한 것은 다시 열지 않는다."""
    imp = elements.get(p, eid).impact
    if imp and imp.outcome == "dismissed":
        imp.outcome = ""


# ---------- 4. 본문 생성 ----------
# 본문의 글자 중 한글이 이보다 적으면 모델이 생각 과정이나 다른 언어를 낸 것으로 보고 다시 쓴다.
# 연구에서 Gemini 4 Argon 이 92번 중 1번 영어 생각 과정을 본문으로 냈다.
HANGUL_MIN = 0.8
WRITE_TRIES = 3


def write_episode(llm: LLM, p: Project, n: int, approach: str = "") -> str:
    """approach: 1~3화를 여러 안으로 쓸 때 여는 방식 (prompts.OPENING_APPROACHES)."""
    ep = p.episode(n)
    if ep.status == "draft":
        raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요 (confirm 먼저)")
    require_previous(p, n)
    return _write(llm, p, n, prompts.episode_prompt(p, n, approach))


def _write(llm: LLM, p: Project, n: int, prompt: str) -> str:
    system = prompts.writer_system(p)
    for _ in range(WRITE_TRIES):
        text = llm.text(system, prompt)
        if metrics.hangul_ratio(text) >= HANGUL_MIN:
            return text
    raise ValueError(f"{n}화 본문 대신 다른 글(영어로 된 생각 과정 등)이 {WRITE_TRIES}번 나왔어요. 다시 시도해 주세요")


def compare_drafts(llms: dict[str, LLM], p: Project, n: int) -> dict[str, str]:
    """같은 화를 여러 백엔드로 쓴다. 프롬프트는 write_episode 와 같다. 저장은 호출자가 한다."""
    return {name: write_episode(llm, p, n) for name, llm in llms.items()}


def adopt_draft(p: Project, n: int, text: str) -> None:
    """비교에서 고른 본문을 그 화의 본문으로 쓴다. 상태 반영이 끝난 화는 되돌린 뒤에만 바꾼다."""
    ep = p.episode(n)
    if ep.status == "finalized":
        raise ValueError(f"{n}화는 상태 반영이 끝났어요. 바꾸려면 상태 승인 화면에서 {n}화부터 반영을 취소한 뒤 다시 하세요 (명령줄은 revert {n - 1})")
    replace_text(ep, text)


# ---------- 4-0. 다시 생성 ----------
# 작가의 피드백, 빠른 요청, 함께 넣을 재료(검수 결과 등), 살릴 부분으로 그 화를 다시 쓴다. 새 판은 본문을 덮지 않고
# Episode.candidate 에 두어 지금 본문과 비교해 고르게 한다. 바꾸기 전 판과 고르지 않은 판은 versions 에 남아 되돌릴 수 있다.

VERSION_KEEP = 6  # 화마다 남기는 다른 판 수
REWRITE_EDITS = 8  # 재료로 넣는 최근 수정 수


def clean_rewrite(req: RewriteRequest) -> RewriteRequest:
    """모르는 빠른 요청은 막고, 겹치거나 빈 것은 뺀다."""
    bad = [x for x in req.presets if x not in prompts.REWRITE_PRESETS]
    if bad:
        raise ValueError(f"모르는 빠른 요청이에요: {', '.join(bad)}")
    keep = [k.strip()[:prompts.REWRITE_KEEP_LIMIT] for k in req.keep if k.strip()]
    return RewriteRequest(feedback=req.feedback.strip(), presets=list(dict.fromkeys(req.presets)),
                          materials=list(dict.fromkeys(req.materials)), mode=req.mode,
                          keep=list(dict.fromkeys(keep))[:prompts.REWRITE_KEEP])


def text_since(ep: Episode) -> str:
    """지금 본문이 생긴 시각: 마지막으로 판을 바꾼 때. 그 전 수정은 지난 판을 고친 것이다."""
    return max((v.at for v in ep.versions if v.kind == "previous"), default="")


def _hook_lines(h: HookReport) -> list[str]:
    out = [f"- {it.aspect} {it.score}/5: {it.note}" + (f" (근거: «{prompts._clip(it.quote, 120)}»)" if it.quote else "")
           for it in sorted(h.items, key=lambda x: x.score) if it.score <= 3]
    if not h.next_click:
        out.append(f"- 독자가 여기서 내릴 수 있다: {h.reason}")
    if not h.reader_question:
        out.append("- 마지막 장면에서 독자가 들고 갈 질문이 보이지 않는다")
    return out


def rewrite_materials(p: Project, n: int) -> dict[str, list[str]]:
    """함께 넣을 수 있는 재료와 프롬프트에 들어갈 줄. 없는 재료는 빈 목록."""
    ep = p.episode(n)
    since = text_since(ep)
    edits = [e for e in ep.edits if not e.undone and e.at > since and (e.before or e.after)][-REWRITE_EDITS:]
    return {
        "issues": [f"- [{x.type}] {x.description}" + (f" (어긋난 문장: «{prompts._clip(x.current_quote, 160)}»)" if x.current_quote else "")
                   + (f" → {x.suggestion}" if x.suggestion else "") for x in findings.open_findings(ep)],
        "hook": _hook_lines(ep.hook) if ep.hook and prompts.is_opening(n) else [],
        "style": [f"- {w}" for w in style_drift(p, n)[1]] if ep.text else [],
        "edits": [f"- «{prompts._clip(e.before, 200)}» → «{prompts._clip(e.after, 200)}»"
                  + (f" (요청: {prompts._clip(e.instruction, 80)})" if e.instruction else "") for e in edits],
    }


def rewrite_prompt(p: Project, n: int, req: RewriteRequest) -> str:
    return prompts.rewrite_prompt(p, n, req, rewrite_materials(p, n), p.episode(n).text)


def rewrite_episode(llm: LLM, p: Project, n: int, req: RewriteRequest) -> str:
    """피드백을 반영해 그 화를 다시 쓴다. 저장하지 않는다 (set_candidate 로 새 판에 둔다)."""
    ep = _editable(p, n)
    require_previous(p, n)
    if req.mode == "revise" and not ep.text.strip():
        raise ValueError("고쳐 쓸 지난 판이 없어요")
    return _write(llm, p, n, rewrite_prompt(p, n, clean_rewrite(req)))


def _version_id(ep: Episode) -> str:
    vs = ep.versions + ([ep.candidate] if ep.candidate else [])
    nums = [int(v.id[1:]) for v in vs if v.id[1:].isdigit()]
    return f"v{max(nums, default=0) + 1}"


def _keep_version(ep: Episode, v: TextVersion) -> None:
    """판을 남긴다. 한도를 넘으면 고르지 않은 새 판(rejected)부터 오래된 순으로 지우고, 바꾸기 전 본문(previous)은 마지막까지 남긴다."""
    vs = ep.versions + [v]
    while len(vs) > VERSION_KEEP:
        vs.pop(next((i for i, x in enumerate(vs) if x.kind == "rejected"), 0))
    ep.versions = vs


def set_candidate(p: Project, n: int, text: str, req: RewriteRequest) -> TextVersion:
    """새 판을 고르기 대기에 둔다. 고르지 않은 앞 새 판은 versions 로 보낸다."""
    ep = p.episode(n)
    if ep.candidate:
        ep.candidate.kind = "rejected"
        _keep_version(ep, ep.candidate)
    ep.candidate = TextVersion(id=_version_id(ep), at=_now(), text=text, request=clean_rewrite(req))
    return ep.candidate


def replace_text(ep: Episode, text: str, made_by: RewriteRequest | None = None) -> None:
    """지금 본문을 versions 에 남기고 text 로 바꾼다. 검수 결과는 지난 판 것이라 지운다.
    상태 반영이 끝난 화는 반영을 그대로 두고 before_change 로 반영 뒤 고침만 표시한다."""
    done = ep.status == "finalized"
    if text == ep.text:
        ep.status = "finalized" if done else "written"
        return
    if ep.text.strip():
        _keep_version(ep, TextVersion(id=_version_id(ep), at=_now(), text=ep.text, kind="previous", request=ep.made_by))
    before_change(ep)
    ep.text, ep.made_by, ep.status = text, made_by, "finalized" if done else "written"
    findings.clear(ep)


def adopt_candidate(p: Project, n: int) -> None:
    """새 판을 본문으로 쓴다. 지금 본문은 versions 에 남는다."""
    ep = _editable(p, n)
    if ep.candidate is None:
        raise ValueError(f"{n}화에 고를 새 판이 없어요")
    c, ep.candidate = ep.candidate, None
    replace_text(ep, c.text, c.request)


def drop_candidate(p: Project, n: int) -> None:
    """새 판을 고르지 않고 지금 본문을 둔다. 버린 판도 versions 에 남는다."""
    ep = p.episode(n)
    if ep.candidate is None:
        raise ValueError(f"{n}화에 고를 새 판이 없어요")
    ep.candidate.kind = "rejected"
    _keep_version(ep, ep.candidate)
    ep.candidate = None


def restore_version(p: Project, n: int, vid: str) -> None:
    """남겨 둔 판으로 되돌린다. 지금 본문은 versions 에 남는다."""
    ep = _editable(p, n)
    v = next((x for x in ep.versions if x.id == vid), None)
    if v is None:
        raise KeyError(f"남겨 둔 판이 없어요: {vid}")
    replace_text(ep, v.text, v.request)
    ep.versions = [x for x in ep.versions if x is not v]


# ---------- 4-1. 본문 부분 수정 ----------
# 작가가 본문에서 고른 부분을 직접 고치거나 AI 후보로 바꾼다. 고칠 때마다 전후 쌍을 Episode.edits 에 남겨
# 되돌릴 수 있게 하고, 나중에 선호 · 미세 조정 자료로 꺼낼 수 있게 한다 (cli edits --jsonl).

EDIT_KEEP = 50  # 화마다 남기는 수정 기록 수


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _editable(p: Project, n: int) -> Episode:
    """본문을 고칠 수 있는 화. 상태 반영이 끝난 화도 고친다 (반영된 상태는 그대로 두고 before_change 가 표시한다)."""
    ep = p.episode(n)
    if not ep.text:
        raise ValueError(f"{n}화 본문이 없어요")
    return ep


def before_change(ep: Episode) -> None:
    """본문을 바꾸기 직전에 부른다. 반영이 끝난 화면 처음 고치기 전 본문을 final_text 에 남겨 반영 기준 본문과 비교할 수 있게 한다."""
    if ep.status == "finalized" and not ep.final_text:
        ep.final_text = ep.text


def edited_after_final(ep: Episode) -> bool:
    """상태 반영이 끝난 뒤 본문을 고쳐, 반영된 요약 · 상태 · 복선이 고치기 전 본문 기준이다."""
    return ep.status == "finalized" and bool(ep.final_text) and ep.final_text != ep.text


def locate(text: str, quote: str, start: int) -> int:
    """quote 가 있는 자리. 본문이 앞에서 바뀌어 위치가 밀렸으면 start 에서 가장 가까운 같은 글을 찾는다."""
    if not quote:
        raise ValueError("고른 부분이 비었어요")
    if text[start:start + len(quote)] == quote:
        return start
    found, i = [], text.find(quote)
    while i != -1:
        found.append(i)
        i = text.find(quote, i + 1)
    if not found:
        raise ValueError("고른 부분을 본문에서 찾을 수 없어요. 그사이 본문이 바뀌었을 수 있어요. 다시 골라 주세요")
    return min(found, key=lambda x: abs(x - start))


def _record(ep: Episode, edit: TextEdit) -> TextEdit:
    nums = [int(e.id[1:]) for e in ep.edits if e.id[1:].isdigit()]
    edit.id = f"e{max(nums, default=0) + 1}"
    edit.at = edit.at or _now()
    ep.edits = (ep.edits + [edit])[-EDIT_KEEP:]
    return edit


def edit_text(p: Project, n: int, sel: Selection, after: str, source: str = "manual", instruction: str = "",
              preset: str = "", proposed: str = "", rejected: list[str] | None = None) -> TextEdit:
    """고른 부분(sel)을 after 로 바꾸고 기록을 남긴다."""
    ep = _editable(p, n)
    at = locate(ep.text, sel.text, sel.start)
    if after == sel.text:
        raise ValueError("바뀐 내용이 없어요")
    before_change(ep)
    ep.text = ep.text[:at] + after + ep.text[at + len(sel.text):]
    return _record(ep, TextEdit(id="", source=source, start=at, before=sel.text, after=after, instruction=instruction,  # type: ignore[arg-type]
                                preset=preset, proposed=proposed if proposed != after else "", rejected=list(rejected or [])))


def record_typed(p: Project, n: int, old: str, new: str) -> TextEdit | None:
    """본문을 통째로 고쳐 저장했을 때 앞뒤가 같은 부분을 빼고 바뀐 곳만 기록한다. 처음 쓰거나 지운 것은 기록하지 않는다."""
    if not old or not new or old == new:
        return None
    a = 0
    while a < min(len(old), len(new)) and old[a] == new[a]:
        a += 1
    b = 0
    while b < min(len(old), len(new)) - a and old[-1 - b] == new[-1 - b]:
        b += 1
    return _record(p.episode(n), TextEdit(id="", source="typed", start=a, before=old[a:len(old) - b], after=new[a:len(new) - b]))


def undo_edit(p: Project, n: int, eid: str) -> TextEdit:
    """수정 하나를 되돌린다. 그 뒤에 같은 자리를 또 고쳤으면 찾지 못해 되돌릴 수 없다."""
    ep = _editable(p, n)
    edit = next((e for e in ep.edits if e.id == eid), None)
    if edit is None:
        raise KeyError(f"수정 기록이 없어요: {eid}")
    if edit.undone:
        raise ValueError("이미 되돌린 수정이에요")
    if edit.after:
        at = locate(ep.text, edit.after, edit.start)
    elif edit.start <= len(ep.text):  # 지우기만 한 수정은 그 자리에 다시 넣는다
        at = edit.start
    else:
        raise ValueError("되돌릴 자리를 찾을 수 없어요")
    before_change(ep)
    ep.text = ep.text[:at] + edit.before + ep.text[at + len(edit.after):]
    edit.undone = True
    return edit


def redo_edit(p: Project, n: int, eid: str) -> TextEdit:
    """수정 취소(undo_edit)한 수정을 다시 넣는다. 그 뒤에 같은 자리를 또 고쳤으면 찾지 못해 다시 넣을 수 없다."""
    ep = _editable(p, n)
    edit = next((e for e in ep.edits if e.id == eid), None)
    if edit is None:
        raise KeyError(f"수정 기록이 없어요: {eid}")
    if not edit.undone:
        raise ValueError("취소하지 않은 수정이에요")
    if edit.before:
        at = locate(ep.text, edit.before, edit.start)
    elif edit.start <= len(ep.text):  # 더하기만 한 수정은 그 자리에 다시 넣는다
        at = edit.start
    else:
        raise ValueError("다시 넣을 자리를 찾을 수 없어요")
    before_change(ep)
    ep.text = ep.text[:at] + edit.after + ep.text[at + len(edit.before):]
    edit.undone = False
    return edit


def revise_passage(llm: LLM, p: Project, n: int, sel: Selection, message: str = "", preset: str = "") -> PassageRevision:
    """고른 부분의 고친 후보를 만든다. 저장하지 않는다. 원문과 같거나 겹치는 후보는 뺀다."""
    if preset and preset not in prompts.PASSAGE_PRESETS:
        raise ValueError(f"모르는 빠른 요청이에요: {preset}")
    if not message.strip() and not preset:
        raise ValueError("무엇을 바꿀지 적거나 빠른 요청을 고르세요")
    ep = _editable(p, n)
    sel = Selection(start=locate(ep.text, sel.text, sel.start), text=sel.text)
    rev = llm.json(prompts.reviser_system(p), prompts.passage_prompt(p, n, sel, message, preset), PassageRevision,
                   hint={"selection": sel.text, "preset": preset, "message": message})
    keep, seen = [], {sel.text.strip()}
    for c in rev.candidates:
        c.text = c.text.strip().replace("【고칠 부분】", "").replace("【여기까지】", "")
        if c.text and c.text not in seen:
            seen.add(c.text)
            keep.append(c)
    rev.candidates = keep[:3]
    if not keep:
        rev.reply = rev.reply.rstrip() + "\n\n※ 원문과 다른 후보가 없었어요. 요청을 조금 더 구체적으로 적어 주세요."
    return rev


def record_passage(p: Project, n: int, sel: Selection, message: str, preset: str, rev: PassageRevision) -> ChatMessage:
    """작가의 요청과 AI 후보를 그 화의 부분 수정 대화('text:<화>')에 남긴다."""
    now = _now()
    chat = p.chat(f"text:{n}")
    label = prompts.PASSAGE_PRESETS[preset][0] if preset in prompts.PASSAGE_PRESETS else ""
    user = ChatMessage(role="user", text=message.strip() or label, selection=sel, preset=preset, at=now)
    reply = ChatMessage(role="assistant", text=rev.reply, passage=rev if rev.candidates else None, selection=sel,
                        preset=preset, at=now)
    chat.messages += [user, reply]
    chat.messages = chat.messages[-CHAT_KEEP:]
    return reply


def apply_passage(p: Project, n: int, i: int, k: int, text: str | None = None) -> TextEdit:
    """부분 수정 대화의 i 번째 메시지에서 k 번째 후보를 본문에 넣는다. text 를 주면 작가가 손본 글을 넣는다."""
    msgs = p.chat(f"text:{n}").messages
    if not 0 <= i < len(msgs) or msgs[i].passage is None or msgs[i].selection is None:
        raise KeyError("후보가 있는 메시지가 아니에요")
    m = msgs[i]
    if m.outcome:
        raise ValueError("이미 처리한 후보여요")
    cands = m.passage.candidates
    if not 0 <= k < len(cands):
        raise ValueError("후보 번호가 맞지 않아요")
    user = next((x for x in reversed(msgs[:i]) if x.role == "user"), None)
    after = (text if text is not None else cands[k].text).strip()
    if not after:
        raise ValueError("넣을 글이 비었어요")
    edit = edit_text(p, n, m.selection, after, "ai", instruction=user.text if user else "", preset=m.preset,
                     proposed=cands[k].text, rejected=[c.text for j, c in enumerate(cands) if j != k])
    m.outcome, m.applied = "applied", [str(k)]
    return edit


# ---------- 4-3. 삽화 프롬프트 (NovelAI) ----------
# AI 는 장면을 태그로 옮긴 원안만 낸다. 외형 · 인물 수 · 등급 · 품질 태그는 illust.assemble 이 붙인다.
# 본문을 바꾸지 않으므로 반영(finalized)한 화에서도 만든다.

def illustrate(llm: LLM, p: Project, n: int, sel: Selection | None = None, request: str = "", model: str = "") -> Illustration:
    """고른 부분(없으면 AI 가 고른 장면)의 삽화 프롬프트를 만든다. 저장하지 않는다."""
    ep = p.episode(n)
    if not ep.text:
        raise ValueError(f"{n}화 본문이 없어요")
    if sel is not None:
        sel = Selection(start=locate(ep.text, sel.text, sel.start), text=sel.text)
    draft = llm.json(prompts.SYSTEM_ILLUSTRATOR, prompts.illust_prompt(p, n, sel, request), IllustDraft,
                     hint={"selection": sel.text if sel else "", "text": ep.text, "cast": ep.plot.characters})
    ids = {c.id for c in p.characters}
    for c in draft.characters:
        if c.id and c.id not in ids:  # 이름으로 적었거나 없는 id 면 설정에 없는 인물로 본다
            hit = next((x.id for x in p.characters if x.name and x.name == c.id), "")
            c.id = hit
    return illust.assemble(p, Illustration(id="", model=model or p.illust.model, selection=sel, request=request.strip(), draft=draft))


def add_illustration(p: Project, n: int, ill: Illustration) -> Illustration:
    ep = p.episode(n)
    nums = [int(x.id[1:]) for x in ep.illustrations if x.id[1:].isdigit()]
    ill.id = f"i{max(nums, default=0) + 1}"
    ill.at = ill.at or _now()
    ep.illustrations = (ep.illustrations + [ill])[-illust.KEEP:]
    return ill


def _illustration(p: Project, n: int, iid: str) -> Illustration:
    ill = next((x for x in p.episode(n).illustrations if x.id == iid), None)
    if ill is None:
        raise KeyError(f"삽화 프롬프트가 없어요: {iid}")
    return ill


def rebuild_illustration(p: Project, n: int, iid: str, model: str = "") -> Illustration:
    """모델이나 외형 태그 · 화풍을 바꾼 뒤 AI 를 다시 부르지 않고 조립만 새로 한다."""
    if model and model not in illust.MODELS:
        raise ValueError(f"모르는 모델이에요: {model}")
    return illust.assemble(p, _illustration(p, n, iid), model or None)


def remove_illustration(p: Project, n: int, iid: str) -> None:
    ep = p.episode(n)
    _illustration(p, n, iid)
    ep.illustrations = [x for x in ep.illustrations if x.id != iid]


def suggest_voice(llm: LLM, p: Project, cid: str, request: str = "") -> VoiceSuggestion:
    """인물이 시점 인물인 화의 서술 말투 초안. 저장하지 않는다 (작가가 고쳐 Character.narration_voice 에 저장)."""
    if not any(c.id == cid for c in p.characters):
        raise KeyError(f"인물이 없어요: {cid}. 새로 더한 인물이면 저장한 뒤 다시 하세요")
    s = llm.json(prompts.SYSTEM_VOICE, prompts.voice_prompt(p, cid, request), VoiceSuggestion, hint={"character": cid})
    s.voice = s.voice.strip()
    return s


def sort_places(llm: LLM, p: Project, texts: list[str] | None = None) -> dict:
    """장소와 맞지 않은 인물 위치 글을 AI 가 장소에 맞춘 제안 (atlas.clean_sort 모양). 저장하지 않는다.
    texts 를 주면 그 글만. 많으면 atlas.SORT_CHUNK 개씩 나눠 부른다."""
    from . import atlas

    pls = atlas.places(p)
    items = atlas.unmatched(p, atlas.frames(p, pls))
    if texts is not None:
        want = {t.strip() for t in texts}
        items = [it for it in items if it["text"] in want]
    if not items:
        raise ValueError("장소와 맞지 않은 위치 글이 없어요")
    outs = []
    for i in range(0, len(items), atlas.SORT_CHUNK):
        part = items[i:i + atlas.SORT_CHUNK]
        outs.append(llm.json(prompts.SYSTEM_PLACE_SORTER, prompts.place_sort_prompt(p, part, pls), PlaceSort,
                             hint={"texts": [it["text"] for it in part], "places": [pl["name"] for pl in pls]}))
    return atlas.clean_sort(p, items, outs)


def suggest_map(llm: LLM, p: Project, spec: MapSpec | None = None) -> dict:
    """지도 만들기 설정 제안 (MapSuggestion). 저장하지 않는다. 좌표는 마을 · 도시 생성기가 정한다.
    돌려주는 것: 지도 종류 kind(village | city), 설정 칸(size, roads, water, fields, forest), places [{key, name, kind, put, note}], reason.
    도시에 호수를 고르면 강으로 바꾼다 (도시 생성기에는 호수 칸이 없다).
    장소 이름은 키로 바꾸고, 모르는 장소 · 모르는 종류 id 는 뺀다 (지금 값을 그대로 둔다)."""
    from . import atlas, towngen

    pls = atlas.places(p)
    if not pls:
        raise ValueError("장소가 아직 없어요. 장소를 더한 뒤 제안을 받으세요")
    rows = atlas.gen_places(p, spec)
    kinds = [(cid, label) for cid, label, _ in towngen.CATEGORIES]
    options = {k: m[1].OPTIONS for k, m in atlas.MAKERS.items()}
    s = llm.json(prompts.SYSTEM_MAP_PLANNER, prompts.map_suggest_prompt(p, rows, pls, kinds, options), MapSuggestion,
                 hint={"places": [r["name"] for r in rows]})
    names = {pl["key"]: pl["name"] for pl in pls}
    out, seen = [], set()
    for g in s.places:
        key = atlas.place_by_name(g.name, pls)
        kind = g.kind.strip()
        if not key or key in seen or kind not in towngen.CATEGORY_IDS:
            continue
        seen.add(key)
        out.append({"key": key, "name": names[key], "kind": kind, "put": bool(g.put), "note": g.note.strip()})
    water = "river" if s.kind == "city" and s.water == "lake" else s.water
    return {"kind": s.kind, "size": s.size, "roads": s.roads, "water": water, "fields": s.fields, "forest": s.forest,
            "places": out, "reason": s.reason.strip()}


def suggest_look(llm: LLM, p: Project, cid: str) -> LookSuggestion:
    """인물 설정을 외형 태그로 옮긴 제안. 저장하지 않는다."""
    if not any(c.id == cid for c in p.characters):
        raise KeyError(f"인물이 없어요: {cid}. 새로 더한 인물이면 저장한 뒤 다시 하세요")
    s = llm.json(prompts.SYSTEM_ILLUSTRATOR, prompts.look_prompt(p, cid), LookSuggestion, hint={"character": cid})
    s.look, s.outfit = illust.clean(s.look), illust.clean(s.outfit)
    return s


def suggest_body(llm: LLM, p: Project, cid: str) -> BodySuggestion:
    """신체 프로필 제안. 저장하지 않는다 (작가가 칸별로 골라 Character.body 에 넣고 작품을 저장한다).
    미성년 인물은 쓰리사이즈를 묻지 않고, 모델이 적어 와도 비운다."""
    from . import cast

    c = next((c for c in p.characters if c.id == cid), None)
    if c is None:
        raise KeyError(f"인물이 없어요: {cid}. 새로 더한 인물이면 저장한 뒤 다시 하세요")
    minor = cast.is_minor_age(c.age)
    s = llm.json(prompts.SYSTEM_PLANNER, prompts.body_prompt(p, cid, minor), BodySuggestion, hint={"character": cid})
    for k in ("height", "weight", "build", "measurements", "features", "note"):
        setattr(s, k, getattr(s, k).strip())
    if minor:
        s.measurements = ""
    return s


def suggest_stat_window(llm: LLM, p: Project, request: str = "") -> StatWindowSuggestion:
    """상태창 꾸미기 안 (본문 서식 · 창 이름 · 항목 틀 · 화면 스킨). 저장하지 않는다 (작가가 고른 안만 statwin-template 로 저장)."""
    s = llm.json(prompts.SYSTEM_PLANNER, prompts.stat_window_prompt(p, request), StatWindowSuggestion, hint={"request": request})
    return statwin.clean_options(s)

def suggest_initial_stats(llm: LLM, p: Project, request: str = "") -> StatInitSuggestion:
    """1화 전 상태창 처음 수치 제안. 저장하지 않는다 (작가가 고른 인물의 값을 statwin.set_stats 로 저장).
    1화를 반영한 뒤에는 처음 값이 아니라 그 화의 작가 수정이 되므로 막는다."""
    if statwin.last_done(p):
        raise ValueError("1화를 반영한 뒤에는 처음 수치를 제안하지 않아요. 상태창 수치 화면에서 고쳐요")
    if not p.characters:
        raise ValueError("인물이 없어요. 인물을 먼저 만드세요")
    s = llm.json(prompts.SYSTEM_PLANNER, prompts.stat_init_prompt(p, request), StatInitSuggestion,
                 hint={"characters": [c.id for c in p.characters], "names": p.stat_window.names})
    return statwin.clean_init(p, s)


def save_look(p: Project, cid: str, look: list[str], outfit: list[str] | None = None, subject: str = "",
              keep_outfit: bool = False) -> CharacterVisual:
    """작가가 고른 외형 태그를 저장한다. keep_outfit 이면 이미 있는 기본 옷차림은 두고 비었을 때만 채운다."""
    if not any(c.id == cid for c in p.characters):
        raise KeyError(f"인물이 없어요: {cid}. 새로 더한 인물이면 저장한 뒤 다시 하세요")
    v = p.visual(cid)
    if v is None:
        v = CharacterVisual(character_id=cid)
        p.visuals.append(v)
    v.look = illust.clean(look)
    if outfit is not None and not (keep_outfit and v.outfit):
        v.outfit = illust.clean(outfit)
    if subject in ("girl", "boy", "other"):
        v.subject = subject  # type: ignore[assignment]
    return v


def keep_illust_look(p: Project, n: int, iid: str, cid: str, force: bool = False) -> CharacterVisual:
    """삽화 원안에서 AI 가 채운 외형 태그를 그 인물의 외형 태그로 저장하고, 그 인물 외형이 비어 있던 삽화를 모두 다시 조립한다.
    그 인물에 이미 외형 태그가 저장돼 있으면 force 일 때만 바꾼다 (작가가 적은 태그를 덮지 않게)."""
    ill = _illustration(p, n, iid)
    ch = next((c for c in ill.draft.characters if c.id == cid and c.look), None)
    if ch is None:
        raise ValueError("이 삽화에 그 인물의 외형 태그가 없어요")
    have = p.visual(cid)
    if have is not None and have.look and not force:
        raise ValueError("이 인물은 이미 외형 태그가 저장돼 있어요. 다시 조립하면 저장된 태그가 들어가요")
    v = save_look(p, cid, ch.look, ch.outfit, ch.subject, keep_outfit=True)
    for e in p.episodes:
        for x in e.illustrations:
            if x is ill or cid in x.missing_look:
                illust.assemble(p, x)
    return v


# ---------- 5. 검수 (모순 찾기, 문체 지표) ----------

def check_episode(llm: LLM, p: Project, n: int, widen: bool | None = None) -> ConsistencyReport:
    """한 화 검수. 장편이고 widen 이면(비우면 작품 설정 check_widen) 검수 넓히기(widen_check)를 이어 붙인다. 단편은 넓히지 않는다."""
    if not p.episode(n).text:
        raise ValueError(f"{n}화 본문이 없어요")
    report = llm.json(prompts.SYSTEM_CHECKER, prompts.check_prompt(p, n), ConsistencyReport, hint={"episode": n})
    report.episode = n
    if widen_on(p, widen):
        report, _ = widen_check(llm, p, n, report)
    return report


def widen_on(p: Project, widen: bool | None = None) -> bool:
    """이 검수에 넓혀 찾기를 붙이는지: 장편이고 widen(비우면 작품 설정 check_widen)이 켜졌을 때."""
    return p.serial and (p.settings.check_widen if widen is None else widen)


_same_quote = findings.same_quote


def widen_check(llm: LLM, p: Project, n: int, report: ConsistencyReport, hint: dict | None = None) -> tuple[ConsistencyReport, dict]:
    """장편 검수 넓히기: 첫 검수(budget)는 이번 화 전체로 한 번 찾은 옛 단락만 본다. 이번 화의 사실 진술을 뽑아(claims_prompt)
    진술마다 옛 화를 따로 찾고(claim_evidence, LLM 없음), 첫 검수에 넣지 않은 단락이 근거로 나온 진술만 그 근거와 함께
    검수 모델에 다시 묻는다(widen_prompt). 판단기는 쓰지 않는다. 더한 지적은 첫 검수와 같은 문장을 짚으면 뺀다.
    (첫 검수 지적 + 더한 지적, 단계별 크기 · 진술 기록)"""
    from .context import PassageIndex, est_tokens

    ep = p.episode(n)
    hint = hint or {}
    part = getattr(llm, "part", None)  # 자동 집필 배치: 호출마다 작업 slot 을 따로 둔다 (llm.BatchLLM.part)
    first = prompts.claims_prompt(p, n)
    claims = (part("claims") if part else llm).json(prompts.SYSTEM_CLAIMS, first, ClaimSet, hint={"episode": n, "text": ep.text}).claims
    claims = [c for c in claims if c.quote.strip() and c.claim.strip()][:prompts.TWOSTEP_CLAIMS]
    recent, found = prompts.check_recall(p, n)
    seen = {para for _, paras in found for para in paras}
    index = PassageIndex(p, n, {e.plot.number for e in recent})  # 직전 화는 첫 검수가 원문으로 봤다
    rows = []
    for i, c in enumerate(claims):
        parts, hits = prompts.claim_sources(p, n, c, index)
        paras = [x for _, xs in hits for x in xs]
        new = sum(len(x) for x in paras if x not in seen)
        rows.append({"quote": c.quote, "claim": c.claim, "new": new, "old": sum(x in seen for x in paras),
                     "widened": False, "evidence": prompts.evidence_text(parts, hits)})
    # 첫 검수에서 근거 단락을 하나도 못 본 진술, 새로 나온 단락이 긴 진술부터
    order = sorted((i for i, r in enumerate(rows) if r["new"]), key=lambda i: (rows[i]["old"] > 0, -rows[i]["new"], i))
    picked = sorted(order[:prompts.WIDEN_MAX])
    for i in picked:
        rows[i]["widened"] = True
    stats = {"claims": len(claims), "widened": len(picked), "added": 0,
             "claims_tokens": est_tokens(prompts.SYSTEM_CLAIMS + first), "verdict_tokens": 0,
             "rows": [{k: v for k, v in r.items() if k != "evidence"} for r in rows]}
    if not picked:
        return report, stats
    last = prompts.widen_prompt(p, n, [(claims[i], rows[i]["evidence"]) for i in picked], report.issues)
    stats["verdict_tokens"] = est_tokens(prompts.SYSTEM_CHECKER + last)
    more = (part("widen") if part else llm).json(prompts.SYSTEM_CHECKER, last, ConsistencyReport, hint={"episode": n, **hint})
    issues = list(report.issues)
    for x in more.issues:
        if x.current_quote.strip() and not any(_same_quote(x.current_quote, y.current_quote) for y in issues):
            issues.append(x)
    stats["added"] = len(issues) - len(report.issues)
    return ConsistencyReport(episode=n, issues=issues), stats


def check_scene(llm: LLM, p: Project, n: int, hint: dict | None = None) -> tuple[ConsistencyReport, dict]:
    """장면 상태표 검수 (연구 화면에서만 씀): 검수 모델이 이번 화 본문을 장면 상태표(향한 쪽, 두 손, 착용 겹침,
    몸 앞뒤, 물건 자리)로 먼저 옮겨 적고, 그 표와 어긋나는 동선만 찾는다. 옛 화 · 설정은 넣지 않는다. (보고서, 상태표와 크기)"""
    from .context import est_tokens

    ep = p.episode(n)
    if not ep.text:
        raise ValueError(f"{n}화 본문이 없어요")
    prompt = prompts.scene_prompt(p, n)
    sc = llm.json(prompts.SYSTEM_SCENE, prompt, SceneCheck, hint={"episode": n, "text": ep.text, **(hint or {})})
    beats = sc.beats[:prompts.SCENE_BEATS]
    stats = {"chars": len(prompt), "tokens": est_tokens(prompts.SYSTEM_SCENE + prompt), "beats": [b.model_dump() for b in beats]}
    return ConsistencyReport(episode=n, issues=sc.issues), stats


def check_two_step(llm: LLM, judge: Judge, p: Project, n: int, hint: dict | None = None) -> tuple[ConsistencyReport, dict]:
    """두 걸음 검수 (연구 화면에서만 씀): 검수 모델이 이번 화의 사실 진술을 뽑고, 판단기가 진술마다 옛 화 · 설정 · 사실과 견줘
    '어긋남' 확률을 내고, 의심 진술만 근거와 함께 검수 모델이 판정한다. 옛 화는 직전 화까지 모두 찾아본다.
    같은 화 안의 동선 · 시점처럼 옛 자료와 견주지 않는 검사는 하지 않는다. (보고서, 단계별 크기 · 판단 기록)"""
    from .context import PassageIndex, est_tokens

    ep = p.episode(n)
    if not ep.text:
        raise ValueError(f"{n}화 본문이 없어요")
    hint = hint or {}
    first = prompts.claims_prompt(p, n)
    claims = llm.json(prompts.SYSTEM_CLAIMS, first, ClaimSet, hint={"episode": n, "text": ep.text}).claims
    claims = [c for c in claims if c.quote.strip() and c.claim.strip()][:prompts.TWOSTEP_CLAIMS]
    index = PassageIndex(p, n)
    evidence = [prompts.claim_evidence(p, n, c, index) for c in claims]
    qs = [Question(id=str(i), state=ev, text=prompts.claim_question(c), options=prompts.CLAIM_OPTIONS)
          for i, (c, ev) in enumerate(zip(claims, evidence))]
    answers = judge.decide(prompts.SYSTEM_JUDGE_CHECK, qs) if qs else []
    bad = [a.probs[1] if len(a.probs) > 1 else 0.0 for a in answers]
    order = sorted((i for i, x in enumerate(bad) if x >= prompts.TWOSTEP_FLAG), key=lambda i: -bad[i])[:prompts.TWOSTEP_FLAG_MAX]
    flagged = sorted(order)
    stats = {"claims": len(claims), "flagged": len(flagged),
             "first_tokens": est_tokens(prompts.SYSTEM_CLAIMS + first),
             "judge_tokens": sum(est_tokens(prompts.SYSTEM_JUDGE_CHECK + prompts.judge_message(q.state, q.text, q.options)) for q in qs),
             "verdict_tokens": 0,
             "judged": [{"quote": c.quote, "claim": c.claim, "probs": a.probs, "mass": a.mass, "flagged": i in flagged}
                        for i, (c, a) in enumerate(zip(claims, answers))]}
    if not flagged:
        return ConsistencyReport(episode=n, issues=[]), stats
    last = prompts.verdict_prompt(p, n, [(claims[i], evidence[i], bad[i]) for i in flagged])
    stats["verdict_tokens"] = est_tokens(prompts.SYSTEM_CHECKER + last)
    report = llm.json(prompts.SYSTEM_CHECKER, last, ConsistencyReport, hint={"episode": n, **hint})
    report.episode = n
    return report, stats


def apply_check(p: Project, r: ConsistencyReport, source: CheckSource = "api", widen: bool = False) -> CheckRound:
    """검수 결과는 참고용 경고라 승인 없이 화에 붙여 둔다. 지적 목록에 회차 하나로 합친다 (findings.merge:
    작가가 그대로 둠 · 잘못 짚음으로 정한 지적은 다시 나와도 그대로)."""
    ep = p.episode(r.episode)
    if not ep.text:
        raise ValueError(f"{r.episode}화 본문이 없어요")
    return findings.merge(ep, r.issues, _now(), text_basis(ep.text), source, widen)


def style_baseline(p: Project) -> metrics.StyleMetrics:
    """레퍼런스 원문 전체로 잰 값이 없으면(예전 프로젝트) 발췌 문단으로 잰다."""
    return p.style_baseline or metrics.measure("\n\n".join(p.style.sample_passages))


VOICE_SKIP = ("과거형 서술 비율", "문체 거리")  # 서술 말투가 있는 화에서 빼는 어미 관련 경고


def style_drift(p: Project, n: int) -> tuple[metrics.StyleMetrics, list[str]]:
    """이번 화 문체 지표와 경고. 기준값과의 차이, 문체 거리, 표지 빈도, 예시 문단 베끼기를 본다."""
    text = p.episode(n).text
    base = style_baseline(p)
    cur = metrics.measure(text, p.style.banned_phrases)
    cur.style_distance = metrics.style_distance(base, text)
    warns = metrics.drift(base, cur)
    voiced = (c := prompts.pov_character(p, n)) is not None and bool(c.narration_voice.strip())
    if voiced:  # 시점 인물의 서술 말투로 쓴 화는 어미가 기준 원문과 달라야 맞다
        warns = [w for w in warns if not w.startswith(VOICE_SKIP)]
    marks = [] if voiced else metrics.marker_warnings(p.style.markers, text)
    if marks:
        warns.append(f"문체 표지: {', '.join(marks)}")
    warns[:0] = [f"장치 {w}" for w in metrics.device_warnings(p.style.devices, p.episodes, n, text)]  # 자동 집필 기록은 앞 3개만 남긴다
    copied = metrics.copied_sentences(text, p.style.sample_passages)
    if copied:
        quotes = ", ".join(f"'{s[:30]}{'…' if len(s) > 30 else ''}'" for s in copied[:3])
        warns.append(f"예시 문단을 옮긴 문장 {len(copied)}개: {quotes}")
    return cur, warns


# ---------- 5-1. 초반 1~3화: 지표, 흡입력 판정, 여는 방식 여러 안 ----------

def hero_name(p: Project) -> str:
    """주인공 이름: 역할에 '주인공'이 들어간 인물, 없으면 첫 주역."""
    lead = next((c for c in p.characters if "주인공" in c.role), None) or next(
        (c for c in p.characters if c.tier == "main"), None)
    return lead.name if lead else ""


def lore_terms(p: Project) -> list[str]:
    """설정어: 세계관 장소 이름('등대: 설명' 이면 '등대')과 이야기 요소 이름 · 다른 이름."""
    import re

    out = [re.split(r"[:(（\-–—,]", x, maxsplit=1)[0].strip() for x in p.world.locations]
    for el in p.elements:
        out += [el.name, *el.aliases]
    return [x for x in dict.fromkeys(out) if len(x) >= 2]


def opening_metrics(p: Project, n: int, text: str | None = None) -> tuple[metrics.OpeningMetrics, list[str]]:
    """1~3화 초반 지표와 경고. text 를 주면 그 글(비교본)을 잰다."""
    body = p.episode(n).text if text is None else text
    hero = hero_name(p)
    m = metrics.measure_opening(body, [c.name for c in p.characters], hero, lore_terms(p))
    return m, metrics.opening_warnings(m, n, style_baseline(p).dialogue_ratio or None, hero)


def text_basis(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


def check_hook(llm: LLM, p: Project, n: int, text: str | None = None) -> HookReport:
    """1~3화 흡입력 판정. 저장하지 않는다. text 를 주면 그 글(비교본)을 판정한다."""
    if not prompts.is_opening(n):
        raise ValueError(f"흡입력 판정은 1~{prompts.OPENING_EPISODES}화만 해요")
    body = p.episode(n).text if text is None else text
    if not body.strip():
        raise ValueError(f"{n}화 본문이 없어요")
    rep = llm.json(prompts.SYSTEM_HOOK, prompts.hook_prompt(p, n, body), HookReport,
                   hint={"episode": n, "text": body})
    return clean_hook(rep, n, body)


def clean_hook(rep: HookReport, n: int, text: str) -> HookReport:
    """본문에서 찾지 못한 인용은 지우고 점수를 1로 내린다 (LLM 판정자가 근거 없이 후하게 주는 것을 막는다).
    같은 항목이 둘이면 앞의 것만, 빠진 항목은 그대로 둔다. 전제 문장의 위치를 잰다."""
    rep.episode = n
    seen, items = set(), []
    for it in rep.items:
        if it.aspect in seen:
            continue
        seen.add(it.aspect)
        it.score = min(5, max(1, it.score))
        if it.quote.strip() and not elements.find(text, it.quote):
            it.quote, it.score = "", 1
            it.note = (it.note + " (근거 문장을 본문에서 찾지 못해 1점으로 내림)").strip()
        items.append(it)
    rep.items = items
    hit = elements.find(text, rep.premise_quote) if rep.premise_quote.strip() else None
    if rep.premise_quote.strip() and not hit:
        rep.premise_quote = ""
    rep.premise_at = hit[0] if hit else -1
    rep.basis, rep.checked_at = text_basis(text), _now()
    return rep


def apply_hook(p: Project, rep: HookReport) -> None:
    """판정은 참고용이라 승인 없이 화에 붙인다. 다시 판정하면 덮어쓴다."""
    p.episode(rep.episode).hook = rep


def hook_stale(p: Project, n: int) -> bool:
    e = p.episode(n)
    return bool(e.hook) and e.hook.basis != text_basis(e.text)


def _approaches(approaches: list[str] | None) -> list[str]:
    picked = [a for a in dict.fromkeys(approaches or prompts.DEFAULT_APPROACHES) if a in prompts.OPENING_APPROACHES]
    if not 2 <= len(picked) <= 4:
        raise ValueError(f"여는 방식은 2~4개를 고르세요: {', '.join(prompts.OPENING_APPROACHES)}")
    return picked


def suggest_openings(llm: LLM, p: Project, n: int, approaches: list[str] | None = None) -> OpeningPlots:
    """n화(1~3) 플롯을 여는 방식만 달리한 여러 안. 저장하지 않는다."""
    if not prompts.is_opening(n):
        raise ValueError(f"여는 방식 비교는 1~{prompts.OPENING_EPISODES}화만 해요")
    cur = next((e for e in p.episodes if e.plot.number == n), None)
    if cur and cur.status in LOCKED:
        raise ValueError(f"{n}화는 본문이 있어 플롯을 바꿀 수 없어요")
    if not p.beats() or not p.act_for(n):
        raise ValueError("다음 아크를 먼저 기획하세요" if p.serial else "기승전결 구조(arc)를 먼저 만드세요")
    ways = _approaches(approaches)
    out = llm.json(prompts.SYSTEM_PLANNER, prompts.opening_plots_prompt(p, n, ways), OpeningPlots,
                   hint={"episode": n, "approaches": ways, "act": p.act_for(n).name})
    return clean_openings(p, n, out, ways)


def clean_openings(p: Project, n: int, out: OpeningPlots, ways: list[str]) -> OpeningPlots:
    """요청한 방식만 한 번씩, 화 번호와 구간은 맞추고, 작가가 붙인 이야기 줄기는 지킨다."""
    cur = next((e for e in p.episodes if e.plot.number == n), None)
    act = p.act_for(n)
    keep, seen = [], set()
    for o in out.options:
        if o.approach not in ways or o.approach in seen:
            continue
        seen.add(o.approach)
        o.plot.number = n
        if act:
            o.plot.act = act.name
        if cur and (cur.plot.storyline or cur.plot.threads) and not (o.plot.storyline or o.plot.threads):
            o.plot.storyline, o.plot.threads = cur.plot.storyline, list(cur.plot.threads)
        keep.append(o)
    if not keep:
        raise ValueError("AI가 요청한 여는 방식으로 안을 내지 않았어요. 다시 시도하세요")
    out.options = keep
    return out


def apply_opening(p: Project, n: int, plot: EpisodePlot) -> None:
    """고른 안을 n화 플롯으로. 본문이 있는 화는 막고, 확정했던 화는 초안으로 돌린다 (플롯 대화 반영과 같은 규칙)."""
    if plot.number != n:
        raise ValueError(f"{n}화 플롯이 아니에요 ({plot.number}화)")
    by_no = {e.plot.number: e for e in p.episodes}
    cur = by_no.get(n)
    if cur and cur.status in LOCKED:
        raise ValueError(f"{n}화는 본문이 있어 플롯을 바꿀 수 없어요")
    act = p.act_for(n)
    if act:
        plot.act = act.name
    plot = plot.model_copy(deep=True)
    if cur:  # 여는 방식과 상관없는 칸은 작가가 정한 값을 지킨다: 시점, 서술 방식, 회수 복선, 넣어 둔 인물
        plot.pov = cur.plot.pov or plot.pov
        plot.pov_mode = cur.plot.pov_mode or plot.pov_mode
        plot.foreshadow_payoff = cur.plot.foreshadow_payoff or plot.foreshadow_payoff
        plot.characters = list(dict.fromkeys(cur.plot.characters + plot.characters))
    # 처음 고르기 전 플롯을 남겨 새로고침 뒤에도 되돌릴 수 있게 한다. 다른 안으로 다시 바꿔도 처음 것을 지킨다
    prev = (cur.opening_prev or cur.plot).model_copy(deep=True) if cur else None
    by_no[n] = Episode(plot=plot, opening_prev=prev)
    storylines.clean_plot(p, by_no[n])
    p.episodes = [by_no[k] for k in sorted(by_no)]
    sync_candidates(p)


def undo_opening(p: Project, n: int) -> None:
    """n화 플롯을 여는 방식 안을 처음 고르기 전으로 되돌린다. 화는 초안이 된다 (확정했던 화는 다시 확정한다)."""
    e = p.episode(n)
    if e.opening_prev is None:
        raise ValueError(f"{n}화는 여는 방식 안을 고르기 전 플롯이 남아 있지 않아요")
    if e.status in LOCKED:
        raise ValueError(f"{n}화는 본문이 있어 플롯을 바꿀 수 없어요")
    plot = e.opening_prev.model_copy(deep=True)
    act = p.act_for(n)
    if act:
        plot.act = act.name
    p.episodes = [Episode(plot=plot) if x.plot.number == n else x for x in p.episodes]
    storylines.clean_plot(p, p.episode(n))
    sync_candidates(p)


def opening_drafts(llm: LLM, p: Project, n: int, approaches: list[str] | None = None) -> dict[str, str]:
    """n화(1~3) 본문을 여는 방식마다 하나씩 쓴다. 키는 방식 이름. 저장은 호출자가 한다 (research.save_compare)."""
    if not prompts.is_opening(n):
        raise ValueError(f"여는 방식 비교는 1~{prompts.OPENING_EPISODES}화만 해요")
    return {prompts.OPENING_APPROACHES[a][0]: write_episode(llm, p, n, a) for a in _approaches(approaches)}


# ---------- 6. 상태 갱신 ----------

def extract_state(llm: LLM, p: Project, n: int) -> StateDelta:
    if not p.episode(n).text:
        raise ValueError(f"{n}화 본문이 없어요")
    carried = carried_delta(p, n)
    if carried is not None:
        return carried
    delta = llm.json(prompts.SYSTEM_EDITOR, prompts.state_prompt(p, n), StateDelta,
                     hint={"episode": n, "stats": statwin.enabled(p)})
    delta.episode = n
    clean_delta(p, delta)
    return delta


def clean_delta(p: Project, d: StateDelta) -> None:
    """AI 나 채팅 앱이 낸 상태 변경안 정리. 기능마다 하는 일(복선 문장 맞추기, 새 장소 거르기, 이동 거리 · 상태창 경고 등)은
    features.CLEAN 목록에 있다."""
    features.clean(p, d)


def apply_delta(p: Project, d: StateDelta) -> None:
    ep = p.episode(d.episode)
    dynamics.ensure_initial(p)
    ep.summary = d.summary
    ep.status, ep.final_text = "finalized", ""
    _add_characters(p, d.new_characters, d.episode)
    features.apply(features.APPLY_FIRST, p, d)  # 설정 바꾸기 제안 · 새 장소
    ep.auto = False  # 자동 집필은 반영한 뒤 True 로 표시한다

    for upd in d.character_updates:
        cur = p.state_of(upd.character_id)
        if cur is None:
            cur = upd.model_copy(deep=True, update={"stats": []})
            p.states.append(cur)
        else:
            for field in ("emotional_state", "current_goal", "location", "attire", "notes"):
                if getattr(upd, field):
                    setattr(cur, field, getattr(upd, field))
            cur.knows += [k for k in upd.knows if k not in cur.knows]
        statwin.merge(p, cur, upd.stats, d.episode)  # +3 같은 바뀐 양은 여기서 값으로 바꾸고 기록한다

    for upd in d.relationship_updates:
        if upd.a == upd.b:  # 같은 인물끼리의 관계는 두지 않는다 (화면 저장이 막는 관계, validate_relationships)
            continue
        key = frozenset((upd.a, upd.b))
        for r in p.relationships:
            if frozenset((r.a, r.b)) == key:
                r.type, r.description = upd.type or r.type, upd.description or r.description
                if not d.events:  # 사건 없이 수치만 온 예전 형식: 양방향 온기를 affinity 에 맞춘다
                    r.affinity, r.tension = upd.affinity, upd.tension
                    for s, t in ((r.a, r.b), (r.b, r.a)):
                        dynamics.get_tie(p.ties, s, t).warmth = dynamics.clip(upd.affinity / 5)
                break
        else:
            p.relationships.append(upd)
            dynamics.seed_ties(p)

    known_secrets = {s.id for s in p.secrets}
    # 복사해 넣는다. 사건이 비밀을 드러내 hidden_from 을 줄여도 기록(history)의 처음 모습은 남아야 다시 계산할 수 있다
    p.secrets += [s.model_copy(deep=True) for s in d.secrets_added if s.id not in known_secrets]
    events = [e.model_copy(update={"episode": d.episode}) for e in d.events if e.kind != "수동보정"]
    dynamics.run_episode(p, d.episode, events, ep.plot.characters)
    p.events += events

    p.facts += [f for f in d.new_facts if f not in p.facts]
    known = {f.id for f in p.foreshadows}
    p.foreshadows += [f for f in d.foreshadow_planted if f.id not in known]
    for f in p.foreshadows:
        if f.id in d.foreshadow_resolved:
            f.status, f.payoff_ep = "resolved", d.episode
    features.apply(features.APPLY_LAST, p, d)  # 복선 문장 · 작품 속 시간
    p.history.append(d)
    dynamics.take_snapshot(p, d.episode)
    if p.serial:
        prune_snapshots(p)


SNAPSHOT_KEEP = 20  # 장편에서 남기는 최근 스냅샷 수. 시작점과 아크가 끝난 화는 늘 남긴다


def prune_snapshots(p: Project) -> None:
    """장편은 화마다 상태 전체를 복사하면 project.json 이 너무 커진다. 관계는 사건 로그로 다시 계산할 수 있다.
    작품 설정 keep_snapshots 를 켜면(연구용 작품) 지우지 않는다."""
    if p.settings.keep_snapshots:
        return
    ends = {a.end_ep for a in p.story_arcs}
    recent = sorted(s.episode for s in p.snapshots)[-SNAPSHOT_KEEP:]
    keep = {0, *ends, *recent}
    p.snapshots = [s for s in p.snapshots if s.episode in keep]


def adjust_tie(p: Project, source: str, target: str, warmth: float | None, trust: float | None) -> None:
    """사용자가 관계 수치를 직접 고친다. 마지막으로 확정된 화의 수동보정 사건으로 기록한다."""
    done = [e.plot.number for e in p.episodes if e.status == "finalized"]
    n = max(done, default=0)
    dynamics.ensure_initial(p)
    e = StoryEvent(episode=n, actor=source, target=target, kind="수동보정", set_warmth=warmth, set_trust=trust)
    dynamics.apply_event(p.ties, p.secrets, p.params, e)
    dynamics.sync_relationships(p)
    p.events.append(e)
    dynamics.take_snapshot(p, n)


def revert(p: Project, n: int) -> None:
    """n화 상태 반영 직후로 되돌린다. 이후 화의 본문은 남기고 상태 반영만 취소한다."""
    snap = p.snapshot(n)
    if snap is None:
        raise ValueError(f"{n}화 스냅샷이 없어요 (있는 화: {[s.episode for s in p.snapshots]})")
    # 되돌리는 반영이 더한 인물(new_characters)도 되돌린다. 뒤 화 플롯에 나오면 지우지 않고 인물 후보로 돌린다
    added = {c.id for d in p.history if d.episode > n for c in d.new_characters}
    if added:
        back = [c for c in p.characters if c.id in added]
        p.characters = [c for c in p.characters if c.id not in added]
        have = {c.id for c in p.cast_candidates}
        p.cast_candidates += [c for c in back if c.id not in have]
    features.revert(features.REVERT_FIRST, p, n, snap)  # 뒤 반영이 본문에서 등록한 장소
    p.states = [s.model_copy(deep=True) for s in snap.states]
    p.relationships = [r.model_copy(deep=True) for r in snap.relationships]
    p.ties = [t.model_copy(deep=True) for t in snap.ties]
    p.secrets = [s.model_copy(deep=True) for s in snap.secrets]
    p.facts = list(snap.facts)
    p.foreshadows = [f.model_copy(deep=True) for f in snap.foreshadows]
    p.events = [e for e in p.events if e.episode <= n]
    p.history = [d for d in p.history if d.episode <= n]
    p.snapshots = [s for s in p.snapshots if s.episode <= n]
    features.revert(features.REVERT_LAST, p, n, snap)  # 복선 문장 · 상태창 기록 · 작품 속 시간 · 설정 변경 기록
    for ep in p.episodes:
        if ep.plot.number > n and ep.status == "finalized":
            ep.status, ep.summary, ep.auto, ep.final_text = "written", "", False, ""
    sync_candidates(p)


# ---------- 6-1. 반영 뒤 고친 화 다시 맞추기 ----------
# 반영이 끝난 화의 본문을 고쳐도 반영된 상태는 그대로 둔다 (뒤 화가 그 위에 쌓였다). 고친 본문에서 변경안을 다시 뽑아
# 뒤 화의 전제를 흔들지 않는 것(요약, 새 사실, 새 복선, 새 장소)만 골라 더한다. 인물 상태 · 관계 · 비밀까지 바꾸려면 그 화부터 반영을 취소한다.

def apply_restate(p: Project, d: StateDelta) -> dict:
    """반영 뒤 고친 화에 요약 · 새 사실 · 새 복선 · 새 장소만 반영한다. 그 화와 뒤 화의 스냅샷 · 반영 기록에도 넣어 되돌리기와 맞춘다."""
    n = d.episode
    ep = p.episode(n)
    if ep.status != "finalized":
        raise ValueError(f"{n}화는 상태 반영이 끝난 화가 아니에요. 상태 승인 화면에서 반영하세요")
    summary = d.summary.strip()
    facts = list(dict.fromkeys(f for f in d.new_facts if f.strip() and f not in p.facts))
    known = {f.id for f in p.foreshadows}
    plants = [f.model_copy(update={"planted_ep": n, "status": "open", "payoff_ep": None}) for f in d.foreshadow_planted if f.id not in known]
    if summary:
        ep.summary = summary
    p.facts += facts
    p.foreshadows += plants
    added = elements.add_places(p, d.new_places, n, "본문")
    places = [x for x in d.new_places if x.name.strip() in added]
    for snap in p.snapshots:
        if snap.episode >= n:
            snap.facts += [f for f in facts if f not in snap.facts]
            snap.foreshadows += [f.model_copy(deep=True) for f in plants]
    rec = next((h for h in reversed(p.history) if h.episode == n), None)
    if rec is not None:
        rec.summary = summary or rec.summary
        rec.new_facts += facts
        rec.foreshadow_planted += [f.model_copy(deep=True) for f in plants]
        rec.new_places += [x.model_copy(deep=True) for x in places]
    ep.final_text = ""
    return {"summary": bool(summary), "facts": len(facts), "foreshadows": len(plants), "places": len(places)}


def keep_state(p: Project, n: int) -> None:
    """반영 뒤 고쳤지만 상태는 그대로 둬도 된다고 정한다 (오타 · 문장 다듬기). 반영 뒤 고침 표시를 지운다."""
    ep = p.episode(n)
    if ep.status != "finalized":
        raise ValueError(f"{n}화는 상태 반영이 끝난 화가 아니에요")
    ep.final_text = ""


def recalc(p: Project) -> None:
    """계수(params)를 바꾼 뒤 사건 로그를 처음부터 다시 재생해 현재 관계를 다시 계산한다."""
    p.ties = dynamics.replay(p)
    dynamics.sync_relationships(p)
