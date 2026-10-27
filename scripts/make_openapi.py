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


def add_skipped(s: dict) -> dict:
    """`SkipJsonSchema` 로 숨긴 칸을 앱 명세에 되돌린다 (예: `Character.body`).
    그 칸은 Gemini 구조화 출력 스키마에서 빼려고 숨긴 것이다. 명세에도 없으면 Swift 생성 타입에 칸이 없어,
    앱이 작품을 저장할 때 그 값이 지워진다. 칸 순서는 모델 순서를 따른다."""
    import pydantic
    from pydantic.json_schema import SkipJsonSchema
    from canon import schema as sc
    comps = s["components"]["schemas"]
    for name, comp in comps.items():
        cls = getattr(sc, name, None)
        if not (isinstance(cls, type) and issubclass(cls, pydantic.BaseModel)) or "properties" not in comp:
            continue
        skipped = {f.alias or k: f for k, f in cls.model_fields.items() if any(isinstance(m, SkipJsonSchema) for m in f.metadata)}
        if not skipped:
            continue
        props = {}
        for k, f in cls.model_fields.items():
            key = f.alias or k
            if key in comp["properties"]:
                props[key] = comp["properties"][key]
            elif key in skipped:
                inner = f.annotation
                if not (isinstance(inner, type) and issubclass(inner, pydantic.BaseModel)):
                    raise TypeError(f"{name}.{key}: 숨긴 칸은 모델 타입만 되돌릴 수 있어요")
                if inner.__name__ not in comps:
                    comps[inner.__name__] = inner.model_json_schema(ref_template="#/components/schemas/{model}")
                props[key] = {"$ref": f"#/components/schemas/{inner.__name__}"}
        comp["properties"] = props
    return s


def spec() -> str:
    """JSON 글. 필드 순서는 서버 모델 순서 그대로라 Swift 생성 타입의 init 인자 순서도 같다. 화면 HTML(/)은 앱이 쓰지 않아 뺀다."""
    sys.path.insert(0, str(ROOT))
    from canon.web import app
    s = app.openapi()
    s["paths"].pop("/", None)
    return json.dumps(drop_null(add_skipped(s)), ensure_ascii=False, indent=1) + "\n"


if __name__ == "__main__":
    OUT.write_text(spec(), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} 를 다시 만들었어요")
