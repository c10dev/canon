"""문체 라이브러리 (mock LLM). 실행: python -m pytest tests"""
import importlib
import json
import os

import pytest
from fastapi.testclient import TestClient

SAMPLE = open(os.path.join(os.path.dirname(__file__), "..", "examples", "sample_style.txt"), encoding="utf-8").read()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("CANON_STYLES", raising=False)
    from canon import library, store, web

    importlib.reload(store)
    importlib.reload(library)
    importlib.reload(web)
    return TestClient(web.app)


def test_library_crud_and_apply(client, tmp_path):
    assert client.get("/api/styles").json() == []
    prof = client.post("/api/styles/analyze", json={"text": SAMPLE}).json()
    assert prof["narration_pov"]
    assert client.post("/api/styles/analyze", json={"text": "짧다"}).status_code == 400
    assert client.post("/api/styles", json={"name": "  ", "profile": prof}).status_code == 400

    e = client.post("/api/styles", json={"name": "건조체", "source": "예시", "sample": SAMPLE, "profile": prof}).json()
    assert e["baseline"]["sentences"] > 0 and (tmp_path / ".styles" / f"{e['id']}.json").exists()

    # 작품 폴더 목록에는 섞이지 않는다
    meta = {"title": "등대", "target_episodes": 10}
    client.post("/api/projects", json={"name": "a", "meta": meta, "style_id": e["id"]})
    client.post("/api/projects", json={"name": "b", "meta": meta})
    assert [x["name"] for x in client.get("/api/projects").json()] == ["a", "b"]

    a = client.get("/api/projects/a").json()
    assert a["style_id"] == e["id"] and a["style"] == prof and a["style_baseline"]["sentences"] > 0
    assert client.get("/api/projects/a/style/link").json()["state"] == "same"
    assert client.get("/api/projects/b/style/link").json() == {"state": "none"}

    # 라이브러리를 고쳐도 작품은 다시 적용하기 전까지 그대로
    changed = dict(prof, tense="현재형")
    up = client.put(f"/api/styles/{e['id']}", json={"name": "건조체 2", "sample": SAMPLE, "profile": changed}).json()
    assert up["used_by"] == ["a"] and up["baseline"] == e["baseline"]
    assert client.get("/api/projects/a").json()["style"]["tense"] == prof["tense"]
    assert client.get("/api/projects/a/style/link").json()["state"] == "changed"
    a = client.post("/api/projects/a/style/apply", json={"style_id": e["id"]}).json()
    assert a["style"]["tense"] == "현재형"

    # 작품에서 고친 문체로 라이브러리 항목을 갱신
    a["style"]["dos"] = ["짧게 쓴다"]
    client.put("/api/projects/a", json=a)
    client.post("/api/projects/a/style/library", json={"update": True})
    assert client.get(f"/api/styles/{e['id']}").json()["profile"]["dos"] == ["짧게 쓴다"]
    assert client.post("/api/projects/b/style/library", json={"update": True}).status_code == 400

    # 작품 문체를 새 항목으로 저장하면 그 항목에 연결된다
    r = client.post("/api/projects/b/style/library", json={"name": "b 문체", "sample": SAMPLE}).json()
    assert r["project"]["style_id"] == r["entry"]["id"] and r["project"]["style_baseline"]

    dup = client.post(f"/api/styles/{e['id']}/duplicate").json()
    assert dup["name"] == "건조체 2 사본" and dup["id"] != e["id"] and dup["profile"]["dos"] == ["짧게 쓴다"]
    listed = client.get("/api/styles").json()
    assert len(listed) == 3 and {x["id"]: x["used_by"] for x in listed}[e["id"]] == ["a"]

    # 지워도 작품의 복사본은 남는다
    assert client.delete(f"/api/styles/{e['id']}").json() == {"ok": True}
    assert client.get(f"/api/styles/{e['id']}").status_code == 404
    assert client.get("/api/projects/a/style/link").json()["state"] == "missing"
    assert client.get("/api/projects/a").json()["style"]["dos"] == ["짧게 쓴다"]
    assert client.get("/api/styles/..%2Fa").status_code == 404
    assert client.post("/api/projects/a/style/apply", json={"style_id": "nope"}).status_code == 400


def test_old_project_json_loads(client, tmp_path):
    """style_id 가 없던 project.json 도 읽힌다."""
    d = tmp_path / "old"
    d.mkdir()
    (d / "project.json").write_text(json.dumps({"meta": {"title": "옛 작품"}}), encoding="utf-8")
    assert client.get("/api/projects/old").json()["style_id"] == ""
    assert client.get("/api/projects/old/style/link").json() == {"state": "none"}


def test_cli_styles(client, tmp_path, capsys):
    from canon import cli, library, store

    f = tmp_path / "s.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    cli.main(["styles", "add", "건조체", str(f), "-y"])
    [e] = library.entries()
    store.save("x", store.Project())
    cli.main(["style", "x", "--library", e.id, "-y"])
    assert store.load("x").style_id == e.id
    cli.main(["styles"])
    assert "건조체" in capsys.readouterr().out
    cli.main(["style", "x", str(f), "--save", "새 문체", "-y"])
    p = store.load("x")
    assert p.style_id != e.id and library.load(p.style_id).name == "새 문체"
    cli.main(["styles", "rm", e.id, "-y"])
    assert len(library.entries()) == 1


def test_web_analysis_keeps_baseline(client):
    """작품 화면에서 분석한 원문의 기준 지표를 project.json 에 남길 수 있다."""
    client.post("/api/projects", json={"name": "w", "meta": {"title": "w", "target_episodes": 10}})
    p = client.get("/api/projects/w").json()
    p["style"] = client.post("/api/projects/w/style", json={"text": SAMPLE}).json()
    p["style_baseline"] = client.post("/api/metrics", json={"text": SAMPLE}).json()
    p = client.put("/api/projects/w", json=p).json()
    assert p["style_baseline"]["chars"] >= len(SAMPLE.strip()) - 50 and p["style_baseline"]["sentences"] > 5
