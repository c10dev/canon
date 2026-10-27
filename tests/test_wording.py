"""화면 문구 규칙(AGENTS.md '규칙'): 영문 뒤 조사는 붙이고, 해요체로 쓴다.
static/*.js 의 문자열과 서버가 사용자에게 내보내는 문구(예외 메시지, HTTP 오류, 명령줄 출력)를 본다.
LLM 프롬프트와 주석, docstring 은 이 규칙 밖이라 보지 않는다."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "canon"
STATIC = ROOT / "static"

# 영문 · 숫자 · 닫는 괄호 뒤에 띄어 쓴 조사. 조사 뒤는 공백 · 문장부호 · 끝이어야 한다 ('API 키' 같은 낱말은 걸리지 않는다)
PARTICLES = "이라고|라고|으로|에서|까지|부터|처럼|보다|이나|이|가|은|는|을|를|로|와|과|의|에|도|만|나"
SPACED = re.compile(rf"[A-Za-z0-9)\]] ({PARTICLES})(?=$|[\s,.!?:;'\"<)\]…·])")
# 식 바로 뒤 문자열이 띄운 조사로 시작한다: `${name} 가` (조사는 josa() 로 고른다)
LEADING = re.compile(rf"^ ({PARTICLES})(?=$|[\s,.!?:;'\"<)\]…·])")
# 합쇼체 끝맺음 (해요체로 쓴다): ㅂ 받침 글자 + '니다' ('합니다', '없습니다'). '아니다' 는 걸리지 않는다
FORMAL = re.compile(r"[가-힣]니다(?![가-힣])")
# 식 뒤의 '이'가 조사가 아니라 지시어('이 구조', '이 수정')인 문구
ALLOW_LEADING = (" 이 구조는", " 이 수정을")


def formal(text: str):
    return [m.group(0) for m in FORMAL.finditer(text) if (ord(m.group(0)[0]) - 0xAC00) % 28 == 17]


def js_strings(src: str):
    """JS 소스에서 문자열 조각을 (줄, 글, 식 바로 뒤인지) 로 낸다. 주석과 정규식 리터럴은 건너뛴다.
    템플릿 문자열은 ${...} 를 식으로 다시 읽어 안쪽 문자열도 낸다."""
    out = []
    i, n, line = 0, len(src), 1
    stack = []  # 템플릿 안 ${ 깊이: 닫는 } 를 만나면 템플릿으로 돌아간다
    prev = ""  # 정규식과 나눗셈을 가르는 앞 토큰
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += src.count("\n", i, j)
            i = j
            continue
        if c in "'\"":
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == "\\":
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            out.append((line, "".join(buf), False))
            i, prev = j + 1, "str"
            continue
        if c == "`" or (c == "}" and stack and stack[-1] == 0):
            after_expr = c == "}"
            if after_expr:
                stack.pop()
            j, buf, start = i + 1, [], line
            while j < n and src[j] != "`" and not src.startswith("${", j):
                if src[j] == "\\":
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                if src[j] == "\n":
                    line += 1
                buf.append(src[j])
                j += 1
            out.append((start, "".join(buf), after_expr))
            if src.startswith("${", j):
                stack.append(0)
                i = j + 2
                prev = "("
            else:
                i, prev = j + 1, "str"
            continue
        if c == "{" and stack:
            stack[-1] += 1
        elif c == "}" and stack:
            stack[-1] -= 1
        if c == "/" and (prev in ("", "(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";", "+", "-", "*", "%", "<", ">", "~", "^")
                         or prev in ("return", "typeof", "case", "of", "in")):
            j, cls = i + 1, False  # 정규식 리터럴
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    cls = True
                elif src[j] == "]":
                    cls = False
                elif src[j] == "/" and not cls:
                    break
                j += 1
            i, prev = j + 1, "re"
            while i < n and src[i].isalpha():
                i += 1
            continue
        m = re.match(r"[A-Za-z_$][\w$]*|\d[\w.]*", src[i:])
        if m:
            prev = m.group(0) if m.group(0) in ("return", "typeof", "case", "of", "in") else "id"
            i += len(m.group(0))
            continue
        prev = c
        i += 1
    return out


def py_messages(path: Path):
    """사용자에게 보이는 서버 문구: raise 의 메시지, HTTPException 의 detail, print 출력."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []

    def texts(node):
        after = set()  # f-string 에서 {식} 바로 뒤에 오는 조각
        for sub in ast.walk(node):
            if isinstance(sub, ast.JoinedStr):
                after |= {id(b) for a, b in zip(sub.values, sub.values[1:]) if isinstance(a, ast.FormattedValue)}
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                yield sub.lineno, sub.value, id(sub) in after

    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            out += texts(node.exc)
        elif isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name in ("HTTPException", "print"):
                out += texts(node)
    return out


def problems(items, where):
    bad = []
    for line, text, after_expr in items:
        lead = LEADING.match(text) if after_expr and not text.startswith(ALLOW_LEADING) else None
        hits = [text[max(0, m.start() - 12):m.end()] for m in SPACED.finditer(text)] + (["${…}" + lead.group(0)] if lead else [])
        hits += [f"합쇼체 {w}" for w in formal(text)]
        bad += [f"{where}:{line}: {h!r}  ← {text.strip()[:60]!r}" for h in hits]
    return bad


def test_js_strings_follow_wording_rules():
    bad = []
    for f in sorted(STATIC.glob("*.js")):
        bad += problems(js_strings(f.read_text(encoding="utf-8")), f.name)
    assert not bad, "화면 문구 규칙 위반 (영문 뒤 조사는 붙이고, 해요체로):\n" + "\n".join(bad)


def test_server_messages_follow_wording_rules():
    bad = []
    for f in sorted(ROOT.glob("*.py")):
        if f.name == "mock.py":  # 테스트용 가짜 LLM 출력
            continue
        bad += problems(py_messages(f), f.name)
    assert not bad, "서버 문구 규칙 위반 (영문 뒤 조사는 붙이고, 해요체로):\n" + "\n".join(bad)


def test_scanner_reads_strings_not_comments():
    src = "// AI 가 주석\nconst a = 'AI 가 문자열'; const r = /x 가/; const t = `${n} 가 ${'Gemini 나'}` /* API 를 */;"
    texts = [t for _, t, _ in js_strings(src)]
    assert "AI 가 문자열" in texts and "Gemini 나" in texts
    assert not any("주석" in t or "API 를" in t or "x 가" in t for t in texts)
    assert problems(js_strings(src), "x") and len(problems(js_strings(src), "x")) == 3
