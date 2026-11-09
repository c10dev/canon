"""본문 부분 수정 테스트 (mock LLM): 고른 부분 직접 고치기, AI 후보 넣기, 되돌리기, 기록. 실행: python -m pytest tests"""
from canon import pipeline, prompts, store
from canon.mock import MockLLM
from canon.schema import ConsistencyIssue, EpisodePlot, Episode, Project, Selection

from .test_plot_chat import _project

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


def _old_passage(name, n, sel, message, preset=""):
    """옛 'AI에게 고치기' 대화 기록을 남긴다. 보내기(chat_send 'text:N')는 04e 에서 지웠고, 같은 함수를 대화 에이전트(agent_text)와 명령줄이 부른다."""
    q = store.load(name)
    s = Selection(start=sel["start"], text=sel["text"])
    pipeline.record_passage(q, n, s, message, preset, pipeline.revise_passage(MockLLM(), q, n, s, message, preset, rules=True))
    store.save(name, q)
    return store.load(name).model_dump(mode="json")


def test_ai_candidates_apply(client):
    _written(client)
    quote = "도현은 대답하지 않았다."
    sel = {"start": TEXT.index(quote), "text": quote}
    assert client.post("/api/projects/lh/chat/text:1", json={"message": "x", "selection": sel}).status_code == 404  # 옛 대화는 보내지 않는다
    p = _old_passage("lh", 1, sel, "", "dialogue")
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

    _old_passage("lh", 1, {"start": 0, "text": "바람이 불었다."}, "다르게")
    p = client.post("/api/projects/lh/chat/text:1/3/dismiss").json()
    assert next(c for c in p["chats"] if c["topic"] == "text:1")["messages"][3]["outcome"] == "dismissed"
    p = client.delete("/api/projects/lh/chat/text:1").json()
    assert next(c for c in p["chats"] if c["topic"] == "text:1")["messages"] == []


def test_finalized_can_be_edited(client):
    """반영이 끝난 화도 고친다. 상태는 그대로 두고 처음 고치기 전 본문을 final_text 에 남긴다 (자세한 것은 test_restate)."""
    _written(client)
    d = client.post("/api/projects/lh/episodes/1/state").json()
    client.post("/api/projects/lh/episodes/1/apply", json=d)
    sel = {"start": 0, "text": "바람이 불었다."}
    e = _ep(client.post("/api/projects/lh/episodes/1/edits", json={"selection": sel, "after": "비가 왔다."}).json())
    assert e["status"] == "finalized" and e["text"].startswith("비가 왔다.") and e["final_text"] == TEXT
    assert client.post("/api/projects/lh/episodes/1/fix-now", json={"message": "x", "selection": {"start": 0, "text": "비가 왔다."}}).status_code == 200


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


def test_fix_request_keeps_wording(client):
    """검수 지적 · 상태 정리 경고에서 온 요청은 낱말만 바꾸는 규칙을 받고, 다른 요청은 서로 다른 방향의 후보를 받는다."""
    _written(client)
    q = Project.model_validate(client.get("/api/projects/lh").json())
    sel = Selection(start=0, text="바람이 불었다.")
    for head in prompts.PASSAGE_FIX_HEADS:
        fix = prompts.passage_prompt(q, 1, sel, f"{head} 80화와 위치가 다르다 → 벽면으로")
        assert prompts.PASSAGE_FIX_RULES in fix and prompts.PASSAGE_FREE_RULES not in fix
    free = prompts.passage_prompt(q, 1, sel, "벽면으로 바꿔 줘")
    assert prompts.PASSAGE_FREE_RULES in free and prompts.PASSAGE_FIX_RULES not in free
    assert prompts.PASSAGE_FIX_RULES not in prompts.passage_prompt(q, 1, sel, "검수 지적: x", "longer")


class _TextRight:
    """본문이 맞고 플롯이 틀렸다고 답하는 LLM (prompts.TEXT_RIGHT_RULE)."""
    def json(self, system, prompt, schema, hint=None):
        return schema(reply="본문이 맞아요. 플롯의 38L을 22L로 고치세요.")


def test_fix_request_may_keep_text(client):
    """고치기 요청에는 본문을 두라는 답이 오면 그대로 보이고, 다른 요청은 다시 적어 달라는 말이 붙는다."""
    _written(client)
    q = Project.model_validate(client.get("/api/projects/lh").json())
    sel = Selection(start=0, text="바람이 불었다.")
    assert prompts.TEXT_RIGHT_RULE.format(field="candidates") in prompts.passage_prompt(q, 1, sel, "상태 정리 경고: 38L")
    rev = pipeline.revise_passage(_TextRight(), q, 1, sel, "상태 정리 경고: 38L")
    assert rev.candidates == [] and rev.reply == "본문이 맞아요. 플롯의 38L을 22L로 고치세요."
    assert "※" in pipeline.revise_passage(_TextRight(), q, 1, sel, "더 낫게").reply


def test_fix_now_applies_first(client):
    """상태 정리 경고의 'AI에게 고치기': 후보를 받아 대화에 남기고 첫 후보를 한 요청 안에서 바로 넣는다."""
    _written(client)
    quote = "도현은 대답하지 않았다."
    sel = {"start": TEXT.index(quote), "text": quote}
    msg = f"상태 정리 경고: 도현 «{quote}» 말이 없다"
    out = client.post("/api/projects/lh/episodes/1/fix-now", json={"message": msg, "selection": sel}).json()
    e = _ep(out["project"])
    edit = e["edits"][-1]
    assert out["edit"] == edit["id"] and edit["source"] == "ai" and edit["instruction"] == msg
    assert edit["before"] == quote and e["text"] != TEXT and edit["after"] in e["text"]
    ai = next(c for c in out["project"]["chats"] if c["topic"] == "text:1")["messages"][-1]
    assert (ai["outcome"], ai["applied"]) == ("applied", ["0"])
    assert client.post("/api/projects/lh/episodes/99/fix-now", json={"message": msg, "selection": sel}).status_code == 404


def test_fix_now_without_candidate(client, monkeypatch):
    """AI가 본문이 맞다고 답하면 본문은 그대로 두고 대화에 답만 남긴다."""
    from canon import web
    _written(client)
    monkeypatch.setattr(web, "get_llm", lambda stage=None: _TextRight())
    out = client.post("/api/projects/lh/episodes/1/fix-now", json={"message": "상태 정리 경고: 38L", "selection": {"start": 0, "text": "바람이 불었다."}}).json()
    assert out["edit"] == "" and _ep(out["project"])["text"] == TEXT
    ai = next(c for c in out["project"]["chats"] if c["topic"] == "text:1")["messages"][-1]
    assert ai["text"].startswith("본문이 맞아요") and ai["passage"] is None


def test_passage_ai_blocked_while_auto(client, monkeypatch):
    """자동 집필이 도는 동안에는 AI를 부르기 전에 막는다 (넣기에서 막히면 AI 비용만 쓴다). 대화 에이전트의 본문 도구는 test_agent_text 가 본다."""
    from canon import autorun
    _written(client)
    called = []
    monkeypatch.setattr(pipeline, "revise_passage", lambda *a, **k: called.append(1))
    monkeypatch.setattr(autorun, "active", lambda name: True)
    sel = {"start": 0, "text": "바람이 불었다."}
    assert client.post("/api/projects/lh/episodes/1/fix-now", json={"message": "상태 정리 경고: x", "selection": sel}).status_code == 400
    assert called == []


def test_passage_head_stays_same_for_the_episode(client):
    # 같은 화의 부분 수정은 고른 곳 · 본문 · 대화가 달라도 같은 앞부분으로 시작해야 캐시가 맞는다
    from canon.llm import PREFIX_HINT

    p = Project.model_validate(_written(client))
    head = prompts.passage_head(p, 1)
    a = prompts.passage_prompt(p, 1, Selection(start=0, text="바람이 불었다."), "짧게")
    p.episode(1).text = TEXT.replace("도현은", "도현이")
    b = prompts.passage_prompt(p, 1, Selection(start=TEXT.index("\"됐어"), text="\"됐어, 내가 할게.\""), "길게")
    assert a.startswith(head + "\n\n# 인물 현재 상태") and b.startswith(head + "\n\n# 인물 현재 상태")
    assert "【고칠 부분】" not in head and "# 1화 본문" not in head

    seen = []

    class Spy:
        def json(self, system, prompt, schema, hint=None):
            seen.append((prompt, hint))
            return schema(reply="ok", candidates=[{"text": "바람이 세게 불었다."}])

    pipeline.revise_passage(Spy(), p, 1, Selection(start=0, text="바람이 불었다."), "세게")
    prompt, hint = seen[0]
    assert hint[PREFIX_HINT] == len(head) and prompt.startswith(head)
