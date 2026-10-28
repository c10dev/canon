"""집필 화면(static/write.js)의 이번 화 플롯 띠와 공통 펼침 메뉴(app.js menuBtn). node 가 있을 때만 돈다."""
from canon.schema import Project

from .jsvm import dump, episode, needs_node, run_js

FILES = ["app.js", "plot.js", "write.js", "chat.js", "passage.js", "timeline.js"]


def _project():
    p = Project()
    p.meta.target_episodes = 3
    p.episodes = [
        episode(1, plot={"events": ["정전", "손님", "편지"], "ending_hook": "열쇠가 남는다", "summary": "책방에 손님이 온다"}, text="본문",
                status="written", events_done=["손님"]),
        episode(2, plot={"events": ["열쇠"], "ending_hook": "", "summary": "옛집에 간다"}),
    ]
    return dump(p)


@needs_node
def test_menu_draws_panel_only_when_open():
    expr = """const calls = [];
      const body = () => { calls.push(1); return '<b>안</b>'; };
      const closed = menuBtn('copy', '▾', body);
      S.popMenu = 'copy';
      const open = menuBtn('copy', '▾', body, { aria: '복사 설정' });
      [closed, open, calls.length]"""
    closed, open_, calls = run_js(FILES, expr, None)
    assert 'aria-expanded="false"' in closed and "pop-panel" not in closed
    assert 'aria-expanded="true"' in open_ and 'id="pop-copy"' in open_ and "<b>안</b>" in open_
    assert 'aria-label="복사 설정"' in open_
    assert calls == 1  # 닫힌 메뉴는 창 내용을 만들지 않는다


@needs_node
def test_plot_strip_starts_open_without_body():
    expr = """S.project = data; S.name = 'lh';
      const before = [plotOpenOf(1), plotOpenOf(2)];
      S.plotOpen['lh:2'] = false;
      [before, plotOpenOf(2)]"""
    (with_body, without_body), after = run_js(FILES, expr, _project())
    assert with_body is False  # 본문이 있는 화는 기억한 값(없으면 접힘)
    assert without_body is True  # 본문이 없는 화는 펼쳐서 시작
    assert after is False  # 이 화에서 고른 값을 따른다


@needs_node
def test_plot_strip_row_shows_hook_and_event_count():
    expr = """S.project = data; S.name = 'lh'; S.route = ['p', 'lh', 'write', '1'];
      S.jobs = []; S.plotOpen['lh:1'] = false;
      const shut = plotStrip(1, null);
      S.plotOpen['lh:2'] = true;
      const open = plotStrip(2, null);
      [shut.row, shut.body, open.row, open.body]"""
    row1, body1, row2, body2 = run_js(FILES, expr, _project())
    assert "엔딩 훅" in row1 and "열쇠가 남는다" in row1 and "사건 1/3" in row1  # 체크한 '손님' 하나
    assert 'aria-expanded="false"' in row1 and body1 == ""
    assert "옛집에 간다" in row2 and "엔딩 훅" not in row2  # 엔딩 훅이 없으면 줄거리
    assert 'aria-expanded="true"' in row2 and 'id="wp-body"' in body2 and 'data-ev="2:0"' in body2
    assert "wp-step goal" not in body2  # 엔딩 훅이 없으면 도착점도 없다


@needs_node
def test_progress_line_marks_done_now_and_goal():
    expr = """S.project = data; S.name = 'lh'; S.route = ['p', 'lh', 'write', '1']; S.jobs = [];
      S.plotOpen['lh:1'] = true;
      const body = plotStrip(1, null).body;
      P().episodes[0].events_done = ['정전', '손님', '편지'];
      const all = plotStrip(1, null).body;
      P().episodes[0].plot.events[1] = '손님이 온다';  // 사건 글을 고치면 그 체크는 풀린다
      [body, all, doneEvents(P().episodes[0])]"""
    body, all_, after = run_js(FILES, expr, _project())
    steps = body.split('<li class="wp-step ')[1:]
    assert [s.split('"')[0] for s in steps] == ["now", "done", "todo", "goal"]  # '손님'만 체크: 첫 사건이 지금
    assert "checked" in steps[1] and "checked" not in steps[0] and "지금" in steps[0]
    assert "열쇠가 남는다" in steps[3] and "도착" not in steps[3]
    assert "도착" in all_.split('wp-step goal')[1]  # 모두 체크하면 도착점에 '도착'
    assert after == [True, False, True]
