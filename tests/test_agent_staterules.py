"""대화 에이전트의 상태 규칙 제안 propose_rule (docs/context/specs/07-rules.md 의 7c, canon/agent_staterules.py). mock LLM.

실행: CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_agent_staterules.py
"""
import json

from canon import agent, agent_staterules, prompts, store
from canon.schema import AGENT_TOOL_NAMES, AgentSession, CharacterState, StatValue

from .test_agent import _say, _session, _turn
from .test_agent_style import _usage_calls
from .test_plot_chat import _project


def _approve(client, sid, t=0, yes=True, **kw):
    return client.post(f"/api/projects/lh/sessions/{sid}/turns/{t}/approval", json={"approve": yes, **kw})


def _undo(client, sid, t=0):
    return client.post(f"/api/projects/lh/sessions/{sid}/turns/{t}/undo", json={})


def _setup(client) -> str:
    """작품 lh 에 첫 인물의 상태창(마력 0, 상태 정상)을 둔다. 첫 인물 id 를 돌려준다."""
    _project(client)
    p = store.load("lh")
    cid = p.characters[0].id
    st = p.state_of(cid)
    if st is None:
        p.states.append(CharacterState(character_id=cid))
        st = p.state_of(cid)
    st.stats = [StatValue(name="마력", value="0"), StatValue(name="상태", value="정상")]
    store.save("lh", p)
    return cid


def test_tool_is_registered_and_always_asks():
    assert {"propose_rule", "read_state_rules"} <= set(AGENT_TOOL_NAMES)
    assert agent.CARD_TOOLS["propose_rule"] is agent_staterules and agent_staterules.KIND == "rule"
    assert "read_state_rules" in agent.READ_TOOLS and agent.ALWAYS_ASK.count("rule") == 1
    assert agent.permit(AgentSession(id="x", mode="all", auto_kinds=["rule"]), "rule") == "ask"  # '모두 자동' · 묻지 않기도 늘 묻는다
    assert "- propose_rule (args:" in prompts.AGENT_PLOT_TOOLS and "- read_state_rules" in prompts.AGENT_PLOT_TOOLS
    assert "인과율 › 상태 규칙: 상태 규칙 지우기" in prompts.AGENT_PLOT_TOOLS


def test_card_apply_and_undo(client, monkeypatch):
    """새 규칙 카드: 적용 전에는 작품이 그대로이고, 적용하면 r1 로 들어가고, 되돌리면 빠진다. AI 호출은 에이전트 한 단계뿐이다."""
    cid = _setup(client)
    name = store.load("lh").characters[0].name
    calls = _usage_calls(monkeypatch)
    sid = _session(client, topic="agent")
    t = _say(client, sid, f"상태 규칙 {name} 마력 le 0 => {cid} 상태 기절")  # 조건의 인물은 이름으로 적어도 id 로 바꾼다
    a = t["approval"]
    assert t["end"] == "wait" and a["tool"] == "propose_rule" and a["kinds"] == ["rule"] and a["keys"] == ["rule"]
    c = a["state_rule"]
    assert c["before"] is None and c["rule"]["when"][0]["character"] == cid and c["rule"]["changes"][0]["value"] == "기절"
    assert calls == ["PlotAgentStep"]
    assert store.load("lh").state_rules == []  # 적용 전에는 그대로
    calls.clear()
    r = _approve(client, sid)
    assert r.status_code == 200, r.text
    assert calls == []
    rules = store.load("lh").state_rules
    assert [(x.id, x.name) for x in rules] == [("r1", "마력 0 le")]
    t = _turn(client, sid)
    assert t["end"] == "done" and t["approval"]["state"] == "approved"
    assert t["writes"][0]["state_rule"]["rule"]["id"] == "r1" and t["writes"][0]["items"][0]["label"] == "상태 규칙 · 마력 0 le"
    r = _undo(client, sid).json()
    assert r["restored"] == ["상태 규칙 · 마력 0 le"] and store.load("lh").state_rules == []


def test_edit_card_turns_rule_off_and_undo_keeps_later_edit(client):
    cid = _setup(client)
    sid = _session(client, topic="agent")
    _say(client, sid, f"상태 규칙 {cid} 마력 le 0 => {cid} 상태 기절")
    _approve(client, sid)
    t = _say(client, sid, "상태 규칙 rule=r1 끄기")
    c = t["approval"]["state_rule"]
    assert c["before"]["on"] is True and c["rule"]["on"] is False and "꺼 둔 규칙" in " ".join(c["notices"])
    assert _approve(client, sid, t=1).status_code == 200
    assert store.load("lh").state_rules[0].on is False
    p = store.load("lh")
    p.state_rules[0].name = "작가가 고침"
    store.save("lh", p)
    r = _undo(client, sid, t=1).json()
    assert r["restored"] == [] and r["kept"] and store.load("lh").state_rules[0].name == "작가가 고침"  # 그 뒤 고친 규칙은 그대로


def test_blocked_without_card_and_agent_replies(client):
    """JSON 이 아닌 when, 없는 인물은 카드 없이 까닭을 돌려주고 에이전트가 답으로 턴을 끝낸다."""
    _setup(client)
    sid = _session(client, topic="agent")
    t = _say(client, sid, "상태 규칙 깨진")
    assert t["approval"] is None and t["end"] == "done"
    block = next(s for s in t["steps"] if s["kind"] == "block")
    assert block["tool"] == "propose_rule" and "JSON" in block["why"]
    t = _say(client, sid, "상태 규칙 ghost 마력 le 0 => ghost 상태 기절")
    block = next(s for s in t["steps"] if s["kind"] == "block")
    assert "조건의 인물이 없어요: ghost" in block["why"] and "바꿀 인물이 없어요: ghost" in block["why"]
    assert store.load("lh").state_rules == []


def test_prepare_checks_and_holds_now():
    from canon.schema import AgentTurn, Character, Episode, EpisodePlot, PlotAgentStep, Project, StateRule, ToolArg
    p = Project()
    p.characters = [Character(id="hero", name="서윤", role="주인공"), Character(id="ally", name="도현", role="친구")]
    p.episodes = [Episode(plot=EpisodePlot(number=1, act="기", title="1", summary="", events=[], characters=["hero"], emotional_shift="", ending_hook=""),
                          status="finalized", text="글")]
    p.states = [CharacterState(character_id="hero", stats=[StatValue(name="마력", value="0")])]
    s, turn = AgentSession(id="s"), AgentTurn(message="m")

    def go(**args):
        return agent_staterules.prepare("w", p, s, turn, PlotAgentStep(tool="propose_rule", args=[ToolArg(name=k, value=v) for k, v in args.items()]))

    when = json.dumps([{"kind": "stat", "character": "서윤", "name": "마력", "op": "le", "value": "0"}], ensure_ascii=False)
    stat = json.dumps([{"kind": "stat", "character_id": "hero", "stat": "상태", "value": "기절"}], ensure_ascii=False)
    card = go(when=when, changes=stat)
    assert card.holds_ep == 1 and card.holds_now is True and card.rule.when[0].character == "hero"
    assert "changes" in go(when=when)  # 빈 변경
    assert go().startswith("인자가 하나도 없어요")  # 막힌 뒤 인자 없이 다시 부른 단계
    num = json.dumps([{"kind": "stat", "character": "hero", "name": "마력", "op": "le", "value": 0}])
    assert go(when=num, changes=stat).rule.when[0].value == "0"  # 수로 적은 값도 받는다
    assert "kind" in go(when=when, changes=json.dumps([{"kind": "tie", "character_id": "hero"}]))  # 관계 수치는 제안할 수 없다
    tie = json.dumps([{"kind": "tie", "character": "hero", "target": "ally", "name": "love", "op": "ge", "value": "1"}])
    assert "관계 수치 이름은" in go(when=tie, changes=stat)
    p.state_rules = [StateRule(id="r1", name="기절", when=card.rule.when, changes=card.rule.changes)]
    assert "같은 조건과 변경의 규칙이 이미 있어요: id r1" in go(when=when, changes=stat)
    assert "바뀌는 칸이 없어요" in go(rule="r1", name="기절")
    assert "찾을 수 없어요" in go(rule="r9", on="false")
    head, body = agent_staterules.read(p)
    data = json.loads(body)
    assert head == "상태 규칙 1개" and data["characters_with_stats"] == [{"id": "hero", "name": "서윤", "stats": ["마력"]}]
    assert data["state_rules"][0]["id"] == "r1" and list(data)[0] == "tie_names"
    p.state_rules = []
    mana = json.dumps([{"kind": "stat", "character": "hero", "name": "마나", "op": "le", "value": "0"}], ensure_ascii=False)
    assert "'마나'" in " ".join(go(when=mana, changes=stat).notices)  # 없는 상태창 항목은 막지 않고 알린다


from .jsvm import needs_node, run_js  # noqa: E402

SR_FILES = ["app.js", "chat.js", "agent.js", "staterules.js"]


@needs_node
def test_state_rule_card_shows_rule_and_no_remember_box():
    """상태 규칙 카드는 규칙 칸(조건 · 제안 요약)과 지금 조건이 맞는지를 보이고 '이 세션에서 묻지 않기'를 그리지 않는다. 고치기 카드는 바뀐 칸만 전 → 뒤."""
    rule = {"id": "", "name": "기절", "note": "", "on": True,
            "when": [{"kind": "stat", "character": "hero", "target": "", "name": "마력", "op": "le", "value": "0", "from_ep": 0, "to_ep": 0, "foreshadow": "", "status": "open"}],
            "changes": [{"kind": "stat", "character_id": "hero", "stat": "상태", "value": "기절", "foreshadow_id": ""}]}
    card = {"rule": rule, "before": None, "project": "lh", "holds_ep": 3, "holds_now": True, "notices": []}
    got = run_js(SR_FILES, """(() => {
      S.name = 'lh'; S.project = { episodes: [], chats: [], characters: [{ id: 'hero', name: '서윤' }], states: [], foreshadows: [] };
      S.agent = { name: 'lh', sessions: [], legacy: 0, older: [], model: 'm', max_steps: 8 };
      const ap = (c) => ({ tool: 'propose_rule', state_rule: c, keys: ['rule'], kinds: ['rule'], state: 'wait', picked: [], target: '', revision: null, op: null });
      const t = (c) => ({ user: '규칙', mode: '', steps: [], reply: '', writes: [], approval: ap(c), ask: null, end: 'wait' });
      const fresh = agentApproval(t(data), 0, true);
      const edit = agentApproval(t({ ...data, before: { ...data.rule, id: 'r1' }, rule: { ...data.rule, id: 'r1', on: false } }), 0, true);
      return { fresh, edit, name: agentToolName('propose_rule'), read: agentToolName('read_state_rules') };
    })()""", card)
    assert "상태 규칙 · 기절" in got["fresh"] and "서윤 마력 0 이하" in got["fresh"] and "서윤 상태를 기절로 바꾸자고 제안해요" in got["fresh"]
    assert "3화를 반영한 지금 상태로는 조건이 맞아요" in got["fresh"] and "data-agent-remember" not in got["fresh"]
    assert 'data-arg="0|1"' in got["fresh"] and "규칙 고치기" in got["edit"] and "<del>켬</del><ins>끔</ins>" in got["edit"]
    assert "마력 0 이하" not in got["edit"]  # 바뀌지 않은 칸은 보이지 않는다
    assert (got["name"], got["read"]) == ("상태 규칙 제안", "상태 규칙 읽기")


def test_all_mode_still_asks_and_remember_does_not_open(client):
    """'모두 자동' 세션에서도 propose_rule 은 카드로 묻고 상태 규칙은 그대로다. 승인할 때 '묻지 않기'를 보내도 rule 은 auto_kinds 에 들지 않는다 (Q29)."""
    cid = _setup(client)
    sid = _session(client, topic="agent")
    assert client.patch(f"/api/projects/lh/sessions/{sid}", json={"mode": "all"}).status_code == 200
    t = _say(client, sid, f"상태 규칙 {cid} 마력 le 0 => {cid} 상태 기절")
    assert t["end"] == "wait" and t["approval"]["state_rule"] and store.load("lh").state_rules == []
    assert _approve(client, sid, remember=True).status_code == 200
    sess = next(x for x in client.get("/api/projects/lh/sessions?topic=plot").json()["sessions"] if x["id"] == sid)
    assert sess["mode"] == "all" and "rule" not in sess["auto_kinds"] and len(store.load("lh").state_rules) == 1


def test_stale_edit_card_is_blocked_and_stays(client):
    cid = _setup(client)
    sid = _session(client, topic="agent")
    _say(client, sid, f"상태 규칙 {cid} 마력 le 0 => {cid} 상태 기절")
    _approve(client, sid)
    _say(client, sid, "상태 규칙 rule=r1 끄기")
    rule = client.get("/api/projects/lh/state-rules").json()[0]
    assert client.put("/api/projects/lh/state-rules/r1", json={**rule, "name": "작가가 먼저 고침"}).status_code == 200
    r = _approve(client, sid, t=1)
    assert r.status_code == 400 and "그 사이 규칙이 바뀌었어요" in r.text
    assert _turn(client, sid, t=1)["approval"]["state"] == "wait" and store.load("lh").state_rules[0].on is True


def test_empty_args_step_is_filled_with_typed_form(client, monkeypatch):
    """도구만 고르고 인자를 비운 단계(2026-11-15 실측)는 agent.fill 이 StateRuleFill 로 한 번 더 받아 카드를 띄운다. AI 호출 두 번."""
    cid = _setup(client)
    calls = _usage_calls(monkeypatch)
    sid = _session(client, topic="agent")
    t = _say(client, sid, f"상태 규칙 빈 {cid} 마력 le 0 => {cid} 상태 기절")
    assert t["end"] == "wait" and t["approval"]["state_rule"]["rule"]["changes"][0]["value"] == "기절"
    assert calls == ["PlotAgentStep", "StateRuleFill"]
