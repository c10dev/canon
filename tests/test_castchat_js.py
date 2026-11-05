"""대화 보내기(chat.js chatSend) · 줄기 지우기(lines.js lineDelete) · 관계 보정(cast.js tieFix)이 저장하지 않은 변경을
말없이 저장하지 않고 먼저 묻는지, 취소하면 아무것도 보내지 않는지. 관계도 다시 그리기(cast.js castSwap)가 포커스를 되돌리는지,
새 AI 답만 숨은 알림 칸(chat.js chatAnnounce)에 들어가는지. node 가 있을 때만 돈다."""
from canon.schema import Project

from .jsvm import dump, needs_node, run_js

FILES = ["app.js", "statwin.js", "chat.js", "agent.js", "cast.js", "lines.js"]

# 묻기 · 저장 · 서버 부르기를 기록하는 대역. answers 는 askConfirm 이 차례로 돌려줄 답
FAKE = """
const log = [];
let answers = [];
askConfirm = async (text, o) => { log.push(['ask', text, o && o.ok]); return answers.shift(); };
saveIfDirty = async () => { log.push(['save']); };
api = async (m, url) => { log.push(['api', m, url]); return S.project; };
render = () => {};
redrawChat = () => {};
toast = () => {};
"""


@needs_node
def test_chat_send_asks_before_save_and_cancel_keeps_draft():
    expr = FAKE + """(async () => {
      S.project = data;
      S.name = 'p'; S.chatTopic = 'plot'; S.dirty = true; S.chatDraft = '고쳐 줘';
      answers = [false];
      await legacyChatSend();  // 플롯 대화는 agent.js 가 가로채므로 chat.js 의 보내기를 바로 부른다
      return { log, pending: S.chatPending, draft: S.chatDraft };
    })()"""
    got = run_js(FILES, expr, dump(Project()))
    assert got["log"] == [["ask", "저장하지 않은 변경이 있어요. 저장하고 보낼까요?", "저장하고 보내기"]]
    assert got["pending"] is None
    assert got["draft"] == "고쳐 줘"


@needs_node
def test_line_delete_and_tie_fix_ask_before_save():
    expr = FAKE + """(async () => {
      S.project = { ...data, storylines: [{ id: 'l1', title: '복수' }] };
      S.name = 'p'; S.dirty = true;
      answers = [true, false];
      await actions.lineDelete('l1');
      const line = log.splice(0);
      answers = [true, false];
      await actions.tieFix('a|b|0');
      return { line, tie: log };
    })()"""
    got = run_js(FILES, expr, dump(Project()))
    assert [x[0] for x in got["line"]] == ["ask", "ask"]
    assert got["line"][1][1:] == ["저장하지 않은 변경이 있어요. 저장하고 줄기를 지울까요?", "저장하고 지우기"]
    assert [x[0] for x in got["tie"]] == ["ask", "ask"]
    assert got["tie"][1][1:] == ["저장하지 않은 변경이 있어요. 저장하고 관계를 보정할까요?", "저장하고 보정하기"]


@needs_node
def test_cast_swap_returns_focus():
    # el.innerHTML 을 바꾸면 새 요소들이 생긴다고 치는 작은 대역. 꺼진 버튼은 건너뛴다
    expr = """(() => {
      const mk = (action, arg, disabled = false) => ({ action, arg, disabled, focused: false,
        getAttribute(k) { return k === 'data-action' ? this.action : k === 'data-arg' ? this.arg : null; },
        focus() { this.focused = true; } });
      CSS = { escape: (s) => s };
      const make = (items) => {
        const el = { kids: [], contains: (x) => el.kids.includes(x),
          querySelectorAll: (sel) => el.kids.filter((k) => sel === `[data-action="${k.action}"]`) };
        Object.defineProperty(el, 'innerHTML', { set() { el.kids = items(); } });
        return el;
      };
      const out = [];
      const a = make(() => [mk('castMapPick', 'c:x'), mk('castMapPick', 'p:a|b')]);
      a.kids = [mk('castMapPick', 'p:a|b')];
      document = { activeElement: a.kids[0] };
      castSwap(a, '');
      out.push(a.kids.map((k) => k.focused));
      const z = make(() => [mk('castZoom', '1', true), mk('castZoom', '-1')]);
      z.kids = [mk('castZoom', '1')];
      document = { activeElement: z.kids[0] };
      castSwap(z, '');
      out.push(z.kids.map((k) => k.focused));
      return out;
    })()"""
    assert run_js(FILES, expr, dump(Project())) == [[False, True], [False, True]]


@needs_node
def test_chat_announce_only_new_reply():
    expr = """(() => {
      const live = { textContent: '' };
      let panel = true;
      document = { getElementById: (id) => (id === 'chat-live' ? live : null), querySelector: () => (panel ? {} : null) };
      S.name = 'p'; S.chatTopic = 'text:1';
      S.project = { ...data, chats: [{ topic: 'text:1', messages: [{ role: 'user', text: '질문' }, { role: 'ai', text: '옛 답' }] }] };
      const out = [];
      chatAnnounce(); out.push(live.textContent);  // 처음 연 패널: 옛 답은 알리지 않는다
      chatAnnounce(); out.push(live.textContent);  // 다시 그려도 그대로
      S.project.chats[0].messages.push({ role: 'user', text: '또' }, { role: 'ai', text: '새 답' });
      chatAnnounce(); out.push(live.textContent);
      S.chatTopic = 'text:2';
      chatAnnounce(); out.push(live.textContent);  // 다른 대화로 옮기면 알리지 않는다
      return out;
    })()"""
    assert run_js(FILES, expr, dump(Project())) == ["", "", "AI 답: 새 답", "AI 답: 새 답"]
