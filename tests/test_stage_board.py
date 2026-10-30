"""장면 연출과 화별 스토리보드 잇기 (docs/stage/specs/08-board.md): stage.board_scene_of · room_hints · new_scene · view,
prompts.stage_board_lines · stage_block 자리, 화면 stage.js 의 사건 칩 묶음 · 방 순서, board.js 의 '🎬 연출' 링크."""
import re

from canon import prompts, stage
from canon.schema import BoardScene, Character, Episode, EpisodePlot, Project, Storyboard

from .jsvm import STATIC, needs_node, run_js
from .test_stage_prompt import _scene

FILES = re.findall(r'src="/static/([a-z0-9-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


def _board() -> Storyboard:
    return Storyboard(scenes=[
        BoardScene(place="등대섬", spot="하린의 방", present=["h"], events=[1], goal="편지를 숨긴다"),
        BoardScene(place="부두", spot="부두 끝 창고", present=["d", "h", "x", "d"], events=[2, 3],
                   goal="도윤을 붙든다", turn="도윤이 편지를 본다", end_state="둘이 창고에 남는다"),
    ])


def _project(board: bool = True) -> Project:
    p = Project(characters=[Character(id="h", name="하린", role="주인공", age="27"), Character(id="d", name="도윤", role="조연", age="29"),
                            Character(id="m", name="민서", role="조연", age="30")])
    p.rooms += [stage.make_room("bedroom", "r1", "하린의 방"), stage.make_room("empty", "r2", "창고", place="부두"),
                stage.make_room("office", "r3", "부두 끝 창고"), stage.make_room("empty", "r5", "부두 끝 창고 2층"), stage.make_room("living", "r4", "거실")]
    plot = EpisodePlot(number=1, title="다툼", act="기", summary="", characters=["h", "d", "m"], emotional_shift="", ending_hook="",
                       events=["하린이 방에 들어온다", "둘이 다툰다", "도윤이 편지를 본다", "하린이 떠난다"])
    p.episodes.append(Episode(plot=plot, storyboard=_board() if board else None))
    return p


def test_board_scene_of():
    p = _project()
    ep = p.episodes[0]
    assert stage.board_scene_of(ep, 0)[0] == 1
    k, sc = stage.board_scene_of(ep, 2)
    assert (k, sc.spot) == (2, "부두 끝 창고")
    assert stage.board_scene_of(ep, 3) is None  # 4번 사건은 맡은 장면이 없다
    assert stage.board_scene_of(_project(board=False).episodes[0], 0) is None


def test_room_hints_order():
    p = _project()
    sc = p.episodes[0].storyboard.scenes[1]
    assert stage.room_hints(p, sc) == ["r3", "r2", "r5"]  # 자리와 같은 이름 → 자리와 서로 포함(목록 순서), 거실 · 침실은 뺌
    assert stage.room_hints(p, p.episodes[0].storyboard.scenes[0]) == ["r1"]
    assert stage.room_hints(p, BoardScene()) == []


def test_new_scene_cast_from_present():
    p = _project()
    ep = p.episodes[0]
    s = stage.new_scene(p, ep, 1, p.rooms[1])
    assert s.cast == ["d", "h"]  # present 순서, 모르는 id x 와 겹친 d 는 뺌
    assert [b.who for b in s.start] == ["d", "h"]
    rest = stage.new_scene(p, ep, 3, p.rooms[0])
    assert rest.cast == ["h", "d", "m"]  # 맡은 장면이 없으면 플롯 등장 인물


def test_view_has_board_events():
    p = _project()
    v = stage.view(p, 1)["board"]
    assert v["stale"] is False
    assert [x and x["no"] for x in v["events"]] == [1, 2, 2, None]
    assert v["events"][1] == {"no": 2, "place": "부두", "spot": "부두 끝 창고", "hints": ["r3", "r2", "r5"]}
    assert stage.view(_project(board=False), 1)["board"]["events"] == []


def test_draft_prompt_has_board_scene():
    p = _project()
    text = prompts.stage_draft_prompt(p, 1, 2)
    assert "[이 사건을 맡은 스토리보드 장면 2]" in text
    for line in ("- 장소: 부두 · 부두 끝 창고", "- 함께 있는 인물: 도윤, 하린, x, 도윤", "- 목표: 도윤을 붙든다",
                 "- 전환: 도윤이 편지를 본다", "- 끝: 둘이 창고에 남는다"):
        assert line in text
    assert text.index("[이번 사건]") < text.index("[이 사건을 맡은 스토리보드 장면 2]") < text.index("할 일:")
    assert "스토리보드 장면" not in prompts.stage_draft_prompt(p, 1, 3)
    assert "스토리보드 장면" not in prompts.stage_draft_prompt(_project(board=False), 1, 2)


def _with_stage(board: bool = True) -> Project:
    p = _project(board)
    p.rooms[0] = stage.make_room("bedroom", "r1", "하린의 방")
    s = _scene()  # 2번 사건 '둘이 다툰다', 방 r1
    p.episodes[0].stage.append(s)
    return p


def test_context_moves_stage_block_after_board():
    p = _with_stage()
    ctx = prompts.build_episode_context(p, 1)
    i, j, k = ctx.index("# 이번 화 스토리보드"), ctx.index("# 장면 연출"), ctx.index("# 이번 화 플롯")
    assert i < j < k
    assert ctx.count("# 장면 연출") == 1
    assert "스토리보드 장면 2 · 사건 2: 둘이 다툰다" in ctx
    assert ctx[j:k].count("\n# ") == 0  # 사이에 다른 블록이 없다: 스토리보드 바로 뒤, 플롯 바로 앞


def test_context_keeps_stage_block_without_board():
    for ctx in (prompts.build_episode_context(_with_stage(board=False), 1), prompts.build_episode_context(_with_stage(), 1, use_board=False)):
        assert "# 이번 화 스토리보드" not in ctx
        j = ctx.index("# 장면 연출")
        assert j < ctx.index("# 이번 화 플롯")
        assert "스토리보드 장면" not in ctx
        assert "사건 2: 둘이 다툰다" in ctx


@needs_node
def test_js_event_groups_and_room_order():
    board = [{"no": 1, "place": "등대섬", "spot": "하린의 방"}, {"no": 2, "place": "부두", "spot": "부두 끝 창고"},
             {"no": 2, "place": "부두", "spot": "부두 끝 창고"}, None, {"no": 1, "place": "", "spot": ""}]
    got = run_js(FILES, "[stgEventGroups(5, data.board), stgEventGroups(3, []), stgRoomOrder(data.rooms, ['c', 'a']).map((r) => r.id)]",
                 {"board": board, "rooms": [{"id": x} for x in "abcd"]})
    assert got[0] == [{"no": 1, "place": "등대섬", "spot": "하린의 방", "events": [1]},
                      {"no": 2, "place": "부두", "spot": "부두 끝 창고", "events": [2, 3]},
                      {"no": None, "place": "", "spot": "", "events": [4]},
                      {"no": 1, "place": "", "spot": "", "events": [5]}]
    assert got[1] == [{"no": None, "place": "", "spot": "", "events": [1, 2, 3]}]
    assert got[2] == ["c", "a", "b", "d"]


@needs_node
def test_js_board_stage_link():
    got = run_js(FILES, "S.route = ['p', 'demo']; [boardStageLink(3, {events: [4, 2]}), boardStageLink(3, {events: []})]", {})
    assert "/stage/3/2" in got[0] and "🎬 연출" in got[0]
    assert got[1] == ""
