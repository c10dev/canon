"""효과음 줄(소리나 몸짓만 적은 한 줄 문단)을 재고 지킨다. 실행: python -m pytest tests/test_sfx.py"""
import re
from pathlib import Path

from canon import metrics, pipeline, prompts
from canon.schema import StyleEdit, StyleProfile

TEXT = """문이 열렸다.

콰앙-!

문짝이 벽에 부딪혀 튕겨 나왔다.

터벅, 터벅.

"누구야?"

툭.

그가 가방을 내려놓았다."""


def test_is_sfx_line_accepts_sounds_and_gestures():
    for line in ["콰앙-!", "터벅, 터벅.", "─찌걱, 찌걱…!", "움찔.", "쿵, 쿵, 쿵!", "솨아아아아-!", "톡. 톡.", "스윽", "-띠링띠링."]:
        assert metrics.is_sfx_line(line), line


def test_is_sfx_line_rejects_narration_dialogue_and_words():
    for line in ["그때였다.", "하지만.", "부장님.", "\"쾅!\"", "뭐지?", "대형 배수구.", "-여보세요.", "진짜였다.", "통했다…!",
                 "문이 쾅 닫혔다.", "", "끼익 소리와 함께 문이 열리고 그가 들어왔다."]:
        assert not metrics.is_sfx_line(line), line


def test_sfx_mark_reads_end_marks():
    assert [metrics.sfx_mark(x) for x in ["콰앙-!", "지잉-", "뚝…뚝…", "쾅!", "툭.", "쿠웅,", "스윽"]] == ["-!", "-", "…", "!", ".", ",", "없음"]


def test_measure_counts_sfx_and_sound_word():
    m = metrics.measure(TEXT + "\n\n소리가 났다. 그는 소리쳤다. 목소리가 떨렸다.")
    assert m.sfx_per_1k == round(3 * 1000 / m.chars, 2)
    assert m.sfx_marks == {".": 0.67, "-!": 0.33}
    assert m.sound_word_per_1k == round(1 * 1000 / m.chars, 2)  # '소리쳤다' · '목소리'는 세지 않는다
    assert metrics.measure("짧다.").sfx_marks == {}  # SFX_MARK_MIN 줄 미만


def test_drift_warns_on_new_sfx_mark_not_sound_word():
    base = metrics.measure(TEXT)
    other = TEXT.replace("콰앙-!", "콰앙~").replace("터벅, 터벅.", "터벅, 터벅~").replace("툭.", "툭~")
    cur = metrics.measure(other + "\n\n소리가 났다. 소리가 울렸다. 소리가 들렸다.")
    warns = metrics.drift(base, cur)
    assert any(w.startswith("효과음 끝 표시") and "'-' 100%" in w for w in warns), warns
    assert not any("'소리'" in w for w in warns), warns  # 재기만 한다 (2026-11-05 실험)
    assert not any(w.startswith("효과음 끝 표시") for w in metrics.drift(base, metrics.measure(TEXT)))


def test_old_baseline_without_sfx_fields_is_quiet():
    base = metrics.StyleMetrics(chars=100, sentences=5, sentence_len_mean=20)
    assert base.sfx_per_1k is None and base.sound_word_per_1k is None
    warns = metrics.drift(base, metrics.measure(TEXT + "\n\n소리가 났다. 소리가 울렸다."))
    assert not any("효과음" in w or "'소리'" in w for w in warns)


def test_narration_tics_skip_sfx_lines():
    assert metrics.narration_tics("뚝…뚝…\n\n그는 걸었다.") == {"trail": 0, "question": 0}


def test_fixed_lines_keep_sfx_lines_and_polish_problem_catches_change():
    assert pipeline.fixed_lines(TEXT) == ["콰앙-!", "터벅, 터벅.", "\"누구야?\"", "툭."]
    merged = TEXT.replace("콰앙-!\n\n문짝이", "콰앙 하고 문짝이")
    assert "효과음 줄이 바뀌었어요" in pipeline.polish_problem(TEXT, merged)
    assert pipeline.polish_problem(TEXT, TEXT.replace("문이 열렸다.", "문이 열린다.")) == ""


def test_style_profile_has_sound_effects_everywhere():
    assert "sound_effects" in StyleProfile.model_fields
    StyleEdit(key="sound_effects", text="한 줄 문단, 끝은 '-!'")  # 대화 변경안 칸
    assert "sound_effects" in pipeline.STYLE_TEXT_KEYS and prompts.STYLE_KEY_LABELS["sound_effects"] == "효과음 표기"
    static = Path(__file__).parent.parent / "canon" / "static"
    assert "['sound_effects', '효과음 표기']" in (static / "stylechat.js").read_text(encoding="utf-8")
    assert re.search(r"NARR_KEYS = \[[^\]]*'sound_effects'", (static / "style.js").read_text(encoding="utf-8"))


def test_style_prompt_adds_measured_sfx_note():
    assert "프로그램이 원문에서 센 값: 효과음 줄 3개" in prompts.style_prompt(TEXT)
    assert "프로그램이 원문에서 센 값" not in prompts.style_prompt("바람이 불었다. 그는 섰다.")
    assert "sound_effects 에는" in prompts.style_prompt("바람이 불었다.")


def test_no_write_rule_against_sound_word():
    # '소리가 났다'로 알리지 말라는 규칙은 블라인드 판정에서 져서 넣지 않았다 (reports/소리 표현 실측 2026-11-05.md)
    assert "소리 자체를 적습니다" not in prompts.prose_rules() and "소리 자체를 적습니다" not in prompts.prose_rules(styled=True)
