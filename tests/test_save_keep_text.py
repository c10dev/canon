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


def test_put_force_from_stale_tab_keeps_written_status(client):
    """오래된 탭이 2화를 아직 안 쓴(confirmed · 빈 본문) 사본으로 덮어써도 상태와 본문을 함께 디스크 것으로 둔다.
    본문만 되돌리면 본문이 있는데 안 쓴 화로 보여 플롯 잠금이 풀리고 다시 쓰기가 본문을 덮는다."""
    sent = _setup(client)
    two = next(e for e in sent["episodes"] if e["plot"]["number"] == 2)
    two.update(status="confirmed", text="")
    two["plot"]["summary"] = "옛 요약"
    r = client.put("/api/projects/kt?force=true", json=sent)
    assert r.status_code == 200, r.text
    ep = store.load("kt").episode(2)
    assert (ep.status, ep.text, ep.plot.summary) == ("written", "2화 본문", "")
    assert {"field": "text", "ep": 2} in _kept(r)


def test_patch_text_empty_with_lower_status_keeps_written(client):
    sent = _setup(client)
    eps = [{"$same": e["plot"]["number"]} for e in sent["episodes"]]
    two = next(e for e in sent["episodes"] if e["plot"]["number"] == 2)
    eps[1] = {**two, "text": "", "status": "confirmed"}
    r = client.patch("/api/projects/kt", json={"edit_rev": sent["edit_rev"], "fields": {"episodes": eps}})
    assert r.status_code == 200, r.text
    ep = store.load("kt").episode(2)
    assert (ep.status, ep.text) == ("written", "2화 본문")


def test_put_skips_renumbered_copy(client):
    """화 끼워 넣기로 번호가 밀린 뒤 옛 탭이 덮어쓰면, 빠진 끝 화는 옛 탭이 앞 번호로 보낸 본문과 같아 되살리지 않는다."""
    sent = _setup(client)
    p = store.load("kt")
    p.episodes = [episode(1, status="written", text="1화 본문"), episode(2), episode(3, status="written", text="2화 본문")]
    store.save("kt", p)
    sent["episodes"] = [e for e in sent["episodes"] if e["plot"]["number"] != 3]  # 옛 탭: 1화, 2화(2화 본문)
    r = client.put("/api/projects/kt?force=true", json=sent)
    assert r.status_code == 200, r.text
    p = store.load("kt")
    assert [(e.plot.number, e.text) for e in p.episodes] == [(1, "1화 본문"), (2, "2화 본문")]
    assert _kept(r) == []


def test_put_skips_renumbered_copy_when_text_emptied(client):
    """화 지우기(본문을 앞으로 당김) 뒤 옛 탭이 덮어쓰면, 비운 2화 자리에 당겨진 3화 본문을 되돌리지 않는다 (같은 본문이 두 화에 생기지 않게)."""
    sent = _setup(client)
    sent["episodes"] = [episode(1, status="written", text="1화 본문").model_dump(), episode(2).model_dump(),
                        episode(3, status="written", text="3화 본문").model_dump()]  # 옛 탭: 2화는 본문 없는 초안
    p = store.load("kt")
    p.episodes = [episode(1, status="written", text="1화 본문"), episode(2, status="written", text="3화 본문")]
    store.save("kt", p)  # 디스크: 2화를 지워 3화 본문이 2화로 당겨졌다
    r = client.put("/api/projects/kt?force=true", json=sent)
    assert r.status_code == 200, r.text
    texts = [e.text for e in store.load("kt").episodes]
    assert texts.count("3화 본문") == 1
    assert _kept(r) == []


def test_put_restored_episode_drops_gone_character_and_storyline(client):
    from canon.schema import Character, Storyline
    _setup(client)
    p = store.load("kt")
    p.characters = [Character(id="a", name="가", role=""), Character(id="x", name="엑스", role="")]
    p.storylines = [Storyline(id="sl-01")]
    p.episodes[0] = episode(1, status="written", text="1화 본문", plot={"characters": ["a", "x"], "storyline": "sl-01", "pov": "x"})
    store.save("kt", p)
    sent = client.get("/api/projects/kt").json()
    sent["characters"] = [c for c in sent["characters"] if c["id"] != "x"]
    sent["storylines"] = []
    sent["episodes"] = [e for e in sent["episodes"] if e["plot"]["number"] != 1]
    r = client.put("/api/projects/kt", json=sent)
    assert r.status_code == 200, r.text
    ep = store.load("kt").episode(1)
    assert ep.text == "1화 본문"
    assert (ep.plot.characters, ep.plot.storyline, ep.plot.pov) == (["a"], "", "")


def test_put_marks_restored_episode_over_target(client):
    _setup(client)
    p = store.load("kt")
    p.episodes.append(episode(5, status="written", text="5화 본문"))
    store.save("kt", p)
    sent = client.get("/api/projects/kt").json()
    sent["episodes"] = [e for e in sent["episodes"] if e["plot"]["number"] != 5]
    r = client.put("/api/projects/kt", json=sent)
    assert r.status_code == 200, r.text
    assert store.load("kt").episode(5).text == "5화 본문"
    assert _kept(r) == [{"field": "episode", "ep": 5, "why": "over_target"}]
