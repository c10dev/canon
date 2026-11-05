"""역설계 실험 화면(static/revlab.js)이 고치던 글을 잃지 않는지: 다른 실험으로 옮기면 맡겨 두고 돌아오면 되살린다,
글 · 이름 고치기 칸은 S 에 묶여 다시 그려도 남는다. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

FILES = ["app.js", "cue.js", "revlab.js"]

LABS = {
    "/revlab/1": {"id": 1, "title": "첫 실험", "first": 1, "items": [{"number": 1, "head": "1화", "text": "원문", "chars": 2}]},
    "/revlab/2": {"id": 2, "title": "둘째 실험", "first": 5, "items": [{"number": 5, "head": "5화", "text": "다른 글", "chars": 4}]},
}


@needs_node
def test_switching_labs_keeps_drafts_for_each_lab():
    got = run_js(FILES, """(async () => {
      api = async (m, path) => structuredClone(data[path]);
      S.rev = { min_chars: 0 };
      const out = {};
      await revFetch(1);
      S.revAdd = '붙여 넣은 다음 화';
      S.revEpEdit = { n: 1, head: '1화', text: '고친 글', head0: '1화', text0: '원문' };
      revEditOpen();
      S.revEditDraft.text = '새로 붙인 글';
      out.before = [revUnsaved(), hasUnsaved(), leaveUnsaved()];
      await revFetch(2);  // 다른 실험: 칸은 닫히지만 버리지 않는다
      out.other = [S.revAdd, S.revEpEdit, S.revEdit, Object.keys(S.revKept), hasUnsaved()];
      await revFetch(1);  // 돌아오면 되살린다
      out.back = [S.revAdd, S.revEpEdit.text, S.revEdit, S.revEditDraft.text, Object.keys(S.revKept)];
      out.card = revEditCard().includes('새로 붙인 글');
      return out;
    })()""", LABS)
    assert got["before"] == [True, True, False]  # 화면을 옮겨도 남으므로 새로고침 · 탭 닫기에서만 묻는다
    assert got["other"] == [None, None, False, ["1"], True]
    assert got["back"] == ["붙여 넣은 다음 화", "고친 글", True, "새로 붙인 글", []]
    assert got["card"] is True


@needs_node
def test_untouched_drafts_are_not_kept():
    got = run_js(FILES, """(async () => {
      api = async (m, path) => structuredClone(data[path]);
      S.rev = { min_chars: 0 };
      await revFetch(1);
      S.revAdd = '   ';
      S.revEpEdit = { n: 1, head: '1화', text: '원문', head0: '1화', text0: '원문' };
      revEditOpen();
      const before = revUnsaved();
      await revFetch(2);
      return [before, Object.keys(S.revKept), revUnsaved()];
    })()""", LABS)
    assert got == [False, [], False]


@needs_node
def test_edit_card_saves_bound_values_and_close_asks():
    got = run_js(FILES, """(async () => {
      globalThis.clearInterval = () => {}; globalThis.AbortController = class { abort() {} }; globalThis.CSS = { escape: (x) => x };
      const calls = [];
      api = async (m, path, body) => { calls.push([m, path, body || null]); return m === 'GET' ? structuredClone(data[path]) : {}; };
      askConfirm = async (msg, o) => { calls.push(['ask', o.ok]); return false; };
      render = () => {};
      revLoad = async () => {};
      S.rev = { min_chars: 0 };
      await revFetch(1);
      calls.length = 0;
      await actions.revEditToggle();
      Object.assign(S.revEditDraft, { title: '바꾼 이름', first: '3', text: '' });
      await actions.revEditToggle();  // 고친 것이 있으면 닫기 전에 묻는다. 거절하면 그대로 열려 있다
      const closed = S.revEdit;
      await actions.revSaveEdit();
      return { calls, closed, after: [S.revEdit, S.revEditDraft] };
    })()""", LABS)
    assert got["closed"] is True
    assert got["calls"] == [["ask", "버리기"], ["PUT", "/revlab/1", {"title": "바꾼 이름", "text": None, "first": 3}]]
    assert got["after"] == [False, None]
