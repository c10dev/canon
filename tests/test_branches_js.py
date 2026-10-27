"""갈래 화면(static/branches.js · home.js)이 서버와 같은 규칙을 쓰는지. node 가 있을 때만 돈다.
branchName ↔ 명령줄 branches 의 이름, folderOf · branchFolder 가 만드는 폴더 이름 ↔ web.NAME_RE."""
import pytest

from canon import web

from .jsvm import needs_node, run_js
from .test_restate import _two_done
from .test_web import client  # noqa: F401  (pytest fixture)

TITLES = ["등대", "  밤의 등대  ", "a/b\\c:d*e?f\"g<h>i|j", "...숨은 폴더", ". 점 뒤 빈칸", "탭\t과\n줄바꿈", "가" * 80, "x" * 63 + " y",
          "", "   ", "///", "회귀한 S급 헌터의 두 번째 인생은 생각보다 조용하다 — 1부 · 겨울 편"]


@needs_node
def test_folder_names_pass_server_check():
    expr = "S.name = 'lh'; data.map((t) => [folderOf(t), branchFolder(t), FOLDER_BAD.test(folderOf(t))])"
    got = run_js(["app.js", "home.js", "branches.js"], expr, TITLES)
    for t, (folder, branch, bad) in zip(TITLES, got):
        assert folder == "" or (web.NAME_RE.match(folder) and not bad), t
        assert web.NAME_RE.match(branch), t
    assert sum(f == "" for f, _, _ in got) == 3


@needs_node
@pytest.mark.xfail(strict=True, reason="어긋남: folderOf 는 64 UTF-16 단위로 잘라 이모지 가운데를 끊을 수 있다. "
                   "끊긴 반쪽 글자는 NAME_RE 를 지나도 폴더를 만들 때 깨진다")
def test_folder_name_cut_keeps_whole_characters():
    title = "a" + "🗡" * 40
    folder = run_js(["app.js", "home.js"], "folderOf(data)", title)
    assert folder == title[:len(folder)] and folder.encode("utf-8")


@needs_node
def test_branch_name_matches_cli(client, capsys):  # noqa: F811
    from canon import cli

    _two_done(client)
    cli.main(["branch", "lh", "2", "lh-b", "--label", "B안"])
    cli.main(["branch", "lh", "2", "lh-k", "--keep"])
    cli.main(["branch", "lh-k", "2", "lh-k2"])
    got = []
    for promote in [False, True]:
        if promote:
            cli.main(["promote", "lh-b", "-y"])  # 이름 붙은 갈래가 본편이 된다
        capsys.readouterr()
        cli.main(["branches", "lh"])
        heads = [x.strip().removeprefix("└ ").split(" · ")[0] for x in capsys.readouterr().out.splitlines() if " · " in x]
        members = client.get("/api/projects/lh/branches").json()["members"]
        names = run_js(["app.js", "branches.js"], "data.map(branchName)", members)
        assert names == [h.removesuffix(f" ({m['name']})") for h, m in zip(heads, members)]
        got.append(names)
    assert got == [["등대", "B안", "lh-k", "lh-k2"], ["B안", "lh", "lh-k", "lh-k2"]]  # 본편에서 내려온 lh 는 이름이 없어 폴더 이름
