"""자동 집필 승인 정책 중 이야기 데이터를 보는 칸 (새 인물 · 비밀 · 복선 회수 · 기한 · 시간 건너뜀 · 지운 칸)."""
import contextlib
import io
import os
import tempfile

import pytest

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())

from canon import autorun, jobs, mock, store  # noqa: E402
from canon.cli import main  # noqa: E402
from canon.schema import Character, CharacterState, Deadline, Foreshadow, Secret, StateDelta, StoryTime  # noqa: E402


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("CANON_BATCH_POLL", "0.01")
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(autorun, "_controls", {})
    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
        main(["arc", "demo", "-y"])
        main(["plot", "demo"])
        main(["confirm", "demo", "all"])
    yield "demo"
    jobs.draining.clear()


def Policy(**kw):
    """다른 정책(초반 화 멈춤, 관계 움직임)은 꺼 두고 고른 칸만 본다."""
    return autorun.Policy(**{"hand_pick_opening": False, "max_shift": 0, **kw})


def reasons(p, d, **kw):
    return autorun.review_reasons(p, d, None, Policy(**kw))


def test_off_by_default(demo):
    """새 칸은 모두 기본으로 꺼져 있어 예전처럼 멈추지 않는다."""
    p = store.load(demo)
    p.foreshadows.append(Foreshadow(id="fs-x", description="낡은 열쇠", planted_ep=1, due_ep=5, scope="series"))
    p.timeline.deadlines.append(Deadline(id="dl-x", what="축제 첫날", day=3, set_ep=1))
    p.episode(1).time = StoryTime(day=2)
    cid = p.characters[0].id
    d = StateDelta(episode=2, summary="s", new_characters=[Character(id="c-new", name="새사람", role="support")],
                   secrets_added=[Secret(id="s1", owner=cid, content="숨긴 편지")], foreshadow_resolved=["fs-x"],
                   deadlines_done=["dl-x"], time=StoryTime(day=400),
                   character_updates=[CharacterState(character_id=cid, cleared=["current_goal"])])
    assert reasons(p, d) == []
    pol = autorun.Policy()
    assert not (pol.stop_on_new_characters or pol.stop_on_secrets or pol.stop_on_resolve or pol.stop_on_early_resolve
                or pol.stop_on_deadline_done or pol.max_time_jump_days or pol.stop_on_clear)


def test_new_characters(demo):
    p = store.load(demo)
    d = StateDelta(episode=2, summary="s", new_characters=[Character(id="c-new", name="새사람", role="support")])
    assert reasons(p, d, stop_on_new_characters=True) == ["새 인물 1명이 나왔어요: 새사람"]
    assert reasons(p, StateDelta(episode=2, summary="s"), stop_on_new_characters=True) == []


def test_secrets(demo):
    p = store.load(demo)
    d = StateDelta(episode=2, summary="s", secrets_added=[Secret(id="s1", owner=p.characters[0].id, content="숨긴 편지")])
    assert reasons(p, d, stop_on_secrets=True) == ["새 비밀 1개가 생겼어요: 숨긴 편지"]
    assert reasons(p, StateDelta(episode=2, summary="s"), stop_on_secrets=True) == []


def test_resolve(demo):
    """복선 회수: 모두 멈춤과, 예정보다 이르거나 범위가 큰 복선만 멈춤. 없는 복선 · 닫힌 복선은 세지 않는다."""
    p = store.load(demo)
    p.foreshadows = [Foreshadow(id="fs-a", description="낡은 열쇠", planted_ep=1),
                     Foreshadow(id="fs-b", description="등대지기의 편지", planted_ep=1, due_ep=6),
                     Foreshadow(id="fs-c", description="왕가의 피", planted_ep=1, scope="series"),
                     Foreshadow(id="fs-d", description="닫힌 것", planted_ep=1, status="resolved")]
    plain = StateDelta(episode=3, summary="s", foreshadow_resolved=["fs-a", "ghost", "fs-d"])
    assert reasons(p, plain, stop_on_early_resolve=True) == []
    assert reasons(p, plain, stop_on_resolve=True) == ["복선 1개를 회수했어요: 낡은 열쇠"]
    early = StateDelta(episode=3, summary="s", foreshadow_resolved=["fs-a", "fs-b", "fs-c"])
    assert reasons(p, early, stop_on_early_resolve=True) == [
        "복선 2개를 회수했어요: 등대지기의 편지 (예정 6화보다 일찍); 왕가의 피 (작품 전체 범위)"]
    assert reasons(p, early, stop_on_resolve=True, stop_on_early_resolve=True)[0].startswith("복선 3개를 회수했어요")
    on_time = StateDelta(episode=6, summary="s", foreshadow_resolved=["fs-b"])
    assert reasons(p, on_time, stop_on_early_resolve=True) == []


def test_deadline_done(demo):
    p = store.load(demo)
    p.timeline.deadlines = [Deadline(id="dl-a", what="축제 첫날", day=3, set_ep=1),
                            Deadline(id="dl-b", what="이미 닫힘", set_ep=1, done_ep=1)]
    d = StateDelta(episode=2, summary="s", deadlines_done=["dl-a", "dl-b", "ghost"])
    assert reasons(p, d, stop_on_deadline_done=True) == ["기한 1개가 닫혔어요: 축제 첫날"]
    assert reasons(p, d) == []


def test_time_jump(demo):
    """시간 건너뜀: 직전 화 끝 날수에서 기준을 넘게 앞으로 가면 멈춘다. 어느 쪽이든 날수를 모르면 보지 않는다."""
    p = store.load(demo)
    for e in p.episodes:
        e.time = StoryTime()
    far = StateDelta(episode=2, summary="s", time=StoryTime(day=40))
    assert reasons(p, far, max_time_jump_days=30) == []  # 1화 날수를 모른다
    p.episode(1).time = StoryTime(day=5)
    assert reasons(p, far, max_time_jump_days=30) == ["작품 속 시간이 35일 건너뛰었어요: 5일째 → 40일째 (멈춤 기준 30일)"]
    assert reasons(p, StateDelta(episode=2, summary="s", time=StoryTime(day=35)), max_time_jump_days=30) == []
    assert reasons(p, StateDelta(episode=2, summary="s", time=StoryTime(day=1)), max_time_jump_days=30) == []  # 거슬러 가는 것은 보지 않는다
    assert reasons(p, StateDelta(episode=2, summary="s"), max_time_jump_days=30) == []  # 이번 화 날수를 모른다
    assert reasons(p, far) == []
    p.timeline.enabled = False
    assert reasons(p, far, max_time_jump_days=30) == []


def test_clear(demo):
    p = store.load(demo)
    c = p.characters[0]
    d = StateDelta(episode=2, summary="s", character_updates=[CharacterState(character_id=c.id, cleared=["current_goal", "notes"])])
    assert reasons(p, d, stop_on_clear=True) == [f"지운 상태 칸이 있어요: {c.name or c.id} 목표, 메모"]
    plain = StateDelta(episode=2, summary="s", character_updates=[CharacterState(character_id=c.id, notes="x")])
    assert reasons(p, plain, stop_on_clear=True) == []


def test_option_stops_run(demo, monkeypatch):
    """켠 정책은 실제 실행에서도 그 화를 검토 대기로 둔다."""
    real = mock.MockLLM.json

    def with_secret(self, *a, **kw):
        out = real(self, *a, **kw)
        if isinstance(out, StateDelta):
            out.secrets_added = [Secret(id="s-run", owner=store.load(demo).characters[0].id, content="실행 중 비밀")]
        return out
    monkeypatch.setattr(mock.MockLLM, "json", with_secret)
    run = autorun.start(demo, 1, False, Policy(check=False, stop_on_secrets=True), foreground=True)
    assert run.status == "review" and run.ep == 1
    assert "새 비밀 1개가 생겼어요: 실행 중 비밀" in run.reasons
