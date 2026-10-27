"""도시 생성기 테스트 (canon/citygen.py): 재현성, 결과 모양, 길 연결, 집 겹침, 성벽 · 성문, 구역 종류, 이야기 장소 규칙.
실행: python -m pytest tests/test_citygen.py. 성능은 CANON_PERF=1 일 때만 잰다."""
import json
import math
import os
import time

import pytest

from canon import atlas, citygen, geom
from canon.schema import MapSpec

SPOTS = [{"key": "a", "name": "대광장", "kind": "center"}, {"key": "b", "name": "대성당", "kind": "temple"},
         {"key": "c", "name": "중앙 시장", "kind": "market"}, {"key": "d", "name": "부두", "kind": "shore"},
         {"key": "e", "name": "돌다리", "kind": "bridge"}, {"key": "f", "name": "백작 저택", "kind": "manor"},
         {"key": "g", "name": "왕도", "kind": "far"}, {"key": "h", "name": "황금 사자 여관", "kind": "inn"},
         {"key": "i", "name": "대장간", "kind": "smith"}, {"key": "j", "name": "빵집", "kind": "home"}]
COMBOS = [(size, water) for size in ("small", "medium") for water in ("none", "river", "lake", "sea")]


def _city(seed: int = 5, **kw) -> dict:
    return citygen.city(MapSpec(kind="city", seed=seed, **kw), SPOTS)


def _m(lo: dict, q) -> tuple:
    return (q[0] * lo["w"], q[1] * lo["h"])


def _ward_at(lo: dict, spot: dict) -> set:
    """이야기 장소가 들어 있는 구역 종류."""
    q = (spot["x"], spot["y"])
    return {wd["kind"] for wd in lo["wards"] if geom.inside(q, [tuple(p) for p in wd["shape"]])}


def test_city_is_reproducible():
    spec = MapSpec(kind="city", seed=42, water="river")
    a = json.dumps(citygen.city(spec, SPOTS), sort_keys=True)
    assert a == json.dumps(citygen.city(spec, SPOTS), sort_keys=True)
    assert a != json.dumps(citygen.city(spec.model_copy(update={"seed": 43}), SPOTS), sort_keys=True)
    with pytest.raises(ValueError):
        citygen.city(MapSpec(kind="village"), [])


@pytest.mark.parametrize("size,water", COMBOS)
def test_city_rules(size, water):
    lo = _city(size=size, water=water)
    # 올린 파일 · 마을과 같은 모양, 좌표는 0~1
    assert lo["generator"] == "canon-city" and lo["version"] == str(citygen.VERSION) and lo["seed"] == 5
    assert lo["roads"] and lo["buildings"] and lo["wards"]
    polys = lo["buildings"] + lo["fields"] + lo["greens"] + lo["squares"] + lo["water"] + [wd["shape"] for wd in lo["wards"]]
    for poly in polys:
        assert len(poly) >= 3 and all(0 <= v <= 1 for q in poly for v in q)
    lines = [r["points"] for r in lo["roads"]] + [r["points"] for r in lo["rivers"]] + [r["points"] for r in lo["walls"]]
    assert all(0 <= v <= 1 for ln in lines for q in ln for v in q) and all(0 <= v <= 1 for q in lo["trees"] for v in q)
    assert {r["kind"] for r in lo["roads"]} <= {"road", "bridge"} and all(r["width"] > 0 for r in lo["roads"])
    # 모든 길이 한 덩어리 (길찾기 그래프가 길 꼭짓점을 다 담는다)
    g = atlas.road_graph(lo)
    assert len(g["nodes"]) == len({(round(q[0] * lo["w"], 2), round(q[1] * lo["h"], 2)) for r in lo["roads"] for q in r["points"]})
    # 집끼리, 집과 길은 겹치지 않는다
    segs = geom.Grid(40)
    for r in lo["roads"]:
        for a, b in zip(r["points"], r["points"][1:]):
            a, b = _m(lo, a), _m(lo, b)
            segs.add(geom.bbox([a, b]), (a, b, r["width"] / 2))
    grid = geom.Grid(30)
    for i, poly in enumerate(lo["buildings"]):
        hs = [_m(lo, q) for q in poly]
        box = geom.bbox(hs)
        assert not any(geom.convex_overlap(hs, other, -0.01) for other in grid.near(box)), i  # 붙은 집은 맞닿기만
        grid.add(box, hs)
        assert not any(geom.poly_seg_near(hs, a, b, gap) for a, b, gap in segs.near(box, 12)), i
    # 성벽은 닫힌 선, 성문은 3~5개이고 성벽 위에 있다
    assert len(lo["walls"]) == 1
    wall = lo["walls"][0]["points"]
    assert len(wall) >= 5 and wall[0] == wall[-1]
    assert 3 <= len(lo["gates"]) <= 5 and all(gt in wall for gt in lo["gates"])
    # 구역 종류는 알려진 값, 성안 구역 수는 크기를 따른다
    kinds = [wd["kind"] for wd in lo["wards"]]
    assert set(kinds) <= set(citygen.WARD_KINDS)
    assert kinds.count("plaza") == 1 and kinds.count("temple") == 1
    inner = [k for k in kinds if k not in ("farm", "wood")]
    assert citygen.SIZES[size] <= len(inner) <= citygen.SIZES[size] * 1.6
    # 물: 바다면 물 다각형과 항구, 강이면 강 선
    assert bool(lo["rivers"]) == (water in ("river", "lake"))
    assert water != "sea" or (lo["water"] and "harbor" in kinds)
    # 집 수와 번호
    assert lo["houses"] == len(lo["numbers"]) and all(0 <= i < len(lo["buildings"]) for i in lo["numbers"])
    # 이야기 장소: 놓은 것과 못 놓은 것을 합치면 전부, 같은 자리에 겹치지 않는다
    put = {s["key"] for s in lo["spots"]}
    assert put | {m["key"] for m in lo["missing"]} == {s["key"] for s in SPOTS} and not put & {m["key"] for m in lo["missing"]}
    assert len({(s["x"], s["y"]) for s in lo["spots"]}) == len(lo["spots"])
    assert {"a", "b", "c", "f", "g", "h", "i", "j"} <= put


@pytest.mark.parametrize("water", ["none", "river", "sea"])
def test_story_places_go_to_their_wards(water):
    lo = _city(seed=11, size="medium", water=water)
    spot = {s["key"]: s for s in lo["spots"]}
    lost = {m["key"]: m["reason"] for m in lo["missing"]}
    assert "plaza" in _ward_at(lo, spot["a"])
    assert "temple" in _ward_at(lo, spot["b"])
    assert _ward_at(lo, spot["c"]) & {"market", "plaza"}
    assert "noble" in _ward_at(lo, spot["f"])
    g = spot["g"]
    assert min(g["x"], g["y"], 1 - g["x"], 1 - g["y"]) < 0.01  # 성 밖으로 나가는 간선 끝 (지도 가장자리)
    if water == "none":
        assert "물" in lost["d"] and "강" in lost["e"]
    else:
        assert "harbor" in _ward_at(lo, spot["d"])
    if any(r["kind"] == "bridge" and len(r["points"]) > 2 for r in lo["roads"]):
        assert "e" in spot
    assert lo["missing"] == [] or all(m["reason"].endswith("요") for m in lo["missing"])  # 해요체


def test_river_city_has_bridges():
    """강이 성안을 지나면 다리로 건넌다 (고정 시드 몇 개 가운데 하나라도)."""
    found = [lo for lo in (_city(seed=s, water="river") for s in (1, 2, 3))
             if any(r["kind"] == "bridge" for r in lo["roads"])]
    assert found
    lo = found[0]
    rv = [_m(lo, q) for q in lo["rivers"][0]["points"]]
    bridge = next(r for r in lo["roads"] if r["kind"] == "bridge")
    mid = _m(lo, bridge["points"][len(bridge["points"]) // 2])
    assert min(geom.seg_dist(mid, a, b) for a, b in zip(rv, rv[1:])) < lo["rivers"][0]["width"]


def test_size_grows_the_city():
    small, large = _city(size="small"), _city(size="large")
    assert small["houses"] < large["houses"] and small["w"] < large["w"]
    assert len(small["gates"]) <= len(large["gates"])


def test_city_summary_snapshot():
    """알고리즘을 바꾸면 이 값이 바뀐다. 그때 VERSION 을 올리고 함께 고친다."""
    assert citygen.VERSION == 1
    lo = _city(seed=7, water="river")
    assert (lo["houses"], len(lo["buildings"]), len(lo["roads"]), len(lo["wards"]), len(lo["gates"]), lo["retries"]) == SNAPSHOT
    sea = _city(seed=7, water="sea")
    assert (sea["houses"], len(sea["buildings"]), len(sea["roads"]), len(sea["wards"]), len(sea["gates"]), sea["retries"]) == SEA_SNAPSHOT


SNAPSHOT = (977, 979, 63, 81, 3, 0)
SEA_SNAPSHOT = (1182, 1184, 74, 57, 3, 0)


@pytest.mark.skipif(os.environ.get("CANON_PERF") != "1", reason="CANON_PERF=1 일 때만 잰다")
def test_city_speed():
    for size, limit in (("medium", 2.0), ("large", 4.0)):
        worst = 0.0
        for seed in range(1, 6):
            for water in ("none", "river", "sea"):
                t = time.perf_counter()
                _city(seed=seed, size=size, water=water)
                worst = max(worst, time.perf_counter() - t)
        assert worst < limit, (size, worst)


def test_spots_keep_out_of_each_other():
    lo = _city(seed=3, size="medium")
    pts = [_m(lo, (s["x"], s["y"])) for s in lo["spots"]]
    assert all(math.dist(p, q) >= 5 for i, p in enumerate(pts) for q in pts[i + 1:])
