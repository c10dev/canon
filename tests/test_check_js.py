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
             "restate.js", "opening.js", "auto.js", "marks.js", "check.js", "flow.js"]
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


# ---------- 심각도 순서 · 딸린 지적 · 회차 비교 · 비슷한 문장 · 고치는 창 ----------

def rich_session():
    """1회차 f1~f3 → f2 를 작가가 치명으로, f1 고침안 묶음을 넣고 이 지적만 다시 검수로 풀림 + 딸린 지적 f4."""
    from canon.schema import FindingRecheck, FixOption, FixPatch
    e = episode(1, status="written", text=TEXT)
    findings.merge(e, [issue(Q1), issue(Q2, "동선"), issue(Q3, "말투")], "2026-10-28T10:00:00", "b")
    e.findings[2].severity = "low"
    findings.set_severity(e, "f2", "crit", "t")
    e.findings[0].fixes = [FixOption(label="왼손으로", text="도현은 왼손에 남은 흉터를 감췄다.",
                                     extra=[FixPatch(quote=Q4, replacement="도현은 속으로 빌었다.", reason="맞춤")])]
    new = "도현은 왼손에 남은 흉터를 감췄다."
    e.text = e.text.replace(Q1, new)
    e.edits.append(TextEdit(id="e1", at="2026-10-28T10:30:00", source="fix", group="x1", before=Q1, after=new))
    e.findings[0].fix_group = "x1"
    findings.settle(e, e.findings[0], FindingRecheck(resolved=True, reason="풀림", new_issues=[issue(new, "인물 정보")]), "2026-10-28T10:31:00")
    return e


@needs_node
def test_order_rounds_near_and_fix_helpers():
    e = rich_session()
    e2 = episode(1, status="written", text=TEXT)
    findings.merge(e2, [issue(Q1), issue(Q2, "동선")], "2026-10-28T10:00:00", "b")
    e2.text = e2.text.replace(Q1, "도현은 오른손의 흉터를 엄지로 오래 문질렀다.")
    findings.merge(e2, [issue(Q2, "동선"), issue(Q3, "말투")], "2026-10-28T11:00:00", "b")
    got = run_js(["app.js", "home.js", "chat.js", "passage.js", "check.js"], """(() => {
      const [e, e2] = data;
      const near = nearQuote(e2.text, e2.findings[0].current_quote);
      return {
        order: findingOrder(e.findings).map((f) => f.id),
        flag: findingFlag(e, e.findings[0], e.text),
        round: roundChanges(e2, 2),
        near: near && e2.text.slice(near.a, near.b),
        none: nearQuote(e2.text, '전혀 다른 문장이 여기에 있다.'),
        marks: findingMarks(e2, e2.text, 'f1').map((r) => r.kind),
        missing: fixMissing(e.text, e.findings[0], e.findings[0].fixes[0], []),
        skipped: fixMissing(e.text.replace(data[2], ''), e.findings[0], e.findings[0].fixes[0], [0]),
        applied: fixApplied(e, e.findings[0]),
        state: checkState(e),
      };
    })()""", [dump(e), dump(e2), Q4])
    # 치명 f2 → 보통 f1 → 그 아래 딸린 f4 → 사소 f3
    assert got["order"] == ["f2", "f1", "f4", "f3"]
    assert got["flag"] == "one"
    assert got["round"] == {"f3": "new", "f2": "again", "f1": "gone"}
    assert got["near"] == "도현은 오른손의 흉터를 엄지로 오래 문질렀다." and got["none"] is None
    assert got["marks"] == ["issue sel near", "issue", "issue"]
    assert got["missing"] == [Q1] and got["skipped"] == [Q1]  # 지적 문장이 이미 바뀌었고, 뺀 딸린 곳은 보지 않는다
    assert got["applied"] is True
    # 이 지적만 다시 검수로 풀린 고침안 묶음은 '검수 뒤 고침'으로 세지 않는다
    assert got["state"] == {"checked": True, "stale": False, "open": 3, "done": False}


@needs_node
def test_check_view_and_fix_panel_render():
    from canon.schema import FixOption, FixPatch, Meta, Project
    e = episode(1, status="written", text=TEXT)
    findings.merge(e, [issue(Q1), issue(Q2, "동선")], "2026-10-28T10:00:00", "b")
    findings.set_severity(e, "f1", "crit", "t")
    e.findings[0].fixes = [FixOption(label="왼손으로", text="도현은 왼손에 남은 흉터를 감췄다.",
                                     extra=[FixPatch(quote=Q4, replacement="도현은 속으로 빌었다.", reason="맞춤")])]
    findings.new_version(e)  # 결정한 지적이 없으니 모두 지워지고 회차에 새 판 표시
    findings.merge(e, [issue(Q1), issue(Q2, "동선")], "2026-10-28T11:00:00", "b")
    findings.set_severity(e, "f1", "crit", "t")
    e.findings[0].fixes = [FixOption(label="왼손으로", text="도현은 왼손에 남은 흉터를 감췄다.",
                                     extra=[FixPatch(quote=Q4, replacement="도현은 속으로 빌었다.", reason="맞춤")])]
    p = Project(meta=Meta(title="t", target_episodes=3), episodes=[e])
    files = ["app.js", "home.js", "branches.js", "style.js", "plot.js", "write.js", "review.js", "chat.js", "passage.js", "rewrite.js",
             "restate.js", "opening.js", "auto.js", "marks.js", "check.js", "flow.js"]
    got = run_js(files, """(() => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'check', '1'];
      const view = viewCheck(1);
      S.chkRound[1] = 2;
      const round = viewCheck(1);
      S.fixSkip['1:f1:0'] = [0];
      return { view, round, panel: fixPanel(1, 'f1'), skipped: fixPanel(1, 'f1'), closed: (ep(1).findings[1].status = 'kept', fixPanel(1, 'f2')) };
    })()""", dump(p))
    v = got["view"]
    assert "새 판" in v and 'data-action="chkRound" data-arg="2"' in v
    assert v.index('data-arg="f1"') < v.index('data-arg="f2"') and '<span class="chip crit">치명</span>' in v
    assert 'data-action="setSeverity" data-arg="f1:low"' in v and "처리 기록" in v
    assert "2회차가 바꾼 지적" in got["round"] and "새로 나옴" in got["round"]
    assert "2곳 적용" not in got["skipped"] and "적용" in got["skipped"]
    assert "AI 고침안 1개" in got["panel"] and "이 화의 딸린 곳 1" in got["panel"]
    assert "근거 쪽이 틀렸어요" in got["panel"] and 'data-action="setFinding" data-arg="f1:wrong"' in got["panel"]
    assert "다시 열기" in got["closed"]


@needs_node
def test_fix_batch_view():
    """고침안 한꺼번에: 지적 목록 위 띠(받기 · 검토), 검토 화면의 고르기 · 같은 문장 겹침 표시 · 넣을 수 없는 지적, 서버 fix_targets 와 같은 셈."""
    from canon import pipeline
    from canon.schema import FixOption, FixPatch, Meta, Project
    e = episode(1, status="written", text=TEXT)
    findings.merge(e, [issue(Q1), issue(Q2, "동선"), issue(Q3, "말투"), issue("본문에 없는 문장.", "시점")], "2026-10-28T10:00:00", "b")
    p = Project(meta=Meta(title="t", target_episodes=3), episodes=[e])
    files = ["app.js", "home.js", "branches.js", "style.js", "plot.js", "write.js", "review.js", "chat.js", "passage.js", "rewrite.js",
             "restate.js", "opening.js", "auto.js", "marks.js", "check.js", "flow.js"]
    before = run_js(files, """(() => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'check', '1'];
      return { view: viewCheck(1), need: fbNeed(ep(1), ep(1).text).map((f) => f.id) };
    })()""", dump(p))
    assert before["need"] == pipeline.fix_targets(e) == ["f1", "f2", "f3"]
    assert 'data-action="fixAll" data-arg="1"' in before["view"] and "열린 지적 3개 고침안 받기" in before["view"]
    assert 'data-action="fbOpen"' not in before["view"]  # 받은 고침안이 없으면 검토 버튼도 없다

    e.findings[0].fixes = [FixOption(label="왼손으로", text="도현은 왼손에 남은 흉터를 감췄다."),
                           FixOption(label="뒤까지", text="도현은 흉터를 감췄다.", extra=[FixPatch(quote=Q2, replacement="서윤은 문을 붙잡았다.", reason="맞춤")])]
    e.findings[1].fixes = [FixOption(label="한 손으로", text="서윤은 문손잡이를 한 손으로 붙잡았다.")]
    e.findings[2].fixes = [FixOption(label="옛 안", text="x", extra=[FixPatch(quote="본문에 없는 곳.", replacement="y")])]  # 본문이 바뀌어 넣을 수 없음
    p = Project(meta=Meta(title="t", target_episodes=3), episodes=[e])
    got = run_js(files, """(() => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'check', '1'];
      render = () => {};  // 동작이 다시 그리기를 부른다 (이 시험은 화면 함수를 직접 부른다)
      const list = viewCheck(1);
      S.fbOpen = 1;
      const empty = viewCheck(1);
      actions.fbAll('1');
      const all = viewCheck(1);
      actions.fbOpt('f1:1');  // f1 의 둘째 안은 f2 문장도 바꾼다 → f2 에 겹침 표시
      const clash = fbClash(1, ep(1), ep(1).text, findingOrder(ep(1).findings.filter((f) => f.status === 'open')));
      const clashView = viewCheck(1);
      actions.fbPick('f2');
      return { list, empty, all, clash: Object.fromEntries(Object.entries(clash).map(([k, v]) => [k, v.id])), clashView,
               after: viewCheck(1), on: Object.keys(S.fbOn).sort(), need: fbNeed(ep(1), ep(1).text).map((f) => f.id) };
    })()""", dump(p))
    assert got["need"] == pipeline.fix_targets(e) == ["f3"]
    assert 'data-action="fbOpen" data-arg="1">한꺼번에 검토 · 2' in got["list"]
    assert "고침안 한꺼번에 검토" in got["empty"] and "고른 0개 넣기" in got["empty"] and 'data-action="fbApply" disabled' in got["empty"]
    assert "아직 고침안이 없어요" not in got["empty"] and "고침안을 받은 뒤 본문이 바뀌었어요" in got["empty"]  # f3
    assert "지적한 문장을 지금 본문에서 찾을 수 없어요" in got["empty"]  # f4
    assert "남은 1개 고침안 받기" in got["empty"]
    assert "고른 2개 넣기" in got["all"]  # 넣을 수 있는 f1 · f2 만
    assert got["clash"] == {"f2": "f1"} and "같은 문장을 바꿔요" in got["clashView"]
    assert got["on"] == ["1:f1"] and "고른 1개 넣기" in got["after"] and "같은 문장을 바꿔요" not in got["after"]


CHK_FILES = ["app.js", "home.js", "branches.js", "style.js", "plot.js", "write.js", "review.js", "chat.js", "passage.js", "rewrite.js",
             "restate.js", "opening.js", "auto.js", "marks.js", "check.js", "flow.js"]
CHK_SETUP = """S.project = data; S.name = 't'; S.route = ['p', 't', 'check', '1'];
  render = () => {};
  const toasts = [];
  toast = (m, err, opt) => toasts.push([m, !!err, ((opt || {}).actions || []).map((a) => a.label)]);"""


def check_project():
    from canon.schema import Meta, Project
    return dump(Project(meta=Meta(title="t", target_episodes=3), episodes=[session()]))


@needs_node
def test_note_draft_kept_until_saved():
    """메모 초안은 지적마다 남는다. 저장이 실패하면 초안을 그대로 두고 저장했다고 알리지 않는다. 성공하면 그 지적의 초안만 지운다."""
    got = run_js(CHK_FILES, """(async () => {
      %s
      const e = ep(1);
      S.chkNotes = { '1:f2': '새 메모', '1:f3': '다른 메모' }; S.chkNotesOf = 't';
      syncNoteDraft();  // 메모 칸 입력이 하는 일
      const html = chkDetail(1, e, e.text, 'f2');
      api = async () => { throw new Error('저장하지 못했어요'); };
      await actions.saveFindingNote('f2');
      const failed = { notes: { ...S.chkNotes }, draft: !!S.editDrafts.chkNote, toasts: toasts.splice(0) };
      api = async (m, path, body) => { const pj = structuredClone(data); pj.episodes[0].findings[1].note = body.note; return pj; };
      await actions.saveFindingNote('f2');
      const saved = { notes: { ...S.chkNotes }, draft: !!S.editDrafts.chkNote, note: ep(1).findings[1].note, toasts: toasts.splice(0) };
      await actions.saveFindingNote('f3');
      return { html, failed, saved, last: { notes: S.chkNotes, draft: 'chkNote' in S.editDrafts } };
    })()""" % CHK_SETUP, check_project())
    assert 'data-chk-note="1:f2">새 메모</textarea>' in got["html"]
    assert got["failed"]["notes"]["1:f2"] == "새 메모" and got["failed"]["draft"] is True
    assert got["failed"]["toasts"] == [["저장하지 못했어요", True, []]]
    assert "1:f2" not in got["saved"]["notes"] and got["saved"]["note"] == "새 메모"
    assert got["saved"]["draft"] is True  # f3 초안이 아직 남았다
    assert got["saved"]["toasts"] == [["메모를 저장했어요", False, []]]
    assert got["last"] == {"notes": {}, "draft": False}


@needs_node
def test_recheck_outcome_is_not_error():
    """이 지적만 다시 검수의 보통 결과(아직 어긋남 · 딸린 지적 더함)는 오류 알림이 아니다."""
    got = run_js(CHK_FILES, """(async () => {
      %s
      saveIfDirty = async () => {}; flushText = async () => {};
      run = async (label, fn) => fn();
      api = async () => structuredClone(data);
      await actions.chkRecheck('f4');
      api = async () => { const pj = structuredClone(data); pj.episodes[0].findings.push({ ...pj.episodes[0].findings[3], id: 'f5', parent: 'f4' }); return pj; };
      await actions.chkRecheck('f4');
      return toasts;
    })()""" % CHK_SETUP, check_project())
    assert got[0] == ["아직 어긋나요. 처리 기록에 까닭을 남겼어요", False, ["처리 기록 보기"]]
    assert got[1] == ["고친 문장 때문에 새로 어긋난 곳 1개를 딸린 지적으로 더했어요", False, []]


@needs_node
def test_fix_recheck_button_matches_server():
    """지난 검수 뒤 수정이 모두 고침안이면 '고친 곳만 다시 보기'가 주 버튼이고 다시 검수는 옆에 남는다.
    직접 고친 곳이 있으면 다시 검수가 주 버튼이다. home.js fixRecheckTargets 는 서버 findings.fix_recheck_targets 와 같은 셈."""
    from canon.schema import FindingEvent, Meta, Project
    e = episode(1, status="written", text=TEXT)
    findings.merge(e, [issue(Q1), issue(Q2, "동선"), issue(Q3, "말투")], "2026-10-28T10:00:00", "b")
    e.findings[0].fix_group, e.findings[1].fix_group = "x1", "x2"
    e.edits = [TextEdit(id="e1", at="2026-10-28T11:00:00", source="fix", group="x1", before=Q1, after="a"),
               TextEdit(id="e2", at="2026-10-28T11:00:00", source="fix", group="x2", before=Q2, after="b")]
    typed = e.model_copy(deep=True)
    typed.edits.append(TextEdit(id="e3", at="2026-10-28T12:00:00", source="typed", before="c", after="d"))
    seen = e.model_copy(deep=True)  # f1 은 묶음을 넣은 뒤 이미 다시 봤다
    seen.findings[0].log.append(FindingEvent(at="2026-10-28T11:30:00", kind="recheck", text="아직 어긋남"))
    cases = [e, typed, seen]
    files = ["app.js", "home.js", "branches.js", "style.js", "plot.js", "write.js", "review.js", "chat.js", "passage.js", "rewrite.js",
             "restate.js", "opening.js", "auto.js", "marks.js", "check.js", "flow.js"]
    got = run_js(files, """(() => {
      const ids = data.cases.map((x) => fixRecheckTargets(x).map((f) => f.id));
      const views = data.cases.map((x) => {
        S.project = Object.assign({}, data.p, { episodes: [x] }); S.name = 't'; S.route = ['p', 't', 'check', '1'];
        return viewCheck(1);
      });
      return { ids, views };
    })()""", {"cases": [dump(x) for x in cases], "p": dump(Project(meta=Meta(title="t", target_episodes=3), episodes=[e]))})
    assert got["ids"] == [[f.id for f in findings.fix_recheck_targets(x)] for x in cases] == [["f1", "f2"], [], ["f2"]]
    fast, slow, one = got["views"]
    assert 'class="btn primary" data-action="fixRecheck" data-arg="1">고친 곳만 다시 보기 · 지적 2' in fast
    assert 'class="btn" data-action="checkEp"' in fast and "고침안만 넣었어요" in fast  # 다시 검수는 주 버튼이 아닌 채 남는다
    assert 'data-action="fixRecheck"' not in slow and 'class="btn primary" data-action="checkEp"' in slow
    assert "고친 곳만 다시 보기 · 지적 1" in one


@needs_node
def test_fix_recheck_asks_before_saving_project():
    """고친 곳만 다시 보기도 검수하기와 같이 저장하지 않은 작품 변경을 묻고, 거절하면 아무것도 저장 · 시작하지 않는다 (app.js checkReady)."""
    got = run_js(CHK_FILES, """(async () => {
      %s
      const calls = [];
      S.textDraft = { 1: '고친 본문' };
      S.dirty = true;
      askConfirm = async (msg, o) => { calls.push(['ask', o.ok]); return false; };
      save = async () => { calls.push(['save']); S.dirty = false; };
      api = async (m, path) => { calls.push([m, path]); return structuredClone(data); };
      startJob = async (kind, n) => { calls.push(['job', kind, n]); };
      await actions.fixRecheck('1');
      const refused = calls.splice(0);
      askConfirm = async (msg, o) => { calls.push(['ask', o.ok]); return true; };
      await actions.fixRecheck('1');
      return { refused, calls };
    })()""" % CHK_SETUP, check_project())
    assert got["refused"] == [["ask", "저장하고 시작하기"]]
    assert got["calls"] == [["ask", "저장하고 시작하기"], ["save"], ["PUT", "/projects/t/episodes/1/text"], ["job", "recheck", 1]]
