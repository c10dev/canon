"""상태창: 게임 판타지 · 헌터물처럼 본문에 레벨, 능력치, 스킬이 숫자로 나오는 작품에서 인물별 수치를 화마다 기록한다.

작가가 인물의 상태창 항목(CharacterState.stats)을 정하면 켜진다. 켜지면 쓰기 · 상태 정리 프롬프트에 규칙 한 줄이 붙고,
AI 는 상태 변경안에 바뀐 항목만 적는다(+3 처럼 바뀐 양만 적으면 Canon 이 계산). 반영은 승인 후.
바뀐 기록(Project.stat_log)으로 화별 비교를 그린다. LLM 을 부르지 않는다.
"""
from __future__ import annotations

import re

from . import dynamics, logline
from .schema import (CharacterState, Project, StatInitCharacter, StatInitSuggestion, StatRecord, StateDelta, StatValue,
                     StatWindowOption, StatWindowSuggestion)

PRESETS: dict[str, list[str]] = {
    "game": ["레벨", "HP", "MP", "힘", "민첩", "체력", "지능", "스킬"],
    "hunter": ["등급", "레벨", "마력", "스킬", "칭호"],
    "simple": ["레벨", "스킬"],
    "growth": ["레벨", "스킬", "특성", "칭호", "골드", "인벤토리"],
}

SOURCE = {"ai": "", "author": " (작가)", "both": " (승인 뒤 작가가 고침)"}
# 화면 스킨 (schema.StatSkin). 화면 이름은 static/statwin.js 의 SW_SKINS 와 같다
SKINS: dict[str, str] = {
    "system": "시스템 창: 어두운 바탕에 푸른 선. 게임 판타지 · 헌터물 · 회귀물",
    "parchment": "양피지: 누런 종이에 갈색 잉크. 서양 판타지 · 마법 학교 · 길드",
    "scroll": "두루마리: 한지 바탕에 먹과 붉은 인장. 무협 · 선협 · 동양풍",
    "neon": "네온: 검은 바탕에 분홍 · 하늘색 빛. 사이버펑크 · SF · 가상 현실 게임",
    "plain": "담백한 서류: 흰 바탕에 검은 선. 현대물 · 협회 등록증 · 기록부",
}
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


def write_rule(p: Project, n: int = 0) -> str:
    """본문 쓰기 프롬프트 끝에 붙는 규칙. 상태창을 만든 인물이 없으면 빈 글.
    넣는 방식(stat_window.prompt)이 none 이면 빈 글, lines 면 이번 화 인물의 수치 줄과 도감 줄(lines_block)."""
    if not enabled(p) or p.stat_window.prompt == "none":
        return ""
    if p.stat_window.prompt == "lines" and n:
        return lines_block(p, n)
    who = next((s.character_id for s in p.states if s.stats), "")
    return ("\n\n상태창: [인물 현재 상태]의 stats 가 지금 수치입니다. 본문에 상태창이나 수치를 보여 줄 때는 이 값을 그대로 쓰고, "
            "이번 화 사건으로 바뀌는 값만 바꿉니다. 이유 없이 수치를 올리거나 내리지 않습니다. "
            "스킬 · 특성 · 칭호처럼 늘어놓은 항목에 없는 것을 쓰려면 얻는 장면을 먼저 보여 줍니다."
            + (_INVENTORY_HAS if inventory(p) else "")
            + " 상태창은 아래 서식으로 씁니다.\n"
            + render(p, who))


def episode_cast(p: Project, n: int) -> list[str]:
    """이번 화에 나오는 인물 중 상태창이 있는 인물 id. 플롯에 인물이 없으면 상태창이 있는 인물 모두."""
    have = [s.character_id for s in p.states if s.stats]
    ids = p.episode(n).plot.characters if any(e.plot.number == n for e in p.episodes) else []
    picked = [c for c in ids if c in have]
    return picked or ([] if ids else have)


def wants_window(p: Project, n: int) -> bool:
    """이번 화 플롯에 상태창 장면이 있는지: 플롯 글에 '상태창'이나 작품의 창 이름이 나온다."""
    from . import elements

    if not any(e.plot.number == n for e in p.episodes):
        return False
    text = elements.plot_text(p.episode(n))
    return any(w and w in text for w in {"상태창", p.stat_window.title.strip()})


def lines_block(p: Project, n: int) -> str:
    """상태창 줄 형식(stat_window.prompt = lines): 이번 화 인물의 수치를 한 줄씩, 그 인물이 가진 스킬 · 특성은 도감 한 줄로.
    수치는 확인용 사실로만 주고, 상태창 서식 예시는 플롯에 상태창 장면이 있을 때만 붙인다. 도감 줄은 context.BUDGET['stat_lines'] 까지."""
    from . import abilities, context, elements

    ids = episode_cast(p, n)
    if not ids:
        return ""
    name = {c.id: c.name or c.id for c in p.characters}
    blocks = []
    for cid in ids:
        st = p.state_of(cid)
        rows = [f"- {s.name}: {s.value}" for s in (st.stats if st else []) if s.value.strip()]
        if rows:
            blocks.append(name.get(cid, cid) + "\n" + "\n".join(rows))
    plot = elements.plot_text(p.episode(n)) if any(e.plot.number == n for e in p.episodes) else ""
    picks = []
    for a in p.abilities:
        if a.context == "off":
            continue
        own = abilities.owners(p, a)
        mine = [o for o in own if o["character_id"] in ids]
        named = any(t in plot for t in abilities.terms(a))
        if not (mine or named or a.context == "always"):
            continue
        line = abilities.line(p, a, mine or own)
        if line:
            picks.append((0 if named else 1 if a.context == "always" else 2, line))
    budget, used, lines, cut = context.BUDGET["stat_lines"], 0, [], 0
    for _, line in sorted(picks, key=lambda x: x[0]):
        if used + len(line) > budget:
            cut += 1
            continue
        lines.append(line)
        used += len(line)
    out = f"\n\n상태창 수치 ({n - 1}화가 끝났을 때, 이번 화 인물만):\n" + "\n".join(blocks)
    if lines:
        out += "\n스킬 · 특성:\n" + "\n".join(lines)
    if cut:
        out += f"\n(스킬 · 특성 {cut}개는 분량 때문에 뺐습니다)"
    out += ("\n위 수치는 어긋나지 않게 확인하는 자료입니다. 본문에 꼭 보일 필요는 없습니다. "
            "본문에 수치를 쓸 때는 이 값을 그대로 쓰고, 이번 화 사건으로 바뀌는 값만 바꿉니다. 이유 없이 수치를 올리거나 내리지 않습니다. "
            "스킬 · 특성 · 칭호를 쓸 때는 위 효과와 대가를 지키고, 목록에 없는 것을 쓰려면 얻는 장면을 먼저 보여 줍니다."
            + (_INVENTORY_HAS if inventory(p) else ""))
    if wants_window(p, n):
        out += " 이번 화 플롯에 상태창 장면이 있습니다. 상태창은 아래 서식으로 씁니다.\n" + render(p, ids[0])
    return out


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
    """검수 요구사항에 붙는 줄. 상태창을 만든 인물이 없으면 빈 글. 인벤토리 줄은 인벤토리 항목이 있을 때만."""
    if not enabled(p):
        return ""
    out = ("\n- 상태창: [인물 현재 상태]의 stats 는 직전 화가 끝났을 때의 상태창 수치입니다. "
           "본문의 상태창이나 서술에 나온 수치 · 등급이 그 값과 다른데 이번 화에 그렇게 바뀌는 사건(레벨 업, 전투 피해, 회복, 사고팔기, 보상 알림)이 없는지, "
           "스킬 · 특성 · 칭호를 목록에 없는데 얻는 장면 없이 쓰는지 봅니다. "
           "이번 화 사건으로 바뀐 값은 모순이 아닙니다. 근거가 stats 면 type 은 사실, source_episode 는 0, source_quote 는 그 항목과 값(예: 레벨: 4)입니다. "
           "한 화 안에서 앞뒤 상태창이 맞지 않거나(두 상태창의 레벨이 다름) 본문에 나온 셈이 틀리면(1,200골드에서 300골드를 썼는데 남은 돈이 1,000골드) "
           "source_episode 는 이번 화, source_quote 는 앞 문장입니다.")
    if inventory(p):
        out += ("\n- 인벤토리:" + _INVENTORY_HAS + " 인벤토리에도 attire 에도 없는 물건을 얻는 장면 없이 꺼내 쓰는지 봅니다. "
                "type 은 사실, source_episode 는 0, source_quote 는 그 인벤토리 값입니다.")
    return out


_FENCE = re.compile(r"^```\w*\n?|\n?```$")


def clean_options(s: StatWindowSuggestion) -> StatWindowSuggestion:
    """AI 가 낸 꾸미기 안 정리: 코드 블록 표시를 벗기고, {rows} · {key} · {value} 가 빠진 서식은 고친다. 빈 안은 버린다."""
    out: list[StatWindowOption] = []
    for o in s.options[:4]:
        tpl = _FENCE.sub("", o.template.replace("\\n", "\n").strip()).strip("\n")
        if not tpl.strip():
            continue
        if "{rows}" not in tpl:
            tpl += "\n{rows}"
        row = o.row.strip("\n")
        if "{key}" not in row or "{value}" not in row:
            row = "{key}: {value}"
        names: list[str] = []
        for x in o.names:
            x = x.strip()
            if x and x not in names:
                names.append(x)
        out.append(StatWindowOption(label=o.label.strip() or o.title.strip() or "상태창", title=o.title.strip() or "상태창",
                                    template=tpl, row=row, names=names[:12], skin=o.skin if o.skin in SKINS else "system", why=o.why.strip()))
    return StatWindowSuggestion(options=out)


def clean_init(p: Project, s: StatInitSuggestion) -> StatInitSuggestion:
    """AI 가 낸 처음 수치 정리: 없는 인물과 빈 값은 버린다. 작품 틀이 있으면 그 항목만, 그 순서로 둔다.
    +3 처럼 바뀐 양으로 적은 값은 앞의 + 를 뗀다 (처음 값이라 더할 값이 없다)."""
    names = [x.strip() for x in (p.stat_window.names or s.names) if x.strip()]
    names = list(dict.fromkeys(names))
    ids = {c.id for c in p.characters}
    out: dict[str, StatInitCharacter] = {}
    for c in s.characters:
        if c.character_id not in ids or c.character_id in out:
            continue
        vals: dict[str, str] = {}
        for x in c.stats:
            k, v = x.name.strip(), re.sub(r"^\+\s*(?=\d)", "", x.value.strip())
            if k and v and k not in vals and (k in names or not p.stat_window.names):
                vals[k] = v
        if not vals:
            continue
        order = [k for k in names if k in vals] + [k for k in vals if k not in names]
        out[c.character_id] = StatInitCharacter(character_id=c.character_id, stats=[StatValue(name=k, value=vals[k]) for k in order],
                                                 note=c.note.strip())
    names += [x.name for c in out.values() for x in c.stats if x.name not in names]
    return StatInitSuggestion(names=list(dict.fromkeys(names)), characters=list(out.values()))


def sample_rows(p: Project) -> list[StatValue]:
    """서식 미리 보기에 쓸 항목: 상태창이 있는 첫 인물의 값, 없으면 작품 틀 이름과 빈 값."""
    st = next((s for s in p.states if any(x.value.strip() for x in s.stats)), None)
    if st:
        return [x for x in st.stats if x.value.strip()]
    return [StatValue(name=x, value="") for x in p.stat_window.names]


# ---------- 본문 상태창 읽기: 반영 뒤 값과 대조 (LLM 없음) ----------

def _pattern(line: str, slots: dict[str, str]) -> re.Pattern:
    """서식 한 줄 → 정규식. 글자는 그대로, 빈칸은 있어도 없어도 되고, {이름} 은 잡는 칸."""
    out, i = "", 0
    for m in re.finditer(r"\{(\w+)\}", line):
        out += _literal(line[i:m.start()])
        out += slots.get(m.group(1), _literal(m.group(0)))
        i = m.end()
    return re.compile("^" + out + _literal(line[i:]) + "$")


def _literal(s: str) -> str:
    return r"\s*".join(re.escape(x) for x in re.split(r"\s+", s.strip())) if s.strip() else r"\s*"


def read_windows(p: Project, text: str) -> list[dict]:
    """본문에서 stat_window 서식으로 쓴 상태창을 찾는다. [{name, rows: [(항목, 값, 원문 줄)]}].

    서식의 {rows} 앞 줄 가운데 글자가 있는 첫 줄(예: 【 상태창 】)로 상태창 시작을 찾는다. 그런 줄이 없으면 찾지 않는다.
    머리의 다른 줄은 맞으면 읽고(이름), 없어도 넘어간다. 그 뒤로 항목 줄 서식에 맞는 줄을 읽고, 맞지 않는 줄에서 끝낸다(빈 줄은 건너뜀).
    """
    w = p.stat_window
    lines = w.template.split("\n")
    at = next((i for i, x in enumerate(lines) if "{rows}" in x), len(lines))
    head = [x for x in lines[:at] if x.strip()]
    anchor = next((i for i, x in enumerate(head) if re.sub(r"\{\w+\}|\s", "", x)), None)
    if anchor is None:
        return []
    heads = [_pattern(x, {"name": r"(?P<name>.+?)"}) for x in head]
    row = _pattern(w.row, {"key": r"(?P<key>.+?)", "value": r"(?P<value>.*?)"})
    stat_names = {_canon(x.name) for s in p.states for x in s.stats}
    people = {_canon(c.name) for c in p.characters if c.name}
    body = text.split("\n")
    out, i = [], 0
    while i < len(body):
        m = heads[anchor].match(body[i].strip())
        if not m:
            i += 1
            continue
        name = m.groupdict().get("name") or ""
        i += 1
        rest = heads[anchor + 1:]
        rows: list[tuple[str, str, str]] = []
        while i < len(body):
            s = body[i].strip()
            if not s:
                i += 1
                continue
            hm = next((h.match(s) for h in rest if h.match(s)), None)
            if hm and not rows:  # 이름 줄 같은 머리 줄
                name = name or hm.groupdict().get("name") or ""
                i += 1
                continue
            rm = row.match(s)
            if not rm or not rm.group("key").strip():
                break
            if not rows and not name and _canon(rm.group("key")) not in stat_names and _canon(rm.group("value")) in people:
                name = rm.group("value")  # 서식에 없는 '이름: 서윤' 줄
                i += 1
                continue
            rows.append((rm.group("key").strip(), rm.group("value").strip(), s))
            i += 1
        if rows:
            out.append({"name": name.strip(), "rows": rows})
    return out


def _canon(x: str) -> str:
    return re.sub(r"\s+", "", x).casefold()


def same(shown: str, value: str) -> bool:
    """본문에 보인 값과 기록 값이 같은지. 수치는 쉼표 · 빈칸을 무시하고, 목록은 순서를 무시한다."""
    a, b = _amount(shown), _amount(value)
    if a and b:
        return a[2] == b[2] and _canon(a[0]) == _canon(b[0]) and _canon(a[4]) == _canon(b[4])
    xs, ys = items(shown), items(value)
    if len(xs) > 1 or len(ys) > 1:
        return sorted(map(_canon, xs)) == sorted(map(_canon, ys))
    return _canon(shown) == _canon(value)


def after_delta(p: Project, d: StateDelta) -> dict[str, dict[str, str]]:
    """변경안을 반영하면 될 상태창 값. {인물 id: {항목: 값}}. 상태창이 있거나 변경안에 수치가 있는 인물만."""
    out = {s.character_id: {x.name: x.value for x in s.stats} for s in p.states if s.stats}
    for u in d.character_updates:
        cur = out.setdefault(u.character_id, {})
        for s in u.stats:
            name = s.name.strip()
            if not name:
                continue
            if not s.value.strip():
                cur.pop(name, None)
            else:
                cur[name] = resolve(cur.get(name, ""), s.value)
    return {k: v for k, v in out.items() if v}


def _who(p: Project, name: str, have: dict[str, dict[str, str]]) -> str:
    """상태창 머리의 이름 → 인물 id. 서식에 이름이 없으면 상태창이 있는 인물이 하나일 때만 그 인물."""
    if not name:
        return next(iter(have)) if len(have) == 1 else ""
    n = _canon(name)
    c = next((c for c in p.characters if _canon(c.name) == n or c.id.casefold() == n), None)
    c = c or next((c for c in p.characters if c.name and _canon(c.name) in n), None)
    return c.id if c else ""


def window_warnings(p: Project, d: StateDelta) -> list[str]:
    """본문 상태창과 변경안을 반영한 값이 다른 곳. 인물마다 이 화의 마지막 상태창만 본다 (앞 상태창은 오르기 전 값일 수 있다).
    문장은 «» 에 본문 줄을 그대로 넣어 승인 화면이 그 줄을 찾게 한다."""
    if not enabled(p) and not any(u.stats for u in d.character_updates):
        return []
    have = after_delta(p, d)
    last: dict[str, dict] = {}
    for win in read_windows(p, p.episode(d.episode).text):
        cid = _who(p, win["name"], have)
        if cid:
            last[cid] = win
    out = []
    for cid, win in last.items():
        name = next((c.name for c in p.characters if c.id == cid), cid) or cid
        vals = have.get(cid, {})
        keys = {_canon(k): k for k in vals}
        for key, shown, line in win["rows"]:
            k = keys.get(_canon(key))
            if k is None:
                if vals:
                    out.append(f"{name} 상태창: 본문 «{line}»의 '{key}' 항목은 상태창 기록에 없어요. 이 화에 생긴 항목이면 변경안에 넣으세요.")
            elif not same(shown, vals[k]):
                out.append(f"{name} 상태창: 본문은 «{line}»인데 반영하면 {k}{logline.josa(k, '이', '가')} {vals[k]}{logline.josa(vals[k], '이에요', '예요')}.")
    return out


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
