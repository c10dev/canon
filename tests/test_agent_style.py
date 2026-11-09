"""대화 에이전트의 문체 도구 (UX 04d, canon/agent_style.py). mock LLM. 실행: python -m pytest tests"""
import json

from canon import agent, store
from canon.schema import AgentSession

from .jsvm import needs_node, run_js
from .test_agent import _ep, _say, _session, _turn
from .test_plot_chat import _project


def _style(client, name="lh"):
    return client.get(f"/api/projects/{name}").json()["style"]


def _usage_calls(monkeypatch):
    """단계마다 부른 응답 형식 이름을 모은다 (mock 호출 수)."""
    from canon import mock
    seen: list[str] = []
    orig = mock.MockLLM.json

    def spy(self, system, prompt, schema, hint=None, **kw):
        seen.append(schema.__name__)
        return orig(self, system, prompt, schema, hint=hint, **kw)
    monkeypatch.setattr(mock.MockLLM, "json", spy)
    return seen


def test_style_target_makes_a_card_with_sample(client, monkeypatch):
    """문체 대상: 에이전트가 edit_style 을 고르고, 문체 편집자(plan 단계)가 낸 변경안이 카드로 남는다. 작품 문체는 그대로다."""
    _project(client)
    before = _style(client)
    calls = _usage_calls(monkeypatch)
    sid = _session(client, topic="agent", target="style")
    t = _say(client, sid, "대사를 더 짧게 끊어 줘", target="style", screen="style")
    a = t["approval"]
    assert t["end"] == "wait" and a["tool"] == "edit_style" and a["kinds"] == ["style"]
    assert a["keys"] == ["sentence_rhythm", "dos"]  # 지금 값과 같은 시제 칸은 걸렀다
    assert a["style"]["revision"]["preview"].startswith("그는 문을 열었다")
    assert "문장 리듬과 규칙" in t["reply"]
    assert [s["kind"] for s in t["steps"]] == ["wait"] and t["steps"][0]["tool"] == "edit_style"
    assert calls == ["PlotAgentStep", "StyleRevision"]  # 에이전트 한 단계 + 문체 편집자 한 번
    assert _style(client) == before
    assert not any(c["topic"] == "style" for c in client.get("/api/projects/lh").json()["chats"])  # 옛 문체 대화에는 남기지 않는다


def test_picked_fields_only_and_undo(client, monkeypatch):
    """고른 칸만 들어가고, 답하면 턴이 끝난다 (AI 를 더 부르지 않는다). 적용 취소는 그 칸만 돌린다."""
    _project(client)
    before = _style(client)
    sid = _session(client, topic="agent", target="style")
    _say(client, sid, "대사를 더 짧게 끊어 줘", target="style")
    calls = _usage_calls(monkeypatch)
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True, "picked": ["dos"]})
    assert r.status_code == 200, r.text
    assert r.json()["job"] is None and calls == []
    st = r.json()["project"]["style"]
    assert st["dos"][-1] == "대사는 한 줄을 넘기지 않는다" and st["sentence_rhythm"] == before["sentence_rhythm"]
    t = _turn(client, sid)
    assert t["end"] == "done" and t["approval"]["state"] == "approved" and t["approval"]["picked"] == ["dos"]
    assert all(x["result"] == "" for x in t["steps"])  # 끝난 턴은 단계 결과를 지운다
    w = t["writes"][0]
    assert w["tool"] == "edit_style" and [i["key"] for i in w["items"]] == ["dos"] and w["style"]["before"]["dos"] == before["dos"]

    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={}).json()
    assert r["restored"] == ["지킬 것"] and r["kept"] == []
    assert r["project"]["style"] == before
    assert _turn(client, sid)["writes"][0]["items"][0]["state"] == "reverted"
    assert client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={}).status_code == 400


def test_undo_keeps_field_edited_later(client):
    _project(client)
    sid = _session(client, topic="agent", target="style")
    _say(client, sid, "대사를 더 짧게 끊어 줘", target="style")
    client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True})
    p = client.get("/api/projects/lh").json()
    p["style"]["dos"] = ["작가가 다시 고침"]
    assert client.put("/api/projects/lh", json=p).status_code == 200
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={}).json()
    assert r["restored"] == ["문장 리듬"] and r["kept"] == ["지킬 것"]
    assert r["project"]["style"]["dos"] == ["작가가 다시 고침"]
    items = {i["key"]: i for i in _turn(client, sid)["writes"][0]["items"]}
    assert items["dos"]["state"] == "kept" and "다시 고친" in items["dos"]["reason"]


def test_all_mode_still_asks_and_remember_is_ignored(client):
    """권한 모드 '모두 자동'이어도 묻고, '이 세션에서 묻지 않기'를 보내도 auto_kinds 에 넣지 않는다."""
    _project(client)
    before = _style(client)
    sid = _session(client, topic="agent", target="style")
    client.patch(f"/api/projects/lh/sessions/{sid}", json={"mode": "all"})
    t = _say(client, sid, "대사를 더 짧게 끊어 줘", target="style")
    assert t["end"] == "wait" and t["writes"] == [] and _style(client) == before
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True, "remember": True})
    assert r.status_code == 200
    s = client.get("/api/projects/lh/sessions").json()["sessions"][0]
    assert s["auto_kinds"] == []
    t = _say(client, sid, "묘사를 줄여 줘", target="style")
    assert t["end"] == "wait" and t["writes"] == []
    assert agent.permit(AgentSession(id="x", mode="all", auto_kinds=["style", "renumber"]), "style") == "ask"


def test_denied_card_and_new_turn_write_nothing(client):
    _project(client)
    before = _style(client)
    sid = _session(client, topic="agent", target="style")
    _say(client, sid, "대사를 더 짧게 끊어 줘", target="style")
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": False}).json()
    assert r["job"] is None
    t = _turn(client, sid)
    assert t["approval"]["state"] == "denied" and t["end"] == "done" and t["writes"] == []
    _say(client, sid, "대사를 더 짧게 끊어 줘", target="style")
    _say(client, sid, "다른 걸 해 보자", target="style")  # 답하지 않고 새로 말하면 묻던 카드는 쓰지 않는다
    assert _turn(client, sid, t=1)["approval"]["state"] == "denied"
    assert _style(client) == before
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True})
    assert r.status_code == 400  # 이미 답한 카드


def test_reference_episode_from_chip_and_from_args(client):
    """참고할 화: 문체 대상 턴의 episode(화면의 '참고할 화' 칩)를 쓰고, 본문이 없는 화면 막힘 단계로 AI 에게 돌려준다."""
    _project(client)
    p = client.get("/api/projects/lh").json()
    p["episodes"][1]["text"] = "바람이 불었다. 그는 문을 열었다. 그녀가 물었다."
    p["episodes"][1]["status"] = "written"
    assert client.put("/api/projects/lh", json=p).status_code == 200
    sid = _session(client, topic="agent", target="style")
    t = _say(client, sid, "대사를 더 짧게 끊어 줘", target="style", episode=2)
    assert t["approval"]["style"]["episode"] == 2
    assert t["approval"]["style"]["revision"]["preview_source"] == "바람이 불었다. 그는 문을 열었다. 그녀가 물었다."
    assert "문체" in t["where"] and "2화" in t["where"]
    t = _say(client, sid, "대사를 더 짧게, 3화 참고", target="style")  # 인자가 칩보다 먼저다. 3화는 본문이 없다
    assert t["end"] == "done" and t["approval"] is None
    assert t["steps"][0]["kind"] == "block" and "3화에 본문이 없어요" in t["steps"][0]["why"]
    assert "만들지 못했어요" in t["reply"]


def test_other_target_can_use_style_tool(client):
    """다른 대상(작품 전체 · 플롯 화면)에서도 작가가 문체를 말하면 쓴다. 늘 묻는다."""
    _project(client)
    plot = _ep(client, 3)["plot"]
    sid = _session(client, topic="agent")
    t = _say(client, sid, "문체를 좀 더 건조하게", target="", screen="arc")
    assert t["end"] == "wait" and t["approval"]["tool"] == "edit_style" and _ep(client, 3)["plot"] == plot
    t = _say(client, _session(client, topic="agent", target="style"), "3화 플롯 전개가 너무 빨라", target="style")
    assert t["approval"]["tool"] == "edit_plot" and t["approval"]["kinds"] == ["outside"]  # 문체 화면에서도 플롯은 플롯 도구로


def test_old_project_json_reads_and_old_turns_drop_style_undo(client, monkeypatch):
    """옛 project.json(style 칸 없는 승인 · 쓴 기록)이 읽히고, 오래된 턴은 문체 되돌리기 기록도 지운다."""
    _project(client)
    path = store.project_dir("lh") / "project.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["agent_sessions"] = [{"id": "old1", "topic": "plot", "turns": [
        {"user": "x", "end": "done", "approval": {"tool": "edit_plot", "keys": ["3"], "state": "denied"},
         "writes": [{"tool": "edit_plot", "items": [{"key": "3", "state": "reverted"}]}]}]}]
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    s = client.get("/api/projects/lh/sessions").json()["sessions"][0]
    assert s["turns"][0]["approval"]["style"] is None and s["turns"][0]["writes"][0]["style"] is None

    monkeypatch.setattr(agent, "UNDO_TURNS", 1)
    sid = _session(client, topic="agent", target="style")
    _say(client, sid, "대사를 더 짧게 끊어 줘", target="style")
    client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True})
    _say(client, sid, "다음", target="style")
    _say(client, sid, "그다음", target="style")
    w = _turn(client, sid, t=0)["writes"][0]
    assert w["style"] is None and {i["state"] for i in w["items"]} == {"kept"}


def test_style_screen_prompt_points_to_edit_style():
    from canon import prompts
    from canon.schema import Project
    block = prompts.agent_focus_block(Project(), "style")
    assert "edit_style" in block and "도구는 없으니" not in block
    assert "- edit_style (args: request, episode)" in prompts.AGENT_PLOT_TOOLS



# ---------- 화면 (static/agent.js) ----------


JS = ["app.js", "chat.js", "agent.js", "passage.js", "stylechat.js"]


@needs_node
def test_style_card_shows_fields_side_by_side_and_no_remember_box():
    """문체 카드는 칸을 지금 값과 나란히, 시험 문단과 함께 보이고 '이 세션에서 묻지 않기'를 그리지 않는다.
    적용한 기록은 칸마다 되돌리기 대신 '적용 취소' 하나다. 참고할 화 칩은 문체 대상에서만 붙고 턴의 episode 로 간다."""
    got = run_js(JS, """(() => {
      S.project = data; S.name = 'lh'; S.route = ['p', 'lh', 'style']; S.chatHere = { target: 'style' };
      S.agent = { max_steps: 8, sessions: [], model: 'mock' }; S.agentPicks = {};
      const rev = { reply: '고쳤어요', edits: [{ key: 'sentence_rhythm', text: '짧은 문장', items: [], markers: [], devices: [], why: '요청' },
        { key: 'dos', text: '', items: ['감정은 행동으로', '대사는 짧게'], markers: [], devices: [], why: '' }],
        preview_source: '', preview: '그는 문을 열었다.' };
      const a = { tool: 'edit_style', style: { revision: rev, episode: 0, applied: [], before: null }, keys: ['sentence_rhythm', 'dos'],
        kinds: ['style'], state: 'wait', picked: [], target: '', revision: null, op: null };
      const t = { user: '대사를 짧게', mode: '', steps: [], reply: '고쳤어요', writes: [], approval: a, ask: null, end: 'wait' };
      const wait = agentApproval(t, 0, true);
      const done = { ...t, end: 'done', approval: { ...a, state: 'approved', picked: ['dos'] },
        writes: [{ tool: 'edit_style', items: [{ key: 'dos', label: '지킬 것', state: 'done', reason: '' }],
          style: { revision: rev, episode: 0, applied: ['dos'], before: data.style } }] };
      const html = agentTurn({ id: 's', turns: [done] }, done, 0);
      S.styleRefEp = '2';
      const chip = agentRefChip('style'); const noChip = agentRefChip('');
      const scope = agentTurnScope(null);
      return { wait, html, chip, noChip, scope };
    })()""", {"style": {"sentence_rhythm": "긴 문장", "dos": ["감정은 행동으로"]}, "episodes": [], "chats": []})
    w = got["wait"]
    assert 'data-agent-pick="0:sentence_rhythm"' in w and 'data-agent-pick="0:dos"' in w
    assert "긴 문장" in w and "짧은 문장" in w and "대사는 짧게" in w  # 지금 값과 바뀐 값
    assert "그는 문을 열었다." in w and "시험 문단" in w
    assert "data-agent-remember" not in w and "묻지 않고" not in w
    assert "고른 칸 적용" in w and "권한 모드와 상관없이" in w
    h = got["html"]
    assert ">적용 취소</button>" in h and 'data-arg="0|0|dos"' not in h
    assert "바로 씀" not in h
    assert "2화 참고" in got["chip"] and got["noChip"] == ""
    assert got["scope"]["episode"] == 2 and got["scope"]["target"] == "style"
