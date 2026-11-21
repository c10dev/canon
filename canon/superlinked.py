"""Superlinked SIE Serverless 추론 API 백엔드 (OpenAI 호환, https://superlinked.com/docs).

LocalLLM 의 요청 · 흘려 받기 · 구조화 출력을 그대로 쓰고, 주소 · 키 · 모델 · 다시 부르기 · 오류 안내만 바꾼다.
키는 환경 변수 SUPERLINKED_API_KEY 또는 설정 파일 superlinked_api_key, 모델은 CANON_SUPERLINKED_MODEL 또는 설정 파일 superlinked_model.
사용량은 백엔드 이름 superlinked 로 남고 가격표가 없어 0원으로 센다.
"""
from __future__ import annotations

import contextvars
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from . import cancel, llm
from .llm import BadKey, LocalLLM, MissingKey

BASE_URL = "https://api.superlinked.com/v1"
DEFAULT_MODEL = "google/gemma-4-31B-it:h100-96k-hires-out8k-no-spec"
DEADLINE_S = 900  # 429 · 503 을 다시 보내는 총 시간. 문서의 예시 값
DEFAULT_WAIT_S = 5  # Retry-After 가 정수가 아닐 때
FALLBACK_OUT = 8192  # 모델 정보에 max_output_tokens 가 없을 때
KEY_HINT = "Superlinked API 키를 받지 않았어요. 웹 설정의 AI 연결에서 키를 다시 넣거나 SUPERLINKED_API_KEY를 확인해 주세요."
NO_KEY_HINT = "Superlinked API 키가 없어요. 웹 설정의 AI 연결에서 넣거나 SUPERLINKED_API_KEY를 설정하세요."
RELAY_OFF_HINT = ("이 모델은 SIE Relay로만 돌아요. Superlinked 콘솔의 Settings → SIE Relay를 켜거나 다른 모델을 골라 주세요.")


def retry_wait(e: RuntimeError) -> float | None:
    """다시 보낼 오류면 기다릴 초, 아니면 None.
    LocalLLM 은 HTTPError 를 RuntimeError 로 바꾸므로 e.__cause__ 가 urllib.error.HTTPError 다.
    429 · 503 이고 Retry-After 가 있고 X-SIE-Fallback-Error 가 없을 때만 다시 보낸다 (Fallback 오류는 생성이 이미 돌았을 수 있다)."""
    cause = e.__cause__
    if not isinstance(cause, urllib.error.HTTPError) or cause.code not in (429, 503):
        return None
    headers = cause.headers
    if headers is None or headers.get("X-SIE-Fallback-Error") is not None:
        return None
    after = headers.get("Retry-After")
    if after is None:
        return None
    after = str(after).strip()
    return float(int(after)) if after.isdigit() else float(DEFAULT_WAIT_S)


def explain(e: RuntimeError) -> RuntimeError:
    """LocalLLM 이 낸 오류를 Superlinked 안내로 바꾼다. 키 오류는 BadKey(웹 code bad_key), 릴레이 꺼짐은 켜기 안내."""
    msg = str(e)
    if "THIRD_PARTY_SERVING_DISABLED" in msg:
        return RuntimeError(RELAY_OFF_HINT)
    if "invalid_api_key" in msg or "Unauthorized" in msg or "오류 401" in msg:
        return BadKey(KEY_HINT)
    return RuntimeError(msg.replace("로컬 서버", "Superlinked").replace("로컬 모델", "Superlinked 모델")
                        .replace("CANON_LOCAL_TIMEOUT", "CANON_LOCAL_TIMEOUT(Superlinked 도 이 값을 씀)"))


def patient(call: Callable[[], dict]) -> dict:
    """429 · 503 에 Retry-After 가 있으면 기다려 다시 부른다. 기다리기 전에 멈추기 신호를 본다. 처음 부른 때부터 DEADLINE_S 를 넘기면 그만둔다."""
    start = time.monotonic()
    while True:
        try:
            return call()
        except MissingKey:
            raise
        except RuntimeError as e:
            wait = retry_wait(e)
            if wait is None or time.monotonic() - start + wait > DEADLINE_S:
                raise explain(e) from e
            cancel.check()
            if getattr(e.__cause__, "code", None) == 429:
                cancel.say(f"Superlinked 요청 한도에 걸려 {wait:g}초 기다려요")
            else:
                cancel.say(f"Superlinked 모델을 준비하는 중이라 {wait:g}초 기다려요")
            time.sleep(wait)


class SuperlinkedLLM(LocalLLM):
    """Superlinked 의 Chat Completions. 추론 강도는 받지 않는다. max_tokens 는 늘 보낸다(안 보내면 서버가 1024 토큰에서 끊는다)."""

    def __init__(self, model: str | None = None, api_key: str | None = None, timeout: float | None = None):
        from . import settings

        key = api_key if api_key is not None else settings.superlinked_key()[0]
        if not key:
            raise MissingKey(NO_KEY_HINT)
        # 샘플링은 서버 기본값을 쓴다. 로컬 기본값의 min_p 는 OpenAI 규격에 없는 칸이다
        super().__init__(base_url=BASE_URL, model=model or settings.superlinked_model()[0] or DEFAULT_MODEL,
                         api_key=key, sampling={}, timeout=timeout)
        self._info: dict[str, dict] = {}

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
        """생성(POST)만 기다려 다시 보낸다. 모델 목록 · 정보(GET)는 설정 화면이 기다리지 않게 한 번만 부른다."""
        if method != "GET":
            return patient(lambda: LocalLLM._request(self, method, path, body, timeout))
        try:
            return LocalLLM._request(self, method, path, body, timeout)
        except MissingKey:
            raise
        except RuntimeError as e:
            raise explain(e) from e

    def _stream(self, body: dict, on_chunk: Callable[[str], None]) -> dict:
        return patient(lambda: LocalLLM._stream(self, body, on_chunk))

    def info(self, model: str | None = None) -> dict:
        """GET /models/{model} 의 응답. 실패하면 {}. 같은 객체 안에서는 모델별로 한 번만 부른다."""
        name = model or self.model
        if name not in self._info:
            try:
                got = self._request("GET", f"/models/{name}", timeout=llm.LOCAL_LIST_TIMEOUT)
            except RuntimeError:
                got = {}
            self._info[name] = got if isinstance(got, dict) else {}
        return self._info[name]

    def out_limit(self) -> int:
        """요청에 넣을 max_tokens. 모델 정보의 max_output_tokens, 없으면 FALLBACK_OUT."""
        return int(self.info().get("max_output_tokens") or FALLBACK_OUT)

    def _chat(self, system: str, messages: list[dict], attempt: int = 1, parse: Any = None,
              on_chunk: Callable[[str], None] | None = None, **extra: Any) -> Any:
        if "max_tokens" not in extra and not llm._out_cap.get():
            extra["max_tokens"] = self.out_limit()
        return super()._chat(system, messages, attempt, parse, on_chunk, **extra)

    def models(self) -> list[str]:
        """채팅 모델 id 만. 목록의 id 마다 모델 정보를 불러 outputs 에 tokens 가 있고 guard 가 아닌 것만 남긴다. 목록 차례를 지킨다."""
        ids = [m["id"] for m in self._request("GET", "/models", timeout=llm.LOCAL_LIST_TIMEOUT).get("data", [])]

        def detail(mid: str) -> dict:
            try:
                got = self._request("GET", f"/models/{mid}", timeout=llm.LOCAL_LIST_TIMEOUT)
            except RuntimeError:
                return {}  # 세부 호출 하나가 실패하면 그 id 는 뺀다
            return got if isinstance(got, dict) else {}

        if not ids:
            return []
        with ThreadPoolExecutor(max_workers=8) as pool:
            infos = list(pool.map(lambda mid: contextvars.copy_context().run(detail, mid), ids))
        return [mid for mid, d in zip(ids, infos)
                if "tokens" in (d.get("outputs") or []) and (d.get("capabilities") or {}).get("guard") is not True]

    def server_info(self) -> dict:
        info = super().server_info()
        keep = set(self.models())
        return {**info, "server": "Superlinked", "models": [m for m in info["models"] if m["id"] in keep]}

    def context_limit(self) -> int | None:
        return self.info().get("context_length") or None

    def count_tokens(self, text: str) -> int | None:
        return None  # /tokenize 가 없다
