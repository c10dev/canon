"""대화 에이전트 테스트 (mock LLM). 실행: python -m pytest tests"""
from .test_arc_chat import _three_arcs
from .test_plot_chat import _project
from .test_web import _wait, client  # noqa: F401  (pytest fixture)


def _session(client, name="lh", **kw):
    r = client.post(f"/api/projects/{name}/sessions", json={"topic": "plot", **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _say(client, sid, message, name="lh", **kw):
    r = client.post(f"/api/projects/{name}/sessions/{sid}/turns", json={"message": message, **kw})
    assert r.status_code == 200, r.text
    assert _wait(client, r.json()["id"])["status"] == "done"
    return _turn(client, sid, name)


def _turn(client, sid, name="lh", t=-1):
    out = client.get(f"/api/projects/{name}/sessions?topic=plot").json()
    s = next(x for x in out["sessions"] if x["id"] == sid)
    return s["turns"][t]


def _ep(client, n, name="lh"):
    return client.get(f"/api/projects/{name}").json()["episodes"][n - 1]


def test_draft_episode_is_written_at_once_and_undone(client):
    before = _project(client)
    sid = _session(client)
    t = _say(client, sid, "3화 전개가 너무 빨라")
    assert [s["kind"] for s in t["steps"]] == ["read", "write"] and t["end"] == "done"
    assert t["steps"][0]["result"] == ""  # 끝난 턴은 단계 결과를 지운다
    assert [i["key"] for i in t["writes"][0]["items"]] == ["3"]
    assert _ep(client, 3)["plot"]["summary"].endswith("(천천히)")

    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={}).json()
    assert r["restored"] == ["3화 플롯"] and r["kept"] == []
    assert r["project"]["episodes"][2]["plot"] == before["episodes"][2]["plot"]
    assert _turn(client, sid)["writes"][0]["items"][0]["state"] == "reverted"
    assert client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={}).status_code == 400  # 되돌릴 것이 없다


def test_confirmed_episode_asks_and_approval_continues(client):
    _project(client)
    client.post("/api/projects/lh/episodes/3/confirm")
    plot = _ep(client, 3)["plot"]
    sid = _session(client)
    t = _say(client, sid, "3화 전개가 너무 빨라")
    assert t["end"] == "wait" and t["approval"]["keys"] == ["3"] and t["approval"]["kinds"] == ["confirmed"]
    assert t["steps"][-1]["kind"] == "wait" and _ep(client, 3)["plot"] == plot  # 묻는 동안은 그대로

    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True, "remember": True})
    assert r.status_code == 200, r.text
    assert r.json()["project"]["episodes"][2]["status"] == "draft"  # 확정한 화를 바꾸면 초안으로 돌아간다
    assert _wait(client, r.json()["job"]["id"])["status"] == "done"
    t = _turn(client, sid)
    assert t["end"] == "done" and t["approval"]["state"] == "approved" and t["reply"] == "작가의 답대로 마쳤어요."
    s = client.get("/api/projects/lh/sessions").json()["sessions"][0]
    assert s["auto_kinds"] == ["confirmed"]  # 이 세션에서는 확정한 화도 묻지 않는다


def test_denied_approval_writes_nothing(client):
    _project(client)
    client.post("/api/projects/lh/episodes/3/confirm")
    plot = _ep(client, 3)["plot"]
    sid = _session(client)
    _say(client, sid, "3화 전개가 너무 빨라")
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": False}).json()
    _wait(client, r["job"]["id"])
    t = _turn(client, sid)
    assert t["approval"]["state"] == "denied" and t["writes"] == [] and t["end"] == "done"
    assert _ep(client, 3)["plot"] == plot and _ep(client, 3)["status"] == "confirmed"


def test_written_episode_is_blocked(client):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    client.post("/api/projects/lh/episodes/1/write")
    plot = _ep(client, 1)["plot"]
    sid = _session(client)
    t = _say(client, sid, "1화 바꿔 줘")
    block = [s for s in t["steps"] if s["kind"] == "block"]
    assert block and "본문이 있음" in block[0]["why"] and t["writes"] == []
    assert _ep(client, 1)["plot"] == plot


def test_modes(client):
    _project(client)
    client.post("/api/projects/lh/episodes/4/confirm")
    sid = _session(client)
    client.patch(f"/api/projects/lh/sessions/{sid}", json={"mode": "ask"})
    t = _say(client, sid, "3화 전개가 너무 빨라")
    assert t["end"] == "wait" and t["approval"]["kinds"] == ["draft"]  # 물어보기는 초안도 묻는다

    sid2 = _session(client)
    client.patch(f"/api/projects/lh/sessions/{sid2}", json={"mode": "all"})
    t = _say(client, sid2, "4화 전개가 너무 빨라")
    assert t["end"] == "done" and [i["key"] for i in t["writes"][0]["items"]] == ["4"]  # 모두 자동은 확정한 화도 쓴다
    assert client.patch(f"/api/projects/lh/sessions/{sid2}", json={"mode": "x"}).status_code == 400


def test_new_turn_while_waiting_drops_the_approval(client):
    _project(client)
    client.post("/api/projects/lh/episodes/3/confirm")
    sid = _session(client)
    _say(client, sid, "3화 전개가 너무 빨라")
    _say(client, sid, "괜찮아, 그냥 둬?")
    first = _turn(client, sid, t=0)
    assert first["approval"]["state"] == "denied" and first["steps"][-1]["kind"] == "note"


def test_step_cap_and_continue(client):
    _project(client)
    sid = _session(client)
    t = _say(client, sid, "끝없이 읽어 줘")
    assert t["end"] == "cap" and len(t["steps"]) == 8
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/continue")
    assert r.status_code == 200, r.text
    _wait(client, r.json()["id"])
    assert len(_turn(client, sid)["steps"]) == 16


def test_end_name_as_tool_ends_the_turn(client):
    _project(client)
    sid = _session(client)
    t = _say(client, sid, "읽고 끝 이름으로 끝내 줘")
    assert [s["kind"] for s in t["steps"]] == ["read"] and t["end"] == "done"  # '없는 도구예요' 단계가 없다
    assert t["reply"] == "읽어 보니 고칠 곳이 없어요."


def test_preamble_reply_is_sent_back_once(client):
    """예고만 한 답("…분석해 전달합니다")은 한 번 되돌려 내용을 쓰게 한다 (2026-11-04 서버 턴)."""
    _project(client)
    sid = _session(client)
    t = _say(client, sid, "아크 1을 서사 분석")
    assert [(s["kind"], s["tool"]) for s in t["steps"]] == [("note", "reply")] and t["end"] == "done"
    assert t["reply"].startswith("기(1~2화)")


def test_empty_ask_is_sent_back_once(client):
    """question · options · reply 가 모두 빈 ask 는 답할 것이 없는 '되물음' 줄만 남겼다 (2026-11-04 서버 턴). 한 번 되돌린다."""
    _project(client)
    sid = _session(client)
    t = _say(client, sid, "빈 물음으로 분석해 줘")
    assert [(s["kind"], s["tool"]) for s in t["steps"]] == [("note", "ask_empty")] and t["end"] == "done"
    assert t["reply"].startswith("1~7화") and not t["ask"]
    t = _say(client, sid, "빈 물음 계속")
    assert t["end"] == "done" and t["reply"].startswith("AI가 묻는 말을 비운 채")


def test_empty_tool_payload_is_filled_in_the_same_step(client):
    """tool 만 고르고 칸을 비운 응답은 그 칸만 담은 형식으로 한 번 더 불러 채운다 (2026-11-04 gemini-4-argon)."""
    _project(client)
    sid = _session(client)
    t = _say(client, sid, "빈 고치기로 3화 전개가 너무 빨라")
    assert [(s["kind"], s["tool"]) for s in t["steps"]][0] == ("write", "edit_plot") and t["writes"]
    t = _say(client, sid, "빈 채우기")
    assert t["end"] == "ask" and t["ask"]["question"] == "몇 화로 갈까요?" and len(t["ask"]["options"]) == 2


def test_fill_turns_options_only_edit_into_ask():
    from canon import agent
    from canon.schema import Direction, PlotAgentStep, PlotRevision

    class Fake:
        def json(self, system, prompt, schema, hint=None):
            assert "[이번 단계] 도구 edit_plot" in prompt and schema is PlotRevision
            return PlotRevision(reply="방향부터 골라 주세요", options=[Direction(title="가", idea="가")])

    step = agent.fill(Fake(), "s", "p", PlotAgentStep(thought="고쳐요", tool="edit_plot"), {})
    assert step.tool == "ask" and step.question == "방향부터 골라 주세요" and step.options[0].title == "가"
    full = PlotAgentStep(tool="ask", question="이미 있음")
    assert agent.fill(Fake(), "s", "p", full, {}) is full  # 칸이 있으면 부르지 않는다


def test_is_preamble():
    from canon.agent import is_preamble
    assert is_preamble("아크 1(1~7화)의 기승전결 구조, 심리·감각의 점층성, 그리고 현재 화별 플롯의 보완 필요 지점을 분석해 작가님께 전달합니다.")
    assert is_preamble("먼저 1~3화 줄거리를 살펴보겠습니다.")
    assert not is_preamble("3화 플롯의 갈등을 앞당겼어요. 4화는 그대로 뒀어요.")
    assert not is_preamble("가" * 301 + "하겠습니다.")
    assert not is_preamble("")


def test_step_tool_names():
    import pytest
    from pydantic import ValidationError

    from canon.schema import PlotAgentStep

    assert [PlotAgentStep(tool=x).tool for x in ("reply", " Reply ", "DONE", "finish", "end", "none", "")] == [""] * 7
    assert PlotAgentStep(tool="Read_Plots").tool == "read_plots"
    with pytest.raises(ValidationError):
        PlotAgentStep(tool="write_plot")  # 없는 도구는 형식 오류로 다시 묻는다


def test_options_mode_asks_without_writing(client):
    _project(client)
    sid = _session(client)
    t = _say(client, sid, "갈등을 어떻게 잡을지 모르겠어", mode="options")
    assert t["end"] == "ask" and len(t["ask"]["options"]) == 3 and t["writes"] == []


def test_undo_keeps_reedited_episode(client):
    _project(client)
    sid = _session(client)
    _say(client, sid, "3화 전개가 너무 빨라")
    p = client.get("/api/projects/lh").json()
    p["episodes"][2]["plot"]["title"] = "작가가 다시 고친 제목"
    client.put("/api/projects/lh", json=p)
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={"write": 0, "key": "3"}).json()
    assert r["restored"] == [] and r["kept"] == ["3화 플롯"] and "다시 고침" in r["reasons"][0]
    item = _turn(client, sid)["writes"][0]["items"][0]
    assert item["state"] == "kept" and "다시 고침" in item["reason"]


def test_screen_save_keeps_sessions_and_legacy_chat_shows(client):
    p = _project(client)  # 대화 세션이 없을 때 받은 작품
    client.post("/api/projects/lh/chat/plot", json={"message": "3화 전개가 너무 빨라"})  # 옛 단발 대화
    sid = _session(client, target="")
    _say(client, sid, "4화 전개가 너무 빨라")
    out = client.get("/api/projects/lh/sessions").json()
    assert out["legacy"] == 2 and out["model"] and out["max_steps"] == 8
    p["meta"]["title"] = "등대 2"
    client.put("/api/projects/lh", json=p)
    out = client.get("/api/projects/lh/sessions").json()
    assert [s["id"] for s in out["sessions"]] == [sid]
    assert out["sessions"][0]["title"] == "4화 전개가 너무 빨라"


def test_stopped_turn_saves_nothing(client, monkeypatch):
    _project(client)
    sid = _session(client)
    monkeypatch.setenv("CANON_MOCK_DELAY", "0.3")
    r = client.post("/api/projects/lh/sessions/{}/turns".format(sid), json={"message": "3화 전개가 너무 빨라"}).json()
    client.post(f"/api/jobs/{r['id']}/stop")
    import time
    time.sleep(0.5)
    monkeypatch.setenv("CANON_MOCK_DELAY", "0")
    t = _turn(client, sid)
    assert t["end"] == "stopped" and t["writes"] == []
    assert not _ep(client, 3)["plot"]["summary"].endswith("(천천히)")
    assert client.post(f"/api/projects/lh/sessions/{sid}/turns/0/continue").status_code == 200  # 멈춘 턴은 이어 할 수 있다


def test_next_arc_goes_to_draft_without_changing_the_project(client):
    from canon import store

    p, a1, a2, a3 = _three_arcs()
    store.save("sr", p)
    arcs = [a.model_dump() for a in store.load("sr").story_arcs]
    sid = _session(client, name="sr", target="next")
    t = _say(client, sid, "15화짜리로 짜 줘", name="sr")
    keys = [i["key"] for w in t["writes"] for i in w["items"]]
    assert keys == ["draft"] and t["writes"][0]["revision"]["arc"]["title"] == "대화로 짠 아크"
    assert [a.model_dump() for a in store.load("sr").story_arcs] == arcs  # 다음 아크 초안은 화면에만 놓인다


def test_step_call_waits_less_and_caps_output(client, monkeypatch):
    """한 단계의 AI 호출은 STEP_WAIT 초까지만 기다리고 출력도 STEP_OUT_TOKENS 까지 받는다. 작업에 단계 시작 시각을 남긴다."""
    import time

    from canon import agent, jobs, llm, store
    from canon.schema import PlotAgentStep

    monkeypatch.delenv("CANON_GEMINI_TIMEOUT", raising=False)
    _project(client)
    sid = _session(client)
    p = store.load("lh")
    t = agent.add_turn(p, sid, "3화 전개가 너무 빨라")
    store.save("lh", p)
    seen = {}

    class Fake:
        def json(self, system, prompt, schema, hint=None):
            seen.update(wait=llm.gemini_timeout(), out=llm._out_cap.get())
            return PlotAgentStep(reply="그대로 둘게요")

    job = jobs.Job(id="x", project="lh", kind="agent", ep=None, label="")
    before = time.time()
    assert agent.run_turn(Fake(), "lh", sid, t, job)["end"] == "done"
    assert seen == {"wait": agent.STEP_WAIT, "out": agent.STEP_OUT_TOKENS}
    assert job.step_at >= before and job.public()["step_at"] == job.step_at
    assert llm.gemini_timeout() == llm.GEMINI_TIMEOUT  # 단계 밖은 그대로


def test_wait_cap_never_raises_the_limit(monkeypatch):
    from canon import llm

    monkeypatch.setenv("CANON_GEMINI_TIMEOUT", "90")
    with llm.wait_cap(300):
        assert llm.gemini_timeout() == 90
    monkeypatch.delenv("CANON_GEMINI_TIMEOUT")
    with llm.wait_cap(300):
        assert llm.gemini_timeout() == 300


def test_chat_stage_follows_plan_until_set(monkeypatch, tmp_path):
    """플롯 대화 단계(chat)는 비우면 계획 단계를 따르고, 따로 고르면 그 백엔드 · 모델만 쓴다."""
    from canon import settings
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("CANON_LLM", "gemini")
    for k in ("CANON_LLM_PLAN", "CANON_LLM_CHAT", "CANON_MODEL_PLAN", "CANON_MODEL_CHAT"):
        monkeypatch.delenv(k, raising=False)
    assert settings.STAGE_PARENT["chat"] == "plan"
    settings.update(stage_models={"plan": "gemini-4-argon"})
    assert settings.stage_provider("chat")[0] == "gemini" and settings.stage_model("chat")[0] == "gemini-4-argon"
    settings.update(stages={"chat": "claude"})
    assert settings.stage_provider("chat")[0] == "claude" and settings.stage_provider("plan")[0] == "gemini"
    assert settings.stage_model("chat")[0] == ""  # 백엔드가 다르면 계획 단계 모델을 물려받지 않는다


def test_turn_uses_chat_stage(client, monkeypatch):
    from canon import web
    asked = []
    real = web.get_llm
    monkeypatch.setattr(web, "get_llm", lambda stage=None: asked.append(stage) or real(stage))
    _project(client)
    asked.clear()  # 작품 만들기는 계획 단계를 쓴다
    _say(client, _session(client), "3화 고쳐 줘")
    assert set(asked) == {"chat"}  # 턴과 패널 상태 줄의 모델 이름 모두


def _with_text(client, n=5):
    """n 화에 본문만 있다 (반영 전). 서버 subway-1-수정본처럼 재구성으로 옮겨 온 본문."""
    from canon import store
    _project(client)
    p = store.load("lh")
    p.episode(n).text, p.episode(n).status = "옮겨 온 본문", "written"
    store.save("lh", p)


def test_insert_episodes_always_asks_then_moves_written(client):
    _with_text(client)
    sid = _session(client, mode="all")  # '모두 자동'이어도 묻는다
    t = _say(client, sid, "5화 본문을 7화로 옮기게 5화 앞에 2화 넣어 줘")
    a = t["approval"]
    assert t["end"] == "wait" and a["keys"] == ["renumber"] and a["op"]["at"] == 5 and len(a["op"]["titles"]) == 2
    assert any("본문이 있는 5화는 7화" in x for x in a["op"]["notes"])
    assert _ep(client, 5)["text"] == "옮겨 온 본문"  # 묻는 동안은 그대로

    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/approval", json={"approve": True})
    assert r.status_code == 200, r.text
    assert _wait(client, r.json()["job"]["id"])["status"] == "done"
    assert _ep(client, 7)["text"] == "옮겨 온 본문" and _ep(client, 5)["plot"]["title"] == "새 화 1"
    t = _turn(client, sid)
    assert t["writes"][0]["items"][0]["key"] == "renumber" and t["end"] == "done"

    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={}).json()
    assert r["restored"] == ["5화 앞에 새 화 2개 넣기"]
    assert _ep(client, 5)["text"] == "옮겨 온 본문" and len(client.get("/api/projects/lh").json()["episodes"]) == 10


def test_remove_episode_blocks_text_and_asks_for_empty(client):
    _with_text(client)
    sid = _session(client)
    t = _say(client, sid, "5화 빼 줘")
    assert t["steps"][0]["kind"] == "block" and "본문이 있어" in t["steps"][0]["why"] and not t["approval"]
    t = _say(client, sid, "4화 빼 줘")
    assert t["end"] == "wait" and t["approval"]["op"]["kind"] == "remove"
    title = _ep(client, 4)["plot"]["title"]
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/1/approval", json={"approve": True})
    _wait(client, r.json()["job"]["id"])
    assert _ep(client, 4)["text"] == "옮겨 온 본문"
    client.post(f"/api/projects/lh/sessions/{sid}/turns/1/undo", json={})
    assert _ep(client, 4)["plot"]["title"] == title and _ep(client, 5)["text"] == "옮겨 온 본문"


def test_undo_remove_brings_back_the_whole_episode_and_insert_undo_keeps_edits(client):
    """화 빼기를 되돌리면 스토리보드 · 큐 시트 · 다 쓴 사건 체크까지 살린다. 넣은 화를 그 뒤 고쳤으면 넣기를 되돌리지 않는다."""
    import pytest

    from canon import agent, store
    from canon.schema import CueSheet, Storyboard
    _project(client)
    p = store.load("lh")
    e = p.episode(4)
    e.status, e.storyboard, e.cue_sheet, e.events_done = "confirmed", Storyboard(made_by="author"), CueSheet(key="불안"), ["x"]
    op = agent.op_from("remove_episode", {"n": "4"})
    agent.apply_op(p, op, True)
    agent.inverse(p, op, True)
    e = p.episode(4)
    assert (e.status, e.storyboard.made_by, e.cue_sheet.key, e.events_done) == ("confirmed", "author", "불안", ["x"])
    op = agent.op_from("insert_episodes", {"at": "5", "titles": "새 화"})
    agent.apply_op(p, op, True)
    p.episode(5).plot.summary = "작가가 쓴 요약"
    with pytest.raises(ValueError, match="5화를 그 뒤에 고쳐서"):
        agent.inverse(p, op, True)
    assert p.episode(5).plot.summary == "작가가 쓴 요약"
    p.episode(5).plot.summary = op.inserted[0].plot.summary
    total = len(p.episodes)
    agent.inverse(p, op, True)
    assert len(p.episodes) == total - 1


def test_old_turns_drop_undo_data(client, monkeypatch):
    """최근 UNDO_TURNS 턴보다 오래된 턴은 쓰기 전 · 뒤 값을 지워 project.json 이 끝없이 커지지 않는다. 턴 번호는 그대로다."""
    from canon import agent, store
    monkeypatch.setattr(agent, "UNDO_TURNS", 2)
    _project(client)
    sid = _session(client)
    for _ in range(5):
        _say(client, sid, "3화 전개가 너무 빨라")
    turns = next(s for s in store.load("lh").agent_sessions if s.id == sid).turns
    assert len(turns) == 5
    old, recent = turns[:2], turns[-2:]
    assert all(w.before is None and w.after is None for t in old for w in t.writes)
    assert all(i.state != "done" for t in old for w in t.writes for i in w.items)
    assert any(i.reason == agent.OLD_UNDO for t in old for w in t.writes for i in w.items)
    assert any(w.before is not None for t in recent for w in t.writes)
    r = client.post(f"/api/projects/lh/sessions/{sid}/turns/0/undo", json={})
    assert r.status_code == 400


def test_op_from_and_shift():
    import pytest
    from canon import agent
    op = agent.op_from("insert_episodes", {"at": "8화", "titles": "가 | 나 | 다"})
    assert (op.at, op.titles, op.summaries) == (8, ["가", "나", "다"], ["", "", ""])
    assert agent.shift(op)(8) == 11 and agent.shift(op)(7) == 7 and agent.shift(op, inverse=True)(11) == 8
    rm = agent.op_from("remove_episode", {"n": "4"})
    assert agent.shift(rm)(5) == 4 and agent.shift(rm, inverse=True)(4) == 5
    with pytest.raises(ValueError):
        agent.op_from("insert_episodes", {"at": "3", "count": "11"})
    with pytest.raises(ValueError):
        agent.op_from("remove_episode", {})


def test_part_and_episode_targets():
    import pytest
    from canon import pipeline, prompts
    p, a1, a2, a3 = _three_arcs()  # 1부 1~100화, 아크 1~3 (1~36화), 아크 1은 반영함
    assert pipeline.chat_target(p, "part:1") == ("arc:2", a2)  # 본문이 없는 첫 아크
    assert pipeline.chat_target(p, "ep:30") == ("arc:3", a3)
    assert pipeline.chat_session_target(p, "part:1") == "part:1" and pipeline.chat_session_target(p, "") == "arc:2"
    assert pipeline.chat_focus(p, "ep:30")[:3] == ("ep", 30, 30)
    with pytest.raises(ValueError, match="아크가 없고"):
        pipeline.chat_target(p, "part:2")
    with pytest.raises(ValueError, match="9부가 없어요"):
        pipeline.chat_target(p, "part:9")
    with pytest.raises(ValueError, match="40화 플롯이 없어요"):
        pipeline.chat_target(p, "ep:40")
    block = prompts.agent_focus_block(p, "part:1")
    assert "1부" in block and f"아크 {a3.number}" in block and prompts.agent_focus_block(p, "") == ""


def test_episode_focus_asks_outside_even_in_all_mode(client):
    _project(client)
    sid = _session(client, mode="all", target="ep:3")
    assert _turn_session(client, sid)["target"] == "ep:3"
    t = _say(client, sid, "3화 전개가 너무 빨라")
    assert t["writes"] and t["writes"][0]["items"][0]["key"] == "3"  # 고른 화는 권한 모드대로 바로 쓴다
    r = client.patch(f"/api/projects/lh/sessions/{sid}", json={"target": "ep:5"})
    assert r.status_code == 200 and r.json()["target"] == "ep:5"
    t = _say(client, sid, "3화 전개가 너무 빨라")
    assert t["end"] == "wait" and t["approval"]["kinds"] == ["outside"]  # 고른 화 밖이라 '모두 자동'이어도 묻는다
    assert client.patch(f"/api/projects/lh/sessions/{sid}", json={"target": "ep:99"}).status_code == 400


def _turn_session(client, sid, name="lh"):
    return next(x for x in client.get(f"/api/projects/{name}/sessions?topic=plot").json()["sessions"] if x["id"] == sid)


def test_step_prompt_extends_the_previous_step_prompt(client, monkeypatch):
    """단계 k+1 요청은 단계 k 요청(끝 줄 '남은 단계는 N개입니다.' 뺀 것)으로 시작한다. 서버 캐시가 앞 요청을 다시 쓰게 한다."""
    from canon import agent, prompts
    seen = []
    real = prompts.agent_plot_prompt

    def spy(*a, **kw):
        seen.append(real(*a, **kw))
        return seen[-1]
    monkeypatch.setattr(agent.prompts, "agent_plot_prompt", spy)
    _project(client)
    sid = _session(client)
    t = _say(client, sid, "끝없이 읽어 줘")  # 쓰기 없이 8단계를 읽는다
    assert t["end"] == "cap" and len(seen) == 8
    for k, (a, b) in enumerate(zip(seen, seen[1:])):
        head, last = a.rsplit("\n", 1)
        assert last == f"남은 단계는 {8 - k}개입니다."
        assert b.startswith(head) and len(b) > len(a)
    at = [seen[0].index(x) for x in ("요구사항:", "\n[작가의 새 말]\n", "\n[이번 턴 방식]\n", "\n[이번 턴에 한 일]")]
    assert at == sorted(at)  # 세션 안에서 바뀌지 않는 요구사항이 앞, 턴마다 바뀌는 블록이 뒤
    assert "이 프롬프트의 위아래 블록과 [이번 턴에 한 일]에 이미 있는 내용은 다시 읽지 않고" in seen[0]  # 요구사항 위의 플롯 블록도 덮는다
    seen.clear()
    _say(client, sid, "다른 방향 몇 가지 보여 줘", mode="options")
    assert "작가가 방향 여러 안을 청했습니다" in seen[0].split("\n[이번 턴 방식]\n", 1)[1]


def test_plot_chat_parts_names_follow_the_given_rng():
    """대화 에이전트는 세션 id 로 이름 후보를 고정한다. 같은 난수면 장편 앞부분도 글자까지 같다."""
    import random
    from canon import prompts
    from canon.schema import ChatScope
    p = _three_arcs()[0]
    one, two = (prompts.plot_chat_parts(p, ChatScope(), random.Random("s1")) for _ in range(2))
    assert one == two and "[이름 후보]" in one[1]
