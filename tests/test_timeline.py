"""작품 속 시간(canon/timeline.py) 테스트 (mock LLM): 반영, 프롬프트 블록, 기한 남은 날 · 예산, 되돌리기, 작가 수정, 끄기, CLI, 웹. 실행: python -m pytest tests"""
import importlib

from fastapi.testclient import TestClient

from canon import cli, context, pipeline, prompts, store, timeline
from canon.mock import MockLLM
from canon.schema import Deadline, StateDelta, StoryTime

from .test_storylines import _short

LLM = MockLLM()


def _play(p, frm, upto):
    for n in range(frm, upto + 1):
        pipeline.confirm_plot(p, n)
        p.episode(n).text = pipeline.write_episode(LLM, p, n)
        p.episode(n).status = "written"
        pipeline.apply_delta(p, pipeline.extract_state(LLM, p, n))
    return p


def test_no_record_keeps_write_prompt():
    p = _short(8)
    assert timeline.episode_block(p, 1) == "" and "작품 속 시간" not in prompts.episode_prompt(p, 1)
    assert timeline.check_rule(p, 1) == ""


def test_apply_tags_and_blocks():
    p = _play(_short(8), 1, 2)  # mock: 화마다 n일째 밤, 1화에 축제 기한(5일째)
    assert p.episode(2).time == StoryTime(day=2, part="밤")
    assert [d.id for d in p.timeline.deadlines] == ["dl-01-festival"] and p.timeline.deadlines[0].set_ep == 1
    p.episode(3).plot.time = "다음 날 아침"
    block = timeline.episode_block(p, 3)
    assert "직전 화(2화) 끝: 2일째 밤" in block and "다음 날 아침" in block and "등대 축제 (5일째, 3일 남음" in block
    w = prompts.episode_prompt(p, 3)
    assert "# 작품 속 시간" in w and "2화 [2일째 밤] " in w
    assert w.index("# 작품 속 시간") < w.index("# 직전 화 마지막 부분")  # 화마다 바뀌는 뒤쪽 블록
    s = prompts.state_prompt(p, 3)
    assert "[작품 속 시간]" in s and "직전 화 끝 2일째에서 이어 셉니다" in s and "dl-03-키워드" in s
    c = prompts.check_prompt(p, 3)
    assert "# 작품 속 시간" in c and "- 작품 속 시간:" in c
    assert "[작품 속 시간 (3화 직전)]" in prompts.plot_prompt(p, 3, 4)


def test_deadline_left_and_close():
    p = _play(_short(8), 1, 3)  # 3화에 축제 기한을 닫는다
    d = p.timeline.deadlines[0]
    assert d.done_ep == 3 and timeline.open_deadlines(p, 3) == [d] and timeline.open_deadlines(p, 4) == []
    assert timeline.left(Deadline(id="x", what="x", day=5), 7) == "2일 지남"
    assert timeline.left(Deadline(id="x", what="x", day=5), 5) == "오늘"
    assert timeline.left(Deadline(id="x", what="x"), 5) == ""


def test_deadline_budget_cuts_far_ones():
    p = _play(_short(8), 1, 1)
    for k in range(80):
        timeline.upsert(p, Deadline(id="", what=f"먼 약속 {k} " + "가" * 20, day=10 + k))
    rows, cut = timeline.deadline_lines(p, 2)
    assert cut > 0 and len(rows) + cut == 81 and "등대 축제" in rows[0]
    assert f"먼 것 {cut}개 생략" in timeline.episode_block(p, 2)
    assert sum(map(len, rows)) <= context.BUDGET["deadlines"]


def test_clean_delta():
    p = _play(_short(8), 1, 1)
    d = StateDelta(episode=2, summary="", time=StoryTime(day=-3),
                   deadlines_added=[Deadline(id="", what="장날", day=4), Deadline(id="a", what=""), Deadline(id="dl-02-x", what="첫 판"), Deadline(id="dl-02-x", what="둘째 판")],
                   deadlines_done=["dl-01-festival", "nope", "dl-01-festival"])
    timeline.clean_delta(p, d)
    assert d.time.day == 0
    assert [x.what for x in d.deadlines_added] == ["장날", "둘째 판"] and d.deadlines_added[0].id.startswith("dl-02")
    assert d.deadlines_done == ["dl-01-festival"]


def test_revert_restores_times_and_deadlines():
    p = _play(_short(8), 1, 3)
    pipeline.revert(p, 1)
    assert p.episode(2).time == StoryTime() and p.episode(1).time.day == 1
    assert p.timeline.deadlines[0].done_ep == 0  # 3화에 닫은 것이 다시 열린다
    p = _play(_short(8), 1, 3)
    for s in p.snapshots:
        s.deadlines = None  # 기한이 생기기 전 판의 스냅샷
    pipeline.revert(p, 2)
    assert [(d.id, d.done_ep) for d in p.timeline.deadlines] == [("dl-01-festival", 0)]
    pipeline.revert(p, 0)
    assert p.timeline.deadlines == []


def test_author_upsert_and_remove_follow_snapshots():
    p = _play(_short(8), 1, 2)
    d = timeline.upsert(p, Deadline(id="", what="빚 갚을 날", day=9, note="이레 안에"))
    assert d.set_ep == 2 and any(x.id == d.id for x in p.snapshot(2).deadlines)
    timeline.upsert(p, d.model_copy(update={"day": 8}))
    assert next(x for x in p.snapshot(2).deadlines if x.id == d.id).day == 8
    pipeline.revert(p, 2)  # 2화 스냅샷에 작가 기한이 있어 남는다
    assert any(x.id == d.id for x in p.timeline.deadlines)
    timeline.remove(p, d.id)
    assert all(x.id != d.id for s in p.snapshots for x in s.deadlines or [])
    for bad in (Deadline(id="", what=" "), Deadline(id="", what="a", day=-1)):
        try:
            timeline.upsert(p, bad)
            raise AssertionError("막혀야 한다")
        except ValueError:
            pass


def test_off_drops_blocks_and_rules():
    p = _play(_short(8), 1, 2)
    p.timeline.enabled = False
    assert timeline.episode_block(p, 3) == "" and timeline.state_rule(p, 3) == "" and timeline.tag(p, p.episode(2)) == ""
    assert "작품 속 시간" not in prompts.episode_prompt(p, 3) and "[작품 속 시간]" not in prompts.state_prompt(p, 3)


def test_view_rows_gap():
    p = _play(_short(8), 1, 3)
    p.episode(3).time.day = 1  # 시간이 거꾸로 감
    rows = timeline.rows(p)
    assert [r["gap"] for r in rows[:3]] == [None, 1, -1]
    v = timeline.view(p)
    assert v["now"] == "1일째 밤" and v["deadlines"][0]["done_ep"] == 3


def test_cli_and_web(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    importlib.reload(store)
    store.save("tl", _play(_short(8), 1, 2))
    cli.main(["time", "tl", "--start", "2024년 3월 2일 토요일", "--add", "빚 갚을 날@9", "--close", "dl-01-festival"])
    out = capsys.readouterr().out
    assert "기준: 1일째 = 2024년 3월 2일 토요일" in out and "빚 갚을 날 (9일째) · 7일 남음" in out and "2화에 닫힘" in out

    from canon import web
    importlib.reload(web)
    c = TestClient(web.app)
    v = c.get("/api/projects/tl/timeline").json()
    assert v["day"] == 2 and v["rows"][1]["gap"] == 1 and v["deadlines"][0]["left"] == "7일 남음"
    p = c.put("/api/projects/tl/timeline/deadlines", json={"what": "결혼식", "day": 12}).json()
    new = next(d for d in p["timeline"]["deadlines"] if d["what"] == "결혼식")
    assert new["set_ep"] == 2
    p = c.delete(f"/api/projects/tl/timeline/deadlines/{new['id']}").json()
    assert all(d["what"] != "결혼식" for d in p["timeline"]["deadlines"])
    assert c.put("/api/projects/tl/timeline/deadlines", json={"what": ""}).status_code == 400


def test_calendar_weekdays_in_blocks():
    p = _short(8)
    assert timeline.calendar(p) == (None, False, None) and timeline.day_label(p, 3) == "" and timeline.weekday_hint(p, 3) == ""
    p.timeline.start = "1일째 월요일"
    assert timeline.day_label(p, 30) == "화요일"  # 월요일로부터 29일 뒤
    assert timeline.weekday_hint(p, 2) == "2일째는 화요일. 같은 요일: 9 · 16 · 23 · 30 · 37일째"
    p.timeline.start = "2024년 3월 4일 금요일"  # 연도가 있으면 날짜로 요일을 센다
    assert timeline.calendar(p)[2] == 0 and timeline.day_label(p, 1) == "3월 4일 월요일"
    p.timeline.start = "2024년 12월 30일"
    assert timeline.day_label(p, 3) == "2025년 1월 1일 수요일"
    p.timeline.start = "2월 29일"
    assert timeline.day_label(p, 2) == "3월 1일"

    p = _play(_short(8), 1, 2)
    p.timeline.start = "2024년 3월 4일 월요일"
    p.episode(2).time.label = "화요일 저녁"  # AI 가 적은 요일 글은 계산한 것으로 바뀐다
    assert timeline.when(p, p.episode(2).time) == "2일째 밤 (3월 5일 화요일)"
    block = timeline.episode_block(p, 3)
    assert "직전 화(2화) 끝: 2일째 밤 (3월 5일 화요일)" in block and "요일 셈: 2일째는 화요일" in block
    assert "등대 축제 (5일째 = 3월 8일 금요일, 3일 남음" in block
    assert "Canon 이 계산합니다" in timeline.state_rule(p, 3) and "«»" in timeline.state_rule(p, 3)
    assert "직접 셈하지 말고" in timeline.check_rule(p, 3)
    assert "«»" in prompts.state_prompt(p, 3)
