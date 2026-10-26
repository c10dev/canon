"""판단기: 글을 쓰지 않고 정해 둔 선택지 가운데 하나를 확률과 함께 고른다 (TypeSafe Jev 의 System One 방식).

검수 · 자료 고르기처럼 답이 정해진 판단을 긴 생성 호출 대신 싸게 한다. 지금은 연구 화면의 두 걸음 검수만 쓴다.
  LocalJudge  OpenAI 호환 서버(vLLM, llama.cpp)에 질문마다 출력 1토큰을 요청하고, 선택지 글자(A, B, C)의
              다음 토큰 확률(logprobs)을 읽는다. 공통 지시는 시스템 프롬프트 앞에 두어 서버의 앞부분 캐시가 맞게 한다.
  MockJudge   테스트용. contradicts 의 글이 질문에 있으면 두 번째 선택지를 높게 준다.
LLM 인터페이스와 따로 두지만 호출마다 usage.record 로 사용량 화면에 잡힌다 (단계 이름 judge).
"""
from __future__ import annotations

import contextvars
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from pydantic import BaseModel, Field

from . import prompts, usage

LABELS = "ABCDEFGH"


class Question(BaseModel):
    """판단 하나. state 는 이 질문만의 자료(근거 묶음), text 는 물음, options 는 고를 답."""
    id: str
    state: str = ""
    text: str
    options: list[str] = Field(min_length=2, max_length=len(LABELS))


class Answer(BaseModel):
    id: str
    choice: str = Field(description="가장 높은 선택지")
    probs: list[float] = Field(default_factory=list, description="options 와 같은 순서의 확률 (합 1)")
    mass: float = Field(1.0, description="모델이 선택지 글자에 준 확률의 합. 낮으면 모델이 엉뚱한 답을 내려 한 것")


class Judge(Protocol):
    def decide(self, system: str, questions: list[Question]) -> list[Answer]: ...


def _answer(q: Question, weights: list[float], mass: float = 1.0) -> Answer:
    total = sum(weights)
    probs = [w / total for w in weights] if total > 0 else [1 / len(q.options)] * len(q.options)
    best = max(range(len(probs)), key=lambda i: probs[i])
    return Answer(id=q.id, choice=q.options[best], probs=[round(x, 4) for x in probs], mass=round(mass, 4))


class MockJudge:
    """contradicts 에 든 글이 질문(자료 포함)에 나오면 두 번째 선택지, 아니면 첫 번째 선택지를 높게 준다."""

    def __init__(self, contradicts: list[str] | None = None):
        self.contradicts = [x for x in (contradicts or []) if x]
        self.calls = 0

    def decide(self, system: str, questions: list[Question]) -> list[Answer]:
        self.calls += len(questions)
        out = []
        for q in questions:
            hit = any(x in q.text or x in q.state for x in self.contradicts)
            w = [0.1] * len(q.options)
            w[1 if hit else 0] = 0.8
            out.append(_answer(q, w))
        return out


_LABEL_TOKEN = re.compile(r"^[\s▁Ġ(\[]*([A-H])[\s)\].:]*$")


def label_probs(top: list[dict], n: int) -> tuple[list[float], float]:
    """top_logprobs([{token, logprob}]) 에서 선택지 글자 A.. 의 확률. 같은 글자의 여러 토큰(' A', 'A')은 더한다."""
    w = [0.0] * n
    for t in top:
        m = _LABEL_TOKEN.match(str(t.get("token", "")))
        if not m:
            continue
        i = LABELS.index(m.group(1))
        if i < n:
            w[i] += math.exp(float(t.get("logprob", -100.0)))
    return w, sum(w)


class LocalJudge:
    """OpenAI 호환 /v1/chat/completions 서버의 logprobs 로 판단한다. 표준 라이브러리만 쓴다 (LocalLLM 의 요청을 재사용)."""

    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None,
                 workers: int | None = None, timeout: float | None = None):
        from .llm import LocalLLM

        self._llm = LocalLLM(base_url=base_url, model=model, api_key=api_key, sampling={}, timeout=timeout)
        self.workers = workers or int(os.environ.get("CANON_JUDGE_WORKERS", "4"))
        self.stage = "judge"
        self.calls = 0

    @property
    def _model(self) -> str:  # usage 기록이 모델 이름을 읽는다
        return self._llm._model

    @property
    def model(self) -> str:
        return self._llm.model

    @property
    def base_url(self) -> str:
        return self._llm.base_url

    def _one(self, system: str, q: Question) -> Answer:
        t, tokens = time.time(), None
        body = {"model": self.model, "max_tokens": 1, "temperature": 0, "logprobs": True, "top_logprobs": 20,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompts.judge_message(q.state, q.text, q.options)}]}
        try:
            resp = self._llm._request("POST", "/chat/completions", body)
            u = resp.get("usage")
            tokens = {**u, "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0} if isinstance(u, dict) else None
            choice = (resp.get("choices") or [{}])[0]
            content = ((choice.get("logprobs") or {}).get("content") or [{}])[0]
            top = content.get("top_logprobs") or ([content] if "token" in content else [])
            w, mass = label_probs(top, len(q.options))
            if not mass:  # logprobs 를 주지 않는 서버: 낸 글자 하나만 믿는다
                said = _LABEL_TOKEN.match(((choice.get("message") or {}).get("content") or "").strip()[:3])
                i = LABELS.index(said.group(1)) if said else -1
                if not 0 <= i < len(q.options):
                    raise RuntimeError(f"판단기가 선택지 글자로 답하지 않았어요: {(choice.get('message') or {}).get('content')!r}")
                w, mass = [1.0 if k == i else 0.0 for k in range(len(q.options))], 0.0
        except Exception as e:
            usage.record(self, tokens, t, ok=False, error=e)
            raise
        usage.record(self, tokens, t)
        return _answer(q, w, mass)

    def decide(self, system: str, questions: list[Question]) -> list[Answer]:
        self.calls += len(questions)
        self.model  # noqa: B018  모델 이름을 스레드 전에 정한다
        with ThreadPoolExecutor(max_workers=max(1, self.workers)) as ex:
            futs = [ex.submit(contextvars.copy_context().run, self._one, system, q) for q in questions]
            return [f.result() for f in futs]


def make_judge(provider: str, model: str | None = None, url: str | None = None, contradicts: list[str] | None = None) -> Judge:
    if provider == "mock":
        return MockJudge(contradicts)
    if provider == "local":
        return LocalJudge(base_url=url or None, model=model or None)
    raise ValueError(f"알 수 없는 판단기: {provider} (local | mock)")


def get_judge() -> Judge:
    """CANON_JUDGE(local | mock, 기본 local), CANON_JUDGE_URL / CANON_JUDGE_MODEL (비면 로컬 서버 설정)."""
    return make_judge(os.environ.get("CANON_JUDGE", "local"), os.environ.get("CANON_JUDGE_MODEL"),
                      os.environ.get("CANON_JUDGE_URL"))
