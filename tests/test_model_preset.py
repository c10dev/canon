"""작품별 단계 프리셋 (Settings.model_preset, settings.project_preset). 화면 계산(static/settings.js 의 projectStage)은 node 가 있을 때만 돈다."""
import importlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from canon.schema import Meta, Project

SETTINGS_JS = Path(__file__).resolve().parent.parent / "canon" / "static" / "settings.js"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """mock 이 아닌 전체 설정: 모든 단계 gemini, 설정 파일의 단계 칸은 상태 변경안만 로컬."""
    for name in ("CANON_LLM", "CANON_MODEL", "CANON_CLAUDE_MODEL", "CANON_LOCAL_MODEL"):
        monkeypatch.delenv(name, raising=False)
    from canon import settings
    for s in settings.STAGES:
        monkeypatch.delenv(f"CANON_LLM_{s.upper()}", raising=False)
        monkeypatch.delenv(f"CANON_MODEL_{s.upper()}", raising=False)
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store
    importlib.reload(store)
    settings.update(provider="gemini", stages={"state": "local"})
    store.save("a", Project(meta=Meta(title="가")))
    store.save("b", Project(meta=Meta(title="나")))
    return settings, store


def _pick(store, name, preset):
    p = store.load(name)
    p.settings.model_preset = preset
    store.save(name, p)


def test_old_project_loads_without_preset():
    p = Project.model_validate({"meta": {"title": "옛 작품"}, "settings": {"show_numbers": True}})
    assert p.settings.model_preset == ""


def test_project_preset_only_inside_its_project(env):
    settings, store = env
    from canon import usage
    _pick(store, "a", "anthropic")
    assert store.model_preset("a") == "anthropic" and store.model_preset("b") == ""
    with usage.scope(project="a"):
        assert settings.stage_provider("write") == ("claude-api", "project")
        assert settings.stage_model("state") == ("claude-sonnet-5-5", "project")
        # 프리셋에 없는 단계는 부모 단계를 따르고, 설정 파일의 단계 칸(state=local)은 보지 않는다
        assert settings.stage_provider("revise")[0] == "claude-api"
        assert settings.stage_model("revise")[0] == "claude-opus-5-5"
        assert settings.stage_model("name")[0] == "claude-haiku-5-5"
    with usage.scope(project="b"):
        assert settings.stage_provider("write") == ("gemini", "file")
        assert settings.stage_provider("state") == ("local", "file")
    assert settings.stage_provider("write")[0] == "gemini"  # 작품 밖
    assert settings.stage_provider("write", settings.find_preset("anthropic"))[0] == "claude-api"  # 직접 줄 수도 있다


def test_get_llm_uses_project_preset(env, monkeypatch):
    settings, store = env
    from canon import llm, usage
    made = []
    monkeypatch.setattr(llm, "make_llm", lambda prov, model=None: made.append((prov, model)) or type("Fake", (), {})())
    _pick(store, "a", "anthropic")
    with usage.scope(project="a"):
        llm.get_llm("check")
    with usage.scope(project="b"):
        llm.get_llm("check")
    assert made == [("claude-api", "claude-opus-5-5"), ("gemini", "")]


def test_deleted_preset_falls_back_to_global(env):
    settings, store = env
    from canon import usage
    mine = settings.save_preset("본문만 로컬", {"write": "local"}, {})
    _pick(store, "a", mine["id"])
    with usage.scope(project="a"):
        assert settings.stage_provider("write")[0] == "local"
        assert settings.stage_provider("state")[0] == "gemini"  # 프리셋에 없는 단계는 생성 방식
    settings.delete_preset(mine["id"])
    assert settings.project_preset("a") is None
    with usage.scope(project="a"):
        assert settings.stage_provider("write")[0] == "gemini"
        assert settings.stage_provider("state")[0] == "local"


def test_env_wins_over_project_preset(env, monkeypatch):
    settings, store = env
    from canon import usage
    _pick(store, "a", "anthropic")
    monkeypatch.setenv("CANON_LLM_WRITE", "local")
    monkeypatch.setenv("CANON_MODEL_PLAN", "gemini-3.8-flash")
    with usage.scope(project="a"):
        assert settings.stage_provider("write") == ("local", "env")
        assert settings.stage_model("plan") == ("gemini-3.8-flash", "env")
        assert settings.stage_provider("check")[0] == "claude-api"
    monkeypatch.setenv("CANON_LLM", "mock")  # mock 이면 모든 단계가 mock
    with usage.scope(project="a"):
        assert settings.stage_provider("check")[0] == "mock"


def test_store_reads_preset_again_after_save(env):
    settings, store = env
    assert store.model_preset("a") == ""
    _pick(store, "a", "gemini")
    assert store.model_preset("a") == "gemini"
    _pick(store, "a", "")
    assert store.model_preset("a") == ""
    assert store.model_preset("없는작품") == ""


def test_web_sets_project_preset(env):
    settings, store = env
    from canon import web
    importlib.reload(web)
    client = TestClient(web.app)
    assert client.put("/api/projects/a/model-preset", json={"preset": "없음"}).status_code == 404
    r = client.put("/api/projects/a/model-preset", json={"preset": "anthropic"})
    assert r.status_code == 200 and r.json()["settings"]["model_preset"] == "anthropic"
    assert store.load("a").settings.model_preset == "anthropic"
    assert client.get("/api/config").json()["stages"]["write"]["provider"] == "gemini"  # 전체 설정 화면은 그대로
    assert client.put("/api/projects/a/model-preset", json={"preset": ""}).json()["settings"]["model_preset"] == ""


def test_cli_model(env, capsys):
    settings, store = env
    from canon import cli
    cli.main(["model", "a", "Anthropic (Claude API 키)"])  # 이름으로도 고른다
    assert store.load("a").settings.model_preset == "anthropic"
    assert "write: claude-api · claude-opus-5-5" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["model", "a", "없음"])
    cli.main(["model", "a", "--clear"])
    assert store.load("a").settings.model_preset == ""
    assert "전체 설정을 따라요" in capsys.readouterr().out


# settings.js 가 읽힐 때 거는 이벤트만 흉내 내고, projectStage 결과를 돌려준다
HARNESS = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = { data, S: { config: data.config, project: data.project }, actions: {}, document: { addEventListener() {} }, window: { addEventListener() {} } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + `
;globalThis.out = Object.fromEntries(data.stages.map((s) => [s, projectStage(s)]));`, ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
@pytest.mark.parametrize("preset", ["anthropic", "mine", "", "gone"])
def test_js_project_stage_matches_server(env, monkeypatch, preset):
    settings, store = env
    monkeypatch.setenv("CANON_MODEL_CHECK", "gemini-3.8-flash")  # 단계 환경 변수는 화면도 프리셋보다 앞세운다
    mine = settings.save_preset("계획만 Claude", {"plan": "claude"}, {"state": "gemini-3.8-flash"})
    pid = {"mine": mine["id"], "gone": "my-gone"}.get(preset, preset)
    _pick(store, "a", pid)
    stages = ["plan", "write", "check", "state", "name", "revise", "illustration"]
    data = {"config": settings.public(), "project": json.loads(store.load("a").model_dump_json()), "stages": stages}
    run = subprocess.run(["node", "-e", HARNESS, str(SETTINGS_JS)], input=json.dumps(data), capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    want = settings.stage_view(settings.project_preset("a"))
    assert {s: (got[s]["provider"], got[s]["model"]) for s in stages} == {s: (want[s]["provider"], want[s]["model"]) for s in stages}
