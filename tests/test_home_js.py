"""작품 홈 계산(static/home.js homeCounts · homeCast · homeForeshadows · homeRecaps · homeTodos)을 node 로 맞춰 본다. node 가 있을 때만 돈다."""
from canon import foreshadows
from canon.schema import Character, Deadline, Foreshadow, Meta, Part, Project, StateDelta, StoryArc, StoryTime

from .jsvm import dump, episode, needs_node, run_js

FILES = ["app.js", "home.js"]


def project(**kw) -> Project:
    p = Project(meta=Meta(title="시험", genre="판타지", logline="", target_episodes=12, form=kw.pop("form", "short")))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def js(p: Project, expr: str):
    return run_js(FILES, expr, {"p": dump(p)})


def eps(fin: int, total: int, **kw):
    return [episode(n, status="finalized" if n <= fin else "draft", **kw) for n in range(1, total + 1)]


@needs_node
def test_home_counts_split_target():
    p = project(episodes=eps(3, 5))
    p.episodes[3].status = "written"
    c = js(p, "homeCounts(data.p)")
    assert (c["target"], c["finalized"], c["written"], c["draft"], c["none"]) == (12, 3, 1, 1, 7)


@needs_node
def test_home_cast_puts_core_first_and_skips_off():
    chars = [Character(id=f"c{i}", name=n, role="", tier=t, context=x)
             for i, (n, t, x) in enumerate([("가", "minor", "auto"), ("나", "main", "auto"), ("다", "support", "always"),
                                            ("라", "main", "off"), ("마", "support", "auto"), ("바", "minor", "auto")])]
    names = js(project(characters=chars), "homeCast(data.p).map((c) => c.name)")
    assert names == ["나", "다", "가", "마"]


@needs_node
def test_home_foreshadows_match_center_overdue():
    p = project(episodes=eps(8, 10), foreshadows=[
        Foreshadow(id="fs-b", description="늦은 복선", planted_ep=5, due_ep=6),
        Foreshadow(id="fs-a", description="오래된 복선", planted_ep=2),
        Foreshadow(id="fs-c", description="닫힌 복선", planted_ep=1, status="resolved"),
        Foreshadow(id="fs-d", description="아직 때 아님", planted_ep=7, due_ep=9),
    ])
    got = js(p, "homeForeshadows(data.p).map((f) => [f.id, f.age, f.overdue])")
    assert got == [["fs-a", 6, False], ["fs-b", 3, True], ["fs-d", 1, False]]
    center = {x["id"]: x["overdue"] for x in foreshadows.center(p)["items"] if x["status"] == "open"}
    assert {k: o for k, _, o in got} == center


@needs_node
def test_home_todos():
    p = project(form="serial", episodes=eps(8, 10), parts=[Part(number=1, title="", start_ep=1, end_ep=20, goal="")],
                story_arcs=[StoryArc(number=1, title="", start_ep=1, end_ep=4, goal="", summary="요약"),
                            StoryArc(number=2, title="", start_ep=5, end_ep=8, goal=""), StoryArc(number=3, title="", start_ep=9, end_ep=12, goal="")],
                foreshadows=[Foreshadow(id="fs-1", description="열쇠", planted_ep=3, due_ep=5)])
    p.episodes[7].time = StoryTime(day=9)
    p.timeline.deadlines = [Deadline(id="dl-1", what="보름 시장", day=11), Deadline(id="dl-2", what="먼 일", day=30),
                            Deadline(id="dl-3", what="닫힌 일", day=10, done_ep=8)]
    p.history = [StateDelta(episode=8, summary="", warnings=["마루의 위치가 맞지 않아요", "날짜가 거꾸로예요"])]
    todos = js(p, "homeTodos(data.p, '#/p/x')")
    assert [(t["tag"], t["label"], t["href"]) for t in todos] == [
        ("경고", "8화 반영 때 검수 경고 2개", "#/p/x/write/8"),
        ("할 일", "아크 2 요약이 없어요", "#/p/x/arc/a2"),
        ("기한", "보름 시장 · 2일 남았어요", "#/p/x/timeline"),
        ("복선", "회수 예정이 지난 복선 1개", "#/p/x/foreshadow"),
    ]
    assert todos[0]["sub"] == "마루의 위치가 맞지 않아요 외 1개"

    # 시간 기록을 끄거나 아무 일도 없으면 빈 목록
    q = project(episodes=eps(2, 4))
    q.timeline.enabled = False
    assert js(q, "homeTodos(data.p, '#/p/x')") == []


def _next(p: Project, expr: str = "nextStep()"):
    return js(p, f"(() => {{ S.project = data.p; S.name = 't'; S.route = ['p', 't']; const next = {expr}; return {{ next, html: nextStepHtml(nextStep()) }}; }})()")


@needs_node
def test_next_step_finished_opens_export():
    from canon.schema import Act
    p = project(episodes=eps(3, 3, text="본문"), characters=[Character(id="c1", name="가", role="")],
                arc=[Act(name="기", start_ep=1, end_ep=3, goal="")])
    p.meta.target_episodes = 3
    got = _next(p)
    # 주소만 읽는 곳(사이드바 · 팔레트 · serialHead)은 [글, 주소]로 마지막 화에 가니 글은 '보기', 버튼은 동작 글
    assert got["next"] == ["완결 원고 보기", "#/p/t/write/3", "exportAll", "완결 원고 내보내기"]
    assert got["html"] == '<button type="button" class="btn primary" data-action="exportAll">완결 원고 내보내기</button>'


@needs_node
def test_next_step_draft_links_episode_plot():
    from canon.schema import Act
    p = project(episodes=eps(1, 3), characters=[Character(id="c1", name="가", role="")],
                arc=[Act(name="기", start_ep=1, end_ep=3, goal="")])
    got = _next(p)
    assert got["next"] == ["2화 플롯 확정", "#/p/t/arc/2"]
    assert got["html"] == '<a class="btn primary" href="#/p/t/arc/2">2화 플롯 확정</a>'


@needs_node
def test_next_step_auto_is_navigation_label():
    p = project(episodes=eps(1, 3), characters=[Character(id="c1", name="가", role="")])
    got = js(p, "(() => { S.project = data.p; S.name = 't'; S.route = ['p', 't']; S.auto = { active: true, run: { ep: 2 } }; return [nextStep(), autoMenuLabel()]; })()")
    assert got == [["자동 집필로", "#/p/t/auto"], "자동 집필 · 쓰는 중"]


@needs_node
def test_next_step_serial_draft_keeps_arc_screen():
    """장편 초안 화는 '/arc' 로 둔다: plot.js serialHead 가 이 주소를 보고 '아크 N 초안 k화 모두 확정'을 primary 로 둔다."""
    from canon.schema import Act
    p = project(form="serial", episodes=eps(1, 3), characters=[Character(id="c1", name="가", role="")],
                parts=[Part(number=1, title="", start_ep=1, end_ep=12, goal="")],
                story_arcs=[StoryArc(number=1, title="", start_ep=1, end_ep=12, goal="", acts=[Act(name="기", start_ep=1, end_ep=12, goal="")])])
    got = _next(p)
    assert got["next"] == ["2화 플롯 확정", "#/p/t/arc"]
    got = js(p, "(() => { S.project = data.p; S.name = 't'; S.route = ['p', 't']; return [isArcHref('#/p/t/arc'), isArcHref('#/p/t/arc/2'), isArcHref('#/p/t/write/2')]; })()")
    assert got == [True, True, False]
    # plot.js serialHead 는 이 주소를 보고 아크 초안 모두 확정을 primary 로 둔다
    head = run_js(["app.js", "home.js", "plot.js"], "(() => { S.project = data.p; S.name = 't'; S.route = ['p', 't', 'arc', '2']; return serialHead([], []); })()", {"p": dump(p)})
    assert head["kind"] == "confirm" and 'data-action="confirmAll"' in head["html"]


@needs_node
def test_home_now_card_auto_heading_is_status():
    p = project(episodes=eps(1, 3), characters=[Character(id="c1", name="가", role="")])
    got = js(p, "(() => { S.project = data.p; S.name = 't'; S.route = ['p', 't']; S.auto = { active: true, run: { ep: 2 } }; const [l, h] = nextStep(); return homeNowCard(l, h); })()")
    assert '<h2 id="home-now-h">자동 집필이 2화를 쓰는 중이에요</h2>' in got


@needs_node
def test_home_head_more_menu():
    """작품 홈 머리는 주 버튼 하나와 ⋯ 메뉴다. 메뉴 안: 장편으로 늘리기 · 기승전결 · 플롯 · 갈래 만들기 (조건마다)."""
    p = project(episodes=eps(3, 3, text="본문"), characters=[Character(id="c1", name="가", role="")])
    p.meta.target_episodes = 3
    got = js(p, """(() => {
      S.project = data.p; S.name = 't'; S.route = ['p', 't'];
      const shut = homeHeadMore(3, false);
      S.popMenu = 'home-more';
      return { shut, open: homeHeadMore(3, false), arcNext: homeHeadMore(0, true) };
    })()""")
    assert 'data-arg="home-more"' in got["shut"] and 'aria-label="작품 더 보기 메뉴"' in got["shut"]
    assert "갈래 만들기" not in got["shut"]  # 닫힌 메뉴는 안을 그리지 않는다
    o = got["open"]
    assert '<a class="pop-item" href="#/p/t/convert">장편으로 늘리기</a>' in o
    assert '<a class="pop-item" href="#/p/t/arc">기승전결 · 플롯</a>' in o
    assert 'data-action="branchOpen"' in o and "btn primary" not in o
    assert got["arcNext"] == ""  # 반영한 화가 없고 다음 할 일이 플롯 화면이면 넣을 것이 없어 ⋯ 도 없다
