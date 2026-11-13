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


# 모든 시스템 프롬프트는 머리말(prompts.PREAMBLE)로 시작한다. 한국어 출력 줄(prompts.KOREAN_LINE)을 받지 않는 것과 그 까닭.
NO_KOREAN_LINE = {
    "FAMILY_SYSTEM": "캐시 가족 공통 글. 할 일과 출력 언어는 사용자 메시지 앞의 원래 시스템 프롬프트가 들고 온다",
    "SYSTEM_CHECKER_EN": "영어 검수",
    "SYSTEM_ILLUSTRATOR": "Danbooru 영어 태그를 쓴다. 설명 칸만 한국어라고 따로 적는다",
    "SYSTEM_JUDGE_CHECK": "답이 A~H 글자 하나다 (judge.label_probs 가 글자 토큰을 읽는다)",
    "SYSTEM_MAP_PLANNER": "종류 칸에 목록 id 를 그대로 쓴다. 설명 칸만 한국어라고 따로 적는다",
    "SYSTEM_STAGE": "어휘 칸에 목록 id 를 그대로 쓴다. 설명 칸만 한국어라고 따로 적는다",
}


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

    def test_preamble(self):
        # 본문을 쓰는 시스템 프롬프트는 머리말로 시작하고 역할 문장이 없다. 성인 · 전연령 작품이 같은 글을 받는다(#272).
        plain, adult = _project(), _project()
        adult.meta.adult = True
        for fn in (prompts.writer_system, prompts.reviser_system, prompts.paragraph_system):
            for p in (plain, adult):
                text = fn(p)
                self.assertTrue(text.startswith(prompts.PREAMBLE))
                self.assertNotIn("당신은", text)
                self.assertIn("모든 출력은 한국어로 작성합니다", text)  # 머리말이 영어라서 출력 언어를 밝힌다
                self.assertNotIn("NSFW", text)
            self.assertEqual(fn(plain), fn(adult))
        self.assertIn("본문만 출력하고", prompts.writer_system(plain))
        self.assertNotIn("절대", prompts.writer_system(plain))  # 강한 금지어 대신 이유를 붙인 지시
        self.assertIn("앞 화와 이어져야 하므로 어기지 않습니다", prompts.writer_system(plain))
        self.assertEqual(prompts.reviser_system(plain), prompts.SYSTEM_REVISER)

    def test_every_system_prompt_starts_with_preamble(self):
        # SYSTEM_* 상수와 캐시 가족 공통 글은 모두 머리말로 시작하고 역할 문장이 없다. 새 상수가 머리말을 빠뜨리면 여기서 걸린다
        names = sorted(n for n in dir(prompts) if n.startswith("SYSTEM_") and isinstance(getattr(prompts, n), str))
        names.append("FAMILY_SYSTEM")
        self.assertLessEqual(set(NO_KOREAN_LINE), set(names))  # 지운 상수는 목록에서도 뺀다
        for name in names:
            text = getattr(prompts, name)
            self.assertTrue(text.startswith(prompts.PREAMBLE), f"{name} 에 머리말이 없어요. prompts.system_prompt 로 만들어요")
            body = text[len(prompts.PREAMBLE):]
            self.assertNotIn("당신은", body, name)  # 머리말이 Canon 은 역할이 아니라고 한다
            self.assertNotIn("You are", body, name)
            if name in NO_KOREAN_LINE:
                self.assertNotIn(prompts.KOREAN_LINE, text, f"{name} 는 한국어 줄을 받으니 NO_KOREAN_LINE 에서 빼요")
            else:
                self.assertIn(prompts.KOREAN_LINE, text, f"{name} 에 한국어 줄이 없어요. 머리말이 영어라서 출력 언어를 밝혀요")

    def test_role_block_does_not_repeat_preamble(self):
        # 캐시 가족: 머리말은 시스템 자리의 공통 글에 있으니 사용자 메시지로 옮긴 원래 시스템 프롬프트에서는 뺀다
        from canon.llm import role_block

        block = role_block(prompts.SYSTEM_EDITOR)
        self.assertNotIn(prompts.PREAMBLE.strip(), block)
        self.assertTrue(block.startswith("# 이번 요청에서 할 일\n연재 소설의 설정을 관리합니다."))
        self.assertEqual(role_block("검수"), "# 이번 요청에서 할 일\n검수\n\n")

    def test_vivid_rules(self):
        # 늘려 쓰기 규칙은 문체 원문이 있어도 넣는다. 감각 · 비유 횟수 · 튀는 생각 줄은 뺐다 (2026-11-13 가려 읽기, 작가 결정)
        plain, styled, split = prompts.prose_rules(False), prompts.prose_rules(True), prompts.prose_rules(split=True)
        for rules in (plain, styled, split):
            self.assertIn("시간을 늘려", rules)
            for rule in ("비유는 아끼고", "비유는 장면마다", "소리, 냄새, 온도", "엉뚱한 연상"):
                self.assertNotIn(rule, rules)
        # 문체 원문이 없는 작품은 비유를 쓸 때의 방법과 대명사 줄이 남는다. 문체 원문이 있으면 둘 다 뺀다 (번역투 절은 남는다)
        self.assertIn("비유를 쓸 때는", plain)
        self.assertIn("대명사보다 이름", plain)
        for rule in ("비유", "대명사"):
            self.assertNotIn(rule, styled)
        self.assertIn("'~를 통해'", styled)
        self.assertEqual((len(plain.splitlines()), len(styled.splitlines()), len(split.splitlines())), (14, 12, 8))  # 머리 줄 + 규칙 13 · 11 · 7
        self.assertIn(prompts.FOCUS_LINE, prompts.episode_prompt(_project(), 1))
        self.assertIn("vivid", prompts.REWRITE_PRESETS)
        self.assertIn("vivid", prompts.PASSAGE_PRESETS)

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
