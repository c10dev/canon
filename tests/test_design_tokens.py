"""디자인 시스템 색 토큰(docs/design/tokens.json)과 화면 CSS(canon/static/app.css)가 같은지 본다.

app.css 의 밝은 테마는 맨 위 `:root`, 어두운 테마는 `@media (prefers-color-scheme: dark)` 안의 `:root` 다.
색을 더하거나 바꾸면 두 파일을 함께 고친다.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "docs" / "design" / "tokens.json"
CSS = ROOT / "canon" / "static" / "app.css"

COLOR = re.compile(r"^(#[0-9a-f]{3,8}|rgba?\([^)]*\))$")
DECL = re.compile(r"--([\w-]+)\s*:\s*([^;]+);")


def _block(text, start):
    """text[start] 의 `{` 와 짝이 맞는 `}` 까지의 안쪽 글."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    raise AssertionError("app.css 의 괄호 짝이 맞지 않아요")


def _norm(v):
    return re.sub(r"\s+", "", v.strip().lower())


def _colors(body):
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    out = {}
    for name, value in DECL.findall(body):
        v = _norm(value)
        if COLOR.match(v):
            out[name] = v
    return out


def css_themes():
    text = CSS.read_text(encoding="utf-8")
    light = re.search(r"^:root\s*\{", text, flags=re.M)
    assert light, "app.css 맨 위에 :root 블록이 없어요"
    media = re.search(r"@media\s*\(\s*prefers-color-scheme\s*:\s*dark\s*\)\s*\{", text)
    assert media, "app.css 에 @media (prefers-color-scheme: dark) 블록이 없어요"
    inner = _block(text, media.end() - 1)
    dark = re.search(r":root\s*\{", inner)
    assert dark, "어두운 테마 블록 안에 :root 가 없어요"
    return _colors(_block(text, light.end() - 1)), _colors(_block(inner, dark.end() - 1))


def doc_themes():
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    light, dark = {}, {}
    for t in data["color"]["tokens"]:
        light[t["name"]] = _norm(t["value"]["light"])
        dark[t["name"]] = _norm(t["value"]["dark"])
    return light, dark


def _diff(theme, doc, css):
    errs = []
    for k in sorted(doc.keys() - css.keys()):
        errs.append(f"{theme}: --{k} 는 tokens.json 에만 있어요")
    for k in sorted(css.keys() - doc.keys()):
        errs.append(f"{theme}: --{k} 는 app.css 에만 있어요 (docs/design/tokens.json 에 더해 주세요)")
    for k in sorted(doc.keys() & css.keys()):
        if doc[k] != css[k]:
            errs.append(f"{theme}: --{k} 값이 달라요 (tokens.json {doc[k]}, app.css {css[k]})")
    return errs


def test_color_tokens_match_css():
    css_light, css_dark = css_themes()
    doc_light, doc_dark = doc_themes()
    errs = _diff("밝게", doc_light, css_light) + _diff("어둡게", doc_dark, css_dark)
    assert not errs, "\n".join(errs)


def test_parser_finds_tokens():
    # 파서가 빈 결과로 통과하지 않게 한다
    css_light, css_dark = css_themes()
    assert {"bg", "accent", "overlay"} <= css_light.keys()
    assert {"bg", "accent", "overlay"} <= css_dark.keys()
    assert "sans" not in css_light  # 글꼴 변수는 색이 아니다
