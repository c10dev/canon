"""작품 저장 PATCH: 바뀐 칸만 받고, 고치지 않은 화는 {"$same": 화} 로 디스크 것을 쓴다. 화면의 patchBody 도 본다."""
from .jsvm import needs_node, run_js
from .test_web import client  # noqa: F401  (pytest fixture)

META = {"title": "등대", "genre": "미스터리", "logline": "오빠를 찾는다", "target_episodes": 10}


def _new(client):  # noqa: F811
    assert client.post("/api/projects", json={"name": "pt", "meta": META}).status_code == 200
    client.post("/api/projects/pt/arc", json={})
    return client.get("/api/projects/pt").json()


def test_patch_changes_only_sent_fields(client):  # noqa: F811
    from canon import store
    p = _new(client)
    p2 = store.load("pt")
    p2.world.setting = "디스크에서 바뀐 세계"  # 다른 곳이 그 사이 저장했다 (화면은 world 를 고치지 않았다)
    store.save("pt", p2)
    r = client.patch("/api/projects/pt", json={"edit_rev": p["edit_rev"], "fields": {"meta": {**p["meta"], "logline": "새 로그라인"}}})
    assert r.status_code == 200, r.text
    q = store.load("pt")
    assert q.meta.logline == "새 로그라인" and q.world.setting == "디스크에서 바뀐 세계"


def test_patch_same_episode_uses_disk(client):  # noqa: F811
    from canon import store
    from canon.schema import Episode, EpisodePlot
    _new(client)
    p = store.load("pt")
    for n in (1, 2):
        p.episodes.append(Episode(plot=EpisodePlot(number=n, act="기", title=f"{n}화", summary="", events=[], characters=[],
                                                   emotional_shift="", ending_hook="")))
    store.save("pt", p)
    got = client.get("/api/projects/pt").json()
    ep2 = {**got["episodes"][1], "plot": {**got["episodes"][1]["plot"], "title": "고친 2화"}}
    r = client.patch("/api/projects/pt", json={"edit_rev": got["edit_rev"], "fields": {"episodes": [{"$same": 1}, ep2]}})
    assert r.status_code == 200, r.text
    q = store.load("pt")
    assert [e.plot.title for e in q.episodes] == ["1화", "고친 2화"]
    r = client.patch("/api/projects/pt", json={"edit_rev": got["edit_rev"], "fields": {"episodes": [{"$same": 9}]}})
    assert r.status_code == 409
    assert client.patch("/api/projects/pt", json={"fields": {"nope": 1}}).status_code == 400


@needs_node
def test_patch_body_sends_changed_fields_only():
    expr = "(() => { const b0 = baseOf(structuredClone(data)); data.meta.title = '바뀐 제목'; data.episodes[1].plot.title = '고침'; return patchBody(data, b0); })()"
    proj = {"meta": {"title": "t"}, "world": {"setting": "w"}, "edit_rev": 3, "saved_by": "x", "snapshots": [{"episode": 0}], "relationships": [],
            "episodes": [{"plot": {"number": 1, "title": "a"}}, {"plot": {"number": 2, "title": "b"}}]}
    got = run_js(["app.js"], expr, proj)
    assert got["edit_rev"] == 3
    assert set(got["fields"]) == {"meta", "episodes"}
    assert got["fields"]["episodes"][0] == {"$same": 1} and got["fields"]["episodes"][1]["plot"]["title"] == "고침"
    unchanged = run_js(["app.js"], "patchBody(data, baseOf(structuredClone(data)))", proj)
    assert unchanged["fields"] == {}
