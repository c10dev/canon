"""CSS 선택자 오타 막기: 의사 클래스 앞 콜론 뒤에 빈칸이 들어가면(`li: first-child`) 브라우저가 그 규칙 전체를 버린다.
app.css 와 화면 파일이 주입하는 CSS 를 모두 본다."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"
# 의사 클래스 · 의사 요소 이름 (콜론 뒤에 빈칸이 오면 오타다)
TYPO = re.compile(r"[a-z0-9)\]]: (hover|focus|focus-visible|focus-within|active|visited|checked|disabled|empty|before|after|placeholder"
                  r"|not\(|is\(|where\(|has\(|(first|last|nth|only)-(child|of-type))\b"
                  r"[\w\s.,>+~#:()\[\]=\"'*-]*\{")  # 선택자 뒤에 규칙 몸통 '{' 가 와야 CSS 다 (JS 객체 'done: checked' 를 빼려고)
# 미디어 · 컨테이너 조건 '(hover: hover)', '(max-width: 640px)' 은 빼고 본다
MEDIA = re.compile(r"\((?:any-)?(?:hover|pointer|max-width|min-width|max-height|min-height|orientation|forced-colors|prefers-[a-z-]+)[^)]*\)")


def test_no_space_after_pseudo_class_colon():
    bad = []
    for f in sorted([STATIC / "app.css", *STATIC.glob("*.js")]):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if TYPO.search(MEDIA.sub("", line)):
                bad.append(f"{f.name}:{i}: {line.strip()[:80]}")
    assert not bad, "의사 클래스 앞 콜론 뒤 빈칸:\n" + "\n".join(bad)
