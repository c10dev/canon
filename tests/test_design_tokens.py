"""디자인 시스템 토큰(docs/design/tokens.json)과 화면 CSS(canon/static/app.css)가 같은지 본다.

app.css 의 밝은 테마는 맨 위 `:root`, 어두운 테마는 `@media (prefers-color-scheme: dark)` 안의 `:root` 다.
색을 더하거나 바꾸면 두 파일을 함께 고친다.
간격 · 간격 리듬 · 모서리 · 크기 · 그림자 · 쌓는 층(z)은 테마가 없어 맨 위 `:root` 에만 있다.
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


NON_COLOR = ("spacing", "rhythm", "radius", "size", "shadow", "z")


def _decls(body):
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return {name: _norm(value) for name, value in DECL.findall(body)}


def _root_text():
    text = CSS.read_text(encoding="utf-8")
    light = re.search(r"^:root\s*\{", text, flags=re.M)
    assert light, "app.css 맨 위에 :root 블록이 없어요"
    return _block(text, light.end() - 1)


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


def test_non_color_tokens_match_css():
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    css = _decls(_root_text())
    errs = []
    for group in NON_COLOR:
        assert group in data, f"tokens.json 에 {group} 묶음이 없어요"
        for tok in data[group]["tokens"]:
            name, want = tok["name"], _norm(tok["value"])
            if name not in css:
                errs.append(f"--{name} 가 app.css :root 에 없어요 (tokens.json {group})")
            elif css[name] != want:
                errs.append(f"--{name} 값이 달라요 (tokens.json {want}, app.css {css[name]})")
    prefixes = ("space-", "gap-", "pad-", "radius-", "shadow-", "z-")
    names = {t["name"] for g in NON_COLOR for t in data[g]["tokens"]}
    for name in sorted(css):
        if name.startswith(prefixes) and name not in names:
            errs.append(f"--{name} 는 app.css 에만 있어요 (docs/design/tokens.json 에 더해 주세요)")
    assert not errs, "\n".join(errs)


def test_rhythm_uses_space_scale():
    # 간격 리듬은 spacing 단계를 가리키는 이름이다. 640px 이하 값(phone)도 단계 안에서 고른다
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    steps = {t["name"] for t in data["spacing"]["tokens"]}
    errs = []
    for tok in data["rhythm"]["tokens"]:
        for key in ("value", "phone"):
            v = tok.get(key)
            if v is None:
                continue
            m = re.fullmatch(r"var\(--([\w-]+)\)", v)
            if not m or m.group(1) not in steps:
                errs.append(f"--{tok['name']} {key} 는 var(--space-*) 여야 해요: {v}")
    text = CSS.read_text(encoding="utf-8")
    phone = re.search(r"@media \(max-width: 640px\) \{ :root \{([^}]*)\}", text)
    assert phone, "app.css 에 640px 이하 리듬(:root) 블록이 없어요"
    got = _decls(phone.group(1))
    want = {t["name"]: _norm(t["phone"]) for t in data["rhythm"]["tokens"] if "phone" in t}
    if got != want:
        errs.append(f"640px 이하 리듬이 tokens.json phone 과 달라요: app.css {got}, tokens.json {want}")
    assert not errs, "\n".join(errs)


def test_z_index_uses_ladder():
    # 쌓는 층은 --z-* 사다리로 쓴다. 0 · auto 와 한 층 안의 작은 수(1~2)만 숫자로 둘 수 있다
    text = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    bad = [v for v in re.findall(r"z-index\s*:\s*([^;}]+)", text)
           if not v.strip().startswith(("var(--z-", "calc(var(--z-")) and v.strip() not in ("0", "auto")]
    assert not bad, f"z-index 를 --z-* 변수로 써 주세요: {bad}"
