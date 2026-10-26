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


NULL = {"type": "null"}


def drop_null(o):
    """`str | None` 같은 칸의 `anyOf: [..., {"type": "null"}]` 에서 null 을 뺀다.
    swift-openapi-generator 는 null 을 읽지 못해 그 칸을 생성 타입에서 아예 뺀다. 그러면 앱이 작품을 저장할 때 그 칸이 지워진다.
    null 을 빼고 필수 목록에서도 빼면 Swift 옵셔널이 된다. 서버의 null 은 nil 로 읽히고, nil 은 칸을 빼고 보내 서버 기본값(None)이 된다."""
    if isinstance(o, list):
        return [drop_null(x) for x in o]
    if not isinstance(o, dict):
        return o
    nullable = {k for k, p in (o.get("properties") or {}).items() if NULL in p.get("anyOf", [])}
    was_null = NULL in o.get("anyOf", [])
    o = {k: drop_null(v) for k, v in o.items()}
    if was_null:
        rest = [x for x in o["anyOf"] if x != NULL]
        del o["anyOf"]
        if o.get("default", 0) is None:
            del o["default"]
        if len(rest) == 1:
            o = {**rest[0], **o}
        elif rest:
            o["anyOf"] = rest
    if nullable and "required" in o:
        o["required"] = [r for r in o["required"] if r not in nullable] or None
        if o["required"] is None:
            del o["required"]
    return o


def spec() -> str:
    """JSON 글. 필드 순서는 서버 모델 순서 그대로라 Swift 생성 타입의 init 인자 순서도 같다. 화면 HTML(/)은 앱이 쓰지 않아 뺀다."""
    sys.path.insert(0, str(ROOT))
    from canon.web import app
    s = app.openapi()
    s["paths"].pop("/", None)
    return json.dumps(drop_null(s), ensure_ascii=False, indent=1) + "\n"


if __name__ == "__main__":
    OUT.write_text(spec(), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} 를 다시 만들었어요")
