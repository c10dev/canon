"""상태 정리 경고의 'AI에게 고치기'(static/passage.js aiFixNow)가 한 요청(POST …/fix-now)으로 첫 후보를 넣는지,
기다리는 동안 화면을 잠그지 않고 그 화 본문만 잠그는지, 후보가 없으면 대화 에이전트를 열고 그 문장을 재료로 붙이는지,
비슷한 문장이면 바로 넣지 않는지, 저장하지 않은 다른 입력을 지키는지. 서버 호출은 가짜로 바꿔 본다. node 가 있을 때만 돈다."""
from .jsvm import dump, episode, needs_node, run_js

Q = "서윤은 화요일 아침에 등대로 갔다."
TEXT = "바람이 불었다. " + Q + " 문이 잠겨 있었다."
NEW = "서윤은 수요일 아침에 등대로 갔다."
W = "«" + Q + "» 요일이 어긋나요"

FILES = ["app.js", "chat.js", "passage.js"]

# api 를 가짜로 바꿔 aiFixNow 를 돌린다. data.cands 가 비면 AI가 후보 없이 답한 경우. data.dirty 면 저장하지 않은 다른 입력이 있다
EXPR = """(async () => {
  const calls = [];
  S.name = 'p';
  S.project = data.project;
  S.textDraft = data.draft ? { 1: data.text } : {};
  S.route = ['p', 'p', 'write', '1'];
  run = async (label, fn) => { calls.push(['run', label]); await fn(); return true; };
  saveIfDirty = async () => calls.push('save');
  flushText = async () => calls.push('flush');
  render = () => {};
  toast = (msg, err, opt) => calls.push(['toast', msg, !!err, ((opt || {}).actions || []).map((a) => a.label)]);
  let during = null;
  api = async (method, path, body) => {
    calls.push([method, path, body]);
    during = { fixing: aiFixing(1), lock: draftLocked() };
    if (data.dirty) P().meta.title = '고치던 제목';
    const at = data.text.indexOf(data.q);
    const ok = data.cands.length > 0;
    const msgs = [{ role: 'user', text: body.message }, { role: 'ai', text: '답', passage: ok ? { candidates: data.cands } : null, outcome: ok ? 'applied' : '' }];
    const edits = ok ? [{ id: 'e1', source: 'ai', start: at, before: data.q, after: data.cands[0].text, instruction: body.message, undone: false }] : [];
    const text = ok ? data.text.replace(data.q, data.cands[0].text) : data.text;
    return { project: { ...data.project, edit_rev: 2, chats: [{ topic: 'text:1', messages: msgs }], episodes: [{ ...data.project.episodes[0], text, edits }] }, edit: ok ? 'e1' : '' };
  };
  if (data.dirty) S.dirty = true;
  const at = data.text.indexOf(data.q);
  await aiFixNow(1, data.q, at, data.w);
  return { calls, during, after: aiFixing(1), text: ep(1).text, title: P().meta.title, chats: P().chats.length, rev: P().edit_rev,
    sel: S.sel, mat: S.agentMaterial || null, chatOpen: !!S.chatOpen, quiet: !!(S.selFocus && S.selFocus.quiet), tools: warnTools(1, 0, data.w) };
})()"""

# 본문 칸이 잠겼는지: marks.js draftBox 대신 같은 조건(aiFixing)을 본다
LOCK = "const draftLocked = () => aiFixing(1);\n"


def _data(cands, **kw):
    e = episode(1, status="written", text=TEXT)
    return {"project": {"meta": {"title": "t"}, "edit_rev": 1, "episodes": [dump(e)], "chats": []}, "text": TEXT, "q": Q, "w": W, "cands": cands, **kw}


def _run(data):
    return run_js(FILES, LOCK + EXPR, data)


@needs_node
def test_ai_fix_now_puts_first_candidate():
    got = _run(_data([{"text": NEW, "note": ""}, {"text": "다른 안", "note": ""}]))
    calls = got["calls"]
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 1 and posts[0][1] == "/projects/p/episodes/1/fix-now"  # 후보 받기와 넣기를 한 요청으로
    assert posts[0][2] == {"message": "상태 정리 경고: " + W, "selection": {"start": TEXT.index(Q), "text": Q}}
    assert not any(c[0] == "run" for c in calls if isinstance(c, list))  # 저장할 것이 없으면 기다림 상자를 띄우지 않는다
    assert got["during"] == {"fixing": True, "lock": True} and got["after"] is False  # 기다리는 동안 그 화 본문만 잠근다
    assert ["toast", "AI가 1화 경고 문장을 고쳤어요.", False, ["되돌리기", "상태 승인으로"]] in calls
    assert NEW in got["text"]
    assert got["sel"] == {"n": 1, "start": TEXT.index(Q), "text": NEW}  # 이어 고치면 넣은 글을 고른다
    assert got["quiet"] is True  # 손가락 기기에서는 넣은 글을 고르기만 하고 본문 칸에 포커스하지 않는다 (syncPassage)
    assert "AI가 고침" in got["tools"]  # 상태 승인 · 집필 화면의 경고 줄은 고친 경고에 표시를 단다


@needs_node
def test_ai_fix_now_saves_draft_first():
    got = _run(_data([{"text": NEW, "note": ""}], draft=True))
    assert got["calls"][:3] == [["run", "본문 저장하는 중"], "save", "flush"]  # 저장하지 않은 본문을 먼저 저장한다


@needs_node
def test_ai_fix_now_keeps_unsaved_input():
    """기다리는 사이 다른 칸을 고쳤으면 작품을 통째로 바꾸지 않고 그 화와 대화 기록만 받는다."""
    got = _run(_data([{"text": NEW, "note": ""}], dirty=True))
    assert got["title"] == "고치던 제목" and NEW in got["text"] and got["chats"] == 1 and got["rev"] == 2


@needs_node
def test_ai_fix_now_without_candidates_opens_chat():
    got = _run(_data([]))
    calls = got["calls"]
    assert ["toast", "AI가 1화 경고 문장을 고친 글을 내지 않았어요. AI 답: 답", True, []] in calls  # 답은 옛 기록 'text:1'에 남고 알림에도 보인다
    assert got["text"] == TEXT
    assert got["chatOpen"] is True
    assert got["sel"] == got["mat"] == {"n": 1, "start": TEXT.index(Q), "text": Q}  # 대화 에이전트의 재료로 붙는다


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


# 경고 문장이 본문에 그대로 한 번만 있을 때만 바로 넣는다. 비슷한 문장이면 재료로 붙이고 경고를 대화 에이전트 입력칸에 넣는다
NEAR = """(() => {
  S.name = 'p';
  S.project = data.project;
  S.textDraft = {};
  S.route = ['p', 'p', 'write', '1'];
  S.deltas = { 1: { warnings: [data.w] } };
  const got = [];
  render = () => {};
  aiFixNow = () => got.push('fix');
  toast = (msg) => got.push(msg.slice(0, 12));
  actions.warnPick('1:0:ask');
  return { got, draft: S.agentDraft, mat: S.agentMaterial || null, chatOpen: !!S.chatOpen, sel: S.sel, spot: warnSpot(data.w, data.text) };
})()"""


@needs_node
def test_warn_pick_near_sentence_goes_to_chat():
    w = "«서윤은 화요일에 등대로 갔다» 요일이 어긋나요"  # 옮겨 적은 글이 본문과 조금 다르다
    got = run_js(FILES, NEAR, _data([], w=w))
    assert got["spot"] == {"q": Q, "exact": False}
    assert "fix" not in got["got"] and got["draft"] == "상태 정리 경고: " + w and got["chatOpen"] is True
    assert got["sel"] == got["mat"] == {"n": 1, "start": TEXT.index(Q), "text": Q}
    twice = run_js(FILES, NEAR, _data([], text=TEXT + " " + Q))  # 같은 글이 두 곳이면 어느 쪽인지 몰라 바로 넣지 않는다
    assert twice["spot"]["exact"] is False
    exact = run_js(FILES, NEAR, _data([]))
    assert exact["spot"] == {"q": Q, "exact": True} and exact["got"] == ["fix"]


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


# 휴대폰 문장 고르기(passage.js sentenceRanges): 줄바꿈과 문장 끝(닫는 따옴표까지)에서 끊고 앞뒤 공백은 뺀다
@needs_node
def test_sentence_ranges():
    text = '바람이 불었다. 서윤은 등대 앞에 섰다.\n\n"됐어, 내가 할게." 그가 말했다!  끝'
    got = run_js(["app.js", "chat.js", "passage.js"], "sentenceRanges(data.t).map((r) => data.t.slice(r.start, r.end))", {"t": text})
    assert got == ["바람이 불었다.", "서윤은 등대 앞에 섰다.", '"됐어, 내가 할게."', "그가 말했다!", "끝"]
