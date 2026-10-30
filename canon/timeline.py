"""작품 속 시간: 화가 끝난 시점(Episode.time)과 앞으로 올 기한(Timeline.deadlines)을 기록한다.

AI 는 상태 변경안에 이번 화가 끝난 시점(며칠째, 시간대)과 새 기한만 적고, 남은 날은 Canon 이 계산한다.
쓰기 · 검수 · 플롯 프롬프트에는 직전 화 끝 시점, 이번 화 플롯의 시점, 열린 기한 몇 줄만 넣어 화수가 늘어도 크기가 일정하다.
줄거리 요약 줄에는 화가 끝난 시점을 짧게 붙인다(tag). 반영은 승인 후. LLM 을 부르지 않는다.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

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


# ---------- 달력: 기준(start)에서 날짜 · 요일 계산 ----------
# AI 는 날짜 셈을 자주 틀린다(월요일에서 29일 뒤를 금요일로). 기준에 날짜나 요일이 있으면 Canon 이 센다.
# 화면 tlCalendar · tlDayLabel(static/timeline.js)과 같은 규칙이라 함께 고친다.

WEEKDAYS = "월화수목금토일"
_YMD = re.compile(r"(\d{1,4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_MD = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_WD = re.compile(r"([월화수목금토일])요일")
_DATE_WORDS = re.compile(r"\d+\s*(?:년|월|일)|요일")


def _date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


_ISO = re.compile(r"^\s*(\d{1,4})-(\d{1,2})-(\d{1,2})\s*$")


def calendar(p: Project) -> tuple[date | None, bool, int | None]:
    """(1일째 날짜, 연도를 아는지, 1일째 요일 0=월). 날짜 칸(start_date, YYYY-MM-DD)이 먼저이고, 없으면 기준 글(start)에서 읽는다.
    글에 연도 없이 '3월 2일'만 있으면 2001년(2월 29일은 2000년)으로 센다. 연도가 있으면 요일은 날짜로 계산하고, 적은 요일은 무시한다. 모르면 None."""
    m = _ISO.match(p.timeline.start_date)
    first = m and _date(*map(int, m.groups()))
    if first:
        return first, True, first.weekday()
    text = p.timeline.start
    wd_m = _WD.search(text)
    wd = WEEKDAYS.index(wd_m.group(1)) if wd_m else None
    m = _YMD.search(text)
    if m:
        first = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return (first, True, first.weekday()) if first else (None, False, wd)
    m = _MD.search(text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        return _date(2000 if (mo, d) == (2, 29) else 2001, mo, d), False, wd
    return None, False, wd


def dated(p: Project) -> bool:
    """1일째 날짜를 알아 화마다 날짜로 보이는지."""
    return calendar(p)[0] is not None


def date_of(p: Project, day: int) -> date | None:
    first = calendar(p)[0]
    return first + timedelta(days=day - 1) if first and day > 0 else None


def start_text(p: Project) -> str:
    """기준 한 줄: '2024년 3월 4일 월요일 (초봄)'. 날짜 칸이 없으면 기준 글 그대로."""
    m = _ISO.match(p.timeline.start_date)
    first = m and _date(*map(int, m.groups()))
    note = p.timeline.start.strip()
    if not first:
        return note
    head = f"{first.year}년 {first.month}월 {first.day}일 {WEEKDAYS[first.weekday()]}요일"
    return f"{head} ({note})" if note else head


def day_label(p: Project, day: int) -> str:
    """날수의 날짜와 요일 ('3월 31일 화요일', 해가 바뀌면 '2025년 1월 2일 목요일', 요일만 알면 '화요일'). 모르면 빈 문자열."""
    if day <= 0:
        return ""
    first, has_year, wd = calendar(p)
    parts = []
    if first:
        x = first + timedelta(days=day - 1)
        parts.append(f"{x.year}년 {x.month}월 {x.day}일" if has_year and x.year != first.year else f"{x.month}월 {x.day}일")
    if wd is not None:
        parts.append(WEEKDAYS[(wd + day - 1) % 7] + "요일")
    return " ".join(parts)


def day_from_text(p: Project, text: str, near: int = 0) -> int:
    """글에 나온 날짜('3월 10일', '2024년 3월 10일')의 날수. 날짜를 모르는 작품이거나 1일째보다 앞이면 0.
    연도가 없으면 near(지금 날수) 이후 가장 가까운 그 날로 본다."""
    first = calendar(p)[0]
    if not first or not text:
        return 0
    m = _YMD.search(text)
    if m:
        x = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    else:
        m = _MD.search(text)
        if not m:
            return 0
        ref = first + timedelta(days=max(near, 1) - 1)
        tries = [_date(y, int(m.group(1)), int(m.group(2))) for y in (ref.year - 1, ref.year, ref.year + 1)]
        tries = [t for t in tries if t]
        later = [t for t in tries if t >= ref]
        x = min(later) if later else (max(tries) if tries else None)
    day = (x - first).days + 1 if x else 0
    return day if day > 0 else 0


def when(p: Project, t: StoryTime | None) -> str:
    """시점 한 줄. 날짜를 알면 날짜가 앞('3월 6일 수요일 밤 (3일째)'), 요일만 알면 '3일째 밤 (수요일)'.
    AI 가 적은 날짜 · 요일 글은 계산한 것으로 바꾸고 계절 같은 글만 남긴다."""
    if t is None:
        return ""
    cal = day_label(p, t.day)
    if not cal:
        return fmt(t)
    extra = t.label.strip()
    extra = extra if extra and not _DATE_WORDS.search(extra) else ""
    if dated(p):
        return f"{' '.join(x for x in (cal, t.part.strip()) if x)} ({t.day}일째{f', {extra}' if extra else ''})"
    head = " ".join(x for x in (f"{t.day}일째", t.part.strip()) if x)
    return f"{head} ({cal}{f', {extra}' if extra else ''})"


def weekday_hint(p: Project, day: int, weeks: int = 5) -> str:
    """'2일째는 화요일. 같은 요일: 9 · 16 · 23 · 30 · 37일째'. 날짜를 알면 '오늘(2일째)은 3월 5일 화요일. 같은 요일: 3월 12일 · …'.
    요일을 모르면 빈 문자열."""
    _, _, wd = calendar(p)
    if wd is None or day <= 0:
        return ""
    if dated(p):
        same = " · ".join(day_label(p, day + 7 * k).rsplit(" ", 1)[0] for k in range(1, weeks + 1))
        return f"오늘({day}일째)은 {day_label(p, day)}. 같은 요일: {same}"
    same = " · ".join(str(day + 7 * k) for k in range(1, weeks + 1))
    return f"{day}일째는 {WEEKDAYS[(wd + day - 1) % 7]}요일. 같은 요일: {same}일째"


def known(t: StoryTime | None) -> bool:
    return bool(t and (t.day > 0 or t.part.strip() or t.label.strip()))


def tag(p: Project, e: Episode) -> str:
    """줄거리 요약 줄 앞에 붙일, 그 화가 끝난 시점 ('[3일째 밤] '). 꺼졌거나 모르면 빈 문자열."""
    if not enabled(p) or not known(e.time):
        return ""
    t = e.time
    x = date_of(p, t.day)
    day = f"{x.month}월 {x.day}일" if x else f"{t.day}일째" if t.day > 0 else ""  # 줄마다 붙어 요일 · 날짜 글은 뺀다
    short = " ".join(y for y in (day, t.part.strip()) if y) or t.label.strip()
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


def deadline_line(d: Deadline, day: int, ids: bool = False, p: Project | None = None) -> str:
    """'- 왕성 축제 첫날 (3월 10일 일요일, 6일 남음, '사흘 뒤')'. 날짜를 모르면 '9일째'. ids 는 상태 변경안처럼 id 로 가리켜야 할 때만."""
    cal = day_label(p, d.day) if p is not None else ""
    if d.day <= 0:
        at = ""
    elif p is not None and dated(p):
        at = f"{cal} = {d.day}일째" if ids else cal  # 상태 변경안은 날수로 적으니 날수도
    else:
        at = f"{d.day}일째" + (f" = {cal}" if cal else "")
    extra = ", ".join(x for x in (at, left(d, day), d.note.strip() and f"'{d.note.strip()}'") if x)
    return f"- {d.what}{f' ({extra})' if extra else ''}{f' [{d.id}]' if ids else ''}"


def deadline_lines(p: Project, n: int, budget: int = 0, ids: bool = False) -> tuple[list[str], int]:
    """열린 기한 줄과 예산(context.BUDGET["deadlines"]) 때문에 뺀 수. 지난 기한 → 가까운 기한 순으로 넣고 먼 것부터 뺀다.
    단편도 같은 예산을 쓴다 (기한은 화수와 상관없이 쌓일 수 있다)."""
    budget = budget or context.BUDGET["deadlines"]
    day = current_day(p, n)
    rows, size, cut = [], 0, 0
    for d in open_deadlines(p, n):
        line = deadline_line(d, day, ids, p)
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
    hint = weekday_hint(p, current_day(p, n) or (1 if n == 1 else 0))  # 1화는 1일째에서 시작한다
    if not (prev or plan or rows or hint):
        return ""
    lines = []
    if start_text(p):
        lines.append(f"기준: 1일째 = {start_text(p)}")
    if prev:
        gap = "" if prev[0] == n - 1 else f" ({prev[0] + 1}화는 시점 기록 없음)" if prev[0] == n - 2 else f" ({prev[0] + 1}~{n - 1}화는 시점 기록 없음)"
        lines.append(f"직전 화({prev[0]}화) 끝: {when(p, prev[1])}{gap}")
    lines.append(f"이번 화 플롯의 시점: {plan}" if plan else "이번 화 플롯의 시점: 따로 없음 (직전 화 끝에서 바로 이어짐)")
    if hint:
        lines.append(f"요일 셈: {hint}")
    if rows:
        lines.append(f"열린 기한{f' (먼 것 {cut}개 생략)' if cut else ''}:")
        lines += rows
    lines.append("- 지난 시간에 맞게 빛, 날씨, 계절, 피로, 상처, 배고픔이 달라집니다. 인물이 기한까지 남은 날을 말하면 위 날수와 맞춥니다."
                 + (" 본문에서 날짜나 요일을 새로 말할 때는 위 요일 셈과 날짜를 따릅니다 (N일 뒤는 날수에 N을 더한 날)." if hint else ""))
    return "\n".join(lines)


def plan_block(p: Project, n: int, rule: str | None = None) -> str:
    """플롯 기획에 넣는 블록: n화 직전 시점과 열린 기한. 꺼졌거나 없으면 빈 문자열.
    rule 은 끝 줄의 지시 (비우면 화별 플롯의 time 칸 지시. 다음 아크 기획처럼 time 칸이 없는 응답은 따로 준다)."""
    if not enabled(p):
        return ""
    prev = prev_end(p, n)
    rows, cut = deadline_lines(p, n)
    if not (prev or rows):
        return ""
    lines = [f"{prev[0]}화 끝: {when(p, prev[1])}"] if prev else []
    if rows:
        lines.append(f"열린 기한{f' (먼 것 {cut}개 생략)' if cut else ''}:")
        lines += rows
    lines.append(rule if rule is not None else "- 화마다 time 칸에 " + ("시점을 적고(직전 화에서 얼마나 지났는지나 '3월 8일 아침' 같은 날짜)" if dated(p) else "직전 화에서 얼마나 지났는지 적고")
                 + ", 기한이 있으면 그 날에 맞게 사건을 놓습니다.")
    return "\n".join(lines)


def state_block(p: Project, n: int) -> str:
    """상태 변경안 프롬프트의 [작품 속 시간] 자료. 꺼졌으면 빈 문자열."""
    if not enabled(p):
        return ""
    prev = prev_end(p, n)
    plan = _plot_time(p, n)
    rows, cut = deadline_lines(p, n, ids=True)
    lines = []
    if start_text(p):
        lines.append(f"기준: 1일째 = {start_text(p)}")
    lines.append(f"직전 화({prev[0]}화) 끝: {when(p, prev[1])}" if prev else "앞 화 시점 기록 없음")
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
            + ("label 에는 계절이나 날씨처럼 날짜 밖의 것만 적습니다(날짜 · 요일은 기준으로 Canon 이 계산합니다). " if calendar(p) != (None, False, None)
               else "label 은 본문이나 기준에서 드러난 날짜 · 요일 · 계절만 적습니다. ")
            + "회상 · 외전처럼 메인 시간 밖의 화면 메인 시간 기준으로 적습니다(보통 직전 화 끝 그대로)."
            f"\n- 본문에서 앞으로 올 날이 정해지면(축제, 결혼식, '사흘 안에' 같은 약속이나 마감) deadlines_added 에 넣습니다. id 는 dl-{n:02d}-키워드, "
            "day 는 그날의 날수, note 는 본문에 나온 말 그대로입니다" + ("(본문에 '3월 10일'처럼 날짜가 나오면 그 말을 note 에 넣습니다. 날수는 Canon 이 날짜로 다시 셉니다)" if dated(p) else "") + ". "
            " 열린 기한의 날이 바뀌면 같은 id 로 넣고, 그날이 와서 일이 일어났거나 기한이 없어졌으면 deadlines_done 에 id 를 넣습니다."
            "\n- 본문 속 시간이 직전 화 끝이나 열린 기한과 어긋나면(밤이었는데 설명 없이 낮, 남은 날 수나 요일이 틀림) warnings 에 적고, 어긋난 본문 문장을 «» 안에 글자 그대로 넣습니다.")


def check_rule(p: Project, n: int) -> str:
    """검수 확인 목록에 붙는 줄. 넣은 시간 블록이 없으면 빈 문자열."""
    if not episode_block(p, n):
        return ""
    return ("\n- 작품 속 시간: 위 '작품 속 시간'의 직전 화 끝 시점, 이번 화 플롯의 시점, 기한까지 남은 날과 어긋나는지, "
            "한 화 안에서 시간대가 설명 없이 뒤바뀌는지(밤 장면이 다음 문단에 한낮), 지난 시간에 맞지 않는 상처 · 날씨 · 계절이 있는지 봅니다. "
            "날짜 · 요일은 직접 셈하지 말고 위 요일 셈과 날짜를 근거로 봅니다. "
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
    if dated(p):  # 본문에 나온 날짜가 있으면 AI 가 센 날수 대신 날짜로 센다
        near = d.time.day or current_day(p, d.episode)
        for x in d.deadlines_added:
            x.day = day_from_text(p, x.note, near) or day_from_text(p, x.what, near) or x.day
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
                    "time": e.time, "text": when(p, e.time), "gap": gap})
        if e.time.day > 0:
            last = e.time.day
    return out


def view(p: Project) -> dict:
    """시간 화면 계산값: 화별 시점, 기한(남은 날 포함), 지금 날수."""
    n = last_done(p) + 1
    day = current_day(p, n)
    items = []
    for d in sorted(p.timeline.deadlines, key=lambda d: (bool(d.done_ep), d.day <= 0, d.day, d.set_ep)):
        items.append({**d.model_dump(), "date": day_label(p, d.day), "left": "" if d.done_ep else left(d, day)})
    prev = prev_end(p, n)
    return {"day": day, "now": when(p, prev[1]) if prev else "", "dated": dated(p), "rows": rows(p), "deadlines": items}


def describe(p: Project) -> str:
    """명령줄 출력."""
    v = view(p)
    lines = [f"작품 속 시간 ({'켜짐' if enabled(p) else '꺼짐'})" + (f" · 기준: 1일째 = {start_text(p)}" if start_text(p) else "")]
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
            at = (d["date"] if v["dated"] else f"{d['day']}일째") if d["day"] else ""
            lines.append(f"  {d['id']}: {d['what']}" + (f" ({at})" if at else "") + f" · {state}")
    return "\n".join(lines)
