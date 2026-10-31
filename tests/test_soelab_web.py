"""쇠맛 실험실 웹 API (/api/soelab/..., canon/web.py · soelab.py 화면 값). AI 를 부르지 않는다.
명세 8장 시험 7(가린 조각 정보가 응답에 없음) · 8(정답은 이번 10개가 끝난 뒤에만)과 호출 수 0.
시험 글은 test_soelab.py 와 같이 tests/fixtures/soelab/ 의 직접 지은 글에서 문장을 섞어 만든다."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from canon import soelab, store, web
from canon.mock import MockLLM

from .test_soelab import serial, story

AI_SENT = "그것은 단순한 바람이 아니었다. 어둡고, 차갑고, 조용했다. 불안감이 밀려왔다 — 그는 숨을 삼켰다."


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_USAGE", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(soelab.report, "__defaults__", (soelab.SEED, 200, True))  # 시험은 부트스트랩을 짧게
    soelab._cache.clear()
    return TestClient(web.app)


def _collect(c, eps: int = 12, sets: int = 1) -> dict:
    """사람 글 · AI 글을 eps 화씩 sets 벌 (원천 상한 20 이 있어 벌마다 따로 붙여 넣는다)."""
    srcs = []
    for k in range(sets):
        ai = "\n\n".join(f"{n}화\n\n{AI_SENT}\n\n{story(3000 + 100 * k + n)}\n\n{AI_SENT}" for n in range(1, eps + 1))
        srcs += [{"kind": "paste", "text": serial(1, eps, 2000 + 100 * k), "title": f"사람 글 {k}", "origin": "human"},
                 {"kind": "paste", "text": ai, "title": f"AI 글 {k}", "origin": "ai", "model": "gemini"}]
    body = {"sources": srcs}
    pre = c.post("/api/soelab/collect/preview", json=body).json()
    n = eps * sets
    assert pre["new"] == 2 * n and pre["queue"] == 2 * n and pre["groups"] == {"human": n, "ai": n}
    assert soelab.load_pieces() == []  # 미리보기는 저장하지 않는다
    r = c.post("/api/soelab/collect", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _judge(c, n: int, now=None) -> list[str]:
    """대기열 차례대로 n 개를 판정한다 (출처 그대로 판정, 첫 조각에는 문장 표시 하나)."""
    by_id = {p.id: p for p in soelab.load_pieces()}
    done = []
    for _ in range(n):
        j = c.get("/api/soelab/judge").json()
        if j["piece"] is None:  # 끝난 '이번 10개' 정답 카드를 넘긴다
            c.put("/api/soelab/state", json={"seen": j["screen"]["ended"]})
            j = c.get("/api/soelab/judge").json()
        pid = j["piece"]["id"]
        spans = [{"start": 0, "end": 10, "kind": "other", "note": "첫 줄"}]
        if now:
            soelab.save_judge(pid, by_id[pid].origin, spans, seconds=30, now=now)
        else:
            r = c.post("/api/soelab/judge", json={"piece": pid, "verdict": by_id[pid].origin, "spans": spans, "seconds": 30})
            assert r.status_code == 200, r.text
        done.append(pid)
    return done


def _leaks(data, pid: str) -> bool:
    return pid in json.dumps(data, ensure_ascii=False)


# ---------- 7. 가린 조각의 출처 · 원천 · 지표 값은 어느 응답에도 없다 ----------

def test_masked_pieces_not_in_responses(c):
    _collect(c)
    opened = _judge(c, 3)  # 끝나지 않은 '이번 10개'의 조각도 가린다
    q = soelab.load_queue()
    waiting = [x for x in q["order"] if x not in opened][:3]
    masked = soelab.masked_ids()
    assert set(opened) <= masked and set(waiting) <= masked

    rows = {r["id"]: r for r in c.get("/api/soelab/pieces").json()["rows"]}
    for pid in opened + waiting:
        assert set(rows[pid]) == {"n", "id", "chars", "labels", "known", "paste", "hidden"}
        assert rows[pid]["hidden"] == "judge"
        assert set(c.get(f"/api/soelab/pieces/{pid}").json()) == {"id", "text", "chars", "hidden"}

    bodies = [c.get("/api/soelab").json(), c.get("/api/soelab/patterns").json(), c.get("/api/soelab/check").json(),
              c.get("/api/soelab/redo").json(), c.get("/api/soelab/reports").json()]
    bodies += [c.get(f"/api/soelab/metrics/{m}").json() for m in soelab.METRIC_IDS]
    for body in bodies:
        for pid in opened + waiting:
            assert not _leaks(body, pid)
    # 판정 화면은 지금 조각의 글과 id 만 준다
    j = c.get("/api/soelab/judge").json()
    assert set(j["piece"]) == {"id", "text", "chars"}
    # 다시 채점해도 저장한 보고서의 조각별 줄에 가린 조각이 없다
    c.post("/api/soelab/report")
    rep = soelab.latest_report()
    assert not {r["id"] for r in rep["pieces"]} & masked
    assert rep["counts"]["judged"] == 0  # 끝나지 않은 이번 10개의 판정은 작가 판정 기준에도 넣지 않는다


# ---------- 8. 정답은 이번 10개가 끝난 뒤에만 ----------

def test_answers_only_after_batch(c):
    _collect(c)
    first = _judge(c, 9)
    r = c.get("/api/soelab/batch/1")
    assert r.status_code == 400 and "마치면" in r.json()["detail"]
    assert c.get("/api/soelab").json()["ended"] == 0
    first += _judge(c, 1)
    sc = c.get("/api/soelab").json()
    assert sc["ended"] == 1 and sc["batches"] == 1
    assert c.get("/api/soelab/judge").json()["piece"] is None  # 정답 카드를 넘기기 전에는 다음 조각을 주지 않는다
    rev = c.get("/api/soelab/batch/1").json()
    q = soelab.load_queue()
    redo, spare = set(q["redo"]), set(q["spare"])
    assert [r["id"] for r in rev["rows"]] == first
    for row in rev["rows"]:
        if row["id"] in redo | spare:  # 다시 읽기 예정은 재판정 뒤에, 예비는 보여 줄 때가 되어야 보인다
            assert row["hidden"] and "origin" not in row and "text" not in row
            assert row["why"] == ("spare" if row["id"] in spare else "redo")
        else:
            assert row["origin"] in ("human", "ai") and row["match"] is True
    assert rev["same"] == rev["comparable"] == sum(not r["hidden"] for r in rev["rows"])
    assert soelab.latest_report()["counts"]["judged"] == 10  # 10개를 마치면 다시 채점한다
    hid = next(r["id"] for r in rev["rows"] if r["hidden"] and r["why"] == "redo")
    assert hid in soelab.masked_ids()
    # 7일 전 다시 읽기는 막는다
    r = c.post("/api/soelab/redo", json={"piece": hid, "verdict": "ai"})
    assert r.status_code == 400 and "부터 다시 읽을 수 있어요" in r.json()["detail"]
    # 7일 뒤 재판정하면 그 조각의 정답도 보인다
    later = datetime.now().astimezone() + timedelta(days=8)
    soelab.save_judge(hid, "ai", redo_too=True, now=later)
    row = next(r for r in c.get("/api/soelab/batch/1").json()["rows"] if r["id"] == hid)
    assert not row["hidden"] and "origin" in row


def test_redo_view_dates(c):
    _collect(c)
    _judge(c, 10)
    v = c.get("/api/soelab/redo").json()
    rs = v["screen"]["redo_state"]
    assert v["piece"] is None and rs["due"] == 0 and rs["waiting"] >= 1
    assert rs["opens"] == (datetime.now().astimezone().date() + timedelta(days=7)).isoformat()


def test_round_goal_and_stop(c):
    _collect(c, eps=13, sets=2)
    assert c.put("/api/soelab/state", json={"goal": 50}).status_code == 400
    _judge(c, 40)
    c.put("/api/soelab/state", json={"seen": 4})
    j = c.get("/api/soelab/judge").json()
    assert j["piece"] is None and j["screen"]["judged"] == 40 and j["screen"]["goal"] == 40  # 1차 끝: 계속 읽기를 고를 때까지
    c.put("/api/soelab/state", json={"goal": 60})
    assert c.get("/api/soelab/judge").json()["piece"] is not None
    c.put("/api/soelab/state", json={"stopped": True})
    assert c.get("/api/soelab/judge").json()["piece"] is None


# ---------- 패턴 확인 · 혼동표 ----------

def test_check_and_patterns(c):
    _collect(c)
    _judge(c, 10)
    c.put("/api/soelab/state", json={"seen": 1})
    v = c.get("/api/soelab/check").json()
    card = v["card"]
    assert card and card["piece"] not in soelab.masked_ids() and card["sentence"] and card["marks"]
    for _ in range(6):
        v = c.post("/api/soelab/check", json={"hit": v["card"]["hit"], "ok": "yes"}).json()
        if not v["card"]:
            break
    assert v["done"] >= 1
    # 같은 문장을 다시 매기면 앞 것을 바꾼다
    c.post("/api/soelab/check", json={"hit": card["hit"], "ok": "no"})
    hits = [lb for lb in soelab.load_labels() if lb.kind == "hit" and lb.hit == card["hit"]]
    assert len(hits) == 1 and hits[0].hit_ok == "no" and not hits[0].blind
    assert c.post("/api/soelab/check", json={"hit": "nope-0-0", "ok": "yes"}).status_code == 400
    pv = c.get("/api/soelab/patterns").json()
    row = next(r for r in pv["rows"] if r["kind"] == card["kind"])
    assert row["checked"] >= 1 and any(s["kind"] == "fp" for s in row["sentences"])
    assert pv["others"] and pv["others"][0]["note"] == "첫 줄"  # 기타 표시 (가리지 않은 조각)
    # 패턴 확인은 가려 읽기 판정(첫 판정 수)에 들어가지 않는다
    assert c.get("/api/soelab").json()["judged"] == 10


# ---------- 말뭉치 고치기 ----------

def test_paste_remove_and_origin_rules(c):
    _collect(c, eps=6)
    q = soelab.load_queue()
    pid = q["order"][0]
    r = c.put(f"/api/soelab/pieces/{pid}/origin", json={"origin": "ai", "model": "claude"})
    assert r.status_code == 400 and "판정 뒤" in r.json()["detail"]
    assert c.delete(f"/api/soelab/pieces/{pid}").status_code == 200
    assert pid not in soelab.load_queue()["order"] and pid not in {p.id for p in soelab.load_pieces()}
    judged = _judge(c, 1)[0]
    assert c.delete(f"/api/soelab/pieces/{judged}").status_code == 400


def test_judge_spans_checked(c):
    _collect(c, eps=6)
    pid = c.get("/api/soelab/judge").json()["piece"]["id"]
    bad = c.post("/api/soelab/judge", json={"piece": pid, "verdict": "ai", "spans": [{"start": 0, "end": 99999, "kind": "other"}]})
    assert bad.status_code == 400
    bad = c.post("/api/soelab/judge", json={"piece": pid, "verdict": "ai", "spans": [{"start": 0, "end": 4, "kind": "새갈래"}]})
    assert bad.status_code == 400
    ok = c.post("/api/soelab/judge", json={"piece": pid, "verdict": "ai", "seconds": 99999,
                                           "spans": [{"start": 0, "end": 4, "kind": "cliche", "quote": "가짜"}]})
    assert ok.status_code == 200
    lb = soelab.load_labels()[0]
    text = next(p.text for p in soelab.load_pieces() if p.id == pid)
    assert lb.spans[0].quote == text[:4] and lb.seconds == soelab.SECONDS_MAX


# ---------- AI 호출 수 0 ----------

def test_web_no_llm_calls(c, monkeypatch):
    calls = []
    monkeypatch.setattr(MockLLM, "json", lambda self, *a, **k: calls.append("json"))
    monkeypatch.setattr(MockLLM, "text", lambda self, *a, **k: calls.append("text"))
    from canon import llm
    real = llm.get_llm
    monkeypatch.setattr(llm, "get_llm", lambda *a, **k: calls.append("get_llm") or real(*a, **k))
    _collect(c)
    _judge(c, 10)
    c.get("/api/soelab/batch/1")
    c.post("/api/soelab/report")
    for m in soelab.METRIC_IDS:
        c.get(f"/api/soelab/metrics/{m}")
    c.get("/api/soelab/patterns")
    v = c.get("/api/soelab/check").json()
    if v["card"]:
        c.post("/api/soelab/check", json={"hit": v["card"]["hit"], "ok": "yes"})
    c.get("/api/soelab/sources")
    c.get("/api/soelab/reports")
    c.post("/api/soelab/spares/open")  # 보류가 아니라 막히지만 AI 를 부르지 않는다
    assert calls == []


def test_redo_slots_not_fixed(c):
    """다시 읽기 자리가 늘 이번 10개의 1 · 4 · 7번째면 정답 카드에서 차례가 드러난다. 세 자리 안 자리는 섞는다."""
    _collect(c, eps=13, sets=2)
    q = soelab.load_queue()
    redo = set(q["redo"])
    slots = {i % 3 for i, x in enumerate(q["order"][:30]) if x in redo}
    assert len(slots) > 1
    assert sum(x in redo for x in q["order"][:30]) >= 8  # 셋에 하나꼴은 그대로


# ---------- 예비: 판정 일관성이 보류일 때만 다시 읽기로 여는 숨긴 조각 ----------

HELD = {"pairs": 30, "kappa": 0.2, "ci95": [0.05, 0.4], "preview": False, "hold": True, "hold_below": 0.3}
SETTLED = {**HELD, "kappa": 0.7, "ci95": [0.5, 0.85], "hold": False}


def _judge_fast(n: int, now=None) -> list[str]:
    """대기열 차례로 n 개를 서버 함수로 판정한다 (웹 왕복 없이)."""
    by_id = {p.id: p for p in soelab.load_pieces()}
    done = []
    for pid in soelab.load_queue()["order"][:n]:
        soelab.save_judge(pid, by_id[pid].origin, now=now)
        done.append(pid)
    soelab.set_state(seen=n // soelab.BATCH)
    return done


def test_spare_ratio_and_hidden(c):
    _collect(c, eps=13, sets=2)
    q = soelab.load_queue()
    n = len(q["order"])
    assert abs(len(q["spare"]) - round(n / 6)) <= 1 and not set(q["spare"]) & set(q["redo"])
    assert sum(x in set(q["spare"]) for x in q["order"][:30]) >= 4  # 이번 10개마다 하나 남짓
    slots = {i % 6 for i, x in enumerate(q["order"][:48]) if x in set(q["spare"])}
    assert len(slots) > 1  # 자리가 짐작되지 않게 섞는다
    judged = _judge_fast(30)
    spare = [x for x in judged if x in set(q["spare"])]
    assert spare and set(spare) <= soelab.masked_ids()
    rows = {r["id"]: r for r in c.get("/api/soelab/pieces").json()["rows"]}
    assert all(rows[x]["hidden"] == "spare" for x in spare)
    bodies = [c.get("/api/soelab").json(), c.get("/api/soelab/patterns").json(), c.get("/api/soelab/check").json(),
              c.get("/api/soelab/redo").json()] + [c.get(f"/api/soelab/batch/{k}").json() for k in (1, 2, 3)]
    bodies += [c.get(f"/api/soelab/metrics/{m}").json() for m in soelab.METRIC_IDS]
    for pid in spare:
        assert set(c.get(f"/api/soelab/pieces/{pid}").json()) == {"id", "text", "chars", "hidden"}
        for body in bodies:
            text = json.dumps(body, ensure_ascii=False)
            assert pid not in text or all(
                r["id"] != pid or (r["hidden"] and r["why"] == "spare" and "origin" not in r) for r in body.get("rows", []))
    # 보고서 계산에는 예비 판정도 들어간다 (정답만 작가에게 숨긴다)
    c.post("/api/soelab/report")
    assert soelab.latest_report()["counts"]["judged"] == 30


def test_spare_opens_only_when_held(c, monkeypatch):
    _collect(c, eps=13, sets=2)
    q = soelab.load_queue()
    judged = _judge_fast(30)
    spare = [x for x in judged if x in set(q["spare"])]
    r = c.post("/api/soelab/spares/open")
    assert r.status_code == 400 and "보류일 때만" in r.json()["detail"]
    monkeypatch.setattr(soelab, "consistency", lambda *a, **k: dict(HELD))
    c.post("/api/soelab/report")
    sc = c.get("/api/soelab").json()
    assert sc["held"] and sc["spare"]["ready"] == len(spare)
    r = c.post("/api/soelab/spares/open").json()
    assert r["opened"] == len(spare) <= soelab.SPARE_OPEN
    q2 = soelab.load_queue()
    assert set(spare) <= set(q2["redo"]) and set(spare) == set(q2["opened"])
    assert set(spare) <= soelab.masked_ids()  # 다시 읽기 예정이 되어 재판정 전까지 숨긴다
    rows = {x["id"]: x for x in c.get("/api/soelab/pieces").json()["rows"]}
    assert all(rows[x]["hidden"] == "redo" for x in spare)
    # 7일 규칙: 오늘 판정한 예비는 오늘 열리지 않는다
    assert not set(spare) & set(soelab.redo_due())
    later = datetime.now().astimezone() + timedelta(days=8)
    assert set(spare) <= set(soelab.redo_due(later.date()))
    assert c.post("/api/soelab/spares/open").status_code == 400  # 더 열 예비가 없다
    soelab.save_judge(spare[0], "ai", redo_too=True, now=later)
    assert spare[0] not in soelab.masked_ids()


def test_spare_open_limit(c, monkeypatch):
    _collect(c, eps=13, sets=2)
    q = soelab.load_queue()
    _judge_fast(len(q["order"]))
    ready = [x for x in q["spare"]]
    monkeypatch.setattr(soelab, "consistency", lambda *a, **k: dict(HELD))
    soelab.set_state(goal=90)
    soelab.report(n_boot=50)
    assert not soelab.load_state()["spare_shown"]  # 90개 아래(52개)이고 보류라 아직 보여 주지 않았다
    assert soelab.open_spares(limit=3) == min(3, len(ready))
    assert soelab.screen()["spare"]["ready"] == min(soelab.SPARE_OPEN, len(ready) - 3)


@pytest.mark.parametrize("how", ["settled", "stop", "ninety"])
def test_spare_answers_shown(c, monkeypatch, how):
    _collect(c, eps=13, sets=4 if how == "ninety" else 2)
    q = soelab.load_queue()
    if how == "ninety":
        soelab.set_state(goal=90)
        judged = _judge_fast(90)
    else:
        judged = _judge_fast(30)
    spare = [x for x in judged if x in set(q["spare"])]
    if how == "settled":
        assert spare[0] in soelab.masked_ids()
        monkeypatch.setattr(soelab, "consistency", lambda *a, **k: dict(SETTLED))
        c.post("/api/soelab/report")
    elif how == "stop":
        assert spare[0] in soelab.masked_ids()
        c.put("/api/soelab/state", json={"stopped": True})
    assert soelab.load_state()["spare_shown"]
    opened = set(soelab.load_queue()["opened"])  # 60개에서 다시 읽기로 연 예비는 다시 읽기 규칙을 따른다 (재판정 뒤에 보임)
    assert opened or how != "ninety"
    spare = [x for x in spare if x not in opened]
    assert spare and not set(spare) & soelab.masked_ids()
    k = judged.index(spare[0]) // soelab.BATCH + 1
    row = next(r for r in c.get(f"/api/soelab/batch/{k}").json()["rows"] if r["id"] == spare[0])
    assert not row["hidden"] and row["origin"] in ("human", "ai")
    # 본 뒤에는 다시 읽기에 쓸 수 없다 (보류가 다시 와도)
    monkeypatch.setattr(soelab, "consistency", lambda *a, **k: dict(HELD))
    soelab.report(n_boot=50)
    r = c.post("/api/soelab/spares/open")
    assert r.status_code == 400 and "이미 보여" in r.json()["detail"]
    # 멈췄다가 이어 해도 다시 숨기지 않는다
    c.put("/api/soelab/state", json={"stopped": False})
    assert soelab.load_state()["spare_shown"]


# ---------- 예비: 60개에 닿으면 재판정을 30개까지 채운다 ----------

def test_spare_fill_at_60(c, monkeypatch):
    _collect(c, eps=13, sets=3)
    q = soelab.load_queue()
    judged = _judge_fast(40)
    assert soelab.load_queue()["opened"] == [] and soelab.load_state()["filled"] is None  # 1차(40개)에서는 열지 않는다
    soelab.set_state(goal=60)
    by_id = {p.id: p for p in soelab.load_pieces()}
    for pid in q["order"][40:60]:
        soelab.save_judge(pid, by_id[pid].origin)
    judged = q["order"][:60]
    have = sum(x in set(q["redo"]) for x in judged)
    spare = [x for x in judged if x in set(q["spare"])]
    want = min(max(0, soelab.FILL_TO - have), len(spare))
    q2 = soelab.load_queue()
    assert want > 0 and len(q2["opened"]) == want and set(q2["opened"]) <= set(spare)
    assert sum(x in set(q2["redo"]) for x in judged) == min(soelab.FILL_TO, have + len(spare))
    sc = c.get("/api/soelab").json()
    assert sc["spare"]["filled"] == want and sc["redo_state"]["target"] >= have + want
    assert not set(q2["opened"]) & set(soelab.redo_due())  # 7일 규칙은 그대로
    assert set(q2["opened"]) <= soelab.masked_ids()
    # 한 번만: 더 판정해도 다시 채우지 않는다
    for pid in q["order"][60:62]:
        soelab.save_judge(pid, by_id[pid].origin)
    assert soelab.load_queue()["opened"] == q2["opened"]
    # 60개에서 쓴 만큼 줄어든 예비만 보류 때 열린다. 다 쓰면 열 수 없다
    monkeypatch.setattr(soelab, "consistency", lambda *a, **k: dict(HELD))
    c.post("/api/soelab/report")
    left = c.get("/api/soelab").json()["spare"]["ready"]
    assert left == min(soelab.SPARE_OPEN, len([x for x in q["order"][:62] if x in set(q["spare"])]) - want)
    while left:
        assert c.post("/api/soelab/spares/open").json()["opened"] == left
        left = c.get("/api/soelab").json()["spare"]["ready"]
    r = c.post("/api/soelab/spares/open")
    assert r.status_code == 400 and "재판정이 따라 늘어요" in r.json()["detail"]
