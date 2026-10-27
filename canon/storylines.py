"""이야기 줄기: 메인 줄기에서 갈라졌다 합류하는 서브플롯, 과거 회상, 외전, 인물 이야기.

LLM 을 부르지 않는 부분만 둔다. 화가 어느 줄기에 속하는지(episodes_of), 줄기가 걸친 범위(span),
프롬프트에 넣을 블록(plan_block, episode_block), 명령줄 노선도(ascii_map)를 만든다.
AI 제안과 반영은 pipeline.suggest_storyline / apply_storyline 이 맡는다.
화의 줄기는 EpisodePlot.storyline(그 화가 주로 따라가는 줄기, 비면 메인)과 threads(끼어드는 장면)로 적는다.
span · tag · episodes_of 는 웹 static/lines.js 와 Swift 앱 swift/Sources/FeatureLines/LineRules.swift 에도 있어 함께 고친다.
"""
from __future__ import annotations

from .schema import Episode, Project, Storyline

KINDS = ["서브플롯", "과거 회상", "외전", "인물 이야기"]
RECENT = 3  # 본문 컨텍스트에 넣는 그 줄기의 앞 화 요약 수


def get(p: Project, sid: str) -> Storyline:
    s = p.storyline(sid)
    if s is None:
        raise KeyError(f"이야기 줄기가 없어요: {sid}")
    return s


def new_id(p: Project) -> str:
    have = {s.id for s in p.storylines}
    n = len(p.storylines) + 1
    while f"sl-{n:02d}" in have:
        n += 1
    return f"sl-{n:02d}"


def past(s: Storyline) -> bool:
    """메인과 다른 시점(과거 회상, 앞뒤 시간의 외전)을 따라가는 줄기인가."""
    return bool(s.when.strip()) or s.kind == "과거 회상"


def episodes_of(p: Project, sid: str) -> list[tuple[int, str]]:
    """(화, 'main' 또는 'thread'). main 은 그 화가 이 줄기를 주로 따라가고, thread 는 장면으로 끼어든다."""
    out = []
    for e in sorted(p.episodes, key=lambda e: e.plot.number):
        if e.plot.storyline == sid:
            out.append((e.plot.number, "main"))
        elif sid in e.plot.threads:
            out.append((e.plot.number, "thread"))
    return out


def span(p: Project, s: Storyline) -> tuple[int, int]:
    """줄기가 걸친 화 범위. 갈라지는 화와 합류하는 화가 비어 있으면 속한 화로 정한다. 아무것도 없으면 (0, 0)."""
    eps = [n for n, _ in episodes_of(p, s.id)]
    lo = min([x for x in [s.branch_ep, *eps] if x], default=0)
    hi = max([x for x in [s.join_ep, *eps] if x], default=0)
    return lo, hi


def is_open(p: Project, s: Storyline) -> bool:
    """아직 합류하지 않은 줄기. 합류 화를 정하지 않았거나 합류 화 본문이 아직 없으면 열려 있다."""
    if not s.join_ep:
        return True
    e = next((e for e in p.episodes if e.plot.number == s.join_ep), None)
    return not (e and e.text)


def clean_plot(p: Project, e: Episode) -> list[str]:
    """화 플롯의 줄기 표시에서 없는 줄기를 지운다. 지운 id 를 돌려준다."""
    ids = {s.id for s in p.storylines}
    gone = []
    if e.plot.storyline and e.plot.storyline not in ids:
        gone.append(e.plot.storyline)
        e.plot.storyline = ""
    keep = []
    for t in e.plot.threads:
        if t in ids and t != e.plot.storyline and t not in keep:
            keep.append(t)
        elif t not in ids:
            gone.append(t)
    e.plot.threads = keep
    return gone


def tag(p: Project, n: int, sid: str, role: str = "main") -> None:
    """n화를 줄기에 붙인다. role 'main' 은 그 화가 줄기를 주로 따라가고, 'thread' 는 장면만 끼어든다. sid 가 비면 메인으로 되돌린다."""
    e = p.episode(n)
    if sid:
        get(p, sid)
    if role == "main":
        e.plot.threads = [t for t in e.plot.threads if t != sid]
        e.plot.storyline = sid
    elif sid and sid not in e.plot.threads and e.plot.storyline != sid:
        e.plot.threads.append(sid)


def untag_all(p: Project, sid: str) -> None:
    for e in p.episodes:
        if e.plot.storyline == sid:
            e.plot.storyline = ""
        e.plot.threads = [t for t in e.plot.threads if t != sid]


# ---------- 프롬프트 블록 ----------

def describe(p: Project, s: Storyline) -> str:
    names = {c.id: c.name for c in p.characters}
    lo, hi = span(p, s)
    eps = episodes_of(p, s.id)
    line = f"- {s.id} [{s.kind}] {s.title}"
    if s.focus:
        line += f"\n  중심 인물: {', '.join(names.get(c, c) + f'({c})' for c in s.focus)}"
    if s.when:
        line += f"\n  이야기 속 시점: {s.when}"
    if s.goal:
        line += f"\n  풀어 갈 것: {s.goal}"
    where = []
    if s.branch_ep:
        where.append(f"{s.branch_ep}화에서 갈라짐")
    if s.join_ep:
        where.append(f"{s.join_ep}화에 메인으로 합류")
    elif lo:
        where.append("아직 합류 화를 정하지 않음")
    if where:
        line += "\n  흐름: " + ", ".join(where)
    if s.rejoin:
        line += f"\n  합류 때 메인에 남기는 것: {s.rejoin}"
    if eps:
        line += "\n  지금 붙은 화: " + ", ".join(f"{n}화" + ("(장면)" if r == "thread" else "") for n, r in eps)
    return line


def plan_block(p: Project) -> str:
    """기획용(화별 플롯, 플롯 대화, 다음 아크): 모든 줄기. 줄기가 없으면 빈 문자열."""
    return "\n".join(describe(p, s) for s in p.storylines)


def plan_rule(p: Project) -> str:
    """플롯 규칙에 붙는 한 줄. 줄기가 없으면 빈 문자열."""
    if not p.storylines:
        return ""
    return ("\n- 이야기 줄기가 있으면: 그 줄기를 주로 따라가는 화는 storyline 에 줄기 id 를, 메인 화 안에 그 줄기 장면이 끼어들면 threads 에 id 를 넣습니다. "
            "메인 화는 storyline 을 비웁니다. 줄기는 갈라지는 화 뒤에 시작해 합류하는 화에서 메인으로 돌아오고, 합류 때 남기는 것을 메인 사건으로 이어 받습니다. "
            "과거 시점 줄기의 화에서는 메인 시간이 흐르지 않습니다.")


def episode_block(p: Project, n: int) -> str:
    """본문 쓰기 · 검수 컨텍스트에 넣는 블록: 이번 화가 따르는 줄기와 끼어드는 줄기, 그 줄기의 앞 화 요약.
    메인 줄기 화이고 끼어드는 줄기도 없으면 빈 문자열."""
    e = p.episode(n)
    lines = []
    s = p.storyline(e.plot.storyline)
    if s:
        lines.append("이번 화는 메인이 아니라 아래 줄기를 따라간다.\n" + describe(p, s) + _recent(p, s, n))
        if past(s):
            lines.append(f"※ 이번 화는 '{s.when or '과거'}' 시점이다. 그 시점에 아직 일어나지 않은 일이나 인물이 아직 몰랐던 것을 알고 있는 듯 쓰지 않는다. "
                         "아래 '인물 현재 상태'와 관계는 지금(메인) 기준이므로 그 시점에 맞게 거슬러 올라가 쓴다. 나이, 외모, 호칭도 그 시점에 맞춘다.")
    threads = [t for t in (p.storyline(x) for x in e.plot.threads) if t]
    if threads:
        lines.append("이번 화 안에 장면으로 끼어드는 줄기 (짧게, 메인 흐름을 끊지 않게):\n"
                     + "\n".join(describe(p, t) + _recent(p, t, n) for t in threads))
    return "\n\n".join(lines)


def _recent(p: Project, s: Storyline, n: int) -> str:
    if s.summary:
        return f"\n  지금까지 이 줄기: {s.summary}"
    prev = [m for m, _ in episodes_of(p, s.id) if m < n][-RECENT:]
    sums = [f"{m}화: {p.episode(m).summary}" for m in prev if p.episode(m).summary]
    return ("\n  이 줄기의 앞 화: " + " / ".join(sums)) if sums else ""


def state_rule(p: Project, n: int) -> str:
    """상태 변경안 지시에 붙는 줄. 과거 시점 화면 지금 상태를 덮지 않게 한다."""
    s = p.storyline(p.episode(n).plot.storyline)
    if not (s and past(s)):
        return ""
    return (f"\n- 이번 화는 이야기 줄기 '{s.title}'({s.when or '과거'} 시점)를 따라갑니다. 과거 장면에서 일어난 일로 인물의 지금 emotional_state, current_goal, location 을 바꾸지 않습니다. "
            "knows 는 지금 시점의 인물이 이번 화에서 새로 알게 된 것만 넣습니다. 관계 events 는 과거 사건이 지금 관계를 바꾸는 경우(누가 그 과거를 새로 알게 됨 등)에만 넣고, "
            "드러난 과거 사실은 new_facts 에 '과거:' 로 시작해 적습니다.")


def summary_tag(p: Project, e: Episode) -> str:
    """줄거리 요약 줄 앞에 붙일 표시. 메인 화면 빈 문자열."""
    s = p.storyline(e.plot.storyline)
    return f"[{s.kind}: {s.title}] " if s else ""


# ---------- 명령줄 노선도 ----------

def ascii_map(p: Project, width: int = 0) -> str:
    """가로가 화인 노선도. ● 그 줄기 화, · 끼어드는 장면, ╰ 갈라짐, ╯ 합류, ─ 걸친 범위."""
    total = max([p.meta.target_episodes] + [e.plot.number for e in p.episodes]) or 1
    width = width or total
    rows = []
    main = "".join("─" if any(e.plot.number == n and not e.plot.storyline for e in p.episodes) else " " for n in range(1, width + 1))
    rows.append(f"{'메인':<10}{main}")
    for s in p.storylines:
        lo, hi = span(p, s)
        roles = dict(episodes_of(p, s.id))
        cells = []
        for n in range(1, width + 1):
            if roles.get(n) == "main":
                cells.append("●")
            elif roles.get(n) == "thread":
                cells.append("·")
            elif n == s.branch_ep:
                cells.append("╰")
            elif n == s.join_ep:
                cells.append("╯")
            elif lo and lo <= n <= hi:
                cells.append("─")
            else:
                cells.append(" ")
        rows.append(f"{s.id:<10}{''.join(cells)}  {s.kind} · {s.title}")
    ruler = "".join(str(n // 10 % 10) if n % 10 == 0 else " " for n in range(1, width + 1))
    return "\n".join([f"{'':<10}{ruler}", *rows])
