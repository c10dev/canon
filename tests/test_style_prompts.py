"""문체 표지, 기본 규칙 조정, 본문 한글 비율 가드. 실행: python -m unittest"""
import unittest

from canon import pipeline, prompts
from canon.mock import _plot
from canon.schema import Episode, Meta, Project, StyleDevice, StyleMarker, StyleProfile


def _project(style: StyleProfile | None = None) -> Project:
    p = Project(meta=Meta(title="등대", genre="미스터리", logline="x", target_episodes=2, words_per_episode=5000))
    p.style = style or StyleProfile()
    p.episodes = [Episode(plot=_plot(1, "기"), status="confirmed")]
    return p


class FakeLLM:
    def __init__(self, outputs: list[str]):
        self.outputs, self.calls = outputs, 0

    def text(self, system: str, prompt: str) -> str:
        self.calls += 1
        return self.outputs.pop(0)


class StylePromptTest(unittest.TestCase):
    def test_prose_rules_drop_conflicts_when_styled(self):
        plain, styled = prompts.prose_rules(False), prompts.prose_rules(True)
        self.assertEqual(plain, prompts.PROSE_RULES)
        for rule in ("쉼표가 둘 이상", "셋씩 나열", "줄표"):
            self.assertIn(rule, plain)
            self.assertNotIn(rule, styled)
        self.assertIn("부정 후 재정의", styled)
        for rules in (plain, styled):  # 동선 규칙은 문체와 부딪치지 않아 늘 들어간다
            self.assertIn("몸이 향한 쪽", rules)
        self.assertEqual(prompts.writer_system(_project()), prompts.SYSTEM_WRITER)
        p = _project(StyleProfile(sample_passages=["바람이 불었다."]))
        self.assertNotIn("쉼표가 둘 이상", prompts.writer_system(p))
        self.assertNotIn("쉼표가 둘 이상", prompts.reviser_system(p))

    def test_marker_block(self):
        self.assertEqual(prompts.marker_block(_project()), "")
        p = _project(StyleProfile(markers=[StyleMarker(text="것이었다", note="문단 끝", per_1k=0.8),
                                           StyleMarker(text="더라", per_1k=0.1), StyleMarker(text="말이지")]))
        block = prompts.marker_block(p)
        self.assertIn("'것이었다': 한 화에 4번 안팎 (문단 끝)", block)
        self.assertIn("'더라': 몇 화에 한 번", block)
        self.assertIn("'말이지': 원문 빈도 모름", block)
        ctx = prompts.static_context(p)
        self.assertIn("# 문체 표지", ctx)
        self.assertNotIn('"markers"', ctx)

    def test_count_markers(self):
        prof = StyleProfile(markers=[StyleMarker(text="~더라", per_1k=99), StyleMarker(text="없는표지", per_1k=5)])
        pipeline.count_markers(prof, "갔더라. " * 5 + "가" * 975)
        self.assertEqual([m.text for m in prof.markers], ["~더라"])
        self.assertEqual(prof.markers[0].per_1k, 5.0)

    def test_count_markers_drops_short_name_and_made_up(self):
        sample = "서윤은 대답하지 않았다. 대답은 없었다. 바람이 불었다. " * 10
        prof = StyleProfile(markers=[StyleMarker(text="다"), StyleMarker(text="."), StyleMarker(text="~다."), StyleMarker(text="서윤은"),
                                     StyleMarker(text="않았다")],
                            devices=[StyleDevice(name="침묵", cues=["대답", "다", "?"], example="대답은  없었다."),
                                     StyleDevice(name="지어냄", cues=["대답"], example="그는 하늘을 보았다.")])
        pipeline.count_markers(prof, sample, ["서윤", "도"])  # 한 글자 이름은 거르지 않는다 ('도' 가 든 표지를 다 빼지 않게)
        self.assertEqual([m.text for m in prof.markers], ["않았다"])
        self.assertEqual(prof.devices[0].cues, ["대답"])
        self.assertEqual(prof.devices[0].example, "대답은  없었다.")  # 공백만 다르면 원문에 있는 것으로 본다
        self.assertEqual(prof.devices[1].example, "")
        pipeline.count_markers(prof := StyleProfile(markers=[StyleMarker(text="서윤은")]), sample)
        self.assertEqual([m.text for m in prof.markers], ["서윤은"])  # 이름을 주지 않으면 이름 표지를 거르지 않는다

    def test_write_retries_non_korean(self):
        thought = "**Planning** The scene opens at the pier and I should keep the tone dry."
        llm = FakeLLM([thought, "바람이 불었다. 서윤은 고개를 들지 않았다."])
        self.assertEqual(pipeline.write_episode(llm, _project(), 1), "바람이 불었다. 서윤은 고개를 들지 않았다.")
        self.assertEqual(llm.calls, 2)
        with self.assertRaises(ValueError):
            pipeline.write_episode(FakeLLM([thought] * pipeline.WRITE_TRIES), _project(), 1)

    def test_style_drift_flags_copied_sentence(self):
        p = _project(StyleProfile(sample_passages=["부두 끝에 매인 배들이 서로 몸을 부딪치며 삐걱거렸다."]))
        p.episodes[0].text = "서윤이 걸었다. 부두 끝에 매인 배들이 서로 몸을 부딪치며 울었다."
        _, warns = pipeline.style_drift(p, 1)
        self.assertTrue(any(w.startswith("예시 문단을 옮긴 문장 1개") for w in warns))


if __name__ == "__main__":
    unittest.main()
