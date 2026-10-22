"""웹 API 전체 흐름 테스트 (mock LLM). 실행: python -m pytest tests"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store, web

    importlib.reload(store)
    importlib.reload(web)
    return TestClient(web.app)


def test_full_flow(client):
    meta = {"title": "등대", "genre": "미스터리", "logline": "오빠를 찾는다", "target_episodes": 10}
    assert client.post("/api/projects", json={"name": "lh", "meta": meta}).status_code == 200
    assert client.post("/api/projects", json={"name": "lh", "meta": meta}).status_code == 409
    assert client.get("/api/projects").json()[0]["name"] == "lh"

    s = client.post("/api/projects/lh/suggest").json()
    p = client.post("/api/projects/lh/suggest/apply", json=s).json()
    assert len(p["characters"]) == 2 and len(p["states"]) == 2

    sample = open(os.path.join(os.path.dirname(__file__), "..", "examples", "sample_style.txt"), encoding="utf-8").read()
    p["style"] = client.post("/api/projects/lh/style", json={"text": sample}).json()
    p["arc"] = client.post("/api/projects/lh/arc").json()["acts"]
    p = client.put("/api/projects/lh", json=p).json()
    assert p["style"]["narration_pov"] and len(p["arc"]) == 4

    bad = dict(p, arc=[dict(a) for a in p["arc"]])
    bad["arc"][0]["end_ep"] = 5
    assert client.put("/api/projects/lh", json=bad).status_code == 400

    p = client.post("/api/projects/lh/plots", json={}).json()
    assert [e["status"] for e in p["episodes"]] == ["draft"] * 10
    assert client.post("/api/projects/lh/episodes/1/write").status_code == 400  # 확정 전

    client.post("/api/projects/lh/episodes/1/confirm")
    client.post("/api/projects/lh/episodes/2/confirm")
    assert client.post("/api/projects/lh/episodes/2/write").status_code == 400  # 1화 반영 전
    p = client.post("/api/projects/lh/episodes/1/write").json()
    assert p["episodes"][0]["status"] == "written"

    ctx = client.get("/api/projects/lh/episodes/1/context").json()
    assert ctx[0]["title"] == "작품 정보" and all(c["chars"] >= 0 for c in ctx)
    assert "작업지시서" in client.get("/api/projects/lh/episodes/1/brief").json()["text"]
    assert "JSON" in client.get("/api/projects/lh/episodes/1/brief?kind=state").json()["text"]

    d = client.post("/api/projects/lh/episodes/1/state").json()
    d["new_facts"] = []  # 화면에서 체크를 푼 항목
    p = client.post("/api/projects/lh/episodes/1/apply", json=d).json()
    assert p["episodes"][0]["status"] == "finalized" and p["facts"] == [] and len(p["foreshadows"]) == 1
    assert client.post("/api/projects/lh/episodes/1/apply", json=d).status_code == 400

    # 채팅 앱 경로: 본문 가져오기 → JSON 붙여넣기
    p = client.put("/api/projects/lh/episodes/2/text", json={"text": "바람이 불었다."}).json()
    assert p["episodes"][1]["status"] == "written"
    raw = '```json\n{"episode": 9, "summary": "요약", "foreshadow_resolved": ["fs-01-key"]}\n```'
    d = client.post("/api/projects/lh/episodes/2/state/parse", json={"raw": raw}).json()
    assert d["episode"] == 2
    assert client.post("/api/projects/lh/episodes/2/state/parse", json={"raw": "{oops"}).status_code == 400
    p = client.post("/api/projects/lh/episodes/2/apply", json=d).json()
    assert p["foreshadows"][0]["status"] == "resolved"


def test_bad_names(client):
    assert client.get("/api/projects/nope").status_code == 404
    assert client.post("/api/projects", json={"name": "../x", "meta": {}}).status_code == 400
    assert client.get("/").status_code == 200


def test_settings(client, tmp_path, monkeypatch):
    for name in ("CANON_LLM", "CANON_MODEL", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    c = client.get("/api/config").json()
    assert c["provider"] == "gemini" and not c["has_key"] and c["key_source"] == "none"

    c = client.put("/api/config", json={"api_key": "AIza-secret-1234", "model": "gemini-2.5-flash"}).json()
    assert c["has_key"] and c["key_hint"] == "…1234" and c["model"] == "gemini-2.5-flash"
    assert "secret" not in str(c)
    cfg = tmp_path / "config.json"
    assert oct(cfg.stat().st_mode & 0o777) == "0o600"

    # 키를 비워 보내지 않으면 그대로, 환경 변수가 있으면 환경 변수가 우선
    c = client.put("/api/config", json={"model": "gemini-2.5-pro"}).json()
    assert c["key_source"] == "file" and c["model"] == "gemini-2.5-pro"
    monkeypatch.setenv("GEMINI_API_KEY", "env-key-9999")
    assert client.get("/api/config").json()["key_source"] == "env"
    monkeypatch.delenv("GEMINI_API_KEY")

    assert client.put("/api/config", json={"provider": "claude"}).status_code == 400
    assert client.put("/api/config", json={"clear_key": True}).json()["key_source"] == "none"

    # 화면에서 mock 으로 바꾸면 AI 호출도 mock 으로 간다
    client.put("/api/config", json={"provider": "mock"})
    assert client.post("/api/config/test").json()["ok"]
    from canon.llm import get_llm
    from canon.mock import MockLLM
    assert isinstance(get_llm(), MockLLM)
