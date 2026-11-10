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


def _prompts(monkeypatch):
    """응답 형식 이름마다 받은 요청 프롬프트를 모은다."""
    from canon import mock
    seen: dict[str, list[str]] = {}
    orig = mock.MockLLM.json

    def spy(self, system, prompt, schema, hint=None, **kw):
        seen.setdefault(schema.__name__, []).append(prompt)
        return orig(self, system, prompt, schema, hint=hint, **kw)
    monkeypatch.setattr(mock.MockLLM, "json", spy)
    return seen


def test_editor_sees_denied_card_values_of_this_session(client, monkeypatch):
    """설정 편집자는 이 세션의 지난 설정 카드를 부분 값과 작가의 결정까지 본다. 그래야 '아까 그 인물 말고', '약점만 다시'를 지난 안 기준으로 고친다."""
    _project(client)
    hero = _setup(client)["characters"][0]["name"]
    seen = _prompts(monkeypatch)
    sid = _session(client, topic="agent", target="setup")
    _say(client, sid, ASK)
    assert "[지금까지의 대화]\n없음 (첫 대화)" in seen["SetupRevision"][0]
    assert _decide(client, sid, 0, [], approve=False).status_code == 200
    t = _say(client, sid, "아까 그 인물 말고, 약점만 다시 다듬어 줘")
    assert t["approval"]["tool"] == "edit_setup"
    editor = seen["SetupRevision"][1]
    assert f"작가: {ASK}" in editor
    assert "/ 작가가 적용하지 않음)" in editor and "(변경안: 로그라인 · 무엇이 막나, 주제, 깨면 안 되는 규칙" in editor
    assert f"    - 주제: 잃은 것을 놓아줄 수 있나 ({ASK})" in editor
    assert f"    - {hero} 두려운 것 · 약점: 버려질까 두렵다 ({ASK})" in editor
    assert "    - 새 인물 한결: 조력자. 목표: 마을의 비밀을 지킨다" in editor
    assert f"    - 관계 {hero} ↔ 한결: 사제" in editor
    assert "    - 깨면 안 되는 규칙: " in editor and " / 밤에는 등대 불을 끄지 않는다" in editor  # 목록 칸은 ' / ' 로 잇는다
    assert "지난 변경안을 가리키면" in editor
    assert editor.index("[지금까지의 대화]") < editor.index("[작가의 새 말]\n아까 그 인물 말고")


def test_editor_history_marks_picked_and_reverted_parts(client, monkeypatch):
    _project(client)
    seen = _prompts(monkeypatch)
    sid = _session(client, topic="agent", target="setup")
    _say(client, sid, ASK)
    assert _decide(client, sid, 0, ["logline.block", "new:mentor"]).status_code == 200
    client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={"write": 0, "key": "logline.block"})
    _say(client, sid, "다시 다듬어 줘")
    assert "/ 작가가 적용함: 로그라인 · 무엇이 막나, 새 인물 한결 / 나중에 되돌림: 로그라인 · 무엇이 막나)" in seen["SetupRevision"][-1]


def test_editor_ignores_old_setup_chat_in_agent_path_but_cli_reads_it(client, monkeypatch):
    """옛 설정 대화(Project.chats 'setup')는 웹에서 더 쌓이지 않는다. 대화 에이전트 경로는 그 기록을 읽지 않고, 명령줄 경로(history 없음)는 그대로 읽는다."""
    from canon import pipeline
    from canon.mock import MockLLM

    _project(client)
    path = store.project_dir("lh") / "project.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["chats"] = [{"topic": "setup", "messages": [{"role": "user", "text": "옛날에 한 말"}]}]
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    seen = _prompts(monkeypatch)
    sid = _session(client, topic="agent", target="setup")
    _say(client, sid, ASK)
    assert "옛날에 한 말" not in seen["SetupRevision"][0]
    pipeline.revise_setup(MockLLM(), store.load("lh"), ASK)
    assert "작가: 옛날에 한 말" in seen["SetupRevision"][1]


def test_setup_session_history_lines():
    from canon import prompts, setupchat
    from canon.schema import AgentTurn, Approval, AskCard, Direction

    p = Project.model_validate({"meta": {"title": "등대"}, "characters": [{"id": "hero", "name": "서윤", "role": "주인공"}]})
    rev = SetupRevision(reply="", edits=[SetupEdit(key="world.rules", items=[]), SetupEdit(key="tone", text="가" * 300)],
                        characters=[CharacterEdit(id="hero", field="secrets", items=["동생이 살아 있다", "등대 열쇠"])])
    card = AgentTurn(user="바꿔 줘", approval=Approval(tool="edit_setup", setup=rev, keys=setupchat.part_ids(rev), state="wait"))
    ask = AgentTurn(user="방향을 물어봐 줘", mode="options", reply="두 갈래예요.",
                    ask=AskCard(question="어느 쪽?", options=[Direction(title="복수", idea="되찾으려 한다."), Direction(title="구원", idea="이해하게 된다.")]))
    lines = prompts.setup_session_history(p, [AgentTurn(user=f"말{i}", reply="답") for i in range(9)] + [ask, card])
    assert len(lines) == 12 and lines[0] == "작가: 말5"  # 최근 여섯 턴 (SETUP_CHAT_HISTORY // 2)
    assert lines[-4] == "작가 [방향 여러 안 요청]: 방향을 물어봐 줘"
    assert lines[-3] == "편집자: 두 갈래예요.\n  (되물음: 1. 복수: 되찾으려 한다. / 2. 구원: 이해하게 된다.)"
    assert lines[-1].startswith("편집자:\n  (변경안: 깨면 안 되는 규칙, 톤, 서윤 숨기는 것 / 아직 결정 전)")
    assert "- 깨면 안 되는 규칙: (비움)" in lines[-1] and "- 서윤 숨기는 것: 동생이 살아 있다 / 등대 열쇠" in lines[-1]
    assert "- 톤: " + "가" * prompts.SETUP_VALUE_CLIP + "…" in lines[-1]


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
