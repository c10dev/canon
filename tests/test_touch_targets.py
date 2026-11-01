"""손가락 기기 · 휴대폰 폭의 누름 크기(docs/design README '테마와 접근성').

누름 크기는 `--touch-min`(44px) 변수로 쓴다. JS 가 넣는 CSS 도 같다.
작게 그린 공용 부품은 app.css 의 `@media (pointer: coarse), (max-width: 640px)` 블록이 키운다.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "canon" / "static"
CSS = STATIC / "app.css"
COARSE = "@media (pointer: coarse), (max-width: 640px) {"


def _coarse_block():
    text = CSS.read_text(encoding="utf-8")
    i = text.index(COARSE)
    depth = 0
    for j in range(i + len(COARSE) - 1, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j]
    raise AssertionError("손가락 기기 블록의 괄호 짝이 맞지 않아요")


def test_js_css_uses_touch_min():
    bad = []
    for path in sorted(STATIC.glob("*.js")):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"(?<![\w-])(min-)?(height|width)\s*:\s*44px", line):
                bad.append(f"{path.name}:{no}")
    assert not bad, "누름 크기 44px 는 var(--touch-min) 으로 써 주세요: " + ", ".join(bad)


def test_shared_parts_grow_on_touch():
    block = _coarse_block()
    for sel in (".btn.small", ".seg button", ".outline-item", ".pop-radio", ".pop-check", ".cmd", "#toast .t .t-act",
                ".plot-wrap .outline-item.act", ".plot-wrap .outline-item.ep-row"):
        assert sel in block, f"{sel} 가 손가락 기기 블록에 없어요"


def test_undo_toast_buttons_are_touch_size():
    text = (STATIC / "review.js").read_text(encoding="utf-8")
    assert "#toast .rv-undo .btn { min-height: var(--touch-min);" in text
    assert re.search(r"#toast \.rv-undo \.x \{[^}]*min-width: var\(--touch-min\); min-height: var\(--touch-min\)", text)
