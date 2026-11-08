"""작품 저장(PUT · PATCH)이 본문이 있던 화를 빼거나 본문을 비우면 서버가 디스크 것을 두고 X-Canon-Kept 로 알린다 (web._keep_texts)."""
import json
from urllib.parse import unquote

from canon import store

from .jsvm import episode


def _setup(client, name="kt"):
    meta = {"title": "등대", "genre": "미스터리", "logline": "x", "target_episodes": 4}
    assert client.post("/api/projects", json={"name": name, "meta": meta}).status_code == 200
    p = store.load(name)
    p.episodes = [episode(1, status="written", text="1화 본문"), episode(2, status="written", text="2화 본문"), episode(3)]
    store.save(name, p)
    return client.get(f"/api/projects/{name}").json()


def _kept(r) -> list:
    head = r.headers.get("X-Canon-Kept")
    return json.loads(unquote(head)) if head else []


def test_put_keeps_dropped_episode_with_text(client):
    sent = _setup(client)
    sent["episodes"] = [e for e in sent["episodes"] if e["plot"]["number"] != 1]
    r = client.put("/api/projects/kt", json=sent)
    assert r.status_code == 200, r.text
    p = store.load("kt")
    assert [e.plot.number for e in p.episodes] == [1, 2, 3]
    assert p.episode(1).text == "1화 본문"
    assert _kept(r) == [{"field": "episode", "ep": 1}]


def test_patch_keeps_text_emptied_even_with_force(client):
    sent = _setup(client)
    eps = [{"$same": e["plot"]["number"]} for e in sent["episodes"]]
    two = next(e for e in sent["episodes"] if e["plot"]["number"] == 2)
    eps[1] = {**two, "text": "", "plot": {**two["plot"], "storyline": ""}}
    body = {"edit_rev": sent["edit_rev"], "fields": {"episodes": eps, "meta": {**sent["meta"], "title": "새 제목"}}}
    r = client.patch("/api/projects/kt?force=true", json=body)  # force 는 충돌 덮어쓰기일 뿐 본문 지키기를 풀지 않는다
    assert r.status_code == 200, r.text
    p = store.load("kt")
    assert p.episode(2).text == "2화 본문"
    assert p.meta.title == "새 제목"  # 다른 칸은 그대로 저장한다
    assert _kept(r) == [{"field": "text", "ep": 2}]


def test_put_allows_dropping_episode_without_text(client):
    sent = _setup(client)
    sent["episodes"] = [e for e in sent["episodes"] if e["plot"]["number"] != 3]
    r = client.put("/api/projects/kt", json=sent)
    assert r.status_code == 200, r.text
    assert [e.plot.number for e in store.load("kt").episodes] == [1, 2]
    assert "X-Canon-Kept" not in r.headers


def test_put_allows_emptying_lists(client):
    """인물 · 떡밥 · 비밀 목록을 비우는 것은 작가가 일부러 지운 결과라 막지 않는다."""
    sent = _setup(client)
    sent["foreshadows"], sent["secrets"] = [], []
    r = client.put("/api/projects/kt", json=sent)
    assert r.status_code == 200, r.text
    assert "X-Canon-Kept" not in r.headers


def test_dedicated_routes_still_remove_episodes(client):
    _setup(client)
    r = client.delete("/api/projects/kt/episodes/3")
    assert r.status_code == 200, r.text
    r = client.post("/api/projects/kt/episodes/2/delete", json={})
    assert r.status_code == 200, r.text
    assert [e.plot.number for e in store.load("kt").episodes] == [1]
