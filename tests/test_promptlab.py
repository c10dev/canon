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
    # claude-api 시도의 캐시 쓰기는 사용량 화면처럼 캐시 쓰기 값으로 센다
    tok = {"prompt_tokens": 1_000_000, "completion_tokens": 0, "cached_tokens": 0, "written": 1_000_000, "written_1h": 0}
    assert promptlab.run_cost("claude-api", "claude-opus-5-5", tok) == pytest.approx(4 * 1.25)


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
        system, prompt, schema = prompts.brief_request(p, n, kind)  # 스키마 글은 칸에 넣지 않는다 (돌릴 때 구조화 출력)
        assert s.system == system and s.source.schema_name == (schema.__name__ if schema else "")
        assert prompts.brief_parts(p, n, kind)[1].startswith(prompt.split("새 남자 인물 후보")[0])  # 작업지시서는 스키마 글을 붙인다
        if kind == "plot":  # 플롯 프롬프트는 새 인물 이름 후보를 부를 때마다 무작위로 뽑는다
            assert s.prompt.split("새 남자 인물 후보")[0] == prompt.split("새 남자 인물 후보")[0]
        else:
            assert s.prompt == prompt  # 작업지시서와 같은 조립 (스키마 글만 뺀다)
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
    assert [k["id"] for k in src["kinds"]] == ["setup_chat", "style_chat", "arc", "heat", "plots", "plot", "agent_plot", "storyboard", "cue",
                                              "episode", "passage", "check", "state"]
    assert src["defaults"]["check"] == 2
    assert client.get("/api/promptlab/sources?project=없는작품").status_code == 404
    v = client.post(f"/api/promptlab/{s['id']}/load", json={"kind": "check"}).json()
    assert v["source"]["kind"] == "check" and v["system"] and v["prompt"]
    assert v["title"] == "검수 · 예시 작품 2화"  # 지은 제목은 불러온 이름으로
    v = client.post(f"/api/promptlab/{s['id']}/run", json={"system": v["system"], "prompt": v["prompt"], "backends": [{"provider": "mock"}]}).json()
    assert v["trials"][0]["source"]["label"].startswith("검수") and v["trials"][0]["source_edited"] is False
    assert client.post(f"/api/promptlab/{s['id']}/load", json={"kind": "check", "n": 5}).status_code == 400


class _Seen:
    """MockLLM 을 감싸 json 호출의 (시스템, 요청)을 남긴다."""

    def __init__(self):
        from canon.mock import MockLLM

        self.llm, self.calls = MockLLM(), []

    def __getattr__(self, name):
        return getattr(self.llm, name)

    def json(self, system, prompt, schema, hint=None):
        self.calls.append((system, prompt))
        return self.llm.json(system, prompt, schema, hint=hint)


def _names_out(text):
    """새 인물 이름 · 장소 후보 줄은 부를 때마다 무작위로 뽑으므로 견주기에서 뺀다."""
    return "\n".join(x for x in text.splitlines() if not x.startswith(("- 새 남자 인물 후보", "- 새 여자 인물 후보", "- 장소 후보")))


def _same_as_pipeline(p, kind, n, call):
    """brief_parts 가 pipeline 이 보내는 첫 요청과 같은지 본다. 놀이터 쪽은 응답 스키마 글(## 출력 형식)이 끝에 더 붙는다."""
    from canon import prompts

    seen = _Seen()
    call(seen)
    system, prompt = prompts.brief_parts(p, n, kind)
    assert "\n\n## 출력 형식\n" in prompt
    assert (system, _names_out(prompt.split("\n\n## 출력 형식\n")[0])) == (seen.calls[0][0], _names_out(seen.calls[0][1]))


def test_new_kinds_match_pipeline_short():
    from canon import pipeline

    p = promptlab.example_project()
    for e in p.episodes[:2]:
        e.status = "finalized"
    _same_as_pipeline(p, "plots", 4, lambda llm: pipeline.draft_plots(llm, p, 4, 4))
    _same_as_pipeline(p, "plots", 6, lambda llm: pipeline.draft_plots(llm, p, 5, 6))  # 구간 안 어느 화를 골라도 구간 전체
    _same_as_pipeline(p, "plot", 4, lambda llm: pipeline.draft_episode(llm, p, 4))  # 한 화 플롯은 웹 작업 plot_one 과 같다
    _same_as_pipeline(p, "storyboard", 3, lambda llm: pipeline.make_storyboard(llm, p, 3))
    _same_as_pipeline(p, "cue", 3, lambda llm: pipeline.make_cue_sheet(llm, p, 3))
    _same_as_pipeline(p, "arc", 0, lambda llm: pipeline.plan_arc(llm, p))
    _same_as_pipeline(p, "heat", 0, lambda llm: pipeline.propose_heat(llm, p))
    p.settings.heat_plan = True  # 열 계획을 켠 단편은 구조 요청에 열 계획 규칙이 붙는다
    _same_as_pipeline(p, "arc", 0, lambda llm: pipeline.plan_arc(llm, p))


def test_new_kinds_match_pipeline_serial():
    from canon import pipeline
    from canon.mock import MockLLM

    llm = MockLLM()
    p = promptlab.Project()
    p.meta.title, p.meta.form, p.meta.target_episodes = "탑", "serial", 120
    pipeline.apply_setup(p, pipeline.suggest_setup(llm, p))
    _same_as_pipeline(p, "series", 0, lambda x: pipeline.plan_series(x, p))
    pipeline.apply_series(p, pipeline.plan_series(llm, p))
    _same_as_pipeline(p, "arc", 0, lambda x: pipeline.plan_next_arc(x, p))
    a = pipeline.apply_arc(p, pipeline.plan_next_arc(llm, p))
    _same_as_pipeline(p, "heat", 0, lambda x: pipeline.propose_heat(x, p))
    g = pipeline.act_groups(a.acts)[1]
    _same_as_pipeline(p, "plots", g[1], lambda x: pipeline.draft_plots(x, p, g[1], g[2]))
    p.settings.heat_plan = True
    _same_as_pipeline(p, "arc", 0, lambda x: pipeline.plan_next_arc(x, p))


def test_chat_kinds_match_pipeline():
    """대화로 다듬기 갈래는 작가의 말 자리에 CHAT_MESSAGE 를 넣고 pipeline 의 대화 호출과 같은 글을 조립한다."""
    from canon import pipeline, prompts

    p = promptlab.example_project()
    msg = prompts.CHAT_MESSAGE
    _same_as_pipeline(p, "setup_chat", 0, lambda llm: pipeline.revise_setup(llm, p, msg))
    _same_as_pipeline(p, "style_chat", 0, lambda llm: pipeline.revise_style(llm, p, msg))
    _same_as_pipeline(p, "passage", 2, lambda llm: pipeline.revise_passage(llm, p, 2, prompts.passage_sample(p, 2), msg))
    sel = prompts.passage_sample(p, 2)
    assert sel.text.strip() and p.episode(2).text[sel.start:sel.start + len(sel.text)] == sel.text


def test_agent_plot_kind_is_the_first_step_of_a_new_turn(client):
    """대화 에이전트 갈래는 새 세션 첫 턴에서 run_turn 이 처음 보내는 요청과 같다 (이름 후보 줄은 세션 id 로 뽑아 뺀다)."""
    from canon import agent, prompts, store
    from canon.schema import PlotAgentStep

    from .test_plot_chat import _project

    _project(client)
    p = store.load("lh")
    system, prompt, schema = prompts.brief_request(p, 0, "agent_plot")
    assert schema is PlotAgentStep and system == prompts.SYSTEM_AGENT_PLOT and prompts.CHAT_MESSAGE in prompt
    assert prompt == prompts.brief_request(p, 0, "agent_plot")[1] and not p.agent_sessions  # 불러올 때마다 같고 작품에 세션을 붙이지 않는다
    s = agent.new_session(p, "plot")
    t = agent.add_turn(p, s.id, prompts.CHAT_MESSAGE)
    store.save("lh", p)
    seen = []

    class Fake:
        def json(self, system, prompt, schema, hint=None):
            seen.append((system, prompt))
            return PlotAgentStep(reply="그대로 둘게요")

    agent.run_turn(Fake(), "lh", s.id, t)
    assert (system, _names_out(prompt)) == (seen[0][0], _names_out(seen[0][1]))


def test_chat_kinds_run_like_their_stage(home):
    s = promptlab.create(backends=[PromptBackend(provider="mock")])
    promptlab.load_prompt(s, "agent_plot")
    spec = promptlab.view(s)["spec"]
    assert (spec["schema"], spec["stage"], spec["stage_label"], spec["out_tokens"]) == ("PlotAgentStep", "chat", "플롯 대화", 16384)
    promptlab.load_prompt(s, "passage")
    spec = promptlab.view(s)["spec"]
    assert s.source.n == 2 and (spec["schema"], spec["stage_label"], spec["out_tokens"]) == ("PassageRevision", "부분 수정", 0)
    with pytest.raises(ValueError, match="본문이 없어"):
        promptlab.load_prompt(s, "passage", n=4)
    for kind, schema in (("setup_chat", "SetupRevision"), ("style_chat", "StyleRevision")):
        promptlab.load_prompt(s, kind)
        assert s.source.n == 0 and s.source.schema_name == schema and s.source.stage == "plan"
    assert promptlab.run(s)[0].ok


def test_new_kinds_sources_and_guards(home, monkeypatch, tmp_path):
    from canon import store

    info = promptlab.sources()
    ids = [k["id"] for k in info["kinds"]]
    assert ids == ["setup_chat", "style_chat", "arc", "heat", "plots", "plot", "agent_plot", "storyboard", "cue", "episode", "passage", "check",
                   "state"]  # 단편에는 부 구성이 없다
    assert {k["id"]: k["scope"] for k in info["kinds"]}["heat"] == "work" and info["defaults"]["arc"] == 0
    assert [g["n"] for g in info["groups"]] == [1, 2, 4, 5] and info["groups"][0]["label"] == "기 구간 1화"
    assert info["defaults"]["plots"] == 4  # 초안이 든 첫 구간
    assert [e["confirmed"] for e in info["episodes"]] == [True, True, True, False, False, False]
    s = promptlab.create(backends=[PromptBackend(provider="mock")])
    promptlab.load_prompt(s, "arc")
    assert s.source.label == "기승전결 구조 · 예시 작품" and s.source.n == 0
    promptlab.load_prompt(s, "plots", n=6)
    assert s.source.label == "플롯 초안 · 예시 작품 5~6화"
    assert s.title == s.source.label  # 앞서 불러온 이름으로 지은 제목은 다음 불러오기 이름으로 바뀐다
    s.title = "내 제목"
    promptlab.load_prompt(s, "arc")
    assert s.title == "내 제목"
    with pytest.raises(ValueError, match="확정하지 않아"):
        promptlab.load_prompt(s, "storyboard", n=4)
    with pytest.raises(ValueError, match="초안인 화를 고르세요"):
        promptlab.load_prompt(s, "plot", n=3)
    with pytest.raises(ValueError, match="장편 연재"):
        promptlab.load_prompt(s, "series")
    monkeypatch.setattr(store, "ROOT", tmp_path / "projects")
    q = promptlab.example_project()
    q.episodes = q.episodes[:2]  # 3화 플롯이 없는 작품: 스토리보드 기본 화는 확정한 화 가운데 본문이 없는 화가 없으니 마지막 확정 화
    store.save("짧은작품", q)
    d = promptlab.sources("짧은작품")["defaults"]
    assert d["storyboard"] == 2 and d["plots"] == 1 and d["check"] == 2


def test_policy_note_is_shown_not_put_in_the_prompt(home):
    from canon import llm

    assert promptlab.limits()["policy_note"] == llm.POLICY_NOTE
    s = promptlab.create(backends=[PromptBackend(provider="mock")])
    promptlab.load_prompt(s, "episode")
    assert llm.POLICY_NOTE not in s.prompt  # 백엔드가 보낼 때 붙인다. 칸에 넣으면 두 번 붙는다


def _fake_gemini(monkeypatch, answer):
    """research.GeminiLLM 을 보낸 config 를 남기는 가짜로 바꾼다."""
    from types import SimpleNamespace

    from canon import research
    from canon.llm import GeminiLLM

    seen = []

    def generate(model, contents, config):
        seen.append({"model": model, "config": config, "contents": contents})
        u = SimpleNamespace(prompt_token_count=1, candidates_token_count=1, thoughts_token_count=0, cached_content_token_count=0)
        return SimpleNamespace(text=answer, usage_metadata=u, candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))])

    def fake(model=None, effort="", temperature=None, **kw):
        llm = object.__new__(GeminiLLM)
        llm.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        llm.model, llm.effort, llm.temperature = model or "gemini-4-argon", effort, temperature
        return llm

    monkeypatch.setattr(research, "GeminiLLM", fake)
    return seen


def test_run_uses_structured_output_stage_and_cap(home, monkeypatch):
    """불러온 갈래는 실제 호출처럼 구조화 출력 · 그 단계의 모델과 추론 강도 · 출력 한도로 돌린다."""
    from canon import llm, settings

    monkeypatch.setenv("CANON_LLM", "gemini")
    monkeypatch.setenv("CANON_MODEL_BOARD", "gemini-board-model")
    monkeypatch.setenv("CANON_EFFORT_BOARD", "xhigh")
    seen = _fake_gemini(monkeypatch, '{"scenes": []}')
    assert settings.stage_model("board")[0] == "gemini-board-model"
    s = promptlab.create(backends=[PromptBackend(provider="gemini"), PromptBackend(provider="gemini", model="내 모델")])
    promptlab.load_prompt(s, "storyboard")
    assert "## 출력 형식" not in s.prompt and s.source.schema_name == "StoryboardDraft" and s.source.stage == "board"
    spec = promptlab.view(s)["spec"]
    assert spec["schema"] == "StoryboardDraft" and spec["out_tokens"] == 16384 and spec["stage_label"] == "스토리보드 · 큐 시트"
    assert spec["backends"] == [{"model": "gemini-board-model", "effort": "high"}, {"model": "내 모델", "effort": "high"}]
    runs = promptlab.run(s)
    assert [r.model for r in runs] == ["gemini-board-model", "내 모델"] and all(r.ok for r in runs)
    assert runs[0].schema_name == "StoryboardDraft" and runs[0].out_tokens == 16384 and runs[0].effort == "high"
    cfg = seen[0]["config"]
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema["title"] == "StoryboardDraft"
    assert cfg.max_output_tokens == 16384 and cfg.thinking_config.thinking_level.name.lower() == "high"
    assert seen[0]["contents"].endswith(llm.POLICY_NOTE)  # 정책 줄은 보낼 때 한 번 붙는다
    promptlab.load_prompt(s, "episode")  # 본문 쓰기는 글로 받고 기본 한도
    seen.clear()
    runs = promptlab.run(s)
    assert runs[0].schema_name == "" and runs[0].out_tokens == 0
    assert seen[0]["config"].response_mime_type is None and not seen[0]["config"].max_output_tokens


def test_run_without_source_or_with_mock_stays_text(home):
    s = promptlab.create(prompt="그냥 요청", backends=[PromptBackend(provider="mock")])
    assert promptlab.view(s)["spec"] == {"schema": "", "stage": "", "stage_label": "", "out_tokens": 0, "backends": []}
    assert promptlab.run(s)[0].schema_name == ""
    promptlab.load_prompt(s, "check")
    r = promptlab.run(s)[0]
    assert r.ok and r.schema_name == ""  # mock 은 hint 없이 스키마 응답을 짓지 못해 글로 받는다


def test_failed_structured_run_keeps_raw(home, monkeypatch):
    """형식이 어긋난 응답은 형식 고치기를 한 번 더 묻고, 그래도 실패하면 마지막 원문과 끝난 이유를 남긴다."""
    monkeypatch.setenv("CANON_LLM", "gemini")
    seen = _fake_gemini(monkeypatch, "JSON 이 아닌 답")
    s = promptlab.create(backends=[PromptBackend(provider="gemini")])
    promptlab.load_prompt(s, "storyboard")
    r = promptlab.run(s)[0]
    assert not r.ok and r.raw == "JSON 이 아닌 답" and r.finish == "STOP" and len(seen) == 2
    assert promptlab.add_trial(s, s.system, s.prompt, None, [r]).runs[0].raw == "JSON 이 아닌 답"


def test_structured_run_is_checked_like_canon(home, monkeypatch):
    """구조화 출력 결과의 빈 칸 수와, 실제 경로라면 Canon 이 정리하거나 거절하는 것을 적는다."""
    import json

    monkeypatch.setenv("CANON_LLM", "gemini")
    scene = {"place": "등대", "spot": "계단", "goal": "열쇠를 찾는다", "turn": "", "end_state": "문이 열린다"}
    _fake_gemini(monkeypatch, json.dumps({"scenes": [scene, {"place": "", "spot": "", "goal": "", "turn": "", "end_state": ""}]}))
    s = promptlab.create(backends=[PromptBackend(provider="gemini")])
    promptlab.load_prompt(s, "storyboard")
    r = promptlab.run(s)[0]
    assert r.ok and r.notes == ["빈 장면 1개는 Canon이 빼요"]
    assert r.empty_count > 0 and "scenes[0].turn" in r.empty
    from canon.schema import PlotBatch

    other = promptlab.example_project().episode(5).plot.model_copy(update={"number": 9})
    _fake_gemini(monkeypatch, PlotBatch(episodes=[other]).model_dump_json())
    promptlab.load_prompt(s, "plots", n=5)
    r = promptlab.run(s)[0]
    assert r.ok and r.notes == ["요청한 화(5~6화)와 받은 화([9])가 달라 Canon은 받지 않아요"]
    _fake_gemini(monkeypatch, json.dumps({"scenes": []}))
    promptlab.load_prompt(s, "storyboard")
    assert "장면이 하나도 없어" in promptlab.run(s)[0].notes[0]
