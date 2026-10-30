"""관계 역학(canon/dynamics.py) 단위 테스트. LLM 을 부르지 않는다."""
import json
import os
import tempfile
import unittest

os.environ["CANON_LLM"] = "mock"
os.environ["CANON_HOME"] = tempfile.mkdtemp()

from canon import dynamics, pipeline, store  # noqa: E402
from canon.cli import main  # noqa: E402
from canon.schema import ModelParams, Project, Relationship, Secret, StoryEvent, Tie  # noqa: E402


def lie(**kw) -> StoryEvent:
    base = dict(episode=5, actor="doheon", target="seoyun", kind="거짓말발각", intensity=3)
    return StoryEvent(**{**base, **kw})


class EventMathTest(unittest.TestCase):
    def test_lie_reveal_matches_formula(self):
        ties = [
            Tie(source="seoyun", target="doheon", warmth=0.55, trust_pos=5.25, trust_neg=1.85),
            Tie(source="doheon", target="seoyun", warmth=0.60),
        ]
        secrets = [Secret(id="sec-letter", owner="doheon", content="편지", hidden_from=["seoyun", "seojin"])]
        dynamics.apply_event(ties, secrets, ModelParams(), lie(witnesses=["seojin"], reveals_secret="sec-letter"))

        t = dynamics.find_tie(ties, "seoyun", "doheon")
        w = 0.55 - 0.24 * (1 + 0.55) / 2           # 포화
        w += 0.1 * (0.60 - w)                        # 상호성
        self.assertAlmostEqual(t.warmth, w)
        self.assertAlmostEqual(t.trust, 5.25 / (5.25 + 6.35))
        self.assertAlmostEqual(t.grievance, 0.6)
        self.assertEqual(secrets[0].hidden_from, [])  # 당사자와 목격자 모두 알게 됨
        self.assertIsNotNone(dynamics.find_tie(ties, "seojin", "doheon"))  # 목격자의 시선도 움직임
        self.assertLess(dynamics.find_tie(ties, "seojin", "doheon").warmth, 0)

    def test_trust_with_more_evidence_moves_less(self):
        new = [Tie(source="a", target="b", trust_pos=2, trust_neg=1)]
        old = [Tie(source="a", target="b", trust_pos=20, trust_neg=10)]
        e = StoryEvent(episode=1, actor="b", target="a", kind="배신", intensity=2)
        before = (new[0].trust, old[0].trust)
        dynamics.apply_event(new, [], ModelParams(), e)
        dynamics.apply_event(old, [], ModelParams(), e)
        self.assertGreater(before[0] - new[0].trust, before[1] - old[0].trust)

    def test_stage_moves_one_step(self):
        self.assertEqual(dynamics.step_stage("신뢰", "적대"), "균열")
        self.assertEqual(dynamics.step_stage("낯섦", "신뢰"), "호감")
        self.assertEqual(dynamics.step_stage("호감", "호감"), "호감")
        # 나쁜 단계 사이는 '호감'을 거치지 않는다 (경계 ↔ 균열 간선이 없으면 반감인 쌍에 '단계: 호감'이 붙었다)
        self.assertEqual(dynamics.step_stage("경계", "균열"), "균열")
        self.assertEqual(dynamics.step_stage("균열", "경계"), "경계")
        self.assertEqual(dynamics.step_stage("낯섦", "균열"), "경계")
        for a in ("경계", "균열", "적대"):
            for b in ("경계", "균열", "적대"):
                self.assertNotEqual(dynamics.step_stage(a, b), "호감")

    def test_unbalanced_triad_raises_tension(self):
        p = Project(relationships=[
            Relationship(a="s", b="d", type="친구", affinity=3),
            Relationship(a="s", b="j", type="친구", affinity=2),
            Relationship(a="d", b="j", type="라이벌", affinity=-2),
        ])
        dynamics.seed_ties(p)
        self.assertEqual(dynamics.unbalanced_triads(p.ties), [("d", "j", "s")])
        with_triad = dynamics.tension(p, "s", "d")
        self.assertGreater(with_triad, dynamics.tension(p, "s", "d", triads=[]))


class FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main(["new", "dyn", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
        main(["arc", "dyn", "-y"])
        main(["plot", "dyn"])
        main(["confirm", "dyn", "all"])
        main(["run", "dyn", "-y"])

    def test_events_logged_and_snapshots_per_episode(self):
        p = store.load("dyn")
        self.assertEqual([s.episode for s in p.snapshots], [0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(len([e for e in p.events if e.kind != "수동보정"]), 12)
        self.assertEqual(p.secrets[0].hidden_from, [])
        rel = p.relationships[0]
        self.assertEqual(rel.description, "서로 의지하는 사이")
        self.assertEqual(rel.affinity, round(dynamics.pair_warmth(p.ties, "hero", "ally") * 5))

    def test_replay_matches_incremental(self):
        p = store.load("dyn")
        for got, want in zip(sorted(dynamics.replay(p), key=lambda t: (t.source, t.target)),
                             sorted(p.ties, key=lambda t: (t.source, t.target))):
            self.assertAlmostEqual(got.warmth, want.warmth)
            self.assertAlmostEqual(got.trust_pos, want.trust_pos)
            self.assertAlmostEqual(got.trust_neg, want.trust_neg)
            self.assertEqual(got.stage, want.stage)

    def test_revert_restores_snapshot(self):
        p = store.load("dyn")
        snap = p.snapshot(1)
        pipeline.revert(p, 1)
        self.assertEqual([e.status for e in p.episodes], ["finalized"] + ["written"] * 5)
        self.assertEqual(p.ties, snap.ties)
        self.assertEqual(p.secrets[0].hidden_from, ["hero"])
        self.assertTrue(all(e.episode <= 1 for e in p.events))

    def test_adjust_and_toggle(self):
        main(["view", "dyn", "numbers"])
        main(["adjust", "dyn", "hero", "ally", "--warmth", "-0.5"])
        p = store.load("dyn")
        self.assertTrue(p.settings.show_numbers)
        self.assertAlmostEqual(dynamics.find_tie(p.ties, "hero", "ally").warmth, -0.5)
        self.assertEqual(p.events[-1].kind, "수동보정")


class MigrationTest(unittest.TestCase):
    def test_old_project_json_gets_ties(self):
        old = Project(relationships=[Relationship(a="a", b="b", type="연인", affinity=4, tension=2)]).model_dump()
        for key in ("ties", "secrets", "events", "params", "snapshots", "settings"):
            old.pop(key)
        old["relationships"][0].pop("goal_conflict")
        d = store.project_dir("old")
        d.mkdir(parents=True, exist_ok=True)
        (d / "project.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        p = store.load("old")
        self.assertEqual(len(p.ties), 2)
        self.assertAlmostEqual(p.ties[0].warmth, 0.8)


if __name__ == "__main__":
    unittest.main()
