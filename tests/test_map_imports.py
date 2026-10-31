"""지도 패키지(canon/maps/) 가져오기 그래프 테스트 (docs/map/modules.md 2절의 의존 방향): 순환이 없고, 생성기끼리 가져오지 않고,
아래층이 위층을 가져오지 않는다. 모듈 맨 위의 `from . import …` · `from .x import …` · `from .. import …` 만 본다.
모듈 이름은 canon/maps/ 기준 점 경로(gen.towngen, sources.osm)다. 실행: python -m pytest tests/test_map_imports.py"""
import ast
from pathlib import Path

CANON = Path(__file__).resolve().parent.parent / "canon"
MAPS = CANON / "maps"
GENERATORS = {"gen.towngen", "gen.citygen", "gen.moderngen"}
# 아래층 → 위층. 화살표는 언제나 더 낮은 층으로 간다.
TIERS = {
    "geom": 0, "kinds": 0,
    "blocks": 1, "sources.osm": 1, "gen.roadnet": 1, "buildings": 1, "routes": 1, "places": 1,
    "gen.towngen": 2, "gen.citygen": 2, "gen.moderngen": 2,
    "fill": 3,
    "layout": 4,
    "spots": 5, "travel": 5,
    "makers": 6, "prompt": 6,
    "view": 7,
}
UPPER = {"atlas", "web", "cli", "pipeline", "prompts", "mock", "autorun", "features", "birth"}  # 지도를 부르는 쪽


def _modules() -> list[str]:
    return sorted(".".join(f.relative_to(MAPS).with_suffix("").parts) for f in MAPS.rglob("*.py") if f.name != "__init__.py")


def _imports(mod: str) -> tuple[set[str], set[str]]:
    """mod 가 맨 위에서 가져오는 (지도 모듈, 지도 밖 canon 모듈)."""
    full = ["canon", "maps", *mod.split(".")[:-1]]
    inside, outside = set(), set()
    for node in ast.parse((MAPS / (mod.replace(".", "/") + ".py")).read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.ImportFrom) or node.level == 0:
            continue
        base = full[:len(full) - (node.level - 1)]
        if base[:2] != ["canon", "maps"]:
            outside.update([node.module.split(".")[0]] if node.module else [a.name for a in node.names])
            continue
        path = base[2:] + (node.module.split(".") if node.module else [])
        if node.module and not (MAPS / "/".join(path)).is_dir():
            inside.add(".".join(path))
        else:  # 패키지에서 모듈을 가져온다 (from . import geom, from .gen import towngen)
            inside.update(".".join([*path, a.name]) for a in node.names)
    return inside, outside


def _graph() -> dict[str, set[str]]:
    return {m: _imports(m)[0] for m in _modules()}


def test_every_module_has_a_tier():
    assert set(_modules()) == set(TIERS), "TIERS 에 새 지도 모듈의 층을 적는다"


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

    for m in graph:
        walk(m, [])


def test_imports_go_down():
    for m, deps in _graph().items():
        for d in deps:
            assert d in TIERS, f"{m} 가 모르는 지도 모듈을 가져온다: {d}"
            assert TIERS[d] < TIERS[m], f"{m}(층 {TIERS[m]}) 가 같거나 위층 {d}(층 {TIERS[d]}) 를 가져온다"


def test_generators_do_not_import_each_other():
    graph = _graph()
    for g in GENERATORS:
        assert not graph[g] & GENERATORS, f"{g} 가 다른 생성기를 가져온다: {sorted(graph[g] & GENERATORS)}"


def test_outside_modules():
    for m in _modules():
        outside = _imports(m)[1]
        assert not outside & UPPER, f"{m} 가 지도를 부르는 쪽을 가져온다: {sorted(outside & UPPER)}"
        if m != "prompt":
            assert "context" not in outside, f"{m}: 프롬프트 예산(context)은 prompt 만 쓴다"
    assert _imports("geom") == (set(), set()) and _imports("kinds") == (set(), set())


def test_facade_only_reexports_maps():
    tree = ast.parse((CANON / "atlas.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module != "__future__":
            assert node.level == 1 and node.module.startswith("maps."), f"공개 면은 canon/maps 만 가져온다: {node.module}"
        assert not isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign)), "공개 면에는 계산을 두지 않는다"
