"""플레이 엔진 시험 (mock LLM): 시작(세계 복사 · 반영 안 된 화 빼기 · 단편 → 장편), 턴(장면 → 반영), 운, 되감기, 장 접기, 결말,
설정 바꾸기 제안 남기기, 명령줄. 실행: python -m pytest tests"""
import pytest

from canon import cli, mock, mock_play, pipeline, play, prompts, store
from canon.schema import Part, StoryArc

from .test_passage import _written
from .test_restate import _two_done
from .test_web import client  # noqa: F401  (pytest fixture)

LLM = mock.MockLLM()


def _turn(p, info, action="", kind="choice"):
    s = play.scene(LLM, p, info, action, kind)
    n = info.turns[-1].number
    play.settle(LLM, p, info, n)
    return s, n


def test_start_copies_world_and_converts_short(client):
    _two_done(client)
    raw = (store.project_dir("lh") / "project.json").read_bytes()
    w = store.load("lh")
    assert not w.serial and any(e.plot.number > 2 for e in w.episodes)  # 3화부터는 플롯만 있다
    p, info = play.start("lh", "pl", player="hero", person="first", seed=7)
    assert (store.project_dir("lh") / "project.json").read_bytes() == raw  # 세계 작품은 그대로
    assert store.load_play("lh") is None and not (store.project_dir("lh") / "branch.json").exists()
    assert store.load_play("pl") == info and info.world_ep == 2 and info.person == "first"
    assert [e.plot.number for e in p.episodes] == [1, 2]  # 반영 안 된 화는 뺐다
    assert p.serial and p.arc == [] and p.settings.keep_snapshots
    assert [(a.start_ep, a.end_ep) for a in p.story_arcs] == [(1, 2), (3, 22)]  # 세계를 아크 1, 첫 장은 3화부터 20턴
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
    assert not store.exists("pl3")  # 막히면 폴더를 남기지 않는다


def test_turn_applies_and_blocks_until_settled(client):
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    s = play.scene(LLM, p, info)  # 첫 턴은 행동 없이
    t = info.turns[-1]
    assert (t.number, t.kind, t.state) == (3, "start", "pending") and len(t.choices) == 4
    ep = p.episode(3)
    assert ep.status == "written" and ep.text == s.text and ep.plot.characters[0] == "hero"
    with pytest.raises(ValueError, match="3턴 상태 반영이 끝나지 않았어요"):
        play.scene(LLM, p, info, "등대로 간다")
    play.settle(LLM, p, info, 3)
    assert t.state == "applied" and ep.status == "finalized" and ep.auto and ep.summary
    assert p.history[-1].episode == 3 and p.snapshot(3) is not None
    with pytest.raises(ValueError, match="이미 상태를 반영"):
        play.settle(LLM, p, info, 3)
    with pytest.raises(ValueError, match="행동을 적거나"):
        play.scene(LLM, p, info, " ")

    action, kind = play.choice_action(info, 4)  # 사흘 뒤로 (건너뛰기)
    assert kind == "skip" and "사흘" in action
    play.scene(LLM, p, info, action, kind)
    assert p.episode(4).plot.time == "사흘 뒤" and info.turns[-1].kind == "skip"


def test_settle_failure_can_retry(client, monkeypatch):
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
    with pytest.raises(ValueError, match="응답"):
        play.scene(LLM, p, info, "등대로 간다")
    play.settle(LLM, p, info, 3)
    assert t.state == "applied" and t.error == ""


def test_luck_is_seeded():
    from canon.schema import PlayInfo
    a, b = PlayInfo(world="w", player="x", seed=7), PlayInfo(world="w", player="x", seed=8)
    rolls = [play.roll_luck(a, n) for n in range(1, 200)]
    assert rolls == [play.roll_luck(a.model_copy(), n) for n in range(1, 200)]
    assert rolls != [play.roll_luck(b, n) for n in range(1, 200)]
    assert set(rolls) <= {-2, -1, 0, 1, 2} and rolls.count(0) > rolls.count(2) and rolls.count(0) > rolls.count(-2)


def test_rewind_then_new_turn_same_number(client):
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    _turn(p, info)
    _turn(p, info, "등대로 간다")
    _turn(p, info, "시장 사람에게 말을 건다")
    assert [t.number for t in info.turns] == [3, 4, 5]
    luck4 = info.turns[1].luck
    state3 = p.snapshot(3)
    with pytest.raises(ValueError, match="되감을 수 있는 곳"):
        play.rewind(p, info, 1)  # 세계의 화로는 되감지 않는다
    play.rewind(p, info, 3)
    assert [t.number for t in info.turns] == [3] and [e.plot.number for e in p.episodes] == [1, 2, 3]
    assert p.history[-1].episode == 3 and [s.model_dump() for s in p.states] == [s.model_dump() for s in state3.states]
    assert p.arc_for(4) is not None
    _, n = _turn(p, info, "집으로 돌아가 쉰다")
    assert n == 4 and info.turns[-1].luck == luck4 and "집으로" in p.episode(4).text  # 같은 번호, 같은 운

    play.rewind(p, info, 2)  # 시작 전으로: 첫 턴부터 다시
    assert info.turns == [] and [e.plot.number for e in p.episodes] == [1, 2]
    play.scene(LLM, p, info, "무시되는 행동")
    assert info.turns[-1].kind == "start"


def test_chapters_fold_and_story_keeps_recent_turns(client, monkeypatch):
    monkeypatch.setattr(play, "CHAPTER_LEN", 3)
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    assert [(a.start_ep, a.end_ep) for a in p.story_arcs] == [(1, 2), (3, 5)]
    for action in ("", "등대로 간다", "시장 사람에게 말을 건다", "집으로 돌아가 쉰다"):
        _turn(p, info, action)
    ch1 = p.arc_for(5)
    assert ch1.title == "1장" and ch1.summary.startswith("아크 2 요약")  # 마지막 턴을 반영하면 요약으로 접는다
    assert [(a.start_ep, a.end_ep) for a in p.story_arcs] == [(1, 2), (3, 5), (6, 8)]
    pipeline.validate_story_arcs(p)
    text = prompts.story_so_far(p, 7)
    assert "아크 2 요약" in text and "[이번 아크 3 2장]" in text and "6화" in text  # 접은 장과 지금 장의 턴 요약이 함께 들어간다

    play.rewind(p, info, 5)  # 장 끝으로 되감으면 접은 요약은 두고 다음 장을 새로 연다
    assert p.arc_for(5).summary and p.arc_for(6).summary == "" and (p.arc_for(6).start_ep, p.arc_for(6).end_ep) == (6, 8)
    play.rewind(p, info, 4)  # 접힌 장 안으로 되감으면 요약을 비우고 다시 연다
    ch1 = p.arc_for(5)
    assert ch1.summary == "" and (ch1.start_ep, ch1.end_ep) == (3, 5) and p.arc_for(6) is None
    _turn(p, info, "등대로 간다")
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
    p, info = play.start("lh", "pl", player="hero", seed=7, max_turns=0)
    _turn(p, info)
    _turn(p, info, f"모든 것을 {mock_play.MOCK_ENDING_WORD}")
    assert info.ending and info.ended_ep == 4 and info.turns[-1].ending
    with pytest.raises(ValueError, match="플레이가 끝났어요"):
        play.scene(LLM, p, info, "등대로 간다")
    play.rewind(p, info, 3)
    assert info.ending == "" and info.ended_ep == 0
    _turn(p, info, "등대로 간다")
    assert info.ending == "" and info.turns[-1].number == 4


def test_max_turns_ends_play(client):
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7, max_turns=2)
    assert p.arc_for(3).end_ep == 4  # 장도 한도에서 끝난다
    _turn(p, info)
    _turn(p, info, "등대로 간다")
    assert "턴 한도" in info.ending and p.arc_for(4).summary


def test_setting_change_is_held(client):
    _written(client)  # 1화만 반영한 세계: 첫 턴이 2화라 mock 이 설정 바꾸기 제안을 낸다
    client.post("/api/projects/lh/episodes/1/apply", json=client.post("/api/projects/lh/episodes/1/state").json())
    p, info = play.start("lh", "pl", player="hero", seed=7)
    look = next(c for c in p.characters if c.id == "hero").appearance
    _turn(p, info)
    assert info.turns[-1].number == 2
    assert next(c for c in p.characters if c.id == "hero").appearance == look  # 반영하지 않았다
    assert [x.episode for x in p.setting_held] == [2] and p.episode(2).auto
    play.rewind(p, info, 1)
    assert p.setting_held == []  # 되감으면 남겨 둔 제안도 지운다


def test_cli_flow(client, capsys):
    _two_done(client)
    cli.main(["play", "new", "lh", "pl", "--as", "hero", "--seed", "7", "--person", "third"])
    out = capsys.readouterr().out
    assert "플레이를 열었어요" in out and "(mock 3턴 장면)" in out and "4. 사흘 뒤로" in out and "3턴 상태를 반영했어요" in out
    cli.main(["play", "turn", "pl", "--choice", "1"])
    out = capsys.readouterr().out
    assert "등대로 간다." in out and "4턴 상태를 반영했어요" in out
    cli.main(["play", "turn", "pl", "몰래 문을 연다"])
    capsys.readouterr()
    info = store.load_play("pl")
    assert [(t.number, t.kind, t.state) for t in info.turns] == [(3, "start", "applied"), (4, "choice", "applied"), (5, "free", "applied")]
    assert (store.project_dir("pl") / "episodes" / "05.md").exists()
    cli.main(["play", "log", "pl"])
    out = capsys.readouterr().out
    assert "5턴 [직접] 몰래 문을 연다 · 반영함" in out and "luck" not in out
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
