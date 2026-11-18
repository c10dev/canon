"""문체 분석이 빈 칸 많은 프로필을 받으면 한 번 다시 묻는다 (canon#595). 실행: python -m pytest tests/test_style_blanks.py"""
import logging

from canon import pipeline, prompts
from canon.mock import MockLLM
from canon.schema import StyleProfile

from .test_library import SAMPLE


class _Spy:
    """MockLLM 을 감싸 json 호출의 프롬프트를 모은다."""

    def __init__(self):
        self.inner = MockLLM()
        self.prompts: list[str] = []

    def json(self, system, prompt, schema, *a, **k):
        self.prompts.append(prompt)
        return self.inner.json(system, prompt, schema, *a, **k)


def test_mock_default_profile_has_no_blanks():
    prof = MockLLM().json(prompts.SYSTEM_PLANNER, prompts.style_prompt(SAMPLE), StyleProfile)
    assert pipeline.style_blanks(prof, passages=True) == []


def test_style_blanks_counts():
    empty = StyleProfile()
    blanks = pipeline.style_blanks(empty, passages=True)
    assert len(blanks) == 15
    assert len(pipeline.style_blanks(empty, passages=False)) == 14
    assert "devices" not in blanks and "banned_phrases" not in blanks
    assert pipeline.style_blanks(StyleProfile(vocabulary="  \n")).count("vocabulary") == 1


def test_blank_response_is_asked_again(caplog):
    spy = _Spy()
    with caplog.at_level(logging.WARNING, logger="canon"):
        prof = pipeline.analyze_style(spy, SAMPLE + "\nMOCK_STYLE_BLANK")
    assert len(pipeline.style_blanks(prof)) <= pipeline.STYLE_BLANK_MAX
    assert len(spy.prompts) == 2
    first_blanks = pipeline.style_blanks(
        spy.inner.json(prompts.SYSTEM_PLANNER, spy.prompts[0], StyleProfile))
    assert "vocabulary" in first_blanks
    assert spy.prompts[1].endswith(prompts.style_blank_retry(first_blanks))
    assert "vocabulary" in spy.prompts[1].rsplit("앞 응답에서 ", 1)[1]
    assert not [r for r in caplog.records if r.name == "canon" and r.levelno == logging.WARNING]


def test_few_blanks_are_not_asked_again():
    spy = _Spy()
    pipeline.analyze_style(spy, SAMPLE)
    assert len(spy.prompts) == 1


def test_persistent_blanks_warn(caplog):
    spy = _Spy()
    with caplog.at_level(logging.WARNING, logger="canon"):
        prof = pipeline.analyze_style(spy, SAMPLE + "\nMOCK_STYLE_BLANK_ALWAYS")
    assert prof.narration_pov
    assert len(spy.prompts) == 2
    warns = [r for r in caplog.records if r.name == "canon" and r.levelno == logging.WARNING and "빈 칸" in r.getMessage()]
    assert len(warns) == 1
    assert str(len(pipeline.style_blanks(prof))) in warns[0].getMessage()


def test_retry_off_keeps_first_response(caplog):
    spy = _Spy()
    with caplog.at_level(logging.WARNING, logger="canon"):
        prof = pipeline.analyze_style(spy, SAMPLE + "\nMOCK_STYLE_BLANK", retry=False)
    assert len(spy.prompts) == 1
    assert "vocabulary" in pipeline.style_blanks(prof)
    assert not [r for r in caplog.records if r.name == "canon" and r.levelno == logging.WARNING]
