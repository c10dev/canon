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

    def test_same_text_no_drift(self):
        m = metrics.measure(SAMPLE)
        self.assertEqual(metrics.drift(m, m), [])


if __name__ == "__main__":
    unittest.main()
