"""Swift 앱의 API 명세(swift/Sources/CanonAPI/openapi.json)가 지금 서버와 같은지 본다."""
import importlib.util
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("make_openapi", ROOT / "scripts" / "make_openapi.py")
make_openapi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_openapi)


@unittest.skipUnless(os.environ.get("CANON_SWIFT"), "Swift 앱 개발을 멈춘 동안은 CANON_SWIFT=1 일 때만 봐요")
class OpenAPITest(unittest.TestCase):
    def test_swift_spec_is_current(self):
        want = make_openapi.spec()
        have = make_openapi.OUT.read_text(encoding="utf-8")
        self.assertEqual(have, want, "web.py 가 바뀌었어요. python scripts/make_openapi.py 로 openapi.json 을 다시 만드세요")

    def test_no_null_schema(self):
        # 생성기는 null 을 읽지 못해 그 칸을 빼고, 앱이 작품을 저장하면 그 칸이 지워진다
        import json
        s = json.loads(make_openapi.spec())
        self.assertNotIn('{"type": "null"}', json.dumps(s))
        fs = s["components"]["schemas"]["Foreshadow"]
        self.assertEqual(fs["properties"]["payoff_ep"]["type"], "integer")
        self.assertNotIn("payoff_ep", fs.get("required", []))

    def test_schema_models_keep_every_field(self):
        # 명세에 없는 칸은 Swift 생성 타입에도 없어, 앱이 작품을 저장하면 지워진다 (SkipJsonSchema 로 숨긴 칸 포함)
        import json
        import pydantic
        from canon import schema as sc
        comps = json.loads(make_openapi.spec())["components"]["schemas"]
        self.assertIn("body", comps["Character"]["properties"])
        for name, comp in comps.items():
            cls = getattr(sc, name, None)
            if isinstance(cls, type) and issubclass(cls, pydantic.BaseModel) and "properties" in comp:
                want = {f.alias or k for k, f in cls.model_fields.items()}
                self.assertEqual(want - set(comp["properties"]), set(), name)

    def test_operation_ids_are_function_names(self):
        import json
        ops = [o["operationId"] for p in json.loads(make_openapi.spec())["paths"].values() for o in p.values()]
        self.assertIn("list_projects", ops)
        self.assertEqual(len(ops), len(set(ops)))


if __name__ == "__main__":
    unittest.main()
