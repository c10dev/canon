"""감정의 두 층(겉 · 속, 머리 · 몸) 테스트 (mock LLM): 라벨 찾기, 상태 변경안 규칙, 검수 규칙. 실행: python -m pytest tests"""
from canon import prompts
from canon.schema import CharacterState

from .test_serial import _plan_arc, _serial
from .test_storylines import _short
from .test_timeline import _play

MASK = "겉: 다정하게 웃음 / 속: 서준을 경계"


def test_layer_label():
    states = [CharacterState(character_id="a", emotional_state=MASK),
              CharacterState(character_id="b", emotional_state="머리：거절해야 함 /몸: 끌려 흔들림"),
              CharacterState(character_id="c", emotional_state="불안하면서도 기대함"),
              CharacterState(character_id="d", emotional_state="속: 경계")]
    assert prompts.layered(states) == ["a", "b"]


def test_state_rule_always():
    p = _short(8)
    assert prompts.LAYER_STATE_RULE in prompts.state_prompt(p, 1)
    assert prompts.LAYER_STATE_RULE in prompts.state_brief(p, 1)  # 작업지시서도 같은 프롬프트
    s = _serial(40)
    _plan_arc(s)
    assert prompts.LAYER_STATE_RULE in prompts.state_prompt(s, 1)


def test_check_rule_only_when_layered():
    p = _play(_short(8), 1, 2)
    assert "- 겉과 속:" not in prompts.check_prompt(p, 3)
    p.state_of("hero").emotional_state = MASK
    check = prompts.check_prompt(p, 3)
    assert "- 겉과 속:" in check and MASK in check  # 규칙이 가리키는 라벨이 자료에 있다


def test_check_rule_follows_check_cast():
    p = _play(_short(8), 1, 1)
    p.state_of("hero").emotional_state = MASK
    assert prompts.layer_check_rule(p, {"hero"}) and prompts.layer_check_rule(p)
    assert prompts.layer_check_rule(p, {"someone-else"}) == ""  # 검수에 넣지 않는 인물의 라벨로는 붙이지 않는다


def test_serial_budget_check():
    p = _serial(40)
    _plan_arc(p)
    e = p.episode(1)
    e.text, e.status = "본문", "written"
    who = sorted(prompts.check_cast(p, 1))[0]
    p.states = [CharacterState(character_id=who, emotional_state="머리: 거절해야 함 / 몸: 끌려 흔들림")]
    assert "- 겉과 속:" in prompts.check_prompt(p, 1)
