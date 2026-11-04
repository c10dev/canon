"""쓰기 재료 '고정점만' (Settings.write_material = fixed, board.fixed_only): 스토리보드 장면 · 큐 시트를 빼고 고정점만 넣는다.

    CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_fixed_points.py
"""
from fastapi.testclient import TestClient

from canon import board, cue, prompts, store
from canon.schema import BoardMove, Storyboard

from .test_storyboard import EXAMPLES, _written, demo  # noqa: F401  (pytest fixture)


def _ready(name: str):
    """2화에 스토리보드와 뼈대 큐 시트를 둔다 (1화는 반영이 끝남)."""
    p = store.load(name)
    _written(p, 1)
    e = p.episode(2)
    e.storyboard = Storyboard.model_validate(EXAMPLES["10"])
    e.cue_sheet = cue.from_board(p, 2)
    return p


def test_default_keeps_scenes_and_cue_sheet(demo):
    p = _ready(demo)
    assert p.settings.write_material == "" and not board.fixed_only(p)
    out = prompts.episode_prompt(p, 2)
    assert "# 이번 화 스토리보드" in out and "\n장면:\n" in out and "맡은 사건:" in out
    assert "위 장면 순서와 값을 따릅니다" in out
    assert prompts.cue_write_block(p, p.episode(2).cue_sheet) in out
    assert "플롯의 사건은 모두 다루되" in prompts.writer_system(p)


def test_fixed_drops_scenes_and_cue_sheet_but_keeps_fixed_points(demo):
    p = _ready(demo)
    b = p.episode(2).storyboard
    b.moves = [BoardMove(character_id=p.characters[0].id, scene=2, to="등대")]
    p.settings.write_material = "fixed"
    assert board.fixed_only(p) and not cue.on(p)
    out = prompts.episode_prompt(p, 2)
    assert "# 이번 화 고정점 (반드시 지킬 것" in out and "# 이번 화 스토리보드" not in out
    assert "\n장면:\n" not in out and "맡은 사건:" not in out and "2장면" not in out
    assert "시간: " in out and "은결의 배에서 등유를 옮겨 담지 않는다" in out  # 시간 줄과 깨지 않을 것은 남는다
    assert "등대(으)로" in out
    assert "장면을 어떻게 나누고 무엇에 오래 머물지는 직접 정합니다" in out
    assert "자료가 서로 부딪히면 고정점, 이번 화 플롯" in out
    assert "# 큐 시트" not in out and "큐 시트의 순서와 진행" not in out  # 시트가 있어도 넣지 않는다
    sys = prompts.writer_system(p)
    assert "플롯의 사건은 모두 다루되" not in sys and "자료는 두 층입니다" in sys


def test_fixed_rewrite_leaves_cue_sheet_out(demo):
    from canon.schema import RewriteRequest

    p = _ready(demo)
    p.settings.write_material = "fixed"
    p.episode(2).text = "본문. " * 100
    out = prompts.rewrite_prompt(p, 2, RewriteRequest(feedback="더 길게"), {})
    assert "큐 시트의 순서와 진행" not in out and "맡은 사건:" not in out


def test_old_project_reads_without_field():
    from canon.schema import Settings

    assert Settings.model_validate({"storyboard": True}).write_material == ""


def test_endpoint_sets_and_checks_mode(demo):
    from canon import web

    store.save(demo, _ready(demo))
    c = TestClient(web.app)
    r = c.put(f"/api/projects/{demo}/write-material", json={"mode": "fixed"})
    assert r.status_code == 200 and r.json()["settings"]["write_material"] == "fixed"
    assert store.load(demo).settings.write_material == "fixed"
    assert c.put(f"/api/projects/{demo}/write-material", json={"mode": "scenes-only"}).status_code == 422
    c.put(f"/api/projects/{demo}/write-material", json={"mode": ""})
    assert not board.fixed_only(store.load(demo))
