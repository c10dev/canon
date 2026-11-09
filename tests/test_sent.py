"""보낸 집필 프롬프트 기록 (canon/sent.py): 본문으로 채택한 집필 호출의 요청을 sent/<화>.json.gz 에 남긴다.
mock LLM 의 본문 응답만 바꾼다. 실행: python -m pytest tests/test_sent.py"""
import gzip

from canon import llm as llm_mod
from canon import mock, pipeline, prompts, sent, settings, store
from canon.schema import RewriteRequest

from .test_meta_cut import BODY, JOB, _reply, _write
from .test_passage import _ep
from .test_plot_chat import _project
from .test_web import _wait
from .test_autorun import demo  # noqa: F401  (pytest fixture)


def test_write_job_keeps_record_and_prompt_view(client, monkeypatch):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    r = client.get("/api/projects/lh/episodes/1/prompt").json()
    assert r["source"] == "rebuilt" and not r["has_sent"] and r["note"] == ""  # 쓰기 전: 보낼 프롬프트 미리보기

    _reply(monkeypatch, BODY)
    _write(client)
    assert not (store.project_dir("lh") / "project.json").read_text(encoding="utf-8").count("sent_prompt")
    f = store.sent_path("lh", 1)
    assert f.exists() and gzip.decompress(f.read_bytes())  # gzip 으로 남긴다
    rec = sent.read("lh", 1)
    p = store.load("lh")
    assert rec.kind == "write" and rec.model == "mock:mock" and rec.attempt == 1 and rec.retries == []
    assert rec.system == prompts.writer_system(p)
    assert sent.matches(rec, p.episode(1).text)
    assert rec.tail == ""  # 가짜 응답은 정책 줄을 붙이지 않는다

    r = client.get("/api/projects/lh/episodes/1/prompt").json()
    assert r["source"] == "sent" and r["has_sent"] and r["at"] == rec.at
    assert r["prompt"] == rec.prompt
    assert "본문 쓰기 때 보낸 그대로예요" in r["note"] and "1번째 호출" in r["note"] and "바뀌었어요" not in r["note"]
    r = client.get("/api/projects/lh/episodes/1/prompt?source=rebuilt").json()
    assert r["source"] == "rebuilt" and r["has_sent"] and "다를 수 있어요" in r["note"]

    client.put("/api/projects/lh/episodes/1/text", json={"text": BODY + "\n\n덧붙인 문단."})  # 작가가 고친다
    r = client.get("/api/projects/lh/episodes/1/prompt").json()
    assert r["source"] == "sent" and "그 뒤로 본문이 바뀌었어요" in r["note"]


def test_no_record_says_rebuilt(client):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    p = store.load("lh")
    p.episode(1).text, p.episode(1).status = BODY, "written"  # 기록 없이 들어온 본문 (예전 작품 · 가져오기)
    store.save("lh", p)
    r = client.get("/api/projects/lh/episodes/1/prompt").json()
    assert r["source"] == "rebuilt" and not r["has_sent"] and "보낸 프롬프트 기록이 없어요" in r["note"]


def test_retry_reasons_and_attempt(client, monkeypatch):
    """한글이 적은 응답을 버리고 두 번째 호출을 받으면 시도 번호 2, 까닭 thought 를 남긴다."""
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    replies = iter(["I am thinking about the scene in English first." * 20, BODY])
    monkeypatch.setattr(mock.MockLLM, "text", lambda self, system, prompt: next(replies))
    _write(client)
    rec = sent.read("lh", 1)
    assert rec.attempt == 2 and [(r.call, r.reason) for r in rec.retries] == [(1, "thought")]
    note = client.get("/api/projects/lh/episodes/1/prompt").json()["note"]
    assert "2번째 호출" in note and "한글이 적은 응답 1번" in note


def test_rewrite_waits_until_adopted(client, monkeypatch):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    _reply(monkeypatch, BODY)
    _write(client)
    first = sent.read("lh", 1)
    new = BODY.replace("코미는", "코미가")
    _reply(monkeypatch, new)
    j = _wait(client, client.post(JOB, json={"kind": "write", "ep": 1, "rewrite": {"feedback": "조용히"}}).json()["id"])
    assert j["status"] == "done", j.get("error")
    assert sent.read("lh", 1) == first  # 새 판은 고르기 전에는 지금 기록을 바꾸지 않는다
    assert sent._read("lh", 1).candidate.kind == "rewrite"
    e = _ep(client.post("/api/projects/lh/episodes/1/candidate/adopt").json())
    rec = sent.read("lh", 1)
    assert rec.kind == "rewrite" and sent.matches(rec, e["text"]) and sent._read("lh", 1).candidate is None

    _reply(monkeypatch, BODY.replace("코미는", "코미도"))
    _wait(client, client.post(JOB, json={"kind": "write", "ep": 1, "rewrite": {"feedback": "다시"}}).json()["id"])
    client.delete("/api/projects/lh/episodes/1/candidate")
    assert sent.read("lh", 1) == rec and sent._read("lh", 1).candidate is None  # 버린 판의 기록은 지운다


def test_polish_counts_calls_across_tries(monkeypatch):
    """다듬기가 대사 줄을 바꾼 판을 버리고 다시 부르면 시도 번호를 이어 세고 까닭 polish 를 남긴다."""
    from .test_insert import _short

    p = _short()
    ep = p.episode(1)
    ep.text = "\"안녕.\"\n\n" + BODY
    replies = iter(["\"잘 가.\"\n\n" + BODY, "\"안녕.\"\n\n" + BODY.replace("코미는", "코미가")])
    monkeypatch.setattr(mock.MockLLM, "text", lambda self, system, prompt: next(replies))
    got: list = []
    pipeline.polish_episode(mock.MockLLM(), p, 1, sent=got)
    assert got[0].kind == "polish" and got[0].attempt == 2
    assert [(r.call, r.reason) for r in got[0].retries] == [(1, "polish")]


def test_scored_and_unsaved_calls_leave_no_file(client, monkeypatch):
    """_write 는 재료만 채운다. 기록을 넘기지 않는 호출(비교 · 실험)은 파일을 만들지 않는다."""
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    _reply(monkeypatch, BODY)
    pipeline.write_episode(mock.MockLLM(), store.load("lh"), 1)
    assert not store.sent_path("lh", 1).exists() and sent.episodes("lh") == []


def test_mask_keys(monkeypatch):
    monkeypatch.setattr(settings, "api_key", lambda: ("my-secret-gemini-value", "env"))
    monkeypatch.setattr(settings, "anthropic_key", lambda: ("", "default"))
    text, k = sent.mask("가 my-secret-gemini-value 나 AIza" + "x" * 35 + " 다 sk-ant-api03-" + "y" * 20)
    assert k == 3 and "secret" not in text and "AIza" not in text and "sk-ant" not in text
    rec = sent.record(mock.MockLLM(), "시스템 my-secret-gemini-value", "요청", "", 1, [])
    assert rec.masked == 1 and "secret" not in rec.system


def test_tail_for_real_backend(monkeypatch):
    from canon import usage

    monkeypatch.setattr(usage, "model_id", lambda llm: "gemini:gemini-4-argon")
    rec = sent.record(object(), "s", "요청", "", 1, [])
    assert rec.model == "gemini:gemini-4-argon" and rec.tail.endswith(llm_mod.POLICY_NOTE)


def test_moved_record_writes_to_new_number(client):
    """화를 넣어 옮긴 기록을 다시 쓰면 새 번호 파일에 쓴다 (파일 안의 옛 번호를 따르지 않는다)."""
    from .test_insert import _short

    store.save("mv", _short())
    sent.keep("mv", 7, sent.SentPrompt(prompt="7화 요청"), "7화 본문")
    assert client.post("/api/projects/mv/episodes/insert", json={"at": 6}).status_code == 200
    sent.hold("mv", 8, sent.SentPrompt(prompt="새 판"), "새 판 본문", "v2")
    assert sent.episodes("mv") == [8]
    assert sent.read("mv", 8).prompt == "7화 요청" and sent._read("mv", 8).candidate.version == "v2"


def test_head_chars_only_when_prefix():
    rec = sent.record(mock.MockLLM(), "s", "앞부분 뒤", "앞부분", 1, [])
    assert rec.head == "앞부분" and not rec.family  # mock 은 캐시 가족 경계를 받지 않는다
    assert sent.record(mock.MockLLM(), "s", "다른 요청", "앞부분", 1, []).head_chars == 0


def test_renumber_and_delete_move_records(client):
    """화를 넣고 빼면 기록도 새 번호로 옮긴다. 뺀 화 · 본문만 지운 화의 기록은 sent/removed/ 에 남긴다."""
    from .test_insert import _short

    store.save("side", _short())
    rec = sent.SentPrompt(prompt="요청")
    for n in (6, 7, 9):
        sent.keep("side", n, rec.model_copy(update={"prompt": f"{n}화 요청"}), f"{n}화 본문")
    r = client.post("/api/projects/side/episodes/insert", json={"at": 7})
    assert r.status_code == 200, r.text
    assert any("보낸 프롬프트 기록도 새 화 번호로" in x for x in r.json()["notes"])
    assert sent.episodes("side") == [6, 8, 10] and sent.read("side", 8).prompt == "7화 요청"
    r = client.delete("/api/projects/side/episodes/8")
    assert r.status_code == 200, r.text
    assert sent.episodes("side") == [6, 9] and sent.read("side", 9).prompt == "9화 요청"
    kept = store.project_dir("side") / "sent" / store.SIDE_REMOVED
    assert [f.name.split(".")[0] for f in kept.iterdir()] == ["8"] and all(f.name.endswith(".json.gz") for f in kept.iterdir())

    assert sent.set_aside("side", 6).startswith("sent/removed/6.") and sent.read("side", 6) is None
    assert sent.set_aside("side", 6) == ""


def test_delete_keep_plot_sets_record_aside(client, monkeypatch):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    _reply(monkeypatch, BODY)
    _write(client)
    r = client.post("/api/projects/lh/episodes/1/delete", json={"keep_plot": True})
    assert r.status_code == 200, r.text
    assert any("보낸 프롬프트 기록은 따로 남겨 뒀어요: sent/removed/" in x for x in r.json()["notes"])
    assert sent.read("lh", 1) is None


def test_old_or_broken_file_reads_empty():
    from .test_insert import _short

    store.save("bad", _short())
    f = store.sent_path("bad", 2)
    f.parent.mkdir(parents=True)
    f.write_bytes(b"not gzip")
    assert sent.read("bad", 2) is None
    sent.keep("bad", 2, None, "본문")  # 기록 없이 쓴 본문은 아무것도 하지 않는다
    assert f.read_bytes() == b"not gzip"
    sent.hold("bad", 3, None, "본문", "v1")
    assert not store.sent_path("bad", 3).exists()
    assert RewriteRequest(mode="polish").mode == "polish"


def test_autorun_keeps_write_then_polish_record(demo):
    """자동 집필은 쓴 본문의 기록을 남기고, 다듬은 판으로 바꾸면 다듬기 기록으로 바꾼다."""
    from canon import autorun

    from .test_autorun import Policy

    run = autorun.start(demo, 1, False, Policy(polish=True), foreground=True)
    assert run.status == "done"
    rec = sent.read(demo, 1)
    assert rec.kind == "polish" and sent.matches(rec, store.load(demo).episode(1).text)
    autorun.start(demo, 2, False, Policy(), foreground=True)
    assert sent.read(demo, 2).kind == "write" and sent.episodes(demo) == [1, 2]
