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

    # 로컬 서버와 단계별 백엔드
    for name in ("CANON_LOCAL_URL", "CANON_LOCAL_MODEL", "CANON_LLM_WRITE"):
        monkeypatch.delenv(name, raising=False)
    c = client.put("/api/config", json={"local_url": "http://nhn:8000/v1", "local_model": "gemma",
                                        "local_key": "lk-1", "stages": {"write": "local"}}).json()
    assert c["local_url"] == "http://nhn:8000/v1" and c["has_local_key"] and "lk-1" not in str(c)
    assert c["stages"]["write"] == {"provider": "local", "source": "file", "model": "gemma", "model_source": "default"}
    assert c["stages"]["plan"]["provider"] == "gemini"

    # 이름·지명 단계는 따로 정하지 않으면 계획 단계를 따르고, 단계별 모델을 지정할 수 있다
    assert c["stages"]["name"]["provider"] == "gemini"
    c = client.put("/api/config", json={"stage_models": {"plan": "gemini-2.5-pro"}}).json()
    assert c["stages"]["name"]["model"] == "gemini-2.5-pro"
    c = client.put("/api/config", json={"stages": {"name": "local"}, "stage_models": {"name": "qwen3"}}).json()
    assert c["stages"]["name"] == {"provider": "local", "source": "file", "model": "qwen3", "model_source": "file"}
    assert c["stage_model_settings"] == {"plan": "gemini-2.5-pro", "name": "qwen3"}
    from canon.llm import get_llm as _get
    assert _get("name").model == "qwen3" and _get("plan").model == "gemini-2.5-pro"
    assert client.put("/api/config", json={"stage_models": {"draft": "x"}}).status_code == 400
    c = client.put("/api/config", json={"stages": {"name": ""}, "stage_models": {"plan": "", "name": ""}}).json()
    assert c["stage_model_settings"] == {}
    assert client.put("/api/config", json={"stages": {"write": "claude"}}).status_code == 400
    assert client.put("/api/config", json={"stages": {"draft": "local"}}).status_code == 400
    assert client.put("/api/config", json={"stages": {"write": ""}}).json()["stage_settings"] == {}
    assert client.put("/api/config", json={"clear_key": True}).json()["key_source"] == "none"

    # 화면에서 mock 으로 바꾸면 AI 호출도 mock 으로 간다
    client.put("/api/config", json={"provider": "mock"})
    assert client.post("/api/config/test").json()["ok"]
    from canon.llm import get_llm
    from canon.mock import MockLLM
    assert isinstance(get_llm(), MockLLM)


def test_names(client):
    meta = {"title": "검", "genres": ["martial_arts"], "target_episodes": 10}
    client.post("/api/projects", json={"name": "wx", "meta": meta})
    s = client.post("/api/projects/wx/suggest").json()
    p = client.post("/api/projects/wx/suggest/apply", json=s).json()
    assert {x["id"] for x in client.get("/api/naming/styles").json()} >= {"korea_modern", "wuxia", "japan"}

    r = client.post("/api/projects/wx/names", json={"character": "hero"}).json()
    assert r["style"] == "wuxia" and len(r["candidates"]) == 8
    r = client.post("/api/projects/wx/names", json={"place_kind": "문파", "ai": True, "n": 4}).json()
    assert len(r["options"]) == 4 and all(o["reason"] for o in r["options"])
    assert {o["name"] for o in r["options"]} <= {c["name"] for c in r["candidates"]}

    # 저장 전 화면 값으로 뽑는다: 이름 스타일을 일본으로 바꾸면 일본식 이름
    p["world"]["name_style"] = "japan"
    r = client.post("/api/projects/wx/names", json={"character": "hero", "project": p}).json()
    assert r["style"] == "japan" and all(" " in c["name"] for c in r["candidates"])
    assert client.post("/api/projects/wx/names", json={"character": "nobody"}).status_code == 400

    w = client.post("/api/projects/wx/names/check", json=p).json()["warnings"]
    assert any("AI 가 자주" in x for x in w)  # mock 제안의 '서윤', '도현'


def test_relations(client):
    meta = {"title": "등대", "target_episodes": 10}
    client.post("/api/projects", json={"name": "rel", "meta": meta})
    s = client.post("/api/projects/rel/suggest").json()
    p = client.post("/api/projects/rel/suggest/apply", json=s).json()
    p["arc"] = client.post("/api/projects/rel/arc").json()["acts"]

    # 첫 반영 전: 보는 방식을 말로 고르면 방향마다 다른 시작 관계가 된다
    r = p["relationships"][0]
    assert r["a_view"] == ["경계한다"]
    by = {(t["source"], t["target"]): t for t in p["ties"]}
    assert by[("hero", "ally")]["warmth"] < 0 < by[("ally", "hero")]["warmth"]
    assert by[("ally", "hero")]["status"] < 0  # 빚졌다

    # 말을 지우면 설정 화면의 시작 호감이 시작 관계가 된다
    r.update(a_view=[], b_view=[], affinity=-5)
    p = client.put("/api/projects/rel", json=p).json()
    assert all(t["warmth"] == -1 for t in p["ties"])
    rel = client.get("/api/projects/rel/relations").json()
    assert rel["words"] and "온기 -1.00" in rel["numbers"] and rel["show_numbers"] is False

    client.post("/api/projects/rel/plots", json={})
    client.post("/api/projects/rel/episodes/1/confirm")
    client.post("/api/projects/rel/episodes/1/write")
    d = client.post("/api/projects/rel/episodes/1/state").json()
    assert d["events"]

    # 미리 보기는 저장하지 않고, 고른 사건에 따라 결과가 달라진다
    with_events = client.post("/api/projects/rel/episodes/1/preview", json=d).json()
    without = client.post("/api/projects/rel/episodes/1/preview", json=dict(d, events=[])).json()
    assert with_events["numbers"] != without["numbers"]
    assert client.get("/api/projects/rel").json()["episodes"][0]["status"] == "written"

    p = client.post("/api/projects/rel/episodes/1/apply", json=d).json()
    assert client.get("/api/projects/rel/relations").json()["numbers"] == with_events["numbers"]

    # 첫 반영 뒤에는 화면 저장이 계산된 관계를 덮어쓰지 않는다
    ties = p["ties"]
    p["relationships"][0]["affinity"] = 5
    assert client.put("/api/projects/rel", json=p).json()["ties"] == ties

    assert client.put("/api/projects/rel/view", json={"show_numbers": True}).json()["settings"]["show_numbers"] is True
    assert client.get("/api/projects/rel/relations").json()["show_numbers"] is True


def test_genres(client):
    cat = client.get("/api/genres").json()
    assert any(g["id"] == "romance_fantasy" for g in cat)
    meta = {"title": "t", "genre": "로맨스 판타지, 회귀", "adult": True}
    p = client.post("/api/projects", json={"name": "g", "meta": meta}).json()
    assert p["meta"]["genres"] == ["romance_fantasy", "regression"]
    assert p["meta"]["genre"] == "로맨스 판타지 · 회귀" and p["meta"]["adult"] is True
    p["meta"]["genres"] = ["mystery", "오컬트"]
    p = client.put("/api/projects/g", json=p).json()
    assert p["meta"]["genre"] == "미스터리 · 추리 · 오컬트"


def test_create_with_genre_list(client):
    meta = {"title": "t", "genres": ["mystery", "오컬트"], "adult": False}
    p = client.post("/api/projects", json={"name": "gl", "meta": meta}).json()
    assert p["meta"]["genres"] == ["mystery", "오컬트"] and p["meta"]["genre"] == "미스터리 · 추리 · 오컬트"


def test_logline_parts_and_tone(client):
    meta = {"title": "등대", "genres": ["mystery"], "target_episodes": 10}
    p = client.post("/api/projects", json={"name": "lg", "meta": meta}).json()
    assert p["meta"]["logline_parts"] == {"who": "", "why": "", "goal": "", "block": "", "stake": ""}
    mystery = next(g for g in client.get("/api/genres").json() if g["id"] == "mystery")
    assert len(mystery["logline"]) == 2 and mystery["logline"][0]["who"]

    p["meta"]["logline_parts"] = {"who": "사진관을 하는 서윤", "why": "", "goal": "오빠를 찾는다", "block": "", "stake": ""}
    p["meta"]["tone_dials"] = {"dark": 3, "serious": 0, "slow": 4}
    p = client.put("/api/projects/lg", json=p).json()
    assert p["meta"]["logline_parts"]["goal"] == "오빠를 찾는다" and p["meta"]["tone_dials"]["slow"] == 4

    # 작업 데이터인 칸과 다이얼은 프롬프트에 넣지 않는다
    from canon import prompts, store
    text = prompts.meta_text(store.load("lg"))
    assert "logline_parts" not in text and "tone_dials" not in text


def _wait(client, jid, timeout=10):
    import time

    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않았습니다")


def test_background_jobs(client, monkeypatch):
    client.post("/api/projects", json={"name": "bg", "meta": {"title": "t", "target_episodes": 10}})
    s = client.post("/api/projects/bg/suggest").json()
    p = client.post("/api/projects/bg/suggest/apply", json=s).json()

    assert client.post("/api/projects/bg/jobs", json={"kind": "plots"}).status_code == 400  # 구조 없음
    j = _wait(client, client.post("/api/projects/bg/jobs", json={"kind": "arc"}).json()["id"])
    assert j["status"] == "done" and len(j["result"]["acts"]) == 4
    p["arc"] = j["result"]["acts"]
    p = client.put("/api/projects/bg", json=p).json()

    # 구간마다 따로 만들고, 같은 작업은 하나만 돈다
    monkeypatch.setenv("CANON_MOCK_DELAY", "0.2")
    first = client.post("/api/projects/bg/jobs", json={"kind": "plots"}).json()
    again = client.post("/api/projects/bg/jobs", json={"kind": "plots"}).json()
    assert first["total"] == 4 and again["already"] and again["id"] == first["id"]
    # 작업 중에 화면이 옛 내용으로 저장해도 작업이 만든 화는 지켜진다
    client.put("/api/projects/bg", json=p)
    j = _wait(client, first["id"])
    assert j["status"] == "done" and j["done"] == 4
    p = client.get("/api/projects/bg").json()
    assert [e["plot"]["number"] for e in p["episodes"]] == list(range(1, 11))
    assert client.put("/api/projects/bg", json=dict(p, episodes=[])).json()["episodes"] != []  # 받아 가기 전
    assert client.put(f"/api/projects/bg?merged={first['id']}", json=p).json()["episodes"] == p["episodes"]
    monkeypatch.setenv("CANON_MOCK_DELAY", "0")

    # 확정된 화만 남은 구간은 다시 만들지 않는다
    for n in range(1, 11):
        client.post(f"/api/projects/bg/episodes/{n}/confirm")
    assert client.post("/api/projects/bg/jobs", json={"kind": "plots"}).status_code == 400

    j = _wait(client, client.post("/api/projects/bg/jobs", json={"kind": "write", "ep": 1}).json()["id"])
    assert j["status"] == "done"
    assert client.get("/api/projects/bg").json()["episodes"][0]["status"] == "written"
    j = _wait(client, client.post("/api/projects/bg/jobs", json={"kind": "state", "ep": 1}).json()["id"])
    assert j["result"]["episode"] == 1
    j = _wait(client, client.post("/api/projects/bg/jobs", json={"kind": "write", "ep": 3}).json()["id"])
    assert j["status"] == "error" and "이전 화" in j["error"]
    assert any(x["id"] == j["id"] for x in client.get("/api/jobs?project=bg").json())
