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


def _hold_first_save(monkeypatch):
    """첫 작품 저장이 검사 도중(validate_storylines)에 멈추게 한다. (들어옴, 풀기) 신호를 돌려준다."""
    import threading

    from canon import web
    entered, release = threading.Event(), threading.Event()
    real = web.pipeline.validate_storylines

    def slow(p):
        if not entered.is_set():
            entered.set()
            assert release.wait(5)
        return real(p)
    monkeypatch.setattr(web.pipeline, "validate_storylines", slow)
    return entered, release


def _put_in_thread(name, p, who, out):
    import threading

    from fastapi import HTTPException, Response

    from canon import store, web

    def run():
        store.writer.set(who)
        try:
            web.put_project(name, p, Response())
            out[who] = 200
        except HTTPException as e:
            out[who] = e.status_code
    t = threading.Thread(target=run)
    t.start()
    return t


def test_racing_saves_from_two_screens_conflict(client, monkeypatch):  # noqa: F811
    """두 화면이 같은 판을 거의 동시에 저장하면 하나만 저장하고 다른 하나는 409. 충돌 검사를 저장과 같은 잠금 안에서 한다."""
    import time

    from canon import store
    _new(client)
    a, b = store.load("pt"), store.load("pt")
    a.meta.logline, b.meta.logline = "A 로그라인", "B 로그라인"
    entered, release = _hold_first_save(monkeypatch)
    out: dict[str, int] = {}
    ta = _put_in_thread("pt", a, "a", out)
    assert entered.wait(5)
    tb = _put_in_thread("pt", b, "b", out)
    time.sleep(0.2)  # b 가 잠금 앞에서 기다리게 한다 (고치기 전에는 여기서 a 보다 먼저 저장했다)
    release.set()
    ta.join(5)
    tb.join(5)
    assert sorted(out.values()) == [200, 409], out
    assert out["a"] == 200 and store.load("pt").meta.logline == "A 로그라인"


def test_save_keeps_log_written_during_save(client, monkeypatch):  # noqa: F811
    """작품 저장이 도는 동안 작업이 잠금을 잡고 더한 설정 변경 기록은 저장 뒤에도 남는다."""
    import threading
    import time

    from canon import jobs, store
    from canon.schema import SettingRecord
    _new(client)
    a = store.load("pt")
    a.meta.logline = "A 로그라인"
    entered, release = _hold_first_save(monkeypatch)
    out: dict[str, int] = {}
    ta = _put_in_thread("pt", a, "a", out)
    assert entered.wait(5)

    def job():
        with jobs.project_lock("pt"):
            p = store.load("pt")
            p.setting_log.append(SettingRecord(character_id="c1", field="말투", before="반말", after="존댓말", episode=1))
            store.save("pt", p)
    tj = threading.Thread(target=job)
    tj.start()
    time.sleep(0.2)
    release.set()
    ta.join(5)
    tj.join(5)
    q = store.load("pt")
    assert out["a"] == 200 and q.meta.logline == "A 로그라인"
    assert [r.after for r in q.setting_log] == ["존댓말"]
