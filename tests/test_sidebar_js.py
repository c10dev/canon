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
        one: navBadges(p, 1, [], null),
        none: navBadges(p, 3, [], null),
      };
    })()""", project())
    assert got["two"] == {"check": 2, "review": 1, "auto": 3, "tofix": 1}  # kept 지적 · done 고칠 곳은 세지 않는다
    assert got["one"] == {"check": 0, "review": 0, "auto": None, "tofix": 1}
    assert got["none"]["check"] == 0


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
    assert ">결과</span><span class=\"sr-only\">, 반영하지 않은 상태 변경안 1개</span>" in w
    assert ", 남은 고칠 곳 1개" in w
    assert 'data-action="navFold" data-arg="tools"' in w and 'data-action="toggleRail"' in w and 'data-action="openPalette"' in w
    assert 'class="side-set" href="#/settings"' in w and 'data-arg="side-more"' in w
    assert "토스페이스" in w and 'id="hub-slot"' in w
    # 시험 대역의 저장소는 '1' 을 돌려주지 않아 묶음이 접힌다. 지금 보는 화면이 든 묶음만 펼쳐 그린다
    assert re.search(r'id="fold-more" hidden', w) and re.search(r'id="fold-lab" hidden', w)
    assert not re.search(r'id="fold-more" hidden', got["folded"])
    assert not re.search(r'id="fold-lab" hidden', got["lab"])
    assert 'class="side open"' in got["open"] and 'class="side-scrim"' in got["open"]
    assert 'class="side-scrim"' not in w


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
