"""Claude 백엔드 두 가지: 구독 로그인(설치된 Claude Code) 과 Anthropic API 키.

claude (구독 로그인)
  이 컴퓨터에 설치하고 로그인한 Claude Code 를 `claude -p` 로 부른다. 로그인은 Claude Code 가
  Anthropic 의 로그인 화면으로 직접 하고(`claude auth login`), Canon 은 계정 정보나 토큰을 읽지도
  저장하지도 않는다. Anthropic 은 다른 앱이 Claude 계정 로그인을 제공하거나 Pro/Max 토큰을 받아
  대신 호출하는 것을 허용하지 않기 때문이다 (Claude Code 문서 'Legal and compliance' 의
  Authentication and credential use). 그래서 Canon 화면에는 로그인 칸이 없고 상태 확인과 안내만 있다.
  서버처럼 브라우저가 없는 곳은 `claude setup-token` 으로 받은 토큰을 Canon 이 아니라 서버 환경의
  CLAUDE_CODE_OAUTH_TOKEN 에 둔다.
  Canon 전용 로그인: 설정의 claude_separate(또는 CANON_CLAUDE_CONFIG_DIR)를 켜면 Canon 이 부르는 claude 에
  CLAUDE_CONFIG_DIR 로 Canon 전용 폴더를 넘긴다. 그러면 평소 쓰는 Claude Code 와 다른 계정으로 로그인할 수 있다.
  설정 화면의 '로그인 시작'은 그 폴더로 `claude auth login` 을 띄울 뿐이고, 로그인 화면 · 코드 · 토큰은
  Claude Code 와 Anthropic 이 다룬다. Canon 은 출력도 읽지 않는다. 브라우저가 Canon 을 실행하는 컴퓨터에서
  열리므로 같은 컴퓨터에서 접속할 때만 받는다 (web.py). 구독 한도는 평범한 개인 사용을 전제로 하므로 긴 자동 집필은
  API 키 쪽이 맞다.

claude-api (API 키)
  Claude Console 에서 받은 API 키로 Messages API 를 부른다. 종량제로 사용량 화면에 비용이 잡힌다.

설정 (환경 변수가 설정 파일보다 우선):
  CANON_CLAUDE_MODEL  두 백엔드의 기본 모델. 비우면 구독은 Claude Code 기본 모델, API 는 DEFAULT_API_MODEL
  CANON_CLAUDE_BIN    claude 실행 파일 경로 (PATH 에 없을 때)
  CANON_CLAUDE_CONFIG_DIR  Canon 전용 Claude Code 설정 폴더 (settings.claude_config_dir)
  ANTHROPIC_API_KEY   claude-api 의 키. 구독 호출에는 넘기지 않는다 (넘기면 Claude Code 가 키로 과금한다)
  CANON_CLAUDE_TIMEOUT  한 번 호출의 제한 시간(초, 기본 900). llm.wait_cap 안이면 그 값을 넘지 않는다
  CANON_EFFORT_<단계>   단계별 추론 강도 (settings.stage_effort). 구독은 --effort, API 는 output_config.effort 로 넘긴다.
                      비우면 모델 기본값 (Opus 5.5 는 medium, Sonnet 5.5 는 high. 구독은 Claude Code 설정을 따른다)
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from . import cancel, usage

T = TypeVar("T", bound=BaseModel)

DEFAULT_API_MODEL = "claude-opus-5-5"
# 설정 화면 모델 칸의 추천. 구독(Claude Code)은 별칭도 받는다.
CLI_MODELS = ["opus", "sonnet", "haiku", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
# 안전 분류기가 거절하면 다른 모델로 이어 받는 서버 쪽 대체. 이 모델들만 받는다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
MAX_TOKENS = 64000  # 본문 한 화와 생각을 넉넉히. 스트리밍으로 받아 시간 초과를 피한다
STOP_POLL = 0.25  # Claude Code 를 기다리며 멈추기 신호를 보는 간격(초)

LOGIN_HINT = ("Claude Code 에 로그인돼 있지 않아요. 이 컴퓨터의 터미널에서 `claude auth login` 을 실행해 "
              "Anthropic 로그인 화면에서 구독 계정으로 로그인하세요. 서버라면 `claude setup-token` 으로 받은 토큰을 "
              "서버 환경 변수 CLAUDE_CODE_OAUTH_TOKEN 에 두세요.")
INSTALL_HINT = ("Claude Code(claude 명령)를 찾지 못했어요. https://code.claude.com/docs/en/setup 에서 설치한 뒤 "
                "`claude auth login` 으로 로그인하세요. PATH 밖에 있으면 설정에 실행 파일 경로를 적으세요.")
LIMIT_HINT = "Claude 구독 사용 한도에 걸렸어요. 한도가 풀린 뒤 다시 하거나 이 단계를 다른 백엔드로 돌리세요."
# 상태 화면에 보여 줄 칸. 토큰 같은 다른 값은 내보내지 않는다.
STATUS_FIELDS = ("loggedIn", "authMethod", "apiProvider", "email", "orgName", "organizationName", "subscriptionType")


# ---------- JSON 스키마 ----------

_DROP = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength", "maxLength",
         "pattern", "minItems", "maxItems", "uniqueItems", "default", "title"}


def strict_schema(schema: type[BaseModel]) -> dict:
    """Claude 구조화 출력용 스키마. $ref 를 풀고, 모든 칸을 required 로, 객체마다 additionalProperties: false 를
    붙이고, Claude 가 받지 않는 제약(minimum, maxLength 등)은 뺀다. 뺀 제약은 받은 뒤 pydantic 이 검사한다."""
    from .llm import _inline_refs

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(v) for v in node]
        if not isinstance(node, dict):
            return node
        out = {}
        for k, v in node.items():
            if k in _DROP:
                continue
            out[k] = {name: walk(s) for name, s in v.items()} if k == "properties" and isinstance(v, dict) else walk(v)
        if isinstance(out.get("properties"), dict):
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        elif out.get("type") == "object":
            out["additionalProperties"] = False
        return out

    return walk(_inline_refs(schema.model_json_schema()))


def json_instruction(schema: type[BaseModel]) -> str:
    """구조화 출력 없이 JSON 을 받을 때 요청 끝에 붙이는 형식 지시. 받은 글은 _parse 가 검증한다."""
    from .llm import _inline_refs

    js = json.dumps(_inline_refs(schema.model_json_schema()), ensure_ascii=False, separators=(",", ":"))
    return ("\n\n응답 형식: 아래 JSON 스키마를 따르는 JSON 객체 하나만 냅니다. 앞뒤에 다른 글이나 코드 블록 표시를 붙이지 않습니다.\n"
            f"{js}")


def _parse(schema: type[T], raw: Any) -> T:
    if isinstance(raw, (dict, list)):
        return schema.model_validate(raw)
    from .llm import _validate

    return _validate(schema, raw)


# ---------- 구독 로그인: Claude Code ----------

def find_binary(path: str | None = None) -> str | None:
    """설정한 경로, PATH, 설치 프로그램이 두는 흔한 자리 순서로 claude 실행 파일을 찾는다."""
    from . import settings

    want = path or settings.claude_bin()[0]
    if want:
        p = Path(want).expanduser()
        return str(p) if p.exists() else shutil.which(want)
    found = shutil.which("claude")
    if found:
        return found
    for cand in ("~/.local/bin/claude", "~/.claude/local/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        p = Path(cand).expanduser()
        if p.exists():
            return str(p)
    return None


def config_dir() -> str:
    """Canon 전용 Claude Code 설정 폴더. 비우면 평소 Claude Code 로그인을 같이 쓴다 (settings.claude_config_dir)."""
    from . import settings

    return settings.claude_config_dir()[0]


def login_command() -> str:
    """사용자가 터미널에서 칠 로그인 명령. 전용 폴더를 쓰면 그 폴더를 앞에 붙인다."""
    d = config_dir()
    return f"CLAUDE_CONFIG_DIR={shlex.quote(d)} claude auth login" if d else "claude auth login"


def cache_1h() -> bool:
    """CANON_CLAUDE_CACHE_1H 가 켜져 있으면 프롬프트 캐시를 1시간으로 쓴다. 쓰기 값이 5분 캐시의 1.25배에서 2배로 오르므로
    한 시간 안에 같은 앞부분을 세 번 이상 읽을 때 이득이다. 기본은 끔이다. 끄면 child_env 가 5분 캐시를 강제한다
    (구독 로그인에서 Claude Code 는 스스로 1시간 캐시를 쓴다. 2026-11-05 서버 실측)."""
    return os.environ.get("CANON_CLAUDE_CACHE_1H", "").strip().lower() in ("1", "true", "yes", "on")


def child_env(extra: dict | None = None) -> dict:
    """claude 를 부를 때의 환경. API 키를 빼야 구독으로 호출한다 (-p 에서는 키가 있으면 늘 키를 쓴다).
    사용자 CLAUDE.md 와 자동 메모리는 소설 프롬프트에 섞이지 않게 끈다. CLAUDE_CODE_OAUTH_TOKEN 은 그대로 둔다.
    Canon 전용 폴더를 쓰면 CLAUDE_CONFIG_DIR 로 넘긴다 (없으면 만든다). extra 는 이 호출에만 더할 값이다."""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    if cache_1h():
        env["ENABLE_PROMPT_CACHING_1H"] = "1"  # Claude Code 가 구독 초과 사용 중에도 1시간 캐시를 쓰게 한다
        env.pop("FORCE_PROMPT_CACHING_5M", None)
    else:
        env["FORCE_PROMPT_CACHING_5M"] = "1"  # 구독 기본인 1시간 캐시는 쓰기 값이 2배다. Canon 의 캐시 읽기는 대부분 5분 안에 온다
    d = config_dir()
    if d:
        Path(d).mkdir(parents=True, exist_ok=True, mode=0o700)
        env["CLAUDE_CONFIG_DIR"] = d
    env.update(extra or {})
    return env


def _flags(binary: str) -> frozenset[str]:
    """이 버전이 아는 옵션. 오래된 버전에 없는 옵션을 넘기면 실행이 실패하므로 있는 것만 쓴다.
    `claude update` 는 링크가 가리키는 파일을 바꾸므로 실제 파일로 기억하고, 읽지 못한 결과는 기억하지 않는다."""
    try:
        return _probe(binary, os.path.realpath(binary))
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()


@lru_cache(maxsize=8)
def _probe(binary: str, real: str) -> frozenset[str]:
    out = _run([binary, "--help"], 30)
    text = out.stdout + out.stderr
    known = ("--safe-mode", "--tools", "--strict-mcp-config", "--no-session-persistence", "--json-schema", "--effort", "--settings")
    found = {f for f in known if f in text}
    if "--system-prompt-file" in text or "--system-prompt[-file]" in text:  # 2.1.x 는 옵션 목록에 따로 싣지 않는다
        found.add("--system-prompt-file")
    return frozenset(found)


def _run(args: list[str], timeout: float, stdin: str | None = None,
         stop: threading.Event | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    """args 를 실행하고 끝날 때까지 기다린다. timeout 초를 넘기면 하위 프로세스를 끝내고 TimeoutExpired 를 낸다.
    stop 이 서면(웹 작업의 멈추기) STOP_POLL 초 안에 하위 프로세스를 끝내고 cancel.Cancelled 를 낸다."""
    # 작업 폴더를 빈 임시 폴더로 둬서 Canon 저장소의 CLAUDE.md, 훅, MCP 설정을 읽지 않게 한다.
    # 출력은 파일로 받는다. 2.1.312 는 출력이 파이프면 8KB · 16KB 에서 끊고 끝난다 (--help 의 --json-schema 줄을 잃음).
    # 입력도 파일로 넘긴다. 파이프에 쓰다 막히지 않고 기다리는 동안 멈추기 신호를 볼 수 있다.
    with tempfile.TemporaryDirectory(prefix="canon-claude-") as cwd, \
            tempfile.TemporaryFile("w+", encoding="utf-8") as inp, \
            tempfile.TemporaryFile("w+", encoding="utf-8") as out, \
            tempfile.TemporaryFile("w+", encoding="utf-8") as err:
        inp.write(stdin or "")
        inp.flush()
        inp.seek(0)
        proc = subprocess.Popen(args, stdin=inp, stdout=out, stderr=err, cwd=cwd, env=child_env(env))
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    proc.wait(timeout=max(0.0, min(STOP_POLL, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    if stop is not None and stop.is_set():
                        raise cancel.Cancelled("작업을 멈췄어요") from None
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(args, timeout) from None
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(args, proc.returncode, out.read(), err.read())


def status(binary: str | None = None) -> dict:
    """설치 여부, 버전, 로그인 상태. 생성 호출은 하지 않는다. 화면과 명령줄에서 쓴다."""
    path = find_binary(binary)
    env_token = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
    d = config_dir()
    base = {"installed": bool(path), "path": path or "", "version": "", "logged_in": False, "account": {},
            "env_token": env_token, "api_key_ignored": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "message": "", "reason": "", "login_command": login_command(), "token_command": "claude setup-token",
            "separate": bool(d), "config_dir": d, "login_running": login_running()}
    # reason: ok | login(로그인 필요) | metered(구독이 아닌 API 계정) | install(설치 안 됨) | error(상태를 못 읽음)
    if not path:
        return {**base, "reason": "install", "message": INSTALL_HINT}
    try:
        ver = _run([path, "--version"], 30)
        base["version"] = (ver.stdout or ver.stderr).strip().splitlines()[0] if (ver.stdout or ver.stderr).strip() else ""
        st = _run([path, "auth", "status", "--json"], 30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {**base, "reason": "error", "message": f"Claude Code 를 실행하지 못했어요: {e}"}
    try:
        data = json.loads(st.stdout)
    except json.JSONDecodeError:
        msg = (st.stderr or st.stdout).strip()[:300]
        return {**base, "reason": "error", "message": f"로그인 상태를 읽지 못했어요 (Claude Code 를 업데이트해 보세요: claude update). {msg}"}
    account = {k: data[k] for k in STATUS_FIELDS if k in data and isinstance(data[k], (str, bool, int))}
    logged = bool(data.get("loggedIn"))
    method = str(data.get("authMethod") or "")
    paid = "api" in method.lower() and "oauth" not in method.lower()
    msg = ("로그인돼 있어요." if logged else LOGIN_HINT.replace("`claude auth login`", f"`{login_command()}`"))
    if logged and paid:
        msg = ("Claude Code 가 구독이 아니라 Console API 계정으로 로그인돼 있어 종량제로 과금돼요. "
               f"구독으로 쓰려면 터미널에서 `claude auth logout` 후 `{login_command()}` 으로 구독 계정을 고르세요.")
    reason = ("metered" if paid else "ok") if logged else "login"
    return {**base, "logged_in": logged, "account": account, "auth_method": method, "metered": paid,
            "reason": reason, "message": msg}


_login: subprocess.Popen | None = None
LOGIN_WAIT = 600  # 초. 브라우저에서 로그인을 마치지 않으면 띄운 claude auth login 을 끝낸다


def login_running() -> bool:
    return _login is not None and _login.poll() is None


def start_login(binary: str | None = None) -> dict:
    """`claude auth login --claudeai` 를 Canon 의 설정 폴더로 띄운다. 브라우저에 Anthropic 로그인 화면이 열린다.
    Canon 은 출력을 읽지 않고 입력도 넘기지 않는다 (코드 붙여 넣기는 받지 않음). 상태는 status 로 다시 본다.
    started: 지금 띄웠거나 이미 떠 있는지."""
    global _login
    path = find_binary(binary)
    if not path:
        return {"started": False, "message": INSTALL_HINT}
    if login_running():
        return {"started": True, "message": "로그인 창을 이미 열었어요. 브라우저에서 로그인을 마치세요."}
    cwd = tempfile.mkdtemp(prefix="canon-claude-login-")
    try:
        proc = subprocess.Popen([path, "auth", "login", "--claudeai"], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=cwd, env=child_env(),
                                start_new_session=True)
    except OSError as e:
        return {"started": False, "message": f"Claude Code 를 실행하지 못했어요: {e}"}
    _login = proc

    def stop() -> None:
        if proc.poll() is None:
            proc.terminate()
        shutil.rmtree(cwd, ignore_errors=True)

    t = threading.Timer(LOGIN_WAIT, stop)
    t.daemon = True
    t.start()
    return {"started": True, "message": "브라우저에 Anthropic 로그인 화면을 열었어요. Pro 또는 Max 계정으로 로그인하세요."}


def logout(binary: str | None = None) -> dict:
    """Canon 전용 폴더의 로그인만 끝낸다. 평소 Claude Code 로그인은 건드리지 않게 전용 폴더가 아니면 거절한다."""
    path = find_binary(binary)
    if not path:
        return {"ok": False, "message": INSTALL_HINT}
    if not config_dir():
        return {"ok": False, "message": "Canon 전용 로그인을 켰을 때만 여기서 로그아웃할 수 있어요."}
    try:
        out = _run([path, "auth", "logout"], 30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "message": f"Claude Code 를 실행하지 못했어요: {e}"}
    if out.returncode != 0:
        return {"ok": False, "message": f"로그아웃하지 못했어요: {(out.stderr or out.stdout).strip()[:200]}"}
    return {"ok": True, "message": "Canon 전용 계정에서 로그아웃했어요."}


class ClaudeCodeError(RuntimeError):
    pass


class ClaudeTimedOut(ClaudeCodeError):
    """하위 프로세스가 제한 시간 안에 끝나지 않았다. 끝낸 프로세스는 사용량을 남기지 않는다."""


def _explain(text: str) -> str:
    low = text.lower()
    if any(w in low for w in ("not logged in", "/login", "login expired", "invalid api key", "authentication", "oauth token")):
        return f"{LOGIN_HINT} ({text[:200]})"
    if "limit" in low and any(w in low for w in ("usage", "reached", "rate", "hit")):
        return f"{LIMIT_HINT} ({text[:200]})"
    return text[:500]


def _cli_usage(d: dict, structured: bool = False) -> dict | None:
    """JSON 결과의 토큰 수. 있으면 turns(num_turns) · stop(stop_reason) · api_seconds(duration_api_ms) ·
    models(modelUsage 의 모델별 입력 · 출력 · 캐시)도 담는다. 사용량 기록 줄의 같은 이름 칸이 된다.
    resent 는 CLI 가 한 호출 안에서 같은 요청을 다시 보낸 입력의 어림값이다. 캐시 비율을 셀 때 빼려는 값이다 (_resent)."""
    u = d.get("usage")
    if not isinstance(u, dict):
        return None
    cached = int(u.get("cache_read_input_tokens") or 0)
    prompt = int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0) + cached
    # 생각 토큰은 output_tokens 에 들어 있어 따로 세지 않는다 (사용량 화면이 출력에 더한다)
    out = {"prompt_tokens": prompt, "completion_tokens": int(u.get("output_tokens") or 0),
           "thought_tokens": 0, "cached_tokens": cached}
    out |= _written(int(u.get("cache_creation_input_tokens") or 0), u.get("cache_creation"))
    turns = d.get("num_turns")
    if isinstance(turns, int) and turns > 0:
        out["turns"] = turns
    if isinstance(d.get("stop_reason"), str) and d["stop_reason"]:
        out["stop"] = d["stop_reason"]
    if isinstance(d.get("duration_api_ms"), (int, float)):
        out["api_seconds"] = round(d["duration_api_ms"] / 1000, 2)
    mu = d.get("modelUsage")
    if isinstance(mu, dict) and mu:
        models = {}
        for name, m in mu.items():
            if not isinstance(m, dict):
                continue
            read = int(m.get("cacheReadInputTokens") or 0)
            models[name] = {"in": int(m.get("inputTokens") or 0) + int(m.get("cacheCreationInputTokens") or 0) + read,
                            "out": int(m.get("outputTokens") or 0), "cached": read}
        if models:
            out["models"] = models
    resent = _resent(prompt, out.get("turns"), out.get("models"), structured)
    if resent:
        out["resent"] = resent
    return out


def _written(total: int, split: Any) -> dict:
    """캐시에 새로 쓴 입력. written 은 쓴 토큰 수, written_1h 는 그 가운데 1시간 캐시로 쓴 몫이다 (응답의 cache_creation 내역).
    쓰지 않았으면 빈 dict 다. 쓰기는 읽기보다 비싸므로(5분 1.25배, 1시간 2배) 사용량 화면이 따로 보려는 값이다."""
    if total <= 0:
        return {}
    out = {"written": total}
    long = split.get("ephemeral_1h_input_tokens") if isinstance(split, dict) else getattr(split, "ephemeral_1h_input_tokens", None)
    if isinstance(long, int) and long > 0:
        out["written_1h"] = long
    return out


def _resent(prompt: int, turns: int | None, models: dict | None, structured: bool) -> int:
    """한 호출 안에서 다시 보낸 입력의 어림값. 두 신호 가운데 큰 쪽을 쓴다.
    - 턴: 구조화 출력(--json-schema)은 답을 도구로 내므로 요청이 한 번이어도 num_turns 가 2 다. 그래서 요청 수는
      구조화 출력이면 turns-1, 아니면 turns 로 보고 in × (요청 수-1)/요청 수 를 다시 보낸 몫으로 본다.
    - 대체 모델: modelUsage 에 모델이 둘 이상이면 (안전 분류기 거절 뒤 다른 모델로 이어 받음) 가장 작은 모델 입력을
      요청 한 번의 크기로 보고, in 이 그보다 큰 몫을 다시 보낸 몫으로 본다. 이때 num_turns 는 1 로 온다.
    실측(2026-11-05 서버, Opus 구독): 구조화 출력 11건은 모두 turns 2 · stop tool_use 인데 입력은 글자 수의 약 1.07배(한 번),
    turns 3 인 검수 1건은 2.16배(두 번). 대체 모델이 낀 쓰기 2건은 turns 1 인데 Opus 입력이 Fable 입력의 2배였다."""
    by_turns = 0
    if isinstance(turns, int) and turns > 0:
        sends = max(1, turns - 1 if structured else turns)
        by_turns = round(prompt * (sends - 1) / sends)
    by_models = 0
    ins = [m["in"] for m in (models or {}).values() if m.get("in")]
    if len(ins) > 1:
        by_models = max(0, prompt - min(ins))
    return max(by_turns, by_models)


def _served(d: dict) -> str:
    """실제로 답한 모델. 보조 호출이 섞이면 출력이 가장 많은 모델."""
    mu = d.get("modelUsage")
    if not isinstance(mu, dict) or not mu:
        return ""
    return max(mu, key=lambda k: (mu[k] if isinstance(mu[k], dict) else {}).get("outputTokens") or 0)


# Canon 이 부르는 Claude Code 에서 끄는 사용자 설정. --safe-mode 는 advisor 를 끄지 않는다.
# 사용자 설정에 advisorModel 이 있으면 Canon 호출에도 advisor(다른 모델)가 붙어, 긴 호출마다 그 모델 요청이 하나 늘고
# 본 모델 요청도 advisor 앞뒤로 두 번 나간다 (2026-11-09 실측: subway 11-06~11-09 Claude 호출 544번 중 84번, advisor 입력 약 703만 토큰)
NO_ADVISOR = '{"advisorModel": ""}'


class ClaudeCodeLLM:
    """설치된 Claude Code 를 `claude -p` 로 부른다. 도구는 모두 끄고, 시스템 프롬프트를 Canon 것으로 바꾸고,
    세션을 남기지 않는다. 구조화 출력은 --json-schema 로 받고 pydantic 으로 검증해, 어긋나면 한 번 더 묻는다."""
    family_cache = True  # PREFIX_HINT 를 받으면 캐시 가족으로 부른다 (prompts.FAMILY_SYSTEM)

    def __init__(self, model: str | None = None, binary: str | None = None, timeout: float | None = None,
                 effort: str = ""):
        from . import settings

        self.binary = find_binary(binary)
        self.requested = model or settings.claude_model()[0]
        self.effort = effort if effort in settings.EFFORTS else ""  # 실제로 넘긴 값만 남긴다 (_args)
        self.timeout = timeout or float(os.environ.get("CANON_CLAUDE_TIMEOUT", "900"))
        self.served = ""
        self.last_usage: dict | None = None
        self.last_attempts = 0
        self.last_raw = self.last_note = ""
        self.last_keep = True  # 이번 호출이 캐시에 쓰나. 아니면 DISABLE_PROMPT_CACHING 을 넣는다 (_split)
        self.last_cache_note = ""  # 캐시에 쓰거나 쓰지 않는 까닭 (사용량 칸 cache_note, worth_caching)

    @property
    def model(self) -> str:
        return self.served or self.requested or "claude-code"

    def _bin(self) -> str:
        if not self.binary:
            raise ClaudeCodeError(INSTALL_HINT)
        return self.binary

    def check(self) -> None:
        st = status(self.binary)
        if not st["installed"]:
            raise ClaudeCodeError(INSTALL_HINT)
        if not st["logged_in"]:
            raise ClaudeCodeError(st["message"] or LOGIN_HINT)

    def models(self) -> list[str]:
        return list(CLI_MODELS)

    def context_limit(self) -> int | None:
        return None

    def count_tokens(self, text: str) -> int | None:
        return None

    def _args(self, system: str, schema: dict | None, system_file: str | None = None) -> list[str]:
        """system_file 을 주면 시스템 프롬프트를 글 대신 그 파일로 넘긴다 (_call 이 앞부분을 시스템 프롬프트로 옮긴 때)."""
        binary = self._bin()
        flags = _flags(binary)
        if schema is not None and "--json-schema" not in flags:
            raise ClaudeCodeError("이 Claude Code 버전은 구조화 출력(--json-schema)을 몰라요. `claude update` 로 올리세요.")
        if "--tools" not in flags:  # 도구를 끄지 못하면 부르지 않는다 (옵션 목록을 읽지 못한 때도)
            raise ClaudeCodeError("이 Claude Code 버전에서 도구 끄기(--tools)를 확인하지 못했어요. `claude update` 로 올리세요.")
        sp = ["--system-prompt-file", system_file] if system_file else ["--system-prompt", system]
        args = [binary, "-p", "--output-format", "json", *sp,
                "--tools", ""]  # 파일 읽기, 명령 실행, 웹 검색을 모두 끈다
        for f in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
            if f in flags:
                args.append(f)
        if "--settings" in flags:  # 사용자 설정의 advisor 를 끈다 (NO_ADVISOR)
            args += ["--settings", NO_ADVISOR]
        if self.requested:
            args += ["--model", self.requested]
        if self.effort:
            if "--effort" not in flags:  # 오래된 버전: 강도 없이 부르고, 사용량 기록에 강도를 남기지 않는다
                self.effort = ""
            else:
                args += ["--effort", self.effort]
        if schema is not None:
            args += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
        return args

    def _call(self, system: str, prompt: str, schema: type[BaseModel] | None = None, attempt: int = 1,
              cut: int | None = None, prefix: int | None = None) -> Any:
        """한 번 부르고 사용량을 기록한다. 프롬프트는 표준 입력으로 넘긴다 (인자 길이 한도를 피한다).
        schema 가 있으면 검증한 값을, 없으면 글을 돌려준다. cut 을 주면 그 자리에서 앞부분을 옮긴다 (_split).
        prefix 는 부른 쪽이 아는 공통 앞부분의 글자 수다 (llm.prefix_of)."""
        from .llm import caps, with_note

        cancel.check()  # 멈춘 작업은 다음 호출을 보내지 않는다 (형식 고치기 재시도도)
        cap, wait = caps()
        # 출력 한도는 CLI 옵션이 없어 이 호출의 환경 변수로만 넘긴다. 한도가 없으면 넣지 않는다 (Claude Code 기본값)
        env = {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(cap)} if cap else None
        timeout = min(self.timeout, wait) if wait else self.timeout
        t, tokens = time.time(), None
        self.last_raw = self.last_note = ""
        if cut is None:
            self.last_cache_note = ""  # _split 이 정한다. 재시도(cut 있음)는 첫 시도의 까닭을 그대로 쓴다
        gate, claim, reached, sent = None, None, False, 0.0
        self.last_cut = 0
        try:
            sch = strict_schema(schema) if schema else None
            head, ask, self.last_cut = self._split(system, prompt, schema, cut, prefix)
            if not self.last_keep:
                # 다음 호출이 읽지 않을 캐시는 쓰지 않는다. 캐시 쓰기는 입력 값의 1.25배다
                env = {**(env or {}), "DISABLE_PROMPT_CACHING": "1"}
            family = bool(prefix and self.last_cut)
            if family and schema is not None:
                # --json-schema 는 스키마마다 다른 도구를 붙여 캐시를 가른다 (도구가 시스템 프롬프트보다 앞). 가족 호출은 글로 JSON 을 받는다
                sch, ask = None, ask.rstrip() + json_instruction(schema)
            if head != system and self.last_keep:
                # 가족 호출은 스키마가 달라도 같은 앞부분이면 같은 캐시다
                gate = ("cli", self.requested, None if family else schema and schema.__name__, len(head), hash(head))
                claim = _claim(gate)
                t = time.time()  # 앞 호출을 기다린 시간은 이 호출의 시간에 넣지 않는다
            sent = time.time()
            try:
                with tempfile.TemporaryDirectory(prefix="canon-claude-sys-") as tmp:
                    system_file = None
                    if head != system:
                        system_file = os.path.join(tmp, "system.txt")
                        Path(system_file).write_text(head, encoding="utf-8")
                    proc = _run(self._args(head, sch, system_file), timeout, stdin=with_note(ask),
                                stop=cancel.current.get(), env=env)
            except subprocess.TimeoutExpired as e:
                raise ClaudeTimedOut(f"Claude Code 응답이 {timeout:g}초 안에 오지 않았어요"
                                      + ("" if wait and wait < self.timeout else " (CANON_CLAUDE_TIMEOUT)")) from e
            try:
                d = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else None
            except json.JSONDecodeError:
                d = None
            if not isinstance(d, dict):
                raise ClaudeCodeError(f"Claude Code 실행 실패 (종료 코드 {proc.returncode}): "
                                      f"{_explain((proc.stderr or proc.stdout).strip() or '출력 없음')}")
            tokens = self.last_usage = _cli_usage(d, structured=sch is not None)
            reached = bool(tokens and tokens["prompt_tokens"])  # 요청이 모델까지 갔으면 앞부분이 캐시에 들어갔다
            self.served = _served(d) or self.served
            if d.get("is_error") or d.get("subtype") not in (None, "success"):
                raise ClaudeCodeError(f"Claude Code 오류: {_explain(str(d.get('result') or d.get('subtype') or d))}")
            if d.get("stop_reason") == "refusal":
                raise ClaudeCodeError("Claude가 이 요청을 거절했어요 (안전 분류기). 수위나 표현을 조정하거나 다른 백엔드로 돌리세요.")
            raw = d.get("structured_output") if sch is not None else None
            if raw is not None:
                self.last_note = str(d.get("result") or "").strip()  # 구조화 출력 곁에 남긴 글. 빈 결과의 이유를 보인다
            if raw is None:
                raw = str(d.get("result") or "").strip()
                if not raw:
                    raise ClaudeCodeError("Claude Code 응답이 비었어요")
            self.last_raw = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
            tokens = usage.with_extra(tokens, out_chars=len(self.last_raw))  # 사용량 기록 칸 (끝난 이유 stop 은 _cli_usage 가 담는다)
            out = _parse(schema, raw) if schema is not None else raw
        except Exception as e:
            if sent or not isinstance(e, cancel.Cancelled):  # 앞 호출을 기다리다 멈췄으면 보내지 않았으니 기록하지 않는다
                usage.record(self, usage.with_extra(tokens, cache_note=self.last_cache_note), t, ok=False, error=e,
                             attempt=attempt, prompt=prompt)
            raise
        finally:
            if gate is not None:
                _release(gate, claim, reached, sent)
        usage.record(self, usage.with_extra(tokens, cache_note=self.last_cache_note), t, attempt=attempt, prompt=prompt)
        return out

    def _split(self, system: str, prompt: str, schema: type[BaseModel] | None,
               cut: int | None = None, prefix: int | None = None) -> tuple[str, str, int]:
        """(시스템 프롬프트, 사용자 메시지, 옮긴 글자 수). Claude Code 는 시스템 프롬프트 끝에 캐시 표시를 달고, 사용자 메시지는
        통째로 같을 때만 캐시가 맞는다. 그래서 같은 종류 직전 요청과 겹치는 앞부분(shared_cut)을 시스템 프롬프트 뒤로 옮긴다.
        cut 을 주면 그 자리를 쓴다 (형식 고치기 재시도가 첫 시도와 같은 시스템 프롬프트로 캐시를 읽게).
        prefix 를 주면 직전 요청과 견주지 않고 그 자리(단락 경계로 맞춤)에서 옮긴다. 같은 앞부분의 첫 호출부터 캐시에 넣는다.
        겹침이 짧거나 이 버전이 --system-prompt-file 을 모르면 그대로 둔다 (긴 글을 인자로 넘기면 Linux 한도 128KB 에 걸린다).
        캐시에 쓸지(last_keep)와 그 까닭(last_cache_note, 사용량 칸 cache_note)도 정한다 (worth_caching).
        cut 을 주면(형식 고치기 재시도) 첫 시도의 값을 그대로 쓴다."""
        if "--system-prompt-file" not in _flags(self._bin()):
            self.last_keep, self.last_cache_note = True, "unsupported"  # 앞부분을 옮기지 못하는 버전은 예전처럼 Claude Code 에 맡긴다
            return system, prompt, 0
        if cut is None:
            cut, recent = cut_and_recent(("cli", self.requested, system, schema and schema.__name__), prompt, prefix)
            self.last_keep, self.last_cache_note = worth_caching(cut, prefix, recent)
        if not cut:
            return system, prompt, 0
        if prefix:  # 캐시 가족: 시스템 프롬프트를 가족 공통 글로 두고 원래 것은 사용자 메시지 앞으로 (prompts.FAMILY_SYSTEM)
            from .llm import role_block
            from .prompts import FAMILY_SYSTEM

            return f"{FAMILY_SYSTEM}\n\n{prompt[:cut]}", role_block(system) + prompt[cut:].lstrip("\n"), cut
        return f"{system.rstrip()}\n\n{prompt[:cut]}", prompt[cut:].lstrip("\n"), cut

    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        from .llm import SchemaMismatch, prefix_of, repair_prompt

        ask, cut, prefix = prompt, None, prefix_of(hint)
        for attempt in range(2):
            self.last_attempts = attempt + 1
            try:
                return self._slow_retry(lambda: self._call(system, ask, schema, attempt + 1, cut, prefix))
            except ValidationError as e:
                if attempt:
                    raise SchemaMismatch(schema, e, "Claude") from e
                ask = repair_prompt(prompt, self.last_raw, schema, e)  # 처음 요청 뒤에 덧붙이므로 같은 자리에서 자른다
                cut = self.last_cut
        raise AssertionError("unreachable")

    def text(self, system: str, prompt: str, hint: dict | None = None) -> str:
        """hint 의 PREFIX_HINT 는 캐시 가족 경계다 (llm.family_text)."""
        from .llm import prefix_of

        self.last_attempts = 1
        return self._slow_retry(lambda: self._call(system, prompt, prefix=prefix_of(hint)))

    def _slow_retry(self, call: Any) -> Any:
        """wait_cap 으로 줄인 한도를 넘기면 llm.TIMEOUT_RETRIES 번 다시 부른다 (Gemini 와 같다).
        한도를 줄이지 않은 호출(CANON_CLAUDE_TIMEOUT)은 다시 부르지 않는다. 그 한도를 두 번 기다리지 않게 한다."""
        from .llm import TIMEOUT_RETRIES, caps

        for i in range(TIMEOUT_RETRIES + 1):
            try:
                return call()
            except ClaudeTimedOut:
                _, wait = caps()
                if i >= TIMEOUT_RETRIES or not wait or wait >= self.timeout:
                    raise
                cancel.say("AI 응답이 늦어 다시 불러요")
        raise AssertionError("unreachable")


# ---------- API 키: Messages API ----------

def api_model(model: str) -> str:
    """claude-api 가 쓸 모델. 단계 모델이 비어 Gemini 모델 이름이 넘어오면 Claude 기본 모델로 바꾼다 (비용 추정용)."""
    from . import settings

    if model.startswith("claude"):
        return model
    return settings.claude_model()[0] or DEFAULT_API_MODEL


# 프롬프트 캐시: Messages API 는 cache_control 을 단 블록까지만 캐시한다. 프롬프트는 작품 고정 블록이 앞, 화마다 바뀌는
# 블록이 뒤라(prompts.build_episode_context), 같은 종류의 직전 요청과 겹치는 앞부분 끝에 표시를 달면 다음 화부터 그 앞부분을 읽는다.
_SEEN: dict[tuple, str] = {}  # (모델, 시스템, 스키마) → 직전 요청 본문
_SEEN_AT: dict[tuple, float] = {}  # 같은 열쇠 → 직전 요청을 본 시각
_SEEN_LOCK = threading.Lock()
CACHE_MIN_CHARS = 2_000  # 겹치는 앞부분이 이보다 짧으면 표시하지 않는다 (최소 캐시 길이 아래)


def shared_cut(key: tuple, prompt: str, prefix: int | None = None) -> int:
    """직전 같은 종류 요청과 겹치는 앞부분이 끝나는 단락 경계. 겹침이 CACHE_MIN_CHARS 보다 짧으면 0. 이 요청을 직전 요청으로 기억한다.
    prefix 를 주면 직전 요청 대신 그 글자 수를 앞부분 끝으로 본다 (부른 쪽이 공통 자료가 끝나는 곳을 안다: llm.prefix_of).
    그 자리 바로 뒤의 단락 구분까지 앞부분에 넣어, 자료 뒤에 '\n\n'으로 요청을 붙인 프롬프트는 자료 끝에서 자른다."""
    return cut_and_recent(key, prompt, prefix)[0]


def cut_and_recent(key: tuple, prompt: str, prefix: int | None = None) -> tuple[int, bool]:
    """(shared_cut 의 자리, 같은 종류 직전 요청을 캐시 유지 시간 안에 봤는지)."""
    now = time.time()
    with _SEEN_LOCK:
        prev = _SEEN.get(key, "")
        recent = key in _SEEN and now - _SEEN_AT.get(key, 0.0) < _warm_seconds()
        _SEEN[key] = prompt
        _SEEN_AT[key] = now
    end = min(prefix, len(prompt)) + 2 if prefix else len(os.path.commonprefix([prev, prompt]))
    cut = prompt.rfind("\n\n", 0, end)
    return (cut if cut >= CACHE_MIN_CHARS else 0), recent


def worth_caching(cut: int, prefix: int | None, recent: bool) -> tuple[bool, str]:
    """(이 요청을 캐시에 쓸 만한가, 그 까닭 낱말). 캐시 쓰기는 입력 값의 1.25배(1시간 캐시는 2배)라, 다음 요청이 읽을 앞부분이 있을 때만 쓴다.
    - 나눌 앞부분이 없으면(cut 0) 쓰지 않는다 (short). 다음 요청은 다른 자리에서 나누므로 이 요청의 캐시를 읽지 못한다.
    - 부른 쪽이 경계를 알려 줬으면(prefix, 캐시 가족 · 부분 수정) 쓴다 (prefix). 곧 같은 앞부분 요청이 온다.
    - 경계 없이 직전 요청과 견줘 나눴으면, 직전 요청을 캐시 유지 시간 안에 봤을 때만 쓴다 (recent, 아니면 not_worth).
      화마다 한 번 부르는 단계(plot_one 등)는 다음 요청이 캐시 유지 시간 뒤에 와서 읽지 못한다 (2026-11-07 서버 실측).
    까닭 낱말은 사용량 기록 칸 cache_note 가 된다 (llm.CACHE_NOTES)."""
    if not cut:
        return False, "short"
    if prefix:
        return True, "prefix"
    return (True, "recent") if recent else (False, "not_worth")


# 구독(Claude Code)은 앞부분을 시스템 프롬프트로 옮겨 캐시한다(ClaudeCodeLLM._split). 고침안 받기처럼 같은 앞부분 요청을
# 동시에 여럿 보내면 모두 캐시를 새로 쓰므로, 같은 시스템 프롬프트를 먼저 보낸 호출이 앞부분을 읽어 캐시에 넣을 동안
# (CACHE_PREFILL_SECONDS, 그 전에 끝나면 끝날 때까지) 뒤 호출을 기다리게 한다. 캐시는 응답이 나오기 시작하면 읽을 수 있어
# 앞 호출의 응답이 끝날 때까지 기다리지 않는다. 보낸 뒤 CACHE_WARM_SECONDS 동안은 기다리지 않는다 (이미 캐시에 있다).
_WRITING: dict[tuple, tuple[threading.Event, float]] = {}  # 캐시를 쓰는 중인 시스템 프롬프트 → (끝나면 세우는 신호, 보낸 시각)
_WARM: dict[tuple, float] = {}  # 캐시에 들어간 시스템 프롬프트 → 마지막으로 보낸 시각
CACHE_WARM_SECONDS = 300  # 캐시 유지 시간 (짧은 쪽 5분)
CACHE_WARM_SECONDS_1H = 3600  # CANON_CLAUDE_CACHE_1H 를 켰을 때의 유지 시간
CACHE_PREFILL_SECONDS = 30  # 앞 호출을 보낸 뒤 이만큼만 기다린다 (실행 준비와 앞부분 읽기)


def _warm_seconds() -> int:
    return CACHE_WARM_SECONDS_1H if cache_1h() else CACHE_WARM_SECONDS


def _claim(gate: tuple) -> threading.Event | None:
    """캐시를 쓸 차례면 신호를 돌려준다(끝나면 _release). 다른 호출이 같은 앞부분을 쓰는 중이면 그 호출이 끝나거나
    보낸 지 CACHE_PREFILL_SECONDS 가 지나기를 기다려 None 을 돌려준다. 이미 캐시에 있어도 None 이다. 기다리는 동안 작업 멈추기를 본다."""
    while True:
        with _SEEN_LOCK:
            if time.time() - _WARM.get(gate, 0.0) < _warm_seconds():
                return None
            writing = _WRITING.get(gate)
            if writing is None:
                ev = threading.Event()
                _WRITING[gate] = (ev, time.time())
                return ev
        ev, started = writing
        left = started + CACHE_PREFILL_SECONDS - time.time()
        if left <= 0:
            return None
        cancel.check()
        ev.wait(min(left, 1.0))  # 앞 호출이 끝나면 다시 본다. 모델까지 갔으면 None, 못 갔으면 이 호출이 대신 쓴다


def _release(gate: tuple, claim: threading.Event | None, reached: bool, sent: float = 0.0) -> None:
    """호출이 끝났다. 모델까지 간 요청이면 보낸 시각(sent)부터 그 앞부분이 캐시에 있다고 기억하고, 쓰던 차례를 놓는다."""
    now = time.time()
    with _SEEN_LOCK:
        if reached:
            _WARM[gate] = max(_WARM.get(gate, 0.0), sent or now)
            for k in [k for k, at in _WARM.items() if now - at >= _warm_seconds()]:
                del _WARM[k]
        if claim is not None and _WRITING.get(gate, (None,))[0] is claim:
            del _WRITING[gate]
    if claim is not None:
        claim.set()


def cache_blocks(key: tuple, prompt: str, prefix: int | None = None) -> str | list[dict]:
    """직전 같은 종류 요청과 겹치는 앞부분을 단락 경계에서 잘라 캐시 표시를 단 블록으로 나눈다. 겹침이 짧으면 글 그대로.
    prefix 를 주면 그 자리에서 자른다 (shared_cut). 다음 요청이 읽을 만하지 않으면 표시하지 않는다 (worth_caching)."""
    return cache_blocks_note(key, prompt, prefix)[0]


def cache_blocks_note(key: tuple, prompt: str, prefix: int | None = None) -> tuple[str | list[dict], str]:
    """(cache_blocks 의 값, worth_caching 의 까닭 낱말). 까닭은 사용량 기록 칸 cache_note 가 된다."""
    cut, recent = cut_and_recent(key, prompt, prefix)
    keep, note = worth_caching(cut, prefix, recent)
    if not keep:
        return prompt, note
    mark = {"type": "ephemeral", "ttl": "1h"} if cache_1h() else {"type": "ephemeral"}
    return [{"type": "text", "text": prompt[:cut], "cache_control": mark},
            {"type": "text", "text": prompt[cut:]}], note


def _api_usage(u: Any) -> dict | None:
    if u is None:
        return None
    cached = getattr(u, "cache_read_input_tokens", None) or 0
    written = getattr(u, "cache_creation_input_tokens", None) or 0
    prompt = (u.input_tokens or 0) + written + cached
    out = {"prompt_tokens": prompt, "completion_tokens": u.output_tokens or 0, "thought_tokens": 0, "cached_tokens": cached}
    return out | _written(written, getattr(u, "cache_creation", None))


class ClaudeAPILLM:
    """Anthropic API 키로 Messages API 를 부른다. 구조화 출력은 output_config.format 으로 강제하고
    pydantic 으로 검증한다. 긴 본문도 끊기지 않게 스트리밍으로 받는다."""
    family_cache = True
    knows_cut = True  # 끊긴 응답(stop_reason max_tokens)은 llm.OutputCut 오류로 알린다

    def __init__(self, model: str | None = None, api_key: str | None = None, effort: str = ""):
        import anthropic

        from . import settings

        key = api_key or settings.anthropic_key()[0]
        if not key:
            from .llm import MissingKey  # 웹이 설정 안내(code no_key)로 보인다

            raise MissingKey("Anthropic API 키가 없어요. 웹 설정의 AI 연결에서 넣거나 ANTHROPIC_API_KEY를 설정하세요.")
        self.client = anthropic.Anthropic(api_key=key, max_retries=3)
        self.model = model or settings.claude_model()[0] or DEFAULT_API_MODEL
        self.effort = effort if effort in settings.EFFORTS else ""
        self.last_usage: dict | None = None
        self.last_attempts = 0
        self.last_raw = ""

    def check(self) -> None:
        self.client.models.retrieve(self.model)

    def models(self) -> list[str]:
        return [m.id for m in self.client.models.list()]

    def context_limit(self) -> int | None:
        return getattr(self.client.models.retrieve(self.model), "max_input_tokens", None)

    def count_tokens(self, text: str) -> int | None:
        return self.client.messages.count_tokens(model=self.model, messages=[{"role": "user", "content": text}]).input_tokens

    def _call(self, system: str, prompt: str, schema: type[BaseModel] | None = None, attempt: int = 1,
              prefix: int | None = None, on_chunk: Callable[[str], None] | None = None) -> Any:
        """on_chunk 가 있으면 글 조각(text 이벤트)마다 지금까지 받은 글 전체로 부른다. 사용량은 다 받은 뒤 한 번 기록한다."""
        from .llm import caps, with_note

        cancel.check()  # 멈춘 작업은 다음 호출을 보내지 않는다 (형식 고치기 재시도도)
        out_cap, wait = caps()
        limit = min(MAX_TOKENS, out_cap) if out_cap else MAX_TOKENS
        t, tokens = time.time(), None
        self.last_raw = ""
        content, note = cache_blocks_note((self.model, system, schema and schema.__name__), with_note(prompt), prefix)
        if prefix and isinstance(content, list):  # 캐시 가족: 시스템 프롬프트를 가족 공통 글로, 원래 것은 뒤 블록 앞으로
            from .llm import role_block
            from .prompts import FAMILY_SYSTEM

            content[1]["text"] = role_block(system) + content[1]["text"].lstrip("\n")
            system = FAMILY_SYSTEM
        req: dict[str, Any] = {"model": self.model, "max_tokens": limit, "system": system,
                               "messages": [{"role": "user", "content": content}]}
        if schema is not None:
            req["output_config"] = {"format": {"type": "json_schema", "schema": strict_schema(schema)}}
        if self.effort:
            req.setdefault("output_config", {})["effort"] = self.effort
        if self.model.startswith(FALLBACK_MODELS):
            req |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        if wait:
            req["timeout"] = wait  # SDK 요청 옵션: 연결과 조각 사이 기다림의 한도
        try:
            got: list[str] = []
            with self.client.beta.messages.stream(**req) as stream:
                for ev in stream:  # 조각마다 멈추기 신호를 본다. 멈추면 스트림을 닫는다
                    cancel.check()
                    if on_chunk is not None and getattr(ev, "type", "") == "text" and getattr(ev, "text", ""):
                        got.append(ev.text)
                        on_chunk("".join(got).lstrip())
                msg = stream.get_final_message()
            tokens = self.last_usage = _api_usage(msg.usage)
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
            # 사용량 기록 칸 (usage.EXTRA). 끊긴 응답도 받은 글자 수를 남긴다
            tokens = usage.with_extra(tokens, stop=msg.stop_reason, out_chars=len(text))
            if msg.stop_reason == "refusal":
                raise RuntimeError("Claude가 이 요청을 거절했어요 (안전 분류기). 수위나 표현을 조정하거나 다른 백엔드로 돌리세요.")
            if msg.stop_reason == "max_tokens":
                from .llm import OutputCut
                raise OutputCut(f"Claude 응답이 최대 길이({limit} 토큰)에서 끊겼어요")
            if not text:
                raise RuntimeError(f"Claude 응답이 비었어요: stop_reason={msg.stop_reason}")
            self.last_raw = text
            out = _parse(schema, text) if schema is not None else text
        except Exception as e:
            usage.record(self, usage.with_extra(tokens, cache_note=note), t, ok=False, error=e, attempt=attempt, prompt=prompt)
            raise
        usage.record(self, usage.with_extra(tokens, cache_note=note), t, attempt=attempt, prompt=prompt)
        return out

    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        from .llm import SchemaMismatch, prefix_of, repair_prompt

        ask, prefix = prompt, prefix_of(hint)
        for attempt in range(2):
            self.last_attempts = attempt + 1
            try:
                return self._call(system, ask, schema, attempt + 1, prefix)
            except ValidationError as e:
                if attempt:
                    raise SchemaMismatch(schema, e, "Claude API") from e
                ask = repair_prompt(prompt, self.last_raw, schema, e)
        raise AssertionError("unreachable")

    def text(self, system: str, prompt: str, hint: dict | None = None) -> str:
        from .llm import prefix_of

        self.last_attempts = 1
        return self._call(system, prompt, prefix=prefix_of(hint))

    def text_stream(self, system: str, prompt: str, on_chunk: Callable[[str], None], hint: dict | None = None) -> str:
        """text 와 같지만 글 조각마다 지금까지 받은 글 전체로 on_chunk 를 부른다 (llm.family_text)."""
        from .llm import prefix_of

        self.last_attempts = 1
        return self._call(system, prompt, prefix=prefix_of(hint), on_chunk=on_chunk)
