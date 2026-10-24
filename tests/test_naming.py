"""이름·지명 생성 (LLM 없음)."""
import random
import unittest

from canon import naming, prompts
from canon import naming_data as D
from canon.schema import Character, Meta, Project, WorldSetting


def project(**world) -> Project:
    return Project(meta=Meta(title="t"), world=WorldSetting(**world))


class NamingTest(unittest.TestCase):
    def test_age_and_birth_year(self):
        self.assertEqual(naming.age_years("17세 (고1)"), 17)
        self.assertEqual(naming.age_years("40대 초반"), 42)
        self.assertEqual(naming.age_years("중2"), 14)
        self.assertIsNone(naming.age_years("나이 불명"))
        self.assertEqual(naming.birth_year("45세", "1988년 서울"), 1943)

    def test_detect_style(self):
        self.assertEqual(naming.detect_style(project(era="현대 일본의 봄 학기")), "japan")
        self.assertEqual(naming.detect_style(project(setting="조선 후기 한양")), "joseon")
        p = project()
        p.meta.genres = ["martial_arts"]
        self.assertEqual(naming.detect_style(p), "wuxia")
        self.assertEqual(naming.detect_style(project()), "korea_modern")
        p = project(era="현대 일본", name_style="sf")
        self.assertEqual(naming.resolve_style(p), "sf")  # 작가가 고른 스타일이 먼저
        p.world.name_style = "없는값"
        self.assertEqual(naming.resolve_style(p), "japan")

    def test_era_names(self):
        """1980년생 무렵 인물에게는 그 시대 이름이 나온다 (앞뒤 10년까지)."""
        rng = random.Random(0)
        cands = naming.generate_people("korea_modern", 40, "남", 1981, rng=rng)
        self.assertEqual(len(cands), 40)
        for c in cands:
            self.assertRegex(c.note, r"19[789]0년대생")
            self.assertNotIn(c.name[1:], D.AI_OVERUSED)

    def test_every_style_makes_people_and_places(self):
        rng = random.Random(1)
        for st in naming.STYLES:
            people = naming.generate_people(st.id, 8, rng=rng)
            places = naming.generate_places(st.id, 8, rng=rng)
            self.assertEqual(len({c.name for c in people}), 8, st.id)
            self.assertEqual(len({c.name for c in places}), 8, st.id)
            self.assertTrue(all(c.kind for c in places), st.id)
            for kind in naming.place_kinds(st.id)[:3]:
                hit = naming.generate_places(st.id, 3, kind, rng=rng)
                self.assertTrue(all(c.kind == kind for c in hit), (st.id, kind))
        west = naming.generate_people("western_fantasy", 30, rng=rng)
        self.assertFalse({c.name.split()[0] for c in west} & D.WEST_CLICHE)

    def test_character_candidates_avoid_confusion(self):
        p = project(era="2026년")
        p.characters = [Character(id="a", name="김정훈", role="형사", age="45세", gender="남"),
                        Character(id="b", name="", role="증인", age="23세", gender="여")]
        cands = naming.character_candidates(p, p.characters[1], 8, rng=random.Random(2))
        for c in cands:
            given = c.name[1:]
            self.assertNotEqual(given[0], "정")
            self.assertNotEqual(given[-1], "훈")
        self.assertTrue(all(c.note.startswith("여") for c in cands))

    def test_cast_warnings(self):
        p = project(era="2026년")
        p.characters = [Character(id="a", name="한도윤", role="x", age="45세"),
                        Character(id="b", name="김도진", role="x"),
                        Character(id="c", name="박영숙", role="x", age="70세")]
        w = naming.cast_warnings(p)
        self.assertTrue(any("첫 글자" in x and "한도윤과 김도진은" in x for x in w))
        self.assertTrue(any("1981년생" in x and "'도윤'은" in x for x in w))
        self.assertTrue(any("AI가 자주 짓는 이름" in x and "김도진" in x for x in w))
        self.assertFalse(any("박영숙" in x for x in w))  # 1956년생에 영숙은 맞다

    def test_cast_issues_grouped_and_styled(self):
        p = project(era="2026년")
        p.characters = [Character(id="a", name="서윤", role="주인공", age="19세"),
                        Character(id="b", name="서윤", role="조연", age="60대"),
                        Character(id="c", name="엘레나", role="조연"),
                        Character(id="d", name="김철", role="x"), Character(id="e", name="김영", role="x")]
        issues = naming.cast_issues(p)
        same = [i for i in issues if i["kind"] == "same"]
        self.assertEqual(len(same), 1)
        self.assertEqual(same[0]["ids"], ["a", "b"])
        self.assertIn("서윤(주인공, 19세)", same[0]["text"])  # 같은 이름은 역할 · 나이로 가른다
        self.assertTrue(any(i["kind"] == "style" and i["ids"] == ["c"] for i in issues))
        # 두 글자 이름의 같은 첫 글자는 성이라 헷갈리는 이름으로 보지 않는다
        self.assertFalse(any(i["kind"] == "confusable" and set(i["ids"]) == {"d", "e"} for i in issues))
        self.assertEqual(sum(i["kind"] == "overused" for i in issues), 1)  # 흔한 이름은 한 줄로
        # 서양 이름은 흔한 끝 글자 하나로는 잡지 않는다
        self.assertEqual(naming._confusable("Elena", "Mira", "western_fantasy"), "")
        self.assertEqual(naming._confusable("Elena", "Elric", "western_fantasy"), "앞 두 글자")

    def test_setup_prompt_has_candidates(self):
        p = project(setting="바닷가 소도시", name_rules=["뱃사람 집안은 돌림자 '수'를 쓴다"])
        text = prompts.setup_prompt(p)
        self.assertIn("[이름·지명 후보]", text)
        self.assertIn("새 남자 인물 후보", text)
        self.assertIn("돌림자 '수'", text)
        p.characters = [Character(id="hero", name="", role="주인공", age="17세")]
        self.assertIn("- hero (주인공, 17세):", prompts.setup_prompt(p))


if __name__ == "__main__":
    unittest.main()
