"""로컬(OpenAI 호환) 백엔드, 단계별 라우팅, compare 명령 테스트. 가짜 서버를 띄워 확인한다.

    python -m unittest
"""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

os.environ["CANON_LLM"] = "mock"
os.environ["CANON_HOME"] = tempfile.mkdtemp()  # 셸에 CANON_HOME 이 있어도 사용자 작품 폴더를 건드리지 않게

from canon import settings, store  # noqa: E402
from canon.cli import main  # noqa: E402
from canon.llm import LocalLLM, get_llm  # noqa: E402
from canon.mock import MockLLM  # noqa: E402
from canon.schema import StyleProfile  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample_style.txt"


class FakeServer(BaseHTTPRequestHandler):
    """요청을 기록하고, 큐에 넣어 둔 응답을 차례로 돌려준다."""
    requests: list[dict] = []
    replies: list[str] = []
    models = ["gemma-4-31b-it"]

    def log_message(self, *args):  # 테스트 출력 조용히
        pass

    def _send(self, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send({"data": [{"id": m} for m in self.models]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        body["_auth"] = self.headers.get("Authorization")
        FakeServer.requests.append(body)
        content = FakeServer.replies.pop(0) if FakeServer.replies else "바람이 불었다. (로컬 본문)"
        self._send({"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]})


class LocalLLMTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeServer)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeServer.requests, FakeServer.replies = [], []
        self.cfg = Path(tempfile.mkdtemp()) / "config.json"
        env = {"CANON_CONFIG": str(self.cfg), "CANON_LOCAL_URL": self.url}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        stage_env = [f"CANON_{k}_{s.upper()}" for k in ("LLM", "MODEL") for s in settings.STAGES]
        for name in ("CANON_LOCAL_MODEL", "CANON_LOCAL_KEY", *stage_env):
            os.environ.pop(name, None)

    def tearDown(self):
        self.env.stop()

    def test_model_autodetect_and_text(self):
        llm = LocalLLM(api_key="secret")
        llm.check()
        self.assertEqual(llm.model, "gemma-4-31b-it")
        FakeServer.replies = ["<think>계획</think>\n서윤은 웃지 않았다."]
        self.assertEqual(llm.text("시스템", "써라"), "서윤은 웃지 않았다.")
        req = FakeServer.requests[-1]
        self.assertEqual(req["messages"][0], {"role": "system", "content": "시스템"})
        self.assertEqual(req["min_p"], settings.DEFAULT_SAMPLING["min_p"])
        self.assertEqual(req["_auth"], "Bearer secret")

    def test_unknown_model_fails_check(self):
        with self.assertRaises(RuntimeError):
            LocalLLM(model="없는-모델").check()

    def test_json_retries_once_on_invalid(self):
        good = StyleProfile(narration_pov="3인칭 제한", tense="과거형").model_dump_json()
        FakeServer.replies = ['{"narration_pov": 3, "dos": "x"}', "```json\n" + good + "\n```"]
        out = LocalLLM().json("시스템", "분석", StyleProfile)
        self.assertEqual(out.tense, "과거형")
        first, second = FakeServer.requests
        self.assertEqual(first["response_format"]["type"], "json_schema")
        self.assertEqual(first["response_format"]["json_schema"]["name"], "StyleProfile")
        self.assertNotIn("$defs", json.dumps(first["response_format"]))
        sent = first["response_format"]["json_schema"]["schema"]
        self.assertEqual(sent["required"], list(sent["properties"]))  # 기본값 있는 필드도 빼먹지 않게
        self.assertEqual(len(second["messages"]), 4)  # 시스템, 질문, 틀린 답, 오류 안내

        FakeServer.replies = ["{}x", "{}x"]
        with self.assertRaises(RuntimeError):
            LocalLLM().json("시스템", "분석", StyleProfile)

    def test_out_of_range_numbers_are_clamped(self):
        from canon.schema import Relationship, StoryEvent
        r = Relationship(a="a", b="b", type="적", affinity=40, tension=90, goal_conflict=-1.0)
        self.assertEqual((r.affinity, r.tension, r.goal_conflict), (5, 10, 0.0))
        self.assertEqual(StoryEvent(episode=1, actor="a", target="b", kind="도움", intensity=7).intensity, 3)
        self.assertEqual(Relationship.model_json_schema()["properties"]["affinity"]["minimum"], -5)

    def test_stage_routing(self):
        with mock.patch.dict(os.environ, {"CANON_LLM": "gemini", "CANON_LLM_WRITE": "mock"}):
            self.assertIsInstance(get_llm("write"), MockLLM)
            self.assertEqual(settings.stage_provider("plan")[0], "gemini")
            settings.update(stages={"check": "local", "state": "local"})
            self.assertIsInstance(get_llm("check"), LocalLLM)
            self.assertEqual(settings.public()["stages"]["state"]["model"], "로컬 서버 모델")
            settings.update(stages={"check": ""})
            self.assertEqual(settings.stage_provider("check")[0], "gemini")
            self.assertEqual(settings.public()["stage_settings"], {"state": "local"})
        with mock.patch.dict(os.environ, {"CANON_LLM": "mock"}):  # mock 이면 단계 설정과 무관하게 mock
            self.assertIsInstance(get_llm("state"), MockLLM)

    def test_stage_model(self):
        with mock.patch.dict(os.environ, {"CANON_LLM": "local"}):
            settings.update(stage_models={"state": "gemma-small"})
            self.assertEqual(get_llm("state").model, "gemma-small")
            self.assertEqual(get_llm("write").model, "gemma-4-31b-it")  # 비우면 서버의 기본 모델
            self.assertEqual(settings.public()["stages"]["state"]["model"], "gemma-small")
            with mock.patch.dict(os.environ, {"CANON_MODEL_STATE": "gemma-env"}):
                self.assertEqual(settings.stage_model("state"), ("gemma-env", "env"))
            FakeServer.replies = ["상태 정리"]
            get_llm("state").text("시스템", "정리")
            self.assertEqual(FakeServer.requests[-1]["model"], "gemma-small")

    def test_compare_and_pick(self):
        # 다른 테스트가 먼저 store 를 불러왔어도 매번 빈 폴더에서 돈다
        patcher = mock.patch.object(store, "ROOT", Path(tempfile.mkdtemp()))
        patcher.start()
        self.addCleanup(patcher.stop)
        main(["new", "cmp", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "10", "-y"])
        main(["style", "cmp", str(SAMPLE), "-y"])
        main(["arc", "cmp", "-y"])
        main(["plot", "cmp"])
        main(["confirm", "cmp", "all"])
        main(["compare", "cmp", "1", "--a", "mock", "--b", "local"])
        out = store.project_dir("cmp") / "compare" / "01"
        order = json.loads((out / "key.json").read_text(encoding="utf-8"))["order"]
        self.assertEqual(sorted(order), ["local", "mock"])
        k = order.index("local") + 1
        self.assertIn("로컬 본문", (out / f"{k}.md").read_text(encoding="utf-8"))

        main(["compare", "cmp", "1", "--pick", str(k)])
        ep = store.load("cmp").episode(1)
        self.assertEqual((ep.status, ep.text), ("written", "바람이 불었다. (로컬 본문)"))
        log = (store.project_dir("cmp") / "compare" / "log.jsonl").read_text(encoding="utf-8")
        self.assertEqual(json.loads(log)["picked"], "local")


if __name__ == "__main__":
    unittest.main()
