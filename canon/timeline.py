"""작품 속 시간: 화가 끝난 시점(Episode.time)과 앞으로 올 기한(Timeline.deadlines)을 기록한다.

AI 는 상태 변경안에 이번 화가 끝난 시점(며칠째, 시간대)과 새 기한만 적고, 남은 날은 Canon 이 계산한다.
쓰기 · 검수 · 플롯 프롬프트에는 직전 화 끝 시점, 이번 화 플롯의 시점, 열린 기한 몇 줄만 넣어 화수가 늘어도 크기가 일정하다.
줄거리 요약 줄에는 화가 끝난 시점을 짧게 붙인다(tag). 반영은 승인 후. LLM 을 부르지 않는다.
"""
from __future__ import annotations

import re

from . import context
from .schema import Deadline, Episode, Project, StateDelta, StoryTime


def enabled(p: Project) -> bool:
    return p.timeline.enabled


def fmt(t: StoryTime | None) -> str:
    """'3일째 밤 (3월 5일 화요일)'. 아무것도 없으면 빈 문자열."""
    if t is None:
        return ""
    head = " ".join(x for x in (f"{t.day}일째" if t.day > 0 else "", t.part.strip()) if x)
    label = t.label.strip()
    if head and label:
        return f"{head} ({label})"
    return head or label


def known(t: StoryTime | None) -> bool:
    return bool(t and (t.day > 0 or t.part.strip() or t.label.strip()))


def tag(p: Project, e: Episode) -> str:
    """줄거리 요약 줄 앞에 붙일, 그 화가 끝난 시점 ('[3일째 밤] '). 꺼졌거나 모르면 빈 문자열."""
    if not enabled(p) or not known(e.time):
        return ""
    t = e.time
    short = " ".join(x for x in (f"{t.day}일째" if t.day > 0 else "", t.part.strip()) if x) or t.label.strip()  # 줄마다 붙어 날짜 글은 뺀다
    return f"[{short}] "


def prev_end(p: Project, n: int) -> tuple[int, StoryTime] | None:
    """n화보다 앞에서 시점을 아는 마지막 화와 그 끝 시점."""
    for e in sorted(p.episodes, key=lambda x: -x.plot.number):
        if e.plot.number < n and known(e.time):
            return e.plot.number, e.time
    return None


def current_day(p: Project, n: int) -> int:
    """n화 직전의 날수. 앞 화 어디에도 날수가 없으면 0."""
    for e in sorted(p.episodes, key=lambda x: -x.plot.number):
        if e.plot.number < n and e.time.day > 0:
            return e.time.day
    return 0


def left(d: Deadline, day: int) -> str:
    """'4일 남음', '오늘', '2일 지남'. 날수를 모르면 빈 문자열."""
    if d.day <= 0 or day <= 0:
        return ""
    gap = d.day - day
    if gap > 0:
        return f"{gap}일 남음"
    return "오늘" if gap == 0 else f"{-gap}일 지남"


def is_open(d: Deadline, n: int) -> bool:
    """n화를 쓸 때 열려 있는 기한: n화보다 앞에서 생겼고 n화 전에 닫히지 않았다."""
    return d.set_ep < n and not (0 < d.done_ep < n)


def open_deadlines(p: Project, n: int) -> list[Deadline]:
    """n화를 쓸 때 열린 기한. 날이 가까운 것부터, 날을 모르는 것은 뒤에."""
    out = [d for d in p.timeline.deadlines if is_open(d, n)]
    return sorted(out, key=lambda d: (d.day <= 0, d.day, d.set_ep))


def deadline_line(d: Deadline, day: int, ids: bool = False) -> str:
    """'- 왕성 축제 첫날 (9일째, 6일 남음, '사흘 뒤')'. ids 는 상태 변경안처럼 id 로 가리켜야 할 때만."""
    when = f"{d.day}일째" if d.day > 0 else ""
    extra = ", ".join(x for x in (when, left(d, day), d.note.strip() and f"'{d.note.strip()}'") if x)
    return f"- {d.what}{f' ({extra})' if extra else ''}{f' [{d.id}]' if ids else ''}"


def deadline_lines(p: Project, n: int, budget: int = 0, ids: bool = False) -> tuple[list[str], int]:
    """열린 기한 줄과 예산(context.BUDGET["deadlines"]) 때문에 뺀 수. 지난 기한 → 가까운 기한 순으로 넣고 먼 것부터 뺀다.
    단편도 같은 예산을 쓴다 (기한은 화수와 상관없이 쌓일 수 있다)."""
    budget = budget or context.BUDGET["deadlines"]
    day = current_day(p, n)
    rows, size, cut = [], 0, 0
    for d in open_deadlines(p, n):
        line = deadline_line(d, day, ids)
        if size + len(line) > budget and rows:
            cut += 1
            continue
        rows.append(line)
        size += len(line) + 1
    return rows, cut


def _plot_time(p: Project, n: int) -> str:
    e = next((x for x in p.episodes if x.plot.number == n), None)
    return e.plot.time.strip() if e else ""


def episode_block(p: Project, n: int) -> str:
    """본문 쓰기 · 검수에 넣는 블록: 기준, 직전 화 끝 시점, 이번 화 플롯의 시점, 열린 기한.
    꺼졌거나 넣을 것이 하나도 없으면 빈 문자열 (기록이 없는 작품의 프롬프트는 그대로)."""
    if not enabled(p):
        return ""
    prev = prev_end(p, n)
    plan = _plot_time(p, n)
    rows, cut = deadline_lines(p, n)
    if not (prev or plan or rows):
        return ""
    lines = []
    if p.timeline.start.strip():
        lines.append(f"기준: 1일째 = {p.timeline.start.strip()}")
    if prev:
        gap = "" if prev[0] == n - 1 else f" ({prev[0] + 1}화는 시점 기록 없음)" if prev[0] == n - 2 else f" ({prev[0] + 1}~{n - 1}화는 시점 기록 없음)"
        lines.append(f"직전 화({prev[0]}화) 끝: {fmt(prev[1])}{gap}")
    lines.append(f"이번 화 플롯의 시점: {plan}" if plan else "이번 화 플롯의 시점: 따로 없음 (직전 화 끝에서 바로 이어짐)")
    if rows:
        lines.append(f"열린 기한{f' (먼 것 {cut}개 생략)' if cut else ''}:")
        lines += rows
    lines.append("- 지난 시간에 맞게 빛, 날씨, 계절, 피로, 상처, 배고픔이 달라집니다. 인물이 기한까지 남은 날을 말하면 위 날수와 맞춥니다.")
    return "\n".join(lines)


def plan_block(p: Project, n: int) -> str:
    """플롯 기획에 넣는 블록: n화 직전 시점과 열린 기한. 꺼졌거나 없으면 빈 문자열."""
    if not enabled(p):
        return ""
    prev = prev_end(p, n)
    rows, cut = deadline_lines(p, n)
    if not (prev or rows):
        return ""
    lines = [f"{prev[0]}화 끝: {fmt(prev[1])}"] if prev else []
    if rows:
        lines.append(f"열린 기한{f' (먼 것 {cut}개 생략)' if cut else ''}:")
        lines += rows
    lines.append("- 화마다 time 칸에 직전 화에서 얼마나 지났는지 적고, 기한이 있으면 그 날에 맞게 사건을 놓습니다.")
    return "\n".join(lines)


def state_block(p: Project, n: int) -> str:
    """상태 변경안 프롬프트의 [작품 속 시간] 자료. 꺼졌으면 빈 문자열."""
    if not enabled(p):
        return ""
    prev = prev_end(p, n)
    plan = _plot_time(p, n)
    rows, cut = deadline_lines(p, n, ids=True)
    lines = []
    if p.timeline.start.strip():
        lines.append(f"기준: 1일째 = {p.timeline.start.strip()}")
    lines.append(f"직전 화({prev[0]}화) 끝: {fmt(prev[1])}" if prev else "앞 화 시점 기록 없음")
    if plan:
        lines.append(f"이번 화 플롯의 시점: {plan}")
    lines.append(f"열린 기한{f' (먼 것 {cut}개 생략)' if cut else ''}:\n" + "\n".join(rows) if rows else "열린 기한: 없음")
    return "\n".join(lines)


def state_rule(p: Project, n: int) -> str:
    """상태 변경안 요구사항에 붙는 줄."""
    if not enabled(p):
        return ""
    prev = prev_end(p, n)
    count = (f"직전 화 끝 {prev[1].day}일째에서 이어 셉니다" if prev and prev[1].day > 0
             else "앞 화 기록이 없으면 1화가 시작한 날을 1일째로 보고 줄거리에서 짐작합니다")
    return (f"\n- time 에는 이번 화가 끝난 작품 속 시점을 적습니다. day 는 날수({count}), part 는 시간대(새벽, 아침, 낮, 오후, 저녁, 밤, 한밤 또는 '오후 3시쯤'), "
            "label 은 본문이나 기준에서 드러난 날짜 · 요일 · 계절만 적습니다. 회상 · 외전처럼 메인 시간 밖의 화면 메인 시간 기준으로 적습니다(보통 직전 화 끝 그대로)."
            f"\n- 본문에서 앞으로 올 날이 정해지면(축제, 결혼식, '사흘 안에' 같은 약속이나 마감) deadlines_added 에 넣습니다. id 는 dl-{n:02d}-키워드, "
            "day 는 그날의 날수, note 는 본문에 나온 말 그대로입니다. 열린 기한의 날이 바뀌면 같은 id 로 넣고, 그날이 와서 일이 일어났거나 기한이 없어졌으면 deadlines_done 에 id 를 넣습니다."
            "\n- 본문 속 시간이 직전 화 끝이나 열린 기한과 어긋나면(밤이었는데 설명 없이 낮, 남은 날 수가 틀림) warnings 에 적습니다.")


def check_rule(p: Project, n: int) -> str:
    """검수 확인 목록에 붙는 줄. 넣은 시간 블록이 없으면 빈 문자열."""
    if not episode_block(p, n):
        return ""
    return ("\n- 작품 속 시간: 위 '작품 속 시간'의 직전 화 끝 시점, 이번 화 플롯의 시점, 기한까지 남은 날과 어긋나는지, "
            "한 화 안에서 시간대가 설명 없이 뒤바뀌는지(밤 장면이 다음 문단에 한낮), 지난 시간에 맞지 않는 상처 · 날씨 · 계절이 있는지 봅니다. "
            "근거가 시간 기록이면 source_episode 는 0, source_quote 는 그 줄입니다.")


# ---------- 반영 · 되돌리기 ----------

def clean_delta(p: Project, d: StateDelta) -> None:
    """AI 가 낸 기한 정리: 빈 기한은 버리고, 같은 id 가 겹치면 뒤의 것을, 없는 기한을 닫으면 지운다."""
    seen: dict[str, Deadline] = {}
    for x in d.deadlines_added:
        if x.what.strip():
            x.id = x.id.strip() or new_id(p, d.episode, x.what, set(seen))
            seen[x.id] = x
    d.deadlines_added = list(seen.values())
    have = {x.id for x in p.timeline.deadlines} | set(seen)
    d.deadlines_done = [x for x in dict.fromkeys(d.deadlines_done) if x in have]
    if d.time.day < 0:
        d.time.day = 0


def apply_delta(p: Project, d: StateDelta) -> None:
    """승인된 변경안의 시점과 기한을 반영한다. pipeline.apply_delta 가 스냅샷을 찍기 전에 부른다."""
    n = d.episode
    p.episode(n).time = d.time.model_copy()
    by_id = {x.id: x for x in p.timeline.deadlines}
    for x in d.deadlines_added:
        cur = by_id.get(x.id)
        if cur is None:
            new = x.model_copy(update={"set_ep": n, "done_ep": 0})
            p.timeline.deadlines.append(new)
            by_id[new.id] = new
        else:
            cur.what, cur.day = x.what.strip() or cur.what, x.day or cur.day
            cur.note = x.note.strip() or cur.note
    for i in d.deadlines_done:
        if i in by_id and not by_id[i].done_ep:
            by_id[i].done_ep = n


def revert(p: Project, n: int, snap_deadlines: list[Deadline] | None) -> None:
    """pipeline.revert 에서 부른다. n화 뒤 화의 시점을 지우고, 기한은 n화 스냅샷으로 (예전 스냅샷이면 화 번호로) 돌린다."""
    for e in p.episodes:
        if e.plot.number > n:
            e.time = StoryTime()
    if snap_deadlines is not None:
        p.timeline.deadlines = [x.model_copy(deep=True) for x in snap_deadlines]
        return
    keep = [x for x in p.timeline.deadlines if x.set_ep <= n]
    for x in keep:
        if x.done_ep > n:
            x.done_ep = 0
    p.timeline.deadlines = keep


def new_id(p: Project, n: int, what: str, taken: set[str] | None = None) -> str:
    """dl-NN-k 형식. 한글 키워드는 id 에 쓰기 어려워 번호를 붙인다."""
    taken = (taken or set()) | {x.id for x in p.timeline.deadlines}
    word = re.sub(r"[^a-z0-9]+", "-", what.lower()).strip("-")[:16]
    base = f"dl-{n:02d}-{word}" if word else f"dl-{n:02d}"
    if base not in taken and word:
        return base
    k = 1
    while f"{base}-{k}" in taken:
        k += 1
    return f"{base}-{k}"


def _copies(p: Project, n: int) -> list[list[Deadline]]:
    """작가가 고친 기한을 함께 적을 곳: 지금 목록과 n화 이후 스냅샷 (그 뒤로 되돌려도 고친 것이 남게)."""
    out = [p.timeline.deadlines]
    for s in p.snapshots:
        if s.episode >= n and s.deadlines is not None:
            out.append(s.deadlines)
    return out


def last_done(p: Project) -> int:
    return max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)


def upsert(p: Project, x: Deadline) -> Deadline:
    """작가가 기한을 더하거나 고친다. 새 기한은 마지막으로 반영한 화에 생긴 것으로 본다."""
    what = x.what.strip()
    if not what:
        raise ValueError("무엇의 기한인지 적어 주세요")
    if x.day < 0:
        raise ValueError("날수는 0(모름) 이상이어야 해요")
    cur = next((d for d in p.timeline.deadlines if d.id == x.id), None) if x.id else None
    if cur is None:
        n = last_done(p)
        new = Deadline(id=new_id(p, n, what), what=what, day=x.day, note=x.note.strip(), set_ep=n, done_ep=x.done_ep)
        for lst in _copies(p, n):
            lst.append(new.model_copy())
        return new
    if x.done_ep and x.done_ep < cur.set_ep:
        raise ValueError(f"{cur.set_ep}화에 생긴 기한을 {x.done_ep}화에 닫을 수 없어요")
    for lst in _copies(p, 0):
        d = next((y for y in lst if y.id == cur.id), None)
        if d is not None:
            d.what, d.day, d.note, d.done_ep = what, x.day, x.note.strip(), x.done_ep
    return cur


def remove(p: Project, did: str) -> None:
    if not any(d.id == did for d in p.timeline.deadlines):
        raise ValueError(f"없는 기한이에요: {did}")
    p.timeline.deadlines = [d for d in p.timeline.deadlines if d.id != did]
    for s in p.snapshots:
        if s.deadlines is not None:
            s.deadlines = [d for d in s.deadlines if d.id != did]


# ---------- 화면 · 명령줄 ----------

def rows(p: Project) -> list[dict]:
    """화마다 플롯의 시점, 끝난 시점, 직전 화에서 지난 날 (날수를 아는 화끼리)."""
    out, last = [], 0
    for e in sorted(p.episodes, key=lambda x: x.plot.number):
        gap = e.time.day - last if e.time.day > 0 and last > 0 else None
        out.append({"episode": e.plot.number, "title": e.plot.title, "status": e.status, "plan": e.plot.time,
                    "time": e.time, "text": fmt(e.time), "gap": gap})
        if e.time.day > 0:
            last = e.time.day
    return out


def view(p: Project) -> dict:
    """시간 화면 계산값: 화별 시점, 기한(남은 날 포함), 지금 날수."""
    n = last_done(p) + 1
    day = current_day(p, n)
    items = []
    for d in sorted(p.timeline.deadlines, key=lambda d: (bool(d.done_ep), d.day <= 0, d.day, d.set_ep)):
        items.append({**d.model_dump(), "left": "" if d.done_ep else left(d, day)})
    prev = prev_end(p, n)
    return {"day": day, "now": fmt(prev[1]) if prev else "", "rows": rows(p), "deadlines": items}


def describe(p: Project) -> str:
    """명령줄 출력."""
    v = view(p)
    lines = [f"작품 속 시간 ({'켜짐' if enabled(p) else '꺼짐'})" + (f" · 기준: 1일째 = {p.timeline.start}" if p.timeline.start else "")]
    lines.append(f"지금: {v['now'] or '기록 없음'}")
    lines.append("")
    for r in v["rows"]:
        if not (r["text"] or r["plan"]):
            continue
        gap = f" (+{r['gap']}일)" if r["gap"] else ""
        plan = f" · 플롯: {r['plan']}" if r["plan"] else ""
        lines.append(f"{r['episode']:>4}화 {r['text'] or '-'}{gap}{plan}")
    if v["deadlines"]:
        lines.append("\n기한")
        for d in v["deadlines"]:
            state = f"{d['done_ep']}화에 닫힘" if d["done_ep"] else (d["left"] or "열림")
            lines.append(f"  {d['id']}: {d['what']}" + (f" ({d['day']}일째)" if d["day"] else "") + f" · {state}")
    return "\n".join(lines)
