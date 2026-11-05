"""app.js 뼈대의 작은 규칙: 위험한 확인의 첫 포커스, 실패 말풍선의 '다시 시도' · '설정', 떠날 때 묻는 기준(S.editDrafts · 가격표),
말풍선 낭독 칸, 검수 시작 전 본문 초안 저장. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

# 대화상자 대역: 어느 버튼에 포커스했는지 남긴다
FAKE_DLG = """
const seen = { focus: null };
showDialog = (id, html) => ({ open: true, dataset: { ask: '1' }, returnValue: '', addEventListener() {}, close() {},
  querySelector: (sel) => (html.includes(sel.slice(1, -1)) ? { focus() { seen.focus = sel; }, select() {} } : null) });
"""


@needs_node
def test_danger_confirm_focuses_cancel():
    got = run_js(["app.js"], FAKE_DLG + """(() => {
      const out = {};
      askConfirm('지울까요?', { ok: '지우기', danger: true }); out.danger = seen.focus;
      askConfirm('바꿀까요?'); out.plain = seen.focus;
      askConfirm('이동할까요?', { ok: '이동하기', danger: true, alt: '저장하고 이동' }); out.alt = seen.focus;
      askConfirm('이동할까요?', { ok: '이동하기', danger: true, alt: '' }); out.noAlt = seen.focus;
      return out;
    })()""", {})
    assert got == {"danger": '[data-ask=""]', "plain": '[data-ask="ok"]', "alt": '[data-ask="alt"]', "noAlt": '[data-ask=""]'}


@needs_node
def test_error_toast_offers_retry_only_when_it_can_help():
    got = run_js(["app.js"], """(() => {
      const shown = [];
      toast = (msg, err, opt = {}) => shown.push({ msg, err: !!err, acts: (opt.actions || []).map((a) => a.label) });
      const retry = () => {};
      const e = (msg, status, code) => Object.assign(new Error(msg), { status, code });
      showError(e('AI 응답이 비었어요', 500), { retry });
      showError(e('서버에 연결하지 못했어요', 0), { retry });
      showError(e('제목을 적으세요', 400), { retry });
      showError(e('기다리지 않기로 했어요', 0, 'aborted'), { retry });
      showError(new Error('화면 안 오류'), { retry });
      showError(e('API 키 한도를 넘었어요', 429), { retry });
      showError(e('AI 응답이 비었어요', 500));
      return shown;
    })()""", {})
    assert got == [
        {"msg": "AI 응답이 비었어요", "err": True, "acts": ["다시 시도"]},
        {"msg": "서버에 연결하지 못했어요", "err": True, "acts": ["다시 시도", "설정"]},
        {"msg": "제목을 적으세요", "err": True, "acts": []},
        {"msg": "기다리지 않기로 했어요", "err": False, "acts": []},
        {"msg": "화면 안 오류", "err": True, "acts": []},
        {"msg": "API 키 한도를 넘었어요", "err": True, "acts": ["다시 시도", "설정"]},
        {"msg": "AI 응답이 비었어요", "err": True, "acts": []},
    ]


@needs_node
def test_run_retry_reruns_same_action():
    got = run_js(["app.js"], """(async () => {
      let tries = 0;
      let again = null;
      toast = (msg, err, opt = {}) => { const a = (opt.actions || []).find((x) => x.label === '다시 시도'); if (a) again = a.run; };
      render = () => {};
      clearInterval = () => {};
      AbortController = class { constructor() { this.signal = {}; } abort() {} };
      const fn = async () => { tries += 1; if (tries === 1) throw Object.assign(new Error('AI 호출 실패'), { status: 502 }); };
      const first = await run('받는 중', fn, { render: 'never' });
      const second = await again();
      return { first, second, tries };
    })()""", {})
    assert got == {"first": False, "second": True, "tries": 2}


@needs_node
def test_leave_guard_counts_inline_editors_and_prices():
    got = run_js(["app.js"], """(() => {
      const out = { fresh: [hasUnsaved(), leaveUnsaved()] };
      S.editDrafts.someEditor = true;
      out.editor = [hasUnsaved(), leaveUnsaved()];
      S.editDrafts.someEditor = false;
      S.priceDirty = true;
      out.price = [hasUnsaved(), leaveUnsaved()];  // 가격표는 화면을 옮겨도 남는다: 새로고침 · 탭 닫기에서만 묻는다
      return out;
    })()""", {})
    assert got == {"fresh": [False, False], "editor": [True, True], "price": [True, False]}


@needs_node
def test_toast_text_goes_to_live_regions():
    got = run_js(["app.js"], """(() => {
      const boxes = { '#sr-live': { textContent: '' }, '#sr-alert': { textContent: '' } };
      document = { querySelector: (q) => boxes[q] || null };
      setTimeout = (f) => f();
      toastSay('저장했어요', false);
      toastSay('저장하지 못했어요', true);
      return { live: boxes['#sr-live'].textContent, alert: boxes['#sr-alert'].textContent };
    })()""", {})
    assert got == {"live": "저장했어요", "alert": "저장하지 못했어요"}


@needs_node
def test_check_saves_body_draft_first():
    got = run_js(["app.js", "chat.js", "passage.js", "flow.js"], """(async () => {
      const calls = [];
      S.name = 't';
      S.route = ['p', 't', 'check', '1'];
      S.textDraft = { 1: '고친 본문', 2: '다른 화' };
      api = async (m, path, body) => { calls.push([m, path, body && body.text]); return { episodes: [], relationships: [] }; };
      startJob = async (kind, n) => { calls.push(['job', kind, n]); };
      flowStateToo = () => false;
      await actions.checkEp('1');
      S.textDraft[1] = '또 고침';
      await actions.flowCheck('1');
      return { calls, left: Object.keys(S.textDraft) };
    })()""", {})
    assert got["calls"] == [
        ["PUT", "/projects/t/episodes/1/text", "고친 본문"], ["job", "check", 1],
        ["PUT", "/projects/t/episodes/1/text", "또 고침"], ["job", "check", 1],
    ]
    assert got["left"] == ["2"]
