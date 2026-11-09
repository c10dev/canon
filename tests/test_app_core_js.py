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
        {"msg": "서버에 연결하지 못했어요", "err": True, "acts": ["다시 시도"]},  # 서버가 꺼졌으면 AI 설정으로 못 고친다
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
def test_run_retry_false_offers_no_retry():
    got = run_js(["app.js"], """(async () => {
      const acts = [];
      toast = (msg, err, opt = {}) => acts.push(...(opt.actions || []).map((a) => a.label));
      render = () => {};
      clearInterval = () => {};
      AbortController = class { constructor() { this.signal = {}; } abort() {} };
      await run('저장하는 중', async () => { throw Object.assign(new Error('저장 실패'), { status: 500 }); }, { render: 'never', retry: false });
      return acts;
    })()""", {})
    assert got == []


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
def test_discard_resets_only_open_editor_drafts():
    # 버리고 이동을 고른 편집기만 초안을 비운다. 저장하지 않은 입력이 없던 편집기는 그대로 둔다
    got = run_js(["app.js"], """(() => {
      const calls = [];
      onEditDiscard('a', () => calls.push('a'));
      onEditDiscard('b', () => calls.push('b'));
      S.editDrafts = { a: true, b: false };
      discardEditDrafts();
      return { calls, left: S.editDrafts };
    })()""", {})
    assert got == {"calls": ["a"], "left": {}}


@needs_node
def test_toast_text_goes_to_live_regions():
    got = run_js(["app.js"], """(() => {
      const box = () => { const b = { kids: [], appendChild(n) { b.kids.push(n); n.remove = () => { b.kids = b.kids.filter((x) => x !== n); }; } }; return b; };
      const boxes = { '#sr-live': box(), '#sr-alert': box() };
      const later = [];
      document = { querySelector: (q) => boxes[q] || null, createElement: () => ({ textContent: '' }) };
      setTimeout = (f) => later.push(f);
      toastSay('저장했어요', false);
      toastSay('저장했어요', false);  // 같은 글이 이어 와도 줄을 따로 덧붙여 둘 다 읽힌다
      toastSay('저장하지 못했어요', true);
      const read = (b) => b.kids.map((n) => n.textContent);
      const out = { live: read(boxes['#sr-live']), alert: read(boxes['#sr-alert']) };
      later.forEach((f) => f());
      out.after = read(boxes['#sr-live']).length;
      return out;
    })()""", {})
    assert got == {"live": ["저장했어요", "저장했어요"], "alert": ["저장하지 못했어요"], "after": 0}


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


@needs_node
def test_check_saves_dirty_project_before_body_draft():
    got = run_js(["app.js", "chat.js", "passage.js", "flow.js"], """(async () => {
      const calls = [];
      S.name = 't';
      S.route = ['p', 't', 'check', '1'];
      S.textDraft = { 1: '고친 본문' };
      S.dirty = true;
      askConfirm = async (msg, o) => { calls.push(['ask', o.ok]); return false; };
      save = async () => { calls.push(['save']); S.dirty = false; };
      api = async (m, path) => { calls.push([m, path]); return { episodes: [], relationships: [] }; };
      startJob = async (kind, n) => { calls.push(['job', kind, n, S.dirty]); };
      flowStateToo = () => false;
      await actions.checkEp('1');  // 저장을 거절하면 본문도 작품도 건드리지 않는다
      const refused = calls.splice(0);
      askConfirm = async (msg, o) => { calls.push(['ask', o.ok]); return true; };
      await actions.flowCheck('1');
      return { refused, calls, left: Object.keys(S.textDraft) };
    })()""", {})
    assert got["refused"] == [["ask", "저장하고 시작하기"]]
    assert got["calls"] == [["ask", "저장하고 시작하기"], ["save"], ["PUT", "/projects/t/episodes/1/text"], ["job", "check", 1, False]]
    assert got["left"] == []


def test_confirmed_leave_clears_edit_drafts():
    # 화면 이동 처리기는 vm 대역 window 에 걸려 직접 부를 수 없다. 이동이 이어지는 자리에서 키를 모두 비우는지 글로 본다
    from .jsvm import STATIC
    src = (STATIC / "app.js").read_text(encoding="utf-8")
    body = src[src.index("window.addEventListener('hashchange'"):]
    body = body[:body.index("await route();")]
    assert "if (leaveUnsaved())" in body
    tail = body[body.index("lastHash = location.hash;"):]
    assert "S.libDirty = false;" in tail and "discardEditDrafts();" in tail


@needs_node
def test_leave_guard_counts_storyboard_and_cue_edits():
    # 스토리보드 · 큐 시트 고침은 화면을 옮겨도 S 에 남는다. 새로고침 · 탭 닫기(hasUnsaved)에서만 묻는다
    got = run_js(["app.js", "board.js"], """(() => {
      S.name = 'w';
      S.project = { episodes: [{ plot: { number: 3 }, storyboard: { scenes: [], time: '아침' } }] };
      const out = {};
      const both = () => [hasUnsaved(), leaveUnsaved()];
      S.boardEdit = { key: 'w:3', draft: { scenes: [], time: '아침' } };
      out.opened = both();  // 열기만 하고 고치지 않았다
      S.boardEdit.draft.time = '밤';
      out.edited = both();
      S.boardEdit = { key: 'other:3', draft: { scenes: [], time: '아침' } };
      out.other = both();  // 다른 작품의 칸은 견줄 저장본이 없어 남은 것으로 센다
      S.boardEdit = null;
      S.boardAsk = { key: 'w:3', text: '  ' };
      out.blankAsk = both();
      S.boardAsk.text = '2장을 더 짧게';
      out.ask = both();
      S.boardAsk = null;
      S.cueEdits = { 'ep:3:w': { draft: {}, dirty: false } };
      out.cueClean = both();
      S.cueEdits['ep:3:w'].dirty = true;
      out.cue = both();
      return out;
    })()""", {})
    assert got == {"opened": [False, False], "edited": [True, False], "other": [True, False], "blankAsk": [False, False],
                   "ask": [True, False], "cueClean": [False, False], "cue": [True, False]}


@needs_node
def test_app_starts_when_storage_is_blocked():
    # 저장소를 막은 브라우저도 앱 전체를 읽고 기본값으로 연다. 집필 방식 바꾸기도 이번 화면에서는 된다
    import re

    from .jsvm import STATIC
    files = re.findall(r'src="/static/([a-z0-9-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))
    got = run_js(files, """(() => {
      const start = S.mode;
      render = () => {};
      actions.setMode('brief');
      return [start, S.mode];
    })()""", {}, block_storage=True)
    assert got == ["api", "brief"]


# run() 의 가림막 늦추기: 가짜 시계와 가짜 화면. '보인다'는 #busy 가 hidden 이 아니고 투명 표시(busy-wait)도 없는 때다
FAKE_BUSY = """
const timers = [];
const cleared = [];
setTimeout = (f, ms) => { timers.push({ f, ms }); return timers.length; };
clearTimeout = (id) => { if (id) cleared.push(id); };
clearInterval = () => {};
render = () => {};
toast = () => {};
AbortController = class { constructor() { this.signal = {}; } abort() {} };
const el = (extra = {}) => {
  const cls = new Set();
  const attrs = {};
  return Object.assign({ hidden: true, inert: false, textContent: '', focused: 0, isConnected: true,
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), toggle: (c, on) => (on ? cls.add(c) : cls.delete(c)), contains: (c) => cls.has(c) },
    setAttribute: (k, v) => { attrs[k] = String(v); }, removeAttribute: (k) => { delete attrs[k]; },
    getAttribute: (k) => (k in attrs ? attrs[k] : null), hasAttribute: (k) => k in attrs,
    focus() { this.focused += 1; } }, extra);
};
const btn = el({ matches: (q) => q.includes('button') });
const page = { '#busy': el(), '#busy-label': el(), '#busy-sec': el(), '#busy-stop': el(), '#busy .busy-box': el(), '#app': el(), '#hub-pop': el(), '#savebar': el() };
document = { querySelector: (q) => page[q] || null, activeElement: btn, body: {} };
const busy = page['#busy'];
const shown = () => !busy.hidden && !busy.classList.contains('busy-wait');
"""


@needs_node
def test_run_quick_work_never_darkens_screen():
    got = run_js(["app.js"], FAKE_BUSY + """(async () => {
      const during = {};
      const ok = await run('저장하는 중', async () => {
        Object.assign(during, { shown: shown(), blocking: !busy.hidden, inert: page['#app'].inert, boxFocus: page['#busy .busy-box'].focused,
          btnBusy: btn.getAttribute('aria-busy'), spin: btn.classList.contains('run-wait') });
      }, { render: 'never' });
      return { ok, during, delay: timers.map((t) => t.ms), cleared: cleared.length, everShown: shown(), hidden: busy.hidden,
        inert: page['#app'].inert, btnBusy: btn.getAttribute('aria-busy'), spin: btn.classList.contains('run-wait'), backFocus: btn.focused };
    })()""", {})
    assert got == {
        "ok": True,
        # 투명한 막은 바로 깔려 클릭을 막고, 뒤 화면 inert 와 상자 포커스도 바로 건다. 누른 버튼엔 기다림을 단다
        "during": {"shown": False, "blocking": True, "inert": True, "boxFocus": 1, "btnBusy": "true", "spin": True},
        "delay": [400], "cleared": 1, "everShown": False, "hidden": True,
        "inert": False, "btnBusy": None, "spin": False, "backFocus": 1,
    }


@needs_node
def test_run_slow_work_darkens_after_delay():
    got = run_js(["app.js"], FAKE_BUSY + """(async () => {
      let done;
      const out = {};
      const p = run('지우는 중', () => new Promise((r) => { done = r; }), { render: 'never' });
      out.before = shown();
      timers[0].f();  // 400ms 가 지났다
      out.after = shown();
      done();
      await p;
      out.end = { shown: shown(), hidden: busy.hidden, wait: busy.classList.contains('busy-wait') };
      return out;
    })()""", {})
    assert got == {"before": False, "after": True, "end": {"shown": False, "hidden": True, "wait": False}}


@needs_node
def test_run_now_darkens_at_once_and_keeps_job_button():
    got = run_js(["app.js"], FAKE_BUSY + """(async () => {
      btn.setAttribute('aria-busy', 'true');  // jobBtn 이 단 기다림은 run 이 떼지 않는다
      let at = null;
      await run('옮기는 중', async () => { at = { shown: shown(), spin: btn.classList.contains('run-wait') }; }, { render: 'never', now: true });
      return { at, timers: timers.length, btnBusy: btn.getAttribute('aria-busy') };
    })()""", {})
    assert got == {"at": {"shown": True, "spin": False}, "timers": 0, "btnBusy": "true"}
