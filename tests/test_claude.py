"""Claude 백엔드 테스트: 구독 로그인(Claude Code CLI)은 가짜 claude 실행 파일로, API 키 쪽은 가짜 클라이언트로 확인한다.

    python -m unittest
"""
import json
import os
import stat
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ["CANON_LLM"] = "mock"
os.environ["CANON_HOME"] = tempfile.mkdtemp()

from canon import cancel, claude, settings, usage  # noqa: E402
from canon.llm import PREFIX_HINT, SchemaMismatch, get_llm, out_cap, wait_cap, with_note  # noqa: E402
from canon.schema import NameOptions  # noqa: E402

FAKE = textwrap.dedent('''\
    #!{python}
    """가짜 claude. FAKE_CLAUDE_DIR 의 replies.json 을 차례로 내고, 부른 모양을 calls.jsonl 에 남긴다."""
    import json, os, sys, time
    d = os.environ["FAKE_CLAUDE_DIR"]
    args = sys.argv[1:]
    if args == ["--help"]:
        print(open(os.path.join(d, "help.txt")).read() if os.path.exists(os.path.join(d, "help.txt")) else
              "--safe-mode --tools <tools...> --strict-mcp-config --no-session-persistence --json-schema <schema>")
        sys.exit(0)
    if args == ["--version"]:
        print("9.9.9 (Claude Code)")
        sys.exit(0)
    if args[:2] in (["auth", "login"], ["auth", "logout"]):
        with open(os.path.join(d, "auth_calls.jsonl"), "a") as f:
            f.write(json.dumps({{"args": args, "dir": os.environ.get("CLAUDE_CONFIG_DIR"),
                                 "stdin_tty": sys.stdin.isatty()}}) + "\\n")
        sys.exit(0)
    if args[:2] == ["auth", "status"]:
        p = os.path.join(d, "auth.json")
        print(open(p).read() if os.path.exists(p) else json.dumps({{"loggedIn": True, "authMethod": "claude.ai"}}))
        sys.exit(0)
    stdin = sys.stdin.read()
    env = {{k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_DISABLE_CLAUDE_MDS", "CLAUDE_CODE_OAUTH_TOKEN",
                                       "CLAUDE_CONFIG_DIR")}}
    system = open(args[args.index("--system-prompt-file") + 1], encoding="utf-8").read() if "--system-prompt-file" in args else None
    with open(os.path.join(d, "calls.jsonl"), "a") as f:
        f.write(json.dumps({{"args": args, "stdin": stdin, "env": env, "cwd": os.getcwd(), "system_file": system}},
                           ensure_ascii=False) + "\\n")
    p = os.path.join(d, "replies.json")
    replies = json.load(open(p)) if os.path.exists(p) else []
    reply = replies.pop(0) if replies else {{"result": "바다가 울었다."}}
    json.dump(replies, open(p, "w"))
    time.sleep(reply.pop("sleep", 0))
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
        self.assertEqual(call["stdin"], with_note("등대를 써라"))  # 긴 프롬프트도 인자 길이 한도에 걸리지 않게 표준 입력으로
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

    def test_wait_cap_ends_slow_call(self):
        self.replies({"sleep": 10})
        t = time.monotonic()
        with wait_cap(0.5), self.assertRaisesRegex(claude.ClaudeCodeError, "0.5초"):
            claude.ClaudeCodeLLM().text("s", "p")  # 플롯 대화 한 단계의 한도가 Claude Code 에도 걸린다
        self.assertLess(time.monotonic() - t, 5)
        self.assertFalse(usage.read()[-1]["ok"])

    def test_stop_kills_running_call(self):
        self.replies({"sleep": 10})
        ev = threading.Event()
        tok = cancel.current.set(ev)
        try:
            threading.Timer(0.5, ev.set).start()
            t = time.monotonic()
            with self.assertRaises(cancel.Cancelled):
                claude.ClaudeCodeLLM().text("s", "p")
            self.assertLess(time.monotonic() - t, 5)  # 하위 프로세스를 끝내고 바로 돌아온다
            n = len(self.calls())
            with self.assertRaises(cancel.Cancelled):
                claude.ClaudeCodeLLM().text("s", "p")  # 멈춘 작업은 다음 호출을 보내지 않는다
            self.assertEqual(len(self.calls()), n)
        finally:
            cancel.current.reset(tok)

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

    def test_shared_prefix_goes_to_system_prompt_file(self):
        # Claude Code 는 시스템 프롬프트 끝에만 캐시 표시를 달아, 겹치는 앞부분을 시스템 프롬프트로 옮겨야 캐시에서 읽는다
        (self.dir / "help.txt").write_text("--safe-mode --tools <t> --strict-mcp-config --no-session-persistence "
                                           "--json-schema <s> via: --system-prompt[-file], --append-system-prompt[-file]",
                                           encoding="utf-8")
        claude._SEEN.clear()
        claude._WARM.clear()
        head = "# 작품 정보\n" + "가" * 3000
        llm = claude.ClaudeCodeLLM()
        for n in (1, 2, 3):
            llm.text("쓰기", f"{head}\n\n# 이번 화 플롯\n{n}화")
        llm.text("검수", head + "\n\n# 검수 대상\n3화")
        first, second, third, other = self.calls()
        self.assertEqual(first["args"][first["args"].index("--system-prompt") + 1], "쓰기")  # 겹칠 앞 요청이 없다
        self.assertEqual(first["stdin"], with_note(f"{head}\n\n# 이번 화 플롯\n1화"))
        for call, n in ((second, 2), (third, 3)):
            self.assertNotIn("--system-prompt", call["args"])
            self.assertEqual(call["system_file"], f"쓰기\n\n{head}")  # 같은 시스템 프롬프트라야 앞 호출이 쓴 캐시를 읽는다
            self.assertEqual(call["stdin"], with_note(f"# 이번 화 플롯\n{n}화"))
        self.assertIsNone(other["system_file"])  # 시스템 프롬프트가 다르면 따로 센다
        self.assertEqual(usage.read()[-2]["chars"], len(f"{head}\n\n# 이번 화 플롯\n3화"))  # 기록은 원래 프롬프트 기준

        # 형식 고치기 재시도는 첫 시도 뒤에 덧붙이므로 첫 시도와 같은 시스템 프롬프트로 보낸다
        self.replies({"structured_output": {"options": []}}, {"structured_output": {"wrong": 1}},
                     {"structured_output": {"options": [], "reason": "x"}})
        llm.json("쓰기", head + "\n\n# 이번 화 플롯\n3화", NameOptions)  # 구조화 출력은 스키마마다 따로 센다
        try:
            llm.json("쓰기", head + "\n\n# 이번 화 플롯\n4화", NameOptions)
        except SchemaMismatch:
            pass
        retry = self.calls()[-1]
        self.assertEqual(retry["system_file"], f"쓰기\n\n{head}")
        self.assertTrue(retry["stdin"].startswith("# 이번 화 플롯\n4화"))

        claude._SEEN.clear()
        (self.dir / "help.txt").write_text("--safe-mode --tools <t> --json-schema <s>", encoding="utf-8")
        claude._probe.cache_clear()
        llm.text("쓰기", head + "\n\n# 이번 화 플롯\n1화")
        llm.text("쓰기", head + "\n\n# 이번 화 플롯\n2화")
        self.assertIsNone(self.calls()[-1]["system_file"])  # 이 옵션을 모르는 버전은 예전처럼 사용자 메시지에 둔다
        self.assertEqual(self.calls()[-1]["stdin"], with_note(head + "\n\n# 이번 화 플롯\n2화"))

    def test_prefix_hint_moves_prefix_on_first_call(self):
        # 부른 쪽이 공통 자료의 끝(hint prefix_chars)을 알려 주면 직전 요청이 없어도 첫 호출부터 시스템 프롬프트로 옮긴다
        (self.dir / "help.txt").write_text("--safe-mode --tools <t> --strict-mcp-config --no-session-persistence "
                                           "--json-schema <s> via: --system-prompt[-file], --append-system-prompt[-file]",
                                           encoding="utf-8")
        claude._SEEN.clear()
        claude._WARM.clear()
        material = "# 작품 정보\n" + "가" * 3000 + "\n\n# 3화 본문 (검수 대상)\n" + "나" * 500
        llm = claude.ClaudeCodeLLM()
        out = {"structured_output": {"options": [{"name": "윤채린", "reason": "맑다"}]}}
        self.replies(out, out, out, out)
        llm.json("고침", f"{material}\n\n# 고칠 지적\n- f1", NameOptions, hint={"episode": 3, PREFIX_HINT: len(material)})
        llm.json("고침", f"{material}\n\n# 고칠 지적\n- f2", NameOptions, hint={PREFIX_HINT: len(material)})
        first, second = self.calls()
        self.assertNotIn("--system-prompt", first["args"])
        self.assertEqual(first["system_file"], f"고침\n\n{material}")  # 앞 요청이 없어도 자료 끝에서 옮긴다
        self.assertEqual(first["stdin"], with_note("# 고칠 지적\n- f1"))
        self.assertEqual(second["system_file"], first["system_file"])  # 둘째 호출은 첫 호출이 쓴 캐시를 읽는다
        # 경계가 단락 가운데면 그 앞 단락 경계로 맞추고, 앞부분이 너무 짧으면 옮기지 않는다
        llm.json("고침2", f"{material}\n\n# 고칠 지적\n- f3", NameOptions, hint={PREFIX_HINT: len(material) - 10})
        self.assertEqual(self.calls()[-1]["system_file"], "고침2\n\n# 작품 정보\n" + "가" * 3000)
        llm.json("고침3", "짧은 자료\n\n# 고칠 지적", NameOptions, hint={PREFIX_HINT: 5})
        self.assertIsNone(self.calls()[-1]["system_file"])

    def test_same_prefix_waits_for_first_writer(self):

        from canon import cancel

        claude._WARM.clear()
        claude._WRITING.clear()
        gate = ("cli", "", "S", 1, 1)
        first = claude._claim(gate)
        self.assertIsNotNone(first)  # 처음 보내는 호출이 캐시를 쓴다
        got = []
        t = threading.Thread(target=lambda: got.append(claude._claim(gate)))
        t.start()
        t.join(0.3)
        self.assertTrue(t.is_alive())  # 같은 앞부분 호출은 앞 호출이 끝나기를 기다린다
        claude._release(gate, first, True)
        t.join(5)
        self.assertEqual(got, [None])  # 앞 호출이 캐시에 넣었으니 읽기만 한다
        self.assertIsNone(claude._claim(gate))  # 캐시 유지 시간 안에는 기다리지 않는다

        failed = ("cli", "", "S", 2, 2)
        first = claude._claim(failed)
        t = threading.Thread(target=lambda: got.append(claude._claim(failed)))
        t.start()
        claude._release(failed, first, False)  # 모델까지 가지 못했으면 캐시에 없다
        t.join(5)
        self.assertIsInstance(got[-1], threading.Event)  # 기다리던 호출이 대신 쓴다
        claude._release(failed, got[-1], True)

        old = ("cli", "", "S", 4, 4)
        claude._release(old, claude._claim(old), True, time.time() - claude.CACHE_WARM_SECONDS - 1)
        self.assertIsNotNone(claude._claim(old))  # 캐시 유지 시간은 끝난 때가 아니라 보낸 때부터 센다

        with mock.patch.object(claude, "CACHE_PREFILL_SECONDS", 0.2):
            slow = ("cli", "", "S", 3, 3)
            claude._claim(slow)
            self.assertIsNone(claude._claim(slow))  # 앞 호출이 앞부분을 읽었을 즈음이면 끝나기 전이라도 보낸다
            stop = threading.Event()
            stop.set()
            busy = ("cli", "", "S", 5, 5)
            claude._claim(busy)
            tok = cancel.current.set(stop)
            try:
                with self.assertRaises(cancel.Cancelled):  # 기다리는 동안 작업 멈추기를 본다
                    claude._claim(busy)
            finally:
                cancel.current.reset(tok)

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

    def auth_calls(self):
        path = self.dir / "auth_calls.jsonl"
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def test_separate_config_dir(self):
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        self.assertEqual(settings.claude_config_dir(), ("", "default"))
        self.assertEqual(claude.login_command(), "claude auth login")
        st = claude.status()
        self.assertFalse(st["separate"])
        claude.ClaudeCodeLLM().text("s", "p")
        self.assertIsNone(self.calls()[-1]["env"]["CLAUDE_CONFIG_DIR"])  # 끄면 평소 Claude Code 로그인
        self.assertFalse(claude.logout()["ok"])  # 평소 로그인은 Canon 에서 끝내지 않는다
        self.assertEqual(self.auth_calls(), [])

        settings.update(claude_separate=True)
        want = str(self.dir / "claude-code")
        self.assertEqual(settings.claude_config_dir(), (want, "file"))
        self.assertEqual(settings.public()["claude_config_dir"], want)
        st = claude.status()
        self.assertTrue(st["separate"])
        self.assertIn(f"CLAUDE_CONFIG_DIR={want} claude auth login", st["login_command"])
        claude.ClaudeCodeLLM().text("s", "p")
        self.assertEqual(self.calls()[-1]["env"]["CLAUDE_CONFIG_DIR"], want)
        self.assertTrue(Path(want).is_dir())

        r = claude.start_login()
        self.assertTrue(r["started"])
        claude._login.wait(10)
        self.assertFalse(claude.login_running())
        self.assertEqual(self.auth_calls()[-1], {"args": ["auth", "login", "--claudeai"], "dir": want, "stdin_tty": False})
        self.assertTrue(claude.logout()["ok"])
        self.assertEqual(self.auth_calls()[-1]["args"], ["auth", "logout"])
        self.assertEqual(self.auth_calls()[-1]["dir"], want)

        with mock.patch.dict(os.environ, {"CANON_CLAUDE_CONFIG_DIR": str(self.dir / "env-dir")}):
            self.assertEqual(settings.claude_config_dir(), (str(self.dir / "env-dir"), "env"))
        settings.update(claude_separate=False)
        self.assertNotIn("claude_separate", json.loads((self.dir / "config.json").read_text()))
        self.assertEqual(settings.claude_config_dir()[0], "")

    def test_login_route_only_from_same_machine(self):
        from fastapi.testclient import TestClient
        from canon import web

        c = TestClient(web.app)  # 테스트 클라이언트의 주소는 testclient: 다른 컴퓨터로 본다
        r = c.post("/api/claude/login")
        self.assertEqual(r.status_code, 400)
        self.assertIn("claude setup-token", r.json()["detail"])
        self.assertEqual(self.auth_calls(), [])
        r = c.put("/api/config", json={"claude_separate": True})
        self.assertEqual(r.json()["claude_config_dir"], str(self.dir / "claude-code"))
        with mock.patch.object(web, "_same_machine", return_value=True):
            r = c.post("/api/claude/login")
        self.assertTrue(r.json()["ok"])
        claude._login.wait(10)
        self.assertEqual(self.auth_calls()[-1]["dir"], str(self.dir / "claude-code"))
        self.assertTrue(c.post("/api/claude/logout").json()["ok"])
        self.assertTrue(c.get("/api/claude/status").json()["separate"])
        c.put("/api/config", json={"claude_separate": False})

    def test_effort_flag_and_usage(self):
        (self.dir / "help.txt").write_text("--safe-mode --tools <t> --strict-mcp-config --no-session-persistence "
                                           "--json-schema <s> --effort <level>", encoding="utf-8")
        llm = claude.ClaudeCodeLLM(effort="high")
        llm.text("s", "p")
        args = self.calls()[-1]["args"]
        self.assertEqual(args[args.index("--effort") + 1], "high")
        self.assertEqual(usage.read()[-1]["effort"], "high")
        claude.ClaudeCodeLLM().text("s", "p")  # 비우면 Claude Code 기본 강도
        self.assertNotIn("--effort", self.calls()[-1]["args"])
        self.assertNotIn("effort", usage.read()[-1])
        self.assertEqual(claude.ClaudeCodeLLM(effort="huge").effort, "")  # 모르는 값은 넘기지 않는다

    def test_effort_skipped_on_old_cli(self):
        llm = claude.ClaudeCodeLLM(effort="low")  # 기본 가짜 --help 에는 --effort 가 없다
        llm.text("s", "p")
        self.assertNotIn("--effort", self.calls()[-1]["args"])
        self.assertNotIn("effort", usage.read()[-1])  # 넘기지 못한 강도는 기록하지 않는다

    def test_stage_effort_setting(self):
        with mock.patch.dict(os.environ, {"CANON_LLM": "gemini", "CANON_LLM_CHECK": "claude", "CANON_LLM_WRITE": "claude"}):
            self.assertEqual(get_llm("check").effort, "")
            settings.update(stage_efforts={"check": "XHigh", "write": "low"})
            self.assertEqual(settings.stage_effort("check"), ("xhigh", "file"))
            self.assertEqual(get_llm("check").effort, "xhigh")
            self.assertEqual(settings.stage_effort("revise"), ("low", "file"))  # 부분 수정은 본문 쓰기를 따른다
            pub = settings.public()
            self.assertEqual(pub["stages"]["check"]["effort"], "xhigh")
            self.assertEqual(pub["stage_effort_settings"], {"check": "xhigh", "write": "low"})
            self.assertEqual(pub["stages"]["plan"]["effort"], "")  # 계획 단계(Gemini)는 강도를 정하지 않았다
            with mock.patch.dict(os.environ, {"CANON_EFFORT_CHECK": "medium"}):
                self.assertEqual(settings.stage_effort("check"), ("medium", "env"))
                self.assertEqual(settings.public()["stages"]["check"]["effort_env"], "CANON_EFFORT_CHECK")
            with self.assertRaisesRegex(ValueError, "추론 강도"):
                settings.update(stage_efforts={"check": "huge"})
            settings.update(stage_efforts={"check": ""})
            self.assertEqual(settings.stage_effort("check"), ("", "default"))

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
    on_event = None  # 조각마다 부를 함수 (멈추기 시험)

    def __init__(self, msg, log, req):
        self.msg = msg
        log.append(req)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for _ in range(3):
            if self.on_event:
                self.on_event()
            yield SimpleNamespace(type="content_block_delta")

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

    def test_effort_in_output_config(self):
        llm = claude.ClaudeAPILLM(effort="max")
        self.reqs, queue = [], [_msg('{"options": [{"name": "윤채린", "reason": "맑다"}]}'), _msg("글")]
        llm.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
            stream=lambda **req: FakeStream(queue.pop(0), self.reqs, req))))
        llm.json("s", "p", NameOptions)
        self.assertEqual(self.reqs[0]["output_config"]["effort"], "max")
        self.assertEqual(self.reqs[0]["output_config"]["format"]["type"], "json_schema")
        llm.text("s", "p")
        self.assertEqual(self.reqs[1]["output_config"], {"effort": "max"})
        self.assertEqual(usage.read()[-1]["effort"], "max")
        plain = self.make(_msg("글"))
        plain.text("s", "p")
        self.assertNotIn("output_config", self.reqs[0])  # 비우면 모델 기본값 (Opus 5.5 는 medium)

    def test_out_cap_and_wait_cap_reach_request(self):
        llm = self.make(_msg("글"), _msg("글"), _msg("", "max_tokens"))
        llm.text("s", "p")
        self.assertEqual(self.reqs[0]["max_tokens"], claude.MAX_TOKENS)
        self.assertNotIn("timeout", self.reqs[0])
        with wait_cap(300), out_cap(16384):
            llm.text("s", "p")
            with self.assertRaisesRegex(RuntimeError, "16384 토큰"):
                llm.text("s", "p")
        self.assertEqual((self.reqs[1]["max_tokens"], self.reqs[1]["timeout"]), (16384, 300))

    def test_stop_before_and_during_stream(self):
        ev = threading.Event()
        tok = cancel.current.set(ev)
        try:
            llm = self.make(_msg("글"))
            FakeStream.on_event = ev.set
            with self.assertRaises(cancel.Cancelled):
                llm.text("s", "p")  # 스트림 조각 사이에 멈추면 끝까지 받지 않는다
            FakeStream.on_event = None
            with self.assertRaises(cancel.Cancelled):
                llm.text("s", "p")
            self.assertEqual(len(self.reqs), 1)  # 멈춘 뒤에는 요청을 보내지 않는다
        finally:
            FakeStream.on_event = None
            cancel.current.reset(tok)

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
        self.assertEqual(second, [mark, {"type": "text", "text": with_note("\n\n# 이번 화 플롯\n2화")}])
        self.assertEqual(third[0], mark)  # 같은 자리에 표시해야 앞 요청이 쓴 캐시를 읽는다
        self.assertEqual("".join(b["text"] for b in third), with_note(head + "\n\n# 이번 화 플롯\n3화"))
        self.assertIsInstance(other, str)  # 시스템 프롬프트가 다르면 따로 센다
        self.assertEqual(claude.cache_blocks(("k",), "짧은 글\n\n끝"), "짧은 글\n\n끝")

    def test_cache_mark_at_prefix_hint_on_first_request(self):
        # API 경로도 부른 쪽이 알려 준 경계에서 첫 요청부터 캐시 표시를 단다
        claude._SEEN.clear()
        material = "# 작품 정보\n" + "가" * 3000
        llm = self.make(_msg('{"options": []}'))
        llm.json("고침", material + "\n\n# 고칠 지적\n- f1", NameOptions, hint={PREFIX_HINT: len(material)})
        blocks = self.reqs[0]["messages"][0]["content"]
        self.assertEqual(blocks[0], {"type": "text", "text": material, "cache_control": {"type": "ephemeral"}})
        self.assertEqual(blocks[1]["text"], with_note("\n\n# 고칠 지적\n- f1"))

    def test_stage_cost_uses_claude_price(self):
        self.assertAlmostEqual(usage.stage_cost("claude-api", "gemini-4-argon", 1e6, 0), 4.0)
        self.assertEqual(usage.stage_cost("claude", "", 1e6, 1e6), 0.0)

    def test_missing_key(self):
        os.environ.pop("ANTHROPIC_API_KEY")
        with self.assertRaisesRegex(RuntimeError, "Anthropic API 키"):
            claude.ClaudeAPILLM()


if __name__ == "__main__":
    unittest.main()
