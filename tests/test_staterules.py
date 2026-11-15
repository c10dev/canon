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
