"""연재 일정(Project.release)과 화 진행 단계. 화면 계산(static/home.js 의 epSteps · releasePlan)은 node 가 있을 때만 돈다."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from canon.schema import Episode, EpisodePlot, Finding, Project, TextEdit

HOME = Path(__file__).resolve().parent.parent / "canon" / "static" / "home.js"

# home.js 가 읽힐 때 거는 이벤트만 흉내 내고, 고른 함수만 불러 결과를 돌려준다
HARNESS = """
const vm = require('vm');
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const ctx = { data, actions: {}, document: { addEventListener() {} }, window: { addEventListener() {} } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + `
;globalThis.out = {
  steps: data.episodes.map((e) => epSteps(e).map((s) => (s.done ? 1 : 0))),
  plan: releasePlan(data),
};`, ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""


def _ep(n, status, **kw):
    plot = EpisodePlot(number=n, act="기", title=f"{n}화", summary="", events=[], characters=[], emotional_shift="", ending_hook="")
    return Episode(plot=plot, status=status, **kw)


def _run(p):
    run = subprocess.run(["node", "-e", HARNESS, str(HOME)], input=p.model_dump_json(), capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_release_defaults_for_old_projects():
    p = Project.model_validate({"meta": {"title": "옛 작품"}})
    assert p.release.per_week == 0 and p.release.released == 0
    p.release.per_week, p.release.released = 5, 7
    assert Project.model_validate_json(p.model_dump_json()).release.released == 7


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_episode_steps():
    edit = TextEdit(id="e1", at="2026-10-27T10:00:00", before="a", after="b")
    open_ = Finding(id="f1", type="사실", description="x", source_quote="a", current_quote="b")
    p = Project(episodes=[
        _ep(1, "draft"),
        _ep(2, "confirmed"),
        _ep(3, "written", text="본문"),
        _ep(4, "written", text="본문", checked_at="2026-10-27T09:00:00"),
        _ep(5, "written", text="본문", checked_at="2026-10-27T09:00:00", edits=[edit]),  # 검수 뒤에 고침
        _ep(6, "finalized", text="본문"),  # 검수 없이 반영
        _ep(7, "finalized", text="본문", checked_at="2026-10-27T11:00:00", edits=[edit]),
        _ep(8, "written", text="본문", checked_at="2026-10-27T11:00:00", findings=[open_]),  # 열린 지적이 남음
        _ep(9, "written", text="본문", checked_at="2026-10-27T11:00:00", findings=[open_.model_copy(update={"status": "kept"})]),
    ])
    assert _run(p)["steps"] == [
        [0, 0, 0, 0], [1, 0, 0, 0], [1, 1, 0, 0], [1, 1, 1, 0], [1, 1, 0, 0], [1, 1, 0, 1], [1, 1, 1, 1], [1, 1, 0, 0], [1, 1, 1, 0]]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_release_plan():
    p = Project(episodes=[_ep(n, "finalized") for n in range(1, 11)] + [_ep(11, "written"), _ep(12, "finalized")])
    # 일정이 없으면 비축 일수와 하루 목표를 계산하지 않는다
    plan = _run(p)["plan"]
    assert plan["ready"] == 10 and plan["buffer"] == 10 and plan["bufferDays"] is None and plan["perDay"] == 0
    # 주 5화, 7화까지 올림: 1화부터 이어진 반영 완료는 10화까지(12화는 11화가 비어 세지 않는다)
    p.release.per_week, p.release.released = 5, 7
    plan = _run(p)["plan"]
    assert plan["ready"] == 10 and plan["buffer"] == 3 and plan["bufferDays"] == 4 and not plan["over"]
    assert abs(plan["perDay"] - 5 / 7) < 1e-9
    # 반영한 화보다 더 올렸다고 적으면 비축은 0, 경고 표시
    p.release.released = 12
    plan = _run(p)["plan"]
    assert plan["buffer"] == 0 and plan["over"] and plan["bufferDays"] == 0
    # 손으로 적은 값이 범위를 벗어나도 계산은 0~70 화로 맞춘다 (서버는 막지 않는다)
    p.release.per_week, p.release.released = -3, -1
    plan = _run(p)["plan"]
    assert plan["perWeek"] == 0 and plan["released"] == 0 and plan["bufferDays"] is None
    p.release.per_week = 99
    assert _run(p)["plan"]["perWeek"] == 70
