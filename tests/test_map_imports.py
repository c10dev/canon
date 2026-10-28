"""지도 모듈 가져오기 그래프 테스트 (docs/map/modules.md 4절의 의존 방향): 순환이 없고, 생성기끼리 가져오지 않는다.
모듈 맨 위의 `from . import …` · `from .x import …` 만 본다. 함수 안에서 가져오는 것(옛 이름 travel.episode_block ·
atlas.episode_block 이 mapprompt 를 부르는 것)은 가져오는 순서에 걸리지 않아 세지 않는다. 실행: python -m pytest tests/test_map_imports.py"""
import ast
from pathlib import Path

CANON = Path(__file__).resolve().parent.parent / "canon"
MAP = {"atlas", "travel", "mapprompt", "towngen", "citygen", "moderngen", "roadnet", "osm", "bldgs", "geom", "blocks", "placekinds"}
GENERATORS = {"towngen", "citygen", "moderngen"}


def _imports(name: str) -> set[str]:
    """name 모듈이 맨 위에서 가져오는 canon 모듈."""
    out = set()
    for node in ast.parse((CANON / f"{name}.py").read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                out.add(node.module.split(".")[0])
            else:
                out.update(a.name for a in node.names)
    return out


def _graph() -> dict[str, set[str]]:
    return {m: _imports(m) & MAP for m in MAP}


def test_no_cycle():
    graph = _graph()
    done: set[str] = set()

    def walk(m: str, path: list[str]) -> None:
        if m in path:
            raise AssertionError("순환 가져오기: " + " → ".join([*path[path.index(m):], m]))
        if m in done:
            return
        for x in sorted(graph[m]):
            walk(x, [*path, m])
        done.add(m)

    for m in sorted(MAP):
        walk(m, [])


def test_generators_do_not_import_each_other():
    graph = _graph()
    for g in GENERATORS:
        assert not graph[g] & GENERATORS, f"{g} 가 다른 생성기를 가져온다: {sorted(graph[g] & GENERATORS)}"


def test_layers():
    graph = _graph()
    assert "travel" not in graph["atlas"] and "mapprompt" not in graph["atlas"]  # 위층(travel · 프롬프트 블록)을 가져오지 않는다
    assert "mapprompt" not in graph["travel"]
    assert graph["geom"] == set() and graph["blocks"] <= {"geom"} and graph["placekinds"] == set()
    assert "context" not in _imports("atlas") and "context" not in _imports("travel")  # 예산은 mapprompt 가 쓴다
