"""문체 분석이 빈 칸 많은 프로필을 받으면 한 번 다시 묻는다 (canon#595). 실행: python -m pytest tests/test_style_blanks.py"""
import logging
import time

from canon import cli, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import StyleProfile

from .test_library import SAMPLE
from .test_plot_chat import _project


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


# ---------- 남은 빈 칸을 화면 · 명령줄에 보이기 ----------

def test_full_returns_remaining_blanks():
    prof, blanks = pipeline.analyze_style_full(MockLLM(), SAMPLE + "\nMOCK_STYLE_BLANK_ALWAYS")
    assert len(blanks) > pipeline.STYLE_BLANK_MAX
    assert blanks == pipeline.style_blanks(prof)
    assert pipeline.analyze_style_full(MockLLM(), SAMPLE)[1] == []
    assert pipeline.analyze_style_full(MockLLM(), SAMPLE + "\nMOCK_STYLE_BLANK")[1] == []


def _wait_job(client, jid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않았어요")


def test_style_job_result_has_blanks(client):
    _project(client)
    long = SAMPLE * 3
    for text, empty in ((long + "\nMOCK_STYLE_BLANK_ALWAYS", False), (long, True)):
        r = client.post("/api/projects/lh/jobs", json={"kind": "style", "text": text})
        assert r.status_code == 200, r.text
        j = _wait_job(client, r.json()["id"])
        assert j["status"] == "done", j
        assert (j["result"]["blanks"] == []) is empty


def test_lib_style_job_result_has_blanks(client):
    j = client.post("/api/styles/analyze/job", json={"text": SAMPLE * 3 + "\nMOCK_STYLE_BLANK_ALWAYS"}).json()
    end = time.time() + 10
    while time.time() < end:
        cur = next(x for x in client.get("/api/jobs").json() if x["id"] == j["id"])
        if cur["status"] != "running":
            break
        time.sleep(0.02)
    assert cur["status"] == "done" and cur["result"]["blanks"]


def test_cli_blank_line():
    assert cli._style_blank_line(["vocabulary", "sample_passages"]) == "AI가 칸 2개를 비워 두었어요: 어휘, 대표 문단. 다시 분석하거나 직접 채워 주세요."
    assert cli._style_blank_line([]) == ""
