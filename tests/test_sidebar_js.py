"""사이드바(static/app.js sidebar)의 배지 · 접는 묶음 · 아래 고정 줄 · 레일 버튼과 플레이 사이드바(play.js)가 그려지는지.
node 가 있을 때만 돈다."""
import re

from canon import tofix
from canon.schema import Meta, Project

from .jsvm import STATIC, dump, episode, needs_node, run_js

FILES = re.findall(r'src="/static/([a-z]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


def project():
    e1 = episode(1, status="finalized", text="비가 왔다. 바람이 불었다.", plot={"title": "첫 화"})
    tofix.add(e1, "비가 왔다.", "", 0, "2026-10-30T10:00:00+00:00")
    tofix.add(e1, "바람이 불었다.", "", 0, "2026-10-30T10:01:00+00:00")
    tofix.update(e1, "x2", "2026-10-30T11:00:00+00:00", status="done")
    e2 = episode(2, status="written", text="새벽이 밝았다.", plot={"title": "둘째 화"})
    d = dump(Project(meta=Meta(title="등대지기의 겨울", target_episodes=3), episodes=[e1, e2]))
    d["episodes"][1]["findings"] = [{"id": "f1", "status": "open"}, {"id": "f2", "status": "open"}, {"id": "f3", "status": "kept"}]
    return d


@needs_node
def test_badges():
    got = run_js(FILES, """(() => {
      const p = data;
      return {
        two: navBadges(p, 2, [{ kind: 'state', ep: 2 }, { kind: 'arc', ep: 0 }], 3),
        other: navBadges(p, 2, [{ kind: 'state', ep: 1 }], null),  // 다른 화의 상태 변경안은 4 · 5 · 6 줄이 가리키는 화의 배지가 아니다
        one: navBadges(p, 1, [], null),
        none: navBadges(p, 3, [], null),
      };
    })()""", project())
    assert got["two"] == {"check": 2, "review": 1, "auto": 3, "tofix": 1}  # kept 지적 · done 고칠 곳은 세지 않는다
    assert got["one"] == {"check": 0, "review": 0, "auto": None, "tofix": 1}
    assert got["none"]["check"] == 0
    assert got["other"]["review"] == 0


@needs_node
def test_sidebar_render():
    got = run_js(FILES, """(() => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'write', '2'];
      S.pending = { name: 't', results: { k: { key: 'k', kind: 'state', ep: 2 } }, failures: {} };
      const write = sidebar('write');
      const folded = sidebar('abilities');  // 데이터 없는 도구를 보면 그 묶음을 펼쳐 그린다
      const lab = sidebar('research');
      S.menuOpen = true;
      const open = sidebar('home');
      return { write, folded, lab, open };
    })()""", project())
    w = got["write"]
    assert 'aria-current="page"' in w and "<span class=\"sr-only\"> (단계 4)</span>" in w
    assert ">2</span><span class=\"sr-only\">, 열린 지적 2개</span>" in w
    assert ">결과</span><span class=\"sr-only\">, 반영하지 않은 상태 변경안이 있어요</span>" in w
    assert ", 남은 고칠 곳 1개" in w
    assert 'data-action="navFold" data-arg="tools"' in w and 'data-action="toggleRail"' in w and 'data-action="openPalette"' in w
    assert 'class="side-set" href="#/settings"' in w and 'data-arg="side-more"' in w
    assert "토스페이스" in w and 'id="hub-slot"' in w
    # 아직 안 쓴 도구는 접혀 있고, 지금 보는 화면이 든 묶음만 펼쳐 그린다
    assert re.search(r'id="fold-more" hidden', w)
    assert not re.search(r'id="fold-more" hidden', got["folded"])
    # 실험 묶음은 작품 안 사이드바에 없다. 실험 화면을 보는 동안에도 그리지 않는다 (찾기 팔레트로 부른다)
    for html in (w, got["lab"]):
        assert 'data-arg="lab"' not in html and "실험 · 본편과 분리" not in html
        assert "연구 · 모델 실험" not in html and "큐 시트 집필 실험" not in html
    assert 'class="side open"' in got["open"] and 'class="side-scrim"' in got["open"]
    assert 'class="side-scrim"' not in w


@needs_node
def test_more_fold_not_kept():
    """아직 안 쓴 도구는 펼침을 브라우저에 두지 않고, 다른 화면으로 가면 다시 접힌다."""
    got = run_js(FILES, """(() => {
      const kept = [];
      render = () => {};  // 그리기는 이 시험 밖이다
      localStorage = {  // 예전 키가 남아 있어도 보지 않는다
        getItem: (k) => (k === 'canon.navMore' || k === 'canon.nav.more' ? '1' : null),
        setItem: (k, v) => kept.push([k, v]),
      };
      S.project = data; S.name = 't'; S.route = ['p', 't', 'cast'];
      const first = navFoldOpen('more');
      actions.navFold('more');
      const opened = navFoldOpen('more');
      actions.navFold('tools');  // 작품 도구는 그대로 기억한다
      return { first, opened, kept };
    })()""", project())
    assert got["first"] is False and got["opened"] is True
    assert got["kept"] == [["canon.nav.tools", "0"]]


@needs_node
def test_palette_finds_every_project_screen():
    """작품 안 화면은 사이드바에 있든 없든 모두 찾기 팔레트에서 이름으로 찾아진다."""
    got = run_js(FILES, """(() => {
      S.project = data; S.name = 't'; S.route = ['p', 't'];
      S.pending = { name: 't', results: {}, failures: {} };
      const nav = navItems();
      const items = paletteItems(palContext());
      const screens = [...nav.steps, nav.auto, ...nav.tools, ...nav.apart].map((x) => [x[3], x[1]]);
      const foot = nav.foot.map(([href, label]) => [label, href]);
      const side = sidebar('home');
      return {
        apart: nav.apart.map((x) => x[3]),
        missing: [...screens, ...foot].filter(([label, href]) => {
          const top = paletteMatch(items, label)[0];
          return !top || top.href !== href && !(href === '#/settings' && top.label === '설정');
        }),
        dup: items.filter((it) => it.kind === 'screen').map((it) => it.href).filter((h, i, a) => a.indexOf(h) !== i),
        notInSide: [...screens].filter(([, href]) => !side.includes(`href="${href}"`)).map(([label]) => label),
      };
    })()""", project())
    assert got["missing"] == []
    assert got["dup"] == []  # 역설계 · 쇠맛은 실험과 작품 밖 화면(foot)에 다 있지만 한 번만 나온다
    assert set(got["apart"]) == {"연구 · 모델 실험", "큐 시트 집필 실험", "역설계 실험", "쇠맛 실험실", "사용량 · 비용"}
    assert set(got["apart"]) <= set(got["notInSide"])  # 사이드바에서 뺀 실험 화면도 팔레트에 있다 (위 missing)


@needs_node
def test_play_sidebar_render():
    got = run_js(FILES, """(() => {
      S.play = { name: 'pl', title: '', world: 'w', world_title: '세계', world_exists: true, days: 3, decisions: 2, ending: null };
      return playSidebar('now');
    })()""", {})
    assert "세계 작품 「세계」로" in got and 'href="#/p/w"' in got
    assert 'data-action="toggleMenu"' in got and 'data-action="toggleRail"' in got
    assert 'id="hub-slot"' not in got and 'data-action="openPalette"' not in got
    assert 'class="side-set" href="#/settings"' in got


@needs_node
def test_flow_rows_follow_viewed_episode():
    got = run_js(FILES, """(() => {
      S.project = data; S.name = 't';
      const links = () => navItems().steps.filter(([id]) => ['write', 'check', 'review'].includes(id)).map(([, href]) => href);
      S.route = ['p', 't', 'check', '1'];
      const viewed = links();
      S.route = ['p', 't', 'cast'];
      const elsewhere = links();
      S.route = ['p', 't', 'write', '9'];  // 없는 화는 지금 작업할 화로
      const missing = links();
      return { viewed, elsewhere, missing };
    })()""", project())
    assert got["viewed"] == ["#/p/t/write/1", "#/p/t/check/1", "#/p/t/review/1"]
    assert got["elsewhere"] == ["#/p/t/write/2", "#/p/t/check/2", "#/p/t/review/2"]
    assert got["missing"] == got["elsewhere"]


@needs_node
def test_play_copy_work_card():
    got = run_js(FILES, """(() => {
      S.project = data; S.name = 't'; S.route = ['p', 't'];
      const before = { card: workCard(), next: nextStep() };
      S.homePlay = { name: 't', title: '임유웅의 삶', world_title: '세계' };
      return { before, card: workCard(), next: nextStep() };
    })()""", project())
    assert "플레이 사본" not in got["before"]["card"] and got["before"]["next"][1] != "#/play/t"
    assert "플레이 사본 · 임유웅의 삶" in got["card"]
    assert got["next"] == ["플레이로 돌아가기", "#/play/t"]
