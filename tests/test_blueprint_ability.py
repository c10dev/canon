"""설계도 능력 일정(canon/blueprint.py, docs/blueprint/specs/10-ability.md): 저장 검사 · 얻은 화 계산 · 경고 · 프롬프트 줄. LLM 비용 없음."""
import pytest

from canon import blueprint, context, pipeline, prompts, renumber, statwin
from canon.schema import Ability, AbilityGrade, AbilityPlan, Blueprint, CharacterState, Project, StatRecord, StateDelta, StatValue

from .test_blueprint import _ep_project, _proj
from .test_insert import _short as _short_insert


def _plan(**kw) -> AbilityPlan:
    return AbilityPlan(**{"character": "hero", "ability": "빙결", **kw})


def _grown(done: int = 3):
    """8화 단편: hero 가 3화에 빙결(초급)을 얻었다. done 화까지 반영."""
    p = _ep_project()
    p.blueprint = Blueprint()
    for n in range(1, done + 1):
        p.episode(n).status = "finalized"
    st = next(s for s in p.states if s.character_id == "hero")
    st.stats = [StatValue(name="근력", value="12"), StatValue(name="특성", value="빙결(초급)")]
    p.stat_log = [StatRecord(episode=0, character_id="hero", name="근력", value="12"),
                  StatRecord(episode=3, character_id="hero", name="특성", value="빙결(초급)")]
    return p


def test_old_project_reads_and_ids_fill():
    p = Project.model_validate({"blueprint": {"milestones": [], "ladders": [], "note": "x"}})
    assert p.blueprint.ability_plans == []
    p = _proj()
    p.blueprint.ability_plans = [AbilityPlan(character="a", ability=" 화염구 Lv3 ", grade=" Lv2 "), AbilityPlan(id="ap-1", character="j", ability="은신 (중급)")]
    blueprint.check(p)
    assert [x.id for x in p.blueprint.ability_plans] == ["ap-2", "ap-1"]
    assert (p.blueprint.ability_plans[0].ability, p.blueprint.ability_plans[0].grade) == ("화염구", "Lv2")  # 이름의 등급 꼬리는 뗀다
    assert (p.blueprint.ability_plans[1].ability, p.blueprint.ability_plans[1].grade) == ("은신", "(중급)")  # 등급 칸이 비었으면 꼬리를 등급으로 옮긴다


@pytest.mark.parametrize("rows, match", [
    ([AbilityPlan(character="x", ability="은신")], "없는 인물"),
    ([AbilityPlan(character="a", ability=" ")], "이름이 비었어요"),
    ([AbilityPlan(character="a", ability="은신", from_ep=5)], "한쪽만"),
    ([AbilityPlan(character="a", ability="은신", from_ep=9, to_ep=5)], "앞이에요"),
    ([AbilityPlan(character="a", ability="은신", grade="초급"), AbilityPlan(character="a", ability="은 신", grade="(초급)")], "두 줄"),
])
def test_check_refuses(rows, match):
    p = _proj()
    p.blueprint.ability_plans = rows
    with pytest.raises(ValueError, match=match):
        blueprint.check(p)


def test_check_allows_grades_of_one_ability_and_old_broken_character():
    p = _proj()
    p.blueprint.ability_plans = [AbilityPlan(character="a", ability="은신", grade="Lv1"), AbilityPlan(character="a", ability="은신", grade="Lv3"),
                                 AbilityPlan(character="gone", ability="은신")]
    before = p.model_copy(deep=True)
    blueprint.check(p, before)  # 디스크에서 이미 끊긴 인물은 막지 않는다


def test_got_ep_reads_stat_log_and_grades():
    p = _grown()
    assert blueprint.got_ep(p, _plan()) == 3
    assert blueprint.got_ep(p, _plan(grade="초급")) == 3 and blueprint.got_ep(p, _plan(grade="(초급)")) == 3  # 괄호를 떼고 견준다
    assert blueprint.got_ep(p, _plan(grade="중급")) is None
    assert blueprint.got_ep(p, _plan(ability="화염구")) is None and blueprint.got_ep(p, _plan(character="ally")) is None
    p.abilities = [Ability(id="ab-01", name="빙결", aliases=["얼음 손"], grades=[AbilityGrade(grade="초급"), AbilityGrade(grade="중급"), AbilityGrade(grade="상급")])]
    p.stat_log.append(StatRecord(episode=5, character_id="hero", name="특성", value="얼음 손(상급)", before="빙결(초급)"))
    assert blueprint.got_ep(p, _plan(grade="중급")) == 5  # 도감 등급 목록의 차례로 '그 이상', 다른 이름도 같은 항목
    assert blueprint.got_ep(p, _plan(ability="얼음 손")) == 3


def test_numeric_grades_and_start_values():
    p = _grown()
    st = next(s for s in p.states if s.character_id == "hero")
    st.stats.append(StatValue(name="스킬", value="은신 Lv4, 도약"))
    p.stat_log += [StatRecord(episode=2, character_id="hero", name="스킬", value="은신 Lv2"),
                   StatRecord(episode=3, character_id="hero", name="스킬", value="은신 Lv4")]
    assert blueprint.got_ep(p, _plan(ability="은신", grade="Lv3")) == 3  # Lv2 → Lv4 로 건너뛰어도 Lv3 에 닿았다
    assert blueprint.got_ep(p, _plan(ability="은신", grade="Lv5")) is None
    assert blueprint.got_ep(p, _plan(ability="도약")) == 0  # 기록 없이 상태창에만 있으면 시작 때


def test_states_and_warnings():
    p = _grown(done=6)
    p.abilities = [Ability(id="ab-01", name="빙결")]
    p.blueprint.ability_plans = [_plan(id="ap-1", from_ep=3, to_ep=4), _plan(id="ap-2", grade="초급", from_ep=5, to_ep=6), _plan(id="ap-3", grade="초급", from_ep=1, to_ep=2),
                                 _plan(id="ap-4", ability="화염구", from_ep=4, to_ep=5), _plan(id="ap-5", ability="화염구", grade="Lv2", from_ep=7, to_ep=8),
                                 _plan(id="ap-6", ability="화염구", grade="Lv9")]
    got = {x["id"]: (x["got"], x["state"], x["linked"]) for x in blueprint.ability_states(p)}
    assert got == {"ap-1": (3, "얻음", True), "ap-2": (3, "앞섬", True), "ap-3": (3, "늦음", True),
                   "ap-4": (None, "지남", False), "ap-5": (None, "예정", False), "ap-6": (None, "미정", False)}
    rows = blueprint.ability_warning_rows(p)
    assert all(c == "hero" for c, _ in rows)
    text = "\n".join(w for _, w in rows)
    assert "빙결 초급: 3화에 얻었어요. 설계도는 5~6화에 얻기로 했어요." in text and "설계도는 1~2화까지 얻기로 했어요." in text
    assert "화염구: 4~5화에 얻기로 했는데 6화까지 반영한 상태창 기록에 없어요." in text
    assert text.count("스킬 도감에 없는 이름이에요") == 3 and "'화염구'는 스킬 도감에" in text
    assert set(w for _, w in rows) <= set(blueprint.warnings(p))
    assert blueprint.ability_warning_rows(_grown()) == []  # 일정이 없으면 경고도 없다


def test_move_remap_and_insert():
    p = _proj()
    p.blueprint.ability_plans = [AbilityPlan(character="a", ability="은신", from_ep=5, to_ep=8)]
    blueprint.move(p, renumber.point_insert(7))
    assert (p.blueprint.ability_plans[0].from_ep, p.blueprint.ability_plans[0].to_ep) == (5, 9)
    notes = blueprint.remap(p, lambda n: 0)
    assert p.blueprint.ability_plans[0].from_ep == 0 and "능력 일정 아영의 은신" in notes[0]
    q = _short_insert()
    q.blueprint.ability_plans = [AbilityPlan(character=q.characters[0].id, ability="은신", from_ep=7, to_ep=9)]
    notes = pipeline.insert_episode(q, 8)
    assert q.blueprint.ability_plans[0].to_ep == 10 and "설계도 줄 1개" in " ".join(notes)


def _scheduled():
    p = _grown()
    p.blueprint.ability_plans = [_plan(grade="초급", from_ep=3, to_ep=3),  # 이미 얻음: 프롬프트에 넣지 않는다
                                 _plan(ability="화염구", from_ep=1, to_ep=2, condition="첫 사냥"),  # 범위를 지남
                                 _plan(grade="중급", from_ep=4, to_ep=5, condition="호수에 빠진다"),
                                 _plan(grade="상급", from_ep=7, to_ep=8),
                                 _plan(ability="비행", from_ep=20, to_ep=22),
                                 _plan(character="ally", ability="치유", from_ep=6, to_ep=6)]
    blueprint.check(p)
    return p


def test_plan_lines_and_block():
    p = _scheduled()
    hero, ally = next(c.name for c in p.characters if c.id == "hero"), next(c.name for c in p.characters if c.id == "ally")
    lines = blueprint.ability_plan_lines(p, None, 4, 6)
    assert lines == [f"- 1~2화에 얻기로 했으나 아직 얻지 못함: {hero} 화염구 (조건: 첫 사냥)", f"- 4~5화에 얻음: {hero} 빙결 중급 (조건: 호수에 빠진다)",
                     f"- 6화에 얻음: {ally} 치유", f"- 7~8화에 얻음 (이 범위 뒤): {hero} 빙결 상급"]  # 범위 뒤는 인물마다 첫 줄만
    assert all("치유" not in x for x in blueprint.ability_plan_lines(p, {"hero"}, 4, 6))  # 기획 인물만
    later = blueprint.ability_plan_lines(p, {"hero"}, 7, 8)  # 3화까지 반영: 4~5화 줄은 아직 쓰지 않은 화라 '얻지 못함'이 아니다
    assert later[:2] == [f"- 1~2화에 얻기로 했으나 아직 얻지 못함: {hero} 화염구 (조건: 첫 사냥)", f"- 앞 화(4~5화)에서 얻을 예정: {hero} 빙결 중급 (조건: 호수에 빠진다)"]
    block = prompts.blueprint_ability_block(p, None, 4, 6)
    assert block.startswith("\n[설계도: 능력 일정 (작가가 정한 계획. 지금 가진 능력이 아니다.") and "생략" not in block
    assert prompts.blueprint_ability_block(_grown(), None, 1, 8) == ""
    budget = context.BUDGET["ability_plan"]
    try:
        context.BUDGET["ability_plan"] = 60
        assert "(그 밖 2줄 생략)" in prompts.blueprint_ability_block(p, None, 4, 6)
    finally:
        context.BUDGET["ability_plan"] = budget


def test_serial_planning_prompts_carry_ability_block():
    from .test_serial import _plan_arc, _serial
    p = _serial()
    _plan_arc(p)
    arc = p.story_arcs[0]
    assert "능력 일정" not in prompts.serial_plot_prompt(p, arc.start_ep, arc.end_ep)
    p.blueprint.ability_plans = [AbilityPlan(character=p.characters[0].id, ability="은신", from_ep=arc.start_ep, to_ep=arc.end_ep)]
    plot = prompts.serial_plot_prompt(p, arc.start_ep, arc.end_ep)
    assert "[설계도: 능력 일정" in plot and plot.index("[설계도: 능력 일정") > plot.index("[관계]")
    assert "[설계도: 능력 일정" in prompts.next_arc_prompt(p, arc.start_ep, 0, "")


def test_board_write_check_state_lines():
    p = _scheduled()
    hero = next(c.name for c in p.characters if c.id == "hero")
    board = prompts.ability_board_rule(p, 4)
    assert f"- 이 화가 얻는 범위(4~5화)인 능력: {hero} 빙결 중급 (조건: 호수에 빠진다)" in board
    assert f"- 다음 능력(7화부터)은 이 화에 얻지 않습니다: {hero} 빙결 상급" in board and "비행" not in board and "초급" not in board
    assert board.rstrip().endswith("warnings 에 적습니다.")
    write = prompts.ability_write_line(p, 4)
    assert "빙결 중급 (4~5화 · 조건: 호수에 빠진다)" in write and "상급" not in write and "얻지 않습니다" not in write  # 쓰기에는 다음 줄이 없다
    assert prompts.ability_write_line(p, 6) == "" or "치유" in prompts.ability_write_line(p, 6)
    assert prompts.ability_write_line(p, 3) == ""  # 3화 줄은 이미 얻었다
    check = prompts.ability_check_rule(p, 4)
    assert "빙결 상급 (7화부터)" in check and "비행 (20화부터)" in check and "type 은 플롯" in check
    state = blueprint.ability_state_rule(p, 4)
    assert "화염구" in state and "빙결 중급" in state and "상급" not in state  # 범위 뒤 줄은 넣지 않는다
    p.episode(4).plot.characters = ["ally"]
    assert "빙결" not in prompts.ability_board_rule(p, 4) and prompts.ability_write_line(p, 4) == ""  # 그 화 플롯 인물만


def test_lines_drop_once_acquired():
    p = _scheduled()
    p.stat_log.append(StatRecord(episode=4, character_id="hero", name="특성", value="빙결(중급)", before="빙결(초급)"))
    assert prompts.ability_write_line(p, 5) == "" and "중급" not in prompts.ability_board_rule(p, 5)


def test_episode_requests_carry_lines_and_stay_same_without_plans():
    p = _scheduled()
    assert "[설계도: 능력 일정 (작가가 정한 계획, 이번 화)]" in prompts.storyboard_prompt(p, 4)
    write = prompts.episode_prompt(p, 4)
    assert "설계도에서 이 화는 능력을 얻는 범위입니다" in write and "이 화에 얻지 않습니다" not in write
    assert "설계도의 능력 일정에 아래 능력이 있습니다" in prompts.state_prompt(p, 4)
    p.episode(4).text, p.episode(4).status = "본문", "written"
    assert "- 설계도 능력 일정:" in prompts.check_prompt(p, 4)
    empty = _grown()
    for f in (prompts.storyboard_prompt, prompts.episode_prompt, prompts.state_prompt):
        assert "능력 일정" not in f(empty, 4)
    assert blueprint.ability_state_rule(_scheduled_without_stats(), 4) == ""


def _scheduled_without_stats():
    p = _scheduled()
    for s in p.states:
        s.stats = []
    return p


def test_delta_warning_when_acquired_before_range():
    p = _scheduled()
    d = StateDelta(episode=4, summary="", character_updates=[CharacterState(character_id="hero", stats=[StatValue(name="특성", value="+빙결(상급)")])])
    assert statwin.after_delta(p, d)["hero"]["특성"] == "빙결(상급)"
    got = blueprint.ability_delta_warnings(p, d)
    assert len(got) == 1 and got[0][1] == "hero" and "빙결 상급: 설계도는 7~8화에 얻기로 했어요. 이 변경안을 반영하면 4화에 얻어요." in got[0][0]
    ok = StateDelta(episode=4, summary="", character_updates=[CharacterState(character_id="hero", stats=[StatValue(name="특성", value="+빙결(중급)")])])
    assert blueprint.ability_delta_warnings(p, ok) == []
    assert blueprint.ability_delta_warnings(_grown(), d) == []


def test_view_api(client):
    meta = {"title": "성장", "genre": "판타지", "logline": "", "target_episodes": 10}
    assert client.post("/api/projects", json={"name": "apv", "meta": meta}).status_code == 200
    p = client.post("/api/projects/apv/suggest/apply", json=client.post("/api/projects/apv/suggest").json()).json()
    a = p["characters"][0]["id"]
    bp = {"milestones": [], "ladders": [], "note": "", "ability_plans": [{"character": a, "ability": "은신", "grade": "Lv2", "condition": "밤 훈련", "from_ep": 2, "to_ep": 3}]}
    saved = client.put("/api/projects/apv/blueprint", json=bp)
    assert saved.status_code == 200 and saved.json()["blueprint"]["ability_plans"][0]["id"] == "ap-1"
    v = client.get("/api/projects/apv/blueprint").json()
    assert v["plans"] == [{"id": "ap-1", "got": None, "state": "예정", "linked": False}]
    assert [w["character"] for w in v["ability_warnings"]] == [a] and "스킬 도감에 없는 이름" in v["ability_warnings"][0]["text"]
    bp["ability_plans"].append({"character": "nobody", "ability": "은신"})
    bad = client.put("/api/projects/apv/blueprint", json=bp)
    assert bad.status_code == 400 and "없는 인물" in bad.json()["detail"]
