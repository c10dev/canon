"""복선 센터 화면(static/foreshadow.js)의 순수 함수: 축 띠 · 표시 · 줄 끝 한마디 · 손볼 것 · 목차 · 흐름 · 앞으로 회수할 것 · 눈금 · 걸기 칸 후보,
그리고 화면 HTML(목차 틀 · 개요 · 복선 하나 · 빈 화면 · 걸기 칸). 서버 계산값은 canon/foreshadows.py center() 로 만든다.
node 가 있을 때만 돈다."""
from canon import foreshadows
from canon.schema import Foreshadow, ForeshadowClue, Project

from .jsvm import dump, episode, needs_node, run_js

FILES = ["app.js", "chat.js", "passage.js", "foreshadow.js"]


def _project() -> Project:
    """지어낸 장편: 12화, 9화까지 반영. 복선 넷(끊어진 연결 · 예정 지남 · 플롯 회수 계획 · 회수함)."""
    eps = []
    for n in range(1, 13):
        text = {2: "등불이 세 번 깜박였다.", 3: "열쇠는 왼손에 있었다.", 5: "등불이 다시 흔들렸다.", 7: "그 열쇠가 문을 열었다."}.get(n, "바람이 불었다.")
        e = episode(n, status="finalized" if n <= 9 else "confirmed", text=text if n <= 9 else "",
                    plot={"title": f"{n}화", "foreshadow_payoff": ["fs-lamp"] if n == 11 else []})
        eps.append(e)
    p = Project(episodes=eps)
    p.meta.form = "serial"
    p.story_arcs = []
    p.foreshadows = [
        Foreshadow(id="fs-lamp", description="깜박이는 등불", planted_ep=2, scope="part"),
        Foreshadow(id="fs-key", description="왼손의 열쇠", planted_ep=3, status="resolved", payoff_ep=7),
        Foreshadow(id="fs-door", description="잠긴 지하 문", planted_ep=1, due_ep=4),
        Foreshadow(id="fs-map", description="젖지 않는 지도", planted_ep=4, due_ep=12),
    ]
    p.foreshadow_clues = [
        ForeshadowClue(foreshadow="fs-lamp", kind="plant", quote="등불이 세 번 깜박였다.", episode=2, by="ai"),
        ForeshadowClue(foreshadow="fs-lamp", kind="plant", quote="등불이 다시 흔들렸다.", episode=5, by="author"),
        ForeshadowClue(foreshadow="fs-lamp", kind="plant", quote="사라진 문장이다.", episode=6, by="ai"),
        ForeshadowClue(foreshadow="fs-key", kind="plant", quote="열쇠는 왼손에 있었다.", episode=3, by="ai"),
        ForeshadowClue(foreshadow="fs-key", kind="payoff", quote="그 열쇠가 문을 열었다.", episode=7, by="ai"),
    ]
    return p


def _center(p: Project) -> dict:
    return foreshadows.center(p)


@needs_node
def test_marks_flags_and_attention():
    c = _center(_project())
    got = run_js(FILES, """(() => {
      const by = Object.fromEntries(data.c.items.map((x) => [x.id, x]));
      return {
        marks: Object.fromEntries(Object.entries(by).map(([k, x]) => [k, fsMarks(x).map((m) => m.kind + m.ep)])),
        flags: Object.fromEntries(Object.entries(by).map(([k, x]) => [k, fsFlag(x, data.c.done)])),
        att: Object.fromEntries(Object.entries(by).map(([k, x]) => [k, fsAttention(x)])),
        tail: Object.fromEntries(Object.entries(by).map(([k, x]) => [k, fsTail(x)])),
      };
    })()""", {"c": c})
    # 끊어진 문장은 모양이 다르고, 플롯 회수 계획 · 예정 화는 열린 복선에만
    assert got["marks"]["fs-lamp"] == ["plant2", "plant5", "broken6", "plan11"]
    assert got["marks"]["fs-key"] == ["plant3", "payoff7"]
    assert got["marks"]["fs-door"] == ["plant1", "due4"]  # 걸린 문장이 없으면 심은 화에 점 하나
    assert got["flags"]["fs-lamp"] == ["끊어진 연결 1", "bad"]
    assert got["flags"]["fs-key"] == ["7화 회수", ""]
    assert got["flags"]["fs-door"] == ["예정 4화 지남", "warn"]
    assert got["flags"]["fs-map"] == ["예정 12화", ""]
    assert got["att"] == {"fs-lamp": True, "fs-key": False, "fs-door": True, "fs-map": False}
    assert got["tail"] == {"fs-lamp": "끊어짐", "fs-key": "7화 회수", "fs-door": "예정 지남", "fs-map": "4화~"}


@needs_node
def test_todo_rows_have_one_action_each():
    c = _center(_project())
    rows = run_js(FILES, "fsTodo(data.c)", {"c": c})
    assert [(r["id"], r["label"], r["go"]) for r in rows] == [("fs-lamp", "끊어진 연결", "write"), ("fs-door", "예정 지남", "edit")]
    assert rows[0]["ep"] == 6 and rows[0]["act"] == "6화에서 다시 걸기" and "6화 본문" in rows[0]["why"]
    assert "4화에 회수할 예정" in rows[1]["why"] and "9화까지" in rows[1]["why"]


@needs_node
def test_stale_row_and_no_duplicate_with_overdue():
    c = _center(_project())
    door = next(x for x in c["items"] if x["id"] == "fs-door")
    door["stale"] = True  # 예정도 지나고 오래 묵은 복선은 한 줄만
    rows = run_js(FILES, "fsTodo(data.c)", {"c": c})
    assert [r["label"] for r in rows if r["id"] == "fs-door"] == ["예정 지남"]
    door["overdue"] = False
    rows = run_js(FILES, "fsTodo(data.c)", {"c": c})
    assert [(r["label"], r["go"]) for r in rows if r["id"] == "fs-door"] == [("오래 묵음", "view")]


@needs_node
def test_toc_rows_split_open_and_resolved():
    c = _center(_project())
    t = run_js(FILES, "fsTocRows(data.c, 'fs-map')", {"c": c})
    assert [r["id"] for r in t["open"]] == ["fs-door", "fs-lamp", "fs-map"]  # 심은 차례
    assert [r["id"] for r in t["resolved"]] == ["fs-key"]
    assert [r["cur"] for r in t["open"]] == [False, False, True]
    assert t["resolved"][0]["done"] is True


@needs_node
def test_flow_orders_past_now_future():
    c = _center(_project())
    flow = run_js(FILES, """(() => {
      const by = Object.fromEntries(data.c.items.map((x) => [x.id, x]));
      const f = (id) => fsFlow(by[id], data.c.done, { 11: { status: 'confirmed', title: '11화' } }).map((e) => [e.ep, e.kind, e.label]);
      return { lamp: f('fs-lamp'), key: f('fs-key'), door: f('fs-door'), map: f('fs-map') };
    })()""", {"c": c})
    assert flow["lamp"] == [[2, "plant", "심음"], [5, "plant", "다시 떠올림"], [6, "broken", "본문에서 사라진 문장"],
                            [9, "now", "지금 · 9화까지 반영했어요"], [11, "plan", "회수 예정"]]
    assert flow["key"] == [[3, "plant", "심음"], [7, "payoff", "회수"]]  # 회수한 복선은 지금 · 앞으로 줄이 없다
    assert flow["door"] == [[1, "plant", "심음"], [4, "due", "회수 예정 화가 지났어요"], [9, "now", "지금 · 9화까지 반영했어요"]]
    assert flow["map"][-1] == [12, "due", "회수 예정 화"]


@needs_node
def test_ahead_groups_plot_and_due():
    c = _center(_project())
    rows = run_js(FILES, "fsAhead(data.c)", {"c": c})
    assert rows == [{"ep": 11, "kind": "plot", "items": [{"id": "fs-lamp", "d": "깜박이는 등불"}]},
                    {"ep": 12, "kind": "due", "items": [{"id": "fs-map", "d": "젖지 않는 지도"}]}]


@needs_node
def test_ticks_drop_crowded_keep_now():
    got = run_js(FILES, "[fsTicks([1, 58, 64], 64, 58), fsTicks([1, 2, 3, 30], 64, 3), fsTicks([], 64, 58), fsTicks([1], 1, 0)]", {})
    assert [(t["ep"], t["label"], t["cls"]) for t in got[0]] == [(1, "1화", "tk first"), (58, "58화 지금", "tk now"), (64, "64화", "tk last")]
    assert [t["ep"] for t in got[1]] == [3, 30]  # 1 · 2 · 3 은 겹쳐서 지금 화(3)만
    assert got[2] == []
    assert [t["ep"] for t in got[3]] == [1]


@needs_node
def test_bands_and_positions():
    got = run_js(FILES, """[
      fsBands({ meta: { form: 'serial' }, story_arcs: [{ number: 1, title: '안개', start_ep: 1, end_ep: 20 }] }),
      fsBands({ meta: { form: 'short' }, arc: [{ name: '기', start_ep: 1, end_ep: 3 }] }),
      fsAt(1, 64), fsAt(64, 64), fsAt(5, 1),
    ]""", {})
    assert got[0] == [{"label": "아크 1 · 안개", "s": 1, "e": 20}]
    assert got[1] == [{"label": "기", "s": 1, "e": 3}]
    assert got[2:4] == ["0%", "100%"]


@needs_node
def test_candidates_near_first_open_first_and_search():
    p = dump(_project())
    got = run_js(FILES, """[fsCandidates(data.p, 6), fsCandidates(data.p, 6, '열 쇠'), fsCandidates(data.p, 6, '없는말'),
      fsCandidates({ ...data.p, foreshadows: Array.from({ length: 9 }, (_, i) => ({ id: 'f' + i, description: '복선 ' + i, planted_ep: i + 1, status: 'open' })) }, 1)]""", {"p": p})
    near, found, none, many = got
    # 열린 것 먼저, 그 안에서 6화에 가까운 차례(fs-lamp 는 6화에 걸린 문장이 있다), 회수한 것은 뒤
    assert [r["id"] for r in near["rows"]] == ["fs-lamp", "fs-map", "fs-door", "fs-key"]
    assert near["rows"][0] == {"id": "fs-lamp", "d": "깜박이는 등불", "open": True, "planted": 2, "seen": 6, "payoff": 0}
    assert [r["id"] for r in found["rows"]] == ["fs-key"]  # 띄어쓰기를 빼고 찾는다
    assert none == {"rows": [], "more": 0}
    assert len(many["rows"]) == 6 and many["more"] == 3


@needs_node
def test_overview_detail_and_empty_html():
    p = _project()
    c = _center(p)
    got = run_js(FILES, """(() => {
      S.name = 'w'; S.project = data.p; S.fs = data.c;
      S.fsSel = ''; const overview = viewForeshadow();
      S.fsSel = 'fs-lamp'; const detail = viewForeshadow();
      S.fsEdit = 'fs-lamp'; const editing = viewForeshadow(); S.fsEdit = '';
      S.fsResolving = 'fs-lamp'; const resolving = viewForeshadow(); S.fsResolving = '';
      S.fsSel = 'nope'; const lost = viewForeshadow();
      S.fs = { ...data.c, total: 0, open: 0, resolved: 0, items: [] }; S.fsSel = ''; const empty = viewForeshadow();
      return { overview, detail, editing, resolving, lost, empty };
    })()""", {"p": dump(p), "c": c})
    o = got["overview"]
    assert 'class="outline-wrap fs-wrap"' in o and 'id="fs-toc"' in o
    assert 'role="tablist"' not in o and 'role="group" aria-label="보이는 복선"' in o
    assert 'id="fs-todo"' in o and "6화에서 다시 걸기" in o and 'href="#/p/w/write/6"' in o
    assert 'href="#/p/w/foreshadow/fs-lamp"' in o and "앞으로 회수할 것" in o and "플롯에 아직 없음" in o
    assert 'style="color' not in o and "background:var(--red" not in o  # 색은 클래스로만
    assert o.count('class="btn primary"') == 1
    d = got["detail"]
    assert "<h1>깜박이는 등불</h1>" in d and 'aria-current="page"' in d
    assert "본문에 걸린 문장 3" in d and "6화에서 다시 걸기" in d and "지금 · 9화까지 반영했어요" in d
    assert 'data-action="fsResolveGo"' in d and 'aria-label="복선 더 보기"' in d
    assert 'id="fs-plan"' in d and ">고치기</button>" in d
    assert 'id="fs-d-fs-lamp"' in got["editing"] and "고치는 중" in got["editing"] and 'data-action="fsResolveGo"' not in got["editing"]
    assert 'id="fs-r-fs-lamp"' in got["resolving"] and 'data-action="fsResolveGo"' not in got["resolving"]
    assert "복선을 찾지 못했어요" in got["lost"] and 'id="fs-todo"' in got["lost"]
    e = got["empty"]
    assert 'class="empty"' in e and "아직 복선이 없어요" in e and e.count('class="btn primary"') == 1 and "fs-toc" not in e


@needs_node
def test_link_box_html():
    p = dump(_project())
    got = run_js(FILES, """(() => {
      S.project = data.p;
      const base = { n: 6, start: 0, text: '등불이 다시 흔들렸다.', mode: 'foreshadow', q: '', fid: 'fs-lamp', kind: 'plant', desc: '', scope: 'arc', due: '' };
      return [fsLinkHtml({ ...base, way: 'pick' }), fsLinkHtml({ ...base, way: 'new', desc: '새 <복선>' }), fsLinkHtml({ ...base, way: 'pick', q: '없는말' })];
    })()""", {"p": p})
    pick, new, none = got
    assert "6화 문장을 복선에 걸기" in pick and 'id="fs-find"' in pick and 'role="radiogroup"' in pick
    assert 'value="fs-lamp" checked' in pick and "6화 가까이 나온 복선" in pick
    assert 'aria-pressed="true" data-action="fsLinkKind" data-arg="plant"' in pick
    assert 'data-action="selCancel"' in pick and ">걸기</button>" in pick
    assert 'id="fs-pick-d"' in new and "새 &lt;복선&gt;" in new and 'id="fs-pick-s"' in new and 'id="fs-pick-u"' in new and ">심기</button>" in new
    assert "맞는 복선이 없어요" in none


@needs_node
def test_review_clue_rows_use_meaning_chips():
    got = run_js(FILES, """(() => {
      S.project = data.p;
      const d = { foreshadow_planted: [], foreshadow_clues: [{ foreshadow: 'fs-key', kind: 'payoff', quote: '그 열쇠가 문을 열었다.' }, { foreshadow: 'fs-lamp', kind: 'plant', quote: '등불' }] };
      return fsClueRows(d, (k) => `<input id="pk-${k}">`, 0);
    })()""", {"p": dump(_project())})
    assert '<span class="chip ok">회수한 문장</span>' in got and '<span class="chip">다시 떠올린 문장</span>' in got
    assert "finalized" not in got and "confirmed" not in got


@needs_node
def test_planted_episode_is_first_plant_without_clue_there():
    """심은 화에 걸린 문장이 없고 뒤 화에만 문장이 있으면, 심은 화가 '심음'이고 뒤 문장은 '다시 떠올림'이다."""
    x = {"id": "f", "description": "d", "planted_ep": 3, "status": "open", "scope": "arc", "due_ep": None, "payoff_ep": None,
         "plants": [{"episode": 8, "quote": "q", "by": "author", "broken": False}], "payoffs": [], "last_seen": 8,
         "planned": [], "overdue": False, "stale": False, "broken": 0}
    got = run_js(FILES, "[fsFlow(data.x, 9).map((e) => [e.ep, e.label]), fsMarks(data.x).map((m) => [m.kind, m.ep, m.title])]", {"x": x})
    assert got[0] == [[3, "심음"], [8, "다시 떠올림"], [9, "지금 · 9화까지 반영했어요"]]
    assert got[1] == [["plant", 3, "3화 심음"], ["plant", 8, "8화 다시 떠올림"]]


@needs_node
def test_due_episode_reached_is_overdue_everywhere():
    """예정 화까지 반영했는데 회수하지 않은 복선은 손볼 것에 들고, 앞으로 회수할 것 · 흐름의 앞으로 줄에 남지 않는다."""
    p = _project()
    p.foreshadows[3].due_ep = 9  # fs-map: 9화까지 반영
    c = _center(p)
    m = next(x for x in c["items"] if x["id"] == "fs-map")
    assert m["overdue"] is True
    got = run_js(FILES, """(() => {
      const m = data.c.items.find((x) => x.id === 'fs-map');
      return [fsTodo(data.c).filter((r) => r.id === 'fs-map').map((r) => r.label), fsAhead(data.c).filter((r) => r.items.some((y) => y.id === 'fs-map')).length,
        fsFlow(m, data.c.done).filter((e) => e.kind === 'due').map((e) => [e.ep, !!e.late, !!e.future])];
    })()""", {"c": c})
    assert got == [["예정 지남"], 0, [[9, True, False]]]


@needs_node
def test_single_episode_tick_stays_on_axis():
    got = run_js(FILES, "fsTicks([1, 1, 1], 1, 1)", {})
    assert got == [{"ep": 1, "label": "1화 지금", "cls": "tk now first"}]


@needs_node
def test_toc_opens_resolved_group_for_current_and_todo_due_button():
    c = _center(_project())
    got = run_js(FILES, """(() => {
      S.name = 'w'; S.project = data.p; S.fs = data.c; S.fsDoneOpen = false;
      S.fsSel = 'fs-key'; const toc = fsToc(data.c);
      S.fsSel = ''; const todo = fsTodoCard(data.c);
      return [toc, todo];
    })()""", {"c": c, "p": dump(_project())})
    toc, todo = got
    assert 'data-action="fsDoneToggle" data-outline-keep aria-expanded="true"' in toc and 'href="#/p/w/foreshadow/fs-key" aria-current="page"' in toc
    assert 'data-action="fsDueGo" data-arg="fs-door"' in todo
