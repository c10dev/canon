"""반영 취소가 뒤 화의 반영 기록을 검토를 기다리는 상태 변경안으로 남기는지 (web._revert_kept). 실행: python -m pytest tests"""
from canon import store

from .test_restate import _two_done


def test_revert_keeps_deltas_as_pending(client):
    p = _two_done(client)
    hist = {h["episode"]: h for h in p["history"]}
    text1 = p["episodes"][0]["text"]
    # 1화는 반영 뒤 고쳤다. 변경안을 만든 본문(base)은 고치기 전 본문이라 승인 화면이 고쳤다고 알린다
    client.post("/api/projects/lh/episodes/1/edits", json={"selection": {"start": 0, "text": "바람이 불었다."}, "after": "비가 왔다."})

    p = client.post("/api/projects/lh/revert/0").json()
    assert [e["status"] for e in p["episodes"][:2]] == ["written", "written"] and p["history"] == []

    res = client.get("/api/projects/lh/pending").json()["results"]  # 본문 작성 상태 화의 변경안이라 지우지 않는다
    assert set(res) == {"state:1", "state:2"}
    for m in (1, 2):
        r = res[f"state:{m}"]
        assert r["kind"] == "state" and r["ep"] == m and r["result"] == hist[m]
    assert res["state:1"]["base"] == text1 != store.load("lh").episode(1).text
    assert res["state:2"]["base"] == "2화 본문."
    assert res["state:1"]["id"] != res["state:2"]["id"]

    # 남긴 변경안을 그대로 다시 반영할 수 있다 (AI로 다시 뽑지 않는다). 1화는 반영 뒤 고쳐 본문 지문이 달라 작가 확인(force)이 필요하다
    r = client.post("/api/projects/lh/episodes/1/apply", json=res["state:1"]["result"])
    assert r.status_code == 409 and r.json()["code"] == "stale_delta"
    p = client.post("/api/projects/lh/episodes/1/apply?force=1", json=res["state:1"]["result"]).json()
    assert p["episodes"][0]["status"] == "finalized"
    assert set(client.get("/api/projects/lh/pending").json()["results"]) == {"state:2"}  # 반영한 화의 변경안은 지운다


def test_revert_keeps_only_later_episodes(client):
    _two_done(client)
    client.post("/api/projects/lh/revert/1")
    assert set(client.get("/api/projects/lh/pending").json()["results"]) == {"state:2"}


def test_revert_keeps_fresh_restate_delta(client):
    # 반영 뒤 고친 2화에서 다시 맞추려고 뽑아 둔 변경안은 지금 본문에서 뽑은 것이라 반영 기록으로 덮지 않는다
    _two_done(client)
    client.put("/api/projects/lh/episodes/2/text", json={"text": "2화 고친 본문."})
    fresh = {"key": "state:2", "id": "job-x", "kind": "state", "ep": 2, "label": "2화 상태 변경안",
             "result": {"episode": 2, "summary": "고친 본문 요약"}, "base": "2화 고친 본문.", "at": "t"}
    store.edit_pending("lh", lambda d: d["results"].__setitem__("state:2", fresh))
    client.post("/api/projects/lh/revert/0")
    res = client.get("/api/projects/lh/pending").json()["results"]
    assert res["state:2"] == fresh and res["state:1"]["id"].startswith("revert:")
