"""두 사람 사이 이력 블록 (canon/pairlog.py). 실행: python -m pytest tests/test_pairlog.py"""
from canon import context, pairlog, prompts
from canon.schema import StoryEvent
from tests.test_char_context import _long


def _ids(p, k=2):
    return [c.id for c in p.characters][:k]


def test_history_pairs_before_episode_and_skips_manual():
    p = _long()
    a, b = _ids(p)
    p.events = [StoryEvent(episode=2, actor=a, target=b, kind="도움", quote="문을 열어 주었다."),
                StoryEvent(episode=4, actor=b, target=a, kind="진심고백", intensity=3, quote="좋아해."),
                StoryEvent(episode=5, actor=a, target=b, kind="수동보정"),
                StoryEvent(episode=9, actor=a, target=b, kind="배신")]
    h = pairlog.history(p, 6)
    assert list(h) == [tuple(sorted((a, b)))]
    assert [e.kind for e in h[tuple(sorted((a, b)))]] == ["도움", "진심고백"]  # 수동보정 · 뒤 화는 뺀다


def test_write_block_is_one_label_line_per_plot_pair():
    p = _long()
    a, b = _ids(p)
    p.events = [StoryEvent(episode=2, actor=a, target=b, kind="도움", quote="문을 열어 주었다."),
                StoryEvent(episode=4, actor=b, target=a, kind="진심고백", intensity=3, quote="좋아해.")]
    block = pairlog.write_block(p, 6, {a, b}, 600)
    assert "사건 2번" in block and "처음 2화 도움" in block and "결정적 4화 진심고백" in block
    assert "좋아해" not in block  # 쓰기에는 근거 문장을 넣지 않는다 (본문으로 옮겨지지 않게)
    assert pairlog.write_block(p, 6, {a}, 600) == ""  # 한 사람만 나오면 없음
    lines, cut = pairlog.write_lines(p, 6, {a, b}, 10)
    assert lines == [] and cut == 1


def test_check_block_has_first_of_each_kind_with_quote_and_rule():
    p = _long()
    a, b = _ids(p)
    p.events = [StoryEvent(episode=2, actor=a, target=b, kind="진심고백", quote="좋아해."),
                StoryEvent(episode=5, actor=b, target=a, kind="진심고백", quote="나도."),
                StoryEvent(episode=6, actor=b, target=a, kind="사과", quote="미안해.")]
    block = pairlog.check_block(p, 8, {a, b}, 3_000)
    assert "진심고백: 처음 2화 «좋아해.»" in block and "나도." not in block and "사과: 처음 6화" in block
    assert "처음 · 다시" in pairlog.check_rule(block) and pairlog.check_rule("") == ""


def test_serial_write_and_check_prompts_carry_pair_blocks():
    p = _long()
    n = next(e.plot.number for e in p.episodes if not e.text)
    a, b = p.episode(n).plot.characters[:2]
    p.events.append(StoryEvent(episode=n - 1, actor=a, target=b, kind="진심고백", intensity=3, quote="좋아해."))
    write = prompts.episode_prompt(p, n)
    assert "# 두 사람 사이에 있었던 일" in write and "좋아해." not in write.split("# 두 사람 사이에 있었던 일")[1].split("\n#")[0]
    p.episode(n).text = "처음으로 고백했다."
    check = prompts.check_prompt(p, n)
    assert "# 두 사람 사이에 이미 있었던 일" in check and "- 처음 · 다시:" in check
    assert len(pairlog.write_block(p, n, set(p.episode(n).plot.characters), context.BUDGET["pairs"])) <= context.BUDGET["pairs"] + 80
