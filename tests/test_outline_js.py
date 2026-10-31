"""공용 목차 틀(static/outline.js): 목차 nav HTML · 열림 기억 · 지금 구역 고르기 · 틀 HTML.
node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

FILES = ["app.js", "outline.js"]


@needs_node
def test_pick_current_section():
    tops = [["a", -400], ["b", 80], ["c", 300]]
    got = run_js(FILES, """[
      outlinePick(data.tops),
      outlinePick(data.tops, { line: 40 }),
      outlinePick([['a', 200], ['b', 500]]),
      outlinePick([['a', 200], ['b', 500]], { first: false }),
      outlinePick(data.tops, { bottom: true }),
      outlinePick([['late', -10], ['early', -900]]),
      outlinePick([]),
    ]""", {"tops": tops})
    # 120px 줄을 지난 마지막 구역, 아무것도 안 지났으면 맨 위(또는 없음), 맨 아래면 마지막, 순서는 화면 위치로
    assert got == ["b", "a", "a", None, "c", "late", None]


@needs_node
def test_nav_has_button_only_with_now():
    got = run_js(FILES, """[
      outlineNav({ id: 'x-toc', label: '목차', now: '1 · 기본', body: '<a class="outline-item">줄</a>' }),
      outlineNav({ id: 'steps', label: '걸음', body: 'B', cls: 'steps', after: '<span>뒤</span>' }),
    ]""", {})
    wide, steps = got
    assert 'id="x-toc"' in wide and 'aria-label="목차"' in wide
    assert 'class="btn outline-now" data-action="outlineToggle" data-arg="x-toc" aria-expanded="false" aria-controls="x-toc-list"' in wide
    assert '<div class="outline-list" id="x-toc-list"><a class="outline-item">줄</a></div>' in wide
    assert 'outline-now' not in steps and 'class="outline steps"' in steps and steps.endswith('</div><span>뒤</span></nav>')


@needs_node
def test_open_state_survives_redraw():
    """펼친 목차를 다시 그려도(스크롤로 지금 구역이 바뀜) 열림과 aria-expanded 가 맞는다. 닫으면 함께 돌아온다."""
    got = run_js(FILES, """(() => {
      const nav = () => outlineNav({ id: 'x-toc', label: '목차', now: '지금', body: '' });
      outlineToggle('x-toc');
      const opened = nav();
      outlineToggle('x-toc');
      const closed = nav();
      outlineToggle('x-toc', true);
      outlineClose();
      return [opened, closed, nav(), OUTLINE_OPEN.size];
    })()""", {})
    opened, closed, after_close, left = got
    assert 'class="outline open"' in opened and 'aria-expanded="true"' in opened
    assert 'class="outline"' in closed and 'aria-expanded="false"' in closed
    assert 'aria-expanded="false"' in after_close and left == 0


@needs_node
def test_doc_wraps_toc_and_column():
    got = run_js(FILES, """[outlineDoc('<nav></nav>', '<div class="m"></div>'),
      outlineDoc('T', 'M', { wide: true, cls: 'rev-wrap' })]""", {})
    assert got[0] == '<div class="outline-wrap"><div class="outline-doc"><nav></nav><div class="m"></div></div></div>'
    assert got[1] == '<div class="outline-wrap rev-wrap"><div class="outline-doc wide">TM</div></div>'
