"""상태창: 게임 판타지 · 헌터물처럼 본문에 레벨, 능력치, 스킬이 숫자로 나오는 작품에서 인물별 수치를 화마다 기록한다.

작가가 인물의 상태창 항목(CharacterState.stats)을 정하면 켜진다. 켜지면 쓰기 · 상태 정리 프롬프트에 규칙 한 줄이 붙고,
AI 는 상태 변경안에 바뀐 항목만 적는다(+3 처럼 바뀐 양만 적으면 Canon 이 계산). 반영은 승인 후.
바뀐 기록(Project.stat_log)으로 화별 비교를 그린다. LLM 을 부르지 않는다.
"""
from __future__ import annotations

import re

from . import dynamics
from .schema import CharacterState, Project, StatRecord, StatValue

PRESETS: dict[str, list[str]] = {
    "game": ["레벨", "HP", "MP", "힘", "민첩", "체력", "지능", "스킬"],
    "hunter": ["등급", "레벨", "마력", "스킬", "칭호"],
    "simple": ["레벨", "스킬"],
    "growth": ["레벨", "스킬", "특성", "칭호", "골드", "인벤토리"],
}

SOURCE = {"ai": "", "author": " (작가)", "both": " (승인 뒤 작가가 고침)"}
# 단위가 붙은 수치: 앞에 짧은 표지(₩, Lv.), 뒤에 단위(골드, 원, G). 숫자 사이 쉼표는 자릿수
_AMOUNT = re.compile(r"^([^\d\s,+-]{0,4})(\s?)(-?\d[\d,]*(?:\.\d+)?)(\s?)([^\d\s,]{0,6})$")
_DELTA = re.compile(r"^([+-])\s?([^\d\s,+-]{0,4})\s?(\d[\d,]*(?:\.\d+)?)\s?([^\d\s,]{0,6})$")
# 목록 항목(스킬, 특성, 칭호, 인벤토리)을 나누는 표시
_SPLIT = re.compile(r"\s*(?:,|、| · )\s*")
# 같은 것으로 보는 꼬리: 화염구 Lv3 · 화염구(B급) · 롱소드 +2 · 검술 3단계
_GRADE = re.compile(r"\s*(?:\([^()]*\)|\[[^\[\]]*\]|lv\.?\s*\d+|\+\d+|\d+\s*(?:레벨|단계|성|강|개))$", re.I)
# 상태창 인벤토리 항목 이름. 이 항목이 있는 인물은 가방에 든 물건을 지금 차림(attire)이 아니라 여기 적는다
INVENTORY = ("인벤토리", "소지품", "아이템", "가방", "보관함")


def enabled(p: Project) -> bool:
    return any(s.stats for s in p.states)


def _fmt(x: float, commas: bool = False) -> str:
    s = f"{x:,.2f}" if commas else f"{x:.2f}"
    s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _amount(text: str):
    """'1,200골드' → ('', '', 1200.0, '', '골드', True). 수치가 아니면 None."""
    m = _AMOUNT.match(text.strip())
    if not m:
        return None
    return m.group(1), m.group(2), float(m.group(3).replace(",", "")), m.group(4), m.group(5), "," in m.group(3)


def items(text: str) -> list[str]:
    """목록 항목 값을 나눈다. '화염구 Lv3, 은신' → ['화염구 Lv3', '은신']."""
    return [x for x in _SPLIT.split(text.strip()) if x]


def _key(item: str) -> str:
    k = item.strip()
    while True:
        k2 = _GRADE.sub("", k).strip()
        if k2 == k or not k2:
            return k.casefold()
        k = k2


def _ops(value: str) -> list[tuple[str, str]] | None:
    """'+독 내성, -은신' → [('+', '독 내성'), ('-', '은신')]. 모두 +이름 · -이름 이 아니면 None."""
    out = []
    for part in items(value):
        name = part[1:].strip()
        if part[:1] not in "+-" or not name or name[0].isdigit():
            return None
        out.append((part[0], name))
    return out or None


def _sep(before: str) -> str:
    m = _SPLIT.search(before)
    return {"、": "、", "·": " · "}.get(m.group(0).strip(), ", ") if m else ", "


def resolve(before: str, value: str) -> str:
    """AI 나 작가가 적은 값을 이전 값에 맞춰 새 값으로.

    - 수치: '+3', '-10' 은 이전 값이 수치일 때 더하고 뺀다. 단위와 자릿수 쉼표는 이전 값을 따른다('1,200골드' + '+300' → '1,500골드').
    - 목록(스킬 · 특성 · 칭호 · 인벤토리): '+독 내성' 은 붙이고 '-은신' 은 뺀다. '+화염구 Lv4' 처럼 이미 있는 것의 등급만 다르면 바꾼다.
    - 그 밖에는 적은 값 그대로.
    """
    v = value.strip()
    b = before.strip()
    d, a = _DELTA.match(v), _amount(b)
    if d and a and (not d.group(2) or d.group(2) == a[0]) and (not d.group(4) or d.group(4) == a[4]):
        x = a[2] + (1 if d.group(1) == "+" else -1) * float(d.group(3).replace(",", ""))
        return f"{a[0]}{a[1]}{_fmt(x, a[5])}{a[3]}{a[4]}"
    ops = _ops(v)
    if ops is None or a:
        return v
    cur = items(b)
    for op, name in ops:
        k = _key(name)
        at = next((i for i, x in enumerate(cur) if x == name), None)
        if at is None:
            at = next((i for i, x in enumerate(cur) if _key(x) == k), None)
        if op == "-":
            if at is not None:
                cur.pop(at)
        elif at is None:
            cur.append(name)
        else:
            cur[at] = name
    return _sep(b).join(cur)


def diff(before: str, after: str) -> dict[str, list[str]]:
    """목록 값이 바뀐 것: 더한 것과 뺀 것. 수치거나, 처음 정했거나, 둘 다 한 덩이면 빈 목록."""
    if _amount(before) or _amount(after):
        return {"added": [], "removed": []}
    b, a = items(before), items(after)
    if not b or (len(b) < 2 and len(a) < 2):  # 처음 정한 값은 '없음 → 값' 으로 충분하다
        return {"added": [], "removed": []}
    return {"added": [x for x in a if x not in b], "removed": [x for x in b if x not in a]}


def inventory(p: Project) -> bool:
    """상태창에 인벤토리(소지품 · 아이템 · 가방) 항목을 둔 인물이 있는지."""
    return any(any(w in s.name for w in INVENTORY) for st in p.states for s in st.stats)


def _state(p: Project, cid: str) -> CharacterState:
    s = p.state_of(cid)
    if s is None:
        s = CharacterState(character_id=cid)
        p.states.append(s)
    return s


def merge(p: Project, state: CharacterState, updates: list[StatValue], n: int, source: str = "ai") -> list[StatRecord]:
    """바뀐 항목만 반영하고 기록을 남긴다. 값이 빈 항목은 지운다."""
    out = []
    for u in updates:
        name = u.name.strip()
        if not name:
            continue
        cur = next((s for s in state.stats if s.name == name), None)
        before = cur.value if cur else ""
        if not u.value.strip():
            if cur is None:
                continue
            state.stats.remove(cur)
            new = ""
        else:
            new = resolve(before, u.value)
            if cur is not None and new == before:
                continue
            if cur is None:
                state.stats.append(StatValue(name=name, value=new))
            else:
                cur.value = new
        rec = StatRecord(episode=n, character_id=state.character_id, name=name, value=new, before=before, source=source)  # type: ignore[arg-type]
        p.stat_log.append(rec)
        out.append(rec)
    return out


def last_done(p: Project) -> int:
    return max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)


def set_stats(p: Project, cid: str, rows: list[StatValue]) -> list[StatRecord]:
    """작가가 상태창 전체를 고친다. 마지막으로 반영한 화(없으면 0)의 작가 기록으로 남기고, 그 화 스냅샷도 맞춘다."""
    if not any(c.id == cid for c in p.characters):
        raise KeyError(f"없는 인물이에요: {cid}")
    names = [r.name.strip() for r in rows if r.name.strip()]
    if len(names) != len(set(names)):
        raise ValueError("항목 이름이 겹쳐요")
    n = last_done(p)
    st = _state(p, cid)
    cur = {s.name: s.value for s in st.stats}
    keep = [StatValue(name=r.name.strip(), value=r.value.strip()) for r in rows if r.name.strip()]
    ups = [StatValue(name=k, value="") for k in cur if k not in names]
    ups += [r for r in keep if r.value or cur.get(r.name)]  # 값을 비운 항목은 지운 기록으로
    recs = merge(p, st, ups, n, "author")
    # 값을 비워 둔 새 항목도 틀로 남기고, 작가가 정한 순서를 따른다
    have = {s.name: s for s in st.stats}
    st.stats = [have.get(r.name) or StatValue(name=r.name, value="") for r in keep]
    if p.snapshot(n) is not None:
        dynamics.take_snapshot(p, n)
    return recs


def revert(p: Project, n: int) -> None:
    """pipeline.revert 뒤에 부른다. 상태는 스냅샷에서 돌아오고, 기록은 n화까지만 남긴다."""
    p.stat_log = [r for r in p.stat_log if r.episode <= n]


def timeline(p: Project, cid: str) -> dict:
    """화별 비교표: 기록이 있는 화마다 그 화가 끝났을 때의 값. 바뀐 칸은 changed."""
    recs = [r for r in p.stat_log if r.character_id == cid]
    st = p.state_of(cid)
    names: list[str] = []
    for r in recs:
        if r.name not in names:
            names.append(r.name)
    for s in (st.stats if st else []):
        if s.name not in names:
            names.append(s.name)
    eps = sorted({r.episode for r in recs})
    cur: dict[str, str] = {}
    cols = []
    for n in eps:
        changed = {}
        for r in (x for x in recs if x.episode == n):
            cur[r.name] = r.value
            prev = changed.get(r.name)  # 같은 화에 AI 반영 뒤 작가가 또 고쳤으면 처음 값과 둘 다 남긴다
            src = r.source if prev is None or prev["source"] == r.source else "both"
            changed[r.name] = {"before": prev["before"] if prev else r.before, "source": src}
        for name, ch in changed.items():
            ch.update({k: v for k, v in diff(ch["before"], cur[name]).items() if v})  # 목록 항목은 더한 것 · 뺀 것도
        cols.append({"episode": n, "values": dict(cur), "changed": changed})
    return {"names": names, "columns": cols, "current": [s.model_dump() for s in (st.stats if st else [])]}


def render(p: Project, cid: str, stats: list[StatValue] | None = None) -> str:
    """본문에 넣을 상태창 글. 값이 빈 항목은 뺀다."""
    c = next((x for x in p.characters if x.id == cid), None)
    st = p.state_of(cid)
    items = stats if stats is not None else (st.stats if st else [])
    w = p.stat_window
    rows = "\n".join(w.row.replace("{key}", s.name).replace("{value}", s.value) for s in items if s.value.strip())
    return w.template.replace("{name}", c.name if c else cid).replace("{rows}", rows).strip()


def write_rule(p: Project) -> str:
    """본문 쓰기 프롬프트 끝에 붙는 규칙. 상태창을 만든 인물이 없으면 빈 글."""
    if not enabled(p):
        return ""
    who = next((s.character_id for s in p.states if s.stats), "")
    return ("\n\n상태창: [인물 현재 상태]의 stats 가 지금 수치입니다. 본문에 상태창이나 수치를 보여 줄 때는 이 값을 그대로 쓰고, "
            "이번 화 사건으로 바뀌는 값만 바꿉니다. 이유 없이 수치를 올리거나 내리지 않습니다. "
            "스킬 · 특성 · 칭호처럼 늘어놓은 항목에 없는 것을 쓰려면 얻는 장면을 먼저 보여 줍니다."
            + (_INVENTORY_HAS if inventory(p) else "")
            + " 상태창은 아래 서식으로 씁니다.\n"
            + render(p, who))


def state_rule(p: Project) -> str:
    """상태 정리 요구사항에 붙는 한 줄. 상태창을 만든 인물이 없으면 빈 글."""
    if not enabled(p):
        return ""
    return ("\n- [이전 인물 상태]의 stats 는 상태창 수치입니다. 본문에서 바뀐 항목만 그 인물의 character_updates 항목 stats 에 넣습니다. "
            "value 는 새 값을 적거나, 바뀐 양만 알면 +3, -10 처럼 적습니다(골드 · 원처럼 단위가 붙은 값도 +300). "
            "스킬 · 특성 · 칭호 · 인벤토리처럼 쉼표로 늘어놓은 항목은 얻은 것을 +이름, 잃은 것을 -이름 으로만 적습니다(예: '+독 내성, -은신'). "
            "등급 · 레벨 · 개수가 바뀐 것은 '+화염구 Lv4', '+포션 2개' 처럼 새 값으로 적으면 바꿉니다. 사라진 항목은 value 를 비웁니다. "
            "본문 수치가 이전 값에서 설명 없이 튀거나 앞뒤가 맞지 않으면 warnings 에 적습니다."
            + (" 상태창에 인벤토리 항목이 있는 인물은 가방 · 인벤토리에 넣은 물건을 그 항목에만 적고, "
               "attire 에는 입고 있거나 손에 들고 몸에 찬 것만 적습니다." if inventory(p) else ""))


_INVENTORY_HAS = " stats 의 인벤토리에 든 물건은 attire 에 없어도 그 인물이 지니고 있어 꺼내 쓸 수 있습니다."


def check_rule(p: Project) -> str:
    """검수 요구사항에 붙는 한 줄. 상태창에 인벤토리 항목이 없으면 빈 글."""
    if not inventory(p):
        return ""
    return ("\n- 인벤토리:" + _INVENTORY_HAS + " 인벤토리에도 attire 에도 없는 물건을 얻는 장면 없이 꺼내 쓰는지 봅니다. "
            "type 은 사실, source_episode 는 0, source_quote 는 그 인벤토리 값입니다.")


def _change(ch: dict, after: str) -> str:
    """'레벨 3 → 4', 목록이면 '+독 내성 -은신'."""
    if ch.get("added") or ch.get("removed"):
        return " ".join([f"+{x}" for x in ch.get("added", [])] + [f"-{x}" for x in ch.get("removed", [])])
    return f"{ch['before'] or '없음'} → {after or '지움'}"


def describe(p: Project, cid: str) -> str:
    """명령줄 출력: 지금 상태창과 화별 변화."""
    c = next((x for x in p.characters if x.id == cid or x.name == cid), None)
    if c is None:
        raise KeyError(f"없는 인물이에요: {cid}")
    t = timeline(p, c.id)
    if not t["names"]:
        return f"{c.name} 의 상태창이 없습니다. statwin {'<작품>'} {c.id} --set 레벨=1 처럼 만듭니다."
    out = [render(p, c.id), ""]
    for col in t["columns"]:
        ch = [f"{k} {_change(v, col['values'].get(k, ''))}{SOURCE.get(v['source'], '')}" for k, v in col["changed"].items()]
        out.append(f"{col['episode']}화: " + ", ".join(ch))
    return "\n".join(out)
