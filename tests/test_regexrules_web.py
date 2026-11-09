"""정규식 규칙 묶음의 웹 길 (docs/context/specs/06-regex-rules.md 의 시험).

묶음 라우트 · 규칙 시험 · 켠 묶음 저장 · 고침 되돌리기 라우트, 그리고 웹 저장 길(동기 쓰기 · 쓰기 작업 · 새 판 · 부분 수정 ·
AI에게 고치기 · 받은 본문 붙여 넣기 · 재구성 다듬기 받아들이기)이 규칙을 한 번 걸고 기록을 남기는지 본다.
명령줄 · 파이프라인 길은 test_regexrules_paths.py.

실행: CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_regexrules_web.py
"""
import pytest

from canon import regexrules, store

from .test_passage import TEXT, _ep, _written
from .test_web import _wait

JOB = "/api/projects/lh/jobs"
WIND = {"in": "바람(?!결)", "out": "바람결", "action": "fix", "comment": "바람"}
STOOD = {"in": "섰다", "out": "서 있었다", "action": "fix", "comment": "섰다"}
TOWER = {"in": "등대", "action": "warn", "comment": "등대 경고"}


@pytest.fixture(autouse=True)
def _rules_home(client, monkeypatch):
    monkeypatch.delenv("CANON_RULES", raising=False)  # 묶음은 store.ROOT(시험 폴더)/.rules 에 둔다
    yield


def _make(client, *rules, name="표기") -> str:
    r = client.post("/api/rules", json={"name": name, "rules": list(rules or (WIND, STOOD, TOWER))})
    assert r.status_code == 200, r.json()
    return r.json()["id"]


def _use(client, *ids):
    r = client.put("/api/projects/lh/rule-bundles", json={"bundles": list(ids)})
    assert r.status_code == 200, r.json()
    return r.json()


# ---------- 묶음 라우트 ----------

def test_bundle_routes(client):
    r = client.post("/api/rules", json={"name": "표기", "rules": [WIND, {"in": "a", "out": "{{char}}", "action": "fix"}]})
    b = r.json()
    assert r.status_code == 200 and b["rules"][0]["in"] == "바람(?!결)" and "in_" not in b["rules"][0]
    assert b["version"] == 1 and b["used_by"] == []
    assert len(b["notices"]) == 1 and b["notices"][0].startswith("2번 규칙 · ")  # {{char}} 는 풀지 않는다는 알림 (저장은 됨)
    bid = b["id"]
    assert (store.ROOT / ".rules" / f"{bid}.json").exists()

    rows = client.get("/api/rules").json()
    assert [(x["id"], x["fix"], x["warn"], x["used_by"]) for x in rows] == [(bid, 2, 0, 0)]
    assert client.get(f"/api/rules/{bid}").json()["name"] == "표기"

    r = client.put(f"/api/rules/{bid}", json={"name": "표기 2", "rules": [b["rules"][0], TOWER]})  # 규칙 id 를 보내야 같은 규칙으로 본다
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["notices"] == []
    vs = client.get(f"/api/rules/{bid}/versions").json()
    assert [v["number"] for v in vs] == [2, 1] and vs[0]["added"] == ["등대 경고"]
    r = client.post(f"/api/rules/{bid}/versions/1/restore")
    assert r.status_code == 200 and r.json()["version"] == 3 and len(r.json()["rules"]) == 2
    assert client.post(f"/api/rules/{bid}/versions/9/restore").status_code == 400

    assert client.delete(f"/api/rules/{bid}").json() == {"ok": True}
    assert client.get(f"/api/rules/{bid}").status_code == 404
    assert client.put(f"/api/rules/{bid}", json={"name": "x"}).status_code == 404
    assert client.get("/api/rules/not-an-id").status_code == 404


def test_bundle_validation_refuses(client):
    bad = [{"in": "(a+)+", "out": "b", "action": "fix", "comment": "겹친 반복"},
           {"in": "x", "flag": "gy", "action": "fix"},
           {"in": "\\p{L}", "action": "warn"}]
    r = client.post("/api/rules", json={"name": "나쁨", "rules": bad})
    assert r.status_code == 400
    lines = r.json()["detail"].split("\n")
    assert lines[0].startswith("겹친 반복 · 이 정규식은 저장할 수 없어요: ")
    assert any(x.startswith("2번 규칙 · ") for x in lines) and any("[가-힣]" in x for x in lines)
    assert client.get("/api/rules").json() == []  # 아무것도 저장하지 않았다
    bid = _make(client)
    assert client.put(f"/api/rules/{bid}", json={"name": "표기", "rules": bad[:1]}).status_code == 400
    assert len(client.get(f"/api/rules/{bid}").json()["rules"]) == 3
    assert client.post("/api/rules", json={"name": "  ", "rules": []}).status_code == 400  # 이름 없음


def test_rule_test_endpoint(client):
    r = client.post("/api/rules/test", json={"rules": [WIND, TOWER], "text": "바람이 분다. 등대가 보인다."}).json()
    assert r["text"] == "바람결이 분다. 등대가 보인다." and r["skipped"] == ""
    assert [(c["before"], c["after"], c["start"]) for c in r["changes"]] == [("바람", "바람결", 0)]
    assert [h["current_quote"] for h in r["hits"]] == ["등대가 보인다."]
    assert client.post("/api/rules/test", json={"rules": [{"in": "(a*)*", "action": "warn"}], "text": "x"}).status_code == 400
    assert client.post("/api/rules/test", json={"text": "x"}).status_code == 400  # 규칙도 묶음도 없음
    assert client.post("/api/rules/test", json={"rules": [WIND]}).status_code == 400  # 글도 화도 없음

    _written(client)  # 저장된 묶음 + 작품의 화
    bid = _make(client)
    r = client.post("/api/rules/test", json={"bundle": bid, "project": "lh", "episode": 1}).json()
    assert r["text"] == TEXT.replace("바람", "바람결").replace("섰다", "서 있었다") and len(r["changes"]) == 2
    assert _ep(client.get("/api/projects/lh").json())["text"] == TEXT  # 저장하지 않는다
    assert client.post("/api/rules/test", json={"bundle": "0" * 12, "text": "x"}).status_code == 404


# ---------- 켠 묶음 저장 ----------

def test_rule_bundles_put(client):
    _written(client)
    a, b = _make(client, name="가"), _make(client, WIND, name="나")
    assert client.put("/api/projects/lh/rule-bundles", json={"bundles": [a, "f" * 12]}).status_code == 400
    assert client.put("/api/projects/lh/rule-bundles", json={"bundles": ["../x"]}).status_code == 400
    p = _use(client, b, a, b)
    assert p["settings"]["rule_bundles"] == [b, a]  # 차례를 지키고 겹친 id 는 한 번만
    assert store.load("lh").settings.rule_bundles == [b, a]
    assert client.get("/api/rules").json()[0]["used_by"] == 1
    assert set(client.get(f"/api/rules/{a}").json()["used_by"]) == {"lh"}
    client.delete(f"/api/rules/{a}")
    p = _use(client, a, b)  # 이미 켜 둔 id 는 지워진 묶음이어도 받는다 (화면이 '찾을 수 없는 묶음이에요' 로 보임)
    assert p["settings"]["rule_bundles"] == [a, b] and regexrules.missing(store.load("lh")) == [a]
    assert _use(client)["settings"]["rule_bundles"] == []
    assert client.put("/api/projects/nope/rule-bundles", json={"bundles": []}).status_code == 404


# ---------- 웹 저장 길 ----------

def test_sync_write_records_and_undo_routes(client):
    _written(client)
    _use(client, _make(client))
    client.put("/api/projects/lh/episodes/1/text", json={"text": ""})  # 빈 화로 되돌려 다시 쓴다
    p = client.post("/api/projects/lh/episodes/1/write").json()
    e = _ep(p)
    assert e["text"].startswith("바람결이 불었다.") and "서 있었다" in e["text"]
    assert [(r["id"], r["kind"], len(r["changes"])) for r in e["rule_runs"]] == [("r1", "write", 2)]
    assert e["edits"][-1]["source"] == "typed"  # 규칙이 바꾼 곳은 수정 기록(edits)에 넣지 않는다

    # 바뀐 곳 하나 되돌리기
    p = client.post("/api/projects/lh/episodes/1/rule-runs/r1/changes/1/undo").json()
    e = _ep(p)
    assert "서 있었다" not in e["text"] and "섰다" in e["text"] and e["text"].startswith("바람결")
    assert e["rule_runs"][0]["changes"][1]["undone"]
    assert client.post("/api/projects/lh/episodes/1/rule-runs/r1/changes/1/undo").status_code == 400  # 이미 되돌림
    assert client.post("/api/projects/lh/episodes/1/rule-runs/r1/changes/9/undo").status_code == 400
    assert client.post("/api/projects/lh/episodes/1/rule-runs/r9/undo").status_code == 400

    # 보낸 그대로 보기: 본문이 바뀐 까닭에 규칙 되돌리기가 든다
    note = client.get("/api/projects/lh/episodes/1/prompt?source=sent").json()["note"]
    assert "규칙 되돌리기" in note

    # 한 번 전체 되돌리기: 남은 곳만 되돌린다
    out = client.post("/api/projects/lh/episodes/1/rule-runs/r1/undo").json()
    assert (out["undone"], out["left"]) == (1, 0)
    assert _ep(out["project"])["text"].startswith("바람이 불었다.")
    assert client.post("/api/projects/lh/episodes/1/rule-runs/r1/undo").status_code == 400  # 이미 모두 되돌림


def test_write_job_exposes_run(client):
    _written(client)
    client.put("/api/projects/lh/episodes/1/text", json={"text": ""})
    j = _wait(client, client.post(JOB, json={"kind": "write", "ep": 1}).json()["id"])
    assert j["status"] == "done" and j["result"] is None  # 묶음을 켜지 않으면 예전 그대로
    assert store.load("lh").episode(1).rule_runs == []

    _use(client, _make(client))
    client.put("/api/projects/lh/episodes/1/text", json={"text": ""})
    j = _wait(client, client.post(JOB, json={"kind": "write", "ep": 1}).json()["id"])
    assert j["status"] == "done", j.get("error")
    run = j["result"]["rule_run"]
    assert run["id"] == "r1" and run["kind"] == "write" and len(run["changes"]) == 2
    ep = store.load("lh").episode(1)
    assert [r.id for r in ep.rule_runs] == ["r1"] and ep.text.startswith("바람결")
    assert ep.text.count("바람결") == 1  # 한 번만 건다


def test_write_job_then_check_keeps_run(client):
    _written(client)
    _use(client, _make(client))
    p = store.load("lh")
    p.settings.check_after_write = True
    store.save("lh", p)
    client.put("/api/projects/lh/episodes/1/text", json={"text": ""})
    j = _wait(client, client.post(JOB, json={"kind": "write", "ep": 1}).json()["id"])
    assert j["status"] == "done", j.get("error")
    assert "check" in j["result"] and j["result"]["rule_run"]["kind"] == "write"
    ep = store.load("lh").episode(1)
    assert any(f.origin == "regex" for f in ep.findings)  # 경고 규칙(등대)이 검수에 합쳐진다


def test_rewrite_candidate_records(client):
    _written(client)
    _use(client, _make(client))
    j = _wait(client, client.post(JOB, json={"kind": "write", "ep": 1, "rewrite": {"feedback": "더 조용하게"}}).json()["id"])
    assert j["status"] == "done", j.get("error")
    assert j["result"]["candidate"] is True and j["result"]["rule_run"]["kind"] == "rewrite"
    ep = store.load("lh").episode(1)
    assert ep.text == TEXT and [r.kind for r in ep.candidate.rule_runs] == ["rewrite"]
    assert ep.candidate.text.count("바람결") >= 1


def test_put_text_import_and_typed(client):
    _written(client)
    _use(client, _make(client))
    p = client.put("/api/projects/lh/episodes/1/text", json={"text": TEXT + "\n\n바람이 멎었다."}).json()
    e = _ep(p)
    assert e["text"].endswith("바람이 멎었다.") and e["rule_runs"] == []  # 작가가 친 글에는 걸지 않는다

    p = client.put("/api/projects/lh/episodes/1/text", json={"text": "  바람이 분다. 서윤은 섰다.  ", "source": "import"}).json()
    e = _ep(p)
    assert e["text"] == "바람결이 분다. 서윤은 서 있었다." and e["written_by"] == "import"
    assert [(r["kind"], len(r["changes"])) for r in e["rule_runs"]] == [("import", 2)]
    assert e["versions"][-1]["text"].endswith("바람이 멎었다.")  # 지금 본문은 '이전 판'에 남는다 (명령줄 import 와 같다)

    p = client.put("/api/projects/lh/episodes/1/text", json={"text": ""}).json()
    e = _ep(p)
    assert e["text"] == "" and e["rule_runs"] == [] and e["meta_cut"] == [] and e["written_by"] == ""
    assert client.put("/api/projects/lh/episodes/1/text", json={"text": "x", "source": "paste"}).status_code == 422


def test_put_text_import_without_bundles(client):
    _written(client)
    p = client.put("/api/projects/lh/episodes/1/text", json={"text": "바람이 분다.", "source": "import"}).json()
    e = _ep(p)
    assert e["text"] == "바람이 분다." and e["rule_runs"] == [] and e["written_by"] == "import"
    assert client.put("/api/projects/lh/episodes/2/text", json={"text": "x", "source": "import"}).status_code == 400  # 플롯 초안


def test_passage_and_fix_now_record(client):
    _written(client)
    _use(client, _make(client, STOOD))
    quote = "서윤은 등대 앞에 섰다."
    sel = {"start": TEXT.index(quote), "text": quote}
    p = client.post("/api/projects/lh/chat/text:1", json={"message": "더 짧게", "selection": sel}).json()
    ai = next(c for c in p["chats"] if c["topic"] == "text:1")["messages"][-1]
    first = ai["passage"]["candidates"][0]
    assert "서 있었다" in first["text"] and [c["after"] for c in first["ruled"]] == ["서 있었다"]
    assert _ep(p)["text"] == TEXT  # 고르기 전에는 그대로
    p = client.post("/api/projects/lh/chat/text:1/1/apply", json={"candidate": 0}).json()
    e = _ep(p)
    run = e["rule_runs"][-1]
    assert run["kind"] == "passage" and e["text"][run["changes"][0]["start"]:].startswith("서 있었다")

    quote2 = "도현은 대답하지 않았다."
    msg = f"상태 정리 경고: «{quote2}» 섰다"
    out = client.post("/api/projects/lh/episodes/1/fix-now",
                      json={"message": msg, "selection": {"start": TEXT.index(quote2), "text": quote2}}).json()
    e = _ep(out["project"])
    assert out["edit"] and [r["kind"] for r in e["rule_runs"]] == ["passage", "passage"]
    assert "서 있었다" in e["text"].split("\n")[-1]


def test_rework_accept_with_ruled(client):
    from .test_rebuild import _rebuilt

    p, *_ = _rebuilt()
    store.save("lh", p)
    bid = _make(client, {"in": "본문", "out": "원고", "action": "fix", "comment": "원고"})
    _use(client, bid)
    j = _wait(client, client.post(JOB, json={"kind": "rework", "ep": 3}).json()["id"])
    assert j["status"] == "done", j.get("error")
    rw = j["result"]
    assert rw["ruled"] and "원고" in rw["text"]
    p = client.post("/api/projects/lh/episodes/3/rework", json={"text": rw["text"], "proposed": rw["text"], "ruled": rw["ruled"]}).json()
    ep3 = next(e for e in p["episodes"] if e["plot"]["number"] == 3)
    run = ep3["rule_runs"][-1]
    assert run["kind"] == "rework" and len(run["changes"]) == len(rw["ruled"])
    assert all(ep3["text"][c["start"]:c["start"] + len(c["after"])] == c["after"] for c in run["changes"])

    # 옛 화면처럼 ruled 없이 보내면 기록은 남기지 않는다
    p, *_ = _rebuilt()
    store.save("lh", p)
    _use(client, bid)
    j = _wait(client, client.post(JOB, json={"kind": "rework", "ep": 3}).json()["id"])
    p = client.post("/api/projects/lh/episodes/3/rework", json={"text": j["result"]["text"], "proposed": j["result"]["text"]}).json()
    assert next(e for e in p["episodes"] if e["plot"]["number"] == 3)["rule_runs"] == []


def test_rule_runs_not_job_field():
    from canon import web
    assert "rule_runs" not in web.JOB_EP_FIELDS


TWICE = {"in": "바람", "out": "바람바람", "action": "fix", "comment": "두 번"}  # 다시 걸면 바뀌므로 두 번 걸기를 잡는다


def test_write_job_applies_once_with_non_idempotent_rule(client):
    _written(client)
    _use(client, _make(client, TWICE))
    client.put("/api/projects/lh/episodes/1/text", json={"text": ""})
    j = _wait(client, client.post(JOB, json={"kind": "write", "ep": 1}).json()["id"])
    assert j["status"] == "done", j.get("error")
    text = store.load("lh").episode(1).text
    assert text.startswith("바람바람이 불었다.") and not text.startswith("바람바람바람")
    p = client.put("/api/projects/lh/episodes/1/text", json={"text": "바람이 분다.", "source": "import"}).json()
    assert _ep(p)["text"] == "바람바람이 분다."


def test_put_text_import_rules_outside_lock_keeps_other_saves(client, monkeypatch):
    from canon import jobs, pipeline
    _written(client)
    _use(client, _make(client))
    real = pipeline.apply_rules
    seen = []

    def slow(p, text, kind, runs):  # 규칙을 거는 사이 다른 저장이 끼어든다
        seen.append(jobs._project_locks["lh"].locked())
        q = store.load("lh")
        q.meta.title = "그사이 바꾼 제목"
        store.save("lh", q)
        return real(p, text, kind, runs)
    monkeypatch.setattr(pipeline, "apply_rules", slow)
    p = client.put("/api/projects/lh/episodes/1/text", json={"text": "바람이 분다.", "source": "import", "base": TEXT}).json()
    assert seen == [False]  # 작품을 잠그지 않은 채 건다
    assert p["meta"]["title"] == "그사이 바꾼 제목" and _ep(p)["text"] == "바람결이 분다."
    assert store.load("lh").meta.title == "그사이 바꾼 제목"

    def edit(p, text, kind, runs):  # 그사이 다른 탭이 본문을 저장했다
        q = store.load("lh")
        q.episode(1).text = "다른 탭 본문"
        store.save("lh", q)
        return real(p, text, kind, runs)
    monkeypatch.setattr(pipeline, "apply_rules", edit)
    base = store.load("lh").episode(1).text
    r = client.put("/api/projects/lh/episodes/1/text", json={"text": "바람이 멎었다.", "source": "import", "base": base})
    assert r.status_code == 409 and r.json()["code"] == "stale_text"
    assert store.load("lh").episode(1).text == "다른 탭 본문"


def test_check_import_rules_outside_lock(client, monkeypatch):
    from canon import jobs
    _written(client)
    _use(client, _make(client))
    real = regexrules.hits
    seen = []
    monkeypatch.setattr(regexrules, "hits", lambda *a, **k: seen.append(jobs._project_locks["lh"].locked()) or real(*a, **k))
    p = client.post("/api/projects/lh/episodes/1/check/import", json={"raw": '{"issues": []}'}).json()
    assert seen == [False]  # 경고 규칙은 잠그기 전에 한 번만 건다
    assert any(f["origin"] == "regex" for f in _ep(p)["findings"])


def test_core_doc_routes_line_matches():
    import re
    from pathlib import Path
    from canon import web
    line = next(x for x in (Path(__file__).parents[1] / "docs/modules/core.md").read_text(encoding="utf-8").splitlines()
                if x.startswith("- 기능별 라우트"))
    names = re.search(r"`ROUTES`: ([^)]*)\)", line).group(1).split(" · ")
    count = "하나 둘 셋 넷 다섯 여섯 일곱 여덟 아홉 열 열하나 열둘".split()[len(web.ROUTES) - 1]
    assert len(names) == len(web.ROUTES) and f"라우트 {count} 묶음" in line
