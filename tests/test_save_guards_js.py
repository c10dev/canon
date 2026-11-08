"""작가가 쓰거나 고른 것을 묻지 않고 지우거나 덮지 않는지, 저장이 실패하면 저장했다고 알리지 않는지 node 로 맞춰 본다.
본문 저장 충돌(write.js) · 비교 채택(research.js) · 자동 집필 변경안 열기와 추정(auto.js) · 칸 후보(ideas.js) · 정착 문체(anchor.js) ·
지도 살펴보기 칸(atlas.js) · 큐 시트 저장(cue.js) · 설정 키 경고(settings.js) · 인과율 관련 화(causal.js). node 가 있을 때만 돈다."""
import re

from canon.schema import Project, StateDelta, StoryElement

from .jsvm import STATIC, dump, episode, needs_node, run_js

FILES = re.findall(r'src="/static/([a-z0-9]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))

# vm 에는 화면이 없다. 그리기 · 알림 · 기다림 상자는 대역으로 둔다
STUB = """render = () => {}; const toasts = []; toast = (m) => { toasts.push(m); };
run = async (label, fn) => { try { await fn(); return true; } catch (e) { toasts.push('ERR ' + e.message); return false; } };"""


def _project(**ep1) -> dict:
    p = Project()
    p.meta.target_episodes = 2
    p.episodes = [episode(1, **{"status": "written", "text": "옛 본문", **ep1}), episode(2)]
    return dump(p)


@needs_node
def test_save_text_conflict_reload_keeps_draft_then_overwrite():
    expr = STUB + """(async () => {
      S.project = data; S.name = 'lh'; S.route = ['p', 'lh', 'write', '1']; S.jobs = [];
      markTextBase(1); S.textDraft[1] = '내 글';
      const sent = []; let server = '다른 탭 본문';
      api = async (m, path, body) => {
        sent.push([m, path, body && body.base]);
        if (m === 'GET') return { ...data, episodes: data.episodes.map((e, i) => (i ? e : { ...e, text: server })) };
        if (!path.includes('force=true') && body.base !== server) throw Object.assign(new Error('먼저 저장'), { status: 409, code: 'stale_text' });
        server = body.text;
        return { ...data, episodes: data.episodes.map((e, i) => (i ? e : { ...e, text: server })) };
      };
      const picks = ['alt', true];
      const asked = [];
      askConfirm = async (q, o) => { asked.push([q, o.alt, o.ok]); return picks.shift(); };
      await actions.saveText(1);  // 막힘 → 다시 불러오기: 칸의 글은 둔다
      const reloaded = [S.textDraft[1], ep(1).text, textBase(1)];
      server = '또 다른 본문';
      await actions.saveText(1);  // 또 막힘 → 덮어쓰기
      return { sent, asked, reloaded, draft: S.textDraft[1] === undefined, server, toasts };
    })()"""
    got = run_js(FILES, expr, _project())
    assert got["sent"][0] == ["PUT", "/projects/lh/episodes/1/text", "옛 본문"]  # 고침을 시작한 저장 본문을 함께 보낸다
    assert got["sent"][1][0] == "GET"
    assert got["reloaded"] == ["내 글", "다른 탭 본문", "다른 탭 본문"]  # 서버 본문을 받아 오고 쓰던 글은 그대로
    assert got["sent"][2] == ["PUT", "/projects/lh/episodes/1/text", "다른 탭 본문"]
    assert got["sent"][3][1].endswith("?force=true")
    assert len(got["asked"]) == 2 and "1화 본문을 먼저 저장했어요" in got["asked"][0][0]
    assert got["asked"][0][1:] == ["다시 불러오기", "내 글로 덮어쓰기"]
    assert got["server"] == "내 글" and got["draft"] is True
    assert got["toasts"][-1] == "본문을 저장했어요" and not any(t.startswith("ERR") for t in got["toasts"])


@needs_node
def test_research_pick_keeps_draft_unless_adopted():
    expr = STUB + """(async () => {
      S.project = data; S.name = 'lh'; S.route = ['p', 'lh', 'research'];
      blindPickOk = async () => true; rsLoadLog = async () => {}; saveIfDirty = async () => {};
      const asked = []; let yes = true;
      askConfirm = async (q) => { asked.push(q); return yes; };
      let adopted = false;
      api = async () => ({ compare: {}, result: { picked: 'a', adopted }, project: data });
      S.rs = { ...S.rs, compareEp: 1, adopt: false, compare: {} };
      S.textDraft[1] = '쓰던 글'; S.deltas[1] = { summary: 's' };
      await actions.rsPickDraft(1);
      const kept = [S.textDraft[1], !!S.deltas[1], asked.length];
      S.rs.adopt = true; yes = false;
      await actions.rsPickDraft(1);  // 본문으로 바꾸기는 묻는다. 그만두면 그대로
      const declined = [S.textDraft[1], asked.length];
      yes = true; adopted = true;
      await actions.rsPickDraft(1);
      return { kept, declined, asked, gone: [S.textDraft[1] === undefined, S.deltas[1] === undefined] };
    })()"""
    got = run_js(FILES, expr, _project())
    assert got["kept"] == ["쓰던 글", True, 0]  # 고르기만 했으면 초안 · 변경안을 두고 묻지도 않는다
    assert got["declined"] == ["쓰던 글", 1]
    assert "저장하지 않은 고침" in got["asked"][-1] and len(got["asked"]) == 3
    assert got["gone"] == [True, True]


@needs_node
def test_auto_open_review_keeps_edited_delta():
    pending = dump(StateDelta(episode=1, summary="자동 요약"))
    expr = STUB + """(async () => {
      S.project = data.project; S.name = 'lh'; S.route = ['p', 'lh', 'auto'];
      const asked = []; let yes = false;
      askConfirm = async (q) => { asked.push(q); return yes; };
      let rec = { id: 'r1', key: 'state:1', kind: 'state', ep: 1, label: '1화 상태 변경안', result: data.pending };
      api = async (m, path) => (path.endsWith('/auto/review') ? S.auto : { results: { 'state:1': rec }, failures: {} });
      S.auto = { run: { ep: 1 } };
      await actions.autoOpenReview();
      S.deltas[1].summary = '작가가 고친 요약';
      await actions.autoOpenReview();  // 같은 결과: 묻지 않고 이동만
      const same = [S.deltas[1].summary, asked.length];
      rec = { ...rec, id: 'r2', result: { ...data.pending, summary: '새 자동 요약' } };
      await actions.autoOpenReview();  // 다른 결과 · 고친 것 있음: 묻고, 그만두면 둔다
      const kept = [S.deltas[1].summary, asked.length];
      rec = { ...rec, id: 'r3' };
      yes = true;
      await actions.autoOpenReview();
      return { same, kept, replaced: S.deltas[1].summary, asked };
    })()"""
    got = run_js(FILES, expr, {"project": _project(), "pending": pending})
    assert got["same"] == ["작가가 고친 요약", 0]
    assert got["kept"] == ["작가가 고친 요약", 1] and "고친 칸" in got["asked"][0]
    assert got["replaced"] == "새 자동 요약" and len(got["asked"]) == 2


@needs_node
def test_use_idea_asks_before_replacing_written_field():
    p = Project()
    p.world.setting = "작가가 쓴 배경"
    expr = STUB + """(async () => {
      S.project = data; S.name = 'demo';
      const asked = []; let yes = false;
      askConfirm = async (q) => { asked.push(q); return yes; };
      const opts = { options: [{ text: '안개 낀 섬', reason: '' }] };
      S.ideas = { 'world.setting': { ...opts } };
      await actions.useIdea('world.setting|0');
      const kept = [P().world.setting, asked.length];
      yes = true;
      await actions.useIdea('world.setting|0');
      const changed = P().world.setting;
      S.ideas = { 'world.era': { ...opts } };
      await actions.useIdea('world.era|0');  // 빈 칸은 묻지 않는다
      return { kept, changed, era: P().world.era, asked };
    })()"""
    got = run_js(FILES, expr, dump(p))
    assert got["kept"] == ["작가가 쓴 배경", 1] and "지금: 작가가 쓴 배경" in got["asked"][0]
    assert got["changed"] == "안개 낀 섬"
    assert got["era"] == "안개 낀 섬" and len(got["asked"]) == 2


@needs_node
def test_anchor_repick_keeps_passages():
    expr = STUB + """(async () => {
      S.project = data; S.name = 'lh';
      S.anchorView = { anchor: { episodes: [1, 2], passages: ['가 문단', '나 문단'] }, suggest: [1], usable: [1, 2, 3], min_chars: 6000 };
      const sent = []; const asked = []; let yes = false;
      askConfirm = async (q) => { asked.push(q); return yes; };
      api = async (m, path, body) => {
        sent.push([m, path, body]);
        if (path.endsWith('/candidates')) return { passages: ['나 문단', '다 문단'], chars: 9000, later: null };
        return data;
      };
      anchorLoad = async () => {};
      actions.anchorStart();
      S.anchorPick = [1, 2, 3];
      const noCands = anchorBody();  // 후보를 열지 않고 화만 바꿨다
      await actions.anchorCands();
      const cands = [[...S.anchorCands.passages], { ...S.anchorPass }, anchorChooser(S.anchorView).includes('지금 문단')];
      S.anchorPass[0] = false; S.anchorPass[2] = true;
      await actions.anchorSave();  // 지금 문단이 빠진다: 묻고, 그만두면 저장하지 않는다
      const puts = sent.filter((x) => x[0] === 'PUT').length;
      yes = true;
      await actions.anchorSave();
      return { noCands, cands, puts, asked, last: sent[sent.length - 1] };
    })()"""
    got = run_js(FILES, expr, _project())
    assert got["noCands"] == {"episodes": [1, 2, 3], "passages": ["가 문단", "나 문단"]}
    assert got["cands"][0] == ["가 문단", "나 문단", "다 문단"] and got["cands"][1] == {"0": True, "1": True} and got["cands"][2]
    assert got["puts"] == 0 and "2개 중 1개가 빠져요" in got["asked"][0]
    assert got["last"][0] == "PUT" and got["last"][2]["passages"] == ["나 문단", "다 문단"]


@needs_node
def test_atlas_paint_keeps_typed_value():
    expr = """(() => {
      CSS = { escape: (s) => s };
      const typed = { id: 'at-bld-name', tagName: 'INPUT', type: 'text', value: '새 장소', selectionStart: 2, selectionEnd: 3, dataset: {} };
      const fresh = { value: '', focused: false, sel: null, focus() { this.focused = true; }, setSelectionRange(a, b) { this.sel = [a, b]; } };
      let html = '';
      const box = { contains: (x) => x === typed, set innerHTML(h) { html = h; }, querySelector: (q) => (q === '#at-bld-name' ? fresh : null) };
      document = { activeElement: typed, getElementById: () => box };
      atlasPaint('atlas-side', '<input id="at-bld-name">');
      return { html, value: fresh.value, focused: fresh.focused, sel: fresh.sel };
    })()"""
    got = run_js(FILES, expr, {})
    assert got == {"html": '<input id="at-bld-name">', "value": "새 장소", "focused": True, "sel": [2, 3]}


@needs_node
def test_cue_save_toasts_only_on_success():
    expr = STUB + """(async () => {
      cueCtx = () => ({ kind: 'ep', n: 1 });
      run = async () => false;
      await actions.cueSave();
      const failed = toasts.length;
      run = async () => true;
      await actions.cueSave();
      return [failed, toasts];
    })()"""
    assert run_js(FILES, expr, {}) == [0, ["큐 시트를 저장했어요"]]


@needs_node
def test_auto_estimate_keeps_last_answer_and_blocks_start():
    expr = STUB + """(async () => {
      S.project = data; S.name = 'lh';
      S.autoForm = { project: 'lh', target: 5, batch: false, policy: {} };
      const wait = [];
      api = (m, path, body) => new Promise((ok) => wait.push(() => ok({ episodes: body.target, from: 1, to: body.target })));
      const first = autoEstimate();
      S.autoForm.target = 9;
      const second = autoEstimate();
      wait.slice(2).forEach((f) => f());  // 나중 요청이 먼저 온다
      await second;
      wait.slice(0, 2).forEach((f) => f());
      await first;
      const est = S.autoEst.off.episodes;
      S.autoEst = null;
      const asked = [];
      askConfirm = async (q) => { asked.push(q); return false; };
      await actions.autoStart();
      return { est, asked: asked.length, toasts };
    })()"""
    got = run_js(FILES, expr, _project())
    assert got["est"] == 9  # 늦게 온 앞 요청(5화)이 새 추정을 덮지 않는다
    assert got["asked"] == 0 and "추정하는 중" in got["toasts"][-1]


@needs_node
def test_settings_key_save_redraws_after_health_when_closed():
    expr = """(async () => {
      let draws = 0; render = () => { draws++; }; setPaint = () => {};
      let open = false;
      const key = { matches: () => true };  // 대화상자 안 키 칸에 포커스가 남아 있다
      document = { getElementById: (id) => (id === 'set-dlg' ? { open, contains: (x) => x === key } : null), activeElement: key };
      api = async (m, path) => (path === '/config/health' ? { ok: true } : {});
      await setSave('key', { gemini_key: 'x' });
      await new Promise((r) => r());
      const closed = [draws, S.health];
      open = true;
      await setSave('key', { gemini_key: 'x' });
      await new Promise((r) => r());
      return { closed, open: draws };
    })()"""
    got = run_js(FILES, expr, {})
    assert got["closed"] == [1, {"ok": True}]
    assert got["open"] == 1  # 대화상자가 열려 있으면 닫을 때 그린다


@needs_node
def test_causal_cells_leave_tab_order_and_rows_expand():
    p = Project()
    p.meta.target_episodes = 20
    p.episodes = [episode(n) for n in range(1, 21)]
    el = StoryElement(id="el-01", kind="장소", name="탑")
    links = [{"episode": n, "where": ["본문"], "planned": False, "terms": ["탑"], "characters": [], "snippet": "탑"} for n in range(1, 16)]
    expr = """(() => {
      S.project = data.project; S.name = 'lh'; render = () => {};
      S.causalLinks = { 'el-01': data.links }; S.causalLinkTab = 'rel';
      const short = causalLinksCard(data.el);
      actions.causalLinkAll('el-01');
      const all = causalLinksCard(data.el);
      S.causalLinkTab = 'bad';
      return { short, all, focus: S.focusTarget, other: S.causalLinkAll };
    })()"""
    got = run_js(FILES, expr, {"project": dump(p), "el": dump(el), "links": links})
    cells = re.findall(r'<button type="button" class="[^"]*" data-action="causalCell"[^>]*aria-label[^>]*>', got["short"])
    assert len(cells) == 20 and all('tabindex="-1"' in c for c in cells)
    assert got["short"].count('class="cz-row"') == 12 and 'data-action="causalLinkAll"' in got["short"] and "3개 더 있어요" in got["short"]
    assert got["all"].count('class="cz-row"') == 15 and 'data-action="causalLinkAll"' not in got["all"]
    assert got["other"] == "el-01:rel" and "nth-child(13)" in got["focus"]


@needs_node
def test_save_warns_when_server_keeps_episode_text():
    """작품 저장이 본문 있는 화를 빼거나 본문을 비워 서버가 디스크 것을 두면(web._keep_texts) '저장했어요' 대신 알린다."""
    expr = STUB + """(async () => {
      S.project = data; S.name = 'lh'; S.route = ['p', 'lh', 'plot']; S.jobs = []; S.dirty = true;
      const kept = [{ field: 'episode', ep: 1 }, { field: 'text', ep: 2 }];
      api = async (m, path, body, meta) => {
        meta.headers = { get: (k) => (k === 'X-Canon-Kept' ? encodeURIComponent(JSON.stringify(kept)) : null) };
        return data;
      };
      const ok = await save();
      await actions.save();
      return { ok, toasts };
    })()"""
    got = run_js(FILES, expr, _project())
    assert got["ok"] is False
    lost = [t for t in got["toasts"] if t.startswith("본문이 있는 화를 빼거나 본문을 비우는 저장이라")]
    assert len(lost) == 2 and "1~2화" in lost[0]
    assert "저장했어요" not in got["toasts"]
    assert not any("화 플롯" in t for t in got["toasts"])  # 플롯을 버렸다고 잘못 알리지 않는다
