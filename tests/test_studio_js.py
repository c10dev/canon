"""문단 연습장(static/studio.js)의 시도 고치기 칸: 글을 S 에 두어 다른 버튼으로 다시 그려도 남고, 버릴 때는 묻는다. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js


@needs_node
def test_try_edit_text_survives_redraw_and_asks_before_drop():
    got = run_js(["app.js", "studio.js"], """(async () => {
      globalThis.clearInterval = () => {}; globalThis.AbortController = class { abort() {} }; globalThis.CSS = { escape: (x) => x };
      const calls = [];
      render = () => {};
      askConfirm = async (msg, o) => { calls.push(['ask', o.ok]); return false; };
      api = async (m, path, body) => { calls.push([m, path, body]); return S.stu; };
      S.stu = { id: 's1', tries: [{ no: 1, by: 'author', text: '처음 글', at: '' }, { no: 2, by: 'author', text: '둘째 글', at: '' }], measures: {} };
      S.stuForm = { title: '', card: {} };
      await actions.stuEditOpen(1);
      S.stuEditText = '고친 글';  // 칸의 data-local 이 적는 값
      fmtDateTime = () => '';
      const card = stuTryCard(S.stu.tries[0]).includes('고친 글');
      const kept = [stuEditDirty(), hasUnsaved()];
      await actions.stuEditOpen(2);  // 다른 시도를 열면 먼저 묻는다. 거절하면 그대로다
      await actions.stuEditCancel();
      const still = [S.stuEdit, S.stuEditText];
      await actions.stuEditSave(1);
      return { card, kept, still, calls };
    })()""", {})
    assert got["card"] is True
    assert got["kept"] == [True, True]
    assert got["still"] == [1, "고친 글"]
    assert got["calls"] == [["ask", "버리고 열기"], ["ask", "버리기"], ["PUT", "/studio/s1/tries/1", {"text": "고친 글"}]]


@needs_node
def test_view_prefs_pick_and_paragraphs():
    got = run_js(["app.js", "studio.js"], """(() => ({
      bad: stuViewPick({ lh: '9', gap: 'x' }),
      none: stuViewPick(null),
      good: stuViewPick({ lh: 2.2, gap: '1' }),
      paras: stuParas('첫 줄\\n\\n<둘>'),
    }))()""", {})
    assert got["bad"] == {"lh": "1.85", "gap": "0"}
    assert got["none"] == {"lh": "1.85", "gap": "0"}
    assert got["good"] == {"lh": "2.2", "gap": "1"}
    assert got["paras"] == "<p>첫 줄</p><p><br></p><p>&lt;둘&gt;</p>"
