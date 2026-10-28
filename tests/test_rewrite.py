"""다시 생성 테스트 (mock LLM): 피드백 · 재료 · 고쳐 쓰기 프롬프트, 새 판 고르기, 이전 판 되돌리기. 실행: python -m pytest tests"""
from canon import pipeline, prompts
from canon.schema import ConsistencyIssue, ConsistencyReport, RewriteRequest, TextVersion

from .test_passage import TEXT, _ep, _written
from .test_web import _wait, client  # noqa: F401  (pytest fixture)

JOB = "/api/projects/lh/jobs"


def _rewrite(client, **req):
    j = _wait(client, client.post(JOB, json={"kind": "write", "ep": 1, "rewrite": req}).json()["id"])
    assert j["status"] == "done", j.get("error")
    assert j["result"] == {"candidate": True}
    return client.get("/api/projects/lh").json()


def test_prompt_keeps_writing_prompt_first(client):
    from canon import store

    _written(client)
    p = store.load("lh")
    pipeline.apply_check(p, ConsistencyReport(episode=1, issues=[ConsistencyIssue(
        type="사실", description="등대 색이 다르다", source_quote="흰 등대", current_quote="서윤은 등대 앞에 섰다.", suggestion="흰색으로")]))
    req = RewriteRequest(feedback="서윤이 더 망설이게", presets=["slower", "length"], materials=["issues", "style"],
                         mode="revise", keep=["\"됐어, 내가 할게.\""])
    out = pipeline.rewrite_prompt(p, 1, req)
    base = prompts.episode_prompt(p, 1)
    assert out.startswith(base)  # 쓰기 프롬프트는 그대로, 요청은 뒤에 (캐시)
    tail = out[len(base):]
    assert "서윤이 더 망설이게" in tail and prompts.REWRITE_PRESETS["slower"][1] in tail
    assert f"지난 판은 {len(TEXT):,}자" in tail
    assert "등대 색이 다르다" in tail and "→ 흰색으로" in tail
    assert "[살릴 부분]" in tail and "[지난 판 본문]" in tail and TEXT in tail

    fresh = pipeline.rewrite_prompt(p, 1, RewriteRequest())
    assert "[지난 판 본문]" not in fresh and "처음부터 새로" in fresh and "[검수에서 찾은 곳]" not in fresh
    try:
        pipeline.clean_rewrite(RewriteRequest(presets=["없는 요청"]))
        raise AssertionError("모르는 빠른 요청은 막는다")
    except ValueError:
        pass


def test_rewrite_candidate_adopt_and_restore(client):
    _written(client)
    info = client.get("/api/projects/lh/episodes/1/rewrite").json()
    assert {x["id"] for x in info["presets"]} == set(prompts.REWRITE_PRESETS)
    assert [m["id"] for m in info["materials"]] == ["issues", "hook", "style", "edits"]  # 1화라 흡입력 판정도 있다
    assert next(m for m in info["materials"] if m["id"] == "edits")["lines"]  # 통째로 고쳐 저장한 것도 기록이라 재료가 된다

    shown = client.post("/api/projects/lh/episodes/1/rewrite/prompt", json={"feedback": "더 조용하게", "mode": "revise"}).json()
    assert "더 조용하게" in shown["prompt"] and TEXT in shown["prompt"]

    p = _rewrite(client, feedback="더 조용하게", presets=["dialogue"], materials=["edits"], mode="revise")
    e = _ep(p)
    assert e["text"] == TEXT  # 새 판은 본문을 덮지 않는다
    assert e["candidate"]["text"].endswith("(mock 다시 쓴 본문)")
    assert e["candidate"]["request"]["feedback"] == "더 조용하게"

    # 한 번 더 만들면 앞 새 판은 고르지 않은 판으로 남는다
    p = _rewrite(client, presets=["faster"])
    e = _ep(p)
    assert [v["kind"] for v in e["versions"]] == ["rejected"]
    assert e["candidate"]["request"]["presets"] == ["faster"]

    p = client.post("/api/projects/lh/episodes/1/candidate/adopt").json()
    e = _ep(p)
    assert e["text"].endswith("(mock 다시 쓴 본문)") and e["candidate"] is None and e["status"] == "written"
    assert e["made_by"]["presets"] == ["faster"]
    prev = e["versions"][-1]
    assert (prev["kind"], prev["text"]) == ("previous", TEXT)
    assert client.post("/api/projects/lh/episodes/1/candidate/adopt").status_code == 400  # 고를 새 판이 없다

    # 바꾼 뒤의 수정만 '내가 고친 곳' 재료가 된다
    info = client.get("/api/projects/lh/episodes/1/rewrite").json()
    assert next(m for m in info["materials"] if m["id"] == "edits")["lines"] == []

    p = client.post(f"/api/projects/lh/episodes/1/versions/{prev['id']}/restore").json()
    e = _ep(p)
    assert e["text"] == TEXT and e["made_by"] is None
    assert e["versions"][-1]["text"].endswith("(mock 다시 쓴 본문)") and e["versions"][-1]["request"]["presets"] == ["faster"]
    assert all(v["id"] != prev["id"] for v in e["versions"])
    assert client.post("/api/projects/lh/episodes/1/versions/v99/restore").status_code == 400

    p = _rewrite(client)
    p = client.delete("/api/projects/lh/episodes/1/candidate").json()
    e = _ep(p)
    assert e["candidate"] is None and e["text"] == TEXT and e["versions"][-1]["kind"] == "rejected"


def test_rewrite_rules(client):
    _written(client)
    assert client.post(JOB, json={"kind": "write", "ep": 1, "rewrite": {"presets": ["없음"]}}).status_code == 400
    # 본문이 없는 화는 다시 생성이 아니라 처음 쓰기다
    client.post("/api/projects/lh/episodes/2/confirm")
    p = client.get("/api/projects/lh").json()
    assert not _ep(p, 2)["text"]


def test_plain_write_keeps_previous(client):
    from canon import store

    _written(client)
    ep = store.load("lh").episode(1)
    ep.text, ep.issues = "옛 본문", [ConsistencyIssue(type="사실", description="x", source_quote="a", current_quote="b")]
    pipeline.replace_text(ep, "새 본문")
    assert ep.text == "새 본문" and ep.issues == [] and ep.versions[-1].text == "옛 본문"
    for k in range(pipeline.VERSION_KEEP + 2):
        pipeline.replace_text(ep, f"본문 {k}")
    assert len(ep.versions) == pipeline.VERSION_KEEP
    assert len({v.id for v in ep.versions}) == pipeline.VERSION_KEEP
    # 고르지 않은 새 판이 쌓여도 바꾸기 전 본문(previous)은 밀려나지 않는다
    ep.versions = ep.versions[:1]
    keep = ep.versions[0].id
    for k in range(pipeline.VERSION_KEEP + 3):
        pipeline._keep_version(ep, TextVersion(id=f"r{k}", text=f"버린 판 {k}", kind="rejected"))
    assert len(ep.versions) == pipeline.VERSION_KEEP and ep.versions[0].id == keep
    assert [v.id for v in ep.versions[1:]] == [f"r{k}" for k in range(4, pipeline.VERSION_KEEP + 3)]


def test_cli_rewrite(tmp_path, monkeypatch):
    import contextlib
    import io

    from canon import store
    from canon.cli import main

    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["new", "cl", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
        main(["arc", "cl", "-y"])
        main(["plot", "cl"])
        main(["confirm", "cl", "all"])
        main(["write", "cl", "1"])
        main(["rewrite", "cl", "1", "--ask", "더 조용하게", "--preset", "slower,dialogue", "--use", "style", "--revise", "-y"])
        main(["rewrite", "cl", "1", "--versions"])
    e = store.load("cl").episode(1)
    assert e.text.endswith("(mock 다시 쓴 본문)") and e.made_by.presets == ["slower", "dialogue"]
    assert e.versions[-1].kind == "previous" and e.versions[-1].text.endswith("(mock 본문)")
    assert "바꾸기 전" in out.getvalue()
    with contextlib.redirect_stdout(io.StringIO()):
        main(["rewrite", "cl", "1", "--restore", e.versions[-1].id])
    assert store.load("cl").episode(1).text.endswith("(mock 본문)")
