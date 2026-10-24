"""Claude 백엔드 두 가지: 구독 로그인(설치된 Claude Code) 과 Anthropic API 키.

claude (구독 로그인)
  이 컴퓨터에 설치하고 로그인한 Claude Code 를 `claude -p` 로 부른다. 로그인은 Claude Code 가
  Anthropic 의 로그인 화면으로 직접 하고(`claude auth login`), Canon 은 계정 정보나 토큰을 읽지도
  저장하지도 않는다. Anthropic 은 다른 앱이 Claude 계정 로그인을 제공하거나 Pro/Max 토큰을 받아
  대신 호출하는 것을 허용하지 않기 때문이다 (Claude Code 문서 'Legal and compliance' 의
  Authentication and credential use). 그래서 Canon 화면에는 로그인 칸이 없고 상태 확인과 안내만 있다.
  서버처럼 브라우저가 없는 곳은 `claude setup-token` 으로 받은 토큰을 Canon 이 아니라 서버 환경의
  CLAUDE_CODE_OAUTH_TOKEN 에 둔다. 구독 한도는 평범한 개인 사용을 전제로 하므로 긴 자동 집필은
  API 키 쪽이 맞다.

claude-api (API 키)
  Claude Console 에서 받은 API 키로 Messages API 를 부른다. 종량제로 사용량 화면에 비용이 잡힌다.

설정 (환경 변수가 설정 파일보다 우선):
  CANON_CLAUDE_MODEL  두 백엔드의 기본 모델. 비우면 구독은 Claude Code 기본 모델, API 는 DEFAULT_API_MODEL
  CANON_CLAUDE_BIN    claude 실행 파일 경로 (PATH 에 없을 때)
  ANTHROPIC_API_KEY   claude-api 의 키. 구독 호출에는 넘기지 않는다 (넘기면 Claude Code 가 키로 과금한다)
  CANON_CLAUDE_TIMEOUT  한 번 호출의 제한 시간(초, 기본 900)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from . import usage

T = TypeVar("T", bound=BaseModel)

DEFAULT_API_MODEL = "claude-opus-5-5"
# 설정 화면 모델 칸의 추천. 구독(Claude Code)은 별칭도 받는다.
CLI_MODELS = ["opus", "sonnet", "haiku", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
# 안전 분류기가 거절하면 다른 모델로 이어 받는 서버 쪽 대체. 이 모델들만 받는다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
MAX_TOKENS = 64000  # 본문 한 화와 생각을 넉넉히. 스트리밍으로 받아 시간 초과를 피한다

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


def child_env() -> dict:
    """claude 를 부를 때의 환경. API 키를 빼야 구독으로 호출한다 (-p 에서는 키가 있으면 늘 키를 쓴다).
    사용자 CLAUDE.md 와 자동 메모리는 소설 프롬프트에 섞이지 않게 끈다. CLAUDE_CODE_OAUTH_TOKEN 은 그대로 둔다."""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    return env


@lru_cache(maxsize=8)
def _flags(binary: str) -> frozenset[str]:
    """이 버전이 아는 옵션. 오래된 버전에 없는 옵션을 넘기면 실행이 실패하므로 있는 것만 쓴다."""
    try:
        out = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=30, env=child_env())
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    text = out.stdout + out.stderr
    known = ("--safe-mode", "--tools", "--strict-mcp-config", "--no-session-persistence", "--json-schema")
    return frozenset(f for f in known if f in text)


def _run(args: list[str], timeout: float, stdin: str | None = None) -> subprocess.CompletedProcess:
    # 작업 폴더를 빈 임시 폴더로 둬서 Canon 저장소의 CLAUDE.md, 훅, MCP 설정을 읽지 않게 한다
    with tempfile.TemporaryDirectory(prefix="canon-claude-") as cwd:
        return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout,
                              cwd=cwd, env=child_env())


def status(binary: str | None = None) -> dict:
    """설치 여부, 버전, 로그인 상태. 생성 호출은 하지 않는다. 화면과 명령줄에서 쓴다."""
    path = find_binary(binary)
    env_token = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
    base = {"installed": bool(path), "path": path or "", "version": "", "logged_in": False, "account": {},
            "env_token": env_token, "api_key_ignored": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "message": "", "reason": "", "login_command": "claude auth login", "token_command": "claude setup-token"}
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
    msg = ("로그인돼 있어요." if logged else LOGIN_HINT)
    if logged and paid:
        msg = ("Claude Code 가 구독이 아니라 Console API 계정으로 로그인돼 있어 종량제로 과금돼요. "
               "구독으로 쓰려면 터미널에서 `claude auth logout` 후 `claude auth login` 으로 구독 계정을 고르세요.")
    reason = ("metered" if paid else "ok") if logged else "login"
    return {**base, "logged_in": logged, "account": account, "auth_method": method, "metered": paid,
            "reason": reason, "message": msg}


class ClaudeCodeError(RuntimeError):
    pass


def _explain(text: str) -> str:
    low = text.lower()
    if any(w in low for w in ("not logged in", "/login", "login expired", "invalid api key", "authentication", "oauth token")):
        return f"{LOGIN_HINT} ({text[:200]})"
    if "limit" in low and any(w in low for w in ("usage", "reached", "rate", "hit")):
        return f"{LIMIT_HINT} ({text[:200]})"
    return text[:500]


def _cli_usage(d: dict) -> dict | None:
    u = d.get("usage")
    if not isinstance(u, dict):
        return None
    cached = int(u.get("cache_read_input_tokens") or 0)
    prompt = int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0) + cached
    # 생각 토큰은 output_tokens 에 들어 있어 따로 세지 않는다 (사용량 화면이 출력에 더한다)
    return {"prompt_tokens": prompt, "completion_tokens": int(u.get("output_tokens") or 0),
            "thought_tokens": 0, "cached_tokens": cached}


def _served(d: dict) -> str:
    """실제로 답한 모델. 보조 호출이 섞이면 출력이 가장 많은 모델."""
    mu = d.get("modelUsage")
    if not isinstance(mu, dict) or not mu:
        return ""
    return max(mu, key=lambda k: (mu[k] or {}).get("outputTokens") or 0)


class ClaudeCodeLLM:
    """설치된 Claude Code 를 `claude -p` 로 부른다. 도구는 모두 끄고, 시스템 프롬프트를 Canon 것으로 바꾸고,
    세션을 남기지 않는다. 구조화 출력은 --json-schema 로 받고 pydantic 으로 검증해, 어긋나면 한 번 더 묻는다."""

    def __init__(self, model: str | None = None, binary: str | None = None, timeout: float | None = None):
        from . import settings

        self.binary = find_binary(binary)
        self.requested = model or settings.claude_model()[0]
        self.timeout = timeout or float(os.environ.get("CANON_CLAUDE_TIMEOUT", "900"))
        self.served = ""
        self.last_usage: dict | None = None
        self.last_attempts = 0
        self.last_raw = ""

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

    def _args(self, system: str, schema: dict | None) -> list[str]:
        binary = self._bin()
        flags = _flags(binary)
        if schema is not None and "--json-schema" not in flags:
            raise ClaudeCodeError("이 Claude Code 버전은 구조화 출력(--json-schema)을 몰라요. `claude update` 로 올리세요.")
        args = [binary, "-p", "--output-format", "json", "--system-prompt", system]
        if "--tools" in flags:
            args += ["--tools", ""]  # 파일 읽기, 명령 실행, 웹 검색을 모두 끈다
        for f in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
            if f in flags:
                args.append(f)
        if self.requested:
            args += ["--model", self.requested]
        if schema is not None:
            args += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
        return args

    def _call(self, system: str, prompt: str, schema: type[BaseModel] | None = None, attempt: int = 1) -> Any:
        """한 번 부르고 사용량을 기록한다. 프롬프트는 표준 입력으로 넘긴다 (인자 길이 한도를 피한다).
        schema 가 있으면 검증한 값을, 없으면 글을 돌려준다."""
        t, tokens = time.time(), None
        self.last_raw = ""
        try:
            args = self._args(system, strict_schema(schema) if schema else None)
            try:
                proc = _run(args, self.timeout, stdin=prompt)
            except subprocess.TimeoutExpired as e:
                raise ClaudeCodeError(f"Claude Code 응답이 {int(self.timeout)}초 안에 오지 않았어요 (CANON_CLAUDE_TIMEOUT)") from e
            try:
                d = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else None
            except json.JSONDecodeError:
                d = None
            if not isinstance(d, dict):
                raise ClaudeCodeError(f"Claude Code 실행 실패 (종료 코드 {proc.returncode}): "
                                      f"{_explain((proc.stderr or proc.stdout).strip() or '출력 없음')}")
            tokens = self.last_usage = _cli_usage(d)
            self.served = _served(d) or self.served
            if d.get("is_error") or d.get("subtype") not in (None, "success"):
                raise ClaudeCodeError(f"Claude Code 오류: {_explain(str(d.get('result') or d.get('subtype') or d))}")
            raw = d.get("structured_output") if schema is not None else None
            if raw is None:
                raw = str(d.get("result") or "").strip()
                if not raw:
                    raise ClaudeCodeError("Claude Code 응답이 비었어요")
            self.last_raw = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
            out = _parse(schema, raw) if schema is not None else raw
        except Exception as e:
            usage.record(self, tokens, t, ok=False, error=e, attempt=attempt)
            raise
        usage.record(self, tokens, t, attempt=attempt)
        return out

    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        from .llm import SchemaMismatch, repair_prompt

        ask = prompt
        for attempt in range(2):
            self.last_attempts = attempt + 1
            try:
                return self._call(system, ask, schema, attempt + 1)
            except ValidationError as e:
                if attempt:
                    raise SchemaMismatch(schema, e, "Claude") from e
                ask = repair_prompt(prompt, self.last_raw, schema, e)
        raise AssertionError("unreachable")

    def text(self, system: str, prompt: str) -> str:
        self.last_attempts = 1
        return self._call(system, prompt)


# ---------- API 키: Messages API ----------

def api_model(model: str) -> str:
    """claude-api 가 쓸 모델. 단계 모델이 비어 Gemini 모델 이름이 넘어오면 Claude 기본 모델로 바꾼다 (비용 추정용)."""
    from . import settings

    if model.startswith("claude"):
        return model
    return settings.claude_model()[0] or DEFAULT_API_MODEL


def _api_usage(u: Any) -> dict | None:
    if u is None:
        return None
    cached = getattr(u, "cache_read_input_tokens", None) or 0
    prompt = (u.input_tokens or 0) + (getattr(u, "cache_creation_input_tokens", None) or 0) + cached
    return {"prompt_tokens": prompt, "completion_tokens": u.output_tokens or 0, "thought_tokens": 0, "cached_tokens": cached}


class ClaudeAPILLM:
    """Anthropic API 키로 Messages API 를 부른다. 구조화 출력은 output_config.format 으로 강제하고
    pydantic 으로 검증한다. 긴 본문도 끊기지 않게 스트리밍으로 받는다."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        import anthropic

        from . import settings

        key = api_key or settings.anthropic_key()[0]
        if not key:
            raise RuntimeError("Anthropic API 키가 없어요. 설정 화면에서 넣거나 ANTHROPIC_API_KEY 를 설정하세요.")
        self.client = anthropic.Anthropic(api_key=key, max_retries=3)
        self.model = model or settings.claude_model()[0] or DEFAULT_API_MODEL
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

    def _call(self, system: str, prompt: str, schema: type[BaseModel] | None = None, attempt: int = 1) -> Any:
        t, tokens = time.time(), None
        self.last_raw = ""
        req: dict[str, Any] = {"model": self.model, "max_tokens": MAX_TOKENS, "system": system,
                               "messages": [{"role": "user", "content": prompt}]}
        if schema is not None:
            req["output_config"] = {"format": {"type": "json_schema", "schema": strict_schema(schema)}}
        if self.model.startswith(FALLBACK_MODELS):
            req |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        try:
            with self.client.beta.messages.stream(**req) as stream:
                msg = stream.get_final_message()
            tokens = self.last_usage = _api_usage(msg.usage)
            if msg.stop_reason == "refusal":
                raise RuntimeError("Claude 가 이 요청을 거절했어요 (안전 분류기). 수위나 표현을 조정하거나 다른 백엔드로 돌리세요.")
            if msg.stop_reason == "max_tokens":
                raise RuntimeError(f"Claude 응답이 최대 길이({MAX_TOKENS} 토큰)에서 끊겼어요")
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
            if not text:
                raise RuntimeError(f"Claude 응답이 비었어요: stop_reason={msg.stop_reason}")
            self.last_raw = text
            out = _parse(schema, text) if schema is not None else text
        except Exception as e:
            usage.record(self, tokens, t, ok=False, error=e, attempt=attempt)
            raise
        usage.record(self, tokens, t, attempt=attempt)
        return out

    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        from .llm import SchemaMismatch, repair_prompt

        ask = prompt
        for attempt in range(2):
            self.last_attempts = attempt + 1
            try:
                return self._call(system, ask, schema, attempt + 1)
            except ValidationError as e:
                if attempt:
                    raise SchemaMismatch(schema, e, "Claude API") from e
                ask = repair_prompt(prompt, self.last_raw, schema, e)
        raise AssertionError("unreachable")

    def text(self, system: str, prompt: str) -> str:
        self.last_attempts = 1
        return self._call(system, prompt)
