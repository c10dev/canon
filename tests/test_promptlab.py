"""프롬프트 놀이터 (canon/promptlab.py, 웹 /api/promptlab, mock LLM). 실행: python -m pytest tests/test_promptlab.py"""

import pytest

from canon import promptlab, usage
from canon.schema import PromptBackend


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_PROMPTLAB", str(tmp_path / "promptlab"))
    return tmp_path


def test_create_title_and_backends(home):
    s = promptlab.create(prompt="\n  첫 줄 요청\n둘째 줄", backends=[PromptBackend(provider="mock"), PromptBackend(provider="mock"),
                                                                   PromptBackend(provider="gemini", url="http://x")])
    assert s.title == "첫 줄 요청"
    assert [b.provider for b in s.backends] == ["mock", "gemini"] and s.backends[1].url == ""  # 같은 백엔드는 한 번, 주소는 로컬만
    assert promptlab.load(s.id).title == "첫 줄 요청"
    s = promptlab.update(s.id, "내 제목", "", "다른 요청", 9, s.backends)
    assert s.title == "내 제목" and s.temperature == promptlab.TEMPERATURE[1]
    s = promptlab.update(s.id, "내 제목", "", "또 다른 요청", None, s.backends)
    assert s.title == "내 제목"  # 작가가 적은 제목은 남는다
    with pytest.raises(ValueError, match="알 수 없는 백엔드"):
        promptlab.create(backends=[PromptBackend(provider="openai")])
    with pytest.raises(ValueError, match="4개까지"):
        promptlab.create(backends=[PromptBackend(provider="local", model=str(i)) for i in range(5)])
    with pytest.raises(KeyError):
        promptlab.load("../x")


def test_run_trials_restore(home):
    s = promptlab.create(system="시스템", prompt="요청", backends=[PromptBackend(provider="mock")])
    runs = promptlab.run(s)
    assert len(runs) == 1 and runs[0].ok and runs[0].text and runs[0].cost == 0.0
    t = promptlab.add_trial(s, s.system, s.prompt, s.temperature, runs)
    assert t.no == 1
    promptlab.edit(s, 1, star=True, note=" 좋음 ")
    assert s.trials[0].star and s.trials[0].note == "좋음"
    s.prompt = "고친 요청"
    promptlab.restore(s, 1)
    assert s.prompt == "요청"
    promptlab.remove(s, 1)
    assert s.trials == []
    with pytest.raises(KeyError):
        promptlab.find(s, 1)
    with pytest.raises(ValueError, match="요청 프롬프트"):
        promptlab.run(promptlab.create(prompt="  ", backends=[PromptBackend(provider="mock")]))


def test_run_cost():
    assert promptlab.run_cost("local", "qwen", {"prompt_tokens": 10}) == 0.0
    assert promptlab.run_cost("gemini", "모르는-모델", {"prompt_tokens": 10}) is None
    p = usage.prices()[0]
    got = promptlab.run_cost("gemini", p.model, {"prompt_tokens": 1000, "completion_tokens": 100, "thought_tokens": 100})
    assert got == pytest.approx(usage.cost(usage.rate(p.model), 1000, 200))


def test_room(home, monkeypatch):
    monkeypatch.setattr(promptlab, "MAX_TRIALS", 1)
    s = promptlab.create(prompt="요청", backends=[PromptBackend(provider="mock")])
    promptlab.add_trial(s, "", "요청", None, [])
    with pytest.raises(ValueError, match="1개까지"):
        promptlab.run(s)


def test_web_flow(client):
    s = client.post("/api/promptlab", json={"prompt": "요청", "backends": [{"provider": "mock"}]}).json()
    home = client.get("/api/promptlab").json()
    assert [x["id"] for x in home["sessions"]] == [s["id"]] and home["providers"] == ["gemini", "local", "mock"]
    r = client.post(f"/api/promptlab/{s['id']}/run", json={"title": "", "system": "넌 작가", "prompt": "한 문단", "backends": [{"provider": "mock"}]})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["prompt"] == "한 문단" and v["title"] == "한 문단"  # 받은 칸을 먼저 저장한다
    assert len(v["trials"]) == 1 and v["trials"][0]["system"] == "넌 작가" and v["trials"][0]["runs"][0]["ok"]
    v = client.put(f"/api/promptlab/{s['id']}/trials/1", json={"star": True}).json()
    assert v["trials"][0]["star"] and v["summary"]["stars"] == 1
    client.put(f"/api/promptlab/{s['id']}", json={"prompt": "바꾼 요청", "backends": [{"provider": "mock"}]})
    v = client.post(f"/api/promptlab/{s['id']}/trials/1/restore").json()
    assert v["prompt"] == "한 문단"
    d = client.post(f"/api/promptlab/{s['id']}/duplicate").json()
    assert d["id"] != s["id"] and d["trials"] == [] and d["prompt"] == "한 문단"
    assert client.delete(f"/api/promptlab/{s['id']}/trials/9").status_code == 404
    assert client.post("/api/promptlab", json={"backends": [{"provider": "nope"}]}).status_code == 400
    assert client.delete(f"/api/promptlab/{s['id']}").json() == {"ok": True}
    assert client.get(f"/api/promptlab/{s['id']}").status_code == 404
