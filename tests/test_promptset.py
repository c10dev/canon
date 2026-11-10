"""실험 판(canon/promptset.py)과 놀이터의 원래 판 대 실험 판 블라인드 (mock LLM). 실행: python -m pytest tests/test_promptset.py"""
import ast
from pathlib import Path

import pytest

from canon import promptlab, prompts, promptset
from canon.schema import PromptSetChange

CANON = Path(__file__).resolve().parent.parent / "canon"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_PROMPTSETS", str(tmp_path / "sets"))
    monkeypatch.setenv("CANON_PROMPTLAB", str(tmp_path / "lab"))
    return tmp_path


def _changed(kind: str = "episode", pieces=("write_style",)) -> promptset.PromptSet:
    ps = promptset.create("짧은 문체 지시", kind)
    return promptset.update(ps.id, ps.name, kind, [PromptSetChange(piece=x, text=f"[바꾼 {x}] ") for x in pieces], "메모")


def test_store_round_trip(home):
    ps = _changed()
    assert (home / "sets" / f"{ps.id}.json").exists()
    assert promptset.load(ps.id).changes[0].text == "[바꾼 write_style] "
    assert [x.id for x in promptset.sets()] == [ps.id]
    cp = promptset.duplicate(ps.id)
    assert cp.name.endswith("사본") and cp.changes == ps.changes
    promptset.delete(ps.id)
    with pytest.raises(KeyError):
        promptset.load(ps.id)
    with pytest.raises(KeyError):
        promptset.load("../../x")


def test_clean_changes(home):
    with pytest.raises(ValueError):  # 보내기 직전 줄은 백엔드가 붙여 바꿀 수 없다
        promptset.clean_changes([PromptSetChange(piece="policy_note", text="x")])
    with pytest.raises(ValueError):  # 요청 전체를 만드는 조각
        promptset.clean_changes([PromptSetChange(piece="plot_req", text="x")])
    with pytest.raises(ValueError):
        promptset.create("x", "setup")  # 조립 보기가 없는 갈래
    got = promptset.clean_changes([PromptSetChange(piece="ending", text="a"), PromptSetChange(piece="ending", text="b")])
    assert [(c.piece, c.text) for c in got] == [("ending", "b")]


def test_apply_swaps_only_the_piece(home):
    p = promptlab.example_project()
    system, prompt, _ = prompts.view_request(p, 3, "episode")
    ps = _changed(pieces=("write_style", "prose_rules", "gone_piece", "devices"))
    ps.changes.append(PromptSetChange(piece="write_speech", text=prompts.WRITE_SPEECH_LINE))
    s2, p2, rows = promptset.apply(p, 3, "episode", system, prompt, ps)
    state = {r["piece"]: r["state"] for r in rows}
    assert state == {"write_style": "applied", "prose_rules": "applied", "gone_piece": "missing", "devices": "absent", "write_speech": "same"}
    assert "[바꾼 write_style] " in p2 and prompts.WRITE_STYLE_LINE not in p2
    assert "[바꾼 prose_rules] " in s2 and prompts.prose_rules() not in s2
    # 나머지 글은 그대로: 바꾼 두 곳을 되돌리면 원래 요청과 같다
    assert p2.replace("[바꾼 write_style] ", prompts.WRITE_STYLE_LINE) == prompt
    assert s2.replace("[바꾼 prose_rules] ", prompts.prose_rules(prompts.styled(p))) == system


def test_real_requests_never_use_sets():
    """실험 판은 놀이터 · 프롬프트 관리 페이지에서만 끼운다. 실제 집필 · 자동 집필 · 작업지시서 경로는 promptset 을 부르지 않는다 (정할 것 1)."""
    allowed = {"promptset.py", "promptlab.py", "prompts.py"}  # prompts.py 는 이름만 (routes/prompts.py 는 아래에서 따로)
    for f in CANON.rglob("*.py"):
        if f.name in allowed and f.parent == CANON:
            continue
        if f.parent.name == "routes" and f.name == "prompts.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert "promptset" not in names and not any(m.endswith("promptset") for m in mods), f
    assert "promptset" not in (CANON / "prompts.py").read_text(encoding="utf-8").replace("promptset.py", "")


def test_playground_load_with_set_and_blind(home):
    ps = _changed()
    s = promptlab.create()
    promptlab.load_prompt(s, "episode", "", 0, ps.id, blind=True)
    assert "[바꾼 write_style] " in s.prompt and s.base and prompts.WRITE_STYLE_LINE in s.base.prompt
    assert s.source.promptset == ps.id and "실험 판 짧은 문체 지시" in s.source.label
    s.backends = [promptlab.PromptBackend(provider="mock"), promptlab.PromptBackend(provider="mock", model="b")]
    runs = promptlab.run(s)
    assert [r.side for r in runs] == ["set", "set", "original", "original"]
    t = promptlab.add_trial(s, s.system, s.prompt, s.temperature, runs, s.source, s.base)
    assert len(t.blinds) == 2 and all(sorted(b.order) == ["original", "set"] for b in t.blinds)
    v = promptlab.view(s)["trials"][0]
    assert v["runs"] == [] and v["blinds"][0]["state"] == "pending"
    assert "side" not in v["blinds"][0]["shown"][0] and "order" not in v["blinds"][0]  # 고르기 전에는 어느 쪽인지 알리지 않는다
    got = promptlab.pick(s, t.no, 0, 1)
    assert got == t.blinds[0].order[0] and t.blinds[0].seen == 0
    assert promptlab.pick(s, t.no, 1, 0) == "skip" and t.blinds[1].seen == 1
    with pytest.raises(ValueError):
        promptlab.pick(s, t.no, 0, 2)
    done = promptlab.view(s)["trials"][0]["blinds"][0]
    assert done["state"] == "done" and done["shown"][0]["side"] == done["order"][0]
    # 되돌리기는 원래 판도 되돌린다. 실험 판 없이 블라인드는 막는다
    promptlab.load_prompt(s, "check")
    assert s.base is None
    promptlab.restore(s, t.no)
    assert s.base is not None
    with pytest.raises(ValueError):
        promptlab.load_prompt(s, "episode", blind=True)


def test_playground_rejects_set_without_pieces_here(home):
    ps = _changed(pieces=("motion_rules",))  # 본문 쓰기 요청에는 동선 목록이 없다
    with pytest.raises(ValueError):
        promptlab.load_prompt(promptlab.create(), "episode", "", 0, ps.id)
    s = promptlab.create()
    promptlab.load_prompt(s, "motion", "", 0, ps.id)  # 조립 보기 갈래도 불러온다
    assert s.source.stage == "check" and s.source.schema_name == "ConsistencyReport" and "[바꾼 motion_rules]" in s.prompt


def test_routes(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_PROMPTSETS", str(tmp_path / "sets"))
    monkeypatch.setenv("CANON_PROMPTLAB", str(tmp_path / "lab"))
    ps = client.post("/api/promptsets", json={"name": "판", "kind": "episode"}).json()
    d = client.put(f"/api/promptsets/{ps['id']}", json={"name": "판", "kind": "episode", "note": "",
                                                        "changes": [{"piece": "ending", "text": "문장 끝을 섞어요."}]}).json()
    assert d["rows"][0]["state"] == "applied" and "문장 끝을 섞어요." in d["applied"]["prompt"]
    assert d["original"]["prompt"] != d["applied"]["prompt"] and any(x["id"] == "ending" for x in d["pieces"])
    assert not any(x["id"] in prompts.SEND_PIECES for x in d["pieces"])
    assert client.get("/api/promptsets").json()["sets"][0]["id"] == ps["id"]
    lab = client.post(f"/api/promptsets/{ps['id']}/playground", json={"blind": True}).json()
    assert lab["base"] and lab["source"]["promptset"] == ps["id"]
    run = client.post(f"/api/promptlab/{lab['id']}/run", json={**{k: lab[k] for k in ("title", "system", "prompt")},
                                                                "backends": [{"provider": "mock"}]}).json()
    assert run["trials"][0]["blinds"][0]["state"] == "pending"
    picked = client.post(f"/api/promptlab/{lab['id']}/trials/1/pick", json={"k": 0, "choice": 2}).json()
    assert picked["trials"][0]["blinds"][0]["picked"] in ("original", "set")
    bad = client.put(f"/api/promptsets/{ps['id']}", json={"name": "판", "kind": "episode", "changes": [{"piece": "policy_note", "text": "x"}]})
    assert bad.status_code == 400
    assert client.post(f"/api/promptsets/{ps['id']}/duplicate").status_code == 200
    assert client.delete(f"/api/promptsets/{ps['id']}").json() == {"ok": True}
    assert client.get(f"/api/promptsets/{ps['id']}").status_code == 404
