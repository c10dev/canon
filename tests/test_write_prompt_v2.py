"""쓰기 프롬프트 v2 (Settings.write_prompt = v2, prompts.context_parts): 직전 화는 끝 1,500자, 대표 문단은 직전 화 블록 뒤에 한 번 더.

    CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_write_prompt_v2.py
"""
from fastapi.testclient import TestClient

from canon import prompts, store

from .test_char_context import _long
from .test_fixed_points import _ready
from .test_storyboard import demo  # noqa: F401  (pytest fixture)

PASSAGE = "대표 문단이다. 바다가 보였다."


def _v2(p, on=True):
    p.settings.write_prompt = "v2" if on else ""
    return p


def _fresh(p) -> int:
    return min(e.plot.number for e in p.episodes if not e.text)


def test_default_has_no_again_block(demo):
    p = _ready(demo)
    p.style.sample_passages = [PASSAGE]
    out = prompts.episode_prompt(p, 2)
    assert p.settings.write_prompt == "" and prompts.STYLE_HEAD_AGAIN not in out
    assert "# 직전 화 본문 (전체" in out


def test_v2_with_board_uses_tail_only(demo):
    p = _ready(demo)
    p.style.sample_passages = [PASSAGE]
    out = prompts.episode_prompt(_v2(p), 2)
    assert "# 직전 화 본문 (전체" not in out and "# 직전 화 마지막 부분" in out
    assert "# 이번 화 스토리보드" in out


def test_v2_again_block_follows_prev_block_once(demo):
    p = _v2(_ready(demo))
    p.style.sample_passages = [PASSAGE]
    out = prompts.episode_prompt(p, 2)
    assert out.count(prompts.STYLE_HEAD_AGAIN) == 1
    assert out.index("# 직전 화 마지막 부분") < out.index(prompts.STYLE_HEAD_AGAIN) < out.index("# 이번 화 스토리보드")
    assert out.split(prompts.STYLE_HEAD_AGAIN + "\n", 1)[1].startswith(PASSAGE)
    p.style.sample_passages = []
    assert prompts.STYLE_HEAD_AGAIN not in prompts.episode_prompt(p, 2)


def test_v2_serial_late_branch():
    p = _long()
    n = _fresh(p)
    p.style.sample_passages = [PASSAGE]
    base = prompts.episode_prompt(p, n)
    out = prompts.episode_prompt(_v2(p), n)
    assert prompts.STYLE_HEAD_AGAIN not in base
    assert out.count(prompts.STYLE_HEAD_AGAIN) == 1
    assert out.index("# 직전 화 마지막 부분") < out.index(prompts.STYLE_HEAD_AGAIN)
    head = prompts.write_head(p, n)
    assert head == prompts.write_head(_v2(p, False), n)


def test_v2_leaves_check_and_state_prompts(demo):
    p = _ready(demo)
    p.style.sample_passages = [PASSAGE]
    base = (prompts.check_prompt(p, 1, "full"), prompts.state_prompt(p, 1))
    _v2(p)
    assert (prompts.check_prompt(p, 1, "full"), prompts.state_prompt(p, 1)) == base


def test_endpoint_saves_mode(demo):
    from canon import web

    store.save(demo, _ready(demo))
    c = TestClient(web.app)
    r = c.put(f"/api/projects/{demo}/write-prompt", json={"mode": "v2"})
    assert r.status_code == 200 and r.json()["settings"]["write_prompt"] == "v2"
    assert store.load(demo).settings.write_prompt == "v2"
    assert c.put(f"/api/projects/{demo}/write-prompt", json={"mode": "v3"}).status_code == 422
    c.put(f"/api/projects/{demo}/write-prompt", json={"mode": ""})
    assert store.load(demo).settings.write_prompt == ""
