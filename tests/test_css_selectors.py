"""CSS 선택자 오타 막기: 의사 클래스 앞 콜론 뒤에 빈칸이 들어가면(`li: first-child`) 브라우저가 그 규칙 전체를 버린다.
app.css 와 화면 파일이 주입하는 CSS 를 모두 본다."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"
TYPO = re.compile(r"[a-z0-9)\]]: (first|last|nth|only)-(child|of-type)")


def test_no_space_after_pseudo_class_colon():
    bad = []
    for f in sorted([STATIC / "app.css", *STATIC.glob("*.js")]):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if TYPO.search(line):
                bad.append(f"{f.name}:{i}: {line.strip()[:80]}")
    assert not bad, "의사 클래스 앞 콜론 뒤 빈칸:\n" + "\n".join(bad)
