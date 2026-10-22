"""LLM 프로바이더 추상화. 기본은 Gemini, 테스트용 mock 제공.

설정은 웹 설정 화면(~/.canon/config.json) 또는 환경 변수로 한다. 환경 변수가 우선이다.
  CANON_LLM    gemini(기본) | mock
  CANON_MODEL  Gemini 모델 이름 (기본 gemini-2.5-pro)
  GEMINI_API_KEY  Gemini API 키
"""
from __future__ import annotations

import copy
import json
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

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


class GeminiLLM:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        from google import genai

        from . import settings

        key = api_key or settings.api_key()[0]
        if not key:
            raise RuntimeError("Gemini API 키가 없습니다. 웹 설정 화면에서 넣거나 GEMINI_API_KEY 를 설정하세요.")
        self.client = genai.Client(api_key=key)
        self.model = model or settings.model()[0]

    def check(self) -> None:
        """키와 모델 이름이 맞는지 가볍게 확인한다 (생성 호출 없음)."""
        self.client.models.get(model=self.model)

    def _call(self, system: str, prompt: str, **config: Any) -> str:
        from google.genai import types

        resp = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system, **config),
        )
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
        return schema.model_validate_json(raw)

    def text(self, system: str, prompt: str) -> str:
        return self._call(system, prompt)


def get_llm() -> LLM:
    from . import settings

    if settings.provider()[0] == "mock":
        from .mock import MockLLM

        return MockLLM()
    return GeminiLLM()


def dump(model: BaseModel | list | dict) -> str:
    """프롬프트에 넣을 JSON 문자열."""
    if isinstance(model, BaseModel):
        data = model.model_dump(exclude_defaults=False)
    elif isinstance(model, list):
        data = [m.model_dump() if isinstance(m, BaseModel) else m for m in model]
    else:
        data = model
    return json.dumps(data, ensure_ascii=False, indent=2)
