"""AI 제안을 기다리는 동안 화면을 막지 않게 백그라운드 작업으로 옮긴 호출 (docs/ux 02b).

작업은 mock LLM 으로 돌고, 제안만 돌려주는 작업은 작품을 바꾸지 않는다. 문체 규칙 찾기 · 예시 쓰기는 옛 동기 경로처럼
작품의 제안 칸(style_learning · style_example)에만 쓴다. 대상(target)이 다른 인물 작업은 함께 돈다.
"""
import json
import time

from canon import jobs, store, web

from .jsvm import STATIC, needs_node, run_js
from .test_own_style import _edited_project
from .test_plot_chat import _project
from .test_storylines import _short


def _wait(client, jid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않았어요")


def _run(client, name, body):
    r = client.post(f"/api/projects/{name}/jobs", json=body)
    assert r.status_code == 200, r.text
    j = _wait(client, r.json()["id"])
    assert j["status"] == "done", j
    return j


def _saved(name):
    return json.loads(store.load(name).model_dump_json())


def test_new_kinds_are_registered():
    for kind in ("char_body", "char_voice", "char_look", "statwin_suggest", "statwin_init", "names_ai", "style_learn", "style_example"):
        assert kind in web.JOB_MAKERS, kind
        assert kind not in web.PENDING_KINDS  # 화면 제안으로만 놓고 pending.json 에는 남기지 않는다


def test_character_jobs_return_drafts_without_saving(client):
    _project(client)
    before = _saved("lh")
    j = _run(client, "lh", {"kind": "char_body", "target": "ally"})
    assert j["target"] == "ally" and j["result"]["height"] and "measurements" in j["result"]
    j = _run(client, "lh", {"kind": "char_voice", "target": "ally", "note": "더 건조하게"})
    assert j["result"]["voice"]
    j = _run(client, "lh", {"kind": "char_look", "target": "ally"})
    assert j["result"]["look"] and j["result"]["subject"]
    assert _saved("lh") == before  # 작가가 칸에서 적용하고 저장해야 들어간다


def test_character_job_checks_character_before_start(client):
    _project(client)
    r = client.post("/api/projects/lh/jobs", json={"kind": "char_body", "target": "nobody"})
    assert r.status_code == 400 and "인물이 없어요" in r.json()["detail"]
    assert client.post("/api/projects/lh/jobs", json={"kind": "char_look"}).status_code == 400


def test_character_jobs_for_different_targets_run_together(client, monkeypatch):
    """같은 종류라도 인물이 다르면 함께 돈다. 같은 인물이면 이미 도는 작업을 돌려준다 (already)."""
    import threading

    _project(client)
    go = threading.Event()
    real = web.pipeline.suggest_body

    def slow(llm, p, cid):
        go.wait(5)
        return real(llm, p, cid)
    monkeypatch.setattr(web.pipeline, "suggest_body", slow)
    a = client.post("/api/projects/lh/jobs", json={"kind": "char_body", "target": "ally"}).json()
    b = client.post("/api/projects/lh/jobs", json={"kind": "char_body", "target": "hero"}).json()
    again = client.post("/api/projects/lh/jobs", json={"kind": "char_body", "target": "ally"}).json()
    go.set()
    assert a["id"] != b["id"] and not b.get("already")
    assert again["already"] and again["id"] == a["id"]
    assert _wait(client, a["id"])["status"] == _wait(client, b["id"])["status"] == "done"


def test_failed_character_job_keeps_failure_per_target(client, monkeypatch):
    _project(client)

    def boom(llm, p, cid):
        raise ValueError("시험용 실패")
    monkeypatch.setattr(web.pipeline, "suggest_look", boom)
    j = _wait(client, client.post("/api/projects/lh/jobs", json={"kind": "char_look", "target": "ally"}).json()["id"])
    assert j["status"] == "error"
    assert "char_look::ally" in client.get("/api/projects/lh/pending").json()["failures"]


def test_statwin_jobs_return_drafts_without_saving(client):
    store.save("sw", _short(8))
    before = _saved("sw")
    j = _run(client, "sw", {"kind": "statwin_suggest", "note": "더 어둡게"})
    assert j["result"]["options"]
    client.put("/api/projects/sw/statwin-template", json={"template": "【 상태창 】\n{rows}", "names": ["레벨", "HP"]})
    before = _saved("sw")
    j = _run(client, "sw", {"kind": "statwin_init"})
    assert j["result"]["names"] == ["레벨", "HP"] and j["result"]["characters"]
    assert _saved("sw") == before


def test_names_job_reads_saved_project(client):
    meta = {"title": "검", "genres": ["martial_arts"], "target_episodes": 10}
    client.post("/api/projects", json={"name": "wx", "meta": meta})
    s = client.post("/api/projects/wx/suggest").json()
    client.post("/api/projects/wx/suggest/apply", json=s)
    before = _saved("wx")
    j = _run(client, "wx", {"kind": "names_ai", "place_kind": "문파"})
    assert j["target"] == "" and j["result"]["style"] == "wuxia"
    assert j["result"]["options"] and {o["name"] for o in j["result"]["options"]} <= {c["name"] for c in j["result"]["candidates"]}
    j = _run(client, "wx", {"kind": "names_ai", "target": "hero"})
    assert j["target"] == "hero" and j["result"]["options"]
    assert _saved("wx") == before
    assert client.post("/api/projects/wx/jobs", json={"kind": "names_ai", "target": "nobody"}).status_code == 400


def test_style_learn_job_writes_only_suggestion_field(client):
    p = _edited_project()
    client.post("/api/projects", json={"name": "b", "meta": {"title": "등대", "target_episodes": 10}})
    cur = client.get("/api/projects/b").json()
    cur["episodes"] = [json.loads(e.model_dump_json()) for e in p.episodes]
    client.put("/api/projects/b", json=cur)
    j = _run(client, "b", {"kind": "style_learn"})
    got = store.load("b")
    assert j["result"]["style_learning"]["suggestions"] and got.style_learning is not None
    assert got.style.banned_phrases == []  # 찾기만 하고 바꾸지 않는다
    r = client.post("/api/projects/b/style/learn/apply", json={"picks": [0]}).json()
    assert r["applied"] == 1  # 고르기는 디스크에 둔 후보로 한다


def test_style_learn_job_refuses_short_history(client):
    client.post("/api/projects", json={"name": "c", "meta": {"title": "등대", "target_episodes": 10}})
    r = client.post("/api/projects/c/jobs", json={"kind": "style_learn"})
    assert r.status_code == 400 and "수정 기록" in r.json()["detail"]


def test_style_example_job_writes_example_field(client):
    client.post("/api/projects", json={"name": "a", "meta": {"title": "등대", "target_episodes": 10}})
    r = client.post("/api/projects/a/jobs", json={"kind": "style_example"})
    assert r.status_code == 400 and "문체가 비어" in r.json()["detail"]
    cur = client.get("/api/projects/a").json()
    cur["style"]["dos"] = ["짧은 문장으로 끊어 쓴다"]
    client.put("/api/projects/a", json=cur)
    j = _run(client, "a", {"kind": "style_example", "note": "다툼"})
    assert "다툼" in j["result"]["style_example"]["text"]
    got = store.load("a")
    assert got.style_example is not None and "다툼" in got.style_example.text
    assert got.style.dos == ["짧은 문장으로 끊어 쓴다"]


def test_job_target_in_public_and_busy_key():
    import threading

    go = threading.Event()
    a = jobs.start(".t", "char_body", None, "a", lambda j: go.wait(5), target="x")
    b = jobs.start(".t", "char_body", None, "b", lambda j: go.wait(5), target="y")
    try:
        assert a.public()["target"] == "x" and b.id != a.id
        try:
            jobs.start(".t", "char_body", None, "c", lambda j: None, target="x")
            raise AssertionError("같은 대상은 Busy 여야 해요")
        except jobs.Busy as e:
            assert e.job.id == a.id
    finally:
        go.set()


FILES = __import__("re").findall(r'src="/static/([a-z-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


KINDS = {"char_body": ["cast"], "char_voice": ["cast"], "char_look": ["cast"], "statwin_suggest": ["statwin"],
         "statwin_init": ["statwin"], "names_ai": ["setup", "arc", "review"], "style_learn": ["style"], "style_example": ["style"]}


@needs_node
def test_js_registers_pages_messages_links_and_buttons():
    """옮긴 작업마다 다시 그릴 화면 · 끝 알림 · '가서 보기' 주소 · 결과 놓기 · 잠글 버튼이 있다."""
    got = run_js(FILES, """(() => {
      const j = (kind) => ({ kind, project: '등대', label: '앨리 신체 프로필 제안', target: 'ally', ep: null, result: {} });
      const kinds = %s;
      return {
        pages: Object.fromEntries(kinds.map((k) => [k, JOB_PAGES[k]])),
        msg: kinds.filter((k) => { const m = JOB_DONE_MSG[k]; return !(typeof m === 'function' ? m(j(k)) : m); }),
        link: kinds.filter((k) => !(JOB_LINK[k] && JOB_LINK[k](j(k)).startsWith('#/p/'))),
        result: kinds.filter((k) => typeof JOB_RESULT[k] !== 'function'),
        btns: Object.keys(JOB_BTNS).sort(),
        screen: [...SCREEN_ONLY_JOBS].sort(),
        body: JOB_LINK.char_body(j('char_body')),
      };
    })()""" % json.dumps(list(KINDS)), {})
    assert got["pages"] == KINDS
    assert got["msg"] == [] and got["link"] == [] and got["result"] == []
    assert got["btns"] == sorted(["bodyAI", "voiceAI", "lookAI", "swSuggest", "swInitAI", "nameAI", "placeAI", "learnRun", "styleExampleWrite",
                                  "illMake", "atlasGenSuggest", "atlasSort",  # 뒤 여덟은 02c (test_ai_jobs_more.py)
                                  "rsSample", "rsStage", "rsCheck", "rsBudget", "rsCompare"])
    assert got["screen"] == sorted(["char_body", "char_voice", "char_look", "statwin_suggest", "statwin_init", "names_ai", "atlas_suggest", "atlas_sort"])
    assert got["body"] == "#/p/%EB%93%B1%EB%8C%80/cast/ally"


@needs_node
def test_js_job_target_keys():
    got = run_js(FILES, """(() => {
      S.name = 'a';
      S.jobs = [{ id: '1', status: 'running', project: 'a', kind: 'char_body', ep: null, target: 'ally' }];
      return [jobKey('char_body', null, 'ally'), jobKey('state', 3), !!jobFor('char_body', null, 'a', 'ally'),
        !!jobFor('char_body', null, 'a', 'hero'), !!jobFor('char_body'), jobBtn('char_body', null, '받기', 'a', 'hero').label,
        jobBtn('char_body', null, '받기', 'a', 'ally').attr.includes('aria-disabled')];
    })()""", {})
    assert got == ["char_body::ally", "state:3", True, False, True, "받기", True]


@needs_node
def test_js_voice_result_fills_field_or_waits():
    """서술 말투 초안은 칸에 넣는다. 시작한 뒤 작가가 그 칸을 고쳤으면 덮지 않고 알림의 '넣기'로 넣는다."""
    p = {"characters": [{"id": "ally", "name": "앨리", "narration_voice": "옛 말투"}], "episodes": []}
    got = run_js(FILES, """(() => {
      S.project = data.p;
      const job = (id) => ({ id, kind: 'char_voice', label: '앨리 서술 말투 초안', target: 'ally', result: { voice: '새 말투', note: '메모' } });
      S.jobArgs = { a: { opt: { before: '옛 말투' } }, b: { opt: { before: '옛 말투' } } };
      const put = JOB_RESULT.char_voice(job('a'));
      const first = P().characters[0].narration_voice;
      P().characters[0].narration_voice = '작가가 고친 말투';
      const held = JOB_RESULT.char_voice(job('b'));
      const kept = P().characters[0].narration_voice;
      held.actions[0].run();
      return [put.msg, first, S.voices.ally, held.msg, held.actions[0].label, kept, P().characters[0].narration_voice];
    })()""", {"p": p})
    assert got[0].startswith("앨리 서술 말투 초안을 칸에 넣었어요") and got[1] == "새 말투" and got[2] == "메모"
    assert "넣지 않았어요" in got[3] and got[4] == "넣기"
    assert got[5] == "작가가 고친 말투" and got[6] == "새 말투"


@needs_node
def test_js_style_learning_result_takes_only_that_field():
    """문체 규칙 후보는 그 칸만 받고 받은 판도 맞춘다. 저장하지 않은 문체 칸은 그대로 두고, 다음 저장에 그 칸을 보내지 않는다."""
    got = run_js(FILES, """(() => {
      S.project = data.p;
      projectBase = { keys: new Map([['style', JSON.stringify(data.p.style)], ['style_learning', 'null']]), plots: new Map(), eps: new Map() };
      P().style.dos = ['고치던 칸'];
      const r = JOB_RESULT.style_learn({ result: { style_learning: { suggestions: [{ kind: 'do' }] } } });
      return [r.msg, P().style_learning.suggestions.length, P().style.dos, projectBase.keys.get('style_learning') === JSON.stringify(P().style_learning)];
    })()""", {"p": {"style": {"dos": []}, "style_learning": None, "episodes": []}})
    assert got == ["규칙 후보 1개를 찾았어요. 고른 것만 넣어요.", 1, ["고치던 칸"], True]


@needs_node
def test_js_names_and_statwin_results_land_in_draft_slots():
    got = run_js(FILES, """(() => {
      S.project = { characters: [], episodes: [] };
      JOB_RESULT.names_ai({ target: 'hero', result: { style: 'wuxia', detected: 'wuxia', candidates: [], options: [{ name: '진무', reason: '굳셈' }] } });
      JOB_RESULT.names_ai({ target: '', result: { style: 'wuxia', detected: 'wuxia', candidates: [], options: [] } });
      const none = JOB_RESULT.statwin_suggest({ result: { options: [] } });
      JOB_RESULT.statwin_init({ result: { names: ['레벨'], characters: [] } });
      return [S.names['c:hero'].ai, S.names['c:hero'].options[0].name, !!S.names.place, none.msg, S.swInitSug.names];
    })()""", {})
    assert got == [True, "진무", True, "쓸 만한 꾸미기 안이 오지 않았어요. 다시 받아 보세요", ["레벨"]]
