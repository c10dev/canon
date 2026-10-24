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

    # 단계별 모델: 상태 변경안만 Flash
    for name in ("CANON_MODEL_STATE", "CANON_MODEL_PLAN"):
        monkeypatch.delenv(name, raising=False)
    c = client.put("/api/config", json={"stage_models": {"state": " gemini-3.8-flash "}}).json()
    assert c["stages"]["state"]["model"] == "gemini-3.8-flash" and c["stages"]["plan"]["model"] == "gemini-2.5-pro"
    assert c["stage_model_settings"] == {"state": "gemini-3.8-flash"}
    assert client.put("/api/config", json={"stage_models": {"draft": "x"}}).status_code == 400
    assert client.put("/api/config", json={"stage_models": {"state": ""}}).json()["stage_model_settings"] == {}
    m = client.get("/api/config/models").json()  # 키도 서버도 없어도 화면은 열린다
    assert set(m) == {"gemini", "local"} and m["local"]["error"]
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


def test_usage_page_records_web_calls(client, monkeypatch):
    """웹 요청 안에서 부른 AI 호출이 작품, 화, 단계와 함께 기록되고 /api/usage 로 모여 나온다."""
    from types import SimpleNamespace

    from canon import web
    from canon.llm import GeminiLLM
    from canon.schema import StateDelta

    meta = {"title": "등대", "genre": "미스터리", "logline": "오빠를 찾는다", "target_episodes": 4}
    client.post("/api/projects", json={"name": "lh", "meta": meta})
    p = client.get("/api/projects/lh").json()
    p["arc"] = client.post("/api/projects/lh/arc").json()["acts"]
    client.put("/api/projects/lh", json=p)
    client.post("/api/projects/lh/plots", json={})
    client.post("/api/projects/lh/episodes/1/confirm")
    client.post("/api/projects/lh/episodes/1/write")

    def fake(stage=None):
        llm = object.__new__(GeminiLLM)
        meta = SimpleNamespace(prompt_token_count=5000, candidates_token_count=800, thoughts_token_count=0,
                               cached_content_token_count=0)
        reply = StateDelta(episode=1, summary="s").model_dump_json()
        llm.client = SimpleNamespace(models=SimpleNamespace(
            generate_content=lambda **kw: SimpleNamespace(text=reply, usage_metadata=meta, candidates=[])))
        llm.model, llm.stage, llm.last_raw = "gemini-3.8-flash", stage, ""
        return llm

    monkeypatch.setattr(web, "get_llm", fake)
    r = client.post("/api/projects/lh/episodes/1/state")
    assert r.status_code == 200, r.text
    s = client.get("/api/usage?days=7").json()
    assert s["total"]["calls"] == 1
    assert s["by_episode"] == [dict(s["by_episode"][0], project="lh", episode=1)]
    assert s["by_stage"][0]["stage"] == "state" and s["recent"][0]["source"] == "web"
    assert s["total"]["cost"] == round((5000 * 0.75 + 800 * 3.75) / 1e6, 6)
    assert client.get("/api/usage?project=없음").json()["total"]["calls"] == 0

    t = client.get("/api/usage/prices").json()
    rows = [dict(r, input=0.5) if r["model"] == "gemini-3.8-flash" and not r["since"] else r for r in t["rows"]]
    t = client.put("/api/usage/prices", json={"rows": rows}).json()
    assert any(r["custom"] for r in t["rows"])
    assert client.get("/api/usage").json()["total"]["cost"] < s["total"]["cost"]
    assert not any(r["custom"] for r in client.delete("/api/usage/prices").json()["rows"])


def test_stale_screen_save_conflicts(client):
    """다른 화면(탭 · 기기)이 먼저 저장했으면 오래된 화면의 작품 전체 저장은 409. force 면 덮는다. 작업의 저장은 충돌로 세지 않는다."""
    meta = {"title": "등대", "genre": "미스터리", "logline": "x", "target_episodes": 10}
    client.post("/api/projects", json={"name": "two", "meta": meta}, headers={"X-Canon-Client": "a"})
    A = {"X-Canon-Client": "a"}
    B = {"X-Canon-Client": "b"}
    pa = client.get("/api/projects/two", headers=A).json()
    pb = client.get("/api/projects/two", headers=B).json()
    pa["meta"]["title"] = "A 제목"
    pa = client.put("/api/projects/two", json=pa, headers=A).json()
    assert pa["saved_by"] == "a" and pa["edit_rev"] > pb["edit_rev"]
    pb["meta"]["logline"] = "B 로그라인"
    r = client.put("/api/projects/two", json=pb, headers=B)
    assert r.status_code == 409
    assert client.get("/api/projects/two").json()["meta"]["title"] == "A 제목"
    # 같은 화면이 연달아 저장하는 것은 충돌이 아니다
    pa["meta"]["title"] = "A 제목 2"
    assert client.put("/api/projects/two", json=pa, headers=A).status_code == 200
    # 덮기를 고르면 저장한다
    assert client.put("/api/projects/two?force=true", json=pb, headers=B).json()["meta"]["logline"] == "B 로그라인"
    # 백그라운드 작업이 저장해도 화면 저장 번호는 그대로라 다음 저장이 막히지 않는다
    import time

    from canon import jobs
    pb = client.get("/api/projects/two", headers=B).json()
    pb["arc"] = client.post("/api/projects/two/arc", headers=B).json()["acts"]
    pb = client.put("/api/projects/two", json=pb, headers=B).json()
    client.post("/api/projects/two/jobs", json={"kind": "plots"}, headers=A)
    for _ in range(500):
        if not any(j.status == "running" for j in jobs.listing("two")):
            break
        time.sleep(0.02)
    after = client.get("/api/projects/two").json()
    assert len(after["episodes"]) == 10  # 작업이 디스크에 썼다
    assert after["edit_rev"] == pb["edit_rev"] and after["saved_by"] == "b"
    assert client.put("/api/projects/two", json=pb, headers=B).status_code == 200


def test_setup_suggestion_id_clash_and_order_rule(client):
    """제안 인물 id 가 기존 인물과 겹쳐도 이름이 다르면 새 id 로 넣고 관계도 그 인물에 잇는다. 본문 저장 · 반영은 이전 화 반영 순서를 지킨다."""
    meta = {"title": "등대", "genre": "미스터리", "logline": "x", "target_episodes": 10}
    client.post("/api/projects", json={"name": "lh", "meta": meta})
    s = client.post("/api/projects/lh/suggest").json()
    p = client.post("/api/projects/lh/suggest/apply", json=s).json()
    first = p["characters"][0]
    s2 = dict(s, characters=[dict(first, name="다른 사람")], relationships=[dict(s["relationships"][0], a=p["characters"][1]["id"], b=first["id"]), dict(s["relationships"][0], a="ghost", b=first["id"])])
    p = client.post("/api/projects/lh/suggest/apply", json=s2).json()
    new = next(c for c in p["characters"] if c["name"] == "다른 사람")
    assert new["id"] == first["id"] + "2"
    assert any({r["a"], r["b"]} == {p["characters"][1]["id"], new["id"]} for r in p["relationships"])
    assert not any("ghost" in (r["a"], r["b"]) for r in p["relationships"])

    p["arc"] = client.post("/api/projects/lh/arc").json()["acts"]
    client.put("/api/projects/lh", json=p)
    client.post("/api/projects/lh/plots", json={})
    client.post("/api/projects/lh/episodes/1/confirm")
    client.post("/api/projects/lh/episodes/2/confirm")
    assert client.put("/api/projects/lh/episodes/1/text", json={"text": "1화 본문"}).status_code == 200
    r = client.put("/api/projects/lh/episodes/2/text", json={"text": "2화 본문"})
    assert r.status_code == 400 and "상태 갱신" in r.json()["detail"]
    # 반영도 순서를 지킨다: 1화가 written 이면 2화 변경안은 반영하지 않는다 (2화를 옛 데이터로 다시 written 으로 만든 경우)
    from canon import store
    q = store.load("lh")
    q.episode(2).text, q.episode(2).status = "2화 본문", "written"
    store.save("lh", q)
    r = client.post("/api/projects/lh/episodes/2/apply", json={"episode": 2, "summary": "요약"})
    assert r.status_code == 400 and "상태 갱신" in r.json()["detail"]


def test_missing_key_is_settings_hint(client, monkeypatch):
    """키가 없으면 서버 오류(500, 예외 이름)가 아니라 400 과 code=no_key 로 설정을 안내한다."""
    meta = {"title": "등대", "genre": "미스터리", "logline": "x", "target_episodes": 10}
    client.post("/api/projects", json={"name": "nk", "meta": meta})
    monkeypatch.setenv("CANON_LLM", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = client.post("/api/projects/nk/suggest")
    assert r.status_code == 400 and r.json()["code"] == "no_key" and "RuntimeError" not in r.json()["detail"]


def test_pending_results_and_failures_survive_reload(client, monkeypatch):
    """끝난 제안 작업의 결과와 실패한 작업은 pending.json 에 남아, 새로 연 화면이 받아 간다. 반영 · 버리면 화면이 지운다."""
    import time

    from canon import jobs, mock

    def wait():
        for _ in range(500):
            if not any(j.status == "running" for j in jobs.listing("pd")):
                return
            time.sleep(0.02)

    meta = {"title": "등대", "genre": "미스터리", "logline": "x", "target_episodes": 10}
    client.post("/api/projects", json={"name": "pd", "meta": meta})
    client.post("/api/projects/pd/jobs", json={"kind": "suggest"})
    wait()
    d = client.get("/api/projects/pd/pending").json()
    assert d["results"]["suggest:"]["result"]["characters"] and d["failures"] == {}
    assert client.delete("/api/projects/pd/pending/suggest:").json()["results"] == {}

    def boom(*a, **k):
        raise RuntimeError("모델 응답이 없습니다")
    monkeypatch.setattr(mock.MockLLM, "json", boom)
    client.post("/api/projects/pd/jobs", json={"kind": "suggest"})
    wait()
    d = client.get("/api/projects/pd/pending").json()
    assert d["failures"]["suggest:"]["error"] == "모델 응답이 없습니다"
    monkeypatch.undo()
    monkeypatch.setenv("CANON_LLM", "mock")
    client.post("/api/projects/pd/jobs", json={"kind": "suggest"})
    wait()
    d = client.get("/api/projects/pd/pending").json()
    assert d["failures"] == {} and "suggest:" in d["results"]  # 같은 작업이 성공하면 지난 실패를 지운다


def test_stop_job_discards_result(client, monkeypatch):
    """멈춘 작업은 바로 cancelled 로 보이고, 늦게 온 AI 응답을 저장하지 않으며 실패로도 남기지 않는다."""
    import time

    from canon import jobs

    meta = {"title": "등대", "genre": "미스터리", "logline": "x", "target_episodes": 10}
    client.post("/api/projects", json={"name": "st", "meta": meta})
    monkeypatch.setenv("CANON_MOCK_DELAY", "0.5")
    j = client.post("/api/projects/st/jobs", json={"kind": "suggest"}).json()
    r = client.post(f"/api/jobs/{j['id']}/stop").json()
    assert r["status"] == "cancelled"
    time.sleep(0.8)
    assert jobs.get(j["id"]).status == "cancelled" and jobs.get(j["id"]).result is None
    d = client.get("/api/projects/st/pending").json()
    assert d["results"] == {} and d["failures"] == {}
    # 같은 작업을 다시 시작할 수 있다
    assert client.post("/api/projects/st/jobs", json={"kind": "suggest"}).json()["status"] == "running"


def test_project_manage_check_job_and_tie_adjust(client, tmp_path):
    """작품 복제 · 이름 바꾸기 · 지우기(휴지통), 한 화 검수 작업, 관계 수동보정, AI 연결 상태."""
    import time

    from canon import jobs

    def wait(name):
        for _ in range(500):
            if not any(j.status == "running" for j in jobs.listing(name)):
                return
            time.sleep(0.02)

    meta = {"title": "등대", "genre": "미스터리", "logline": "x", "target_episodes": 10}
    client.post("/api/projects", json={"name": "a", "meta": meta})
    p = client.post("/api/projects/a/suggest/apply", json=client.post("/api/projects/a/suggest").json()).json()
    p["arc"] = client.post("/api/projects/a/arc").json()["acts"]
    client.put("/api/projects/a", json=p)
    client.post("/api/projects/a/plots", json={})
    client.post("/api/projects/a/episodes/1/confirm")
    client.post("/api/projects/a/episodes/1/write")

    # 한 화 검수
    j = client.post("/api/projects/a/jobs", json={"kind": "check", "ep": 1}).json()
    wait("a")
    assert jobs.get(j["id"]).status == "done"
    assert client.post("/api/projects/a/jobs", json={"kind": "check", "ep": 2}).status_code == 400  # 본문 없음

    # 관계 수동보정은 사건으로 남는다
    a, b = [c["id"] for c in p["characters"][:2]]
    q = client.post("/api/projects/a/ties/adjust", json={"source": a, "target": b, "warmth": 0.9}).json()
    assert q["events"][-1]["kind"] == "수동보정" and q["events"][-1]["set_warmth"] == 0.9
    assert client.post("/api/projects/a/ties/adjust", json={"source": a, "target": b, "warmth": 3}).status_code == 400

    # 복제 · 이름 바꾸기 · 지우기
    assert client.post("/api/projects/a/duplicate", json={"name": "b"}).json() == {"name": "b"}
    assert client.get("/api/projects/b").json()["meta"]["title"] == "등대"
    assert client.post("/api/projects/a/duplicate", json={"name": "b"}).status_code == 409
    assert client.post("/api/projects/b/rename", json={"name": "c"}).json() == {"name": "c"}
    assert client.get("/api/projects/b").status_code == 404
    assert client.delete("/api/projects/c").json()["ok"]
    assert [x["name"] for x in client.get("/api/projects").json()] == ["a"]
    assert list((tmp_path / ".trash").iterdir())  # 서버 휴지통에 남는다

    h = client.get("/api/config/health").json()
    assert h["mock"] and h["has_key"]
