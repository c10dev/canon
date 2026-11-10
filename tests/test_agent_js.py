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

FILES = ["app.js", "chat.js", "agent.js", "agentsetup.js"]  # agentsetup.js: 설정 대상의 빈 세션 안내 (agentSetupIntro)


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
    """패널은 drawApp 이 셸 끝에 하나만 붙인다. 화면 파일은 chatPanel 을 부르지 않는다 (다시 생성 열이 자리를 쓰면 chatHold 로 알린다)."""
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
    assert got["scope"] == {"act": "", "episode": 0, "draft": None, "screen": "setup", "target": "setup"}
    assert got["pinnedFlash"] == "2화 플롯 2화 제목"  # 고정하면 세션 대상(ep:2)을 보인다
    assert got["pinnedScope"] == {"act": "", "episode": 0, "draft": None, "screen": "cast"}  # 고정한 세션은 화면 대상을 보내지 않는다
    assert got["pinnedHtml"] and got["pinnedTarget"] == "ep:2"


@needs_node
def test_no_old_chat_switch_and_read_only_old_chats():
    """옛 대화 셋은 지웠다(04e): 어느 화면에서든 패널은 대화 에이전트이고 전환 줄이 없다. 머리 버튼은 에이전트를 연다.
    옛 기록은 '이전 대화'로 읽기만 하고(고르기 · 넣기 버튼 없음), 적용한 설정 · 문체 변경안은 거기서 적용 취소한다."""
    setup = {"reply": "바꿔 봤어요", "edits": [{"key": "theme", "text": "새 주제", "items": [], "why": ""}], "characters": [],
             "new_characters": [], "relationships": [], "options": []}
    style = {"reply": "짧게", "edits": [{"key": "dos", "items": ["짧게"], "text": "", "markers": [], "devices": [], "why": ""}], "preview": ""}
    msgs = {
        "setup": [{"role": "user", "text": "주제를 바꿔 줘"}, {"role": "assistant", "text": "바꿔 봤어요", "setup": setup, "outcome": "applied", "applied": ["theme"]}],
        "style": [{"role": "user", "text": "짧게"}, {"role": "assistant", "text": "짧게", "style": style, "outcome": "applied", "applied": ["dos"]}],
        "text:3": [{"role": "user", "text": "더 짧게", "selection": {"start": 0, "text": "바람이 불었다."}},
                   {"role": "assistant", "text": "후보예요", "passage": {"reply": "후보예요", "candidates": [{"text": "바람.", "note": ""}]},
                    "outcome": "applied", "applied": ["0"]}],
    }
    project = {**_demo(), "chats": [{"topic": t, "messages": m} for t, m in msgs.items()]}
    got = run_js([*FILES, "setupchat.js", "stylechat.js"], SETUP + """(() => {
      const docks = {};
      for (const page of ['setup', 'style', 'write']) { S.route = ['p', 'demo', page, '1']; chatScreen(page, 1); docks[page] = chatDock(); }
      const button = chatButton();
      const ro = {};
      for (const t of ['setup', 'style', 'text:3']) { S.agentSid = `legacy:${t}`; ro[t] = chatDock(); }
      S.agentMenu = true; const menu = chatDock();
      return { docks, button, ro, menu, topic: S.chatTopic };
    })()""", {"project": project, "older": [{"topic": "setup", "count": 2}, {"topic": "style", "count": 2}, {"topic": "text:3", "count": 2}]})
    for page, html in got["docks"].items():
        assert 'aria-label="대화 에이전트"' in html and "chat-switch" not in html and "chatUseOld" not in html, page
    assert 'data-action="toggleChat"' in got["button"] and "대화로 다듬기" in got["button"] and got["topic"] == "plot"
    assert 'data-action="setupChatUndo" data-arg="1"' in got["ro"]["setup"] and "적용한 것: 주제" in got["ro"]["setup"]
    assert 'data-action="styleChatUndo" data-arg="1"' in got["ro"]["style"] and "적용한 것: 지킬 것" in got["ro"]["style"]
    assert "3화 본문 고치기 예전 대화 기록" in got["ro"]["text:3"] and "바람." in got["ro"]["text:3"] and "적용함" in got["ro"]["text:3"]
    assert "수정 기록에서 되돌려요" in got["ro"]["text:3"] and "ChatUndo" not in got["ro"]["text:3"]
    for html in got["ro"].values():
        assert "chatApply" not in html and "chatDismiss" not in html and "passageApply" not in html
    assert "이전 대화 · 설정 도우미" in got["menu"] and "이전 대화 · 3화 본문 고치기" in got["menu"]


def test_old_chat_panels_are_gone():
    """옛 대화 셋의 패널 · 보내기 · 전환 줄을 부르는 곳이 남지 않았다 (04e). 머리 버튼은 주제 없이 에이전트를 연다."""
    gone = ["chatLegacy(", "chatSwitch(", "chatOldToggle", "chatUseOld", "chatUseAgent", "S.chatOld", "chat-switch", "CHAT_TOPICS.setup",
            "CHAT_TOPICS.style", "CHAT_TOPICS.text", "setupProposal", "styleProposal", "passageProposal", "/chat/${enc(topic)}`, body"]
    for f in [*STATIC.glob("*.js"), STATIC / "app.css"]:
        src = f.read_text(encoding="utf-8")
        for g in gone:
            assert g not in src, (f.name, g)
        assert not re.search(r"chatButton\('", src), f.name


@needs_node
def test_open_state_has_one_owner():
    """열림 상태(S.chatOpen, localStorage 'canon.chat')를 읽고 쓰는 곳은 chat.js 의 chatOpenSaved · chatSetOpen 뿐이다 (휴대폰 시트 일감 08)."""
    for f in STATIC.glob("*.js"):
        src = f.read_text(encoding="utf-8")
        assert "'canon.chat'" not in src or f.name == "chat.js", f.name
        assert not re.search(r"S\.chatOpen\s*=[^=]|chatOpen:\s*(true|false)", src.replace("S.chatOpen = !!on", "")), f.name
    got = run_js(FILES, "chatSetOpen(true); const a = S.chatOpen; chatSetOpen(false, { save: false }); [a, S.chatOpen, chatOpenSaved()]", None)
    assert got == [True, False, False]


def test_server_screens_match_drawapp_views():
    """턴이 실어 보내는 화면 이름(agent.SCREENS)은 drawApp 의 views 표와 작품 홈이다. 화면이 늘면 서버 목록도 늘린다."""
    from canon import agent
    assert set(agent.SCREENS) == {"home", *_views()}
    assert set(agent.PLOT_SCREENS) <= set(agent.SCREENS)


# ---------- 04b: 본문 고치기 (재료 칩 · 빠른 요청 · 후보 카드) ----------

_TEXT_PROJECT = {"title": "t", "serial": False, "meta": {"target_episodes": 3}, "parts": [], "story_arcs": [],
                 "episodes": [{"plot": {"number": 1, "title": "첫 화"}, "status": "written", "text": "바람이 불었다. 도현은 대답하지 않았다.",
                               "edits": [{"id": "e1", "before": "도현은 대답하지 않았다.", "after": "도현은 입을 닫았다.", "undone": False}]}]}


@needs_node
def test_preset_commands_and_material_chip():
    """본문 빠른 요청은 '/' 명령이 된다('/더 짧게', 띄어쓰기 없이도). 본문 대상이거나 재료가 붙었을 때만 목록에 뜬다.
    재료 칩은 입력 상자 위에 고른 본문을 보이고, 본문에서 사라진 재료는 칩을 감춘다."""
    got = run_js(["app.js", "chat.js", "agent.js"], """(() => {
      S.name = 'lh'; S.project = data; S.route = ['p', 'lh', 'write', '1'];
      S.presets = [{ id: 'shorter', label: '더 짧게' }, { id: 'dialogue', label: '대사 늘리기' }];
      S.agent = { name: 'lh', sessions: [], legacy: 0, older: [], model: 'm', max_steps: 8 };
      S.chatHere = { target: '', legacy: '', hold: false };
      const none = agentTextCmds().length;
      S.chatHere.target = 'text:1';
      const cmds = agentTextCmds().map((x) => x[0]);
      const empty = agentMats();
      S.agentMaterial = { n: 1, start: 9, text: '도현은 대답하지 않았다.' };
      const chip = agentMats();
      const comp = agentComposer();
      S.agentMaterial = { n: 1, start: 0, text: '본문에 없는 글' };
      return { none, cmds, empty, chip, comp, gone: agentMats(),
        p1: agentParsePreset('/더 짧게'), p2: agentParsePreset('/더짧게 더 담백하게'), p3: agentParsePreset('/대사 늘리기는 어때'), p4: agentParsePreset('더 짧게') };
    })()""", _TEXT_PROJECT)
    assert got["none"] == 0 and got["cmds"] == ["/더 짧게", "/대사 늘리기"]
    assert "hidden" in got["empty"] and "hidden" in got["gone"]
    assert "재료" in got["chip"] and "1화 · 도현은 대답하지 않았다." in got["chip"] and 'data-action="agentMaterialDrop"' in got["chip"]
    assert 'class="composer-mats"' in got["comp"] and 'data-action="agentPreset" data-arg="shorter"' in got["comp"]
    assert got["p1"] == {"id": "shorter", "label": "더 짧게", "rest": ""}
    assert got["p2"] == {"id": "shorter", "label": "더 짧게", "rest": "더 담백하게"}
    assert got["p3"] is None and got["p4"] is None  # 이름 뒤에 바로 붙은 말 · '/' 없는 말은 빠른 요청이 아니다


@needs_node
def test_text_card_picks_one_candidate_and_never_offers_remember():
    """본문 고치기 카드는 후보마다 '이걸로 넣기' · '손봐서 넣기'를 두고 '이 세션에서 묻지 않기'를 두지 않는다.
    넣은 뒤에는 쓴 것 목록이 수정 기록으로 바뀐 글을 보이고, 수정 기록에서 되돌렸으면 되돌린 것으로 보인다."""
    got = run_js(["app.js", "chat.js", "passage.js", "agent.js"], """(() => {
      S.name = 'lh'; S.project = data; S.route = ['p', 'lh', 'write', '1']; S.presets = [{ id: 'shorter', label: '더 짧게' }];
      S.agent = { name: 'lh', sessions: [], legacy: 0, older: [], model: 'm', max_steps: 8 };
      const a = { tool: 'revise_text', keys: ['0', '1'], kinds: ['text'], state: 'wait', picked: [], episode: 1, preset: 'shorter',
        selection: { start: 9, text: '도현은 대답하지 않았다.' }, passage: { reply: '두 가지예요', candidates: [{ text: '도현은 말이 없었다.', note: '짧게' }, { text: '도현은 입을 닫았다.', note: '' }] } };
      const t = { user: '더 짧게', preset: 'shorter', selection: { episode: 1, start: 9, text: '도현은 대답하지 않았다.' }, mode: '', steps: [], reply: '두 가지예요', writes: [], approval: a, end: 'wait' };
      const s = { id: 's', mode: 'all', turns: [t] };
      S.agent.sessions = [s]; S.agentSid = 's';
      const wait = agentTurn(s, t, 0);
      const done = { ...t, end: 'done', approval: { ...a, state: 'approved', picked: ['1'] },
        writes: [{ tool: 'revise_text', episode: 1, edit: 'e1', items: [{ key: 'text', label: '1화 본문 · 2번 후보', state: 'done' }] }] };
      const after = agentTurn(s, done, 0);
      data.episodes[0].edits[0].undone = true;
      return { wait, after, undone: agentTurn(s, done, 0), plot: agentApproval({ ...t, approval: { tool: 'edit_plot', keys: ['3'], kinds: ['draft'], state: 'wait', picked: [], revision: { episodes: [] }, target: '' } }, 0, true) };
    })()""", _TEXT_PROJECT)
    w = got["wait"]
    assert w.count('data-action="agentPickCand"') == 2 and w.count('data-action="agentCandTweak"') == 2
    assert "data-agent-remember" not in w and "권한 모드와 상관없이" in w and 'data-arg="0|0"' in w
    assert "<del>" in w and "msg-quote" in w and "/더 짧게" in w  # 후보는 원문과의 낱말 비교, 보낸 말은 재료와 빠른 요청
    assert "agentPickCand" not in got["after"] and "후보 2 · 넣음" in got["after"]
    assert 'data-action="agentUndo" data-arg="0|0|text"' in got["after"] and "입을 닫았다" in got["after"]
    assert "agentUndo" not in got["undone"] and "되돌림" in got["undone"]
    assert "data-agent-remember" in got["plot"]  # 플롯 카드의 '묻지 않기'는 그대로


# ---------- 06b: 정규식 규칙 제안 카드 (docs/context/specs/06b-rule-propose.md) ----------


@needs_node
def test_always_ask_kinds_match_server():
    got = run_js(["app.js", "chat.js", "agent.js"], "AGENT_ALWAYS", None)
    assert got == list(agent.ALWAYS_ASK)


RX_FILES = ["app.js", "chat.js", "regexrules.js", "agent.js"]  # regexrules.js: 카드의 바뀐 곳은 ruleChangeHtml 로 그린다


def _rx_card(key: str) -> dict:
    """규칙 카드. key 는 규칙의 찾을 정규식 키: 승인 응답(FastAPI)은 'in', 작품 저장(get_project)은 'in_'."""
    rule = {"id": "r1", "comment": "말줄임표", key: "\\.\\.\\.", "out": "…", "action": "fix", "type": "output", "flag": "g", "enabled": True}
    return {"bundle": "b1", "bundle_name": "표기", "new_bundle": False, "project": "lh", "used_by": ["ot"], "rule": rule, "before": None,
            "episode": 2, "changes": [{"bundle": "b1", "version": 1, "rule": "r1", "name": "말줄임표", "start": 6, "before": "...", "after": "…"}],
            "hits": [], "change_count": 2, "hit_count": 0, "export_changed": False, "notices": ["바꿀 글의 {{…}}는 풀지 않고 글자 그대로 넣어요"],
            "version": 0}


@needs_node
def test_regex_card_shows_rule_trial_and_no_remember_box():
    """규칙 카드는 규칙 칸 · 시험 줄 · 묶음 이름 · 다른 작품 수 · 알림을 보이고 '이 세션에서 묻지 않기'를 그리지 않는다.
    규칙 키가 in 이든 in_ 이든 찾을 정규식을 보인다. 적용한 항목은 '적용함'이고 되돌리기 버튼이 있다."""
    got = run_js(RX_FILES, """(() => {
      S.name = 'lh'; S.project = { episodes: [], chats: [] }; S.agent = { name: 'lh', sessions: [], legacy: 0, older: [], model: 'm', max_steps: 8 };
      const card = (c) => ({ tool: 'propose_regex', regex: c, keys: ['rule'], kinds: ['rule'], state: 'wait', picked: [], target: '', revision: null, op: null });
      const t = (c) => ({ user: '규칙', mode: '', steps: [], reply: '', writes: [], approval: card(c), ask: null, end: 'wait' });
      const a = agentApproval(t(data.a), 0, true);
      const b = agentApproval(t(data.b), 0, true);
      const fresh = agentApproval(t({ ...data.a, new_bundle: true, bundle: '', used_by: [], episode: 0, changes: [], change_count: 0 }), 0, true);
      const off = agentApproval(t({ ...data.a, before: { ...data.a.rule }, rule: { ...data.a.rule, enabled: false }, hit_count: 1 }), 0, true);
      const exp = agentApproval(t({ ...data.a, rule: { ...data.a.rule, type: 'export' }, changes: [], change_count: 0, export_changed: true }), 0, true);
      const slow = agentApproval(t({ ...data.a, before: { ...data.a.rule }, rule: { ...data.a.rule, enabled: false }, changes: [], change_count: 0, timed_out: true }), 0, true);
      const done = { ...t(data.a), end: 'done', approval: { ...card(data.a), state: 'approved', picked: ['rule'] },
        writes: [{ tool: 'propose_regex', regex: { ...data.a, version: 2 }, items: [{ key: 'rule', label: '정규식 규칙 · 말줄임표', state: 'done', reason: '' }] }] };
      const html = agentTurn({ id: 's', turns: [done] }, done, 0);
      return { a, b, fresh, off, exp, slow, html, name: agentToolName('propose_regex'), read: agentToolName('read_rules') };
    })()""", {"a": _rx_card("in"), "b": _rx_card("in_")})
    a = got["a"]
    assert "정규식 규칙 · 표기" in a and "말줄임표" in a and "\\.\\.\\." in a and "…" in a
    assert "2화에 걸어 보면 바뀌는 곳 2곳 · 걸리는 곳 0곳이에요" in a and 'class="rx-change"' in a and "rx-name" in a
    assert "다른 작품 1개에도 걸려요" in a and "풀지 않고 글자 그대로" in a
    assert "적용하면 다음에 본문을 쓸 때부터 본문을 바꿔요" in a
    assert "data-agent-remember" not in a and "묻지 않고" not in a
    assert 'data-arg="0|1"' in a and 'data-arg="0|0"' in a and ">적용</button>" in a
    assert "\\.\\.\\." in got["b"]  # 작품 저장 모양(in_)도 읽는다
    f = got["fresh"]
    assert "정규식 규칙 · 새 묶음 표기" in f and "시험할 본문이 없어요" in f and "새 묶음을 만들고 이 작품에서 켜요" in f
    assert "다른 작품" not in f
    assert "2화에서 적용하면 더 걸리지 않을 곳 2곳 · 1곳이에요" in got["off"] and "<del>켬</del>" in got["off"]
    assert "2화를 내보낼 때 글이 바뀌어요" in got["exp"] and "내보낼 때만 걸려요" in got["exp"]
    assert "2화에 걸어 보니 시험 시간이 넘었어요. 끄면 이 규칙은 더 걸리지 않아요" in got["slow"] and "더 걸리지 않을 곳" not in got["slow"]
    h = got["html"]
    assert "적용함" in h and "바로 씀" not in h and 'data-action="agentUndo" data-arg="0|0|rule"' in h
    assert "approval settled" in h and "바뀐 칸 보기" in h
    assert got["name"] == "정규식 규칙 제안" and got["read"] == "규칙 읽기"


@needs_node
def test_regex_decide_sends_rule_and_says_when_it_applies():
    """적용하면 picked ['rule'] 를 보내고, 턴이 끝나므로 '이어서 돌아요' 대신 언제부터 걸리는지 알린다."""
    got = run_js(RX_FILES, """(async () => {
      S.name = 'lh'; S.project = { episodes: [], chats: [] }; S.dirty = false; S.jobs = []; S.agentPicks = {}; S.agentRemember = {};
      const said = []; const sent = [];
      toast = (m) => said.push(m); saveIfDirty = async () => {}; pollJobs = () => {}; agentLoad = async () => {}; render = () => {};
      api = async (m, path, body) => { sent.push(body); return { project: S.project, job: null }; };
      const mk = (rule) => ({ user: '규칙', steps: [], writes: [], end: 'wait', approval: { tool: 'propose_regex', keys: ['rule'], kinds: ['rule'], state: 'wait',
        picked: [], regex: { ...data, rule: { ...data.rule, ...rule } } } });
      for (const rule of [{}, { action: 'warn' }, { type: 'export' }, { enabled: false }]) {
        S.agent = { name: 'lh', sessions: [{ id: 's', turns: [mk(rule)] }], legacy: 0, older: [], model: 'm', max_steps: 8 }; S.agentSid = 's';
        await actions.agentDecide('0|1');
      }
      return { said, sent };
    })()""", _rx_card("in"))
    assert got["sent"][0]["picked"] == ["rule"] and got["sent"][0]["approve"] is True
    assert got["said"] == ["규칙을 넣었어요. 다음에 본문을 쓸 때부터 걸려요", "규칙을 넣었어요. 다음 검수부터 걸려요",
                           "규칙을 넣었어요. 다음에 내보낼 때부터 걸려요", "규칙을 껐어요. 다음 걸기부터 걸리지 않아요"]
    assert not any("이어서 돌아요" in x for x in got["said"])
