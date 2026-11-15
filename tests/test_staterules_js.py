"""상태 조건 고치기 칸(static/staterules.js)의 요약 · 없는 대상 경고와 인과율 요소 카드. node 가 있을 때만 돈다."""
from canon.schema import Activation, Character, CharacterState, Condition, Foreshadow, Project, StatValue, StoryElement

from .jsvm import dump, needs_node, run_js


def _p() -> Project:
    p = Project()
    p.characters = [Character(id="hero", name="서윤", role="주인공"), Character(id="ally", name="도현", role="친구")]
    p.states = [CharacterState(character_id="hero", stats=[StatValue(name="마력", value="0"), StatValue(name="스킬", value="은신")])]
    p.foreshadows = [Foreshadow(id="fs-1", description="낡은 열쇠가 등대 밑에 있다", planted_ep=1)]
    return p


CONDS = [
    Condition(kind="stat", character="hero", name="마력", op="le", value="0"),
    Condition(kind="stat", character="hero", name="스킬", op="has", value="은신"),
    Condition(kind="stat", character="hero", name="상태", op="eq", value="기절"),
    Condition(kind="tie", character="hero", target="ally", name="trust", op="ge", value="0.7"),
    Condition(kind="episode", from_ep=3, to_ep=10),
    Condition(kind="episode", from_ep=3),
    Condition(kind="episode"),
    Condition(kind="foreshadow", foreshadow="fs-1", status="resolved"),
    Condition(kind="in_plot", character="ghost"),
    Condition(kind="foreshadow", foreshadow="fs-9"),
    Condition(kind="tie", character="hero", target="ally", name="", value="0.5"),
]


@needs_node
def test_cond_summary_and_missing():
    got = run_js(["app.js", "staterules.js"], "data.conds.map((c) => [condSummary(c, data.p), condMissing(c, data.p)])",
                 {"p": dump(_p()), "conds": [dump(c) for c in CONDS]})
    assert got == [
        ["서윤 마력 0 이하", ""],
        ["서윤 스킬에 은신 있음", ""],
        ["서윤 상태: 기절", "없는 스탯이에요"],
        ["서윤 → 도현 신뢰 0.7 이상", ""],
        ["3~10화", ""],
        ["3화부터", ""],
        ["모든 화", ""],
        ["복선 「낡은 열쇠가 등대 밑에 있다」 회수됨", ""],
        ["이번 화 플롯에 나옴: ghost", "없는 인물이에요"],
        ["복선 「fs-9」 열림", "없는 복선이에요"],
        ["서윤 → 도현  0.5 이상", "관계 수치를 고르세요"],
    ]


@needs_node
def test_cond_editor_rows_and_add_delete():
    """조건 칸은 줄마다 종류 고르기와 지우기를 두고, 더하기 · 지우기는 등록한 주인의 목록을 고친다."""
    p = _p()
    p.elements = [StoryElement(id="e1", name="붉은 달", activation=Activation(conditions=CONDS[:2]))]
    expr = """(() => {
      S.project = data;
      const html = condEditor('el:e1', data.elements[0].activation.conditions, data);
      COND_OWNERS.el = (id) => S.project.elements.find((x) => x.id === id).activation.conditions;
      markDirty = () => {}; render = () => {};
      actions.condAdd('el:e1');
      const added = S.project.elements[0].activation.conditions.map((c) => c.kind);
      actions.condDel('el:e1|0');
      return { rows: (html.match(/class="cond-row"/g) || []).length, kinds: (html.match(/data-cond-f="kind"/g) || []).length,
               dels: (html.match(/data-action="condDel"/g) || []).length, added,
               left: S.project.elements[0].activation.conditions.map((c) => c.name) };
    })()"""
    got = run_js(["app.js", "staterules.js"], expr, dump(p))
    assert got == {"rows": 2, "kinds": 2, "dels": 2, "added": ["stat", "stat", "stat"], "left": ["스킬", ""]}


@needs_node
def test_kind_switch_resets_row():
    """종류를 바꾸면 인물만 남기고 앞 종류의 항목 이름 · 값을 비운다 (늘 맞지 않는 조건이 남지 않게)."""
    p = _p()
    p.elements = [StoryElement(id="e1", activation=Activation(conditions=CONDS[:1]))]
    expr = """(() => {
      S.project = data;
      COND_OWNERS.el = (id) => S.project.elements.find((x) => x.id === id).activation.conditions;
      markDirty = () => {}; render = () => {};
      const sel = { tagName: 'SELECT', value: 'tie', dataset: { cond: 'el:e1', condI: '0', condF: 'kind' } };
      condChange(sel);
      return S.project.elements[0].activation.conditions[0];
    })()"""
    got = run_js(["app.js", "staterules.js"], expr, dump(p))
    assert (got["kind"], got["character"], got["name"], got["value"], got["op"]) == ("tie", "hero", "", "", "ge")
