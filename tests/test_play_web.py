"""플레이 모드 웹 엔드포인트 시험 (mock LLM): 새 플레이 → 첫 구간 → 닿음(see)과 미리 쓰기 → 결정 → 끼어들기 → 자동 결정 →
반영 실패와 다시 시도 → 되감기 · 다르게 해 보기 → 끝내기 → 생애 기록, 작품 목록 묶기.
mock 은 짝수 구간에서만 결정 장면을 낸다 (mock_play.decides). 세계 lh 는 2화까지 반영했으니 구간은 3화부터다."""
import time

from canon import prompts, store

from .test_restate import _two_done
from .test_web import client  # noqa: F401  (pytest fixture)


def _settled(client, name, timeout=10):
    """그 플레이의 구간 작업이 모두 끝날 때까지 기다린 뒤 플레이 화면 값."""
    end = time.time() + timeout
    while time.time() < end:
        if not any(j["status"] == "running" for j in client.get(f"/api/jobs?project={name}").json()):
            return client.get(f"/api/projects/{name}/play").json()
        time.sleep(0.05)
    raise AssertionError("구간 작업이 끝나지 않았습니다")


def _job(client, jid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않았습니다")


def _random_play(client, to="pl"):
    w = client.get("/api/projects/lh/play/world").json()
    assert w["world_ep"] == 2 and w["unit"] == "day" and any(c["id"] == "hero" for c in w["characters"])
    card = client.post("/api/projects/lh/play/roll", json={"seed": 7}).json()
    assert card["birth"]["seed"] == 7 and card["archetype"] and card["wound"] and card["speech"]
    assert client.post("/api/projects/lh/play/roll", json={"seed": 7}).json() == card  # 같은 시드면 같은 출생
    sk = _job(client, client.post("/api/projects/lh/play/sketch", json={"birth": card["birth"]}).json()["id"])
    assert sk["status"] == "done" and sk["result"]["opening"]
    r = client.post("/api/projects/lh/play/start", json={"to": to, "birth": card["birth"], "sketch": sk["result"], "title": "어부의 삶"})
    assert r.status_code == 200, r.text
    return r.json(), card


def test_play_flow(client, monkeypatch):  # noqa: F811
    _two_done(client)
    raw = (store.project_dir("lh") / "project.json").read_bytes()
    started, card = _random_play(client)
    assert started["name"] == "pl" and started["job"]["ep"] == 3
    v = _settled(client, "pl")
    assert v["title"] == "어부의 삶" and v["origin"] == "random" and v["me"]["name"] == card["birth"]["name"]
    assert [t["number"] for t in v["turns"]] == [3] and v["turns"][0]["kind"] == "start" and v["turns"][0]["state"] == "applied"
    assert v["turns"][0]["beats"][0]["when"] and "luck" not in v["turns"][0]  # 운은 화면에 보내지 않는다
    assert v["seen"] == 0 and v["job"] is None  # 아직 화면이 닿지 않았다
    assert (store.project_dir("lh") / "project.json").read_bytes() == raw  # 세계 작품은 그대로

    # 작품 목록: 플레이 사본은 세계를 가리킨다
    cards = {c["name"]: c for c in client.get("/api/projects").json()}
    assert cards["lh"]["play"] is None and cards["pl"]["play"]["world"] == "lh" and cards["pl"]["play"]["title"] == "어부의 삶"

    # 아직 닿지 않았으면 흐르지 않는다. 닿으면 서버가 다음 구간을 미리 쓴다 (4구간은 결정 장면)
    assert client.post("/api/projects/pl/play/advance", json={}).status_code == 400
    assert client.post("/api/projects/pl/play/see", json={"n": 3}).json() == {"seen": 3}
    v = _settled(client, "pl")
    assert [t["number"] for t in v["turns"]] == [3, 4] and v["turns"][1]["choices"] and v["turns"][1]["scene"]
    assert v["turns"][1]["kind"] == "flow" and v["seen"] == 3
    client.post("/api/projects/pl/play/see", json={"n": 9})  # 써 둔 구간보다 뒤로는 가지 않는다
    v = _settled(client, "pl")
    assert v["seen"] == 4 and len(v["turns"]) == 2  # 결정 장면에서는 미리 쓰지 않는다
    r = client.post("/api/projects/pl/play/advance", json={})
    assert r.status_code == 400 and "결정할 차례" in r.json()["detail"]
    assert client.get("/api/projects").json() and next(c for c in client.get("/api/projects").json() if c["name"] == "pl")["play"]["waiting"]

    # 결정: 선택지 2번 → 5구간 (결정 없음)
    assert client.post("/api/projects/pl/play/advance", json={"choice": 9}).status_code == 400
    client.post("/api/projects/pl/play/advance", json={"choice": 2})
    v = _settled(client, "pl")
    t5 = v["turns"][-1]
    assert t5["number"] == 5 and t5["kind"] == "choice" and t5["action"] == "시장 사람에게 말을 건다" and not t5["choices"]

    # 끼어들기: 5구간에 닿아 6구간을 미리 써 둔 뒤 직접 적으면, 보지 않은 6구간을 버리고 5구간 끝에서 행동한다
    client.post("/api/projects/pl/play/see", json={"n": 5})
    v = _settled(client, "pl")
    assert [t["number"] for t in v["turns"]][-1] == 6 and v["seen"] == 5
    client.post("/api/projects/pl/play/advance", json={"action": "바다로 뛰어든다"})
    v = _settled(client, "pl")
    assert [t["number"] for t in v["turns"]] == [3, 4, 5, 6] and v["turns"][-1]["kind"] == "free"
    assert v["turns"][-1]["action"] == "바다로 뛰어든다" and v["turns"][-1]["choices"]

    # 자동 결정: AI 가 낸 lean (mock 은 2번)
    client.post("/api/projects/pl/play/see", json={"n": 6})
    client.put("/api/projects/pl/play/settings", json={"auto_decide": True, "focus": "사람"})
    client.post("/api/projects/pl/play/advance", json={"kind": "auto"})
    v = _settled(client, "pl")
    assert v["auto_decide"] and v["focus"] == "사람"
    assert v["turns"][-1]["kind"] == "auto" and v["turns"][-1]["action"] == "시장 사람에게 말을 건다" and v["decisions"] == 3

    # 반영 실패 → 구간은 남고 failed, 행동 없는 advance 가 반영만 다시 한다
    # 막기는 see 보다 먼저: see 가 띄운 작업이 막기 전에 반영까지 가 버릴 수 있다
    real = prompts.play_state_prompt
    monkeypatch.setattr(prompts, "play_state_prompt", lambda *a, **k: (_ for _ in ()).throw(ValueError("형식 오류")))
    client.post("/api/projects/pl/play/see", json={"n": 7})
    v = _settled(client, "pl")
    assert v["turns"][-1]["number"] == 8 and v["turns"][-1]["state"] == "failed" and "형식 오류" in v["turns"][-1]["error"]
    assert v["job"]["status"] == "error"
    monkeypatch.setattr(prompts, "play_state_prompt", real)
    client.post("/api/projects/pl/play/advance", json={})
    v = _settled(client, "pl")
    assert v["turns"][-1]["state"] == "applied" and v["job"] is None and len(v["turns"]) == 6  # 반영만 했다 (결정 장면)

    # 다르게 해 보기: 원본은 그대로, 사본은 5구간 직후
    r = client.post("/api/projects/pl/play/fork", json={"n": 5, "to": "pl-b", "title": "다른 길"})
    assert r.status_code == 200
    b = client.get("/api/projects/pl-b/play").json()
    assert [t["number"] for t in b["turns"]] == [3, 4, 5] and b["title"] == "다른 길" and b["seen"] == 5
    assert not (store.project_dir("pl-b") / "branch.json").exists()
    assert len(client.get("/api/projects/pl/play").json()["turns"]) == 6
    assert client.post("/api/projects/pl/play/fork", json={"n": 99, "to": "pl-c"}).status_code == 400 and not store.exists("pl-c")
    _settled(client, "pl-b")

    # 되감기
    v = client.post("/api/projects/pl/play/rewind", json={"n": 6}).json()
    assert [t["number"] for t in v["turns"]] == [3, 4, 5, 6] and v["seen"] == 6

    # 끝내기 → 생애 기록
    v = client.post("/api/projects/pl/play/end", json={"reason": ""}).json()
    assert v["ending"] == "플레이어가 끝냈어요"
    assert client.post("/api/projects/pl/play/advance", json={"choice": 1}).status_code == 400
    assert client.post("/api/projects/pl/play/end", json={}).status_code == 400
    life = client.get("/api/projects/pl/play/life").json()
    assert life["player"] == card["birth"]["name"] and life["archetype"] == card["archetype"] and life["seed"] == 7
    assert life["turns"] == 4 and life["decisions"] == 2 and life["free"] == 1 and life["ending"] == "플레이어가 끝냈어요"
    assert life["chapters"] and life["chapters"][0]["start_ep"] == 3 and life["last_text"]
    assert client.get("/api/projects/lh/play").status_code == 400  # 세계 작품은 플레이가 아니다


def test_play_as_world_character(client):  # noqa: F811
    _two_done(client)
    r = client.post("/api/projects/lh/play/start", json={"to": "pl", "player": "hero", "person": "third", "unit": "year"})
    assert r.status_code == 200, r.text
    v = _settled(client, "pl")
    assert v["origin"] == "character" and v["me"]["id"] == "hero" and v["unit"] == "year" and v["person"] == "third"
    assert client.post("/api/projects/lh/play/start", json={"to": "pl", "player": "hero"}).status_code == 409
    assert client.post("/api/projects/lh/play/start", json={"to": "pl2", "player": "nobody"}).status_code == 400
    assert client.get("/api/projects/pl/play/world").status_code == 400  # 플레이 사본에서는 새 플레이를 열지 않는다


def test_play_new_world(client):  # noqa: F811
    assert client.post("/api/play/worlds", json={"name": "fog", "genres": ["mystery"], "logline": " "}).status_code == 400
    j = _job(client, client.post("/api/play/worlds", json={"name": "fog", "genres": ["mystery"], "logline": "안개 낀 항구의 실종"}).json()["id"])
    assert j["status"] == "done" and j["result"] == {"name": "fog"}
    assert store.exists("fog") and store.load_play("fog") is None
    assert client.post("/api/play/worlds", json={"name": "fog", "logline": "x"}).status_code == 409
