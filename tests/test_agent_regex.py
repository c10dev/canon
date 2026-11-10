"""대화 에이전트의 정규식 규칙 제안 (docs/context/specs/06b-rule-propose.md, canon/agent_regex.py). mock LLM.

실행: CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_agent_regex.py
"""
import json

from canon import agent, agent_regex, prompts, regexrules, store
from canon.schema import AGENT_TOOL_NAMES, AgentSession

from .test_agent import _say, _session, _turn
from .test_agent_style import _usage_calls
from .test_plot_chat import _project

TEXT = "그는 웃었다... 그리고 말했다... 끝."
ELLIPSIS = "말줄임표 규칙 고침 «...» «…»"  # mock: 첫 «» 는 찾을 글, 둘째 «» 는 바꿀 글, '고침' 은 fix


def _text(client, n=2, text=TEXT, name="lh"):
    p = client.get(f"/api/projects/{name}").json()
    p["episodes"][n - 1]["text"] = text
    p["episodes"][n - 1]["status"] = "written"
    assert client.put(f"/api/projects/{name}", json=p).status_code == 200


def _make(client, name="표기", rules=None) -> str:
    r = client.post("/api/rules", json={"name": name, "rules": rules or []})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _use(client, *ids, name="lh"):
    r = client.put(f"/api/projects/{name}/rule-bundles", json={"bundles": list(ids)})
    assert r.status_code == 200, r.text


def _approve(client, sid, t=0, yes=True, **kw):
    return client.post(f"/api/projects/lh/sessions/{sid}/turns/{t}/approval", json={"approve": yes, **kw})


def _undo(client, sid, t=0):
    return client.post(f"/api/projects/lh/sessions/{sid}/turns/{t}/undo", json={})


def _setup(client, rules=None):
    """작품 lh(2화에 본문)와 이 작품이 켠 묶음 하나."""
    _project(client)
    _text(client)
    bid = _make(client, rules=rules)
    _use(client, bid)
    return bid


# ---------- 등록 · 프롬프트 ----------

def test_tool_is_registered_and_always_asks():
    assert "propose_regex" in AGENT_TOOL_NAMES and "read_rules" in AGENT_TOOL_NAMES
    assert agent.CARD_TOOLS["propose_regex"] is agent_regex
    assert "rule" in agent.ALWAYS_ASK and agent.KIND_LABELS["rule"] == "규칙"
    assert "read_rules" in agent.READ_TOOLS
    assert agent.permit(AgentSession(id="x", mode="all", auto_kinds=["rule"]), "rule") == "ask"


def test_prompt_lists_both_tools():
    assert "- propose_regex (args:" in prompts.AGENT_PLOT_TOOLS
    assert "- read_rules" in prompts.AGENT_PLOT_TOOLS
    assert "규칙 묶음 화면: 정규식 규칙 · 묶음 지우기" in prompts.AGENT_PLOT_TOOLS


# ---------- 카드 · 적용 · 되돌리기 ----------

def test_card_apply_and_undo(client, monkeypatch):
    """켠 묶음 하나에 고침 규칙을 제안한다. 카드에는 2화에 걸어 본 결과가 들고, 적용하면 규칙이 하나 늘고 버전이 오른다.
    이미 쓴 본문과 규칙 걸기 기록은 바뀌지 않는다. 되돌리면 그 규칙만 빠진다. AI 호출은 에이전트 한 단계뿐이다."""
    bid = _setup(client)
    v0 = regexrules.load(bid).version
    ep_before = client.get("/api/projects/lh").json()["episodes"][1]
    calls = _usage_calls(monkeypatch)
    sid = _session(client, topic="agent")
    t = _say(client, sid, ELLIPSIS)
    a = t["approval"]
    assert t["end"] == "wait" and a["tool"] == "propose_regex" and a["kinds"] == ["rule"] and a["keys"] == ["rule"]
    c = a["regex"]
    assert c["bundle"] == bid and c["bundle_name"] == "표기" and not c["new_bundle"] and c["project"] == "lh"
    assert c["rule"]["action"] == "fix" and c["rule"]["out"] == "…" and c["before"] is None
    assert c["episode"] == 2 and c["change_count"] == 2 and c["hit_count"] == 0 and len(c["changes"]) == 2
    assert c["changes"][0]["before"] == "..." and c["changes"][0]["after"] == "…"
    assert [s["kind"] for s in t["steps"]] == ["wait"] and t["steps"][0]["tool"] == "propose_regex"
    assert calls == ["PlotAgentStep"]
    assert regexrules.load(bid).rules == []  # 적용 전에는 묶음이 그대로다

    calls.clear()
    r = _approve(client, sid)
    assert r.status_code == 200, r.text
    assert r.json()["job"] is None and calls == []
    b = regexrules.load(bid)
    assert len(b.rules) == 1 and b.rules[0].in_ == "\\.\\.\\." and b.version == v0 + 1
    assert b.versions[-1].note == "대화 에이전트 제안: 대화로 만든 규칙"
    t = _turn(client, sid)
    assert t["end"] == "done" and t["approval"]["state"] == "approved" and t["approval"]["picked"] == ["rule"]
    w = t["writes"][0]
    assert w["tool"] == "propose_regex" and w["items"][0]["label"] == "정규식 규칙 · 대화로 만든 규칙" and w["regex"]["version"] == b.version
    assert "다음에 본문을 쓸 때부터" in t["steps"][-1]["why"]
    ep_after = client.get("/api/projects/lh").json()["episodes"][1]
    assert ep_after["text"] == ep_before["text"] == TEXT and ep_after["rule_runs"] == ep_before["rule_runs"]

    r = _undo(client, sid).json()
    assert r["restored"] == ["정규식 규칙 · 대화로 만든 규칙"] and r["kept"] == []
    b = regexrules.load(bid)
    assert b.rules == [] and b.versions[-1].note == "대화 에이전트 제안 되돌림"
    assert _turn(client, sid)["writes"][0]["items"][0]["state"] == "reverted"
    assert calls == []


def test_all_mode_still_asks_and_remember_is_ignored(client):
    bid = _setup(client)
    sid = _session(client, topic="agent")
    client.patch(f"/api/projects/lh/sessions/{sid}", json={"mode": "all"})
    t = _say(client, sid, ELLIPSIS)
    assert t["end"] == "wait" and t["writes"] == [] and regexrules.load(bid).rules == []
    assert _approve(client, sid, remember=True).status_code == 200
    s = client.get("/api/projects/lh/sessions").json()["sessions"][0]
    assert s["auto_kinds"] == []
    t = _say(client, sid, "웃음 규칙 «웃었다»")
    assert t["end"] == "wait" and t["writes"] == []


def test_no_bundle_makes_new_one_and_undo_removes_it(client):
    """켠 묶음이 없으면 새 묶음 카드다. 적용하면 묶음을 만들고 이 작품 끝에 켠다. 되돌리면 끄고, 그 규칙만 남았고
    다른 작품이 켜지 않았으면 묶음 파일도 지운다 (디스크의 이 작품은 아직 켠 채라 used_by 에 들지만 카드의 project 를 뺀다)."""
    _project(client)
    _text(client)
    gone = _make(client, "지운 묶음")
    _use(client, gone)
    regexrules.delete(gone)  # 지운 묶음 id 만 남은 작품
    sid = _session(client, topic="agent")
    t = _say(client, sid, ELLIPSIS)
    c = t["approval"]["regex"]
    assert c["new_bundle"] and c["bundle"] == "" and c["bundle_name"] == "등대 규칙" and c["used_by"] == []
    assert _approve(client, sid).status_code == 200
    on = store.load("lh").settings.rule_bundles
    assert len(on) == 2 and on[0] == gone
    bid = on[1]
    assert regexrules.load(bid).name == "등대 규칙" and len(regexrules.load(bid).rules) == 1
    assert _turn(client, sid)["approval"]["regex"]["bundle"] == bid
    assert regexrules.used_by(bid) == ["lh"]

    r = _undo(client, sid).json()
    assert r["kept"] == [] and len(r["restored"]) == 1
    assert store.load("lh").settings.rule_bundles == [gone]
    assert not regexrules.exists(bid)


def test_new_bundle_undo_keeps_bundle_with_other_rules(client):
    _project(client)
    sid = _session(client, topic="agent")
    _say(client, sid, ELLIPSIS)
    _approve(client, sid)
    bid = store.load("lh").settings.rule_bundles[0]
    regexrules.set_rule(bid, "abcd1234", regexrules.RegexRule(id="abcd1234", **{"in": "x"}), "작가가 더함")
    r = _undo(client, sid).json()
    assert len(r["restored"]) == 1
    assert store.load("lh").settings.rule_bundles == []
    assert [x.id for x in regexrules.load(bid).rules] == ["abcd1234"]  # 작가가 더한 규칙이 있어 묶음은 남긴다


def test_new_bundle_undo_in_duplicated_project_keeps_bundle_the_original_uses(client):
    """작품을 복제하면 세션도 복사돼 카드의 project 가 원본 이름으로 남는다. 사본에서 묶음을 끄고 되돌려도
    원본이 켠 묶음 파일은 지우지 않는다 (다른 작품 수는 지금 작품이 켰는지로 센다)."""
    _project(client)
    sid = _session(client, topic="agent")
    _say(client, sid, ELLIPSIS)
    _approve(client, sid)
    bid = store.load("lh").settings.rule_bundles[0]
    assert client.post("/api/projects/lh/duplicate", json={"name": "cp"}).status_code == 200
    _use(client, name="cp")  # 사본에서 그 묶음을 끈다
    r = client.post(f"/api/projects/cp/sessions/{sid}/turns/0/undo", json={}).json()
    assert len(r["restored"]) == 1
    assert regexrules.exists(bid) and regexrules.load(bid).rules == []
    assert store.load("lh").settings.rule_bundles == [bid]


def test_new_bundle_undo_after_rename_deletes_bundle(client):
    """이름을 바꾼 작품에서 되돌려도 이 작품만 켠 새 묶음은 지운다 (빈 묶음이 남지 않는다)."""
    _project(client)
    sid = _session(client, topic="agent")
    _say(client, sid, ELLIPSIS)
    _approve(client, sid)
    bid = store.load("lh").settings.rule_bundles[0]
    assert client.post("/api/projects/lh/rename", json={"name": "lh2"}).status_code == 200
    assert regexrules.used_by(bid) == ["lh2"]
    r = client.post(f"/api/projects/lh2/sessions/{sid}/turns/0/undo", json={}).json()
    assert len(r["restored"]) == 1
    assert store.load("lh2").settings.rule_bundles == []
    assert not regexrules.exists(bid)


# ---------- 막힘 ----------

def _blocked(t) -> str:
    assert t["approval"] is None and t["end"] == "done"
    block = [s for s in t["steps"] if s["kind"] == "block"]
    assert block and block[0]["tool"] == "propose_regex"
    assert "만들지 못했어요" in t["reply"]  # mock 은 막힘을 보고 답만 한다
    return block[0]["why"]


def test_two_bundles_and_blank_bundle_blocks(client):
    _project(client)
    _text(client)
    a, b = _make(client, "표기"), _make(client, "말투")
    _use(client, a, b)
    why = _blocked(_say(client, _session(client, topic="agent"), ELLIPSIS))
    assert "표기" in why and "말투" in why and "bundle" in why
    t = _say(client, _session(client, topic="agent"), ELLIPSIS + f" bundle={b}")
    assert t["approval"]["regex"]["bundle"] == b


def test_bundle_not_enabled_blocks(client):
    _setup(client)
    other = _make(client, "다른 묶음")
    why = _blocked(_say(client, _session(client, topic="agent"), ELLIPSIS + f" bundle={other}"))
    assert "켠 묶음이 아니에요" in why


def test_bad_regex_blocks_with_refuse_text(client):
    bid = _setup(client)
    why = _blocked(_say(client, _session(client, topic="agent"), "나쁜 규칙 «a»"))
    assert regexrules.REFUSE in why and "반복 안에 또 반복" in why
    assert regexrules.load(bid).rules == []


def test_slow_warn_rule_blocks(client, monkeypatch):
    """시간 한도를 넘는 경고 규칙(기본 warn)은 trial(strict=True) 가 건너뜀을 알려 카드 없이 막힌다."""
    _setup(client)
    monkeypatch.setattr(regexrules, "_call", lambda op, text, steps: (None, steps[0][0]))
    why = _blocked(_say(client, _session(client, topic="agent"), "웃음 규칙 «웃었다»"))
    assert "시간 한도" in why and "2화" in why


def test_same_rule_already_in_bundle_blocks(client):
    _setup(client, rules=[{"id": "11112222", "in": "\\.\\.\\.", "out": "…", "action": "fix"}])
    why = _blocked(_say(client, _session(client, topic="agent"), ELLIPSIS))
    assert "11112222" in why


# ---------- 시험 결과 ----------

def test_export_card_reports_export_changed(client):
    _setup(client)
    t = _say(client, _session(client, topic="agent"), ELLIPSIS + " type=export")
    c = t["approval"]["regex"]
    assert c["rule"]["type"] == "export" and c["export_changed"] and c["change_count"] == 0


def test_warn_card_counts_hits(client):
    _setup(client)
    c = _say(client, _session(client, topic="agent"), "웃음 규칙 «웃었다»")["approval"]["regex"]
    assert c["rule"]["action"] == "warn" and c["hit_count"] == 1 and c["hits"][0]["current_quote"] == "그는 웃었다..."
    assert not c["export_changed"]


def test_disable_card_trials_the_rule_before_and_undo_restores(client):
    """끄기 카드의 시험 결과는 적용 전 규칙으로 건 값이다. 되돌리면 적용 전 규칙으로 돌아간다."""
    bid = _setup(client, rules=[{"id": "aaaa1111", "comment": "웃음", "in": "웃었다", "action": "warn"}])
    sid = _session(client, topic="agent")
    t = _say(client, sid, "규칙 rule=aaaa1111 enabled=false")
    c = t["approval"]["regex"]
    assert c["before"]["enabled"] and not c["rule"]["enabled"] and c["hit_count"] == 1
    assert _approve(client, sid).status_code == 200
    assert regexrules.load(bid).rules[0].enabled is False
    assert _undo(client, sid).json()["kept"] == []
    r = regexrules.load(bid).rules[0]
    assert r.enabled is True and r.comment == "웃음" and r.id == "aaaa1111"


def test_slow_rule_disable_card_is_not_blocked(client, monkeypatch):
    """켠 규칙이 시간 한도를 넘어도 끄기 카드는 막지 않는다. 카드에 timed_out 이 들고 적용하면 규칙이 꺼진다."""
    bid = _setup(client, rules=[{"id": "aaaa1111", "comment": "웃음", "in": "웃었다", "action": "warn"}])
    monkeypatch.setattr(regexrules, "_call", lambda op, text, steps: (None, steps[0][0]))
    sid = _session(client, topic="agent")
    t = _say(client, sid, "규칙 rule=aaaa1111 enabled=false")
    c = t["approval"]["regex"]
    assert c["timed_out"] and c["episode"] == 2 and c["hit_count"] == 0 and not c["rule"]["enabled"]
    assert not [s for s in t["steps"] if s["kind"] == "block"]
    assert _approve(client, sid).status_code == 200
    assert regexrules.load(bid).rules[0].enabled is False


def test_old_rule_that_fails_validate_can_be_disabled(client):
    """지금 검사(validate)를 통과하지 못하는 옛 규칙도 끄기만 하면 카드가 오고 적용된다. 다른 칸을 고치면 여전히 막힌다."""
    bid = _setup(client)
    b = regexrules.load(bid)
    b.rules = [regexrules.RegexRule(id="bbbb2222", comment="옛 규칙", action="warn", **{"in": "(a+)+"})]
    regexrules.save(b, "검사 전에 저장한 옛 규칙")
    why = _blocked(_say(client, _session(client, topic="agent"), "규칙 rule=bbbb2222 comment=새이름"))
    assert regexrules.REFUSE in why
    sid = _session(client, topic="agent")
    c = _say(client, sid, "규칙 rule=bbbb2222 enabled=false")["approval"]["regex"]
    assert c["before"]["enabled"] and not c["rule"]["enabled"]
    assert _approve(client, sid).status_code == 200
    assert regexrules.load(bid).rules[0].enabled is False
    r = _undo(client, sid).json()  # 다시 켜면 검사에 걸리므로 되돌리지 않고 까닭을 남긴다
    assert r["restored"] == [] and regexrules.REFUSE in r["reasons"][0]
    assert regexrules.load(bid).rules[0].enabled is False


def test_set_rule_skips_check_only_when_switching_off():
    bad = regexrules.RegexRule(id="cccc3333", **{"in": "(a+)+"})
    b = regexrules.save(regexrules.RuleBundle(id="0123456789ab", name="옛 묶음", rules=[bad]), "옛 규칙")
    off = bad.model_copy(update={"enabled": False})
    assert regexrules.switched_off(bad, off) and not regexrules.switched_off(off, bad)
    assert not regexrules.switched_off(bad, off.model_copy(update={"comment": "새이름"}))
    assert regexrules.set_rule(b.id, bad.id, off).rules[0].enabled is False
    try:
        regexrules.set_rule(b.id, bad.id, bad)
    except ValueError as e:
        assert regexrules.REFUSE in str(e)
    else:
        raise AssertionError("다시 켜는 것은 검사해야 해요")


def test_text_target_calls_propose_regex_not_revise_text(client):
    _setup(client)
    _text(client, n=3, text="그녀는 걸었다... 멀리.")
    sid = _session(client, topic="agent", target="text:3")
    t = _say(client, sid, ELLIPSIS, target="text:3", screen="write")
    assert t["approval"]["tool"] == "propose_regex" and t["approval"]["regex"]["episode"] == 3


def test_card_used_by_lists_other_projects_only(client):
    bid = _setup(client)
    client.post("/api/projects", json={"name": "ot", "meta": {"title": "다른 작품", "target_episodes": 3}})
    _use(client, bid, name="ot")
    c = _say(client, _session(client, topic="agent"), ELLIPSIS)["approval"]["regex"]
    assert c["used_by"] == ["ot"]


# ---------- 적용 막힘 · 되돌리기 남김 ----------

def test_bundle_dropped_after_card_blocks_apply(client):
    _setup(client)
    sid = _session(client, topic="agent")
    _say(client, sid, ELLIPSIS)
    _use(client)  # 설정 화면에서 묶음을 껐다 (묶음 파일은 남는다)
    r = _approve(client, sid)
    assert r.status_code == 400 and "이 작품에서 그 묶음을 껐어요" in r.text
    t = _turn(client, sid)
    assert t["approval"]["state"] == "wait" and t["end"] == "wait"


def test_bundle_deleted_after_card_blocks_apply(client):
    bid = _setup(client)
    sid = _session(client, topic="agent")
    _say(client, sid, ELLIPSIS)
    regexrules.delete(bid)
    r = _approve(client, sid)
    assert r.status_code == 400 and "그 묶음을 찾을 수 없어요" in r.text
    assert _turn(client, sid)["approval"]["state"] == "wait"


def test_rule_changed_after_card_blocks_apply(client):
    bid = _setup(client, rules=[{"id": "aaaa1111", "comment": "웃음", "in": "웃었다", "action": "warn"}])
    sid = _session(client, topic="agent")
    _say(client, sid, "규칙 rule=aaaa1111 enabled=false")
    b = regexrules.load(bid)
    regexrules.update(bid, b.name, b.notes, [b.rules[0].model_copy(update={"comment": "작가가 고침"})])
    r = _approve(client, sid)
    assert r.status_code == 400 and "그 사이 규칙이 바뀌었어요" in r.text
    assert _turn(client, sid)["approval"]["state"] == "wait"


def test_undo_keeps_rule_edited_later(client):
    bid = _setup(client)
    sid = _session(client, topic="agent")
    _say(client, sid, ELLIPSIS)
    _approve(client, sid)
    b = regexrules.load(bid)
    regexrules.update(bid, b.name, b.notes, [b.rules[0].model_copy(update={"out": "⋯"})])
    r = _undo(client, sid).json()
    assert r["restored"] == [] and r["kept"] == ["정규식 규칙 · 대화로 만든 규칙"]
    item = _turn(client, sid)["writes"][0]["items"][0]
    assert item["state"] == "kept" and item["reason"] == agent_regex.KEPT
    assert regexrules.load(bid).rules[0].out == "⋯"


def test_undo_keeps_when_bundle_deleted(client):
    bid = _setup(client)
    sid = _session(client, topic="agent")
    _say(client, sid, ELLIPSIS)
    _approve(client, sid)
    regexrules.delete(bid)
    r = _undo(client, sid).json()
    assert r["kept"] == ["정규식 규칙 · 대화로 만든 규칙"]
    assert _turn(client, sid)["writes"][0]["items"][0]["reason"] == agent_regex.GONE


# ---------- 읽기 도구 ----------

def test_read_rules_shows_enabled_bundles_and_cuts_long_result(client):
    _project(client)
    long = [{"comment": f"규칙 {k} " + "가" * 40, "in": f"말{k}", "action": "warn"} for k in range(60)]
    on = _make(client, "켠 묶음", long)
    _make(client, "끈 묶음", [{"in": "x"}])  # 이 작품이 켜지 않은 묶음은 보이지 않는다
    p = store.load("lh")
    assert agent.read(p, "read_rules", {})[0] == "켠 묶음 없음"
    _use(client, on)
    where, result = agent.read(store.load("lh"), "read_rules", {})
    assert where == "묶음 1개 · 규칙 60개" and "켠 묶음" in result and "끈 묶음" not in result
    assert len(result) > agent.RESULT_LIMIT and result.endswith(f"… (예산 {agent.RESULT_LIMIT}자에서 잘랐어요)")
    assert '"in": "말0"' in result


# ---------- 저장 모양 · 옛 작품 ----------

def test_old_project_json_reads_and_old_turns_drop_regex_undo(client, monkeypatch):
    _setup(client)
    path = store.project_dir("lh") / "project.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["agent_sessions"] = [{"id": "old1", "topic": "plot", "turns": [
        {"user": "x", "end": "done", "approval": {"tool": "edit_plot", "keys": ["3"], "state": "denied"},
         "writes": [{"tool": "edit_plot", "items": [{"key": "3", "state": "reverted"}]}]}]}]
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    s = client.get("/api/projects/lh/sessions").json()["sessions"][0]
    assert s["turns"][0]["approval"]["regex"] is None and s["turns"][0]["writes"][0]["regex"] is None

    monkeypatch.setattr(agent, "UNDO_TURNS", 1)
    sid = _session(client, topic="agent")
    _say(client, sid, ELLIPSIS)
    _approve(client, sid)
    _say(client, sid, "다음")
    _say(client, sid, "그다음")
    w = _turn(client, sid, t=0)["writes"][0]
    assert w["regex"] is None and {i["state"] for i in w["items"]} == {"kept"}


def test_saved_card_keys_read_back():
    """작품 저장은 규칙 키가 in_ 이고, 묶음 파일 모양(in)으로도 읽힌다."""
    from canon.schema import RegexCard, RegexRule
    c = RegexCard(rule=RegexRule(**{"in": "a"}))
    raw = json.loads(c.model_dump_json())
    assert raw["rule"]["in_"] == "a"
    assert RegexCard.model_validate(raw).rule.in_ == "a"
    raw["rule"] = {"in": "b"}
    assert RegexCard.model_validate(raw).rule.in_ == "b"


def test_prompt_turn_line_names_the_rule(client):
    _setup(client)
    sid = _session(client, topic="agent")
    _say(client, sid, ELLIPSIS)
    s = store.load("lh").agent_sessions[0]
    line = prompts._agent_turn_line(s.turns[0])
    assert "물음(작가 답 기다림): 정규식 규칙 대화로 만든 규칙" in line


# ---------- regexrules: set_rule · trial(strict) ----------

def test_set_rule_changes_one_rule_only(client):
    bid = _make(client, rules=[{"id": "aaaa1111", "in": "a"}, {"id": "bbbb2222", "in": "b"}])
    R = regexrules
    b = R.set_rule(bid, "bbbb2222", R.RegexRule(id="bbbb2222", **{"in": "B"}), "고침")
    assert [r.in_ for r in b.rules] == ["a", "B"] and b.versions[-1].note == "고침"
    b = R.set_rule(bid, "cccc3333", R.RegexRule(id="cccc3333", **{"in": "c"}))
    assert [r.id for r in b.rules] == ["aaaa1111", "bbbb2222", "cccc3333"]
    b = R.set_rule(bid, "aaaa1111", None)
    assert [r.id for r in b.rules] == ["bbbb2222", "cccc3333"]
    import pytest
    with pytest.raises(ValueError, match="저장할 수 없어요"):
        R.set_rule(bid, "dddd4444", R.RegexRule(id="dddd4444", **{"in": "(a+)+"}))
    assert len(R.load(bid).rules) == 2


def test_trial_strict_reports_warn_and_export_skips(monkeypatch):
    R = regexrules
    warn = R.RegexRule(**{"in": "a", "action": "warn"})
    export = R.RegexRule(**{"in": "a", "out": "b", "action": "fix", "type": "export"})
    monkeypatch.setattr(R, "_call", lambda op, text, steps: (None, steps[0][0]))
    assert R.trial([warn], "abc")["skipped"] == ""  # 규칙 화면의 시험(strict 거짓)은 예전 그대로다
    assert R.trial([export], "abc")["skipped"] == ""
    assert "시간 한도" in R.trial([warn], "abc", strict=True)["skipped"]
    res = R.trial([export], "abc", name="묶음", strict=True)
    assert res["skipped"] == "묶음" and res["exported"] == "abc"
