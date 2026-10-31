"""LLM 이 채우는 응답 형식에 dict 칸이 없는지 본다 (Gemini 구조화 출력이 받지 못한다).

응답 형식은 canon/ 코드에서 `.json(system, prompt, 형식)` 으로 부르는 곳을 AST 로 찾는다.
그 형식과 안에 든 모든 모델의 JSON 스키마를 훑어 열린 object(additionalProperties)가 있으면 실패한다.
"""
import ast
import importlib
from pathlib import Path

import pydantic

ROOT = Path(__file__).resolve().parent.parent
MODULES = ("canon.schema", "canon.pipeline", "canon.agent", "canon.setupchat", "canon.revlab", "canon.birth")


def _names(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.IfExp):
        return _names(node.body) + _names(node.orelse)
    return []


def _response_names():
    found = set()
    for path in (ROOT / "canon").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "json"):
                continue
            arg = node.args[2] if len(node.args) >= 3 else next((k.value for k in node.keywords if k.arg == "schema"), None)
            if arg is not None:
                found.update(_names(arg))
    found.discard("schema")  # LLM 구현 안에서 넘겨받은 형식을 그대로 다시 넘기는 곳
    return found


def _model(name):
    for mod in MODULES:
        obj = getattr(importlib.import_module(mod), name, None)
        if isinstance(obj, type) and issubclass(obj, pydantic.BaseModel):
            return obj
    raise AssertionError(f"응답 형식 {name} 을 {MODULES} 에서 찾지 못했어요")


def _open_objects(node, path, out):
    if isinstance(node, dict):
        if node.get("type") == "object" and node.get("additionalProperties") not in (None, False):
            out.append(path)
        for key, value in node.items():
            _open_objects(value, f"{path}/{key}", out)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _open_objects(value, f"{path}[{i}]", out)


def test_finds_response_schemas():
    names = _response_names()
    assert {"StateDelta", "PlotBatch", "EpisodeDraft", "ConsistencyReport"} <= names
    assert len(names) >= 40


def test_response_schemas_have_no_dict():
    bad = []
    for name in sorted(_response_names()):
        _open_objects(_model(name).model_json_schema(), name, bad)
    assert not bad, f"LLM 응답 형식에 dict 칸이 있어요: {bad}"


def test_detects_dict():
    class Bad(pydantic.BaseModel):
        tags: dict[str, str]

    found = []
    _open_objects(Bad.model_json_schema(), "Bad", found)
    assert found
