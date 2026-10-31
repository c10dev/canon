"""Claude 백엔드 테스트: 구독 로그인(Claude Code CLI)은 가짜 claude 실행 파일로, API 키 쪽은 가짜 클라이언트로 확인한다.

    python -m unittest
"""
import json
import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ["CANON_LLM"] = "mock"
os.environ["CANON_HOME"] = tempfile.mkdtemp()

from canon import claude, settings, usage  # noqa: E402
from canon.llm import SchemaMismatch, get_llm  # noqa: E402
from canon.schema import NameOptions  # noqa: E402

FAKE = textwrap.dedent('''\
    #!{python}
    """가짜 claude. FAKE_CLAUDE_DIR 의 replies.json 을 차례로 내고, 부른 모양을 calls.jsonl 에 남긴다."""
    import json, os, sys
    d = os.environ["FAKE_CLAUDE_DIR"]
    args = sys.argv[1:]
    if args == ["--help"]:
        print(open(os.path.join(d, "help.txt")).read() if os.path.exists(os.path.join(d, "help.txt")) else
              "--safe-mode --tools <tools...> --strict-mcp-config --no-session-persistence --json-schema <schema>")
        sys.exit(0)
    if args == ["--version"]:
        print("9.9.9 (Claude Code)")
        sys.exit(0)
    if args[:2] == ["auth", "status"]:
        p = os.path.join(d, "auth.json")
        print(open(p).read() if os.path.exists(p) else json.dumps({{"loggedIn": True, "authMethod": "claude.ai"}}))
        sys.exit(0)
    stdin = sys.stdin.read()
    env = {{k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_DISABLE_CLAUDE_MDS", "CLAUDE_CODE_OAUTH_TOKEN")}}
    with open(os.path.join(d, "calls.jsonl"), "a") as f:
        f.write(json.dumps({{"args": args, "stdin": stdin, "env": env, "cwd": os.getcwd()}}, ensure_ascii=False) + "\\n")
    p = os.path.join(d, "replies.json")
    replies = json.load(open(p)) if os.path.exists(p) else []
    reply = replies.pop(0) if replies else {{"result": "바다가 울었다."}}
    json.dump(replies, open(p, "w"))
    out = {{"type": "result", "subtype": "success", "is_error": False, "result": "",
           "usage": {{"input_tokens": 10, "cache_creation_input_tokens": 1500, "cache_read_input_tokens": 20,
                     "output_tokens": 30}},
           "modelUsage": {{"claude-test-model": {{"outputTokens": 30}}}}}}
    out.update(reply)
    print(json.dumps(out, ensure_ascii=False))
''')


class ClaudeCodeTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        exe = self.dir / "claude"
        exe.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        claude._probe.cache_clear()
        self.env = mock.patch.dict(os.environ, {
            "FAKE_CLAUDE_DIR": str(self.dir), "CANON_CLAUDE_BIN": str(exe), "CANON_CONFIG": str(self.dir / "config.json"),
            "CANON_USAGE": str(self.dir / "usage.jsonl"), "ANTHROPIC_API_KEY": "sk-ant-should-not-pass"})
        self.env.start()
        os.environ.pop("CANON_CLAUDE_MODEL", None)

    def tearDown(self):
        self.env.stop()

    def replies(self, *items):
        (self.dir / "replies.json").write_text(json.dumps(list(items), ensure_ascii=False), encoding="utf-8")

    def calls(self):
        path = self.dir / "calls.jsonl"
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def test_text_runs_cli_without_tools_or_api_key(self):
        llm = claude.ClaudeCodeLLM(model="sonnet")
        self.assertEqual(llm.text("시스템 지시", "등대를 써라"), "바다가 울었다.")
        call = self.calls()[0]
        args = call["args"]
        self.assertEqual(args[0], "-p")
        self.assertEqual(args[args.index("--system-prompt") + 1], "시스템 지시")
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertEqual(args[args.index("--model") + 1], "sonnet")
        for f in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
            self.assertIn(f, args)
        self.assertNotIn("--json-schema", args)
        self.assertEqual(call["stdin"], "등대를 써라")  # 긴 프롬프트도 인자 길이 한도에 걸리지 않게 표준 입력으로
        self.assertIsNone(call["env"]["ANTHROPIC_API_KEY"])  # 키가 있으면 구독 대신 키로 과금된다
        self.assertEqual(call["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"], "1")
        self.assertNotEqual(Path(call["cwd"]).resolve(), Path.cwd().resolve())  # 저장소의 CLAUDE.md, 훅을 읽지 않는 빈 폴더
        self.assertEqual(llm.model, "claude-test-model")
        row = usage.read()[-1]
        self.assertEqual((row["backend"], row["in"], row["out"], row["cached"]), ("claude", 1530, 30, 20))
        self.assertEqual(usage.row_cost(row, usage.prices())[0], 0.0)  # 구독은 요금제에 포함

    def test_json_schema_and_repair(self):
        good = {"options": [{"name": "정하윤", "reason": "부드럽다"}]}
        self.replies({"structured_output": {"options": "이름들"}}, {"structured_output": good})
        llm = claude.ClaudeCodeLLM()
        out = llm.json("작명가", "이름 후보", NameOptions)
        self.assertEqual(out.options[0].name, "정하윤")
        self.assertEqual(llm.last_attempts, 2)
        first, second = self.calls()
        self.assertNotIn("--model", first["args"])  # 비우면 Claude Code 기본 모델
        schema = json.loads(first["args"][first["args"].index("--json-schema") + 1])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], ["options"])
        self.assertIn("형식과 맞지 않았습니다", second["stdin"])
        self.assertTrue(second["stdin"].startswith("이름 후보"))

    def test_json_keeps_note_and_refusal(self):
        self.replies({"structured_output": {"options": []}, "result": "이 요청에는 이름을 내지 않을게요."},
                     {"stop_reason": "refusal", "structured_output": {"options": []}})
        llm = claude.ClaudeCodeLLM()
        self.assertEqual(llm.json("s", "p", NameOptions).options, [])
        self.assertEqual(llm.last_note, "이 요청에는 이름을 내지 않을게요.")  # 빈 결과의 이유를 화면에 보인다
        with self.assertRaisesRegex(claude.ClaudeCodeError, "거절"):
            llm.json("s", "p", NameOptions)
        self.assertEqual(llm.last_note, "")

    def test_json_gives_up_after_two(self):
        self.replies({"structured_output": {"options": 1}}, {"structured_output": {"options": 2}})
        with self.assertRaises(SchemaMismatch):
            claude.ClaudeCodeLLM().json("s", "p", NameOptions)

    def test_login_and_limit_errors(self):
        self.replies({"is_error": True, "subtype": "success", "result": "Not logged in · Please run /login"},
                     {"is_error": True, "result": "Claude AI usage limit reached|1792830000"})
        llm = claude.ClaudeCodeLLM()
        with self.assertRaisesRegex(claude.ClaudeCodeError, "claude auth login"):
            llm.text("s", "p")
        with self.assertRaisesRegex(claude.ClaudeCodeError, "사용 한도"):
            llm.text("s", "p")
        self.assertFalse(usage.read()[-1]["ok"])

    def test_old_cli_without_json_schema(self):
        (self.dir / "help.txt").write_text("--tools <tools...>", encoding="utf-8")
        llm = claude.ClaudeCodeLLM()
        self.assertEqual(llm.text("s", "p"), "바다가 울었다.")
        self.assertNotIn("--safe-mode", self.calls()[0]["args"])
        with self.assertRaisesRegex(claude.ClaudeCodeError, "claude update"):
            llm.json("s", "p", NameOptions)

    def test_cli_without_tools_flag_is_not_called(self):
        # 도구를 끌 수 없으면 소설 글을 넘기지 않는다 (옛 버전이거나 --help 를 읽지 못한 때)
        (self.dir / "help.txt").write_text("--json-schema <schema>", encoding="utf-8")
        with self.assertRaisesRegex(claude.ClaudeCodeError, "--tools"):
            claude.ClaudeCodeLLM().text("s", "p")
        self.assertEqual(self.calls(), [])

    def test_flags_reread_after_update(self):
        # claude update 는 같은 링크가 새 파일을 가리키게 바꾼다. 서버를 다시 켜지 않아도 새 옵션을 읽는다
        exe, new, link = self.dir / "claude", self.dir / "claude-new", self.dir / "claude-link"
        new.write_bytes(exe.read_bytes())
        new.chmod(exe.stat().st_mode)
        link.symlink_to(exe)
        (self.dir / "help.txt").write_text("--tools <tools...>", encoding="utf-8")
        self.assertNotIn("--json-schema", claude._flags(str(link)))
        (self.dir / "help.txt").unlink()
        link.unlink()
        link.symlink_to(new)
        self.assertIn("--json-schema", claude._flags(str(link)))

    def test_long_help_is_read_whole(self):
        (self.dir / "help.txt").write_text("x" * 30000 + "\n--json-schema <schema>", encoding="utf-8")
        self.assertIn("--json-schema", claude._flags(str(self.dir / "claude")))

    def test_status(self):
        st = claude.status()
        self.assertTrue(st["installed"] and st["logged_in"])
        self.assertEqual(st["version"], "9.9.9 (Claude Code)")
        self.assertTrue(st["api_key_ignored"])
        (self.dir / "auth.json").write_text(json.dumps({"loggedIn": False, "secretToken": "x"}), encoding="utf-8")
        st = claude.status()
        self.assertFalse(st["logged_in"])
        self.assertIn("claude auth login", st["message"])
        self.assertNotIn("secretToken", json.dumps(st))  # 화면에는 정해진 칸만 내보낸다
        with self.assertRaisesRegex(claude.ClaudeCodeError, "claude auth login"):
            claude.ClaudeCodeLLM().check()
        (self.dir / "auth.json").write_text(json.dumps({"loggedIn": True, "authMethod": "api_key"}), encoding="utf-8")
        self.assertEqual(claude.status()["reason"], "metered")
        with mock.patch.dict(os.environ, {"CANON_CLAUDE_BIN": str(self.dir / "없음")}):
            st = claude.status()
            self.assertFalse(st["installed"])
            with self.assertRaisesRegex(claude.ClaudeCodeError, "설치"):
                claude.ClaudeCodeLLM().text("s", "p")

    def test_settings_route_stages(self):
        with mock.patch.dict(os.environ, {"CANON_LLM": "gemini", "CANON_LLM_WRITE": "claude", "CANON_CLAUDE_MODEL": "opus"}):
            llm = get_llm("write")
            self.assertIsInstance(llm, claude.ClaudeCodeLLM)
            self.assertEqual(llm.requested, "opus")
            pub = settings.public()
            self.assertEqual(pub["stages"]["write"]["provider"], "claude")
            self.assertEqual(pub["stages"]["revise"]["provider"], "claude")  # 부분 수정은 본문 쓰기를 따른다
            self.assertEqual(pub["anthropic_key_source"], "env")
            self.assertNotIn("should-not-pass", json.dumps(pub))
        settings.update(anthropic_api_key="sk-ant-file-1234", claude_model="sonnet")
        os.environ.pop("ANTHROPIC_API_KEY")
        self.assertEqual(settings.anthropic_key(), ("sk-ant-file-1234", "file"))
        self.assertEqual(settings.public()["anthropic_key_hint"], "…1234")
        settings.update(clear_anthropic_key=True)
        self.assertEqual(settings.anthropic_key()[1], "default")


class StrictSchemaTest(unittest.TestCase):
    def test_keeps_property_named_title(self):
        from pydantic import BaseModel, Field

        class Inner(BaseModel):
            title: str = Field("", description="제목")
            score: int = Field(0, ge=0, le=10)

        class Outer(BaseModel):
            items: list[Inner] = []

        s = claude.strict_schema(Outer)
        inner = s["properties"]["items"]["items"]
        self.assertEqual(set(inner["properties"]), {"title", "score"})
        self.assertEqual(inner["required"], ["title", "score"])
        self.assertIs(inner["additionalProperties"], False)
        self.assertNotIn("minimum", json.dumps(s))
        self.assertNotIn("$defs", s)


class FakeStream:
    def __init__(self, msg, log, req):
        self.msg = msg
        log.append(req)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


def _msg(text, stop="end_turn"):
    u = SimpleNamespace(input_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=0, output_tokens=1000)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop, usage=u)


@unittest.skipUnless(__import__("importlib").util.find_spec("anthropic"), "anthropic 패키지 없음")
class ClaudeAPITest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"CANON_CONFIG": str(self.dir / "c.json"),
                                                "CANON_USAGE": str(self.dir / "u.jsonl"), "ANTHROPIC_API_KEY": "sk-ant-test"})
        self.env.start()
        os.environ.pop("CANON_CLAUDE_MODEL", None)

    def tearDown(self):
        self.env.stop()

    def make(self, *msgs, model=None):
        llm = claude.ClaudeAPILLM(model=model)
        self.reqs, queue = [], list(msgs)
        llm.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
            stream=lambda **req: FakeStream(queue.pop(0), self.reqs, req))))
        return llm

    def test_json_with_structured_output_and_cost(self):
        llm = self.make(_msg('{"options": "x"}'), _msg('{"options": [{"name": "윤채린", "reason": "맑다"}]}'))
        self.assertEqual(llm.model, claude.DEFAULT_API_MODEL)
        out = llm.json("s", "p", NameOptions)
        self.assertEqual(out.options[0].name, "윤채린")
        req = self.reqs[0]
        self.assertEqual(req["output_config"]["format"]["type"], "json_schema")
        self.assertFalse(req["output_config"]["format"]["schema"]["additionalProperties"])
        self.assertEqual(req["fallbacks"], "default")
        self.assertNotIn("temperature", req)
        rows = usage.read()
        self.assertEqual([r["backend"] for r in rows], ["claude-api", "claude-api"])
        cost = usage.row_cost(rows[-1], usage.prices())[0]
        self.assertAlmostEqual(cost, (100 * 4 + 1000 * 20) / 1e6)

    def test_refusal_and_haiku_without_fallback(self):
        llm = self.make(_msg("", "refusal"), model="claude-haiku-5-5")
        with self.assertRaisesRegex(RuntimeError, "거절"):
            llm.text("s", "p")
        self.assertNotIn("fallbacks", self.reqs[0])
        self.assertFalse(usage.read()[-1]["ok"])

    def test_cache_mark_on_prefix_shared_with_previous_request(self):
        claude._SEEN.clear()
        head = "# 작품 정보\n" + "가" * 3000
        llm = self.make(_msg("1화"), _msg("2화"), _msg("3화"), _msg("다른 지시"))
        llm.text("쓰기", head + "\n\n# 이번 화 플롯\n1화")
        llm.text("쓰기", head + "\n\n# 이번 화 플롯\n2화")
        llm.text("쓰기", head + "\n\n# 이번 화 플롯\n3화")
        llm.text("검수", head + "\n\n# 검수 대상\n3화")
        first, second, third, other = (r["messages"][0]["content"] for r in self.reqs)
        self.assertIsInstance(first, str)  # 처음 보는 종류는 겹칠 앞 요청이 없다
        mark = {"type": "text", "text": head, "cache_control": {"type": "ephemeral"}}
        self.assertEqual(second, [mark, {"type": "text", "text": "\n\n# 이번 화 플롯\n2화"}])
        self.assertEqual(third[0], mark)  # 같은 자리에 표시해야 앞 요청이 쓴 캐시를 읽는다
        self.assertEqual("".join(b["text"] for b in third), head + "\n\n# 이번 화 플롯\n3화")
        self.assertIsInstance(other, str)  # 시스템 프롬프트가 다르면 따로 센다
        self.assertEqual(claude.cache_blocks(("k",), "짧은 글\n\n끝"), "짧은 글\n\n끝")

    def test_stage_cost_uses_claude_price(self):
        self.assertAlmostEqual(usage.stage_cost("claude-api", "gemini-4-argon", 1e6, 0), 4.0)
        self.assertEqual(usage.stage_cost("claude", "", 1e6, 1e6), 0.0)

    def test_missing_key(self):
        os.environ.pop("ANTHROPIC_API_KEY")
        with self.assertRaisesRegex(RuntimeError, "Anthropic API 키"):
            claude.ClaudeAPILLM()


if __name__ == "__main__":
    unittest.main()
