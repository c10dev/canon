"""본문을 쓴 모델 기록 (Episode.written_by · TextVersion.model): 옛 파일 읽기, 쓰기 경로마다 기록, 다시 생성 판 고르기 · 되돌리기,
쇠맛 실험실의 record. mock LLM 만 쓴다. 실행: python -m pytest tests"""
import contextlib
import io
import json
from pathlib import Path

from canon import autorun, jobs, pipeline, prompts, research, soelab, store, usage
from canon.cli import main
from canon.schema import Episode, RewriteRequest, TextVersion

from .test_autorun import Policy, demo  # noqa: F401  (pytest fixture)
from .test_passage import TEXT, _ep, _written
from .test_play import _step
from .test_restate import _two_done
from .test_soelab import _project, home, story  # noqa: F401  (pytest fixture)
from .test_web import _wait, client  # noqa: F401  (pytest fixture)


class GeminiLLM:  # usage.backend_of 는 클래스 이름으로 백엔드를 고른다
    def __init__(self, model):
        self.model = model


class ClaudeCodeLLM:
    model = ""


class Batch:  # llm.BatchLLM 처럼 안쪽 LLM 을 inner 에 둔다
    inner = GeminiLLM("gemini-4-argon")


def test_old_files_read_and_model_id():
    e = Episode.model_validate({"plot": {"number": 1, "act": "기", "title": "", "summary": "", "events": [], "characters": [],
                                         "emotional_shift": "", "ending_hook": ""}, "text": "옛 본문",
                                "versions": [{"id": "v1", "text": "옛 판"}]})
    assert e.written_by == "" and e.versions[0].model == ""
    assert usage.model_id(GeminiLLM("gemini-4-argon")) == "gemini:gemini-4-argon"
    assert usage.model_id(ClaudeCodeLLM()) == "claude:default"  # 모델 칸이 비면 사용량 기록 · 쇠맛 실험실과 같은 'default'
    assert usage.model_id(Batch()) == "gemini:gemini-4-argon"
    assert pipeline.writer_of(__import__("canon.mock", fromlist=["MockLLM"]).MockLLM()) == "mock:mock"


def test_web_write_edit_rewrite_adopt_restore(client):
    p = _written(client)  # AI 로 쓴 뒤 화면에서 통째로 고쳐 저장
    e = _ep(p)
    assert e["text"] == TEXT and e["written_by"] == "mock:mock"  # 작가가 고쳐도 쓴 모델은 그대로, 고친 것은 edits
    assert e["edits"][-1]["source"] == "typed"

    j = _wait(client, client.post("/api/projects/lh/jobs", json={"kind": "write", "ep": 1, "rewrite": {"feedback": "조용히"}}).json()["id"])
    assert j["status"] == "done", j.get("error")
    e = _ep(client.get("/api/projects/lh").json())
    assert e["candidate"]["model"] == "mock:mock"

    # 판의 모델이 고르기 · 되돌리기를 따라간다 (모델이 다른 판을 손으로 만든다)
    p = store.load("lh")
    pipeline.set_candidate(p, 1, "제미나이가 쓴 새 판", RewriteRequest(feedback="x"), "gemini:gemini-4-argon")
    pipeline.adopt_candidate(p, 1)
    ep = p.episode(1)
    assert (ep.text, ep.written_by) == ("제미나이가 쓴 새 판", "gemini:gemini-4-argon")
    prev = next(v for v in ep.versions if v.kind == "previous" and v.text == TEXT)
    assert prev.model == "mock:mock"
    rejected = next(v for v in ep.versions if v.kind == "rejected")
    assert rejected.model == "mock:mock"
    pipeline.restore_version(p, 1, prev.id)
    assert (ep.text, ep.written_by) == (TEXT, "mock:mock")
    assert next(v for v in ep.versions if v.text == "제미나이가 쓴 새 판" and v.kind == "previous").model == "gemini:gemini-4-argon"

    # 빈 화에 화면으로 넣은 본문은 직접 쓴 것인지 붙여 넣은 것인지 몰라 비운다. 비우면 모델도 지운다
    store.save("lh", p)
    client.put("/api/projects/lh/episodes/1/text", json={"text": ""})
    e = _ep(client.put("/api/projects/lh/episodes/1/text", json={"text": "작가가 처음부터 쓴 글"}).json())
    assert e["written_by"] == ""
    r = client.post("/api/projects/lh/episodes/1/write").json()  # 동기 쓰기도 남긴다
    assert _ep(r)["written_by"] == "mock:mock" and _ep(r)["versions"][-1]["model"] == ""


def test_written_by_stays_out_of_prompts(client):
    _two_done(client)
    p = store.load("lh")
    p.episode(1).written_by = "zzbackend:zzmodel"
    p.episode(1).versions = [TextVersion(id="v1", text="옛 판", model="zzbackend:zzmodel")]
    for text in (prompts.episode_prompt(p, 2), prompts.episode_brief(p, 2), prompts.state_brief(p, 2)):
        assert "zzmodel" not in text and "written_by" not in text


def test_cli_write_and_import(client, tmp_path):
    _written(client)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["confirm", "lh", "1"])
    f = tmp_path / "chat.md"
    f.write_text("채팅 앱에서 받은 본문", encoding="utf-8")
    with contextlib.redirect_stdout(out):
        main(["import", "lh", "1", str(f)])
    ep = store.load("lh").episode(1)
    assert ep.written_by == "import" and ep.versions[-1].model == "mock:mock"
    with contextlib.redirect_stdout(out):
        main(["write", "lh", "1"])
    ep = store.load("lh").episode(1)
    assert ep.written_by == "mock:mock" and ep.versions[-1].model == "import"


def test_autorun_records_model(demo):  # noqa: F811
    jobs.draining.clear()  # 앞 시험(서버 재시작 흉내)이 남긴 표시가 있으면 배치 실행이 쓰기 전에 멈춘다
    run = autorun.start(demo, 1, True, Policy(), foreground=True)  # 배치: BatchLLM 안쪽 모델을 적는다
    ep = store.load(demo).episode(1)
    assert ep.text and ep.written_by == "mock:mock", (run.status, [x.message for x in run.log])


def test_play_scene_records_model(client):
    from canon import play

    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    _, n = _step(p, info)
    assert p.episode(n).written_by == "mock:mock"


def test_compare_pick_carries_model(client):
    _written(client)
    p = store.load("lh")
    research.save_compare("lh", 1, {"a": "가 안", "b": "나 안"}, models={"a": "gemini:gemini-4-argon", "b": "claude:default"})
    assert "models" not in json.dumps(research.load_compare("lh", 1), ensure_ascii=False)  # 고르기 전에는 가린다
    order = json.loads((research.compare_dir("lh", 1) / "key.json").read_text(encoding="utf-8"))["order"]
    research.pick_compare("lh", p, 1, order.index("b") + 1)
    assert (p.episode(1).text, p.episode(1).written_by) == ("나 안", "claude:default")


def test_soelab_prefers_record(home):  # noqa: F811
    rows = [{"project": "작품", "episode": n, "stage": "write", "ok": True, "backend": "gemini", "model": "gemini-4-argon"}
            for n in (1, 2, 3)]
    (Path(home) / "usage.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    p = _project("작품", {1: story(1400), 2: story(1401), 3: story(1402)})
    p.episode(1).written_by = "claude:claude-opus-5-5"
    p.episode(2).written_by = "import"
    store.save("작품", p)
    got = {x.source.episode: (x.model, x.model_source) for x in soelab.collect_episodes("작품")}
    assert got == {1: ("claude:claude-opus-5-5", "record"), 2: ("", "unknown"), 3: ("gemini:gemini-4-argon", "usage")}
