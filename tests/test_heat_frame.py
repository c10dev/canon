"""완급 계획의 웹소설 판 (docs/webnovel/specs/09-heat-frame.md): 웹소설 틀 장편만 heat_rules · 경고 · 밑그림이 갈리고,
드라마 틀 · 단편 · 완급 계획을 끈 작품은 그대로인지 본다. 드라마 틀 요청의 글자는 tests/test_prompt_registry.py 의 스냅샷이 본다."""
from canon import heatplan, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Foreshadow, HeatStep, HeatTurn

from . import test_prompt_registry as reg
from .jsvm import dump, needs_node, run_js
from .test_serial import _plan_arc, _serial

FILES = ["app.js", "home.js", "plot.js", "heatplan.js"]


def _arc_work(frame: str, shape: list[tuple[int, str, str]] | None = None):
    """60화 장편의 첫 아크(1~12화)에 열 계획을 둔 작품. shape 는 화마다 (열, 몫, 정점 종류).
    기본 shape 는 웹소설 판 규칙을 따른다: 쌓기 · 미루기 1~3화, 작은 터뜨리기, 끝의 큰 정점, 뒤집힘 없음."""
    p = _serial(60)
    p.meta.frame = frame
    a = _plan_arc(p)
    shape = shape or [(1, "build", ""), (1, "build", ""), (2, "hold", ""), (3, "peak", "첫 사냥"), (1, "after", ""), (1, "build", ""),
                      (2, "hold", ""), (3, "peak", "길드 시험"), (1, "after", ""), (2, "hold", ""), (5, "peak", "관객 앞 승급"), (1, "after", "")]
    a.heat = [HeatStep(ep=a.start_ep + i, level=lv, role=r, kind=k) for i, (lv, r, k) in enumerate(shape)]
    a.heat_turn = HeatTurn()
    big = a.start_ep + 10
    p.foreshadows += [Foreshadow(id="s1", description="잃을 수 있는 등급", planted_ep=a.start_ep + 1, kind="stake"),
                      Foreshadow(id="c1", description="시험 시한", planted_ep=a.start_ep + 2, kind="constraint")]
    p.episode(big).plot.foreshadow_payoff = ["s1", "c1"]
    return p, a


def test_web_gate_is_serial_webnovel_like_arc_axes():
    for form in ("short", "serial"):
        for frame in ("drama", "webnovel"):
            p = prompts.Project()
            p.meta.form, p.meta.frame = form, frame
            assert heatplan.web(p) == prompts.arc_axes(p)[0] == (form == "serial" and frame == "webnovel")


def test_drama_heat_rules_are_the_old_text():
    old = prompts.heat_rules("1화부터 16화까지", 16, "요구사항:")
    assert old == prompts.heat_rules("1화부터 16화까지", 16, "요구사항:", False)
    assert "앞쪽 40~50%" in old and "승 구간 끝에 낮은 정점" in old and "정점마다 그 전 화에 심은 stake" in old
    assert not any(x in old for x in (prompts.HEAT_WEB_BLOCK, prompts.HEAT_WEB_SMALL, prompts.HEAT_WEB_PROP, prompts.HEAT_WEB_TURN))


def test_web_heat_rules_lines():
    for size in (8, 16):
        web = prompts.heat_rules("아크 첫 화(21화)부터 아크 끝 화(arc.end_ep)까지", size, "요구사항:", True)
        assert prompts.HEAT_WEB_BLOCK in web and prompts.HEAT_WEB_SMALL in web and prompts.HEAT_WEB_PROP in web and web.endswith(prompts.HEAT_WEB_TURN)
        assert "40~50%" not in web and "정점은 하나만" not in web and "낮은 정점" not in web and "정점마다" not in web
        assert "마다" not in prompts.HEAT_WEB_BLOCK + prompts.HEAT_WEB_SMALL  # '몇 화마다' 꼴의 빈도 규칙을 넣지 않는다
    assert f"1~{heatplan.LONG_BLOCK}화" in prompts.HEAT_WEB_BLOCK and prompts.ARC_SHORT_BLOCK.endswith("1~3화로 짧게 둡니다.")


def test_short_webnovel_with_heat_on_is_drama():
    p = reg._short()
    p.meta.frame = "webnovel"
    assert reg._heat_requests(reg._short()) == reg._heat_requests(p)


def test_serial_webnovel_requests_use_web_lines():
    drama, web = reg._heat_requests(reg._long()), reg._heat_requests(reg._web(reg._long))
    for k in ("heat_ask", "heat_plan_arc", "heat_propose"):
        assert prompts.HEAT_WEB_BLOCK in web[k] and prompts.HEAT_WEB_BLOCK not in drama[k], k
    assert f"- {prompts.HEAT_WEB_PAYOFF}의 foreshadow_payoff" in web["heat_plot_rules"]
    assert "- 터뜨리기 화의 foreshadow_payoff" in drama["heat_plot_rules"] and prompts.HEAT_WEB_PAYOFF not in drama["heat_plot_rules"]


def test_write_side_heat_line_is_the_same_in_both_frames():
    """쓰기 · 스토리보드 · 큐 시트의 이번 화 열 줄(HEAT_ROLE_GUIDE)은 틀이 같은 계획이면 같다 (정할 것 9)."""
    p, a = _arc_work("webnovel")
    q = p.model_copy(deep=True)
    q.meta.frame = "drama"
    for n in range(a.start_ep, a.end_ep + 1):
        assert prompts.heat_step_line(p, n) == prompts.heat_step_line(q, n)
    n = a.start_ep + 3
    assert prompts.build_episode_context(p, n) == prompts.build_episode_context(q, n)
    assert prompts.cue_sheet_prompt(p, n) == prompts.cue_sheet_prompt(q, n)


def test_rule_following_web_arc_has_no_warnings_but_drama_warns():
    p, _ = _arc_work("webnovel")
    assert heatplan.warnings(p) == []
    q, a = _arc_work("drama")
    assert _codes(q) == [(a.start_ep + 3, "no_pressure"), (a.start_ep + 7, "no_pressure")]  # 드라마 판은 작은 터뜨리기에도 관객 · 제약을 찾는다


def _codes(p):
    return [(w.ep, w.code) for w in heatplan.warnings(p)]


def test_long_block_boundary_and_frame():
    three = [(1, "build", ""), (1, "build", ""), (2, "hold", ""), (3, "peak", "첫 사냥")] + [(1, "after", "")] * 6 + [(5, "peak", "승급"), (1, "after", "")]
    four = [(1, "build", ""), (1, "build", ""), (2, "hold", ""), (2, "hold", ""), (3, "peak", "첫 사냥")] + [(1, "rest", "")] * 5 + [(5, "peak", "승급"), (1, "after", "")]
    p, a = _arc_work("webnovel", three)
    assert "long_block" not in {c for _, c in _codes(p)}
    p, a = _arc_work("webnovel", four)
    got = [w for w in heatplan.warnings(p) if w.code == "long_block"]
    assert [(w.ep, w.text.split("화에")[0]) for w in got] == [(a.start_ep, f"{a.start_ep}~{a.start_ep + 3}")]
    assert heatplan.WARN_CODES["long_block"] == "긴 고구마"
    q, _ = _arc_work("drama", four)
    assert "long_block" not in {c for _, c in _codes(q)}  # 드라마 판은 앞쪽 쌓기가 원래 길다


def test_after_and_rest_break_the_block_and_end_counts():
    shape = [(1, "build", ""), (1, "hold", ""), (1, "build", ""), (1, "rest", ""), (1, "build", ""), (1, "build", ""), (1, "hold", ""),
             (3, "peak", "a"), (1, "build", ""), (1, "build", ""), (2, "hold", ""), (2, "hold", "")]
    p, a = _arc_work("webnovel", shape)
    assert [ep for ep, c in _codes(p) if c == "long_block"] == [a.start_ep + 8]  # 끝까지 이어진 쌓기 · 미루기도 센다


def test_web_skips_flat():
    """실측 웹소설 판 세 계획이 모두 기복 경고에 걸렸다 (정할 것 11). 웹소설 판은 기복을 보지 않는다."""
    flat = [(2, "build", ""), (2, "hold", ""), (3, "peak", "a"), (2, "after", ""), (2, "build", ""), (2, "hold", ""), (3, "peak", "b"),
            (2, "after", ""), (2, "build", ""), (2, "hold", ""), (5, "peak", "c"), (2, "after", "")]
    p, a = _arc_work("webnovel", flat)
    q, _ = _arc_work("drama", flat)
    assert "flat" not in {c for _, c in _codes(p)} and (a.start_ep, "flat") in _codes(q)


def test_web_checks_stake_and_pressure_only_on_the_big_peak():
    p, a = _arc_work("webnovel")
    p.episode(a.start_ep + 10).plot.foreshadow_payoff = []
    assert {(ep, c) for ep, c in _codes(p)} == {(a.start_ep + 10, "no_pressure")}
    p.foreshadows = [f for f in p.foreshadows if f.id != "s1"]
    assert (a.start_ep + 10, "no_stake") in _codes(p) and all(ep == a.start_ep + 10 for ep, _ in _codes(p))


def test_web_shape_and_mock_plan():
    steps = [HeatStep(ep=n, level=1, role="build" if n % 5 else "hold") for n in range(1, 12)]
    got = heatplan.web_shape(steps)
    assert [s.role for s in got] == ["build", "build", "build", "peak", "hold", "build", "build", "peak", "build", "hold", "build"]
    assert [s.ep for s in got] == list(range(1, 12)) and got[3].level == heatplan.WEB_SMALL_LEVEL and got[3].kind == ""
    p = _serial(60)
    p.meta.frame = "webnovel"
    a = _plan_arc(p)
    prop = pipeline.propose_heat(MockLLM(), p, a.number)
    assert prop.heat_turn.plant_ep == 0 and "long_block" not in {c for _, c in _codes_after(p, prop, a)}
    p.settings.heat_plan = True
    arc = pipeline.plan_next_arc(MockLLM(), p).arc
    assert arc.heat_turn.plant_ep == 0 and max(_block_runs(arc.heat)) <= heatplan.LONG_BLOCK


def _codes_after(p, prop, a):
    pipeline.apply_heat_plan(p, prop, a)
    return _codes(p)


def _block_runs(steps):
    runs, n = [0], 0
    for s in steps:
        n = n + 1 if s.role in heatplan.BLOCK_ROLES else 0
        runs.append(n)
    return runs


def test_heat_off_webnovel_serial_has_no_heat_lines():
    p = reg._web(reg._long)
    assert not p.settings.heat_plan and heatplan.scopes(p) == []
    assert "열 계획" not in prompts.arc_ask(p)[0] and heatplan.warnings(p) == []


@needs_node
def test_js_warnings_and_shape_match_python():
    cases = [_arc_work("webnovel")[0], _arc_work("drama")[0]]
    four = [(1, "build", ""), (1, "build", ""), (2, "hold", ""), (2, "hold", ""), (3, "peak", "첫 사냥")] + [(1, "rest", "")] * 5 + [(5, "peak", "승급"), (1, "after", "")]
    cases += [_arc_work("webnovel", four)[0], _arc_work("drama", four)[0]]
    flat = [(2, "build", ""), (2, "hold", ""), (3, "peak", "a"), (2, "after", "")] * 2 + [(2, "build", ""), (2, "hold", ""), (5, "peak", "c"), (2, "after", "")]
    cases += [_arc_work("webnovel", flat)[0], _arc_work("drama", flat)[0]]
    p, a = _arc_work("webnovel")
    p.episode(a.start_ep + 10).plot.foreshadow_payoff = []
    cases.append(p)
    steps = [HeatStep(ep=n, level=1, role=("build", "hold", "rest")[n % 3] if n > 6 else "build") for n in range(1, 16)]
    got = run_js(FILES, "({ w: data.cases.map((p) => heatWarnings(p)), s: heatWebShape(data.steps), web: data.cases.map(heatWeb) })",
                 {"cases": [dump(c) for c in cases], "steps": [s.model_dump() for s in steps]})
    assert got["w"] == [[w.model_dump() for w in heatplan.warnings(c)] for c in cases]
    assert any(got["w"]) and any("long_block" == w["code"] for ws in got["w"] for w in ws)
    assert got["s"] == [s.model_dump() for s in heatplan.web_shape(steps)]
    assert got["web"] == [True, False, True, False, True, False, True]


@needs_node
def test_js_start_lays_web_shape_on_web_arc():
    expr = """(() => { S.name = 'g'; S.route = ['p', 'g', 'arc']; S.project = data.p; render = () => {}; markDirty = () => {};
      S.selArc = data.n; actions.heatStart(); return S.project.story_arcs[0].heat; })()"""
    for frame in ("drama", "webnovel"):
        p = _serial(60)
        p.meta.frame = frame
        a = _plan_arc(p)
        got = [HeatStep(**s) for s in run_js(FILES, expr, {"p": dump(p), "n": a.number})]
        assert [s.ep for s in got] == list(range(a.start_ep, a.end_ep + 1))
        if frame == "webnovel":
            assert max(_block_runs(got)) <= heatplan.LONG_BLOCK and len(heatplan.peak_runs(got)) >= 2
        else:
            assert max(_block_runs(got)) > heatplan.LONG_BLOCK  # 드라마 밑그림은 그대로
