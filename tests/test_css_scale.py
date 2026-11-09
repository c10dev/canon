"""app.css 의 둥글기(border-radius)와 글자 크기(font-size)가 디자인 시스템 단계 안의 값만 쓰는지 본다 (docs/ux/specs/11-hierarchy.md).

- 둥글기: `var(--radius-*)` 토큰(docs/design/tokens.json radius)과 0, 원을 그리는 50%.
- 글자 크기: tokens.json type 의 fontSize(px)를 rem(16px = 1rem)으로 옮긴 값과 inherit.
- 단계 밖이지만 정한 값은 EXCEPTIONS 에 선택자 · 까닭과 함께 둔다. tokens.json 에 글자 단계를 더하면 이 시험도 그 값을 받는다.
"""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = json.loads((ROOT / "docs" / "design" / "tokens.json").read_text(encoding="utf-8"))
CSS = (ROOT / "canon" / "static" / "app.css").read_text(encoding="utf-8")

RADIUS_VARS = {t["name"] for t in TOKENS["radius"]["tokens"]}
FONT_PX = {float(s["fontSize"].removesuffix("px")) for g in TOKENS["type"]["groups"] for s in g["styles"]}

# 단계 밖이지만 정한 값: (속성, 선택자, 값) → 까닭. 선택자는 app.css 규칙의 선택자 글 그대로다
EXCEPTIONS = {
    ("font-size", ".usage-tile.hero .usage-num", "3rem"): "사용량 첫 수 타일의 큰 수 48px. Card 문서 '수 타일'에 적었다",
    ("font-size", ".nav a .num.tf, .nav-off .num.tf", "1.125rem"): "사이드바 이모지 칸 18px(README '표시와 그림'). 사이드바 표시는 일감 14 가 다룬다",
}
# 꾸밈 변수: 작가가 고른 상태창 꾸밈(.sw-box)이 값을 준다
SKIN_VARS = {"var(--sw-radius)"}


def _rules() -> list[tuple[str, str]]:
    """(선택자, 선언 글). @media 안 규칙도 가장 안쪽 괄호로 잡는다."""
    body = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    return [(sel.strip().split("{")[-1].strip(), decl) for sel, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", body)]


def _decls(prop: str) -> list[tuple[str, str]]:
    return [(sel, v.strip()) for sel, decl in _rules() for v in re.findall(rf"(?<![\w-]){prop}\s*:\s*([^;]+)", decl)]


def _radius_ok(sel: str, value: str) -> bool:
    if ("border-radius", sel, value) in EXCEPTIONS or value in SKIN_VARS:
        return True
    parts = value.split()
    return all(p in ("0", "50%") or (m := re.fullmatch(r"var\(--([\w-]+)\)", p)) and m.group(1) in RADIUS_VARS for p in parts)


def _font_ok(sel: str, value: str) -> bool:
    if ("font-size", sel, value) in EXCEPTIONS or value == "inherit":
        return True
    m = re.fullmatch(r"([\d.]+)(rem|px)", value)
    return bool(m) and float(m.group(1)) * (16 if m.group(2) == "rem" else 1) in FONT_PX


def off_scale() -> Counter:
    """단계 밖 값과 그 개수. 보고에 쓰는 셈이기도 하다."""
    bad = Counter()
    bad.update(("border-radius", v) for sel, v in _decls("border-radius") if not _radius_ok(sel, v))
    bad.update(("font-size", v) for sel, v in _decls("font-size") if not _font_ok(sel, v))
    return bad


def test_radius_and_font_size_on_scale():
    assert not off_scale(), dict(off_scale())


def test_font_sizes_use_rem():
    """글자 크기는 rem 으로 쓴다. 브라우저 글자 크기 설정을 따르게 하려는 것이다."""
    px = [v for _, v in _decls("font-size") if v.endswith("px")]
    assert not px, px


def test_exceptions_still_used():
    """쓰지 않게 된 예외는 지운다."""
    used = {("font-size", sel, v) for sel, v in _decls("font-size")} | {("border-radius", sel, v) for sel, v in _decls("border-radius")}
    assert set(EXCEPTIONS) <= used, set(EXCEPTIONS) - used
