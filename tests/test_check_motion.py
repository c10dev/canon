"""동선 따로 보기 (pipeline.motion_check) 테스트: 프롬프트에 이번 화 본문만 들어가는지, 본 검수와 지적이 겹치지 않게 합쳐지는지,
설정 · 실패 · 명령줄 · 웹 · 자동 집필 추정 · 연구 화면 검수 시험. mock 으로 확인한다.

    python -m pytest tests/test_check_motion.py
"""
import contextlib
import io
import os
import tempfile
import threading

os.environ.setdefault("CANON_LLM", "mock")
os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())

from canon import autorun, pipeline, prompts, research, store  # noqa: E402
from canon.mock import MockLLM  # noqa: E402
from canon.schema import (Character, ConsistencyIssue, ConsistencyReport, Episode, EpisodePlot, Meta,  # noqa: E402
                          Project)

HELD = "서윤은 두 손으로 등불을 받쳐 들었다."
BAD = "서윤은 한 손을 들어 도현에게 흔들었다."
OLD = "서윤은 왼손을 다쳐 붕대를 감았다."


def _plot(n: int) -> EpisodePlot:
    return EpisodePlot(number=n, act="기", title=f"{n}화", summary="", events=[], characters=["a", "b"], emotional_shift="", ending_hook="")


def _project() -> Project:
    return Project(meta=Meta(title="t", form="serial", target_episodes=2),
                   characters=[Character(id="a", name="서윤", role="주인공", tier="main"),
                               Character(id="b", name="도현", role="등대지기", tier="main")],
                   episodes=[Episode(plot=_plot(1), status="finalized", text=OLD),
                             Episode(plot=_plot(2), status="written", text=f"{HELD} 바람이 불었다. {BAD}")])


def _issue(quote: str, type_: str = "사실", src: int = 0) -> ConsistencyIssue:
    return ConsistencyIssue(type=type_, description="d", source_episode=src, source_quote="q", current_quote=quote)


class Split(MockLLM):
    """본 검수와 동선 따로 보기에 다른 결과를 돌려주는 mock. 부른 스레드도 남긴다."""

    def __init__(self, main: list, motion: list | Exception):
        super().__init__()
        self.main, self.motion = main, motion
        self.calls: list[tuple[str, str]] = []

    def json(self, system, prompt, schema, hint=None):
        side = system == prompts.SYSTEM_MOTION
        self.calls.append(("motion" if side else "main", threading.current_thread().name))
        if side:
            if isinstance(self.motion, Exception):
                raise self.motion
            return ConsistencyReport(episode=2, issues=list(self.motion))
        return ConsistencyReport(episode=2, issues=list(self.main))


def test_prompt_has_only_this_episode_and_cast():
    p = _project()
    text = prompts.motion_prompt(p, 2)
    assert HELD in text and BAD in text
    assert OLD not in text  # 옛 화는 넣지 않는다
    assert "- 서윤 (주인공)" in text and "- 도현 (등대지기)" in text
    assert "source_episode 는 2" in text and "severity" in text


def test_merge_adds_new_motion_issues_and_drops_repeats():
    p = _project()
    llm = Split(main=[_issue(BAD, "동선", 2)],
                motion=[_issue(BAD), _issue(HELD, "사실", 0), _issue("   ")])
    rep = pipeline.check_episode(llm, p, 2)
    assert [i.current_quote for i in rep.issues] == [BAD, HELD]  # 본 검수가 짚은 문장은 다시 넣지 않는다, 빈 인용은 버린다
    assert (rep.issues[1].type, rep.issues[1].source_episode) == ("동선", 2)  # 갈래 · 근거 화를 고친다
    assert sorted(c for c, _ in llm.calls) == ["main", "motion"]
    assert {t for c, t in llm.calls if c == "motion"} != {t for c, t in llm.calls if c == "main"}  # 동시에 다른 스레드에서


def test_setting_and_override_turn_it_off():
    p = _project()
    assert p.settings.check_motion is True  # 기본은 켬
    assert Project.model_validate({}).settings.check_motion is True  # 예전 project.json
    p.settings.check_motion = False
    llm = Split(main=[], motion=[_issue(HELD)])
    assert pipeline.check_episode(llm, p, 2).issues == []
    assert [c for c, _ in llm.calls] == ["main"]
    llm = Split(main=[], motion=[_issue(HELD)])
    assert [i.current_quote for i in pipeline.check_episode(llm, p, 2, motion=True).issues] == [HELD]  # 한 번만 켜기 (cli check --motion)


def test_failed_motion_call_keeps_main_report():
    p = _project()
    llm = Split(main=[_issue(BAD)], motion=RuntimeError("형식 오류"))
    assert [i.current_quote for i in pipeline.check_episode(llm, p, 2).issues] == [BAD]


def test_apply_check_records_motion_issue_as_finding():
    p = _project()
    rep = pipeline.check_episode(Split(main=[], motion=[_issue(BAD, "동선", 2)]), p, 2)
    rnd = pipeline.apply_check(p, rep)
    assert rnd.found == 1
    assert [(f.type, f.status) for f in p.episode(2).findings] == [("동선", "open")]


def test_research_trial_runs_motion_mode():
    p = _project()
    r = research.check_trial(p, 2, research.Backend(provider="mock"), plants=1, seed=1)
    assert [m["mode"] for m in r["runs"]] == ["full", "budget", "widen", "motion"]
    m = r["runs"][3]
    assert m["ok"], m.get("error")
    assert m["tokens"] < r["runs"][1]["tokens"]  # 이번 화 본문만
    assert "motion" in research.TRIAL_MODES


def test_cli_web_and_autorun_estimate(tmp_path, monkeypatch):
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
    r = c.put("/api/projects/demo/check-motion", json={"on": False})
    assert r.status_code == 200 and r.json()["settings"]["check_motion"] is False
    p = store.load("demo")
    assert p.settings.check_motion is False
    p.settings.stage_extract = False  # 장면 뽑기 호출은 tests/test_autorun.py 의 추정 시험이 센다
    policy = autorun.Policy()
    off = autorun.estimate(p, 6, False, policy)
    p.settings.check_motion = True
    on = autorun.estimate(p, 6, False, policy)
    assert off["calls"]["check"] == 6 and on["calls"]["check"] == 12
    assert on["tokens_in"] > off["tokens_in"]
    assert on["seconds_min"] == off["seconds_min"]  # 본 검수와 동시에 부르므로 시간은 그대로
