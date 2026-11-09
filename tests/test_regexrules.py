"""정규식 규칙 묶음 (canon/regexrules.py): 저장소, 문법 바꾸기, 검사, 걸기, 되돌리기, 시간 한도.

실행: CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_regexrules.py
"""
import json
import re

import pytest

from canon import regexrules as R
from canon import store
from canon.schema import (ConsistencyReport, ConsistencyReportEn, Episode, EpisodePlot, Finding, PassageCandidate,
                          PassageRevision, PlantSet, Project, RegexRule, Rework, RuleBundle, RuleRun, TextVersion)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.delenv("CANON_RULES", raising=False)
    return tmp_path


def rule(pat, out="", action="fix", **kw) -> RegexRule:
    return RegexRule(**{"in": pat, "out": out, "action": action, **kw})


def project(*bids, text="") -> Project:
    p = Project()
    p.settings.rule_bundles = list(bids)
    plot = EpisodePlot(number=1, act="기", title="1화", summary="", events=[], characters=[], emotional_shift="", ending_hook="")
    p.episodes = [Episode(plot=plot, text=text, status="written")]
    return p


def bundle(name, *rules) -> RuleBundle:
    """검사를 거치지 않고 저장한다 (느린 패턴 시험용)."""
    return R.save(RuleBundle(id=R.uuid.uuid4().hex[:12], name=name, rules=list(rules)))


# ---------- 저장소 ----------

def test_store_crud_versions(home):
    assert R.entries() == [] and R.root() == home / ".rules"
    b = R.create("표기", "메모", [rule(r"\.\.\.", "…", comment="말줄임")])
    path = home / ".rules" / f"{b.id}.json"
    assert path.exists() and b.version == 1 and len(b.versions) == 1
    assert R.exists(b.id) and not R.exists("zz") and not R.exists("../x")
    with pytest.raises(KeyError):
        R.load("0123456789ab")

    b2 = R.update(b.id, "표기 2", "메모", b.rules)  # 규칙 그대로: 새 버전 없음
    assert b2.version == 1 and b2.name == "표기 2"
    b3 = R.update(b.id, "표기 2", "", b.rules + [rule("하였다", action="warn", comment="상투")])
    assert b3.version == 2 and [v["number"] for v in R.versions(b3)] == [2, 1]
    assert R.versions(b3)[0]["added"] == ["상투"] and R.versions(b3)[0]["current"]

    back = R.restore(b.id, 1)
    assert back.version == 3 and len(back.rules) == 1 and back.versions[-1].note == "1번 버전으로 되돌림"
    with pytest.raises(ValueError):
        R.restore(b.id, 1)
    with pytest.raises(KeyError):
        R.restore(b.id, 99)

    s = R.summary(R.load(b.id))
    assert (s["warn"], s["fix"], s["used_by"], s["version"]) == (0, 1, 0, 3)

    (home / ".rules" / "ffffffffffff.json").write_text("{깨짐", encoding="utf-8")
    assert [x.id for x in R.entries()] == [b.id]

    with pytest.raises(ValueError):
        R.create("  ")
    with pytest.raises(ValueError, match="저장할 수 없어요"):
        R.create("나쁨", rules=[rule("(a+)+")])
    R.delete(b.id)
    assert not path.exists()
    with pytest.raises(KeyError):
        R.delete(b.id)


def test_store_env_path(home, tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_RULES", str(tmp_path / "elsewhere"))
    b = R.create("다른 곳")
    assert (tmp_path / "elsewhere" / f"{b.id}.json").exists()


def test_alias_round_trip(home):
    b = R.create("별칭", rules=[rule("a+", "b")])
    raw = json.loads((home / ".rules" / f"{b.id}.json").read_text(encoding="utf-8"))
    assert raw["rules"][0]["in"] == "a+" and "in_" not in raw["rules"][0]
    assert R.load(b.id).rules[0].in_ == "a+"
    assert RegexRule(in_="x").in_ == "x"  # populate_by_name


def test_blank_rule_id_gets_new_id(home):
    """빈 id 는 새 id 로 바꾼다. 두 규칙이 빈 id 를 나눠 쓰면 지적 · 기록이 섞인다."""
    a, b = RegexRule(**{"id": "", "in": "a"}), RegexRule(**{"id": "  ", "in": "b"})
    assert a.id and b.id.strip() and a.id != b.id and len(a.id) == 8
    assert RegexRule(id="keep").id == "keep"
    saved = R.create("빈 id", rules=[RegexRule.model_validate({"id": "", "in": "x", "action": "warn"}),
                                     RegexRule.model_validate({"id": "", "in": "y", "action": "warn"})])
    ids = [r.id for r in R.load(saved.id).rules]
    assert all(ids) and len(set(ids)) == 2


def test_cli_list_counts_export_apart(home, capsys):
    from canon.cli import main

    R.create("셈", rules=[rule("a", "b"), rule("c", "d", type="export"), rule("e", action="warn")])
    R.create("내보내기 없음", rules=[rule("a", "b")])
    main(["rules"])
    out = capsys.readouterr().out
    assert "경고 1 · 고침 1 · 내보내기 1" in out and "경고 0 · 고침 1  켠 작품" in out


def test_used_by(home):
    b = R.create("켠 묶음")
    for name, on in (("a", [b.id]), ("b", [])):
        (home / name).mkdir()
        p = project(*on)
        (home / name / "project.json").write_text(p.model_dump_json(), encoding="utf-8")
    assert R.used_by(b.id) == ["a"] and R.summary(R.load(b.id))["used_by"] == 1


# ---------- 문법 ----------

def test_convert_in():
    assert R.convert_in(r"(?<y>\d+)-\k<y>") == r"(?P<y>\d+)-(?P=y)"
    assert R.convert_in(r"(?<=a)(?<!b)c") == r"(?<=a)(?<!b)c"
    assert R.convert_in(r"\(?<n>x") == r"\(?<n>x"
    assert R.convert_in(r"[(?<q>]") == r"[(?<q>]"
    assert R.convert_in(r"[\]](?<z>a)") == r"[\]](?P<z>a)"


def test_convert_in_literal_brace():
    """반복이 아닌 { 는 JavaScript 처럼 글자로 읽는다 (Python 3.14 는 {,3} 을 {0,3} 으로 읽는다)."""
    assert re.sub(R.convert_in("a{,3}"), "X", "aa{,3}") == "aX"
    assert re.sub(R.convert_in("{x}"), "X", "a{x}b") == "aXb"
    assert re.sub(R.convert_in("a{2}"), "X", "aaa") == "Xa"  # 반복은 그대로
    assert R.convert_in("a{2,}b{1,3}[{]") == "a{2,}b{1,3}[{]"
    assert R.convert_in(r"\{a}") == r"\{a}"
    assert R.validate(rule("a{,3}")) == []


def test_flags():
    assert R.flags("g") == (0, True)
    assert R.flags("") == (0, False)
    f, g = R.flags("imsud")
    assert f == re.I | re.M | re.S and not g


def sub(out, pat, text, count=0):
    rx = re.compile(R.convert_in(pat))
    return rx.sub(R.to_python(out, rx), text, count=count)


def test_to_python_basic():
    assert sub("[$1]", r"(\d)", "a1b2") == "a[1]b[2]"
    assert sub("<$&>", "b", "abc") == "a<b>c"
    assert sub("$$", "b", "abc") == "a$c"
    assert sub("$<x>!", r"(?<x>b)", "abc") == "ab!c"
    assert sub("{{data}}{{data}}", "b", "abc") == "abbc"
    assert sub("x$ny", "b", "abc") == "ax\nyc"
    assert sub("$$n", "b", "abc") == "a$\nc"  # $n 을 먼저 줄바꿈으로 (RisuAI 와 같다)
    assert sub(r"\1", r"(b)", "abc") == r"a\1c"  # 역슬래시는 글자 그대로


def test_to_python_js_edges():
    assert sub("[$`|$']", "b", "abc") == "a[a|c]c"
    assert sub("$<x>", "b", "abc") == "a$<x>c"  # 이름 붙은 묶음이 없으면 글자 그대로
    assert sub("[$<nope>]", r"(?<x>b)", "abc") == "a[]c"  # 없는 이름은 빈 글
    assert sub("$12", r"(b)", "abc") == "ab2c"  # 묶음 1개: 1번 + '2'
    pat12 = "".join(f"({c})" for c in "abcdefghijkl")
    assert sub("$12", pat12, "abcdefghijkl") == "l"
    assert sub("$0$2", r"(b)", "abc") == "a$0$2c"  # 없는 번호는 글자 그대로
    assert sub("[$2]", r"(b)|(z)", "abc") == "a[]c"  # 맞지 않은 묶음은 빈 글
    assert sub("$", "b", "abc") == "a$c" and sub("$x", "b", "abc") == "a$xc"


def test_validate():
    ok = R.validate(rule(r"\.{3,}", "…"))
    assert ok == []
    assert R.validate(rule("", action="warn")) == []  # 빈 in 은 걸지 않으므로 막지 않는다

    def errs(**kw):
        r = rule(kw.pop("pat", "a"), **kw)
        out = R.validate(r)
        assert out and all(e.startswith("이 정규식은 저장할 수 없어요: ") for e in out)
        return " ".join(out)

    assert "문법" in errs(pat="(a")
    assert "반복 횟수가 너무 커요" in errs(pat="a{4294967296}")  # OverflowError 도 저장을 막는 이유로 (500 이 아니다)
    assert "y" in errs(flag="gy") and "v" in errs(flag="v") and "x" in errs(flag="gx")
    assert "꺾쇠" in errs(flag="<order 1>")
    assert "@@" in errs(out="@@move_top")
    assert "500" in errs(pat="a" * 501)
    assert "내보내기" in errs(type="export", action="warn")
    for pat in ("(a+)+", "(a*)*", "(a|a)*", r"(\w+\s?)+", "(a{2,})+"):
        assert "반복 안에" in errs(pat=pat), pat
    for pat in ("a++", "a*+", "a{2}+", r"\A", r"a\Z", "(?>a)", "(?P<x>a)", "(?P=x)"):
        assert "Python에만 있는 문법은 쓸 수 없어요: " in errs(pat=pat), pat
    assert "[가-힣]" in errs(pat=r"\p{L}+") and r"[^\W\d_]" in errs(pat=r"\p{Script=Hangul}")
    for pat in ("(a{2,3})+", "(?:ab)+", "a+?b", "(x|y)+", "(?<n>a)\\k<n>", "(?<=ab|cd)e", "[a+]+"):
        assert R.validate(rule(pat)) == [], pat


def test_notices():
    assert R.notices(rule("a", "{{char}}")) == ["바꿀 글의 {{…}}는 풀지 않고 글자 그대로 넣어요"]
    assert R.notices(rule("a", "{{data}}")) == []


# ---------- 걸기 ----------

def test_run_order_and_record(home):
    b1 = R.create("하나", rules=[rule(r"\.\.\.", "…", comment="말줄임"), rule("x", "y", enabled=False),
                                 rule("z", "Z", type="export"), rule("하였다", action="warn")])
    b2 = R.create("둘", rules=[rule("…", "⋯", comment="가운데"), rule("a", "A", flag="")])
    p = project(b1.id, "0123456789ab", b2.id)  # 지워진 묶음 id 는 건너뛴다
    assert R.missing(p) == ["0123456789ab"] and [b.name for b in R.bundles_of(p)] == ["하나", "둘"]
    text, run = R.run(p, "a... x z a...", "write")
    assert text == "A⋯ x z a⋯"  # 앞 규칙 결과에 뒤 규칙, g 없음은 첫 자리만, 꺼진 · 내보내기 · 경고 규칙은 안 걸림
    assert run.kind == "write" and run.id == "" and run.skipped == "" and run.at
    # 뒤 규칙이 앞 규칙이 바꾼 곳을 다시 바꾸면 바뀐 곳 하나로 합치고 뒤 규칙 것으로 둔다. 목록은 자리 순서다
    assert [(c.name, c.bundle, c.rule, c.before, c.after) for c in run.changes] == [
        ("", b2.id, b2.rules[1].id, "a", "A"), ("말줄임 · 가운데", b2.id, b2.rules[0].id, "...", "⋯"),
        ("말줄임 · 가운데", b2.id, b2.rules[0].id, "...", "⋯")]
    for c in run.changes:  # 자리는 마지막 본문 안 자리
        assert text[c.start:c.start + len(c.after)] == c.after

    same, none = R.run(p, "변화 없음", "write")
    assert (same, none) == ("변화 없음", None)
    assert R.export_text(p, "z z") == "Z Z"


def test_no_worker_without_bundles(home):
    R.shutdown()
    assert R.run(project(), "a... b", "write") == ("a... b", None)
    assert R.hits(project(), "a", 1) == [] and R.export_text(project(), "a") == "a"
    b = R.create("경고만", rules=[rule("a", action="warn")])
    assert R.run(project(b.id), "a", "write") == ("a", None)
    assert not R.worker_alive()


def test_undo_change_and_run(home):
    b = R.create("묶음", rules=[rule("X", "YY", comment="길게"), rule("a", "bbb", comment="앞")])
    p = project(b.id)
    ep = p.episodes[0]
    ep.text, run = R.run(p, "a or X then X", "write")
    assert ep.text == "bbb or YY then YY"
    ep.rule_runs = R.add_runs(ep.rule_runs, [run])
    assert run.id == "r1"
    assert [c.after for c in run.changes] == ["bbb", "YY", "YY"]  # 자리 순서
    c = R.undo_change(p, 1, "r1", 2)  # 두 번째 X: 뒤 규칙이 앞에서 글을 늘린 만큼 밀린 자리
    assert c.undone and ep.text == "bbb or YY then X"
    with pytest.raises(ValueError):
        R.undo_change(p, 1, "r1", 2)
    with pytest.raises(KeyError):
        R.undo_change(p, 1, "r9", 0)
    done, left = R.undo_run(p, 1, "r1")
    assert ep.text == "a or X then X" and len(done) == 2 and left == []
    assert all(c.undone for c in run.changes) and len(ep.rule_runs[0].changes) == 3  # 기록은 지우지 않는다
    with pytest.raises(ValueError, match="이미"):
        R.undo_run(p, 1, "r1")


def test_undo_overlapping_rules(home):
    b = R.create("겹침", rules=[rule(r"\.\.\.", "…"), rule("…", "⋯")])
    p = project(b.id)
    ep = p.episodes[0]
    ep.text, run = R.run(p, "앞... 가운데… 끝", "write")
    assert ep.text == "앞⋯ 가운데⋯ 끝" and [(c.before, c.after) for c in run.changes] == [("...", "⋯"), ("…", "⋯")]
    ep.rule_runs = R.add_runs([], [run])
    R.undo_change(p, 1, run.id, 0)  # 합친 곳 하나만 되돌려도 걸기 전 글이 돌아온다
    assert ep.text == "앞... 가운데⋯ 끝"
    done, left = R.undo_run(p, 1, run.id)
    assert ep.text == "앞... 가운데… 끝" and len(done) == 1 and not left


def test_undo_deleting_rule_and_author_edit(home):
    b = R.create("지우기", rules=[rule(r" +(?=[.,])", ""), rule("하였다", "했다")])
    p = project(b.id)
    ep = p.episodes[0]
    ep.text, run = R.run(p, "그가 하였다 . 그녀도 하였다 , 끝", "write")
    assert ep.text == "그가 했다. 그녀도 했다, 끝"
    ep.rule_runs = R.add_runs([], [run])
    ep.text = ep.text.replace("그녀도 했다", "그녀도 웃다")  # 작가가 같은 자리를 고침 (글 길이는 같게: 지우기 자리는 locate 로 찾지 못한다)
    done, left = R.undo_run(p, 1, run.id)
    assert [c.after for c in left] == ["했다"] and len(done) == 3
    assert ep.text == "그가 하였다 . 그녀도 웃다 , 끝"

    ep.text = "짧다"
    ep.rule_runs = R.add_runs(ep.rule_runs, [RuleRun(changes=[R.RuleChange(bundle=b.id, rule="x", start=99, before=" ", after="")])])
    with pytest.raises(ValueError, match="되돌릴 자리"):
        R.undo_change(p, 1, "r2", 0)


def test_finalized_undo_keeps_final_text(home):
    b = R.create("묶음", rules=[rule("a", "b")])
    p = project(b.id)
    ep = p.episodes[0]
    ep.text, run = R.run(p, "aaa", "write")
    ep.rule_runs = R.add_runs([], [run])
    ep.status = "finalized"
    R.undo_change(p, 1, run.id, 0)
    assert ep.final_text == "bbb" and ep.text == "abb"


def test_add_runs_keep():
    runs = R.add_runs([], [RuleRun() for _ in range(R.RULE_RUN_KEEP + 5)])
    assert len(runs) == R.RULE_RUN_KEEP and runs[-1].id == f"r{R.RULE_RUN_KEEP + 5}"
    more = R.add_runs(runs, [RuleRun()])
    assert more[-1].id == f"r{R.RULE_RUN_KEEP + 6}"


# ---------- 경고 ----------

def test_hits(home):
    b = R.create("경고", rules=[rule("하였다", action="warn", comment="상투"), rule("그", action="warn"),
                                rule("끝", "끝!", action="fix")])
    p = project(b.id)
    text = "그는 하였다. 다시 하였다 하였다.\n그녀가 왔다."
    out = R.hits(p, text, 3)
    by = {(i.regex_rule.split("/")[1], i.current_quote) for i in out}
    r1, r2 = b.rules[0].id, b.rules[1].id
    assert by == {(r1, "그는 하였다."), (r1, "다시 하였다 하였다."), (r2, "그는 하였다."), (r2, "그녀가 왔다.")}
    x = next(i for i in out if i.regex_rule == f"{b.id}/{r1}")
    assert (x.type, x.severity, x.origin, x.description, x.source_quote, x.source_episode) == ("표기", "low", "regex", "상투", "하였다", 3)
    assert {i.description for i in out if i.regex_rule.endswith(r2)} == {"정규식 규칙에 걸렸어요"}
    only = R.hits(p, text, 3, only=f"{b.id}/{r2}")
    assert {i.regex_rule for i in only} == {f"{b.id}/{r2}"}
    Finding(**x.model_dump(), id="f1")  # 지적으로 옮길 수 있다


def test_hits_strict(home):
    """strict=True 는 걸지 못한 것(없는 규칙)을 RuleSkipped 로 알리고, 걸었는데 맞은 곳이 없으면 빈 목록이다."""
    b = R.create("경고", rules=[rule("하였다", action="warn"), rule("끝", action="warn", enabled=False)])
    p = project(b.id)
    key = f"{b.id}/{b.rules[0].id}"
    assert R.hits(p, "했다.", 1, only=key, strict=True) == []
    assert len(R.hits(p, "하였다.", 1, only=key, strict=True)) == 1
    for q, proj in ((f"{b.id}/zzzz", p), (f"{b.id}/{b.rules[1].id}", p), (key, project()), ("0123456789ab/x", p)):
        assert R.hits(proj, "하였다.", 1, only=q) == []  # 기본은 예전처럼 빈 목록
        with pytest.raises(R.RuleSkipped, match="찾을 수 없어요"):
            R.hits(proj, "하였다.", 1, only=q, strict=True)
    assert R.hits(project(), "하였다.", 1, strict=True) == []  # only 없이 켠 묶음이 없으면 맞은 곳 없음


def test_trial():
    res = R.trial([rule("a", "b"), rule("b", action="warn", comment="비"), rule("c", "C", type="export")], "abc")
    assert res["text"] == "bbc" and len(res["changes"]) == 1 and res["skipped"] == ""
    assert {h["current_quote"] for h in res["hits"]} == {"bbc"} and res["exported"] == "bbC"


# ---------- 시간 한도 ----------

def test_time_limit(home, monkeypatch, caplog):
    slow = bundle("느린 묶음", rule("(a+)+$", "x"))  # 검사를 거치지 않은 겹친 반복
    fast = bundle("빠른 묶음", rule("b", "B"))
    p = project(fast.id, slow.id)
    monkeypatch.setattr(R, "TIME_LIMIT", 0.5)
    text = "b" + "a" * 40 + "!"
    with caplog.at_level("WARNING", logger="canon"):
        out, run = R.run(p, text, "auto")
    assert out == text and run.changes == [] and run.skipped == "느린 묶음" and run.kind == "auto"
    assert "느린 묶음" in caplog.text
    assert not R.worker_alive()  # 한도를 넘은 일꾼은 버린다
    assert R.hits(project(slow.id), text, 1) == []
    slow.rules[0].action = "warn"
    R.save(slow)
    assert R.hits(project(slow.id), text, 1) == []
    with pytest.raises(R.RuleSkipped, match="시간 한도"):  # strict 는 시간 초과를 '맞은 곳 없음' 과 가른다
        R.hits(project(slow.id), text, 1, only=f"{slow.id}/{slow.rules[0].id}", strict=True)
    # 다음 걸기는 새 일꾼으로 된다
    assert R.run(project(fast.id), "bb", "write")[0] == "BB" and R.worker_alive()


# ---------- 스키마 ----------

def test_old_project_loads():
    p = Project.model_validate({"meta": {"title": "옛"}, "settings": {"show_numbers": True}})
    assert p.settings.rule_bundles == []
    ep = Episode.model_validate({"plot": {"number": 1, "act": "기", "title": "t", "summary": "", "events": [], "characters": [],
                                               "emotional_shift": "", "ending_hook": ""}})
    assert ep.rule_runs == [] and TextVersion(id="v").rule_runs == []
    assert PassageCandidate(text="a").ruled == [] and Rework(text="a").ruled == []


NEW_FIELDS = ("ruled", "regex_rule", "rule_runs", "rule_bundles", "표기", '"regex"')


@pytest.mark.parametrize("model", [ConsistencyReport, PlantSet, ConsistencyReportEn, PassageRevision, Rework])
def test_llm_schemas_unchanged(model):
    s = json.dumps(model.model_json_schema(), ensure_ascii=False)
    assert not [f for f in NEW_FIELDS if f in s]
    assert '"origin"' not in s  # 프로그램 칸은 응답 형식에 없다


def test_no_response_schema_has_new_fields():
    from . import test_schema_nodict as t

    for name in t._response_names():
        s = json.dumps(t._model(name).model_json_schema(), ensure_ascii=False)
        assert not [f for f in NEW_FIELDS if f in s], name


def test_undo_rule_overlapping_from_before(home):
    b = R.create("앞에서 겹침", rules=[rule("ab", "abab"), rule("ba", ""), rule("y", "Y")])
    p = project(b.id)
    ep = p.episodes[0]
    ep.text, run = R.run(p, "xx ab yy", "write")
    # 뒤 규칙이 앞 규칙 글 안의 'ba' 를 지워 'ab' 로 돌아왔다: 합치면 전후 글이 같으므로 바뀐 곳에서 뺀다
    assert ep.text == "xx ab YY" and [(c.start, c.before, c.after) for c in run.changes] == [(6, "y", "Y"), (7, "y", "Y")]
    ep.rule_runs = R.add_runs([], [run])
    R.undo_run(p, 1, run.id)
    assert ep.text == "xx ab yy"
    assert R.run(project(b.id), "ab", "write") == ("ab", None)


def _undo_all(rules: list[RegexRule], text: str, order=None):
    """규칙을 걸고 한 번 전체를 되돌린다. (건 글, 기록, 되돌린 글, 남긴 곳).
    order 를 주면 바뀐 곳을 그 차례(random.Random)로 섞어 하나씩 되돌린다."""
    b = bundle("겹침", *rules)
    p = project(b.id)
    ep = p.episodes[0]
    ep.text, run = R.run(p, text, "write")
    got = ep.text
    if run is None or not got:  # 다 지운 본문은 되돌리기 화면에 오지 않는다 (본문이 없는 화)
        return got, run, text, []
    ep.rule_runs = R.add_runs([], [run])
    if order is None:
        _, left = R.undo_run(p, 1, run.id)
        return got, run, ep.text, left
    ks = list(range(len(run.changes)))
    order.shuffle(ks)
    for k in ks:
        R.undo_change(p, 1, run.id, k)
    return got, run, ep.text, []


@pytest.mark.parametrize("rules, text, got", [
    ([rule(r"(?<=\.) (?=\.)", ""), rule(r"\.{3}", "…")], "그래. . . 알았어", "그래… 알았어"),
    ([rule("d", "D"), rule("bcDe", "X")], "abcdeD", "aXD"),
    ([rule("b", ""), rule("ac", "Z")], "abc", "Z"),
])
def test_undo_run_overlap_repros(home, rules, text, got):
    """뒤 규칙이 앞 규칙이 바꾼 곳과 겹치게 맞아도 한 번 전체 되돌리기가 걸기 전 글을 그대로 돌려준다."""
    out, run, back, left = _undo_all(rules, text)
    assert out == got and back == text and left == []
    assert len(run.changes) == 1 and run.changes[0].before != run.changes[0].after


def test_undo_change_merged_single(home):
    """합친 곳 하나 되돌리기도 걸기 전 글을 돌려준다. 이름은 두 규칙 이름을 잇는다."""
    b = R.create("합침", rules=[rule("d", "D", comment="대문자"), rule("bcDe", "X", comment="묶기"), rule("q", "Q", comment="대문자")])
    p = project(b.id)
    ep = p.episodes[0]
    ep.text, run = R.run(p, "abcdeD q", "write")
    assert ep.text == "aXD Q"
    assert [(c.name, c.rule, c.start, c.before, c.after) for c in run.changes] == [
        ("대문자 · 묶기", b.rules[1].id, 1, "bcde", "X"), ("대문자", b.rules[2].id, 4, "q", "Q")]
    ep.rule_runs = R.add_runs([], [run])
    R.undo_change(p, 1, run.id, 0)
    assert ep.text == "abcdeD Q"
    R.undo_change(p, 1, run.id, 1)
    assert ep.text == "abcdeD q"


def test_undo_run_property(home):
    """여러 규칙 짝 · 글에서 한 번 전체 되돌리기는 늘 걸기 전 글을 돌려주고, 바뀐 곳은 마지막 본문 자리에 있다."""
    import random

    rnd = random.Random(6)
    pats = ["a", "b", "ab", "ba", "a+", "b?a", "(?<=a)", "(?=b)", "c", "abc", "[ab]{2}", "^", "$", " ", "  +", "(?<=\\.) "]
    outs = ["", "x", "ab", "a", "$&$&", "[$&]", "b", "…"]
    for _ in range(60):
        rules = [rule(rnd.choice(pats), rnd.choice(outs), flag=rnd.choice(["g", "g", ""])) for _ in range(rnd.randint(2, 4))]
        text = "".join(rnd.choice("abc. ") for _ in range(rnd.randint(1, 14)))
        out, run, back, left = _undo_all(rules, text)
        desc = ([(r.in_, r.out, r.flag) for r in rules], text)
        assert back == text and left == [], desc
        assert _undo_all(rules, text, rnd)[2] == text, desc  # 하나씩 아무 차례로 되돌려도 같다
        if run:
            starts = [c.start for c in run.changes]
            assert starts == sorted(starts), desc
            for c in run.changes:
                assert out[c.start:c.start + len(c.after)] == c.after, desc
