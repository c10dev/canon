"""서술 문장 끝 지표(metrics._endings)와 쓰기 요청의 끝 섞기 줄(prompts.ending_line).

    CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_endings.py
"""
import os
import tempfile

os.environ.setdefault("CANON_LLM", "mock")
os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())

from canon import metrics, prompts  # noqa: E402
from canon.schema import Character, Episode, EpisodePlot, Project  # noqa: E402


def _lines(*parts: str) -> str:
    return "\n\n".join(parts)


DA = [f"나는 {k}번째 문을 열었다." for k in range(40)]
MIXED = [("물이 식었다." if k % 2 else "식어 가는 물…") for k in range(40)]


def test_all_da_is_one_long_run():
    m = metrics.measure(_lines(*DA))
    assert m.da_ending_ratio == 1.0
    assert m.da_run_ratio == 1.0


def test_dialogue_line_breaks_run_and_is_not_counted():
    parts = []
    for k in range(40):
        parts.append(DA[k])
        if k % 4 == 3:
            parts.append("“가자.”")
    m = metrics.measure(_lines(*parts))
    assert m.da_ending_ratio == 1.0  # 대사는 세지 않는다
    assert m.da_run_ratio == 0.0     # 넷마다 대사가 끼어 다섯 줄 덩어리가 없다


def test_other_endings_count():
    m = metrics.measure(_lines(*MIXED))
    assert m.da_ending_ratio == 0.5
    assert m.da_run_ratio == 0.0


def test_da_with_ellipsis_or_mark_is_not_da():
    assert metrics._da_end("물이 식었다.")
    assert metrics._da_end("물이 식었다")
    assert not metrics._da_end("물이 식었다…")
    assert not metrics._da_end("물이 식었다!")
    assert not metrics._da_end("왜 식었지?")


def test_short_text_is_not_measured():
    m = metrics.measure(_lines(*DA[:10]))
    assert m.da_ending_ratio is None and m.da_run_ratio is None


def test_drift_uses_default_when_base_has_none():
    base = metrics.measure(_lines(*DA[:10]))  # 서술이 모자라 기준이 비었다
    warns = metrics.drift(base, metrics.measure(_lines(*DA)))
    assert any(w.startswith("'~다.' 끝 서술 비율: 기준 0.56") for w in warns)
    assert any(w.startswith("'~다.' 다섯 줄 이상") for w in warns)


def test_drift_does_not_warn_when_lower():
    base = metrics.measure(_lines(*DA))
    warns = metrics.drift(base, metrics.measure(_lines(*MIXED)))
    assert not any(w.startswith("'~다.'") for w in warns)


def test_old_baseline_reads_without_fields():
    m = metrics.StyleMetrics.model_validate({"chars": 10, "past_tense_ratio": 0.9})
    assert m.da_ending_ratio is None and m.da_run_ratio is None


def _project(samples: list[str], voice: str = "") -> Project:
    p = Project()
    p.characters = [Character(id="hero", name="엘렌", role="주인공", narration_voice=voice)]
    p.episodes = [Episode(plot=EpisodePlot(number=1, act="기", title="t", summary="s", events=[], characters=["hero"],
                                           emotional_shift="", ending_hook="h", pov="hero" if voice else ""))]
    p.style.sample_passages = samples
    return p


def test_ending_line_default_share():
    line = prompts.ending_line(_project([]), 1)
    assert "열에 여섯쯤만 '~다.'로" in line
    assert "현재형" not in line          # 기준이 없으면 시제는 건드리지 않는다
    assert "네 줄 넘게 잇지 않습니다" in line


def test_ending_line_follows_baseline_and_clips():
    p = _project([])
    p.style_baseline = metrics.StyleMetrics(chars=9000, da_ending_ratio=0.9, past_tense_ratio=0.95)
    assert "열에 일곱쯤만" in prompts.ending_line(p, 1)  # 사람 범위 위는 잘라 둔다
    p.style_baseline = metrics.StyleMetrics(chars=9000, da_ending_ratio=0.3, past_tense_ratio=0.5)
    line = prompts.ending_line(p, 1)
    assert "열에 다섯쯤만" in line
    assert "열에 셋쯤은 '~한다'" in line  # 현재형 몫은 셋까지만


def test_ending_line_skipped_for_narration_voice():
    assert prompts.ending_line(_project([], voice="해요체로 서술한다"), 1) == ""


def test_episode_prompt_ends_with_line_without_cue_sheet():
    p = _project([])
    p.episodes[0].status = "confirmed"
    assert prompts.episode_prompt(p, 1).endswith(prompts.ending_line(p, 1))
