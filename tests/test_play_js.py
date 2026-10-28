"""플레이 화면 시계(static/play.js)의 규칙: 줄이 나타나는 시점, 닿음(see), 결정에서 멈춤, 자동 결정, 다음 결정까지, 끼어들기, 상태.
DOM 없는 순수 함수(playItems · playGap · playClockStart · playPhase · playTick · playClock)를 node 로 돌린다. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

FILES = ["app.js", "play.js"]
UNIT = 20000  # play.js PLAY_UNIT_MS
AUTO = 8000  # play.js PLAY_AUTO_MS


def _turn(n, days, choices=0, state="applied"):
    return {"number": n, "kind": "flow", "action": "", "beats": [{"when": f"{d}일째" if d else "", "day": d, "text": f"{n}-{i}"} for i, d in enumerate(days)],
            "scene": "장면" if choices else "", "choices": [f"선택 {k + 1}" for k in range(choices)], "state": state, "error": "", "ending": "",
            "when": "", "summary": ""}


# 시계를 움직이는 식. data: { turns, seen, steps: [[밀리초, 사건 | null], ...], clock?, v? }. 걸음마다 { pos, phase, see, want, auto } 를 모은다
SIM = """(() => {
  const items = playItems(data.turns);
  const last = data.turns.length ? data.turns[data.turns.length - 1] : null;
  let v = { items, last: last && { number: last.number, state: last.state, choices: last.choices.length > 0 }, seen: data.seen,
    ended: false, busy: false, jobError: false, autoDecide: false, unit: 'day', ...(data.v || {}) };
  let c = { ...playClockStart(items, data.seen, true, 1), ...(data.clock || {}) };
  const out = [];
  for (const [dt, ev] of data.steps) {
    if (ev) c = playClock(c, ev, v);
    const r = playTick(c, v, dt);
    c = r.c;
    if (r.see != null) v = { ...v, seen: Math.max(v.seen, r.see) };
    out.push({ pos: c.pos, phase: playPhase(c, v), see: r.see, want: r.want, auto: c.auto, speed: c.speed });
  }
  return out;
})()"""


@needs_node
def test_items_and_gaps():
    turns = [_turn(3, [1, 1, 3]), _turn(4, [4], choices=3), _turn(5, [0, 0])]
    items = run_js(FILES, "playItems(data)", turns)
    assert [(x["n"], x["kind"]) for x in items] == [(3, "beat")] * 3 + [(4, "beat"), (4, "decision"), (5, "beat"), (5, "beat")]
    gaps = run_js(FILES, "data.items.map((x, i) => playGap(data.items[i - 1], x, data.unit))", {"items": items, "unit": "day"})
    # 첫 줄 0, 같은 날 1, 이틀 뒤 2, 하루 뒤 1, 결정 0, 결정 바로 뒤(고른 결과) 0, 날을 모르면 1
    assert gaps == [0, 1, 2, 1, 0, 0, 1]
    far = run_js(FILES, "[playGap({kind:'beat',day:1},{kind:'beat',day:40},'day'), playGap({kind:'beat',day:1},{kind:'beat',day:61},'month'),"
                 " playGap({kind:'beat',day:1},{kind:'beat',day:1},'hour'), playGap({kind:'beat',day:1},{kind:'beat',day:2},'hour'),"
                 " playGap({kind:'beat',day:1},{kind:'beat',day:300},'year')]", None)
    assert far == [3, 2, 1, 3, 1]  # 칸 수는 3까지만, 시간 단위로 셈한다
    assert run_js(FILES, "playClockStart(playItems(data), 4).pos", turns) == 5  # 닿은 구간까지는 다 보인 채로 연다


@needs_node
def test_lines_appear_by_speed_and_report_seen():
    turns = [_turn(3, [1, 2, 3]), _turn(4, [4, 5])]
    got = run_js(FILES, SIM, {"turns": turns, "seen": 0, "steps": [[0, None], [UNIT - 1, None], [1, None], [UNIT, None],
                                                                   [0, {"type": "speed", "speed": 4}], [UNIT // 4, None], [UNIT // 4, None]]})
    assert [x["pos"] for x in got] == [1, 1, 2, 3, 3, 4, 5]
    assert [x["see"] for x in got] == [3, None, None, None, None, 4, None]  # 새 구간의 첫 줄이 보일 때만 알린다
    assert got[-1]["phase"] == "writing"  # 써 둔 줄 끝: 앞날을 쓰는 중
    paused = run_js(FILES, SIM, {"turns": turns, "seen": 0, "steps": [[0, None], [0, {"type": "toggle"}], [UNIT * 5, None]]})
    assert [x["pos"] for x in paused] == [1, 1, 1] and paused[-1]["phase"] == "paused"
    fast = run_js(FILES, SIM, {"turns": turns, "seen": 0, "steps": [[0, {"type": "faster"}], [0, {"type": "faster"}], [0, {"type": "faster"}],
                                                                    [0, {"type": "faster"}], [0, {"type": "slower"}]]})
    assert [x["speed"] for x in fast] == [2, 4, 8, 8, 4]


@needs_node
def test_decision_stops_and_auto_decide():
    turns = [_turn(3, [1]), _turn(4, [2, 3], choices=3)]
    got = run_js(FILES, SIM, {"turns": turns, "seen": 3, "clock": {"pos": 1}, "steps": [[UNIT * 10, None], [UNIT * 10, None]]})
    assert got[0]["pos"] == 4 and got[0]["phase"] == "decide" and got[0]["see"] == 4  # 결정 항목에서 멈춘다
    assert got[1]["pos"] == 4 and got[1]["want"] is None  # 자동 결정이 꺼져 있으면 기다린다
    auto = run_js(FILES, SIM, {"turns": turns, "seen": 4, "v": {"autoDecide": True}, "steps": [[3000, None], [AUTO - 3000 - 1, None], [1, None], [AUTO * 2, None]]})
    assert [x["want"] for x in auto] == [None, None, "auto", None]  # 8초를 센 뒤 한 번만
    assert auto[0]["auto"] == AUTO - 3000
    held = run_js(FILES, SIM, {"turns": turns, "seen": 4, "v": {"autoDecide": True}, "steps": [[3000, None], [0, {"type": "hold"}], [AUTO * 2, None]]})
    assert [x["want"] for x in held] == [None, None, None] and held[1]["auto"] is None  # 아무 키나 누르면 기다린다
    stopped = run_js(FILES, SIM, {"turns": turns, "seen": 4, "v": {"autoDecide": True}, "steps": [[0, {"type": "pause"}], [AUTO * 2, None]]})
    assert [x["want"] for x in stopped] == [None, None] and stopped[1]["phase"] == "decide"  # 멈춰 있으면 세지 않는다


@needs_node
def test_rush_and_act():
    turns = [_turn(3, [1, 2, 3]), _turn(4, [4, 5, 6], choices=2), _turn(5, [7])]
    got = run_js(FILES, SIM, {"turns": turns[:2], "seen": 0, "steps": [[0, {"type": "rush"}], [UNIT * 9, None]]})
    assert got[0]["pos"] == 7 and got[0]["phase"] == "decide" and got[0]["see"] == 4  # 다음 결정까지 기다리지 않는다
    # 끼어들기: 3구간 둘째 줄에서 행동 → 3구간 남은 줄을 다 보이고, 새 구간이 올 때까지 쓰는 중
    act = run_js(FILES, SIM, {"turns": turns[:1], "seen": 3, "clock": {"pos": 2}, "steps": [[0, {"type": "act"}], [UNIT * 5, None]]})
    assert [x["pos"] for x in act] == [3, 3] and [x["phase"] for x in act] == ["writing", "writing"]
    # 새 구간이 오면 act 표시를 지우고 다시 흐른다
    sync = run_js(FILES, """(() => {
      let v = { items: playItems(data.a), last: { number: 3, state: 'applied', choices: false }, seen: 3, unit: 'day' };
      let c = playClock(playClockStart(v.items, 3, true), { type: 'act' }, v);
      const before = playPhase(c, v);
      v = { ...v, items: playItems(data.b), last: { number: 4, state: 'pending', choices: false } };
      c = playClock(c, { type: 'sync' }, v);
      const r = playTick(c, v, 0);
      return [before, c.acted, r.c.pos, r.see];
    })()""", {"a": turns[:1], "b": [turns[0], {**_turn(4, [4, 5]), "kind": "free", "action": "바다로 뛰어든다"}]})
    assert sync == ["writing", None, 4, 4]  # 행동의 결과는 기다리지 않고 바로 보인다


@needs_node
def test_phases():
    base = """(() => { const items = playItems(data.turns); const t = data.turns[data.turns.length - 1];
      const v = { items, last: { number: t.number, state: t.state, choices: t.choices.length > 0 }, seen: t.number, unit: 'day', ...data.v };
      return playPhase({ ...playClockStart(items, t.number, true), ...(data.c || {}) }, v); })()"""
    assert run_js(FILES, base, {"turns": [_turn(3, [1], state="failed")], "v": {}}) == "failed"
    assert run_js(FILES, base, {"turns": [_turn(3, [1], state="failed")], "v": {"busy": True}}) == "writing"  # 다시 반영하는 중
    assert run_js(FILES, base, {"turns": [_turn(3, [1])], "v": {"ended": True}}) == "ended"
    assert run_js(FILES, base, {"turns": [_turn(3, [1])], "v": {"jobError": True}}) == "error"
    assert run_js(FILES, base, {"turns": [_turn(3, [1])], "v": {}, "c": {"run": False}}) == "paused"
    assert run_js(FILES, base, {"turns": [_turn(3, [1], choices=2)], "v": {}, "c": {"run": False}}) == "decide"  # 결정은 멈춤보다 앞선다
    assert run_js(FILES, base, {"turns": [_turn(3, [1, 2])], "v": {}, "c": {"pos": 1}}) == "flowing"


@needs_node
def test_retry_body():
    """다시 시도: 반영 실패면 반영만, 보낸 행동이 아직 구간이 되지 않았으면 그 행동, 이미 구간이 됐으면 흐름 (지난 선택지 번호를 다시 보내지 않는다)."""
    cases = [
        [{"number": 5, "state": "failed"}, {"body": {"choice": 2}, "at": 4}],
        [{"number": 4, "state": "applied"}, {"body": {"choice": 2}, "at": 4}],
        [{"number": 5, "state": "applied"}, {"body": {"choice": 2}, "at": 4}],
        [{"number": 5, "state": "applied"}, {"body": {"action": "바다로 뛰어든다"}, "at": 5}],
        [{"number": 5, "state": "applied"}, None],
        [None, {"body": {}, "at": 2}],
    ]
    got = run_js(FILES, "data.map(([t, a]) => playRetryBody(t, a))", cases)
    assert got == [{}, {"choice": 2}, {}, {"action": "바다로 뛰어든다"}, {}, {}]
