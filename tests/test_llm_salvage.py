"""생각 글이 섞인 JSON 응답 읽기와 다시 요청. 실제 모델은 부르지 않는다."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from canon.llm import POLICY_NOTE, GeminiLLM, SchemaMismatch, _json_objects, _validate, repair_prompt, with_note
from canon.schema import CueSheetDraft, StateDelta, StyleProfile

GOOD = StyleProfile(narration_pov="1인칭", markers=[{"text": "것이었다"}]).model_dump_json()
LEAK = ("Sample passages must NOT contain the devices! Clean passage: { ... } ], -> Done. "
        + "], -> . " * 50 + "Let's generate the JSON directly.```json")


def test_validate_reads_json_after_leaked_thought():
    assert _validate(StyleProfile, LEAK + GOOD + "```").narration_pov == "1인칭"
    assert _validate(StyleProfile, GOOD).markers[0].text == "것이었다"


def test_json_objects_skip_inner_braces_and_keep_order():
    assert _json_objects('글 {"a": {"b": 1}} 글 {"c": 2} { 깨진 }') == ['{"a": {"b": 1}}', '{"c": 2}']
    assert _json_objects(LEAK) == []


def test_validate_takes_the_last_object_that_fits():
    raw = '{"episode": "x"} 생각 ' + StateDelta(episode=2, summary="s").model_dump_json()
    assert _validate(StateDelta, raw).episode == 2
    with pytest.raises(Exception):
        _validate(StateDelta, LEAK)


BROKEN_CUES = ('{"key": "불안", "cadence": "half", "cues": [{"scene": 1, "beat": "문을 연다", "lines": []}, '
               '{"scene": 2, "beat": "묻는다", "lines": [{"speaker": "a", "text": "왜?"}]}],}')  # 끝 쉼표로 바깥 객체가 깨짐


def test_validate_skips_inner_objects_of_a_broken_answer():
    # 바깥 객체가 깨지면 안쪽 큐 객체만 남는다. 칸이 모두 기본값인 CueSheetDraft 가 그것을 큐 0개로 받으면 안 된다
    with pytest.raises(ValidationError):
        _validate(CueSheetDraft, BROKEN_CUES)
    assert len(_validate(CueSheetDraft, BROKEN_CUES.replace("],}", "]}")).cues) == 2


def test_repair_resends_the_first_prompt_when_no_json():
    try:
        _validate(StyleProfile, LEAK)
    except Exception as e:
        err = e
    assert repair_prompt("원래 요청", LEAK, StyleProfile, err) == "원래 요청"  # 생각 글을 다음 요청에 붙이지 않는다
    bad = '{"narration_pov": 3}'
    try:
        _validate(StyleProfile, bad)
    except Exception as e:
        err = e
    assert bad in repair_prompt("원래 요청", bad, StyleProfile, err)


def _gemini(replies, reason="STOP"):
    llm = object.__new__(GeminiLLM)
    asks = []

    def generate(model, contents, config):
        asks.append(contents)
        return SimpleNamespace(text=replies.pop(0), usage_metadata=None, candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=reason))])
    llm.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    llm.model = "gemini-4-argon"
    return llm, asks


def test_gemini_salvages_without_second_call():
    llm, asks = _gemini([LEAK + GOOD])
    assert llm.json("", "원래 요청", StyleProfile).narration_pov == "1인칭" and len(asks) == 1 and llm.last_finish == "STOP"


def test_gemini_repairs_a_broken_answer_instead_of_reading_an_empty_sheet():
    llm, asks = _gemini([BROKEN_CUES, BROKEN_CUES.replace("],}", "]}")])
    assert len(llm.json("", "원래 요청", CueSheetDraft).cues) == 2
    assert len(asks) == 2 and BROKEN_CUES in asks[1]  # 두 번째 요청은 깨진 응답을 붙인 형식 고치기


def test_gemini_retries_plain_prompt_and_names_length_cut():
    llm, asks = _gemini([LEAK, GOOD])
    assert llm.json("", "원래 요청", StyleProfile).narration_pov == "1인칭"
    assert asks == [with_note("원래 요청")] * 2
    llm, _ = _gemini([LEAK, LEAK], reason="MAX_TOKENS")
    with pytest.raises(SchemaMismatch, match="출력 길이 한도"):
        llm.json("", "원래 요청", StyleProfile)


def test_every_request_ends_with_the_policy_note():
    llm, asks = _gemini([GOOD])
    llm.text("", "요청")
    assert asks[0].endswith("\n\n" + POLICY_NOTE) and asks[0].count(POLICY_NOTE) == 1


def test_out_cap_sets_gemini_output_limit_only_inside():
    from canon.llm import out_cap

    llm, _ = _gemini([GOOD, GOOD])
    seen = []
    generate = llm.client.models.generate_content
    llm.client.models.generate_content = lambda model, contents, config: seen.append(config.max_output_tokens) or generate(model, contents, config)
    with out_cap(1000):
        llm.json("", "요청", StyleProfile)
    llm.json("", "요청", StyleProfile)
    assert seen == [1000, None]
