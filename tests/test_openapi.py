"""Swift 앱의 API 명세(swift/Sources/CanonAPI/openapi.json)가 지금 서버와 같은지 본다."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("make_openapi", ROOT / "scripts" / "make_openapi.py")
make_openapi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_openapi)


class OpenAPITest(unittest.TestCase):
    def test_swift_spec_is_current(self):
        want = make_openapi.spec()
        have = make_openapi.OUT.read_text(encoding="utf-8")
        self.assertEqual(have, want, "web.py 가 바뀌었어요. python scripts/make_openapi.py 로 openapi.json 을 다시 만드세요")

    def test_operation_ids_are_function_names(self):
        import json
        ops = [o["operationId"] for p in json.loads(make_openapi.spec())["paths"].values() for o in p.values()]
        self.assertIn("list_projects", ops)
        self.assertEqual(len(ops), len(set(ops)))


if __name__ == "__main__":
    unittest.main()
