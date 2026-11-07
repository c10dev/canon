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
from canon.schema import BoardStat, BoardWarning, CharacterState, StatValue, Storyboard, StoryTime

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
    assert "가" * 1501 not in ctx and "# 직전 화 마지막 부분" in ctx  # 스토리보드가 없는 화는 직전 화 끝부분만 (자기 글 따라 하기를 줄임)
    assert "# 작품 속 시간" in ctx  # 스토리보드가 없으면 시간 블록 그대로
    assert "가" * 3000 in prompts.storyboard_prompt(p, 2)  # 스토리보드 만들기는 직전 화 원문 전체
    p.episode(2).storyboard = Storyboard.model_validate(EXAMPLES["10"])
    ctx = prompts.build_episode_context(p, 2)
    assert "가" * 3000 in ctx and "# 직전 화 본문 (전체" in ctx  # 스토리보드를 넣는 쓰기는 직전 화 원문 전체
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


def test_storyboard_call_caps_output_tokens(demo):
    from canon import llm as llm_mod

    class Capped(MockLLM):
        def json(self, system, prompt, schema, hint=None):
            caps.append(llm_mod._out_cap.get())
            return super().json(system, prompt, schema, hint)

    caps: list = []
    p = store.load(demo)
    _written(p, 1)
    pipeline.make_storyboard(Capped(), p, 2)
    assert caps and set(caps) == {pipeline.BOARD_OUT_TOKENS}  # 되풀이하는 응답이 65,536토큰까지 가지 않게
    assert llm_mod._out_cap.get() is None  # 끝나면 풀린다


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
    assert any(e.step == "board" for e in run.log)
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
    assert on["calls"]["board"] == 3 and off["calls"]["board"] == 0
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
    assert e.text and e.storyboard.made_by == "ai" and not e.storyboard.skipped
    # 스토리보드 없이 다시 쓰면 검수가 그 전제를 대조하지 않게 표시한다
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 2, "board": "none"})
    assert _wait(c, r.json()["id"])["status"] == "done"
    assert store.load(demo).episode(2).storyboard.skipped
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


@needs_node
def test_board_job_redraws_write_page_and_says_done():
    """스토리보드 작업이 끝나면 집필 화면을 다시 그리고 끝 알림 글이 있다 (없으면 '만드는 중' 줄이 남고 알림이 빈다)."""
    got = run_js(FILES, "[JOB_PAGES.board, JOB_DONE_MSG.board({ ep: 3 })]", {})
    assert got[0] == ["write"]
    assert got[1].startswith("3화 스토리보드를 만들었어요")


def test_stopped_board_keeps_late_storyboard(demo, monkeypatch):
    """멈춘 스토리보드 작업의 늦은 응답은 값을 치렀으니 그 화에 스토리보드와 본문이 없으면 남긴다. 그 사이 생겼으면 버린다."""
    import threading
    import time

    from canon import cancel, web

    go, sent = threading.Event(), threading.Event()

    class Late(MockLLM):
        def json(self, *a, **k):
            sent.set()
            go.wait(5)
            with cancel.ignored():  # 이미 보낸 호출의 응답은 멈춘 뒤에도 온다
                return super().json(*a, **k)

    monkeypatch.setattr(web, "get_llm", lambda *a, **k: Late())
    c = TestClient(web.app)
    p = store.load(demo)
    _written(p, 1)
    store.save(demo, p)

    def stopped_late():
        go.clear()
        sent.clear()
        jid = c.post(f"/api/projects/{demo}/jobs", json={"kind": "board", "ep": 2}).json()["id"]
        assert sent.wait(5)
        assert c.post(f"/api/jobs/{jid}/stop").json()["waiting"] is True
        return jobs.get(jid)

    j = stopped_late()
    go.set()
    for _ in range(100):
        if not j.alive:
            break
        time.sleep(0.05)
    assert j.status == "cancelled" and j.result == {"kept": True}
    sb = store.load(demo).episode(2).storyboard
    assert sb is not None and sb.made_by == "ai"
    assert "board:2" not in store.load_pending(demo)["failures"]
    q = store.load(demo)
    q.episode(2).storyboard.protect = ["작가 줄"]
    store.save(demo, q)

    j = stopped_late()  # 이미 스토리보드가 있으면 늦은 응답으로 덮지 않는다
    go.set()
    for _ in range(100):
        if not j.alive:
            break
        time.sleep(0.05)
    assert j.status == "cancelled" and j.result == {"kept": False}
    assert store.load(demo).episode(2).storyboard.protect == ["작가 줄"]


def test_check_gets_protect_and_write_has_one_priority_line(demo):
    p = store.load(demo)
    _written(p, 1, "가" * 3000)
    p.episode(2).storyboard = Storyboard.model_validate(EXAMPLES["10"])
    p.episode(2).text = "본문"
    check = prompts.check_prompt(p, 2)
    assert "# 스토리보드가 정한 다음 화 전제" in check and "은결의 배에서 등유를 옮겨 담지 않는다" in check
    assert "- 스토리보드 전제:" in check
    write = prompts.episode_prompt(p, 2)
    assert "이번 화 플롯과 다른 곳은 스토리보드를 따릅니다" not in write
    assert "자료가 서로 부딪히면 스토리보드, 이번 화 플롯" in write
    p.episode(2).storyboard = None
    assert "# 스토리보드가 정한 다음 화 전제" not in prompts.check_prompt(p, 2)


def test_priority_line_reaches_cue_and_rework_prompts_and_skipped_board(demo):
    p = store.load(demo)
    _written(p, 1, "가" * 3000)
    p.episode(2).storyboard = Storyboard.model_validate(EXAMPLES["10"])
    assert "자료가 서로 부딪히면 스토리보드, 이번 화 플롯" in prompts.cue_sheet_prompt(p, 2)
    p.episode(2).text = "본문"
    p.episode(2).storyboard.skipped = True  # 스토리보드 없이 쓴 본문
    assert "# 스토리보드가 정한 다음 화 전제" not in prompts.check_prompt(p, 2)
    pipeline.set_storyboard(p, 2, p.episode(2).storyboard, by="author")
    assert p.episode(2).storyboard.skipped  # 본문이 그대로면 고쳐도 표시는 남는다


def test_revise_keeps_prefix_and_undo(demo):
    """AI 고치기: 만들기 프롬프트 뒤에 지금 스토리보드와 요청을 붙이고, 고치기 전 것은 적용 취소로 되돌린다."""
    p = store.load(demo)
    _written(p, 1)
    with pytest.raises(ValueError, match="스토리보드가 없어요"):
        pipeline.revise_storyboard(MockLLM(), p, 2, "2장면을 밤으로")
    pipeline.set_storyboard(p, 2, pipeline.make_storyboard(MockLLM(), p, 2), by="ai")
    first = p.episode(2).storyboard.model_copy(deep=True)
    with pytest.raises(ValueError, match="고칠 내용"):
        pipeline.revise_storyboard(MockLLM(), p, 2, "  ")
    text = prompts.storyboard_revise_prompt(p, 2, first, "1장면을 밤으로")
    assert text.startswith(prompts.storyboard_prompt(p, 2))  # 앞부분이 같아야 캐시가 맞는다
    assert text.index("# 지금 스토리보드") < text.index("# 작가 요청") and text.rstrip().endswith("warnings 에 적습니다.")
    assert '"made_by"' not in text and '"basis"' not in text  # 저장 칸은 프롬프트에 넣지 않는다

    b = pipeline.revise_storyboard(MockLLM(), p, 2, "1장면을 밤으로")
    assert b.made_by == "both" and b.ask == "1장면을 밤으로" and b.scenes[0].time == "밤"
    assert b.scenes[1:] == first.scenes[1:] and "요청: 1장면을 밤으로" in b.protect
    pipeline.apply_storyboard_revision(p, 2, b)
    pipeline.apply_storyboard_revision(p, 2, pipeline.revise_storyboard(MockLLM(), p, 2, "한 번 더"))
    e = p.episode(2)
    assert e.storyboard.ask == "한 번 더" and e.storyboard_prev.scenes == first.scenes  # 연달아 고쳐도 처음 것을 남긴다
    pipeline.undo_storyboard(p, 2)
    assert e.storyboard.scenes == first.scenes and e.storyboard.made_by == "ai" and e.storyboard_prev is None
    with pytest.raises(ValueError, match="되돌릴"):
        pipeline.undo_storyboard(p, 2)
    # 작가가 저장하면 적용 취소는 없어진다
    pipeline.apply_storyboard_revision(p, 2, pipeline.revise_storyboard(MockLLM(), p, 2, "다시"))
    pipeline.set_storyboard(p, 2, e.storyboard.model_copy(deep=True))
    assert e.storyboard_prev is None


def test_web_board_revise_job_and_undo(demo):
    from canon import web

    c = TestClient(web.app)
    p = store.load(demo)
    _written(p, 1)
    store.save(demo, p)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "board", "ep": 2, "note": "1장면을 밤으로"})
    assert r.status_code == 400 and "먼저 만드세요" in r.text
    assert _wait(c, c.post(f"/api/projects/{demo}/jobs", json={"kind": "board", "ep": 2}).json()["id"])["status"] == "done"
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "board", "ep": 2, "note": "1장면을 밤으로"})
    assert r.status_code == 200 and r.json()["label"] == "2화 스토리보드 고친 안"
    j = _wait(c, r.json()["id"])
    assert j["status"] == "done" and j["result"] == {"revised": True}
    e = store.load(demo).episode(2)
    assert e.storyboard.scenes[0].time == "밤" and e.storyboard_prev is not None
    out = c.post(f"/api/projects/{demo}/episodes/2/storyboard/undo")
    assert out.status_code == 200
    e = store.load(demo).episode(2)
    assert e.storyboard.scenes[0].time != "밤" and e.storyboard_prev is None
    assert c.post(f"/api/projects/{demo}/episodes/2/storyboard/undo").status_code == 400


@needs_node
def test_board_js_changes_and_done_message():
    got = run_js(FILES, """(() => {
      const sc = (t) => ({ place: '부두', spot: '', time: t, present: [], events: [1], goal: '', turn: '', end_state: '' });
      const base = { scenes: [sc('새벽'), sc('아침')], time: { after: 0 }, stats: [], stat_basis: [], moves: [], attire: [], handover: [], protect: [], warnings: [] };
      const cur = JSON.parse(JSON.stringify(base));
      cur.scenes[1].time = '밤'; cur.scenes.push(sc('낮')); cur.protect = ['새 줄'];
      return [boardChanges(base, cur), boardChanges(base, base), boardChanges(null, base),
        JOB_DONE_MSG.board({ ep: 2, result: { revised: true } }), JOB_DONE_MSG.board({ ep: 2, result: null })];
    })()""", {})
    assert got[0] == ["장면 2", "장면 3 더함", "깨지 않을 것"] and got[1] == [] and got[2] == []
    assert got[3].startswith("2화 스토리보드를 요청대로 고쳤어요") and got[4].startswith("2화 스토리보드를 만들었어요")


class _EmptyScenes(MockLLM):
    """scenes 만 비운 응답을 몇 번 낸다 (실측: gemini-4-argon 이 성인 장면 플롯에서 그랬다)."""
    def __init__(self, empty: int):
        super().__init__()
        self.empty, self.calls, self.prompts = empty, 0, []

    def json(self, system, prompt, schema, hint=None):
        d = super().json(system, prompt, schema, hint)
        self.calls += 1
        self.prompts.append(prompt)
        if self.calls <= self.empty:
            d.scenes = []
        return d


def test_empty_scenes_retry_then_error(demo):
    p = store.load(demo)
    _written(p, 1)
    llm = _EmptyScenes(1)
    b = pipeline.make_storyboard(llm, p, 2)  # 한 번 비면 다시 묻는다
    assert llm.calls == 2 and b.scenes
    assert llm.prompts[1].startswith(llm.prompts[0]) and "scenes 가 비어" in llm.prompts[1]  # 덧붙임은 맨 뒤
    with pytest.raises(RuntimeError, match="장면을 하나도"):
        pipeline.make_storyboard(_EmptyScenes(2), p, 2)  # 두 번 비면 저장하지 않게 오류
    pipeline.set_storyboard(p, 2, b, by="ai")
    with pytest.raises(RuntimeError, match="장면을 하나도"):
        pipeline.revise_storyboard(_EmptyScenes(2), p, 2, "밤으로")
