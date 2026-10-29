"""장면 연출 쓰기 프롬프트 블록 (stage.episode_lines, prompts.stage_block). 실행: python -m pytest tests"""
from canon import context, prompts, stage
from canon.schema import (Character, Episode, EpisodePlot, Project, StageBeat, StageBody, StageContact, StageScene,
                          StageSpot)


def _plot(n: int = 1) -> EpisodePlot:
    return EpisodePlot(number=n, title="다툼", act="기", summary="하린과 도윤이 다툰다", characters=["h", "d"],
                       emotional_shift="", ending_hook="", events=["하린이 방에 들어온다", "둘이 다툰다"])


def _scene(sid: str = "s1", event: int = 1, sexual: bool = False, room: str = "r1") -> StageScene:
    r = stage.make_room("bedroom", room)
    a = {x.name: x.id for x in r.anchors}
    touch = [StageContact(id=f"{sid}c2", by="right", to="h", part="chest", act="stroke")] if sexual else []
    return StageScene(id=sid, event=event, event_text=_plot().events[event], room=room, cast=["h", "d"], start=[
        StageBody(who="h", at=StageSpot(ref=a["문"], rel="front"), posture="stand", facing="@d", left="", right="컵"),
        StageBody(who="d", at=StageSpot(ref=a["침대"], rel="on"), posture="lie"),
    ], beats=[
        StageBeat(bodies=[StageBody(who="h", at=StageSpot(ref=a["침대"], rel="beside"),
                                    contacts=[StageContact(id=f"{sid}c1", by="left", to="d", part="wrist_r", act="hold")])]),
        StageBeat(bodies=[StageBody(who="d", posture="chair", contacts=touch), StageBody(who="h", ends=[f"{sid}c1"])]),
    ])


def _project(scenes=None, adult: bool = True, minor: bool = False) -> Project:
    p = Project(characters=[Character(id="h", name="하린", role="주인공", age="16" if minor else "27"),
                            Character(id="d", name="도윤", role="조연", age="29")])
    p.meta.adult = adult
    p.rooms.append(stage.make_room("bedroom", "r1", "하린의 방"))
    p.episodes.append(Episode(plot=_plot(), stage=[_scene()] if scenes is None else scenes))
    return p


def test_beat_summary_uses_names_not_coordinates():
    lines, dropped, filtered = stage.episode_lines(_project(), _project().episodes[0])
    assert (dropped, filtered) == (0, 0)
    assert lines == [[
        "사건 2: 둘이 다툰다 · 하린의 방 · 기준점: 침대, 책상, 의자, 창, 문",
        "- 시작 하린: 문 앞 서기, 도윤 쪽을 봄, 왼손 빈손, 오른손에 컵",
        "- 시작 도윤: 침대 위 눕기",
        "1. 하린: 문 앞 서기 → 침대 옆, 왼손으로 도윤 오른 손목 잡기",
        "2. 도윤: 의자에 앉기 / 하린: 왼손으로 도윤 오른 손목 잡기 멈춤",
    ]]


def test_block_comes_after_static_context():
    p = _project()
    ctx = prompts.build_episode_context(p, 1)
    assert "# 장면 연출" in ctx
    assert ctx.index(prompts.static_context(p)) < ctx.index("# 장면 연출")
    assert "왼손으로 도윤 오른 손목 잡기" in ctx


def test_brief_has_same_block():
    p = _project()
    block = prompts.stage_block(p, 1)
    assert block and block in prompts.episode_brief(p, 1)


def test_no_scene_means_empty_block():
    p = _project(scenes=[])
    assert prompts.stage_block(p, 1) == ""
    assert "# 장면 연출" not in prompts.build_episode_context(p, 1)
    assert prompts.stage_block(p, 9) == ""  # 없는 화


def test_switched_off_and_lost_event_are_left_out():
    off = _scene()
    off.prompt = False
    lost = _scene("s2", event=0)
    lost.event, lost.event_text = 7, "지운 사건"
    assert prompts.stage_block(_project(scenes=[off, lost]), 1) == ""


def test_budget_drops_later_scenes_and_counts_them():
    p = _project(scenes=[_scene("s2", event=1), _scene("s1", event=0)])
    full = prompts.stage_block(p, 1)
    assert full.index("사건 1:") < full.index("사건 2:")  # 사건 순서
    one = prompts.stage_block(p, 1, budget=len(full) // 2)
    assert "사건 1:" in one and "사건 2:" not in one and "(장면 1개 생략)" in one
    assert context.BUDGET["stage"] == 1_500


def test_all_ages_work_drops_sexual_contacts():
    p = _project(scenes=[_scene(sexual=True)], adult=False)
    lines, dropped, filtered = stage.episode_lines(p, p.episodes[0])
    assert (dropped, filtered) == (0, 1)
    assert "가슴" not in prompts.stage_block(p, 1)
    assert "오른 손목 잡기" in prompts.stage_block(p, 1)  # 성적이 아닌 접촉은 남는다


def test_adult_work_keeps_sexual_contacts():
    p = _project(scenes=[_scene(sexual=True)], adult=True)
    assert stage.episode_lines(p, p.episodes[0])[1:] == (0, 0)
    assert "오른손으로 하린 가슴 쓰다듬기" in prompts.stage_block(p, 1)


def test_minor_sexual_contact_never_enters():
    for adult in (True, False):
        p = _project(scenes=[_scene(sexual=True)], adult=adult, minor=True)
        lines, dropped, _ = stage.episode_lines(p, p.episodes[0])
        assert dropped == 1
        assert "가슴" not in prompts.stage_block(p, 1)
        assert "가슴" not in prompts.episode_brief(p, 1)


def test_new_relation_words_read_as_labels():
    p = _project()
    assert stage._spot_text(StageSpot(ref="@d", rel="across"), None, p) == "도윤 맞은편"
    assert stage._spot_text(StageSpot(ref="@d", rel="against"), None, p) == "도윤 기대어 맞닿음"
