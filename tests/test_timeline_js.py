"""작품 속 시간 화면(static/timeline.js)의 달력이 timeline.calendar · day_label · when 과 같게 세는지,
tlLeft · tlDay · tlPrev · tlIsOpen · tlFmt 가 left · current_day · prev_end · is_open · fmt 와 같은지,
상태 정리 경고에서 본문 문장을 찾는 passage.js warnQuote 가 맞게 찾는지. node 가 있을 때만 돈다."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from canon import timeline
from canon.schema import Deadline, Project, StoryTime

from .jsvm import dump, episode, needs_node, run_js

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"

# timeline.js · passage.js 가 기대는 app.js · chat.js 전역을 최소한으로 흉내 낸다
HARNESS = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const el = () => ({ appendChild() {}, set textContent(v) {} });
const ctx = {
  data, S: {}, actions: {}, CHAT_TOPICS: {}, P: () => data.project, ep: () => null, outlineSpy() {},
  document: { addEventListener() {}, createElement: el, head: el() },
};
vm.createContext(ctx);
for (const f of process.argv.slice(1)) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx);
vm.runInContext(`globalThis.out = {
  labels: data.cases.map((c) => { Object.assign(data.project.timeline, c); return [tlDated(), c.days.map(tlDayLabel), c.days.map(tlISO), c.days.map((d) => tlDayOf(tlISO(d)))]; }),
  whens: data.starts.map((c) => { Object.assign(data.project.timeline, c); return data.whens.map(tlWhen); }),
  quotes: data.warns.map((w) => warnQuote(w, data.text)),
};`, ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""

CASES = [
    ("", "2024-03-04"),  # 날짜 칸이 먼저
    ("2024년 5월 1일", "2024-03-04"),
    ("초봄", "2024-02-30"),  # 없는 날이면 글을 읽는다
    "1일째 월요일",
    "2024년 3월 4일 월요일, 초봄",  # 연도가 있으면 적은 요일보다 날짜가 이긴다
    "2024년 3월 4일 금요일",
    "3월 2일",
    "2월 29일 목요일",
    "2024년 12월 30일",
    "2월 30일 화요일",  # 없는 날: 요일만
    "초봄",
    "",
]
CASES = [c if isinstance(c, tuple) else (c, "") for c in CASES]
DAYS = [0, 1, 2, 7, 30, 59, 400]
TEXT = ("광장 게시판에 공고문이 붙어 있었다.\n"
        "'29일 후 금요일 오전 10시, 대성당 앞에서 선발 시험을 치른다.' 리안은 손가락으로 날짜를 짚었다. "
        "그는 고개를 끄덕였다.")
WARNS = [
    "시간/요일 모순: 본문 «29일 후 금요일 오전 10시, 대성당 앞에서 선발 시험을 치른다.» 의 요일이 맞지 않습니다.",
    "시간/요일 모순: 게시판 공고문에 '29일 후 금요일 오전 10시'라고 적혀 있습니다.",
    "요일 모순: «29일 뒤 금요일 오전 10시에 대성당 앞에서 선발 시험»",  # 조금 바꿔 옮김 → 겹치는 문장
    "플롯 사건 '시험 등록'이 빠졌습니다.",  # 본문 문장이 아님
    "설정 위반: 말투가 다릅니다.",
]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_timeline_js_calendar_and_warn_quote():
    p = Project()
    whens = [StoryTime(day=3, part="밤", label="수요일 비 옴"), StoryTime(day=3, part="밤", label="비 옴"),
             StoryTime(day=0, label="그날 밤"), StoryTime()]
    starts = [("2024년 3월 4일 월요일", ""), ("1일째 수요일", ""), ("", "2024-03-04")]
    data = {"project": json.loads(p.model_dump_json()), "cases": [{"start": s, "start_date": d, "days": DAYS} for s, d in CASES],
            "starts": [{"start": s, "start_date": d} for s, d in starts], "whens": [json.loads(t.model_dump_json()) for t in whens], "warns": WARNS, "text": TEXT}
    files = [str(STATIC / "timeline.js"), str(STATIC / "passage.js")]
    run = subprocess.run(["node", "-e", HARNESS, *files], input=json.dumps(data),
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)

    for (start, iso), (is_dated, labels, isos, back) in zip(CASES, out["labels"]):
        p.timeline.start, p.timeline.start_date = start, iso
        assert is_dated == timeline.dated(p) and labels == [timeline.day_label(p, d) for d in DAYS], (start, iso)
        first = timeline.calendar(p)[0]
        assert isos == [timeline.date_of(p, d).isoformat() if first and d > 0 else "" for d in DAYS]
        assert back == [d if first and d > 0 else 0 for d in DAYS]
    for (start, iso), got in zip(starts, out["whens"]):
        p.timeline.start, p.timeline.start_date = start, iso
        assert got == [timeline.when(p, t) for t in whens], (start, iso)
    assert out["whens"][0][:2] == ["3월 6일 수요일 밤 (3일째)", "3월 6일 수요일 밤 (3일째, 비 옴)"]
    assert out["whens"][1][1] == "3일째 밤 (금요일, 비 옴)"

    sentence = "'29일 후 금요일 오전 10시, 대성당 앞에서 선발 시험을 치른다.'"
    assert out["quotes"][0] == "29일 후 금요일 오전 10시, 대성당 앞에서 선발 시험을 치른다."
    assert out["quotes"][1] == "29일 후 금요일 오전 10시"
    assert out["quotes"][2] == sentence
    assert out["quotes"][3:] == ["", ""]


# tlCalendar 의 1일째 Date 를 timeline.calendar 와 같은 (ISO 날짜, 연도를 아는지, 요일) 로
CAL_ROW = ("const calRow = () => { const c = tlCalendar(); const f = c.first;"
           " return [f ? `${String(f.getUTCFullYear()).padStart(4, '0')}-${f.toISOString().slice(-19, -14)}` : null, c.year, c.wd]; };")
TIMES = [StoryTime(day=3, part="밤", label="비 옴"), StoryTime(day=0, part=" 새벽 "), StoryTime(label="그날"), StoryTime(),
         StoryTime(day=7), StoryTime(day=-1, label=" ")]
NS = [0, 1, 2, 3, 4, 5, 6, 9]


def _calendar_rows(p, cases):
    out = []
    for start, iso in cases:
        p.timeline.start, p.timeline.start_date = start, iso
        first, year, wd = timeline.calendar(p)
        out.append([first.isoformat() if first else None, year, wd])
    return out


def _js_calendar_rows(p, cases):
    expr = CAL_ROW + "S.project = data.project; data.cases.map((c) => { Object.assign(P().timeline, c); return calRow(); })"
    return run_js(["app.js", "timeline.js"], expr, {"project": dump(p), "cases": [{"start": s, "start_date": d} for s, d in cases]})


@needs_node
def test_timeline_js_calendar_left_day_match_server():
    p = Project(episodes=[episode(1, time=StoryTime(day=2)), episode(2, time=StoryTime(part="밤")), episode(3),
                          episode(6, time=StoryTime(day=9)), episode(5, time=StoryTime(day=6, label="장날"))])  # 4화는 없다
    assert _js_calendar_rows(p, CASES) == _calendar_rows(p, CASES)

    deadlines = [Deadline(id=f"d{i}", what="x", day=d, set_ep=s, done_ep=e)
                 for i, (d, s, e) in enumerate([(9, 0, 0), (4, 2, 0), (0, 1, 3), (6, 4, 4), (6, 5, 9)])]
    days = [-1, 0, 1, 4, 6, 9]
    data = {"project": dump(p), "times": [dump(t) for t in TIMES], "deadlines": [dump(d) for d in deadlines], "days": days, "ns": NS}
    out = run_js(["app.js", "timeline.js"], """S.project = data.project; ({
      fmt: data.times.map(tlFmt),
      day: data.ns.map(tlDay),
      prev: data.ns.map((n) => (tlPrev(n) || { plot: {} }).plot.number || null),
      left: data.deadlines.map((d) => data.days.map((x) => tlLeft(d, x))),
      open: data.deadlines.map((d) => data.ns.map((n) => tlIsOpen(d, n))),
    })""", data)
    assert out["fmt"] == [timeline.fmt(t) for t in TIMES]
    assert out["day"] == [timeline.current_day(p, n) for n in NS]
    assert out["prev"] == [(timeline.prev_end(p, n) or (None,))[0] for n in NS]
    assert out["left"] == [[timeline.left(d, x) for x in days] for d in deadlines]
    assert out["open"] == [[timeline.is_open(d, n) for n in NS] for d in deadlines]


@needs_node
@pytest.mark.xfail(strict=True, reason="어긋남: Python 정규식 \\d 는 전각 · 아랍 숫자도 읽고 JS 는 ASCII 만 읽는다. "
                   "0년은 JS Date 로는 만들어지고 Python date 로는 안 된다")
def test_timeline_js_calendar_edge_match_server():
    cases = [("２０２４년 ３월 ４일", ""), ("", "0000-03-04"), ("0년 3월 4일", "")]
    assert _js_calendar_rows(Project(), cases) == _calendar_rows(Project(), cases)


@needs_node
def test_timeline_js_groups_and_deadline_rows():
    """시간 흐름 묶음(tlGroups): 아크마다 줄, 날수를 아는 앞 화와의 차(gap), 거꾸로(back), 묶음 밖의 화.
    기한 줄(tlDeadlineRows): 지남 · 오늘 · 사흘 안 · 열림 · 날 모름 · 닫힘 차례와 꼬리 글."""
    from canon.schema import StoryArc
    days = {1: 1, 2: 3, 3: 0, 4: 2, 5: 5, 7: 9}  # 3화는 날 모름(회상), 4화는 2일째로 거꾸로
    eps = [episode(n, time=StoryTime(day=d)) for n, d in days.items()]
    eps.reverse()  # 화 순서가 섞여 있어도 화 번호 순으로 센다
    p = Project(episodes=eps)
    p.meta.form = "serial"
    p.story_arcs = [StoryArc(number=1, title="부두", start_ep=1, end_ep=3, goal=""), StoryArc(number=2, title="", start_ep=4, end_ep=5, goal="")]
    p.timeline.deadlines = [
        Deadline(id="a", what="지남", day=6, set_ep=1), Deadline(id="b", what="오늘", day=9, set_ep=2),
        Deadline(id="c", what="사흘 안", day=12, set_ep=1), Deadline(id="d", what="먼 날", day=30, set_ep=1),
        Deadline(id="e", what="모름", day=0, set_ep=1), Deadline(id="f", what="닫힘", day=2, set_ep=1, done_ep=2),
    ]
    expr = ("S.project = data; ({ groups: tlGroups(P()).map((g) => [g.key, g.label, g.s, g.e, g.rows.map((r) => [r.n, r.day, r.gap, r.back]), g.back, g.lo, g.hi]),"
            " rows: tlDeadlineRows(P().timeline.deadlines, 9).map((r) => [r.d.id, r.state, r.left]),"
            " none: tlDeadlineRows(P().timeline.deadlines, 0).map((r) => [r.d.id, r.state]) })")
    out = run_js(["app.js", "timeline.js"], expr, dump(p))
    assert out["groups"] == [
        ["a1", "아크 1 부두", 1, 3, [[1, 1, None, False], [2, 3, 2, False], [3, 0, None, False]], 0, 1, 3],
        ["a2", "아크 2", 4, 5, [[4, 2, -1, True], [5, 5, 3, False]], 1, 2, 5],
        ["rest", "그 밖의 화", 7, 7, [[7, 9, 4, False]], 0, 9, 9],
    ]
    assert out["rows"] == [["a", "overdue", "3일 지남"], ["b", "today", "오늘"], ["c", "soon", "3일 남음"],
                           ["d", "open", "21일 남음"], ["e", "unknown", "날 모름"], ["f", "closed", "2화에 닫힘"]]
    assert [s for _, s in out["none"]] == ["open", "open", "open", "open", "unknown", "closed"]  # 지금 날수를 모르면 남은 날을 세지 않는다
    for _, state, left in out["rows"][:4]:
        d = next(x for x in p.timeline.deadlines if x.id == _)
        assert left == timeline.left(d, 9)


@needs_node
def test_timeline_js_short_label():
    """tlShort: 날짜를 알면 '3월 21일 수', 연도가 바뀌면 연도를 붙이고, 날짜가 없으면 '18일째 · 토'(요일을 알 때)."""
    cases = [("", "2024-03-04"), ("2024년 12월 30일", ""), ("1일째 수요일", ""), ("", "")]
    expr = "S.project = data.project; data.cases.map((c) => { Object.assign(P().timeline, c); return [1, 3, 18, 0].map(tlShort); })"
    out = run_js(["app.js", "timeline.js"], expr, {"project": dump(Project()), "cases": [{"start": s, "start_date": d} for s, d in cases]})
    assert out == [["3월 4일 월", "3월 6일 수", "3월 21일 목", ""],
                   ["12월 30일 월", "2025년 1월 1일 수", "2025년 1월 16일 목", ""],
                   ["1일째 · 수", "3일째 · 금", "18일째 · 토", ""],
                   ["1일째", "3일째", "18일째", ""]]
