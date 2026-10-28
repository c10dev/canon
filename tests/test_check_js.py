"""검수 화면(static/check.js)의 지적 표시 · 본문 밑줄 · 진행 단계(home.js checkState)가 서버 findings.merge 결과와 맞는지,
화면이 오류 없이 그려지는지. node 가 있을 때만 돈다."""
from canon import findings
from canon.schema import ConsistencyIssue, TextEdit

from .jsvm import dump, episode, needs_node, run_js

Q1 = "도현은 오른손에 남은 흉터를 엄지로 문질렀다."
Q2 = "서윤은 눈앞의 문손잡이를 두 손으로 붙잡았다."
Q3 = "“그만해. 네가 뭘 안다고.”"
Q4 = "도현은 그녀가 눈치채지 못하기를 속으로 빌었다."
TEXT = " ".join([Q1, Q2, Q3, Q4])


def issue(q, t="사실"):
    return ConsistencyIssue(type=t, description=f"{t} 어긋남", source_episode=0, source_quote="설정", current_quote=q)


def session():
    """1회차 4곳 → f1 고침(문장 고침) · f2 그대로 둠 · f3 잘못 짚음 → 2회차가 f2 · f3 · f4 를 다시 짚지 않고 f2 만 짚음."""
    e = episode(1, status="written", text=TEXT)
    findings.merge(e, [issue(Q1), issue(Q2, "동선"), issue(Q3, "말투"), issue(Q4, "시점")], "2026-10-28T10:00:00", "b")
    findings.set_status(e, "f2", "kept", "일부러", "t")
    findings.set_status(e, "f3", "wrong", None, "t")
    e.text = e.text.replace(Q1, "도현은 왼손에 남은 흉터를 엄지로 문질렀다.")
    findings.merge(e, [issue(Q2, "동선")], "2026-10-28T11:00:00", "b")
    return e


@needs_node
def test_flags_and_marks():
    e = session()
    assert [f.status for f in e.findings] == ["fixed", "kept", "wrong", "open"]
    got = run_js(["app.js", "home.js", "check.js"], """(() => {
      const e = data.e;
      const draft = e.text.replace(data.q4, '도현이 시선을 피했다.');
      return {
        flags: e.findings.map((f) => findingFlag(e, f, e.text)),
        changed: findingFlag(e, e.findings[3], draft),
        marks: findingMarks(e, e.text, 'f2').map((r) => [r.key, r.kind, e.text.slice(r.a, r.b)]),
        state: checkState(e),
      };
    })()""", {"e": dump(e), "q4": Q4})
    assert got["flags"] == ["gone", "again", "", "miss"]
    assert got["changed"] == "changed"
    # 열린 지적(f4)과 고른 지적(f2)만 밑줄. 처리한 f3 는 고르지 않았으니 없다
    assert got["marks"] == [["i:f2", "issue sel", Q2], ["i:f4", "issue", Q4]]
    assert got["state"] == {"checked": True, "stale": False, "open": 1, "done": False}


@needs_node
def test_check_state_done_and_stale():
    e = session()
    findings.set_status(e, "f4", "kept", None, "t")
    edited = e.model_copy(deep=True)
    edited.edits.append(TextEdit(id="e1", at="2026-10-28T12:00:00", before="a", after="b"))
    got = run_js(["app.js", "home.js", "check.js"], "[checkState(data[0]), checkState(data[1]), epSteps(data[0]).map((s) => s.done)]",
                 [dump(e), dump(edited)])
    assert got[0]["done"] is True and got[0]["open"] == 0
    assert got[1]["stale"] is True and got[1]["done"] is False
    assert got[2] == [True, True, True, False]


@needs_node
def test_view_check_renders():
    from canon.schema import Meta, Project
    e = session()
    p = Project(meta=Meta(title="t", target_episodes=3), episodes=[e])
    files = ["app.js", "home.js", "branches.js", "style.js", "plot.js", "write.js", "review.js", "chat.js", "passage.js", "rewrite.js",
             "restate.js", "opening.js", "auto.js", "marks.js", "check.js"]
    html = run_js(files, """(() => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'check', '1'];
      const all = viewCheck(1);
      S.chkFilter = 'all'; S.chkTab = 'issues';
      return [all, viewCheck(1)];
    })()""", dump(p))
    open_view, all_view = html
    assert "2회차" in open_view and "열린 지적 1" in open_view and "이번 회차에서 안 짚음" in open_view
    assert 'data-action="setFinding" data-arg="f4:kept"' in open_view
    assert "다시 검수에서 사라짐" in all_view and "다시 나옴 · 결정 그대로" in all_view
