"""AI 답 흘려 보이기 (docs/ux 05): 백엔드의 text_stream, 작업의 부분 글(Job.partial), 본문 쓰기 작업.

실제 모델은 부르지 않는다. mock 과 가짜 SDK 클라이언트만 쓴다."""
import io
import json
import re
import threading
from types import SimpleNamespace

import pytest

from canon import cancel, jobs, llm, mock, store, usage
from canon.claude import ClaudeAPILLM
from canon.llm import GeminiLLM, LocalLLM, family_text
from canon.schema import Project

from .jsvm import STATIC, dump, episode, needs_node, run_js
from .test_passage import _project
from .test_web import _wait


# ---------- family_text: 흘려 받는 백엔드만 text_stream, 나머지는 text ----------

class _TextOnly:
    """text 만 아는 백엔드 (Claude Code, 배치, 시험용 가짜 LLM)."""

    def __init__(self):
        self.calls = []

    def text(self, system, prompt):
        self.calls.append("text")
        return "다 쓴 글"


def test_family_text_uses_text_without_text_stream():
    seen = []
    b = _TextOnly()
    assert family_text(b, "s", "p", "", seen.append) == "다 쓴 글"
    assert b.calls == ["text"] and seen == []  # 부분 글 없이 지금처럼 다 끝난 뒤 한 번에


def test_family_text_streams_when_backend_can():
    seen = []
    out = family_text(mock.MockLLM(), "s", "본문을 써 주세요", "", seen.append)
    assert seen and seen[-1] == out  # 마지막 조각은 다 받은 글
    assert all(seen[i] == seen[i + 1][:len(seen[i])] for i in range(len(seen) - 1))  # 늘 앞 글을 품고 늘어난다
    assert len(seen) > 1
    assert family_text(mock.MockLLM(), "s", "본문을 써 주세요", "") == out  # on_chunk 가 없으면 text


# ---------- Gemini: generate_content_stream ----------

def _chunk(text, reason=None, usage_meta=None):
    cands = [SimpleNamespace(finish_reason=SimpleNamespace(name=reason) if reason else None)]
    return SimpleNamespace(text=text, usage_metadata=usage_meta, candidates=cands, prompt_feedback=None)


def _gemini(chunks):
    g = object.__new__(GeminiLLM)
    asked = []

    def stream(model, contents, config):
        asked.append(contents)
        yield from chunks

    def whole(**kw):
        raise AssertionError("흘려 받을 때는 generate_content 를 부르지 않는다")
    g.client = SimpleNamespace(models=SimpleNamespace(generate_content_stream=stream, generate_content=whole))
    g.model = "gemini-4-argon"
    return g, asked


def test_gemini_text_stream_sends_growing_text_and_records_once(monkeypatch):
    rows = []
    monkeypatch.setattr(usage, "record", lambda *a, **k: rows.append(k))
    meta = SimpleNamespace(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=0, cached_content_token_count=0)
    g, asked = _gemini([_chunk("바람이 "), _chunk(None), _chunk("불었다."), _chunk("", "STOP", meta)])
    seen = []
    assert g.text_stream("s", "요청", seen.append) == "바람이 불었다."
    assert seen == ["바람이 ", "바람이 불었다."]  # 글 없는 조각은 부르지 않는다
    assert g.last_finish == "STOP" and g.last_usage["completion_tokens"] == 5
    assert len(rows) == 1 and rows[0].get("ok", True)  # 사용량은 다 받은 뒤 한 번
    assert asked == [llm.with_note("요청")]


def test_gemini_text_stream_keeps_the_cut_reason():
    g, _ = _gemini([_chunk("끊긴 "), _chunk("글", "MAX_TOKENS")])
    assert g.text_stream("s", "요청", lambda t: None) == "끊긴 글"
    assert g.last_finish == "MAX_TOKENS"  # pipeline.was_cut 이 끊김을 안다


def test_gemini_text_stream_stops_between_chunks(monkeypatch):
    rows = []
    monkeypatch.setattr(usage, "record", lambda *a, **k: rows.append(k))
    stop = threading.Event()
    g, _ = _gemini([_chunk("하나"), _chunk("둘"), _chunk("셋", "STOP")])
    seen = []

    def on(t):
        seen.append(t)
        stop.set()  # 첫 조각을 받은 뒤 작가가 멈췄다
    token = cancel.current.set(stop)
    try:
        with pytest.raises(cancel.Cancelled):
            g.text_stream("s", "요청", on)
    finally:
        cancel.current.reset(token)
    assert seen == ["하나"]
    assert len(rows) == 1 and rows[0]["ok"] is False


# ---------- Claude API: 이미 도는 스트림의 text 이벤트 ----------

class _Stream:
    def __init__(self, events, msg):
        self.events, self.msg = events, msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return self.msg


def test_claude_api_text_stream(monkeypatch):
    rows = []
    monkeypatch.setattr(usage, "record", lambda *a, **k: rows.append(k))
    c = object.__new__(ClaudeAPILLM)
    c.model, c.effort = "claude-test", ""
    text = "바람이 불었다."
    msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
                          usage=SimpleNamespace(input_tokens=3, output_tokens=4, cache_read_input_tokens=0, cache_creation_input_tokens=0))
    events = [SimpleNamespace(type="message_start"), SimpleNamespace(type="text", text="바람이 "),
              SimpleNamespace(type="text", text="불었다."), SimpleNamespace(type="message_stop")]
    c.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **req: _Stream(events, msg))))
    seen = []
    assert c.text_stream("s", "요청", seen.append) == text
    assert seen == ["바람이 ", "바람이 불었다."] and len(rows) == 1


# ---------- 로컬(OpenAI 호환): stream=True 의 SSE ----------

def _sse(*events):
    lines = [f"data: {json.dumps(e, ensure_ascii=False)}\n".encode() for e in events] + [b"data: [DONE]\n"]
    return io.BytesIO(b"".join(lines))


def test_local_text_stream_hides_think_and_reads_usage(monkeypatch):
    rows = []
    monkeypatch.setattr(usage, "record", lambda *a, **k: rows.append(a[1]))
    bodies = []

    def urlopen(req, timeout=None):
        bodies.append(json.loads(req.data))
        return _sse({"choices": [{"delta": {"content": "<think>생각"}}]}, {"choices": [{"delta": {"content": "</think>바람이 "}}]},
                    {"choices": [{"delta": {"content": "불었다."}, "finish_reason": "stop"}]},
                    {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    loc = LocalLLM(base_url="http://x/v1", model="m", api_key="", sampling={"temperature": 0.7}, timeout=5)
    seen = []
    assert loc.text_stream("s", "요청", seen.append) == "바람이 불었다."
    assert seen == ["바람이 ", "바람이 불었다."]  # 닫히지 않은 생각 블록은 보이지 않는다
    assert bodies[0]["stream"] is True and bodies[0]["temperature"] == 0.7
    assert loc.last_finish == "stop" and rows[0]["prompt_tokens"] == 7 and len(rows) == 1


def test_local_text_stream_retries_without_stream_options(monkeypatch):
    bodies = []

    def urlopen(req, timeout=None):
        body = json.loads(req.data)
        bodies.append(body)
        if "stream_options" in body:
            raise llm.urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(b"unknown field stream_options"))
        return _sse({"choices": [{"delta": {"content": "글"}, "finish_reason": "stop"}]})
    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    loc = LocalLLM(base_url="http://x/v1", model="m", api_key="", sampling={}, timeout=5)
    assert loc.text_stream("s", "요청", lambda t: None) == "글"
    assert len(bodies) == 2 and "stream_options" not in bodies[1]


# ---------- 작업의 부분 글 ----------

def test_job_partial_only_while_running():
    gate = threading.Event()
    job = jobs.start(".stream", "write", 1, "본문", lambda j: (j.set_partial("쓰는 중"), gate.wait(5)))
    for _ in range(100):
        if job.partial:
            break
        threading.Event().wait(0.01)
    assert job.public()["partial"] == "쓰는 중"
    gate.set()
    for _ in range(200):
        if not job.alive:
            break
        threading.Event().wait(0.01)
    assert job.status == "done" and job.partial == "" and job.public()["partial"] == ""
    job.set_partial("늦은 조각")
    assert job.partial == ""  # 끝난 작업은 부분 글을 받지 않는다


def _watch(monkeypatch, then=None):
    """Job.set_partial 이 받은 값과 그때 작업 응답(public)의 partial 을 모은다. then(job, text) 은 받은 뒤 부른다."""
    seen = []
    real = jobs.Job.set_partial

    def spy(self, text):
        real(self, text)
        seen.append((text, self.public()["partial"]))
        if then:
            then(self, text)
    monkeypatch.setattr(jobs.Job, "set_partial", spy)
    return seen


def test_write_job_streams_then_clears(client, monkeypatch):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    seen = _watch(monkeypatch)
    j = _wait(client, client.post("/api/projects/lh/jobs", json={"kind": "write", "ep": 1, "board": "none"}).json()["id"])
    assert j["status"] == "done", j.get("error")
    grown = [t for t, _ in seen if t]
    assert len(grown) > 1 and all(a == b[:len(a)] for a, b in zip(grown, grown[1:]))  # 늘어난다
    assert all(shown == t for t, shown in seen if t)  # 도는 동안 작업 응답에 실린다
    assert seen[-1][0] == "" and j["partial"] == ""  # 끝나면 비운다
    text = store.load("lh").episode(1).text
    assert text and text in grown[-1]  # 저장한 본문은 흘려 받은 글 (앞뒤 작업 설명만 뗀다)


def test_write_job_stop_drops_partial(client, monkeypatch):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    monkeypatch.setenv("CANON_MOCK_STREAM_DELAY", "0.02")
    seen = _watch(monkeypatch, lambda job, t: t and jobs.stop(job.id))  # 첫 조각을 받자 작가가 멈춘다
    j = _wait(client, client.post("/api/projects/lh/jobs", json={"kind": "write", "ep": 1, "board": "none"}).json()["id"])
    assert j["status"] == "cancelled" and j["partial"] == ""
    assert len([t for t, _ in seen if t]) == 1  # 멈춘 뒤에는 조각을 더 받지 않는다
    for _ in range(200):
        if not jobs.get(j["id"]).alive:
            break
        threading.Event().wait(0.01)
    assert store.load("lh").episode(1).text == ""  # 흘려 보인 글은 저장한 것이 아니다


def test_write_job_without_text_stream_takes_the_old_path(client, monkeypatch):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    monkeypatch.delattr(mock.MockLLM, "text_stream")  # Claude Code · 배치처럼 흘려 받지 못하는 백엔드
    seen = _watch(monkeypatch)
    j = _wait(client, client.post("/api/projects/lh/jobs", json={"kind": "write", "ep": 1, "board": "none"}).json()["id"])
    assert j["status"] == "done", j.get("error")
    assert [t for t, _ in seen if t] == []  # 부분 글 없이 다 끝난 뒤 한 번에
    assert store.load("lh").episode(1).text


# ---------- 집필 화면: 읽기 전용 미리보기 ----------

def _js_project():
    p = Project()
    p.meta.target_episodes = 3
    p.episodes = [episode(1, text="본문", status="finalized"), episode(2, status="confirmed")]
    return dump(p)


def _index_files():
    return re.findall(r'src="/static/([a-z]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


JOB = "{ id: 'j1', status: 'running', project: 'lh', kind: 'write', ep: 2, label: '2화 본문', started: 0, done: 0, total: 1, partial: %s }"


@needs_node
def test_write_screen_draws_partial_in_read_only_preview():
    got = run_js(_index_files(), """(() => {
      S.project = data; S.name = 'lh'; S.route = ['p', 'lh', 'write', '2'];
      render = () => {};
      S.jobs = [%s];
      const waiting = viewWrite(2);
      S.jobs = [%s];
      const shown = viewWrite(2);
      S.jobs = [];
      return { waiting, shown, idle: viewWrite(2) };
    })()""" % (JOB % "''", JOB % "'바람이 <불었다>'"), _js_project())
    card = re.search(r'<section class="card w-stream"[^>]*>.*?</section>', got["shown"], re.S).group(0)
    assert "바람이 &lt;불었다&gt;" in card and 'data-stream-text' in card and "hidden" not in card.split(">")[0]
    assert "<textarea" not in card and "data-keep" not in card and "aria-live" not in card  # 본문 칸도 낭독 칸도 아니다
    assert re.search(r'<section class="card w-stream"[^>]* hidden>', got["waiting"])  # 부분 글이 없으면 숨긴다
    assert "w-stream" not in got["idle"]  # 도는 쓰기 작업이 없으면 그리지 않는다


@needs_node
def test_poll_patches_preview_without_redraw():
    got = run_js(_index_files(), """(async () => {
      S.project = data; S.name = 'lh'; S.route = ['p', 'lh', 'write', '2'];
      let renders = 0;
      render = () => { renders += 1; }; renderHub = () => {}; notifyJobs = () => {}; finishJob = async () => {};
      const box = { textContent: '', scrollHeight: 100, scrollTop: 0, clientHeight: 100 };
      const count = { textContent: '' };
      const card = { hidden: true, querySelector: (q) => (q === '[data-stream-text]' ? box : count) };
      document = { getElementById: (id) => (id === 'w-stream-2' ? card : null), activeElement: null, getSelection: () => null };
      const reply = [];
      api = async () => reply.shift();
      S.jobs = [%s]; S.jobsSeen = new Set();
      const out = [];
      for (const partial of ['바람이 ', '바람이 불었다.']) {
        reply.push([{ ...S.jobs[0], partial }]);
        await pollJobs();
        out.push([box.textContent, count.textContent, card.hidden]);
      }
      return { out, renders };
    })()""" % (JOB % "''"), _js_project())
    assert got["out"] == [["바람이 ", "4자", False], ["바람이 불었다.", "8자", False]]
    assert got["renders"] == 0  # 부분 글이 늘어도 화면 전체를 다시 그리지 않는다
