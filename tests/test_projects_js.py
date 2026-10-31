"""작품 목록 계산(static/home.js plStatus · plRows · projectGo · fmtWhen · plTimeGroup · plHero)과 작품 밖 사이드바(app.js outNav · outSidebar)를
node 로 맞춰 본다. node 가 있을 때만 돈다."""
import re

from .jsvm import STATIC, needs_node, run_js

FILES = ["app.js", "home.js", "branches.js"]
ALL = re.findall(r'src="/static/([a-z]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))  # 사이드바는 hub.js 도 쓴다


def card(name, title="", fin=0, eps=12, planned=12, genre="판타지", branch=None, play=None, alerts=None):
    return {"name": name, "title": title or name, "genre": genre, "form": "short", "episodes": eps, "finalized": fin,
            "planned": planned, "open_ep": 0 if fin >= eps or not planned else fin + 1, "open_status": "" if fin >= eps or not planned else "confirmed",
            "updated_at": "", "branch": branch, "play": play, "alerts": alerts or []}


def branch(id, parent="", from_ep=0, label=""):
    return {"id": id, "family": "fam", "parent": parent, "from_ep": from_ep, "label": label}


def play(world, title):
    return {"world": world, "title": title, "player": "서린", "origin": "random", "ending": "", "turns": 3, "decisions": 2, "days": 4, "waiting": True}


LIST = [
    card("sea", "검은 바다", fin=3, eps=120, branch=branch("a")),
    card("glass", "유리 정원", fin=0, eps=16, genre="로맨스"),
    card("sea-b", "검은 바다 B", fin=5, eps=120, branch=branch("b", "a", 4, "떠나는 길"),
         alerts=[{"kind": "fail", "job": "check", "ep": 6, "label": "6화 검수", "error": "요청 한도"}]),
    card("fog", "안개 고양이", fin=10, eps=10, planned=10, genre="일상"),
    card("sea-play", "", fin=0, eps=120, play=play("sea", "서린의 삶")),
    card("lost-play", "", play=play("gone", "옛 삶")),
    card("blank", "빈 작품", fin=0, eps=12, planned=0),
]


def rows(**opt):
    expr = """(() => { const r = plRows(data.list, data.opt);
      return { names: r.groups.map((g) => g.card.name), counts: r.counts, lost: r.lost.map((x) => x.name),
               kids: r.groups.map((g) => [g.branches.map((b) => b.card.name), g.plays.map((y) => y.name)]) }; })()"""
    return run_js(FILES, expr, {"list": LIST, "opt": opt})


@needs_node
def test_status_matches_project_next():
    got = run_js(FILES, "data.list.map((x) => [plStatus(x), projectNext(x)])", {"list": LIST[:4] + [LIST[6]]})
    assert got == [["writing", "4화 쓰기 대기"], ["fresh", "1화 쓰기 대기"], ["writing", "6화 쓰기 대기"], ["done", "완결"], ["fresh", "플롯 없음"]]
    # 본문을 쓴 화: 검수가 끝나야 상태 승인 차례 (사이드바 · 작품 홈의 다음 할 일과 같다)
    written = [{**LIST[0], "open_status": "written", "open_checked": c} for c in (False, True)]
    assert run_js(FILES, "data.list.map(projectNext)", {"list": written}) == ["4화 검수 대기", "4화 상태 승인 대기"]


@needs_node
def test_rows_group_branches_and_plays():
    r = rows()
    assert r["names"] == ["sea", "glass", "fog", "blank"]
    assert r["kids"][0] == [["sea-b"], ["sea-play"]]
    assert r["lost"] == ["lost-play"]
    assert r["counts"] == {"all": 4, "alert": 1, "writing": 1, "fresh": 2, "done": 1}


@needs_node
def test_rows_find_filter_sort():
    # 찾기는 갈래 · 플레이 이름도 보고, 낱말마다 맞아야 한다. 수는 찾기만 거친 값
    assert rows(q="떠나는")["names"] == ["sea"]
    assert rows(q="서린의")["names"] == ["sea"]
    assert rows(q="로맨스 유리")["names"] == ["glass"]
    assert rows(q="없는말")["names"] == []
    r = rows(q="정원", filter="done")
    assert (r["names"], r["counts"]["fresh"]) == ([], 1)
    assert rows(filter="fresh")["names"] == ["glass", "blank"]
    assert rows(filter="alert")["names"] == ["sea"]  # 갈래의 멈춘 작업도 본편 묶음의 확인할 것
    assert rows(sort="title")["names"] == ["sea", "blank", "fog", "glass"]
    assert rows(sort="progress")["names"][:2] == ["fog", "sea"]


@needs_node
def test_project_go_links_to_step_screen():
    xs = [{**LIST[0], "open_status": st, "open_checked": c} for st, c in (("draft", False), ("confirmed", False), ("written", False), ("written", True))]
    xs += [LIST[3], LIST[6], LIST[4]]
    got = run_js(FILES, "data.list.map((x) => { const g = projectGo(x); return [g.label, g.href, g.done]; })", {"list": xs})
    assert got == [
        ["4화 플롯 확정", "#/p/sea/arc/4", False],
        ["4화 쓰기", "#/p/sea/write/4", False],
        ["4화 검수하기", "#/p/sea/check/4", False],
        ["4화 상태 승인", "#/p/sea/review/4", False],
        ["완결", "#/p/fog", True],
        ["플롯 만들기", "#/p/blank/arc", False],
        ["결정 고르기", "#/play/sea-play", False],
    ]


@needs_node
def test_when_and_time_groups():
    got = run_js(FILES, """(() => {
      const now = new Date(2026, 9, 31, 15, 0);
      const at = (d, h, m) => new Date(2026, 9, d, h, m).toISOString();
      return {
        when: [fmtWhen(at(31, 9, 5), now), fmtWhen(at(30, 23, 40), now), fmtWhen(at(2, 7, 0), now), fmtWhen(new Date(2025, 11, 3).toISOString(), now), fmtWhen('', now)],
        group: [plTimeGroup(at(26, 0, 0), now), plTimeGroup(at(10, 0, 0), now), plTimeGroup(new Date(2026, 6, 1).toISOString(), now), plTimeGroup('', now)],
      };
    })()""", {})
    assert got["when"] == ["오늘 09:05", "어제 23:40", "10.02 07:00", "2025.12.03", ""]
    assert got["group"] == ["week", "month", "old", "old"]


@needs_node
def test_hero_skips_finished_and_plays():
    order = [LIST[3], LIST[4], LIST[1], LIST[0]]  # 완결 → 플레이 → 시작 전 → 쓰는 중 (고친 때 순서)
    got = run_js(FILES, "(() => { const g = plHero(data.list); return g && g.card.name; })()", {"list": order})
    assert got == "glass"
    assert run_js(FILES, "plHero(data.list)", {"list": [LIST[3]]}) is None


@needs_node
def test_out_nav_and_sidebar():
    got = run_js(ALL, """(() => {
      const nav = outNav(data.list, [{ id: 's1' }, { id: 's2' }]);
      S.projects = data.list; S.libs = []; S.route = ['styles'];
      return { nav, html: outSidebar('styles') };
    })()""", {"list": LIST})
    nav = got["nav"]
    assert [m[1] for m in nav["main"]] == ["#/", "#/new", "#/play/new"]
    assert [r["name"] for r in nav["recent"]] == ["sea", "glass", "sea-b"]  # 플레이 사본은 빼고 고친 때 순서로 셋
    assert nav["recent"][2]["fail"] == 1 and nav["recent"][2]["label"] == "검은 바다 B · 떠나는 길" and nav["recent"][0]["mark"] == "검"
    assert (nav["alerts"], nav["fails"]) == (1, 1)
    assert [t[0] for t in nav["tools"]] == ["styles", "revlab", "soelab", "usage"] and nav["tools"][0][4] == "2"
    h = got["html"]
    assert 'class="side side-out"' in h and 'aria-label="작품 밖 메뉴"' in h
    assert 'href="#/styles" title="문체 라이브러리" aria-current="page"' in h
    assert '<span class="nav-off"' in h and "쇠맛 실험실" in h  # 아직 열지 않은 화면은 링크가 아니다
    assert ", 확인할 것 1개" in h and ", 멈춘 작업 1개" in h
    assert 'data-arg="side-more"' not in h and 'class="side-set" href="#/settings"' in h  # ⋯ 메뉴 없이 설정만
