"""작품 목록 카드 캐시 (web._cards · store.peek). 실행: python -m pytest tests"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store, web

    importlib.reload(store)
    importlib.reload(web)
    return store, web, TestClient(web.app)


def test_cards_read_each_project_once_until_it_changes(env, monkeypatch):
    store, web, client = env
    meta = {"title": "등대", "target_episodes": 10}
    for i in range(6):  # store 캐시(_VIEWS_MAX = 4)보다 많다
        assert client.post("/api/projects", json={"name": f"p{i}", "meta": meta}).status_code == 200
    store._views.clear()

    reads = []
    peek = store.peek
    monkeypatch.setattr(store, "peek", lambda name: reads.append(name) or peek(name))
    monkeypatch.setattr(store, "load", lambda name: pytest.fail("목록이 작품 전체를 읽었어요"))
    first = client.get("/api/projects").json()
    assert sorted(reads) == [f"p{i}" for i in range(6)]

    reads.clear()
    assert client.get("/api/projects").json() == first
    assert reads == []

    # 저장해 판이 바뀐 작품만 다시 읽고, 바뀐 제목이 카드에 보인다
    monkeypatch.undo()
    p = store.load("p2")
    p.meta.title = "새 제목"
    store.save("p2", p)
    store._views.clear()
    monkeypatch.setattr(store, "peek", lambda name: reads.append(name) or peek(name))
    cards = {c["name"]: c for c in client.get("/api/projects").json()}
    assert reads == ["p2"] and cards["p2"]["title"] == "새 제목"

    # 지운 작품은 캐시에서도 빠진다
    import shutil
    shutil.rmtree(store.project_dir("p0"))
    assert "p0" not in {c["name"] for c in client.get("/api/projects").json()}
    assert "p0" not in web._cards


def test_peek_skips_snapshot_files(env):
    store, _, client = env
    assert client.post("/api/projects", json={"name": "s", "meta": {"title": "s", "target_episodes": 3}}).status_code == 200
    from canon.schema import Snapshot

    p = store.load("s")
    p.snapshots = [Snapshot(episode=1)]
    store.save("s", p)
    assert list((store.project_dir("s") / store.SNAP_DIR).glob("*.json"))
    store._views.clear()
    light = store.peek("s")
    assert light.meta.title == "s" and light.snapshots == []
    assert "s" not in store._views  # 스냅샷이 빠진 사본은 캐시에 두지 않는다
    assert store.load("s").snapshots[0].episode == 1
