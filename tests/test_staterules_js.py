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


# ---------- 7b: 상태 승인 화면의 규칙 제안 · 상태 규칙 쪽 ----------
import re  # noqa: E402

from canon.schema import RuleProposal, RuleProposalSpec, StateDelta, StateRule  # noqa: E402

from .jsvm import STATIC  # noqa: E402

FILES = re.findall(r'src="/static/([a-z0-9]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


def _prop(key, after="기절", rid="r1"):
    return RuleProposal(kind="stat", character_id="hero", stat="상태", value=after, rule_id=rid, rule_name="기절", key=key, before="정상", after=after)


@needs_node
def test_rule_rows_default_checked_and_refresh_keeps_unchecked():
    """규칙 제안은 기본 체크('규칙' 표시), rule_off 는 풀린 채. 미리 보기가 다시 계산해도 작가가 푼 key 는 풀린 채 두고 새 key 는 체크한다."""
    p = _p()
    d = StateDelta(episode=1, summary="s", rule_proposals=[_prop("a"), _prop("b")], rule_off=["b"])
    expr = """(() => {
      S.project = data.p; S.name = 't'; S.route = ['p', 't', 'x'];
      S.deltas = { 1: data.d }; S.picks = {}; render = () => {};
      Object.assign(S.picks, defaultPicks(data.d));
      const first = [S.picks.g0, S.picks.g1, ruleRows(data.d).includes('<span class="chip">규칙</span>')];
      S.picks.g0 = false;  // 작가가 a 를 푼다
      ruleRefresh(1, [data.c, data.a]);  // 다시 계산: c 가 새로 생김, b 는 빠짐
      const out = pickedDelta(1);
      return { first, picks: [S.picks.g0, S.picks.g1], keys: out.rule_proposals.map((x) => x.key), off: out.rule_off,
               dismissed: out.dismissed.rule_proposals.map((x) => x.key), count: deltaCount(out) };
    })()"""
    got = run_js(FILES, expr, {"p": dump(p), "d": dump(d), "a": dump(_prop("a")), "c": dump(_prop("c"))})
    assert got == {"first": [True, False, True], "picks": [True, False], "keys": ["c", "a"], "off": ["a"], "dismissed": ["a"], "count": 2}


@needs_node
def test_spec_summary_and_missing():
    p = _p()
    specs = [RuleProposalSpec(character_id="hero", stat="상태", value="기절"), RuleProposalSpec(character_id="hero", stat="마력", value="+3"),
             RuleProposalSpec(character_id="hero", stat="스킬", value=""), RuleProposalSpec(kind="resolve", foreshadow_id="fs-1"),
             RuleProposalSpec(character_id="ally", stat="상태", value="x"), RuleProposalSpec(character_id="ghost", stat="상태", value="x"),
             RuleProposalSpec(kind="resolve", foreshadow_id="nope")]
    got = run_js(["app.js", "staterules.js"], "data.s.map((c) => [specSummary(c, data.p), specMissing(c, data.p)])",
                 {"p": dump(p), "s": [dump(x) for x in specs]})
    assert got == [
        ["서윤 상태를 기절로 바꾸자고 제안해요", ""],
        ["서윤 마력 +3 바꾸자고 제안해요", ""],
        ["서윤 스킬을 지우자고 제안해요", ""],
        ["복선 「낡은 열쇠가 등대 밑에 있다」 회수를 제안해요", ""],
        ["도현 상태를 x(으)로 바꾸자고 제안해요", "상태가 없는 인물이에요"],
        ["ghost 상태를 x(으)로 바꾸자고 제안해요", "없는 인물이에요"],
        ["복선 「nope」 회수를 제안해요", "없는 복선이에요"],
    ]


@needs_node
def test_rules_page_lists_rules_and_condition_elements():
    p = _p()
    p.state_rules = [StateRule(id="r1", name="기절", when=CONDS[:1], changes=[RuleProposalSpec(character_id="hero", stat="상태", value="기절")]),
                     StateRule(id="r2", name="끈 것", on=False)]
    p.elements = [StoryElement(id="e1", name="붉은 달", activation=Activation(conditions=CONDS[:1]))]
    html = run_js(FILES, "(() => { S.project = data; S.name = 't'; S.route = ['p', 't', 'causal', '_rules']; S.causalSel = '_rules'; return viewCausal(); })()", dump(p))
    assert "상태 규칙 2" in html and "서윤 마력 0 이하" in html and "서윤 상태를 기절로 바꾸자고 제안해요" in html
    assert 'class="sr-row off"' in html and "이 항목을 넣어요: 붉은 달" in html and 'aria-current="page"><span class="tl">상태 규칙' in html
    empty = _p()
    html = run_js(FILES, "(() => { S.project = data; S.name = 't'; S.causalSel = '_rules'; return viewCausal(); })()", dump(empty))
    assert "아직 규칙이 없어요. 조건과 효과를 골라 규칙을 만들어 보세요." in html


@needs_node
def test_review_has_no_rule_group_without_rules():
    """켠 규칙이 없는 작품의 상태 승인 화면은 지금과 같다: '상태 규칙 제안' 갈래도 '변경 없음' 줄의 이름도 없다."""
    from .jsvm import episode
    p = _p()
    p.episodes = [episode(1, status="written", text="본문.")]
    d = StateDelta(episode=1, summary="s")
    expr = """(() => { S.project = data.p; S.name = 't'; S.route = ['p', 't', 'review', '1']; setDelta(1, data.d); return viewReview(1); })()"""
    html = run_js(FILES, expr, {"p": dump(p), "d": dump(d)})
    assert "상태 규칙 제안" not in html
    p.state_rules = [StateRule(id="r1", name="기절")]
    html = run_js(FILES, expr, {"p": dump(p), "d": dump(d)})
    assert "상태 규칙 제안" in html  # 켠 규칙이 있으면 걸린 제안이 없어도 '변경 없음' 에 보인다


@needs_node
def test_history_view_shows_applied_and_dismissed_rule_proposals():
    h = StateDelta(episode=1, summary="s", rule_proposals=[_prop("a")])
    h.dismissed.rule_proposals = [_prop("b", after="졸림", rid="r2")]
    html = run_js(FILES, "(() => { S.project = data.p; S.name = 't'; return historyView(data.h); })()", {"p": dump(_p()), "h": dump(h)})
    assert "<h2>상태 규칙 제안</h2>" in html and "「기절」: 서윤 상태 정상 → 기절" in html
    assert "빼 둔 항목 1개" in html and "상태 규칙 제안 · 「기절」: 서윤 상태 정상 → 졸림" in html
