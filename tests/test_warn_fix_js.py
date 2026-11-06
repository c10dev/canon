"""상태 정리 경고의 'AI에게 고치기'(static/passage.js aiFixNow)가 첫 후보를 바로 본문에 넣는지,
후보가 없으면 본문을 두고 대화 패널을 여는지. 서버 호출은 가짜로 바꿔 순서만 본다. node 가 있을 때만 돈다."""
from .jsvm import dump, episode, needs_node, run_js

Q = "서윤은 화요일 아침에 등대로 갔다."
TEXT = "바람이 불었다. " + Q + " 문이 잠겨 있었다."
NEW = "서윤은 수요일 아침에 등대로 갔다."

FILES = ["app.js", "chat.js", "passage.js"]

# api 를 가짜로 바꿔 aiFixNow 를 돌린다. data.cands 가 비면 AI가 후보 없이 답한 경우
EXPR = """(async () => {
  const calls = [];
  const proj = (msgs, text, edits) => ({ ...data.project, chats: [{ topic: 'text:1', messages: msgs }],
    episodes: [{ ...data.project.episodes[0], text, edits }] });
  S.name = 'p';
  S.project = data.project;
  S.textDraft = {};
  run = async (label, fn) => fn();
  saveIfDirty = async () => calls.push('save');
  flushText = async () => calls.push('flush');
  render = () => {};
  toast = (msg, err) => calls.push(['toast', msg, !!err]);
  undoToast = (msg, id) => calls.push(['undo', msg, id]);
  api = async (method, path, body) => {
    calls.push([method, path, body]);
    const msgs = [{ role: 'user', text: body.message || '' }, { role: 'ai', text: '답', passage: { candidates: data.cands } }];
    if (path.endsWith('/apply')) {
      const at = data.text.indexOf(data.q);
      return proj(msgs, data.text.replace(data.q, data.cands[0].text), [{ id: 'e1', start: at, before: data.q, after: data.cands[0].text }]);
    }
    return proj(msgs, data.text, []);
  };
  const at = data.text.indexOf(data.q);
  await aiFixNow(1, data.q, at, '상태 정리 경고: «' + data.q + '» 요일이 어긋나요');
  return { calls, text: ep(1).text, sel: S.sel, chatOpen: !!S.chatOpen, quiet: !!(S.selFocus && S.selFocus.quiet) };
})()"""


def _data(cands):
    e = episode(1, status="written", text=TEXT)
    return {"project": {"meta": {"title": "t"}, "episodes": [dump(e)], "chats": []}, "text": TEXT, "q": Q, "cands": cands}


@needs_node
def test_ai_fix_now_puts_first_candidate():
    got = run_js(FILES, EXPR, _data([{"text": NEW, "note": ""}, {"text": "다른 안", "note": ""}]))
    calls = got["calls"]
    assert calls[:2] == ["save", "flush"]  # 저장하지 않은 본문을 먼저 저장한다
    send, apply, undo = calls[2], calls[3], calls[4]
    assert send[:2] == ["POST", "/projects/p/chat/text%3A1"]
    assert send[2]["selection"] == {"start": TEXT.index(Q), "text": Q}
    assert send[2]["message"].startswith("상태 정리 경고:")
    assert apply[:2] == ["POST", "/projects/p/chat/text%3A1/1/apply"] and apply[2] == {"candidate": 0}
    assert undo == ["undo", "AI가 고쳤어요.", "e1"]
    assert NEW in got["text"]
    assert got["sel"] == {"n": 1, "start": TEXT.index(Q), "text": NEW}  # 이어 고치면 넣은 글을 고른다
    assert got["quiet"] is True  # 손가락 기기에서는 넣은 글을 고르기만 하고 본문 칸에 포커스하지 않는다 (syncPassage)


@needs_node
def test_ai_fix_now_without_candidates_opens_chat():
    got = run_js(FILES, EXPR, _data([]))
    calls = got["calls"]
    assert [c[1] for c in calls if c[0] == "POST"] == ["/projects/p/chat/text%3A1"]  # 후보가 없으면 적용하지 않는다
    assert ["toast", "AI가 고친 글을 내지 않았어요. 대화 패널에서 답을 보세요", True] in calls
    assert got["text"] == TEXT
    assert got["chatOpen"] is True
    assert got["sel"] == {"n": 1, "start": TEXT.index(Q), "text": Q}


# 상태 승인 화면에서 누른 경고: 집필 화면을 다 그린 뒤 고치도록 goThen 에 맡긴다 (저장 확인 창이 떠도 옛 화면에서 돌지 않게)
WARN_PICK = """(() => {
  S.name = 'p';
  S.project = data.project;
  S.textDraft = {};
  S.route = ['p', 'p', 'review', '1'];
  S.deltas = { 1: { warnings: ['인물이 «' + data.q + '» 라고 했는데 상태와 어긋나요'] } };
  const got = [];
  goThen = (hash, fn) => got.push(hash);
  actions.warnPick('1:0:ask');
  return got;
})()"""


@needs_node
def test_warn_pick_waits_for_write_screen():
    got = run_js(FILES, WARN_PICK, _data([]))
    assert got == ["#/p/p/write/1"]


# 본문 밖에서 시작한 터치의 touchend · mouseup 은 본문 칸에 남은 선택으로 고른 부분 도구를 띄우지 않는다
ON_SELECT = """(() => {
  S.project = data.project;
  S.textDraft = {};
  let queued = 0;
  setTimeout = () => { queued++; };
  const ta = { matches: (q) => q === 'textarea[data-draft]', dataset: { draft: '1' } };
  outsideTouch = Date.now();
  onSelect({ type: 'touchend', target: {} });
  onSelect({ type: 'mouseup', target: ta });
  const blocked = queued;
  outsideTouch = 0;
  onSelect({ type: 'touchend', target: ta });
  return { blocked, after: queued };
})()"""


@needs_node
def test_outside_touch_does_not_reopen_tool():
    got = run_js(FILES, ON_SELECT, _data([]))
    assert got == {"blocked": 0, "after": 1}


# 휴대폰 시트는 지금 고른 부분의 후보가 왔을 때만 높인다(.has-cands). 다른 부분을 새로 고르면 옛 후보로 본문을 가리지 않는다
CANDS = """(() => {
  const msgs = [{ role: 'user', text: '더 짧게', selection: { start: 0, text: data.q } },
    { role: 'ai', text: '답', selection: { start: 0, text: data.q }, passage: { candidates: [{ text: '새 글', note: '' }] } }];
  S.name = 'p';
  S.project = { ...data.project, chats: [{ topic: 'text:1', messages: msgs }] };
  S.textDraft = {};
  S.route = ['p', 'p', 'write', '1'];
  S.chatOpen = true;
  S.presets = [];
  const tall = (sel) => { S.sel = sel; return chatPanel('text:1').includes('has-cands'); };
  return { same: tall({ n: 1, start: 0, text: data.q }), other: tall({ n: 1, start: 0, text: '바람이 불었다.' }), none: tall(null) };
})()"""


@needs_node
def test_sheet_grows_only_for_current_candidates():
    got = run_js(FILES, CANDS, _data([]))
    assert got == {"same": True, "other": False, "none": False}
