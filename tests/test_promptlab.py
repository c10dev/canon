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


def test_load_prompt_from_example_uses_brief_parts(home):
    from canon import prompts

    s = promptlab.create(prompt="손으로 쓴 요청", backends=[PromptBackend(provider="mock")])
    for kind, n in promptlab.EXAMPLE_N.items():
        promptlab.load_prompt(s, kind)
        p = promptlab.example_project()
        system, prompt = prompts.brief_parts(p, n, kind)
        assert s.system == system
        if kind == "plot":  # 플롯 프롬프트는 새 인물 이름 후보를 부를 때마다 무작위로 뽑는다
            assert s.prompt.split("새 남자 인물 후보")[0] == prompt.split("새 남자 인물 후보")[0]
        else:
            assert s.prompt == prompt  # 작업지시서와 같은 조립
        assert s.source.kind == kind and s.source.n == n and s.source.project == "" and "예시 작품" in s.source.label
    assert prompts.brief_parts(p, 2, "check")[1] in prompts.check_brief(p, 2)
    t = promptlab.add_trial(s, s.system, s.prompt, None, [], s.source)
    assert t.source.kind == "state" and not t.source_edited
    t2 = promptlab.add_trial(s, s.system, s.prompt + " 고침", None, [], s.source)
    assert t2.source_edited
    assert promptlab.view(s)["source_edited"] is False
    s.prompt += "!"
    assert promptlab.view(s)["source_edited"] is True
    with pytest.raises(ValueError, match="본문이 없어"):
        promptlab.load_prompt(s, "check", n=4)
    with pytest.raises(ValueError, match="모르는 프롬프트"):
        promptlab.load_prompt(s, "nope")
    with pytest.raises(KeyError):
        promptlab.load_prompt(s, "episode", project="../x")


def test_load_prompt_from_a_work_reads_only(home, monkeypatch, tmp_path):
    from canon import store

    monkeypatch.setattr(store, "ROOT", tmp_path / "projects")
    p = promptlab.example_project()
    store.save("내작품", p)
    before = (store.project_dir("내작품") / "project.json").read_text(encoding="utf-8")
    src = promptlab.sources("내작품")
    assert src["defaults"]["check"] == 2 and src["defaults"]["episode"] == 3
    s = promptlab.create(backends=[PromptBackend(provider="mock")])
    promptlab.load_prompt(s, "check", project="내작품")
    assert s.source.project == "내작품" and s.source.n == 2
    assert (store.project_dir("내작품") / "project.json").read_text(encoding="utf-8") == before  # 작품은 바꾸지 않는다


def test_gemini_gets_temperature_only_when_set(monkeypatch):
    from types import SimpleNamespace

    from canon import research
    from canon.llm import GeminiLLM

    seen = []

    def generate(model, contents, config):
        seen.append(config)
        u = SimpleNamespace(prompt_token_count=1, candidates_token_count=1, thoughts_token_count=0, cached_content_token_count=0)
        return SimpleNamespace(text="답", usage_metadata=u, candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))])

    def fake(model=None, temperature=None, **kw):
        llm = object.__new__(GeminiLLM)
        llm.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        llm.model, llm.temperature = "gemini-4-argon", temperature
        return llm

    monkeypatch.setattr(research, "GeminiLLM", fake)
    research.make_backend(research.Backend(provider="gemini"), 0.4).text("", "요청")
    research.make_backend(research.Backend(provider="gemini")).text("", "요청")
    assert seen[0].temperature == 0.4 and seen[1].temperature is None


def test_web_load(client):
    s = client.post("/api/promptlab", json={"backends": [{"provider": "mock"}]}).json()
    src = client.get("/api/promptlab/sources").json()
    assert [k["id"] for k in src["kinds"]] == ["episode", "plot", "check", "state"] and src["defaults"]["check"] == 2
    assert client.get("/api/promptlab/sources?project=없는작품").status_code == 404
    v = client.post(f"/api/promptlab/{s['id']}/load", json={"kind": "check"}).json()
    assert v["source"]["kind"] == "check" and v["system"] and v["prompt"]
    assert v["title"] == "검수 · 예시 작품 2화"  # 지은 제목은 불러온 이름으로
    v = client.post(f"/api/promptlab/{s['id']}/run", json={"system": v["system"], "prompt": v["prompt"], "backends": [{"provider": "mock"}]}).json()
    assert v["trials"][0]["source"]["label"].startswith("검수") and v["trials"][0]["source_edited"] is False
    assert client.post(f"/api/promptlab/{s['id']}/load", json={"kind": "check", "n": 5}).status_code == 400
