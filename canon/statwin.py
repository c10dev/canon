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
}

SOURCE = {"ai": "", "author": " (작가)", "both": " (승인 뒤 작가가 고침)"}
_NUM = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


def enabled(p: Project) -> bool:
    return any(s.stats for s in p.states)


def _fmt(x: float) -> str:
    return str(int(x)) if x == int(x) else f"{x:.2f}".rstrip("0").rstrip(".")


def resolve(before: str, value: str) -> str:
    """'+3', '-10' 은 이전 값이 숫자일 때 더하고 뺀다. 그 밖에는 적은 값 그대로."""
    v = value.strip().replace(",", "")
    b = before.strip().replace(",", "")
    if v[:1] in "+-" and _NUM.match(v) and _NUM.match(b):
        return _fmt(float(b) + float(v))
    return value.strip()


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
        raise KeyError(f"인물이 없습니다: {cid}")
    names = [r.name.strip() for r in rows if r.name.strip()]
    if len(names) != len(set(names)):
        raise ValueError("항목 이름이 겹칩니다")
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
            "이번 화 사건으로 바뀌는 값만 바꿉니다. 이유 없이 수치를 올리거나 내리지 않습니다. 상태창은 아래 서식으로 씁니다.\n"
            + render(p, who))


def state_rule(p: Project) -> str:
    """상태 정리 요구사항에 붙는 한 줄. 상태창을 만든 인물이 없으면 빈 글."""
    if not enabled(p):
        return ""
    return ("\n- [이전 인물 상태]의 stats 는 상태창 수치입니다. 본문에서 바뀐 항목만 그 인물의 character_updates 항목 stats 에 넣습니다. "
            "value 는 새 값을 적거나, 바뀐 양만 알면 +3, -10 처럼 적습니다. 사라진 항목은 value 를 비웁니다. "
            "본문 수치가 이전 값에서 설명 없이 튀거나 앞뒤가 맞지 않으면 warnings 에 적습니다.")


def describe(p: Project, cid: str) -> str:
    """명령줄 출력: 지금 상태창과 화별 변화."""
    c = next((x for x in p.characters if x.id == cid or x.name == cid), None)
    if c is None:
        raise KeyError(f"인물이 없습니다: {cid}")
    t = timeline(p, c.id)
    if not t["names"]:
        return f"{c.name} 의 상태창이 없습니다. statwin {'<작품>'} {c.id} --set 레벨=1 처럼 만듭니다."
    out = [render(p, c.id), ""]
    for col in t["columns"]:
        ch = [f"{k} {v['before'] or '없음'} → {col['values'].get(k) or '지움'}{SOURCE.get(v['source'], '')}"
              for k, v in col["changed"].items()]
        out.append(f"{col['episode']}화: " + ", ".join(ch))
    return "\n".join(out)
