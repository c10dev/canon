"""플레이 모드의 바탕 시험 (mock LLM): 기능별 가짜 응답 등록, play.json 저장, play 단계, 처음 판 프롬프트.
엔진(test_play.py) · 프롬프트 · 무작위 출생 시험은 따로 둔다. 실행: python -m pytest tests"""
from canon import mock, mock_play, prompts, settings, store
from canon.llm import get_llm
from canon.schema import Birth, BirthSketch, PlayInfo, PlayScene, PlayTurn

from .test_restate import _two_done
from .test_web import client  # noqa: F401  (pytest fixture)


def test_mock_responders():
    assert PlayScene in mock.RESPONDERS and BirthSketch in mock.RESPONDERS
    llm = mock.MockLLM()
    s = llm.json("", "", PlayScene, hint={"number": 3, "action": "등대로 간다", "luck": 1})
    assert s.text.startswith("등대로 간다.") and "운이 따랐다" in s.text and s.ending == ""
    assert len(s.choices) == 4 and [c.skip for c in s.choices].count("사흘") == 1
    end = llm.json("", "", PlayScene, hint={"number": 4, "action": f"모든 것을 {mock_play.MOCK_ENDING_WORD}"})
    assert end.ending and end.choices == []
    b = llm.json("", "", BirthSketch, hint={"name": "도윤", "place": "수산시장"})
    assert "도윤" in b.background and "수산시장" in b.opening


def test_play_info_store(client):
    _two_done(client)
    assert store.load_play("lh") is None  # 플레이가 아닌 작품
    info = PlayInfo(world="lh", world_ep=2, player="hero", seed=7, turns=[PlayTurn(number=3, action="", kind="start")])
    store.save_play("lh", info)
    assert store.load_play("lh") == info
    (store.project_dir("lh") / "play.json").write_text("{깨진", encoding="utf-8")
    assert store.load_play("lh") is None
    store.drop_play("lh")
    assert not (store.project_dir("lh") / "play.json").exists()


def test_play_stage(monkeypatch, tmp_path):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    assert "play" in settings.STAGES and settings.STAGE_PARENT["play"] == "write"
    assert get_llm("play").stage == "play"


def test_first_prompts(client):
    _two_done(client)
    p = store.load("lh")
    hero = p.characters[0].id
    text = prompts.play_scene_prompt(p, PlayInfo(world="lh", world_ep=2, player=hero, person="first"), 3, "등대로 간다", -2)
    assert "등대로 간다" in text and "아주 나쁨" in text and "1인칭" in text
    assert text.index("[이번 행동]") > text.index("[직전 장면 마지막 부분]")  # 턴마다 바뀌는 블록이 뒤
    assert prompts.play_state_prompt(p, 2) == prompts.state_prompt(p, 2)
    assert "도윤" in prompts.birth_prompt(p, Birth(seed=1, name="도윤", place="등대"))
