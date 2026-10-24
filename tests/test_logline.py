"""로그라인 다섯 칸 합치기, 톤 다이얼, 말로 고른 관계 (LLM 없음)."""
import re
import unittest
from pathlib import Path

from canon import dynamics, genres, logline
from canon.schema import LoglineParts, Project, Relationship, ToneDials


class LoglineTest(unittest.TestCase):
    def test_compose(self):
        p = LoglineParts(who="사진관을 하는 서윤", why="오빠의 실종 소식에 돌아와", goal="오빠의 마지막 열흘을 되짚는다",
                         block="도현은 무언가를 숨긴다", stake="진실을 알면 가족을 잃는다")
        self.assertEqual(logline.compose(p), "사진관을 하는 서윤이 오빠의 실종 소식에 돌아와 오빠의 마지막 열흘을 되짚는다. "
                                             "하지만 도현은 무언가를 숨긴다. 진실을 알면 가족을 잃는다.")
        self.assertTrue(all(ok for ok, _ in logline.checks(p)))
        self.assertEqual(logline.compose(LoglineParts(who="서진", goal="등대를 지킨다.")), "서진이 등대를 지킨다.")
        self.assertEqual(logline.compose(LoglineParts(block="모두가 숨긴다")), "모두가 숨긴다.")
        self.assertEqual(logline.compose(LoglineParts()), "")

    def test_josa(self):
        self.assertEqual(logline.josa("서윤", "이", "가"), "이")
        self.assertEqual(logline.josa("서진이", "이", "가"), "가")
        self.assertEqual(logline.josa("K", "이", "가"), "이(가)")
        # 숫자는 읽는 소리로: 손님2(이) → 와, 손님3(삼) → 과
        self.assertEqual(logline.josa("손님2", "과", "와"), "와")
        self.assertEqual(logline.josa("손님3", "과", "와"), "과")

    def test_checks_flag_missing(self):
        oks = [ok for ok, _ in logline.checks(LoglineParts(who="서윤", goal="행복"))]
        self.assertEqual(oks, [False] * 5)

    def test_tone_text(self):
        self.assertEqual(logline.tone_text(ToneDials(dark=3, serious=4, slow=4)), "조금 어둡고 진지하고 호흡이 느리다")
        self.assertEqual(logline.tone_text(ToneDials(dark=1, serious=2)), "밝고 조금 가볍다")
        self.assertEqual(logline.tone_text(ToneDials()), "")

    def test_genre_examples_pass_checks(self):
        for g in genres.CATALOG:
            self.assertGreaterEqual(len(g.logline), 2, g.id)
            for ex in g.logline:
                failed = [label for ok, label in logline.checks(ex) if not ok]
                self.assertEqual(failed, [], f"{g.id}: {logline.compose(ex)}")


class ViewTest(unittest.TestCase):
    def test_views_seed_directional_ties(self):
        p = Project(relationships=[Relationship(a="hero", b="ally", type="친구", a_view=["경계한다"], b_view=["믿는다", "좋아한다"])])
        dynamics.seed_ties(p)
        ab, ba = dynamics.find_tie(p.ties, "hero", "ally"), dynamics.find_tie(p.ties, "ally", "hero")
        self.assertLess(ab.warmth, 0)
        self.assertLess(ab.trust, 0.5)
        self.assertGreater(ba.warmth, 0.5)
        self.assertGreater(ba.trust, 0.6)  # 시작 증거 2개 분량이라 0.65 근처
        self.assertEqual(p.relationships[0].affinity, round((ab.warmth + ba.warmth) / 2 * 5))

    def test_unknown_words_and_one_side(self):
        p = Project(relationships=[Relationship(a="a", b="b", type="x", affinity=5, a_view=["모르는 말"], b_view=[])])
        dynamics.seed_ties(p)
        self.assertEqual(dynamics.find_tie(p.ties, "a", "b").warmth, 0)  # 말을 골랐지만 모르는 말이면 중립
        self.assertEqual(dynamics.find_tie(p.ties, "b", "a").warmth, 1)  # 말이 없는 쪽은 affinity

    def test_web_lists_match(self):
        js = (Path(__file__).parent.parent / "canon" / "static" / "app.js").read_text(encoding="utf-8")
        views = re.search(r"const VIEWS = \[(.*?)\];", js).group(1)
        self.assertEqual(re.findall(r"'([^']+)'", views), list(dynamics.VIEWS))
