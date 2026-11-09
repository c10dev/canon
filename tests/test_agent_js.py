"""대화 에이전트 패널(static/agent.js)의 권한 이름이 서버 canon/agent.py 와 같은지. node 가 있을 때만 돈다."""
from canon import agent

from .jsvm import needs_node, run_js


@needs_node
def test_mode_and_kind_labels_match_server():
    got = run_js(["app.js", "chat.js", "agent.js"],
                 "({ modes: Object.fromEntries(Object.entries(AGENT_MODES).map(([k, v]) => [k, v[0]])), kinds: AGENT_KINDS })", None)
    assert got["modes"] == agent.MODE_LABELS
    assert got["kinds"] == agent.KIND_LABELS


@needs_node
def test_step_wait_matches_server():
    got = run_js(["app.js", "chat.js", "agent.js"],
                 "({ wait: AGENT_STEP_WAIT, text: agentStepWait({ started: Date.now() / 1000 - 75 }),"
                 " step: agentStepWait({ started: 0, step_at: Date.now() / 1000 - 5 }),"
                 " limit: [agentStepLimit({ step_wait: 480 }), agentStepLimit({ step_wait: 0 }), agentStepLimit(null)] })", None)
    assert got["wait"] == agent.STEP_WAIT
    assert got["limit"] == [480, agent.STEP_WAIT, agent.STEP_WAIT]  # 작업이 알려 준 한도(Claude Code 는 더 길다)를 쓴다
    assert got["text"] == "이번 단계 1:15"
    assert got["step"] == "이번 단계 0:05"


@needs_node
def test_step_now_and_turn_end():
    """도는 단계는 AI 호출 사정(Job.retry)을 보이고, 끝난 턴은 단계 수와 걸린 시간을 보인다."""
    got = run_js(["app.js", "chat.js", "agent.js"], """(() => {
      S.agent = { max_steps: 8, sessions: [] };
      const t = { user: '3화', mode: '', steps: [{ kind: 'read', tool: 'read_plots', label: '3화', why: '' }], reply: '그대로 둘게요',
        writes: [], end: 'done', error: '', at: '2026-11-07T10:00:00+00:00', ended: '2026-11-07T10:01:12+00:00' };
      const s = { id: 'a', turns: [t] };
      return {
        idle: agentStepNow({ retry: '' }), retry: agentStepNow({ retry: 'AI 요청 한도에 걸려 60초 기다려요 (1/3)' }),
        took: agentTurnTook(t), short: agentTurnTook({ ...t, ended: '2026-11-07T10:00:45+00:00' }), old: agentTurnTook({ ...t, ended: '' }),
        html: agentTurn(s, t, 0), oldHtml: agentTurn(s, { ...t, ended: '' }, 0),
      };
    })()""", None)
    assert got["idle"] == "AI 응답을 기다리는 중"
    assert got["retry"] == "AI 요청 한도에 걸려 60초 기다려요 (1/3)"
    assert got["took"] == "1분 12초" and got["short"] == "45초" and got["old"] == ""
    assert "끝났어요 · 1단계 · 1분 12초" in got["html"]
    assert "끝났어요 · 1단계</div>" in got["oldHtml"]


@needs_node
def test_continue_keeps_project_data():
    """이어 하기 응답은 작업 정보라 project 칸이 작품 이름 글이다. 2026-11-09 그 글이 S.project 를 덮어
    화면이 'Cannot read properties of undefined (reading 'map')' 으로 깨졌다."""
    got = run_js(["app.js", "chat.js", "agent.js"], """(async () => {
      S.name = 'lh'; S.project = data; S.dirty = false; S.jobs = [];
      saveIfDirty = async () => {}; pollJobs = () => {}; agentLoad = async () => {}; render = () => {};
      await agentAct(async () => ({ id: 'j1', kind: 'agent', project: 'lh', status: 'running' }));
      const kept = S.project === data;
      await agentAct(async () => ({ project: { ...data, title: '새 제목' }, job: { id: 'j2', kind: 'agent', project: 'lh' } }));
      return { kept, title: S.project.title, jobs: S.jobs.map((j) => j.id) };
    })()""", {"title": "옛 제목", "episodes": []})
    assert got == {"kept": True, "title": "새 제목", "jobs": ["j1", "j2"]}


# ---------- 04a: 패널 하나 · 화면이 주는 대상 · 대상 고정 (docs/ux/specs/04-one-agent.md) ----------
import re  # noqa: E402

from canon.schema import Project  # noqa: E402

from .jsvm import STATIC, dump, episode  # noqa: E402

FILES = ["app.js", "chat.js", "agent.js"]


def _views() -> list[str]:
    """app.js drawApp 의 작품 화면 이름 (views 표). 화면이 늘면 이 시험도 저절로 그 화면을 본다."""
    src = (STATIC / "app.js").read_text(encoding="utf-8")
    table = re.search(r"const views = \{(.*?)\};", src, re.S).group(1)
    return re.findall(r"(\w+): ", table)


def _demo(serial: bool = False) -> dict:
    p = Project(episodes=[episode(n, plot={"title": f"{n}화 제목"}) for n in range(1, 6)])
    if serial:
        p.meta.form = "serial"
    return dump(p)


SETUP = """S.name = 'demo'; S.project = data.project; S.chatOpen = true; S.jobs = [];
  S.agent = { name: 'demo', sessions: data.sessions || [], legacy: 0, older: data.older || [], model: 'mock', max_steps: 8 };"""


def test_drawapp_paints_one_panel_and_screens_do_not():
    """패널은 drawApp 이 셸 끝에 하나만 붙인다. 화면 파일은 chatPanel 을 부르지 않고 옛 대화 주제만 알린다 (chatLegacy)."""
    src = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "</main>${chatDock()}</div>" in src
    assert "chatScreen(views[page] ? page : '', n)" in src
    for f in STATIC.glob("*.js"):
        if f.name not in ("chat.js",):
            assert "${chatPanel(" not in f.read_text(encoding="utf-8"), f.name


@needs_node
def test_every_project_screen_shows_the_same_agent_panel():
    pages = ["", *_views()]
    got = run_js(FILES, SETUP + """
      data.pages.map((page) => { S.route = ['p', 'demo', page, '3']; chatScreen(page, 3);
        const html = chatDock(); return [page, S.chatHere.target, html.includes('<aside class="chat-panel" aria-label="대화 에이전트">'), S.chatTopic]; })""",
                 {"project": _demo(), "pages": pages})
    assert all(on and topic == "plot" for _, _, on, topic in got), [g for g in got if not g[2]]
    target = {page: t for page, t, _, _ in got}
    assert {k: target[k] for k in ("write", "check", "review", "setup", "style")} == {
        "write": "text:3", "check": "text:3", "review": "text:3", "setup": "setup", "style": "style"}
    assert all(target[k] == "" for k in pages if k not in ("write", "check", "review", "setup", "style"))
    assert {"", "cast", "foreshadow", "atlas", "arc"} <= set(target)  # 작품 홈 · 인물 · 복선 · 지도처럼 옛날엔 패널이 없던 화면도


@needs_node
def test_plot_screen_target_and_text_names():
    got = run_js(FILES, SETUP + """(() => {
      S.route = ['p', 'demo', 'arc']; S.selArc = 2; chatScreen('arc', 0);
      const arc = S.chatHere.target;
      chatScreen('write', 99);  // 없는 화는 작품 전체
      const plotName = agentTargetText('');  // 장편 플롯 화면에서 아크를 고르지 않으면 플롯 쓰기는 본문이 없는 첫 아크로 간다
      S.route = ['p', 'demo', 'cast'];
      return { arc, missing: S.chatHere.target, plotName, names: ['text:3', 'setup', 'style', ''].map(agentTargetText) };
    })()""", {"project": _demo(serial=True)})
    assert got["arc"] == "arc:2" and got["missing"] == "" and got["plotName"] == "본문이 없는 첫 아크"
    assert got["names"] == ["3화 본문 3화 제목", "설정", "문체", "작품 전체"]


@needs_node
def test_target_follows_screen_unless_pinned_and_flashes_once():
    got = run_js(FILES, SETUP + """(() => {
      const go = (page, n) => { S.route = ['p', 'demo', page, String(n || '')]; chatScreen(page, n); return chatDock(); };
      S.agentSid = 'a'; S.agentFlash = null;
      go('write', 2); const first = S.agentFlash;
      const html = go('setup'); const flash = S.agentFlash; S.agentFlash = null;
      const scope = agentTurnScope();
      go('setup'); const again = S.agentFlash;
      S.agent.sessions[0].pinned = true;
      go('cast'); const pinnedFlash = S.agentFlash;
      return { first, flash, again, pinnedFlash, foot: html.includes('설정 ▾'), scope, pinnedScope: agentTurnScope(),
        pinBtn: html.includes('data-action="agentPin" aria-pressed="false"'), pinnedHtml: go('style').includes('data-action="agentPin" aria-pressed="true"'),
        pinnedTarget: agentTarget() };
    })()""", {"project": _demo(), "sessions": [{"id": "a", "topic": "agent", "title": "", "target": "ep:2", "pinned": False,
                                                "mode": "draft", "auto_kinds": [], "archived": False, "turns": []}]})
    assert got["first"] is None  # 패널을 처음 그릴 때는 알리지 않는다
    assert got["flash"] == "설정" and got["again"] is None and got["foot"] and got["pinBtn"]
    assert got["scope"] == {"act": "", "episode": 0, "draft": None, "target": "setup"}
    assert got["pinnedFlash"] == "2화 플롯 2화 제목"  # 고정하면 세션 대상(ep:2)을 보인다
    assert got["pinnedScope"] == {"act": "", "episode": 0, "draft": None}  # 고정한 세션은 화면 대상을 보내지 않는다
    assert got["pinnedHtml"] and got["pinnedTarget"] == "ep:2"


@needs_node
def test_legacy_switch_and_read_only_old_chats():
    """옛 대화가 남은 화면은 패널 머리에서 옛 대화로 바꾼다. 다른 화면에서는 '이전 대화'로 읽기만 한다 (변경안 버튼 없음)."""
    msgs = [{"role": "user", "text": "주인공을 더 어둡게"},
            {"role": "assistant", "text": "바꿔 봤어요", "setup": {"reply": "바꿔 봤어요", "edits": [], "characters": [], "new_characters": [],
                                                              "relationships": [], "options": []}, "outcome": ""},
            {"role": "user", "text": "더 짧게", "selection": {"start": 0, "text": "바람이 불었다."}},
            {"role": "assistant", "text": "후보예요", "passage": {"reply": "후보예요", "candidates": [{"text": "바람.", "note": ""}]},
             "outcome": "applied", "applied": ["0"]}]
    project = {**_demo(), "chats": [{"topic": "setup", "messages": msgs[:2]}, {"topic": "text:3", "messages": msgs[2:]}]}
    got = run_js([*FILES, "setupchat.js"], SETUP + """(() => {
      S.route = ['p', 'demo', 'setup']; chatScreen('setup', 0); chatLegacy('setup');
      const agent = chatDock();
      S.chatOld = 'setup'; const old = chatDock(); const oldTopic = S.chatTopic;
      S.route = ['p', 'demo', 'cast']; chatScreen('cast', 0);
      const away = chatDock();  // 옛 대화 화면 밖에서는 늘 에이전트
      S.agentSid = 'legacy:text:3'; const ro = chatDock();
      S.agentMenu = true; const menu = chatDock();
      return { agent, old, oldTopic, away, ro, menu };
    })()""", {"project": project, "older": [{"topic": "setup", "count": 2}, {"topic": "text:3", "count": 2}]})
    assert 'data-action="chatUseOld" data-arg="setup" aria-pressed="false"' in got["agent"]
    assert 'aria-label="대화로 다듬기"' in got["old"] and got["oldTopic"] == "setup"
    assert 'data-action="chatUseAgent" aria-pressed="false"' in got["old"]
    assert 'aria-label="대화 에이전트"' in got["away"] and "chatUseOld" not in got["away"]
    assert "3화 본문 고치기 예전 대화 기록" in got["ro"] and "바람." in got["ro"] and "적용함" in got["ro"]
    assert "chatApply" not in got["ro"] and "chatDismiss" not in got["ro"]
    assert "이전 대화 · 설정 도우미" in got["menu"] and "이전 대화 · 3화 본문 고치기" in got["menu"]


@needs_node
def test_open_state_has_one_owner():
    """열림 상태(S.chatOpen, localStorage 'canon.chat')를 읽고 쓰는 곳은 chat.js 의 chatOpenSaved · chatSetOpen 뿐이다 (휴대폰 시트 일감 08)."""
    for f in STATIC.glob("*.js"):
        src = f.read_text(encoding="utf-8")
        assert "'canon.chat'" not in src or f.name == "chat.js", f.name
        assert not re.search(r"S\.chatOpen\s*=[^=]|chatOpen:\s*(true|false)", src.replace("S.chatOpen = !!on", "")), f.name
    got = run_js(FILES, "chatSetOpen(true); const a = S.chatOpen; chatSetOpen(false, { save: false }); [a, S.chatOpen, chatOpenSaved()]", None)
    assert got == [True, False, False]
