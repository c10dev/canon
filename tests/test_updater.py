"""자동 업데이트 테스트. 임시 git 저장소 두 개(origin, 클론)로 확인한다."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from canon import updater


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin, self.clone, self.dev = root / "origin.git", root / "clone", root / "dev"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.dev)], check=True)
        git(self.dev, "config", "user.email", "t@example.com")
        git(self.dev, "config", "user.name", "t")
        self.commit("a.txt", "1", "첫 커밋")
        git(self.dev, "push", "-q", "origin", "HEAD:main")
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.clone)], check=True)
        git(self.clone, "config", "user.email", "t@example.com")
        git(self.clone, "config", "user.name", "t")

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, name: str, text: str, msg: str, repo: Path = None) -> None:
        repo = repo or self.dev
        (repo / name).write_text(text)
        git(repo, "add", name)
        git(repo, "commit", "-q", "-m", msg)

    def push_new(self) -> None:
        self.commit("a.txt", "2", "새 기능")
        git(self.dev, "push", "-q", "origin", "HEAD:main")

    def test_up_to_date(self):
        self.assertFalse(updater.update(self.clone, install=False).updated)

    def test_pulls_and_keeps_user_data(self):
        (self.clone / "projects").mkdir()
        (self.clone / "projects" / "project.json").write_text("{}")  # 추적하지 않는 사용자 데이터
        self.push_new()
        r = updater.update(self.clone, install=False)
        self.assertTrue(r.updated, r.message)
        self.assertIn("새 기능", r.message)
        self.assertEqual((self.clone / "a.txt").read_text(), "2")
        self.assertEqual((self.clone / "projects" / "project.json").read_text(), "{}")

    def test_skips_when_files_changed(self):
        (self.clone / "a.txt").write_text("내가 고침")
        self.push_new()
        r = updater.update(self.clone, install=False)
        self.assertFalse(r.updated)
        self.assertIn("고친 파일", r.message)
        self.assertEqual((self.clone / "a.txt").read_text(), "내가 고침")

    def test_skips_other_branch(self):
        git(self.clone, "checkout", "-q", "-b", "work")
        self.push_new()
        self.assertIn("브랜치가 아니라", updater.update(self.clone, install=False).message)

    def test_skips_local_commits(self):
        self.commit("b.txt", "x", "로컬 커밋", repo=self.clone)
        self.push_new()
        r = updater.update(self.clone, install=False)
        self.assertFalse(r.updated)
        self.assertIn("로컬 커밋", r.message)

    def test_not_a_repo(self):
        self.assertFalse(updater.update(Path(self.tmp.name), install=False).updated)


if __name__ == "__main__":
    unittest.main()
