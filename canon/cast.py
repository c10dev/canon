"""인물 화면: 화별 관계 프레임, 인물 등장과 타임라인. LLM 을 부르지 않는다.

관계 값은 dynamics 가 남긴 스냅샷(0 = 1화 시작 전, n = n화 반영 뒤)을 그대로 읽는다.
장편은 오래된 스냅샷을 지우므로(pipeline.prune_snapshots), 빈 화는 앞 스냅샷에서 사건 로그와
상태 변경 기록(history)을 이어 재생해 채운다. 남아 있는 스냅샷을 만나면 그 값으로 다시 맞춘다.
긴장도는 저장하지 않으므로 각 시점의 간선 · 비밀 · 관계 설정으로 다시 계산한다.

화면은 canon/static/cast.js. 말로 보기 문구는 dynamics 의 구간 표현을 그대로 쓴다.
"""
from __future__ import annotations

from typing import Iterator, Optional

from . import dynamics
from .schema import CharacterState, Project, Snapshot, StateDelta

STATE_FIELDS = ("emotional_state", "current_goal", "location", "attire")


def _sim(p: Project, snap: Snapshot) -> Project:
    """스냅샷 하나를 계산용 작품으로. 원본 스냅샷은 건드리지 않는다."""
    return Project(
        characters=p.characters,
        states=[s.model_copy(deep=True) for s in snap.states],
        relationships=[r.model_copy(deep=True) for r in snap.relationships],
        ties=[t.model_copy(deep=True) for t in snap.ties],
        secrets=[s.model_copy(deep=True) for s in snap.secrets],
        params=p.params,
    )


def _start(p: Project) -> Project:
    """1화 시작 전. 스냅샷 0 이 없으면(아직 반영 전) 설정 화면의 관계로 시작 간선을 만든다."""
    base = p.snapshot(0)
    if base is not None:
        return _sim(p, base)
    sim = Project(
        characters=p.characters,
        states=[s.model_copy(deep=True) for s in p.states],
        relationships=[r.model_copy(deep=True) for r in p.relationships],
        ties=[t.model_copy(deep=True) for t in p.ties],
        secrets=[s.model_copy(deep=True) for s in p.secrets],
        params=p.params,
    )
    dynamics.seed_ties(sim)
    dynamics.sync_relationships(sim)
    return sim


def _apply_gap(sim: Project, p: Project, n: int, delta: Optional[StateDelta]) -> None:
    """스냅샷이 지워진 화를 다시 계산한다. pipeline.apply_delta 의 인물 · 관계 · 비밀 부분과 같은 순서."""
    have = {s.character_id for s in sim.states}
    for c in p.characters:  # 이 화까지 등록된 인물은 빈 상태로 시작한다 (pipeline._init_states)
        if c.id not in have and 0 < c.first_ep <= n:
            sim.states.append(CharacterState(character_id=c.id, current_goal=c.goal))
    if delta:
        for upd in delta.character_updates:
            cur = next((s for s in sim.states if s.character_id == upd.character_id), None)
            if cur is None:
                sim.states.append(upd.model_copy(deep=True))
                continue
            for f in (*STATE_FIELDS, "notes"):
                if getattr(upd, f):
                    setattr(cur, f, getattr(upd, f))
            cur.knows += [k for k in upd.knows if k not in cur.knows]
        for upd in delta.relationship_updates:
            r = next((r for r in sim.relationships if {r.a, r.b} == {upd.a, upd.b}), None)
            if r is None:
                sim.relationships.append(upd.model_copy(deep=True))
                dynamics.seed_ties(sim)
            else:
                r.type, r.description = upd.type or r.type, upd.description or r.description
        have = {s.id for s in sim.secrets}
        sim.secrets += [s.model_copy(deep=True) for s in delta.secrets_added if s.id not in have]
    dynamics.run_episode(sim, n, [e for e in p.events if e.episode == n], p.episode(n).plot.characters)


def walk(p: Project) -> Iterator[tuple[int, Project]]:
    """(화, 그 화 반영 뒤 상태) 를 0 부터 반영이 끝난 화까지 차례로. 0 은 1화 시작 전."""
    sim = _start(p)
    yield 0, sim
    done = sorted(e.plot.number for e in p.episodes if e.status == "finalized")
    if not done:
        return
    for n in done:
        snap = p.snapshot(n)
        if snap is not None:
            sim = _sim(p, snap)
        else:
            sim = sim.model_copy(deep=True)
            _apply_gap(sim, p, n, next((d for d in p.history if d.episode == n), None))
        yield n, sim


def _r(v: float) -> float:
    return round(v, 3)


def frame(sim: Project, n: int) -> dict:
    """한 시점의 관계 그림. 간선(방향)과 쌍(긴장), 불안정한 삼각관계, 비밀, 인물 상태."""
    triads = dynamics.unbalanced_triads(sim.ties)
    ties = [{
        "source": t.source, "target": t.target, "stage": t.stage,
        "warmth": _r(t.warmth), "trust": _r(t.trust), "evidence": _r(t.evidence),
        "grievance": _r(t.grievance), "status": _r(t.status), "familiarity": _r(t.familiarity),
        "warmth_word": dynamics.warmth_word(t.warmth), "trust_word": dynamics.trust_word(t.trust),
    } for t in sorted(sim.ties, key=lambda t: (t.source, t.target))]
    pairs, seen = [], set()
    for r in sim.relationships:
        seen.add(frozenset((r.a, r.b)))
        v = dynamics.tension(sim, r.a, r.b, triads)
        pairs.append({"a": r.a, "b": r.b, "type": r.type, "description": r.description,
                      "goal_conflict": r.goal_conflict, "tension": _r(v), "tension_word": dynamics.tension_word(v)})
    for t in sim.ties:  # 사건으로만 생긴 쌍 (관계 설정이 없음)
        key = frozenset((t.source, t.target))
        if key not in seen:
            seen.add(key)
            v = dynamics.tension(sim, t.source, t.target, triads)
            pairs.append({"a": t.source, "b": t.target, "type": "", "description": "", "goal_conflict": 0.0,
                          "tension": _r(v), "tension_word": dynamics.tension_word(v)})
    return {
        "episode": n,
        "ties": ties,
        "pairs": pairs,
        "triads": [list(x) for x in triads],
        "secrets": [{"id": s.id, "owner": s.owner, "content": s.content, "hidden_from": list(s.hidden_from)} for s in sim.secrets],
        "states": [s.model_dump() for s in sim.states],
    }


def frames(p: Project) -> list[dict]:
    return [frame(sim, n) for n, sim in walk(p)]


def appearances(p: Project) -> dict[str, list[dict]]:
    """인물별 플롯 등장 화. 본문 전 화도 넣는다 (status 로 구분). pov 는 그 화의 시점 인물인지."""
    out: dict[str, list[dict]] = {}
    for e in sorted(p.episodes, key=lambda e: e.plot.number):
        for cid in dict.fromkeys(e.plot.characters + ([e.plot.pov] if e.plot.pov else [])):
            out.setdefault(cid, []).append({"n": e.plot.number, "status": e.status, "pov": e.plot.pov == cid})
    return out


def _changes(prev: Optional[CharacterState], cur: Optional[CharacterState]) -> dict:
    if cur is None:
        return {}
    out = {f: getattr(cur, f) for f in STATE_FIELDS if getattr(cur, f) and getattr(cur, f) != (getattr(prev, f) if prev else "")}
    known = set(prev.knows) if prev else set()
    learned = [k for k in cur.knows if k not in known]
    if learned:
        out["knows"] = learned
    return out


def timeline(p: Project, cid: str, frames_: Optional[list[dict]] = None) -> list[dict]:
    """반영이 끝난 화마다 이 인물에게 일어난 일: 상태 변화, 알게 된 것, 관계 사건, 생긴 비밀, 첫 등장."""
    fs = frames_ if frames_ is not None else frames(p)
    states = {f["episode"]: next((CharacterState(**s) for s in f["states"] if s["character_id"] == cid), None) for f in fs}
    order = [f["episode"] for f in fs]
    out = []
    for i, n in enumerate(order):
        if n == 0:
            continue
        e = p.episode(n)
        delta = next((d for d in p.history if d.episode == n), None)
        events = [ev.model_dump() for ev in p.events if ev.episode == n and cid in (ev.actor, ev.target, *ev.witnesses)]
        secrets = [s.content for s in (delta.secrets_added if delta else []) if s.owner == cid]
        new = bool(delta and any(c.id == cid for c in delta.new_characters))
        row = {
            "n": n, "title": e.plot.title, "appears": cid in e.plot.characters, "pov": e.plot.pov == cid,
            "changes": _changes(states.get(order[i - 1]), states.get(n)), "events": events, "secrets": secrets, "new": new,
        }
        if row["appears"] or row["changes"] or events or secrets or new:
            out.append(row)
    return out


def summary(p: Project) -> dict:
    """인물 화면 한 번에 필요한 계산값. 인물 설정 · 플롯 · 사건 원본은 화면이 작품에서 직접 읽는다."""
    fs = frames(p)
    ids = [c.id for c in p.characters]
    return {
        "frames": fs,
        "appearances": appearances(p),
        "timelines": {cid: timeline(p, cid, fs) for cid in ids},
    }


def describe(p: Project, cid: str, numbers: bool = False) -> str:
    """명령줄 `cast <작품> <인물>`: 설정 한 줄, 등장, 지금 관계, 화별 타임라인."""
    c = next((c for c in p.characters if cid in (c.id, c.name)), None)
    if c is None:
        raise KeyError(f"인물을 찾지 못했어요: {cid}")
    name = {x.id: x.name for x in p.characters}
    nm = lambda x: name.get(x, x)  # noqa: E731
    fs = frames(p)
    last = fs[-1]
    apps = appearances(p).get(c.id, [])
    lines = [f"{c.name} ({c.id}) · {c.role} · {dict(main='주역', support='조연', minor='단역')[c.tier]}"]
    for label, v in (("성격", c.personality), ("목표", c.goal), ("결핍", c.wound), ("말투", c.speech_style), ("아크", c.arc)):
        if v:
            lines.append(f"  {label}: {v}")
    pov = [a["n"] for a in apps if a["pov"]]
    lines.append(f"등장 {len(apps)}화 ({apps[0]['n']}~{apps[-1]['n']}화)" + (f" · 시점 {len(pov)}화" if pov else "") if apps else "플롯에 나오는 화가 아직 없어요")
    st = next((s for s in last["states"] if s["character_id"] == c.id), None)
    where = f"{last['episode']}화 반영 뒤" if last["episode"] else "1화 시작 전"
    if st:
        lines.append(f"\n지금 상태 ({where})")
        for f, label in (("emotional_state", "감정"), ("current_goal", "목표"), ("location", "위치"), ("attire", "차림")):
            if st[f]:
                lines.append(f"  {label}: {st[f]}")
        if st["knows"]:
            lines.append(f"  아는 것: {', '.join(st['knows'])}")
    rel = [t for t in last["ties"] if c.id in (t["source"], t["target"])]
    if rel:
        lines.append(f"\n관계 ({where})")
        for t in sorted(rel, key=lambda t: (t["target"] if t["source"] == c.id else t["source"], t["source"] != c.id)):
            head = f"  {nm(t['source'])} → {nm(t['target'])}: "
            if numbers:
                lines.append(head + f"온기 {t['warmth']:+.2f} 신뢰 {t['trust']:.2f} 원한 {t['grievance']:.2f} 친숙 {t['familiarity']:.2f} 단계 {t['stage']}")
            else:
                lines.append(head + f"{t['warmth_word']}, {t['trust_word']} (단계 {t['stage']})")
    tl = timeline(p, c.id, fs)
    if tl:
        lines.append("\n화별")
    labels = {"emotional_state": "감정", "current_goal": "목표", "location": "위치", "attire": "차림"}
    for row in tl:
        bits = [f"{labels[k]} {v}" for k, v in row["changes"].items() if k in labels]
        if row["changes"].get("knows"):
            bits.append("알게 됨 " + ", ".join(row["changes"]["knows"]))
        bits += [f"{nm(ev['actor'])}→{nm(ev['target'])} {ev['kind']}" for ev in row["events"]]
        bits += [f"비밀 생김 {s}" for s in row["secrets"]]
        mark = ("첫 등장 " if row["new"] else "") + ("시점 " if row["pov"] else "")
        lines.append(f"  {row['n']:>3}화 {mark}{' · '.join(bits) or ('등장' if row['appears'] else '')}")
    return "\n".join(lines)
