"""열 계획 (canon/heatplan.py, schema.HeatStep · HeatTurn · HeatArcPlan · Foreshadow.kind)."""
from canon import heatplan
from canon.schema import Foreshadow, HeatArcPlan, HeatStep, HeatTurn, Meta, Project, Settings


def _short(steps=None, turn=None) -> Project:
    return Project(meta=Meta(title="열", target_episodes=4), heat=steps or [], heat_turn=turn or HeatTurn())


def test_old_files_read_without_heat():
    p = Project.model_validate({"meta": {"title": "옛"}, "foreshadows": [{"id": "f1", "description": "열쇠", "planted_ep": 1}]})
    assert p.heat == [] and p.heat_rule == "" and p.heat_turn.plant_ep == 0
    assert p.foreshadows[0].kind == "clue" and p.foreshadows[0].public is False
    assert Settings.model_validate({}).heat_plan is False


def test_step_and_turn_find_short_plan():
    p = _short([HeatStep(ep=1, level=0), HeatStep(ep=2, level=4, role="peak", kind="흥정")], HeatTurn(plant_ep=1, fail_ep=2, gain="녹음"))
    assert heatplan.step(p, 2).level == 4
    assert heatplan.step(p, 3) is None
    assert heatplan.turn(p).gain == "녹음"
    assert heatplan.turn(_short()) is None


def test_serial_has_no_plan_yet():
    p = _short([HeatStep(ep=1)], HeatTurn(plant_ep=1, fail_ep=1))
    p.meta.form = "serial"
    assert heatplan.plan(p) == [] and heatplan.step(p, 1) is None and heatplan.turn(p) is None


def test_fit_fills_gaps_drops_outside_and_clamps():
    steps = [HeatStep(ep=3, level=9, role="peak", kind=" 관객 앞 "), HeatStep(ep=1, level=-2, role="build", kind="지울 것"),
             HeatStep(ep=1, level=5), HeatStep(ep=7, level=3)]
    got, notes = heatplan.fit(steps, 1, 4)
    assert [s.ep for s in got] == [1, 2, 3, 4]
    assert got[0].level == 0 and got[0].kind == ""  # 첫 줄을 쓰고 정점이 아니면 종류를 지운다
    assert got[2].level == 5 and got[2].kind == "관객 앞"
    assert (got[1].level, got[1].role) == (heatplan.FILL_LEVEL, heatplan.FILL_ROLE)
    assert notes == ["범위(1~4화) 밖의 7화를 열 계획에서 뺐어요", "열 계획에 없던 2 · 4화를 열 2 · 쌓기로 채웠어요"]


def test_fit_keeps_empty_plan_empty():
    assert heatplan.fit([], 1, 10) == ([], [])


def test_fit_turn():
    ok = HeatTurn(plant_ep=2, fail_ep=3, gain="백업")
    assert heatplan.fit_turn(ok, 1, 4) == (ok, [])
    assert heatplan.fit_turn(HeatTurn(), 1, 4) == (HeatTurn(), [])
    bad, notes = heatplan.fit_turn(HeatTurn(plant_ep=3, fail_ep=2), 1, 4)
    assert bad.plant_ep == 0 and "뺐어요" in notes[0]
    assert heatplan.fit_turn(HeatTurn(plant_ep=2, fail_ep=9), 1, 4)[0].plant_ep == 0


def test_heat_arc_plan_reads_stakes():
    plan = HeatArcPlan.model_validate({
        "acts": [], "heat": [{"ep": 1, "level": 1, "role": "build"}], "heat_rule": "앞 절반은 열 없이",
        "stakes": [{"id": "s1", "description": "단톡방 사진", "planted_ep": 1, "kind": "stake", "public": True}]})
    assert plan.stakes[0].kind == "stake" and plan.stakes[0].public
    assert plan.heat_turn.plant_ep == 0


def test_foreshadow_rejects_unknown_kind():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Foreshadow(id="f", description="x", planted_ep=1, kind="weird")


# ---------- 경고 · 실제 열 ----------

from canon.schema import Act, Cue, CueSheet  # noqa: E402

from .jsvm import episode  # noqa: E402

SHAPE = [(0, "build"), (1, "build"), (1, "build"), (3, "peak"), (1, "after"), (2, "hold"), (5, "peak"), (2, "after")]


def _work(shape=SHAPE, pays: dict | None = None, fs: list | None = None, kinds: dict | None = None) -> Project:
    """8화 단편: 기 1~2, 승 3~4, 전 5~7, 결 8. 4화 낮은 정점, 7화 큰 정점."""
    pays = pays if pays is not None else {4: ["s1", "a1"], 5: ["a1"], 7: ["s2", "c1"]}
    kinds = kinds or {4: "흥정", 7: "관객 앞"}
    p = Project(meta=Meta(title="열", target_episodes=8),
                arc=[Act(name="기", start_ep=1, end_ep=2, goal=""), Act(name="승", start_ep=3, end_ep=4, goal=""),
                     Act(name="전", start_ep=5, end_ep=7, goal=""), Act(name="결", start_ep=8, end_ep=8, goal="")],
                heat=[HeatStep(ep=i, level=lv, role=r, kind=kinds.get(i, "")) for i, (lv, r) in enumerate(shape, 1)],
                episodes=[episode(i, plot={"foreshadow_payoff": pays.get(i, [])}) for i in range(1, 9)])
    p.foreshadows = fs if fs is not None else [
        Foreshadow(id="s1", description="비밀 계정", planted_ep=1, kind="stake"),
        Foreshadow(id="s2", description="단톡방 사진", planted_ep=5, kind="stake", public=True),
        Foreshadow(id="a1", description="동생", planted_ep=2, kind="audience"),
        Foreshadow(id="c1", description="6시 시한", planted_ep=6, kind="constraint")]
    return p


def _codes(p: Project) -> list[tuple[int, str]]:
    return [(w.ep, w.code) for w in heatplan.warnings(p)]


def test_good_plan_has_no_warnings():
    assert _codes(_work()) == []
    assert heatplan.warnings(_short()) == []


def test_flat_plan_warns_once_for_whole_plan():
    flat = [(2, "build"), (2, "build"), (2, "build"), (3, "peak"), (2, "after"), (2, "hold"), (3, "peak"), (2, "after")]
    assert (0, "flat") in _codes(_work(flat))


def test_early_peak_in_gi_or_first_share():
    shape = [(0, "build"), (4, "peak")] + SHAPE[2:]
    codes = _codes(_work(shape, pays={2: ["a1"], 4: ["s1", "a1"], 5: ["a1"], 7: ["s2", "c1"]}))
    assert (2, "early_peak") in codes and (4, "early_peak") not in codes


def test_peak_needs_stake_before_and_pressure_in_plot():
    p = _work(pays={4: ["s1"], 5: [], 7: ["s2", "c1"]})
    assert (4, "no_pressure") in _codes(p)
    p = _work(fs=[Foreshadow(id="a1", description="동생", planted_ep=2, kind="audience"),
                  Foreshadow(id="c1", description="시한", planted_ep=6, kind="constraint")])
    assert (4, "no_stake") in _codes(p) and (7, "no_stake") in _codes(p)


def test_same_kind_and_same_stake():
    p = _work(kinds={4: "흥정", 7: " 흥정 "}, pays={4: ["s1", "a1"], 5: ["a1"], 7: ["s1", "c1"]})
    codes = _codes(p)
    assert (7, "same_kind") in codes and (7, "same_stake") in codes


def test_audience_needs_aftermath_next_episode():
    p = _work(pays={4: ["s1", "a1"], 7: ["s2", "c1"]})
    assert (5, "no_aftermath") in _codes(p)
    p.episodes[4].plot.summary = "a1 이 본 일로 다투는 화"
    assert (5, "no_aftermath") not in _codes(p)


def test_late_turn():
    p = _work()
    p.heat_turn = HeatTurn(plant_ep=5, fail_ep=7, gain="백업")
    assert (7, "late_turn") in _codes(p)
    p.heat_turn = HeatTurn(plant_ep=5, fail_ep=6, gain="백업")
    assert (7, "late_turn") not in _codes(p)


def test_hot_cue_on_build_episode():
    p = _work()
    p.episodes[1].cue_sheet = CueSheet(cues=[Cue(tension=2), Cue(tension=4)])
    assert (2, "hot_cue") in _codes(p)
    assert [w.code for w in heatplan.warnings_for(p, 2)] == ["hot_cue"]


def test_density_and_cue_tension():
    assert heatplan.density("숨 숨 결", ["숨"]) == round(2 * 1000 / 3, 2)
    assert heatplan.density("숨", []) is None and heatplan.density("  ", ["숨"]) is None
    assert heatplan.cue_tension(CueSheet(cues=[Cue(tension=1, length=100), Cue(tension=5, length=300)])) == 4.0
    assert heatplan.cue_tension(CueSheet(cues=[Cue(tension=2), Cue(tension=4)])) == 3.0
    assert heatplan.cue_tension(CueSheet(cues=[Cue(tension=5)], skipped=True)) is None
    assert heatplan.cue_tension(None) is None


def test_actual_only_written_episodes():
    p = _work()
    p.settings.heat_words = ["숨"]
    p.episodes[0].text = "숨이 멎었다."
    got = heatplan.actual(p)
    assert [a.ep for a in got] == [1] and got[0].density > 0 and got[0].tension is None


def test_cli_confirm_prints_heat_warnings(capsys):
    from canon import cli, store
    p = _work(pays={4: ["s1"], 5: [], 7: ["s2", "c1"]})
    store.save("heat-cli", p)
    cli.main(["confirm", "heat-cli", "4"])
    assert "열 계획: 4화 플롯이 거두는 관객" in capsys.readouterr().out


# ---------- 서버: 복선 갈래 고치기, 저장 때 계획 맞추기 ----------

def test_foreshadow_add_and_update_kind(client):
    from canon import store
    store.save("heat-web", _work())
    r = client.post("/api/projects/heat-web/foreshadows", json={"description": "엄마의 목소리", "episode": 3, "kind": "audience"})
    assert r.status_code == 200
    new = [f for f in r.json()["foreshadows"] if f["description"] == "엄마의 목소리"][0]
    assert new["kind"] == "audience" and new["public"] is False
    r = client.put(f"/api/projects/heat-web/foreshadows/{new['id']}", json={"kind": "stake", "public": True})
    got = [f for f in r.json()["foreshadows"] if f["id"] == new["id"]][0]
    assert (got["kind"], got["public"]) == ("stake", True)
    assert client.put(f"/api/projects/heat-web/foreshadows/{new['id']}", json={"kind": "weird"}).status_code == 400


def test_save_fits_heat_to_episode_count(client):
    from canon import store
    store.save("heat-fit", _work())
    p = client.get("/api/projects/heat-fit").json()
    p["meta"]["target_episodes"] = 10
    p["arc"][-1]["end_ep"] = 10
    p["heat_turn"] = {"plant_ep": 5, "fail_ep": 3, "gain": ""}
    r = client.put("/api/projects/heat-fit", json=p)
    assert r.status_code == 200, r.text
    saved = store.load("heat-fit")
    assert [s.ep for s in saved.heat] == list(range(1, 11)) and saved.heat[9].role == "build"
    assert saved.heat_turn.plant_ep == 0
