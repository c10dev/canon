"""플롯 대화형 다듬기 테스트 (mock LLM). 실행: python -m pytest tests"""
from canon import pipeline, prompts
from canon.schema import Act, EpisodePlot, PlotRevision, Project

from .test_web import client  # noqa: F401  (pytest fixture)


def _project(client, eps=10):
    meta = {"title": "등대", "target_episodes": eps}
    client.post("/api/projects", json={"name": "lh", "meta": meta})
    s = client.post("/api/projects/lh/suggest").json()
    p = client.post("/api/projects/lh/suggest/apply", json=s).json()
    p["arc"] = client.post("/api/projects/lh/arc").json()["acts"]
    client.put("/api/projects/lh", json=p)
    return client.post("/api/projects/lh/plots", json={}).json()


def _last(p):
    msgs = p["chats"][0]["messages"]
    return len(msgs) - 1, msgs[-1]


def test_chat_proposes_without_changing(client):
    before = _project(client)
    p = client.post("/api/projects/lh/chat/plot", json={"message": "3화 전개가 너무 빨라"}).json()
    i, m = _last(p)
    first = p["chats"][0]["messages"][0]
    assert (first["role"], first["text"]) == ("user", "3화 전개가 너무 빨라")
    assert m["role"] == "assistant" and [e["number"] for e in m["revision"]["episodes"]] == [3]
    assert p["episodes"] == before["episodes"]  # 반영 전에는 그대로

    p = client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"episodes": [3]}).json()
    assert p["episodes"][2]["plot"]["summary"].endswith("(천천히)")
    _, m = _last(p)
    assert m["outcome"] == "applied" and m["applied"] == ["3"]
    assert client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"episodes": [3]}).status_code == 400


def test_confirmed_goes_back_to_draft_and_written_is_kept(client):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    client.post("/api/projects/lh/episodes/2/confirm")
    client.post("/api/projects/lh/episodes/1/write")
    p = client.post("/api/projects/lh/chat/plot", json={"message": "1화 바꿔 줘"}).json()
    _, m = _last(p)
    assert m["revision"] is None and "본문이 있어" in m["text"]  # 본문 있는 화는 변경안에서 빠진다

    p = client.post("/api/projects/lh/chat/plot", json={"message": "2화 늘려 줘"}).json()
    i, m = _last(p)
    p = client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"episodes": [2]}).json()
    assert p["episodes"][1]["status"] == "draft"  # 확정된 화를 바꾸면 다시 확정해야 한다
    assert p["episodes"][0]["status"] == "written"


def test_ending_changes_act_and_dismiss(client):
    _project(client)
    p = client.post("/api/projects/lh/chat/plot", json={"message": "결말을 비극으로"}).json()
    i, m = _last(p)
    assert m["revision"]["acts"][3]["goal"] == "비극으로 끝난다" and not m["revision"]["episodes"]
    p = client.post(f"/api/projects/lh/chat/plot/{i}/dismiss").json()
    assert _last(p)[1]["outcome"] == "dismissed" and p["arc"][3]["goal"] != "비극으로 끝난다"

    p = client.post("/api/projects/lh/chat/plot", json={"message": "결말을 비극으로"}).json()
    i, _ = _last(p)
    p = client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"acts": True}).json()
    assert p["arc"][3]["goal"] == "비극으로 끝난다"
    assert "결말을 비극으로" in prompts.plot_chat_prompt(Project.model_validate(p), "다음")  # 대화 기록이 프롬프트에 들어간다

    p = client.delete("/api/projects/lh/chat/plot").json()
    assert p["chats"][0]["messages"] == []
    assert client.post("/api/projects/lh/chat/nope", json={"message": "x"}).status_code == 404
    assert client.post("/api/projects/lh/chat/plot", json={"message": "  "}).status_code == 400


def test_resize_episodes(client):
    _project(client, eps=10)
    p = client.post("/api/projects/lh/chat/plot", json={"message": "12화로 늘려 줘"}).json()
    i, m = _last(p)
    assert m["revision"]["total_episodes"] == 12 and [e["number"] for e in m["revision"]["episodes"]] == [11, 12]
    # 구조를 고르지 않고 새 화만 고르면 총 화수 밖이라 막는다
    assert client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"episodes": [11]}).status_code == 400
    p = client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"acts": True, "episodes": [11, 12]}).json()
    assert p["meta"]["target_episodes"] == 12 and len(p["episodes"]) == 12 and p["arc"][-1]["end_ep"] == 12

    client.post("/api/projects/lh/episodes/12/confirm")
    p = client.post("/api/projects/lh/chat/plot", json={"message": "10화로 줄여 줘"}).json()
    i, _ = _last(p)
    r = client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"acts": True})
    assert r.status_code == 400 and "12" in r.json()["detail"]  # 확정된 화가 빠지면 막는다


def test_clean_revision_drops_bad_parts():
    p = Project()
    p.meta.target_episodes = 4
    p.arc = [Act(name=n, start_ep=i + 1, end_ep=i + 1, goal="g") for i, n in enumerate("기승전결")]
    bad_acts = [a.model_copy(update={"end_ep": 9}) if a.name == "결" else a for a in p.arc]
    plot = EpisodePlot(number=9, act="기", title="t", summary="s", events=[], characters=[], emotional_shift="", ending_hook="")
    ok = plot.model_copy(update={"number": 2, "act": "기"})
    rev = pipeline.clean_revision(p, PlotRevision(reply="답", acts=bad_acts, episodes=[plot, ok]))
    assert rev.acts == [] and [e.number for e in rev.episodes] == [2]
    assert rev.episodes[0].act == "승"  # 구간 이름은 구조에 맞춘다
    assert "구조 변경안" in rev.reply and "9화" in rev.reply


def test_cli_revise(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setattr("canon.store.ROOT", tmp_path)
    from canon import cli, store

    p = Project()
    p.meta.target_episodes = 4
    p.arc = [Act(name=n, start_ep=i + 1, end_ep=i + 1, goal="g") for i, n in enumerate("기승전결")]
    store.save("lh", p)
    cli.main(["revise", "lh", "결말을 비극으로", "-y"])
    p = store.load("lh")
    assert p.arc[3].goal == "비극으로 끝난다" and p.chat("plot").messages[-1].outcome == "applied"
    assert "비극" in capsys.readouterr().out
