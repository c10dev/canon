"""swift/Sources/CanonAPI/openapi.json 만들기. Swift 앱은 이 파일로 API 클라이언트를 만든다
(swift-openapi-generator 빌드 플러그인). web.py 의 엔드포인트나 응답 모델을 바꾸면 다시 만든다.

python scripts/make_openapi.py
tests/test_openapi.py 가 파일이 지금 서버와 같은지 본다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "swift" / "Sources" / "CanonAPI" / "openapi.json"


def spec() -> str:
    """JSON 글. 필드 순서는 서버 모델 순서 그대로라 Swift 생성 타입의 init 인자 순서도 같다. 화면 HTML(/)은 앱이 쓰지 않아 뺀다."""
    sys.path.insert(0, str(ROOT))
    from canon.web import app
    s = app.openapi()
    s["paths"].pop("/", None)
    return json.dumps(s, ensure_ascii=False, indent=1) + "\n"


if __name__ == "__main__":
    OUT.write_text(spec(), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} 를 다시 만들었어요")
