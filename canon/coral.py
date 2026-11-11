"""CoralBricks 추론 API 백엔드 (OpenAI 호환, https://www.coralbricks.ai/docs.md).

LocalLLM 의 요청 · 흘려 받기 · 구조화 출력을 그대로 쓰고, 주소 · 키 · 모델 · 추론 강도 · 오류 안내만 바꾼다.
키는 환경 변수 CORAL_API_KEY 또는 설정 파일 coral_api_key, 모델은 CANON_CORAL_MODEL 또는 설정 파일 coral_model.
사용량은 백엔드 이름 coralbricks 로 남고 usage.DEFAULT_PRICES 의 가격으로 센다.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from . import cancel
from .llm import BadKey, LocalLLM, MissingKey

BASE_URL = "https://inference.coralbricks.ai/v1"
DEFAULT_MODEL = "deepseek-v4.1-flash"
# 서버 /v1/models 는 'coralbricks/<이름>' 으로 준다. 요청과 사용량 기록에는 앞머리를 뗀 이름을 쓴다 (가격표 이름과 같게)
PREFIX = "coralbricks/"
MODELS = ("deepseek-v4.1-flash", "deepseek-v4.1-flash-value", "deepseek-v4.1-flash-fast")
KEY_HINT = "CoralBricks API 키를 받지 않았어요. 웹 설정의 AI 연결에서 키를 다시 넣거나 CORAL_API_KEY를 확인해 주세요."
NO_KEY_HINT = "CoralBricks API 키가 없어요. 웹 설정의 AI 연결에서 넣거나 CORAL_API_KEY를 설정하세요."
CARD_HINT = ("CoralBricks 계정에 결제 카드가 없어 호출이 막혔어요. "
             "https://www.coralbricks.ai/organization/billing 에서 카드를 등록한 뒤 다시 해 주세요.")
# 429 concurrency_limit(계정의 동시 요청 수) · rate_limit_exceeded 뒤 기다리는 초. 문서의 Retry-After 는 2초다
BUSY_WAITS = (2, 4, 8, 16, 30)
CREDIT_HINT = "CoralBricks 선불 잔액이 없어요. https://www.coralbricks.ai 에서 충전한 뒤 다시 해 주세요."


def bare(model: str) -> str:
    return model.removeprefix(PREFIX)


def explain(e: RuntimeError) -> RuntimeError:
    """LocalLLM 이 낸 오류를 CoralBricks 안내로 바꾼다. 키 오류는 BadKey(웹 code bad_key), 카드 없음은 카드 등록 안내, 잔액 없음은 충전 안내."""
    msg = str(e)
    if "card_required" in msg:  # 키는 맞지만 계정에 카드가 없다 (403). 키 안내로 보이면 엉뚱한 곳을 고치게 된다
        return RuntimeError(CARD_HINT)
    if "오류 401" in msg or "오류 403" in msg or "invalid_api_key" in msg or "missing_api_key" in msg:
        return BadKey(KEY_HINT)
    if "insufficient_credits" in msg:
        return RuntimeError(CREDIT_HINT)
    return RuntimeError(msg.replace("로컬 서버", "CoralBricks").replace("로컬 모델", "CoralBricks 모델")
                        .replace("CANON_LOCAL_TIMEOUT", "CANON_LOCAL_TIMEOUT(CoralBricks 도 이 값을 씀)"))


def busy(e: RuntimeError) -> bool:
    """기다렸다 다시 부를 429 인가. 잔액 없음(insufficient_credits)은 기다려도 풀리지 않는다."""
    msg = str(e)
    return "오류 429" in msg and "insufficient_credits" not in msg


def patient(call: Callable[[], dict]) -> dict:
    """요청 한도 429 면 BUSY_WAITS 만큼 기다려 다시 부른다. 기다리기 전에 멈추기 신호를 본다."""
    for wait in (*BUSY_WAITS, None):
        try:
            return call()
        except MissingKey:
            raise
        except RuntimeError as e:
            if wait is None or not busy(e):
                raise explain(e) from e
            cancel.check()
            cancel.say(f"CoralBricks 요청 한도에 걸려 {wait}초 기다려요")
            time.sleep(wait)
    raise AssertionError("unreachable")


class CoralLLM(LocalLLM):
    """CoralBricks 의 Chat Completions. effort 는 reasoning_effort 로 넘긴다 (비우면 보내지 않아 서버 기본값: 추론 없음)."""

    def __init__(self, model: str | None = None, api_key: str | None = None, effort: str = "", timeout: float | None = None):
        from . import settings

        key = api_key if api_key is not None else settings.coral_key()[0]
        if not key:
            raise MissingKey(NO_KEY_HINT)
        # 샘플링은 서버 기본값을 쓴다. 로컬 기본값의 min_p 는 OpenAI 규격에 없는 칸이다
        super().__init__(base_url=BASE_URL, model=bare(model or settings.coral_model()[0] or DEFAULT_MODEL),
                         api_key=key, sampling={}, timeout=timeout)
        self.effort = effort

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
        return patient(lambda: LocalLLM._request(self, method, path, body, timeout))

    def _stream(self, body: dict, on_chunk: Callable[[str], None]) -> dict:
        return patient(lambda: LocalLLM._stream(self, body, on_chunk))

    def _chat(self, system: str, messages: list[dict], attempt: int = 1, parse: Any = None,
              on_chunk: Callable[[str], None] | None = None, **extra: Any) -> Any:
        if self.effort:
            extra.setdefault("reasoning_effort", self.effort)
        return super()._chat(system, messages, attempt, parse, on_chunk, **extra)

    def models(self) -> list[str]:
        return [bare(m) for m in super().models()]

    def server_info(self) -> dict:
        info = super().server_info()
        return {**info, "server": "CoralBricks", "models": [{**m, "id": bare(m["id"])} for m in info["models"]]}

    def context_limit(self) -> int | None:
        return None  # /v1/models 가 vLLM 의 max_model_len 칸을 주지 않는다. 문서의 컨텍스트는 1M 토큰

    def count_tokens(self, text: str) -> int | None:
        return None  # /tokenize 가 없다

    def quota(self) -> dict:
        """선불 잔액 (GET /v1/quota). balance 는 USD."""
        return self._request("GET", "/quota", timeout=15)
