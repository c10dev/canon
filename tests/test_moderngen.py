"""현대 동네 생성기 테스트 (canon/moderngen.py): 재현성, 결과 모양, 길 연결, 건물 겹침, 블록 종류, 쓰임, 이야기 장소, 건물 정보.
실행: python -m pytest tests/test_moderngen.py."""
import json
import math

import pytest

from canon import atlas, bldgs, geom, moderngen, placekinds
from canon.schema import MapSpec

SPOTS = [{"key": "a", "name": "동네", "kind": "center"}, {"key": "b", "name": "교회", "kind": "temple"},
         {"key": "c", "name": "시장", "kind": "market"}, {"key": "d", "name": "강가", "kind": "river"},
         {"key": "e", "name": "다리", "kind": "bridge"}, {"key": "f", "name": "회장 저택", "kind": "manor"},
         {"key": "g", "name": "서울", "kind": "far"}, {"key": "h", "name": "모텔", "kind": "inn"},
         {"key": "i", "name": "공방", "kind": "smith"}, {"key": "j", "name": "주인공 집", "kind": "home"},
         {"key": "k", "name": "숲", "kind": "forest"}, {"key": "l", "name": "밭", "kind": "field"}]
COMBOS = [(size, water) for size in ("small", "medium", "large") for water in ("none", "river")]


def _town(seed: int = 5, **kw) -> dict:
    return moderngen.neighborhood(MapSpec(kind="modern", seed=seed, **kw), SPOTS)


def _m(lo: dict, q) -> tuple:
    return (q[0] * lo["w"], q[1] * lo["h"])


def test_neighborhood_is_reproducible():
    spec = MapSpec(kind="modern", seed=42, water="river")
    a = json.dumps(moderngen.neighborhood(spec, SPOTS), sort_keys=True)
    assert a == json.dumps(moderngen.neighborhood(spec, SPOTS), sort_keys=True)
    assert a != json.dumps(moderngen.neighborhood(spec.model_copy(update={"seed": 43}), SPOTS), sort_keys=True)
    with pytest.raises(ValueError):
        moderngen.neighborhood(MapSpec(kind="city"), [])


@pytest.mark.parametrize("size,water", COMBOS)
def test_neighborhood_rules(size, water):
    lo = _town(size=size, water=water)
    # 올린 파일 · 마을 · 도시와 같은 모양, 좌표는 0~1
    assert lo["generator"] == "canon-modern" and lo["version"] == str(moderngen.VERSION) and lo["seed"] == 5
    assert lo["roads"] and lo["buildings"] and lo["wards"] and lo["walls"] == [] and lo["gates"] == []
    polys = lo["buildings"] + lo["greens"] + lo["squares"] + lo["water"] + [wd["shape"] for wd in lo["wards"]]
    for poly in polys:
        assert len(poly) >= 3 and all(0 <= v <= 1 for q in poly for v in q)
    lines = [r["points"] for r in lo["roads"]] + [r["points"] for r in lo["rivers"]]
    assert all(0 <= v <= 1 for ln in lines for q in ln for v in q) and all(0 <= v <= 1 for q in lo["trees"] for v in q)
    assert {r["kind"] for r in lo["roads"]} <= {"road", "bridge"} and all(r["width"] > 0 for r in lo["roads"])
    # 모든 길이 한 덩어리 (길찾기 그래프가 길 꼭짓점을 다 담는다)
    g = atlas.road_graph(lo)
    assert len(g["nodes"]) == len({(round(q[0] * lo["w"], 2), round(q[1] * lo["h"], 2)) for r in lo["roads"] for q in r["points"]})
    # 길 폭: 대로 20m 넘게, 소로 · 골목은 그보다 좁다
    widths = sorted({r["width"] for r in lo["roads"]})
    assert widths[-1] >= 35 and widths[0] <= 8
    # 건물끼리, 건물과 길은 겹치지 않는다
    segs = geom.Grid(40)
    for r in lo["roads"]:
        for a, b in zip(r["points"], r["points"][1:]):
            a, b = _m(lo, a), _m(lo, b)
            segs.add(geom.bbox([a, b]), (a, b, r["width"] / 2))
    grid = geom.Grid(30)
    for i, poly in enumerate(lo["buildings"]):
        hs = [_m(lo, q) for q in poly]
        box = geom.bbox(hs)
        assert not any(geom.convex_overlap(hs, other, -0.01) for other in grid.near(box)), i
        grid.add(box, hs)
        assert not any(geom.poly_seg_near(hs, a, b, gap) for a, b, gap in segs.near(box, 25)), i
    # 블록 종류: 역 앞 하나, 아파트 · 빌라가 다 있고, 학교가 하나 이상
    kinds = [wd["kind"] for wd in lo["wards"]]
    assert set(kinds) <= set(moderngen.ZONES)
    assert kinds.count("station") == 1 and "apartment" in kinds and "villa" in kinds and "school" in kinds
    # 건물마다 필지 정보, 쓰임은 현대 쓰임, 층수는 1 이상
    assert len(lo["parts"]) == len(lo["buildings"]) == lo["houses"] == len(lo["numbers"])
    uses = {pt["use"] for pt in lo["parts"]}
    assert uses <= set(bldgs.MODERN) | {"home"} and {"apartment", "villa", "school", "station"} <= uses  # home: 단독주택
    assert all(pt["levels"] >= 1 and pt["part"] == "main" for pt in lo["parts"])
    assert all(pt["levels"] >= 12 for pt in lo["parts"] if pt["use"] == "apartment")
    # 물: 하천이면 강 선 · 물 · 다리
    assert bool(lo["rivers"]) == (water == "river")
    assert (water == "river") == any(r["kind"] == "bridge" for r in lo["roads"])
    # 이야기 장소: 놓은 것과 못 놓은 것을 합치면 전부, 같은 자리에 겹치지 않는다
    put = {s["key"] for s in lo["spots"]}
    assert put | {m["key"] for m in lo["missing"]} == {s["key"] for s in SPOTS} and not put & {m["key"] for m in lo["missing"]}
    assert len({(s["x"], s["y"]) for s in lo["spots"]}) == len(lo["spots"])
    assert all(0 <= s[k] <= 1 for s in lo["spots"] for k in ("x", "y"))
    assert {"a", "b", "c", "f", "g", "h", "i", "j"} <= put


def test_lake_and_sea_become_a_river():
    for water in ("lake", "sea"):
        assert _town(seed=3, size="small", water=water)["rivers"]


@pytest.mark.parametrize("water", ["none", "river"])
def test_story_places(water):
    lo = _town(seed=11, size="medium", water=water, forest="some")
    spot = {s["key"]: s for s in lo["spots"]}
    lost = {m["key"]: m["reason"] for m in lo["missing"]}
    station = next(wd for wd in lo["wards"] if wd["kind"] == "station")
    assert geom.inside((spot["a"]["x"], spot["a"]["y"]), [tuple(q) for q in station["shape"]])  # 마을 가운데 → 역 앞 광장
    g = spot["g"]
    assert min(g["x"], g["y"], 1 - g["x"], 1 - g["y"]) < 0.01  # 마을 밖 → 대로 끝 (지도 가장자리)
    park = [wd for wd in lo["wards"] if wd["kind"] == "park"]
    assert park and geom.inside((spot["k"]["x"], spot["k"]["y"]), [tuple(q) for q in park[0]["shape"]])
    assert spot["l"]["kind"] == "house" and "l" not in lost  # 밭은 현대 대응이 없어 집으로 읽는다
    if water == "none":
        assert "하천" in lost["d"] and "하천" in lost["e"]
    else:
        assert {"d", "e"} <= set(spot)
    assert all(m["reason"].endswith("요") for m in lo["missing"])  # 해요체
    # 장소가 놓인 건물은 장소 종류에 맞는 쓰임
    blds = bldgs.describe(lo, lo["seed"], "korea_modern")["blds"]
    by_place = {b.get("place"): b for b in blds if b.get("place")}
    assert by_place["b"]["use"] == "church" and by_place["h"]["use"] == "hotel" and by_place["c"]["use"] == "mart"


def test_size_grows_the_neighborhood():
    small, large = _town(size="small"), _town(size="large")
    assert small["houses"] < large["houses"] and small["w"] < large["w"]


def test_buildings_get_modern_info():
    """bldgs.describe: 쓰임 · 층수는 생성기 값, 사람은 주거 쓰임만, 거리 이름 · 번지를 짓는다."""
    lo = _town(seed=8, size="small")
    out = bldgs.describe(lo, lo["seed"], "korea_modern")
    blds, streets = out["blds"], out["streets"]
    assert len(blds) == len(lo["buildings"])
    for b, pt in zip(blds, lo["parts"]):
        assert b["floors"] == pt["levels"]
        if not b.get("place"):
            assert b["use"] == pt["use"]
        assert (b["people"] > 0) == (b["use"] in bldgs.MODERN_HOMES)
    names = [st["name"] for st in streets]
    assert all(names) and len(set(names)) == len(names)
    assert {st["kind"] for st in streets} >= {"main", "street"}
    assert all(st["name"].endswith("로") for st in streets if st["kind"] == "main")
    assert sum(1 for b in blds if b.get("no")) > 0.9 * len(blds)


def test_neighborhood_summary_snapshot():
    """알고리즘을 바꾸면 이 값이 바뀐다. 그때 VERSION 을 올리고 함께 고친다."""
    assert moderngen.VERSION == 2
    lo = _town(seed=7, size="medium")
    assert (lo["houses"], len(lo["roads"]), len(lo["wards"]), len(lo["trees"]), lo["retries"]) == SNAPSHOT
    rv = _town(seed=7, size="medium", water="river")
    assert (rv["houses"], len(rv["roads"]), len(rv["wards"]), len(rv["trees"]), rv["retries"]) == RIVER_SNAPSHOT


SNAPSHOT = (933, 91, 14, 902, 0)
RIVER_SNAPSHOT = (910, 87, 14, 771, 0)


def test_spots_keep_out_of_each_other():
    lo = _town(seed=3, size="medium", water="river")
    pts = [_m(lo, (s["x"], s["y"])) for s in lo["spots"]]
    assert all(math.dist(p, q) >= 5 for i, p in enumerate(pts) for q in pts[i + 1:])


def test_generate_modern_preview_and_apply(tmp_path):
    from canon import atlas
    from .test_mapgen import _project

    p = _project()
    spec = MapSpec(kind="modern", seed=3, size="small", water="sea")  # 현대 동네는 바다를 하천으로 본다
    out = atlas.generate(p, spec)
    lo = out["layout"]
    assert lo["generator"] == moderngen.GENERATOR and lo["rivers"] and lo["wards"] and lo["blds"] and not p.atlas.layout
    t = out["title"]
    assert t["kind"] == "동네" and t["unit"] == "건물" and t["houses"] == len(lo["buildings"])
    assert t["population"] == int(round(sum(b.get("people", 0) for b in lo["blds"]), -1)) > 0
    assert atlas.apply_generated(tmp_path, p, spec, []) == ""
    assert p.atlas.layout == "gen-modern-3.json" and p.atlas.spec.version == moderngen.VERSION
    saved = atlas.load_layout(tmp_path, p)
    assert "현대 동네 데이터 (지도 만들기, 시드 3)" in atlas.describe(p, saved)
    info = atlas.gen_info(p)
    assert {"id": "modern", "label": "현대 동네"} in info["maps"] and info["version"]["modern"] == moderngen.VERSION
    assert set(info["options"]["modern"]) == {"size", "water", "forest"} and info["wards"]["villa"] == "빌라촌"
    assert info["uses"]["villa"][0] == "빌라" and "villa" in info["modern"]


def test_cli_modern(tmp_path, monkeypatch, capsys):
    from canon import cli, store
    from .test_mapgen import _project

    monkeypatch.setattr(store, "ROOT", tmp_path)
    store.save("c", _project())
    cli.main(["map", "c", "gen", "modern", "--seed", "4", "--size", "작음", "--water", "하천", "-y"])
    out = capsys.readouterr().out
    assert "현대 동네 (시드 4): 건물" in out and "집 " not in out.split("\n")[0] and "작음 · 하천 · " in out
    assert store.load("c").atlas.layout == "gen-modern-4.json"
    with pytest.raises(SystemExit) as e:
        cli.main(["map", "c", "gen", "modern", "--roads", "광장", "-y"])
    assert "--roads 칸은 현대 동네에 쓰지 않아요" in str(e.value)


# 옛 id 가운데 현대 id 하나로 옮기는 것과 두 시대 모두인 것: 08b 전(VERSION 1)과 같은 자리 (seed 11, 보통, 하천, 공원 보통)
OLD_SAME = [{"key": "a", "name": "동네", "kind": "center"}, {"key": "b", "name": "교회", "kind": "temple"},
            {"key": "c", "name": "시장", "kind": "market"}, {"key": "d", "name": "강가", "kind": "river"},
            {"key": "e", "name": "다리", "kind": "bridge"}, {"key": "g", "name": "서울", "kind": "far"},
            {"key": "h", "name": "모텔", "kind": "inn"}, {"key": "i", "name": "공방", "kind": "smith"},
            {"key": "k", "name": "숲", "kind": "forest"}, {"key": "m", "name": "방앗간", "kind": "mill"}]
OLD_SPOTS = {"a": (0.525551, 0.335807, "station"), "b": (0.060541, 0.405032, "church"), "c": (0.523005, 0.40128, "mart"),
             "d": (0.522544, 0.707074, "river"), "e": (0.487133, 0.733663, "bridge"), "g": (0.003665, 0.275013, "far"),
             "h": (0.564858, 0.436309, "hotel"), "i": (0.973318, 0.985091, "factory"), "k": (0.327977, 0.889365, "forest"),
             "m": (0.911305, 0.983303, "factory")}
MODERN = [{"key": k, "name": placekinds.label(k), "kind": k} for k in placekinds.kind_ids("modern")]


def test_old_kinds_keep_their_spots():
    """옛 id 로 저장된 입력은 to_era 로 읽고, 대응이 하나인 종류는 예전과 같은 자리 · 같은 건물 쓰임에 놓인다."""
    lo = moderngen.neighborhood(MapSpec(kind="modern", seed=11, size="medium", water="river", forest="some"), OLD_SAME)
    assert {s["key"]: (s["x"], s["y"], s["kind"]) for s in lo["spots"]} == OLD_SPOTS and lo["missing"] == []
    by_place = {b["place"]: b["use"] for b in bldgs.describe(lo, lo["seed"], "korea_modern")["blds"] if b.get("place")}
    assert by_place == {"b": "church", "c": "mart", "h": "hotel", "i": "factory", "m": "factory"}


def test_old_kinds_that_merge():
    """여럿이 하나로 모이는 옛 id(우물 → 역, 저택 · 집 → 집, 밭 → 집)와 모르는 id 는 현대 id 로 놓인다 (자리는 08b 에서 바뀌었다)."""
    pls = [{"key": "a", "name": "동네", "kind": "center"}, {"key": "w", "name": "우물", "kind": "well"},
           {"key": "f", "name": "저택", "kind": "manor"}, {"key": "j", "name": "집", "kind": "home"},
           {"key": "l", "name": "밭", "kind": "field"}, {"key": "x", "name": "어딘가", "kind": "nowhere"},
           {"key": "y", "name": "빈칸", "kind": ""}]
    lo = moderngen.neighborhood(MapSpec(kind="modern", seed=11, size="medium"), pls)
    spot = {s["key"]: s for s in lo["spots"]}
    assert lo["missing"] == [] and spot["w"]["kind"] == "station"
    assert {spot[k]["kind"] for k in "fjlxy"} == {"house"}
    assert math.dist((spot["a"]["x"] * lo["w"], spot["a"]["y"] * lo["h"]), (spot["w"]["x"] * lo["w"], spot["w"]["y"] * lo["h"])) < 15  # 광장 옆
    by_place = {b["place"]: b["use"] for b in bldgs.describe(lo, lo["seed"], "korea_modern")["blds"] if b.get("place")}
    assert {by_place[k] for k in "fjlxy"} == {"home"}  # 단독주택


def test_kind_spots_cover_modern_kinds():
    assert set(moderngen.KIND_SPOTS) == set(placekinds.kind_ids("modern"))
    assert set(moderngen.USE_OF.values()) <= set(bldgs.MODERN)


@pytest.mark.parametrize("size,water,forest", [("medium", "river", "some"), ("large", "river", "many"), ("small", "none", "few")])
def test_modern_kinds(size, water, forest):
    """현대 종류마다 자리: 놓이거나, 못 놓으면 missing 에 해요체 까닭. 놓인 건물은 종류에 맞는 쓰임."""
    lo = moderngen.neighborhood(MapSpec(kind="modern", seed=11, size=size, water=water, forest=forest), MODERN)
    spot = {s["key"]: s for s in lo["spots"]}
    lost = {m["key"]: m["reason"] for m in lo["missing"]}
    assert set(spot) | set(lost) == {p["key"] for p in MODERN} and not set(spot) & set(lost)
    assert all(s["kind"] == s["key"] for s in lo["spots"])  # 현대 id 는 그대로 나온다
    assert all(r.endswith("요") for r in lost.values())
    assert len({(s["x"], s["y"]) for s in lo["spots"]}) == len(lo["spots"])
    blds = bldgs.describe(lo, lo["seed"], "korea_modern")["blds"]
    by_place = {b["place"]: b["use"] for b in blds if b.get("place")}
    for k, use in moderngen.USE_OF.items():
        assert by_place[k] == use, k
    assert by_place["school"] == "school" and by_place["apartment"] == "apartment" and by_place["villa"] == "villa"
    assert by_place["house"] == "home"

    def in_ward(key: str, kind: str) -> bool:
        return any(geom.inside((spot[key]["x"], spot[key]["y"]), [tuple(q) for q in wd["shape"]])
                   for wd in lo["wards"] if wd["kind"] == kind)
    assert in_ward("station", "station") and in_ward("school", "school")  # 역 → 역 앞 광장, 학교 → 학교 블록
    if water == "none":
        assert {"shore", "river", "bridge"} <= set(lost) and "하천" in lost["river"]
    else:
        assert {"shore", "river", "bridge"} <= set(spot)
    if forest == "few":  # 근린공원 없음
        assert "공원" in lost["park"] and "공원" in lost["forest"]
    else:
        assert in_ward("park", "park")
    if size != "small":
        assert set(lost) <= {"pond"}  # 연못은 공원에 따라 있거나 없다
