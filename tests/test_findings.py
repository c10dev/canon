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
from types import SimpleNamespace

import pytest

os.environ.setdefault("CANON_LLM", "mock")
os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())

from fastapi.testclient import TestClient  # noqa: E402

from canon import autorun, findings, pipeline, store  # noqa: E402
from canon.cli import main  # noqa: E402
from canon.schema import (ConsistencyIssue, ConsistencyReport, Episode, EpisodePlot, StateDelta)

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

    pipeline.replace_text(ep, ep.text + " 덧붙임.")  # 새 판을 고르면 결정한 지적만 남고 회차 번호는 잇는다
    assert [(f.id, f.status) for f in ep.findings] == [("f2", "kept")]
    assert (len(ep.rounds), ep.rounds[-1].superseded, ep.issues, ep.checked_at) == (1, True, [], "")
    r2 = pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue("", desc="사건 누락")]))
    assert (r2.no, r2.kept_again, ep.findings[0].status) == (2, 1, "kept")
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


# ---------- 심각도 · 회차 비교 · 고침안 · 지적 하나 다시 검수 ----------

def test_round_ids_and_author_severity():
    ep = episode()
    findings.merge(ep, [issue(Q1), issue(Q2, "동선"), issue(Q3, "말투")], "t1", "b1")
    findings.set_severity(ep, "f2", "crit", "t1a")
    with pytest.raises(ValueError, match="심각도"):
        findings.set_severity(ep, "f2", "huge", "t1b")
    ep.text = ep.text.replace(Q1, "도현은 왼손에 남은 흉터를 엄지로 문질렀다.")
    low = issue(Q2, "동선")
    low.severity = "low"
    r2 = findings.merge(ep, [low, issue(Q5, "동선")], "t2", "b2")
    f = {x.id: x for x in ep.findings}
    assert (r2.added_ids, r2.again_ids, r2.gone_ids) == (["f4"], ["f2"], ["f1"])
    assert (f["f2"].severity, f["f2"].severity_by_author) == ("crit", True)  # 작가가 정한 심각도는 덮지 않는다
    assert [e.kind for e in f["f2"].log] == ["found", "author", "again"]
    assert "[치명]" in findings.line(ep, f["f2"])


def test_settle_children():
    ep = episode()
    findings.merge(ep, [issue(Q1), issue(Q2, "동선")], "t1", "b1")
    findings.set_status(ep, "f2", "kept", None, "t1a")
    ep.text = ep.text.replace(Q1, "도현은 왼손에 남은 흉터를 감췄다.")
    from canon.schema import FindingRecheck
    res = FindingRecheck(resolved=True, reason="왼손으로 바뀜", new_issues=[
        issue("도현은 왼손에 남은 흉터를 감췄다.", desc="왼손에는 흉터가 없다"),  # 고친 문장: 옛 문장과 겹쳐도 딸린 지적이 된다
        issue(Q2, "동선"),  # 그대로 둔 지적과 같은 문장은 더하지 않는다
        issue("본문에 없는 문장"),  # 본문에 없으면 뺀다
    ])
    kids = findings.settle(ep, findings.find(ep, "f1"), res, "t2")
    f = {x.id: x for x in ep.findings}
    assert (f["f1"].status, f["f1"].closed_by) == ("fixed", "one") and len(ep.rounds) == 1
    assert [(k.id, k.parent) for k in kids] == [("f3", "f1")]
    assert "f1 지적을 고치다 생김" in findings.line(ep, kids[0])
    findings.set_status(ep, "f1", "open", None, "t3")  # 작가가 다시 열면 되돌린다
    assert (f["f1"].status, f["f1"].closed_by) == ("open", "")


def test_fixes_apply_and_undo(demo):
    p = store.load(demo)
    ep = p.episode(1)
    q = "바람이 불었다."
    nxt = "서윤은 등대 앞에 섰다."
    assert q in ep.text and nxt in ep.text
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue(q)]))
    from canon import prompts
    from canon.mock import MockLLM
    # 고침안은 낱말만 바꾸는 규칙을 받는다 (풀어 쓴 고침안이 나오지 않게)
    assert prompts.MINIMAL_FIX_RULES in prompts.fix_prompt(p, 1, ep.issues[0], [])
    assert prompts.TEXT_RIGHT_RULE.format(field="options") in prompts.fix_prompt(p, 1, ep.issues[0], [])

    class TextRight:  # 본문이 맞다는 답은 그 답을 오류로 보인다
        def json(self, system, prompt, schema, hint=None):
            return schema(reply="본문이 맞아요. 플롯을 고치세요.")
    with pytest.raises(ValueError, match="본문은 고치지 않았어요. 본문이 맞아요"):
        pipeline.propose_fixes(TextRight(), p, 1, "f1")
    opts = pipeline.propose_fixes(MockLLM(), p, 1, "f1")
    assert [o.label for o in opts] == ["짧게 고치기", "뒤 문장까지"]  # 원문 그대로인 안은 걸렀다
    assert [x.quote for x in opts[1].extra] == [nxt]
    f = pipeline.store_fixes(p, 1, "f1", opts)
    assert f.fixes_basis == pipeline.text_basis(ep.text)

    before = ep.text
    edits = pipeline.apply_fix(p, 1, "f1", 1)
    assert "바람이 불었다 — 고침 2" in ep.text and q not in ep.text and f"{nxt} (함께 고침)" in ep.text
    assert {e.group for e in edits} == {"x1"} and {e.source for e in edits} == {"fix"} and f.fix_group == "x1"
    assert f.status == "open"  # 적용만으로 닫지 않는다
    done, left = pipeline.undo_fix(p, 1, "x1")
    assert (len(done), left, ep.text, f.fix_group) == (2, [], before, "")
    with pytest.raises(KeyError):
        pipeline.undo_fix(p, 1, "x1")

    # 딸린 곳을 빼고 적용 → 다시 검수(mock: 문장이 바뀌면 풀림) → 고침으로 닫힘
    pipeline.apply_fix(p, 1, "f1", 1, skip=[0])
    assert f"{nxt} (함께 고침)" not in ep.text
    res = pipeline.recheck_finding(MockLLM(), p, 1, "f1")
    assert res.resolved and pipeline.apply_recheck(p, 1, "f1", res) == []
    assert (f.status, f.closed_by, len(ep.rounds)) == ("fixed", "one", 1)
    with pytest.raises(ValueError, match="열린 지적이 아니에요"):
        pipeline.propose_fixes(MockLLM(), p, 1, "f1")


def test_apply_fix_guards(demo):
    p = store.load(demo)
    ep = p.episode(1)
    q, nxt = "바람이 불었다.", "서윤은 등대 앞에 섰다."
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue(q), issue(nxt, "동선")]))
    findings.set_status(ep, "f2", "kept", "일부러", "t")
    from canon.mock import MockLLM
    pipeline.store_fixes(p, 1, "f1", pipeline.propose_fixes(MockLLM(), p, 1, "f1"))
    assert findings.touches(ep, ep.findings[0], ep.findings[0].fixes[1]) == ["f2"]
    with pytest.raises(ValueError, match="그대로 두기로 정한 지적\\(f2\\)"):
        pipeline.apply_fix(p, 1, "f1", 1)
    pipeline.apply_fix(p, 1, "f1", 1, confirm=True)
    assert f"{nxt} (함께 고침)" in ep.text
    pipeline.undo_fix(p, 1, "x1")
    ep.text = ep.text.replace(nxt, "서윤은 등대 뒤에 섰다.")  # 고침안을 받은 뒤 본문이 바뀜
    with pytest.raises(ValueError, match="고침안을 다시 받으세요"):
        pipeline.apply_fix(p, 1, "f1", 1, confirm=True)
    with pytest.raises(KeyError):
        pipeline.apply_fix(p, 1, "f1", 5)


def test_autorun_severity_policy(demo):
    p = store.load(demo)
    delta = StateDelta(episode=1, summary="s")
    crit, low = issue("바람이 불었다."), issue("서윤은 등대 앞에 섰다.")
    crit.severity, low.severity = "crit", "low"
    loose = autorun.Policy(hand_pick_opening=False, max_issues=2)
    assert "치명적인 어긋남 1개" in autorun.review_reasons(p, delta, ConsistencyReport(episode=1, issues=[crit]), loose)[0]
    assert autorun.review_reasons(p, delta, ConsistencyReport(episode=1, issues=[crit]),
                                  loose.model_copy(update={"stop_on_critical": False})) == []
    strict = autorun.Policy(hand_pick_opening=False)
    rep = ConsistencyReport(episode=1, issues=[low])
    assert "어긋난 곳 1개" in autorun.review_reasons(p, delta, rep, strict)[0]  # 기본은 사소도 센다
    assert autorun.review_reasons(p, delta, rep, strict.model_copy(update={"ignore_minor": True})) == []


def test_web_fix_endpoints(demo):
    from canon import web
    importlib.reload(web)
    c = TestClient(web.app)
    p = store.load(demo)
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue("바람이 불었다.")]))
    store.save(demo, p)
    base = f"/api/projects/{demo}/episodes/1"
    f = c.put(f"{base}/findings/f1", json={"severity": "low"}).json()["episodes"][0]["findings"][0]
    assert (f["severity"], f["severity_by_author"], f["status"]) == ("low", True, "open")
    f = c.post(f"{base}/findings/f1/fixes").json()["episodes"][0]["findings"][0]
    assert len(f["fixes"]) == 2 and f["fixes_basis"]
    e = c.post(f"{base}/findings/f1/fixes/1/apply", json={}).json()["episodes"][0]
    assert e["findings"][0]["fix_group"] == "x1" and "(함께 고침)" in e["text"]
    e = c.post(f"{base}/fix-groups/x1/undo").json()["episodes"][0]
    assert "(함께 고침)" not in e["text"] and e["findings"][0]["fix_group"] == ""
    c.post(f"{base}/findings/f1/fixes/0/apply", json={})
    f = c.post(f"{base}/findings/f1/recheck").json()["episodes"][0]["findings"][0]
    assert (f["status"], f["closed_by"]) == ("fixed", "one")
    assert c.post(f"{base}/findings/f1/recheck").status_code == 400  # 닫힌 지적


def test_cli_sev_and_recheck(demo):
    p = store.load(demo)
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue("바람이 불었다.")]))
    store.save(demo, p)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["check", demo, "1", "--sev", "f1", "치명"])
        main(["check", demo, "1", "--recheck", "f1"])
    assert "f1: 심각도를 치명으로 정했어요" in out.getvalue() and "f1: 아직 어긋나요" in out.getvalue()
    f = store.load(demo).episode(1).findings[0]
    assert (f.severity, f.status, f.log[-1].kind) == ("crit", "open", "recheck")


def test_check_done_matches_check_state():
    """findings.check_done 은 home.js checkState 의 done 과 같은 규칙 (작품 목록의 '검수 대기' · '상태 승인 대기')."""
    from canon.schema import Finding, TextEdit
    e = episode("본문")
    assert not findings.check_done(e)  # 검수 전
    e.checked_at = "2026-10-30T10:00:00+00:00"
    assert findings.check_done(e)
    e.findings = [Finding(id="f1", type="사실", description="d", source_quote="", current_quote="본문", status="open")]
    assert not findings.check_done(e)  # 열린 지적
    e.findings[0].status = "kept"
    e.edits = [TextEdit(id="x1", at="2026-10-30T11:00:00+00:00")]
    assert not findings.check_done(e)  # 검수 뒤 고침
    e.edits[0].undone = True
    assert findings.check_done(e)
    e.edits = [TextEdit(id="x2", at="2026-10-30T11:00:00+00:00", group="g1")]
    e.findings[0].closed_by, e.findings[0].fix_group = "one", "g1"
    assert findings.check_done(e)  # 이 지적만 다시 검수가 본 고침


def test_fix_targets_and_batch_apply(demo):
    """열린 지적 모두 고침안 받기의 대상(fix_targets)과 고른 고침안 한꺼번에 넣기(apply_fixes)."""
    from canon.mock import MockLLM
    p = store.load(demo)
    ep = p.episode(1)
    q1, q2 = "바람이 불었다.", "서윤은 등대 앞에 섰다."
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue(q1), issue(q2, "동선"), issue("본문에 없는 문장.", "말투")]))
    findings.set_status(ep, "f2", "kept", None, "t")
    assert pipeline.fix_targets(ep) == ["f1"]  # 처리한 지적 · 문장이 없는 지적은 빼고
    findings.set_status(ep, "f2", "open", None, "t")
    assert pipeline.fix_targets(ep) == ["f1", "f2"]
    for fid in ("f1", "f2"):
        pipeline.store_fixes(p, 1, fid, pipeline.propose_fixes(MockLLM(), p, 1, fid))
    assert pipeline.fix_targets(ep) == []  # 넣을 수 있는 고침안이 있으면 다시 받지 않는다

    # f2 의 안이 f1 문장(q1)도 딸린 곳으로 고친다 → f1 을 먼저 넣으면 f2 는 문장이 없어 못 넣고, 나머지는 넣는다
    from canon.schema import FixOption, FixPatch
    pipeline.store_fixes(p, 1, "f2", [FixOption(label="앞까지", text="서윤은 등대 뒤에 섰다.", extra=[FixPatch(quote=q1, replacement="바람이 멎었다.")])])
    done, failed = pipeline.apply_fixes(p, 1, [("f1", 0, []), ("f2", 0, []), ("f9", 0, [])])
    assert done == ["f1"] and [f for f, _ in failed] == ["f2", "f9"]
    assert "고침안을 다시 받으세요" in failed[0][1] and "그런 지적이 없어요" in failed[1][1]
    assert ep.findings[0].fix_group == "x1" and q1 not in ep.text and q2 in ep.text
    assert pipeline.fix_targets(ep) == ["f2"]  # f1 은 문장이 바뀌어 빠지고, f2 는 넣을 수 있는 안이 없어 다시 받는다
    done, failed = pipeline.apply_fixes(p, 1, [("f2", 0, [0])])  # 딸린 곳을 빼면 넣을 수 있다
    assert done == ["f2"] and failed == [] and "서윤은 등대 뒤에 섰다." in ep.text


def test_web_fixes_job_and_batch_apply(demo):
    import time

    from canon import web
    importlib.reload(web)
    c = TestClient(web.app)
    p = store.load(demo)
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue("바람이 불었다."), issue("서윤은 등대 앞에 섰다.", "동선")]))
    store.save(demo, p)
    j = c.post(f"/api/projects/{demo}/jobs", json={"kind": "fixes", "ep": 1}).json()
    assert j["total"] == 2 and "지적 2개 고침안" in j["label"]
    for _ in range(100):
        j = next(x for x in c.get("/api/jobs").json() if x["id"] == j["id"])
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert (j["status"], j["done"], j["result"]) == ("done", 2, {"done": 2, "failed": []})
    e = store.load(demo).episode(1)
    assert all(len(f.fixes) == 2 for f in e.findings)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "fixes", "ep": 1})
    assert r.status_code == 400 and "고침안을 받을 열린 지적이 없어요" in r.text  # 모두 받았으면 다시 받지 않는다

    base = f"/api/projects/{demo}/episodes/1"
    assert c.post(f"{base}/fixes/apply", json={"items": []}).status_code == 400
    out = c.post(f"{base}/fixes/apply", json={"items": [{"fid": "f1", "k": 0}, {"fid": "f2", "k": 0}]}).json()
    assert out["applied"] == ["f1", "f2"] and out["failed"] == []
    ep = out["project"]["episodes"][0]
    assert [f["fix_group"] for f in ep["findings"]] == ["x1", "x2"]  # 지적마다 한 묶음
    assert all(set(s) == {"episode"} for s in out["project"]["snapshots"])  # 스냅샷은 화 번호만 (작품 응답과 같다)
    assert [f.status for f in store.load(demo).episode(1).findings] == ["open", "open"]  # 넣기만으로 닫지 않는다 (다시 검수가 닫는다)


def test_stale_screen_save_keeps_check_job_results(demo):
    """검수 작업이 지적을 쓴 뒤, 그 전에 읽은 화면이 그 화를 고쳐 PUT · PATCH 로 보내도 검수 결과는 남는다 (web.JOB_EP_FIELDS)."""
    import time

    from canon import web
    importlib.reload(web)
    c = TestClient(web.app)
    stale = c.get(f"/api/projects/{demo}").json()  # 검수 전에 읽은 화면
    assert stale["episodes"][0]["findings"] == []
    j = c.post(f"/api/projects/{demo}/jobs", json={"kind": "check", "ep": 1}).json()
    for _ in range(100):
        j = next(x for x in c.get("/api/jobs").json() if x["id"] == j["id"])
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done"
    after = store.load(demo).episode(1)
    assert after.rounds and after.checked_at
    want = (after.model_dump(include=set(web.JOB_EP_FIELDS)), after.rounds[-1].no)

    stale["episodes"][0]["summary"] = "화면에서 고친 요약"  # 화면이 그 화를 고쳐 화 전체를 보낸다
    out = c.put(f"/api/projects/{demo}", json=stale).json()["episodes"][0]
    assert out["summary"] == "화면에서 고친 요약"
    e = store.load(demo).episode(1)
    assert (e.model_dump(include=set(web.JOB_EP_FIELDS)), e.rounds[-1].no) == want

    ep = dict(stale["episodes"][0], summary="PATCH 로 고친 요약", findings=[], rounds=[], issues=[], checked_at="")
    eps = [ep] + [{"$same": x["plot"]["number"]} for x in stale["episodes"][1:]]
    r = c.patch(f"/api/projects/{demo}", json={"edit_rev": stale["edit_rev"], "fields": {"episodes": eps}})
    assert r.status_code == 200 and r.json()["episodes"][0]["summary"] == "PATCH 로 고친 요약"
    e = store.load(demo).episode(1)
    assert (e.model_dump(include=set(web.JOB_EP_FIELDS)), e.rounds[-1].no) == want


OLD = "2000-01-01T00:00:00+00:00"  # 검수 시각을 앞으로 당겨, 같은 초에 넣은 고침안도 '검수 뒤 수정'으로 센다


def test_fix_recheck_targets_and_pipeline(demo):
    """고친 곳만 다시 보기: 지난 검수 뒤 수정이 모두 고침안이면 그 지적들만, 한 번의 호출로 다시 보고 settle 로 넣는다."""
    from canon import prompts
    from canon.mock import MockLLM
    from canon.schema import FixRecheckItem, FixRecheckReport
    p = store.load(demo)
    ep = p.episode(1)
    q1, q2 = "바람이 불었다.", "서윤은 등대 앞에 섰다."
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue(q1), issue(q2, "동선"), issue("본문에 없는 문장.", "말투")]))
    ep.checked_at = OLD
    assert findings.fix_recheck_targets(ep) == []  # 검수 뒤 고친 곳이 없다
    for fid in ("f1", "f2"):
        pipeline.store_fixes(p, 1, fid, pipeline.propose_fixes(MockLLM(), p, 1, fid))
    pipeline.apply_fixes(p, 1, [("f1", 0, []), ("f2", 0, [])])
    assert [f.id for f in findings.fix_recheck_targets(ep)] == ["f1", "f2"]

    # 직접 고친 곳이 하나라도 있으면 다시 검수해야 한다
    typed = pipeline.record_typed(p, 1, ep.text, ep.text + " 덧붙임.")
    assert findings.fix_recheck_targets(ep) == []
    typed.undone = True
    assert len(findings.fix_recheck_targets(ep)) == 2

    # 프롬프트: 검수 자료 전체가 아니라 작품 설정(검수와 같은 앞부분)과 고친 곳 둘레 문단만
    calls = []

    class Spy(MockLLM):
        def json(self, system, prompt, schema, hint=None, **kw):
            calls.append((prompt, schema))
            return super().json(system, prompt, schema, hint=hint, **kw)
    rep = pipeline.recheck_fixed(Spy(), p, 1)
    assert len(calls) == 1 and calls[0][1] is FixRecheckReport
    prompt = calls[0][0]
    assert prompt.startswith(prompts.static_context(p)) and prompts.check_material(p, 1).startswith(prompts.static_context(p))
    assert "## 지적 f1" in prompt and "## 지적 f2" in prompt and "## 지적 f3" not in prompt
    assert f"「{q1}」 →" in prompt and "# 확정된 사실" not in prompt
    assert len(prompt) < len(prompts.check_material(p, 1))
    assert [(x.id, x.resolved) for x in rep.results] == [("f1", True), ("f2", True)]
    assert pipeline.apply_fix_recheck(p, 1, rep) == []
    f = {x.id: x for x in ep.findings}
    assert [(f[i].status, f[i].closed_by) for i in ("f1", "f2", "f3")] == [("fixed", "one"), ("fixed", "one"), ("open", "")]
    assert len(ep.rounds) == 1 and findings.fix_recheck_targets(ep) == []  # 회차는 늘지 않고, 본 묶음은 다시 부르지 않는다
    with pytest.raises(ValueError, match="고친 곳만 다시 볼 지적이 없어요"):
        pipeline.recheck_fixed(MockLLM(), p, 1)

    # 작가가 다시 열어도 이미 다시 본 묶음은 다시 부르지 않는다. 기록을 지우면 다시 대상이 된다
    findings.set_status(ep, "f1", "open", None, pipeline._now())
    assert findings.fix_recheck_targets(ep) == []
    f["f1"].log = []
    assert [x.id for x in findings.fix_recheck_targets(ep)] == ["f1"]
    fixed_text = f["f1"].fixes[0].text.strip()
    assert fixed_text in ep.text

    class Odd:  # 묻지 않은 id · 같은 id 의 두 번째 답은 버리고, 새로 어긋난 곳은 딸린 지적이 된다
        def json(self, system, prompt, schema, hint=None, **kw):
            return FixRecheckReport(results=[FixRecheckItem(id="f9", resolved=True, reason="x"),
                                             FixRecheckItem(id="f1", resolved=False, reason="아직", new_issues=[issue(fixed_text)]),
                                             FixRecheckItem(id="f1", resolved=True, reason="두 번째")])
    rep = pipeline.recheck_fixed(Odd(), p, 1)
    assert [(x.id, x.resolved) for x in rep.results] == [("f1", False)]
    kids = pipeline.apply_fix_recheck(p, 1, rep)
    assert [(k.parent, k.current_quote) for k in kids] == [("f1", fixed_text)]
    assert (f["f1"].status, f["f1"].log[-1].kind) == ("open", "recheck")
    assert findings.fix_recheck_targets(ep) == []  # 아직 어긋난다고 본 지적은 다시 검수로


def test_fix_recheck_late_result_does_not_override(demo):
    """늦게 온 고친 곳만 다시 보기 결과: 그사이 검수를 다시 했거나 되돌려 본문이 바뀌었으면 넣지 않는다.
    그사이 작가가 닫은 지적은 건너뛰고, 실제로 넣은 결과만 settled 에 남는다."""
    from canon.mock import MockLLM
    from canon.schema import FixRecheckItem, FixRecheckReport
    p = store.load(demo)
    ep = p.episode(1)
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue("바람이 불었다."), issue("서윤은 등대 앞에 섰다.", "동선")]))
    ep.checked_at = OLD
    for fid in ("f1", "f2"):
        pipeline.store_fixes(p, 1, fid, pipeline.propose_fixes(MockLLM(), p, 1, fid))
    pipeline.apply_fixes(p, 1, [("f1", 0, []), ("f2", 0, [])])
    basis = pipeline.fix_recheck_basis(ep)
    assert set(basis[2]) == {"f1", "f2"}
    rep = FixRecheckReport(results=[FixRecheckItem(id="f1", resolved=True, reason="풀림"),
                                    FixRecheckItem(id="f2", resolved=False, reason="아직")])

    # 그사이 검수를 다시 했다
    q = p.model_copy(deep=True)
    q.episode(1).checked_at = "2100-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="바뀌어서 결과를 넣지 않았어요"):
        pipeline.apply_fix_recheck(q, 1, rep, basis)
    assert [f.status for f in q.episode(1).findings] == ["open", "open"]

    # 그사이 f1 의 고침안을 되돌렸다 (본문이 지적한 문장으로 돌아왔다)
    q = p.model_copy(deep=True)
    pipeline.undo_fix(q, 1, q.episode(1).findings[0].fix_group)
    with pytest.raises(ValueError, match="바뀌어서 결과를 넣지 않았어요"):
        pipeline.apply_fix_recheck(q, 1, rep, basis)
    assert q.episode(1).findings[0].status == "open"

    # 그사이 작가가 f2 를 손으로 고침으로 닫았다: f2 는 건너뛰고 세지 않는다
    findings.set_status(ep, "f2", "fixed", None, pipeline._now())
    settled: list = []
    assert pipeline.apply_fix_recheck(p, 1, rep, basis, settled) == []
    assert [x.id for x in settled] == ["f1"]
    assert [(f.status, f.closed_by) for f in ep.findings] == [("fixed", "one"), ("fixed", "author")]


def test_fix_spots_picks_match_nearest_recorded_start():
    """고친 글이 본문에 여러 번 나오면 기록한 자리에 가장 가까운 곳을 고친 곳으로 본다."""
    from canon.schema import TextEdit
    s = "그는 고개를 끄덕였다."
    text = f"{s}\n\n가운데 문단.\n\n{s}"
    ep = SimpleNamespace(text=text)
    late = text.rindex(s)
    assert pipeline._fix_spots(ep, [TextEdit(id="e", before="x", after=s, start=late)]) == [(late, late + len(s))]
    assert pipeline._fix_spots(ep, [TextEdit(id="e", before="x", after=s, start=0)]) == [(0, len(s))]
    assert pipeline._fix_spots(ep, [TextEdit(id="e", before="x", after="", start=999)]) == [(len(text), len(text))]


def test_fix_around_merges_neighbour_paragraphs():
    from canon import prompts
    text = "가.\n\n나.\n다.\n라.\n마.\n바."
    at = text.index("다.")
    assert prompts.fix_around(text, [(at, at + 2)]) == ["나.\n다.\n라."]
    at2 = text.index("마.")
    assert prompts.fix_around(text, [(at, at + 2), (at2, at2 + 2)]) == ["나.\n다.\n라.\n마.\n바."]  # 이웃한 둘레는 합친다
    assert prompts.fix_around(text, [(0, 1)], k=0) == ["가."]
    assert prompts.fix_around("", [(0, 0)]) == []


def test_web_recheck_job(demo):
    """웹 작업 recheck: 고침안만 넣었으면 한 번에 다시 보고, 고친 곳이 없거나 직접 고쳤으면 400 으로 알린다."""
    import time

    from canon import jobs, web
    from canon.mock import MockLLM
    importlib.reload(web)
    assert "recheck" in jobs.EP_AI_KINDS
    c = TestClient(web.app)
    p = store.load(demo)
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue("바람이 불었다."), issue("서윤은 등대 앞에 섰다.", "동선")]))
    p.episode(1).checked_at = OLD
    store.save(demo, p)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "recheck", "ep": 1})
    assert r.status_code == 400 and "고친 곳만 다시 볼 지적이 없어요" in r.text
    p = store.load(demo)
    pipeline.store_fixes(p, 1, "f1", pipeline.propose_fixes(MockLLM(), p, 1, "f1"))
    pipeline.apply_fix(p, 1, "f1", 0)
    store.save(demo, p)
    j = c.post(f"/api/projects/{demo}/jobs", json={"kind": "recheck", "ep": 1}).json()
    assert "고친 곳만 다시 보기 · 지적 1개" in j["label"]
    for _ in range(100):
        j = next(x for x in c.get("/api/jobs").json() if x["id"] == j["id"])
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert (j["status"], j["result"]) == ("done", {"asked": 1, "resolved": 1, "open": 0, "added": 0, "missing": []})
    e = store.load(demo).episode(1)
    assert [(f.status, f.closed_by) for f in e.findings] == [("fixed", "one"), ("open", "")] and len(e.rounds) == 1


def test_cli_recheck_fixed(demo):
    from canon.mock import MockLLM
    p = store.load(demo)
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue("바람이 불었다.")]))
    p.episode(1).checked_at = OLD
    pipeline.store_fixes(p, 1, "f1", pipeline.propose_fixes(MockLLM(), p, 1, "f1"))
    pipeline.apply_fix(p, 1, "f1", 0)
    store.save(demo, p)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["check", demo, "1", "--recheck-fixed"])
    assert "f1: 풀렸어요. 고침으로 닫았어요" in out.getvalue()
    assert store.load(demo).episode(1).findings[0].closed_by == "one"
