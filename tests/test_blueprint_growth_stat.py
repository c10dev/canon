"""성장 일정의 상태창 수치 줄 (docs/blueprint/specs/14-growth-stat.md, 웹소설 일감 5): 얻은 화 계산 · 경고 · 저장 검사 · 프롬프트. LLM 비용 없음."""
import hashlib

import pytest

from canon import blueprint, pipeline, prompts, renumber
from canon.mock import MockLLM
from canon.schema import Ability, AbilityDraft, AbilityGrade, AbilityPlan, Blueprint, CharacterState, Project, StatRecord, StateDelta, StatValue

from .test_blueprint import _ep_project
from .test_blueprint_ability import _scheduled


def _stat(**kw) -> AbilityPlan:
    return AbilityPlan(**{"character": "hero", "ability": "레벨", "stat": "레벨", "grade": "15", **kw})


def _leveled(done: int = 4, before: str = "3", after: str = "15", name: str = "레벨"):
    """8화 단편: hero 의 상태창 수치 항목 name 이 0화 before 에서 3화 after 로 올랐다. done 화까지 반영."""
    p = _ep_project()
    p.blueprint = Blueprint()
    for n in range(1, done + 1):
        p.episode(n).status = "finalized"
    st = next(s for s in p.states if s.character_id == "hero")
    st.stats = [StatValue(name=name, value=after), StatValue(name="스킬", value="검술 Lv3"), StatValue(name="인벤토리", value="포션, 밧줄")]
    p.stat_log = [StatRecord(episode=0, character_id="hero", name=name, value=before),
                  StatRecord(episode=3, character_id="hero", name=name, value=after, before=before),
                  StatRecord(episode=3, character_id="hero", name="스킬", value="검술 Lv3")]
    return p


def test_old_project_reads_without_stat():
    p = Project.model_validate({"blueprint": {"ability_plans": [{"character": "a", "ability": "은신", "grade": "Lv2"}]}})
    assert p.blueprint.ability_plans[0].stat == ""
    assert AbilityDraft(character="a", ability="은신", from_ep=1, to_ep=1).stat == ""


@pytest.mark.parametrize("want, have, ok", [
    ("15", "15", True), ("15", "16", True), ("15", "14", False),
    ("15", "Lv15", True),            # 계획 값에 표지가 없으면 수만 본다
    ("Lv15", "Lv12", False), ("Lv15", "Lv.16", True), ("Lv15", "15", False),  # 표지가 있으면 같아야 한다 (점 · 빈칸 무시)
    ("1,200골드", "1500골드", True), ("1200", "1,100", False), ("12.5", "13", True),
    ("D급", "D급", True), ("D급", "C급", False), ("(중급)", "중급", True),
    ("100", "80/100", False), ("80/100", "80/100", True),  # 한도가 붙은 값은 수로 견주지 않는다
    ("15", "", False),
])
def test_stat_ok(want, have, ok):
    assert blueprint.stat_ok(want, have) is ok


@pytest.mark.parametrize("before, after, grade, got", [
    ("3", "15", "15", 3), ("Lv3", "Lv15", "Lv15", 3), ("3", "15", "10", 3), ("3", "15", "20", None),
    ("100", "300", "300", 3), ("F급", "D급", "D급", 3), ("F급", "D급", "C급", None),
    ("15", "15", "15", 0),  # 1화 전에 정한 값이 이미 닿았다
])
def test_got_ep_reads_the_stat_log(before, after, grade, got):
    name = "마력" if before == "100" else "등급" if "급" in before else "레벨"
    p = _leveled(before=before, after=after, name=name)
    assert blueprint.got_ep(p, _stat(ability=name, stat=name, grade=grade)) == got


def test_got_ep_without_log_uses_the_current_value():
    p = _leveled()
    p.stat_log = []
    assert blueprint.got_ep(p, _stat()) == 0 and blueprint.got_ep(p, _stat(grade="20")) is None
    assert blueprint.got_ep(p, _stat(character="ally")) is None


def test_states_and_warnings_for_stat_lines():
    p = _leveled(done=6)
    p.blueprint.ability_plans = [_stat(id="ap-1", from_ep=2, to_ep=4), _stat(id="ap-2", grade="12", from_ep=5, to_ep=6), _stat(id="ap-3", grade="10", from_ep=1, to_ep=2),
                                 _stat(id="ap-4", grade="30", from_ep=4, to_ep=5), _stat(id="ap-5", grade="40", from_ep=7, to_ep=8),
                                 AbilityPlan(id="ap-6", character="hero", ability="레벨", grade="50", from_ep=7, to_ep=8)]  # 옛 줄: 이름만 적고 항목은 고르지 않음
    got = {x["id"]: (x["got"], x["state"], x["linked"]) for x in blueprint.ability_states(p)}
    assert got == {"ap-1": (3, "얻음", True), "ap-2": (3, "앞섬", True), "ap-3": (3, "늦음", True), "ap-4": (None, "지남", True),
                   "ap-5": (None, "예정", True), "ap-6": (None, "예정", False)}
    text = "\n".join(w for _, w in blueprint.ability_warning_rows(p))
    assert "성장 일정 서윤의 레벨 12: 3화에 닿았어요. 설계도는 5~6화에 닿기로 했어요." in text
    assert "레벨 10: 3화에 닿았어요. 설계도는 1~2화까지 닿기로 했어요." in text
    assert "레벨 30: 4~5화에 닿기로 했는데 6화까지 반영한 상태창 기록에 없어요." in text
    assert "스킬 도감에 없는 이름" not in text  # 수치 줄에는 도감 경고가 없다
    assert text.count("'레벨'은 상태창 수치 항목이에요. 줄을 고쳐 상태창 항목으로 고르면 값으로 셀 수 있어요.") == 1  # 옛 줄만


def test_stat_names_skip_list_and_inventory_items():
    p = _leveled()
    p.stat_log.append(StatRecord(episode=2, character_id="hero", name="명성", value="10"))
    assert blueprint.stat_names(p, "hero") == ["레벨", "명성"]  # 지금 상태창 차례, 그 뒤 기록에만 있는 이름
    assert blueprint.stat_names(p, "ally") == []
    next(x for x in p.states if x.character_id == "hero").stats.append(StatValue(name="마법 공격력", value="120"))
    assert blueprint.stat_names(p, "hero") == ["레벨", "마법 공격력", "명성"]  # 값이 수면 '마법' 이 이름에 들어도 수치 항목


def test_check_keeps_stat_names_and_refuses_empty_values():
    p = _leveled()
    p.blueprint.ability_plans = [AbilityPlan(character="hero", ability="", stat=" 레벨 ", grade=" Lv15 "), AbilityPlan(character="hero", ability="검술 Lv3"),
                                 AbilityPlan(character="hero", ability="아무 이름", stat="공격력 +2", grade="+5")]
    blueprint.check(p)
    rows = [(x.stat, x.ability, x.grade) for x in p.blueprint.ability_plans]
    assert rows == [("레벨", "레벨", "Lv15"), ("", "검술", "Lv3"), ("공격력 +2", "공격력 +2", "+5")]  # 수치 줄은 이름이 항목 이름이고 꼬리를 떼지 않는다
    p.blueprint.ability_plans.append(AbilityPlan(character="hero", ability="레벨", grade="Lv15"))
    blueprint.check(p)  # 같은 이름이라도 도감 항목 줄과 수치 줄은 다른 줄이다
    p.blueprint.ability_plans.append(_stat(grade="lv 15"))
    with pytest.raises(ValueError, match="두 줄"):
        blueprint.check(p)
    p.blueprint.ability_plans = [_stat(grade=" ")]
    with pytest.raises(ValueError, match="닿을 값을 적어 주세요"):
        blueprint.check(p)


def test_move_keeps_the_stat_field():
    p = _leveled()
    p.blueprint.ability_plans = [_stat(from_ep=5, to_ep=8)]
    blueprint.move(p, renumber.point_insert(7))
    x = p.blueprint.ability_plans[0]
    assert (x.stat, x.grade, x.from_ep, x.to_ep) == ("레벨", "15", 5, 9)


def test_plan_lines_and_state_rule_for_stat_lines():
    p = _leveled(done=3)
    p.blueprint.ability_plans = [_stat(grade="20", from_ep=1, to_ep=2), _stat(grade="25", from_ep=4, to_ep=5, condition="던전 공략"),
                                 AbilityPlan(character="hero", ability="빙결", from_ep=4, to_ep=5)]
    blueprint.check(p)
    lines = blueprint.ability_plan_lines(p, None, 4, 6)
    assert lines == ["- 1~2화에 닿기로 했으나 아직 닿지 못함: 서윤 레벨 20", "- 4~5화에 닿음: 서윤 레벨 25 (조건: 던전 공략)", "- 4~5화에 얻음: 서윤 빙결"]
    rule = blueprint.ability_state_rule(p, 4)
    assert "stats 의 목록 항목에 이 이름 그대로 적습니다. 본문에 없으면 적지 않습니다: 서윤(hero) 빙결." in rule
    assert "아래 상태창 수치가 있습니다. 이번 화 본문에서 그 인물의 값이 오르면 stats 의 그 항목 값을 바꿉니다. 본문에 없으면 바꾸지 않습니다: 서윤(hero) 레벨 20; 서윤(hero) 레벨 25." in rule
    p.blueprint.ability_plans = p.blueprint.ability_plans[:2]
    assert "목록 항목" not in blueprint.ability_state_rule(p, 4)  # 수치 줄만 있으면 목록 문장은 없다


def test_write_line_needs_the_value_in_the_plot():
    p = _leveled(done=3)
    p.blueprint.ability_plans = [_stat(grade="Lv25", from_ep=4, to_ep=5)]
    p.episode(4).plot.summary = "서윤의 레벨이 오른다"
    assert prompts.ability_write_line(p, 4) == ""  # '레벨' 낱말만으로는 넣지 않는다
    p.episode(4).plot.summary = "서윤이 레벨 25를 찍는다"
    assert "레벨 Lv25 (4~5화)" in prompts.ability_write_line(p, 4)


def test_delta_warning_for_stat_lines():
    p = _leveled(done=3)
    p.blueprint.ability_plans = [_stat(grade="30", from_ep=7, to_ep=8)]
    up = StateDelta(episode=4, summary="", character_updates=[CharacterState(character_id="hero", stats=[StatValue(name="레벨", value="+20")])])
    got = blueprint.ability_delta_warnings(p, up)
    assert got == [("서윤의 레벨 30: 설계도는 7~8화에 닿기로 했어요. 이 변경안을 반영하면 4화에 닿아요.", "hero")]
    small = StateDelta(episode=4, summary="", character_updates=[CharacterState(character_id="hero", stats=[StatValue(name="레벨", value="+1")])])
    assert blueprint.ability_delta_warnings(p, small) == []


def test_clean_keeps_stat_lines_only_for_known_items():
    p = _leveled(done=0)
    rows = [AbilityDraft(character="hero", ability="레벨", stat="레벨", grade="10", from_ep=2, to_ep=2),
            AbilityDraft(character="hero", ability="마력", stat="마력", grade="300", from_ep=3, to_ep=3),   # 상태창에 없는 항목
            AbilityDraft(character="hero", ability="레벨", stat="레벨", grade="", from_ep=4, to_ep=4),     # 값이 비었다
            AbilityDraft(character="hero", ability="레벨", grade="Lv20", from_ep=5, to_ep=5)]            # 도감 항목 줄로 남는다
    out = blueprint.clean_abilities(p, rows, {"hero"}, 1, 8)
    assert [(x.stat, x.ability, x.grade) for x in out] == [("레벨", "레벨", "10"), ("", "레벨", "Lv20")]
    from canon.schema import AbilityCodexDraft
    codex = blueprint.clean_codex(p, [AbilityCodexDraft(name="레벨")], out[:1])
    assert codex == []  # 수치 줄은 도감 초안을 받지 않는다
    blueprint.apply_abilities(p, out[:1])
    assert p.blueprint.ability_plans[0].stat == "레벨" and blueprint.ability_states(p)[0]["got"] == 3


def test_mock_proposal_stat_line_survives_only_with_the_item():
    p = _leveled(done=0)
    prop = pipeline.draft_abilities(MockLLM(), p, 0, "hero", "")
    assert any(x.stat == "레벨" and x.grade == "Lv10" for x in prop.abilities)
    for s in p.states:
        s.stats = [x for x in s.stats if x.name != "레벨"]
    p.stat_log = [r for r in p.stat_log if r.name != "레벨"]
    assert not any(x.stat for x in pipeline.draft_abilities(MockLLM(), p, 0, "hero", "").abilities)


def test_ai_block_lists_stat_values_only_when_present():
    p = _leveled(done=0)
    s = prompts.ability_ai_block(p, {"hero"})
    assert "[지금 상태창의 수치]\n- 서윤: 레벨 15\n[이미 적은 능력 일정]" in s and "포션" not in s.split("[지금 상태창의 수치]")[1]
    rules = prompts.ability_ai_rules()
    assert "stat 과 ability 에 그 항목 이름을 그대로" in rules and "수치의 오르내림은 능력이 아니므로" not in rules


# 수치 줄이 없는 작품의 요청 글은 이 일감 전(main 173fdd06)과 글자까지 같다. 해시는 그 커밋에서 이 일감 없이 뽑았다.
_BEFORE = {
    "plan_lines": "54b2be0b62e65f7f", "ability_block": "aa0de20a50a659f7", "board": "b2af20832d9c4251", "write": "1e874924a63d3d35",
    "check": "702c5cb71f204e0b", "state": "8bf19180f43de9d9", "have": "465ca225993023bd", "owned": "4dbec046b55b03c6",
    "storyboard": "b9f384001cfaf263", "episode": "024dbd9e0b5c74c6", "state_prompt": "acc6547b1b9e168e",
    "ai_block_nostat": "9e26466ee599de9b", "check_prompt": "1b1781651524f16c",
}


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def test_requests_without_stat_lines_stay_the_same():
    p = _scheduled()
    p.abilities = [Ability(id="ab-01", name="빙결", aliases=["얼음 손"], grades=[AbilityGrade(grade="초급"), AbilityGrade(grade="중급"), AbilityGrade(grade="상급")])]
    p.episode(4).plot.summary = "서윤이 얼음손을 처음 제대로 쓴다"
    got = {
        "plan_lines": "\n".join(blueprint.ability_plan_lines(p, None, 4, 6)), "ability_block": prompts.blueprint_ability_block(p, None, 4, 6),
        "board": prompts.ability_board_rule(p, 4), "write": prompts.ability_write_line(p, 4), "check": prompts.ability_check_rule(p, 4),
        "state": blueprint.ability_state_rule(p, 4), "have": "\n".join(blueprint.ability_have_lines(p, {"hero"}, 4, 6)),
        "owned": "\n".join(blueprint.ability_owned_lines(p, {"hero"})), "storyboard": prompts.storyboard_prompt(p, 4),
        "episode": prompts.episode_prompt(p, 4), "state_prompt": prompts.state_prompt(p, 4),
    }
    for st in p.states:
        st.stats = [s for s in st.stats if s.name != "근력"]
    p.stat_log = [r for r in p.stat_log if r.name != "근력"]
    got["ai_block_nostat"] = prompts.ability_ai_block(p, {"hero"}, 4, 6)  # 수치 항목이 없으면 [지금 상태창의 수치] 도 없다
    p.episode(4).text, p.episode(4).status = "본문", "written"
    got["check_prompt"] = prompts.check_prompt(p, 4)
    assert {k: _h(v) for k, v in got.items()} == _BEFORE


def test_view_api_lists_stat_names_and_saves_stat_lines(client):
    meta = {"title": "성장", "genre": "판타지", "logline": "", "target_episodes": 10}
    assert client.post("/api/projects", json={"name": "gst", "meta": meta}).status_code == 200
    p = client.post("/api/projects/gst/suggest/apply", json=client.post("/api/projects/gst/suggest").json()).json()
    a = p["characters"][0]["id"]
    assert client.put(f"/api/projects/gst/statwin/{a}", json={"stats": [{"name": "레벨", "value": "Lv3"}, {"name": "스킬", "value": "은신"}]}).status_code == 200
    v = client.get("/api/projects/gst/blueprint").json()
    assert v["stat_names"] == {a: ["레벨"]}
    bp = {"milestones": [], "ladders": [], "note": "", "ability_plans": [{"character": a, "ability": "", "stat": "레벨", "grade": "Lv10", "from_ep": 2, "to_ep": 3}]}
    saved = client.put("/api/projects/gst/blueprint", json=bp)
    assert saved.status_code == 200
    row = client.get("/api/projects/gst").json()["blueprint"]["ability_plans"][0]
    assert (row["stat"], row["ability"], row["grade"]) == ("레벨", "레벨", "Lv10")
    v = client.get("/api/projects/gst/blueprint").json()
    assert v["plans"][0]["linked"] is True and v["ability_warnings"] == []
