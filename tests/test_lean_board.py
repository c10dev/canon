"""쓰기 재료 '꼭 쓸 것만' (Settings.write_material = lean, board.lean): 집필에는 이번 화 목표와 꼭 써야 하는 것만 넣는다.
스토리보드를 '어기면 안 되는 것'과 '이번 화에 쓸 것'으로 나누고 설계 메모(장면 끝 상태 · 깨지 않을 것 · 큐 끝 상태 등)를 뺀다.
스토리보드 데이터, 큐 시트 만들기, 검수는 전체를 그대로 본다. 중심 장면(Storyboard.focus)은 이 재료에서만 쓰기 · 큐 시트 지시가 된다.

    CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_lean_board.py
"""
from fastapi.testclient import TestClient

from canon import board, cue, pipeline, prompts, store
from canon.schema import BoardAttire, Storyboard, StoryboardDraft

from .test_storyboard import EXAMPLES, _written, demo  # noqa: F401  (pytest fixture)


def _ready(name: str, focus: int = 3):
    """2화에 스토리보드(중심 장면 focus)와 뼈대 큐 시트를 두고 쓰기 재료를 꼭 쓸 것만으로 둔다."""
    p = store.load(name)
    _written(p, 1)
    e = p.episode(2)
    e.storyboard = Storyboard.model_validate({**EXAMPLES["10"], "focus": focus})
    e.cue_sheet = cue.from_board(p, 2)
    for c in e.cue_sheet.cues:
        c.exit = "큐 끝 메모"
    p.settings.write_material = "lean"
    return p


def test_lean_splits_board_and_drops_design_notes(demo):
    p = _ready(demo)
    assert board.lean(p) and not board.fixed_only(p)
    out = prompts.episode_prompt(p, 2)
    keep, use = out.index("# 이번 화에서 어기면 안 되는 것"), out.index("# 이번 화에 쓸 것")
    assert keep < use < out.index("# 이번 화 플롯")  # 지킬 것이 앞, 쓸 것이 뒤
    assert "# 이번 화 스토리보드" not in out
    assert "시간: " in out[keep:use] and "도윤은 왼손에 붕대를 감았다" in out[keep:use]  # 몸 · 물건 · 장면 · 시간은 남는다
    assert "도윤은 상태창을 숨겼다" not in out and "배에 함께 타지 않는 이유" not in out  # 숨긴 것 · 질문은 뺀다
    assert "목표: " in out and "전환: " in out and "끝: 조건 합의" not in out  # 장면 끝 상태는 뺀다
    assert "은결의 배에서 등유를 옮겨 담지 않는다" not in out  # 깨지 않을 것은 뺀다
    assert "젖은 방수 외투" not in out and "장면 5에서 목록을 접어 넣음" in out  # 끝 차림 목록 대신 바뀌는 순간만
    assert "3. 물푸레 등대섬" in out and "(중심 장면)" in out
    assert "중심 장면(3장면)을 가장 길게" in out and prompts.FOCUS_LINE not in out
    assert "큐 끝 메모" not in out and "일 칸은 설계 메모라" in out  # 큐 끝 상태는 뺀다


def test_lean_drops_stat_change_without_window(demo):
    p = _ready(demo)
    b = p.episode(2).storyboard
    b.stats[0].window = False
    text = prompts.lean_board_block(p, 2)
    assert "상태창 2 (5장면" in text or "상태창 1 (5장면" in text
    assert "3장면에 바뀜" not in text and "창은 뜨지 않음" not in text


def test_lean_keeps_full_board_for_design_and_check(demo):
    p = _ready(demo)
    full = prompts.board_block(p, 2)  # 큐 시트 만들기가 쓰는 글 (write 꺼짐)
    assert "# 이번 화 스토리보드" in full and "끝: 조건 합의" in full and "은결의 배에서 등유를" in full
    assert "도윤은 상태창을 숨겼다" in full
    assert "은결의 배에서 등유를 옮겨 담지 않는다" in prompts.protect_block(p.episode(2))  # 검수는 계속 대조한다
    lead = prompts.storyboard_prompt(p, 2)
    assert "끝: 조건 합의" in prompts.cue_sheet_prompt(p, 2, lead=lead)
    assert "중심 장면(3장면) 큐들의 length 합이" in prompts.cue_sheet_prompt(p, 2)


def test_focus_only_counts_in_lean(demo):
    p = _ready(demo)
    p.settings.write_material = ""
    out = prompts.episode_prompt(p, 2)
    assert prompts.FOCUS_LINE in out and "중심 장면(" not in out and "큐 끝 메모" in out
    assert "중심 장면(" not in prompts.cue_sheet_prompt(p, 2)
    p.settings.write_material = "lean"
    p.episode(2).storyboard.focus = 0  # 고르지 않았으면 지금 문장 그대로
    assert prompts.FOCUS_LINE in prompts.episode_prompt(p, 2)


def test_lean_attire_rule_points_to_change_moments(demo):
    p = _ready(demo)
    p.states[0].attire = "회색 코트"
    out = prompts.episode_prompt(p, 2)
    assert "'차림이 바뀌는 순간'에만 바꿉니다" in out and "스토리보드의 끝 차림" not in out


def test_storyboard_prompt_asks_focus_and_shows_direction(demo):
    p = _ready(demo)
    assert "- focus: 이 화의 중심 장면 번호" in prompts.storyboard_prompt(p, 2)
    p.episode(2).direction = "몸의 반응에 분량을 씁니다"
    assert "(화 연출 지시: 몸의 반응에 분량을 씁니다)" in prompts.storyboard_prompt(p, 2)


def test_clean_storyboard_clamps_focus():
    d = StoryboardDraft.model_validate({**EXAMPLES["10"], "focus": 9})
    assert pipeline.clean_storyboard(d).focus == 0
    d = StoryboardDraft.model_validate({**EXAMPLES["10"], "focus": 2})
    assert pipeline.clean_storyboard(d).focus == 2
    assert board.focus(None) == 0


def test_old_storyboard_reads_without_focus():
    raw = {k: v for k, v in EXAMPLES["10"].items() if k != "focus"}
    assert Storyboard.model_validate(raw).focus == 0


def test_endpoint_accepts_lean(demo):
    from canon import web

    store.save(demo, _ready(demo))
    c = TestClient(web.app)
    r = c.put(f"/api/projects/{demo}/write-material", json={"mode": "lean"})
    assert r.status_code == 200 and r.json()["settings"]["write_material"] == "lean"
    assert board.lean(store.load(demo))


def test_attire_without_why_is_left_out(demo):
    p = _ready(demo)
    p.episode(2).storyboard.attire = [BoardAttire(character_id=p.characters[0].id, end="붕대", why="")]
    assert "차림이 바뀌는 순간" not in prompts.lean_board_block(p, 2)
