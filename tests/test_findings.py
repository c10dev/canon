"""검수 세션 (canon/findings.py) 테스트: 회차 합치기 규칙, 옛 작품 옮기기, 작가가 정한 상태, 자동 집필 허용 개수,
다시 생성 재료, 웹 엔드포인트(지적 상태, 채팅 앱 검수 JSON, 문체 지표, 검수 지시서), 명령줄 플래그.

    python -m pytest tests/test_findings.py
"""
import contextlib
import importlib
import io
import json
import os
import tempfile

import pytest

os.environ.setdefault("CANON_LLM", "mock")
os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())

from fastapi.testclient import TestClient  # noqa: E402

from canon import autorun, findings, pipeline, store  # noqa: E402
from canon.cli import main  # noqa: E402
from canon.schema import (ConsistencyIssue, ConsistencyReport, Episode, EpisodePlot, Meta, Project,  # noqa: E402
                          StateDelta)

Q1 = "도현은 오른손에 남은 흉터를 엄지로 문질렀다."
Q2 = "서윤은 눈앞의 문손잡이를 두 손으로 붙잡았다."
Q3 = "“그만해. 네가 뭘 안다고.”"
Q4 = "도현은 그녀가 눈치채지 못하기를 속으로 빌었다."
Q5 = "서윤은 등불을 내려놓고 두 손으로 책을 펼쳤다."
TEXT = " ".join([Q1, Q2, Q3, Q4, Q5])


def issue(quote: str, type_: str = "사실", desc: str = "어긋남") -> ConsistencyIssue:
    return ConsistencyIssue(type=type_, description=desc, source_episode=0, source_quote="설정", current_quote=quote)


def episode(text: str = TEXT) -> Episode:
    plot = EpisodePlot(number=1, act="기", title="1화", summary="", events=[], characters=[], emotional_shift="", ending_hook="")
    return Episode(plot=plot, status="written", text=text)


def test_merge_rules():
    ep = episode()
    r1 = findings.merge(ep, [issue(Q1), issue(Q2, "동선"), issue(Q3, "말투"), issue(Q4, "시점")], "t1", "b1")
    assert (r1.no, r1.found, r1.added, r1.kept_again) == (1, 4, 4, 0)
    assert [f.id for f in ep.findings] == ["f1", "f2", "f3", "f4"]
    findings.set_status(ep, "f2", "kept", "일부러 둠", "t1a")
    findings.set_status(ep, "f3", "fixed", None, "t1b")  # 고쳤다고 했지만 본문은 그대로
    ep.text = ep.text.replace(Q1, "도현은 왼손에 남은 흉터를 엄지로 문질렀다.")  # f1 은 실제로 고침

    # 2회차: f2 · f3 를 다시 짚고 f4 는 놓치고, 새 지적 하나. 문장을 조금 바꿔 옮겨도 같은 지적으로 본다
    r2 = findings.merge(ep, [issue(Q2[:-1] + "…", "동선", "새 설명"), issue(Q3, "말투"), issue(Q5, "동선")], "t2", "b2", "chat")
    f = {x.id: x for x in ep.findings}
    assert (r2.no, r2.found, r2.added, r2.kept_again, r2.source) == (2, 3, 1, 1, "chat")
    assert (f["f1"].status, f["f1"].closed_by) == ("fixed", "recheck")  # 문장이 사라졌다
    assert (f["f2"].status, f["f2"].note, f["f2"].description, f["f2"].last) == ("kept", "일부러 둠", "새 설명", 2)
    assert (f["f3"].status, f["f3"].closed_by) == ("open", "")  # 고침이었는데 다시 나옴
    assert (f["f4"].status, f["f4"].last) == ("open", 1)  # 짚지 않았지만 문장이 그대로라 열림
    assert (f["f5"].first, f["f5"].status) == (2, "open")
    assert [x.current_quote for x in ep.issues] == [Q2[:-1] + "…", Q3, Q5] and ep.checked_at == "t2"
    assert [x.id for x in findings.open_findings(ep)] == ["f3", "f4", "f5"]
    assert "이번 회차에서 안 짚음" in findings.line(ep, f["f4"]) and "안 짚음" not in findings.line(ep, f["f3"])


def test_same_sentence_prefers_same_type_and_keeps_rounds():
    ep = episode()
    findings.merge(ep, [issue(Q1, "사실"), issue(Q1, "시점")], "t1", "b")
    findings.merge(ep, [issue(Q1, "시점")], "t2", "b")
    f = {x.type: x for x in ep.findings}
    assert (f["시점"].last, f["사실"].last) == (2, 1)
    for k in range(findings.ROUNDS_KEEP + 3):
        findings.merge(ep, [], f"t{k}", "b")
    assert len(ep.rounds) == findings.ROUNDS_KEEP and ep.rounds[-1].no == findings.ROUNDS_KEEP + 5


def test_quote_less_issue_matches_by_description():
    ep = episode()
    findings.merge(ep, [issue("", desc="플롯 사건이 빠졌다")], "t1", "b")
    findings.merge(ep, [issue("", desc="플롯 사건이 빠졌다"), issue("", desc="다른 사건")], "t2", "b")
    assert [(x.description, x.last) for x in ep.findings] == [("플롯 사건이 빠졌다", 2), ("다른 사건", 2)]
    findings.merge(ep, [], "t3", "b")
    assert all(x.status == "open" for x in ep.findings)  # 문장이 없으면 사라졌다고 닫지 않는다


def test_set_status_and_counted():
    ep = episode()
    findings.merge(ep, [issue(Q1), issue(Q2)], "t1", "b")
    findings.set_status(ep, "f1", "wrong", "  10화에서 말해 줬다 ", "t")
    assert (ep.findings[0].note, ep.findings[0].closed_by, ep.findings[0].decided_at) == ("10화에서 말해 줬다", "author", "t")
    findings.set_status(ep, "f1", "open", None, "t2")
    assert (ep.findings[0].note, ep.findings[0].closed_by, ep.findings[0].decided_at) == ("10화에서 말해 줬다", "", "")
    with pytest.raises(ValueError, match="그런 지적이 없어요"):
        findings.set_status(ep, "f9", "kept", None, "t")
    with pytest.raises(ValueError, match="지적 상태는"):
        findings.set_status(ep, "f1", "done", None, "t")
    findings.set_status(ep, "f2", "kept", None, "t")
    assert [x.current_quote for x in findings.counted(ep, [issue(Q1), issue(Q2), issue(Q5)])] == [Q1, Q5]


def test_old_project_moves_issues_into_round_one():
    old = episode().model_dump()
    old.update(issues=[issue(Q1).model_dump(), issue(Q2, "동선").model_dump()], checked_at="2026-10-01T10:00")
    del old["findings"], old["rounds"]
    ep = Episode.model_validate(old)
    assert [(f.id, f.status, f.first) for f in ep.findings] == [("f1", "open", 1), ("f2", "open", 1)]
    assert (ep.rounds[0].no, ep.rounds[0].at, ep.rounds[0].basis, ep.rounds[0].found) == (1, "2026-10-01T10:00", "", 2)
    again = Episode.model_validate(ep.model_dump())  # 이미 옮긴 작품은 그대로
    assert len(again.findings) == 2 and len(again.rounds) == 1
    findings.merge(ep, [issue(Q2, "동선")], "t", "b")
    assert ep.rounds[-1].no == 2


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "3", "-y"])
        main(["arc", "demo", "-y"])
        main(["plot", "demo"])
        main(["confirm", "demo", "all"])
        main(["write", "demo", "1"])
    return "demo"


def test_pipeline_apply_check_and_consumers(demo):
    p = store.load(demo)
    ep = p.episode(1)
    q = ep.text.split(".")[0].strip() + "."
    r = pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue(q), issue("", desc="사건 누락")]), "api", True)
    assert (r.no, r.basis, r.widen) == (1, pipeline.text_basis(ep.text), True)
    findings.set_status(ep, "f2", "kept", None, "t")
    mats = pipeline.rewrite_materials(p, 1)["issues"]
    assert len(mats) == 1 and "사건 누락" not in mats[0]  # 다시 생성 재료는 열린 지적만

    # 자동 집필 허용 개수: 그대로 둔 지적은 다시 나와도 세지 않는다
    rep = ConsistencyReport(episode=1, issues=[issue("", desc="사건 누락")])
    assert autorun.review_reasons(p, StateDelta(episode=1, summary="s"), rep, autorun.Policy(hand_pick_opening=False)) == []
    rep.issues.append(issue(q))
    assert "검수에서 어긋난 곳 1개" in autorun.review_reasons(p, StateDelta(episode=1, summary="s"), rep, autorun.Policy(hand_pick_opening=False))[0]

    pipeline.replace_text(ep, ep.text + " 덧붙임.")  # 새 판을 고르면 새 세션
    assert (ep.findings, ep.rounds, ep.issues, ep.checked_at) == ([], [], [], "")
    with pytest.raises(ValueError, match="본문이 없어요"):
        pipeline.apply_check(p, ConsistencyReport(episode=2, issues=[]))


def test_web_endpoints(demo):
    from canon import web
    importlib.reload(web)
    c = TestClient(web.app)
    text = store.load(demo).episode(1).text
    q = text.split(".")[0].strip() + "."
    brief = c.get(f"/api/projects/{demo}/episodes/1/brief", params={"kind": "check"})
    assert brief.status_code == 200 and "JSON" in brief.json()["text"]
    assert c.get(f"/api/projects/{demo}/episodes/2/brief", params={"kind": "check"}).status_code == 400

    raw = "답이에요\n```json\n" + json.dumps({"issues": [issue(q).model_dump()]}, ensure_ascii=False) + "\n```"
    pj = c.post(f"/api/projects/{demo}/episodes/1/check/import", json={"raw": raw}).json()
    e = pj["episodes"][0]
    assert e["rounds"][0]["source"] == "chat" and e["findings"][0]["id"] == "f1"
    bad = c.post(f"/api/projects/{demo}/episodes/1/check/import", json={"raw": '{"issues": [{"type": "사실"}]}'})
    assert bad.status_code == 400 and "JSON 내용이 맞지 않아요" in bad.json()["detail"]

    pj = c.put(f"/api/projects/{demo}/episodes/1/findings/f1", json={"status": "kept", "note": "의도"}).json()
    assert (pj["episodes"][0]["findings"][0]["status"], pj["episodes"][0]["findings"][0]["note"]) == ("kept", "의도")
    assert c.put(f"/api/projects/{demo}/episodes/1/findings/f9", json={"status": "kept"}).status_code == 400
    assert c.put(f"/api/projects/{demo}/episodes/1/findings/f1", json={"status": "done"}).status_code == 422
    pj = c.post(f"/api/projects/{demo}/episodes/1/check/import", json={"raw": raw}).json()
    f = pj["episodes"][0]
    assert (f["findings"][0]["status"], f["rounds"][-1]["kept_again"]) == ("kept", 1)

    st = c.get(f"/api/projects/{demo}/episodes/1/style").json()
    assert isinstance(st["warnings"], list) and isinstance(st["metrics"], dict)
    assert c.get(f"/api/projects/{demo}/episodes/2/style").status_code == 400


def test_cli_flags(demo):
    out = io.StringIO()
    p = store.load(demo)
    q = p.episode(1).text.split(".")[0].strip() + "."
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue(q)]))
    store.save(demo, p)
    with contextlib.redirect_stdout(out):
        main(["check", demo, "1", "--wrong", "f1", "--note", "괜찮음"])
    assert "f1: 잘못 짚음으로 정했어요 (메모: 괜찮음)" in out.getvalue()
    assert "처리한 지적 1곳" in out.getvalue() and "열린 지적 0곳" in out.getvalue()
    assert store.load(demo).episode(1).findings[0].status == "wrong"
