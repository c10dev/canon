"""안내 문장 셈 (docs/ux/specs/13-subtract-rule.md, docs/design/README.md '덜기'): 작품 화면의 <main> 안 늘 보이는 안내 문장이 상한을 넘지 않는지 본다.
test_primary_count_js 처럼 app.js mainHtml 로 main 을 그리고, scripts/count_copy.py 와 같은 규칙(SKIP · sentences)으로 센다.
브라우저 없이 HTML 만 읽으므로 CSS 로 숨긴 글도 센다. 그래서 수는 count_copy.py 의 Playwright 셈보다 크다. 화면의 실제 수는 count_copy.py 로 잰다.
시험 환경에는 API 키가 없어 작품 홈 · 설정 도우미에 키 안내 두 문장이 늘 들어간다.
상한은 LIMIT 이다. 규칙이 들어온 날 이미 넘은 화면은 BASELINE 에 그날 수를 두고, 그 수보다 늘 때만 실패한다.
화면을 더하려면 test_primary_count_js 의 SCREENS 에 줄을 더한다. 이 시험도 그 줄을 센다. node 가 있을 때만 돈다."""
import importlib.util
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from .jsvm import needs_node
from .test_primary_count_js import SCREENS, main_html

_spec = importlib.util.spec_from_file_location("count_copy", Path(__file__).resolve().parent.parent / "scripts" / "count_copy.py")
count_copy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(count_copy)

# 한 화면의 늘 보이는 안내 문장 상한 (docs/design/README.md '덜기')
LIMIT = 5

# 2026-11-09 에 이미 상한을 넘은 화면의 그날 수: (화면, 주소 뒤쪽, 작품 상태, S 에 넣을 값의 키) → 문장 수.
# 줄이면 이 수도 낮춘다. 상한 아래로 내려가면 줄을 지운다.
BASELINE: dict[tuple[str, str, str, str], int] = {
    ("home", "", "empty", ""): 7,
    ("home", "", "draft", ""): 6,
    ("setup", "setup", "empty", ""): 8,
    ("setup", "setup", "written", ""): 8,
    ("style", "style", "empty", ""): 9,
    ("style", "style", "written", ""): 8,
    ("style", "style", "finished", "anchorView"): 9,
    ("style", "style", "finished", "anchorView-anchorPick"): 12,
    ("arc", "arc-2", "draft", ""): 6,
    ("arc", "arc-2", "confirmed", ""): 6,
    ("arc", "arc-2", "cast", ""): 8,
    ("write", "write-2", "draft", ""): 6,
    ("write", "write-2", "confirmed", ""): 11,
    ("write", "write-2", "confirmed", "dirEdit"): 12,
    ("write", "write-2", "written", ""): 9,
}

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
BLOCK = {"p", "li", "div", "dd", "dt", "blockquote", "figcaption", "section"}


def _selectors(css: str) -> list[tuple[str, str, str, str]]:
    """'a.btn, #toasts, [contenteditable]' 같은 단순 선택자 목록을 (태그, 클래스, id, 속성) 으로 푼다."""
    out = []
    for s in (x.strip() for x in css.split(",")):
        m = re.fullmatch(r"([a-z0-9]*)(?:\.([\w-]+))?(?:#([\w-]+))?(?:\[([\w-]+)\])?", s)
        assert m, f"count_copy.SKIP 의 '{s}' 를 이 시험이 읽지 못해요"
        out.append(m.groups(""))
    return out


SKIP = _selectors(count_copy.SKIP)


def _match(tag: str, attrs: dict, sel: tuple[str, str, str, str]) -> bool:
    t, cls, id_, attr = sel
    return ((not t or t == tag) and (not cls or cls in attrs.get("class", "").split())
            and (not id_ or attrs.get("id") == id_) and (not attr or attr in attrs))


class _Copy(HTMLParser):
    """count_copy.COLLECT 를 HTML 글로 옮긴 것: 세는 자리의 글을 블록마다 모은다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = []  # {tag, skip, block}
        self.blocks: dict[int, str] = {}
        self.seq = 0  # 블록 번호. id() 는 닫힌 요소의 번호를 다시 쓰므로 쓰지 않는다

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        parent = self.stack[-1] if self.stack else {"skip": False, "block": None, "closed": False}
        hidden = ("hidden" in a or re.search(r"display\s*:\s*none", a.get("style", ""))
                  or (tag in ("dialog", "template") and "open" not in a)
                  or (parent["closed"] and tag != "summary"))
        node = {"tag": tag, "skip": parent["skip"] or bool(hidden) or any(_match(tag, a, s) for s in SKIP),
                "closed": tag == "details" and "open" not in a}
        self.seq += 1
        node["id"] = self.seq
        node["block"] = self.seq if tag in BLOCK or (tag == "span" and "hint" in a.get("class", "").split()) else parent["block"]
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        s = data.strip()
        if not s or not self.stack or self.stack[-1]["skip"]:
            return
        key = self.stack[-1]["block"] or self.stack[-1]["id"]
        self.blocks[key] = self.blocks.get(key, "") + " " + s


def guide_sentences(html: str) -> list[str]:
    p = _Copy()
    p.feed(html)
    return [s for block in p.blocks.values() for s in count_copy.sentences(re.sub(r"\s+", " ", block).strip())]


def _key(screen, route, state, extra) -> tuple[str, str, str, str]:
    return (screen, "-".join(route), state, "-".join(extra))


def test_parser_follows_count_copy_rules():
    html = ('<main class="main"><h1>제목이에요</h1><p class="small">늘 보이는 안내예요. 둘째 문장이에요.</p>'
            '<div class="empty">빈 상태 글이에요.</div><button>누르면 돼요</button>'
            '<details><summary>펼쳐 봐요</summary><p>닫힌 글이에요.</p></details>'
            '<p hidden>숨긴 글이에요.</p><div>값<span class="hint">힌트예요.</span></div></main>')
    assert guide_sentences(html) == ["늘 보이는 안내예요.", "둘째 문장이에요.", "펼쳐 봐요", "힌트예요."]


@needs_node
@pytest.mark.parametrize("screen,route,state,_limit,extra", SCREENS,
                         ids=[f"{s}-{'-'.join(r) or 'home'}-{st}{'-' + '-'.join(x) if x else ''}" for s, r, st, _, x in SCREENS])
def test_guide_sentences_within_limit(screen, route, state, _limit, extra):
    html = main_html(route, state, extra)
    assert "<h1" in html or "page-head" in html, html[:300]  # 화면을 실제로 그렸다
    got = guide_sentences(html)
    limit = max(LIMIT, BASELINE.get(_key(screen, route, state, extra), 0))
    assert len(got) <= limit, f"{screen} ({state}) 늘 보이는 안내 문장 {len(got)}개 (기준 {limit}): {got}"


def test_baseline_rows_are_over_limit():
    """기준 표에는 상한을 넘은 화면만 둔다. 상한 아래로 줄었으면 줄을 지운다."""
    assert all(n > LIMIT for n in BASELINE.values()), {k: n for k, n in BASELINE.items() if n <= LIMIT}
