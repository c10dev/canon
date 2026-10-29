"""OpenStreetMap 지도 올리기 테스트 (canon/osm.py, atlas.parse_upload, bldgs.describe 의 실제 지도 경로, 웹 올리기)."""
import json
import math
import os

os.environ.setdefault("CANON_LLM", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canon import atlas, bldgs, geom, osm, towngen  # noqa: E402
from canon.schema import MapSpec  # noqa: E402

S, N, W, E = 37.500, 37.504, 127.000, 127.005  # 범위 (약 442 × 442m)
MX = 111320.0 * math.cos(math.radians((S + N) / 2))
MY = 110574.0


def ll(x: float, y: float) -> tuple[float, float]:
    """지도 m 좌표(왼쪽 위에서, y 아래로) → (lon, lat)."""
    return W + x / MX, N - y / MY


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def _xml() -> str:
    nodes, ways, rels = [], [], []
    nid = [0]

    def node(x, y, **tags):
        nid[0] += 1
        lon, lat = ll(x, y)
        t = "".join(f'<tag k="{k.replace("_", ":")}" v="{v}"/>' for k, v in tags.items())
        nodes.append(f'<node id="{nid[0]}" lat="{lat:.7f}" lon="{lon:.7f}">{t}</node>')
        return nid[0]

    def way(pts, closed=False, **tags):
        ids = [node(x, y) for x, y in (pts[:-1] if closed else pts)]
        if closed:
            ids.append(ids[0])
        wid = 1000 + len(ways)
        t = "".join(f'<tag k="{k.replace("_", ":")}" v="{v}"/>' for k, v in tags.items())
        ways.append(f'<way id="{wid}">{"".join(f"<nd ref={chr(34)}{i}{chr(34)}/>" for i in ids)}{t}</way>')
        return wid

    way([(-50, 100), (500, 100)], highway="primary", lanes="4", name="테스트대로")
    way([(200, 100), (200, 300)], highway="residential", name="테스트로1길")
    way([(300, 100), (300, 250)], highway="service")
    way([(-50, 150), (500, 150)], highway="primary", tunnel="yes")  # 땅속: 그리지 않는다
    way([(100, 300), (100, 330)], highway="residential")
    way([(100, 330), (100, 410)], highway="residential", bridge="yes")
    way([(100, 410), (100, 442)], highway="residential")
    way(rect(220, 120, 270, 170), closed=True, building="commercial", building_levels="12", name="테스트타워",
        addr_street="테스트대로", addr_housenumber="10")
    node(230, 130, amenity="cafe", name="카페 하나")
    node(250, 150, shop="convenience", name="편의점 둘")
    way(rect(40, 120, 100, 180), closed=True, building="apartments")
    way(rect(300, 200, 340, 240), closed=True, building="yes", layer="-1")  # 지하상가
    way(rect(250, 260, 290, 290), closed=True, building="roof")  # 주유소 지붕
    a = way([(320, 120), (380, 120), (380, 170)])
    b = way([(380, 170), (320, 170), (320, 120)])
    rels.append(f'<relation id="1"><member type="way" ref="{a}" role="outer"/><member type="way" ref="{b}" role="outer"/>'
                '<tag k="type" v="multipolygon"/><tag k="building" v="school"/><tag k="name" v="테스트초등학교"/></relation>')
    way(rect(20, 200, 150, 280), closed=True, leisure="park", name="테스트공원")
    node(150, 60, railway="station", public_transport="station", name="테스트")  # 건물 밖 역 (OSM 은 '역'을 뺀 이름)
    way([(300, 410), (340, 410), (340, 435), (300, 435), (300, 410)], closed=True, building="house")
    way(rect(150, 418, 190, 440), closed=True, building="house")
    north = way([(-100, 340), (200, 342), (550, 340)])  # 큰 강의 물가 두 줄 (범위 밖 조각은 파일에 없다)
    south = way([(550, 400), (200, 398), (-100, 400)])
    rels.append(f'<relation id="2"><member type="way" ref="{north}" role="outer"/><member type="way" ref="{south}" role="outer"/>'
                '<tag k="type" v="multipolygon"/><tag k="natural" v="water"/><tag k="water" v="river"/></relation>')
    node(60, 220, natural="tree")
    return (f'<?xml version="1.0" encoding="UTF-8"?><osm version="0.6"><bounds minlat="{S}" minlon="{W}" maxlat="{N}" maxlon="{E}"/>'
            + "".join(nodes) + "".join(ways) + "".join(rels) + "</osm>")


def _geojson() -> dict:
    def pt(x, y):
        return list(ll(x, y))

    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "way/1", "properties": {"@id": "way/1", "highway": "residential", "name": "가길"},
         "geometry": {"type": "LineString", "coordinates": [pt(0, 50), pt(200, 50)]}},
        {"type": "Feature", "id": "way/2", "properties": {"tags": {"building": "apartments", "building:levels": "20"}},
         "geometry": {"type": "Polygon", "coordinates": [[pt(*q) for q in rect(20, 60, 80, 120)]]}},
        {"type": "Feature", "id": "way/3", "properties": {"@id": "way/3", "building": "yes"},
         "geometry": {"type": "Polygon", "coordinates": [[pt(*q) for q in rect(120, 60, 180, 110)]]}},
        {"type": "Feature", "id": "node/4", "properties": {"@id": "node/4", "amenity": "pharmacy", "name": "가약국"},
         "geometry": {"type": "Point", "coordinates": pt(150, 80)}},
    ]}


def _m(lo: dict, q) -> tuple[float, float]:
    return q[0] * lo["w"], q[1] * lo["h"]


def test_xml_roads_buildings_and_water():
    lo = osm.parse(_xml())
    assert lo["generator"] == "osm" and lo["source"] == osm.SOURCE
    assert abs(lo["w"] - 441.6) < 1 and abs(lo["h"] - 442.3) < 1
    widths = {r["name"]: r["width"] for r in lo["roads"] if r["name"]}
    assert widths == {"테스트대로": 15.2, "테스트로1길": 6.0}  # 4차로 × 3.3 + 2, residential 기본 폭
    assert sum(r["kind"] == "bridge" for r in lo["roads"]) == 1
    assert all(r["width"] != 15.2 or abs(_m(lo, r["points"][0])[1] - 100) < 1 for r in lo["roads"])  # 땅속 길은 빠진다
    big = next(r for r in lo["roads"] if r["name"] == "테스트대로")
    assert [round(_m(lo, q)[0]) for q in big["points"]] == [0, 442]  # 범위 테두리에서 자른다
    assert len(lo["buildings"]) == len(lo["parts"]) == 5  # 지하 건물 · 지붕만 있는 것은 뺀다
    uses = {p["name"] or p["use"]: p for p in lo["parts"]}
    tower = uses["테스트타워"]
    assert tower["use"] in ("cafe", "convenience") and tower["levels"] == 12 and tower["addr"] == "테스트대로 10"
    assert tower["tenants"] == ["카페 하나", "편의점 둘"]
    assert uses["테스트초등학교"]["use"] == "school"  # multipolygon 건물
    assert "apartment" in uses and uses["home"]["levels"] == 0
    assert len(lo["greens"]) == 1 and len(lo["trees"]) == 1
    # 끊긴 물가 두 줄 → 그 사이의 강 (건물이 없는 쪽)
    water = [[_m(lo, q) for q in ln] for ln in lo["water"]]
    assert len(water) == 1
    assert geom.inside((220, 370), water[0]) and geom.inside((10, 370), water[0])
    assert not geom.inside((220, 200), water[0]) and not geom.inside((220, 425), water[0])


def test_geojson_and_detect():
    raw = _geojson()
    assert osm.is_osm(raw)
    lo = osm.parse(json.dumps(raw))
    assert [p["use"] for p in lo["parts"]] == ["apartment", "pharmacy"]
    assert lo["parts"][0]["levels"] == 20 and lo["parts"][1]["name"] == "가약국"  # 시설 하나뿐이면 그 이름
    assert lo["roads"][0]["name"] == "가길"
    # Watabou 파일 · 생성기 지도는 OSM 이 아니다
    v = towngen.village(MapSpec(seed=2), [])
    assert not osm.is_osm({"type": "FeatureCollection", "features": [{"type": "Polygon", "id": "earth", "coordinates": []}]})
    assert not osm.is_osm(v)


@pytest.mark.parametrize("text, word", [
    ("<html></html>", "파일이 아니에요"), ("<osm", "읽지 못했어요"), ('{"type": "FeatureCollection", "features": []}', "좌표가 없어요"),
    ("{not json", "JSON 파일을 읽지 못했어요")])
def test_parse_upload_errors(text, word):
    with pytest.raises(ValueError, match=word):
        atlas.parse_upload(text)


def test_limits():
    raw = _geojson()
    raw["features"].append({"type": "Feature", "properties": {"@id": "way/9", "building": "yes"},
                            "geometry": {"type": "Polygon", "coordinates": [[[127.2, 37.6], [127.21, 37.6], [127.21, 37.61], [127.2, 37.6]]]}})
    with pytest.raises(ValueError, match="너무 넓어요"):
        osm.parse(json.dumps(raw))
    no_road = {"type": "FeatureCollection", "features": [f for f in _geojson()["features"] if "highway" not in json.dumps(f)]}
    with pytest.raises(ValueError, match="길이 없어요"):
        osm.parse(json.dumps(no_road))


def test_describe_real_map():
    lo = osm.parse(_xml())
    a = bldgs.describe(lo, "f", "korea_modern")
    assert json.dumps(a, sort_keys=True) == json.dumps(bldgs.describe(lo, "g", "korea_modern"), sort_keys=True)  # 태그만 쓴다
    by = {b.get("name", b["use"]): b for b in a["blds"]}
    assert by["테스트타워"]["floors"] == 12 and by["테스트타워"]["addr"] == "테스트대로 10" and by["테스트타워"]["people"] == 0
    assert by["테스트타워"]["tenants"] == ["카페 하나", "편의점 둘"]
    assert all(b.get("no", 0) == 0 for b in a["blds"])  # 실제 지도에는 번지를 지어 넣지 않는다
    apt = by["apartment"]
    assert apt["floors"] == bldgs.MODERN_FLOORS["apartment"]
    assert apt["people"] == round(round(3600 * 15 * bldgs.FLAT_SHARE / bldgs.FLAT_AREA) * bldgs.HOUSEHOLD_SIZE)
    assert by["테스트초등학교"]["use"] == "school" and bldgs.label("school", "korea_modern") == "학교"
    names = {s["name"] for s in a["streets"]}
    assert {"테스트대로", "테스트로1길", ""} <= names  # 이름 없는 길에 이름을 지어 넣지 않는다
    assert all(b["use"] in bldgs.USES for b in a["blds"])


def test_web_upload_osm(tmp_path, monkeypatch):
    import importlib

    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store, web

    from .test_mapgen import _project
    importlib.reload(store)
    importlib.reload(web)
    store.save("o", _project())
    c = TestClient(web.app)
    pr = c.put("/api/projects/o/atlas/layout", json={"data": _xml()}).json()
    assert pr["atlas"]["layout"].startswith("layout-") and pr["atlas"]["meters"] == 1
    s = c.get("/api/projects/o/atlas").json()
    assert s["layout"]["generator"] == "osm" and s["layout"]["source"] == osm.SOURCE and s["layout"]["buildings"] == 5
    assert c.get("/api/projects/o/atlas/find-spots").json() == {"spots": []}  # 장소 이름과 맞는 곳이 없다
    lo0 = c.get("/api/projects/o/atlas/layout").json()
    k = next(k for k, b in enumerate(lo0["blds"]) if b.get("name") == "테스트타워")
    cx, cy = geom.centroid([tuple(q) for q in lo0["buildings"][k]])
    pr = c.put("/api/projects/o/atlas/pins", json={"pins": [{"place": "el-9", "x": cx, "y": cy}]}).json()
    assert pr["atlas"]["pins"][0]["spot"].startswith("테스트타워 (")  # 핀을 저장하면 놓인 건물 한 줄을 적는다
    pr = c.put(f"/api/projects/o/atlas/buildings/{k}", json={"name": "새 이름"}).json()
    assert pr["atlas"]["pins"][0]["spot"].startswith("새 이름 (")
    assert s["title"]["kind"] == "동네" and s["title"]["unit"] == "건물" and s["title"]["houses"] == 5
    assert "apartment" in s["gen"]["modern"] and s["gen"]["uses"]["convenience"] == ["편의점", "shop"]
    lo = c.get("/api/projects/o/atlas/layout").json()
    i = next(k for k, b in enumerate(lo["blds"]) if b.get("name") == "테스트타워")
    b = c.get(f"/api/projects/o/atlas/buildings/{i}").json()
    assert b["addr"] == "테스트대로 10" and b["tenants"] == ["카페 하나", "편의점 둘"] and b["group"] in ("food", "shop")
    assert c.put("/api/projects/o/atlas/layout", json={"data": "<osm><bounds/></osm>"}).status_code == 400


def test_find_spots():
    from canon.schema import MapPin, StoryElement

    from .test_mapgen import _project
    lo = osm.parse(_xml())
    assert {m["name"]: m["use"] for m in lo["marks"]} == {"테스트": "station", "테스트공원": ""}  # 건물 밖의 이름 붙은 곳
    lo.update(bldgs.describe(lo, "f", "korea_modern"))
    p = _project()
    for i, name in enumerate(["테스트역", "테스트 타워", "카페하나", "테스트공원", "없는 곳", "편의점 둘"]):
        p.elements.append(StoryElement(id=f"t-{i}", kind="장소", name=name))
    atlas.set_pins(p, [MapPin(place="t-5", x=0.1, y=0.1)])
    got = {x["name"]: x for x in atlas.find_spots(p, lo)}
    assert "없는 곳" not in got and "달빛 주막" not in got  # 맞는 곳이 없으면 빼기
    st = got["테스트역"]["options"][0]
    assert st["kind"] == "mark" and st["i"] == -1 and _m(lo, (st["x"], st["y"])) == pytest.approx((150, 60), abs=0.5)
    assert st["near"] == "테스트대로 옆" and st["what"] == "테스트 (역)"  # 건물 밖 표지는 가까운 길 이름으로 가린다
    tower = got["테스트 타워"]["options"][0]  # 띄어쓰기는 무시한다
    assert tower["kind"] == "building" and tower["near"] == "테스트대로 10" and lo["blds"][tower["i"]]["name"] == "테스트타워"
    assert _m(lo, (tower["x"], tower["y"])) == pytest.approx((245, 145), abs=0.5)
    cafe = got["카페하나"]["options"]
    assert [o["kind"] for o in cafe] == ["tenant"] and cafe[0]["i"] == tower["i"] and "테스트타워" in cafe[0]["what"]
    assert got["테스트공원"]["options"][0]["kind"] == "mark"
    assert got["편의점 둘"]["had"] and not got["테스트역"]["had"]
    p.atlas.buildings = [atlas.BuildingNote(i=tower["i"], name="카페 하나")]  # 작가가 붙인 건물 이름이 입점보다 앞
    assert [o["kind"] for o in {x["name"]: x for x in atlas.find_spots(p, lo)}["카페하나"]["options"]] == ["building"]


def test_spot_lines_in_prompt():
    from canon import pipeline, prompts
    from canon.schema import MapPin, StoryElement

    from .test_mapgen import _project
    lo = osm.parse(_xml())
    lo.update(bldgs.describe(lo, "f", "korea_modern"))
    p = _project()
    p.elements += [StoryElement(id="t-1", kind="장소", name="테스트타워"), StoryElement(id="t-2", kind="장소", name="테스트역"),
                   StoryElement(id="t-3", kind="장소", name="빈터")]
    xy = lambda x, y: (x / lo["w"], y / lo["h"])  # noqa: E731
    atlas.set_pins(p, [MapPin(place="t-1", x=xy(245, 145)[0], y=xy(245, 145)[1]),
                       MapPin(place="t-2", x=xy(155, 62)[0], y=xy(155, 62)[1]), MapPin(place="t-3", x=0.99, y=0.01)])
    atlas.fill_spots(p, lo)
    spot = {pin.place: pin.spot for pin in p.atlas.pins}
    assert spot["t-1"].startswith("테스트타워 (") and "· 12층 · 테스트대로 10 · 입점: 카페 하나, 편의점 둘" in spot["t-1"]
    assert spot["t-2"] == "테스트 (역) · 테스트대로 옆" and spot["t-3"] == ""  # 건물 밖은 가까운 표지, 없으면 빈 글
    pipeline.confirm_plot(p, 4)
    p.episode(4).plot.summary = "윤서가 테스트타워 앞에서 테스트역으로 걷는다"
    block = atlas.episode_block(p, 4)
    assert block.splitlines()[0] == f"- 테스트타워: {spot['t-1']}" and "- 테스트역: 테스트 (역)" in block and "빈터" not in block
    ctx = prompts.build_episode_context(p, 4)
    assert "# 장소가 놓인 건물 (지도 기준)" in ctx and ctx.index("# 장소가 놓인 건물") > ctx.index("# 작품 속 시간")  # 화마다 바뀌는 블록 쪽
    assert "# 장소가 놓인 건물 (지도 기준)" in prompts.check_prompt(p, 4)
    assert "(장소 1곳 생략)" in atlas.episode_block(p, 4, budget=10)  # 예산이 작아도 한 줄은 넣고 뺀 수를 적는다
    atlas.fill_spots(p, None)
    assert atlas.episode_block(p, 4) == "" and "# 장소가 놓인 건물" not in prompts.build_episode_context(p, 4)


# ---------- 바다 (natural=coastline) ----------

def _coast_xml(*coasts, extra: str = "") -> str:
    """길 하나 + 해안선들 (지도 m 좌표 꺾은선, 처음 점과 끝 점이 같으면 닫힌 고리). 범위는 위와 같다 (약 442 × 442m)."""
    nodes, ways = [], []
    ids: dict = {}

    def node(q):
        if q not in ids:
            ids[q] = len(ids) + 1
            lon, lat = ll(*q)
            nodes.append(f'<node id="{ids[q]}" lat="{lat:.7f}" lon="{lon:.7f}"/>')
        return ids[q]

    def way(pts, tags):
        refs = "".join(f'<nd ref="{node(q)}"/>' for q in pts)
        ways.append(f'<way id="{2000 + len(ways)}">{refs}{"".join(f"<tag k={chr(34)}{k}{chr(34)} v={chr(34)}{v}{chr(34)}/>" for k, v in tags.items())}</way>')

    way([(0, 20), (442, 20)], {"highway": "residential"})
    for pts in coasts:
        way(pts, {"natural": "coastline"})
    return (f'<?xml version="1.0" encoding="UTF-8"?><osm version="0.6"><bounds minlat="{S}" minlon="{W}" maxlat="{N}" maxlon="{E}"/>'
            + "".join(nodes) + "".join(ways) + extra + "</osm>")


def _polys(lo: dict, key: str) -> list:
    return [[_m(lo, q) for q in ln] for ln in lo.get(key, [])]


def test_coastline_crossing_the_map():
    # 서 → 동으로 그은 해안선: 땅이 왼쪽(북), 바다가 오른쪽(남). 두 길(way)로 나뉘어 있고 범위 밖까지 이어진다
    lo = osm.parse(_coast_xml([(-100, 300), (200, 310)], [(200, 310), (600, 300)]))
    sea = _polys(lo, "water")
    assert len(sea) == 1 and "land" not in lo and "coast_broken" not in lo
    area = abs(geom.area(sea[0]))
    assert abs(area - lo["w"] * (lo["h"] - 306)) < lo["w"] * 6  # 해안선 아래 띠 (약 442 × 136m)
    assert geom.inside((220, 400), sea[0]) and not geom.inside((220, 200), sea[0])
    # 반대로 그으면 (동 → 서) 바다는 북쪽
    lo = osm.parse(_coast_xml([(600, 300), (200, 310), (-100, 300)]))
    sea = _polys(lo, "water")
    assert len(sea) == 1 and geom.inside((220, 100), sea[0]) and not geom.inside((220, 400), sea[0])
    # 한 길에서 들어와 다른 변으로 나가는 해안선 (남서쪽 모퉁이가 바다)
    lo = osm.parse(_coast_xml([(-50, 200), (250, 250), (300, 500)]))
    sea = _polys(lo, "water")
    assert len(sea) == 1 and geom.inside((20, 420), sea[0]) and not geom.inside((400, 100), sea[0])


def test_coastline_island():
    # 섬: 땅이 왼쪽이 되게 (화면에서 반시계 방향) 닫은 고리. 범위를 가로지르는 해안선이 없으니 범위 전체가 바다
    island = [(150, 150), (150, 300), (300, 300), (300, 150), (150, 150)]
    lo = osm.parse(_coast_xml(island))
    sea, land = _polys(lo, "water"), _polys(lo, "land")
    assert len(sea) == 1 and abs(abs(geom.area(sea[0])) - lo["w"] * lo["h"]) < 10
    assert len(land) == 1 and abs(abs(geom.area(land[0])) - 150 * 150) < 50 and geom.inside((220, 220), land[0])
    # 남쪽이 바다인 해안선 + 그 바다 속 섬
    lo = osm.parse(_coast_xml([(-100, 100), (600, 100)], [(150, 200), (150, 300), (300, 300), (300, 200), (150, 200)]))
    sea, land = _polys(lo, "water"), _polys(lo, "land")
    assert len(sea) == 1 and geom.inside((220, 400), sea[0]) and len(land) == 1 and geom.inside((220, 250), land[0])
    # 섬 위는 물이 아니다: 장소를 놓을 수 있다
    assert atlas._blocked(lo, (220 / lo["w"], 400 / lo["h"]))
    assert not atlas._blocked(lo, (220 / lo["w"], 250 / lo["h"]))
    # 범위 전체가 섬 안이면 바다가 없다
    lo = osm.parse(_coast_xml([(-50, -50), (-50, 500), (500, 500), (500, -50), (-50, -50)]))
    assert "water" not in lo and "land" not in lo


def test_coastline_broken():
    # 범위 안에서 끊긴 해안선: 가장 가까운 테두리까지 이어 닫는다
    lo = osm.parse(_coast_xml([(-100, 300), (200, 300)], [(260, 300), (600, 300)]))
    sea = _polys(lo, "water")
    assert "coast_broken" not in lo and sea and all(geom.area(s) > 0 for s in sea)
    assert any(geom.inside((100, 400), s) for s in sea) and not any(geom.inside((100, 200), s) for s in sea)
    # 방향이 어긋난 해안선 두 줄 (둘 다 남쪽이 바다): 닫지 못하면 바다를 그리지 않고 표시한다. 다른 물은 그대로
    pond = ('<node id="900" lat="37.5025" lon="127.001"/><node id="901" lat="37.5025" lon="127.0015"/>'
            '<node id="902" lat="37.5028" lon="127.0015"/><way id="9000"><nd ref="900"/><nd ref="901"/><nd ref="902"/><nd ref="900"/>'
            '<tag k="natural" v="water"/></way>')
    lo = osm.parse(_coast_xml([(-100, 100), (600, 100)], [(-100, 300), (600, 300)], extra=pond))
    assert lo["coast_broken"] is True and len(lo["water"]) == 1 and abs(geom.area(_polys(lo, "water")[0])) < 3000


def test_coastline_keeps_rivers_and_fill():
    # 바다를 더해도 강 가운데 선은 남는다 (넓이로 그린 강이 없으면)
    river = ('<node id="800" lat="37.5039" lon="127.0025"/><node id="801" lat="37.5015" lon="127.0025"/>'
             '<way id="8000"><nd ref="800"/><nd ref="801"/><tag k="waterway" v="river"/></way>')
    lo = osm.parse(_coast_xml([(-100, 300), (600, 300)], extra=river))
    assert lo["rivers"] and lo["water"]
    # 빈 블록 채우기: 바다 쪽 블록은 채우지 않는다
    from canon import fill
    lo = osm.parse(_coast_xml([(-100, 300), (600, 300)], extra=_road_grid()))
    out, info = fill.fill(lo, 1)
    sea = _polys(lo, "water")[0]
    assert info["buildings"] > 0  # 땅 쪽 블록은 채운다
    assert not any(geom.inside(geom.centroid([_m(lo, q) for q in b]), sea) for b in info["added"])


def _road_grid() -> str:
    """60m 간격 길 격자 (블록이 여럿 생기게)."""
    out, nid = [], 700
    for k, v in enumerate(range(40, 442, 60)):
        a, b = ll(v, -10), ll(v, 452)
        c, d = ll(-10, v), ll(452, v)
        for (p, q) in ((a, b), (c, d)):
            out.append(f'<node id="{nid}" lat="{p[1]:.7f}" lon="{p[0]:.7f}"/><node id="{nid + 1}" lat="{q[1]:.7f}" lon="{q[0]:.7f}"/>'
                       f'<way id="{nid}"><nd ref="{nid}"/><nd ref="{nid + 1}"/><tag k="highway" v="residential"/></way>')
            nid += 2
    return "".join(out)
