"""대화 에이전트의 본문 고치기 도구 (canon/agent_text.py, docs/ux/specs/04-one-agent.md 04b). mock LLM. 실행: python -m pytest tests"""
import pytest

from canon import agent, agent_text, prompts, web
from canon.schema import Project

from .test_passage import TEXT, _written
from .test_web import _wait

QUOTE = "도현은 대답하지 않았다."


@pytest.fixture
def calls(monkeypatch):
    """AI 호출마다 응답 형식 이름을 남긴다 (에이전트 단계 PlotAgentStep, 본문 후보 PassageRevision)."""
    from canon import llm

    out: list[str] = []
    real = llm.get_llm

    class Count:
        def __init__(self, inner):
            self.inner = inner

        def json(self, system, prompt, schema, **kw):
            out.append(schema.__name__)
            return self.inner.json(system, prompt, schema, **kw)

        def __getattr__(self, k):
            return getattr(self.inner, k)

    def get(stage=None):
        return Count(real(stage))
    monkeypatch.setattr(web, "get_llm", get)
    monkeypatch.setattr(agent_text, "get_llm", get)
    return out


def _session(client, target="text:1", mode="draft"):
    s = client.post("/api/projects/lh/sessions", json={"topic": "agent", "target": target}).json()
    client.patch(f"/api/projects/lh/sessions/{s['id']}", json={"mode": mode})
    return s["id"]


def _send(client, sid, message, **kw):
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns", json={"message": message, "target": "text:1", "screen": "write", **kw})
    assert r.status_code == 200, r.text
    assert _wait(client, r.json()["id"])["status"] == "done"
    return _turn(client, sid)


def _turn(client, sid, t=-1):
    s = next(x for x in client.get("/api/projects/lh/sessions").json()["sessions"] if x["id"] == sid)
    return s["turns"][t]


def _material(quote=QUOTE):
    return {"episode": 1, "start": TEXT.index(quote), "text": quote}


def _text(client):
    return client.get("/api/projects/lh").json()["episodes"][0]["text"]


def _chat(client):
    p = client.get("/api/projects/lh").json()
    return next(c for c in p["chats"] if c["topic"] == "text:1")["messages"]


def test_shortcut_asks_with_candidates_even_in_all_mode_and_puts_only_the_pick(client, calls):
    """빠른 요청 + 재료: 에이전트 단계 없이 AI 호출 한 번으로 후보 카드를 낸다. '모두 자동'이어도 넣지 않고 묻는다.
    고른 후보만 본문에 들어가고 수정 기록 · 부분 수정 대화에 남는다. 답하면 에이전트를 다시 부르지 않는다. 되돌리면 본문이 돌아온다."""
    _written(client)
    calls.clear()  # 작품을 만드는 호출은 세지 않는다
    sid = _session(client, mode="all")
    t = _send(client, sid, "더 짧게", preset="shorter", selection=_material())
    assert calls == ["PassageRevision"]  # 지름길: 에이전트 단계(PlotAgentStep)를 부르지 않는다
    a = t["approval"]
    assert t["end"] == "wait" and a["tool"] == "revise_text" and a["kinds"] == ["text"] and a["keys"] == ["0", "1"]
    assert a["selection"]["text"] == QUOTE and a["episode"] == 1 and a["preset"] == "shorter"
    assert t["selection"]["text"] == QUOTE and t["preset"] == "shorter"
    assert client.get("/api/projects/lh/sessions").json()["sessions"][0]["title"] == "1화 본문 · 더 짧게"
    assert _text(client) == TEXT  # 고르기 전에는 그대로
    user, ai = _chat(client)[-2:]  # 지금 'AI에게 고치기' 대화와 같은 기록
    assert (user["preset"], ai["outcome"]) == ("shorter", "") and len(ai["passage"]["candidates"]) == 2
    cand = a["passage"]["candidates"][1]["text"]

    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True, "picked": ["0", "1"]})
    assert r.status_code == 400  # 후보는 하나만 넣는다
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True, "picked": ["1"], "remember": True})
    assert r.status_code == 200 and r.json()["job"] is None
    assert calls == ["PassageRevision"]  # 넣은 뒤 에이전트를 다시 부르지 않는다
    assert _text(client) == TEXT.replace(QUOTE, cand)
    edit = client.get("/api/projects/lh").json()["episodes"][0]["edits"][-1]
    assert edit["source"] == "ai" and edit["proposed"] == "" and edit["after"] == cand and edit["preset"] == "shorter"
    assert (_chat(client)[-1]["outcome"], _chat(client)[-1]["applied"]) == ("applied", ["1"])
    t = _turn(client, sid)
    assert t["end"] == "done" and t["approval"]["state"] == "approved" and t["approval"]["picked"] == ["1"]
    assert t["writes"][0]["tool"] == "revise_text" and t["writes"][0]["edit"] == edit["id"] and t["writes"][0]["items"][0]["key"] == "text"
    s = client.get("/api/projects/lh/sessions").json()["sessions"][0]
    assert "text" not in s["auto_kinds"]  # '이 세션에서 묻지 않기'는 본문 고치기에 열지 않는다

    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={})
    assert r.status_code == 200 and r.json()["restored"] == ["1화 본문 · 2번 후보"]
    assert _text(client) == TEXT
    assert _turn(client, sid)["writes"][0]["items"][0]["state"] == "reverted"
    assert client.get("/api/projects/lh").json()["episodes"][0]["edits"][-1]["undone"] is True  # 수정 기록의 되돌리기와 같다


def test_material_without_preset_and_tweaked_pick_and_deny(client, calls):
    """재료만 붙인 요청도 지름길이다. 작가가 손본 글로 넣을 수 있고, 거절하면 본문은 그대로이고 대화의 후보는 버린 것이 된다."""
    _written(client)
    calls.clear()  # 작품을 만드는 호출은 세지 않는다
    sid = _session(client)
    t = _send(client, sid, "더 망설이게", selection=_material())
    assert calls == ["PassageRevision"] and t["end"] == "wait"
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True, "picked": ["0"], "text": "도현은 끝내 입을 다물었다."})
    assert r.status_code == 200
    assert _text(client).endswith("도현은 끝내 입을 다물었다.")
    assert _turn(client, sid)["writes"][0]["items"][0]["label"] == "1화 본문 · 1번 후보 (손봄)"

    t = _send(client, sid, "바꿔 봐", selection=_material("바람이 불었다."))
    assert t["end"] == "wait"
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/1/approval", json={"approve": False})
    assert r.status_code == 200 and r.json()["job"] is None
    assert _text(client).startswith("바람이 불었다.")
    assert _chat(client)[-1]["outcome"] == "dismissed"
    assert _turn(client, sid)["approval"]["state"] == "denied" and _turn(client, sid)["end"] == "done"


def test_agent_calls_revise_text_by_itself(client, calls):
    """재료 없이 말로 청하면 에이전트 단계가 revise_text 를 부르고 같은 카드를 낸다. 원문을 못 찾으면 막힘으로 돌려받는다."""
    _written(client)
    calls.clear()  # 작품을 만드는 호출은 세지 않는다
    sid = _session(client)
    t = _send(client, sid, f"«{QUOTE}» 를 더 짧게 고쳐 줘")
    assert calls == ["PlotAgentStep", "PassageRevision"]
    assert t["end"] == "wait" and t["approval"]["selection"]["text"] == QUOTE and t["approval"]["episode"] == 1
    assert [x["tool"] for x in t["steps"]] == ["revise_text"]
    calls.clear()
    t = _send(client, sid, "«본문에 없는 문장» 을 고쳐 줘")
    assert calls == ["PlotAgentStep", "PlotAgentStep"]  # 찾지 못하면 후보를 만들지 않는다
    assert t["end"] == "done" and t["steps"][0]["kind"] == "block" and t["approval"] is None


def test_bad_requests_are_stopped_before_ai(client, calls, monkeypatch):
    from canon import autorun

    _written(client)
    calls.clear()  # 작품을 만드는 호출은 세지 않는다
    sid = _session(client)
    url = f"/api/projects/lh/sessions/{sid}/turns"
    assert client.post(url, json={"message": "더 짧게", "preset": "shorter"}).status_code == 400  # 재료 없는 빠른 요청
    assert client.post(url, json={"message": "x", "preset": "nope", "selection": _material()}).status_code == 400
    assert client.post(url, json={"message": "x", "selection": {**_material(), "episode": 99}}).status_code == 400  # 없는 화
    monkeypatch.setattr(autorun, "active", lambda name: True)
    assert client.post(url, json={"message": "x", "selection": _material()}).status_code == 400  # 자동 집필 중
    assert calls == []


def test_card_blocked_while_auto_and_new_turn_drops_it(client, calls, monkeypatch):
    from canon import autorun

    _written(client)
    calls.clear()  # 작품을 만드는 호출은 세지 않는다
    sid = _session(client)
    _send(client, sid, "더 짧게", preset="shorter", selection=_material())
    monkeypatch.setattr(autorun, "active", lambda name: True)
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True, "picked": ["0"]})
    assert r.status_code == 400 and _text(client) == TEXT
    monkeypatch.setattr(autorun, "active", lambda name: False)
    _send(client, sid, "다른 이야기", selection=_material("바람이 불었다."))
    assert _turn(client, sid, 0)["approval"]["state"] == "denied"  # 답하지 않고 새로 말하면 넣지 않는다


def test_always_ask_and_permit():
    assert agent.ALWAYS_ASK == ("renumber", "text", "setup", "style")  # 04c 의 설정 도구 · 04d 의 문체 도구도 늘 묻는다
    assert agent.KIND_LABELS["text"] == "본문 고치기"
    from canon.schema import AgentSession
    for mode in ("ask", "draft", "all"):
        assert agent.permit(AgentSession(id="x", mode=mode, auto_kinds=["text", "renumber"]), "text") == "ask"


def test_prompt_lists_the_tool_and_text_focus_points_to_it(client):
    from canon import store

    _written(client)
    p = store.load("lh")
    assert "- revise_text (args: quote, request, n, preset)" in prompts.AGENT_PLOT_TOOLS
    block = prompts.agent_focus_block(p, "text:1")
    assert "revise_text 를 n=1 로" in block and "도구는 없으니" not in block
    assert "edit_style" in prompts.agent_focus_block(p, "style")  # 04d: 문체는 문체 도구로
    assert "edit_setup" in prompts.agent_focus_block(p, "setup")  # 설정은 04c 의 설정 도구


def test_old_project_json_reads():
    """04b 전 project.json: 턴에 재료 · 빠른 요청이, 카드에 후보가, 쓴 기록에 수정 id 가 없다."""
    raw = {"meta": {"title": "옛 작품"}, "agent_sessions": [{"id": "s1", "topic": "plot", "turns": [{
        "user": "3화 고쳐", "end": "wait", "approval": {"tool": "edit_plot", "keys": ["3"], "kinds": ["draft"]},
        "writes": [{"tool": "edit_plot", "items": [{"key": "2"}]}]}]}]}
    p = Project.model_validate(raw)
    t = p.agent_sessions[0].turns[0]
    assert t.selection is None and t.preset == ""
    assert t.approval.passage is None and t.approval.episode == 0 and t.approval.at == ""
    assert t.writes[0].edit == "" and t.writes[0].episode == 0
