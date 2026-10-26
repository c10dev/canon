"""설정 도우미 대화: 작가가 말로 로그라인 · 주제 · 톤 · 세계관 · 인물 · 관계를 다듬는다 (대화 주제 'setup').

AI 는 바뀌는 칸만 담은 SetupRevision 이나 방향 여러 안을 낸다(pipeline.revise_setup). 여기서는 LLM 없이
변경안을 정리하고(clean), 작가가 고른 부분만 적용하고(apply), 그 변경안 단위로 적용을 취소한다(undo).
부분 id 는 기본 정보 · 세계관 칸이면 칸 이름('theme', 'world.rules'), 인물 칸이면 'c:<id>:<칸>',
새 인물이면 'new:<id>', 관계면 'r:<a>:<b>' 다. 화면(static/setupchat.js)도 같은 id 를 쓴다.

설계 원칙: AI 는 칸을 지우지 않고 인물 · 관계도 지우지 않는다. 1화 반영 뒤에는 관계의 시작 방식(a_view · b_view)과
수치를 바꾸지 않는다(지금 관계는 본문 사건이 만든 Tie 가 가진다). 1화 반영 뒤에 바꾼 인물 칸은 작가가 고른 것이라
인물 설정 변경 기록(charlog)에 작가 기록으로 남긴다.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import archetypes, charlog, dynamics, logline
from .schema import (
    Character,
    CharacterEdit,
    ChatMessage,
    Project,
    Relationship,
    SetupBefore,
    SetupEdit,
    SetupRevision,
)

TOPIC = "setup"

# 칸 순서와 이름 (화면 static/setupchat.js 의 SETUP_KEYS 와 같다)
KEY_LABELS: dict[str, str] = {
    "title": "제목", "logline.who": "로그라인 · 누가", "logline.why": "로그라인 · 무엇 때문에", "logline.goal": "로그라인 · 무엇을 하려 하나",
    "logline.block": "로그라인 · 무엇이 막나", "logline.stake": "로그라인 · 무엇이 걸렸나", "theme": "주제", "tone": "톤", "notes": "메모",
    "world.setting": "배경", "world.era": "시대", "world.rules": "깨면 안 되는 규칙", "world.locations": "장소", "world.name_rules": "이름 규칙",
}
LIST_KEYS = ("world.rules", "world.locations", "world.name_rules")
CHAR_LABELS: dict[str, str] = {
    "name": "이름", "role": "역할", "age": "나이", "gender": "성별", "goal": "원하는 것", "wound": "두려운 것 · 약점", "secrets": "숨기는 것",
    "speech_style": "말투", "personality": "성격", "background": "배경", "appearance": "외모", "arc": "아크",
}
REL_FIELDS = ("type", "description", "goal_conflict", "a_view", "b_view")


def started(p: Project) -> bool:
    """첫 상태 반영을 했는지. 그 뒤로는 관계가 본문 사건으로 계산된다 (web.put_project 와 같은 기준)."""
    return p.snapshot(0) is not None


# ---------- 칸 읽고 쓰기 ----------

def key_value(o, key: str):
    """o 는 Project 나 SetupBefore (meta, world 가 있는 것)."""
    if key.startswith("logline."):
        return getattr(o.meta.logline_parts, key[8:])
    if key.startswith("world."):
        return getattr(o.world, key[6:])
    return getattr(o.meta, key)


def _set_key(p: Project, key: str, value) -> None:
    value = list(value) if isinstance(value, list) else value
    if key.startswith("logline."):
        setattr(p.meta.logline_parts, key[8:], value)
    elif key.startswith("world."):
        setattr(p.world, key[6:], value)
    else:
        setattr(p.meta, key, value)


def edit_value(e: SetupEdit):
    return e.items if e.key in LIST_KEYS else e.text


def char_value(x: CharacterEdit):
    return x.items if x.field == "secrets" else x.text


def char_id(x: CharacterEdit) -> str:
    return f"c:{x.id}:{x.field}"


def rel_id(r: Relationship) -> str:
    return f"r:{r.a}:{r.b}"


def part_ids(rev: SetupRevision) -> list[str]:
    """변경안의 부분 id 를 화면에 보이는 순서로."""
    return ([e.key for e in rev.edits] + [char_id(x) for x in rev.characters]
            + [f"new:{c.id}" for c in rev.new_characters] + [rel_id(r) for r in rev.relationships])


def label(p: Project, rev: SetupRevision, pid: str) -> str:
    """부분 id 를 사람이 읽는 이름으로 (명령줄 · 알림 · 대화 기록)."""
    names = {c.id: c.name or c.id for c in [*p.characters, *rev.new_characters]}
    if pid in KEY_LABELS:
        return KEY_LABELS[pid]
    kind, _, rest = pid.partition(":")
    if kind == "c":
        cid, _, field = rest.rpartition(":")
        return f"{names.get(cid, cid)} {CHAR_LABELS.get(field, field)}"
    if kind == "new":
        return f"새 인물 {names.get(rest, rest)}"
    if kind == "r":
        a, _, b = rest.partition(":")
        return f"관계 {names.get(a, a)} ↔ {names.get(b, b)}"
    return pid


def _char(p, cid: str) -> Character | None:
    return next((c for c in p.characters if c.id == cid), None)


def _pair(rels: list[Relationship], a: str, b: str) -> Relationship | None:
    return next((r for r in rels if {r.a, r.b} == {a, b}), None)


def _same_rel(r: Relationship, x: Relationship) -> bool:
    return all(getattr(r, f) == getattr(x, f) for f in REL_FIELDS)


def _norm(items: list[str]) -> list[str]:
    out: list[str] = []
    for x in items:
        x = x.strip()
        if x and x not in out:
            out.append(x)
    return out


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "", s.strip().lower())
    return s or "char"


# ---------- 정리 ----------

def clean(p: Project, rev: SetupRevision, mode: str = "") -> SetupRevision:
    """지금 값과 같은 칸, 빈 값, 없는 인물, 겹치는 관계를 뺀다. 방향 여러 안을 청했으면 안만 남긴다.
    뺀 이유는 답 끝에 붙인다."""
    if mode == "options":
        rev.options = [o for o in rev.options if o.title.strip()][:4]
        rev.edits, rev.characters, rev.new_characters, rev.relationships = [], [], [], []
        return rev
    rev.options = []
    notes: list[str] = []

    keep: dict[str, SetupEdit] = {}
    for e in rev.edits:
        e.why = e.why.strip()
        if e.key in LIST_KEYS:
            e.items, e.text = _norm(e.items), ""
        else:
            e.text, e.items = e.text.strip(), []
        value = edit_value(e)
        if not value or value == key_value(p, e.key):  # AI 는 칸을 비우지 않는다
            keep.pop(e.key, None)
            continue
        keep[e.key] = e
    rev.edits = [keep[k] for k in KEY_LABELS if k in keep]

    chars = {c.id: c for c in p.characters}
    ck: dict[tuple[str, str], CharacterEdit] = {}
    missing: list[str] = []
    for x in rev.characters:
        x.id, x.why = x.id.strip(), x.why.strip()
        c = chars.get(x.id)
        if c is None:
            if x.id not in missing and x.id not in {n.id for n in rev.new_characters}:
                missing.append(x.id)
            continue
        if x.field == "secrets":
            x.items, x.text = _norm(x.items), ""
        else:
            x.text, x.items = x.text.strip(), []
        value = char_value(x)
        if not value or value == getattr(c, x.field):
            ck.pop((x.id, x.field), None)
            continue
        ck[(x.id, x.field)] = x
    order = {cid: i for i, cid in enumerate(chars)}
    fields = list(CHAR_LABELS)
    rev.characters = sorted(ck.values(), key=lambda x: (order[x.id], fields.index(x.field)))
    if missing:
        notes.append(f"설정에 없는 인물({', '.join(missing)})의 칸 변경은 뺐어요")

    taken = set(chars)
    remap: dict[str, str] = {}
    new: list[Character] = []
    for c in rev.new_characters:
        name = c.name.strip()
        if not name:
            continue
        same = next((x for x in p.characters if x.name.strip() == name), None)
        if same is not None:
            remap[c.id] = same.id
            notes.append(f"새 인물 {name}은(는) 이미 있는 인물이라 뺐어요")
            continue
        cid = _slug(c.id)
        if cid in taken:
            k = 2
            while f"{cid}{k}" in taken:
                k += 1
            cid = f"{cid}{k}"
        remap[c.id] = cid
        taken.add(cid)
        new.append(c.model_copy(update={"id": cid, "name": name, "narration_voice": "", "first_ep": 0}))
    rev.new_characters = new

    ids = set(chars) | {c.id for c in new}
    begun = started(p)
    rk: dict[frozenset, Relationship] = {}
    dropped = 0
    for r in rev.relationships:
        a, b = remap.get(r.a.strip(), r.a.strip()), remap.get(r.b.strip(), r.b.strip())
        if a not in ids or b not in ids or a == b:
            dropped += 1
            continue
        av = [w for w in _norm(r.a_view) if w in dynamics.VIEWS][:2]
        bv = [w for w in _norm(r.b_view) if w in dynamics.VIEWS][:2]
        old = _pair(p.relationships, a, b)
        if old is not None and old.a != a:  # 지금 관계와 같은 방향으로 맞춘다
            a, b, av, bv = b, a, bv, av
        upd = {"a": a, "b": b, "type": r.type.strip(), "description": r.description.strip(), "a_view": av, "b_view": bv}
        if old is not None:  # 수치는 보는 방식이나 본문 사건이 정한다
            upd.update(affinity=old.affinity, tension=old.tension)
            upd["type"] = upd["type"] or old.type
        if begun:  # 첫 반영 뒤에는 시작 관계를 바꾸지 않는다
            upd.update(a_view=old.a_view if old else [], b_view=old.b_view if old else [])
        x = r.model_copy(update=upd)
        if not x.type or (old is not None and _same_rel(old, x)):
            continue
        rk[frozenset((a, b))] = x
    rev.relationships = list(rk.values())
    if dropped:
        notes.append(f"없는 인물과의 관계나 같은 인물끼리의 관계 {dropped}개는 뺐어요")

    if notes:
        rev.reply = rev.reply.rstrip() + "\n\n※ " + " ".join(notes)
    return rev


# ---------- 기록 · 적용 · 적용 취소 ----------

def record(p: Project, message: str, mode: str, rev: SetupRevision) -> ChatMessage:
    """작가의 말과 AI 답을 설정 대화에 남긴다."""
    from .pipeline import CHAT_KEEP

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    chat = p.chat(TOPIC)
    keep = rev.has_changes() or bool(rev.options)
    reply = ChatMessage(role="assistant", text=rev.reply, setup=rev if keep else None, mode=mode, at=now)
    asked = ChatMessage(role="user", text=message.strip(), mode=mode, at=now)
    chat.messages += [asked, reply]
    chat.messages = chat.messages[-CHAT_KEEP:]
    return reply


def message(p: Project, i: int) -> ChatMessage:
    msgs = p.chat(TOPIC).messages
    if not 0 <= i < len(msgs) or msgs[i].setup is None or msgs[i].setup.options:
        raise KeyError("설정 변경안이 있는 메시지가 아니에요")
    return msgs[i]


def _recompose(p: Project, parts_before, logline_before: str) -> None:
    """로그라인 칸을 바꿨으면 한 문장도 다시 합친다. 작가가 직접 고친 문장(칸을 합친 것과 다름)과 칸 없이 문장만 있던
    옛 작품의 문장은 덮지 않는다 (화면 updateLogline 과 같은 규칙. 화면에 '칸 내용으로 다시 만들기'가 뜬다)."""
    if not logline_before.strip() or logline_before == logline.compose(parts_before):
        p.meta.logline = logline.compose(p.meta.logline_parts)


def _reseed(p: Project) -> None:
    """첫 반영 전에는 설정의 관계가 시작 관계다 (web.put_project 와 같다)."""
    if not started(p):
        p.ties = []
        dynamics.seed_ties(p)


def _before(p: Project) -> SetupBefore:
    return SetupBefore(meta=p.meta.model_copy(deep=True), world=p.world.model_copy(deep=True),
                       characters=[c.model_copy(deep=True) for c in p.characters],
                       relationships=[r.model_copy(deep=True) for r in p.relationships])


def apply(p: Project, i: int, parts: list[str]) -> list[str]:
    """i 번째 메시지의 변경안에서 고른 부분만 설정에 넣는다. 적용하기 전 설정을 메시지에 남긴다. 넣은 부분 id 를 돌려준다."""
    from .pipeline import _init_states, validate_relationships

    m = message(p, i)
    if m.outcome:
        raise ValueError("이미 처리한 변경안이에요")
    rev = m.setup
    want = set(parts)
    picked = [x for x in part_ids(rev) if x in want]
    if not picked:
        raise ValueError("적용할 칸을 고르세요")
    have = {c.id for c in p.characters} | {c.id for c in rev.new_characters if f"new:{c.id}" in want}
    for r in rev.relationships:
        if rel_id(r) in want and not {r.a, r.b} <= have:
            raise ValueError(f"{label(p, rev, rel_id(r))}은(는) 고르지 않은 새 인물과 이어져 있어요. 그 인물도 함께 고르세요")
    before = _before(p)
    old = p.model_copy(update={"characters": before.characters})  # 인물 설정 변경 기록용

    for e in rev.edits:
        if e.key in want:
            _set_key(p, e.key, edit_value(e))
    if any(e.key in want and e.key.startswith("logline.") for e in rev.edits):
        _recompose(p, before.meta.logline_parts, before.meta.logline)
    for x in rev.characters:
        c = _char(p, x.id)
        if char_id(x) in want and c is not None:
            setattr(c, x.field, list(x.items) if x.field == "secrets" else x.text)
    for c in rev.new_characters:
        if f"new:{c.id}" in want and _char(p, c.id) is None:
            p.characters.append(c.model_copy(deep=True))
    for r in rev.relationships:
        if rel_id(r) not in want:
            continue
        cur = _pair(p.relationships, r.a, r.b)
        if cur is None:
            p.relationships.append(r.model_copy(deep=True))
        else:
            for f in REL_FIELDS:
                v = getattr(r, f)
                setattr(cur, f, list(v) if isinstance(v, list) else v)
    validate_relationships(p)
    _init_states(p)
    _reseed(p)
    charlog.record_author(old, p)
    m.setup_before, m.applied, m.outcome = before, picked, "applied"
    return picked


def _used(p: Project, cid: str) -> bool:
    """새 인물을 적용 취소로 지워도 되는지: 관계 · 플롯 · 관계 사건 · 스냅샷 어디에도 없어야 한다."""
    return (any(cid in (r.a, r.b) for r in p.relationships)
            or any(cid in e.plot.characters for e in p.episodes)
            or any(cid in (ev.actor, ev.target) for ev in p.events)
            or any(s.character_id == cid for snap in p.snapshots for s in snap.states))


def undo(p: Project, i: int) -> tuple[list[str], list[str]]:
    """적용한 변경안을 취소한다. 그 뒤에 다시 고친 부분과 이미 쓰이는 새 인물은 그대로 둔다.
    (되돌린 부분, 그대로 둔 부분) 을 돌려준다. 변경안은 다시 고를 수 있게 연다."""
    m = message(p, i)
    if m.outcome != "applied" or m.setup_before is None:
        raise ValueError("적용한 변경안이 아니에요")
    rev, before, applied = m.setup, m.setup_before, set(m.applied)
    old = p.model_copy(update={"characters": [c.model_copy(deep=True) for c in p.characters]})
    done: list[str] = []
    kept: list[str] = []

    parts_now, logline_now = p.meta.logline_parts.model_copy(), p.meta.logline
    for e in rev.edits:
        if e.key not in applied:
            continue
        if key_value(p, e.key) == edit_value(e):
            _set_key(p, e.key, key_value(before, e.key))
            done.append(e.key)
        else:
            kept.append(e.key)
    if any(k.startswith("logline.") for k in done) and logline_now == logline.compose(parts_now):
        same = p.meta.logline_parts == before.meta.logline_parts
        p.meta.logline = before.meta.logline if same else logline.compose(p.meta.logline_parts)

    for r in rev.relationships:  # 새 인물보다 먼저: 이 변경안이 더한 관계가 빠져야 인물을 지울 수 있다
        pid = rel_id(r)
        if pid not in applied:
            continue
        cur = _pair(p.relationships, r.a, r.b)
        prev = _pair(before.relationships, r.a, r.b)
        if cur is None:
            done.append(pid)
        elif not _same_rel(cur, r):
            kept.append(pid)
        elif prev is None:
            p.relationships.remove(cur)
            done.append(pid)
        else:
            for f in REL_FIELDS:
                v = getattr(prev, f)
                setattr(cur, f, list(v) if isinstance(v, list) else v)
            done.append(pid)

    for x in rev.characters:
        pid = char_id(x)
        if pid not in applied:
            continue
        c, prev = _char(p, x.id), _char(before, x.id)
        if c is not None and prev is not None and getattr(c, x.field) == char_value(x):
            v = getattr(prev, x.field)
            setattr(c, x.field, list(v) if isinstance(v, list) else v)
            done.append(pid)
        else:
            kept.append(pid)

    for c in rev.new_characters:
        pid = f"new:{c.id}"
        if pid not in applied:
            continue
        cur = _char(p, c.id)
        if cur is None:
            done.append(pid)
        elif cur != c or _used(p, c.id):
            kept.append(pid)
        else:
            p.characters.remove(cur)
            p.states = [s for s in p.states if s.character_id != c.id]
            p.ties = [t for t in p.ties if c.id not in (t.source, t.target)]
            done.append(pid)

    _reseed(p)
    archetypes.prune(p)  # 지운 새 인물에 골라 둔 원형
    charlog.record_author(old, p)
    m.outcome, m.applied, m.setup_before = "", [], None
    order = part_ids(rev)
    return sorted(done, key=order.index), sorted(kept, key=order.index)
