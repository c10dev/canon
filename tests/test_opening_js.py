"""여는 방식 비교 카드(static/opening.js openingPanel)의 '여러 안으로 쓰기' 버튼이 켜지는 조건.
본문이 없는 화는 집필 화면처럼 채팅 앱 작업지시서 방식에서도 AI로 쓴다 (write.js isApi). node 가 있을 때만 돈다."""
import pytest

from canon.schema import Project

from .jsvm import dump, episode, needs_node, run_js

FILES = ["app.js", "research.js", "opening.js"]

EXPR = """(() => {
  S.project = data.p; S.name = 'x'; S.mode = data.mode;
  if (data.draft !== null) S.textDraft[1] = data.draft;
  S.approaches = [{id: 'a', label: 'A', how: '', default: true}, {id: 'b', label: 'B', how: '', default: true}];
  S.openingWays = ['a', 'b'];
  const h = openingPanel(1);
  const btn = (h.match(/data-action="openingDrafts"[^>]*>/) || [''])[0];
  return { shown: h.includes('여는 방식 비교'), on: btn.includes('data-opening-go="1"') && !btn.includes('disabled'),
           brief: h.includes('AI로 쓰기 방식에서 쓸 수 있어요') };
})()"""


def _panel(status: str, text: str, mode: str, draft: str | None = None) -> dict:
    p = Project(episodes=[episode(1, status=status, text=text), episode(2, status="draft")])
    return run_js(FILES, EXPR, {"p": dump(p), "mode": mode, "draft": draft})


@needs_node
@pytest.mark.parametrize("mode", ["api", "brief"])
def test_no_text_episode_can_write_in_both_modes(mode):
    got = _panel("confirmed", "", mode)
    assert got == {"shown": True, "on": True, "brief": False}


@needs_node
def test_brief_mode_blocks_once_text_exists():
    assert _panel("written", "본문", "brief") == {"shown": True, "on": False, "brief": True}
    assert _panel("written", "본문", "api")["on"] is True


@needs_node
def test_brief_mode_blocks_unsaved_draft():
    """저장하지 않은 본문 초안이 있으면 본문이 있는 화로 본다 (write.js starting 과 같은 기준)."""
    assert _panel("confirmed", "", "brief", draft="쓰던 글")["on"] is False


@needs_node
def test_plot_draft_and_finalized():
    got = _panel("draft", "", "api")
    assert got["shown"] is True and got["on"] is False
    assert _panel("finalized", "본문", "api")["shown"] is False
