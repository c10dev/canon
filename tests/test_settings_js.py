"""설정 대화상자(static/settings.js): 찾기 · 주소 · 프리셋 맞춤 · 환경 변수 목록은 node 로, 바로 저장하는 작품 설정 API 는 서버로 맞춰 본다."""
import importlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from canon.schema import Meta, Project
from .jsvm import needs_node, run_js

FILES = ["app.js", "settings.js"]
ROWS = "SET_ROWS.map((r) => ({ cat: r.cat, label: r.label, sec: r.sec, words: r.words }))"


@needs_node
def test_settings_match():
    got = run_js(FILES, f"""(() => {{
      const ids = (q) => settingsMatch(SET_ROWS, q).map((r) => r.id);
      return {{ key: ids('키'), apiKey: ids('API 키'), stage: ids('검수'), none: ids('없는말'), blank: ids('  '),
        spaced: ids('스냅 샷'), cat: ids('이 브라우저'), group: ids('고급') }};
    }})()""", {})
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
def test_palette_finds_setting_rows():
    got = run_js(["app.js", "settings.js", "palette.js"], f"""(() => {{
      const settings = {ROWS}.map((r) => ({{ ...r, where: setCat(r.cat)[1] }}));
      const items = paletteItems({{ inProject: false, settings }});
      return {{ empty: paletteMatch(items, '').map((i) => i.label), key: paletteMatch(items, 'Anthropic').map((i) => [i.kind, i.label, i.act, i.cat, i.hint]) }};
    }})()""", {})
    assert got["empty"] == ["작품 목록", "설정", "알림 · AI 작업"]  # 검색어가 없으면 설정 줄은 숨긴다
    assert got["key"][0] == ["setting", "Anthropic API 키", "settings", "ai", "AI 연결 · Claude"]


def test_no_old_settings_route_left():
    """설정은 화면이 아니라 대화상자다: app.js 가 'settings' 화면을 그리거나 저장 안 한 설정을 묻지 않는다"""
    app = (Path(__file__).resolve().parent.parent / "canon" / "static" / "app.js").read_text(encoding="utf-8")
    assert "settingsDirty" not in app and "viewSettings" not in app
    assert re.search(r"settingsCat\(location\.hash\)", app)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store, web
    importlib.reload(store)
    store.save("a", Project(meta=Meta(title="가", form="serial")))
    return TestClient(web.app), store


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
