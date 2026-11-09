"""정규식 규칙 묶음이 걸리는 저장 경로 (docs/context/specs/06-regex-rules.md 의 시험).

본문을 저장하는 길마다 고침 규칙을 한 번 걸고 기록(RuleRun)을 남기는지, 실험 · 비교 길은 걸지 않는지,
검수 합치기 · 다시 판정 · 내보내기, 그리고 묶음을 켜지 않은 작품은 예전과 같은지 본다. 웹 길은 test_regexrules_web.py.

실행: CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_regexrules_paths.py
"""
import contextlib
import inspect
import io

import pytest

from canon import autorun, branches, findings, pipeline, publish, regexrules, sent, store
from canon.cli import main
from canon.mock import MockLLM
from canon.schema import (ConsistencyIssue, ConsistencyReport, PassageCandidate, PassageRevision, RegexRule, Rework,
                          RewriteRequest, RuleBundle, Selection)

from .test_autorun import Policy, demo  # noqa: F401  (pytest fixture)

# mock 본문: "바람이 불었다. 서윤은 등대 앞에 섰다.\n\n\"됐어, 내가 할게.\"\n\n(mock 본문)"
# 서술 다듬기 mock 은 서술 줄 끝 '.' 을 '…' 로 바꾼다. 규칙은 같은 글에 두 번 걸어도 더 바뀌지 않게 골랐다.
WIND = RegexRule(**{"in": "바람(?!결)", "out": "바람결", "action": "fix", "comment": "바람"})
DOTS = RegexRule(**{"in": "…", "out": "⋯", "action": "fix", "comment": "말줄임"})
OFF = RegexRule(**{"in": "섰다", "out": "XX", "action": "fix", "enabled": False})
TOWER = RegexRule(**{"in": "등대", "action": "warn", "comment": "등대 경고"})
STOOD = RegexRule(**{"in": "섰다", "action": "warn", "comment": "섰다 경고"})
EXPORT = RegexRule(**{"in": "서윤", "out": "서윤 씨", "action": "fix", "type": "export"})
LLM = MockLLM()


def _quiet(*argv):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        main(list(argv))
    return out.getvalue()


def _bundle(*rules, name="표기") -> RuleBundle:
    return regexrules.save(RuleBundle(id=regexrules.uuid.uuid4().hex[:12], name=name, rules=list(rules)))


def _on(name: str, *rules) -> RuleBundle:
    b = _bundle(*(rules or (WIND, DOTS, OFF, TOWER, STOOD, EXPORT)))
    _quiet("rules", "use", name, b.id)
    return b


def _found(ep, run):
    """기록의 바뀐 곳이 모두 마지막 본문 자리를 가리킨다."""
    return all(ep.text[c.start:c.start + len(c.after)] == c.after for c in run.changes if not c.undone)


# ---------- 옛 동작 ----------

def test_no_bundles_is_old_behaviour(demo):
    regexrules.shutdown()
    _quiet("write", demo, "1")
    p = store.load(demo)
    ep = p.episode(1)
    assert ep.text.startswith("바람이 불었다.") and ep.rule_runs == [] and ep.versions == []
    assert not regexrules.worker_alive()  # 묶음이 없으면 자식 프로세스를 띄우지 않는다
    rnd = pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[]))
    assert rnd.found == 0 and ep.findings == []
    assert publish.export(p, [1])["text"].count("서윤 씨") == 0
    assert not regexrules.worker_alive()


def test_old_project_json_loads(demo):
    import json
    from canon.schema import Project
    data = json.loads(store.load(demo).model_dump_json())
    data["settings"].pop("rule_bundles")  # 이 칸이 생기기 전 작품
    for e in data["episodes"]:
        e.pop("rule_runs", None)
    p = Project.model_validate(data)
    assert p.settings.rule_bundles == [] and all(e.rule_runs == [] for e in p.episodes)


# ---------- 명령줄 쓰기 · 가져오기 · 다시 생성 ----------

def test_cli_write_records_once_and_sent_basis_matches(demo):
    _on(demo)
    out = _quiet("write", demo, "1")
    assert "규칙으로 1곳 고쳤어요" in out
    ep = store.load(demo).episode(1)
    assert ep.text.startswith("바람결이 불었다.") and "XX" not in ep.text  # 꺼진 규칙은 걸리지 않는다
    assert "서윤 씨" not in ep.text  # 내보내기 규칙은 쓴 본문에 걸리지 않는다
    assert len(ep.rule_runs) == 1
    run = ep.rule_runs[0]
    assert run.id == "r1" and run.kind == "write" and run.skipped == "" and len(run.changes) == 1
    c = run.changes[0]
    assert (c.before, c.after, c.name, c.rule) == ("바람", "바람결", "바람", WIND.id) and _found(ep, run)
    assert sent.matches(sent.read(demo, 1), ep.text)  # 보낸 프롬프트 기록의 지문이 규칙을 건 저장 본문과 맞는다


def test_cli_import(demo, tmp_path):
    _on(demo)
    f = tmp_path / "in.txt"
    f.write_text("  바람이 분다. 서윤은 기다렸다…  ", encoding="utf-8")
    out = _quiet("import", demo, "1", str(f))
    assert "규칙으로 2곳 고쳤어요" in out
    ep = store.load(demo).episode(1)
    assert ep.text == "바람결이 분다. 서윤은 기다렸다⋯" and ep.written_by == "import"
    assert [r.kind for r in ep.rule_runs] == ["import"] and _found(ep, ep.rule_runs[0])


def test_cli_rewrite_candidate_adopt_and_restore(demo, monkeypatch):
    _on(demo)
    _quiet("write", demo, "1")
    monkeypatch.setattr("builtins.input", lambda *a: "n")  # 새 판으로 바꿀지 물으면 '아니요'
    out = _quiet("rewrite", demo, "1", "--ask", "조용히")
    assert "규칙으로 1곳 고쳤어요" in out
    p = store.load(demo)
    ep = p.episode(1)
    c = ep.candidate
    assert c.text.startswith("바람결이 멎었다.") and [r.kind for r in c.rule_runs] == ["rewrite"]
    assert c.rule_runs[0].id == "r2"  # 화 안에서 겹치지 않는다
    assert [r.kind for r in ep.rule_runs] == ["write"]  # 고르기 전에는 지금 본문 것 그대로

    _quiet("rewrite", demo, "1", "--adopt")
    p = store.load(demo)
    ep = p.episode(1)
    assert ep.text.startswith("바람결이 멎었다.") and [r.id for r in ep.rule_runs] == ["r2"] and _found(ep, ep.rule_runs[0])
    prev = next(v for v in ep.versions if v.kind == "previous")
    assert [r.id for r in prev.rule_runs] == ["r1"]

    calls = []
    real = regexrules.run
    monkeypatch.setattr(regexrules, "run", lambda *a, **k: calls.append(1) or real(*a, **k))
    pipeline.restore_version(p, 1, prev.id)
    assert calls == []  # 되살린 본문은 이미 규칙을 건 글이다
    assert ep.text.startswith("바람결이 불었다.") and [r.id for r in ep.rule_runs] == ["r1"]


def test_cli_rewrite_yes_adopts_with_runs(demo):
    _on(demo)
    _quiet("write", demo, "1")
    _quiet("rewrite", demo, "1", "--ask", "조용히", "-y")
    ep = store.load(demo).episode(1)
    assert ep.candidate is None and [r.kind for r in ep.rule_runs] == ["rewrite"]


# ---------- 다듬기 · 끊긴 쓰기 ----------

def test_polish_mode_applies_once(demo):
    _on(demo)
    _quiet("write", demo, "1")
    p = store.load(demo)
    runs = []
    text = pipeline.rewrite_episode(LLM, p, 1, RewriteRequest(mode="polish"), [], [], runs)
    assert "⋯" in text and "…" not in text
    assert len(runs) == 1 and runs[0].kind == "polish"  # 다듬기 모드는 polish_episode 만 건다
    assert {c.before for c in runs[0].changes} == {"…"}


def test_polish_fallback_version_is_ruled(demo, monkeypatch):
    _on(demo)
    _quiet("write", demo, "1")
    p = store.load(demo)
    monkeypatch.setattr(pipeline, "polish_tics", lambda old, new: "말줄임으로 끊는 서술이 늘었어요")
    runs = []
    text = pipeline.polish_episode(LLM, p, 1, ruled=runs)  # 끝내 줄지 않아 덜 늘린 판을 낸다
    assert "⋯" in text and len(runs) == 1 and runs[0].kind == "polish"


def test_failed_write_leaves_no_run(demo, monkeypatch):
    _on(demo)
    p = store.load(demo)

    def cut(*a, **k):
        raise pipeline.WriteCut("본문이 출력 길이 한도에 걸려 끊겼어요")
    monkeypatch.setattr(pipeline, "_write", cut)
    runs = []
    with pytest.raises(pipeline.WriteCut):
        pipeline.write_episode(LLM, p, 1, ruled=runs)
    assert runs == []
    monkeypatch.setattr(pipeline, "_write", lambda *a, **k: (_ for _ in ()).throw(ValueError("세 번 실패")))
    with pytest.raises(ValueError):
        pipeline.write_episode(LLM, p, 1, ruled=runs)
    assert runs == []


# ---------- 부분 수정 · AI에게 고치기 ----------

class _Passage:
    """후보 하나를 내는 가짜 LLM."""

    def __init__(self, text):
        self.cand = text

    def json(self, system, prompt, schema, hint=None):
        assert schema is PassageRevision
        return PassageRevision(reply="고쳤어요", candidates=[PassageCandidate(text=self.cand, note="")])


def _written(demo):
    _on(demo)
    _quiet("write", demo, "1")
    p = store.load(demo)
    ep = p.episode(1)
    q = "서윤은 등대 앞에 섰다."
    return p, ep, Selection(start=ep.text.index(q), text=q)


def test_revise_passage_fills_ruled_only_when_asked(demo):
    p, ep, sel = _written(demo)
    rev = pipeline.revise_passage(_Passage("찬 바람이 분다…"), p, 1, sel, "고쳐 줘")
    assert rev.candidates[0].text == "찬 바람이 분다…" and rev.candidates[0].ruled == []
    rev = pipeline.revise_passage(_Passage("찬 바람이 분다…"), p, 1, sel, "고쳐 줘", rules=True)
    c = rev.candidates[0]
    assert c.text == "찬 바람결이 분다⋯" and [x.after for x in c.ruled] == ["바람결", "⋯"]
    assert all(c.text[x.start:x.start + len(x.after)] == x.after for x in c.ruled)  # 자리는 후보 글 안


def test_apply_passage_records_and_undo(demo):
    p, ep, sel = _written(demo)
    rev = pipeline.revise_passage(_Passage("찬 바람이 분다…"), p, 1, sel, "고쳐 줘", rules=True)
    pipeline.record_passage(p, 1, sel, "고쳐 줘", "", rev)
    i = len(p.chat("text:1").messages) - 1
    pipeline.apply_passage(p, 1, i, 0)
    run = ep.rule_runs[-1]
    assert run.kind == "passage" and run.id == "r2" and len(run.changes) == 2 and _found(ep, run)
    done, left = regexrules.undo_run(p, 1, run.id)
    assert len(done) == 2 and left == [] and "찬 바람이 분다…" in ep.text


def test_apply_passage_author_edit_keeps_found_only(demo):
    p, ep, sel = _written(demo)
    rev = pipeline.revise_passage(_Passage("찬 바람이 분다…"), p, 1, sel, "고쳐 줘", rules=True)
    pipeline.record_passage(p, 1, sel, "고쳐 줘", "", rev)
    i = len(p.chat("text:1").messages) - 1
    pipeline.apply_passage(p, 1, i, 0, text="찬 바람결이 분다…")  # 작가가 말줄임을 되돌려 넣었다
    run = ep.rule_runs[-1]
    assert [c.after for c in run.changes] == ["바람결"] and _found(ep, run)

    sel2 = Selection(start=ep.text.index("찬 바람결이 분다…"), text="찬 바람결이 분다…")
    rev = pipeline.revise_passage(_Passage("찬 바람이 분다…"), p, 1, sel2, "고쳐 줘", rules=True)
    pipeline.record_passage(p, 1, sel2, "고쳐 줘", "", rev)
    n_runs = len(ep.rule_runs)
    pipeline.apply_passage(p, 1, len(p.chat("text:1").messages) - 1, 0, text="따뜻한 바람이 분다.")
    assert len(ep.rule_runs) == n_runs  # 찾히는 곳이 없으면 기록을 남기지 않는다


def test_apply_first_records(demo):
    p, ep, sel = _written(demo)
    rev = pipeline.revise_passage(_Passage("찬 바람이 분다…"), p, 1, sel, "고쳐 줘", rules=True)
    pipeline.apply_first(p, 1, sel, "고쳐 줘", rev)
    assert ep.rule_runs[-1].kind == "passage" and _found(ep, ep.rule_runs[-1])


def test_cli_fix_applies_rules(demo, monkeypatch):
    _on(demo)
    _quiet("write", demo, "1")
    monkeypatch.setattr(MockLLM, "json", lambda self, s, pr, schema, hint=None: _Passage("찬 바람이 분다…").json(s, pr, schema))
    out = _quiet("fix", demo, "1", "서윤은 등대 앞에 섰다.", "--ask", "고쳐 줘", "-y")
    assert "규칙으로 2곳 고쳤어요" in out
    ep = store.load(demo).episode(1)
    assert "찬 바람결이 분다⋯" in ep.text and ep.rule_runs[-1].kind == "passage" and _found(ep, ep.rule_runs[-1])


# ---------- 비교 채택 · 재구성 다듬기 ----------

def test_adopt_draft_applies_once(demo, monkeypatch):
    _on(demo)
    _quiet("write", demo, "1")
    p = store.load(demo)
    calls = []
    real = regexrules.run
    monkeypatch.setattr(regexrules, "run", lambda *a, **k: calls.append(a[2]) or real(*a, **k))
    pipeline.adopt_draft(p, 1, "바람이 분다. 서윤은 웃었다.", "mock:x")
    ep = p.episode(1)
    assert calls == ["adopt"] and ep.text == "바람결이 분다. 서윤은 웃었다."
    assert [r.kind for r in ep.rule_runs] == ["adopt"] and ep.rule_runs[0].id == "r2"
    assert [r.kind for r in ep.versions[-1].rule_runs] == ["write"]


def test_compare_pick_goes_through_adopt_draft():
    from canon import research
    assert "pipeline.adopt_draft(" in inspect.getsource(research.pick_compare)


def test_rework_propose_and_accept(home_rules):
    from .test_rebuild import _rebuilt
    from .test_convert import LLM as CLLM

    b = _bundle(RegexRule(**{"in": "본문", "out": "원고", "action": "fix", "comment": "원고"}))
    p, *_ = _rebuilt()
    p.settings.rule_bundles = [b.id]
    rw = pipeline.propose_rework(CLLM, p, 3)
    assert "원고" in rw.text and rw.ruled and all(rw.text[c.start:c.start + len(c.after)] == c.after for c in rw.ruled)
    assert "ruled" not in Rework.model_json_schema()["properties"]
    pipeline.accept_rework(p, 3, rw.text, rw.text, rw.ruled)
    ep = p.episode(3)
    run = ep.rule_runs[-1]
    assert run.kind == "rework" and len(run.changes) == len(rw.ruled) and _found(ep, run)

    p, *_ = _rebuilt()
    p.settings.rule_bundles = [b.id]
    rw = pipeline.propose_rework(CLLM, p, 3)
    pipeline.accept_rework(p, 3, rw.text.replace("원고", "글"), rw.text, rw.ruled)  # 작가가 모두 고쳐 넣었다
    assert p.episode(3).rule_runs == []


@pytest.fixture()
def home_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.delenv("CANON_RULES", raising=False)
    return tmp_path


# ---------- 자동 집필 ----------

def test_autorun_write_and_polish(demo):
    _on(demo)
    run = autorun.start(demo, 1, False, Policy(polish=True), foreground=True)
    assert run.status == "done"  # 경고 규칙 지적(등대 · 섰다)은 멈춤 규칙에 세지 않는다
    ep = store.load(demo).episode(1)
    assert [r.kind for r in ep.rule_runs] == ["auto"] and {c.after for c in ep.rule_runs[0].changes} == {"⋯"}
    assert _found(ep, ep.rule_runs[0])
    prev = next(v for v in ep.versions if v.kind == "previous")
    assert [r.kind for r in prev.rule_runs] == ["auto"] and prev.rule_runs[0].changes[0].after == "바람결"
    assert any(f.origin == "regex" for f in ep.findings)


def test_autorun_back_moves_runs(demo):
    _on(demo)
    run = autorun.start(demo, 6, False, Policy(max_issues=5, review_every=1), foreground=True)
    assert run.status == "paused" and run.applied == [1]
    run = autorun.start(demo, 3, False, Policy(), foreground=True)
    assert run.status == "review" and run.ep == 2
    old = store.load(demo).episode(2).rule_runs
    assert [r.kind for r in old] == ["auto"]
    autorun.resume(demo, rewrite=True, foreground=True)
    ep = store.load(demo).episode(2)
    assert [r.id for r in ep.versions[-1].rule_runs] == [r.id for r in old]  # 지운 본문의 기록은 이전 판으로
    assert [r.kind for r in ep.rule_runs] == ["auto"] and ep.rule_runs[0].id != old[0].id


# ---------- 기록 비우기 · 옮기기 ----------

def test_delete_last_clears_runs(demo):
    _on(demo)
    _quiet("write", demo, "1")
    p = store.load(demo)
    pipeline._delete_last(p, 1, True)
    assert p.episode(1).rule_runs == [] and p.episode(1).text == ""


def test_fork_clear_moves_runs(demo):
    _on(demo)
    _quiet("write", demo, "1")
    p = store.load(demo)
    runs = list(p.episode(1).rule_runs)
    assert branches.fork(p, 1, "clear") == [1]
    ep = p.episode(1)
    assert ep.rule_runs == [] and ep.versions[-1].rule_runs == runs


# ---------- 검수 ----------

def _checked(demo):
    _on(demo)
    _quiet("write", demo, "1")
    return store.load(demo)


def test_check_merges_regex_and_keeps_decisions(demo):
    p = _checked(demo)
    ep = p.episode(1)
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[]))
    reg = [f for f in ep.findings if f.origin == "regex"]
    assert len(reg) == 2 and {f.description for f in reg} == {"등대 경고", "섰다 경고"}
    assert reg[0].current_quote == reg[1].current_quote == "서윤은 등대 앞에 섰다."  # 한 문장에 규칙 둘
    assert all(f.type == "표기" and f.severity == "low" and f.source_episode == 1 for f in reg)
    tower = next(f for f in reg if f.description == "등대 경고")
    assert tower.regex_rule.endswith("/" + TOWER.id) and tower.source_quote == "등대"
    findings.set_status(ep, tower.id, "kept", None, "2026-11-09T00:00:00+00:00")
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[]))
    reg2 = [f for f in ep.findings if f.origin == "regex"]
    assert len(reg2) == 2  # 규칙마다 따로 잇는다 (_match 가 regex_rule 도 본다)
    assert next(f for f in reg2 if f.id == tower.id).status == "kept"
    assert next(f for f in reg2 if f.id != tower.id).regex_rule.endswith("/" + STOOD.id)


def test_check_same_quote_and_scope(demo):
    p = _checked(demo)
    ep = p.episode(1)
    ai = ConsistencyIssue(type="사실", description="등대가 없다", source_quote="설정", current_quote="서윤은 등대 앞에 섰다.")
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[ai]))
    assert [f.origin for f in ep.findings] == ["ai"]  # 모델이 같은 문장을 짚으면 경고 지적은 뺀다

    findings.clear(ep)
    r = ConsistencyReport(episode=1, issues=[ai])
    r._scope = ["\"됐어. 내가 할게.\""]  # 다시 검수 범위 밖이라 AI 지적이 빠진다
    rnd = pipeline.apply_check(p, r)
    assert rnd.outside == 1 and sorted(f.origin for f in ep.findings) == ["regex", "regex"]  # 경고 지적은 거르지 않고 남는다


def test_recheck_regex_without_llm(demo, monkeypatch):
    p = _checked(demo)
    ep = p.episode(1)
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[]))
    tower = next(f for f in ep.findings if f.description == "등대 경고")
    res = pipeline.recheck_finding(None, p, 1, tower.id)  # LLM 을 부르면 None 이라 터진다
    assert res.resolved is False
    ep.text = ep.text.replace("등대", "언덕")
    assert pipeline.recheck_finding(None, p, 1, tower.id).resolved is True
    monkeypatch.setattr(findings, "fix_recheck_targets", lambda e: [tower])
    rep = pipeline.recheck_fixed(None, p, 1)
    assert [(x.id, x.resolved) for x in rep.results] == [(tower.id, True)]


# ---------- 내보내기 ----------

def test_export_rules(demo):
    p = _checked(demo)
    before = p.episode(1).text
    out = publish.export(p, [1], "blank", title=False)
    assert "서윤 씨은 등대" in out["text"] and "서윤 씨은 등대" in out["html"]
    assert "서윤 씨" not in publish.export(p, [1], "raw", title=False)["text"]
    assert publish.export(p, [1], "compact", title=False, drafts={1: "서윤이 왔다."})["text"].startswith("서윤 씨이 왔다.")
    assert p.episode(1).text == before


# ---------- 실험 · 비교 길 ----------

EXPERIMENTS = ("promptlab", "stattrial", "blocktrial", "opening", "cue", "revlab", "research")


def test_experiment_callers_never_rule():
    import importlib
    for name in EXPERIMENTS:
        src = inspect.getsource(importlib.import_module(f"canon.{name}"))
        assert "ruled=" not in src and "rules=True" not in src and "regexrules" not in src, name
    for fn in (pipeline.compare_drafts, pipeline.write_scored, pipeline.play_cues):
        assert "ruled" not in inspect.getsource(fn)


def test_experiment_writes_are_not_ruled(demo, monkeypatch):
    _on(demo)
    p = store.load(demo)
    monkeypatch.setattr(regexrules, "run", lambda *a, **k: pytest.fail("실험 쓰기에 규칙이 걸렸어요"))
    out = pipeline.compare_drafts({"a": LLM}, p, 1)
    assert out["a"].startswith("바람이 불었다.")
    from canon import opening
    assert all(t.startswith("바람이") for t in opening.opening_drafts(LLM, p, 1).values())


# ---------- 두 번 걸면 틀리는 규칙으로 '한 번만 건다' 보기 ----------
# '바람' → '바람바람' 은 다시 걸면 '바람바람바람바람' 이 된다. 위 시험들의 규칙은 두 번 걸어도 같아 두 번 걸기를 잡지 못한다.

TWICE = RegexRule(**{"in": "바람", "out": "바람바람", "action": "fix", "comment": "두 번"})


def _once(text, head):
    return text.startswith(head) and not text.startswith(head + "바람")


def test_once_write_and_import(demo, tmp_path):
    _on(demo, TWICE)
    _quiet("write", demo, "1")
    ep = store.load(demo).episode(1)
    assert _once(ep.text, "바람바람이 불었다.") and len(ep.rule_runs[0].changes) == 1
    f = tmp_path / "in.txt"
    f.write_text("바람이 분다.", encoding="utf-8")
    _quiet("import", demo, "1", str(f))
    assert store.load(demo).episode(1).text == "바람바람이 분다."


def test_once_rewrite_polish_adopt(demo):
    _quiet("write", demo, "1")  # 규칙 없이 쓴 본문
    _on(demo, TWICE)
    _quiet("rewrite", demo, "1", "--ask", "조용히", "-y")
    ep = store.load(demo).episode(1)
    assert _once(ep.text, "바람바람이 멎었다.") and [r.kind for r in ep.rule_runs] == ["rewrite"]

    p = store.load(demo)
    p.episode(1).text = "바람이 불었다. 서윤은 섰다."
    runs = []
    text = pipeline.rewrite_episode(LLM, p, 1, RewriteRequest(mode="polish"), [], [], runs)
    assert _once(text, "바람바람이 불었다") and len(runs) == 1

    pipeline.adopt_draft(p, 1, "바람이 분다.", "mock:x")
    assert p.episode(1).text == "바람바람이 분다."


def test_once_autorun(demo):
    _on(demo, TWICE)
    run = autorun.start(demo, 1, False, Policy(), foreground=True)
    assert run.status == "done"
    ep = store.load(demo).episode(1)
    assert _once(ep.text, "바람바람이 불었다.") and [r.kind for r in ep.rule_runs] == ["auto"]


# ---------- 부분 수정: 규칙을 건 뒤 원문과 견주기 · 자리 ----------

def test_revise_passage_drops_ruled_candidate_equal_to_selection(demo):
    _on(demo, RegexRule(**{"in": "…", "out": ".", "action": "fix", "comment": "말줄임 → 마침표"}))
    _quiet("write", demo, "1")
    p = store.load(demo)
    ep = p.episode(1)
    q = "서윤은 등대 앞에 섰다."
    sel = Selection(start=ep.text.index(q), text=q)
    rev = pipeline.revise_passage(_Passage("서윤은 등대 앞에 섰다…"), p, 1, sel, "다듬어 줘", rules=True)
    assert rev.candidates == [] and "원문과 다른 후보가 없었어요" in rev.reply  # 규칙을 건 후보가 원문과 같다
    assert pipeline.apply_first(p, 1, sel, "다듬어 줘", rev) is None  # '바뀐 내용이 없어요' 로 터지지 않는다
    rev = pipeline.revise_passage(_Passage("서윤은 등대 앞에 섰다…"), p, 1, sel, "다듬어 줘")
    assert [c.text for c in rev.candidates] == ["서윤은 등대 앞에 섰다…"]  # 규칙을 안 걸면 그대로 남는다


@pytest.mark.parametrize("typed", [None, "  \n그는 웃었다."])
def test_apply_passage_lead_space_positions(demo, typed):
    _on(demo, RegexRule(**{"in": " 음", "out": "", "action": "fix", "comment": "음 지우기"}))
    _quiet("write", demo, "1")
    p = store.load(demo)
    ep = p.episode(1)
    q = "서윤은 등대 앞에 섰다."
    sel = Selection(start=ep.text.index(q), text=q)
    rev = pipeline.revise_passage(_Passage("【고칠 부분】\n그는 음 웃었다."), p, 1, sel, "고쳐 줘", rules=True)
    c = rev.candidates[0]
    assert c.text == "그는 웃었다." and [(x.start, x.before) for x in c.ruled] == [(2, " 음")]  # 다듬은 뒤 규칙을 건다
    pipeline.record_passage(p, 1, sel, "고쳐 줘", "", rev)
    pipeline.apply_passage(p, 1, len(p.chat("text:1").messages) - 1, 0, text=typed)
    run = ep.rule_runs[-1]
    assert run.changes[0].start == ep.text.index("그는 웃었다.") + 2
    regexrules.undo_run(p, 1, run.id)
    assert "서윤은 그는 음 웃었다." not in ep.text and "그는 음 웃었다." in ep.text and "바람이 불었다. 그는 음 웃었다." in ep.text


# ---------- 다시 검수: 걸지 못한 경고 규칙은 닫지 않는다 ----------

def test_recheck_regex_skipped_stays_open(demo, monkeypatch):
    p = _checked(demo)
    ep = p.episode(1)
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[]))
    tower = next(f for f in ep.findings if f.description == "등대 경고")
    ep.text = ep.text.replace("등대", "언덕")  # 걸 수 있으면 '풀림' 이 될 본문

    monkeypatch.setattr(regexrules, "_call", lambda *a, **k: (None, "표기"))  # 시간 한도에 걸린 것처럼
    res = pipeline.recheck_finding(None, p, 1, tower.id)
    assert res.resolved is False and "시간 한도" in res.reason and "판정하지 못해" in res.reason
    monkeypatch.setattr(findings, "fix_recheck_targets", lambda e: [tower])
    rep = pipeline.recheck_fixed(None, p, 1)
    assert [(x.id, x.resolved) for x in rep.results] == [(tower.id, False)]
    monkeypatch.undo()

    p.settings.rule_bundles = []  # 묶음을 껐다
    res = pipeline.recheck_finding(None, p, 1, tower.id)
    assert res.resolved is False and res.reason.startswith(regexrules.RULE_GONE)
    pipeline.apply_recheck(p, 1, tower.id, res)
    assert findings.find(ep, tower.id).status == "open"


# ---------- 재구성: 옮긴 본문의 기록 ----------

def test_rebuild_keeps_rule_runs():
    from .test_convert import LLM as CLLM, _short
    from canon.schema import RuleChange, RuleRun

    p = _short(written=8)
    for e in p.episodes:
        if e.text:
            e.rule_runs = [RuleRun(id="r1", kind="write", changes=[
                RuleChange(bundle="b", rule="x", start=0, before=e.text[:1], after=e.text[:1])])]
    prop = pipeline.propose_rebuild(CLLM, p, 200)
    pipeline.apply_rebuild(p, prop, at="2026-10-22T00:00:00+00:00")
    moved = [x for x in prop.episodes if x.use in ("keep", "revise") and x.sources]
    assert moved
    for x in moved:
        ep, src = p.episode(x.number), p.archive.source(x.sources[0])
        assert [r.id for r in ep.rule_runs] == ["r1"] and ep.rule_runs == src.rule_runs
        assert ep.rule_runs[0] is not src.rule_runs[0] and ep.rule_runs[0].changes[0] is not src.rule_runs[0].changes[0]
        ep.rule_runs[0].changes[0].undone = True
        assert src.rule_runs[0].changes[0].undone is False  # 깊은 사본이라 보관한 옛 화는 그대로
