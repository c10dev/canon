"""초반 1~3화 테스트 (mock LLM): 프롬프트 규칙, 초반 지표, 흡입력 판정, 여는 방식 여러 안. 실행: python -m pytest tests"""
from canon import genres, metrics, pipeline, prompts, research, store
from canon.mock import MockLLM
from canon.schema import EpisodePlot, HookItem, HookReport, Meta, Project

from .test_plot_chat import _project
from .test_web import _wait, client  # noqa: F401  (pytest fixture)

TEXT = "문이 부서졌다. 서윤은 등대 계단을 뛰어 올라갔다.\n\n\"오빠, 거기 있어?\"\n\n대답 대신 불빛이 꺼졌다."


def test_opening_rules_only_first_three():
    p = Project(meta=Meta(title="등대", genres=["mystery"], target_episodes=10))
    assert prompts.is_opening(1) and prompts.is_opening(3) and not prompts.is_opening(4)
    one = prompts.opening_rules(p, 1)
    assert "초반 규칙" in one and "1화" in one
    assert "미스터리 · 추리:" in prompts.opening_rules(p, 2)  # 장르 박자
    assert "사건 한가운데" in prompts.opening_rules(p, 1, "in_medias_res")
    assert prompts.opening_rules(p, 4) == ""
    assert prompts.opening_plot_rule(p) in prompts.plot_rules(p, opening=True)
    assert prompts.opening_plot_rule(p) not in prompts.plot_rules(p)
    assert len(genres.opening_beats(p.meta, 1)) >= 1 and genres.opening_beats(p.meta, 4) == []


def test_episode_prompt_has_opening_rules(client):
    _project(client)
    p = store.load("lh")
    first = prompts.episode_prompt(p, 1)
    assert "초반 규칙" in first and "장면으로 시작" in first and "직전 화 마지막 장면" not in first
    assert "초반 규칙" in prompts.episode_prompt(p, 3)
    fourth = prompts.episode_prompt(p, 4)
    assert "초반 규칙" not in fourth and "직전 화 마지막 장면" in fourth
    # 바뀌지 않는 블록이 앞에 그대로 있어 캐시가 맞는다
    assert first.startswith(prompts.static_context(p)) and fourth.startswith(prompts.static_context(p))
    # 플롯 생성은 1~3화를 포함할 때만 초반 규칙을 붙인다
    assert prompts.opening_plot_rule(p) in prompts.plot_prompt(p, 1, 5)
    assert prompts.opening_plot_rule(p) not in prompts.plot_prompt(p, 4, 6)


def test_measure_opening_and_warnings():
    m = metrics.measure_opening(TEXT, ["강서윤", "강도현"], hero="강서윤", lore=["등대"])
    assert m.first_dialogue_at == TEXT.find("\"") and m.hero_at == TEXT.find("서윤")
    assert m.named == ["강서윤"] and m.lore_per_1k == 1.0
    assert metrics.opening_warnings(m, 1, hero="강서윤") == []

    slow = "\n".join(["아주 오래전, 이 세계에서는 마법이 있었다. 사람들은 그 힘을 두려워했고 또 원했다. " * 4] * 30) + "\n\n앞으로 펼쳐질 운명을 그는 아직 알지 못했다."
    w = metrics.opening_warnings(metrics.measure_opening(slow, ["강서윤"], hero="강서윤"), 1, hero="강서윤")
    joined = " ".join(w)
    assert "대사가 한 줄도 없습니다" in joined and "주인공 강서윤의 이름이 나오지 않습니다" in joined
    assert "대사 없이" in joined and "회상" in joined
    assert metrics.measure_opening("", []).chars == 0 and metrics.opening_warnings(metrics.OpeningMetrics(), 1) == []


def test_clean_hook_drops_made_up_quotes():
    rep = HookReport(episode=9, items=[
        HookItem(aspect="첫 문단", score=9, quote="문이 부서졌다."),
        HookItem(aspect="주인공", score=5, quote="본문에 없는 문장"),
        HookItem(aspect="첫 문단", score=1, quote=""),
    ], premise_quote="없는 전제")
    out = pipeline.clean_hook(rep, 1, TEXT)
    assert out.episode == 1 and [i.aspect for i in out.items] == ["첫 문단", "주인공"]
    assert out.items[0].score == 5  # 1~5 로 자른다
    assert out.items[1].score == 1 and out.items[1].quote == "" and "1점" in out.items[1].note
    assert out.premise_quote == "" and out.premise_at == -1 and out.basis == pipeline.text_basis(TEXT)


def test_check_hook_and_stale(client):
    _project(client)
    p = store.load("lh")
    p.episodes[0].text = TEXT
    rep = pipeline.check_hook(MockLLM(), p, 1)
    assert {i.aspect: i.score for i in rep.items}["주인공"] == 1  # mock 이 지어낸 인용
    assert rep.premise_at == 0
    pipeline.apply_hook(p, rep)
    assert not pipeline.hook_stale(p, 1)
    p.episodes[0].text += "\n\n덧붙인 문장."
    assert pipeline.hook_stale(p, 1)
    try:
        pipeline.check_hook(MockLLM(), p, 4)
        raise AssertionError("4화는 판정하지 않는다")
    except ValueError:
        pass


def test_suggest_and_apply_opening(client):
    _project(client)
    p = store.load("lh")
    p.episodes[0].plot.storyline = "past"
    p.episodes[0].plot.pov, p.episodes[0].plot.pov_mode = "ally", "3인칭 제한"
    p.episodes[0].plot.characters = ["ally", "extra"]
    out = pipeline.suggest_openings(MockLLM(), p, 1, ["in_medias_res", "lack_turn", "nope"])
    assert [o.approach for o in out.options] == ["in_medias_res", "lack_turn"]  # 모르는 방식 · 중복은 버린다
    assert all(o.plot.number == 1 and o.plot.storyline == "past" for o in out.options)
    pick = out.options[1].plot
    pipeline.apply_opening(p, 1, pick)
    assert p.episodes[0].plot.opening == "lack_turn 장면" and p.episodes[0].status == "draft"
    # 여는 방식과 상관없는 칸(시점, 서술 방식, 넣어 둔 인물)은 작가가 정한 값을 지킨다
    e = p.episodes[0].plot
    assert (e.pov, e.pov_mode) == ("ally", "3인칭 제한") and e.characters[:2] == ["ally", "extra"]
    try:
        pipeline.apply_opening(p, 1, EpisodePlot(number=2, title="x"))
        raise AssertionError("화 번호가 다르면 막는다")
    except ValueError:
        pass


def test_web_opening_flow(client):
    _project(client)
    ways = client.get("/api/opening/approaches").json()
    assert {w["id"] for w in ways if w["default"]} == set(prompts.DEFAULT_APPROACHES)
    assert client.get("/api/projects/lh/episodes/4/opening").status_code == 400

    # 여는 방식 여러 안 → 고른 안을 플롯으로
    j = _wait(client, client.post("/api/projects/lh/jobs", json={"kind": "openings", "ep": 1}).json()["id"])
    assert j["status"] == "done" and len(j["result"]["options"]) == 3
    plot = j["result"]["options"][0]["plot"]
    p = client.post("/api/projects/lh/episodes/1/opening-plot", json={"plot": plot}).json()
    assert p["episodes"][0]["plot"]["opening"] == plot["opening"]

    # 확정 전에는 여러 안으로 쓰지 않는다
    assert client.post("/api/projects/lh/jobs", json={"kind": "opening_drafts", "ep": 1}).status_code == 400
    client.post("/api/projects/lh/episodes/1/confirm")
    j = _wait(client, client.post("/api/projects/lh/jobs", json={"kind": "opening_drafts", "ep": 1,
                                                                    "approaches": ["in_medias_res", "lack_turn"]}).json()["id"])
    assert j["status"] == "done" and j["result"]["count"] == 2
    c = client.get("/api/projects/lh/episodes/1/opening").json()["compare"]
    assert c["kind"] == "opening" and len(c["drafts"]) == 2

    # 비교본 판정은 비교 폴더에, 본문 판정은 화에 붙는다
    j = _wait(client, client.post("/api/projects/lh/jobs", json={"kind": "hook", "ep": 1, "draft": 2}).json()["id"])
    assert j["status"] == "done"
    c = client.get("/api/projects/lh/episodes/1/opening").json()["compare"]
    assert c["drafts"][1]["hook"] and not c["drafts"][0]["hook"]
    assert client.post("/api/projects/lh/jobs", json={"kind": "hook", "ep": 1}).status_code == 400  # 본문 없음

    client.post("/api/projects/lh/episodes/1/write")
    j = _wait(client, client.post("/api/projects/lh/jobs", json={"kind": "hook", "ep": 1}).json()["id"])
    assert j["status"] == "done"
    o = client.get("/api/projects/lh/episodes/1/opening").json()
    assert o["hook"]["episode"] == 1 and not o["hook_stale"] and o["metrics"]["chars"] > 0


def test_research_opening_compare_hides_until_pick(client):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    p = store.load("lh")
    c = research.run_opening_compare("lh", p, 1, MockLLM(), ["in_medias_res", "premise_first"])
    assert c["kind"] == "opening" and all("backend" not in d or not d["backend"] for d in c["drafts"])
    research.save_compare_hook("lh", 1, 1, HookReport(episode=1))
    # 새 비교를 만들면 앞 판정은 지운다
    c = research.run_opening_compare("lh", p, 1, MockLLM(), ["in_medias_res", "lack_turn", "premise_first"])
    assert len(c["drafts"]) == 3 and not any(d["hook"] for d in c["drafts"])
