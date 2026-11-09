"""열 계획 받기(이미 있는 단편 · 아크)와 장편 아크의 열 계획 (pipeline.propose_heat · heat_target · plan_next_arc · apply_arc, serialize, web 작업 heat)."""
import pytest

from canon import heatplan, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import HeatArcProposal, HeatProposal, HeatStep, HeatTurn

from .jsvm import dump, needs_node, run_js
from .test_convert import _short as _short_written
from .test_heatplan import _work
from .test_plot_js import VIEW_FILES
from .test_serial import _plan_arc, _serial

LLM = MockLLM()


def _plain():
    p = _work()
    p.heat, p.heat_rule, p.heat_turn = [], "", HeatTurn()
    return p


# ---------- 일감 5: 이미 있는 기승전결 위에 열 계획 받기 ----------

def test_propose_heat_short_keeps_written_episode_plan():
    p = _work()
    p.episodes[0].text = "본문"
    prop = pipeline.propose_heat(LLM, p)  # 가짜 응답은 1화를 열 5 · 터뜨리기로 보낸다
    assert type(prop) is HeatProposal and [s.ep for s in prop.heat] == list(range(1, 9))
    assert (prop.heat[0].level, prop.heat[0].role) == (0, "build")  # 본문 있는 화는 지금 계획 그대로
    assert {f.kind for f in prop.stakes} == {"stake", "audience"} and all(f.id.startswith("fs-01-h") for f in prop.stakes)
    q = _plain()
    q.episodes[0].text = "본문"
    assert pipeline.propose_heat(LLM, q).heat[0].level == 5  # 지금 계획이 없으면 AI 값을 쓴다


def test_propose_prompt_lists_plots_written_and_open_foreshadows():
    p = _work()
    p.episodes[0].text = "숨 숨"
    p.settings.heat_words = ["숨"]
    ask = prompts.heat_propose_prompt(p, 1, 8, p.arc, "이 단편 전체의")
    assert ask.startswith("이 단편 전체의 열 계획을 짭니다")
    assert "- 4화 [기] " in ask and "거두는 복선: s1, a1" in ask
    assert "- 1화: 본문 있음. 열 낱말" in ask and "지금 계획 열 0 · 쌓기 (그대로 둡니다)" in ask
    assert "- s2 [판돈] 단톡방 사진 (5화)" in ask and "1화부터 8화까지 화마다" in ask


def test_heat_target_errors_and_serial_default():
    q = _plain()
    q.arc = []
    with pytest.raises(ValueError, match="기승전결"):
        pipeline.heat_target(q)
    p = _serial(60)
    with pytest.raises(ValueError, match="아크를 먼저"):
        pipeline.heat_target(p)
    a1 = _plan_arc(p)
    a2 = _plan_arc(p)
    for n in range(a1.start_ep, a1.end_ep + 1):
        p.episode(n).text = "본문"
    assert pipeline.heat_target(p)[4].number == a2.number  # 다 쓰지 않은 첫 아크
    assert pipeline.heat_target(p, 1)[4].number == 1
    with pytest.raises(ValueError, match="아크 9"):
        pipeline.heat_target(p, 9)


def test_cli_heat_applies_to_arc(capsys, monkeypatch):
    from canon import cli, store
    monkeypatch.setenv("CANON_LLM", "mock")
    p = _serial(60)
    a = _plan_arc(p)
    store.save("heat-cli-arc", p)
    cli.main(["heat", "heat-cli-arc", "--arc", "1", "-y"])
    out = capsys.readouterr().out
    assert f"{a.start_ep}~{a.end_ep}화 (아크 1)" in out and "새 복선 2개" in out
    saved = store.load("heat-cli-arc")
    assert [s.ep for s in saved.story_arcs[0].heat] == list(range(a.start_ep, a.end_ep + 1)) and not saved.heat


def test_web_heat_job_and_pending(client):
    from canon import store

    from .test_web import _wait
    store.save("heat-job", _plain())
    j = client.post("/api/projects/heat-job/jobs", json={"kind": "heat"}).json()
    done = _wait(client, j["id"])
    assert done["status"] == "done", done
    assert done["result"]["arc"] == 0 and len(done["result"]["heat"]) == 8
    assert any(r["kind"] == "heat" for r in client.get("/api/projects/heat-job/pending").json()["results"].values())
    assert store.load("heat-job").heat == []  # 받기만 하고 저장하지 않는다


# ---------- 일감 6: 장편 아크의 열 계획 ----------

def test_arc_heat_is_hidden_from_llm_schema_and_prompt_dumps():
    from canon.schema import ArcProposal
    assert "heat" not in str(ArcProposal.model_json_schema())
    p = _serial(60)
    a = _plan_arc(p)
    a.heat = [HeatStep(ep=n, level=1) for n in range(a.start_ep, a.end_ep + 1)]
    ctx = prompts.build_episode_context(p, a.start_ep)
    assert '"heat"' not in ctx and '"heat_rule"' not in ctx
    assert "이번 화 열 계획 (작가가 정함): 열 1/5 · 쌓기" in ctx
    assert "작가가 정한 열 계획" in prompts.plot_prompt(p, a.start_ep, a.end_ep)


def test_next_arc_with_heat_plan_fills_arc_and_adds_stakes():
    p = _serial(60)
    p.settings.heat_plan = True
    rec = []

    class Rec(MockLLM):
        def json(self, system, prompt, schema, hint=None):
            rec.append((prompt, schema))
            return super().json(system, prompt, schema, hint)
    prop = pipeline.plan_next_arc(Rec(), p)
    assert rec[0][1] is HeatArcProposal and "이 아크의 열 계획도 함께 짭니다" in rec[0][0]
    a = prop.arc
    assert [s.ep for s in a.heat] == list(range(a.start_ep, a.end_ep + 1)) and a.heat_rule and a.heat_turn.plant_ep
    before = len(p.foreshadows)
    pipeline.apply_arc(p, prop)
    assert p.story_arcs[0].heat == a.heat and len(p.foreshadows) == before + 2
    assert heatplan.step(p, a.start_ep) is not None and heatplan.turn(p, a.start_ep).gain == "새 약점"


def test_next_arc_off_or_screen_edit():
    p = _serial(60)
    prop = pipeline.plan_next_arc(LLM, p)
    assert type(prop) is not HeatArcProposal and not prop.arc.heat
    # 화면이 끝 화를 줄여 보낸 제안: 열 계획을 새 범위에 맞춘다
    p.settings.heat_plan = True
    prop = pipeline.plan_next_arc(LLM, p)
    d = HeatArcProposal(**prop.model_dump())
    d.arc.end_ep -= 2
    d.arc.acts[-1].end_ep -= 2
    pipeline.apply_arc(p, d)
    a = p.story_arcs[0]
    assert [s.ep for s in a.heat] == list(range(a.start_ep, a.end_ep + 1))


def test_serial_warnings_are_per_arc():
    p = _serial(60)
    a1 = _plan_arc(p)
    a2 = _plan_arc(p)
    a1.heat = [HeatStep(ep=n, level=2) for n in range(a1.start_ep, a1.end_ep + 1)]
    a2.heat = [HeatStep(ep=n, level=0, role="build") for n in range(a2.start_ep, a2.end_ep + 1)]
    a2.heat[0] = HeatStep(ep=a2.start_ep, level=5, role="peak")
    codes = [(w.ep, w.code) for w in heatplan.warnings(p)]
    assert (a1.start_ep, "flat") in codes  # 장편은 아크 첫 화를 가리킨다
    assert (a2.start_ep, "early_peak") in codes  # 아크 안에서 앞쪽인지 본다
    assert heatplan.plan(p) == [] and heatplan.plan(p, a2.start_ep) == a2.heat


def test_save_fits_arc_heat(client):
    from canon import store
    p = _serial(60)
    a = _plan_arc(p)
    a.heat = [HeatStep(ep=a.start_ep, level=3)]
    store.save("heat-serial-fit", p)
    got = client.put("/api/projects/heat-serial-fit", json=client.get("/api/projects/heat-serial-fit").json())
    assert got.status_code == 200, got.text
    assert [s.ep for s in store.load("heat-serial-fit").story_arcs[0].heat] == list(range(a.start_ep, a.end_ep + 1))


def test_conversion_moves_short_plan_to_arc_one():
    p = _short_written()
    p.heat = [HeatStep(ep=n, level=n % 4) for n in range(1, 13)]
    p.heat_rule, p.heat_turn = "끝에서 터뜨린다", HeatTurn(plant_ep=3, fail_ep=5, gain="녹음")
    prop = pipeline.propose_conversion(LLM, p, 200, "keep")
    pipeline.apply_conversion(p, prop)
    a = p.story_arcs[0]
    assert [s.level for s in a.heat] == [n % 4 for n in range(1, 13)] and a.heat_rule == "끝에서 터뜨린다" and a.heat_turn.gain == "녹음"
    assert p.heat == [] and p.heat_rule == ""


# ---------- 화면 ----------

@needs_node
def test_serial_warnings_match_python():
    p = _serial(60)
    a1 = _plan_arc(p)
    a2 = _plan_arc(p)
    a1.heat = [HeatStep(ep=n, level=2) for n in range(a1.start_ep, a1.end_ep + 1)]
    a2.heat = [HeatStep(ep=n, level=0 if n != a2.start_ep else 5, role="peak" if n == a2.start_ep else "build") for n in range(a2.start_ep, a2.end_ep + 1)]
    got = run_js(VIEW_FILES, "heatWarnings(data.p)", {"p": dump(p)})
    assert got == [w.model_dump() for w in heatplan.warnings(p)] and got


@needs_node
def test_arc_card_and_draft_use():
    p = _serial(60)
    a = _plan_arc(p)
    prop = pipeline.propose_heat(LLM, p, a.number)
    expr = """(() => { S.name = 'g'; S.route = ['p', 'g', 'arc']; S.project = data.p; render = () => {}; markDirty = () => {}; toast = () => {};
      S.selArc = data.n; const empty = heatCard(S.project, S.project.story_arcs[0]); const none = heatCard(S.project);
      S.heatDraft = { ...data.prop, arc: data.n }; const withDraft = heatCard(S.project, S.project.story_arcs[0]);
      actions.heatDraftUse(); const full = heatCard(S.project, S.project.story_arcs[0]);
      actions.heatLevel(data.start + ':4');
      return { empty, none, withDraft, full, heat: S.project.story_arcs[0].heat, fs: S.project.foreshadows.length, left: S.heatDraft }; })()"""
    got = run_js(VIEW_FILES, expr, {"p": dump(p), "prop": dump(prop), "n": a.number, "start": a.start_ep})
    assert got["none"] == "" and 'data-action="heatPropose"' in got["empty"] and "이 아크의 완급 계획" in got["empty"]
    assert "AI 완급 계획 제안" in got["withDraft"] and 'data-action="heatDraftUse"' in got["withDraft"]
    assert 'data-bind="story_arcs.0.heat_rule"' in got["full"] and got["left"] is None
    assert got["heat"][0]["level"] == 4 and [s["ep"] for s in got["heat"]] == list(range(a.start_ep, a.end_ep + 1))
    assert got["fs"] == len(p.foreshadows) + len(prop.stakes)


@needs_node
def test_default_shape_for_arc_range():
    p = _serial(60)
    _plan_arc(p)
    a = _plan_arc(p)
    steps = run_js(VIEW_FILES, "heatDefaultFor(data.a.acts, data.a.start_ep, data.a.end_ep)", {"a": dump(a)})
    assert [s["ep"] for s in steps] == list(range(a.start_ep, a.end_ep + 1)) and steps[0]["level"] == 0
    assert any(s["role"] == "peak" and s["level"] == 5 for s in steps)
