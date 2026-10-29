"""AI 지도 설정 제안의 장소 종류 (명세서 08c): 지도 종류의 시대에 맞는 id 만 받는다 (pipeline.suggest_map, prompts.map_suggest_prompt, mock).
실행: python -m pytest tests/test_map_suggest.py"""
import os
import tempfile

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())
os.environ.setdefault("CANON_LLM", "mock")

from canon import cli, pipeline, placekinds, store  # noqa: E402
from canon.llm import get_llm  # noqa: E402
from canon.schema import MapPlaceGuess, MapSpec, MapSuggestion, StoryElement  # noqa: E402

from .test_mapgen import _Fixed, _project  # noqa: E402

OLD = set(placekinds.kind_ids("village"))
MODERN = set(placekinds.kind_ids("modern"))


def _modern_project():
    p = _project()
    p.elements += [StoryElement(id="el-21", kind="장소", name="강남역"), StoryElement(id="el-22", kind="장소", name="골목 편의점"),
                   StoryElement(id="el-23", kind="장소", name="한빛 아파트", description="주인공이 사는 곳")]
    return p


def _suggest(kind: str, places: list[MapPlaceGuess], spec: MapSpec | None = None):
    llm = _Fixed(MapSuggestion(kind=kind, size="medium", roads="cross", water="none", fields="few", forest="some", places=places))
    return pipeline.suggest_map(llm, _modern_project(), spec), llm.prompt


def test_mock_uses_kinds_of_the_map_era():
    p = _modern_project()
    modern = pipeline.suggest_map(get_llm("plan"), p, MapSpec(kind="modern"))
    got = {g["name"]: g["kind"] for g in modern["places"]}
    assert modern["kind"] == "modern" and set(got.values()) <= MODERN
    assert (got["강남역"], got["골목 편의점"], got["한빛 아파트"], got["하르덴 왕궁"]) == ("station", "convenience", "apartment", "far")
    assert got["물새집"] == "house"  # 현대에서 못 찾으면 house
    for kind in ("village", "city"):
        old = pipeline.suggest_map(get_llm("plan"), p, MapSpec(kind=kind))
        got = {g["name"]: g["kind"] for g in old["places"]}
        assert set(got.values()) <= OLD and got["달빛 주막"] == "inn" and got["흑송촌"] == "center"


def test_drops_kinds_outside_the_map_era():
    guesses = [MapPlaceGuess(name="강남역", kind="station"), MapPlaceGuess(name="달빛 주막", kind="inn"),
               MapPlaceGuess(name="물새집", kind="hotel"), MapPlaceGuess(name="하르덴 왕궁", kind="far", put=False),
               MapPlaceGuess(name="등대", kind="shore")]
    r, _ = _suggest("modern", guesses, MapSpec(kind="modern"))
    assert [(g["name"], g["kind"]) for g in r["places"]] == [("강남역", "station"), ("물새집", "hotel"), ("하르덴 왕궁", "far"), ("등대", "shore")]
    for kind in ("village", "city"):
        r, _ = _suggest(kind, guesses, MapSpec(kind=kind))
        assert [(g["name"], g["kind"]) for g in r["places"]] == [("달빛 주막", "inn"), ("하르덴 왕궁", "far"), ("등대", "shore")]


def test_switched_map_kind_checks_the_new_era():
    """화면에서 마을을 골랐어도 AI 가 현대 동네를 고르면 현대 목록으로 거른다 (거꾸로도 같다). 프롬프트에는 두 시대 목록이 모두 있다."""
    r, prompt = _suggest("modern", [MapPlaceGuess(name="달빛 주막", kind="restaurant"), MapPlaceGuess(name="흑송촌", kind="center")],
                         MapSpec(kind="village"))
    assert r["kind"] == "modern" and [(g["name"], g["kind"]) for g in r["places"]] == [("달빛 주막", "restaurant")]
    r, _ = _suggest("village", [MapPlaceGuess(name="달빛 주막", kind="restaurant"), MapPlaceGuess(name="흑송촌", kind="center")],
                    MapSpec(kind="modern"))
    assert r["kind"] == "village" and [(g["name"], g["kind"]) for g in r["places"]] == [("흑송촌", "center")]
    block = prompt.split("# 종류")[1].split("요구사항")[0]
    old, modern = block.split("## 현대 동네 (kind=modern)")
    assert "## 마을 · 도시 (kind=village, city)" in old and "- inn: 여관 · 주막" in old and "- station:" not in old
    assert "- station: 역" in modern and "- house: 집 · 단독주택" in modern and "- inn:" not in modern
    assert all(f"- {k}:" in modern for k in MODERN) and all(f"- {k}:" in old for k in OLD)
    assert modern.index("- park:") < modern.index("- shore:")  # 현대 종류 뒤에 두 시대 모두인 종류 (kinds_for 차례)
    assert "/ 현대 동네:" not in prompt and "현대 동네는 house" in prompt


def test_cli_gen_modern_ai(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    store.save("m", _modern_project())
    cli.main(["map", "m", "gen", "modern", "--ai", "--seed", "3", "-y"])
    out = capsys.readouterr().out
    assert out.startswith("AI 제안: ") and "현대 동네 (시드 3)" in out
    spec = store.load("m").atlas.spec
    kinds = {x.key: x.kind for x in spec.places}
    assert spec.kind == "modern" and spec.water == "river" and set(kinds.values()) <= MODERN
    assert (kinds["el-21"], kinds["el-22"], kinds["el-23"]) == ("station", "convenience", "apartment")
