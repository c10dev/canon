"""화별 스토리보드 (canon/board.py, prompts.storyboard_prompt · board_block, pipeline.make_storyboard, 자동 집필 _board, 웹).
예시는 지어낸 등대섬 이야기 10~13화의 스토리보드 (tests/storyboard_examples.json)."""
import contextlib
import io
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from canon import autorun, board, branches, jobs, pipeline, prompts, store
from canon.cli import main
from canon.mock import MockLLM
from canon.mock_board import CONFLICT
from canon.schema import BoardStat, BoardWarning, CharacterState, Episode, StatValue, Storyboard, StoryTime

from .jsvm import STATIC, needs_node, run_js
from .test_web import _wait

EXAMPLES = json.loads((Path(__file__).parent / "storyboard_examples.json").read_text(encoding="utf-8"))


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    """단편 6화 작품, 플롯 모두 확정. 스토리보드는 켠다 (단편 기본은 끔)."""
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(autorun, "_controls", {})
    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
        main(["arc", "demo", "-y"])
        main(["plot", "demo"])
        main(["confirm", "demo", "all"])
    p = store.load("demo")
    p.settings.storyboard = True
    store.save("demo", p)
    yield "demo"
    jobs.draining.clear()


def _written(p, n, text="앞 화 본문. " * 300):
    """n화를 반영이 끝난 화로 둔다 (본문 · 끝 시점)."""
    e = p.episode(n)
    e.text, e.status, e.time = text, "finalized", StoryTime(day=4, part="새벽", label="4일째 화요일 새벽")


def test_examples_load_and_keep_no_dict_fields():
    for k, d in EXAMPLES.items():
        b = Storyboard.model_validate(d)
        assert 3 <= len(b.scenes) <= 7, k
    # 응답 형식에는 작가 · Canon 칸이 없다 (SkipJsonSchema)
    props = Storyboard.model_json_schema()["properties"]
    assert not {"made_at", "made_by", "basis", "checks"} & set(props)
    text = json.dumps(Storyboard.model_json_schema())
    assert "additionalProperties" not in text  # dict 칸 없음 (Gemini 구조화 출력)


def test_on_defaults_by_form(demo):
    p = store.load(demo)
    p.settings.storyboard = None
    assert not board.on(p)  # 단편 기본 끔
    p.meta.form = "serial"
    assert board.on(p)
    p.settings.storyboard = False
    assert not board.on(p)


def test_short_off_keeps_prompt_tail(demo):
    p = store.load(demo)
    p.settings.storyboard = None
    _written(p, 1, "가" * 3000)
    ctx = prompts.build_episode_context(p, 2)
    assert "# 직전 화 마지막 부분" in ctx and "가" * 1501 not in ctx and "# 이번 화 스토리보드" not in ctx


def test_board_block_sits_before_plot_and_replaces_time(demo):
    p = store.load(demo)
    _written(p, 1, "가" * 3000)
    p.timeline.enabled = True
    ctx = prompts.build_episode_context(p, 2)
    assert "가" * 3000 in ctx and "# 직전 화 본문 (전체" in ctx  # 직전 화 원문 전체
    assert "# 작품 속 시간" in ctx  # 스토리보드가 없으면 시간 블록 그대로
    p.episode(2).storyboard = Storyboard.model_validate(EXAMPLES["10"])
    ctx = prompts.build_episode_context(p, 2)
    i, j, k = ctx.index("# 직전 화 본문"), ctx.index("# 이번 화 스토리보드"), ctx.index("# 이번 화 플롯")
    assert i < j < k
    assert "# 작품 속 시간" not in ctx  # 스토리보드의 시간 줄이 대신한다
    assert "시간: 4일째 화요일 새벽" in ctx  # 직전 화 기록 글에서 요일을 읽어 셈 (작품 기준이 비었다)
    assert "warnings" not in ctx and "stat_basis" not in ctx and "22%" not in ctx
    assert "은결의 배에서 등유를 옮겨 담지 않는다" in ctx
    without = prompts.episode_prompt(p, 2, use_board=False)
    assert "# 이번 화 스토리보드" not in without and "# 작품 속 시간" in without


def test_steps_resolve_and_range_checks(demo):
    p = store.load(demo)
    p.states = [CharacterState(character_id="hero", stats=[StatValue(name="연료", value="1.0/60"), StatValue(name="스킬", value="은신")])]
    b = Storyboard(stats=[
        BoardStat(character_id="hero", scene=1, changes=[StatValue(name="연료", value="-0.7")], window=True),
        BoardStat(character_id="hero", scene=2, changes=[StatValue(name="연료", value="-0.5"), StatValue(name="스킬", value="+독 내성")]),
    ])
    st = board.steps(p, b)
    assert [r["after"] for r in st[0]["rows"]] == ["0.3/60"] and st[0]["window"] == 1
    assert [r["before"] for r in st[1]["rows"]] == ["0.3/60", "은신"] and st[1]["window"] == 0
    assert st[1]["rows"][1]["after"] == "은신, 독 내성"
    assert any(c.startswith("값 범위") and "0 아래" in c for c in board.checks(p, 1, b))
    # 상태창 글은 그 단계까지의 값
    assert "0.3/60" in board.window_text(p, st[0])


def test_checks_missing_events_and_unknown_ids(demo):
    p = store.load(demo)
    b = Storyboard.model_validate(EXAMPLES["10"])
    b.scenes = b.scenes[:2]
    out = board.checks(p, 1, b)
    events = len(p.episode(1).plot.events)
    if events > 2:
        assert any("맡은 장면이 없어요" in c for c in out)
    assert any("인물 목록에 없는 id" in c for c in out)  # 예시의 keeper 등은 demo 작품에 없다


def test_basis_goes_stale_and_stops_after_text(demo):
    p = store.load(demo)
    _written(p, 1)
    b = pipeline.make_storyboard(MockLLM(), p, 2)
    pipeline.set_storyboard(p, 2, b, by="ai")
    assert b.basis == pipeline.board_basis(p, 2) and not board.stale(p, 2)
    p.episode(1).text += " 고침"
    assert board.stale(p, 2)
    p.episode(3).plot.summary = "다음 화 바뀜"
    assert board.stale(p, 2)
    p.episode(2).text = "쓴 본문"
    assert not board.stale(p, 2)  # 쓴 뒤에는 상태가 앞으로 가서 보지 않는다


def test_make_with_mock_and_author_edit(demo):
    p = store.load(demo)
    with pytest.raises(ValueError, match="상태 반영"):
        pipeline.make_storyboard(MockLLM(), p, 2)  # 1화가 반영 전
    _written(p, 1)
    b = pipeline.make_storyboard(MockLLM(), p, 2)
    events = len(p.episode(2).plot.events)
    assert b.made_by == "ai" and b.made_at and b.checks == []
    assert sorted(k for s in b.scenes for k in s.events) == list(range(1, events + 1))
    pipeline.set_storyboard(p, 2, b, by="ai")
    edit = p.episode(2).storyboard.model_copy(deep=True)
    edit.protect.append("작가가 더한 줄")
    p.episode(1).text += " 고침"  # 입력이 바뀐 뒤 작가가 보고 저장하면 지금 입력에 맞춘 것
    pipeline.set_storyboard(p, 2, edit)
    sb = p.episode(2).storyboard
    assert sb.made_by == "both" and "작가가 더한 줄" in sb.protect and not board.stale(p, 2)
    pipeline.set_storyboard(p, 2, None)
    assert p.episode(2).storyboard is None


def test_storyboard_prompt_rules_and_blocks(demo):
    p = store.load(demo)
    _written(p, 1, "앞 화 끝 장면.")
    p.states = [CharacterState(character_id=p.characters[0].id, stats=[StatValue(name="연료", value="4.3/60")])]
    text = prompts.storyboard_prompt(p, 2)
    for rule in ("화 번호('6화', '11화')를 쓰지 않습니다", "조건까지 옮깁니다", "소모 항목을 빠짐없이", "물리적 사실로 바꿔 적지 않습니다",
                 "opening(여는 장면)", "플롯 칸을 고쳐 적지 않습니다"):
        assert rule in text, rule
    assert "# 다음 화 플롯" in text and "# 장소 목록" in text and "앞 화 끝 장면." in text
    assert "상태창 지금 값" in text and "4.3/60" in text
    assert text.index("# 직전 화 본문") < text.index("# 다음 화 플롯") < text.index("# 이번 화 플롯")
    p.states = []
    assert "stats 와 stat_basis 는 비웁니다" in prompts.storyboard_prompt(p, 2)


def test_stop_reasons_this_episode_only():
    b = Storyboard(warnings=[BoardWarning(kind="plot_vs_state", text="닿을 수 없어요"),
                             BoardWarning(kind="next_plot", target="next", text="다음 화"),
                             BoardWarning(kind="setting", text="설정에 없음")])
    out = board.stop_reasons(None, 10, b)
    assert len(out) == 1 and "닿을 수 없어요" in out[0]
    b.checks = ["값 범위: 주인공 연료 -1/60 (0 아래예요)", "플롯 사건 3번을 맡은 장면이 없어요"]
    assert len(board.stop_reasons(None, 10, b)) == 2


def test_autorun_makes_boards_and_stops_on_conflict(demo):
    p = store.load(demo)
    p.episode(2).plot.events[0] += " " + CONFLICT
    store.save(demo, p)
    run = autorun.start(demo, 3, False, autorun.Policy(hand_pick_opening=False, check=False), foreground=True)
    assert run.status == "paused" and run.halt == "board" and run.ep == 2
    assert any("플롯 · 상태" in r for r in run.reasons)
    p = store.load(demo)
    assert p.episode(1).storyboard.made_by == "ai" and p.episode(1).status == "finalized"
    assert p.episode(2).storyboard is not None and not p.episode(2).text
    assert any(e.step == "plan" for e in run.log)
    assert any("다음 화 플롯 경고" in e.message for e in run.log)  # 기록만
    # 작가가 카드에서 그대로 저장하면 이어 간다
    pipeline.set_storyboard(p, 2, p.episode(2).storyboard)
    store.save(demo, p)
    run = autorun.resume(demo, foreground=True)
    assert run.status == "done"
    assert all(store.load(demo).episode(k).storyboard for k in (1, 2, 3))


def test_autorun_author_board_stale_pauses_and_policy_off(demo):
    p = store.load(demo)
    pipeline.set_storyboard(p, 1, Storyboard.model_validate(EXAMPLES["11"]))  # 작가가 만든 것
    p.episode(1).storyboard.basis = "old"
    store.save(demo, p)
    run = autorun.start(demo, 1, False, autorun.Policy(hand_pick_opening=False, check=False), foreground=True)
    assert run.halt == "board_stale"
    run = autorun.start(demo, 2, False, autorun.Policy(hand_pick_opening=False, check=False, storyboard=False), foreground=True)
    assert run.status == "done" and store.load(demo).episode(2).storyboard is None


def test_estimate_counts_board_calls(demo):
    p = store.load(demo)
    on = autorun.estimate(p, 3, False, autorun.Policy())
    off = autorun.estimate(p, 3, False, autorun.Policy(storyboard=False))
    assert on["calls"]["plan"] == 3 and off["calls"]["plan"] == 0
    assert on["tokens_in"] > off["tokens_in"]


def test_branch_drops_boards_from_fork(demo):
    run = autorun.start(demo, 2, False, autorun.Policy(hand_pick_opening=False, check=False), foreground=True)
    assert run.status == "done"
    p = store.load(demo)
    p.episode(3).storyboard = Storyboard.model_validate(EXAMPLES["13"])
    assert p.episode(1).storyboard and p.episode(2).storyboard
    branches.fork(p, 2)
    assert p.episode(1).storyboard is not None
    assert p.episode(2).storyboard is None and p.episode(3).storyboard is None


def test_web_job_view_put_delete(demo):
    from canon import web

    c = TestClient(web.app)
    p = store.load(demo)
    _written(p, 1)
    store.save(demo, p)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "board", "ep": 2})
    assert r.status_code == 200, r.text
    assert _wait(c, r.json()["id"])["status"] == "done"
    v = c.get(f"/api/projects/{demo}/episodes/2/storyboard").json()
    assert v["on"] and not v["stale"] and v["time"] == "4일째 화요일 새벽 → 4일째 화요일 아침"
    sb = store.load(demo).episode(2).storyboard
    body = json.loads(sb.model_dump_json())
    body["protect"] = ["작가 줄"]
    out = c.put(f"/api/projects/{demo}/episodes/2/storyboard", json=body).json()
    got = next(e for e in out["episodes"] if e["plot"]["number"] == 2)["storyboard"]
    assert got["made_by"] == "both" and got["protect"] == ["작가 줄"]
    # 바로 쓰기: 스토리보드를 새로 만든 뒤 쓴다
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 2, "board": "make"})
    assert r.status_code == 200 and r.json()["total"] == 2
    assert _wait(c, r.json()["id"])["status"] == "done"
    e = store.load(demo).episode(2)
    assert e.text and e.storyboard.made_by == "ai"
    assert c.delete(f"/api/projects/{demo}/episodes/2/storyboard").status_code == 200
    assert store.load(demo).episode(2).storyboard is None


FILES = re.findall(r'src="/static/([a-z-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


@needs_node
def test_board_js_parse_fields():
    got = run_js(FILES, """(() => [
      boardParse('ids', 'keeper, ferry ,', null),
      boardParse('nums', '1, 2, x, 0', null),
      boardParse('handover', '장면: 테이블에서 끝났다\\n그냥 한 줄', null),
      boardParse('attire', 'keeper = 젖은 외투\\n없는 형식', [{ character_id: 'keeper', end: '', why: '장면 1' }]),
      boardParse('int', 'x', null),
    ])()""", {})
    assert got[0] == ["keeper", "ferry"] and got[1] == [1, 2]
    assert got[2] == [{"kind": "장면", "text": "테이블에서 끝났다"}, {"kind": "", "text": "그냥 한 줄"}]
    assert got[3] == [{"character_id": "keeper", "end": "젖은 외투", "why": "장면 1"}] and got[4] == 0
