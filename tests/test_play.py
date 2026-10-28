"""플레이 엔진 시험 (mock LLM): 시작(세계 복사 · 반영 안 된 화 빼기 · 단편 → 장편 · 시간 단위), 구간(흘러간 일 → 결정 장면 →
반영), 한 구간 넘게 앞서 쓰지 않기, 끼어들기, 자동 결정, 운, 되감기, 장 접기, 결말과 한도, 설정 바꾸기 제안 남기기, 명령줄.
mock 은 짝수 구간에서만 결정 장면을 낸다 (mock_play.decides). 실행: python -m pytest tests"""
import pytest

from canon import cli, mock, mock_play, pipeline, play, prompts, store
from canon.schema import Episode, EpisodePlot, Part, PlayInfo, Project, StoryArc, StoryTime

from .test_passage import _written
from .test_restate import _two_done
from .test_web import client  # noqa: F401  (pytest fixture)

LLM = mock.MockLLM()


def _step(p, info, action="", kind=None):
    """구간 하나: 쓰기 → 화면이 닿음 → 반영."""
    s = play.scene(LLM, p, info, action, kind)
    n = info.turns[-1].number
    play.see(info, n)
    play.settle(LLM, p, info, n)
    return s, n


def _go(p, info, action=""):
    """결정 장면에서 멈춰 있으면 행동(없으면 첫 선택지)으로, 아니면 흐른다."""
    if play.waiting(info):
        return _step(p, info, action or info.turns[-1].choices[0].text)
    return _step(p, info, action)


def test_start_copies_world_and_converts_short(client):
    _two_done(client)
    raw = (store.project_dir("lh") / "project.json").read_bytes()
    w = store.load("lh")
    assert not w.serial and any(e.plot.number > 2 for e in w.episodes)  # 3화부터는 플롯만 있다
    p, info = play.start("lh", "pl", player="hero", person="first", seed=7, focus=" 수련 ")
    assert (store.project_dir("lh") / "project.json").read_bytes() == raw  # 세계 작품은 그대로
    assert store.load_play("lh") is None and not (store.project_dir("lh") / "branch.json").exists()
    assert store.load_play("pl") == info and info.world_ep == 2 and info.person == "first"
    assert info.unit == "day" and info.segment_units == play.SEGMENT_UNITS and info.focus == "수련"
    assert info.start_day == w.episode(2).time.day and not info.auto_decide
    assert [e.plot.number for e in p.episodes] == [1, 2]  # 반영 안 된 화는 뺐다
    assert p.serial and p.arc == [] and p.settings.keep_snapshots
    assert [(a.start_ep, a.end_ep) for a in p.story_arcs] == [(1, 2), (3, 22)]  # 세계를 아크 1, 첫 장은 3화부터 20구간
    pipeline.validate_story_arcs(p)
    assert p.snapshot(2) is not None
    q = store.load("pl")
    assert q.serial and [e.plot.number for e in q.episodes] == [1, 2]

    with pytest.raises(ValueError, match="이미 있는 이름"):
        play.start("lh", "pl", player="hero")
    with pytest.raises(ValueError, match="플레이 사본"):
        play.start("pl", "pl2", player="hero")
    with pytest.raises(ValueError, match="세계에 없는 인물"):
        play.start("lh", "pl3", player="nobody")
    with pytest.raises(ValueError, match="한도는 0"):
        play.start("lh", "pl3", player="hero", end_days=-1)
    assert not store.exists("pl3")  # 막히면 폴더를 남기지 않는다
    _, info4 = play.start("lh", "pl4", player="hero", unit="year")
    assert info4.unit == "year"


def test_pick_unit():
    def world(days):
        eps = [Episode(plot=EpisodePlot(number=i, act="기", title="", summary="", events=[], characters=[], emotional_shift="",
                                        ending_hook=""), status="finalized", time=StoryTime(day=d)) for i, d in enumerate(days, 1)]
        return Project(episodes=eps)
    assert play.pick_unit(world([])) == "day" and play.pick_unit(world([0, 0, 0])) == "day"  # 날수를 적은 화가 없다
    assert play.pick_unit(world([3, 3, 3, 4])) == "hour"
    assert play.pick_unit(world([1, 3, 5])) == "day"
    assert play.pick_unit(world([1, 60, 120])) == "month"
    assert play.pick_unit(world([1, 400, 800])) == "year"


def test_flow_decision_and_lookahead_cap(client):
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    s = play.scene(LLM, p, info)  # 첫 구간은 행동 없이. mock 은 홀수 구간에 결정이 없다
    t = info.turns[-1]
    assert (t.number, t.kind, t.state) == (3, "start", "pending") and t.beats and t.choices == [] and t.lean == 0
    ep = p.episode(3)
    assert ep.status == "written" and ep.plot.pov == "hero" and ep.plot.characters[0] == "hero"
    assert ep.text.splitlines()[0].startswith("[") and s.beats[1].text in ep.text  # 흘러간 일 줄에 시점이 붙는다
    with pytest.raises(ValueError, match="3구간 상태 반영이 끝나지 않았어요"):
        play.scene(LLM, p, info)
    play.settle(LLM, p, info, 3)
    assert t.state == "applied" and ep.status == "finalized" and ep.auto and ep.summary
    assert p.history[-1].episode == 3 and p.snapshot(3) is not None
    with pytest.raises(ValueError, match="이미 상태를 반영"):
        play.settle(LLM, p, info, 3)

    with pytest.raises(ValueError, match="아직 보지 않은 구간"):  # 화면이 닿기 전에는 한 구간 넘게 앞서 쓰지 않는다
        play.scene(LLM, p, info)
    play.see(info, 99)
    assert info.seen == 3  # 써 둔 구간보다 뒤로는 가지 않는다
    play.scene(LLM, p, info)
    t4 = info.turns[-1]
    assert (t4.number, t4.kind) == (4, "flow") and len(t4.choices) == 3 and t4.lean == 2
    assert "\"이제 어떻게 할래?\"" in p.episode(4).text and p.episode(4).plot.title == "시간이 흐른다"
    play.settle(LLM, p, info, 4)
    assert not play.waiting(info)  # 아직 4구간에 닿지 않았다
    play.see(info, 4)
    assert play.waiting(info)
    with pytest.raises(ValueError, match="결정할 차례"):
        play.scene(LLM, p, info)
    action, kind = play.auto_action(info)
    assert (action, kind) == ("시장 사람에게 말을 건다", "auto")
    _step(p, info, action, kind)
    assert info.turns[-1].kind == "auto" and info.turns[-1].action == action
    _go(p, info)
    action, kind = play.choice_action(info, 1)
    _step(p, info, action, kind)
    assert [t.kind for t in info.turns] == ["start", "flow", "auto", "flow", "choice"]


def test_interrupt_drops_unseen_segment(client):
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    _step(p, info)
    play.scene(LLM, p, info)  # 4구간을 앞서 써 둔다 (플레이어는 아직 3구간)
    play.settle(LLM, p, info, 4)
    luck4 = info.turns[-1].luck
    play.scene(LLM, p, info, "몰래 문을 연다")  # 흐르는 중 끼어들기: 보지 않은 4구간을 버리고 3구간 끝에서 행동
    t = info.turns[-1]
    assert [x.number for x in info.turns] == [3, 4] and (t.kind, t.action, t.luck) == ("free", "몰래 문을 연다", luck4)
    assert p.history[-1].episode == 3 and "몰래 문을 연다" in p.episode(4).text
    play.settle(LLM, p, info, 4)

    play.see(info, 4)
    _step(p, info, "등대로 간다")  # 4구간은 결정 장면, 5구간은 흐름
    play.scene(LLM, p, info)  # 6구간을 써 두고 반영 전에 끼어들어도 버린다
    play.scene(LLM, p, info, "등대로 달린다")
    assert [x.number for x in info.turns] == [3, 4, 5, 6] and info.turns[-1].action == "등대로 달린다"


def test_settle_failure_can_retry(client):
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    play.scene(LLM, p, info)

    class Broken:
        def json(self, *a, **k):
            raise RuntimeError("서버가 응답하지 않아요")

    with pytest.raises(RuntimeError):
        play.settle(Broken(), p, info, 3)
    t = info.turns[-1]
    assert t.state == "failed" and "응답" in t.error and p.episode(3).status == "written"
    play.see(info, 3)  # 화면은 구간을 먼저 보인다. 본 구간은 끼어들어도 버리지 않는다
    with pytest.raises(ValueError, match="응답"):
        play.scene(LLM, p, info, "등대로 간다")
    play.settle(LLM, p, info, 3)
    assert t.state == "applied" and t.error == ""


def test_luck_is_seeded():
    a, b = PlayInfo(world="w", player="x", seed=7), PlayInfo(world="w", player="x", seed=8)
    rolls = [play.roll_luck(a, n) for n in range(1, 200)]
    assert rolls == [play.roll_luck(a.model_copy(), n) for n in range(1, 200)]
    assert rolls != [play.roll_luck(b, n) for n in range(1, 200)]
    assert set(rolls) <= {-2, -1, 0, 1, 2} and rolls.count(0) > rolls.count(2) and rolls.count(0) > rolls.count(-2)


def test_rewind_then_new_segment_same_number(client):
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    for _ in range(3):
        _go(p, info)
    assert [t.number for t in info.turns] == [3, 4, 5]
    luck4 = info.turns[1].luck
    state3 = p.snapshot(3)
    with pytest.raises(ValueError, match="되감을 수 있는 곳"):
        play.rewind(p, info, 1)  # 세계의 화로는 되감지 않는다
    play.rewind(p, info, 3)
    assert [t.number for t in info.turns] == [3] and [e.plot.number for e in p.episodes] == [1, 2, 3] and info.seen == 3
    assert p.history[-1].episode == 3 and [s.model_dump() for s in p.states] == [s.model_dump() for s in state3.states]
    assert p.arc_for(4) is not None
    _, n = _step(p, info, "집으로 돌아가 쉰다")
    assert n == 4 and info.turns[-1].luck == luck4 and "집으로" in p.episode(4).text  # 같은 번호, 같은 운

    play.rewind(p, info, 2)  # 시작 전으로: 첫 구간부터 다시
    assert info.turns == [] and [e.plot.number for e in p.episodes] == [1, 2]
    play.scene(LLM, p, info, "무시되는 행동")
    assert info.turns[-1].kind == "start"


def test_chapters_fold_and_story_keeps_recent_segments(client, monkeypatch):
    monkeypatch.setattr(play, "CHAPTER_LEN", 3)
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    assert [(a.start_ep, a.end_ep) for a in p.story_arcs] == [(1, 2), (3, 5)]
    for _ in range(4):
        _go(p, info)
    ch1 = p.arc_for(5)
    assert ch1.title == "1장" and ch1.summary.startswith("아크 2 요약")  # 마지막 구간을 반영하면 요약으로 접는다
    assert [(a.start_ep, a.end_ep) for a in p.story_arcs] == [(1, 2), (3, 5), (6, 8)]
    pipeline.validate_story_arcs(p)
    text = prompts.story_so_far(p, 7)
    assert "아크 2 요약" in text and "[이번 아크 3 2장]" in text and "6화" in text  # 접은 장과 지금 장의 구간 요약이 함께 들어간다

    play.rewind(p, info, 5)  # 장 끝으로 되감으면 접은 요약은 두고 다음 장을 새로 연다
    assert p.arc_for(5).summary and p.arc_for(6).summary == "" and (p.arc_for(6).start_ep, p.arc_for(6).end_ep) == (6, 8)
    play.rewind(p, info, 4)  # 접힌 장 안으로 되감으면 요약을 비우고 다시 연다
    ch1 = p.arc_for(5)
    assert ch1.summary == "" and (ch1.start_ep, ch1.end_ep) == (3, 5) and p.arc_for(6) is None
    _go(p, info)
    assert p.arc_for(5).summary and p.arc_for(6) is not None


def test_serial_world_with_parts(client):
    _two_done(client)
    w = store.load("lh")
    w.meta.form, w.arc = "serial", []
    w.story_arcs = [StoryArc(number=1, title="첫 아크", start_ep=1, end_ep=5, goal="g", acts=play._acts(1, 5))]
    w.parts = [Part(number=1, title="1부", start_ep=1, end_ep=10, goal="g")]
    store.save("lh", w)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    assert [(a.start_ep, a.end_ep, a.summary) for a in p.story_arcs] == [(1, 2, ""), (3, 22, "")]
    assert [(x.title, x.start_ep, x.end_ep) for x in p.parts] == [("1부", 1, 2), (play.PLAY_PART, 3, 22)]
    pipeline.validate_story_arcs(p)


def test_ending_and_rewind_reopens(client):
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    _go(p, info)
    _step(p, info, f"모든 것을 {mock_play.MOCK_ENDING_WORD}")
    assert info.ending and info.ended_ep == 4 and info.turns[-1].ending
    with pytest.raises(ValueError, match="플레이가 끝났어요"):
        play.scene(LLM, p, info, "등대로 간다")
    play.rewind(p, info, 3)
    assert info.ending == "" and info.ended_ep == 0
    _step(p, info, "등대로 간다")
    assert info.ending == "" and info.turns[-1].number == 4


@pytest.mark.parametrize("limit, steps, word", [({"max_turns": 2}, 2, "구간 한도"), ({"end_decisions": 1}, 3, "결정 한도"),
                                                ({"end_days": 2}, 2, "2일이 지났어요")])
def test_limits_end_play(client, limit, steps, word):
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7, **limit)
    for _ in range(steps):
        assert info.ending == ""
        _go(p, info)
    assert word in info.ending and info.ended_ep == info.turns[-1].number
    if "max_turns" in limit:
        assert p.arc_for(3).end_ep == 4  # 장도 한도에서 끝난다


def test_setting_change_is_held(client):
    _written(client)  # 1화만 반영한 세계: 첫 구간이 2화라 mock 이 설정 바꾸기 제안을 낸다
    client.post("/api/projects/lh/episodes/1/apply", json=client.post("/api/projects/lh/episodes/1/state").json())
    p, info = play.start("lh", "pl", player="hero", seed=7)
    look = next(c for c in p.characters if c.id == "hero").appearance
    _step(p, info)
    assert info.turns[-1].number == 2
    assert next(c for c in p.characters if c.id == "hero").appearance == look  # 반영하지 않았다
    assert [x.episode for x in p.setting_held] == [2] and p.episode(2).auto
    play.rewind(p, info, 1)
    assert p.setting_held == []  # 되감으면 남겨 둔 제안도 지운다


def test_cli_flow(client, capsys):
    _two_done(client)
    cli.main(["play", "new", "lh", "pl", "--as", "hero", "--seed", "7", "--person", "third", "--unit", "month"])
    out = capsys.readouterr().out
    assert "플레이를 열었어요" in out and "시간 단위 한 달" in out and "(mock 3구간)" in out and "3구간 상태를 반영했어요" in out
    cli.main(["play", "turn", "pl"])  # 시간이 흐른다 → 4구간 결정 장면
    out = capsys.readouterr().out
    assert "결정할 차례예요" in out and "1. 등대로 간다" in out and "4구간 상태를 반영했어요" in out
    with pytest.raises(SystemExit, match="결정할 차례"):
        cli.main(["play", "turn", "pl"])
    cli.main(["play", "turn", "pl", "--choice", "1"])
    assert "등대로 간다." in capsys.readouterr().out
    cli.main(["play", "turn", "pl", "몰래 문을 연다"])
    capsys.readouterr()
    info = store.load_play("pl")
    assert [(t.number, t.kind, t.state) for t in info.turns] == [
        (3, "start", "applied"), (4, "flow", "applied"), (5, "choice", "applied"), (6, "free", "applied")]
    cli.main(["play", "turn", "pl", "--auto"])
    capsys.readouterr()
    assert store.load_play("pl").turns[-1].kind == "auto"
    assert (store.project_dir("pl") / "episodes" / "07.md").exists()
    cli.main(["play", "log", "pl"])
    out = capsys.readouterr().out
    assert "6구간 [직접] 몰래 문을 연다 · 결정 · 반영함" in out and "4구간 [흐름] 시간이 흐름 · 결정" in out and "luck" not in out
    cli.main(["play", "rewind", "pl", "3", "-y"])
    capsys.readouterr()
    assert [t.number for t in store.load_play("pl").turns] == [3]
    assert not (store.project_dir("pl") / "episodes" / "05.md").exists()
    cli.main(["play", "end", "pl", "--reason", "오늘은 여기까지"])
    assert store.load_play("pl").ending == "오늘은 여기까지"
    cli.main(["play", "show", "pl"])
    assert "이야기가 끝났어요: 오늘은 여기까지" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="플레이가 끝났어요"):
        cli.main(["play", "turn", "pl", "등대로 간다"])
    with pytest.raises(SystemExit, match="--as"):
        cli.main(["play", "new", "lh", "pl2"])
