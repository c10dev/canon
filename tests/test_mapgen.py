"""지도 만들기 테스트: 기하 도구(canon/geom.py), 마을 생성기(canon/towngen.py), 미리보기 · 적용(atlas), 웹, 명령줄.
실행: python -m pytest tests/test_mapgen.py. 성능은 CANON_PERF=1 일 때만 잰다."""
import importlib
import json
import math
import os
import random
import tempfile
import time

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())
os.environ.setdefault("CANON_LLM", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canon import atlas, cli, geom, store, towngen  # noqa: E402
from canon.schema import MapPin, MapPlace, MapSpec, Project, StoryElement  # noqa: E402

from .test_atlas import _played  # noqa: E402

SPOTS = [{"key": "a", "name": "흑송촌", "kind": "center"}, {"key": "b", "name": "서낭당", "kind": "temple"},
         {"key": "c", "name": "달빛 주막", "kind": "inn"}, {"key": "d", "name": "나루터", "kind": "shore"},
         {"key": "e", "name": "돌다리", "kind": "bridge"}]
COMBOS = [(size, water, roads) for size in ("small", "medium") for water in ("none", "river", "lake", "sea")
          for roads in ("line", "cross", "square")]


def _m(lo: dict, q) -> tuple:
    return (q[0] * lo["w"], q[1] * lo["h"])


# ---------- 기하 ----------

def test_voronoi_cells_cover_box_and_hold_their_points():
    rng = random.Random(3)
    pts = [(rng.uniform(0, 100), rng.uniform(0, 80)) for _ in range(150)]
    cells = geom.voronoi(pts, (0, 0, 100, 80))
    assert abs(sum(geom.area(c) for c in cells) - 8000) < 1e-6
    assert all(geom.inside(p, c) for p, c in zip(pts, cells))
    for t in geom.delaunay(pts):  # 외접원 안에 다른 점이 없다
        ux, uy, r2 = geom._circum(*(pts[i] for i in t))
        assert all((p[0] - ux) ** 2 + (p[1] - uy) ** 2 >= r2 - 1e-7 for j, p in enumerate(pts) if j not in t)
    relaxed = geom.lloyd(pts, (0, 0, 100, 80), 2)
    spread = lambda ps: max(geom.area(c) for c in geom.voronoi(ps, (0, 0, 100, 80)))  # noqa: E731
    assert spread(relaxed) < spread(pts)


def test_polygon_helpers():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    left, right = geom.split_convex(sq, (4, -1), (4, 11))
    assert abs(geom.area(left) + geom.area(right) - 100) < 1e-9 and {round(abs(geom.area(left))), round(abs(geom.area(right)))} == {40, 60}
    far = [(10.5, 0), (20, 0), (20, 10), (10.5, 10)]
    assert not geom.convex_overlap(sq, far) and geom.convex_overlap(sq, far, gap=1)
    assert geom.poly_seg_near(sq, (-5, 5), (15, 5), 0) and not geom.poly_seg_near(sq, (12, -5), (12, 15), 1)
    assert geom.seg_cross((0, 0), (10, 10), (0, 10), (10, 0))[2] == (5, 5)
    clipped = geom.clip_convex([(-5, -5), (5, -5), (5, 5), (-5, 5)], sq)
    assert set(clipped) == {(0, 0), (5, 0), (5, 5), (0, 5)} and geom.area(clipped) == 25
    r = geom.rect((0, 0), (0, 1), 4, 2)
    assert abs(abs(geom.area(r)) - 8) < 1e-9 and geom.bbox(r) == (-2, -1, 2, 1)
    pts = geom.poisson(random.Random(1), 100, 100, 10)
    assert all(math.dist(a, b) >= 10 for i, a in enumerate(pts) for b in pts[i + 1:])
    n = geom.Noise(random.Random(2))
    vals = [n.fbm(x / 13, y / 17) for x in range(40) for y in range(40)]
    assert -1.5 < min(vals) < 0 < max(vals) < 1.5


# ---------- 마을 생성기 ----------

def test_classify_place_kinds():
    cases = {"흑송촌": "center", "촌장 댁": "manor", "달빛 주막": "inn", "서낭당": "temple", "수산시장": "market", "등대": "shore",
             "하르덴 왕궁": "far", "돌다리": "bridge", "물새집": "home", "": "home"}
    assert {name: towngen.classify(name)[0] for name in cases} == cases
    assert towngen.classify("검은 문", "마을 어귀의 대장간") == ("smith", "대장간")  # 이름에 없으면 설명에서
    assert not towngen.default_put("far") and towngen.default_put("inn")


def test_village_is_reproducible():
    spec = MapSpec(seed=99, water="river", roads="square")
    a = json.dumps(towngen.village(spec, SPOTS), sort_keys=True)
    assert a == json.dumps(towngen.village(spec, SPOTS), sort_keys=True)
    assert a != json.dumps(towngen.village(spec.model_copy(update={"seed": 100}), SPOTS), sort_keys=True)
    with pytest.raises(ValueError):
        towngen.village(MapSpec(kind="city"), [])


@pytest.mark.parametrize("size,water,roads", COMBOS)
def test_village_rules(size, water, roads):
    lo = towngen.village(MapSpec(seed=5, size=size, water=water, roads=roads), SPOTS)
    # 올린 파일과 같은 모양, 좌표는 0~1
    assert lo["generator"] == "canon-village" and lo["roads"] and lo["buildings"]
    for poly in lo["buildings"] + lo["fields"] + lo["greens"]:
        assert len(poly) >= 3 and all(0 <= v <= 1 for q in poly for v in q)
    assert all(0 <= v <= 1 for q in lo["trees"] for v in q)
    # 모든 길이 한 덩어리 (길찾기 그래프가 길 꼭짓점을 다 담는다)
    g = atlas.road_graph(lo)
    assert len(g["nodes"]) == len({(round(q[0] * lo["w"], 2), round(q[1] * lo["h"], 2)) for r in lo["roads"] for q in r["points"]})
    # 집끼리, 집과 길은 겹치지 않는다
    houses = [[_m(lo, q) for q in poly] for poly in lo["buildings"]]
    grid = geom.Grid(30)
    for i, hs in enumerate(houses):
        assert not any(geom.convex_overlap(hs, other, -0.01) for other in grid.near(geom.bbox(hs)))  # 붙은 채는 맞닿기만
        grid.add(geom.bbox(hs), hs)
        for r in lo["roads"]:
            for a, b in zip(r["points"], r["points"][1:]):
                assert not geom.poly_seg_near(hs, _m(lo, a), _m(lo, b), r["width"] / 2), (i, r["kind"])
    # 물이 있는 종류만 물가 · 다리 장소를 놓는다
    put = {s["key"] for s in lo["spots"]}
    lost = {m["key"]: m["reason"] for m in lo["missing"]}
    assert {"a", "b", "c"} <= put
    assert ("d" in put) == (water != "none") and ("e" in put) == any(r["kind"] == "bridge" for r in lo["roads"])
    assert water != "river" or roads == "line" or "e" in put  # 한길은 강과 나란히 날 수 있다
    assert "e" not in lost or "강" in lost["e"]
    assert len({(s["x"], s["y"]) for s in lo["spots"]}) == len(lo["spots"])  # 같은 자리에 겹치지 않는다


def test_far_place_goes_to_the_road_out():
    lo = towngen.village(MapSpec(seed=3), [{"key": "k", "name": "왕도", "kind": "far"}])
    s = lo["spots"][0]
    assert min(s["x"], s["y"], 1 - s["x"], 1 - s["y"]) < 0.02  # 마을을 떠나는 간선 끝 (지도 가장자리)


def test_village_summary_snapshot():
    """알고리즘을 바꾸면 이 값이 바뀐다. 그때 VERSION 을 올리고 함께 고친다."""
    lo = towngen.village(MapSpec(seed=7, water="river"), SPOTS)
    assert towngen.VERSION == 1
    assert (lo["houses"], len(lo["buildings"]), len(lo["roads"]), lo["retries"]) == SNAPSHOT


SNAPSHOT = (53, 69, 29, 0)


@pytest.mark.skipif(os.environ.get("CANON_PERF") != "1", reason="CANON_PERF=1 일 때만 잰다")
def test_village_speed():
    for size, limit in (("medium", 0.5), ("large", 1.0)):
        worst = 0.0
        for seed in range(1, 6):
            t = time.perf_counter()
            towngen.village(MapSpec(seed=seed, size=size, water="river"), SPOTS)
            worst = max(worst, time.perf_counter() - t)
        assert worst < limit, (size, worst)


# ---------- 미리보기 · 적용 ----------

def _project() -> Project:
    p = _played()
    p.elements.append(StoryElement(id="el-9", kind="장소", name="달빛 주막"))
    p.elements.append(StoryElement(id="el-10", kind="장소", name="하르덴 왕궁"))
    return p


def test_gen_places_and_overrides():
    p = _project()
    rows = {x["key"]: x for x in atlas.gen_places(p)}
    assert rows["el-1"]["kind"] == "center" and rows["el-9"]["kind"] == "inn" and rows["el-2"]["kind"] == "shore"
    assert rows["el-10"]["kind"] == "far" and not rows["el-10"]["put"]
    spec = MapSpec(places=[MapPlace(key="el-9", kind="temple"), MapPlace(key="el-10", put=True), MapPlace(key="el-1", kind="nope")])
    rows = {x["key"]: x for x in atlas.gen_places(p, spec)}
    assert rows["el-9"]["kind"] == "temple" and rows["el-9"]["found"] == "inn"
    assert rows["el-10"]["put"] and rows["el-1"]["kind"] == "center"  # 모르는 종류 id 는 찾은 값으로
    info = atlas.gen_info(p)
    assert not info["made"] and info["spec"]["kind"] == "village" and info["options"]["water"]["sea"] == "바다"
    assert {"id": "inn", "label": "여관 · 주막"} in info["kinds"]


def test_generate_preview_and_apply(tmp_path):
    p = _project()
    atlas.set_pins(p, [MapPin(place="el-9", x=0.5, y=0.5), MapPin(place="w:수산시장", x=0.123, y=0.456)])
    spec = MapSpec(seed=11, water="sea")
    out = atlas.generate(p, spec)
    assert out["layout"]["seed"] == 11 and not p.atlas.layout  # 미리보기는 저장하지 않는다
    pins = {s["place"]: s for s in out["pins"]}
    assert pins["el-9"]["had"] and not pins["el-1"]["had"] and "el-10" not in pins
    assert {"houses", "buildings", "roads", "bridges", "width_m", "height_m"} <= set(out["info"])

    (tmp_path / "layout-1.json").write_text("{}")
    p.atlas.layout = "layout-1.json"
    old = atlas.apply_generated(tmp_path, p, spec, ["el-1"])
    assert old == "layout-1.json" and p.atlas.layout == "gen-village-11.json" and p.atlas.meters == 1.0
    assert p.atlas.spec.seed == 11 and p.atlas.spec.version == towngen.VERSION
    got = {pin.place: (pin.x, pin.y) for pin in p.atlas.pins}
    assert got["el-1"] == (pins["el-1"]["x"], pins["el-1"]["y"])
    assert got["el-9"] == (0.5, 0.5) and got["w:수산시장"] == (0.123, 0.456)  # 고르지 않은 자리는 그대로
    lo = atlas.load_layout(tmp_path, p)
    assert lo["seed"] == 11 and atlas.summary(p, lo)["layout"]["width_m"] == round(lo["w"])
    assert "지도 만들기, 시드 11" in atlas.describe(p, lo)
    assert atlas.apply_generated(tmp_path, p, spec, []) == ""  # 같은 파일을 다시 쓰면 지울 것이 없다


def test_old_project_has_no_spec():
    p = Project.model_validate({"meta": {"title": "옛 작품"}, "atlas": {"layout": "layout-1.json"}})
    assert p.atlas.spec is None and atlas.gen_info(p)["made"] is False


def test_web_generate(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store as st, web

    importlib.reload(st)
    importlib.reload(web)
    st.save("g", _project())
    c = TestClient(web.app)
    v = c.get("/api/projects/g/atlas").json()
    assert v["gen"]["made"] is False and len(v["gen"]["places"]) == len(v["places"])
    spec = {**v["gen"]["spec"], "seed": 21, "water": "river"}
    pv = c.post("/api/projects/g/atlas/generate/preview", json=spec).json()
    assert pv["layout"]["seed"] == 21 and pv["pins"]
    assert not (tmp_path / "g" / "map").exists()  # 미리보기는 파일을 만들지 않는다
    assert c.post("/api/projects/g/atlas/generate/preview", json={**spec, "kind": "realm"}).status_code == 400
    assert c.post("/api/projects/g/atlas/generate/preview", json={**spec, "water": "lava"}).status_code == 422

    pr = c.post("/api/projects/g/atlas/generate", json={"spec": spec, "pins": [pv["pins"][0]["place"]]}).json()
    assert pr["atlas"]["layout"] == "gen-village-21.json" and pr["atlas"]["spec"]["seed"] == 21
    assert [x["place"] for x in pr["atlas"]["pins"]] == [pv["pins"][0]["place"]]
    v = c.get("/api/projects/g/atlas").json()
    assert v["gen"]["made"] and v["layout"]["file"] == "gen-village-21.json"
    assert c.get("/api/projects/g/atlas/layout").json()["houses"] == pv["layout"]["houses"]

    pr = c.post("/api/projects/g/atlas/generate", json={"spec": {**spec, "seed": 22}, "pins": []}).json()
    assert pr["atlas"]["layout"] == "gen-village-22.json" and not (tmp_path / "g" / "map" / "gen-village-21.json").exists()
    from .test_atlas import _village

    pr = c.put("/api/projects/g/atlas/layout", json={"data": json.dumps(_village())}).json()
    assert pr["atlas"]["spec"] is None  # 파일을 올리면 만든 마을이 아니다
    assert c.get("/api/projects/g/atlas").json()["gen"]["made"] is False


def test_cli_map_gen(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _project()
    atlas.set_pins(p, [MapPin(place="el-9", x=0.5, y=0.5)])
    store.save("mapgen", p)
    cli.main(["map", "mapgen", "gen", "--seed", "8", "--size", "작음", "--water", "강", "-y"])
    out = capsys.readouterr().out
    assert "마을 (시드 8)" in out and "작음 · 교차로 · 강" in out
    assert "달빛 주막 → 여관 · 주막 자리 (지도에 놓은 자리가 있어 그대로 둬요" in out and "흑송촌 → 마을 가운데 자리" in out
    q = store.load("mapgen")
    assert q.atlas.spec.seed == 8 and q.atlas.spec.size == "small" and q.atlas.layout == "gen-village-8.json"
    assert {pin.place: (pin.x, pin.y) for pin in q.atlas.pins}["el-9"] == (0.5, 0.5)
    cli.main(["map", "mapgen", "gen", "--seed", "8", "--move", "-y"])  # 설정은 지난번 것 그대로, 옮기기
    q = store.load("mapgen")
    assert q.atlas.spec.size == "small" and {pin.place: (pin.x, pin.y) for pin in q.atlas.pins}["el-9"] != (0.5, 0.5)
    with pytest.raises(SystemExit) as e:
        cli.main(["map", "mapgen", "gen", "--water", "용암", "-y"])
    assert "--water 는 없음, 강, 호수, 바다 중 하나예요" in str(e.value)
