"""열 계획 카드(static/heatplan.js)가 heatplan.py 와 같은 경고 · 재기를 내는지, 카드가 그려지는지 node 로 맞춰 본다. node 가 있을 때만 돈다."""
from canon import heatplan
from canon.schema import Cue, CueSheet, HeatStep, HeatTurn

from .jsvm import dump, needs_node, run_js
from .test_heatplan import SHAPE, _work

FILES = ["app.js", "home.js", "plot.js", "heatplan.js"]


def _cases():
    flat = [(2, "build"), (2, "build"), (2, "build"), (3, "peak"), (2, "after"), (2, "hold"), (3, "peak"), (2, "after")]
    late = _work()
    late.heat_turn = HeatTurn(plant_ep=5, fail_ep=7, gain="백업")
    hot = _work()
    hot.episodes[1].cue_sheet = CueSheet(cues=[Cue(tension=2), Cue(tension=4)])
    return [
        _work(),
        _work(flat),
        _work([(0, "build"), (4, "peak")] + SHAPE[2:], pays={2: ["a1"], 4: ["s1", "a1"], 5: ["a1"], 7: ["s2", "c1"]}),
        _work(pays={4: ["s1"], 5: [], 7: ["s2", "c1"]}),
        _work(kinds={4: "흥정", 7: " 흥정 "}, pays={4: ["s1", "a1"], 5: ["a1"], 7: ["s1", "c1"]}),
        _work(pays={4: ["s1", "a1"], 7: ["s2", "c1"]}),
        late,
        hot,
    ]


@needs_node
def test_warnings_match_python():
    cases = _cases()
    got = run_js(FILES, "data.cases.map((p) => heatWarnings(p))", {"cases": [dump(p) for p in cases]})
    want = [[w.model_dump() for w in heatplan.warnings(p)] for p in cases]
    assert got == want
    assert any(want)  # 경고가 나는 경우가 섞여 있다


@needs_node
def test_density_and_cue_tension_match_python():
    sheets = [CueSheet(cues=[Cue(tension=1, length=100), Cue(tension=5, length=300)]), CueSheet(cues=[Cue(tension=2), Cue(tension=4)]),
              CueSheet(cues=[Cue(tension=5)], skipped=True), CueSheet(cues=[Cue(tension=3, length=333), Cue(tension=4, length=101)])]
    texts = [("숨 숨 결", ["숨"]), ("떨리는 숨이 떨렸다\n\n떨림", ["떨리", "떨림", " "]), ("", ["숨"]), ("숨", [])]
    got = run_js(FILES, "({ t: data.sheets.map(heatCueTension), d: data.texts.map(([a, b]) => heatDensity(a, b)) })",
                 {"sheets": [dump(s) for s in sheets], "texts": texts})
    assert got["t"] == [heatplan.cue_tension(s) for s in sheets]
    assert got["d"] == [heatplan.density(a, b) for a, b in texts]


@needs_node
def test_default_shape_covers_every_episode_and_passes_fit():
    for total in (8, 12, 16, 20):
        p = _work()
        p.meta.target_episodes = total
        from canon import pipeline
        p.arc = [type(p.arc[0])(name=n, start_ep=s, end_ep=e, goal="") for n, (s, e) in zip("기승전결", pipeline.act_ranges(total))]
        steps = [HeatStep(**s) for s in run_js(FILES, "heatDefault(data.p)", {"p": dump(p)})]
        fitted, notes = heatplan.fit(steps, 1, total)
        assert notes == [] and [s.ep for s in steps] == list(range(1, total + 1))
        runs = heatplan.peak_runs(steps)
        assert runs and runs[-1][-1].level == 5
        assert len(runs) == (2 if total >= 13 else 1)
        p.heat = steps
        assert not {w.code for w in heatplan.warnings(p)} & {"flat", "early_peak"}


@needs_node
def test_card_renders_empty_plan_bars_and_warnings():
    empty = _work()
    empty.heat = []
    p = _work(pays={4: ["s1"], 5: [], 7: ["s2", "c1"]})
    expr = """(() => { S.name = 'g'; S.route = ['p', 'g', 'arc'];
      S.project = data.empty; const none = heatCard(S.project);
      S.project = data.p; S.heatSel = 7; const full = heatCard(S.project);
      S.project.meta.form = 'serial'; const ser = heatCard(S.project);
      return { none, full, ser }; })()"""
    got = run_js(FILES, expr, {"empty": dump(empty), "p": dump(p)})
    assert 'data-action="heatStart"' in got["none"] and "heat-col" not in got["none"]
    assert got["full"].count('class="heat-col') == 8
    assert "4화 플롯이 거두는 관객" in got["full"]
    assert 'data-bind="heat.6.kind"' in got["full"]  # 7화가 터뜨리기라 정점 종류 칸이 열린다
    assert "단톡방 사진" in got["full"] and "판돈" in got["full"]
    assert got["ser"] == ""


@needs_node
def test_level_and_role_actions_edit_plan():
    expr = """(() => { S.name = 'g'; S.route = ['p', 'g', 'arc']; S.project = data.p; render = () => {}; markDirty = () => { S.dirty = true; };
      actions.heatLevel('3:4'); actions.heatRole('7:hold'); actions.heatClear();
      const cleared = S.project.heat.length; actions.heatStart();
      return { cleared, n: S.project.heat.length, dirty: S.dirty }; })()"""
    p = _work()
    got = run_js(FILES, expr, {"p": dump(p)})
    assert got == {"cleared": 0, "n": 8, "dirty": True}
    expr2 = """(() => { S.project = data.p; render = () => {}; markDirty = () => {};
      actions.heatLevel('3:4'); actions.heatRole('7:hold'); return S.project.heat; })()"""
    heat = run_js(FILES, expr2, {"p": dump(p)})
    assert heat[2]["level"] == 4 and heat[6]["role"] == "hold" and heat[6]["kind"] == ""
