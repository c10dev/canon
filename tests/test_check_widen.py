"""장편 검수 넓히기 (pipeline.widen_check) 테스트: 첫 검수에 넣지 않은 옛 단락이 근거로 나온 진술만 다시 묻는지,
지적이 겹치지 않게 더해지는지, 설정 · 자동 집필 추정 · 사용량 기록 · 연구 화면 검수 시험. mock 과 가짜 Gemini 로 확인한다.

    python -m pytest tests/test_check_widen.py
"""
import contextlib
import io
import json
import os
import tempfile
from types import SimpleNamespace

import pytest

os.environ.setdefault("CANON_LLM", "mock")
os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())

from canon import autorun, context, pipeline, prompts, research, store, usage  # noqa: E402
from canon.llm import BatchLLM, GeminiLLM  # noqa: E402
from canon.mock import MockLLM  # noqa: E402
from canon.schema import (Character, ConsistencyIssue, ConsistencyReport, Episode, EpisodePlot, Meta,  # noqa: E402
                          Project)

PLANT = "서윤은 오른손을 다쳤다."


def _plot(n: int) -> EpisodePlot:
    return EpisodePlot(number=n, act="기", title=f"{n}화", summary="", events=[], characters=["a"], emotional_shift="", ending_hook="")


def _project(serial: bool = True) -> Project:
    """6화: 1화에만 다친 손이 나온다. 3~5화가 직전 화라 첫 검수의 원문에는 1화가 없다."""
    texts = {1: "서윤은 왼손을 다쳐 붕대를 감았다.\n\n등대지기는 말이 없었다.",
             2: "파도가 거셌다.\n\n배가 늦게 들어왔다.",
             3: "비가 왔다.", 4: "안개가 끼었다.", 5: "해가 났다.",
             6: f"{PLANT} 바람이 불었다. 등대 불이 켜졌다."}
    p = Project(meta=Meta(title="t", form="serial" if serial else "short", target_episodes=6),
                characters=[Character(id="a", name="서윤", role="주인공", tier="main")],
                episodes=[Episode(plot=_plot(n), status="finalized" if n < 6 else "written", text=t) for n, t in texts.items()])
    return p


class Counting(MockLLM):
    """부른 스키마를 차례로 남기는 mock."""

    def __init__(self):
        super().__init__()
        self.calls: list[str] = []
        self.prompts: list[str] = []

    def json(self, system, prompt, schema, hint=None):
        self.calls.append(schema.__name__)
        self.prompts.append(prompt)
        return super().json(system, prompt, schema, hint)


def test_widen_asks_only_claims_with_unseen_passages(monkeypatch):
    p = _project()
    monkeypatch.setitem(context.BUDGET, "check_recall", 0)  # 첫 검수가 옛 단락을 하나도 못 넣은 경우
    assert prompts.check_recall(p, 6)[1] == []
    llm = Counting()
    first = ConsistencyReport(episode=6, issues=[])
    rep, st = pipeline.widen_check(llm, p, 6, first, hint={"plants": [PLANT]})
    assert llm.calls == ["ClaimSet", "ConsistencyReport"]
    assert st["claims"] == 3 and st["widened"] == 1 and st["added"] == 1
    assert [r["widened"] for r in st["rows"]] == [True, False, False]  # 1화 단락과 겹치는 진술만
    assert st["rows"][0]["new"] > 0 and st["rows"][0]["old"] == 0
    assert [i.current_quote for i in rep.issues] == [PLANT]
    last = llm.prompts[-1]
    assert "[1화 발췌]" in last and "서윤은 왼손을 다쳐" in last and "판단기" not in last
    assert st["claims_tokens"] > 0 and st["verdict_tokens"] > 0

    # 첫 검수가 이미 짚은 문장은 다시 더하지 않고, 다시 묻는 프롬프트에 알려 준다
    known = ConsistencyIssue(type="사실", description="손", source_episode=1, source_quote="왼손", current_quote=PLANT)
    llm = Counting()
    rep, st = pipeline.widen_check(llm, p, 6, ConsistencyReport(episode=6, issues=[known]), hint={"plants": [PLANT]})
    assert st["added"] == 0 and len(rep.issues) == 1
    assert "# 이미 보고한 문장" in llm.prompts[-1]


def test_widen_skips_verdict_when_first_check_saw_everything():
    p = _project()
    found = prompts.check_recall(p, 6)[1]
    assert [m for m, _ in found] == [1]  # 예산 안이면 겹치는 옛 단락을 모두 넣었다
    llm = Counting()
    rep, st = pipeline.widen_check(llm, p, 6, ConsistencyReport(episode=6, issues=[]))
    assert llm.calls == ["ClaimSet"]  # 새 단락이 없으니 다시 묻지 않는다
    assert (st["widened"], st["verdict_tokens"], rep.issues) == (0, 0, [])


def test_check_episode_follows_setting_and_only_widens_serial():
    p = _project()
    assert p.settings.check_widen is False  # 기본은 끔
    llm = Counting()
    pipeline.check_episode(llm, p, 6)
    assert llm.calls == ["ConsistencyReport"]
    p.settings.check_widen = True
    llm = Counting()
    pipeline.check_episode(llm, p, 6)
    assert llm.calls[:2] == ["ConsistencyReport", "ClaimSet"]
    llm = Counting()
    pipeline.check_episode(llm, p, 6, widen=False)  # 한 번만 끄기 (cli check --no-widen)
    assert llm.calls == ["ConsistencyReport"]
    short = _project(serial=False)
    short.settings.check_widen = True
    llm = Counting()
    pipeline.check_episode(llm, short, 6)
    assert llm.calls == ["ConsistencyReport"]  # 단편은 넓히지 않는다
    assert Project.model_validate({}).settings.check_widen is False  # 예전 project.json


def test_short_and_budget_prompts_do_not_change():
    """넓히기 설정은 첫 검수 프롬프트를 바꾸지 않는다 (해시 스냅샷은 test_char_context 가 본다)."""
    p = _project()
    before = prompts.check_prompt(p, 6)
    p.settings.check_widen = True
    assert prompts.check_prompt(p, 6) == before


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)

    def generate_content(self, model, contents, config):
        meta = SimpleNamespace(prompt_token_count=100, candidates_token_count=20, thoughts_token_count=0, cached_content_token_count=0)
        return SimpleNamespace(text=self.replies.pop(0), usage_metadata=meta, candidates=[])


def test_widen_calls_are_recorded_in_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_USAGE", str(tmp_path / "usage.jsonl"))
    monkeypatch.setitem(context.BUDGET, "check_recall", 0)
    p = _project()
    p.settings.check_widen = True
    issue = {"type": "사실", "description": "손", "source_episode": 1, "source_quote": "왼손", "current_quote": PLANT, "suggestion": ""}
    replies = [json.dumps({"episode": 6, "issues": []}),
               json.dumps({"claims": [{"quote": PLANT, "claim": "서윤이 오른손을 다쳤다"}]}, ensure_ascii=False),
               json.dumps({"episode": 6, "issues": [issue]}, ensure_ascii=False)]
    llm = GeminiLLM.__new__(GeminiLLM)
    llm.client = SimpleNamespace(models=FakeModels(replies))
    llm.model, llm.last_usage, llm.last_attempts, llm.last_raw, llm.stage = "gemini-4-argon", None, 0, "", "check"
    with usage.scope(project="등대", episode=6, source="web", task="check"):
        rep = pipeline.check_episode(llm, p, 6)
    assert [i.current_quote for i in rep.issues] == [PLANT]
    rows = usage.read()
    assert len(rows) == 3
    assert {(r["project"], r["episode"], r["stage"], r["task"]) for r in rows} == {("등대", 6, "check", "check")}


def test_batch_part_keeps_slots_apart():
    names: dict[str, str] = {}
    b = BatchLLM(SimpleNamespace(model="m"), "6:check", names, lambda: None, lambda s: "")
    c = b.part("claims")
    assert (b.slot, c.slot) == ("6:check", "6:check:claims")
    assert c.names is names  # 서버를 다시 시작하면 같은 기록에서 이어 붙는다


def test_research_trial_runs_widen_mode_for_serial(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setitem(context.BUDGET, "check_recall", 0)
    p = _project()
    r = research.check_trial(p, 6, research.Backend(provider="mock"), plants=1, seed=1)
    assert [m["mode"] for m in r["runs"]] == ["full", "budget", "widen"]
    w = r["runs"][2]
    assert w["ok"], w.get("error")
    assert w["claims"] >= 1 and "first_found" in w and "raised" in w
    assert w["tokens"] > r["runs"][1]["tokens"]  # 첫 검수 + 진술 뽑기 (+ 다시 묻기)
    assert "widen" in research.TRIAL_MODES
    short = research.check_trial(_project(serial=False), 6, research.Backend(provider="mock"), plants=1, seed=1)
    assert [m["mode"] for m in short["runs"]] == ["full", "budget"]


def test_web_toggle_and_autorun_estimate(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from canon import web
    from canon.cli import main

    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
        main(["arc", "demo", "-y"])
        main(["plot", "demo"])
        main(["confirm", "demo", "all"])
    c = TestClient(web.app)
    r = c.put("/api/projects/demo/check-widen", json={"on": True})
    assert r.status_code == 200 and r.json()["settings"]["check_widen"] is True
    p = store.load("demo")
    assert p.settings.check_widen is True
    p.meta.form = "serial"
    policy = autorun.Policy()
    on = autorun.estimate(p, 6, False, policy)
    p.settings.check_widen = False
    off = autorun.estimate(p, 6, False, policy)
    assert off["calls"]["check"] == 6 and on["calls"]["check"] == 18
    assert on["tokens_in"] > off["tokens_in"] and on["seconds_min"] > off["seconds_min"]
