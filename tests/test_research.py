"""연구 화면 API 테스트: 서버 점검, 샘플 생성, 단계 시험, 컨텍스트 크기, 블라인드 비교. 가짜 로컬 서버와 mock 으로 확인한다.

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

os.environ.setdefault("CANON_LLM", "mock")
os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())

from fastapi.testclient import TestClient  # noqa: E402

from canon import research, settings, store, web  # noqa: E402
from canon.schema import Relationship, SetupSuggestion  # noqa: E402

SAMPLE = (Path(__file__).resolve().parent.parent / "examples" / "sample_style.txt").read_text(encoding="utf-8")


class VllmLike(BaseHTTPRequestHandler):
    """vLLM 처럼 max_model_len, /version, /tokenize 를 주는 가짜 서버."""
    replies: list[str] = []
    max_len = 4096

    def log_message(self, *args):
        pass

    def _send(self, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/version":
            return self._send({"version": "0.32.0"})
        self._send({"data": [{"id": "base-12b", "owned_by": "vllm", "parent": None, "max_model_len": VllmLike.max_len},
                             {"id": "base-lora", "owned_by": "vllm", "parent": "base-12b", "max_model_len": None}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/tokenize":
            return self._send({"count": len(body["prompt"]) // 2})
        content = VllmLike.replies.pop(0) if VllmLike.replies else "비가 왔다. 서윤은 등대를 봤다."
        self._send({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20}})


class ResearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), VllmLike)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        VllmLike.replies, VllmLike.max_len = [], 4096
        cfg = Path(tempfile.mkdtemp()) / "config.json"
        self.env = mock.patch.dict(os.environ, {"CANON_CONFIG": str(cfg), "CANON_LOCAL_URL": self.url, "CANON_LLM": "mock"})
        self.env.start()
        for name in ("CANON_LOCAL_MODEL", "CANON_LOCAL_KEY", *(f"CANON_LLM_{s.upper()}" for s in settings.STAGES)):
            os.environ.pop(name, None)
        self.c = TestClient(web.app)
        self.name = "rs-" + next(tempfile._get_candidate_names())
        meta = {"title": "등대", "genre": "미스터리", "logline": "오빠를 찾는다", "target_episodes": 10}
        assert self.c.post("/api/projects", json={"name": self.name, "meta": meta}).status_code == 200
        api = f"/api/projects/{self.name}"
        s = self.c.post(f"{api}/suggest").json()
        p = self.c.post(f"{api}/suggest/apply", json=s).json()
        p["style"] = self.c.post(f"{api}/style", json={"text": SAMPLE}).json()
        p["arc"] = self.c.post(f"{api}/arc").json()["acts"]
        self.c.put(api, json=p)
        self.c.post(f"{api}/plots", json={})
        self.c.post(f"{api}/episodes/1/confirm")
        self.api = api

    def tearDown(self):
        self.env.stop()

    def test_probe_reports_context_and_server(self):
        r = self.c.post("/api/research/probe", json={"url": self.url}).json()
        self.assertEqual(r["server"], "vllm")
        self.assertEqual(r["version"], "0.32.0")
        self.assertEqual([m["max_model_len"] for m in r["models"]], [4096, None])
        bad = self.c.post("/api/research/probe", json={"url": "http://127.0.0.1:9/v1"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("서버가 꺼져 있거나", bad.json()["detail"])
        self.assertNotIn("Errno", bad.json()["detail"])

    def test_lora_uses_parent_context_limit(self):
        from canon.llm import LocalLLM

        self.assertEqual(LocalLLM(model="base-lora").context_limit(), 4096)
        self.assertEqual(LocalLLM(model="base-12b").count_tokens("가나다라"), 2)

    def test_sample_runs_each_backend_and_logs(self):
        runs = [{"provider": "local", "model": "base-12b"}, {"provider": "mock"}, {"provider": "local", "url": "http://127.0.0.1:9/v1"}]
        r = self.c.post(f"{self.api}/research/sample", json={"runs": runs, "prompt": "등대 장면을 써라"}).json()
        ok, mocked, failed = r["rows"]
        self.assertTrue(ok["ok"] and ok["usage"]["completion_tokens"] == 20 and ok["chars"] > 0)
        self.assertTrue(mocked["ok"])
        self.assertFalse(failed["ok"])
        self.assertIn("연결하지 못했어요", failed["error"])
        log = self.c.get(f"{self.api}/research").json()["log"]
        self.assertEqual(log[0]["id"], r["id"])

    def test_stage_trial_finds_empty_fields_and_out_of_range(self):
        VllmLike.replies = [json.dumps({"sample_passages": ["바람이 불었다."]}, ensure_ascii=False)]
        r = self.c.post(f"{self.api}/research/stage", json={"backend": {"provider": "local", "model": "base-12b"}, "stage": "style"}).json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["attempts"], 1)
        self.assertIn("narration_pov", r["empty"])
        self.assertNotIn("sample_passages", r["empty"])
        project = store.load(self.name)
        self.assertTrue(project.style.narration_pov)  # 시험은 저장하지 않는다

        # 검증은 범위 밖 값을 잘라 넣으므로 모델이 낸 원본 JSON 으로 본다
        bad = {"relationships": [{"a": "a", "b": "b", "type": "적대", "affinity": 40, "tension": 90, "goal_conflict": -1.0}]}
        self.assertEqual(Relationship(**bad["relationships"][0]).affinity, 5)
        found = research.out_of_range(SetupSuggestion, bad)
        self.assertEqual([x.split("=")[0] for x in found],
                         ["relationships[0].affinity", "relationships[0].tension", "relationships[0].goal_conflict"])

    def test_check_trial_plants_and_scores_each_mode(self):
        p = store.load(self.name)
        e = p.episode(1)
        e.text, e.status = "서윤은 등대 문을 열었다. 바람이 거셌다. 도현이 뒤에서 불렀다. 둘은 계단을 올랐다.", "written"
        store.save(self.name, p)
        r = self.c.post(f"{self.api}/research/check", json={"backend": {"provider": "mock"}, "episode": 1, "plants": 2}).json()
        self.assertEqual(len(r["planted"]), 2)
        self.assertEqual([m["mode"] for m in r["runs"]], ["full", "budget"])
        self.assertTrue(all(m["ok"] and m["found"] == 2 for m in r["runs"]))
        self.assertIn("사실 그는 처음 보는 사람이었다", r["planted"][0]["replacement"])
        # 동선 모순은 몸 · 접촉 · 물건 갈래로 세고, 근거는 같은 화 앞 문장
        self.assertEqual([(x["kind"], x["source_episode"], x["distance"]) for x in r["planted"]], [("사실", 0, None), ("동선 · 접촉", 1, 0)])
        self.assertEqual(r["runs"][0]["by_kind"], [{"kind": "사실", "found": 1, "planted": 1}, {"kind": "동선 · 접촉", "found": 1, "planted": 1}])
        self.assertEqual(store.load(self.name).episode(1).text, e.text)  # 작품은 그대로
        got = self.c.get(f"{self.api}/research").json()
        self.assertEqual(got["log"][0]["kind"], "check")
        self.assertIn({"mode": "budget", "kind": "동선 · 접촉", "found": 1, "planted": 1, "trials": 1}, got["check_totals"])
        # 갈래를 적기 전 기록은 모순 종류로 센다
        research.record(self.name, "check", {"planted": [{"type": "말투"}], "runs": [{"mode": "full", "ok": True, "hits": [False]},
                                                                                {"mode": "budget", "ok": False}]})
        self.assertIn({"mode": "full", "kind": "말투", "found": 0, "planted": 1, "trials": 1}, research.check_totals(self.name))
        bad = self.c.post(f"{self.api}/research/check", json={"backend": {"provider": "mock"}, "episode": 2})
        self.assertEqual(bad.status_code, 400)  # 본문 없는 화

        r = self.c.post(f"{self.api}/research/check", json={"backend": {"provider": "mock"}, "episode": 1, "plants": 2,
                                                             "judge": {"provider": "mock"}}).json()
        self.assertEqual([m["mode"] for m in r["runs"]], ["full", "budget", "twostep"])
        two = r["runs"][2]
        self.assertTrue(two["ok"], two.get("error"))
        self.assertEqual((two["found"], two["raised"], two["flagged"]), (2, [True, True], 2))
        self.assertEqual(two["claims"], 4)
        self.assertGreater(two["judge_tokens"], 0)
        self.assertEqual(r["judge"], "mock")
        self.assertIn("twostep", self.c.get(f"{self.api}/research").json()["check_modes"])

        # 장면 연출 규칙 검수: 사건마다 본문 장면을 뽑고 규칙 판정이 동선만 짚는다. 심은 동선은 거리 규칙에 걸린다
        r = self.c.post(f"{self.api}/research/check", json={"backend": {"provider": "mock"}, "episode": 1, "plants": 2, "stage": True}).json()
        self.assertEqual([m["mode"] for m in r["runs"]], ["full", "budget", "stage"])
        sc = r["runs"][2]
        self.assertTrue(sc["ok"], sc.get("error"))
        self.assertTrue(sc["scenes"] and sc["tokens"] > 0)
        self.assertEqual([(k["kind"], k["found"]) for k in sc["by_kind"]], [("사실", 1), ("동선 · 접촉", 1)])  # 가짜 응답은 심은 문장마다 짚는다
        self.assertTrue(all(i["type"] == "동선" and i["origin"] == "rule" for i in sc["other"]))
        self.assertIn({"mode": "stage", "kind": "동선 · 접촉", "found": 1, "planted": 1, "trials": 1},
                      self.c.get(f"{self.api}/research").json()["check_totals"])
        self.assertEqual(store.load(self.name).episode(1).stage, [])  # 시험은 작품에 장면을 넣지 않는다

    def test_budget_flags_first_episode_over_limit(self):
        VllmLike.max_len = 3000
        r = self.c.post(f"{self.api}/research/budget", json={"provider": "local", "model": "base-12b"}).json()
        self.assertEqual(r["limit"], 3000)
        self.assertTrue(r["tokenizer"])
        self.assertEqual(len(r["rows"]), 10)
        checks = [x["check"]["tokens"] for x in r["rows"]]
        self.assertEqual(checks, sorted(checks))  # 검수는 앞선 본문을 모두 넣어 커진다
        self.assertIsNotNone(r["first_over"])
        self.assertLessEqual(r["first_tight"], r["first_over"])
        first = r["rows"][r["first_over"] - 1]
        self.assertTrue(any(first[k]["tokens"] > 3000 for k in ("write", "check", "state")))
        VllmLike.max_len = 10_000_000
        r = self.c.post(f"{self.api}/research/budget", json={"provider": "local", "model": "base-12b"}).json()
        self.assertIsNone(r["first_over"])

    def test_blind_compare_hides_until_pick(self):
        body = {"a": {"provider": "mock"}, "b": {"provider": "local", "model": "base-12b"}}
        c = self.c.post(f"{self.api}/research/compare/1", json=body).json()["compare"]
        self.assertEqual(len(c["drafts"]), 2)
        self.assertNotIn("order", c)
        self.assertNotIn("order", self.c.get(f"{self.api}/research/compare/1").json()["compare"])

        r = self.c.post(f"{self.api}/research/compare/1/pick", json={"k": 2, "adopt": False}).json()
        self.assertEqual(set(r["compare"]["order"]), {"mock", "local:base-12b"})
        self.assertFalse(r["result"]["adopted"])
        self.assertEqual(r["project"]["episodes"][0]["status"], "confirmed")

        self.c.post(f"{self.api}/research/compare/1", json=body)
        r = self.c.post(f"{self.api}/research/compare/1/pick", json={"k": 1}).json()
        self.assertTrue(r["result"]["adopted"])
        self.assertEqual(r["project"]["episodes"][0]["status"], "written")
        self.assertEqual(r["project"]["episodes"][0]["text"], r["compare"]["drafts"][0]["text"])
        self.assertEqual(sum(r["result"]["wins"].values()), 2)

        same = self.c.post(f"{self.api}/research/compare/1", json={"a": {"provider": "mock"}, "b": {"provider": "mock"}})
        self.assertEqual(same.status_code, 400)

        # 앞 화 반영이 남은 화는 쓰지 않고, 막힌 화를 사람이 읽는 꼴로 알린다
        from canon import pipeline
        with self.assertRaisesRegex(ValueError, r"이전 화\(1화\)의 상태 반영이 끝나지 않았어요"):
            pipeline.require_previous(store.load(self.name), 2)


if __name__ == "__main__":
    unittest.main()
