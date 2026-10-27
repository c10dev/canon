"""스킬 · 특성 도감: 상태창 목록 항목(스킬 · 특성 · 칭호)의 조각마다 설명 · 효과 · 대가 · 등급별 효과를 둔다.

정의(Project.abilities)는 인물 사이에 하나다. 누가 어느 등급을 가졌는지는 상태창 값(CharacterState.stats)의 조각에서,
얻은 화는 상태창 기록(Project.stat_log)에서 계산한다. 그래서 되돌리기 · 갈래가 따로 맞출 값이 없다.
조각과 도감은 등급 꼬리(Lv3, (B급), 3성)를 뗀 이름으로 잇는다 (statwin._key). LLM 을 부르지 않는다.
"""
from __future__ import annotations

import re

from . import statwin
from .schema import Ability, Project

_TAIL = statwin._GRADE
# 이름만 봐도 목록인 상태창 항목. 인벤토리(statwin.INVENTORY)는 물건이라 도감 항목이 가리킬 때만 잇는다
LIST_NAMES = ("스킬", "특성", "칭호", "능력", "특기", "기술", "무공", "절기", "마법", "축복", "권능", "재능")


def split(item: str) -> tuple[str, str]:
    """조각 → (이름, 등급 꼬리). '화염구 Lv4' → ('화염구', 'Lv4'), '롱소드 +2 (A급)' → ('롱소드', '+2 (A급)')."""
    base, tail = item.strip(), ""
    while True:
        m = _TAIL.search(base)
        if not m or not base[:m.start()].strip():
            return base, tail.strip()
        tail = (base[m.start():].strip() + " " + tail).strip()
        base = base[:m.start()].strip()


def key(name: str) -> str:
    return re.sub(r"\s+", "", split(name)[0]).casefold()


def terms(a: Ability) -> list[str]:
    return [x for x in [a.name, *a.aliases] if x.strip()]


def _keys(a: Ability) -> set[str]:
    return {key(x) for x in terms(a)}


def find(p: Project, item: str, stat: str = "") -> Ability | None:
    """상태창 조각에 이어진 도감 항목. 도감 항목의 stat 이 정해져 있으면 그 상태창 항목의 조각만."""
    k = key(item)
    return next((a for a in p.abilities if k in _keys(a) and (not a.stat or not stat or a.stat == stat)), None)


def grade_effect(a: Ability, grade: str) -> str:
    g = re.sub(r"\s+", "", grade).casefold()
    return next((x.effect for x in a.grades if g and re.sub(r"\s+", "", x.grade).casefold() == g), "")


def list_stats(p: Project) -> set[str]:
    """도감과 잇는 상태창 항목 이름: 이름이 스킬 · 특성 · 칭호 같은 것이거나, 어느 인물이든 값에 조각이 둘 이상이거나,
    도감 항목이 가리키는 항목. 인벤토리는 도감 항목이 가리킬 때만."""
    out = {a.stat for a in p.abilities if a.stat}
    for st in p.states:
        for s in st.stats:
            if any(w in s.name for w in statwin.INVENTORY):
                continue
            if any(w in s.name for w in LIST_NAMES) or (not statwin._amount(s.value) and len(statwin.items(s.value)) > 1):
                out.add(s.name)
    return out


def _pieces(p: Project, value: str) -> list[str]:
    return [] if statwin._amount(value) else statwin.items(value)


def owners(p: Project, a: Ability) -> list[dict]:
    """지금 이 항목을 가진 인물: [{character_id, stat, item, grade}]."""
    out = []
    lists = list_stats(p)
    for st in p.states:
        for s in st.stats:
            if s.name not in lists or (a.stat and s.name != a.stat):
                continue
            for x in _pieces(p, s.value):
                if key(x) in _keys(a):
                    out.append({"character_id": st.character_id, "stat": s.name, "item": x, "grade": split(x)[1]})
    return out


def history(p: Project, cid: str, a: Ability) -> list[dict]:
    """인물 하나가 이 항목을 얻고 · 등급이 바뀌고 · 잃은 화. [{episode, kind: 얻음 | 바뀜 | 잃음, item, before}].
    상태창 기록을 차례로 읽는다. 1화 전에 정한 값은 0화(시작)다."""
    ks = _keys(a)
    have: dict[str, str] = {}  # 상태창 항목 → 지금 가진 조각
    out = []
    for r in (x for x in p.stat_log if x.character_id == cid and (not a.stat or x.name == a.stat)):
        now = next((x for x in _pieces(p, r.value) if key(x) in ks), "")
        was = have.get(r.name, "")
        if now and not was:
            out.append({"episode": r.episode, "kind": "얻음", "item": now, "before": ""})
        elif was and not now:
            out.append({"episode": r.episode, "kind": "잃음", "item": "", "before": was})
        elif now != was:
            out.append({"episode": r.episode, "kind": "바뀜", "item": now, "before": was})
        have[r.name] = now
    return out


def acquired(p: Project, cid: str, a: Ability) -> int | None:
    """지금 가진 것을 얻은 화 (마지막으로 얻은 화). 기록이 없으면 None."""
    got = [h["episode"] for h in history(p, cid, a) if h["kind"] == "얻음"]
    return got[-1] if got else None


def unlinked(p: Project) -> list[dict]:
    """도감에 없는 상태창 조각: [{name, stat, items, characters}]. 같은 이름(등급 꼬리 뗌)은 하나로 묶는다."""
    lists = list_stats(p)
    seen: dict[tuple[str, str], dict] = {}
    for st in p.states:
        for s in st.stats:
            if s.name not in lists:
                continue
            for x in _pieces(p, s.value):
                if find(p, x, s.name):
                    continue
                row = seen.setdefault((s.name, key(x)), {"name": split(x)[0], "stat": s.name, "items": [], "characters": []})
                if x not in row["items"]:
                    row["items"].append(x)
                if st.character_id not in row["characters"]:
                    row["characters"].append(st.character_id)
    return list(seen.values())


def catalog(p: Project) -> dict:
    """도감 화면: 항목마다 가진 인물(등급 · 등급 효과 · 얻은 화)과, 도감에 없는 조각."""
    rows = []
    for a in p.abilities:
        own = [{**o, "grade_effect": grade_effect(a, o["grade"]), "acquired": acquired(p, o["character_id"], a)} for o in owners(p, a)]
        rows.append({"ability": a.model_dump(), "owners": own})
    return {"abilities": rows, "unlinked": unlinked(p), "lists": sorted(list_stats(p))}


def lookup(p: Project, item: str, cid: str = "", stat: str = "") -> dict:
    """칩 카드: 상태창 조각 하나의 도감 항목과, 그 인물의 등급 효과 · 얻은 화 · 바뀐 기록."""
    base, grade = split(item)
    a = find(p, item, stat)
    if a is None:
        return {"item": item, "name": base, "grade": grade, "stat": stat, "ability": None}
    return {"item": item, "name": base, "grade": grade, "stat": stat, "ability": a.model_dump(),
            "grade_effect": grade_effect(a, grade), "acquired": acquired(p, cid, a) if cid else None,
            "history": history(p, cid, a) if cid else []}


def new_id(p: Project) -> str:
    have = {a.id for a in p.abilities}
    n = len(p.abilities) + 1
    while f"ab-{n:02d}" in have:
        n += 1
    return f"ab-{n:02d}"


def upsert(p: Project, a: Ability) -> Ability:
    """작가가 도감 항목을 만들거나 고친다. 이름이 비었거나, 다른 항목과 이름 · 다른 이름이 겹치면 막는다."""
    a = a.model_copy(update={
        "name": split(a.name)[0], "stat": a.stat.strip(), "description": a.description.strip(), "effect": a.effect.strip(),
        "cost": a.cost.strip(), "aliases": list(dict.fromkeys(x.strip() for x in a.aliases if x.strip() and key(x) != key(a.name))),
        "grades": [g.model_copy(update={"grade": g.grade.strip(), "effect": g.effect.strip()}) for g in a.grades if g.grade.strip()]})
    if not a.name:
        raise ValueError("이름을 적어 주세요")
    old = next((x for x in p.abilities if x.id == a.id), None) if a.id else None
    for other in p.abilities:
        if other is old:
            continue
        both = _keys(other) & _keys(a)
        if both and (not other.stat or not a.stat or other.stat == a.stat):
            raise ValueError(f"'{other.name}' 항목과 이름이 겹쳐요")
    if old is None:
        a.id = a.id or new_id(p)
        p.abilities.append(a)
    else:
        a.source, a.created_ep = old.source, old.created_ep
        p.abilities[p.abilities.index(old)] = a
    return a


def remove(p: Project, aid: str) -> None:
    a = next((x for x in p.abilities if x.id == aid), None)
    if a is None:
        raise KeyError(f"도감 항목이 없어요: {aid}")
    p.abilities.remove(a)


def describe(p: Project) -> str:
    """명령줄 출력: 도감 항목과 가진 인물, 도감에 없는 조각."""
    name = {c.id: c.name or c.id for c in p.characters}
    out = []
    for a in p.abilities:
        head = f"{a.name}" + (f" ({', '.join(a.aliases)})" if a.aliases else "") + (f" · {a.stat}" if a.stat else "")
        out.append(head)
        for label, v in (("설명", a.description), ("효과", a.effect), ("대가", a.cost)):
            if v:
                out.append(f"  {label}: {v}")
        for g in a.grades:
            out.append(f"  {g.grade}: {g.effect}")
        for o in owners(p, a):
            ep = acquired(p, o["character_id"], a)
            out.append(f"  - {name.get(o['character_id'], o['character_id'])}: {o['item']}" + (f" ({'시작 때' if ep == 0 else f'{ep}화에'} 얻음)" if ep is not None else ""))
    miss = unlinked(p)
    if miss:
        out.append("")
        out.append("도감에 없는 항목: " + ", ".join(f"{m['name']}({m['stat']})" for m in miss))
    return "\n".join(out) if out else "도감이 비어 있어요. 상태창에 스킬 · 특성 목록을 만들고 항목을 더하세요."
