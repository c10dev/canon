"""화면을 막던 남은 AI 호출을 백그라운드 작업으로 옮긴 것 (docs/ux 02c): 검수 지적 하나의 고침안 · 다시 검수, 삽화, 지도 두 곳.

작업은 mock LLM 으로 돈다. 지적 작업과 삽화는 옛 동기 경로처럼 그 화에 결과를 남긴다. 지도 작업은 제안만 돌려주고 작품을 바꾸지 않는다.
같은 화의 지적 작업끼리 부딪히면 시작하지 않는다 (web._finding_clash).
"""
import json
import threading

from fastapi.testclient import TestClient

from canon import jobs, pipeline, store, web
from canon.schema import ConsistencyReport

from .jsvm import STATIC, needs_node, run_js
from .test_ai_jobs import _run, _saved, _wait
from .test_findings import demo, issue  # noqa: F401  (demo 는 fixture)
from .test_passage import TEXT, _written


def _with_finding(name, quote="바람이 불었다."):
    p = store.load(name)
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue(quote)]))
    store.save(name, p)


def _finding(name, fid="f1"):
    return next(f for f in store.load(name).episode(1).findings if f.id == fid)


def test_new_kinds_are_registered():
    for kind in ("fix_one", "recheck_one", "illust", "atlas_suggest", "atlas_sort"):
        assert kind in web.JOB_MAKERS, kind
        assert kind not in web.PENDING_KINDS  # 결과는 화면이나 그 화에 놓고 pending.json 에는 남기지 않는다
    assert {"fix_one", "recheck_one"} <= jobs.EP_AI_KINDS  # 같은 화의 멈춘 작업이 응답을 기다리면 시작하지 않는다


def test_fix_one_and_recheck_one_store_on_finding(demo):  # noqa: F811
    c = TestClient(web.app)
    _with_finding(demo)
    before = store.load(demo).episode(1).text
    j = _run(c, demo, {"kind": "fix_one", "ep": 1, "target": "f1"})
    assert j["target"] == "f1" and j["ep"] == 1 and j["result"] == {"fid": "f1", "fixes": 2}
    f = _finding(demo)
    assert len(f.fixes) == 2 and f.fixes_basis
    assert store.load(demo).episode(1).text == before  # 고침안은 작가가 고른 것만 넣는다
    c.post(f"/api/projects/{demo}/episodes/1/findings/f1/fixes/0/apply", json={})
    j = _run(c, demo, {"kind": "recheck_one", "ep": 1, "target": "f1"})
    assert j["result"]["resolved"] and j["result"]["kids"] == [] and j["result"]["fid"] == "f1"
    f = _finding(demo)
    assert (f.status, f.closed_by) == ("fixed", "one")


def test_finding_jobs_check_before_start(demo):  # noqa: F811
    c = TestClient(web.app)
    _with_finding(demo)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "fix_one", "ep": 1, "target": "f9"})
    assert r.status_code == 400 and "f9" in r.json()["detail"]
    assert c.post(f"/api/projects/{demo}/jobs", json={"kind": "recheck_one", "ep": 1}).status_code == 400  # 지적 id 가 없다
    c.put(f"/api/projects/{demo}/episodes/1/findings/f1", json={"status": "kept"})
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "recheck_one", "ep": 1, "target": "f1"})
    assert r.status_code == 400 and "열린 지적" in r.json()["detail"]


def test_finding_jobs_do_not_clash(demo, monkeypatch):  # noqa: F811
    """지적 하나 작업은 그 화의 통째 작업 · 같은 지적의 다른 작업과 함께 돌지 않는다. 다른 지적끼리는 함께 돈다."""
    c = TestClient(web.app)
    _with_finding(demo)
    p = store.load(demo)
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[issue("바람이 불었다."), issue("서윤은 등대 앞에 섰다.")]))
    store.save(demo, p)
    ids = [f.id for f in store.load(demo).episode(1).findings if f.status == "open"]
    assert len(ids) >= 2
    go = threading.Event()
    real = web.pipeline.propose_fixes

    def slow(llm, p, n, fid):
        go.wait(5)
        return real(llm, p, n, fid)
    monkeypatch.setattr(web.pipeline, "propose_fixes", slow)
    url = f"/api/projects/{demo}/jobs"
    try:
        a = c.post(url, json={"kind": "fix_one", "ep": 1, "target": ids[0]}).json()
        b = c.post(url, json={"kind": "fix_one", "ep": 1, "target": ids[1]}).json()
        assert a["id"] != b["id"] and not b.get("already")  # 다른 지적은 함께 돈다
        assert c.post(url, json={"kind": "fix_one", "ep": 1, "target": ids[0]}).json()["already"]
        r = c.post(url, json={"kind": "recheck_one", "ep": 1, "target": ids[0]})
        assert r.status_code == 400 and "도는 중" in r.json()["detail"]  # 같은 지적의 다른 작업
        for kind in ("check", "fixes", "recheck"):
            r = c.post(url, json={"kind": kind, "ep": 1})
            assert r.status_code == 400 and "도는 중" in r.json()["detail"], kind
    finally:
        go.set()
    _wait(c, a["id"])
    _wait(c, b["id"])
    go2 = threading.Event()
    monkeypatch.setattr(web, "_run_check", lambda name, n, llm: go2.wait(5) or {})
    try:
        j = c.post(url, json={"kind": "check", "ep": 1}).json()
        r = c.post(url, json={"kind": "fix_one", "ep": 1, "target": ids[0]})
        assert r.status_code == 400 and "검수" in r.json()["detail"]  # 통째 검수가 도는 동안
    finally:
        go2.set()
    _wait(c, j["id"])


def test_illust_job_adds_illustration(client):
    _written(client)
    quote = "서윤은 등대 앞에 섰다."
    sel = {"start": TEXT.index(quote), "text": quote}
    r = client.post("/api/projects/lh/jobs", json={"kind": "illust", "ep": 1, "selection": sel, "model": "nope"})
    assert r.status_code == 400 and "모르는 모델" in r.json()["detail"]
    j = _run(client, "lh", {"kind": "illust", "ep": 1, "selection": sel, "note": "밤"})
    assert j["result"] == {"id": "i1", "missing_look": ["hero"]} and j["label"] == "1화 삽화 태그"
    ill = store.load("lh").episode(1).illustrations[-1]
    assert ill.id == "i1" and ill.selection.text == quote and ill.request == "밤"
    j = _run(client, "lh", {"kind": "illust", "ep": 1})  # 고르지 않으면 AI 가 장면을 고른다
    assert j["label"] == "1화 삽화 장면 고르기" and len(store.load("lh").episode(1).illustrations) == 2


def test_illust_job_needs_text(client):
    _written(client)
    r = client.post("/api/projects/lh/jobs", json={"kind": "illust", "ep": 2})
    assert r.status_code == 400 and "본문이 없어요" in r.json()["detail"]


def _atlas_client(tmp_path, monkeypatch, project):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    store.save("s", project)
    return TestClient(web.app)


def test_atlas_suggest_job_returns_without_saving(tmp_path, monkeypatch):
    from .test_mapgen import _project
    c = _atlas_client(tmp_path, monkeypatch, _project())
    spec = c.get("/api/projects/s/atlas").json()["gen"]["spec"]
    before = _saved("s")
    j = _run(c, "s", {"kind": "atlas_suggest", "spec": spec})
    assert j["result"]["water"] == "sea" and j["result"]["places"] and j["result"]["reason"]
    assert _saved("s") == before and store.load("s").atlas.spec is None  # 제안은 저장하지 않는다


def test_atlas_sort_job_returns_without_saving(tmp_path, monkeypatch):
    from .test_atlas import _played
    p = _played()
    p.characters[0].name = p.characters[0].name or "서윤"
    c = _atlas_client(tmp_path, monkeypatch, p)
    before = _saved("s")
    j = _run(c, "s", {"kind": "atlas_sort"})
    assert j["label"] == "위치 글 1개 정리" and j["result"]["rows"][0]["text"] == "어딘지 모를 지하실" and j["result"]["rows"][0]["skip"]
    assert _saved("s") == before  # 고른 글만 /atlas/sort/apply 로 잇는다
    r = c.post("/api/projects/s/jobs", json={"kind": "atlas_sort", "texts": ["없는 글"]})
    assert r.status_code == 400 and "위치 글이 없어요" in r.json()["detail"]  # 시작 전에 알린다


# ---------- 화면 (node) ----------

FILES = __import__("re").findall(r'src="/static/([a-z-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))
KINDS = {"fix_one": ["check"], "recheck_one": ["check"], "illust": ["write", "check", "review"], "atlas_suggest": ["atlas"], "atlas_sort": ["atlas"]}


@needs_node
def test_js_registers_pages_messages_links_and_buttons():
    got = run_js(FILES, """(() => {
      const j = (kind) => ({ kind, project: '등대', label: 'x', target: 'f1', ep: 2, result: {} });
      const kinds = %s;
      S.route = ['p', '등대', 'check', '2']; S.project = { episodes: [{ plot: { number: 2 } }] };
      return {
        pages: Object.fromEntries(kinds.map((k) => [k, JOB_PAGES[k]])),
        msg: kinds.filter((k) => { const m = JOB_DONE_MSG[k]; return !(typeof m === 'function' ? m(j(k)) : m); }),
        link: Object.fromEntries(kinds.map((k) => [k, JOB_LINK[k] && JOB_LINK[k](j(k))])),
        result: kinds.filter((k) => typeof JOB_RESULT[k] !== 'function'),
        btns: ['illMake', 'atlasGenSuggest', 'atlasSort'].map((a) => JOB_BTNS[a] && JOB_BTNS[a]('f1')),
        chk: ['fixGet', 'chkRecheck'].filter((a) => a in JOB_BTNS),
        screen: kinds.filter((k) => SCREEN_ONLY_JOBS.has(k)),
        epAi: ['fix_one', 'recheck_one'].map((k) => EP_AI_KINDS.has(k)),
      };
    })()""" % json.dumps(list(KINDS)), {})
    assert got["pages"] == KINDS
    assert got["msg"] == [] and got["result"] == []
    enc = "%EB%93%B1%EB%8C%80"
    assert got["link"] == {"fix_one": f"#/p/{enc}/check/2", "recheck_one": f"#/p/{enc}/check/2", "illust": f"#/p/{enc}/write/2",
                           "atlas_suggest": f"#/p/{enc}/atlas", "atlas_sort": f"#/p/{enc}/atlas"}
    # 삽화는 그 화의 작업 하나라 버튼 잠금에 화를 함께 준다. 지적 버튼은 #app 밖 고치는 창에 있어 jobBtn 으로 그린다
    assert got["btns"] == [["illust", None, 2], ["atlas_suggest"], ["atlas_sort"]] and got["chk"] == []
    assert got["screen"] == ["atlas_suggest", "atlas_sort"] and got["epAi"] == [True, True]


@needs_node
def test_js_lock_buttons_by_episode():
    """삽화 버튼은 그 화의 작업만 잠근다. 지적 버튼(jobBtn)은 그 화의 그 지적 작업만 잠근다 (다른 화의 같은 id 는 그대로)."""
    got = run_js(FILES, """(() => {
      S.name = 'a';
      const btn = (action, arg) => ({ dataset: { action, arg }, attrs: {}, textContent: '고른 부분으로 만들기', classList: { add() {}, contains() { return false; } },
        setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; } });
      const btns = [btn('illMake', 'sel')];
      const root = { querySelectorAll: () => btns };
      S.route = ['p', 'a', 'write', '3'];
      S.jobs = [{ id: '1', status: 'running', project: 'a', kind: 'illust', ep: 2, target: '', label: '2화 삽화 태그' },
        { id: '2', status: 'running', project: 'a', kind: 'fix_one', ep: 2, target: 'f1', label: '2화 f1 고침안' }];
      lockJobBtns(root);
      const other = btns[0].getAttribute('aria-disabled');
      S.route = ['p', 'a', 'write', '2'];
      lockJobBtns(root);
      const fix = [jobBtn('fix_one', 2, 'AI 고침안 받기', 'a', 'f1').label, jobBtn('fix_one', 3, 'AI 고침안 받기', 'a', 'f1').label, jobBtn('fix_one', 2, 'AI 고침안 받기', 'a', 'f2').label];
      S.route = ['p', 'a', 'check', '2'];
      S.jobs.push({ id: '3', status: 'running', project: 'a', kind: 'recheck_one', ep: 2, target: 'f1', label: '2화 f1 다시 검수' });
      const re = [recheckBtn({ id: 'f1', origin: 'ai' }), recheckBtn({ id: 'f1', origin: 'regex' })];
      return { other, same: [btns[0].getAttribute('aria-disabled'), btns[0].textContent], fix, re };
    })()""", {})
    assert got["other"] is None
    assert got["same"] == ["true", "2화 삽화 태그 만드는 중…"]
    assert got["fix"] == ["2화 f1 고침안 만드는 중…", "AI 고침안 받기", "AI 고침안 받기"]
    assert 'aria-disabled="true"' in got["re"][0] and "2화 f1 다시 검수 만드는 중…" in got["re"][0]
    assert "aria-disabled" not in got["re"][1] and "판정 다시 보기" in got["re"][1]  # 정규식 판정은 AI 작업이 아니다


CHK_SETUP = """S.project = data; S.name = 't'; S.route = ['p', 't', 'check', '1'];
  render = () => {};
  const started = [];
  startJob = async (...a) => { started.push(a); };
  saveIfDirty = async () => {}; flushText = async () => {};
  isTyping = () => false;"""


@needs_node
def test_js_check_starts_jobs_and_places_results():
    """AI 고침안 받기 · 이 지적만 다시 검수는 작업을 시작한다. 정규식 지적의 판정 다시 보기는 바로 한다.
    결과: 그 지적을 보고 있으면 고치는 창을 열고, 아니면 알림의 '보기'로 연다. 아직 어긋남은 오류 알림이 아니다."""
    from .test_check_js import check_project
    data = check_project()
    data["episodes"][0]["findings"][0]["origin"] = "regex"
    got = run_js(FILES, """(async () => {
      %s
      let synced = 0;
      api = async () => { synced++; return structuredClone(data); };
      run = async (label, fn) => fn();
      toast = () => {};
      S.fixSkip = { '1:f4:0': [1], '1:f2:0': [0] };
      await actions.fixGet('f4');
      await actions.chkRecheck('f4');
      await actions.chkRecheck('f1');
      const skip = Object.keys(S.fixSkip);
      const j = (kind, result) => ({ kind, ep: 1, target: 'f4', project: 't', result });
      S.chkSel = { 1: 'f2' };
      S.selTool = null;
      const away = JOB_RESULT.fix_one(j('fix_one', { fixes: 2 }));
      const tool0 = S.selTool;
      S.chkSel = { 1: 'f4' };
      const here = JOB_RESULT.fix_one(j('fix_one', { fixes: 2 }));
      const tool1 = S.selTool && S.selTool.fid;
      const open = JOB_RESULT.recheck_one(j('recheck_one', { resolved: false, kids: [] }));
      const done = JOB_RESULT.recheck_one(j('recheck_one', { resolved: true, kids: [] }));
      S.chkSel = { 1: 'f2' };
      const kid = JOB_RESULT.recheck_one(j('recheck_one', { resolved: false, kids: ['f3'] }));
      const kidAct = kid.actions.map((a) => a.label);
      kid.actions[0].run();
      return { started, synced, skip, away: away.actions.map((a) => a.label), tool0, here, tool1,
        open: [open.msg, open.actions.map((a) => a.label)], done: done.msg, kid: [kid.msg, kidAct], sel: S.chkSel[1] };
    })()""" % CHK_SETUP, data)
    assert got["started"] == [["fix_one", 1, {"target": "f4"}, {"quiet": True}], ["recheck_one", 1, {"target": "f4"}, {"quiet": True}]]
    assert got["synced"] == 1  # 정규식 지적 f1 은 AI 없이 바로 판정한다
    assert got["skip"] == ["1:f2:0"]  # 다시 받는 지적의 딸린 곳 고르기는 지운다
    assert got["away"] == ["보기"] and got["tool0"] is None  # 다른 지적을 보고 있으면 고치는 창을 옮기지 않는다
    assert got["here"] is None and got["tool1"] == "f4"
    assert got["open"] == ["1화 지적 f4: 아직 어긋나요. 처리 기록에 까닭을 남겼어요", ["처리 기록 보기"]]
    assert got["done"] == "1화 지적 f4: 풀렸어요. 고침으로 닫았어요"
    assert got["kid"] == ["1화 지적 f4: 고친 문장 때문에 새로 어긋난 곳 1개를 딸린 지적으로 더했어요", ["보기"]]
    assert got["sel"] == "f3"  # '보기'는 딸린 지적을 고른다


@needs_node
def test_js_illust_and_atlas_results():
    """삽화 작업은 고른 부분과 바라는 것을 보낸다. 지도 결과는 작가가 고른 칸 · 글을 덮지 않는다."""
    got = run_js(FILES, """(async () => {
      S.name = 't'; S.route = ['p', 't', 'write', '1'];
      S.project = { illust: { model: 'v4' }, episodes: [{ plot: { number: 1 }, text: 'x', illustrations: [] }] };
      render = () => {};
      const started = [];
      startJob = async (...a) => { started.push(a); };
      saveIfDirty = async () => {}; flushText = async () => {};
      isTyping = () => false;
      S.illAsk = '밤';
      await ilMake(1, { start: 3, text: '등대' });
      await ilMake(1, null);
      const ill = JOB_RESULT.illust({ kind: 'illust', ep: 1, result: { missing_look: ['hero'] } }).msg;
      const scroll = S.illScroll;
      S.atlas = { unmatched: [{ text: '지하실' }, { text: '부엌' }, { text: '골목' }], gen: { options: { village: { size: { small: '작음', big: '큼' }, water: { none: '없음', sea: '바다' } } }, places: [] } };
      atlasDraft('부엌').v = '-';  // 기다리는 동안 작가가 고른 글
      const sort = JOB_RESULT.atlas_sort({ kind: 'atlas_sort', result: { rows: [{ text: '지하실', place: 'p1' }, { text: '부엌', place: 'p2' }], new_places: [] } }).msg;
      S.atlasGen = { name: 't', spec: { kind: 'village', size: 'small', water: 'none', places: [{ key: 'a', kind: 'house', put: false }] }, touched: { water: true }, ai: null };
      const gen = JOB_RESULT.atlas_suggest({ kind: 'atlas_suggest', project: 't', result: { kind: 'village', size: 'big', water: 'sea', places: [], reason: '바닷가' } }).msg;
      const lost = JOB_RESULT.atlas_suggest({ kind: 'atlas_suggest', project: 'other', result: { kind: 'village', places: [] } }).msg;
      return { started, ill, scroll, sort, drafts: ['지하실', '부엌'].map((t) => atlasDraft(t).v), gen, spec: S.atlasGen.spec, reason: S.atlasGen.ai.reason, lost };
    })()""", {})
    assert got["started"] == [["illust", 1, {"note": "밤", "model": "v4", "selection": {"start": 3, "text": "등대"}}, {"quiet": True}],
                              ["illust", 1, {"note": "밤", "model": "v4"}, {"quiet": True}]]
    assert got["ill"] == "1화 삽화 프롬프트를 만들었어요. 외형 태그가 없는 인물은 고정해 두세요" and got["scroll"] is True
    assert got["sort"] == "위치 글 1개를 채웠어요. 확인하고 '적용'을 누르세요. 1개는 AI가 정하지 못했어요"
    assert got["drafts"] == ["p1", "-"]
    assert got["gen"] == "AI 제안으로 1칸을 바꿨어요. 확인하고 미리보기를 누르세요"
    assert got["spec"]["size"] == "big" and got["spec"]["water"] == "none" and got["reason"] == "바닷가"
    assert "다시 받으세요" in got["lost"]
