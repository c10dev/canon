"""복선 센터(canon/foreshadows.py) 테스트 (mock LLM): 문장 걸기, 변경안 정리, 반영, 되돌리기, 끊어진 연결, 센터 계산, CLI, 웹. 실행: python -m pytest tests"""
import importlib

from fastapi.testclient import TestClient

from canon import cli, foreshadows, pipeline, prompts, store
from canon.mock import MockLLM
from canon.schema import ForeshadowClue

from .test_storylines import _short

LINE = "서윤은 등대 앞에 섰다."
LLM = MockLLM()


def _play(p, upto):
    for n in range(1, upto + 1):
        pipeline.confirm_plot(p, n)
        p.episode(n).text = pipeline.write_episode(LLM, p, n)
        p.episode(n).status = "written"
        pipeline.apply_delta(p, pipeline.extract_state(LLM, p, n))
    return p


def test_ai_clues_are_cleaned_and_applied():
    p = _play(_short(8), 1)
    assert [(c.foreshadow, c.kind, c.episode, c.by) for c in p.foreshadow_clues] == [("fs-01-key", "plant", 1, "ai")]
    pipeline.confirm_plot(p, 2)
    p.episode(2).text = pipeline.write_episode(LLM, p, 2)
    p.episode(2).status = "written"
    d = pipeline.extract_state(LLM, p, 2)
    d.foreshadow_clues += [
        ForeshadowClue(foreshadow="fs-없음", quote=LINE),                 # 모르는 복선
        ForeshadowClue(foreshadow="fs-01-key", quote="본문에 없는 문장"),  # 본문에 없는 문장
        ForeshadowClue(foreshadow="fs-01-key", kind="payoff", quote=" 서윤은  등대 앞에 섰다 "),  # 같은 문장 (띄어쓰기 · 문장부호만 다름)
    ]
    foreshadows.clean_delta(p, d)
    assert [(c.foreshadow, c.kind) for c in d.foreshadow_clues] == [("fs-01-key", "payoff")]
    # 회수를 고르지 않으면 회수 문장은 심은 문장으로 남는다
    d2 = d.model_copy(deep=True, update={"foreshadow_resolved": []})
    foreshadows.clean_delta(p, d2)
    assert d2.foreshadow_clues[0].kind == "plant"
    pipeline.apply_delta(p, d)
    c = foreshadows.center(p)
    assert c["total"] == 1 and c["resolved"] == 1 and c["rate"] == 1.0
    item = c["items"][0]
    assert [x["episode"] for x in item["plants"]] == [1] and [x["episode"] for x in item["payoffs"]] == [2]


def test_revert_drops_later_ai_clues_keeps_author():
    p = _play(_short(8), 2)
    foreshadows.add_clue(p, 2, LINE, "fs-01-key", "plant")
    assert len(p.foreshadow_clues) == 3
    pipeline.revert(p, 1)
    assert [(c.episode, c.kind, c.by) for c in p.foreshadow_clues] == [(1, "plant", "ai"), (2, "plant", "author")]
    assert p.foreshadows[0].status == "open"


def test_author_clue_new_foreshadow_and_payoff():
    p = _play(_short(8), 2)
    f = foreshadows.add(p, "등대의 불빛", 1, "series", due_ep=6)
    assert f.id.startswith("fs-01-") and p.snapshot(1).foreshadows[-1].id == f.id  # 그 화부터의 스냅샷에도
    foreshadows.add_clue(p, 2, LINE, f.id, "payoff")
    x = foreshadows.get(p, f.id)
    assert x.status == "resolved" and x.payoff_ep == 2
    foreshadows.reopen(p, f.id)
    assert foreshadows.get(p, f.id).status == "open" and not any(c.foreshadow == f.id and c.kind == "payoff" for c in p.foreshadow_clues)
    try:
        foreshadows.add_clue(p, 2, "없는 문장이다", f.id)
        raise AssertionError("본문에 없는 문장은 걸리면 안 된다")
    except ValueError:
        pass
    # 심은 화보다 앞에서 다시 걸면 심은 화가 당겨진다
    g = foreshadows.add(p, "늦게 적은 복선", 2)
    foreshadows.add_clue(p, 1, LINE, g.id)
    assert foreshadows.get(p, g.id).planted_ep == 1
    foreshadows.remove(p, g.id)
    assert not any(c.foreshadow == g.id for c in p.foreshadow_clues)


def test_broken_overdue_and_prune():
    p = _play(_short(8), 3)
    f = foreshadows.add(p, "숨긴 편지", 1, due_ep=2)
    foreshadows.add_clue(p, 3, LINE, f.id)
    c = foreshadows.center(p)
    item = next(x for x in c["items"] if x["id"] == f.id)
    assert item["overdue"] and c["overdue"] == 1 and item["last_seen"] == 3
    p.episode(3).text = "다른 이야기로 바꿨다."
    assert foreshadows.center(p)["broken"] == 1  # 작가가 건 3화 문장 (mock 은 1 · 2화에만 문장을 건다)
    assert foreshadows.prune(p) == 1 and foreshadows.center(p)["broken"] == 0


def test_planned_payoff_and_prompt_rule():
    p = _short(8)
    fid = foreshadows.add(p, "열쇠", 1).id
    p.episode(5).plot.foreshadow_payoff = [fid]
    assert foreshadows.center(p)["items"][-1]["planned"] == [5]
    assert "foreshadow_clues" in prompts.state_prompt(p, 1)


def test_cli_and_web(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    importlib.reload(store)
    p = _play(_short(8), 2)
    store.save("fs", p)
    cli.main(["foreshadows", "fs", "--all"])
    out = capsys.readouterr().out
    assert "회수율 100%" in out and LINE in out

    from canon import web
    importlib.reload(web)
    c = TestClient(web.app)
    r = c.post("/api/projects/fs/foreshadows/clues", json={"episode": 2, "quote": LINE, "description": "등대 앞 발자국"})
    assert r.status_code == 200
    fid = r.json()["foreshadows"][-1]["id"]
    assert c.post("/api/projects/fs/foreshadows/clues", json={"episode": 2, "quote": LINE, "kind": "payoff"}).status_code == 400
    assert c.put(f"/api/projects/fs/foreshadows/{fid}", json={"due_ep": 7, "scope": "part"}).json()["foreshadows"][-1]["due_ep"] == 7
    assert c.post(f"/api/projects/fs/foreshadows/{fid}/resolve", json={"episode": 2}).json()["foreshadows"][-1]["status"] == "resolved"
    assert c.post(f"/api/projects/fs/foreshadows/{fid}/reopen").json()["foreshadows"][-1]["status"] == "open"
    center = c.get("/api/projects/fs/foreshadows").json()
    assert center["total"] == 2 and center["open"] == 1
    r = c.post("/api/projects/fs/foreshadows/clues/remove", json={"foreshadow": fid, "episode": 2, "quote": LINE})
    assert not any(x["foreshadow"] == fid for x in r.json()["foreshadow_clues"])
    assert c.post("/api/projects/fs/foreshadows", json={"description": "새 복선", "episode": 1}).status_code == 200
    assert c.post("/api/projects/fs/foreshadows/prune").status_code == 200
    assert all(x["id"] != fid for x in c.delete(f"/api/projects/fs/foreshadows/{fid}").json()["foreshadows"])
