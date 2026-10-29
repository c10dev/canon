"""고칠 곳 화면(static/tofix.js)이 서버 tofix.spot · collect 와 같은 자리를 짚는지, 밑줄 · 집필 화면 버튼 · 고칠 곳 화면이 그려지는지.
node 가 있을 때만 돈다."""
import re

from canon import tofix
from canon.schema import Meta, Project

from .jsvm import STATIC, dump, episode, needs_node, run_js

TWICE = "그는 웃었다. 비가 왔다. 그는 웃었다."
# index.html 이 읽는 순서 그대로 (화면 파일이 서로의 함수를 감싼다)
FILES = re.findall(r'src="/static/([a-z]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


def project():
    e1 = episode(1, status="finalized", text=TWICE, plot={"title": "첫 화"})
    tofix.add(e1, "그는 웃었다.", "말투가 딱딱함", 20, "2026-10-28T10:00:00+00:00")
    tofix.add(e1, "비가 왔다.", "", 0, "2026-10-28T10:01:00+00:00")
    tofix.update(e1, "x2", "2026-10-28T11:00:00+00:00", status="done")
    e2 = episode(2, status="written", text="새벽이 밝았다.", plot={"title": "둘째 화"})
    tofix.add(e2, "새벽이 밝았다.", "", 0, "2026-10-28T10:02:00+00:00")
    e2.text = "아침이 밝았다."  # 본문을 고쳐 표시한 글이 사라짐
    return Project(meta=Meta(title="t", target_episodes=3), episodes=[e1, e2])


@needs_node
def test_spot_and_list_match_server():
    p = project()
    cases = [[TWICE, "그는 웃었다.", 0], [TWICE, "그는 웃었다.", 20], [TWICE, "없음", 0], [TWICE, " ", 0]]
    got = run_js(FILES, """(() => {
      S.project = data.p; S.name = 't';
      return {
        spots: data.cases.map(([t, q, s]) => { const r = tofixSpot(t, q, s); return r && [r.a, r.b]; }),
        list: ['open', 'done', 'all'].map((k) => tofixList(data.p.episodes, k).map((x) => [x.n, x.m.id, x.found])),
        ranges: tofixRanges(ep(1), ep(1).text).map((r) => [r.a, r.b, r.key, r.kind]),
        all: allRanges(1, ep(1).text).map((r) => r.key),
        at: [tofixAt(ep(1), ep(1).text, 15, 7), tofixAt(ep(1), ep(1).text, 0, 7)].map((m) => m && m.id),
      };
    })()""", {"p": dump(p), "cases": cases})
    want = [list(s) if (s := tofix.spot(t, q, st)) else None for t, q, st in cases]
    assert got["spots"] == want
    for k, rows in zip(("open", "done", "all"), got["list"]):
        assert rows == [[r["ep"], r["mark"].id, r["found"]] for r in tofix.collect(p, k)]
    assert got["ranges"] == [[15, 22, "t:x1", "tofix"]]  # 고친 것(x2)은 밑줄 없음
    assert got["all"] == ["t:x1"]
    assert got["at"] == ["x1", None]


@needs_node
def test_views_render():
    got = run_js(FILES, """(() => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'tofix'];
      const open = viewToFix();
      S.tofixFilter = 'done';
      const done = viewToFix();
      S.tofixFilter = 'all';
      const all = viewToFix();
      S.route = ['p', 't', 'write', '1'];
      const write = viewWrite(1);
      const nav = navItems().tools.find((x) => x[0] === 'tofix');
      S.project.episodes.forEach((e) => { e.to_fix = []; });
      S.route = ['p', 't', 'tofix'];
      return { open, done, all, write, nav, empty: viewToFix(), noBtn: tofixBtn(1) };
    })()""", dump(project()))
    assert "말투가 딱딱함" in got["open"] and 'data-action="tofixGo" data-arg="1:x1"' in got["open"]
    assert "본문에서 이 글을 찾지 못했어요" in got["open"] and "2화 둘째 화" in got["open"]
    assert "비가 왔다." not in got["open"] and 'data-action="tofixReopen" data-arg="1:x2"' in got["done"]
    assert "남음 2" in got["all"] and "고침 1" in got["all"] and "모두 3" in got["all"]
    assert 'data-action="tofixNext" data-arg="1"' in got["write"] and "고칠 곳 1개" in got["write"]
    assert got["nav"][3] == "고칠 곳" and got["nav"][4] is True
    assert "아직 담은 곳이 없어요" in got["empty"] and got["noBtn"] == ""
