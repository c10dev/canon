"""3단계 기승전결 · 플롯 화면(static/plot.js)의 목차 계산과 그리기를 node 로 맞춰 본다. node 가 있을 때만 돈다.
목차: 화 상태 수(plotCounts), 확인할 것(plotTodos), 장편 부 › 아크 › 구간 나무(serialTree)."""
from canon.schema import Act, Character, Meta, Part, Project, StoryArc

from .jsvm import dump, episode, needs_node, run_js

FILES = ["app.js", "home.js", "plot.js"]
VIEW_FILES = ["app.js", "home.js", "branches.js", "style.js", "plot.js", "write.js", "review.js", "chat.js", "agent.js", "passage.js",
              "rewrite.js", "restate.js", "opening.js", "insert.js", "lines.js", "auto.js", "marks.js", "timeline.js", "cast.js", "foreshadow.js"]


def _acts(start: int, end: int) -> list[Act]:
    q = max(1, (end - start + 1) // 4)
    cut = [start, start + q, start + 2 * q, start + 3 * q, end + 1]
    return [Act(name=n, start_ep=cut[i], end_ep=cut[i + 1] - 1, goal=f"{n} 목표") for i, n in enumerate("기승전결")]


def _short() -> Project:
    eps = [episode(n, status=s, plot={"title": f"{n}화 제목", "ending_hook": "" if n in (5, 8) else "훅", "characters": ["a"]})
           for n, s in [(1, "finalized"), (2, "finalized"), (3, "written"), (4, "confirmed"), (5, "draft"), (6, "draft"), (7, "draft"), (8, "draft")]]
    eps[3].plot.characters = ["a", "ghost"]  # 설정 없는 인물
    eps[4].plot.characters = ["a", "newbie"]  # 인물 후보
    eps[2].plot.characters = ["a", "ghost2"]  # 본문이 있는 화는 확인할 것에 넣지 않는다
    eps[2].text = "본문"
    p = Project(meta=Meta(title="t", target_episodes=8), characters=[Character(id="a", name="가람", role="주인공")],
                arc=_acts(1, 8), episodes=eps)
    p.cast_candidates = [Character(id="newbie", name="새봄", role="조연", tier="support")]
    return p


def _serial(arcs: int = 3, parts: bool = True) -> Project:
    """10화짜리 아크 arcs 개. 앞 아크 둘은 반영 끝(요약은 첫째만), 부는 1~30 · 31~60."""
    p = Project(meta=Meta(title="s", form="serial", target_episodes=60))
    eps = []
    for k in range(arcs):
        s, e = k * 10 + 1, k * 10 + 10
        p.story_arcs.append(StoryArc(number=k + 1, title=f"아크{k + 1}", start_ep=s, end_ep=e, goal="", acts=_acts(s, e),
                                     summary="요약" if k == 0 else ""))
        eps += [episode(n, status="finalized" if k < 2 else "draft") for n in range(s, e + 1)]
    p.episodes = eps
    if parts:
        p.parts = [Part(number=1, title="일", start_ep=1, end_ep=30, goal=""), Part(number=2, title="이", start_ep=31, end_ep=60, goal="")]
    return p


@needs_node
def test_plot_counts():
    got = run_js(FILES, "S.project = data; plotCounts(data.episodes)", dump(_short()))
    assert got == {"finalized": 2, "written": 1, "confirmed": 1, "draft": 4, "total": 8}


@needs_node
def test_plot_todos():
    got = run_js(FILES, "S.project = data; plotTodos(data, 1, 8)", dump(_short()))
    kinds = [(t["kind"], t["n"]) for t in got]
    # 후보는 그 화, 설정 없는 id 는 본문 없는 화만, 엔딩 훅은 마지막 화(8)를 빼고
    assert kinds == [("cast", 5), ("unknown", 4), ("hook", 5)]
    assert got[0]["text"] == "새 인물 후보 · 새봄"
    assert got[2]["text"] == "엔딩 훅 빈 화 · 5화"
    assert run_js(FILES, "S.project = data; plotTodos(data, 6, 8)", dump(_short())) == []


@needs_node
def test_serial_tree_opens_the_part_of_the_chosen_arc():
    p = _serial()
    rows = run_js(FILES, "S.project = data; serialTree(data, 2)", dump(p))
    assert [r["kind"] for r in rows] == ["part", "arc", "arc", "act", "act", "act", "act", "arc", "part"]
    assert rows[0]["open"] is True and rows[0]["arcs"] == 3
    assert [r["number"] for r in rows if r["kind"] == "arc"] == [1, 2, 3]
    assert next(r for r in rows if r["kind"] == "arc" and r["number"] == 2)["sel"] is True
    part2 = next(r for r in rows if r["kind"] == "part" and r["number"] == 2)
    assert part2["open"] is False  # 고른 아크가 없는 부는 접힌다. 다음 아크(31화)도 그 부라 같이 숨는다
    assert not any(r["kind"] == "next" for r in rows)


@needs_node
def test_serial_tree_next_slot_and_open_parts():
    p = _serial()
    rows = run_js(FILES, "S.project = data; serialTree(data, 'next')", dump(p))
    kinds = [r["kind"] for r in rows]
    assert kinds == ["part", "part", "next"]  # 다음 아크(31화)가 든 2부만 펼친다
    assert rows[1]["open"] is True and rows[2] == {"kind": "next", "start": 31, "sel": True}
    rows = run_js(FILES, "S.project = data; serialTree(data, 'next', { open: [1] })", dump(p))
    assert [r["kind"] for r in rows] == ["part", "arc", "arc", "arc", "part", "next"]


@needs_node
def test_serial_tree_folds_old_finished_arcs():
    p = _serial(arcs=6, parts=False)
    for a in p.story_arcs[:5]:
        a.summary = "요약"
    for e in p.episodes:
        e.status = "finalized"
    p.story_arcs[5].summary = ""
    rows = run_js(FILES, "S.project = data; serialTree(data, 6)", dump(p))
    assert rows[0] == {"kind": "fold", "from": 1, "to": 5, "count": 5}
    assert [r["number"] for r in rows if r["kind"] == "arc"] == [6]
    rows = run_js(FILES, "S.project = data; serialTree(data, 2)", dump(p))  # 고른 아크는 접혀도 보인다
    assert rows[0]["count"] == 4 and [r["number"] for r in rows if r["kind"] == "arc"] == [2, 6]
    rows = run_js(FILES, "S.project = data; serialTree(data, 6, { all: true })", dump(p))
    assert not any(r["kind"] == "fold" for r in rows)
    # 부가 없고 아크가 작품 끝까지 있으면 다음 아크 자리가 없다
    assert not any(r["kind"] == "next" for r in rows)


@needs_node
def test_views_render_toc_and_board():
    short = _short()
    serial = _serial()
    got = run_js(VIEW_FILES, """(() => {
      S.name = 't';
      S.project = data.short; S.route = ['p', 't', 'arc'];
      const board = viewArc();
      S.route = ['p', 't', 'arc', '5'];
      const page = viewPlotPage(5);
      S.project = data.serial; S.route = ['p', 't', 'arc']; S.selArc = 3;
      const ser = viewSerial();
      return { board, page, ser };
    })()""", {"short": dump(short), "serial": dump(serial)})
    board, page, ser = got["board"], got["page"], got["ser"]
    assert 'id="plot-toc"' in board and 'data-action="jumpAct" data-arg="3"' in board
    assert "확인할 것 3" in board and "초안 4화 모두 확정" in board
    assert 'data-action="menuToggle" data-arg="plotai"' in board and "+ 요청" not in board
    assert 'class="act-map"' not in board and "ep-dots" not in page
    assert 'data-action="openPlot" data-arg="5"' in page and 'aria-current="page"' in page
    for label in ("줄거리", "인물 · 시점", "끝과 이음", "복선"):
        assert f'aria-label="{label}"' in page
    assert "4화 엔딩 훅" in page and "6화 (다음 화)" in page
    assert 'data-action="tocPart" data-arg="1"' in ser and 'data-action="selectArc" data-arg="3" aria-current="true"' in ser
    assert 'class="arc-bar"' not in ser and "부 · 아크 전체 보기" not in ser
