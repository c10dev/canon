"""본문 부분 수정 테스트 (mock LLM): 고른 부분 직접 고치기, AI 후보 넣기, 되돌리기, 기록. 실행: python -m pytest tests"""
from canon import pipeline, prompts
from canon.schema import ConsistencyIssue, EpisodePlot, Episode, Project, Selection

from .test_plot_chat import _project
from .test_web import client  # noqa: F401  (pytest fixture)

TEXT = "바람이 불었다. 서윤은 등대 앞에 섰다.\n\n\"됐어, 내가 할게.\"\n\n도현은 대답하지 않았다."


def _written(client):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    client.post("/api/projects/lh/episodes/1/write")
    return client.put("/api/projects/lh/episodes/1/text", json={"text": TEXT}).json()


def _ep(p, n=1):
    return p["episodes"][n - 1]


def test_manual_edit_and_undo(client):
    p = _written(client)
    assert _ep(p)["edits"][-1]["source"] == "typed"  # mock 본문을 통째로 바꾼 저장도 기록된다
    quote = "서윤은 등대 앞에 섰다."
    sel = {"start": TEXT.index(quote), "text": quote}
    p = client.post("/api/projects/lh/episodes/1/edits", json={"selection": sel, "after": "서윤은 등대 문을 밀었다."}).json()
    e = _ep(p)
    assert e["text"] == TEXT.replace(quote, "서윤은 등대 문을 밀었다.")
    edit = e["edits"][-1]
    assert (edit["source"], edit["before"], edit["after"], edit["start"]) == ("manual", quote, "서윤은 등대 문을 밀었다.", sel["start"])

    # 앞쪽이 바뀌어 위치가 밀려도 원문으로 다시 찾는다
    p = client.put("/api/projects/lh/episodes/1/text", json={"text": "새 첫 문장. " + e["text"]}).json()
    p = client.post(f"/api/projects/lh/episodes/1/edits/{edit['id']}/undo").json()
    assert _ep(p)["text"] == "새 첫 문장. " + TEXT
    assert next(x for x in _ep(p)["edits"] if x["id"] == edit["id"])["undone"]
    assert client.post(f"/api/projects/lh/episodes/1/edits/{edit['id']}/undo").status_code == 400

    gone = {"start": 0, "text": "본문에 없는 문장"}
    assert client.post("/api/projects/lh/episodes/1/edits", json={"selection": gone, "after": "x"}).status_code == 400


def test_ai_candidates_apply(client):
    _written(client)
    quote = "도현은 대답하지 않았다."
    sel = {"start": TEXT.index(quote), "text": quote}
    assert client.post("/api/projects/lh/chat/text:1", json={"message": "더 짧게"}).status_code == 400  # 고른 부분 없음
    assert client.post("/api/projects/lh/chat/text:99", json={"message": "x", "selection": sel}).status_code == 404
    p = client.post("/api/projects/lh/chat/text:1", json={"preset": "dialogue", "selection": sel}).json()
    chat = next(c for c in p["chats"] if c["topic"] == "text:1")
    user, ai = chat["messages"]
    assert (user["text"], user["preset"]) == ("대사 늘리기", "dialogue")
    assert _ep(p)["text"] == TEXT  # 고르기 전에는 그대로
    cands = ai["passage"]["candidates"]
    assert len(cands) == 2 and all(c["text"] != quote for c in cands)  # 원문과 같은 후보는 걸러진다

    p = client.post("/api/projects/lh/chat/text:1/1/apply", json={"candidate": 1, "text": "도현은 끝내 입을 열지 않았다."}).json()
    e = _ep(p)
    assert e["text"].endswith("도현은 끝내 입을 열지 않았다.")
    edit = e["edits"][-1]
    assert edit["source"] == "ai" and edit["proposed"] == cands[1]["text"] and edit["rejected"] == [cands[0]["text"]]
    assert edit["preset"] == "dialogue" and edit["instruction"] == "대사 늘리기"
    ai = next(c for c in p["chats"] if c["topic"] == "text:1")["messages"][1]
    assert (ai["outcome"], ai["applied"]) == ("applied", ["1"])
    assert client.post("/api/projects/lh/chat/text:1/1/apply", json={"candidate": 0}).status_code == 400

    # 같은 부분을 이어서 고치면 대화 기록이 프롬프트에 들어간다
    q = Project.model_validate(p)
    prompt = prompts.passage_prompt(q, 1, Selection(start=edit["start"], text=edit["after"]), "조금 더 길게")
    assert "【고칠 부분】도현은 끝내 입을 열지 않았다.【여기까지】" in prompt and "2번 후보를 넣음" in prompt

    p = client.post("/api/projects/lh/chat/text:1", json={"message": "다르게", "selection": {"start": 0, "text": "바람이 불었다."}}).json()
    p = client.post("/api/projects/lh/chat/text:1/3/dismiss").json()
    assert next(c for c in p["chats"] if c["topic"] == "text:1")["messages"][3]["outcome"] == "dismissed"
    p = client.delete("/api/projects/lh/chat/text:1").json()
    assert next(c for c in p["chats"] if c["topic"] == "text:1")["messages"] == []


def test_finalized_is_locked(client):
    _written(client)
    d = client.post("/api/projects/lh/episodes/1/state").json()
    client.post("/api/projects/lh/episodes/1/apply", json=d)
    sel = {"start": 0, "text": "바람이 불었다."}
    assert client.post("/api/projects/lh/episodes/1/edits", json={"selection": sel, "after": "비가 왔다."}).status_code == 400
    assert client.post("/api/projects/lh/chat/text:1", json={"message": "x", "selection": sel}).status_code == 400


def test_typed_diff_and_presets():
    plot = EpisodePlot(number=1, act="기", title="t", summary="", events=[], characters=[], emotional_shift="", ending_hook="")
    p = Project(episodes=[Episode(plot=plot, status="written", text="가나다라마")])
    e = pipeline.record_typed(p, 1, "가나다라마", "가나X라마")
    assert (e.start, e.before, e.after) == (2, "다", "X")
    assert pipeline.record_typed(p, 1, "", "새 본문") is None
    assert pipeline.locate("abcabc", "abc", 2) == 3 and pipeline.locate("abcabc", "abc", 0) == 0
    for k in range(60):
        pipeline.edit_text(p, 1, Selection(start=0, text=p.episodes[0].text[:1]), "AB"[k % 2])
    assert len(p.episodes[0].edits) == pipeline.EDIT_KEEP and p.episodes[0].edits[-1].id == "e61"
    assert "less_ai" in prompts.PASSAGE_PRESETS
    assert "몸이 향한 쪽" in prompts.passage_request("", "blocking")
    # 검수가 장면 안 동선(앞 · 뒤, 가린 곳)도 짚고, 그 지적은 부분 수정으로 이어진다
    assert "- 동선:" in prompts.check_prompt(p, 1)
    assert ConsistencyIssue(type="동선", description="x", source_episode=1, source_quote="a", current_quote="b").type == "동선"
