"""열 계획 프롬프트와 기승전결 기획 (prompts.heat_* · pipeline.plan_arc · clean_heat_plan · apply_heat_plan, mock_heat)."""
from canon import heatplan, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import ArcPlan, Cue, CueSheet, HeatArcPlan, HeatTurn

from .jsvm import dump, needs_node, run_js
from .test_heatplan import _work


class Rec(MockLLM):
    """요청 글을 남기는 가짜 LLM."""
    def __init__(self):
        self.asks = []

    def json(self, system, prompt, schema, hint=None):
        self.asks.append((prompt, schema))
        return super().json(system, prompt, schema, hint)


def _plain(p):
    q = p.model_copy(deep=True)
    q.heat, q.heat_rule, q.heat_turn = [], "", HeatTurn()
    return q


def test_no_plan_keeps_prompts_unchanged():
    p = _work()
    q = _plain(p)
    assert heatplan.plan(q) == []
    assert prompts.heat_plot_rules(q) == "" and prompts.heat_step_line(q, 3) == "" and prompts.heat_cue_rule(q, 3) == ""
    assert "열 계획" not in prompts.plot_rules(q) and "열 계획" not in prompts.build_episode_context(q, 3)
    assert "열 계획" not in prompts.cue_sheet_prompt(q, 3)


def test_plot_rules_carry_plan_and_stakes():
    p = _work()
    p.heat_rule = "앞 절반은 열 없이"
    p.heat_turn = HeatTurn(plant_ep=5, fail_ep=6, gain="백업")
    r = prompts.plot_rules(p)
    assert "7화: 열 5/5 · 터뜨리기" in r and "정점 종류: 관객 앞" in r
    assert "열 원칙: 앞 절반은 열 없이" in r and "5화에 반격을 심고 6화에 들킨다" in r
    assert "s2 [판돈 · 드러남] 단톡방 사진" in r and "a1 [관객] 동생" in r
    assert prompts.plot_prompt(p, 1, 8).count("작가가 정한 열 계획") == 1


def test_episode_and_cue_get_this_episodes_line():
    p = _work()
    ctx = prompts.build_episode_context(p, 2)
    assert "# 이번 화 열 계획 (작가가 정함)\n열 1/5 · 쌓기" in ctx
    assert ctx.index("# 이번 화 열 계획") < ctx.index("# 이번 화 플롯")
    assert "# 이번 화 열 계획 (작가가 정함)" in prompts.episode_brief(p, 2)  # 작업지시서도 같은 블록
    assert prompts.cue_sheet_prompt(p, 2).endswith("열 0~1 화라 긴장도 4 이상 큐를 만들지 않습니다.")
    assert "열 눈금(5) 안팎" in prompts.heat_cue_rule(p, 7)
    p.episodes[1].storyboard = None
    p.episodes[1].cue_sheet = CueSheet(cues=[Cue(tension=2)])
    assert "이번 화 열 계획" in prompts.storyboard_prompt(p, 2)


def test_plan_arc_off_asks_plain_arc():
    p = _plain(_work())
    llm = Rec()
    plan = pipeline.plan_arc(llm, p)
    assert type(plan) is ArcPlan and llm.asks[0][1] is ArcPlan and "열 계획도 함께" not in llm.asks[0][0]


def test_plan_arc_on_asks_and_cleans_heat_plan():
    p = _plain(_work())
    p.meta.target_episodes = 16
    p.settings.heat_plan = True
    llm = Rec()
    plan = pipeline.plan_arc(llm, p, "로맨스 줄이기")
    ask, schema = llm.asks[0]
    assert schema is HeatArcPlan and "열 계획도 함께 짭니다" in ask and "승 구간 끝에 낮은 정점" in ask
    assert ask.index("열 계획도 함께") < ask.index("로맨스 줄이기")  # 작가 요청이 맨 뒤
    assert [s.ep for s in plan.heat] == list(range(1, 17))
    assert [f.kind for f in plan.stakes] == ["stake", "audience", "stake"]  # 단서는 버린다
    assert plan.stakes[2].planted_ep == 16  # 범위 밖 심는 화는 끝 화로
    ids = [f.id for f in plan.stakes]
    assert len(set(ids)) == 3 and not set(ids) & {f.id for f in p.foreshadows}
    assert len(heatplan.peak_runs(plan.heat)) == 2


def test_plan_arc_serial_never_asks_heat():
    p = _plain(_work())
    p.settings.heat_plan = True
    p.meta.form = "serial"
    llm = Rec()
    pipeline.plan_arc(llm, p)
    assert llm.asks[0][1] is ArcPlan


def test_apply_heat_plan_adds_new_stakes_once():
    p = _plain(_work())
    p.meta.target_episodes = 8
    p.settings.heat_plan = True
    plan = pipeline.plan_arc(MockLLM(), p)
    before = len(p.foreshadows)
    assert pipeline.apply_heat_plan(p, plan) == len(plan.stakes)
    assert pipeline.apply_heat_plan(p, plan) == 0
    assert len(p.foreshadows) == before + len(plan.stakes) and p.heat == plan.heat and p.heat_turn.plant_ep > 0


def test_cli_arc_applies_heat(capsys, monkeypatch):
    from canon import cli, store
    monkeypatch.setenv("CANON_LLM", "mock")
    p = _plain(_work())
    p.settings.heat_plan = True
    store.save("heat-arc", p)
    cli.main(["arc", "heat-arc", "-y"])
    out = capsys.readouterr().out
    assert "완급 계획:" in out and "뒤집힘:" in out
    saved = store.load("heat-arc")
    assert len(saved.heat) == 8 and any(f.kind == "audience" and f.id.startswith("fs-") for f in saved.foreshadows)


from .test_plot_js import VIEW_FILES as FILES  # noqa: E402


@needs_node
def test_proposal_card_and_apply_match_python():
    p = _plain(_work())
    p.settings.heat_plan = True
    plan = pipeline.plan_arc(MockLLM(), p)
    want = p.model_copy(deep=True)
    pipeline.apply_heat_plan(want, plan)
    expr = """(() => { S.name = 'g'; S.route = ['p', 'g', 'arc']; S.project = data.p; render = () => {}; markDirty = () => {}; toast = () => {};
      S.arcProposal = data.plan.acts; S.heatProposal = { heat: data.plan.heat, heat_rule: data.plan.heat_rule, heat_turn: data.plan.heat_turn, stakes: data.plan.stakes };
      const card = arcProposalCard(); const menu = heatPlanToggle('pop-sec');
      actions.useArcProposal();
      return { card, menu, heat: S.project.heat, fs: S.project.foreshadows.map((f) => f.id), left: S.heatProposal }; })()"""
    got = run_js(FILES, expr, {"p": dump(p), "plan": dump(plan)})
    assert "완급 계획" in got["card"] and 'data-action="heatPick"' not in got["card"]
    assert 'data-bind="settings.heat_plan"' in got["menu"] and "checked" in got["menu"]
    assert got["heat"] == [s.model_dump() for s in want.heat]
    assert got["fs"] == [f.id for f in want.foreshadows] and got["left"] is None
