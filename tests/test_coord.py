"""쓰기 재료 '조율' (Settings.write_material = coord, coord.py): 감독은 무엇이 바뀌는지만 정하고 동작은 본문을 쓰는 AI 가 정한다.
고정점만 위에서 플롯 사건을 조율 메모(Episode.coord)로 바꾸고, 이어받을 것의 몸 · 물건 줄을 빼고, 끝 차림은 지키기만 하게 한다.

    CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_coord.py
"""
from fastapi.testclient import TestClient

from canon import board, coord, cue, pipeline, prompts, store
from canon.llm import get_llm
from canon.mock import MockLLM
from canon.schema import CoordDraft, CoordMemo, Storyboard

from .test_storyboard import EXAMPLES, _written, demo  # noqa: F401  (pytest fixture)
from .test_web import _wait


def _ready(name: str, memo: bool = True):
    """2화에 스토리보드와 뼈대 큐 시트를 두고 쓰기 재료를 조율로 둔다. memo 면 지금 플롯으로 만든 조율 메모도 둔다."""
    p = store.load(name)
    _written(p, 1)
    e = p.episode(2)
    e.storyboard = Storyboard.model_validate(EXAMPLES["10"])
    e.cue_sheet = cue.from_board(p, 2)
    p.settings.write_material = "coord"
    if memo:
        e.coord = CoordMemo(summary="조율 요약", events=[f"조율 사건 {i + 1}" for i in range(len(e.plot.events))],
                            ending_hook="조율 끝", basis=coord.basis(e.plot))
    return p


def test_coord_is_fixed_points_without_cues(demo):
    p = _ready(demo)
    assert coord.on(p) and board.fixed_only(p) and not board.lean(p) and not cue.on(p)
    out = prompts.episode_prompt(p, 2)
    assert "# 이번 화 고정점" in out and "장면:\n" not in out
    assert "# 이번 화 큐 시트" not in out
    assert "자료는 두 층입니다" in prompts.writer_system(p)


def test_coord_replaces_plot_with_memo(demo):
    p = _ready(demo)
    e = p.episode(2)
    out = prompts.episode_prompt(p, 2)
    plot = out.split("# 이번 화 플롯\n", 1)[1]
    assert "조율 사건 1" in plot and "조율 요약" in plot and "조율 끝" in plot
    assert f'"{e.plot.events[0]}"' not in plot
    assert out.rstrip().endswith(coord.NOTE)
    assert "조율 사건 1" in prompts.check_material(p, 2)  # 검수도 같은 플롯을 본다 (쓰지 않은 동작을 '플롯 누락'으로 짚지 않게)


def test_coord_drops_body_and_object_handover(demo):
    p = _ready(demo)
    out = prompts.board_block(p, 2, write=True)
    assert "도윤은 왼손에 붕대를 감았다" not in out  # 몸 · 물건 줄은 뺀다
    assert "도윤은 상태창을 숨겼다" in out  # 숨긴 것 · 질문은 남긴다
    assert "끝 차림" not in out  # 끝 차림 값은 본문이 동작으로 옮기므로 넣지 않는다
    full = prompts.board_block(p, 2)  # 쓰기 밖 요청은 그대로
    assert "도윤은 왼손에 붕대를 감았다" in full and "\n끝 차림 (바뀐 인물만):" in full
    rule = prompts.attire_write_rule(p, board=True)
    assert not rule or ("끝 차림" not in rule and "attire 를 지키고" in rule)


def test_stale_memo_falls_back_to_plot(demo):
    p = _ready(demo)
    e = p.episode(2)
    e.plot.events[0] = "바뀐 사건"
    assert not coord.fresh(p, 2) and coord.remake(p, 2) and coord.memo(p, 2) is None
    out = prompts.episode_prompt(p, 2)
    assert "바뀐 사건" in out and "조율 사건 1" not in out and coord.NOTE not in out


def test_memo_only_used_in_coord_mode(demo):
    p = _ready(demo)
    p.settings.write_material = "fixed"
    assert coord.memo(p, 2) is None and not coord.remake(p, 2)
    out = prompts.episode_prompt(p, 2)
    assert "조율 사건 1" not in out and coord.NOTE not in out
    assert "도윤은 왼손에 붕대를 감았다" in out


def test_plot_rule_only_in_coord_mode(demo):
    p = _ready(demo)
    assert prompts.COORD_PLOT_RULE.strip() in prompts.plot_rules(p)
    p.settings.write_material = "fixed"
    assert prompts.COORD_PLOT_RULE.strip() not in prompts.plot_rules(p)


def test_make_coord_keeps_event_count(demo, monkeypatch):
    p = _ready(demo, memo=False)
    m = pipeline.make_coord(get_llm("board"), p, 2)
    assert len(m.events) == len(p.episode(2).plot.events) and m.basis == coord.basis(p.episode(2).plot)
    p.episode(2).coord = m
    assert coord.fresh(p, 2)
    monkeypatch.setattr(MockLLM, "json", lambda self, s, pr, schema, hint=None: CoordDraft(summary="x", events=["하나"], ending_hook="y"))
    try:
        pipeline.make_coord(get_llm("board"), p, 2)
        raise AssertionError("사건 수가 다르면 받지 않는다")
    except ValueError as e:
        assert "사건 수" in str(e)


def test_write_job_makes_memo_first(demo, monkeypatch):
    from canon import web

    store.save(demo, _ready(demo, memo=False))
    seen: list = []
    orig = MockLLM.json

    def json_(self, system, prompt, schema, hint=None):
        seen.append(schema)
        return orig(self, system, prompt, schema, hint)
    monkeypatch.setattr(MockLLM, "json", json_)
    c = TestClient(web.app)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 2})
    assert r.status_code == 200 and "조율 메모" in r.json()["label"], r.text
    assert _wait(c, r.json()["id"])["status"] == "done"
    assert CoordDraft in seen
    q = store.load(demo)
    assert coord.fresh(q, 2) and q.episode(2).text


def test_endpoint_accepts_coord(demo):
    from canon import web

    store.save(demo, _ready(demo))
    c = TestClient(web.app)
    r = c.put(f"/api/projects/{demo}/write-material", json={"mode": "coord"})
    assert r.status_code == 200 and r.json()["settings"]["write_material"] == "coord"
    assert coord.on(store.load(demo))


def test_coord_storyboard_request(demo):
    p = _ready(demo)
    out = prompts.storyboard_prompt(p, 2)
    assert prompts.COORD_BOARD_RULES in out and "attire 는 비웁니다" in out
    assert "장면 끝 상태를 적습니다" not in out and "자리, 손에 든 물건, 다친 곳" not in out
    plot = out.split("# 이번 화 플롯\n", 1)[1]
    assert "조율 사건 1" in plot  # 스토리보드도 조율 메모를 플롯으로 본다
    assert "protect 에는" in out and "time 에는" in out  # 연속성 칸은 그대로
    p.settings.write_material = "fixed"
    full = prompts.storyboard_prompt(p, 2)
    assert prompts.COORD_BOARD_RULES not in full and "장면 끝 상태를 적습니다" in full and "attire 에는 이번 화에" in full
    assert "조율 사건 1" not in full


def test_write_job_makes_memo_before_storyboard(demo, monkeypatch):
    from canon import web
    from canon.schema import StoryboardDraft

    store.save(demo, _ready(demo, memo=False))
    seen: list = []
    orig = MockLLM.json

    def json_(self, system, prompt, schema, hint=None):
        seen.append((schema, prompt))
        return orig(self, system, prompt, schema, hint)
    monkeypatch.setattr(MockLLM, "json", json_)
    c = TestClient(web.app)
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "write", "ep": 2, "board": "make"})
    assert r.status_code == 200 and r.json()["total"] == 3, r.text
    assert _wait(c, r.json()["id"])["status"] == "done"
    kinds = [k for k, _ in seen]
    assert kinds.index(CoordDraft) < kinds.index(StoryboardDraft)
    board_req = next(pr for k, pr in seen if k is StoryboardDraft)
    assert "사건 1에서 주인공의 마음이 한 칸 움직인다" in board_req  # 방금 만든 조율 메모를 플롯으로 본다
