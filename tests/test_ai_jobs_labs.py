"""문단 연습장 · 연구 화면의 AI 호출을 백그라운드 작업으로 옮긴 것 (docs/ux 02c 뒷 절반).

연구 실험(rs_*)은 작품 작업이다. 실험이 고른 백엔드를 쓰고(단계 LLM 을 만들지 않는다), 옛 동기 경로처럼 research/log.jsonl 에 기록을 남긴다.
사용량도 옛 경로처럼 source · stage 'research' 와 실험 이름으로 적는다.
문단 연습장 작업(stu_*)은 작품 밖이다 (project '.studio', 대상은 세션 id). 결과는 세션 파일에 남는다.
"""
import pytest

from canon import jobs, research, store, usage, web

from .jsvm import STATIC, needs_node, run_js
from .test_ai_jobs import _wait

MODEL = "서연은 우산을 접었다. 버스가 왔다. 빗물이 신발에 스몄다. 그녀는 뒤를 돌아보지 않았다. 문이 닫혔다."


def _done(client, r):
    assert r.status_code == 200, r.text
    j = _wait(client, r.json()["id"])
    assert j["status"] == "done", j
    return j


@pytest.fixture()
def rs(client):
    meta = {"title": "등대", "genre": "미스터리", "logline": "오빠를 찾는다", "target_episodes": 4}
    assert client.post("/api/projects", json={"name": "rs", "meta": meta}).status_code == 200
    p = client.post("/api/projects/rs/suggest/apply", json=client.post("/api/projects/rs/suggest").json()).json()
    p["arc"] = client.post("/api/projects/rs/arc").json()["acts"]
    client.put("/api/projects/rs", json=p)
    client.post("/api/projects/rs/plots", json={})
    client.post("/api/projects/rs/episodes/1/confirm")
    q = store.load("rs")
    q.episode(1).text, q.episode(1).status = "서윤은 등대 문을 열었다. 바람이 거셌다. 도현이 뒤에서 불렀다. 둘은 계단을 올랐다.", "written"
    store.save("rs", q)
    return client


def _job(client, kind, trial, ep=None):
    return _done(client, client.post("/api/projects/rs/jobs", json={"kind": kind, "ep": ep, "trial": trial}))


def test_research_kinds_are_registered():
    for kind in ("rs_sample", "rs_stage", "rs_check", "rs_budget", "rs_compare"):
        assert kind in web.JOB_MAKERS and kind in web.OWN_LLM_KINDS, kind
        assert kind not in web.PENDING_KINDS


def test_research_jobs_log_like_old_paths(rs, monkeypatch):
    mock = {"provider": "mock"}
    seen = []
    real = research.sample

    def spy(*a, **kw):
        seen.append({k: usage.context().get(k) for k in ("source", "stage", "task", "project")})
        return real(*a, **kw)
    monkeypatch.setattr(research, "sample", spy)
    j = _job(rs, "rs_sample", {"runs": [mock], "prompt": "등대 장면을 써라"})
    assert j["label"] == "샘플 생성 · 백엔드 1개" and j["result"]["kind"] == "sample"
    assert seen == [{"source": "research", "stage": "research", "task": "sample", "project": "rs"}]  # 옛 경로와 같은 사용량 꼬리표
    log = rs.get("/api/projects/rs/research").json()
    assert log["log"][0]["id"] == j["result"]["id"] and log["latest"]["sample"]["rows"][0]["ok"]  # 기록에 결과 전체가 남는다
    j = _job(rs, "rs_stage", {"backend": mock, "stage": "setup"})
    assert j["label"] == "설정 제안 시험" and rs.get("/api/projects/rs/research").json()["latest"]["stage"]["id"] == j["result"]["id"]
    j = _job(rs, "rs_check", {"backend": mock, "episode": 1, "plants": 2})
    assert j["label"] == "1화 검수 시험"
    assert len(rs.get("/api/projects/rs/research").json()["latest"]["check"]["planted"]) == 2
    j = _job(rs, "rs_budget", mock)
    assert len(j["result"]["rows"]) == 4 and j["result"]["kind"] == "budget"  # 표 전체는 작업 결과로, 기록에는 요약만
    assert "rows" not in rs.get("/api/projects/rs/research").json()["latest"]["budget"]
    r = rs.post("/api/projects/rs/jobs", json={"kind": "rs_compare", "ep": 1, "trial": {"a": mock, "b": mock}})
    assert r.status_code == 400 and "두 백엔드가 같아요" in r.json()["detail"]  # 시작 전에 알린다
    j = _job(rs, "rs_compare", {"a": mock, "b": {"provider": "mock", "model": "다른-모의"}}, ep=1)
    assert j["result"] == {"episode": 1} and j["ep"] == 1
    assert len(rs.get("/api/projects/rs/research/compare/1").json()["compare"]["drafts"]) == 2
    kinds = [x["kind"] for x in rs.get("/api/projects/rs/research").json()["log"]]
    assert kinds[:5] == ["compare", "budget", "check", "stage", "sample"]


def test_research_jobs_check_before_start_and_skip_stage_llm(rs, monkeypatch):
    url = "/api/projects/rs/jobs"
    bad = [("rs_sample", {"runs": [], "prompt": "x"}, None, "백엔드와 요청 문장"), ("rs_stage", {"backend": {"provider": "mock"}, "stage": "nope"}, None, "모르는 단계"),
           ("rs_check", {"backend": {"provider": "mock"}, "episode": 1, "plants": 9}, None, "1~5개"), ("rs_compare", {"a": {"provider": "mock"}, "b": {"provider": "mock"}}, None, "화 번호")]
    for kind, trial, ep, word in bad:
        r = rs.post(url, json={"kind": kind, "ep": ep, "trial": trial})
        assert r.status_code == 400 and word in r.json()["detail"], (kind, r.text)
    assert rs.post(url, json={"kind": "rs_budget", "trial": {"provider": "nope"}}).status_code == 400  # 요청 모양이 틀리면 400

    def boom(stage):
        raise AssertionError(f"단계 LLM 을 만들었어요: {stage}")
    monkeypatch.setattr(web, "get_llm", boom)  # 로컬 백엔드만 쓰는 실험도 단계 키 없이 돈다
    _job(rs, "rs_budget", {"provider": "mock"})


def test_studio_jobs_write_session(client):
    s = client.post("/api/studio", json={"card": {"action": "우산을 건넨다", "people": [{"name": "서연"}], "model": MODEL, "beats": ["setup", "focus"]}}).json()
    sid = s["id"]
    url = f"/api/studio/{sid}/jobs"
    j = _done(client, client.post(url, json={"kind": "draft", "n": 2}))
    assert j["project"] == ".studio" and j["target"] == sid and j["result"]["added"] == 2
    j = _done(client, client.post(url, json={"kind": "anatomy"}))
    assert j["label"].endswith("구조 뜯어보기")
    j = _done(client, client.post(url, json={"kind": "variants", "k": 3}))
    assert j["result"]["variants"] == 3
    j = _done(client, client.post(url, json={"kind": "reader", "no": 1}))
    assert j["ep"] == 1
    v = client.get(f"/api/studio/{sid}").json()
    assert len(v["tries"]) == 2 and v["anatomy"] and len(v["variants"]) == 3 and v["tries"][0]["reader"]
    assert client.get("/api/projects").json() == []  # 작품 밖이다


def test_studio_jobs_check_before_start(client):
    s = client.post("/api/studio", json={"card": {"action": "우산을 건넨다"}}).json()
    url = f"/api/studio/{s['id']}/jobs"
    r = client.post(url, json={"kind": "anatomy"})
    assert r.status_code == 400 and "본보기 문단이 없어요" in r.json()["detail"]
    assert client.post(url, json={"kind": "reader", "no": 7}).status_code == 404
    assert client.post("/api/studio/abcdef123456/jobs", json={"kind": "draft"}).status_code == 404
    assert client.post(url, json={"kind": "nope"}).status_code == 422


def test_studio_jobs_for_different_sessions_run_together(client, monkeypatch):
    import threading

    a = client.post("/api/studio", json={"card": {"action": "우산을 건넨다"}}).json()["id"]
    b = client.post("/api/studio", json={"card": {"action": "문을 연다"}}).json()["id"]
    go = threading.Event()
    real = web.pipeline.draft_paragraph

    def slow(llm, card, n):
        go.wait(5)
        return real(llm, card, n)
    monkeypatch.setattr(web.pipeline, "draft_paragraph", slow)
    try:
        ja = client.post(f"/api/studio/{a}/jobs", json={"kind": "draft", "n": 1}).json()
        jb = client.post(f"/api/studio/{b}/jobs", json={"kind": "draft", "n": 1}).json()
        again = client.post(f"/api/studio/{a}/jobs", json={"kind": "draft", "n": 1}).json()
        assert ja["id"] != jb["id"] and not jb.get("already") and again["already"] and again["id"] == ja["id"]
    finally:
        go.set()
    _wait(client, ja["id"])
    _wait(client, jb["id"])
    assert all(j.project == ".studio" for j in jobs.listing(".studio"))


# ---------- 화면 (node) ----------

FILES = __import__("re").findall(r'src="/static/([a-z-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


@needs_node
def test_js_research_starts_jobs_and_places_results():
    got = run_js(FILES, """(async () => {
      S.name = 'rs'; S.route = ['p', 'rs', 'research', 'sample']; S.project = { episodes: [{ plot: { number: 1 }, text: 'x', status: 'written' }] };
      render = () => {}; isTyping = () => false;
      const started = [];
      startJob = async (...a) => { started.push(a); };
      askConfirm = async () => true;
      rsInit('rs');
      S.rs.prompt = '써라'; S.rs.runs = [{ provider: 'mock', model: '', url: '' }];
      await actions.rsSample();
      await actions.rsStage();
      S.rs.checkEp = 1; await actions.rsCheck();
      await actions.rsBudget();
      S.rs.compareEp = 1; S.rs.compare = null; await actions.rsCompare();
      const calls = [];
      api = async (m, path) => { calls.push(path); return path.includes('/compare/') ? { compare: { drafts: [1, 2] } } : { log: [], latest: { sample: { id: 'a1', rows: [] } }, open_compares: [], stages: {} }; };
      JOB_RESULT.rs_sample({ kind: 'rs_sample', project: 'rs', result: { id: 'a1' } });
      JOB_RESULT.rs_budget({ kind: 'rs_budget', project: 'rs', result: { rows: [1] } });
      JOB_RESULT.rs_compare({ kind: 'rs_compare', project: 'rs', ep: 1, result: { episode: 1 } });
      const other = JOB_RESULT.rs_sample({ kind: 'rs_sample', project: 'zz', result: { id: 'b' } });
      for (let i = 0; i < 10; i++) await null;
      return { kinds: started.map((a) => [a[0], a[1], Object.keys(a[2].trial).sort(), a[3]]), calls, sample: S.rs.cur.sample, budget: S.rs.cur.budget,
        compare: S.rs.compare, other,
        pages: ['sample', 'stage', 'check', 'budget', 'compare'].map((k) => JOB_PAGES['rs_' + k]),
        link: JOB_LINK.rs_check({ project: 'rs' }), msg: JOB_DONE_MSG.rs_compare({ ep: 1 }) };
    })()""", {})
    assert got["kinds"] == [["rs_sample", None, ["prompt", "runs", "system", "temperature"], {"quiet": True}],
                            ["rs_stage", None, ["backend", "sample", "stage"], {"quiet": True}],
                            ["rs_check", None, ["backend", "episode", "plants", "stage"], {"quiet": True}],
                            ["rs_budget", None, ["model", "provider", "url"], {"quiet": True}],
                            ["rs_compare", 1, ["a", "b"], {"quiet": True}]]
    assert got["sample"] == {"id": "a1", "rows": []} and got["budget"] == {"rows": [1]}  # 기록에서 다시 읽은 줄 · 작업 결과
    assert got["compare"] == {"drafts": [1, 2]} and "/projects/rs/research/compare/1" in got["calls"]
    assert got["other"] is None and got["pages"] == [["research"]] * 5
    assert got["link"] == "#/p/rs/research/check" and "1화" in got["msg"]


@needs_node
def test_js_studio_starts_jobs_and_keeps_dirty_card():
    got = run_js(FILES, """(async () => {
      S.route = ['studio', 's1']; render = () => {}; isTyping = () => false; renderHub = () => {}; pollJobs = () => {}; toast = () => {};
      stuSet({ id: 's1', title: 't', card: { action: '건넨다', people: [], beats: [] }, tries: [{ no: 1, text: 'a' }], variants: [] });
      const posts = [];
      api = async (m, path, body) => { posts.push([m, path, body]); return m === 'GET' ? { id: 's1', title: 't', card: { action: '서버 카드', people: [], beats: [] }, tries: [{ no: 1 }, { no: 2 }], variants: [] }
        : { id: 'j' + posts.length, kind: 'stu_' + body.kind, project: '.studio', target: 's1', status: 'running', label: 'x' }; };
      await actions.stuDraft();
      await actions.stuAnatomy();
      await actions.stuVariants();
      await actions.stuReader('1');
      const starts = posts.map((p) => [p[1], p[2].kind, p[2].no ?? null]);
      S.jobs = [{ id: 'j1', status: 'running', project: '.studio', kind: 'stu_draft', ep: null, target: 's1', label: 't · AI 안 3개' },
        { id: 'j4', status: 'running', project: '.studio', kind: 'stu_reader', ep: 1, target: 's1', label: 't · 1번 시도 독자로 읽기' }];
      const btns = [stuBtn('draft', 'AI 안 3개 쓰기').label, stuBtn('reader', '독자 질문', 1).label, stuBtn('reader', '독자 질문', 2).label];
      S.stuForm.card.action = '고치던 카드'; S.stuDirty = true;
      const msg = JOB_DONE_MSG.stu_draft({ status: 'done', target: 's1', result: { added: 1 } });
      for (let i = 0; i < 10; i++) await null;
      return { starts, btns, msg, form: S.stuForm.card.action, tries: S.stu.tries.length, dirty: S.stuDirty, link: JOB_LINK.stu_anatomy({ target: 's1' }), open: S.stuReaderOpen };
    })()""", {})
    assert got["starts"] == [["/studio/s1/jobs", "draft", None], ["/studio/s1/jobs", "anatomy", None], ["/studio/s1/jobs", "variants", None], ["/studio/s1/jobs", "reader", 1]]
    assert got["btns"] == ["t · AI 안 3개 만드는 중…", "t · 1번 시도 독자로 읽기 만드는 중…", "독자 질문"]
    assert got["msg"] == "AI 안 1개를 남겼어요."
    assert got["form"] == "고치던 카드" and got["dirty"] is True and got["tries"] == 2  # 고치던 카드는 남기고 시도는 받는다
    assert got["link"] == "#/studio/s1" and got["open"] == 1


def test_js_studio_jobs_are_mine_everywhere():
    """작품 밖 작업이라 pollJobs 가 어느 화면에서든 제 알림을 낸다 (app.js mine)."""
    src = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "j.project === STU_JOBS" in src and "S.route[0] === 'studio'" in src
    assert "const STU_JOBS = '.studio';" in (STATIC / "studio.js").read_text(encoding="utf-8")  # routes/studio.STU_JOBS 와 같다
    from canon.routes import studio as stu
    assert stu.STU_JOBS == ".studio"
