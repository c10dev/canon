"""판단기 테스트: 로컬 서버의 logprobs 읽기, 사용량 기록, 두 걸음 검수 흐름. 가짜 서버와 mock 으로 확인한다.

    python -m unittest
"""
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

os.environ.setdefault("CANON_LLM", "mock")
os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())

from canon import context, pipeline, prompts, usage  # noqa: E402
from canon.judge import LocalJudge, MockJudge, Question, label_probs  # noqa: E402
from canon.mock import MockLLM  # noqa: E402
from canon.schema import Character, Episode, EpisodePlot, Meta, Project  # noqa: E402


def _plot(n: int, cast: list[str] | None = None) -> EpisodePlot:
    return EpisodePlot(number=n, act="기", title=str(n), summary="", events=[], characters=cast or [], emotional_shift="", ending_hook="")


class LogprobServer(BaseHTTPRequestHandler):
    """질문에 '틀린 진술' 이 있으면 B, 아니면 A 에 높은 확률을 주는 vLLM 흉내. plain=True 면 logprobs 없이 글자만 낸다."""
    requests: list[dict] = []
    plain = False

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
        self._send({"data": [{"id": "gemma-judge"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        LogprobServer.requests.append(body)
        bad = "틀린 진술" in body["messages"][-1]["content"]
        top = [{"token": "B" if bad else "A", "logprob": -0.1}, {"token": " A" if bad else " B", "logprob": -2.5},
               {"token": "C", "logprob": -4.0}, {"token": "그", "logprob": -5.0}]
        choice = {"message": {"content": "B" if bad else "A"}, "finish_reason": "length"}
        if not LogprobServer.plain:
            choice["logprobs"] = {"content": [{"token": top[0]["token"], "logprob": -0.1, "top_logprobs": top}]}
        self._send({"choices": [choice], "usage": {"prompt_tokens": 120, "completion_tokens": 1,
                                                   "prompt_tokens_details": {"cached_tokens": 40}}})


class JudgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), LogprobServer)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        LogprobServer.requests, LogprobServer.plain = [], False
        self.log = tempfile.mktemp(suffix=".jsonl")
        self.env = mock.patch.dict(os.environ, {"CANON_USAGE": self.log})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_label_probs_sums_same_letter(self):
        w, mass = label_probs([{"token": "A", "logprob": 0.0}, {"token": " A", "logprob": 0.0}, {"token": "(B)", "logprob": 0.0},
                               {"token": "Z", "logprob": 0.0}, {"token": "D", "logprob": 0.0}], 3)
        self.assertEqual(w, [2.0, 1.0, 0.0])  # D 는 선택지 밖
        self.assertEqual(mass, 3.0)

    def test_local_judge_reads_logprobs_and_records_usage(self):
        j = LocalJudge(base_url=self.url, model="gemma-judge", workers=2)
        qs = [Question(id="0", state="자료", text="맞는 진술", options=prompts.CLAIM_OPTIONS),
              Question(id="1", state="자료", text="틀린 진술", options=prompts.CLAIM_OPTIONS)]
        a = j.decide(prompts.SYSTEM_JUDGE_CHECK, qs)
        self.assertEqual([x.id for x in a], ["0", "1"])
        self.assertEqual(a[0].choice, "근거와 맞음")
        self.assertEqual(a[1].choice, "근거와 어긋남")
        self.assertAlmostEqual(sum(a[1].probs), 1.0, places=3)
        self.assertGreater(a[1].probs[1], 0.85)
        body = LogprobServer.requests[0]
        self.assertEqual((body["max_tokens"], body["logprobs"], body["temperature"]), (1, True, 0))
        self.assertIn("A. 근거와 맞음", body["messages"][-1]["content"])
        rows = usage.read()
        self.assertEqual(len(rows), 2)
        self.assertEqual({(r["backend"], r["stage"], r["model"], r["in"], r["cached"]) for r in rows},
                         {("local", "judge", "gemma-judge", 120, 40)})

    def test_local_judge_without_logprobs_uses_the_letter(self):
        LogprobServer.plain = True
        a = LocalJudge(base_url=self.url, model="gemma-judge").decide("", [Question(id="x", text="틀린 진술", options=["예", "아니오"])])
        self.assertEqual(a[0].choice, "아니오")
        self.assertEqual(a[0].mass, 0.0)  # 확률이 아니라 낸 글자만 믿었다는 표시

    def test_two_step_flags_only_contradicting_claims(self):
        p = Project(meta=Meta(title="t", form="serial"), characters=[Character(id="a", name="서윤", role="주인공", speech_style="존댓말", tier="main")],
                    facts=["서윤은 왼손을 다쳤다"],
                    episodes=[Episode(plot=_plot(1), status="finalized",
                                      text="서윤은 왼손에 붕대를 감았다.\n\n등대는 바다 끝에 있었다."),
                              Episode(plot=_plot(2, ["a"]), status="written",
                                      text="서윤은 오른손을 다쳤다. 바람이 불었다. 서윤은 등대로 갔다.")])
        llm, judge = MockLLM(), MockJudge(contradicts=["오른손"])
        rep, st = pipeline.check_two_step(llm, judge, p, 2, hint={"plants": ["서윤은 오른손을 다쳤다."]})
        self.assertEqual(st["claims"], 3)
        self.assertEqual(st["flagged"], 1)
        self.assertEqual([j["flagged"] for j in st["judged"]], [True, False, False])
        self.assertEqual(len(rep.issues), 1)
        self.assertGreater(st["verdict_tokens"], 0)
        ev = prompts.claim_evidence(p, 2, pipeline.ClaimSet.model_validate({"claims": [{"quote": "서윤은 왼손", "claim": "서윤 왼손"}]}).claims[0],
                                    context.PassageIndex(p, 2))
        self.assertIn("[1화 발췌]", ev)  # 직전 화도 원문 단락으로 찾는다
        self.assertIn("서윤은 왼손을 다쳤다", ev)  # 겹치는 확정 사실
        self.assertIn("[인물 설정]", ev)

    def test_claim_evidence_brings_setting_lines_with_counts(self):
        p = Project(meta=Meta(title="t", form="serial"),
                    characters=[Character(id="a", name="서윤", role="주인공", speech_style="존댓말",
                                          background="서윤은 사흘 동안 앓아누웠다. 고향은 바닷가다.")],
                    episodes=[Episode(plot=_plot(1, ["a"]), status="written", text="서윤은 일주일 동안 앓았다.")])
        p.world.rules = ["마법은 해가 진 뒤에만 쓸 수 있다"]
        claim = pipeline.ClaimSet.model_validate({"claims": [{"quote": "서윤은 일주일 동안 앓았다.", "claim": "서윤이 일주일 동안 앓았다"}]}).claims[0]
        ev = prompts.claim_evidence(p, 1, claim, context.PassageIndex(p, 1))
        self.assertIn("[작품 설정]", ev)
        self.assertIn("서윤 배경: 서윤은 사흘 동안 앓아누웠다.", ev)
        self.assertNotIn("마법은", ev)  # 겹치지 않는 설정 줄은 넣지 않는다
        self.assertTrue(context.has_count("일주일 동안") and context.has_count("열일곱 살") and not context.has_count("바닷가"))
        # 셈이 있는 진술이면 셈이 있는 줄을 앞세운다
        self.assertEqual(context.related_lines(["서윤은 바닷가에서 자랐다", "서윤은 사흘 앓았다"], "서윤은 일주일", 20),
                         ["서윤은 사흘 앓았다"])
        self.assertIn("기간과 횟수", prompts.claims_prompt(p, 1))
        self.assertIn("사실 하나만", prompts.claims_prompt(p, 1))

    def test_two_step_without_flags_skips_verdict(self):
        p = Project(meta=Meta(title="t"), episodes=[Episode(plot=_plot(1), status="written",
                                                            text="바람이 불었다. 비가 왔다.")])
        rep, st = pipeline.check_two_step(MockLLM(), MockJudge(), p, 1)
        self.assertEqual(rep.issues, [])
        self.assertEqual((st["flagged"], st["verdict_tokens"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
