"""생성 파이프라인. 각 단계는 Project 를 받아 제안을 만들고, 반영은 호출자가 승인 후 한다."""
from __future__ import annotations

import contextvars
import logging

import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from typing import Callable

from . import dynamics, elements, illust, metrics, naming, prompts, renumber, setupchat, storylines
from .judge import Judge, Question
from .llm import LLM, PREFIX_HINT, Interrupted, OutputCut, dump, family_text, out_cap, was_cut
from . import anchor, board, cancel, charlog, context, features, findings, foreshadows, heatplan, knows, metatail, stage, statwin, usage
from . import offscreen, regexrules
from .sent import SentPrompt, SentRetry
from .sent import record as sent_record
from .schema import CoordDraft, CoordMemo, OffscreenSet
from .schema import RuleChange, RuleRun
from .schema import CueSheet, CueSheetDraft, Finding, MetaCut, FindingRecheck, FixBatch, FixOption, FixPatch, FixRecheckItem, FixRecheckReport, FixSet, RevArcSet, RevEpisodeDraft, RevLineSet
from .schema import ParagraphAnatomy, ReaderCheck, SceneCard, SceneVariant, SceneVariants, StudioCandidate, StudioDraft
from .schema import (
    AddedItems,
    Act,
    AuditReport,
    ArcEdit,
    ArcPlan,
    HeatArcPlan,
    HeatArcProposal,
    HeatProposal,
    ClaimSet,
    ArcProposal,
    ArcUndo,
    Character,
    CharacterState,
    CharacterVisual,
    KnowsFoldSet,
    ChatMessage,
    ChatScope,
    CheckRound,
    CheckSource,
    ConsistencyIssue,
    ConsistencyReport,
    StageDraft,
    StageProposal,
    StageRoom,
    StageScene,
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
    FieldIdeas,
    PassageRevision,
    PlotBatch,
    PlotRevision,
    PlotUndo,
    Project,
    Recap,
    Selection,
    SeriesPlan,
    SetupRevision,
    SetupSuggestion,
    Snapshot,
    StateDelta,
    StateDeltaAI,
    StoryArc,
    StoryEvent,
    Storyline,
    StoryTime,
    Storyboard,
    StoryboardDraft,
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
    to_delta,
)
from .logline import josa


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



def field_stage(field: str) -> str:
    """칸 하나 후보를 부를 단계. 제목은 이름 짓기라 'name', 나머지는 기획 'plan'."""
    return "name" if field == "meta.title" else "plan"


def suggest_field(llm: LLM, p: Project, field: str, n: int = 3) -> FieldIdeas:
    """설정 칸 하나의 AI 후보. 저장하지 않는다 (작가가 하나를 고르면 화면이 칸에 넣고 작품을 저장한다).
    field 는 화면 칸 경로 (인물 칸은 characters.<번호>.<칸>). 빈 후보, 겹치는 후보, 지금 값과 같은 후보는 뺀다.
    목록 칸(prompts.IDEA_LISTS)은 후보를 한 줄로 고치고, 목록에 이미 있는 항목은 뺀다."""
    key = prompts.idea_key(field)
    if key not in prompts.FIELD_IDEAS:
        raise KeyError(f"후보를 받을 수 없는 칸이에요: {field}")
    try:
        prompts.idea_character(p, field)
    except IndexError:
        raise KeyError(f"없는 인물의 칸이에요: {field}") from None
    ideas = llm.json(prompts.SYSTEM_PLANNER, prompts.field_prompt(p, field, n), FieldIdeas, hint={"field": key, "n": n})
    now, seen, out = prompts.field_value(p, field), set(), []
    listed = key in prompts.IDEA_LISTS  # 목록 칸: 후보는 한 줄, 이미 있는 항목은 뺀다
    taken = set(now.splitlines()) if listed else {now}
    quotes = "\"'“”‘’"
    for o in ideas.options:
        o.text, o.reason = o.text.strip(), o.reason.strip()
        if key == "characters.*.speech_style":  # 말투는 대사 예시가 따옴표로 끝나므로 양끝을 함께 감쌌을 때만 벗긴다
            if len(o.text) > 1 and o.text[0] in quotes and o.text[-1] in quotes:
                o.text = o.text[1:-1].strip()
        else:
            o.text = o.text.strip(quotes)
        if listed:
            o.text = " ".join(o.text.split()).lstrip("-• ").strip()
        if field.startswith("meta.logline_parts."):
            o.text = o.text.rstrip(".")
        if o.text and o.text not in taken and o.text not in seen:
            seen.add(o.text)
            out.append(o)
    ideas.options = out[:n]
    return ideas

def require_previous(p: Project, n: int) -> None:
    """이전 화가 모두 반영(finalized)돼야 n화를 쓰거나 반영한다. 인물 상태가 화 순서대로 쌓이게 하는 규칙이다."""
    unfinished = [e.plot.number for e in p.episodes if e.plot.number < n and e.status != "finalized"]
    if unfinished:
        raise ValueError(f"이전 화({', '.join(map(str, unfinished))}화)의 상태 반영이 끝나지 않았어요")


APPLY_STATUS = {"draft": "초안", "confirmed": "확정", "written": "작성됨", "finalized": "반영 완료"}


def check_applicable(p: Project, n: int) -> None:
    """n화 상태 변경안을 반영해도 되는지 본다. 본문이 쓰인(written) 화만, 이전 화가 모두 반영됐을 때만 된다.
    웹 반영 · 명령줄 update · 플레이 · 자동 집필이 같은 규칙을 쓴다. 복사본에 해 보는 미리 보기는 부르지 않는다."""
    st = p.episode(n).status
    if st == "finalized":
        raise ValueError(f"{n}화는 이미 상태를 반영했어요")
    if st != "written":
        raise ValueError(f"{n}화는 본문이 작성된 상태가 아니에요 (현재: {APPLY_STATUS.get(st, st)})")
    require_previous(p, n)


# 설정 제안이 이미 있는 인물에게 채우는 칸 (비어 있을 때만). 이름 · id · 비중 · 서술 말투 · 작가 전용 칸은 건드리지 않는다
FILL_CHAR_FIELDS = ("role", "age", "gender", "appearance", "personality", "background", "goal", "wound", "speech_style", "secrets", "arc")


def fill_character(old: Character, new: Character) -> list[str]:
    """old 의 빈 칸을 new 의 값으로 채우고 채운 칸 이름을 돌려준다. 이미 적힌 칸은 그대로 둔다."""
    out = []
    for f in FILL_CHAR_FIELDS:
        cur, val = getattr(old, f), getattr(new, f)
        if isinstance(val, list):
            val = [x.strip() for x in val if x.strip()]
        elif isinstance(val, str):
            val = val.strip()
        if not cur or (isinstance(cur, str) and not cur.strip()):
            if val:
                setattr(old, f, val)
                out.append(f)
    return out


def apply_setup(p: Project, s: SetupSuggestion) -> None:
    """기존 입력은 유지하고 빈칸만 채운다. 이미 있는 인물(같은 id, 같은 이름)은 빈 칸만 채운다(fill_character).
    제안 인물의 id 가 이미 있는 인물과 겹쳐도 이름이 다르면 다른 인물로 보고
    새 id 를 붙여 넣고, 그 인물의 관계도 새 id 로 잇는다. 양쪽 인물이 없는 관계는 넣지 않는다.
    1화 반영 뒤에 채운 인물 칸은 설정 변경 기록(charlog.record_author)에 남는다."""
    before = p.model_copy(update={"characters": [c.model_copy() for c in p.characters]})  # 기록용: 인물만 따로 둔다
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
            if "goal" in fill_character(old, c):  # 같은 인물: 빈 칸만
                st = next((x for x in p.states if x.character_id == old.id), None)
                if st is not None and not st.current_goal:
                    st.current_goal = old.goal
            continue
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
    charlog.record_author(before, p)


def _init_states(p: Project) -> None:
    have = {s.character_id for s in p.states}
    for c in p.characters:
        if c.id not in have:
            p.states.append(CharacterState(character_id=c.id, current_goal=c.goal))


# ---------- 2. 스타일 레퍼런스 ----------

def analyze_style(llm: LLM, sample: str, names: list[str] | None = None, passages: bool = True) -> StyleProfile:
    """passages 가 거짓이면 대표 문단을 묻지 않는다 (prompts.style_prompt)."""
    profile = llm.json(prompts.SYSTEM_PLANNER, prompts.style_prompt(sample, passages), StyleProfile)
    count_markers(profile, sample, names)
    return profile


MARKER_MIN_HANGUL = 2  # 표지와 장치 단서는 한글이 이만큼 있어야 쓴다 ('다' · '.' 는 거의 모든 글에 나와 뜻이 없다)


def _marker_ok(text: str, sample: str, names: list[str]) -> bool:
    m = metrics._marker(text)
    return (len(re.findall(r"[가-힣]", m)) >= MARKER_MIN_HANGUL and not any(n in m for n in names)
            and metrics.marker_count(sample, text) > 0)


def count_markers(profile: StyleProfile, sample: str, names: list[str] | None = None) -> None:
    """표지마다 원문 1,000자당 횟수를 센다. 모델이 적은 빈도는 믿지 않는다. 원문에 없는 표지, 한글이 2자 미만인 표지,
    인물 이름(names, 2자 이상)이 든 표지는 뺀다. 장치 단서도 같게 거르고, 원문 표본에 없는 장치 예시는 비운다."""
    names = [n.strip() for n in names or [] if len(n.strip()) >= 2]
    keep = []
    for m in profile.markers:
        if _marker_ok(m.text, sample, names):
            m.per_1k = metrics.marker_rate(sample, m.text)
            keep.append(m)
    profile.markers = keep
    flat = re.sub(r"\s+", "", sample)
    for d in profile.devices:
        d.cues = [c for c in d.cues if _marker_ok(c, sample, names)]
        d.every = max(0, d.every)
        if d.example and re.sub(r"\s+", "", d.example) not in flat:
            d.example = ""  # 지어낸 예시는 원문 문체가 아니다


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


def check_learnable(p: Project) -> list:
    """규칙을 찾을 만큼 수정 기록이 있는지 본다. 모자라면 ValueError (작업 style_learn 이 시작 전에 부른다). 쓸 수정 기록을 돌려준다."""
    edits = learnable_edits(p)
    if len(edits) < LEARN_MIN:
        raise ValueError(f"쓸 수 있는 수정 기록이 {len(edits)}건이라 너무 적어요. 본문을 {LEARN_MIN}건 이상 고친 뒤에 해 주세요 "
                         "(되돌린 수정, 동선 맞추기, 새로 써 넣기만 한 것은 빼고 세어요)")
    return edits


def learn_style(llm: LLM, p: Project) -> StyleLearning:
    """수정 기록에서 문체 규칙 후보를 찾는다. 저장하지 않는다."""
    edits = check_learnable(p)
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
                   "inner_monologue", "pacing", "scene_transition", "vocabulary", "sound_effects")
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


def apply_style_edits(p: Project, rev: StyleRevision, keys: list[str], episode: int = 0) -> tuple[list[str], StyleProfile]:
    """문체 변경안에서 고른 칸만 작품 문체에 넣는다. (넣은 칸 이름, 넣기 전 문체) 를 돌려준다. 고른 칸이 없으면 ValueError.
    모든 칸을 넣었고 시험 문단이 있으면 예시 칸(style_example)으로 옮긴다. episode 는 시험 문단이 고쳐 쓴 화.
    문체 대화(apply_style_chat)와 대화 에이전트의 문체 도구(agent_style.apply)가 함께 쓴다."""
    picked = [e for e in rev.edits if e.key in set(keys)]
    if not picked:
        raise ValueError("적용할 칸을 고르세요")
    before = p.style.model_copy(deep=True)
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
    if rev.preview and len(picked) == len(rev.edits):  # 시험 문단이 그린 문체가 그대로 들어갔으면 예시 칸으로 옮긴다
        p.style_example = StyleExample(text=rev.preview, source=rev.preview_source,
                                       episode=episode if rev.preview_source else 0,
                                       by="chat", profile=p.style.model_copy(deep=True), at=_now())
    return [e.key for e in picked], before


def undo_style_edits(p: Project, rev: StyleRevision, applied: list[str], before: StyleProfile) -> tuple[list[str], list[str]]:
    """적용한 문체 칸을 넣기 전으로 돌린다. 그 뒤에 다시 고친 칸은 건드리지 않는다. (되돌린 칸, 그대로 둔 칸) 을 돌려준다."""
    by = {e.key: e for e in rev.edits}
    done, kept = [], []
    for k in applied:
        now = getattr(p.style, k)
        if k in by and _style_same(k, now, style_value(by[k])):
            setattr(p.style, k, getattr(before, k))
            done.append(k)
        else:
            kept.append(k)
    return done, kept


def apply_style_chat(p: Project, i: int, keys: list[str]) -> list[str]:
    """i 번째 메시지의 문체 변경안에서 고른 칸만 작품 문체에 넣는다. 적용하기 전 문체를 메시지에 남긴다. 넣은 칸 이름을 돌려준다."""
    m = _style_message(p, i)
    if m.outcome:
        raise ValueError("이미 처리한 변경안이에요")
    asked = p.chat("style").messages[i - 1] if i else None
    m.applied, m.style_before = apply_style_edits(p, m.style, keys, asked.episode if asked else 0)
    m.outcome = "applied"
    return m.applied


def undo_style_chat(p: Project, i: int) -> tuple[list[str], list[str]]:
    """적용한 문체 변경안을 취소한다. 그 뒤에 다시 고친 칸은 건드리지 않는다. (되돌린 칸, 그대로 둔 칸) 을 돌려준다.
    변경안은 다시 고를 수 있게 연다."""
    m = _style_message(p, i)
    if m.outcome != "applied" or m.style_before is None:
        raise ValueError("적용한 변경안이 아니에요")
    done, kept = undo_style_edits(p, m.style, m.applied, m.style_before)
    m.outcome, m.applied, m.style_before = "", [], None
    return done, kept


def check_example(p: Project, episode: int = 0) -> str:
    """예시를 쓸 수 있는지 본다. 안 되면 ValueError (작업 style_example 이 시작 전에 부른다). 고쳐 쓸 화 본문을 돌려준다(없으면 빈 글)."""
    ref = ""
    if episode:
        ep = next((e for e in p.episodes if e.plot.number == episode), None)
        if ep is None or not ep.text.strip():
            raise ValueError(f"{episode}화에 본문이 없어요. 본문이 있는 화를 고르세요")
        ref = ep.text
    if library_blank(p.style):
        raise ValueError("문체가 비어 있어요. 원문을 분석하거나 문체 카드를 채운 뒤 예시를 써 볼 수 있어요")
    return ref


def style_example(llm: LLM, p: Project, scene: str = "", episode: int = 0) -> StyleExample:
    """지금 문체로 예시 글을 쓴다 (write 단계). 저장하지 않는다. episode 를 주면 그 화 한 대목을 고쳐 쓴다."""
    ref = check_example(p, episode)
    r = llm.json(prompts.writer_system(p), prompts.style_example_prompt(p, scene.strip(), episode), StyleSample,
                 hint={"scene": scene, "ref": ref[:prompts.STYLE_REF_LIMIT]})
    text = r.text.strip()
    if not text:
        raise ValueError("AI가 예시 글을 내지 않았어요. 다시 해 보세요")
    source = r.source.strip()
    return StyleExample(text=text, source=source if source and source in ref else "", episode=episode if ref else 0,
                        scene=scene.strip(), by="example", profile=p.style.model_copy(deep=True), at=_now())


def draft_paragraph(llm: LLM, card: SceneCard, n: int = 3) -> list[StudioCandidate]:
    """문단 연습장: 상황 카드로 서로 다른 문단 안 n 개를 쓴다 (write 단계). 저장하지 않는다 (studio.add_ai 가 남긴다).
    빈 안, 겹치는 안, 출발 글과 같은 안은 뺀다. 마크다운 굵은 글씨 · 줄 앞 기호는 떼어 낸다."""
    from . import studio

    studio.can_draft(card)
    lo, hi = studio.DRAFTS
    n = max(lo, min(hi, n))
    p = studio.world(card)
    rules = [studio.DRILLS[k].rule for k in card.drills if k in studio.DRILLS]
    r = llm.json(prompts.paragraph_system(p), prompts.paragraph_prompt(p, card, n, rules), StudioDraft,
                 hint={"n": n, "action": card.action, "source": card.source, "names": [x.name for x in card.people if x.name]})
    keep, seen = [], {card.source.strip()} if card.source.strip() else set()
    for c in r.candidates:
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", c.text).strip()
        text = re.sub(r"^\s*(?:#+|[-*]|\d+[.)])\s+", "", text, flags=re.M).strip()
        if text and text not in seen:
            seen.add(text)
            keep.append(StudioCandidate(text=text, note=c.note.strip()))
    if not keep:
        raise ValueError("AI가 쓸 만한 문단을 내지 않았어요. 다시 해 보세요")
    return keep[:n]


def anatomize_paragraph(llm: LLM, card: SceneCard) -> ParagraphAnatomy:
    """문단 연습장: 본보기 문단을 문장마다 박자로 뜯어본다 (plan 단계). 정리는 studio.clean_anatomy 가 한다."""
    if not card.model.strip():
        raise ValueError("본보기 문단이 없어요")
    return llm.json(prompts.SYSTEM_ANATOMY, prompts.anatomy_prompt(card.model), ParagraphAnatomy, hint={"model": card.model})


def vary_scene(llm: LLM, card: SceneCard, k: int = 4) -> list[SceneVariant]:
    """문단 연습장: 같은 구조로 쓸 다른 상황 k 개 (plan 단계). 저장하지 않는다."""
    from . import studio

    studio.can_vary(card)
    lo, hi = studio.VARIANTS
    k = max(lo, min(hi, k))
    r = llm.json(prompts.SYSTEM_PLANNER, prompts.variants_prompt(card, k), SceneVariants, hint={"k": k, "place": card.place, "action": card.action})
    return studio.clean_variants(r.variants, card)


def reader_check(llm: LLM, text: str) -> ReaderCheck:
    """문단 연습장: 독자가 채울 것과 그것이 이미 적혀 있는지 (check 단계)."""
    if not text.strip():
        raise ValueError("점검할 글이 없어요")
    return llm.json(prompts.SYSTEM_READER, prompts.reader_prompt(text), ReaderCheck, hint={"text": text})


def library_blank(st: StyleProfile) -> bool:
    from . import library

    return library.blank(st)


# ---------- 3. 기승전결 + 화별 플롯 ----------

def plan_arc(llm: LLM, p: Project, note: str = "") -> ArcPlan:
    """note: 작가가 바라는 것 (비우면 AI 가 정한다).
    Settings.heat_plan 을 켠 단편은 열 계획을 함께 받는다(HeatArcPlan). 저장하지 않는다: 적용은 apply_heat_plan."""
    total = p.meta.target_episodes
    heat = p.settings.heat_plan and not p.serial
    ask = prompts.arc_prompt(p) + (prompts.heat_arc_rules(total) if heat else "") + prompts.request_block(note)
    plan = llm.json(prompts.SYSTEM_PLANNER, ask, HeatArcPlan if heat else ArcPlan, hint={"total": total, "note": note})
    fit_arc(plan, total)
    if isinstance(plan, HeatArcPlan):
        clean_heat_plan(p, plan, total)
    return plan


def clean_heat_plan(p: Project, plan: HeatProposal, total: int) -> list[str]:
    """단편 작품 전체(1~total 화)의 열 계획 응답을 고친다 (clean_heat)."""
    return clean_heat(p, plan, 1, total)


def clean_heat(p: Project, plan: HeatProposal, start: int, end: int) -> list[str]:
    """열 계획 응답을 고친다: 화를 빈틈없이 맞추고(heatplan.fit), 뒤집힘을 범위 안에 두고,
    stakes 는 갈래가 단서가 아니고 내용이 있는 것만 남겨 심는 화를 start~end 로 자르고 지금 복선과 겹치지 않는 id 를 준다."""
    plan.heat, notes = heatplan.fit(plan.heat, start, end)
    plan.heat_turn, more = heatplan.fit_turn(plan.heat_turn, start, end)
    have = {f.id for f in p.foreshadows}
    stakes = []
    for f in plan.stakes:
        if f.kind == "clue" or not f.description.strip():
            continue
        n = min(max(f.planted_ep, start), end)
        k = 1
        while f"fs-{n:02d}-h{k}" in have:
            k += 1
        have.add(f"fs-{n:02d}-h{k}")
        due = f.due_ep if f.due_ep and n <= f.due_ep else None
        stakes.append(f.model_copy(update={"id": f"fs-{n:02d}-h{k}", "planted_ep": n, "status": "open", "payoff_ep": None,
                                           "due_ep": due, "scope": "arc", "description": f.description.strip()}))
    plan.stakes = stakes
    return notes + more


def apply_heat_plan(p: Project, plan: HeatProposal, arc: StoryArc | None = None) -> int:
    """열 계획 제안을 넣는다. 단편은 작품에, 장편은 arc 에. 계획 · 원칙 · 뒤집힘은 바꾸고,
    stakes 는 같은 id 가 없을 때만 복선에 더한다. 더한 수를 돌려준다."""
    target = arc if arc is not None else p
    target.heat, target.heat_rule, target.heat_turn = plan.heat, plan.heat_rule, plan.heat_turn
    have = {f.id for f in p.foreshadows}
    new = [f for f in plan.stakes if f.id not in have]
    p.foreshadows.extend(new)
    return len(new)


def heat_target(p: Project, number: int = 0) -> tuple[int, int, list, str, StoryArc | None]:
    """열 계획을 받을 범위: (첫 화, 끝 화, 기승전결, 이름, 아크). 단편은 작품 전체, 장편은 number 아크(0 이면 아직 다 쓰지 않은 첫 아크)."""
    if not p.serial:
        if not p.arc:
            raise ValueError("기승전결 구조를 먼저 만들어 주세요")
        return 1, p.meta.target_episodes, p.arc, "이 단편 전체의", None
    arcs = sorted(p.story_arcs, key=lambda a: a.start_ep)
    if not arcs:
        raise ValueError("아크를 먼저 기획해 주세요")
    written = {e.plot.number for e in p.episodes if e.text}
    a = next((x for x in arcs if x.number == number), None) if number else \
        next((x for x in arcs if any(n not in written for n in range(x.start_ep, x.end_ep + 1))), arcs[-1])
    if a is None:
        raise ValueError(f"아크 {number}이 없어요")
    return a.start_ep, a.end_ep, a.acts, f"아크 {a.number} '{a.title}'({a.start_ep}~{a.end_ep}화)의", a


def propose_heat(llm: LLM, p: Project, number: int = 0, note: str = "") -> HeatProposal:
    """이미 있는 기승전결 · 플롯 위에 열 계획만 받는다. 저장하지 않는다 (적용은 apply_heat_plan).
    본문이 있는 화는 지금 계획이 있으면 그 줄을 그대로 둔다 (AI 가 바꿔 보내도 되돌린다)."""
    start, end, acts, where, arc = heat_target(p, number)
    ask = prompts.heat_propose_prompt(p, start, end, acts, where) + prompts.request_block(note)
    prop = llm.json(prompts.SYSTEM_PLANNER, ask, HeatProposal, hint={"start": start, "end": end, "note": note})
    clean_heat(p, prop, start, end)
    old = {s.ep: s for s in heatplan.plan(p, start)}
    written = {e.plot.number for e in p.episodes if e.text}
    prop.heat = [old[s.ep] if s.ep in written and s.ep in old else s for s in prop.heat]
    return prop


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


def act_groups(acts: list[Act]) -> list[tuple[str, int, int]]:
    """플롯 초안을 한 번에 받는 구간: (구간 이름들, 첫 화, 끝 화). 한 화를 함께 쓰는 구간(짧은 작품)은 한 묶음이다.
    웹 작업 plots 와 프롬프트 놀이터의 '플롯 초안'이 같은 묶음을 쓴다."""
    groups: list[list] = []
    for a in sorted(acts, key=act_order):
        if groups and a.start_ep <= groups[-1][2]:
            groups[-1][0].append(a.name)
            groups[-1][2] = max(groups[-1][2], a.end_ep)
        else:
            groups.append([[a.name], a.start_ep, a.end_ep])
    return [("·".join(names), a, b) for names, a, b in groups]


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
    if not numbers:
        note = " ".join(str(getattr(llm, "last_note", "") or "").split())
        why = f" AI가 남긴 말: {note[:300]}" if note else " AI가 이유를 남기지 않았어요."
        raise ValueError(f"AI가 {start}~{end}화 플롯을 하나도 내지 않았어요.{why}")
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
        new = Episode(plot=plot)
        if cur:  # 작가 자료는 플롯을 다시 받아도 남긴다. 장면 연출은 사건 글로 사건을 다시 찾는다 (stage.find_event)
            new.stage, new.to_fix, new.events_done = cur.stage, cur.to_fix, cur.events_done
            new.direction = cur.direction  # 작가 연출 지시
        by_no[plot.number] = new
        storylines.clean_plot(p, new)
        applied.append(plot)
    p.episodes = [by_no[k] for k in sorted(by_no)]
    add_candidates(p, clean_new_characters(p, batch.new_characters, applied))
    elements.add_place_candidates(p, batch.new_places, plots_text(applied))


def plots_text(plots: list[EpisodePlot]) -> str:
    return "\n".join(elements.plot_text(Episode(plot=x)) for x in plots)


# ---------- 3'. 플롯 · 아크가 데려온 새 인물 ----------
# AI 플롯 초안, 플롯 대화, 다음 아크 기획(apply_arc)이 낸 새 인물은 바로 인물 설정에 넣지 않고 후보(Project.cast_candidates)로 둔다.
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
    """등록됐거나 이제 어느 화 플롯에도, 어느 아크의 주요 인물(StoryArc.cast)에도 나오지 않는 인물 후보와 쓰이지 않는 장소 후보는 지운다.
    아크 주요 인물을 함께 보는 까닭: 아크를 적용한 직후에는 그 아크의 화 플롯이 아직 없다."""
    known = {c.id for c in p.characters}
    used = {c for e in p.episodes for c in e.plot.characters} | {c for a in p.story_arcs for c in a.cast}
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
        arc_first = min((a.start_ep for a in p.story_arcs if c.id in a.cast), default=0)  # 아직 플롯에 없으면 그 인물을 둔 아크의 첫 화
        first = min((e.plot.number for e in p.episodes if c.id in e.plot.characters), default=arc_first)
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
    heat = p.settings.heat_plan
    ask = prompts.next_arc_prompt(p, start, length, note)
    if heat:  # 요청은 맨 뒤에 덧붙인다 (작가의 말은 next_arc_prompt 안에 있다)
        ask += prompts.heat_next_arc_rules(start, length)
    schema = HeatArcProposal if heat else ArcProposal
    hint = {"start": start, "length": length, "limit": limit, "number": len(p.story_arcs) + 1}
    prop = llm.json(prompts.SYSTEM_PLANNER, ask, schema, hint=hint)
    if not prop.arc.acts:  # acts 는 필수 칸이 아니라 모델이 빼먹을 수 있다. 요청을 맨 뒤에 덧붙여 한 번 더 묻는다
        prop = llm.json(prompts.SYSTEM_PLANNER, ask + prompts.ARC_ACTS_RETRY, schema, hint=hint)
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
    ids = known | {c.id for c in prop.new_characters} | {c.id for c in p.cast_candidates}
    a.cast = [c for c in a.cast if c in ids]
    a.cast += [c.id for c in prop.new_characters if c.id not in a.cast]  # 이 아크를 위해 만든 인물이다 (후보로 남는 근거)
    open_fs = {f.id for f in p.foreshadows if f.status == "open"}
    a.payoffs = [f for f in a.payoffs if f in open_fs]
    if isinstance(prop, HeatArcProposal):  # 열 계획은 아크 범위에 맞춰 arc.heat 로 옮긴다. 화면이 고쳐 보낸 arc.heat 가 있으면 그것을 쓴다
        if a.heat and not prop.heat:
            prop.heat, prop.heat_rule, prop.heat_turn = a.heat, a.heat_rule, a.heat_turn
        if prop.heat:
            clean_heat(p, prop, a.start_ep, a.end_ep)
            a.heat, a.heat_rule, a.heat_turn = prop.heat, prop.heat_rule, prop.heat_turn
    elif a.heat:
        a.heat, _ = heatplan.fit(a.heat, a.start_ep, a.end_ep)
        a.heat_turn, _ = heatplan.fit_turn(a.heat_turn, a.start_ep, a.end_ep)
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
    """제안된 다음 아크를 붙인다. 복선 회수 예정 화도 함께 바꾼다. 새 인물은 인물 설정에 넣지 않고 후보로 둔다
    (플롯이 데려온 인물과 같은 길: 그 인물이 나오는 화를 확정하거나 작가가 등록하면 조연 · 단역으로 들어온다)."""
    prop = clean_arc(p, prop.model_copy(deep=True))
    a = prop.arc
    p.story_arcs.append(a)
    try:
        validate_story_arcs(p)
    except ValueError:
        p.story_arcs.pop()
        raise
    add_candidates(p, [c.model_copy(update={"tier": "support" if c.tier == "main" else c.tier, "first_ep": 0})
                       for c in prop.new_characters])
    if isinstance(prop, HeatArcProposal):  # 정점을 받칠 새 판돈 · 관객 · 제약
        have = {f.id for f in p.foreshadows}
        p.foreshadows.extend(f for f in prop.stakes if f.id not in have)
    undo = ArcUndo(number=a.number)  # characters 는 예전 작품(아크가 인물을 바로 더하던 때)의 되돌리기에만 남는다
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
    sync_candidates(p)  # 이 아크만 쓰던 인물 후보를 지운다
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
        raise ValueError(f"{'아크' if kind == 'arc' else '부'} {number}{josa(str(number), '이', '가')} 없어요")
    return hit


def fold_knows(llm: LLM, p: Project, number: int) -> KnowsFoldSet:
    """아크 number 요약 뒤 인물마다 오래된 아는 정보를 몇 줄로 접는 제안 (knows.targets 인물만). 저장하지 않는다 (knows.apply_fold)."""
    want = knows.targets(p, number)
    if not want:
        raise ValueError(f"아크 {number}까지 접을 만큼 아는 정보가 쌓인 인물이 없어요 (인물마다 {context.KNOWS_KEEP}개가 넘어야 접어요)")
    fs = llm.json(prompts.SYSTEM_EDITOR, prompts.fold_prompt(p, number, want), KnowsFoldSet, hint={"arc": number, "ids": list(want)})
    return knows.clean_fold(p, number, fs)


def plan_offscreen(llm: LLM, p: Project) -> OffscreenSet:
    """다음 아크 기획 앞, context.RETURN_GAP 화 넘게 나오지 않은 인물(offscreen.targets)마다 화면 밖 근황 제안. 저장하지 않는다 (offscreen.apply)."""
    want, cut = offscreen.ready(p)
    s = llm.json(prompts.SYSTEM_PLANNER, prompts.offscreen_prompt(p, want, cut), OffscreenSet, hint={"ids": list(want)})
    return offscreen.clean(p, s, want)


def pending_recaps(p: Project) -> list[tuple[str, int]]:
    """모든 화가 끝났는데 요약이 없는 아크와 부. 요약이 있는 부의 아크는 부 요약이 대신 들어가므로(prompts.story_so_far) 빼 둔다."""
    summed = [x for x in p.parts if x.summary]
    out = [("arc", a.number) for a in p.story_arcs if not a.summary and arc_finished(p, a)
           and not any(x.start_ep <= a.start_ep <= x.end_ep for x in summed)]
    out += [("part", x.number) for x in p.parts if not x.summary and arc_finished(p, x)]
    return out


PLAN_AHEAD_MAX = 2  # 본문이 하나도 없는 아크가 이만큼 있으면 다음 아크 기획 앞에서 경고한다 (하나 더 짜면 3개)


def plan_ahead(p: Project) -> dict:
    """다음 아크를 짜기 전에 본문보다 얼마나 앞서 기획했는지. 경고만 하고 막지 않는다. LLM 호출 없음.
    written: 본문이 있거나 written · finalized 인 마지막 화, unwritten_arcs: written 뒤에서 시작하는 아크 수,
    recaps: pending_recaps, notes: 화면 · 명령줄에 보일 경고 글 (static/plot.js planAhead 와 같은 규칙)."""
    written = max((e.plot.number for e in p.episodes if e.text.strip() or e.status in ("written", "finalized")), default=0)
    until = p.planned_until()
    unwritten = sum(1 for a in p.story_arcs if a.start_ep > written)
    recaps = pending_recaps(p)
    notes = []
    if p.serial and unwritten >= PLAN_AHEAD_MAX:
        where = f"본문은 {written}화까지인데" if written else "본문이 아직 없는데"
        notes.append(f"{where} 아크가 {until}화까지 짜여 있어요 (본문 없는 아크 {unwritten}개). "
                     "앞 아크를 쓰고 요약한 뒤 기획하면 쓰인 줄거리를 보고 짤 수 있어요.")
    if p.serial and recaps:
        names = ", ".join(f"아크 {n}" if k == "arc" else f"{n}부" for k, n in recaps)
        notes.append(f"끝났는데 요약이 없어요: {names}. 먼저 요약하면 다음 아크 기획이 그 줄거리를 제대로 봐요. "
                     "요약이 없으면 화마다 첫 문장으로만 들어가요.")
    return {"written": written, "planned_until": until, "unwritten_arcs": unwritten,
            "recaps": [list(x) for x in recaps], "notes": notes}




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
    drop_audit_warnings(d)
    for e in [*d.events, *d.dismissed.events]:  # 빼 둔 항목(dismissed)도 번호를 맞춘다
        e.episode = n
    for f in [*d.foreshadow_planted, *d.dismissed.foreshadow_planted]:
        f.planted_ep = n
    d.warnings = [f"단편 {x.sources[0]}화 때 승인한 변경안을 다시 써요. 앞 화가 바뀌었으니 확인하고 반영하세요."] + d.warnings
    d.basis = text_basis(p.episode(n).text)
    d.warn_to = [""] + d.warn_to if d.warn_to else []  # 경고와 같은 차례를 지킨다
    return d


# ---------- 3-1. 대화로 구조와 플롯 다듬기 ----------

LOCKED = ("written", "finalized")  # 본문이 있어 플롯을 바꿀 수 없는 상태
LOCKED_FREE = ("storyline", "threads")  # 본문이 있는 화도 바꿀 수 있는 플롯 칸 (줄기 표시, static/lines.js)
CHAT_KEEP = 200  # 화면별로 남겨 두는 대화 수


def keep_locked_plots(before: Project, p: Project) -> list[int]:
    """화면이 보낸 작품 전체를 저장할 때(web.put_project) 본문이 있는 화(before 에서 LOCKED)의 플롯은 before 것으로 둔다.
    화면도 막지만, 옛 화면 · 다른 클라이언트가 보낸 값이 본문과 어긋난 플롯을 남기지 않게 서버에서도 막는다.
    줄기 표시(LOCKED_FREE)와 지운 인물을 등장 인물에서 빼는 것은 받는다. before 것으로 되돌린 화 번호를 돌려준다."""
    old = {e.plot.number: e.plot for e in before.episodes if e.status in LOCKED}
    gone = {c.id for c in before.characters} - {c.id for c in p.characters}
    back: list[int] = []
    for e in p.episodes:
        d = old.get(e.plot.number)
        if d is None:
            continue
        keep = d.model_copy(deep=True, update={k: getattr(e.plot, k) for k in LOCKED_FREE})
        keep.characters = [c for c in keep.characters if c not in gone]
        if keep != e.plot:
            e.plot = keep
            back.append(e.plot.number)
    return back


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
    rev = llm.json(prompts.SYSTEM_PLOT_CHAT, prompts.plot_chat_prompt(p, message, scope), PlotRevision,
                   hint=plot_chat_hint(p, message, scope))
    return clean_revision(p, rev, scope)


def plot_chat_hint(p: Project, message: str, scope: ChatScope) -> dict:
    """플롯 대화 · 대화 에이전트가 mock 에 넘기는 힌트. scope.target 은 chat_target 으로 맞춘 값이어야 한다."""
    _, focus = chat_target(p, scope.target)
    return {"message": message, "arc": (focus.acts if focus else scope.draft.arc.acts if scope.draft else [] if p.serial else p.arc),
            "episodes": [e.plot for e in p.episodes], "total": p.meta.target_episodes, "serial": p.serial,
            "target": scope.target, "focus": focus, "draft": scope.draft, "mode": scope.mode, "parts": p.parts,
            "start": next_arc_start(p) if p.serial else 0, "limit": chat_next_limit(p) if p.serial else 0}


def focus_arc(p: Project) -> StoryArc | None:
    """장편 플롯 대화가 따로 고르지 않았을 때 고치는 아크: 아직 본문이 없는 화가 있는 첫 아크, 없으면 마지막 아크."""
    status = {e.plot.number: e.status for e in p.episodes}
    arcs = sorted(p.story_arcs, key=lambda s: s.start_ep)
    for a in arcs:
        if any(status.get(n, "draft") not in LOCKED for n in range(a.start_ep, a.end_ep + 1)):
            return a
    return arcs[-1] if arcs else None


def _target_number(target: str) -> int:
    try:
        return int(target.split(":", 1)[1])
    except (IndexError, ValueError):
        raise ValueError(f"모르는 대화 대상이에요: {target}") from None


def chat_focus(p: Project, target: str = "") -> tuple[str, int, int, str]:
    """세션이 고른 다듬을 곳 'part:N'(부) · 'ep:N'(한 화 플롯), 화면이 주는 'text:N'(그 화 본문) · 'setup'(설정) · 'style'(문체).
    (종류 'part' · 'ep' · 'text' · 'setup' · 'style', 처음 화, 끝 화, 이름). 그 밖의 대상이면 ('', 0, 0, ''). 없는 부 · 화면 ValueError."""
    target = (target or "").strip()
    if target in ("setup", "style"):
        return target, 0, 0, {"setup": "설정", "style": "문체"}[target]
    if target.startswith("text:"):
        n = _target_number(target)
        e = next((x for x in p.episodes if x.plot.number == n), None)
        if e is None:
            raise ValueError(f"{n}화가 없어요. 화를 다시 고르세요")
        return "text", n, n, f"{n}화" + (f" 「{e.plot.title}」" if e.plot.title else "") + " 본문"
    if target.startswith("part:"):
        if not p.serial:
            raise ValueError("부는 장편에만 있어요")
        n = _target_number(target)
        part = next((x for x in p.parts if x.number == n), None)
        if part is None:
            raise ValueError(f"{n}부가 없어요. 부를 다시 고르세요")
        return "part", part.start_ep, part.end_ep, f"{n}부" + (f" 「{part.title}」" if part.title else "") + f" ({part.start_ep}~{part.end_ep}화)"
    if target.startswith("ep:"):
        n = _target_number(target)
        e = next((x for x in p.episodes if x.plot.number == n), None)
        if e is None:
            raise ValueError(f"{n}화 플롯이 없어요. 화를 다시 고르세요")
        return "ep", n, n, f"{n}화" + (f" 「{e.plot.title}」" if e.plot.title else "") + " 플롯"
    return "", 0, 0, ""


def chat_session_target(p: Project, target: str = "") -> str:
    """세션에 기억할 대상. 부 · 화 · 본문 · 설정 · 문체(chat_focus 가 읽는 대상)는 그대로, 나머지는 chat_target 의 실제 대상."""
    target = (target or "").strip()
    if chat_focus(p, target)[0]:
        return target
    return chat_target(p, target)[0]


def chat_target(p: Project, target: str = "") -> tuple[str, StoryArc | None]:
    """플롯 대화가 겨냥하는 곳과 그 아크. 돌려주는 이름은 기록에 남길 실제 대상이다:
    단편은 늘 '' (작품 전체), 장편은 'arc:N' 이나 'next' (다음 아크 기획). 비우면 focus_arc, 아크가 없으면 다음 아크.
    'ep:N' 은 그 화가 든 아크(기획 밖이면 다음 아크), 'part:N' 은 그 부의 아크(본문이 없는 첫 아크, 없으면 마지막 아크,
    아크가 아직 없으면 다음 아크)로 읽는다. 'text:N' 은 'ep:N' 처럼, 'setup' · 'style' 은 '' 처럼 읽는다.
    다듬을 범위는 chat_focus 가 따로 준다."""
    kind = chat_focus(p, target)[0]  # 없는 부 · 화는 여기서 막는다
    if not p.serial:
        return "", None
    target = (target or "").strip()
    if kind in ("setup", "style"):
        target = ""
    if kind in ("ep", "text"):
        n = _target_number(target)
        a = next((x for x in p.story_arcs if x.start_ep <= n <= x.end_ep), None)
        return (f"arc:{a.number}", a) if a else chat_target(p, "next")
    if kind == "part":
        _, lo, hi, _ = chat_focus(p, target)
        inside = sorted((x for x in p.story_arcs if lo <= x.start_ep <= hi), key=lambda x: x.start_ep)
        f = focus_arc(p)
        a = f if f in inside else next((x for x in inside if x.start_ep >= (f.start_ep if f else 0)), None) or (inside[-1] if inside else None)
        if a:
            return f"arc:{a.number}", a
        if lo <= next_arc_start(p) <= hi:
            return chat_target(p, "next")
        raise ValueError(f"{_target_number(target)}부에 아크가 없고, 다음 아크도 이 부에서 시작하지 않아요")
    if target.startswith("arc:"):
        try:
            number = int(target[4:])
        except ValueError:
            raise ValueError(f"모르는 대화 대상이에요: {target}") from None
        a = next((x for x in p.story_arcs if x.number == number), None)
        if a is None:
            raise ValueError(f"아크 {number}{josa(str(number), '이', '가')} 없어요. 아크를 다시 고르세요")
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
    kind, _, _, name = chat_focus(p, scope.focus)
    if kind in ("part", "text", "setup", "style"):
        out.append(name)
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
        was = by_no.get(n)
        by_no[n] = Episode(plot=plot.model_copy(deep=True), direction=was.direction if was else "")  # 확정된 화도 내용이 바뀌면 다시 확정한다. 작가 연출 지시는 남긴다
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
    done, before, after = plot_apply(p, m.revision, target, acts, episodes, arc=arc, parts=parts)
    m.applied, m.outcome = drafted + done, "applied"
    m.plot_before, m.plot_after = (before, after) if done else (None, None)
    return m.applied


def plot_apply(p: Project, rev: PlotRevision, target: str, acts: bool, episodes: list[int], *,
               arc: bool = False, parts: bool = False) -> tuple[list[str], PlotUndo, PlotUndo]:
    """apply_revision 으로 고른 부분을 반영하고, 적용 취소(plot_undo)에 쓸 적용 전 값과 적용 직후 값을 함께 돌려준다.
    플롯 대화 변경안(apply_plot_chat)과 대화 에이전트의 바로 쓰기(agent)가 함께 쓴다."""
    old = {e.plot.number: e.model_copy(deep=True) for e in p.episodes}
    before = _plot_undo_state(p, target)
    done = apply_revision(p, rev, acts, episodes, arc=arc, parts=parts, target=target)
    after = _plot_undo_state(p, target)
    now = {e.plot.number for e in p.episodes}
    touched = {int(x) for x in done if x.isdigit()}
    before.episodes = [old[n] for n in sorted(old) if n in touched or n not in now]  # 바꾼 화와 줄이며 뺀 화
    after.episodes = [e.model_copy(deep=True) for e in p.episodes if e.plot.number in touched]
    return done, before, after


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
    out = plot_undo(p, m.applied, before, after)
    m.outcome, m.applied, m.plot_before, m.plot_after = "", [], None, None
    return out


def plot_undo(p: Project, applied: list[str], before: PlotUndo, after: PlotUndo) -> tuple[list[str], list[str], list[str]]:
    """plot_apply 로 쓴 부분(applied) 가운데 지금 값이 쓴 직후 값과 같은 것만 쓰기 전으로 돌린다.
    (되돌린 부분, 그대로 둔 부분, 그대로 둔 까닭) 을 돌려준다. 일부만 넘기면 그 부분만 돌린다."""
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

    for x in [x for x in applied if x.isdigit()]:
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

    struct = [x for x in ("arc", "acts") if x in applied]
    if before.arc is not None and after.arc is not None and struct:
        a = next((x for x in p.story_arcs if x.number == before.arc.number), None)
        linked = after.arc.end_ep != before.arc.end_ep  # 끝 화가 바뀌면 칸과 구간을 함께 돌린다
        for group in [struct] if linked else [[x] for x in struct]:
            if a is None:
                for x in group:
                    keep(x, f"아크 {before.arc.number}{josa(str(before.arc.number), '이', '가')} 없어짐")
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
    elif "acts" in applied and before.arc is None:
        if p.arc != after.acts or p.meta.target_episodes != after.target_episodes:
            keep("acts", "적용 뒤 다시 고침")
        elif left := sorted(n for n in by_no if n > before.target_episodes):
            keep("acts", f"총 {before.target_episodes}화 밖에 남은 화가 있음 ({left[0]}~{left[-1]}화)")
        else:
            p.arc = [x.model_copy(deep=True) for x in before.acts]
            p.meta.target_episodes = before.target_episodes
            bring_back_cut()
            done.append("acts")

    if "parts" in applied:
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

def insert_range(p: Project, move_text: bool = False) -> tuple[int, int]:
    """새 화를 넣을 수 있는 자리 (그 화 앞에 넣는다). 처음 > 끝이면 넣을 수 없다. move_text 는 renumber.last_fixed 와 같다."""
    last = max((e.plot.number for e in p.episodes), default=0)
    return renumber.last_fixed(p, move_text) + 1, last + 1


def _fixed_why(move_text: bool) -> str:
    return "상태를 반영했거나 연재처에 올려" if move_text else "본문이 있거나 상태를 반영해"


def _text_note(p: Project, moved: list[int], f) -> list[str]:
    """본문이 있는 화를 옮겼으면 어디로 갔는지와 다시 볼 것을 알린다."""
    pairs = [(n, f(n)) for n in moved if renumber.has_text(p.episode(n))]
    if not pairs:
        return []
    return [f"본문이 있는 {' · '.join(f'{a}화' for a, _ in pairs)}는 {' · '.join(f'{b}화' for _, b in pairs)}가 됐어요. "
            "본문은 그대로라 본문 속 화 번호나 앞 화와 잇는 문장은 바뀌지 않아요. 검수로 다시 보세요."]


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


def insert_episode(p: Project, at: int, title: str = "", summary: str = "", storyline: str = "", move_text: bool = False) -> list[str]:
    """at 화 자리에 빈 플롯(제목 · 요약만)의 새 화를 넣고, 지금 at 화부터 뒤 화를 한 칸씩 민다.
    새 화는 바로 뒤 화가 든 구간 · 아크 · 부에 들어가고, 맨 끝에 붙이면 마지막 범위가 늘어난다. 반영한 내용 설명을 돌려준다.
    move_text 면 본문만 있고 반영하지 않은 화도 함께 민다 (renumber.last_fixed)."""
    lo, hi = insert_range(p, move_text)
    if not lo <= at <= hi:
        if at < lo:
            raise ValueError(f"{at}화 앞에는 넣을 수 없어요. {lo - 1}화까지는 {_fixed_why(move_text)} 번호를 옮기지 않아요. "
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

    texts = _text_note(p, moved, lambda x: x + 1)
    notes = _renumbered(p, change)
    head = f"{at}화에 새 화를 넣었어요."
    if moved:
        head += f" 원래 {moved[0]}~{moved[-1]}화는 {moved[0] + 1}~{moved[-1] + 1}화가 됐어요 (확정 상태 그대로)."
    return [head, *texts, *notes]


def remove_episode(p: Project, n: int, move_text: bool = False) -> list[str]:
    """아직 안 쓴 n 화를 빼고 뒤 화를 한 칸씩 당긴다. n 화를 가리키던 복선 · 요소 · 줄기 번호는 그 자리에 온 다음 화를 가리킨다.
    move_text 면 뒤에 본문만 있고 반영하지 않은 화가 있어도 당긴다. 본문이 있는 n 화 자신은 빼지 않는다 (delete_last)."""
    ep = p.episode(n)
    lo, _ = insert_range(p, move_text)
    if n < lo:
        raise ValueError(f"{n}화는 뺄 수 없어요. {lo - 1}화까지는 {_fixed_why(move_text)} 번호를 옮기지 않아요")
    if renumber.has_text(ep):
        raise ValueError(f"{n}화는 본문이 있어 뺄 수 없어요. 마지막으로 쓴 화라면 '이 화 지우기'로 지우세요")
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
            raise ValueError(f"{n}화를 빼면 {', '.join(empty)}{josa(empty[-1], '이', '가')} 비어요. 구간이나 아크 범위를 먼저 늘리세요")
        if n <= q.meta.target_episodes:
            q.meta.target_episodes -= 1
        sync_candidates(q)
        return counts

    texts = _text_note(p, moved, lambda x: x - 1)
    notes = _renumbered(p, change)
    title = ep.plot.title or '제목 없음'
    head = f"{n}화 '{title}'{josa(title, '을', '를')} 뺐어요."
    if moved:
        head += f" 원래 {moved[0]}~{moved[-1]}화는 {moved[0] - 1}~{moved[-1] - 1}화가 됐어요."
    return [head, *texts, *notes]


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
    ep.candidate, ep.versions, ep.made_by, ep.written_by, ep.meta_cut, ep.time = None, [], None, "", [], StoryTime()
    ep.rule_runs = []  # 지운 본문에 고침 규칙을 건 기록
    ep.events_done = []  # 본문이 없으니 쓴 사건 체크도 비운다
    ep.to_fix = []  # 지운 본문 문장에 단 고칠 곳
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

# 본문 쓰기 한 번의 출력 토큰 한도 (생각 토큰 포함) = 목표 글자 수 × WRITE_TOKENS_PER_CHAR + WRITE_THINK_TOKENS, WRITE_OUT_RANGE 안으로.
# 서버 기록(2026-11-08, write 단계 본문 쓰기 271번, 목표 5,000 · 7,000자): 가장 많이 Gemini 17,089토큰(생각 13,185, 목표 글자당 2.44),
# Claude 24,800토큰(목표 글자당 3.54). 목표 7,000자 한도는 44,384토큰이다. effort 가 꺼져도 Gemini 는 생각할 수 있어 생각 몫을 크게 둔다.
# 한도는 끊긴 응답을 알아채는 백엔드(llm.knows_cut)에만 건다. 끊긴 본문은 저장하지 않는다 (_write, WriteCut).
WRITE_TOKENS_PER_CHAR = 4
WRITE_THINK_TOKENS = 16384
WRITE_OUT_RANGE = (24576, 65536)


class WriteCut(ValueError):
    """본문이 WRITE_TRIES 번 모두 출력 길이 한도에 걸려 끊겼다 (가운데 다른 까닭으로 버린 응답도 있을 수 있다). 끊긴 본문은 돌려주지 않는다.
    자동 집필은 이 오류에서 그 화를 반영하지 않고 멈춘다 (autorun kind cut)."""


def write_out_tokens(p: Project, n: int | None = None) -> int:
    """n화 본문 쓰기의 출력 토큰 한도. 글자 수는 목표 분량(Meta.words_per_episode)과 그 화 지금 본문 중 긴 쪽이다:
    다시 생성 · 서술 다듬기는 지금 본문만큼 다시 내니, 작가가 목표보다 길게 쓴 화도 끊기지 않게 한다."""
    chars = p.meta.words_per_episode
    if n is not None:
        try:
            chars = max(chars, len(p.episode(n).text))
        except KeyError:
            pass
    lo, hi = WRITE_OUT_RANGE
    return max(lo, min(hi, chars * WRITE_TOKENS_PER_CHAR + WRITE_THINK_TOKENS))


def write_episode(llm: LLM, p: Project, n: int, approach: str = "", use_board: bool = True, use_cues: bool = True,
                  cut: list[MetaCut] | None = None, sent: list[SentPrompt] | None = None,
                  ruled: list[RuleRun] | None = None, on_chunk: Callable[[str], None] | None = None) -> str:
    """approach: 1~3화를 여러 안으로 쓸 때 여는 방식 (prompts.OPENING_APPROACHES).
    use_board: 그 화에 스토리보드가 있으면 쓰기 프롬프트에 넣는다. 끄면 스토리보드 없이 쓴다.
    use_cues: 그 화에 큐 시트가 있으면 쓰기 프롬프트 끝에 넣는다. 끄면 큐 시트 없이 쓴다.
    cut: 목록을 주면 본문 앞뒤에서 뗀 작업 설명 문단을 채운다 (_write). 저장하는 호출자가 replace_text(meta_cut=)로 넘긴다.
    sent: 목록을 주면 받은 호출의 요청 기록(sent.SentPrompt)을 채운다. 본문을 저장하는 호출자가 sent.keep 으로 남긴다.
    ruled: 목록을 주면 작품이 켠 고침 규칙을 받은 본문에 걸고 그 기록(RuleRun)을 더한다. 본문을 저장하는 호출자만 넘긴다
    (실험 · 비교 쓰기는 넘기지 않아 규칙이 걸리지 않는다). 저장하는 호출자가 replace_text(rule_runs=)로 넘긴다.
    on_chunk: 주면 흘려 받을 수 있는 백엔드에서 조각마다 지금까지 받은 글로 부른다 (_write, llm.family_text). 저장한 글이 아니다."""
    ep = p.episode(n)
    if ep.status == "draft":
        raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요 (confirm 먼저)")
    require_previous(p, n)
    text = _write(llm, p, n, prompts.episode_prompt(p, n, approach, use_board=use_board, use_cues=use_cues), cut, sent,
                  on_chunk=on_chunk)
    return apply_rules(p, text, "write", ruled)


def apply_rules(p: Project, text: str, kind: str, ruled: list[RuleRun] | None) -> str:
    """ruled 목록을 받았으면 작품이 켠 고침 규칙(regexrules.run)을 text 에 걸고 기록을 ruled 에 더한다. 안 받았으면 text 그대로.
    규칙은 본문을 저장하는 가장 바깥 입구에서 한 번만 건다 (_write 는 걸지 않는다)."""
    if ruled is None:
        return text
    text, run = regexrules.run(p, text, kind)
    if run is not None:
        ruled.append(run)
    return text


# ---------- 4-0. 화별 스토리보드 ----------
# 직전 화를 반영한 뒤 쓰기 바로 전에 plan 단계 모델이 장면 목록과 이번 화 확정 값을 만든다 (board.py, DESIGN.md).
# 작가가 고치거나 그대로 쓴다. 상태 변경안이 아니라 상태 승인을 거치지 않는다. 플롯 칸은 바꾸지 않는다.

def board_basis(p: Project, n: int) -> str:
    """스토리보드를 만든 입력의 지문. 지금 값과 다르면 낡은 스토리보드다 (board.basis)."""
    return board.basis(p, n)


def write_family(p: Project, n: int, prompt: str) -> dict:
    """쓰기 가족 경계 hint: 요청이 장편 쓰기 앞부분(prompts.write_head)으로 시작하면 그 길이. 아니면 빈 dict (단편 · 스토리보드 없이 쓰기)."""
    head = prompts.write_head(p, n)
    return {PREFIX_HINT: len(head)} if head and prompt.startswith(head) else {}


def make_storyboard(llm: LLM, p: Project, n: int, lead: list[str] | None = None) -> Storyboard:
    """n화 스토리보드를 만든다. 저장하지 않는다 (호출자가 set_storyboard 로 넣는다).
    lead 목록을 주면 보낸 요청 글을 채운다. 바로 이어 큐 시트를 만들 때 그 글을 앞에 둔다 (cue_lead, make_cue_sheet)."""
    ep = p.episode(n)
    if ep.status == "draft":
        raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요 (confirm 먼저)")
    require_previous(p, n)
    prompt = prompts.storyboard_prompt(p, n)
    if lead is not None:
        lead[:] = [prompt]
    d = _board_draft(llm, n, len(ep.plot.events), prompt,
                     {"episode": n, "events": len(ep.plot.events), "characters": ep.plot.characters,
                      "stats": {s.character_id: [x.name for x in s.stats] for s in p.states if s.stats},
                      **write_family(p, n, prompt)})
    b = Storyboard(**d.model_dump(), made_at=_now(), made_by="ai", basis=board_basis(p, n))
    b.checks = board.checks(p, n, b)
    return b


def revise_storyboard(llm: LLM, p: Project, n: int, ask: str) -> Storyboard:
    """n화 스토리보드를 작가 요청 ask 대로 AI 가 고친다. 저장하지 않는다 (호출자가 apply_storyboard_revision 으로 넣는다).
    작가가 바란 고침이라 made_by 는 both: 자동 집필이 낡았다고 새로 만들어 덮지 않는다."""
    ep = p.episode(n)
    if ep.storyboard is None:
        raise ValueError(f"{n}화 스토리보드가 없어요. 먼저 만드세요")
    if not ask.strip():
        raise ValueError("고칠 내용을 적어 주세요")
    if ep.status == "draft":
        raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요 (confirm 먼저)")
    require_previous(p, n)
    d = _board_draft(llm, n, len(ep.plot.events), prompts.storyboard_revise_prompt(p, n, ep.storyboard, ask),
                     {"episode": n, "events": len(ep.plot.events), "characters": ep.plot.characters,
                      "stats": {s.character_id: [x.name for x in s.stats] for s in p.states if s.stats},
                      "revise": ep.storyboard.model_dump(include=set(StoryboardDraft.model_fields)), "ask": ask})
    b = Storyboard(**d.model_dump(), made_at=_now(), made_by="both", basis=board_basis(p, n),
                   ask=ask.strip()[:prompts.BOARD_ASK_LIMIT])
    b.checks = board.checks(p, n, b)
    return b


def apply_storyboard_revision(p: Project, n: int, b: Storyboard) -> None:
    """AI 가 고친 스토리보드 b 를 넣고, 고치기 전 것을 적용 취소용으로 둔다. 연달아 고치면 처음 것을 남긴다."""
    ep = p.episode(n)
    old = ep.storyboard
    ep.storyboard_prev = ep.storyboard_prev or old
    b.skipped = bool(old and old.skipped and ep.text)
    ep.storyboard = b


def undo_storyboard(p: Project, n: int) -> None:
    """AI 가 고치기 전 스토리보드로 되돌린다."""
    ep = p.episode(n)
    if ep.storyboard_prev is None:
        raise ValueError(f"{n}화 스토리보드에 되돌릴 AI 고치기가 없어요")
    prev = ep.storyboard_prev
    prev.checks = board.checks(p, n, prev)
    ep.storyboard, ep.storyboard_prev = prev, None


# 스토리보드 한 번의 출력 토큰 한도 (생각 토큰 포함). 서버 기록(2026-11): Gemini 는 보통 1,800토큰(가장 많이 2,200),
# Claude 는 보통 6,700토큰(가장 많이 11,100). 같은 글을 되풀이한 응답은 65,536토큰을 780초 동안 내고 형식 불일치로 실패했다.
BOARD_OUT_TOKENS = 16384


def _board_draft(llm: LLM, n: int, events: int, prompt: str, hint: dict) -> StoryboardDraft:
    """스토리보드 응답을 받아 정리한다. 플롯에 사건이 있는데 장면이 하나도 없으면 한 번 더 묻고, 그래도 없으면 저장하지 않게 오류를 낸다.
    실측(2026-11-04, gemini-4-argon): 성인 장면이 많은 플롯에서 다른 칸은 채우고 scenes 만 비운 응답(finish STOP)을 연달아 냈다.
    출력은 BOARD_OUT_TOKENS 로 막는다."""
    with out_cap(BOARD_OUT_TOKENS):
        d = clean_storyboard(llm.json(prompts.SYSTEM_PLANNER, prompt, StoryboardDraft, hint=hint))
    if d.scenes or not events:
        return d
    with out_cap(BOARD_OUT_TOKENS):
        d = clean_storyboard(llm.json(prompts.SYSTEM_PLANNER, prompt + prompts.board_scenes_retry(events), StoryboardDraft,
                                      hint={**hint, "retry": True}))
    if d.scenes:
        return d
    raise RuntimeError(f"AI가 {n}화 스토리보드의 장면을 하나도 만들지 않았어요 (두 번 물었어요). "
                       "모델이 이 플롯의 장면을 나누지 않는 것일 수 있어요. 설정에서 계획 단계 모델을 바꾸거나, 스토리보드 없이 쓰거나 직접 장면을 적어 주세요")


def clean_storyboard(d: StoryboardDraft) -> StoryboardDraft:
    """빈 장면 · 빈 줄을 빼고, 장면 번호(상태창 · 이동 · 중심 장면)를 장면 수 안으로 맞춘다."""
    d.scenes = [x for x in d.scenes if any(v.strip() for v in (x.place, x.spot, x.goal, x.turn, x.end_state))]
    k = len(d.scenes)
    for x in d.stats:
        x.scene = x.scene if 0 <= x.scene <= k else 0
        x.changes = [c for c in x.changes if c.name.strip()]
    d.stats = [x for x in d.stats if x.character_id.strip() and x.changes]
    for m in d.moves:
        m.scene = m.scene if 0 <= m.scene <= k else 0
    d.moves = [m for m in d.moves if m.character_id.strip() and m.to.strip()]
    d.focus = d.focus if 0 <= d.focus <= k else 0
    d.attire = [a for a in d.attire if a.character_id.strip() and a.end.strip()]
    d.handover = [h for h in d.handover if h.text.strip()]
    d.protect = [x.strip() for x in d.protect if x.strip()]
    d.stat_basis = [x.strip() for x in d.stat_basis if x.strip()]
    d.warnings = [w for w in d.warnings if w.text.strip()]
    d.time.days = max(d.time.days, 1)
    return d


def set_storyboard(p: Project, n: int, b: Storyboard | None, by: str = "author") -> None:
    """스토리보드를 넣거나 지운다(b=None). 작가가 저장하면(by='author') 지금 입력을 보고 고친 것으로 보아 지문을 지금 값으로 둔다.
    AI 가 만든 것을 작가가 고치면 made_by 는 both. 본문을 쓴 뒤에도 고칠 수 있다 (다시 생성이 그대로 쓴다)."""
    ep = p.episode(n)
    ep.storyboard_prev = None  # 작가 저장 · 새로 만들기 · 지우기 뒤에는 AI 고치기 적용 취소가 없다
    if b is None:
        ep.storyboard = None
        return
    old = ep.storyboard
    draft = clean_storyboard(StoryboardDraft(**b.model_dump(include=set(StoryboardDraft.model_fields))))
    if by == "ai":
        made_by, basis = "ai", b.basis or board_basis(p, n)
    else:
        made_by, basis = ("both" if old and old.made_by != "author" else "author"), board_basis(p, n)
    b = Storyboard(**draft.model_dump(), made_at=b.made_at or (old.made_at if old else "") or _now(), made_by=made_by, basis=basis)
    b.checks = board.checks(p, n, b)
    b.skipped = bool(old and old.skipped and ep.text)  # 고쳐도 본문이 이 스토리보드 없이 쓴 것이면 그대로
    ep.storyboard = b


def _write(llm: LLM, p: Project, n: int, prompt: str, cut: list[MetaCut] | None = None,
           sent: list[SentPrompt] | None = None, kind: str = "write", target: int | None = None,
           verdict: Callable[[str], str] | None = None, on_chunk: Callable[[str], None] | None = None) -> str:
    """본문을 쓴다. 한글이 적은 응답(영어 생각 과정 등)과 본문 대신 작업 설명 · 거절 문구만 온 응답(metatail.whole)은 다시 부른다.
    본문 앞뒤에 붙은 확실한 작업 설명(metatail.split: 'n화 본문입니다' 머리말, 끝의 '짚어 둘 것' 같은 작가에게 하는 말)은 떼고 서버 기록에 남긴다.
    덜 확실한 것은 떼지 않고 검수 화면의 문체 경고(style_drift)로 알린다.
    cut 목록을 주면 뗀 문단을 앞 · 뒤 자리와 함께 채운다. 본문만 돌려주는 모양은 실험 · 비교 호출자가 그대로 쓰게 둔다.
    sent 목록을 주면 받은 호출의 요청 · 시도 번호 · 다시 부른 까닭(sent.SentPrompt, kind 는 write · rewrite · polish)을 채운다.
    여기서는 파일에 쓰지 않는다: 큐마다 쓰기 · 다듬기 재시도처럼 채택하지 않을 판도 이 함수를 부른다 (sent.py).
    target 은 이 호출이 받은 목표 분량 글자 수다 (비면 화 분량 Meta.words_per_episode). 사용량 기록 줄에 싣는다 (usage.SCOPED).
    다시 부르려고 버린 응답은 그 호출의 사용량 기록 줄에 까닭(discarded: cut · thought · meta)을 단다 (usage.hold).
    verdict(본문) 은 받은 본문을 부른 쪽이 버릴 까닭(빈 글이면 씀)이다. 까닭이 있으면 그 줄에 달고 본문은 그대로 돌려준다 (서술 다듬기).
    on_chunk 는 흘려 받는 글을 받는다 (llm.family_text). 다시 부르는 호출은 빈 글부터 다시 보낸다. 앞뒤 작업 설명은 떼지 않은 글이다."""
    system = prompts.writer_system(p)
    head = prompts.write_head(p, n)  # 장편 쓰기 가족: 스토리보드 · 큐 시트와 같은 앞부분이면 그 캐시를 읽는다
    cap = (write_out_tokens(p, n) if getattr(llm, "knows_cut", False) and getattr(llm, "caps_write", True)
           else None)  # 로컬 모델은 끊김만 보고 한도는 걸지 않는다 (LocalLLM.caps_write)
    bad = {"cut": 0, "thought": 0, "meta": 0}
    size = p.meta.words_per_episode if target is None else target
    retries: list[SentRetry] = []
    for call in range(1, WRITE_TRIES + 1):
        with usage.scope(target=size), usage.hold() as rows:
            why, note = "", ""
            try:
                with out_cap(cap) if cap else nullcontext():
                    if on_chunk is not None and call > 1:
                        on_chunk("")  # 버린 응답의 글을 미리보기에 남기지 않는다
                    text = family_text(llm, system, prompt, head, on_chunk)
            except OutputCut:
                text = None
            except RuntimeError:
                # 생각만 하다 한도에 걸려 글 없이 끝난 응답은 백엔드가 '응답이 비었어요' 로 낸다. 끝난 이유가 끊김이면 끊김으로 센다
                if not was_cut(llm):
                    raise
                text = None
            if text is None or was_cut(llm):  # 출력 길이 한도에 걸려 끊긴 본문은 받지 않는다
                why, note = "cut", (f"{cap}토큰" if cap else "")
                logging.getLogger("canon").warning("%s화 본문이 출력 길이 한도(%s토큰)에 걸려 끊겨 다시 써요", n, cap or "기본")
            elif metrics.hangul_ratio(text) < HANGUL_MIN:
                why = "thought"
            elif metatail.whole(text):
                why = "meta"
            if why:
                bad[why] += 1
                retries.append(SentRetry(call=call, reason=why, note=note))
                usage.discard(rows, why)
                continue
            body, lead, tail = metatail.parts(text)
            if verdict is not None:
                usage.discard(rows, verdict(body))  # 줄을 파일에 쓰기 전에 단다
        if lead or tail:
            logging.getLogger("canon").warning("%s화 본문 앞뒤의 작업 설명 %d문단을 뗐어요: %s", n, len(lead) + len(tail),
                                               " / ".join(x[:80] for x in lead + tail))
        if cut is not None:
            cut[:] = [MetaCut(text=x, at="head") for x in lead] + [MetaCut(text=x, at="tail") for x in tail]
        if sent is not None:
            rec = sent_record(llm, system, prompt, head, call, retries)
            sent[:] = [rec.model_copy(update={"kind": kind})]
        return body
    limit = f"({cap:,}토큰)" if cap else ""
    if bad["cut"] == WRITE_TRIES:  # 세 번 모두 끊겼을 때만 끊김으로 멈춘다 (자동 집필 kind cut)
        raise WriteCut(f"{n}화 본문이 출력 길이 한도{limit}에 걸려 끊겼어요 ({WRITE_TRIES}번 중 {bad['cut']}번). "
                       "끊긴 본문은 저장하지 않았어요. "
                       "모델이 같은 글을 되풀이했을 수 있어요. 다시 시도하거나 설정에서 쓰기 모델을 바꿔 주세요")
    what = " · ".join(f"{label} {k}번" for key, label in (("thought", "다른 글(영어로 된 생각 과정 등)"), ("meta", "작업 설명이나 거절 문구"),
                                                         ("cut", f"출력 길이 한도{limit}에 걸려 끊긴 응답"))
                      if (k := bad[key]))
    raise ValueError(f"{n}화 본문 대신 {what}이 나왔어요. 다시 시도해 주세요")



# ---------- 4-1. 큐 시트 집필 실험 (cue.py) ----------
# 화를 악보처럼 큐로 나눠 진행과 핵심 대사를 먼저 정하고, 본문을 한 번에 또는 큐마다 쓴다. 작품에 저장하지 않는다.

# 큐 시트 한 번의 출력 토큰 한도. 보통 응답은 1,500~2,000토큰이다 (2026-11-03 8~9화). 넘으면 같은 글을 되풀이하는 중이다.
CUE_OUT_TOKENS = 16384


def cue_lead(p: Project, n: int, lead: list[str], made_at: str) -> str:
    """큐 시트 요청 앞에 둘 스토리보드 요청 글. 지금 n화 스토리보드가 방금 그 글로 AI 가 만든 것(made_at 이 같고 made_by 가 ai)이고
    낡지 않았을 때만 그 글을, 아니면 빈 글을 돌려준다. 작가가 고쳤거나 낡은 스토리보드는 예전 큐 시트 요청을 쓴다."""
    b = p.episode(n).storyboard
    if not lead or not made_at or b is None or b.made_by != "ai" or b.made_at != made_at or board.stale(p, n):
        return ""
    return lead[0]


def make_cue_sheet(llm: LLM, p: Project, n: int, lead: str = "") -> CueSheet:
    """n화 큐 시트를 만든다 (plan 단계). 저장은 호출자가 한다.
    lead 는 cue_lead 가 고른 스토리보드 요청 글이다. 주면 그 글로 시작하는 요청을 보낸다 (prompts.cue_sheet_prompt)."""
    from . import cue

    ep = p.episode(n)
    if ep.status == "draft":
        raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요 (confirm 먼저)")
    require_previous(p, n)
    with out_cap(CUE_OUT_TOKENS):
        prompt = prompts.cue_sheet_prompt(p, n, lead=lead)
        d = llm.json(prompts.SYSTEM_PLANNER, prompt, CueSheetDraft,
                     hint={"episode": n, "events": len(ep.plot.events), "characters": ep.plot.characters,
                           "scenes": len(ep.storyboard.scenes) if ep.storyboard else 0, "size": p.meta.words_per_episode,
                           **write_family(p, n, prompt)})
    return CueSheet(**cue.clean(p, d).model_dump(), made_at=_now(), made_by="ai")


def make_coord(llm: LLM, p: Project, n: int) -> CoordMemo:
    """n화 조율 메모를 만든다 (쓰기 재료 조율, coord.py). 저장은 호출자가 한다 (Episode.coord).
    사건 수가 플롯과 다르게 오면 쓰지 않는다 (ValueError): 원래 플롯으로 쓰면 된다."""
    from . import coord

    ep = p.episode(n)
    if ep.status == "draft":
        raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요 (confirm 먼저)")
    d = llm.json(prompts.SYSTEM_PLANNER, prompts.coord_prompt(p, n), CoordDraft, hint={"episode": n, "events": len(ep.plot.events)})
    if len(d.events) != len(ep.plot.events):
        raise ValueError(f"{n}화 조율 메모의 사건 수({len(d.events)})가 플롯({len(ep.plot.events)})과 달라요")
    return CoordMemo(**d.model_dump(), basis=coord.basis(ep.plot), made_at=_now())


def write_scored(llm: LLM, p: Project, n: int, sheet: CueSheet) -> tuple[str, int]:
    """큐 시트를 함께 주고 한 번에 쓴다. (본문, 요청 글자 수)."""
    require_previous(p, n)
    prompt = prompts.cue_score_prompt(p, n, sheet)
    return _write(llm, p, n, prompt), len(prompts.writer_system(p)) + len(prompt)


def play_cues(llm: LLM, p: Project, n: int, sheet: CueSheet, progress=None) -> tuple[list[str], int]:
    """큐마다 차례로 쓴다. (큐별 본문, 요청 글자 수 합). progress(k, total) 는 큐를 쓰기 전에 부른다."""
    require_previous(p, n)
    if not sheet.cues:
        raise ValueError("큐 시트에 큐가 없어요")
    done: list[str] = []
    sent = 0
    system = prompts.writer_system(p)
    for k in range(1, len(sheet.cues) + 1):
        cancel.check()
        if progress:
            progress(k, len(sheet.cues))
        prompt = prompts.cue_play_prompt(p, n, sheet, done)
        sent += len(system) + len(prompt)
        done.append(_write(llm, p, n, prompt, target=sheet.cues[k - 1].length).strip())  # 목표 분량은 그 큐의 분량
    return done, sent


# ---------- 4-2. 역설계 실험 (revlab.py) ----------
# 작가가 넣은 소설을 거꾸로 플롯 · 스토리보드 · 큐 시트 · 이야기 줄기로 푼다. 작품에 저장하지 않는다 (revlab.apply_episode 가 실험 파일에 넣는다).

def reverse_episode(llm: LLM, lab, number: int) -> RevEpisodeDraft:
    """원문 한 화를 역설계한다 (plan 단계). 정리 · 경계 재기는 revlab.apply_episode 가 한다."""
    from . import revlab

    e = revlab.episode(lab, number)
    if not e.text.strip():
        raise ValueError(f"{number}화 원문이 비었어요")
    prompt = prompts.rev_prompt(lab, number)
    hint = {"episode": number, "names": [c.name for c in lab.cast]}
    d = llm.json(prompts.SYSTEM_REVERSE, prompt, RevEpisodeDraft, hint=hint)
    if not rev_empty(d):
        return d
    cancel.check()  # 빈 응답은 한 번만 다시 묻는다. 요청은 맨 뒤에 덧붙여 앞부분 캐시를 지킨다
    d = llm.json(prompts.SYSTEM_REVERSE, prompt + "\n\n" + prompts.REV_EMPTY_RETRY, RevEpisodeDraft, hint=hint)
    if rev_empty(d):
        raise ValueError(f"{number}화 역설계 응답이 비었어요 (사건 · 장면 · 큐가 없어요). 두 번 물어도 같아서 저장하지 않았어요. 다시 시도해 주세요")
    return d


def rev_empty(d: RevEpisodeDraft) -> bool:
    """역설계 응답에 사건 · 장면 · 큐 가운데 하나라도 없다 (저장하지 않고 다시 묻는다)."""
    return not d.events or not d.scenes or not [c for c in d.cues if c.start.strip() or c.beat.strip()]


def reverse_lines(llm: LLM, lab) -> RevLineSet:
    """역설계한 화들의 이야기 줄기 (plan 단계). 화가 둘 넘을 때만 부른다."""
    return llm.json(prompts.SYSTEM_REVERSE, prompts.rev_lines_prompt(lab), RevLineSet,
                    hint={"episodes": [e.number for e in lab.episodes if e.plot]})

def reverse_arcs(llm: LLM, lab) -> RevArcSet:
    """역설계한 화들을 아크 · 부로 나눈다 (plan 단계). 정리는 revlab.clean_arcs 가 한다."""
    eps = [e.number for e in lab.episodes if e.plot]
    return llm.json(prompts.SYSTEM_REVERSE, prompts.rev_arcs_prompt(lab), RevArcSet,
                    hint={"episodes": eps, "cast": [c.name for c in lab.cast]})


def compare_drafts(llms: dict[str, LLM], p: Project, n: int) -> dict[str, str]:
    """같은 화를 여러 백엔드로 쓴다. 프롬프트는 write_episode 와 같다. 저장은 호출자가 한다."""
    return {name: write_episode(llm, p, n) for name, llm in llms.items()}


def adopt_draft(p: Project, n: int, text: str, model: str = "") -> None:
    """비교에서 고른 본문을 그 화의 본문으로 쓴다. 상태 반영이 끝난 화는 되돌린 뒤에만 바꾼다. model: 그 안을 쓴 모델 (usage.model_id)."""
    ep = p.episode(n)
    if ep.status == "finalized":
        raise ValueError(f"{n}화는 상태 반영이 끝났어요. 바꾸려면 상태 승인 화면에서 {n}화부터 반영을 취소한 뒤 다시 하세요 (명령줄은 revert {n - 1})")
    runs: list[RuleRun] = []
    text = apply_rules(p, text, "adopt", runs)  # 비교본은 규칙 없이 쓴 글이라 고른 본문에 여기서 한 번 건다
    replace_text(ep, text, written_by=model, rule_runs=runs)


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
    if req.mode == "polish":  # 서술 다듬기는 규칙이 정해져 있어 피드백 · 빠른 요청 · 재료 · 살릴 부분을 받지 않는다
        return RewriteRequest(mode="polish")
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
    if req.mode == "polish":
        return prompts.polish_prompt(p, n, p.episode(n).text)
    return prompts.rewrite_prompt(p, n, req, rewrite_materials(p, n), p.episode(n).text)


def rewrite_episode(llm: LLM, p: Project, n: int, req: RewriteRequest, cut: list[MetaCut] | None = None,
                    sent: list[SentPrompt] | None = None, ruled: list[RuleRun] | None = None) -> str:
    """피드백을 반영해 그 화를 다시 쓴다. 저장하지 않는다 (set_candidate 로 새 판에 둔다). cut · sent · ruled 는 write_episode 와 같다.
    다듬기 모드는 ruled 를 polish_episode 에 그대로 넘기고 여기서는 걸지 않는다 (두 번 걸지 않는다).
    sent 기록은 새 판을 둘 때 sent.hold 로, 작가가 고르면 sent.adopt 로 남긴다."""
    ep = _editable(p, n)
    require_previous(p, n)
    if req.mode == "revise" and not ep.text.strip():
        raise ValueError("고쳐 쓸 지난 판이 없어요")
    if req.mode == "polish":
        return polish_episode(llm, p, n, cut, sent, ruled)
    return apply_rules(p, _write(llm, p, n, rewrite_prompt(p, n, clean_rewrite(req)), cut, sent, "rewrite"), "rewrite", ruled)


POLISH_TRIES = 2
POLISH_SPAN = (0.85, 1.15)  # 다듬은 글 / 지금 본문 글자 수. 밖이면 내용을 더하거나 뺀 것으로 본다
# 다듬은 판의 말줄임으로 끊는 서술 · 서술 물음(metrics.narration_tics)이 종류마다 이보다 많고 지금 본문보다 늘면 다시 부른다.
# 프롬프트는 '화에 셋까지'라고 쓰지만 그대로 검사하면 좋은 판도 버린다: 2026-11-04 작가 블라인드(Gemini 원고를 Claude 가 다듬음)에서
# 이긴 두 판은 4 · 4, 2 · 4개, 진 판은 9 · 5개였다. Gemini 원래 판은 0~1개.
POLISH_TIC_RETRY = 6
_FIXED_OPEN = ("\"", "“", "「", "『", "‘", "'", "─", "—")


def fixed_lines(text: str) -> list[str]:
    """서술 다듬기가 바꾸면 안 되는 줄: 따옴표로 여는 대사 줄, 줄표로 여는 효과음 줄, 줄표 없이 소리나 몸짓만 적은 효과음 줄
    ('콰앙-!', '터벅, 터벅.', metrics.is_sfx_line) (앞뒤 공백 뺌, 차례대로)."""
    return [x.strip() for x in text.split("\n") if x.strip().startswith(_FIXED_OPEN) or metrics.is_sfx_line(x)]


def polish_problem(old: str, new: str) -> str:
    """다듬은 글을 쓰지 않을 까닭. 대사 · 효과음 줄이 하나라도 바뀌거나 빠지거나 늘었거나, 글자 수가 POLISH_SPAN 밖이면. 괜찮으면 빈 글."""
    a, b = fixed_lines(old), fixed_lines(new)
    if a != b:
        gone = len([x for x in a if x not in b])
        return f"대사 · 효과음 줄이 바뀌었어요 ({len(a)}줄 중 {gone}줄 다름, 다듬은 글 {len(b)}줄)"
    ratio = len(new.strip()) / max(len(old.strip()), 1)
    if not POLISH_SPAN[0] <= ratio <= POLISH_SPAN[1]:
        return f"글자 수가 {len(old.strip()):,}자에서 {len(new.strip()):,}자로 너무 바뀌었어요"
    return ""


def polish_tics(old: str, new: str) -> str:
    """다듬은 글이 말줄임 끝 서술이나 서술 물음을 너무 늘렸으면 그 까닭, 아니면 빈 글.
    종류마다 POLISH_TIC_RETRY 개를 넘고 지금 본문보다 늘었을 때만 짚는다 (원래 많던 글은 탓하지 않는다)."""
    a, b = metrics.narration_tics(old), metrics.narration_tics(new)
    names = {"trail": "말줄임으로 끊는 서술", "question": "서술 속 물음"}
    over = [f"{names[k]}이 {a[k]}개에서 {b[k]}개로 늘었어요" for k in names if b[k] > max(POLISH_TIC_RETRY, a[k])]
    return ", ".join(over)


def polish_episode(llm: LLM, p: Project, n: int, cut: list[MetaCut] | None = None,
                   sent: list[SentPrompt] | None = None, ruled: list[RuleRun] | None = None) -> str:
    """지금 본문의 서술 문장만 다듬는다 (prompts.polish_prompt). 저장하지 않는다 (set_candidate 로 새 판에 둔다).
    대사 · 효과음 줄이 바뀐 글은 POLISH_TRIES 번까지 다시 부르고, 그래도 바뀌면 멈춘다. 다듬기 모델은 revise 단계를 부른 쪽이 고른다.
    말줄임 · 물음을 너무 늘린 글(polish_tics, 서술 말투가 있는 화는 보지 않음)도 다시 부른다. 끝내 줄지 않으면 멈추지 않고
    그중 덜 늘린 판을 낸다: 작가가 새 판을 견줘 고르니, 글은 나아졌을 수 있다.
    sent 는 낸 판의 요청 기록을 채운다. 시도 번호는 다듬기 재시도까지 이어 센다 (버린 판의 까닭은 polish · tics).
    ruled 를 주면 검사를 통과한 판과 덜 늘린 판 모두에 고침 규칙을 건다. 검사는 규칙을 걸기 전 글로 한다."""
    ep = _editable(p, n)
    old = ep.text.strip()
    if not old:
        raise ValueError(f"{n}화에 다듬을 본문이 없어요")
    prompt = prompts.polish_prompt(p, n, old)
    look = not prompts.voiced(p, n)  # 서술 말투가 있는 화는 문장 끝 몫 · 상한을 넣지 않으니 세지도 않는다
    why, best = "", None
    log = logging.getLogger("canon")
    calls, retries = 0, list[SentRetry]()  # 다듬기 재시도까지 이은 호출 수 · 버린 호출

    def rebase(rec: SentPrompt) -> SentPrompt:  # 이번 시도 안의 번호를 앞 시도 뒤로 민다
        return rec.model_copy(update={"attempt": calls + rec.attempt,
                                      "retries": [r.model_copy(update={"call": calls + r.call}) for r in rec.retries]})

    def done(rec: SentPrompt, part: list[MetaCut], dropped: list[SentRetry]) -> None:
        if cut is not None:
            cut[:] = part
        if sent is not None:  # 버린 호출은 낸 판 앞뒤 모두 까닭에 남긴다
            sent[:] = [rec.model_copy(update={"kind": "polish", "retries": sorted(dropped, key=lambda r: r.call)})]

    for _ in range(POLISH_TRIES):
        part: list[MetaCut] = []
        got: list[SentPrompt] = []
        # 대사 · 효과음 줄이나 분량을 바꾼 판은 버리고, 그 호출의 사용량 기록 줄에 polish 를 단다
        new = _write(llm, p, n, prompt, part, got, target=len(old),
                     verdict=lambda t: "polish" if polish_problem(old, t) else "")
        rec = rebase(got[0])  # _write 는 본문을 돌려줄 때 늘 채운다
        calls = rec.attempt
        why = polish_problem(old, new)
        if why:
            log.warning("%s화 서술 다듬기를 다시 불러요: %s", n, why)
            retries.extend([*rec.retries, SentRetry(call=calls, reason="polish", note=why)])
            continue
        tic = polish_tics(old, new) if look else ""
        if not tic:
            done(rec, part, [*retries, *rec.retries])
            return apply_rules(p, new, "polish", ruled)
        log.warning("%s화 서술 다듬기를 다시 불러요: %s", n, tic)
        retries.extend([*rec.retries, SentRetry(call=calls, reason="tics", note=tic)])
        t = metrics.narration_tics(new)
        if best is None or sum(t.values()) < best[0]:
            best = (sum(t.values()), new, part, rec)
    if best is not None:
        log.warning("%s화 서술 다듬기: 말줄임 · 물음이 줄지 않아 덜 늘린 판을 냈어요", n)
        picked = best[3]
        done(picked, best[2], [r for r in retries if r.call != picked.attempt])
        return apply_rules(p, best[1], "polish", ruled)
    raise ValueError(f"{n}화 서술 다듬기를 쓰지 않았어요. {why}. 다시 시도해 주세요")


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


def writer_of(llm: LLM) -> str:
    """본문을 쓴 모델 이름 (Episode.written_by · TextVersion.model). 쓰기 호출자가 저장할 때 함께 적는다."""
    return usage.model_id(llm)


def set_candidate(p: Project, n: int, text: str, req: RewriteRequest, model: str = "",
                  meta_cut: list[MetaCut] | None = None, rule_runs: list[RuleRun] | None = None) -> TextVersion:
    """새 판을 고르기 대기에 둔다. 고르지 않은 앞 새 판은 versions 로 보낸다. model: 새 판을 쓴 모델 (writer_of).
    meta_cut: 새 판을 쓸 때 뗀 작업 설명 문단. 판에 남고 판을 고르면 화로 따라간다.
    rule_runs: 새 판에 고침 규칙을 건 기록 (rewrite_episode(ruled=)). meta_cut 과 같이 판을 따라간다."""
    ep = p.episode(n)
    if ep.candidate:
        ep.candidate.kind = "rejected"
        _keep_version(ep, ep.candidate)
    ep.candidate = TextVersion(id=_version_id(ep), at=_now(), text=text, request=clean_rewrite(req), model=model,
                               meta_cut=list(meta_cut or []), rule_runs=_new_runs(ep, rule_runs))
    return ep.candidate


def _new_runs(ep: Episode, runs: list[RuleRun] | None) -> list[RuleRun]:
    """새 본문 · 새 판에 붙일 고침 규칙 기록. id 가 빈 기록에 그 화에서 겹치지 않는 r<N> 을 붙이고 최근 regexrules.RULE_RUN_KEEP 개만 남긴다."""
    runs = list(runs or [])
    if not runs:
        return []
    have = [*ep.rule_runs, *(r for v in ep.versions for r in v.rule_runs), *(ep.candidate.rule_runs if ep.candidate else [])]
    return regexrules.add_runs(have, runs)[-len(runs):]


def replace_text(ep: Episode, text: str, made_by: RewriteRequest | None = None, written_by: str = "",
                 meta_cut: list[MetaCut] | None = None, rule_runs: list[RuleRun] | None = None) -> None:
    """지금 본문을 versions 에 남기고 text 로 바꾼다. 검수 결과는 지난 판 것이라 결정한 지적만 남긴다 (findings.new_version).
    상태 반영이 끝난 화는 반영을 그대로 두고 before_change 로 반영 뒤 고침만 표시한다.
    written_by: 새 본문을 쓴 모델 (writer_of) 이나 'import'. 모르면 비운다. 남기는 지난 판에는 지난 본문의 모델이 따라간다.
    meta_cut: 새 본문을 쓸 때 뗀 작업 설명 문단. 지난 판에는 지난 본문의 뗀 문단이 따라간다.
    rule_runs: 새 본문에 고침 규칙을 건 기록. meta_cut 과 같이 지난 판에는 지난 본문의 기록이 따라간다."""
    done = ep.status == "finalized"
    if text == ep.text:
        ep.status = "finalized" if done else "written"
        return
    if ep.text.strip():
        _keep_version(ep, TextVersion(id=_version_id(ep), at=_now(), text=ep.text, kind="previous", request=ep.made_by,
                                      model=ep.written_by, meta_cut=ep.meta_cut, rule_runs=ep.rule_runs))
    before_change(ep)
    ep.text, ep.made_by, ep.written_by, ep.status = text, made_by, written_by, "finalized" if done else "written"
    ep.meta_cut = list(meta_cut or [])
    ep.rule_runs = _new_runs(ep, rule_runs)
    ep.style_basis = ""  # 이 판을 쓸 때의 문체를 모른다. AI 가 방금 쓴 본문이면 부른 쪽이 anchor.stamp 로 남긴다
    findings.new_version(ep)


def adopt_candidate(p: Project, n: int) -> None:
    """새 판을 본문으로 쓴다. 지금 본문은 versions 에 남는다."""
    ep = _editable(p, n)
    if ep.candidate is None:
        raise ValueError(f"{n}화에 고를 새 판이 없어요")
    c, ep.candidate = ep.candidate, None
    replace_text(ep, c.text, c.request, c.model, c.meta_cut, c.rule_runs)


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
    replace_text(ep, v.text, v.request, v.model, v.meta_cut, v.rule_runs)  # 그 판의 기록만 되살린다. 규칙은 다시 걸지 않는다
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


def restore_cut(p: Project, n: int, k: int) -> TextEdit:
    """쓰기가 뗀 작업 설명 문단 k 를 뗀 자리(본문 앞 · 뒤)에 되살린다. 수정 기록에 남겨 되돌릴 수 있다. 문단은 뗀 목록에서 빠진다."""
    ep = _editable(p, n)
    if not 0 <= k < len(ep.meta_cut):
        raise KeyError(f"{n}화에 그 뗀 문단이 없어요")
    c = ep.meta_cut.pop(k)
    before_change(ep)
    body = ep.text.strip()
    if c.at == "head":
        add, start, ep.text = c.text + "\n\n", 0, c.text + "\n\n" + body
    else:
        add, start, ep.text = "\n\n" + c.text, len(body), body + "\n\n" + c.text
    return _record(ep, TextEdit(id="", source="manual", start=start, before="", after=add, instruction="뗀 작업 설명 되살리기"))


def drop_cut(p: Project, n: int, k: int) -> None:
    """쓰기가 뗀 작업 설명 문단 k 를 지운다. 본문은 바꾸지 않는다."""
    ep = p.episode(n)
    if not 0 <= k < len(ep.meta_cut):
        raise KeyError(f"{n}화에 그 뗀 문단이 없어요")
    ep.meta_cut.pop(k)


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


def revise_passage(llm: LLM, p: Project, n: int, sel: Selection, message: str = "", preset: str = "",
                   rules: bool = False) -> PassageRevision:
    """고른 부분의 고친 후보를 만든다. 저장하지 않는다. 원문과 같거나 겹치는 후보는 뺀다.
    rules: 참이면 후보마다 작품이 켠 고침 규칙을 걸고 바뀐 곳을 PassageCandidate.ruled 에 채운다 (자리는 후보 글 안).
    대화 기록에 남은 그 값을 apply_passage 가 본문 기록으로 옮긴다. 본문을 저장하는 호출자만 켠다."""
    if preset and preset not in prompts.PASSAGE_PRESETS:
        raise ValueError(f"모르는 빠른 요청이에요: {preset}")
    if not message.strip() and not preset:
        raise ValueError("무엇을 바꿀지 적거나 빠른 요청을 고르세요")
    ep = _editable(p, n)
    sel = Selection(start=locate(ep.text, sel.text, sel.start), text=sel.text)
    head = prompts.passage_head(p, n)  # 같은 화에서 바뀌지 않는 앞부분. 그 끝을 캐시 경계로 넘겨 이어 고칠 때 캐시를 읽는다
    rev = llm.json(prompts.reviser_system(p), prompts.passage_prompt(p, n, sel, message, preset, head=head), PassageRevision,
                   hint={"selection": sel.text, "preset": preset, "message": message, PREFIX_HINT: len(head)})
    keep, seen = [], {sel.text.strip()}
    for c in rev.candidates:
        if len(keep) == 3:
            break
        c.text = c.text.replace("【고칠 부분】", "").replace("【여기까지】", "").strip()  # 규칙 전에 다듬어 자리가 후보 글 안에서 어긋나지 않게
        if rules and c.text:  # 규칙을 먼저 걸고 원문 · 앞 후보와 견준다. 규칙을 건 후보가 원문과 같으면 뺀다
            new, run = regexrules.run(p, c.text, "passage")
            if run is not None and run.changes:
                c.text, c.ruled = new, run.changes
        key = c.text.strip()
        if key and key not in seen:
            seen.add(key)
            keep.append(c)
    rev.candidates = keep
    fix = not preset and message.strip().startswith(prompts.PASSAGE_FIX_HEADS)
    if not keep and not (fix and rev.reply.strip()):  # 고치기 요청은 '본문이 맞다'는 답일 수 있다 (prompts.TEXT_RIGHT_RULE)
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
    raw = text if text is not None else cands[k].text
    after = raw.strip()
    if not after:
        raise ValueError("넣을 글이 비었어요")
    edit = edit_text(p, n, m.selection, after, "ai", instruction=user.text if user else "", preset=m.preset,
                     proposed=cands[k].text, rejected=[c.text for j, c in enumerate(cands) if j != k])
    m.outcome, m.applied = "applied", [str(k)]
    cand = cands[k].text
    same = cand.strip() == after
    spots = still_ruled(cands[k].ruled, after, same, -(len(cand) - len(cand.lstrip())))  # 자리는 후보 글 안이라 후보 글의 앞 공백만큼 옮긴다
    if spots:
        add_run(p.episode(n), RuleRun(kind="passage", changes=[c.model_copy(update={"start": edit.start + c.start}) for c in spots]))
    return edit


def still_ruled(changes: list[RuleChange], text: str, same: bool, shift: int = 0) -> list[RuleChange]:
    """고침 규칙이 바꾼 곳 가운데 text 에 아직 있는 것 (start 는 text 안 자리로 고친 사본).
    same 이면 규칙을 건 글 그대로라 자리만 shift 만큼 옮긴다. 작가가 고쳤으면 바뀐 글을 locate 로 찾고, 못 찾은 곳과
    지우기 규칙이 바꾼 곳(after 가 빈 글, 찾을 수 없음)은 뺀다."""
    out = []
    for c in changes:
        at = c.start + shift
        if same:
            if 0 <= at <= len(text):
                out.append(c.model_copy(update={"start": at}))
            continue
        if not c.after:
            continue
        try:
            out.append(c.model_copy(update={"start": locate(text, c.after, max(at, 0))}))
        except ValueError:
            continue
    return out


def add_run(ep: Episode, run: RuleRun) -> RuleRun:
    """지금 본문의 고침 규칙 기록에 run 을 더한다 (id 를 붙이고 최근 regexrules.RULE_RUN_KEEP 개만 남김)."""
    ep.rule_runs = [*ep.rule_runs, *_new_runs(ep, [run])][-regexrules.RULE_RUN_KEEP:]
    return run


def apply_first(p: Project, n: int, sel: Selection, message: str, rev: PassageRevision) -> TextEdit | None:
    """요청과 AI 후보를 부분 수정 대화에 남기고 첫 후보를 바로 본문에 넣는다 (상태 정리 경고의 'AI에게 고치기').
    남기기와 넣기를 같은 작품에서 해 메시지 번호가 어긋나지 않는다. 후보가 없으면 남기기만 하고 None."""
    reply = record_passage(p, n, sel, message, "", rev)
    if reply.passage is None:
        return None
    return apply_passage(p, n, len(p.chat(f"text:{n}").messages) - 1, 0)


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
    draft.quote, quote_note = illust.match_quote(prompts.illust_scope(ep.text, sel), draft.quote)
    late = illust.states_at(p, n)[1]
    return illust.assemble(p, Illustration(id="", model=model or p.illust.model, selection=sel, request=request.strip(), draft=draft,
                                           draft_notes=[x for x in (quote_note, late) if x]))


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
    """지도 만들기 설정 제안 (MapSuggestion). 저장하지 않는다. 좌표는 마을 · 도시 · 현대 동네 생성기가 정한다.
    돌려주는 것: 지도 종류 kind(village | city | modern), 설정 칸(size, roads, water, fields, forest), places [{key, name, kind, put, note}], reason.
    spec.kind 는 지도 화면에서 지금 고른 종류로 프롬프트에 알린다 (뚜렷한 근거가 없으면 따르게).
    도시에 호수를 고르면 강으로, 현대 동네에 호수 · 바다를 고르면 하천으로 바꾼다 (생성기에 그 칸이 없다).
    장소 종류는 지도 종류의 시대(placekinds.era_of)를 따른다. AI 가 지도 종류를 함께 고르므로 프롬프트에는 시대마다 종류 목록(kinds_for)을 적고,
    받은 id 는 AI 가 고른 지도 종류의 목록(kind_ids(s.kind))으로 거른다.
    장소 이름은 키로 바꾸고, 모르는 장소 · 그 지도 종류에 없는 종류 id 는 뺀다 (지금 값을 그대로 둔다)."""
    from . import atlas
    from .maps import kinds as placekinds

    pls = atlas.places(p)
    if not pls:
        raise ValueError("장소가 아직 없어요. 장소를 더한 뒤 제안을 받으세요")
    rows = atlas.gen_places(p, spec)
    options = {k: m[1].OPTIONS for k, m in atlas.MAKERS.items()}
    kinds = {k: [(x.id, x.label) for x in placekinds.kinds_for(k)] for k in options}
    s = llm.json(prompts.SYSTEM_MAP_PLANNER,
                 prompts.map_suggest_prompt(p, rows, pls, kinds, options, spec.kind if spec else ""), MapSuggestion,
                 hint={"places": [r["name"] for r in rows], "kind": spec.kind if spec else ""})
    names = {pl["key"]: pl["name"] for pl in pls}
    out, seen, ids = [], set(), set(placekinds.kind_ids(s.kind))
    for g in s.places:
        key = atlas.place_by_name(g.name, pls)
        kind = g.kind.strip()
        if not key or key in seen or kind not in ids:
            continue
        seen.add(key)
        out.append({"key": key, "name": names[key], "kind": kind, "put": bool(g.put), "note": g.note.strip()})
    water = "river" if (s.kind == "city" and s.water == "lake") or (s.kind == "modern" and s.water in ("lake", "sea")) else s.water
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

def check_episode(llm: LLM, p: Project, n: int, widen: bool | None = None, motion: bool | None = None,
                  scope: bool | None = None) -> ConsistencyReport:
    """한 화 검수. 장편이고 widen 이면(비우면 작품 설정 check_widen) 검수 넓히기(widen_check)를 이어 붙인다. 단편은 넓히지 않는다.
    motion 이면(비우면 작품 설정 check_motion) 동선 따로 보기(motion_check)를 본 검수와 동시에 불러 지적을 합친다.
    scope 면(비우면 작품 설정 check_scope) 다시 검수는 바뀐 문단(check_scope)만 새로 짚으라고 묻고 report._scope 에 남긴다."""
    if not p.episode(n).text:
        raise ValueError(f"{n}화 본문이 없어요")
    started, basis = _now(), text_basis(p.episode(n).text)  # 모델이 본 본문과 그때 시각 (apply_check 가 회차에 남긴다)
    parts = check_scope(p.episode(n)) if (p.settings.check_scope if scope is None else scope) else []
    part = getattr(llm, "part", None)  # 자동 집필 배치: 호출마다 작업 slot 을 따로 둔다 (llm.BatchLLM.part)
    with ThreadPoolExecutor(max_workers=1) as pool:
        side = (pool.submit(contextvars.copy_context().run, motion_check, part("motion") if part else llm, p, n)
                if (p.settings.check_motion if motion is None else motion) else None)
        material = prompts.check_material(p, n)  # 검수 가족(고침안 · 다시 검수 · 상태)과 같은 앞부분. 본문 바로 앞을 캐시 경계로 알린다 (check_cache_cut)
        report = llm.json(prompts.SYSTEM_CHECKER, prompts.check_prompt(p, n, material=material, scope=parts), ConsistencyReport,
                          hint={"episode": n, PREFIX_HINT: prompts.check_cache_cut(material, n)})
        report.episode = n
        if widen_on(p, widen):
            report, _ = widen_check(llm, p, n, report)
        if side is not None:
            report = merge_motion(report, _side_result(side))
    if p.settings.stage_extract:  # 계획 장면이 있는 사건만 본문 장면 뽑기: apply_check 가 장면에 넣고 규칙 판정을 합친다
        report._stage, report._stage_held = stage_extract_all(llm, p, n)
    report._scope, report._at, report._basis = parts, started, basis
    return report


def _second_before(at: str) -> str:
    """_now 모양 시각의 1초 앞."""
    from datetime import datetime, timedelta

    return (datetime.fromisoformat(at) - timedelta(seconds=1)).isoformat(timespec="seconds")


SCOPE_AROUND = 1  # 다시 검수가 새로 짚을 곳: 고친 문단 앞뒤로 함께 보는 문단 수
SCOPE_MAX = 0.5  # 바뀐 문단이 본문의 이 비율을 넘으면 본문 전체를 새로 짚는다


def check_scope(ep: Episode) -> list[str]:
    """다시 검수가 새로 짚을 바뀐 문단: 마지막 검수 뒤 되돌리지 않은 수정(findings.edits_since_check)이 놓인 문단과 앞뒤 SCOPE_AROUND 문단.
    빈 목록이면 본문 전체를 짚는다: 첫 검수, 새 판, 수정 기록 없이 본문이 바뀜, 바뀐 문단이 본문의 SCOPE_MAX 를 넘음."""
    if not ep.rounds or not ep.checked_at or not ep.text or ep.rounds[-1].superseded:
        return []
    if ep.rounds[-1].basis and ep.rounds[-1].basis == text_basis(ep.text):
        return []  # 지난 검수와 같은 본문: 다시 묻는 것이라 전체를 본다
    edits = findings.edits_since_check(ep)
    if not edits:
        return []
    parts = prompts.fix_around(ep.text, _fix_spots(ep, edits), SCOPE_AROUND)
    if not parts or sum(len(x) for x in parts) > len(ep.text) * SCOPE_MAX:
        return []
    return parts


def motion_check(llm: LLM, p: Project, n: int, hint: dict | None = None) -> list[ConsistencyIssue]:
    """동선 따로 보기: 이번 화 인물 이름과 본문만 넣고 같은 화 안의 동선 어긋남만 찾는다 (prompts.motion_prompt).
    갈래 · 근거 화는 모델이 다르게 적어도 동선 · 이번 화로 고친다. 인용 문장이 빈 지적은 버린다."""
    cancel.check()
    rep = llm.json(prompts.SYSTEM_MOTION, prompts.motion_prompt(p, n), ConsistencyReport, hint={"episode": n, "motion": True, **(hint or {})})
    out = []
    for x in rep.issues:
        if x.current_quote.strip():
            x.type, x.source_episode = "동선", n
            out.append(x)
    return out


def _side_result(fut) -> list[ConsistencyIssue]:
    """동선 따로 보기 결과. 실패해도 본 검수는 살린다. 멈추기 · 배치 멈춤은 그대로 올린다."""
    try:
        return fut.result()
    except (cancel.Cancelled, Interrupted):
        raise
    except Exception:
        return []


def merge_motion(report: ConsistencyReport, extra: list[ConsistencyIssue]) -> ConsistencyReport:
    """동선 따로 보기 지적을 본 검수 뒤에 붙인다. 이미 짚은 문장(findings.same_quote)과 겹치는 지적은 뺀다."""
    issues = list(report.issues)
    for x in extra:
        if not any(_same_quote(x.current_quote, y.current_quote) for y in issues):
            issues.append(x)
    return ConsistencyReport(episode=report.episode, issues=issues)


def widen_on(p: Project, widen: bool | None = None) -> bool:
    """이 검수에 넓혀 찾기를 붙이는지: 장편이고 widen(비우면 작품 설정 check_widen)이 켜졌을 때."""
    return p.serial and (p.settings.check_widen if widen is None else widen)


_same_quote = findings.same_quote


def widen_check(llm: LLM, p: Project, n: int, report: ConsistencyReport, hint: dict | None = None) -> tuple[ConsistencyReport, dict]:
    """장편 검수 넓히기: 첫 검수(budget)는 이번 화 전체로 한 번 찾은 옛 단락만 본다. 이번 화의 사실 진술을 뽑아(claims_prompt)
    진술마다 옛 화를 따로 찾고(claim_evidence, LLM 없음), 첫 검수에 넣지 않은 단락이 근거로 나온 진술만 그 근거와 함께
    검수 모델에 다시 묻는다(widen_prompt). 판단기는 쓰지 않는다. 더한 지적은 첫 검수와 같은 문장을 짚으면 뺀다.
    (첫 검수 지적 + 더한 지적, 단계별 크기 · 진술 기록)"""
    from .context import est_tokens, passage_index

    ep = p.episode(n)
    hint = hint or {}
    part = getattr(llm, "part", None)  # 자동 집필 배치: 호출마다 작업 slot 을 따로 둔다 (llm.BatchLLM.part)
    first = prompts.claims_prompt(p, n)
    claims = (part("claims") if part else llm).json(prompts.SYSTEM_CLAIMS, first, ClaimSet, hint={"episode": n, "text": ep.text}).claims
    claims = [c for c in claims if c.quote.strip() and c.claim.strip()][:prompts.TWOSTEP_CLAIMS]
    recent, found = prompts.check_recall(p, n)
    seen = {para for _, paras in found for para in paras}
    index = passage_index(p, n, {e.plot.number for e in recent})  # 직전 화는 첫 검수가 원문으로 봤다. 첫 검수 색인을 다시 쓴다
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


def check_hits(p: Project, n: int) -> tuple[str, list[ConsistencyIssue]]:
    """apply_check 에 넘길 정규식 경고 지적을 미리 건다: (건 본문, 지적). 규칙 걸기는 몇 초 걸릴 수 있어
    작품을 잠그고 apply_check 를 부르는 쪽(web._edit)이 잠그기 전에 부른다."""
    text = p.episode(n).text
    return text, regexrules.hits(p, text, n)


def apply_check(p: Project, r: ConsistencyReport, source: CheckSource = "api", widen: bool = False,
                hits: tuple[str, list[ConsistencyIssue]] | None = None) -> CheckRound:
    """검수 결과는 참고용 경고라 승인 없이 화에 붙여 둔다. 지적 목록에 회차 하나로 합친다 (findings.merge:
    작가가 그대로 둠 · 잘못 짚음으로 정한 지적은 다시 나와도 그대로). 회차 시각과 지문은 check_episode 가 시작할 때 남긴 값이다.
    hits: check_hits 가 미리 건 정규식 경고 지적. 그 본문이 지금 본문과 같을 때만 쓰고, 다르면 다시 건다."""
    ep = p.episode(r.episode)
    if not ep.text:
        raise ValueError(f"{r.episode}화 본문이 없어요")
    for prop in r._stage:  # 검수 때 뽑은 본문 장면 (stage_extract_all)
        apply_stage(p, prop)
    # 장면 연출 규칙 판정: 설정이 꺼져 있어도 이미 있는 본문 장면은 판정한다. 검수 모델이 같은 문장을 짚었으면 뺀다
    rule = [x for x in stage.episode_issues(p, ep) if not any(_same_quote(x.current_quote, y.current_quote) for y in r.issues)]
    judged = any(stage.scenes_of(ep, i)[1] is not None for i in range(len(ep.plot.events)))
    issues, outside = findings.scoped(ep, r.issues, r._scope)  # 다시 검수: 바뀌지 않은 문단의 새 지적은 넣지 않는다
    # 정규식 경고 규칙: 다시 검수 범위로 거르지 않는다. 거른 뒤의 AI 지적이 같은 문장을 짚었을 때만 뺀다
    found = hits[1] if hits is not None and hits[0] == ep.text else regexrules.hits(p, ep.text, r.episode)
    regex = [x for x in found if not any(_same_quote(x.current_quote, y.current_quote) for y in issues)]
    # 회차 시각 · 지문은 검수를 시작할 때 것이다. 그래야 검수하는 동안 고친 곳이 '검수 뒤 고침'으로 남는다 (check_done · check_scope)
    at = r._at or _now()
    if r._basis and r._basis != text_basis(ep.text):  # 검수하는 동안 본문이 바뀌었다. 시각은 초까지라 시작과 같은 초에 고친 것도 세게 1초 앞당긴다
        at = _second_before(at)
    rnd = findings.merge(ep, [*issues, *rule, *regex], at, r._basis or text_basis(ep.text), source, widen, judged)
    rnd.scoped, rnd.outside = bool(r._scope), len(outside)
    return rnd


# ---------- 5-2. 장면 연출: 플롯에서 초안, 본문에서 뽑기, 검수 때 함께 뽑기 (stage.py, docs/stage/) ----------
# AI 는 이름 · 기준점 + 관계 말로 적고(StageDraft) stage.from_draft 가 id 로 바꿔 정리한다. 결과(StageProposal)는 저장하지 않는다.
# 화면 버튼의 결과는 웹이 pending.json 에 두고 작가가 비교한 뒤 통째로 적용한다(apply_stage). 적용 취소는 한 번(undo_stage).
# 검수 때 뽑은 본문 장면은 비교 없이 바로 넣되, 작가가 손본 본문 장면(source manual)은 덮지 않는다.

def _stage_context(p: Project, ep: Episode, event: int, role: str) -> tuple[StageRoom | None, list[str]]:
    """쓸 방(같은 사건의 짝 장면 방, 없으면 None)과 같은 화 앞 사건 장면이 끝난 상태."""
    plan, text = stage.scenes_of(ep, event)
    mine, pair = (text, plan) if role == "text" else (plan, text)
    room = stage.room_of(p, mine) if mine else None
    room = room or (stage.room_of(p, pair) if pair else None)
    prev: list[str] = []
    for i in range(event - 1, -1, -1):
        a, b = stage.scenes_of(ep, i)
        s = (b or a) if role == "text" else (a or b)
        if s is not None:
            prev = stage.end_lines(s, stage.room_of(p, s), p)
            break
    return room, prev


def _pick_room(p: Project, want: str) -> StageRoom:
    """AI 가 고른 방: 이미 있는 방 이름이면 그 방, 틀 id · 틀 이름이면 새 방 (작품에는 아직 넣지 않는다)."""
    want = want.strip()
    hit = next((r for r in p.rooms if r.name.strip() == want), None)
    if hit:
        return hit
    tid = want if want in stage.ROOMS else next((k for k, v in stage.ROOMS.items() if v[0] == want), "empty")
    return stage.make_room(tid, stage._new_id("r", {r.id for r in p.rooms}))


def _fresh_room(p: Project, ep: Episode, event: int, template: str) -> StageRoom:
    """새 장면 카드의 '빈 방에서 초안': 틀로 만든 새 방 (작품에는 아직 넣지 않는다). 이름은 그 사건을 맡은 스토리보드 자리 · 장소."""
    hit = stage.board_scene_of(ep, event)
    name = (hit[1].spot.strip() or hit[1].place.strip()) if hit else ""
    return stage.make_room(template, stage._new_id("r", {r.id for r in p.rooms}), name)


def _stage_ask(llm: LLM, p: Project, n: int, event: int, role: str, hint: dict | None = None, fresh: str = "") -> StageProposal:
    ep = p.episode(n)
    if not 0 <= event < len(ep.plot.events):
        raise ValueError(f"{n}화에 {event + 1}번째 사건이 없어요")
    if role == "text" and not ep.text:
        raise ValueError(f"{n}화 본문이 없어요")
    room, prev = _stage_context(p, ep, event, role)
    if fresh and room is None:
        room = _fresh_room(p, ep, event, fresh)
    make = prompts.stage_extract_prompt if role == "text" else prompts.stage_draft_prompt
    d = llm.json(prompts.SYSTEM_STAGE, make(p, n, event, room, prev), StageDraft,
                 hint={"episode": n, "event": event, "role": role, "text": ep.text if role == "text" else "",
                       "room": room.model_dump() if room else None, **(hint or {})})
    new_room = None
    if room is None:
        room = _pick_room(p, d.room)
    if not any(r.id == room.id for r in p.rooms):
        new_room = room
    # 방에 없는 장소는 기준점으로 더해 두고 그 방으로 장면을 정리한다 (계획 초안만. 본문 뽑기는 방을 바꾸지 않는다)
    grown, adds, dx, dy = stage.place_anchors(room, d.new_anchors if role == "plan" else [])
    notes_room = []
    have = {a.name.strip() for a in grown.anchors}
    over = list(dict.fromkeys(x.name.strip() for x in (d.new_anchors if role == "plan" else []) if x.name.strip() and x.name.strip() not in have))
    if over:
        notes_room.append(f"기준점 {len(over)}개({', '.join(over)})는 한 번에 더하는 수({stage.MAX_ADDS}개)를 넘어 뺐어요. 방 고치기에서 더해 주세요")
    if adds:
        if (grown.w, grown.h) != (room.w, room.h):
            notes_room.append(f"방을 {room.w:g}×{room.h:g}m 에서 {grown.w:g}×{grown.h:g}m 로 넓혀요")
        room = grown
    scene, dropped, notes = stage.from_draft(d, p, ep, event, room, role)
    notes += stage.fill_arrivals(scene, room, p)
    if role == "text":
        scene.basis = text_basis(ep.text)
    keep = {} if new_room is not None or not adds else {"grown": grown, "shift_x": dx, "shift_y": dy}
    return StageProposal(episode=n, event=event, role=role, scene=scene, room=room if new_room is not None else None, adds=adds,
                         dropped=dropped, notes=[*notes_room, *notes], at=_now(), **keep)


def draft_stage(llm: LLM, p: Project, n: int, event: int, fresh: str = "") -> StageProposal:
    """플롯 사건 하나의 계획 장면 초안 (plan 단계). 본문은 넣지 않는다.
    fresh 는 아직 방이 없을 때 AI 에게 고르게 하지 않고 그 틀(보통 empty)로 새 방을 만들어 준다. 방에 없는 장소는 AI 가 기준점으로 제안한다."""
    return _stage_ask(llm, p, n, event, "plan", fresh=fresh)


def extract_stage(llm: LLM, p: Project, n: int, event: int, hint: dict | None = None) -> StageProposal:
    """화 본문에서 사건 하나의 본문 장면을 뽑는다 (check 단계). 본문 전체를 넣고 그 사건 부분만 뽑게 한다.
    박자가 빈 응답이면 한 번만 다시 묻는다 (같은 LLM 이라 사용량에 잡힌다. 자동 집필 배치는 slot 을 따로 둔다)."""
    prop = _stage_ask(llm, p, n, event, "text", hint)
    if not prop.scene.beats:
        part = getattr(llm, "part", None)
        prop = _stage_ask(part("again") if part else llm, p, n, event, "text", hint)
    return prop


STAGE_EXTRACT_WORKERS = 3  # 검수 때 함께 뽑기의 동시 호출 수. 429 는 llm 의 RATE_WAITS 재시도가 맡는다


def stage_extract_all(llm: LLM, p: Project, n: int, hint: dict | None = None) -> tuple[list[StageProposal], list[StageProposal]]:
    """검수 때 함께 뽑기: 계획 장면이 있는 사건만 본문 장면을 뽑는다 (2026-11-01 사용자: 나머지는 장면 연출 화면 버튼).
    본문이 바뀌지 않은 사건(basis 같음)은 건너뛴다(호출 없음). 사건마다 따로 부르고 STAGE_EXTRACT_WORKERS 개씩 동시에 부른다.
    (바로 넣을 것, 작가가 손본 본문 장면이라 비교로만 남길 것). 한 사건이 실패해도 검수는 잇는다. 멈추기는 바로 올린다."""
    ep = p.episode(n)
    if not ep.text:
        return [], []
    basis = text_basis(ep.text)
    part = getattr(llm, "part", None)  # 자동 집필 배치: 호출마다 작업 slot 을 따로 둔다
    todo = []
    for i in range(len(ep.plot.events)):
        plan, text = stage.scenes_of(ep, i)
        if plan is None or (text is not None and text.basis == basis):
            continue
        todo.append((i, text))
    if not todo:
        return [], []

    def one(i: int) -> StageProposal:
        cancel.check()
        return extract_stage(part(f"stage{i + 1}") if part else llm, p, n, i, hint)

    auto, held = [], []
    with ThreadPoolExecutor(max_workers=min(STAGE_EXTRACT_WORKERS, len(todo))) as pool:
        futures = [(text, pool.submit(contextvars.copy_context().run, one, i)) for i, text in todo]
        for text, fut in futures:
            try:
                prop = fut.result()
            except (cancel.Cancelled, Interrupted):
                pool.shutdown(wait=False, cancel_futures=True)  # 아직 보내지 않은 사건은 부르지 않는다
                raise
            except Exception:
                continue
            (held if text is not None and text.source == "manual" else auto).append(prop)
    return auto, held


def apply_stage(p: Project, prop: StageProposal, shared: bool = False) -> StageScene:
    """AI 장면을 통째로 넣는다. 같은 사건 · 같은 역할의 장면이 있으면 바꾸고 그 장면을 prev 에 남긴다(적용 취소 한 번).
    없던 장면이면 prev 는 id 가 빈 장면(적용 전에는 장면이 없었음)이다. 새 방이면 작품에 더한다(room_made).
    더할 기준점(adds)이 있으면: 장면 전용 방이면 그 방에 더하고(room_prev), 공용 방(stage.room_shared)이면 그 방을 복사한
    장면 전용 방에 더한다. shared 가 참이면 공용 방에 바로 더한다 (2026-10-29 사용자: 복사가 기본)."""
    ep = p.episode(prop.episode)
    scene = prop.scene.model_copy(deep=True)
    made, room_prev = "", None
    if prop.room is not None:
        room = prop.room.model_copy(deep=True)
        if any(r.id == room.id for r in p.rooms):
            room.id = stage._new_id("r", {r.id for r in p.rooms})
        p.rooms.append(room)
        scene.room = made = room.id
    elif prop.adds and prop.grown is not None:
        base = next((r for r in p.rooms if r.id == prop.grown.id), None)
        if base is None:  # 받은 뒤 방을 지웠으면 제안한 모습 그대로 새 방
            grown = prop.grown.model_copy(deep=True)
            p.rooms.append(grown)
            made = grown.id
        else:  # 받은 뒤 작가가 방을 고쳤을 수 있어 지금 방에 더한다
            grown, remap = stage.grow_room(base, prop.adds, prop.shift_x, prop.shift_y, prop.grown.w, prop.grown.h)
            stage.remap_anchors(scene, remap)
            if stage.room_shared(p, base.id, prop.episode, prop.event, prop.role) and not shared:
                grown.id = stage._new_id("r", {r.id for r in p.rooms})
                grown.name, grown.place = f"{base.name} · {prop.episode}화 사건 {prop.event + 1}", ""
                p.rooms.append(grown)
                made = grown.id
            else:
                room_prev = base.model_copy(deep=True)
                p.rooms = [grown if r.id == base.id else r for r in p.rooms]
        scene.room = grown.id
    scene.room_made, scene.room_prev = made, room_prev
    old = stage.scenes_of(ep, prop.event)[prop.role == "text"]
    if old is not None:
        scene.id = old.id
        scene.prev = old.model_copy(update={"prev": None, "room_prev": None, "room_made": ""}, deep=True)
        ep.stage = [scene if s.id == old.id else s for s in ep.stage]
    else:
        scene.id = stage._new_id("s", {s.id for s in ep.stage})
        scene.prev = StageScene(id="", event=prop.event, role=prop.role)
        ep.stage.append(scene)
    return scene


def undo_stage(p: Project, n: int, sid: str) -> StageScene | None:
    """마지막 AI 적용을 되돌린다. 적용 전에 장면이 없었으면 장면을 뺀다 (None)."""
    ep = p.episode(n)
    s = next((x for x in ep.stage if x.id == sid), None)
    if s is None:
        raise KeyError(f"{n}화에 그런 장면이 없어요: {sid}")
    if s.prev is None:
        raise ValueError("적용 취소할 AI 적용이 없어요")
    # 적용이 바꾼 방도 되돌린다: 기준점을 더한 방은 적용 전 모습으로, 새로 만든 방은 다른 장면이 쓰지 않으면 뺀다
    if s.room_prev is not None:
        p.rooms = [s.room_prev.model_copy(deep=True) if r.id == s.room_prev.id else r for r in p.rooms]
    made = s.room_made
    if not s.prev.id:
        stage.remove_scene(ep, sid)
        back = None
    else:
        back = s.prev.model_copy(update={"prev": None, "room_prev": None, "room_made": ""}, deep=True)
        ep.stage = [back if x.id == sid else x for x in ep.stage]
    if made and not stage.room_users(p, made):
        p.rooms = [r for r in p.rooms if r.id != made]
    return back


# ---------- 5-0. 검수 지적 고치기: 고침안, 묶음 적용 · 되돌리기, 지적 하나 다시 검수 ----------
# 고침안 하나는 지적한 문장과, 그 고침 때문에 함께 고칠 이 화의 다른 문장(딸린 곳)의 묶음이다. 한 번에 넣고 한 번에 되돌린다.
# 지적 하나만 다시 검수하면 회차는 늘지 않고, 고친 문장 때문에 새로 어긋난 곳은 딸린 지적이 된다 (findings.settle).

FIX_OPTIONS = 3  # 고침안 수


def _open_finding(p: Project, n: int, fid: str) -> tuple[Episode, Finding]:
    ep = _editable(p, n)
    f = findings.find(ep, fid)
    if f.status != "open":
        raise ValueError(f"{fid}는 열린 지적이 아니에요. 다시 연 뒤에 하세요")
    return ep, f


def _decided(ep: Episode) -> list[Finding]:
    return [g for g in ep.findings if g.status in findings.DECIDED]


_SENTENCE_END = re.compile(r"[.!?…。]+[\"'”’」』)]*(?=\s|$)")


def _adds_sentence(before: str, after: str) -> bool:
    """고친 글이 원래 글보다 문장이 많거나 1.5배(+10자)보다 길다: 새 동작 문장을 더한 고침."""
    count = lambda t: len(_SENTENCE_END.findall(t.strip())) or 1
    return count(after) > count(before) or len(after.strip()) > len(before.strip()) * 1.5 + 10


def clean_fixes(ep: Episode, f: Finding, fs: FixSet) -> list[FixOption]:
    """쓸 수 없는 고침안과 딸린 곳을 뺀다: 빈 글, 원문과 같은 글, 겹치는 안, 본문에 없는 딸린 문장,
    지적한 문장이나 다른 딸린 곳과 겹치는 딸린 곳, 동선 지적이면 새 문장을 더한 안 · 딸린 곳."""
    quote = f.current_quote.strip()
    motion = f.type == "동선"  # 동선 지적: 어긋난 낱말만 바꾼다. 새 동작 문장을 더한 안은 거른다 (장면 연출은 본문을 동작 묘사로 끌지 않는다)
    out: list[FixOption] = []
    for o in fs.options:
        text = o.text.strip()
        if not text or text == quote or any(text == y.text for y in out):
            continue
        if motion and _adds_sentence(quote, text):
            continue
        extra: list[FixPatch] = []
        for x in o.extra:
            q, rep = x.quote.strip(), x.replacement.strip()
            if not q or q not in ep.text or rep == q or (quote and (q in quote or quote in q)):
                continue
            if motion and _adds_sentence(q, rep):
                continue
            if any(q in y.quote or y.quote in q for y in extra):
                continue
            extra.append(FixPatch(quote=q, replacement=rep, reason=x.reason.strip()))
        out.append(FixOption(label=o.label.strip() or f"고침안 {len(out) + 1}", text=text, note=o.note.strip(), extra=extra))
    return out[:FIX_OPTIONS]


def _fixable(p: Project, n: int, fid: str) -> tuple[Episode, Finding]:
    """고침안을 받을 수 있는 열린 지적: 지적한 문장이 지금 본문에 있다."""
    ep, f = _open_finding(p, n, fid)
    if not f.current_quote.strip() or f.current_quote.strip() not in ep.text:
        raise ValueError("지적한 문장을 지금 본문에서 찾을 수 없어요. 이미 고쳤으면 이 지적만 다시 검수하세요")
    return ep, f


def _fix_result(ep: Episode, f: Finding, fs: FixSet) -> list[FixOption]:
    """AI 답 하나를 쓸 수 있는 고침안으로. 하나도 없으면 까닭을 담아 ValueError."""
    opts = clean_fixes(ep, f, fs)
    if not opts and not fs.options and fs.reply.strip():  # 본문이 맞다는 답 (prompts.TEXT_RIGHT_RULE)
        raise ValueError(f"AI가 본문은 고치지 않았어요. {fs.reply.strip()}")
    if not opts:
        raise ValueError("쓸 수 있는 고침안이 없었어요. 다시 받거나 직접 고치세요")
    return opts


def propose_fixes(llm: LLM, p: Project, n: int, fid: str) -> list[FixOption]:
    """열린 지적 하나의 고침안을 받는다. 저장하지 않는다 (store_fixes 가 지적에 남긴다).
    공통 자료(check_material)의 본문 바로 앞을 캐시 경계로 알려 (check_cache_cut), 같은 화의 첫 호출부터 그 앞부분을 캐시에 넣는다."""
    ep, f = _fixable(p, n, fid)
    material = prompts.check_material(p, n)
    fs = llm.json(prompts.reviser_system(p), prompts.fix_prompt(p, n, f, _decided(ep), material), FixSet,
                  hint={"episode": n, "quote": f.current_quote, "text": ep.text, PREFIX_HINT: prompts.check_cache_cut(material, n)})
    return _fix_result(ep, f, fs)


FIX_BATCH = 8  # 고침안을 한 번에 묻는 지적 수 (웹 작업 'fixes'). 지적마다 따로 물으면 같은 검수 자료를 지적 수만큼 보낸다


def propose_fixes_batch(llm: LLM, p: Project, n: int, fids: list[str]) -> dict[str, list[FixOption] | str]:
    """열린 지적 여러 개의 고침안을 한 번에 받는다. 저장하지 않는다. {지적 id: 고침안 또는 못 받은 까닭}.
    답에 없는 지적과 고침안도 답도 빈 항목은 결과에도 없다 (부른 쪽이 propose_fixes 로 따로 묻는다). 답의 id 가 요청에 없으면 버리고, 같은 id 는 처음 것만 쓴다."""
    out: dict[str, list[FixOption] | str] = {}
    ask: list[tuple[Episode, Finding]] = []
    for fid in fids:
        try:
            ask.append(_fixable(p, n, fid))
        except (ValueError, KeyError) as e:
            out[fid] = str(e.args[0]) if e.args else type(e).__name__
    if not ask:
        return out
    ep = ask[0][0]
    material = prompts.check_material(p, n)
    fb = llm.json(prompts.reviser_system(p), prompts.fix_batch_prompt(p, n, [f for _, f in ask], _decided(ep), material), FixBatch,
                  hint={"episode": n, "text": ep.text, "findings": [{"id": f.id, "quote": f.current_quote} for _, f in ask],
                        PREFIX_HINT: prompts.check_cache_cut(material, n)})
    by_id = {f.id: f for _, f in ask}
    for item in fb.items:
        fid = item.finding.strip()
        if fid not in by_id or fid in out or (not item.options and not item.reply.strip()):  # 빈 항목은 답이 없는 것으로 본다
            continue
        try:
            out[fid] = _fix_result(ep, by_id[fid], FixSet(reply=item.reply, options=item.options))
        except ValueError as e:
            out[fid] = str(e.args[0])
    return out


def store_fixes(p: Project, n: int, fid: str, opts: list[FixOption]) -> Finding:
    """받은 고침안을 지적에 남긴다. 지금 본문 지문을 함께 남겨, 본문이 바뀌면 화면이 오래된 안으로 보인다."""
    ep = p.episode(n)
    f = findings.find(ep, fid)
    f.fixes, f.fixes_basis = opts, text_basis(ep.text)
    findings.log(f, _now(), "fix", f"고침안 {len(opts)}개 받음")
    return f


FIX_WORKERS = 3  # 열린 지적 고침안을 한꺼번에 받을 때 동시에 부르는 수 (web 작업 'fixes': FIX_BATCH 개씩 묶은 호출과, 답에서 빠진 지적의 따로 묻기)


def fix_usable(ep: Episode, f: Finding, opt: FixOption) -> bool:
    """이 고침안을 지금 본문에 넣을 수 있는지: 지적한 문장과 딸린 곳이 모두 본문에 그대로 있다 (check.js fixMissing 과 같은 셈)."""
    quotes = [f.current_quote.strip(), *(x.quote.strip() for x in opt.extra)]
    return all(q and q in ep.text for q in quotes)


def fix_targets(ep: Episode) -> list[str]:
    """한꺼번에 고침안을 받을 지적: 열린 지적 가운데 지적한 문장이 지금 본문에 있고, 넣을 수 있는 고침안이 하나도 없는 것."""
    out = []
    for f in findings.open_findings(ep):
        q = f.current_quote.strip()
        if q and q in ep.text and not any(fix_usable(ep, f, o) for o in f.fixes):
            out.append(f.id)
    return out


def apply_fixes(p: Project, n: int, picks: list[tuple[str, int, list[int]]], confirm: bool = False) -> tuple[list[str], list[tuple[str, str]]]:
    """작가가 고른 고침안을 차례로 넣는다 (지적, 고침안 번호, 뺄 딸린 곳). 지적마다 한 묶음이라 하나씩 되돌릴 수 있다.
    앞 고침안이 같은 문장을 바꿔 못 넣은 것은 까닭과 함께 돌려주고 나머지는 넣는다. (넣은 지적, (못 넣은 지적, 까닭))."""
    _editable(p, n)
    done, failed = [], []
    for fid, k, skip in picks:
        try:
            apply_fix(p, n, fid, k, skip, confirm)
            done.append(fid)
        except (ValueError, KeyError) as e:
            failed.append((fid, str(e.args[0]) if e.args else type(e).__name__))
    return done, failed


def _group_id(ep: Episode) -> str:
    nums = [int(e.group[1:]) for e in ep.edits if e.group[1:].isdigit()]
    return f"x{max(nums, default=0) + 1}"


def apply_fix(p: Project, n: int, fid: str, k: int, skip: list[int] | None = None, confirm: bool = False) -> list[TextEdit]:
    """k 번째 고침안을 넣는다: 지적한 문장과, skip 에 없는 딸린 곳을 한 묶음(TextEdit.group)으로.
    작가가 그대로 둠 · 잘못 짚음으로 정한 지적의 문장을 바꾸면 confirm 없이는 막는다.
    지적 상태는 바꾸지 않는다 (이 지적만 다시 검수가 닫는다)."""
    ep, f = _open_finding(p, n, fid)
    if not 0 <= k < len(f.fixes):
        raise KeyError(f"{fid}에 {k + 1}번 고침안이 없어요")
    opt = f.fixes[k]
    skip = set(skip or [])
    chosen = opt.model_copy(update={"extra": [x for i, x in enumerate(opt.extra) if i not in skip]})
    patches = [(f.current_quote.strip(), opt.text), *((x.quote, x.replacement) for x in chosen.extra)]
    missing = [q for q, _ in patches if q not in ep.text]
    if missing:
        raise ValueError(f"고침안을 받은 뒤 본문이 바뀌어 «{missing[0][:30]}»을 찾을 수 없어요. 고침안을 다시 받으세요")
    hit = [g.id for g in ep.findings if g.id in findings.touches(ep, f, chosen) and g.status in findings.DECIDED]
    if hit and not confirm:
        raise ValueError(f"이 고침안은 그대로 두기로 정한 지적({', '.join(hit)})의 문장도 바꿔요. 그래도 적용하려면 확인하고 다시 적용하세요")
    group = _group_id(ep)
    edits = []
    for q, after in patches:
        e = edit_text(p, n, Selection(start=ep.text.find(q), text=q), after, "fix", instruction=f"{fid} · {opt.label}")
        e.group = group
        edits.append(e)
    f.fix_group = group
    findings.log(f, _now(), "fix", f"고침안 적용 · {opt.label}" + (f" · 딸린 곳 {len(patches) - 1}곳 함께" if len(patches) > 1 else ""))
    return edits


def undo_fix(p: Project, n: int, group: str) -> tuple[list[TextEdit], list[TextEdit]]:
    """고침안 묶음을 한 번에 되돌린다. 그 뒤에 같은 자리를 또 고친 곳은 남긴다. (되돌린 것, 남긴 것)."""
    ep = _editable(p, n)
    es = [e for e in ep.edits if e.group == group and not e.undone]
    if not es:
        raise KeyError(f"되돌릴 고침안 묶음이 없어요: {group}")
    done, left = [], []
    for e in reversed(es):
        try:
            undo_edit(p, n, e.id)
            done.append(e)
        except ValueError:
            left.append(e)
    if not done:
        raise ValueError("고침안을 넣은 뒤 같은 자리를 또 고쳐 되돌릴 수 없어요")
    for f in ep.findings:
        if f.fix_group == group:
            f.fix_group = ""
            findings.log(f, _now(), "undo", "고침안 되돌림" + (f" · {len(left)}곳은 그 뒤에 또 고쳐 남김" if left else ""))
    return done, left


def recheck_finding(llm: LLM, p: Project, n: int, fid: str) -> FindingRecheck:
    """열린 지적 하나만 다시 묻는다. 저장하지 않는다 (apply_recheck). 작가가 그 지적 때문에 넣은 고침안 묶음을 함께 보인다."""
    ep, f = _open_finding(p, n, fid)
    if f.origin == "rule":  # 장면 연출 규칙 지적: LLM 없이 지금 본문 장면으로 판정만 다시 (본문 장면은 다시 뽑지 않는다)
        still = [x for x in stage.episode_issues(p, ep) if _same_quote(x.current_quote, f.current_quote)]
        if not f.current_quote.strip() or f.current_quote.strip() not in ep.text:
            return FindingRecheck(resolved=True, reason="짚은 문장이 본문에서 바뀌었어요")
        return FindingRecheck(resolved=not still, reason=still[0].description if still else "장면 연출 규칙 판정에 더 걸리지 않아요")
    if f.origin == "regex":  # 정규식 경고 규칙 지적: LLM 없이 그 규칙만 지금 본문에 다시 건다
        try:  # 시간 한도에 걸렸거나 규칙이 없어졌으면 '안 걸림' 으로 닫지 않고 열어 둔다
            hit = regexrules.hits(p, ep.text, n, only=f.regex_rule, strict=True)
        except regexrules.RuleSkipped as e:
            return FindingRecheck(resolved=False, reason=f"{e}. 판정하지 못해 지적을 열어 두었어요")
        still = [x for x in hit if _same_quote(x.current_quote, f.current_quote)]
        return FindingRecheck(resolved=not still, reason="정규식 규칙에 아직 걸려요" if still else "정규식 규칙에 더 걸리지 않아요")
    changes = [(e.before, e.after) for e in ep.edits if f.fix_group and e.group == f.fix_group and not e.undone]
    material = prompts.check_material(p, n)  # 검수와 같은 앞부분. 본문 바로 앞을 캐시 경계로 알린다 (check_cache_cut)
    return llm.json(prompts.SYSTEM_CHECKER, prompts.recheck_prompt(p, n, f, changes, _decided(ep), material), FindingRecheck,
                    hint={"episode": n, "quote": f.current_quote, "text": ep.text, PREFIX_HINT: prompts.check_cache_cut(material, n)})


def apply_recheck(p: Project, n: int, fid: str, res: FindingRecheck) -> list[Finding]:
    """지적 하나만 다시 검수한 결과를 넣는다 (findings.settle). 새로 생긴 딸린 지적을 돌려준다."""
    ep = p.episode(n)
    return findings.settle(ep, findings.find(ep, fid), res, _now())


def _fix_spots(ep: Episode, es: list[TextEdit]) -> list[tuple[int, int]]:
    """고침안 수정들이 지금 본문에 놓인 자리 [시작, 끝]. 고친 글이 여러 곳에 있으면 기록한 자리(e.start)에 가장 가까운 곳을 고른다.
    고친 글을 못 찾으면 기록한 자리로 본다 (지우기만 한 수정)."""
    out = []
    for e in es:
        hits, at = [], ep.text.find(e.after) if e.after.strip() else -1
        while at >= 0:
            hits.append(at)
            at = ep.text.find(e.after, at + 1)
        at = min(hits, key=lambda h: abs(h - e.start)) if hits else min(e.start, len(ep.text))
        out.append((at, at + len(e.after)))
    return out


def fix_recheck_basis(ep: Episode) -> tuple[str, str, dict[str, str]]:
    """고친 곳만 다시 보기가 본 상태: (마지막 검수 시각, 본문, 대상 지적 id → 고침안 묶음). apply_fix_recheck 가 그사이 바뀌었는지 본다."""
    return ep.checked_at, ep.text, {f.id: f.fix_group for f in findings.fix_recheck_targets(ep)}


def recheck_fixed(llm: LLM, p: Project, n: int) -> FixRecheckReport:
    """고친 곳만 다시 보기: 지난 검수 뒤 고침안을 넣은 열린 지적들을 한 번의 호출로 다시 본다 (findings.fix_recheck_targets).
    검수 자료 전체 대신 작품 설정과 고친 곳 둘레 문단(직접 고친 곳 포함)만 보낸다. 저장하지 않는다 (apply_fix_recheck).
    장면 연출 규칙 · 정규식 경고 규칙 지적은 LLM 없이 판정만 다시 한다 (recheck_finding). 돌려준 결과가 없는 지적은 결과에 없다."""
    ep = _editable(p, n)
    targets = findings.fix_recheck_targets(ep)
    if not targets:
        raise ValueError("고친 곳만 다시 볼 지적이 없어요. 지난 검수 뒤 고침안 말고도 고친 곳이 있으면 다시 검수하세요")
    out = [FixRecheckItem(id=f.id, **recheck_finding(llm, p, n, f.id).model_dump()) for f in targets if f.origin in ("rule", "regex")]
    ai = [f for f in targets if f.origin not in ("rule", "regex")]
    if ai:
        groups = {f.id: [e for e in ep.edits if e.group == f.fix_group and not e.undone] for f in ai}
        items = [(f, f.id, [(e.before, e.after) for e in groups[f.id]]) for f in ai]
        around = prompts.fix_around(ep.text, _fix_spots(ep, findings.edits_since_check(ep)))  # 직접 고친 곳도 둘레로 보인다
        rep = llm.json(prompts.SYSTEM_CHECKER, prompts.fix_recheck_prompt(p, n, items, around, _decided(ep)), FixRecheckReport,
                       hint={"episode": n, "items": [{"id": f.id, "quote": f.current_quote} for f in ai], "text": ep.text,
                             PREFIX_HINT: len(prompts.static_context(p))})  # 첫 호출부터 작품 고정 앞부분을 캐시에 넣는다
        want, seen = {f.id for f in ai}, set()
        for x in rep.results:  # 묻지 않은 id 와 같은 id 의 두 번째 답은 버린다
            if x.id in want and x.id not in seen:
                seen.add(x.id)
                out.append(x)
    return FixRecheckReport(results=out)


def apply_fix_recheck(p: Project, n: int, rep: FixRecheckReport, basis: tuple[str, str, dict[str, str]] | None = None,
                      settled: list[FixRecheckItem] | None = None) -> list[Finding]:
    """고친 곳만 다시 보기 결과를 지적마다 넣는다 (findings.settle). 그사이 닫힌 지적은 건너뛴다. 새로 생긴 딸린 지적을 돌려준다.
    basis(fix_recheck_basis)를 주면, 묻는 사이 검수를 다시 했거나 본문이 바뀌었을 때 아무것도 넣지 않고 ValueError 를 낸다.
    묶음이 바뀐 지적도 건너뛴다. settled 를 주면 실제로 넣은 결과를 거기에 더한다."""
    ep = p.episode(n)
    groups = None
    if basis is not None:
        checked_at, text, groups = basis
        if ep.checked_at != checked_at or ep.text != text:
            raise ValueError("다시 보는 사이 본문이나 검수 결과가 바뀌어서 결과를 넣지 않았어요. 다시 해 주세요")
    at, kids = _now(), []
    for x in rep.results:
        f = next((g for g in ep.findings if g.id == x.id), None)
        if f is None or f.status != "open" or (groups is not None and groups.get(f.id) != f.fix_group):
            continue
        kids += findings.settle(ep, f, x, at)
        if settled is not None:
            settled.append(x)
    return kids


def style_baseline(p: Project) -> metrics.StyleMetrics:
    """문체 기준값: 작품 정착 문체(anchor) → 레퍼런스 원문 전체로 잰 값 → (예전 프로젝트) 발췌 문단으로 잰 값."""
    if p.anchor is not None and p.anchor.metrics is not None:
        return p.anchor.metrics
    return p.style_baseline or metrics.measure("\n\n".join(p.style.sample_passages))


VOICE_SKIP = ("과거형 서술 비율", "문체 거리", "'~다.'")  # 서술 말투가 있는 화에서 빼는 어미 관련 경고 (문장 끝 두 줄 포함)


def style_drift(p: Project, n: int) -> tuple[metrics.StyleMetrics, list[str]]:
    """이번 화 문체 지표와 경고. 기준값과의 차이, 문체 거리, 표지 빈도, 예시 문단 베끼기를 본다."""
    text = p.episode(n).text
    base = style_baseline(p)
    cur = metrics.measure(text, p.style.banned_phrases)
    cur.style_distance = metrics.style_distance(base, text)
    warns = metrics.drift(base, cur)
    warns += metrics.peak_drift(base, metrics.peak_window(text, p.settings.heat_words))
    voiced = (c := prompts.pov_character(p, n)) is not None and bool(c.narration_voice.strip())
    if voiced:  # 시점 인물의 서술 말투로 쓴 화는 어미가 기준 원문과 달라야 맞다
        warns = [w for w in warns if not w.startswith(VOICE_SKIP)]
    marks = [] if voiced else metrics.marker_warnings(anchor.markers(p), text)
    if marks:
        warns.append(f"문체 버릇: {', '.join(marks)}")
    warns[:0] = [f"장치 {w}" for w in metrics.device_warnings(p.style.devices, p.episodes, n, text)]  # 자동 집필 기록은 앞 3개만 남긴다
    if (drift := anchor.warning(p, n)):
        warns.append(drift)
    copied = metrics.copied_sentences(text, list(dict.fromkeys(p.style.sample_passages + prompts.style_passages(p))))
    if copied:
        quotes = ", ".join(f"'{s[:30]}{'…' if len(s) > 30 else ''}'" for s in copied[:3])
        warns.append(f"예시 문단을 옮긴 문장 {len(copied)}개: {quotes}")
    tails = metatail.warnings(text)
    if tails:
        quotes = ", ".join(f"'{s[:40]}{'…' if len(s) > 40 else ''}'" for s in tails[:2])
        warns.append(f"본문이 아닌 작업 설명처럼 보이는 앞뒤 문단 {len(tails)}개: {quotes}")
    said = speech_copied(p, text)
    if said:
        quotes = ", ".join(f"'{s[:30]}{'…' if len(s) > 30 else ''}'" for s in said[:3])
        warns.append(f"말투 예시 대사를 그대로 쓴 문장 {len(said)}개: {quotes}")
    moved = memo_copied(p, n, text)
    if moved:
        quotes = ", ".join(f"'{s[:30]}{'…' if len(s) > 30 else ''}'" for s in moved[:3])
        warns.append(f"설계 메모를 옮긴 문장 {len(moved)}개: {quotes}")
    return cur, warns


def memo_texts(p: Project, n: int) -> list[str]:
    """쓰기 프롬프트에 들어가는 설계 메모 칸: 플롯 감정 변화, 스토리보드 장면 목표 · 전환 · 끝 상태 · 넘겨받을 것, 큐의 일 · 끝 상태.
    큐 핵심 대사와 플롯 사건은 본문에 들어가야 하는 것이라 뺀다."""
    ep = p.episode(n)
    out = [ep.plot.emotional_shift]
    if ep.storyboard:
        out += [x for sc in ep.storyboard.scenes for x in (sc.goal, sc.turn, sc.end_state)]
        out += [h.text for h in ep.storyboard.handover]
    if ep.cue_sheet and not ep.cue_sheet.skipped:  # 큐 시트 없이 쓴 본문에는 큐 메모가 들어가지 않았다
        out += [x for c in ep.cue_sheet.cues for x in (c.beat, c.exit)]
    return [x for x in out if x and x.strip()]


def speech_copied(p: Project, text: str) -> list[str]:
    """인물 말투(speech_style)의 따옴표 대사 예시를 본문에 그대로 쓴 문장 (metrics.speech_copied). 예시는 어미 · 호칭 · 길이를 보여 줄 뿐이다."""
    return metrics.speech_copied(text, [c.speech_style for c in p.characters if c.speech_style])


def memo_copied(p: Project, n: int, text: str) -> list[str]:
    """설계 메모를 본문에 그대로 옮긴 문장 (공백 빼고 metrics.COPY_SPAN 자 이상 겹침). 쇠맛 연구(2026-10-30)에서
    감정 변화 칸 조각의 22%, 스토리보드 장면 메모의 11%가 본문에 그대로 옮겨졌다. 메모는 따를 것이지 옮길 글이 아니다."""
    return metrics.copied_sentences(text, memo_texts(p, n))


def text_basis(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


# ---------- 6. 상태 갱신 ----------

def extract_state(llm: LLM, p: Project, n: int, audit: LLM | None = None) -> StateDelta:
    """n화 상태 변경안. 작품 설정 state_audit 를 켜면 받은 뒤 누락 검사(audit_delta)를 한 번 더 부른다.
    audit 를 주지 않으면 audit 단계 모델(get_llm('audit'))을 쓴다. 반영 기록에서 돌아온 변경안(carried_delta)은 다시 검사하지 않는다."""
    if not p.episode(n).text:
        raise ValueError(f"{n}화 본문이 없어요")
    carried = carried_delta(p, n)
    if carried is not None:
        return carried
    basis = text_basis(p.episode(n).text)  # 프롬프트에 넣은 본문의 지문. 부르는 사이 p 가 바뀌어도 이 본문 기준이다
    hint = {"episode": n, "stats": statwin.enabled(p)}
    if getattr(llm, "family_cache", False):  # 캐시 가족을 받는 백엔드(Claude)는 검수 자료로 시작해 검수가 쓴 캐시를 읽는다
        material = prompts.check_material(p, n)
        prompt, hint[PREFIX_HINT] = prompts.state_prompt(p, n, head=material), prompts.check_cache_cut(material, n)
    else:
        prompt = prompts.state_prompt(p, n)
    raw = llm.json(prompts.SYSTEM_EDITOR, prompt, StateDeltaAI, hint=hint)
    delta = to_delta(raw, n)  # 관계 수치 칸은 응답 형식에 없고, 있어도 버린다
    clean_delta(p, delta)
    delta.basis = basis
    if p.settings.state_audit:
        if audit is None:
            from .llm import get_llm
            audit = get_llm("audit")
        audit_delta(audit, p, n, delta)
    return delta


AUDIT_MARK = "[누락 의심]"  # 누락 검사 경고의 머리. 자동 집필 정책은 이 경고를 따로 센다 (autorun.Policy.stop_on_audit)
AUDIT_MAX = 6
AUDIT_QUOTE_MIN = 8  # 띄어쓰기 · 문장 부호를 뺀 인용 글자 수 하한. '그는' 같은 짧은 인용은 어디에나 있어 근거가 못 된다


def drop_audit_warnings(d: StateDelta) -> None:
    """누락 검사 경고를 warn_to 와 함께 뺀다. 옛 본문 기준의 누락 의심을 다시 쓰는 변경안(carried_delta · 반영 취소)에 남기지 않는다."""
    features.align_warn_to(d)
    keep = [i for i, w in enumerate(d.warnings) if not w.startswith(AUDIT_MARK)]
    d.warnings, d.warn_to = [d.warnings[i] for i in keep], [d.warn_to[i] for i in keep]


def audit_delta(llm: LLM, p: Project, n: int, d: StateDelta) -> list[str]:
    """받은 상태 변경안에 본문의 비밀 공개 · 관계 사건 · 약속 · 부상 · 정체 공개 · 장소 이동 · 소지품이 빠졌는지 한 번 더 묻는다.
    본문에서 찾을 수 없는 인용은 버리고 AUDIT_MAX 개까지 '[누락 의심]' 경고로만 d.warnings 끝에 붙인다(warn_to 는 "").
    변경안 칸은 바꾸지 않는다. 검사가 실패하면 경고를 붙이지 않고 변경안은 그대로 둔다. 붙인 경고."""
    text = p.episode(n).text
    try:
        rep = llm.json(prompts.SYSTEM_EDITOR, prompts.audit_prompt(p, n, d), AuditReport, hint={"episode": n, "text": text})
    except Interrupted:
        raise
    except Exception as e:  # 누락 검사는 덤이라 변경안을 막지 않는다
        logging.getLogger("canon").warning("%s화 상태 변경안 누락 검사가 실패했어요: %s", n, e)
        return []
    out: list[str] = []
    for x in rep.items:
        q = x.quote.strip().strip("«»")
        if len(foreshadows.norm(q)) < AUDIT_QUOTE_MIN or not x.missing.strip() or not findings.in_text(text, q):
            continue
        w = f"{AUDIT_MARK} {x.kind}: {x.missing.strip()} «{q}»"
        if w not in out and w not in d.warnings:
            out.append(w)
        if len(out) >= AUDIT_MAX:
            break
    features.align_warn_to(d)
    d.warnings += out
    d.warn_to += [""] * len(out)
    return out


def clean_delta(p: Project, d: StateDelta) -> None:
    """AI 나 채팅 앱이 낸 상태 변경안 정리. 기능마다 하는 일(복선 문장 맞추기, 새 장소 거르기, 이동 거리 · 상태창 경고 등)은
    features.CLEAN 목록에 있다."""
    features.clean(p, d)


def _delta_checks(p: Project, d: StateDelta) -> list[tuple]:
    """변경안 목록마다 (칸 이름, 목록, 항목 → 문제 문구 또는 ''). validate_delta 와 drop_invalid 가 같이 쓴다."""
    known = {c.id for c in p.characters} | {c.id for c in d.new_characters}
    shadows = {f.id for f in p.foreshadows} | {f.id for f in d.foreshadow_planted}

    def pair(a: str, b: str, what: str) -> str:
        bad = sorted({x for x in (a, b) if x not in known})
        if bad:
            return f"{what}에 설정에 없는 인물이 있어요: {', '.join(bad)}"
        return f"{what}이 같은 인물끼리예요: {a}" if a == b else ""

    return [
        ("character_updates", d.character_updates,
         lambda u: "" if u.character_id in known else f"설정에 없는 인물의 상태예요: {u.character_id}"),
        ("events", d.events,
         lambda e: "" if e.kind == "수동보정" else pair(e.actor, e.target, f"관계 사건({e.actor}→{e.target})")),
        ("relationship_updates", d.relationship_updates, lambda r: pair(r.a, r.b, f"관계 바뀜({r.a}↔{r.b})")),
        ("secrets_added", d.secrets_added,
         lambda s: "" if s.owner in known else f"설정에 없는 인물의 비밀이에요: {s.owner}"),
        ("foreshadow_resolved", d.foreshadow_resolved,
         lambda x: "" if x in shadows else f"없는 복선을 회수했어요: {x}"),
    ]


def validate_delta(p: Project, d: StateDelta) -> list[str]:
    """반영하면 누구의 것도 아닌 데이터가 남는 항목 (설정에 없는 인물 id, 같은 인물끼리의 관계, 설정에 없는 인물의 비밀, 없는 복선 id).
    새 인물(d.new_characters)과 이번에 심는 복선은 아는 것으로 센다. p 와 d 를 바꾸지 않는다. web 반영은 이것이 있으면 막는다."""
    return [m for _, items, why in _delta_checks(p, d) for m in map(why, items) if m]


def drop_invalid(p: Project, d: StateDelta) -> list[str]:
    """validate_delta 에 걸린 항목을 d 에서 빼고 그 문구를 돌려준다. 사건 목격자 중 설정에 없는 인물도 뺀다(사건은 남긴다).
    비밀을 모르는 인물(hidden_from) 중 설정에 없는 인물과 없는 비밀 id 를 가리키는 사건의 reveals_secret 도 빼고(비밀 · 사건은 남긴다) 그 문구를 더한다.
    뺀 항목은 d.dismissed 의 같은 칸에 남겨 반영 기록에서 보이고, 반영 취소로 돌아오면 체크를 푼 채 다시 놓인다."""
    out: list[str] = []
    for name, items, why in _delta_checks(p, d):
        keep, drop = [], []
        for i, x in enumerate(items):
            m = why(x)
            if m:
                out.append(m)
                getattr(d.dismissed, name).append(x)
                drop.append(i)
            else:
                keep.append(x)
        if name == "relationship_updates":
            d.drop_rel_rows(drop)  # rel_flagged 도 남은 행의 차례로 다시 매긴다
        else:
            setattr(d, name, keep)
    known = {c.id for c in p.characters} | {c.id for c in d.new_characters}
    for e in d.events:
        e.witnesses = [w for w in e.witnesses if w in known]
    for s in d.secrets_added:
        if (gone := [x for x in s.hidden_from if x not in known]):
            out.append(f"비밀({s.id})을 모르는 인물에서 설정에 없는 인물을 뺐어요: {', '.join(gone)}")
            s.hidden_from = [x for x in s.hidden_from if x in known]
    secrets = {s.id for s in p.secrets} | {s.id for s in d.secrets_added}
    for e in d.events:
        if e.reveals_secret and e.reveals_secret not in secrets:
            out.append(f"관계 사건({e.actor}→{e.target})이 드러낸 비밀이 없는 비밀이라 지웠어요: {e.reveals_secret}")
            e.reveals_secret = ""
    return out


def apply_delta(p: Project, d: StateDelta) -> list[str]:
    """변경안을 반영한다. 반영하면 누구의 것도 아닌 데이터가 남는 항목은 빼고(drop_invalid) 뺀 항목의 문구를 돌려준다.
    작가가 고르는 web 반영은 그 전에 validate_delta 로 막는다. 자동 집필 · 명령줄은 돌려받은 문구를 경고로 남기고, 플레이는 버린다."""
    dropped = drop_invalid(p, d)
    ep = p.episode(d.episode)
    dynamics.ensure_initial(p)
    ep.summary = d.summary
    ep.status, ep.final_text = "finalized", ""
    # 이미 있는 인물은 새 인물로 더하지 않는다. 기록(history)에 남으면 반영 취소가 그 인물을 지운다
    have = {c.id for c in p.characters}
    dup = [c for c in d.new_characters if c.id in have]
    if dup:
        d.new_characters = [c for c in d.new_characters if c.id not in have]
        d.dismissed.new_characters += dup
        dropped.append(f"이미 있는 인물이라 새 인물에서 뺐어요: {', '.join(c.id for c in dup)}")
    _add_characters(p, d.new_characters, d.episode)
    added = AddedItems()
    features.apply(features.APPLY_FIRST, p, d)  # 설정 바꾸기 제안 · 새 장소
    ep.auto = False  # 자동 집필은 반영한 뒤 True 로 표시한다

    for upd in d.character_updates:
        cur = p.state_of(upd.character_id)
        if cur is None:
            cur = upd.model_copy(deep=True, update={"stats": [], "cleared": []})
            p.states.append(cur)
        else:
            for field in ("emotional_state", "current_goal", "location", "attire", "notes"):
                if field in upd.cleared:  # 지우기는 빈 칸('그대로')과 달리 칸을 비운다
                    setattr(cur, field, "")
                elif getattr(upd, field):
                    setattr(cur, field, getattr(upd, field))
            cur.knows += [k for k in upd.knows if k not in cur.knows]
        statwin.merge(p, cur, upd.stats, d.episode)  # +3 같은 바뀐 양은 여기서 값으로 바꾸고 기록한다

    for upd in d.relationship_updates:  # 관계 수치는 AI 가 적지 않는다: 사건으로 dynamics 가 계산하고, 새 쌍은 중립에서 시작한다
        upd.affinity, upd.tension, upd.goal_conflict, upd.a_view, upd.b_view, upd.destination = 0, 0, 0.0, [], [], ""
    for upd in d.relationship_updates:
        if upd.a == upd.b:  # 같은 인물끼리의 관계는 두지 않는다 (화면 저장이 막는 관계, validate_relationships)
            continue
        key = frozenset((upd.a, upd.b))
        for r in p.relationships:
            if frozenset((r.a, r.b)) == key:
                r.type, r.description = upd.type or r.type, upd.description or r.description
                break
        else:
            p.relationships.append(upd.model_copy(deep=True))  # 복사해 넣는다. sync_relationships 가 바꿔도 기록(history)의 값은 보낸 그대로 남는다
            added.relationships.append([upd.a, upd.b])
            dynamics.seed_ties(p)

    # 복사해 넣는다. 사건이 비밀을 드러내 hidden_from 을 줄여도 기록(history)의 처음 모습은 남아야 다시 계산할 수 있다
    d.secrets_added = _first_new(d.secrets_added, {s.id for s in p.secrets}, d.dismissed.secrets_added)
    p.secrets += [s.model_copy(deep=True) for s in d.secrets_added]
    added.secrets = [s.id for s in d.secrets_added]
    events = [e.model_copy(update={"episode": d.episode}) for e in d.events if e.kind != "수동보정"]
    dynamics.run_episode(p, d.episode, events, ep.plot.characters)
    p.events += events

    d.new_facts = list(dict.fromkeys(f for f in d.new_facts if f not in p.facts))
    p.facts += d.new_facts
    was_resolved = {f.id for f in p.foreshadows if f.status == "resolved"}
    # 심은 복선은 apply_restate 와 같게 이번 화에 심은 열린 복선으로 맞춘다. AI 가 적은 심은 화 · 상태 · 회수 화는 믿지 않는다
    plants = _first_new(d.foreshadow_planted, {f.id for f in p.foreshadows}, d.dismissed.foreshadow_planted)
    d.foreshadow_planted = [f.model_copy(deep=True, update={"planted_ep": d.episode, "status": "open", "payoff_ep": None}) for f in plants]
    p.foreshadows += [f.model_copy(deep=True) for f in d.foreshadow_planted]
    resolved = list(dict.fromkeys(d.foreshadow_resolved))
    d.dismissed.foreshadow_resolved += [x for x in resolved if x in was_resolved]  # 이미 회수한 복선의 회수 화를 덮지 않는다
    d.foreshadow_resolved = [x for x in resolved if x not in was_resolved]
    for c in d.foreshadow_clues:  # 뺀 회수의 회수 문장은 다시 떠올린 문장으로 남긴다 (foreshadows.clean_delta 와 같은 규칙)
        if c.kind == "payoff" and c.foreshadow in was_resolved:
            c.kind = "plant"
    added.facts = list(d.new_facts)
    added.foreshadows = [f.id for f in d.foreshadow_planted]
    for f in p.foreshadows:
        if f.id in d.foreshadow_resolved:
            f.status, f.payoff_ep = "resolved", d.episode
    features.apply(features.APPLY_LAST, p, d)  # 복선 문장 · 작품 속 시간
    d.legacy_rel = False  # 다시 계산(dynamics.replay)이 이 기록의 관계 수치를 쓰지 않게 한다
    d.added = added  # 반영 취소가 이 반영이 실제로 더한 것만 뺀다 (_undo_later)
    d.drop_rel_rows([])  # 기록의 rel_flagged 는 남은 행을 가리키는 차례만 둔다 (반영 취소로 다시 놓일 때 기본 체크)
    p.history.append(d)
    dynamics.take_snapshot(p, d.episode)
    if p.serial:
        prune_snapshots(p)
    return dropped


def _first_new(items: list, known: set[str], skipped: list) -> list:
    """id 가 known 에 없는 항목만 차례대로 남긴다. 한 변경안 안에서 같은 id 가 또 오면 처음 것만 남긴다. 뺀 항목은 skipped 에 넣는다."""
    seen, out = set(known), []
    for x in items:
        if x.id in seen:
            skipped.append(x)
        else:
            seen.add(x.id)
            out.append(x)
    return out


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


def _undo_later(p: Project, n: int, snap: Snapshot) -> None:
    """revert 가 부른다 (반영 기록 · 사건을 자르기 전). n화 뒤 반영(history)이 한 일만 되돌리고, n화 뒤 작가가 더하거나 고친 것은 둔다.
    - 관계 간선(Tie)은 사건이 움직이므로 n화 스냅샷으로 덮고, 작가가 더한 관계의 간선은 지금 관계 값으로 다시 만든다(seed_ties)
    - 인물 상태는 n화 스냅샷으로 덮는다. 스냅샷에 상태가 없는 인물(n화 뒤 작가가 더함)은 지금 상태를 두고, 뒤 반영이 그 상태를 바꿨으면 처음 상태로 만든다
    - 관계 · 비밀 · 사실 · 복선은 뒤 반영이 더한 것만 뺀다. 반영 기록의 added 를 보고, 그 칸이 없는 예전 기록은 반영 직전 스냅샷에 없던 것을 그 반영이 더한 것으로 본다
    - 뒤 반영이 유형 · 설명을 바꾼 관계는 스냅샷 값으로, 남은 관계의 수치는 스냅샷 값으로 돌린다
    - 뒤 사건이 드러낸 비밀은 스냅샷의 모르는 인물로, 뒤 반영이 회수한 그대로인 복선은 스냅샷의 상태 · 회수 화로 돌린다"""
    later = [d for d in p.history if d.episode > n]
    pair = lambda a, b: frozenset((a, b))  # noqa: E731

    def before(m: int) -> Snapshot:  # m화 반영 직전에 가장 가까운 스냅샷 (n화 스냅샷은 늘 있다)
        return max((s for s in p.snapshots if n <= s.episode < m), key=lambda s: s.episode, default=snap)

    born_rel: set[frozenset] = set()
    born_sec: set[str] = set()
    born_fact: set[str] = set()
    born_fs: set[str] = set()
    for d in later:
        if d.added is not None:  # 반영할 때 적은 기록: 그 반영이 실제로 더한 것
            born_rel |= {pair(*x) for x in d.added.relationships if len(x) == 2}
            born_sec |= set(d.added.secrets)
            born_fact |= set(d.added.facts)
            born_fs |= set(d.added.foreshadows)
            continue
        b = before(d.episode)  # 예전 기록: 반영 직전 스냅샷에 없던 것을 그 반영이 더한 것으로 본다
        born_rel |= {pair(r.a, r.b) for r in d.relationship_updates} - {pair(r.a, r.b) for r in b.relationships}
        born_sec |= {s.id for s in d.secrets_added} - {s.id for s in b.secrets}
        born_fact |= set(d.new_facts) - set(b.facts)
        born_fs |= {f.id for f in d.foreshadow_planted} - {f.id for f in b.foreshadows}
    ids = {c.id for c in p.characters}

    had = {s.character_id for s in snap.states}
    moved = {u.character_id for d in later for u in d.character_updates}
    p.states = [s.model_copy(deep=True) for s in snap.states if s.character_id in ids] + [
        s for s in p.states if s.character_id in ids and s.character_id not in had and s.character_id not in moved]
    _init_states(p)

    snap_rel = {pair(r.a, r.b): r for r in snap.relationships}
    touched = {pair(r.a, r.b) for d in later for r in d.relationship_updates}
    rels = []
    for r in p.relationships:
        k = pair(r.a, r.b)
        if k in born_rel or r.a not in ids or r.b not in ids:
            continue
        old = snap_rel.get(k)
        if old is not None and k in touched:
            r = old.model_copy(deep=True)
        elif old is not None:
            r.affinity, r.tension = old.affinity, old.tension
        rels.append(r)
    p.relationships = rels
    p.ties = [t.model_copy(deep=True) for t in snap.ties if t.source in ids and t.target in ids]
    dynamics.seed_ties(p)

    snap_sec = {s.id: s for s in snap.secrets}
    revealed = {e.reveals_secret for e in p.events if e.episode > n and e.reveals_secret}
    p.secrets = [s for s in p.secrets if s.id not in born_sec]
    for s in p.secrets:
        if s.id in revealed and s.id in snap_sec:
            s.hidden_from = list(snap_sec[s.id].hidden_from)

    p.facts = [f for f in p.facts if f not in born_fact]

    snap_fs = {f.id: f for f in snap.foreshadows}
    paid = {x: d.episode for d in later for x in d.foreshadow_resolved}
    p.foreshadows = [f for f in p.foreshadows if f.id not in born_fs]
    for f in p.foreshadows:
        if f.id in paid and f.status == "resolved" and f.payoff_ep == paid[f.id]:
            old = snap_fs.get(f.id)
            f.status, f.payoff_ep = (old.status, old.payoff_ep) if old else ("open", None)


def revert(p: Project, n: int) -> None:
    """n화 상태 반영 직후로 되돌린다. 이후 화의 본문은 남기고 상태 반영만 취소한다."""
    snap = p.snapshot(n)
    if snap is None:
        raise ValueError(f"{n}화 스냅샷이 없어요 (있는 화: {[s.episode for s in p.snapshots]})")
    # 되돌리는 반영이 더한 인물(new_characters)도 되돌린다. 뒤 화 플롯에 나오면 지우지 않고 인물 후보로 돌린다
    # n화 때 이미 있던 인물(n화 스냅샷에 상태가 있거나 설정 단계 인물)은 지우지 않는다: 예전 기록에 이미 있는 id 가 새 인물로 남아 있을 수 있다.
    # first_ep 는 AI 가 채울 수 있는 칸이라 '처음 나온 화 <= n' 으로는 가리지 않는다
    was = {s.character_id for s in snap.states} | {c.id for c in p.characters if not c.first_ep}
    added = {c.id for d in p.history if d.episode > n for c in d.new_characters} - was
    if added:
        back = [c for c in p.characters if c.id in added]
        p.characters = [c for c in p.characters if c.id not in added]
        have = {c.id for c in p.cast_candidates}
        p.cast_candidates += [c for c in back if c.id not in have]
    features.revert(features.REVERT_FIRST, p, n, snap)  # 뒤 반영이 본문에서 등록한 장소
    _undo_later(p, n, snap)
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
    plants = [f.model_copy(update={"planted_ep": n, "status": "open", "payoff_ep": None}) for f in d.foreshadow_planted
              if f.id not in known and not known.add(f.id)]  # 변경안 안에서 같은 id 가 두 번 오면 앞의 것만
    # 복선 근거 문장은 이번에 새로 심은 복선의 plant 문장만 붙인다 (상태 승인의 foreshadows.apply_delta 와 같은 모양)
    new_ids = {f.id for f in plants}
    seen = {foreshadows._key(c) for c in p.foreshadow_clues}
    clues = []
    for c in d.foreshadow_clues:
        c = c.model_copy(update={"episode": n, "by": "ai"})
        if c.kind == "plant" and c.foreshadow in new_ids and foreshadows._key(c) not in seen:
            seen.add(foreshadows._key(c))
            clues.append(c)
    if summary:
        ep.summary = summary
    p.facts += facts
    p.foreshadows += plants
    p.foreshadow_clues += clues
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
        rec.foreshadow_clues += [c.model_copy(deep=True) for c in clues]
        if rec.added is not None:  # 반영 취소가 고친 화에서 더한 것도 뺀다
            rec.added.facts += facts
            rec.added.foreshadows += [f.id for f in plants]
        rec.new_places += [x.model_copy(deep=True) for x in places]
    ep.final_text = ""
    return {"summary": bool(summary), "facts": len(facts), "foreshadows": len(plants), "clues": len(clues), "places": len(places)}


def take_dismissed_fact(p: Project, n: int, i: int) -> str:
    """n화 반영 기록에서 빼 둔 새 사실(dismissed.new_facts) 하나를 확정 사실에 넣는다. 자동 반영이 이미 있는 사실과 비슷해 뺀 것을
    작가가 나중에 고르는 길이다. 그 화와 뒤 화의 스냅샷 · 반영 기록에도 넣어 반영 취소와 맞춘다(apply_restate 와 같다).
    넣은 사실. 이미 있는 사실이면 빼 둔 목록에서만 지우고 빈 글."""
    rec = next((h for h in reversed(p.history) if h.episode == n), None)
    if rec is None or not 0 <= i < len(rec.dismissed.new_facts):
        raise ValueError(f"{n}화 반영 기록에 빼 둔 사실이 없어요. 화면을 새로 고쳐 보세요")
    fact = rec.dismissed.new_facts.pop(i).strip()
    rec.fact_near = [x for x in rec.fact_near if x.fact != fact]  # 작가가 고른 사실이라 반영 취소로 다시 놓일 때 기본으로 빼지 않는다
    if not fact or fact in p.facts:
        return ""
    p.facts.append(fact)
    for snap in p.snapshots:
        if snap.episode >= n and fact not in snap.facts:
            snap.facts.append(fact)
    rec.new_facts.append(fact)
    if rec.added is not None:
        rec.added.facts.append(fact)
    return fact


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


# ---------- 따로 둔 구역 (canon/serialize.py, canon/reshape.py, canon/opening.py) ----------
# 각 모듈은 위의 도우미를 pipeline 에서 불러 쓰므로 맨 끝에서 부른다. 모듈이 정한 이름은 pipeline 에도 둔다
SPLIT = ("serialize", "reshape", "opening",)


def _attach_split() -> None:
    import importlib
    import sys

    for mod in SPLIT:
        full = f"{__package__}.{mod}"
        m = importlib.reload(sys.modules[full]) if full in sys.modules else importlib.import_module(full)
        globals().update({k: getattr(m, k) for k in m.EXPORTS})


_attach_split()
