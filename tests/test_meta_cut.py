"""쓰기가 뗀 작업 설명 문단 (Episode.meta_cut · TextVersion.meta_cut): 남기기, 다시 생성 판을 따라가기, 본문에 되살리기 · 지우기.
mock LLM 의 본문 응답만 바꾼다. 실행: python -m pytest tests"""
import contextlib
import io

from canon import metatail, mock, pipeline, prompts, store
from canon.cli import main
from canon.schema import Episode, MetaCut

from .test_metatail import BODY as SHORT, TAIL
from .test_passage import _ep
from .test_plot_chat import _project
from .test_restate import _two_done
from .jsvm import needs_node, run_js
from .test_web import _wait, client  # noqa: F401  (pytest fixture)

HEAD = "네, 1화 본문입니다."
BODY = SHORT + "\n\n" + SHORT.replace("코미", "미코")  # 뗀 문단이 본문보다 훨씬 적어야 응답 전체를 메타로 보지 않는다 (metatail.whole)
JOB = "/api/projects/lh/jobs"


def _reply(monkeypatch, text):
    monkeypatch.setattr(mock.MockLLM, "text", lambda self, system, prompt: text)


def _write(client, **extra):
    j = _wait(client, client.post(JOB, json={"kind": "write", "ep": 1, **extra}).json()["id"])
    assert j["status"] == "done", j.get("error")
    return client.get("/api/projects/lh").json()


def test_old_files_and_parts():
    e = Episode.model_validate({"plot": {"number": 1, "act": "기", "title": "", "summary": "", "events": [], "characters": [],
                                         "emotional_shift": "", "ending_hook": ""}, "versions": [{"id": "v1"}]})
    assert e.meta_cut == [] and e.versions[0].meta_cut == []
    assert metatail.parts(HEAD + "\n\n" + BODY + "\n\n" + TAIL) == (BODY, [HEAD], [TAIL])
    assert metatail.split(HEAD + "\n\n" + BODY + "\n\n" + TAIL) == (BODY, [HEAD, TAIL])  # 옛 모양은 그대로
    assert metatail.parts(BODY) == (BODY, [], [])


def test_write_keeps_cut_then_restore_and_drop(client, monkeypatch):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    _reply(monkeypatch, HEAD + "\n\n" + BODY + "\n\n" + TAIL)
    e = _ep(_write(client))
    assert e["text"] == BODY
    assert e["meta_cut"] == [{"text": HEAD, "at": "head"}, {"text": TAIL, "at": "tail"}]

    e = _ep(client.post("/api/projects/lh/episodes/1/meta-cut/1/restore").json())
    assert e["text"] == BODY + "\n\n" + TAIL and e["meta_cut"] == [{"text": HEAD, "at": "head"}]
    edit = e["edits"][-1]
    assert edit["instruction"] == "뗀 작업 설명 되살리기"
    e = _ep(client.post(f"/api/projects/lh/episodes/1/edits/{edit['id']}/undo").json())
    assert e["text"] == BODY  # 수정 기록으로 되돌린다

    e = _ep(client.post("/api/projects/lh/episodes/1/meta-cut/0/restore").json())
    assert e["text"] == HEAD + "\n\n" + BODY and e["meta_cut"] == []
    r = client.post("/api/projects/lh/episodes/1/meta-cut/0/restore")
    assert r.status_code == 400 and "뗀 문단이 없어요" in r.json()["detail"]

    _reply(monkeypatch, BODY + "\n\n" + TAIL)
    client.put("/api/projects/lh/episodes/1/text", json={"text": ""})
    e = _ep(_write(client))
    assert e["meta_cut"] == [{"text": TAIL, "at": "tail"}]
    e = _ep(client.delete("/api/projects/lh/episodes/1/meta-cut/0").json())
    assert e["meta_cut"] == [] and e["text"] == BODY  # 지우기는 본문을 바꾸지 않는다


def test_rewrite_version_carries_cut(client, monkeypatch):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    _reply(monkeypatch, BODY + "\n\n" + TAIL)
    _write(client)
    new = BODY.replace("코미는", "코미가")
    _reply(monkeypatch, HEAD + "\n\n" + new)
    e = _ep(_write(client, rewrite={"feedback": "조용히"}))
    assert e["candidate"]["meta_cut"] == [{"text": HEAD, "at": "head"}]
    assert e["meta_cut"] == [{"text": TAIL, "at": "tail"}]  # 고르기 전에는 지금 본문 것 그대로

    p = store.load("lh")
    pipeline.adopt_candidate(p, 1)
    ep = p.episode(1)
    assert ep.text == new and ep.meta_cut == [MetaCut(text=HEAD, at="head")]
    prev = next(v for v in ep.versions if v.kind == "previous")
    assert prev.meta_cut == [MetaCut(text=TAIL, at="tail")]
    pipeline.restore_version(p, 1, prev.id)
    assert ep.text == BODY and ep.meta_cut == [MetaCut(text=TAIL, at="tail")]


def test_cli_write_and_rewrite_keep_cut(client, monkeypatch):
    _project(client)
    client.post("/api/projects/lh/episodes/1/confirm")
    _reply(monkeypatch, BODY + "\n\n" + TAIL)
    with contextlib.redirect_stdout(io.StringIO()):
        main(["write", "lh", "1"])
    assert store.load("lh").episode(1).meta_cut == [MetaCut(text=TAIL, at="tail")]
    _reply(monkeypatch, HEAD + "\n\n" + BODY.replace("코미는", "코미가"))
    monkeypatch.setattr("builtins.input", lambda *a: "n")  # 새 판으로 바꿀지 물으면 '아니요': 고르기 대기로 남는다
    with contextlib.redirect_stdout(io.StringIO()):
        main(["rewrite", "lh", "1", "--ask", "조용히"])
    c = store.load("lh").episode(1).candidate
    assert c is not None and c.meta_cut == [MetaCut(text=HEAD, at="head")]


def test_cut_stays_out_of_prompts(client):
    _two_done(client)
    p = store.load("lh")
    p.episode(1).meta_cut = [MetaCut(text="짚어 둘 것이 있습니다 zzcut", at="tail")]
    for text in (prompts.episode_prompt(p, 2), prompts.episode_brief(p, 2), prompts.state_brief(p, 2)):
        assert "zzcut" not in text and "meta_cut" not in text


@needs_node
def test_write_screen_note():
    files = ["app.js", "flow.js", "restate.js", "write.js"]
    cuts = [{"text": HEAD, "at": "head"}, {"text": "<b>꼬리</b>", "at": "tail"}]
    proj = {"episodes": [{"plot": {"number": 1}, "meta_cut": cuts}, {"plot": {"number": 2}, "meta_cut": []}]}
    out = run_js(files, "S.project = data; [metaCutNote(1, true), metaCutNote(1, false), metaCutNote(2, true)]", proj)
    assert "앞뒤에 붙인 작업 설명 2문단" in out[0] and out[0].count('data-action="metaCutRestore"') == 2
    assert 'data-arg="1:1"' in out[0] and "&lt;b&gt;꼬리" in out[0]  # 글은 가려서 넣는다
    assert "metaCutRestore" not in out[1] and out[2] == ""  # 고칠 수 없으면 버튼 없이, 뗀 것이 없으면 빈 글
