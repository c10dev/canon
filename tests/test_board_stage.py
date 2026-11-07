"""스토리보드 · 큐 시트 단계 (settings.STAGES 의 board, 부모는 plan). 웹 쓰기 · cues · board 작업이 이 단계로 부른다."""
from fastapi.testclient import TestClient

from canon import settings

from .test_cue_write import demo  # noqa: F401  (fixture)
from .test_web import _wait


def test_board_stage_follows_plan(tmp_path, monkeypatch):
    for name in ("CANON_LLM", "CANON_MODEL"):
        monkeypatch.delenv(name, raising=False)
    for s in settings.STAGES:
        monkeypatch.delenv(f"CANON_LLM_{s.upper()}", raising=False)
        monkeypatch.delenv(f"CANON_MODEL_{s.upper()}", raising=False)
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    assert settings.STAGES.index("board") == settings.STAGES.index("plan") + 1
    assert settings.STAGE_PARENT["board"] == "plan"
    settings.update(provider="gemini", stages={"plan": "local"}, stage_models={"plan": "planner"})
    assert settings.stage_provider("board")[0] == "local"  # 비우면 계획 단계를 따른다
    assert settings.stage_model("board")[0] == "planner"
    settings.update(stages={"plan": "local", "board": "gemini"}, stage_models={"plan": "planner", "board": "gemini-3.8-flash"})
    assert settings.stage_provider("board")[0] == "gemini"
    assert settings.stage_model("board")[0] == "gemini-3.8-flash"
    assert settings.stage_provider("plan")[0] == "local"  # 계획 단계는 그대로


def test_web_jobs_use_board_stage(demo, monkeypatch):  # noqa: F811
    from canon import web

    asked: list[str] = []
    real = web.get_llm
    monkeypatch.setattr(web, "get_llm", lambda stage, *a, **k: asked.append(stage) or real(stage, *a, **k))
    c = TestClient(web.app)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 1})  # 큐 시트를 먼저 만들고 쓴다
    assert _wait(c, r.json()["id"])["status"] == "done"
    assert asked == ["write", "board"]
    asked.clear()
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "cues", "ep": 1})
    assert _wait(c, r.json()["id"])["status"] == "done"
    assert asked == ["board"]
