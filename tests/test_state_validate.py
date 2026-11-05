"""상태 반영 전 서버 검사: 누구의 것도 아닌 항목(설정에 없는 인물 · 같은 인물끼리 · 없는 복선)과 본문 지문(basis)."""
import copy
import importlib

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


def _written(client, name="sv"):
    client.post("/api/projects", json={"name": name, "meta": {"title": "등대", "target_episodes": 10}})
    p = client.post(f"/api/projects/{name}/suggest/apply", json=client.post(f"/api/projects/{name}/suggest").json()).json()
    p["arc"] = client.post(f"/api/projects/{name}/arc").json()["acts"]
    client.put(f"/api/projects/{name}", json=p)
    client.post(f"/api/projects/{name}/plots", json={})
    client.post(f"/api/projects/{name}/episodes/1/confirm")
    client.post(f"/api/projects/{name}/episodes/1/write")
    return client.post(f"/api/projects/{name}/episodes/1/state").json()


def test_extract_and_parse_set_basis(client):
    from canon import pipeline, store

    d = _written(client)
    assert d["basis"] == pipeline.text_basis(store.load("sv").episode(1).text) != ""
    got = client.post("/api/projects/sv/episodes/1/state/parse", json={"raw": '{"summary": "요약"}'}).json()
    assert got["basis"] == d["basis"]


def test_basis_not_in_ai_schema():
    from canon.schema import StateDelta

    assert "basis" in StateDelta.model_fields
    assert "basis" not in StateDelta.model_json_schema()["properties"]


def test_apply_refuses_unknown_ids_with_list(client):
    from canon import store

    d = _written(client)
    bad = copy.deepcopy(d)
    cu = copy.deepcopy(d["character_updates"][0])
    cu["character_id"] = "ghost"
    bad["character_updates"].append(cu)
    a = d["character_updates"][0]["character_id"]
    bad["events"].append({"episode": 1, "actor": a, "target": a, "kind": "도움"})
    bad["relationship_updates"].append({"a": a, "b": "nobody", "type": "적"})
    bad["foreshadow_resolved"].append("fs-none")
    r = client.post("/api/projects/sv/episodes/1/apply", json=bad)
    assert r.status_code == 400
    msg = r.json()["detail"]
    assert "4개" in msg and "ghost" in msg and "nobody" in msg and "fs-none" in msg and "같은 인물끼리" in msg
    p = store.load("sv")
    assert p.episode(1).status == "written" and p.state_of("ghost") is None  # 아무것도 저장하지 않았다
    assert client.post("/api/projects/sv/episodes/1/apply", json=d).status_code == 200


def test_new_character_and_planted_foreshadow_count_as_known(client):
    d = _written(client)
    ok = copy.deepcopy(d)
    ok["new_characters"] = [{"id": "newbie", "name": "새 인물", "role": "행인", "tier": "minor"}]
    cu = copy.deepcopy(d["character_updates"][0])
    cu["character_id"] = "newbie"
    ok["character_updates"].append(cu)
    assert ok["foreshadow_planted"]
    ok["foreshadow_resolved"] = [ok["foreshadow_planted"][0]["id"]]
    r = client.post("/api/projects/sv/episodes/1/apply", json=ok)
    assert r.status_code == 200, r.json()
    assert any(s["character_id"] == "newbie" for s in r.json()["states"])


def test_apply_delta_drops_invalid_items(client):
    """자동 집필 · 명령줄 · 플레이 경로(pipeline.apply_delta)는 막지 않고 빼고 반영한 뒤 뺀 항목을 돌려준다."""
    from canon import pipeline, store
    from canon.schema import StateDelta

    d = StateDelta.model_validate(_written(client))
    p = store.load("sv")
    assert d.events
    a = d.character_updates[0].character_id
    d.character_updates.append(d.character_updates[0].model_copy(update={"character_id": "ghost"}))
    d.events.append(d.events[0].model_copy(update={"actor": a, "target": a}))
    d.events[0].witnesses = ["ghost"]  # 목격자는 빼고 사건은 남긴다
    d.foreshadow_resolved.append("fs-none")
    assert len(pipeline.validate_delta(p, d)) == 3
    dropped = pipeline.apply_delta(p, d)
    assert len(dropped) == 3
    assert p.state_of("ghost") is None and p.episode(1).status == "finalized"
    ev = [e for e in p.events if e.episode == 1]
    assert ev and all(e.actor != e.target for e in ev) and all("ghost" not in e.witnesses for e in ev)
    assert "fs-none" not in p.history[-1].foreshadow_resolved


def test_apply_refuses_stale_basis_unless_forced(client):
    from canon import store

    d = _written(client)
    p = client.put("/api/projects/sv/episodes/1/text", json={"text": store.load("sv").episode(1).text + " 덧붙임."}).json()
    assert p["episodes"][0]["status"] == "written"
    r = client.post("/api/projects/sv/episodes/1/apply", json=d)
    assert r.status_code == 409 and r.json()["code"] == "stale_delta" and "본문을 고쳤어요" in r.json()["detail"]
    assert store.load("sv").episode(1).status == "written"
    assert client.post("/api/projects/sv/episodes/1/apply?force=1", json=d).status_code == 200


def test_apply_without_basis_is_not_checked(client):
    """옛 pending.json · 손으로 만든 변경안(basis 빈칸)은 본문 지문을 보지 않는다."""
    from canon import store

    d = _written(client)
    client.put("/api/projects/sv/episodes/1/text", json={"text": store.load("sv").episode(1).text + " 덧붙임."})
    d["basis"] = ""
    assert client.post("/api/projects/sv/episodes/1/apply", json=d).status_code == 200


def test_apply_refuses_secret_of_unknown_owner(client):
    """설정에 없는 인물의 비밀은 누구의 것도 아니라 web 반영이 막는다. 모르는 인물 · 드러낸 비밀의 없는 id 는 막지 않고 뺀다."""
    from canon import store

    d = _written(client)
    a = d["character_updates"][0]["character_id"]
    bad = copy.deepcopy(d)
    bad["secrets_added"].append({"id": "sec-ghost", "owner": "ghost", "content": "숨긴 일"})
    r = client.post("/api/projects/sv/episodes/1/apply", json=bad)
    assert r.status_code == 400 and "ghost" in r.json()["detail"] and "비밀" in r.json()["detail"]
    assert store.load("sv").episode(1).status == "written"
    ok = copy.deepcopy(d)
    ok["secrets_added"].append({"id": "sec-x", "owner": a, "content": "숨긴 일", "hidden_from": ["nobody", a]})
    ok["events"].append({**d["events"][0], "reveals_secret": "sec-none"})
    r = client.post("/api/projects/sv/episodes/1/apply", json=ok)
    assert r.status_code == 200, r.json()
    p = store.load("sv")
    assert next(s for s in p.secrets if s.id == "sec-x").hidden_from == [a]
    assert all(e.reveals_secret != "sec-none" for e in p.events)


def test_apply_delta_drops_bad_secret_refs(client):
    """자동 집필 · 명령줄 경로: 주인이 없는 비밀은 빼서 dismissed 에 두고, 모르는 인물 · 드러낸 비밀의 없는 id 는 지우고 문구를 돌려준다."""
    from canon import pipeline, store
    from canon.schema import Secret, StateDelta

    d = StateDelta.model_validate(_written(client))
    p = store.load("sv")
    a = d.character_updates[0].character_id
    d.secrets_added = [Secret(id="sec-ghost", owner="ghost", content="숨긴 일"),
                       Secret(id="sec-ok", owner=a, content="편지", hidden_from=["nobody"])]
    d.events[0].reveals_secret = "sec-ghost"  # 빠진 비밀을 가리키면 지운다
    assert len(pipeline.validate_delta(p, d)) == 1
    dropped = pipeline.apply_delta(p, d)
    assert len(dropped) == 3 and any("nobody" in m for m in dropped) and any("sec-ghost" in m and "지웠어요" in m for m in dropped)
    assert "sec-ghost" not in {s.id for s in p.secrets} and next(s for s in p.secrets if s.id == "sec-ok").hidden_from == []
    assert [s.id for s in p.history[-1].dismissed.secrets_added] == ["sec-ghost"]
    assert all(e.reveals_secret != "sec-ghost" for e in p.events)
