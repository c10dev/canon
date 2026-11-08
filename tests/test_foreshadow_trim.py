"""장편 본문 쓰기의 열린 복선 한 줄 꼴 (prompts.foreshadow_line, prompts.serial_foreshadow_block).
설계: docs/context/specs/10-foreshadow-trim.md. 실행: python -m pytest tests/test_foreshadow_trim.py"""
import re

from canon import pipeline, prompts
from canon.llm import dump
from canon.schema import Foreshadow
from tests.test_cache_family import _next, _project


def _old_block(fs, fs_cut):
    """바꾸기 전 블록 (JSON 꼴)."""
    return f"""# 열린 복선{f" (이번 아크와 관련된 것만, {fs_cut}개 생략)" if fs_cut else ""}
{dump(fs) or "없음"}

"""


def _many(p, n, count):
    """n 화 직전 아크 안에 심은 열린 복선."""
    a = p.arc_for(n)
    p.foreshadows = [Foreshadow(id=f"fs-t{i:02d}", description=f"떡밥 {i}", planted_ep=a.start_ep) for i in range(count)]
    p.foreshadow_clues = []
    return p.foreshadows


def _serial_n():
    p = _project()
    return p, _next(p)


def test_short_block_unchanged():
    from tests.test_char_context import _short

    p = _short()
    p.foreshadows = [Foreshadow(id=f"fs-{i}", description=f"떡밥 {i}", planted_ep=1) for i in range(40)]
    ctx = prompts.build_episode_context(p, 4)
    assert _old_block(p.foreshadows, 0) in ctx
    assert "1화에 심음" not in ctx


def test_serial_block_is_one_line_each():
    p, n = _serial_n()
    _many(p, n, 20)
    fs, cut = prompts.relevant_foreshadows(p, n)
    ctx = prompts.build_episode_context(p, n)
    want = "# 열린 복선\n" + "\n".join(prompts.foreshadow_line(f) for f in fs) + "\n\n"
    assert cut == 0 and want in ctx
    assert dump(fs) not in ctx


def test_block_head_counts_cut():
    """고른 수 상한(FORESHADOW_CAP)을 넘으면 머리에 뺀 수를 적는다. 고른 복선은 모두 한 줄로 든다."""
    p, n = _serial_n()
    _many(p, n, 30)
    fs, cut = prompts.relevant_foreshadows(p, n)
    assert cut == 5 and len(fs) == prompts.FORESHADOW_CAP
    ctx = prompts.build_episode_context(p, n)
    assert "# 열린 복선 (이번 아크와 관련된 것만, 5개 생략)\n" in ctx
    assert all(prompts.foreshadow_line(f) in ctx for f in fs)


def test_empty_block():
    assert prompts.serial_foreshadow_block([], 0) == "# 열린 복선\n없음"
    assert prompts.serial_foreshadow_block([], 0, as_json=True) == f"# 열린 복선\n{dump([])}"  # 바꾸기 전과 같다


def test_json_switch_restores_old_block():
    """as_json 또는 FORESHADOW_JSON 을 참으로 두면 바꾸기 전과 글자까지 같다 (blocktrial 의 fs_json 조건)."""
    p, n = _serial_n()
    _many(p, n, 20)
    fs, cut = prompts.relevant_foreshadows(p, n)
    assert prompts.serial_foreshadow_block(fs, cut, as_json=True) + "\n\n" == _old_block(fs, cut)
    token = prompts.FORESHADOW_JSON.set(True)
    try:
        ctx = prompts.build_episode_context(p, n)
        assert prompts.serial_foreshadow_block(fs, cut, as_json=False) != prompts.serial_foreshadow_block(fs, cut)
    finally:
        prompts.FORESHADOW_JSON.reset(token)
    assert _old_block(fs, cut) in ctx
    assert prompts.FORESHADOW_JSON.get() is False


def test_foreshadow_line_format():
    f = Foreshadow(id="fs-a", description="가" * 300, planted_ep=3, due_ep=12, scope="part")
    assert prompts.foreshadow_line(f) == f"- fs-a (3화에 심음, 회수 예정 12화, 회수 범위 이번 부, 단서): {'가' * 300}"
    g = Foreshadow(id="fs-b", description="짧은\n설명", planted_ep=5, kind="stake", public=True, scope="series")
    assert prompts.foreshadow_line(g) == "- fs-b (5화에 심음, 회수 범위 작품 전체, 판돈 · 드러남): 짧은 설명"
    h = Foreshadow(id="fs-c", description="문", planted_ep=1, kind="constraint")
    assert prompts.foreshadow_line(h) == "- fs-c (1화에 심음, 회수 범위 이번 아크, 제약): 문"


def test_line_block_is_shorter():
    """같은 복선에서 한 줄 꼴이 JSON 꼴보다 짧다 (JSON 의 키 · 따옴표 · 늘 같은 칸이 빠진다)."""
    p, n = _serial_n()
    fs = _many(p, n, 20)
    assert len(prompts.serial_foreshadow_block(fs, 0)) < 0.6 * len(prompts.serial_foreshadow_block(fs, 0, as_json=True))


def test_same_input_same_block():
    p, n = _serial_n()
    _many(p, n, 20)
    assert prompts.build_episode_context(p, n) == prompts.build_episode_context(p, n)


def test_write_family_starts_with_head_after_storyboard():
    from canon.mock import MockLLM

    p, n = _serial_n()
    _many(p, n, 20)
    head = prompts.write_head(p, n)
    assert prompts.foreshadow_line(p.foreshadows[0]) in head
    assert prompts.storyboard_prompt(p, n).startswith(head)
    pipeline.set_storyboard(p, n, pipeline.make_storyboard(MockLLM(), p, n), by="ai")
    assert prompts.write_head(p, n) == head
    assert prompts.cue_sheet_prompt(p, n).startswith(head)
    assert prompts.episode_prompt(p, n).startswith(head)
    block = head[head.index("# 열린 복선"):head.index("# 지금까지의 줄거리 (이번 아크)")]
    assert block in prompts.rework_prompt(p, n)  # 다시 쓰기도 같은 블록


def _fs_part(text):
    """'[열린 복선]' 블록부터 다음 '[' 머리 전까지 (이름 후보처럼 무작위인 줄은 견주지 않는다)."""
    i = text.index("[열린 복선]")
    m = re.compile(r"\n\[[^\]\n]+\]").search(text, i + 1)
    return text[i:m.start() if m else None]


def test_other_requests_unchanged():
    """상태 변경안 · 플롯 요청의 복선과 relevant_foreshadows 는 꼴 스위치와 상관없다."""
    p, n = _serial_n()
    _many(p, n, 20)
    a = p.arc_for(n)

    def take():
        return (prompts.relevant_foreshadows(p, n), prompts.state_prompt(p, n),
                _fs_part(prompts.serial_plot_prompt(p, a.start_ep, a.end_ep)))

    line = take()
    token = prompts.FORESHADOW_JSON.set(True)
    try:
        old = take()
    finally:
        prompts.FORESHADOW_JSON.reset(token)
    assert line == old
    assert "회수 범위 이번 아크" not in line[1] and "fs-t00" in line[2]
