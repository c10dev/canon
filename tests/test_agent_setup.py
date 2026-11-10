"""대화 에이전트의 설정 도구 (canon/agent_setup.py, UX 04c). mock LLM. 실행: python -m pytest tests/test_agent_setup.py"""
import json

from canon import agent, agent_setup, store
from canon.schema import AgentSession, Character, CharacterEdit, PlotAgentStep, Project, Relationship, SetupEdit, SetupRevision

from .test_agent import _say, _session, _turn
from .test_plot_chat import _project

ASK = "로그라인을 더 날카롭게"
S = AgentSession(id="t")  # record 가 받는 세션 (쓰지 않는다)
STEP = PlotAgentStep(tool="edit_setup")


def _setup(client):
    return client.get("/api/projects/lh").json()


def _decide(client, sid, t, picked, approve=True, remember=False):
    return client.post(f"/api/projects/lh/sessions/{sid}/turns/{t}/approval", json={"approve": approve, "picked": picked, "remember": remember})


def test_setup_tool_asks_with_a_card_and_writes_only_picked(client):
    """mock 단계: 설정 대상에서 말하면 edit_setup 이 변경안 카드를 남기고, 작가가 고른 칸만 들어간다. 되돌리기는 쓰기 전 값으로."""
    _project(client)
    before = _setup(client)
    sid = _session(client, topic="agent", target="setup")
    t = _say(client, sid, ASK)
    a = t["approval"]
    assert t["end"] == "wait" and a["tool"] == "edit_setup" and a["kinds"] == ["setup"]
    assert [s["tool"] for s in t["steps"]] == ["edit_setup"] and t["steps"][0]["kind"] == "wait"
    assert "tone" not in a["keys"] and "c:nobody:goal" not in a["keys"]  # 지금 값과 같은 칸 · 없는 인물은 setupchat.clean 이 뺀다
    assert {"theme", "logline.block", "new:mentor"} <= set(a["keys"])
    assert _setup(client)["meta"] == before["meta"]  # 묻는 동안은 그대로

    r = _decide(client, sid, 0, ["logline.block", "new:mentor"])
    assert r.status_code == 200, r.text
    p = r.json()["project"]
    assert p["meta"]["logline_parts"]["block"] == "바다를 지키는 마을 사람들"
    assert p["meta"]["theme"] == before["meta"]["theme"]  # 고르지 않은 칸은 그대로
    assert any(c["id"] == "mentor" for c in p["characters"])
    assert r.json()["job"] is None  # 카드에 답하면 턴이 끝난다. 에이전트를 다시 부르지 않는다 (agent.CARD_TOOLS)
    t = _turn(client, sid)
    assert t["end"] == "done" and t["approval"]["state"] == "approved"
    assert t["approval"]["picked"] == ["logline.block", "new:mentor"]
    w = t["writes"][0]
    assert w["tool"] == "edit_setup" and [i["key"] for i in w["items"]] == ["logline.block", "new:mentor"]
    assert w["setup_before"]["meta"]["logline_parts"] == before["meta"]["logline_parts"]  # 쓰기 전 값을 남긴다

    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={"write": 0, "key": "logline.block"}).json()
    assert r["restored"] == ["로그라인 · 무엇이 막나"] and r["kept"] == []
    assert r["project"]["meta"]["logline_parts"] == before["meta"]["logline_parts"]
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={}).json()
    assert r["restored"] == ["새 인물 한결"]
    assert [c["id"] for c in r["project"]["characters"]] == [c["id"] for c in before["characters"]]
    assert client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={}).status_code == 400


def test_setup_tool_asks_in_all_mode_and_never_remembers(client):
    """권한 모드 '모두 자동'에서도 카드로 묻고, '이 세션에서 묻지 않기'를 보내도 받지 않는다 (2026-11-09 사용자 결정)."""
    _project(client)
    sid = _session(client, topic="agent", target="setup")
    client.patch(f"/api/projects/lh/sessions/{sid}", json={"mode": "all"})
    t = _say(client, sid, ASK)
    assert t["end"] == "wait" and t["approval"]["tool"] == "edit_setup" and t["writes"] == []
    r = _decide(client, sid, 0, ["theme"], remember=True)
    assert r.status_code == 200, r.text
    s = client.get("/api/projects/lh/sessions").json()["sessions"][0]
    assert s["auto_kinds"] == []
    t = _say(client, sid, ASK + " 한 번 더")
    assert t["end"] == "wait" and t["approval"]["tool"] == "edit_setup"  # 다음 턴도 묻는다
    assert agent.permit(agent.session(store.load("lh"), sid), "setup") == "ask"
    assert agent.CARD_TOOLS["edit_setup"] is agent_setup and "setup" in agent.ALWAYS_ASK


def test_setup_card_needs_a_pick_and_deny_writes_nothing(client):
    _project(client)
    before = _setup(client)
    sid = _session(client, topic="agent", target="setup")
    _say(client, sid, ASK)
    r = _decide(client, sid, 0, [])
    assert r.status_code == 400 and "고르세요" in r.json()["detail"]  # 비우면 모두가 아니라 아무것도 쓰지 않는다
    r = _decide(client, sid, 0, ["r:" + before["characters"][0]["id"] + ":mentor"])
    assert r.status_code == 400 and "새 인물" in r.json()["detail"]  # 고르지 않은 새 인물과 이어진 관계
    assert _turn(client, sid)["approval"]["state"] == "wait"  # 카드는 그대로
    r = _decide(client, sid, 0, [], approve=False)
    assert r.status_code == 200 and r.json()["job"] is None
    p = r.json()["project"]
    assert p["meta"] == before["meta"] and p["characters"] == before["characters"]
    t = _turn(client, sid)
    assert t["end"] == "done" and t["approval"]["state"] == "denied"


def test_defaults_keep_author_fields_and_character_edits_unchecked():
    """사용자가 채운 칸 · 인물 칸(빈 칸이어도)은 처음에 꺼 두고, 빈 칸 · 새 인물 · 새 관계만 켠다."""
    p = Project.model_validate({"meta": {"title": "등대", "theme": "작가가 쓴 주제"},
                                "characters": [{"id": "hero", "name": "서윤", "role": "주인공", "goal": "", "wound": "작가가 쓴 약점"},
                                               {"id": "rival", "name": "도현", "role": "라이벌"}],
                                "relationships": [{"a": "hero", "b": "rival", "type": "라이벌"}]})
    rev = SetupRevision(reply="", edits=[SetupEdit(key="theme", text="AI 주제"), SetupEdit(key="tone", text="AI 톤")],
                        characters=[CharacterEdit(id="hero", field="goal", text="AI 목표"), CharacterEdit(id="hero", field="wound", text="AI 약점")],
                        new_characters=[Character(id="mentor", name="한결", role="조력자")],
                        relationships=[Relationship(a="hero", b="rival", type="원수"), Relationship(a="hero", b="mentor", type="사제")])
    assert agent_setup.defaults(p, rev) == ["tone", "new:mentor", "r:hero:mentor"]


def test_new_relationship_numbers_are_not_written_by_ai():
    """관계 수치는 AI 가 적지 않는다: 새 관계의 호감 · 긴장은 0 으로 둔다 (시작 관계는 보는 방식으로 계산)."""
    from canon.schema import AgentTurn

    p = Project.model_validate({"meta": {"title": "등대"}, "characters": [{"id": "hero", "name": "서윤", "role": "주인공"}]})
    rev = SetupRevision(reply="한 명 더했어요", new_characters=[Character(id="mentor", name="한결", role="조력자")],
                        relationships=[Relationship(a="hero", b="mentor", type="사제", affinity=5, tension=9, a_view=["믿는다"])])
    turn = AgentTurn(user="조력자를 넣어 줘")
    assert agent_setup.record(p, S, turn, STEP, rev) == "wait"
    r = turn.approval.setup.relationships[0]
    assert (r.affinity, r.tension, r.a_view) == (0, 0, ["믿는다"])
    assert turn.reply == "한 명 더했어요"


def test_setup_card_adds_character_aliases_and_undo_restores():
    """정할 것 13: edit_setup 카드로 인물 다른 이름을 넣고 되돌리면 전 값으로 돌아간다. 다른 이름은 setting_log 에 남지 않는다 (정할 것 5)."""
    from canon.schema import AgentTurn

    from .jsvm import episode
    p = Project.model_validate({"meta": {"title": "등대"}, "characters": [{"id": "hero", "name": "서윤", "role": "주인공", "aliases": ["등대지기"]}]})
    p.episodes = [episode(1, text="서윤은 등대에 올랐다.", status="finalized")]  # 1화 반영 뒤라 설정 칸을 고치면 기록이 남는 때
    rev = SetupRevision(reply="별명을 더했어요", characters=[CharacterEdit(id="hero", field="aliases", items=["등대지기", " 꼬맹이 ", "꼬"])])
    turn = AgentTurn(user="서윤 별명에 꼬맹이를 더해 줘")
    assert agent_setup.record(p, S, turn, STEP, rev) == "wait"
    a = turn.approval
    assert a.keys == ["c:hero:aliases"] and a.defaults == []  # 인물 칸은 처음에 꺼 둔다
    assert a.setup.characters[0].items == ["등대지기", "꼬맹이"]  # 한 글자 말은 정리가 뺀다
    agent_setup.decide(p, S, turn, True, ["c:hero:aliases"])
    assert p.characters[0].aliases == ["등대지기", "꼬맹이"] and p.setting_log == []
    assert "서윤 다른 이름" in turn.steps[-1].label
    done, kept, _ = agent_setup.undo(p, turn.writes[0], turn.writes[0].items)
    assert done == ["서윤 다른 이름"] and not kept
    assert p.characters[0].aliases == ["등대지기"] and p.setting_log == []

def test_no_change_and_failed_request_continue_the_turn():
    from canon.schema import AgentTurn

    p = Project.model_validate({"meta": {"title": "등대", "theme": "그대로"}})
    turn = AgentTurn(user="주제를 다듬어 줘")
    assert agent_setup.record(p, S, turn, STEP, SetupRevision(reply="지금이 좋아요", edits=[SetupEdit(key="theme", text="그대로")])) == ""
    assert turn.approval is None and turn.steps[-1].kind == "note" and "지금이 좋아요" in turn.steps[-1].result
    assert agent_setup.record(p, S, turn, STEP, "바라는 것을 적어 주세요") == ""
    assert turn.steps[-1].kind == "block"


def test_setup_tool_from_another_target(client):
    """결정 5: 설정 도우미 화면이 아니어도 작가가 설정을 바꾸라고 하면 같은 도구를 쓴다 (늘 카드로 묻는다)."""
    _project(client)
    sid = _session(client, topic="agent", target="")
    t = _say(client, sid, "설정을 다듬어 줘, 주제가 흐려", target="", screen="cast")
    assert t["end"] == "wait" and t["approval"]["tool"] == "edit_setup"


def test_prompt_lists_the_setup_tool(client):
    _project(client)
    p = store.load("lh")
    text = agent.first_step_prompt(p, ASK, "setup")
    assert "- edit_setup (args: request)" in text
    assert "설정을 바꾸라는 말이면 edit_setup 을 부릅니다" in text and "설정을 바로 고치는 도구는 없으니" not in text


def test_old_project_json_reads_without_setup_fields(client):
    """옛 project.json: 승인 카드 · 쓴 기록에 setup · setup_before · defaults 칸이 없어도 읽히고, 새 칸은 저장 뒤 다시 읽힌다."""
    _project(client)
    path = store.project_dir("lh") / "project.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["agent_sessions"] = [{"id": "old1", "topic": "plot", "turns": [{
        "user": "3화", "end": "wait", "approval": {"target": "", "keys": ["3"], "kinds": ["confirmed"]},
        "writes": [{"target": "", "items": [{"key": "2", "label": "2화 플롯"}]}]}]}]
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    p = store.load("lh")
    t = p.agent_sessions[0].turns[0]
    assert t.approval.setup is None and t.approval.defaults == [] and t.writes[0].setup_before is None
    sid = _session(client, topic="agent", target="setup")
    _say(client, sid, ASK)
    q = store.load("lh")
    a = agent.session(q, sid).turns[0].approval
    assert a.setup is not None and a.defaults and Project.model_validate_json(q.model_dump_json()).agent_sessions[-1].turns[0].approval.setup == a.setup


# ---------- 카드 (static/agentsetup.js) ----------
from .jsvm import needs_node, run_js  # noqa: E402

JS = ["app.js", "setup.js", "chat.js", "agent.js", "setupchat.js", "agentsetup.js"]


@needs_node
def test_card_shows_current_values_and_server_defaults():
    """카드는 칸마다 지금 값과 나란히 보이고, 처음 체크는 서버 defaults 다. 고르지 않은 새 인물과 이어진 관계는 고를 수 없다."""
    p = Project.model_validate({"meta": {"title": "등대", "theme": "작가가 쓴 주제"},
                                "characters": [{"id": "hero", "name": "서윤", "role": "주인공", "wound": "작가가 쓴 약점"}]})
    rev = SetupRevision(reply="다듬었어요", edits=[SetupEdit(key="theme", text="AI 주제", why="더 날카롭게"), SetupEdit(key="tone", text="AI 톤")],
                        characters=[CharacterEdit(id="hero", field="wound", text="AI 약점")],
                        new_characters=[Character(id="mentor", name="한결", role="조력자")],
                        relationships=[Relationship(a="hero", b="mentor", type="사제")])
    from canon.schema import AgentTurn
    turn = AgentTurn(user="다듬어 줘", end="wait")
    assert agent_setup.record(p, S, turn, STEP, rev) == "wait"
    turn.end = "wait"
    got = run_js(JS, """(() => {
      S.name = 'demo'; S.project = data.project; S.agentPicks = {}; S.agentRemember = {};
      const s = { id: 'a', mode: 'all', turns: [data.turn] };
      S.agent = { name: 'demo', sessions: [s], legacy: 0, older: [], model: 'mock', max_steps: 8 }; S.agentSid = 'a';
      const a = data.turn.approval;
      const html = agentApproval(data.turn, 0, true);
      const first = agentSetupPicks(0, a);
      S.agentPicks['0:new:mentor'] = false;
      const blocked = agentApproval(data.turn, 0, true);
      const without = agentSetupPicks(0, a);
      S.agentPicks['0:theme'] = true;
      const settled = agentApproval({ ...data.turn, approval: { ...a, state: 'approved', picked: ['theme'] } }, 0, true);
      const w = { tool: 'edit_setup', setup: a.setup, setup_before: { meta: data.project.meta, world: data.project.world, characters: data.project.characters, relationships: [] },
        items: [{ key: 'theme', label: '주제', state: 'done' }] };
      return { html, first, blocked, without, settled, diff: agentItemDiff(w, w.items[0]), defaults: a.defaults };
    })()""", {"project": p.model_dump(mode="json"), "turn": turn.model_dump(mode="json")})
    assert got["defaults"] == ["tone", "new:mentor", "r:hero:mentor"]
    assert got["first"] == ["tone", "new:mentor", "r:hero:mentor"]  # 채운 주제 · 인물 약점은 꺼 둔다
    html = got["html"]
    assert "설정 5곳 바꾸기" in html
    assert 'data-agent-pick="0:theme">' in html and 'data-agent-pick="0:c:hero:wound">' in html  # 체크 없음
    assert 'data-agent-pick="0:tone" checked' in html and 'data-agent-pick="0:new:mentor" checked' in html
    assert "작가가 쓴 주제" in html and "AI 주제" in html and "더 날카롭게" in html  # 지금 값과 나란히
    assert "채운 칸 바꿈" in html and "인물 설정 바꿈" in html and "새 관계" in html
    assert "묻지 않고 바꾸기" not in html and "data-agent-remember" not in html  # '이 세션에서 묻지 않기'는 없다
    assert "고른 칸 적용하고 이어 하기" in html
    assert 'data-agent-pick="0:r:hero:mentor" disabled' in got["blocked"] and "함께 골라야" in got["blocked"]
    assert got["without"] == ["tone"]
    assert "agentDecide" not in got["settled"] and "적용함" in got["settled"]
    assert "작가가 쓴 주제" in got["diff"] and "AI 주제" in got["diff"]  # 쓴 뒤 비교는 쓰기 전 설정과


def test_compact_drops_old_setup_writes():
    """오래된 턴(agent.UNDO_TURNS 밖)의 설정 쓰기는 쓰기 전 설정을 지우고 kept 로 남긴다 (project.json 이 끝없이 커지지 않게)."""
    from canon.schema import AgentTurn, SetupBefore, WriteItem, WriteRecord

    s = AgentSession(id="t", turns=[AgentTurn(user=str(k), end="done") for k in range(agent.UNDO_TURNS + 1)])
    s.turns[0].writes = [WriteRecord(tool="edit_setup", setup=SetupRevision(reply=""), setup_before=SetupBefore(),
                                     items=[WriteItem(key="theme", label="주제")])]
    agent._compact(s)
    w = s.turns[0].writes[0]
    assert w.setup is None and w.setup_before is None and (w.items[0].state, w.items[0].reason) == ("kept", agent.OLD_UNDO)
