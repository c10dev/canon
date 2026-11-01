"""가려 읽기(static/research.js blindDeck)를 node 로 맞춰 본다: 한 번에 한 안만, 읽지 않은 안 세기, 고른 뒤 공개.
블라인드 비교(연구 화면)와 여는 방식 비교(opening.js)가 함께 쓴다."""
import re

from .jsvm import STATIC, needs_node, run_js

FILES = re.findall(r'src="/static/([a-z-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))

C = {"episode": 3, "created": "2026-11-01T10:00:00", "picked": None,
     "drafts": [{"n": 1, "text": "첫째 안 본문"}, {"n": 2, "text": "둘째 안 본문"}]}


@needs_node
def test_blind_deck_shows_one_draft_at_a_time():
    out = run_js(FILES, """(() => {
      const c = data.c;
      const card = (d, open) => '<card n=' + d.n + ' open=' + open + '>' + blindProse(c, d) + '</card>';
      const out = { unread: data.unread.map(([n, seen, k]) => blindUnread(n, seen, k)), first: blindDeck(c, card) };
      const st = blindState(c);
      st.show = 2; st.seen.push(1);
      out.second = blindDeck(c, card);
      c.picked = 2; c.order = ['gemini', 'local'];
      out.picked = blindDeck(c, card);
      return out;
    })()""", {"c": C, "unread": [[2, [], 0], [2, [], 1], [3, [2], 1], [3, [1, 2, 3], 0]]})
    assert out["unread"] == [[1, 2], [2], [3], []]
    first = out["first"]
    # 탭은 안 수만큼, 본문은 1번 하나만. 읽기 전에는 지표를 접는다
    assert first.count('role="tab"') == 2
    assert "첫째 안 본문" in first and "둘째 안 본문" not in first
    assert "open=false" in first and 'aria-selected="true"' in first and 'data-arg="3:2026-11-01T10:00:00|1"' in first
    assert "2개 안을 아직 끝까지 읽지 않았어요" in first
    second = out["second"]
    assert "둘째 안 본문" in second and "첫째 안 본문" not in second
    assert "1번 · 읽음" in second and "1개 안을 아직" in second
    # 고른 뒤에는 탭에 정체가 붙고 지표를 펼친다
    picked = out["picked"]
    assert "1번 · gemini · 읽음" in picked and "2번 · local · 고름" in picked
    assert "open=true" in picked and "아직 끝까지" not in picked
