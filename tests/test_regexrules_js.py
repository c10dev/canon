"""규칙 묶음 화면(static/regexrules.js)과 작품 화면의 규칙 알림 · 되돌리기 · 정규식 지적 표시 · 설정의 켤 묶음.
node 가 있을 때만 돈다."""
import re

from canon.schema import ConsistencyIssue, Meta, Project, RuleChange, RuleRun

from .jsvm import STATIC, dump, episode, needs_node, run_js

# 화면 파일을 index.html 차례대로 모두 읽는다 (집필 · 검수 화면이 여러 도구 파일을 부른다)
ALL = re.findall(r'src="/static/([a-z0-9-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))

TEXT = "그는 문을 열었다… 바람이 불었다… 끝."


def _runs():
    a = RuleChange(bundle="b1", rule="r1", name="말줄임표", start=8, before="...", after="…")
    b = RuleChange(bundle="b1", rule="r1", name="말줄임표", start=17, before="...", after="…")
    gone = RuleChange(bundle="b1", rule="r2", name="빈칸", start=0, before=" ", after="", undone=True)
    return [RuleRun(id="r1", at="2026-11-09T10:00:00", kind="write", changes=[a, b]),
            RuleRun(id="r2", kind="passage", changes=[gone]),
            RuleRun(id="r3", kind="rewrite", skipped="표기 통일")]


def _project(**kw):
    e = episode(1, status="written", text=TEXT, rule_runs=_runs(), **kw)
    return Project(meta=Meta(title="t", target_episodes=3), episodes=[e])


@needs_node
def test_pure_helpers():
    got = run_js(["app.js", "regexrules.js"], """(() => ({
      say: ruleRunSay({ changes: [{}, {}], skipped: '' }),
      skip: ruleRunSay({ changes: [], skipped: '표기 통일' }),
      skip2: ruleSkipSay('따옴표'),
      none: ruleRunSay(null),
      line: ruledLine([{ name: '말줄임표' }, { name: '말줄임표' }, { name: '' }]),
      empty: ruledLine([]),
      counts: ruleCounts({ warn: 1, fix: 3, export: 1 }),
      body: ruleBody({ name: 'n', rules: [{ id: 'ab', in: 'x', out: 'y' }] }, '메모'),
      blank: ruleBlank(),
      bit: ruleBit('a\\nb') + '|' + ruleBit(''),
    }))()""", None)
    assert got["say"] == "규칙으로 2곳 고쳤어요."
    assert got["skip"] == "규칙 묶음 표기 통일을 거는 데 너무 오래 걸려서 건너뛰었어요."
    assert got["skip2"] == "규칙 묶음 따옴표를 거는 데 너무 오래 걸려서 건너뛰었어요"
    assert got["none"] == ""
    assert got["line"] == "규칙으로 3곳 고쳤어요 · 말줄임표, 이름 없는 규칙"
    assert got["empty"] == ""
    assert got["counts"] == ["경고 1", "고침 2", "내보내기 1"]
    assert got["body"] == {"name": "n", "notes": "", "rules": [{"id": "ab", "in": "x", "out": "y"}], "note": "메모"}
    assert re.fullmatch(r"[0-9a-f]{8}", got["blank"]["id"]) and got["blank"]["in"] == "" and got["blank"]["action"] == "warn"
    assert got["bit"].startswith("a↵b|") and "(지움)" in got["bit"]


@needs_node
def test_write_screen_notice_and_undo():
    got = run_js(ALL, """(async () => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'write', '1'];
      const view = viewWrite(1);
      const ro = ruleRunsNote(1, false);
      const calls = [];
      askConfirm = async () => true;
      run = async (label, fn) => { await fn(); return true; };
      saveIfDirty = async () => {}; flushText = async () => {}; toast = (m) => calls.push(['toast', m]);
      api = async (m, path, body) => { calls.push([m, path]); return path.endsWith('/undo') && path.includes('/changes/') ? data : { project: data, undone: 1, left: 1 }; };
      await actions.ruleUndo('1:r1:0');
      await actions.ruleUndoAll('1:r1');
      return { view, ro, calls };
    })()""", dump(_project()))
    v = got["view"]
    assert "규칙으로 2곳 고쳤어요" in v and "쓰기" in v
    assert 'data-action="ruleUndo" data-arg="1:r1:0"' in v and 'data-action="ruleUndoAll" data-arg="1:r1"' in v
    assert "규칙 묶음 표기 통일을 거는 데 너무 오래 걸려서 건너뛰었어요" in v
    assert "규칙으로 1곳 고쳤어요" not in v  # 모두 되돌린 걸기는 접는다
    assert "ruleUndo" not in got["ro"] and "규칙으로 2곳 고쳤어요" in got["ro"]  # 고칠 수 없으면 보기만
    assert got["calls"] == [
        ["POST", "/projects/t/episodes/1/rule-runs/r1/changes/0/undo"], ["toast", "규칙이 고친 곳을 되돌렸어요"],
        ["POST", "/projects/t/episodes/1/rule-runs/r1/undo"], ["toast", "1곳을 되돌렸어요. 1곳은 그 뒤에 또 고쳐 남겼어요"],
    ]


@needs_node
def test_job_message_and_import_source():
    p = _project()
    got = run_js(ALL, """(async () => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'brief', '1'];
      const msgs = [JOB_DONE_MSG.write({ ep: 1, result: { rule_run: { changes: [{}], skipped: '' } } }),
        JOB_DONE_MSG.write({ ep: 1, result: { candidate: true } }), JOB_DONE_MSG.write({ ep: 1, result: null })];
      const sent = [];
      const after = structuredClone(data);
      after.episodes[0].rule_runs.push({ id: 'r4', kind: 'import', changes: [{}, {}, {}], skipped: '' });
      globalThis.document = { querySelector: (q) => (q === '#imp-body' ? { value: '새 본문' } : null) };
      askConfirm = async () => true; saveIfDirty = async () => {};
      run = async (label, fn) => { await fn(); return true; };
      let said = '';
      toast = (m) => { said = m; };
      api = async (m, path, body) => { sent.push([m, path, body]); return after; };
      await actions.importText(1);
      return { msgs, sent, said };
    })()""", dump(p))
    assert got["msgs"] == ["1화 본문을 저장했어요. 규칙으로 1곳 고쳤어요.", "1화 새 판이 나왔어요. 지금 판과 비교해 고르세요.", "1화 본문을 저장했어요."]
    assert got["sent"] == [["PUT", "/projects/t/episodes/1/text", {"text": "새 본문", "source": "import"}]]
    assert got["said"] == "1화 본문으로 저장했어요. 규칙으로 3곳 고쳤어요."


@needs_node
def test_candidate_cards_show_ruled():
    p = _project()
    got = run_js(ALL, """(async () => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'write', '1'];
      ep(1).candidate = { id: 'v1', text: '새 판…', kind: 'candidate', at: '', request: '', rule_runs: [{ id: 'r5', kind: 'rewrite', changes: [{ name: '말줄임표' }], skipped: '' }] };
      const card = candidateCard(1);
      S.reworks[1] = { text: '다듬은 글…', ruled: [{ name: '말줄임표', before: '...', after: '…', start: 5 }] };
      const sent = [];
      run = async (label, fn) => { await fn(); return true; }; saveIfDirty = async () => {}; toast = () => {}; render = () => {};
      api = async (m, path, body) => { sent.push(body); return data; };
      await actions.reworkAccept(1);
      return { card, sent };
    })()""", dump(p))
    assert "규칙으로 1곳 고쳤어요 · 말줄임표" in got["card"]
    assert got["sent"][0]["ruled"] == [{"name": "말줄임표", "before": "...", "after": "…", "start": 5}]


@needs_node
def test_regex_finding_display():
    e = episode(1, status="written", text=TEXT)
    from canon import findings
    q = "그는 문을 열었다…"
    findings.merge(e, [ConsistencyIssue(type="표기", severity="low", description="말줄임표 확인", source_episode=1, source_quote=r"…",
                                        current_quote=q, origin="regex", regex_rule="b1/r1")], "2026-11-09T10:00:00", "b")
    p = Project(meta=Meta(title="t", target_episodes=3), episodes=[e])
    got = run_js(ALL, """(() => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'check', '1'];
      const view = viewCheck(1);
      return { view, panel: fixPanel(1, 'f1') };
    })()""", dump(p))
    v = got["view"]
    assert "정규식 · 말줄임표 확인" in v and "chk-pattern" in v
    assert "근거 · " not in v and "판정 다시 보기" in v
    assert "근거 쪽이 틀렸어요" not in got["panel"] and "규칙이 잘못 짚었어요" in got["panel"]


@needs_node
def test_rules_screens_and_save():
    got = run_js(ALL, """(async () => {
      S.route = ['rules']; S.ruleList = [{ id: 'b1', name: '표기', notes: '', warn: 1, fix: 2, export: 1, used_by: 2, updated_at: '' }];
      const list = viewRuleList();
      S.route = ['rules', 'new']; S.projects = [{ name: 'p1', title: '작품' }];
      S.ruleB = { name: '새 묶음', notes: '', rules: [{ id: 'aa', comment: '따옴표', in: '"', out: '“', type: 'output', flag: 'g', action: 'warn', enabled: true }], used_by: [], notices: [] };
      actions.ruleSet('0:type:export');
      const forced = S.ruleB.rules[0].action;
      actions.ruleSet('0:action:warn');  // 내보내기 규칙은 경고로 돌아가지 않는다
      const kept = S.ruleB.rules[0].action;
      const edit = viewRuleBundle();
      const sent = [];
      run = async (label, fn) => { try { await fn(); return true; } catch (e) { return false; } };
      toast = () => {};
      api = async (m, path, body) => { sent.push([m, path, body]); throw Object.assign(new Error('따옴표 · 이 정규식은 저장할 수 없어요: x'), { status: 400 }); };
      await actions.ruleSave();
      const err = [S.ruleErr, S.ruleDirty, viewRuleBundle().includes('저장할 수 없어요')];
      return { list, edit, forced, kept, sent, err };
    })()""", None)
    assert "경고 1" in got["list"] and "고침 1" in got["list"] and "내보내기 1" in got["list"] and "켠 작품 2" in got["list"]
    assert got["forced"] == "fix" and got["kept"] == "fix"
    e = got["edit"]
    warn = re.search(r'<button[^>]*data-arg="0:action:warn"[^>]*>', e).group(0)
    fix = re.search(r'<button[^>]*data-arg="0:action:fix"[^>]*>', e).group(0)
    assert "disabled" in warn and "disabled" not in fix  # 내보내기 규칙은 경고를 막고 고침은 눌린 채 둔다
    assert "찾을 정규식" in e and "바꿀 글" in e and 'data-action="ruleTry"' in e and "버전 메모" not in e  # 새 묶음은 버전이 없다
    assert got["sent"] == [["POST", "/rules", {"name": "새 묶음", "notes": "", "note": "", "rules": [
        {"id": "aa", "comment": "따옴표", "in": '"', "out": "“", "type": "export", "flag": "g", "action": "fix", "enabled": True}]}]]
    assert got["err"] == ["따옴표 · 이 정규식은 저장할 수 없어요: x", True, True]


@needs_node
def test_settings_rule_bundles():
    p = Project(meta=Meta(title="t", target_episodes=3))
    p.settings.rule_bundles = ["b2", "gone"]
    got = run_js(ALL, """(async () => {
      S.project = data; S.name = 't'; S.route = ['p', 't', 'write', '1'];
      SET.rules = { name: 't', list: [{ id: 'b1', name: '첫째', warn: 1, fix: 0, export: 0 }, { id: 'b2', name: '둘째', warn: 0, fix: 2, export: 0 }] };
      const html = setRowHtml('regex-rules');
      const sent = [];
      setPaint = () => {};
      api = async (m, path, body) => { sent.push([m, path, body]); const q = structuredClone(data); q.settings.rule_bundles = body.bundles; return q; };
      await actions.setRuleBundle('b1');
      await actions.setRuleMove('2:-1');
      return { html, sent, now: P().settings.rule_bundles, nav: outNav([], [], [], [{ id: 'b1' }]).tools.find((t) => t[0] === 'rules') };
    })()""", dump(p))
    h = got["html"]
    assert h.index("1. 둘째") < h.index("2. gone") < h.index("첫째")
    assert "찾을 수 없는 묶음이에요" in h and 'href="#/rules"' in h
    assert got["sent"] == [["PUT", "/projects/t/rule-bundles", {"bundles": ["b2", "gone", "b1"]}],
                           ["PUT", "/projects/t/rule-bundles", {"bundles": ["b2", "b1", "gone"]}]]
    assert got["now"] == ["b2", "b1", "gone"]
    assert got["nav"] == ["rules", "#/rules", "📏", "규칙 묶음", "1"]
