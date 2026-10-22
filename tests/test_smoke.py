"""mock LLM 으로 설정부터 마지막 화 확정까지 전체 흐름을 돌려 본다.

    python -m unittest
"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ["CANON_LLM"] = "mock"
os.environ["CANON_HOME"] = tempfile.mkdtemp()

from canon import store  # noqa: E402
from canon.cli import main  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample_style.txt"


class SmokeTest(unittest.TestCase):
    def test_full_flow(self):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "10", "-y"])
        main(["style", "demo", str(SAMPLE), "-y"])
        main(["arc", "demo", "-y"])
        main(["plot", "demo"])
        main(["confirm", "demo", "all"])
        main(["run", "demo", "-y"])
        main(["brief", "demo", "3"])
        main(["brief", "demo", "3", "--check"])
        main(["check", "demo", "1"])
        main(["stats", "demo"])

        p = store.load("demo")
        self.assertEqual([e.status for e in p.episodes], ["finalized"] * 10)
        self.assertTrue(all(e.summary for e in p.episodes))
        self.assertEqual(p.foreshadows[0].status, "resolved")
        self.assertTrue((store.project_dir("demo") / "briefs" / "03-episode.md").exists())
        self.assertTrue((store.project_dir("demo") / "briefs" / "03-check.md").exists())
        self.assertIsNotNone(p.style_baseline)
        self.assertEqual(p.episode(2).issues[0].type, "말투")
        self.assertEqual(p.episode(1).issues, [])


if __name__ == "__main__":
    unittest.main()
