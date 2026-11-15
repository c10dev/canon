"""상태 조건 (docs/context/specs/07-rules.md 의 7a): 조건 판정 context.holds 와 효과 (x) 이야기 요소 넣기. LLM 비용 없음.
실행: CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_staterules.py"""
import json

import pytest

from canon import context, elements, prompts, renumber
from canon.schema import (Activation, Character, CharacterState, Condition, Episode, EpisodePlot, Foreshadow, Project,
                          Snapshot, StatValue, StoryElement, Tie)


def _plot(n, chars=("hero",)):
    return EpisodePlot(number=n, act="기", title=f"{n}화", summary="요약", events=["사건"], characters=list(chars),
                       emotional_shift="", ending_hook="")


def _project() -> Project:
    p = Project()
    p.characters = [Character(id="hero", name="서윤", role="주인공"), Character(id="ally", name="도현", role="친구")]
    p.episodes = [Episode(plot=_plot(1), status="finalized", text="서윤이 섰다."),
                  Episode(plot=_plot(2, ("ally",)), status="confirmed"),
                  Episode(plot=_plot(3, ("hero", "ally")), status="draft")]
    p.states = [CharacterState(character_id="hero", stats=[StatValue(name="마력", value="0"), StatValue(name="골드", value="1,200골드"),
                                                          StatValue(name="HP", value="30/100"), StatValue(name="상태", value="정상"),
                                                          StatValue(name="스킬", value="화염구 Lv3, 은신")])]
    p.ties = [Tie(source="hero", target="ally", warmth=0.5, trust_pos=8, trust_neg=2)]
    p.foreshadows = [Foreshadow(id="fs-1", description="낡은 열쇠", planted_ep=1), Foreshadow(id="fs-2", description="편지", planted_ep=1, status="resolved")]
    return p


def stat(name, op, value, who="hero"):
    return Condition(kind="stat", character=who, name=name, op=op, value=value)


@pytest.mark.parametrize("cond,want", [
    (stat("마력", "le", "0"), True),
    (stat("마력", "lt", "0"), False),
    (stat("골드", "ge", "1000"), True),        # 단위 · 쉼표를 떼고 수로 견준다 (statwin.resolve 와 같은 규칙)
    (stat("HP", "lt", "50"), True),           # '30/100' 은 앞 수
    (stat("상태", "eq", "정상"), True),
    (stat("상태", "ne", "기절"), True),
    (stat("상태", "ge", "가"), False),         # 글끼리는 크기를 견주지 않는다
    (stat("스킬", "has", "화염구"), True),      # 등급이 붙은 항목도 이름으로 찾는다
    (stat("스킬", "has", "독 내성"), False),
    (stat("마나", "le", "0"), False),           # 없는 스탯
    (stat("마력", "le", "0", who="ghost"), False),  # 없는 인물
    (Condition(kind="tie", character="hero", target="ally", name="trust", op="ge", value="0.7"), True),
    (Condition(kind="tie", character="hero", target="ally", name="warmth", op="gt", value="0.5"), False),
    (Condition(kind="tie", character="ally", target="hero", name="trust", op="ge", value="0"), False),  # 없는 관계
    (Condition(kind="tie", character="hero", target="ally", name="nope", op="ge", value="0"), False),
    (Condition(kind="foreshadow", foreshadow="fs-1", status="open"), True),
    (Condition(kind="foreshadow", foreshadow="fs-2", status="open"), False),
    (Condition(kind="foreshadow", foreshadow="fs-9", status="open"), False),  # 없는 복선
    (Condition(kind="in_plot", character="ally"), True),
    (Condition(kind="in_plot", character="hero"), False),
    (Condition(kind="episode", from_ep=2, to_ep=3), True),
    (Condition(kind="episode", from_ep=3), False),
    (Condition(kind="episode", to_ep=1), False),
    (Condition(kind="episode"), True),
])
def test_holds(cond, want):
    p = _project()
    before = p.model_dump()
    assert context.holds(p, 2, cond) is want
    assert p.model_dump() == before  # 읽기만 한다 (get_tie 처럼 관계를 만들지 않는다)


def test_view_before_reads_snapshot_when_later_episodes_are_applied():
    p = _project()
    assert context.view_before(p, 2).states is p.states  # 1화까지 반영 → 지금 값
    p.episode(2).status = "finalized"  # 2화까지 반영했는데 2화를 다시 볼 때는 1화 스냅샷
    view = context.view_before(p, 2)
    assert view.states is p.states and "1화 스냅샷이 없어" in view.note
    p.snapshots = [Snapshot(episode=1, states=[CharacterState(character_id="hero", stats=[StatValue(name="마력", value="5")])])]
    view = context.view_before(p, 2)
    assert view.note == "" and context.holds(p, 2, stat("마력", "ge", "5"), view)
    assert not context.holds(p, 2, stat("마력", "le", "0"))
    assert context.holds(p, 3, stat("마력", "le", "0"))  # 3화는 2화를 반영한 지금 값


def test_all_hold_is_and_and_empty_is_true():
    p = _project()
    assert context.all_hold(p, 2, [])
    assert context.all_hold(p, 2, [stat("마력", "le", "0"), Condition(kind="in_plot", character="ally")])
    assert not context.all_hold(p, 2, [stat("마력", "le", "0"), Condition(kind="in_plot", character="hero")])


def _el(id_, conds, **kw):
    return StoryElement(id=id_, name=kw.pop("name", id_), description=f"{id_} 설명", activation=Activation(conditions=conds), **kw)


def test_element_gate():
    p = _project()
    yes, no = stat("마력", "le", "0"), stat("마력", "ge", "1")
    p.elements = [
        _el("늘맞음", [yes], context="always"),
        _el("늘안맞음", [no], context="always"),
        _el("관련안맞음", [no], characters=["ally"]),  # 2화 플롯 인물이 얽혔지만 조건이 문이다
        _el("관련맞음", [yes], characters=["ally"]),
        _el("끔", [yes], context="off"),               # 작가가 끈 것을 규칙이 켜지 않는다
        _el("조건없음", [], characters=["ally"]),
        _el("무관", [yes]),                            # 조건이 맞아도 관련이 없으면 넣지 않는다
    ]
    got = [el.id for el in elements.for_episode(p, 2)]
    assert got == ["늘맞음", "관련맞음", "조건없음"]
    assert [el.id for el in elements.for_episode(p, 2, gate=False)] == ["늘맞음", "늘안맞음", "관련안맞음", "관련맞음", "조건없음"]
    block = elements.episode_block(p, 2)
    assert "늘맞음 설명" in block and "늘안맞음" not in block
    assert "늘안맞음" in context.query_terms(p, 2)  # 관련 말 고르기는 조건을 보지 않는다


def test_prompt_unchanged_when_conditions_hold_and_drops_when_not():
    """조건이 모두 맞는 요소는 조건이 없는 요소와 같은 프롬프트, 맞지 않으면 쓰기 · 작업지시서 · 부분 수정 요청에서 빠진다."""
    for serial in (False, True):
        p = _project()
        p.meta.form = "serial" if serial else "short"
        p.elements = [StoryElement(id="e1", name="붉은 달", description="달이 붉으면 마력이 는다", context="always")]
        plain = (prompts.episode_prompt(p, 2), prompts.episode_brief(p, 2), prompts.passage_head(p, 2))
        p.elements[0].activation.conditions = [stat("마력", "le", "0"), Condition(kind="episode", from_ep=2)]
        assert (prompts.episode_prompt(p, 2), prompts.episode_brief(p, 2), prompts.passage_head(p, 2)) == plain
        p.elements[0].activation.conditions = [stat("마력", "ge", "1")]
        for text in (prompts.episode_prompt(p, 2), prompts.episode_brief(p, 2), prompts.passage_head(p, 2)):
            assert "붉은 달" not in text and "# 이야기 요소" not in text


def test_old_project_json_reads_and_empty_activation_by_default():
    raw = json.loads(_project().model_dump_json())
    raw["elements"] = [{"id": "e1", "name": "옛 요소"}]
    p = Project.model_validate(raw)
    assert p.elements[0].activation.conditions == []
    assert "activation" not in json.dumps(StoryElement.model_json_schema())  # AI 응답 형식에 들어가지 않는다


def test_basis_ignores_conditions():
    el = StoryElement(id="e1", name="탑")
    b = elements.basis(el)
    el.activation.conditions.append(stat("마력", "le", "0"))
    assert elements.basis(el) == b  # 조건을 고쳐도 영향 분석이 지난 것으로 치지 않는다


def test_renumber_moves_condition_ranges():
    p = _project()
    p.elements = [_el("e", [Condition(kind="episode", from_ep=2, to_ep=3), Condition(kind="episode")])]
    renumber.move_points(p, renumber.point_insert(2))
    c1, c2 = p.elements[0].activation.conditions
    assert (c1.from_ep, c1.to_ep, c2.from_ep, c2.to_ep) == (3, 4, 0, 0)
    renumber.move_points(p, renumber.point_remove(1))
    assert (c1.from_ep, c1.to_ep) == (2, 3)


def test_rebuild_moves_condition_ranges():
    """단편 → 장편 재구성도 요소 상태 조건의 화 범위를 새 화 번호로 옮긴다 (reshape, since_ep 과 같은 _remap)."""
    from canon import pipeline
    from tests.test_convert import LLM, _short as short_project
    p = short_project(written=8)
    el = p.elements[0]
    el.since_ep = 3
    el.activation.conditions = [Condition(kind="episode", from_ep=3, to_ep=12), Condition(kind="episode")]
    prop = pipeline.propose_rebuild(LLM, p, 200)
    pipeline.apply_rebuild(p, prop, at="2026-10-22T00:00:00+00:00")
    c1, c2 = p.elements[0].activation.conditions
    assert (c1.from_ep, c1.to_ep) == (p.elements[0].since_ep, 18) and (c2.from_ep, c2.to_ep) == (0, 0)


# ---------- 7b: 효과 (y) 상태 규칙 제안 ----------

from canon import autorun, pipeline, staterules, store  # noqa: E402
from canon.schema import RuleProposalSpec, StateDelta, StateRule  # noqa: E402


def _ready() -> Project:
    """2화를 반영할 차례인 작품: 1화 반영, 2화 본문 있음."""
    p = _project()
    p.episode(2).status, p.episode(2).text = "written", "도현이 웃었다."
    return p


def _rule(id_, when, *changes, name="", on=True):
    return StateRule(id=id_, name=name or id_, on=on, when=when, changes=list(changes))


def ch_stat(value, name="상태", who="hero"):
    return RuleProposalSpec(kind="stat", character_id=who, stat=name, value=value)


def _delta(n=2, **kw) -> StateDelta:
    return StateDelta(episode=n, summary="요약", **kw)


def test_propose_when_conditions_hold_and_not_otherwise():
    p = _ready()
    p.state_rules = [_rule("r1", [stat("마력", "le", "0")], ch_stat("기절"), name="기절"),
                     _rule("r2", [stat("마력", "ge", "1")], ch_stat("멀쩡")),
                     _rule("r3", [stat("마력", "le", "0")], ch_stat("졸림"), on=False)]
    before = p.model_dump()
    got = staterules.propose(p, _delta())
    assert p.model_dump() == before  # 작품을 바꾸지 않는다
    assert [(x.rule_id, x.before, x.after, x.key) for x in got] == [("r1", "정상", "기절", "r1:stat:hero:상태")]
    assert staterules.describe(p, got[0]) == "규칙 「기절」: 서윤 상태 정상 → 기절"


def test_no_repeat_for_same_value_but_amount_repeats():
    p = _ready()
    p.state_rules = [_rule("r1", [], ch_stat("정상")), _rule("r2", [], ch_stat("+은신", name="스킬")),
                     _rule("r3", [Condition(kind="episode", from_ep=3)], ch_stat("+3", name="마력")),
                     _rule("r4", [], ch_stat("+1", name="골드"))]
    assert [x.rule_id for x in staterules.propose(p, _delta())] == ["r4"]  # 같은 값 · 이미 있는 항목은 다시 오지 않는다
    assert staterules.propose(p, _delta())[0].after == "1,201골드"
    p.episode(3).status, p.episode(3).text = "written", "글"
    pipeline.apply_delta(p, _delta(2))
    assert [x.rule_id for x in staterules.propose(p, _delta(3))] == ["r3", "r4"]  # 바뀐 양은 조건이 맞는 화마다


def test_rules_do_not_chain_and_later_rule_wins_with_warning():
    p = _ready()
    p.state_rules = [_rule("a", [], ch_stat("5", name="마력"), name="채움"),
                     _rule("b", [stat("마력", "ge", "5")], ch_stat("기절")),  # a 의 제안을 반영한 값으로 다시 보지 않는다
                     _rule("c", [], ch_stat("9", name="마력"), name="더 채움")]
    got = staterules.propose(p, _delta())
    assert [(x.rule_id, x.after) for x in got] == [("c", "9")]
    assert "「채움」" in got[0].warning


def test_conditions_see_ai_delta_and_warn_on_same_stat():
    p = _ready()
    p.state_rules = [_rule("r1", [stat("마력", "le", "-5")], ch_stat("기절"))]
    d = _delta(character_updates=[CharacterState(character_id="hero", stats=[StatValue(name="마력", value="-5"), StatValue(name="상태", value="피곤")])])
    got = staterules.propose(p, d)
    assert [(x.before, x.after) for x in got] == [("피곤", "기절")] and got[0].warning == staterules.AI_TOO


def test_resolve_and_missing_targets():
    p = _ready()
    p.state_rules = [_rule("r1", [], RuleProposalSpec(kind="resolve", foreshadow_id="fs-1"),
                           RuleProposalSpec(kind="resolve", foreshadow_id="fs-2"),   # 이미 회수
                           RuleProposalSpec(kind="resolve", foreshadow_id="fs-9"),   # 없는 복선
                           ch_stat("기절", who="ghost"))]  # 없는 인물 (반영 뒤에도 상태가 없다)
    assert [x.key for x in staterules.propose(p, _delta())] == ["r1:resolve:fs-1"]


def test_apply_delta_applies_checked_and_dismisses_unchecked_then_revert():
    p = _ready()
    p.snapshots = [Snapshot(episode=1, states=[s.model_copy(deep=True) for s in p.states], foreshadows=[f.model_copy(deep=True) for f in p.foreshadows])]
    p.state_rules = [_rule("r1", [], ch_stat("기절")), _rule("r2", [], RuleProposalSpec(kind="resolve", foreshadow_id="fs-1")),
                     _rule("r3", [], ch_stat("+5", name="마력"))]
    d = _delta()
    staterules.refill(p, d)
    d.rule_off = ["r3:stat:hero:마력"]
    pipeline.apply_delta(p, d)
    assert _stat(p, "상태") == "기절" and _stat(p, "마력") == "0"
    assert next(f for f in p.foreshadows if f.id == "fs-1").status == "resolved"
    assert [r.source for r in p.stat_log] == ["rule"]
    h = p.history[-1]
    assert [x.rule_id for x in h.rule_proposals] == ["r1", "r2"] and [x.rule_id for x in h.dismissed.rule_proposals] == ["r3"]
    pipeline.revert(p, 1)
    assert _stat(p, "상태") == "정상" and next(f for f in p.foreshadows if f.id == "fs-1").status == "open" and p.stat_log == []


def _stat(p, name, who="hero"):
    return next(x.value for x in p.state_of(who).stats if x.name == name)


def test_validate_delta_blocks_rule_proposals_to_missing_targets():
    p = _ready()
    d = _delta()
    d.rule_proposals = [staterules.RuleProposal(kind="stat", character_id="ghost", stat="마력", value="1", key="k")]
    assert pipeline.validate_delta(p, d) == ["상태 규칙 제안이 설정에 없는 인물을 가리켜요: ghost"]


def test_story_reasons_stop_on_rule_resolve():
    p = _ready()
    d = _delta()
    d.rule_proposals = [staterules.RuleProposal(kind="resolve", foreshadow_id="fs-1", key="r:resolve:fs-1")]
    got = autorun._story_reasons(p, d, autorun.Policy(stop_on_resolve=True), {c.id: c.name for c in p.characters})
    assert got == ["복선 1개를 회수했어요: 낡은 열쇠"]
    d.rule_off = ["r:resolve:fs-1"]
    assert autorun._story_reasons(p, d, autorun.Policy(stop_on_resolve=True), {c.id: c.name for c in p.characters}) == []


def test_extract_state_fills_rules_and_old_projects_stay_empty():
    from canon.mock import MockLLM
    p = _ready()
    assert pipeline.extract_state(MockLLM(), p, 2).rule_proposals == []  # 규칙이 없는 작품은 지금과 같다
    p.state_rules = [_rule("r1", [], ch_stat("기절"))]
    assert [x.rule_id for x in pipeline.extract_state(MockLLM(), p, 2).rule_proposals] == ["r1"]


def test_web_preview_apply_stale_rules_and_force(client):
    p = _ready()
    p.state_rules = [_rule("r1", [stat("마력", "le", "-1")], ch_stat("기절"))]
    store.save("sr", p)
    up = CharacterState(character_id="hero", stats=[StatValue(name="마력", value="-3")])
    plain = _delta().model_dump()
    with_ai = _delta(character_updates=[up]).model_dump()
    assert client.post("/api/projects/sr/episodes/2/preview", json=plain).json()["rule_proposals"] == []
    got = client.post("/api/projects/sr/episodes/2/preview", json=with_ai).json()["rule_proposals"]
    assert [x["key"] for x in got] == ["r1:stat:hero:상태"]  # 고른 AI 제안에 따라 바뀐다
    r = client.post("/api/projects/sr/episodes/2/apply", json={**with_ai, "rule_proposals": []})
    assert r.status_code == 409 and r.json()["code"] == "stale_rules" and len(r.json()["rule_proposals"]) == 1
    assert client.post("/api/projects/sr/episodes/2/apply?force=1", json={**with_ai, "rule_proposals": []}).status_code == 409
    q = client.post("/api/projects/sr/episodes/2/apply?force_rules=1", json={**with_ai, "rule_proposals": []}).json()
    assert next(x["value"] for x in q["states"][0]["stats"] if x["name"] == "상태") == "기절"  # 서버가 다시 계산한 제안을 반영한다


def test_web_apply_rule_off_goes_to_dismissed(client):
    p = _ready()
    p.state_rules = [_rule("r1", [], ch_stat("기절"))]
    store.save("sr", p)
    props = client.post("/api/projects/sr/episodes/2/preview", json=_delta().model_dump()).json()["rule_proposals"]
    body = _delta().model_dump()
    body["dismissed"]["rule_proposals"] = props  # 화면도 체크를 푼 제안을 빼 둔다 (pickedDelta). 기록에는 한 번만 남는다
    q = client.post("/api/projects/sr/episodes/2/apply", json={**body, "rule_proposals": props, "rule_off": [props[0]["key"]]}).json()
    assert next(x["value"] for x in q["states"][0]["stats"] if x["name"] == "상태") == "정상"
    assert [x["key"] for x in q["history"][-1]["dismissed"]["rule_proposals"]] == ["r1:stat:hero:상태"]


def test_web_state_rules_crud(client):
    store.save("sr", _ready())
    rules = client.post("/api/projects/sr/state-rules", json={"name": "기절", "when": [stat("마력", "le", "0").model_dump()],
                                                              "changes": [ch_stat("기절").model_dump()]}).json()
    assert [r["id"] for r in rules] == ["r1"]
    rules = client.post("/api/projects/sr/state-rules", json={"name": "둘"}).json()
    assert [r["id"] for r in rules] == ["r1", "r2"]
    rules = client.put("/api/projects/sr/state-rules/r1", json={**rules[0], "on": False, "id": "zz"}).json()
    assert rules[0]["id"] == "r1" and rules[0]["on"] is False
    assert [r["id"] for r in client.delete("/api/projects/sr/state-rules/r2").json()] == ["r1"]
    assert client.delete("/api/projects/sr/state-rules/nope").status_code == 404
    assert len(client.get("/api/projects/sr/state-rules").json()) == 1


def test_prompt_view_shows_condition_drops_and_note(client):
    p = _ready()
    p.episode(2).status = "finalized"
    p.episode(3).status = "draft"
    p.elements = [_el("붉은 달", [stat("마력", "ge", "1")], context="always"), _el("밤", [stat("마력", "le", "0")], context="always")]
    store.save("sr", p)
    rows = client.get("/api/projects/sr/episodes/2/context").json()
    els = next(r for r in rows if r["id"] == "elements")
    assert {"name": "붉은 달", "reason": context.DROP_COND} in els["dropped"]
    assert any(x["reason"] == context.NOTE_COND and "1화 스냅샷이 없어" in x["name"] for x in els["items"])
    assert {"name": "밤", "reason": context.REASON_COND} in els["items"]


def test_cli_staterules(capsys, tmp_path, monkeypatch):
    from canon import cli
    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _ready()
    p.state_rules = [_rule("r1", [], ch_stat("기절"), name="기절"), _rule("r2", [], on=False)]
    store.save("sr", p)
    cli.main(["staterules", "sr"])
    out = capsys.readouterr().out
    assert "상태 규칙 2개 (켬 1개)" in out and "r1 [켬] 기절: 조건 0개 · 제안 1개" in out


def test_stat_timeline_source_merge():
    from canon import statwin
    assert statwin._merge_source("ai", "rule") == "rule" and statwin._merge_source("rule", "author") == "both"
    assert statwin._merge_source("ai", "author") == "both" and statwin._merge_source("rule", "rule") == "rule"
    assert statwin.SOURCE["rule"] == " (규칙)"


def test_parse_state_fills_rule_proposals(client):
    p = _ready()
    p.state_rules = [_rule("r1", [], ch_stat("기절"))]
    store.save("sr", p)
    got = client.post("/api/projects/sr/episodes/2/state/parse", json={"raw": '{"summary": "요약"}'})
    assert got.status_code == 200, got.text
    assert [x["key"] for x in got.json()["rule_proposals"]] == ["r1:stat:hero:상태"]


def test_renumber_and_rebuild_move_rule_ranges():
    p = _project()
    p.state_rules = [_rule("r1", [Condition(kind="episode", from_ep=2, to_ep=3)])]
    renumber.move_points(p, renumber.point_insert(2))
    c = p.state_rules[0].when[0]
    assert (c.from_ep, c.to_ep) == (3, 4)
    from canon import pipeline as pl
    from tests.test_convert import LLM, _short as short_project
    q = short_project(written=8)
    q.state_rules = [_rule("r1", [Condition(kind="episode", from_ep=3, to_ep=12)])]
    pl.apply_rebuild(q, pl.propose_rebuild(LLM, q, 200), at="2026-10-22T00:00:00+00:00")
    c = q.state_rules[0].when[0]
    assert (c.from_ep, c.to_ep) == (4, 18)  # since_ep 과 같은 지도 (test_rebuild 의 3 → 4, 12 → 18)
