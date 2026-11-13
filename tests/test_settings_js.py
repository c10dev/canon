"""설정 대화상자(static/settings.js): 찾기 · 주소 · 프리셋 맞춤 · 환경 변수 목록은 node 로, 바로 저장하는 작품 설정 API 는 서버로 맞춰 본다."""
import re
from pathlib import Path

import pytest

from canon.schema import Meta, Project
from .jsvm import needs_node, run_js

FILES = ["app.js", "notify.js", "settings.js"]
ROWS = "SET_ROWS.map((r) => ({ cat: r.cat, label: r.label, sec: r.sec, words: r.words }))"


@needs_node
def test_settings_match():
    got = run_js(FILES, """(() => {
      const ids = (q) => settingsMatch(SET_ROWS, q).map((r) => r.id);
      return { key: ids('키'), apiKey: ids('API 키'), stage: ids('검수'), none: ids('없는말'), blank: ids('  '),
        spaced: ids('스냅 샷'), cat: ids('이 브라우저'), group: ids('고급') };
    })()""", {})
    # 이름에 든 줄이 앞, 찾을 말에만 든 줄이 뒤
    assert got["key"][:4] == ["gemini-key", "vertex-cred", "anthropic-key", "local-key"]
    assert {"gemini-auth", "test", "env"} <= set(got["key"][4:])
    # 낱말이 모두 맞아야 한다
    assert got["apiKey"][:2] == ["gemini-key", "anthropic-key"] and "local-key" not in got["apiKey"][:2]
    assert got["stage"][0] == "stage-check" and "widen" in got["stage"]
    assert got["none"] == [] and got["blank"] == []
    assert got["spaced"] == ["snapshots"]  # 띄어쓰기는 무시한다
    assert got["group"][:3] == ["env", "sampling", "path"]  # 갈래 이름으로도 찾는다


@needs_node
def test_settings_cat_from_hash():
    got = run_js(FILES, """['#/settings', '#/settings/', '#/settings/ai', '#/settings/writing', '#/settings/nope', '#/p/a/settings', '#/', '#/settingsx']
      .map(settingsCat)""", {})
    assert got == ["", "", "ai", "writing", "", None, None, None]


@needs_node
def test_rows_cover_every_stage_and_unique_ids():
    got = run_js(FILES, "({ ids: SET_ROWS.map((r) => r.id), cats: SET_CATS.map((c) => c[0]), rowCats: [...new Set(SET_ROWS.map((r) => r.cat))], stages: STAGES.map((s) => s[0]) })", {})
    from canon import settings
    assert got["stages"] == list(settings.STAGES)  # 플레이 장면까지 서버와 같은 순서
    assert len(got["ids"]) == len(set(got["ids"]))
    assert set(got["rowCats"]) == set(got["cats"])
    assert {f"stage-{s}" for s in settings.STAGES} <= set(got["ids"])


@needs_node
def test_preset_of_and_env_list(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("CANON_LLM", "gemini")
    monkeypatch.setenv("CANON_LLM_CHECK", "local")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from canon import settings
    gem = next(p for p in settings.presets() if p["id"] == "gemini")
    settings.update(stages=gem["stages"], stage_models=gem["stage_models"])
    c = settings.public()
    got = run_js(FILES, """(() => {
      const c = data.config;
      const same = presetOf(c.stage_presets, { stages: c.stage_settings, stage_models: c.stage_model_settings });
      const changed = presetOf(c.stage_presets, { stages: { ...c.stage_settings, write: 'local' }, stage_models: c.stage_model_settings });
      return { same: same && same.id, changed, env: setEnvList(c) };
    })()""", {"config": c})
    assert got["same"] == "gemini" and got["changed"] is None
    assert ["CANON_LLM", "Gemini API"] in got["env"] and ["CANON_LLM_CHECK", "로컬 서버"] in got["env"]


@needs_node
def test_preset_asks_before_replacing_hand_picked_and_can_undo(tmp_path, monkeypatch):
    """직접 고른 조합을 프리셋으로 덮기 전에 묻고, 그만두면 고른 값을 되돌린다. 채운 뒤에는 '되돌리기'로 앞 칸을 다시 저장한다"""
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("CANON_LLM", "gemini")
    from canon import settings
    settings.update(stages={"write": "local"}, stage_models={"write": "my-model"})
    c = settings.public()
    got = run_js(FILES, """(async () => {
      setPaint = () => {};
      const puts = [];
      const asked = [];
      let yes = false;
      api = async (m, u, b) => {
        if (m !== 'PUT') return {};
        puts.push(b);
        return { ...data.config, stage_settings: b.stages, stage_model_settings: b.stage_models };
      };
      askConfirm = async (msg) => { asked.push(msg); return yes; };
      S.config = data.config;
      const el = { value: 'gemini', dataset: { setfield: 'preset' }, closest: () => ({ id: 'row-preset-pick' }) };
      await setChange({ target: el });
      const cancel = { value: el.value, puts: puts.length, asked: asked.length, undo: SET.undo };
      yes = true;
      el.value = 'gemini';
      await setChange({ target: el });
      const filled = { puts: puts.length, asked: asked.length, undo: !!SET.undo, html: setRowHtml('preset-pick').includes('setPresetUndo') };
      await actions.setPresetUndo();
      const back = puts[puts.length - 1];
      // 프리셋과 같은 칸에서 다른 프리셋을 고르면 묻지 않는다
      S.config = { ...data.config, stage_settings: puts[0].stages, stage_model_settings: puts[0].stage_models };
      el.value = 'anthropic';
      await setChange({ target: el });
      return { cancel, filled, back: [back.stages.write, back.stage_models.write], undoAfter: SET.undo && SET.undo.row,
        asked: asked.length, note: SET.note['preset-pick'].text };
    })()""", {"config": c})
    assert got["cancel"] == {"value": "", "puts": 0, "asked": 1, "undo": None}
    assert got["filled"] == {"puts": 1, "asked": 2, "undo": True, "html": True}
    assert got["back"] == ["local", "my-model"]
    assert got["asked"] == 2 and got["undoAfter"] == "preset-pick"


@needs_node
def test_effort_select_lists_what_the_backend_takes(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("CANON_LLM", "gemini")
    monkeypatch.setenv("CANON_LLM_CHECK", "claude")
    monkeypatch.setenv("CANON_LLM_STATE", "local")
    from canon import settings
    settings.update(stage_efforts={"plan": "max", "write": "medium"})
    c = settings.public()
    got = run_js(FILES, """(() => {
      const c = data.config;
      const opts = (s) => [...effortSelect(s, s, c.stages[s], c).matchAll(/<option value="([^"]*)"( selected)?>([^<]*)</g)].map((m) => [m[1], !!m[2], m[3]]);
      return { plan: opts('plan'), write: opts('write'), check: opts('check').map((o) => o[0]), state: effortSelect('state', 'state', c.stages.state, c) };
    })()""", {"config": c})
    assert [o[0] for o in got["write"]] == ["", "low", "medium", "high"]  # Gemini 는 낮음 · 보통 · 높음
    assert ["medium", True, "추론 강도: 보통"] in got["write"]
    assert got["plan"][-1] == ["max", True, "추론 강도: 최대 → 높음"]  # Gemini 가 받지 않는 값은 실제로 넘기는 값과 함께
    assert got["check"] == ["", "low", "medium", "high", "xhigh", "max"]
    assert got["state"] == ""  # 로컬 서버 단계에는 칸이 없다


@needs_node
def test_palette_finds_setting_rows():
    got = run_js(["app.js", "notify.js", "settings.js", "palette.js"], f"""(() => {{
      const settings = {ROWS}.map((r) => ({{ ...r, where: setCat(r.cat)[1] }}));
      const items = paletteItems({{ inProject: false, settings }});
      return {{ empty: paletteMatch(items, '').map((i) => i.label), key: paletteMatch(items, 'Anthropic').map((i) => [i.kind, i.label, i.act, i.cat, i.hint]) }};
    }})()""", {})
    assert got["empty"] == ["작품 목록", "설정", "알림 · AI 작업", "지시 연습", "가려 읽기 묶음"]  # 검색어가 없으면 설정 줄은 숨긴다
    assert got["key"][0] == ["setting", "Anthropic API 키", "settings", "ai", "AI 연결 · Claude"]


def test_no_old_settings_route_left():
    """설정은 화면이 아니라 대화상자다: app.js 가 'settings' 화면을 그리거나 저장 안 한 설정을 묻지 않는다"""
    app = (Path(__file__).resolve().parent.parent / "canon" / "static" / "app.js").read_text(encoding="utf-8")
    assert "settingsDirty" not in app and "viewSettings" not in app
    assert re.search(r"settingsCat\(location\.hash\)", app)


@pytest.fixture()
def client(client):
    from canon import store

    store.save("a", Project(meta=Meta(title="가", form="serial")))
    return client, store


def test_timeline_and_stat_prompt_save_right_away(client):
    c, store = client
    r = c.put("/api/projects/a/timeline-setting", json={"on": False})
    assert r.status_code == 200 and r.json()["timeline"]["enabled"] is False
    assert store.load("a").timeline.enabled is False
    r = c.put("/api/projects/a/stat-prompt", json={"mode": "lines"})
    assert r.status_code == 200 and store.load("a").stat_window.prompt == "lines"
    assert c.put("/api/projects/a/stat-prompt", json={"mode": "yaml"}).status_code == 422
    assert store.load("a").stat_window.prompt == "lines"


def test_config_shows_local_sampling(client):
    c, _ = client
    got = c.get("/api/config").json()
    assert got["local_sampling"] == {"temperature": 1.0, "top_p": 0.95, "min_p": 0.05}


def test_put_config_changes_only_sent_field(client):
    """설정 대화상자는 바꾼 칸 하나만 보낸다. 다른 칸 · 다른 단계는 그대로다"""
    c, _ = client
    c.put("/api/config", json={"stages": {"write": "local", "check": "claude"}, "stage_models": {"state": "gemini-3.8-flash"}})
    got = c.put("/api/config", json={"stages": {"write": ""}}).json()
    assert got["stage_settings"] == {"check": "claude"} and got["stage_model_settings"] == {"state": "gemini-3.8-flash"}
    got = c.put("/api/config", json={"model": "gemini-3.8-flash"}).json()
    assert got["model_setting"] == "gemini-3.8-flash" and got["stage_settings"] == {"check": "claude"}


def test_put_config_takes_only_a_claude_binary(client):
    """claude_bin 은 로그인 없는 웹 API 로 바꿀 수 있어 claude 라는 이름의 파일만 받는다 (그 파일을 --version 으로 실행한다)"""
    c, _ = client
    r = c.put("/api/config", json={"claude_bin": "/bin/sh"})
    assert r.status_code == 400 and "claude" in r.json()["detail"]
    assert c.get("/api/config").json()["claude_bin"] in ("", None)
    got = c.put("/api/config", json={"claude_bin": "~/.local/bin/claude"}).json()
    assert got["claude_bin"] == "~/.local/bin/claude"
    assert c.put("/api/config", json={"claude_bin": ""}).json()["claude_bin"] in ("", None)


@needs_node
def test_backup_rows_describe_each_backup():
    got = run_js(FILES, """(() => ({
      find: settingsMatch(SET_ROWS, '백업').map((r) => r.id),
      cat: setCat('backup')[2],
      hourly: backupDesc({ kind: 'hourly', episodes: 12, finalized: 10, ep: null }),
      none: backupDesc({ kind: 'prev', episodes: 3, finalized: 0, ep: null }),
      del: backupDesc({ kind: 'delete', episodes: 12, finalized: 12, ep: 12 }),
      broken: backupDesc({ kind: 'hourly', episodes: -1, finalized: 0, ep: null }),
    }))()""", {})
    assert got["find"] == ["backup-list"] and got["cat"] == "project"
    assert got["hourly"] == "시간별 · 12화 · 10화까지 반영"
    assert got["none"] == "직전 판 · 3화 · 반영한 화 없음"
    assert got["del"] == "12화 지우기 전 · 12화 · 12화까지 반영"
    assert got["broken"] == "시간별 · 읽지 못하는 파일이에요"


@needs_node
def test_late_put_response_does_not_overwrite_newer_config():
    """단계 칸 PUT 두 개가 겹쳐 옛 응답이 늦게 와도 S.config 는 마지막 요청의 응답이고, 다 끝난 뒤 GET 으로 한 번 맞춘다 (SET.seq)"""
    got = run_js(FILES, """(async () => {
      setPaint = () => {};
      const waits = [];
      const calls = [];
      api = (m, u, b) => {
        calls.push([m, u]);
        if (u === '/config/health') return Promise.resolve({});
        if (m === 'GET') return new Promise((ok) => waits.push(() => ok({ tag: 'fresh' })));
        return new Promise((ok) => waits.push(() => ok({ tag: b.stages.write ? 'first' : 'second' })));
      };
      S.config = { tag: 'old' };
      const a = setSave('stage-write', { stages: { write: 'local' } });
      const b = setSave('stage-check', { stages: { check: 'claude' } });
      waits[1]();  // 나중 요청이 먼저 온다
      await b;
      const afterSecond = S.config.tag;
      waits[0]();  // 옛 요청이 늦게 온다
      await a;
      const afterFirst = S.config.tag;
      waits[2]();  // 다 끝난 뒤 다시 읽은 GET
      for (let i = 0; i < 5; i += 1) await Promise.resolve();
      return { afterSecond, afterFirst, final: S.config.tag, gets: calls.filter(([m, u]) => m === 'GET' && u === '/config').length,
        notes: [SET.note['stage-write'].kind, SET.note['stage-check'].kind] };
    })()""", {})
    assert got["afterSecond"] == "second"
    assert got["afterFirst"] == "second"  # 늦게 온 옛 응답은 버린다
    assert got["gets"] == 1 and got["final"] == "fresh"  # 버린 응답이 있었으니 끝난 뒤 한 번 다시 읽는다
    assert got["notes"] == ["ok", "ok"]


@needs_node
def test_broken_config_banner_and_reset():
    """설정 파일이 깨지면 맨 위에 보관본과 '기본값으로 새로 시작'을 보이고, 누르면 묻고 POST /config/reset 을 보낸다"""
    got = run_js(FILES, """(async () => {
      setPaint = () => {};
      toast = () => {};
      const calls = [];
      api = async (m, u) => { calls.push([m, u]); return u === '/config/reset' ? { config_broken: false } : {}; };
      let yes = false;
      askConfirm = async () => yes;
      const html = setBrokenHtml({ config_broken: true, config_backup: '/h/.canon/config.json.corrupt-20261108-101500' });
      const lost = setBrokenHtml({ config_broken: true, config_backup: '' });
      const fine = setBrokenHtml({ config_broken: false });
      S.config = { config_broken: true, config_backup: 'x' };
      await actions.setConfigReset();
      const cancel = calls.length;
      yes = true;
      await actions.setConfigReset();
      return { html, lost, fine, cancel, calls, broken: S.config.config_broken };
    })()""", {})
    assert "config.json.corrupt-20261108-101500" in got["html"] and 'data-action="setConfigReset"' in got["html"]
    assert "기본값으로 새로 시작" in got["html"] and 'class="note warn"' in got["html"]
    assert "보관하지 못했어요" in got["lost"]
    assert got["fine"] == ""
    assert got["cancel"] == 0
    assert ["POST", "/config/reset"] in got["calls"] and got["broken"] is False


@needs_node
def test_unreadable_config_banner_has_no_reset():
    """권한 때문에 읽지 못한 설정 파일은 새로 시작을 권하지 않고 권한을 확인하라고 안내한다"""
    got = run_js(FILES, """(() => setBrokenHtml({ config_broken: true, config_unreadable: true, config_backup: '' }))()""", {})
    assert "권한" in got and "setConfigReset" not in got


@needs_node
def test_config_broken_error_refreshes_config():
    """저장이 409 config_broken 으로 막히면 GET /config 로 다시 읽어 맨 위 안내가 서버와 같게 보인다"""
    got = run_js(FILES, """(async () => {
      setPaint = () => {};
      const calls = [];
      api = async (m, u) => {
        calls.push([m, u]);
        if (m === 'PUT') { const e = new Error('설정 파일이 깨져 있어 저장하지 않았어요'); e.code = 'config_broken'; throw e; }
        return { config_broken: true, config_backup: 'b' };
      };
      S.config = { config_broken: false };
      await setSave('model', { model: 'x' });
      for (let i = 0; i < 5; i += 1) await Promise.resolve();
      return { calls, broken: S.config.config_broken };
    })()""", {})
    assert ["GET", "/config"] in got["calls"] and got["broken"] is True


BLOCKS_STATE = """
  setPaint = () => {};
  S.name = 'sr';
  S.dirty = false;
  S.route = ['p', 'sr', 'write', '3'];
  S.project = { meta: { form: 'serial' }, settings: { blocks: [], budgets: [] }, relationships: [], episodes: [] };
  SET.blocks = { name: 'sr',
    blocks: [{ id: 'facts', title: '확정된 사실', locked: false, toggle: true, front: false, note: '', on: true, keys: ['facts'] },
             { id: 'world', title: '세계관', locked: false, toggle: true, front: true, note: '', on: true, keys: [] }],
    budgets: [{ key: 'facts', value: 1500, default: 1500, min: 300, max: 6000 }] };
  const calls = [];
  const waits = [];
  // PUT 은 시험이 풀어 줄 때까지 기다린다 (ok 면 보낸 몸통을 설정으로 돌려주고, 아니면 거절)
  api = (m, u, body) => {
    calls.push([m, u, body ? JSON.parse(JSON.stringify(body)) : null]);
    if (m !== 'PUT') return Promise.resolve([]);
    return new Promise((res, rej) => waits.push((ok) => (ok ? res({ meta: { form: 'serial' }, settings: body, relationships: [], episodes: [] }) : rej(new Error('저장하지 못했어요')))));
  };
  const tick = async () => { for (let i = 0; i < 10; i += 1) await Promise.resolve(); };
  const puts = () => calls.filter((c) => c[0] === 'PUT').map((c) => c[2]);
  const state = () => ({ facts: SET.blocks.blocks[0].on, world: SET.blocks.blocks[1].on, budget: SET.blocks.budgets[0].value });
"""


@needs_node
def test_block_saves_go_one_by_one_and_send_the_last_change():
    """스위치를 빠르게 두 번 누르면 두 번째 저장은 첫 저장이 끝난 뒤 그때 값(다시 켬)을 보낸다"""
    got = run_js(FILES, "(async () => {" + BLOCKS_STATE + """
      actions.setBlock('facts');
      actions.setBlock('facts');
      await tick();
      const sentFirst = puts().length;
      waits[0](true);
      await tick();
      const sentSecond = puts().length;
      waits[1](true);
      await tick();
      return { sentFirst, sentSecond, bodies: puts(), state: state() };
    })()""", {})
    assert got["sentFirst"] == 1 and got["sentSecond"] == 2  # 앞 저장이 끝나야 다음을 보낸다
    assert got["bodies"][0]["blocks"] == [] and got["bodies"][1]["blocks"] == []  # 둘 다 보낼 때의 마지막 값(켬)
    assert got["state"]["facts"] is True


@needs_node
def test_failed_block_save_reverts_only_its_own_change():
    """앞 저장(블록 끄기)이 거절되면 그 변경만 되돌리고, 뒤 저장(예산)은 끈 블록 없이 보낸다"""
    got = run_js(FILES, "(async () => {" + BLOCKS_STATE + """
      actions.setBlock('facts');
      const g = SET.blocks.budgets[0];
      setBlocksSave('budgets', () => { g.value = 2000; }, false);
      actions.setBlock('world');
      await tick();
      waits[0](false);
      await tick();
      const afterFail = state();
      waits[1](true);
      await tick();
      waits[2](true);
      await tick();
      return { afterFail, bodies: puts(), state: state(), note: SET.note.blocks, server: S.project.settings };
    })()""", {})
    assert got["afterFail"] == {"facts": True, "world": False, "budget": 2000}
    assert got["bodies"][1] == {"blocks": [{"id": "world", "on": False}], "budgets": [{"key": "facts", "value": 2000}]}
    assert got["state"] == {"facts": True, "world": False, "budget": 2000}
    assert got["server"]["blocks"] == [{"id": "world", "on": False}]


@needs_node
def test_block_save_drops_the_cached_prompt_text():
    """블록 설정을 저장하면 들고 있던 프롬프트 원문과 토큰 센 값을 버리고 컨텍스트 표를 다시 받는다"""
    got = run_js(FILES, "(async () => {" + BLOCKS_STATE + """
      S.context = [{ id: 'facts' }];
      S.promptText = '[시스템]\\n옛 요청';
      S.ctxCount = { k: 'sr:3', tokens: 10 };
      actions.setBlock('facts');
      await tick();
      waits[0](true);
      await tick();
      return { prompt: S.promptText, count: S.ctxCount, gets: calls.filter((c) => c[0] === 'GET').map((c) => c[1]) };
    })()""", {})
    assert got["prompt"] is None and got["count"] is None
    assert "/projects/sr/episodes/3/context" in got["gets"]
