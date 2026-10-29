"""LLM 프로바이더 추상화. 기본은 Gemini, 로컬(OpenAI 호환 서버)과 테스트용 mock 제공.

설정은 웹 설정 화면(~/.canon/config.json) 또는 환경 변수로 한다. 환경 변수가 우선이다.
  CANON_LLM    gemini(기본) | local | claude (Claude Code 구독 로그인) | claude-api (Anthropic API 키) | mock
  CANON_MODEL  Gemini 모델 이름 (기본 gemini-4-argon)
  GEMINI_API_KEY  Gemini API 키
  CANON_GEMINI_AUTH=vertex  키 대신 Google Cloud 서비스 계정으로 Vertex AI 의 Gemini 를 부른다
    (CANON_VERTEX_CREDENTIALS 또는 GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION)
  CANON_LOCAL_URL / CANON_LOCAL_MODEL / CANON_LOCAL_KEY  로컬 서버 (Ollama, llama.cpp, vLLM, LM Studio)
  CANON_LLM_PLAN / _WRITE / _CHECK / _STATE / _NAME / _REVISE  단계별 백엔드 (예: CANON_LLM_WRITE=local)
  CANON_MODEL_PLAN / _WRITE / _CHECK / _STATE / _NAME / _REVISE  단계별 모델 (예: CANON_MODEL_STATE=gemini-3.8-flash)
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from . import cancel, usage

T = TypeVar("T", bound=BaseModel)


class MissingKey(RuntimeError):
    """API 키가 없다. 웹은 서버 오류가 아니라 설정 안내로 보인다 (code no_key)."""


class LLM(Protocol):
    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T: ...
    def text(self, system: str, prompt: str) -> str: ...


def _inline_refs(schema: dict) -> dict:
    """pydantic JSON 스키마의 $defs/$ref 를 풀어서 단일 스키마로 만든다."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


class SchemaMismatch(RuntimeError):
    """다시 요청해도 모델 응답이 스키마와 맞지 않는다. 자동 집필은 이 오류에서 그 화를 멈추고 기다린다."""

    def __init__(self, schema: type[BaseModel], error: ValidationError, who: str = "모델"):
        self.schema, self.brief = schema.__name__, _brief(error)
        super().__init__(f"{who} 응답이 {self.schema} 형식과 맞지 않아요 (다시 요청해도 같음): {self.brief}")


def _brief(e: ValidationError, limit: int = 8) -> str:
    """검증 오류를 위치와 이유만 짧게. 입력값 전체는 길고 본문이 섞여 있어 뺀다."""
    errs = e.errors(include_url=False)
    parts = [f"{'.'.join(map(str, x['loc'])) or '(전체)'}: {x['msg']}" for x in errs[:limit]]
    return "; ".join(parts) + (f" 외 {len(errs) - limit}개" if len(errs) > limit else "")


def repair_prompt(prompt: str, raw: str, schema: type[BaseModel], error: ValidationError) -> str:
    """스키마와 맞지 않는 응답을 오류와 함께 돌려주며 형식만 고쳐 달라는 요청. 배치처럼 대화가 없는 곳에서도 쓴다."""
    return (f"{prompt}\n\n---\n앞선 응답이 {schema.__name__} JSON 형식과 맞지 않았습니다.\n"
            f"틀린 곳: {_brief(error, 20)}\n"
            "필수 칸을 모두 채우고, 객체여야 할 자리에 문자열을 넣지 마세요. "
            "내용은 살리고 형식만 고쳐 JSON 만 다시 내세요.\n\n"
            f"앞선 응답:\n{raw[:12000]}")


def _validate(schema: type[T], raw: str) -> T:
    return schema.model_validate_json(_FENCE_RE.sub("", raw.strip()))


def _usage(u: Any) -> dict | None:
    """Gemini 토큰 수. 생각(thinking) 토큰은 출력 요금으로 매겨져 따로 센다. 캐시된 토큰은 입력에 들어 있고 싸게 매겨진다."""
    if not u:
        return None
    return {"prompt_tokens": u.prompt_token_count or 0, "completion_tokens": u.candidates_token_count or 0,
            "thought_tokens": getattr(u, "thoughts_token_count", None) or 0,
            "cached_tokens": getattr(u, "cached_content_token_count", None) or 0}


def _vertex_client() -> Any:
    """서비스 계정 키 파일(없으면 gcloud 기본 자격 증명)로 Vertex AI 클라이언트를 만든다.
    키 파일은 설정에 경로만 있고, 여기서 google-auth 가 읽는다."""
    from google import genai

    from . import settings

    path = settings.vertex_credentials()[0]
    creds = None
    if path:
        if not os.path.isfile(path):
            raise MissingKey(f"서비스 계정 키 파일을 찾지 못했어요: {path}")
        from google.oauth2 import service_account

        try:
            creds = service_account.Credentials.from_service_account_file(
                path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
        except (ValueError, KeyError) as e:
            raise MissingKey(f"서비스 계정 키 파일이 아니에요 ({path}): {e}") from e
    project = settings.vertex_project()[0]
    if not project:
        raise MissingKey("Vertex AI 프로젝트 ID가 없어요. 설정 화면에서 서비스 계정 키 파일이나 프로젝트 ID를 넣으세요.")
    return genai.Client(vertexai=True, project=project, location=settings.vertex_location()[0], credentials=creds)


class GeminiLLM:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        from google import genai

        from . import settings

        # api_key 를 직접 넘기면(연구 화면 등) 늘 키 방식이다
        self.vertex = not api_key and settings.gemini_auth()[0] == "vertex"
        if self.vertex:
            self.client = _vertex_client()
        else:
            key = api_key or settings.api_key()[0]
            if not key:
                raise MissingKey("Gemini API 키가 없어요. 웹 설정 화면에서 넣거나 GEMINI_API_KEY를 설정하세요.")
            self.client = genai.Client(api_key=key)
        self.model = model or settings.model()[0]
        self.last_usage: dict | None = None  # 연구 화면에서 보여 줄 마지막 호출의 토큰 수
        self.last_attempts = 0
        self.last_raw = ""

    def check(self) -> None:
        """키와 모델 이름이 맞는지 가볍게 확인한다 (생성 호출 없음)."""
        self.client.models.get(model=self.model)

    def models(self) -> list[str]:
        """글을 생성할 수 있는 모델 이름. 설정 화면의 모델 목록에 쓴다."""
        out = []
        for m in self.client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if actions and "generateContent" not in actions:
                continue
            out.append(m.name.removeprefix("models/").removeprefix("publishers/google/models/"))
        return out

    def context_limit(self) -> int | None:
        return getattr(self.client.models.get(model=self.model), "input_token_limit", None)

    def count_tokens(self, text: str) -> int | None:
        return self.client.models.count_tokens(model=self.model, contents=text).total_tokens

    def _call(self, system: str, prompt: str, attempt: int = 1, parse: Any = None, **config: Any) -> Any:
        """한 번 부르고 사용량을 기록한다. parse 가 있으면 응답 글을 parse 한 값을 돌려주고, parse 가 실패해도
        (형식 불일치) 토큰은 쓴 것이라 실패로 기록한다."""
        cancel.check()  # 멈춘 작업은 다음 호출을 보내지 않는다
        from google.genai import types

        t, tokens = time.time(), None
        self.last_raw = ""
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system, **config),
            )
            tokens = self.last_usage = _usage(resp.usage_metadata)
            if not resp.text:
                raise RuntimeError(f"Gemini 응답이 비었어요: {resp.candidates[0].finish_reason if resp.candidates else resp}")
            self.last_raw = resp.text
            out = parse(resp.text) if parse else resp.text
        except Exception as e:
            usage.record(self, tokens, t, ok=False, error=e, attempt=attempt, prompt=prompt)
            raise
        usage.record(self, tokens, t, attempt=attempt, prompt=prompt)
        return out

    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        """구조화 출력이 어긋나면 (모델이 스키마를 무시하는 일이 있다) 오류를 알려 주고 한 번 더 받는다."""
        ask = prompt
        for attempt in range(2):
            self.last_attempts = attempt + 1
            try:
                return self._call(system, ask, attempt + 1, lambda raw: _validate(schema, raw),
                                  response_mime_type="application/json",
                                  response_json_schema=_inline_refs(schema.model_json_schema()))
            except ValidationError as e:
                if attempt:
                    raise SchemaMismatch(schema, e, "Gemini") from e
                ask = repair_prompt(prompt, self.last_raw, schema, e)
        raise AssertionError("unreachable")

    def text(self, system: str, prompt: str) -> str:
        self.last_attempts = 1
        return self._call(system, prompt)

    # ---------- Batch API (비용 절반, 결과까지 몇 분~최대 24시간) ----------

    @property
    def can_batch(self) -> bool:
        """Vertex AI 배치는 요청을 Cloud Storage · BigQuery 로만 받아 지금은 쓰지 않는다 (자동 집필은 일반 호출로)."""
        return not self.vertex

    def batch_submit(self, system: str, prompt: str, schema: type[BaseModel] | None, label: str,
                     hint: dict | None = None) -> str:
        """요청 하나짜리 배치 작업을 만들고 작업 이름을 돌려준다. hint 는 mock 용이라 쓰지 않는다.

        배치는 response_schema(예전부터 배치 문서에 있는 형식)로 스키마를 보낸다. 실제 실행에서 배치가
        response_json_schema 를 지키지 않고 목록 항목을 문자열로 낸 일이 있었다. SDK 가 스키마를 바꾸지
        못하거나 서버가 요청을 거절(400)하면 response_json_schema 로 보낸다."""
        from google.genai import errors

        def create(fmt: dict[str, Any]) -> Any:
            return self.client.batches.create(
                model=self.model,
                src=[{"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                      "config": {"system_instruction": system, **fmt}}],
                config={"display_name": label[:120]},
            )

        if schema is None:
            return create({}).name
        try:
            return create({"response_mime_type": "application/json", "response_schema": schema}).name
        except (TypeError, ValueError, errors.ClientError) as e:
            if isinstance(e, errors.ClientError) and e.code != 400:
                raise
            return create({"response_mime_type": "application/json",
                           "response_json_schema": _inline_refs(schema.model_json_schema())}).name

    def batch_poll(self, name: str) -> str | None:
        """끝났으면 응답 글, 아직이면 None. 실패, 취소, 만료면 오류를 낸다."""
        job = self.client.batches.get(name=name)
        state = getattr(job.state, "name", str(job.state))
        if state in BATCH_WAITING:
            return None
        if state != "JOB_STATE_SUCCEEDED":
            raise BatchGone(f"Gemini 배치 작업이 끝났어요 (상태 {state}): {job.error or ''}".rstrip(": "))
        out = (job.dest.inlined_responses or [None])[0] if job.dest else None
        if out is None or out.error or out.response is None:
            raise BatchGone(f"Gemini 배치 응답이 없어요: {out.error if out else job.dest}")
        self.last_usage = _usage(out.response.usage_metadata)
        if not out.response.text:
            raise BatchGone("Gemini 배치 응답이 비었어요")
        return out.response.text

    def batch_cancel(self, name: str) -> None:
        self.client.batches.cancel(name=name)


BATCH_WAITING = {"JOB_STATE_UNSPECIFIED", "JOB_STATE_QUEUED", "JOB_STATE_PENDING", "JOB_STATE_RUNNING",
                 "JOB_STATE_PAUSED", "JOB_STATE_UPDATING", "JOB_STATE_CANCELLING"}


class BatchGone(RuntimeError):
    """배치 작업이 확실히 끝났다 (실패, 취소, 만료, 빈 응답). 다시 물어도 결과가 없으니 이름을 버린다.
    이 밖의 조회 오류(연결, 시간 초과)는 잠깐의 문제로 보고 이름을 남겨 다시 묻는다."""


BATCH_POLL_RETRIES = 3


class Interrupted(Exception):
    """배치 결과를 기다리다 사용자가 멈추거나 서버가 다시 시작하려 한다. cancelled 면 배치 작업도 취소했다."""

    def __init__(self, cancelled: bool):
        super().__init__("배치 작업을 취소했어요" if cancelled else "배치 결과를 기다리다 멈췄어요")
        self.cancelled = cancelled


class BatchLLM:
    """LLM 인터페이스 그대로 배치를 쓴다. 호출 하나가 배치 작업 하나이고, 결과가 올 때까지 기다린다.

    names 는 slot -> 배치 작업 이름. 호출자가 저장해 두면 프로세스가 다시 시작해도 같은 slot 으로
    부를 때 새 작업을 만들지 않고 기다리던 작업에 다시 붙는다 (프롬프트가 같다는 전제).
    wait(초) 는 기다리고 나서 'stop'(작업 취소) | 'pause'(작업은 두고 멈춤) | '' 를 돌려준다.
    json 응답이 스키마와 맞지 않으면 오류를 붙여 '<slot>:fix' 로 한 번 더 배치를 보내고, note(글) 로 알린다.
    """

    def __init__(self, inner: Any, slot: str, names: dict[str, str], on_change: Any, wait: Any,
                 label: str = "canon", interval: float | None = None, note: Any = None):
        self.inner, self.slot, self.names, self.on_change, self.wait = inner, slot, names, on_change, wait
        self.label, self.note = label, note
        self.interval = interval if interval is not None else float(os.environ.get("CANON_BATCH_POLL", "30"))
        self.last_usage: dict | None = None
        self.last_attempts = 1
        self.last_prompt = ""  # 사용량 기록에 블록 크기를 남기려고
        self.model = getattr(inner, "model", "")

    def _run(self, system: str, prompt: str, schema: type[BaseModel] | None, hint: dict | None = None,
             slot: str | None = None) -> str:
        slot = slot or self.slot
        self.last_prompt = prompt
        name = self.names.get(slot)
        if not name:
            name = self.inner.batch_submit(system, prompt, schema, f"{self.label} {slot}", hint=hint)
            self.names[slot] = name
            self.on_change()
        fails = 0
        while True:
            try:
                raw = self.inner.batch_poll(name)
            except BatchGone as e:
                self.names.pop(slot, None)  # 끝난 작업에 다시 붙지 않게 한다
                self.on_change()
                usage.record(self.inner, None, ok=False, error=e, attempt=self.last_attempts, batch=True, prompt=prompt)
                raise
            except Exception as e:
                # 연결이 잠깐 끊긴 것일 수 있다. 서버 쪽 배치는 계속 돌므로 이름을 남기고 몇 번 다시 묻는다
                fails += 1
                if fails > BATCH_POLL_RETRIES:
                    raise RuntimeError(f"배치 결과를 묻지 못했어요 ({e}). 이어 가면 기다리던 배치에 다시 붙어요") from e
                why = self.wait(self.interval)
                if why:
                    raise Interrupted(cancelled=False)
                continue
            fails = 0
            if raw is not None:
                self.names.pop(slot, None)
                self.on_change()
                self.last_usage = getattr(self.inner, "last_usage", None)
                return raw
            why = self.wait(self.interval)
            if why == "stop":
                try:
                    self.inner.batch_cancel(name)
                finally:
                    self.names.pop(slot, None)
                    self.on_change()
                raise Interrupted(cancelled=True)
            if why:
                raise Interrupted(cancelled=False)

    def part(self, name: str) -> "BatchLLM":
        """같은 작업 기록(names)을 쓰는 다른 slot. 한 단계가 차례로 여러 번 부를 때(검수 넓히기) 서버를 다시 시작해도
        앞 호출의 slot 에 뒤 호출의 작업이 붙지 않게 한다."""
        out = copy.copy(self)
        out.slot = f"{self.slot}:{name}"
        return out

    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        fix = f"{self.slot}:fix"
        ask = prompt  # 고쳐 달라는 작업을 기다리던 중이면 (서버 재시작) 프롬프트는 쓰이지 않는다
        if fix not in self.names:
            self.last_attempts = 1
            raw = self._run(system, prompt, schema, hint)
            try:
                return self._done(_validate(schema, raw))
            except ValidationError as e:
                self._done(None, e)
                if self.note:
                    self.note(f"응답이 형식과 맞지 않아 ({_brief(e, 3)}) 오류를 알려 주고 한 번 더 배치로 요청해요")
                ask = repair_prompt(prompt, raw, schema, e)
        self.last_attempts = 2
        raw = self._run(system, ask, schema, hint, slot=fix)
        try:
            return self._done(_validate(schema, raw))
        except ValidationError as e:
            self._done(None, e)
            raise SchemaMismatch(schema, e, "Gemini 배치") from e

    def text(self, system: str, prompt: str) -> str:
        self.last_attempts = 1
        return self._done(self._run(system, prompt, None))

    def _done(self, out: Any, error: Exception | None = None) -> Any:
        """받아 온 배치 결과 하나를 기록한다 (형식이 어긋났어도 토큰은 썼다)."""
        usage.record(self.inner, self.last_usage, ok=error is None, error=error, attempt=self.last_attempts, batch=True,
                     prompt=self.last_prompt)
        return out


def _require_all(schema: Any) -> Any:
    """모든 object 의 속성을 required 로 만든다. 기본값이 있는 필드는 pydantic 스키마에서 선택 항목이라
    vLLM 등의 guided decoding 이 필드를 통째로 빼먹는다 (StyleProfile 이 sample_passages 만 오는 식)."""
    if isinstance(schema, dict):
        out = {k: _require_all(v) for k, v in schema.items()}
        if isinstance(out.get("properties"), dict):
            out["required"] = list(out["properties"])
        return out
    if isinstance(schema, list):
        return [_require_all(v) for v in schema]
    return schema


_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$")


def _last_user(messages: list[dict]) -> str:
    """사용량 기록용: 마지막 사용자 메시지 (고쳐 달라는 재요청이면 그 요청)."""
    for m in reversed(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"]
    return ""


def _local_usage(u: Any) -> dict | None:
    """OpenAI 호환 usage. 캐시된 프롬프트 토큰을 주는 서버(vLLM 등)도 있다."""
    if not isinstance(u, dict):
        return None
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return {**u, "cached_tokens": cached}


class LocalLLM:
    """OpenAI 호환 /v1/chat/completions 서버. 표준 라이브러리만 쓴다.

    구조화 출력은 response_format(json_schema) 로 강제하고 pydantic 으로 검증한다.
    검증에 실패하면 오류를 알려 주고 한 번 더 묻는다. 추론 모델의 <think> 블록은 지운다.
    """

    def __init__(self, base_url: str | None = None, model: str | None = None,
                 api_key: str | None = None, sampling: dict | None = None, timeout: float | None = None):
        from . import settings

        self.base_url = (base_url or settings.local_url()[0]).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.local_key()[0]
        self.sampling = sampling if sampling is not None else settings.local_sampling()
        self.timeout = timeout or float(os.environ.get("CANON_LOCAL_TIMEOUT", "900"))
        self._model = model or settings.local_model()[0]
        self.last_usage: dict | None = None  # 연구 화면에서 보여 줄 마지막 호출의 토큰 수
        self.last_attempts = 0
        self.last_raw = ""

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        """path 가 http 로 시작하면 그 주소를 그대로 쓴다 (/v1 밖의 /tokenize, /version)."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        url = path if path.startswith("http") else self.base_url + path
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            hint = ""
            if "context length" in detail or "max_model_len" in detail or "context window" in detail:
                hint = (" 프롬프트가 서버의 컨텍스트 한도를 넘었어요. 서버 한도를 올리거나"
                        " (vLLM --max-model-len, llama.cpp -c) 검수처럼 긴 단계는 Gemini 로 돌리세요 (CANON_LLM_CHECK=gemini).")
            raise RuntimeError(f"로컬 서버 오류 {e.code} ({url}): {detail}{hint}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"로컬 서버에 연결하지 못했어요 ({self.base_url}): {e.reason}") from e

    def models(self) -> list[str]:
        return [m["id"] for m in self._request("GET", "/models").get("data", [])]

    def _root(self) -> str:
        return re.sub(r"/v1$", "", self.base_url)

    def server_info(self) -> dict:
        """모델 목록과 컨텍스트 길이, 서버 종류. vLLM 은 max_model_len 과 /version 을 준다."""
        data = self._request("GET", "/models").get("data", [])
        models = [{"id": m["id"], "owned_by": m.get("owned_by", ""), "parent": m.get("parent"),
                   "max_model_len": m.get("max_model_len")} for m in data]
        try:
            version = self._request("GET", self._root() + "/version").get("version")
        except RuntimeError:
            version = None
        kinds = {m["owned_by"] for m in models} - {""}
        return {"url": self.base_url, "server": ", ".join(sorted(kinds)) or "알 수 없음", "version": version, "models": models}

    def context_limit(self) -> int | None:
        """모델의 최대 컨텍스트. LoRA 처럼 값이 없으면 부모 모델 값을 쓴다."""
        models = {m["id"]: m for m in self.server_info()["models"]}
        m = models.get(self.model) or {}
        return m.get("max_model_len") or (models.get(m.get("parent")) or {}).get("max_model_len")

    def count_tokens(self, text: str) -> int | None:
        """서버 토크나이저로 센다 (vLLM, llama.cpp). 지원하지 않으면 None."""
        for body in ({"model": self.model, "prompt": text}, {"content": text}):
            try:
                r = self._request("POST", self._root() + "/tokenize", body)
            except RuntimeError:
                continue
            if "count" in r:
                return r["count"]
            if isinstance(r.get("tokens"), list):
                return len(r["tokens"])
        return None

    @property
    def model(self) -> str:
        """설정이 비어 있으면 서버에 하나뿐인 모델을 쓴다."""
        if not self._model:
            names = self.models()
            if len(names) != 1:
                raise RuntimeError(f"로컬 모델 이름을 정하세요 (CANON_LOCAL_MODEL). 서버에 있는 모델: {names}")
            self._model = names[0]
        return self._model

    def check(self) -> None:
        names = self.models()
        if self._model and self._model not in names:
            raise RuntimeError(f"서버에 {self._model} 모델이 없어요. 있는 모델: {names}")
        self.model  # noqa: B018  모델 이름 확정

    def _chat(self, system: str, messages: list[dict], attempt: int = 1, parse: Any = None, **extra: Any) -> Any:
        """한 번 부르고 사용량을 기록한다. parse 는 GeminiLLM._call 과 같다."""
        cancel.check()
        t, tokens = time.time(), None
        try:
            body = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages], **extra}
            resp = self._request("POST", "/chat/completions", body)
            tokens = self.last_usage = _local_usage(resp.get("usage"))
            choice = (resp.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            content = _THINK_RE.sub("", content).strip()
            if not content:
                raise RuntimeError(f"로컬 모델 응답이 비었어요: finish_reason={choice.get('finish_reason')}")
            out = parse(content) if parse else content
        except Exception as e:
            usage.record(self, tokens, t, ok=False, error=e, attempt=attempt, prompt=_last_user(messages))
            raise
        usage.record(self, tokens, t, attempt=attempt, prompt=_last_user(messages))
        return out

    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        js = _require_all(_inline_refs(schema.model_json_schema()))
        fmt = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": js}}
        messages = [{"role": "user", "content": prompt}]

        def parse(raw: str) -> T:
            self.last_raw = _FENCE_RE.sub("", raw)  # 연구 화면이 검증 전 값을 본다
            return schema.model_validate_json(self.last_raw)

        for attempt in range(2):
            self.last_attempts = attempt + 1
            try:
                return self._chat(system, messages, attempt + 1, parse, response_format=fmt, temperature=0.3)
            except ValidationError as e:
                if attempt:
                    raise SchemaMismatch(schema, e, "로컬 모델") from e
                messages += [{"role": "assistant", "content": self.last_raw},
                             {"role": "user", "content": f"JSON 이 스키마와 맞지 않습니다. 오류를 고쳐 JSON 만 다시 내세요.\n{e}"}]
        raise AssertionError("unreachable")

    def text(self, system: str, prompt: str) -> str:
        self.last_attempts = 1
        return self._chat(system, [{"role": "user", "content": prompt}], **self.sampling)


def make_llm(provider: str, model: str | None = None) -> LLM:
    """model 이 비어 있으면 그 백엔드의 기본 모델(설정의 model 또는 local_model)을 쓴다."""
    if provider == "mock":
        from .mock import MockLLM

        return MockLLM()
    if provider == "local":
        return LocalLLM(model=model or None)
    if provider == "gemini":
        return GeminiLLM(model=model or None)
    if provider in ("claude", "claude-api"):
        from .claude import ClaudeAPILLM, ClaudeCodeLLM

        return ClaudeCodeLLM(model=model or None) if provider == "claude" else ClaudeAPILLM(model=model or None)
    raise ValueError(f"알 수 없는 LLM 프로바이더: {provider} (gemini | local | claude | claude-api | mock)")


def get_llm(stage: str | None = None) -> LLM:
    """stage: plan | write | check | state | name | revise | illustration. 단계별 백엔드와 모델 설정이 없으면 전체 설정을 쓴다.
    지금 작업의 작품(usage.scope)이 단계 프리셋을 골랐으면 그 프리셋의 단계 칸을 쓴다 (settings.project_preset)."""
    from . import settings

    llm = make_llm(settings.stage_provider(stage)[0], settings.stage_model(stage)[0])
    if stage:
        llm.stage = stage  # type: ignore[attr-defined]  # 사용량 기록이 단계를 적는다
    return llm


_PROMPT = {"prompt": True}  # 프롬프트에 넣지 않는 칸(인물 신체 프로필 등)을 모델이 빼게 하는 표시


def dump(model: BaseModel | list | dict) -> str:
    """프롬프트에 넣을 JSON 문자열."""
    if isinstance(model, BaseModel):
        data = model.model_dump(exclude_defaults=False, context=_PROMPT)
    elif isinstance(model, list):
        data = [m.model_dump(context=_PROMPT) if isinstance(m, BaseModel) else m for m in model]
    else:
        data = model
    return json.dumps(data, ensure_ascii=False, indent=2)
