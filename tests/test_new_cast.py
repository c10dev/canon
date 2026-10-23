"""플롯이 데려온 새 인물 후보 테스트 (mock LLM). 실행: python -m pytest tests"""
from canon import pipeline, prompts
from canon.mock import NEW_CAST, NEW_CAST_EP
from canon.schema import Character, EpisodePlot, PlotBatch, Project

from .test_plot_chat import _last, _project
from .test_web import client  # noqa: F401  (pytest fixture)


def _ids(xs):
    return [x["id"] for x in xs]


def test_plot_draft_brings_candidate_not_character(client):
    p = _project(client)
    assert NEW_CAST.id in p["episodes"][NEW_CAST_EP - 1]["plot"]["characters"]
    assert _ids(p["cast_candidates"]) == [NEW_CAST.id]
    assert NEW_CAST.id not in _ids(p["characters"])  # AI 제안은 바로 인물 설정에 들어가지 않는다
    assert p["cast_candidates"][0]["tier"] == "minor"


def test_confirm_registers_candidate_with_first_ep(client):
    _project(client)
    p = client.post("/api/projects/lh/episodes/1/confirm").json()
    assert p["cast_candidates"] and NEW_CAST.id not in _ids(p["characters"])  # 다른 화의 후보는 그대로
    p = client.post(f"/api/projects/lh/episodes/{NEW_CAST_EP}/confirm").json()
    c = next(c for c in p["characters"] if c["id"] == NEW_CAST.id)
    assert (c["tier"], c["first_ep"]) == ("minor", NEW_CAST_EP)
    assert not p["cast_candidates"]
    assert NEW_CAST.id in [s["character_id"] for s in p["states"]]  # 등록되면 상태도 추적한다


def test_removing_from_plot_drops_candidate_and_screen_keeps_job_candidates(client):
    p = _project(client)
    stale = {**p, "cast_candidates": []}  # 플롯 작업 전에 연 화면이 저장해도 작업이 더한 후보는 지킨다
    p = client.put("/api/projects/lh", json=stale).json()
    assert _ids(p["cast_candidates"]) == [NEW_CAST.id]
    plot = p["episodes"][NEW_CAST_EP - 1]["plot"]
    plot["characters"] = [x for x in plot["characters"] if x != NEW_CAST.id]
    p = client.put("/api/projects/lh", json=p).json()
    assert not p["cast_candidates"]  # 어느 플롯에도 안 나오면 후보에서 빠진다


def test_redrafting_keeps_existing_candidate_and_skips_known():
    p = Project()
    p.characters = [Character(id="hero", name="서윤", role="주인공")]
    p.episodes = []
    first = Character(id="guard", name="문지기", role="문지기", tier="minor")
    plots = [EpisodePlot(number=1, act="기", title="", summary="", events=[], characters=["hero", "guard", "ghost"],
                         emotional_shift="", ending_hook="")]
    hero_again = Character(id="hero", name="딴사람", role="주인공")
    unused = Character(id="nobody", name="안나옴", role="행인")
    pipeline.apply_plots(p, PlotBatch(episodes=plots, new_characters=[first, hero_again, unused]))
    assert [c.id for c in p.cast_candidates] == ["guard"]  # 있는 인물과 플롯에 안 나오는 인물은 뺀다
    again = first.model_copy(update={"name": "다른 이름", "tier": "main"})
    pipeline.apply_plots(p, PlotBatch(episodes=[plots[0].model_copy(deep=True)], new_characters=[again]))
    assert p.cast_candidates[0].name == "문지기"  # 앞 플롯이 쓰던 후보를 바꾸지 않는다
    assert pipeline.register_candidates(p, ["guard"]) == ["guard"]
    assert p.characters[-1].first_ep == 1 and not p.cast_candidates
    assert "ghost" in p.episodes[0].plot.characters  # 설정 없는 id 는 그대로 두고 편집기가 '미등록'으로 보여 준다


def test_chat_new_character_is_demoted_and_added_on_apply(client):
    _project(client)
    p = client.post("/api/projects/lh/chat/plot", json={"message": "4화에 새 인물 넣어 줘"}).json()
    i, m = _last(p)
    new = m["revision"]["new_characters"]
    assert _ids(new) == ["courier"] and new[0]["tier"] == "support"  # 주역은 작가가 정한다
    assert "courier" not in _ids(p["cast_candidates"])  # 반영 전에는 후보도 아니다
    p = client.post(f"/api/projects/lh/chat/plot/{i}/apply", json={"episodes": [4]}).json()
    assert "courier" in _ids(p["cast_candidates"])
    assert "courier" in p["episodes"][3]["plot"]["characters"]


def test_prompts_show_candidates_and_rule(client):
    _project(client)
    from canon import store
    p = store.load("lh")
    text = prompts.plot_prompt(p, 3, 4)
    assert "[새 인물 후보" in text and NEW_CAST.name in text
    assert "new_characters" in text and "[이름 후보]" in text
    assert "new_characters" in prompts.plot_chat_prompt(p, "3화 바꿔 줘")
    assert "new_characters" not in prompts.plot_rules(p)  # 영향 분석 · 여는 방식처럼 칸이 없는 곳에는 붙이지 않는다
