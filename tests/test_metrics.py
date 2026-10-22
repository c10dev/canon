"""문체 지표 단위 테스트. 실행: python -m unittest"""
import unittest
from pathlib import Path

from canon import metrics

SAMPLE = (Path(__file__).resolve().parent.parent / "examples" / "sample_style.txt").read_text(encoding="utf-8")


class MetricsTest(unittest.TestCase):
    def test_sentences_keep_quotes(self):
        sents = metrics.sentences(SAMPLE)
        self.assertIn('"또 여기 있네."', sents)
        self.assertEqual(sents[0], "바람이 불었다.")

    def test_measure_sample(self):
        m = metrics.measure(SAMPLE)
        self.assertEqual(m.past_tense_ratio, 1.0)
        self.assertTrue(0.1 < m.dialogue_ratio < 0.4)
        self.assertEqual(m.cliche_hits, [])

    def test_drift_flags_tense_and_cliche(self):
        base = metrics.measure(SAMPLE)
        cur = metrics.measure(SAMPLE.replace("불었다", "분다").replace("않았다", "않는다") + " 그는 숨을 내쉬었다.", ["삐걱거렸다"])
        warns = metrics.drift(base, cur)
        self.assertTrue(any("과거형" in w for w in warns))
        self.assertTrue(any("숨을 내쉬었다" in w and "삐걱거렸다" in w for w in warns))

    def test_mattr(self):
        self.assertIsNone(metrics.measure(SAMPLE).mattr)  # 100어절 미만은 재지 않는다
        self.assertEqual(metrics.measure(" ".join(str(i) for i in range(300))).mattr, 1.0)
        self.assertEqual(metrics.measure("가 " * 300).mattr, 0.01)

    def test_ai_patterns(self):
        text = (
            "그것은 단순한 위협이 아니었다. 선전포고였다. 그것은 단순한 검격이 아니었다.\n\n"
            "공간을 가르고, 시간을 끊고, 운명마저 베어내는 일격이었다. 그는 분노를 느꼈다. 이 기술을 통해 그는 이겼다.\n\n"
            "그녀의 손이 떨렸다. 짧은 침묵. 그러나 충분했다."
        )
        counts = metrics.pattern_counts(text)
        self.assertEqual(counts["부정 후 재정의"], 2)
        self.assertEqual(counts["셋씩 나열"], 1)
        self.assertEqual(counts["감정 이름 서술"], 1)
        self.assertEqual(counts["번역투"], 1)
        m = metrics.measure(text)
        self.assertEqual(m.ai_pattern_hits, ["부정 후 재정의 2회 (상한 1)"])
        self.assertEqual(m.short_ending_ratio, 0.33)
        self.assertGreater(m.pronoun_per_1k, 20)
        warns = metrics.drift(metrics.measure(SAMPLE), m)
        self.assertTrue(any(w.startswith("쇠맛 패턴") for w in warns))
        self.assertTrue(any("대명사" in w for w in warns))

    def test_sample_has_no_ai_patterns(self):
        m = metrics.measure(SAMPLE)
        self.assertEqual(m.ai_pattern_hits, [])
        self.assertEqual(sum(metrics.pattern_counts(SAMPLE).values()), 0)
        self.assertEqual(m.short_ending_ratio, 0.0)

    def test_old_baseline_without_new_fields(self):
        old = metrics.StyleMetrics.model_validate({"sentence_len_mean": 20, "sentence_len_cv": 0.5})
        self.assertIsNone(old.comma_sentence_ratio)
        warns = metrics.drift(old, metrics.measure(SAMPLE))  # 새 지표가 없는 예전 기준값도 오류 없이 비교
        self.assertFalse(any("쉼표" in w or "대명사" in w for w in warns))

    def test_same_text_no_drift(self):
        m = metrics.measure(SAMPLE)
        self.assertEqual(metrics.drift(m, m), [])


if __name__ == "__main__":
    unittest.main()
