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

from canon import atlas, citygen, cli, geom, moderngen, pipeline, prompts, store, towngen  # noqa: E402
from canon.llm import get_llm  # noqa: E402
from canon.schema import MapPin, MapPlace, MapPlaceGuess, MapSpec, MapSuggestion, Project, StoryElement  # noqa: E402

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
    cases = {"흑송촌": "center", "촌장 댁": "manor", "달빛 주막": "inn", "서낭당": "temple", "수산시장": "shore", "장터": "market", "등대": "shore",
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
    assert towngen.VERSION == 4
    assert (lo["houses"], len(lo["buildings"]), len(lo["roads"]), lo["retries"]) == SNAPSHOT
    sea = towngen.village(MapSpec(seed=7, water="sea"), SPOTS)
    assert (sea["houses"], len(sea["buildings"]), len(sea["roads"]), sea["retries"]) == SEA_SNAPSHOT


SNAPSHOT = (63, 89, 16, 0)
SEA_SNAPSHOT = (69, 93, 17, 0)


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
    assert not info["made"] and info["spec"]["kind"] == "village" and info["options"]["village"]["water"]["sea"] == "바다" and "lake" not in info["options"]["city"]["water"]
    assert {"id": "inn", "label": "여관 · 주막"} in info["kinds"]["village"] and info["eras"]["village"] == "old"


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
    assert "--water 값은 없음, 강, 호수, 바다 중 하나예요" in str(e.value)


# ---------- 도시 지도 (citygen 을 지도 만들기에 연결) ----------

def test_generate_city_preview_and_apply(tmp_path):
    p = _project()
    spec = MapSpec(kind="city", seed=3, size="small", water="lake")  # 도시는 호수를 강으로 본다
    out = atlas.generate(p, spec)
    lo = out["layout"]
    assert lo["generator"] == citygen.GENERATOR and lo["rivers"] and lo["walls"] and lo["wards"] and not p.atlas.layout
    assert out["info"]["wards"] == len(lo["wards"]) and out["info"]["gates"] == len(lo["gates"]) >= 3
    assert {s["place"] for s in out["pins"]} >= {"el-1", "el-9"} and "el-10" not in {s["place"] for s in out["pins"]}
    t = out["title"]
    assert t["kind"] == "도시" and t["population"] == int(round(sum(b.get("people", 0) for b in lo["blds"]), -1))  # 건물마다 센 사람의 합

    assert atlas.apply_generated(tmp_path, p, spec, ["el-1"]) == ""
    assert p.atlas.layout == "gen-city-3.json" and p.atlas.spec.kind == "city" and p.atlas.spec.version == citygen.VERSION
    saved = atlas.load_layout(tmp_path, p)
    assert saved["generator"] == citygen.GENERATOR and "도시 데이터 (지도 만들기, 시드 3)" in atlas.describe(p, saved)
    info = atlas.gen_info(p)
    assert info["made"] and info["spec"]["kind"] == "city" and info["version"]["city"] == citygen.VERSION
    assert {"id": "city", "label": "도시"} in info["maps"] and "roads" not in info["options"]["city"] and info["wards"]["noble"] == "귀족"
    assert atlas.summary(p, saved)["title"]["kind"] == "도시"
    with pytest.raises(ValueError, match="아직 만들 수 없는 지도"):
        atlas.generate(p, MapSpec(kind="realm"))


def test_web_and_cli_city(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store as st, web

    importlib.reload(st)
    importlib.reload(web)
    st.save("c", _project())
    c = TestClient(web.app)
    spec = {**c.get("/api/projects/c/atlas").json()["gen"]["spec"], "kind": "city", "seed": 9, "size": "small"}
    pv = c.post("/api/projects/c/atlas/generate/preview", json=spec).json()
    assert pv["layout"]["generator"] == "canon-city" and pv["info"]["gates"] and pv["title"]["kind"] == "도시"

    monkeypatch.setattr(store, "ROOT", tmp_path)
    cli.main(["map", "c", "gen", "city", "--seed", "4", "--size", "작음", "--water", "강", "-y"])
    out = capsys.readouterr().out
    assert "도시 (시드 4)" in out and "성문" in out and "작음 · 강 · " in out
    q = store.load("c")
    assert q.atlas.spec.kind == "city" and q.atlas.layout == "gen-city-4.json"
    cli.main(["map", "c", "gen", "--seed", "5", "-y"])  # 종류를 비우면 지난번 종류
    assert store.load("c").atlas.layout == "gen-city-5.json"
    with pytest.raises(SystemExit) as e:
        cli.main(["map", "c", "gen", "city", "--roads", "광장", "-y"])
    assert "--roads 칸은 도시에 쓰지 않아요" in str(e.value)


def test_suggest_map_kind():
    class Fake:
        def json(self, system, prompt, schema, hint=None):
            return MapSuggestion(kind="city", size="large", roads="cross", water="lake", fields="few", forest="few",
                                 places=[MapPlaceGuess(name="흑송촌", kind="center")], reason="성이 있는 도시예요.")

    r = pipeline.suggest_map(Fake(), _project())
    assert r["kind"] == "city" and r["water"] == "river" and r["places"][0]["key"] == "el-1"
    assert pipeline.suggest_map(get_llm("plan"), _project())["kind"] == "village"


def test_suggest_map_modern():
    """현대 동네: 호수 · 바다는 하천으로, 장소 종류는 같은 id 에 현대 동네 자리를 함께 적고, 화면에서 고른 지도 종류를 알린다."""
    for water, want in (("sea", "river"), ("lake", "river"), ("none", "none")):
        llm = _Fixed(MapSuggestion(kind="modern", size="medium", roads="cross", water=water, fields="few", forest="some",
                                   places=[MapPlaceGuess(name="달빛 주막", kind="inn")], reason="현대 배경이에요."))
        r = pipeline.suggest_map(llm, _project(), MapSpec(kind="modern"))
        assert (r["kind"], r["water"], r["places"][0]["kind"]) == ("modern", want, "inn")
    assert "## 현대 동네 (kind=modern)" in llm.prompt and "water: none(없음), river(하천)" in llm.prompt
    assert "- inn: 여관 · 주막 / 현대 동네: 호텔 · 모텔" in llm.prompt and "- field: 밭 · 농장 / 현대 동네: 없음" in llm.prompt
    assert "지금 고른 지도: 현대 동네 (kind=modern)" in llm.prompt
    assert "지도 화면에서 지금 고른" not in prompts.map_suggest_prompt(_project(), [], [], [], {})
    mock = pipeline.suggest_map(get_llm("plan"), _project(), MapSpec(kind="modern", water="sea"))
    assert (mock["kind"], mock["water"]) == ("modern", "river")  # 등대 · 수산시장이 바다를 바라도 현대 동네는 하천
    assert set(mock) >= set(moderngen.OPTIONS) and mock["fields"] in towngen.OPTIONS["fields"]


# ---------- 물 기본값 · AI 설정 제안 ----------

def test_water_default_follows_places():
    row = lambda kind, word, put=True: {"kind": kind, "word": word, "put": put}  # noqa: E731
    assert towngen.water_for([row("shore", "등대"), row("home", "")]) == "sea"
    assert towngen.water_for([row("shore", "나루"), row("bridge", "다리")]) == "river"
    assert towngen.water_for([row("pond", "연못"), row("shore", "등대", False)]) == "lake"  # 놓지 않는 장소는 세지 않는다
    assert towngen.water_for([row("shore", "등대"), row("river", "강")]) == "sea"  # 같으면 바다
    assert towngen.water_for([row("inn", "주막")]) == "none"
    p = _project()  # 등대 · 수산시장
    assert atlas.default_spec(p).water == "sea" and atlas.gen_info(p)["spec"]["water"] == "sea"
    p.atlas.spec = MapSpec(water="none", seed=4)
    assert atlas.default_spec(p).water == "none"  # 만든 적이 있으면 그 입력 그대로


class _Fixed:
    """정해 둔 제안을 돌려주는 LLM."""

    def __init__(self, out):
        self.out = out
        self.prompt = ""

    def json(self, system, prompt, schema, hint=None):
        self.prompt = prompt
        return self.out


def test_suggest_map_cleans_names_and_kinds():
    p = _project()
    p.elements.append(StoryElement(id="el-11", kind="장소", name="검은 파도", description="부둣가 선술집"))
    llm = _Fixed(MapSuggestion(size="small", roads="line", water="sea", fields="few", forest="many", reason=" 등대가 있어요. ", places=[
        MapPlaceGuess(name="검은 파도", kind="inn", note="선술집"), MapPlaceGuess(name="흑송 마을", kind="center"),
        MapPlaceGuess(name="하르덴 왕궁", kind="far", put=False), MapPlaceGuess(name="없는 곳", kind="inn"),
        MapPlaceGuess(name="등대", kind="lighthouse"), MapPlaceGuess(name="검은 파도", kind="home")]))
    r = pipeline.suggest_map(llm, p)
    assert (r["size"], r["roads"], r["water"], r["reason"]) == ("small", "line", "sea", "등대가 있어요.")
    assert [(g["key"], g["kind"], g["put"], g["note"]) for g in r["places"]] == [
        ("el-11", "inn", True, "선술집"), ("el-1", "center", True, ""), ("el-10", "far", False, "")]  # 다른 이름도 키로, 모르는 곳 · 종류 · 겹친 것은 뺀다
    assert "- 검은 파도: 부둣가 선술집" in llm.prompt and "water: none(없음), river(강), lake(호수), sea(바다)" in llm.prompt
    assert "- inn: 여관 · 주막" in llm.prompt
    with pytest.raises(ValueError):
        pipeline.suggest_map(llm, Project())
    mock = pipeline.suggest_map(get_llm("plan"), p)
    assert mock["water"] == "sea" and {g["key"] for g in mock["places"]} == {pl["key"] for pl in atlas.places(p)}


def test_map_suggest_prompt_has_setting():
    p = _project()
    text = prompts.map_suggest_prompt(p, atlas.gen_places(p), atlas.places(p), [(c, l) for c, l, _ in towngen.CATEGORIES],
                                  {"village": towngen.OPTIONS, "city": citygen.OPTIONS})
    assert f"배경: {p.world.setting}" in text and "장르: " in text and "- 흑송촌 (다른 이름: 흑송 마을): 산 아래 마을" in text
    assert "## 도시 (kind=city)" in text and "roads" not in text.split("## 도시")[1].split("요구사항")[0]
    text = prompts.map_suggest_prompt(p, atlas.gen_places(p), atlas.places(p), [(c, l) for c, l, _ in towngen.CATEGORIES],
                                      {k: m[1].OPTIONS for k, m in atlas.MAKERS.items()}, moderngen.PLACE_KINDS)
    assert "## 현대 동네 (kind=modern)" in text and "modern(현대 동네)" in text
    assert set(moderngen.PLACE_KINDS) == set(towngen.CATEGORY_IDS)  # 종류마다 현대 동네 자리


def test_web_suggest_and_cli_ai(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store as st, web

    importlib.reload(st)
    importlib.reload(web)
    st.save("s", _project())
    c = TestClient(web.app)
    spec = c.get("/api/projects/s/atlas").json()["gen"]["spec"]
    assert spec["water"] == "sea"
    r = c.post("/api/projects/s/atlas/generate/suggest", json=spec).json()
    assert r["water"] == "sea" and r["places"] and r["reason"]
    assert st.load("s").atlas.spec is None  # 제안은 저장하지 않는다

    monkeypatch.setattr(store, "ROOT", tmp_path)
    cli.main(["map", "s", "gen", "--ai", "--seed", "2", "--size", "큼", "-y"])
    out = capsys.readouterr().out
    assert out.startswith("AI 제안: ") and "큼 · 광장 · 바다" in out  # 직접 적은 크기가 이기고, 나머지는 AI 제안
    q = store.load("s")
    assert q.atlas.spec.size == "large" and q.atlas.spec.roads == "square" and {x.key for x in q.atlas.spec.places} >= {"el-1", "el-2"}


COAST = [{"key": "a", "name": "흑송촌", "kind": "center"}, {"key": "l", "name": "등대", "kind": "shore", "word": "등대"},
         {"key": "f", "name": "수산시장", "kind": "shore", "word": "수산시장"}, {"key": "b", "name": "모래 해변", "kind": "shore", "word": "해변"}]


@pytest.mark.parametrize("size,seed", [(size, seed) for size in ("small", "medium", "large") for seed in (1, 2, 3)])
def test_sea_village_hugs_the_coast(size, seed):
    """바닷가 마을: 가운데가 해안 가까이, 바다로 가는 길 끝에 부두, 등대 · 해변은 물가, 수산시장은 부두 옆."""
    lo = towngen.village(MapSpec(seed=seed, size=size, water="sea"), COAST)
    sea = [_m(lo, q) for q in lo["water"][0]]
    coast = [q for q in sea if 1 < q[0] < lo["w"] - 1 and 1 < q[1] < lo["h"] - 1]
    to_sea = lambda q: min(math.dist(q, c) for c in coast)  # noqa: E731
    at = {s["key"]: _m(lo, (s["x"], s["y"])) for s in lo["spots"]}
    assert to_sea(at["a"]) < 75  # 마을 가운데
    assert to_sea(at["l"]) < 10 and to_sea(at["b"]) < 10  # 등대 · 해변은 물가
    piers = [r for r in lo["roads"] if r["kind"] == "bridge"]
    assert len(piers) == 1 and geom.inside(_m(lo, piers[0]["points"][-1]), sea)  # 부두 끝은 바다 위
    root = _m(lo, piers[0]["points"][0])
    assert math.dist(at["f"], root) < 60  # 수산시장은 부두 옆
    assert any(geom.inside(at["l"], [_m(lo, q) for q in b]) for b in lo["buildings"])  # 등대 탑이 있다
    assert len(lo["squares"]) >= 1  # 부둣가 빈터


def test_shore_place_without_harbor_goes_to_waterline():
    lo = towngen.village(MapSpec(seed=4, water="lake"), [{"key": "n", "name": "나루터", "kind": "shore", "word": "나루"}])
    lake = [_m(lo, q) for q in lo["water"][0]]
    q = _m(lo, (lo["spots"][0]["x"], lo["spots"][0]["y"]))
    assert min(math.dist(q, c) for c in lake) < 45 and not any(r["kind"] == "bridge" for r in lo["roads"])  # 호수에는 부두를 내지 않는다


def test_lighthouse_needs_the_sea():
    lo = towngen.village(MapSpec(seed=2, water="river"), [{"key": "l", "name": "등대", "kind": "shore", "word": "등대"}])
    assert not lo["spots"] and lo["missing"] == [{"key": "l", "name": "등대", "reason": "바다가 없어요. 물을 바다로 바꿔 보세요"}]


@pytest.mark.parametrize("forest", ["few", "some", "many"])
def test_trees_and_fields_keep_their_place(forest):
    """나무는 밭 · 집 · 물 · 길 위에 서지 않고, 숲이 많을수록 나무가 많다. 밭은 마을 둘레에 모인다."""
    spec = MapSpec(seed=6, forest=forest, water="river")
    lo = towngen.village(spec, [])
    fields = [[_m(lo, q) for q in poly] for poly in lo["fields"]]
    houses = [[_m(lo, q) for q in poly] for poly in lo["buildings"]]
    fg, hg = geom.Grid(40), geom.Grid(30)
    for poly in fields:
        fg.add(geom.bbox(poly), poly)
    for poly in houses:
        hg.add(geom.bbox(poly), poly)
    for t in lo["trees"]:
        q = _m(lo, t)
        box = (q[0], q[1], q[0], q[1])
        assert not any(geom.inside(q, poly) for poly in fg.near(box)) and not any(geom.inside(q, poly) for poly in hg.near(box))
    reach = towngen.SIZES[spec.size][1] * 0.42
    c = _m(lo, lo["roads"][0]["points"][0])  # 간선은 마을 가운데에서 시작한다
    assert all(math.dist(geom.centroid(poly), c) < reach * 2.4 for poly in fields)
    counts = {f: len(towngen.village(spec.model_copy(update={"forest": f}), [])["trees"]) for f in ("few", "many")}
    assert counts["few"] < counts["many"]


# ---------- 마을 이름 · 인구, 지도에서 장소 더하기, 집 번호 ----------

def test_title_population_and_numbers():
    p = _project()
    out = atlas.generate(p, MapSpec(seed=3, water="sea"))
    lo = out["layout"]
    assert len(lo["numbers"]) == lo["houses"] == len(set(lo["numbers"]))
    assert all(0 <= i < len(lo["buildings"]) for i in lo["numbers"])
    t = out["title"]
    people = sum(b.get("people", 0) for b in lo["blds"])  # 건물마다 센 사람의 합 (canon/bldgs.py)
    assert t == {"title": "흑송촌", "custom": False, "houses": lo["houses"], "population": int(round(people, -1)), "kind": "마을", "unit": "집"}
    atlas.set_title(p, "  흑송   나루마을 ")
    assert p.atlas.title == "흑송 나루마을" and atlas.village_title(p, lo)["custom"]
    with pytest.raises(ValueError):
        atlas.set_title(p, "가" * 41)
    up = {"buildings": [[[0, 0], [1, 0], [1, 1]]] * 4, "roads": []}  # 올린 파일: 집 수가 없으면 건물 수
    assert atlas.village_title(p, up)["houses"] == 4
    assert atlas.summary(p)["title"] is None  # 마을이 없으면 제목도 없다


def test_add_place_from_map_and_name_ideas():
    p = _project()
    key = atlas.add_place(p, " 파도  여관 ", 0.3, 0.4, "여관")
    el = next(e for e in p.elements if e.id == key)
    assert (el.kind, el.name, el.found_in, el.description) == ("장소", "파도 여관", "", "여관. 지도에서 더한 곳")
    assert {pin.place: (pin.x, pin.y) for pin in p.atlas.pins}[key] == (0.3, 0.4)
    for bad in ("", "파도여관", "흑송 마을"):  # 빈 이름, 띄어쓰기만 다른 이름, 다른 이름(aliases)
        with pytest.raises(ValueError):
            atlas.add_place(p, bad, 0.1, 0.1)
    ideas = atlas.name_ideas(p)
    assert len(ideas) == 6 and not set(ideas) & {pl["name"] for pl in atlas.places(p)}


def test_web_title_places_ideas(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store as st, web

    importlib.reload(st)
    importlib.reload(web)
    st.save("t", _project())
    c = TestClient(web.app)
    assert c.post("/api/projects/t/atlas/generate", json={"spec": {"seed": 5, "water": "river"}, "pins": []}).status_code == 200
    v = c.get("/api/projects/t/atlas").json()
    assert v["title"]["title"] == "흑송촌" and v["title"]["population"] > 0
    assert c.put("/api/projects/t/atlas/title", json={"title": "검은솔 마을"}).json()["atlas"]["title"] == "검은솔 마을"
    assert c.get("/api/projects/t/atlas").json()["title"] == {**v["title"], "title": "검은솔 마을", "custom": True}
    assert c.put("/api/projects/t/atlas/title", json={"title": "가" * 41}).status_code == 400
    assert len(c.get("/api/projects/t/atlas/name-ideas").json()["names"]) == 6
    r = c.post("/api/projects/t/atlas/places", json={"name": "물레방앗간", "x": 0.4, "y": 0.6}).json()
    assert r["key"] and {p["place"]: (p["x"], p["y"]) for p in r["project"]["atlas"]["pins"]}[r["key"]] == (0.4, 0.6)
    assert c.post("/api/projects/t/atlas/places", json={"name": "물레방앗간", "x": 0.1, "y": 0.1}).status_code == 400


# ---------- 연립 줄 · 헛간 · 상징 건물 ----------

@pytest.mark.parametrize("seed,water,roads", [(7, "river", "cross"), (2, "none", "square"), (4, "sea", "line")])
def test_village_rows_barns_landmark(seed, water, roads):
    """가운데는 집이 맞붙은 연립 줄, 바깥 농가에는 긴 헛간, 가운데 가까이 상징 건물(신전 · 사당 장소가 차지한다)."""
    lo = towngen.village(MapSpec(seed=seed, water=water, roads=roads), SPOTS)
    blds = [[_m(lo, q) for q in poly] for poly in lo["buildings"]]
    mains = [blds[i] for i in lo["numbers"]]
    assert sum(1 for i, a in enumerate(mains) for b in mains[i + 1:] if geom.convex_overlap(a, b, 0.5)) >= 5  # 맞붙은 본채
    numbered = set(lo["numbers"])
    sides = [sorted((math.dist(b[0], b[1]), math.dist(b[1], b[2]))) for i, b in enumerate(blds) if i not in numbered and len(b) == 4]
    assert any(long >= 12 and long >= 2 * short for short, long in sides)  # 헛간
    at = {s["key"]: _m(lo, (s["x"], s["y"])) for s in lo["spots"]}
    assert geom.inside(at["b"], max(blds, key=lambda p: abs(geom.area(p))))  # 신전 = 가장 큰 건물
    assert math.dist(at["b"], at["a"]) < 60
