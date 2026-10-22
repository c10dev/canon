"""LLM 프로바이더 추상화. 기본은 Gemini, 로컬(OpenAI 호환 서버)과 테스트용 mock 제공.

설정은 웹 설정 화면(~/.canon/config.json) 또는 환경 변수로 한다. 환경 변수가 우선이다.
  CANON_LLM    gemini(기본) | local | mock
  CANON_MODEL  Gemini 모델 이름 (기본 gemini-4-argon)
  GEMINI_API_KEY  Gemini API 키
  CANON_LOCAL_URL / CANON_LOCAL_MODEL / CANON_LOCAL_KEY  로컬 서버 (Ollama, llama.cpp, vLLM, LM Studio)
  CANON_LLM_PLAN / _WRITE / _CHECK / _STATE  단계별 백엔드 (예: CANON_LLM_WRITE=local)
"""
from __future__ import annotations

import copy
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


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


def _usage(u: Any) -> dict | None:
    """Gemini 토큰 수. 생각(thinking) 토큰은 출력 요금으로 매겨져 따로 센다."""
    if not u:
        return None
    return {"prompt_tokens": u.prompt_token_count or 0, "completion_tokens": u.candidates_token_count or 0,
            "thought_tokens": getattr(u, "thoughts_token_count", None) or 0}


class GeminiLLM:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        from google import genai

        from . import settings

        key = api_key or settings.api_key()[0]
        if not key:
            raise RuntimeError("Gemini API 키가 없습니다. 웹 설정 화면에서 넣거나 GEMINI_API_KEY 를 설정하세요.")
        self.client = genai.Client(api_key=key)
        self.model = model or settings.model()[0]
        self.last_usage: dict | None = None  # 연구 화면에서 보여 줄 마지막 호출의 토큰 수
        self.last_attempts = 0

    def check(self) -> None:
        """키와 모델 이름이 맞는지 가볍게 확인한다 (생성 호출 없음)."""
        self.client.models.get(model=self.model)

    def context_limit(self) -> int | None:
        return getattr(self.client.models.get(model=self.model), "input_token_limit", None)

    def count_tokens(self, text: str) -> int | None:
        return self.client.models.count_tokens(model=self.model, contents=text).total_tokens

    def _call(self, system: str, prompt: str, **config: Any) -> str:
        from google.genai import types

        resp = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system, **config),
        )
        self.last_usage = _usage(resp.usage_metadata)
        if not resp.text:
            raise RuntimeError(f"Gemini 응답이 비었습니다: {resp.candidates[0].finish_reason if resp.candidates else resp}")
        return resp.text

    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        raw = self._call(
            system,
            prompt,
            response_mime_type="application/json",
            response_json_schema=_inline_refs(schema.model_json_schema()),
        )
        self.last_attempts = 1
        return schema.model_validate_json(raw)

    def text(self, system: str, prompt: str) -> str:
        return self._call(system, prompt)

    # ---------- Batch API (비용 절반, 결과까지 몇 분~최대 24시간) ----------

    def batch_submit(self, system: str, prompt: str, schema: type[BaseModel] | None, label: str,
                     hint: dict | None = None) -> str:
        """요청 하나짜리 배치 작업을 만들고 작업 이름을 돌려준다. hint 는 mock 용이라 쓰지 않는다."""
        config: dict[str, Any] = {"system_instruction": system}
        if schema is not None:
            config.update(response_mime_type="application/json",
                          response_json_schema=_inline_refs(schema.model_json_schema()))
        job = self.client.batches.create(
            model=self.model,
            src=[{"contents": [{"role": "user", "parts": [{"text": prompt}]}], "config": config}],
            config={"display_name": label[:120]},
        )
        return job.name

    def batch_poll(self, name: str) -> str | None:
        """끝났으면 응답 글, 아직이면 None. 실패, 취소, 만료면 오류를 낸다."""
        job = self.client.batches.get(name=name)
        state = getattr(job.state, "name", str(job.state))
        if state in BATCH_WAITING:
            return None
        if state != "JOB_STATE_SUCCEEDED":
            raise RuntimeError(f"Gemini 배치 작업이 {state} 로 끝났습니다: {job.error or ''}".rstrip(": "))
        out = (job.dest.inlined_responses or [None])[0] if job.dest else None
        if out is None or out.error or out.response is None:
            raise RuntimeError(f"Gemini 배치 응답이 없습니다: {out.error if out else job.dest}")
        self.last_usage = _usage(out.response.usage_metadata)
        if not out.response.text:
            raise RuntimeError("Gemini 배치 응답이 비었습니다")
        return out.response.text

    def batch_cancel(self, name: str) -> None:
        self.client.batches.cancel(name=name)


BATCH_WAITING = {"JOB_STATE_UNSPECIFIED", "JOB_STATE_QUEUED", "JOB_STATE_PENDING", "JOB_STATE_RUNNING",
                 "JOB_STATE_PAUSED", "JOB_STATE_UPDATING", "JOB_STATE_CANCELLING"}


class Interrupted(Exception):
    """배치 결과를 기다리다 사용자가 멈추거나 서버가 다시 시작하려 한다. cancelled 면 배치 작업도 취소했다."""

    def __init__(self, cancelled: bool):
        super().__init__("배치 작업을 취소했습니다" if cancelled else "배치 결과를 기다리다 멈췄습니다")
        self.cancelled = cancelled


class BatchLLM:
    """LLM 인터페이스 그대로 배치를 쓴다. 호출 하나가 배치 작업 하나이고, 결과가 올 때까지 기다린다.

    names 는 slot -> 배치 작업 이름. 호출자가 저장해 두면 프로세스가 다시 시작해도 같은 slot 으로
    부를 때 새 작업을 만들지 않고 기다리던 작업에 다시 붙는다 (프롬프트가 같다는 전제).
    wait(초) 는 기다리고 나서 'stop'(작업 취소) | 'pause'(작업은 두고 멈춤) | '' 를 돌려준다.
    """

    def __init__(self, inner: Any, slot: str, names: dict[str, str], on_change: Any, wait: Any,
                 label: str = "canon", interval: float | None = None):
        self.inner, self.slot, self.names, self.on_change, self.wait = inner, slot, names, on_change, wait
        self.label = label
        self.interval = interval if interval is not None else float(os.environ.get("CANON_BATCH_POLL", "30"))
        self.last_usage: dict | None = None
        self.last_attempts = 1
        self.model = getattr(inner, "model", "")

    def _run(self, system: str, prompt: str, schema: type[BaseModel] | None, hint: dict | None = None) -> str:
        name = self.names.get(self.slot)
        if not name:
            name = self.inner.batch_submit(system, prompt, schema, f"{self.label} {self.slot}", hint=hint)
            self.names[self.slot] = name
            self.on_change()
        while True:
            try:
                raw = self.inner.batch_poll(name)
            except Exception:
                self.names.pop(self.slot, None)  # 실패한 작업에 다시 붙지 않게 한다
                self.on_change()
                raise
            if raw is not None:
                self.names.pop(self.slot, None)
                self.on_change()
                self.last_usage = getattr(self.inner, "last_usage", None)
                return raw
            why = self.wait(self.interval)
            if why == "stop":
                try:
                    self.inner.batch_cancel(name)
                finally:
                    self.names.pop(self.slot, None)
                    self.on_change()
                raise Interrupted(cancelled=True)
            if why:
                raise Interrupted(cancelled=False)

    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        return schema.model_validate_json(_FENCE_RE.sub("", self._run(system, prompt, schema, hint).strip()))

    def text(self, system: str, prompt: str) -> str:
        return self._run(system, prompt, None)


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
                hint = (" 프롬프트가 서버의 컨텍스트 한도를 넘었습니다. 서버 한도를 올리거나"
                        " (vLLM --max-model-len, llama.cpp -c) 검수처럼 긴 단계는 Gemini 로 돌리세요 (CANON_LLM_CHECK=gemini).")
            raise RuntimeError(f"로컬 서버 오류 {e.code} ({url}): {detail}{hint}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"로컬 서버에 연결하지 못했습니다 ({self.base_url}): {e.reason}") from e

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
            raise RuntimeError(f"서버에 {self._model} 이 없습니다. 있는 모델: {names}")
        self.model  # noqa: B018  모델 이름 확정

    def _chat(self, system: str, messages: list[dict], **extra: Any) -> str:
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages], **extra}
        resp = self._request("POST", "/chat/completions", body)
        self.last_usage = resp.get("usage")
        choice = (resp.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        content = _THINK_RE.sub("", content).strip()
        if not content:
            raise RuntimeError(f"로컬 모델 응답이 비었습니다: finish_reason={choice.get('finish_reason')}")
        return content

    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        js = _require_all(_inline_refs(schema.model_json_schema()))
        fmt = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": js}}
        messages = [{"role": "user", "content": prompt}]
        for attempt in range(2):
            self.last_attempts = attempt + 1
            raw = self._chat(system, messages, response_format=fmt, temperature=0.3)
            self.last_raw = _FENCE_RE.sub("", raw)  # 연구 화면이 검증 전 값을 본다
            try:
                return schema.model_validate_json(self.last_raw)
            except ValidationError as e:
                if attempt:
                    raise RuntimeError(f"로컬 모델이 {schema.__name__} 형식을 맞추지 못했습니다: {e}") from e
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": f"JSON 이 스키마와 맞지 않습니다. 오류를 고쳐 JSON 만 다시 내세요.\n{e}"}]
        raise AssertionError("unreachable")

    def text(self, system: str, prompt: str) -> str:
        return self._chat(system, [{"role": "user", "content": prompt}], **self.sampling)


def make_llm(provider: str) -> LLM:
    if provider == "mock":
        from .mock import MockLLM

        return MockLLM()
    if provider == "local":
        return LocalLLM()
    if provider == "gemini":
        return GeminiLLM()
    raise ValueError(f"알 수 없는 LLM 프로바이더: {provider} (gemini | local | mock)")


def get_llm(stage: str | None = None) -> LLM:
    """stage: plan | write | check | state. 단계별 설정이 없으면 전체 provider 를 쓴다."""
    from . import settings

    return make_llm(settings.stage_provider(stage)[0])


def dump(model: BaseModel | list | dict) -> str:
    """프롬프트에 넣을 JSON 문자열."""
    if isinstance(model, BaseModel):
        data = model.model_dump(exclude_defaults=False)
    elif isinstance(model, list):
        data = [m.model_dump() if isinstance(m, BaseModel) else m for m in model]
    else:
        data = model
    return json.dumps(data, ensure_ascii=False, indent=2)
