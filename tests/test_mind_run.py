"""후보 판 실행기 (scripts/mind_run.py) 테스트. 지어낸 작품과 mock LLM, 가짜 라벨 LLM 으로 돈다."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from canon import autorun, jobs, mock, prompts, settings, store
from canon.cli import main as canon_main


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "mind_run.py"
    spec = importlib.util.spec_from_file_location("mind_run", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mr = _script()
NAME = "demo"
TITLE = "등대"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """원본 저장소(src) 에 지어낸 작품 하나. 판 폴더는 tmp_path/runs."""
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("CANON_BATCH_POLL", "0.01")
    monkeypatch.delenv("CANON_LLM_WRITE", raising=False)
    monkeypatch.delenv("CANON_MODEL_WRITE", raising=False)
    monkeypatch.setattr(store, "ROOT", src)
    monkeypatch.setattr(autorun, "_controls", {})
    with contextlib.redirect_stdout(io.StringIO()):
        canon_main(["new", NAME, "--title", TITLE, "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
        canon_main(["arc", NAME, "-y"])
        canon_main(["plot", NAME])
        canon_main(["confirm", NAME, "all"])
    yield SimpleNamespace(src=src, home=tmp_path / "runs", tmp=tmp_path)
    jobs.draining.clear()


def _hashes(root: Path) -> dict:
    return {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(root.rglob("*")) if f.is_file()}


def _args(w, arm, to=2, **kw):
    ns = dict(project=NAME, arm=arm, to=to, home=str(w.home), dry_run=False, allow_mock=True)
    ns.update(kw)
    return SimpleNamespace(**ns)


def _record(monkeypatch) -> list:
    """상태 변경안(StateDeltaAI) 요청 글을 기록한다."""
    seen: list = []
    orig = mock.MockLLM.json

    def wrapped(self, system, prompt, schema, hint=None):
        if schema.__name__ == "StateDeltaAI":
            seen.append(system + "\n" + prompt)
        return orig(self, system, prompt, schema, hint)

    monkeypatch.setattr(mock.MockLLM, "json", wrapped)
    return seen


# ---------- run ----------

def test_k_arm_state_request_has_new_line(world, monkeypatch):
    seen = _record(monkeypatch)
    assert mr.cmd_run(_args(world, "K")) == 0
    assert seen
    assert all(mr.K_NEW in s and "짧은 라벨로" not in s for s in seen)


def test_b1_keeps_old_line_and_restores(world, monkeypatch):
    seen = _record(monkeypatch)
    before = prompts.LAYER_STATE_RULE
    assert mr.cmd_run(_args(world, "B1")) == 0
    assert seen
    assert all(mr.K_OLD in s and mr.K_NEW not in s for s in seen)
    assert prompts.LAYER_STATE_RULE == before
    assert store.ROOT == world.src


def test_k_restores_rule_after_run(world):
    before = prompts.LAYER_STATE_RULE
    mr.cmd_run(_args(world, "K"))
    assert prompts.LAYER_STATE_RULE == before


def test_d_arm_env(monkeypatch):
    monkeypatch.setenv("CANON_LLM", "gemini")
    monkeypatch.delenv("CANON_LLM_WRITE", raising=False)
    monkeypatch.delenv("CANON_MODEL_WRITE", raising=False)
    with mr.arm_env("D"):
        assert settings.stage_provider("write")[0] == "coralbricks"
        assert settings.stage_model("write")[0] == "deepseek-v4.1-flash"
    assert "CANON_LLM_WRITE" not in os.environ
    assert "CANON_MODEL_WRITE" not in os.environ


def test_d_arm_env_restores_old_values(monkeypatch):
    monkeypatch.setenv("CANON_LLM_WRITE", "gemini")
    monkeypatch.setenv("CANON_MODEL_WRITE", "x")
    with mr.arm_env("D"):
        assert os.environ["CANON_LLM_WRITE"] == "coralbricks"
    assert os.environ["CANON_LLM_WRITE"] == "gemini"
    assert os.environ["CANON_MODEL_WRITE"] == "x"


def test_mock_blocked_without_allow_mock(world):
    with pytest.raises(SystemExit) as e:
        mr.cmd_run(_args(world, "B1", allow_mock=False))
    assert "mock" in str(e.value)
    assert store.ROOT == world.src
    store.ROOT = mr.arm_root(world.home, "B1")
    try:
        assert not any(ep.text for ep in store.load(NAME).episodes)
    finally:
        store.ROOT = world.src


def test_allow_mock_runs_done(world, capsys):
    assert mr.cmd_run(_args(world, "B1")) == 0
    out = capsys.readouterr().out
    assert "상태 done" in out
    store.ROOT = mr.arm_root(world.home, "B1")
    try:
        assert any(ep.text for ep in store.load(NAME).episodes)
    finally:
        store.ROOT = world.src


def test_source_untouched(world):
    before = _hashes(world.src / NAME)
    mr.cmd_run(_args(world, "K"))
    assert _hashes(world.src / NAME) == before


def test_stdout_has_no_story_words(world, capsys):
    mr.cmd_run(_args(world, "K"))
    out = capsys.readouterr().out
    store.ROOT = mr.arm_root(world.home, "K")
    try:
        p = store.load(NAME)
    finally:
        store.ROOT = world.src
    words = {TITLE, p.meta.title}
    words |= {c.name for c in p.characters}
    for ep in p.episodes:
        words |= {ln.strip() for ln in ep.text.splitlines() if len(ln.strip()) > 3}
    assert not any(w in out for w in words if w)


def test_k_old_missing_exits(world, monkeypatch):
    monkeypatch.setattr(prompts, "LAYER_STATE_RULE", "다른 글")
    with pytest.raises(SystemExit):
        mr.cmd_run(_args(world, "K"))
    assert store.ROOT == world.src


def test_home_inside_source_exits(world):
    with pytest.raises(SystemExit):
        mr.cmd_run(_args(world, "B1", home=str(world.src / "runs")))
    with pytest.raises(SystemExit):
        mr.prepare(world.src, world.src, "B1", NAME)


def test_prepare_skips_autorun_json_and_keeps_existing(world):
    (world.src / NAME / "autorun.json").write_text("{}", encoding="utf-8")
    root = mr.prepare(world.src, world.home, "B1", NAME)
    assert not (root / NAME / "autorun.json").exists()
    (root / NAME / "marker.txt").write_text("m", encoding="utf-8")
    mr.prepare(world.src, world.home, "B1", NAME)
    assert (root / NAME / "marker.txt").exists()


def test_dry_run_no_llm_calls_cost_line(world, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("LLM 을 부르면 안 돼요")

    monkeypatch.setattr(mock.MockLLM, "json", boom)
    monkeypatch.setattr(mock.MockLLM, "text", boom)
    assert mr.cmd_run(_args(world, "K", dry_run=True, allow_mock=False)) == 0
    out = capsys.readouterr().out
    assert "비용" in out and "판 K" in out


# ---------- table ----------

def _fake_t(values):
    works = {f"R{i}": {"kind": "ref", "thought_per_1k": {"value": v}} for i, v in enumerate(values, 1)}
    works["C1"] = {"kind": "canon", "thought_per_1k": {"value": 0.01}}
    return {"works": works}


class FakeLabelLLM:
    knows_cut = False
    last_finish = ""

    def __init__(self):
        self.calls = 0

    def json(self, system, prompt, schema, hint=None):
        self.calls += 1
        if schema.__name__ == "EpSummary":
            return schema(line="요약문장갑")
        return schema(items=[{"event": "일", "kind": "마음", "source_ep": 1, "who": "본인", "at": 3}])


def _make_arms(w, arms=("B1", "B2", "K")):
    for arm in arms:
        shutil.copytree(w.src / NAME, mr.arm_root(w.home, arm) / NAME)
        store.ROOT = mr.arm_root(w.home, arm)
        p = store.load(NAME)
        for ep in p.episodes[:4]:
            ep.text = f"본문구절갑 {ep.plot.number}화 아마 그는 생각했다. 판단했다.\n" + "가" * 80
            ep.status = "finalized"
        store.save(NAME, p)
    store.ROOT = w.src


def _table_args(w, tmp, **kw):
    t = tmp / "T.json"
    t.write_text(json.dumps(_fake_t([0.5, 0.9])), encoding="utf-8")
    s = tmp / "S.json"
    s.write_text(json.dumps({"1": "앞요약갑"}), encoding="utf-8")
    ns = dict(home=str(w.home), project=NAME, arms=["B1", "B2", "K"], m1=str(t), summaries=str(s),
              label_model="x:y", out_md=str(tmp / "o" / "R.md"), out_json=str(tmp / "o" / "R.json"),
              from_ep=2, to_ep=4, workers=1, retries=0, dry_run=False)
    ns.update(kw)
    return SimpleNamespace(**ns)


def test_table_files_rules_first_and_clean(world, capsys):
    _make_arms(world)
    llm = FakeLabelLLM()
    a = _table_args(world, world.tmp)
    assert mr.cmd_table(a, llm) == 0
    md = Path(a.out_md).read_text(encoding="utf-8")
    doc = json.loads(Path(a.out_json).read_text(encoding="utf-8"))
    assert md.index("판정 규칙") < md.index("| 판 |")
    assert doc["floor"] == 0.5
    assert doc["eps"] == [2, 3, 4]
    assert set(doc["arms"]) == {"B1", "B2", "K"}
    assert doc["arms"]["K"]["eps"] == 3
    out = capsys.readouterr().out
    for text in (md, out, json.dumps(doc, ensure_ascii=False)):
        for word in (NAME, TITLE, "본문구절갑", "요약문장갑", "앞요약갑"):
            assert word not in text
    cache = mr.arm_root(world.home, "K") / "mind_run"
    assert (cache / "summaries.json").exists() and (cache / "labels.json").exists()
    assert store.ROOT == world.src


def test_table_cache_skips_second_call(world):
    _make_arms(world, ("B1", "B2"))
    llm = FakeLabelLLM()
    a = _table_args(world, world.tmp, arms=["B1", "B2"])
    mr.cmd_table(a, llm)
    n = llm.calls
    assert n > 0
    mr.cmd_table(a, llm)
    assert llm.calls == n


def test_table_dry_run_no_calls(world, capsys):
    _make_arms(world)
    llm = FakeLabelLLM()
    a = _table_args(world, world.tmp, dry_run=True)
    assert mr.cmd_table(a, llm) == 0
    assert llm.calls == 0
    assert "호출" in capsys.readouterr().out
    assert not Path(a.out_md).exists()


def test_m1_floor_uses_ref_min():
    assert mr.m1_floor(_fake_t([0.9, 0.4, 0.7])) == 0.4
    with pytest.raises(SystemExit):
        mr.m1_floor({"works": {"C1": {"kind": "canon", "thought_per_1k": {"value": 1}}}})


def _v(t, body=1.0, style=0.5):
    return {"thought_per_1k": t, "body_per_1k": body, "style_distance": style}


def test_verdict_pass_and_fail():
    vals = {"B1": _v(0.50), "B2": _v(0.52), "K": _v(0.80), "D": _v(0.53)}
    v = mr.verdict(vals, 0.6)
    assert v["passed"] == ["K"]
    assert v["arms"]["D"]["label"] == "못 통과"
    assert v["b_mean"] == 0.51 and v["jitter"] == 0.02


def test_verdict_floor_blocks():
    vals = {"B1": _v(0.50), "B2": _v(0.52), "K": _v(0.80)}
    v = mr.verdict(vals, 0.9)
    assert v["passed"] == [] and v["arms"]["K"]["label"] == "못 통과"


def test_verdict_aux_worse_blocks():
    vals = {"B1": _v(0.5, body=1.0), "B2": _v(0.52, body=1.1), "K": _v(0.9, body=2.0)}
    v = mr.verdict(vals, 0.6)
    assert v["arms"]["K"]["label"] == "보조 지표 나빠짐"
    assert v["passed"] == []


def test_verdict_aux_none_is_skipped():
    vals = {"B1": _v(0.5, style=None), "B2": _v(0.52, style=None), "K": _v(0.9, style=0.1)}
    v = mr.verdict(vals, 0.6)
    assert v["arms"]["K"]["aux"]["style_distance"] == "없음"
    assert v["passed"] == ["K"]


def test_verdict_undetermined_without_b():
    v = mr.verdict({"B1": _v(0.5), "K": _v(0.9)}, 0.6)
    assert v["undetermined"] is True and v["passed"] == []
    doc = {"eps": [1], "floor": 0.6, "arms": {}, "verdict": v}
    assert "못 냄" in mr.table_md(doc)


def test_table_md_no_pass_line():
    v = mr.verdict({"B1": _v(0.5), "B2": _v(0.52), "K": _v(0.51)}, 0.6)
    arms = {"K": {**_v(0.51), "eps": 3, "label_errors": 0}}
    md = mr.table_md({"eps": [1, 2, 3], "floor": 0.6, "arms": arms, "verdict": v})
    assert "통과한 판 없음" in md
