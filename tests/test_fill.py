"""빈 블록 채우기 테스트 (canon/fill.py, blocks.faces, bldgs 의 지은 건물, atlas 적용 · 지우기, 웹 · 명령줄)."""
import json
import math
import os

os.environ.setdefault("CANON_LLM", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canon import atlas, blocks, bldgs, fill, geom, osm  # noqa: E402
from canon.schema import BuildingNote, StoryElement  # noqa: E402

S, N, W, E = 37.500, 37.504, 127.000, 127.005  # 범위 (약 442 × 442m), tests/test_osm.py 와 같은 꼴
MX = 111320.0 * math.cos(math.radians((S + N) / 2))
MY = 110574.0


def ll(x: float, y: float) -> tuple[float, float]:
    return W + x / MX, N - y / MY


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def _xml() -> str:
    """골목 격자 (가로 y=100 · 220 · 340, 세로 x=120 · 240 · 360). 블록 (120~240, 100~220) 은 건물이 꽉 차고,
    (240~360, 100~220) 은 공원, (120~240, 220~340) 은 작은 집 하나만 있는 빈 블록."""
    nodes, ways = [], []
    nid = [0]
    at: dict = {}

    def node(x, y):
        if (x, y) in at:
            return at[(x, y)]
        nid[0] += 1
        lon, lat = ll(x, y)
        nodes.append(f'<node id="{nid[0]}" lat="{lat:.7f}" lon="{lon:.7f}"/>')
        at[(x, y)] = nid[0]
        return nid[0]

    def way(pts, closed=False, **tags):
        ids = [node(x, y) for x, y in (pts[:-1] if closed else pts)]
        if closed:
            ids.append(ids[0])
        t = "".join(f'<tag k="{k.replace("_", ":")}" v="{v}"/>' for k, v in tags.items())
        ways.append(f'<way id="{1000 + len(ways)}">{"".join(f"<nd ref={chr(34)}{i}{chr(34)}/>" for i in ids)}{t}</way>')

    xs, ys = [-50, 120, 240, 360, 500], [-50, 100, 220, 340, 500]
    for y in ys[1:-1]:  # 가로 길은 세로 길과 만나는 점을 함께 쓴다
        way([(x, y) for x in xs], highway="residential", name=f"가로{y}길")
    for x in xs[1:-1]:
        way([(x, y) for y in ys], highway="residential", name=f"세로{x}길")
    way(rect(130, 110, 230, 210), closed=True, building="apartments", name="꽉찬빌딩")
    way(rect(250, 110, 350, 210), closed=True, leisure="park", name="작은공원")
    way(rect(175, 275, 185, 285), closed=True, building="house", addr_street="세로240길", addr_housenumber="7")
    return (f'<?xml version="1.0" encoding="UTF-8"?><osm version="0.6"><bounds minlat="{S}" minlon="{W}" maxlat="{N}" maxlon="{E}"/>'
            + "".join(nodes) + "".join(ways) + "</osm>")


def _m(lo, q):
    return q[0] * lo["w"], q[1] * lo["h"]


def _in(lo, poly, x0, y0, x1, y1) -> bool:
    cx, cy = _m(lo, geom.centroid([tuple(q) for q in poly]))
    return x0 < cx < x1 and y0 < cy < y1


def test_faces_split_crossings_t_and_dead_ends():
    lines = [[(0, 50), (100, 50)], [(50, 0), (50, 100)],  # 꼭짓점 없이 건넌다
             [(50, 75), (100.2, 75)],  # 끝이 테두리에 0.2m 못 미친다 (T자로 잇는다)
             [(10, 10), (30, 30)], [(70, 20), (70, 40)]]  # 막다른 길 · 홀로 선 길
    fs = blocks.faces(lines, 100, 100)
    assert sorted(round(geom.area(f)) for f in fs) == [1250, 1250, 2500, 2500, 2500]
    assert sum(geom.area(f) for f in fs) == pytest.approx(100 * 100, abs=1)
    assert blocks.faces(lines, 100, 100) == fs


def test_fill_empty_blocks():
    lo = osm.parse(_xml())
    n = len(lo["buildings"])
    assert n == 2 and lo["source"] == osm.SOURCE
    out, st = fill.fill(lo, 7)
    made = out["buildings"][n:]
    assert st["buildings"] == len(made) > 20 and st["blocks"] >= 3 and st["empty"] >= st["blocks"]
    assert out["buildings"][:n] == lo["buildings"] and out["parts"][:n] == lo["parts"]  # OSM 건물 번호는 그대로
    assert all(pt["made"] and pt["use"] in ("villa", "home") and pt["levels"] for pt in out["parts"][n:])
    assert {pt["lot"] for pt in out["parts"]} == set(range(len(out["buildings"])))
    assert out["source"] == "© OpenStreetMap 기여자 · 빈 블록 건물은 Canon 이 지음"
    assert not any(_in(lo, b, 120, 100, 240, 220) for b in made)  # 건물이 꽉 찬 블록
    assert not any(_in(lo, b, 240, 100, 360, 220) for b in made)  # 공원
    assert any(_in(lo, b, 120, 220, 240, 340) for b in made)  # 작은 집 하나만 있는 블록은 채운다
    house = [_m(lo, q) for q in lo["buildings"][1]]
    for b in made:
        poly = [_m(lo, q) for q in b]
        assert not any(geom.inside(q, house) for q in poly) and not any(geom.inside(q, poly) for q in house)
        for rd in lo["roads"]:  # 길 폭의 절반 + 2m 안쪽
            pts = [_m(lo, q) for q in rd["points"]]
            assert all(geom.seg_dist(q, a, c) >= rd["width"] / 2 + 2 - 0.1 for q in poly for a, c in zip(pts, pts[1:]))
    again, _ = fill.fill(out, 7)  # 지은 건물을 지우고 다시 지어도 같은 시드면 같다
    assert json.dumps(again) == json.dumps(out)
    assert fill.fill(lo, 8)[0]["buildings"] != out["buildings"]
    assert json.dumps(fill.clear(out)) == json.dumps(lo)
    assert fill.made_count(out) == len(made) and fill.base_count(out) == n


def test_made_buildings_have_no_names():
    from .test_mapgen import _project
    lo, _ = fill.fill(osm.parse(_xml()), 3)
    lo.update(bldgs.describe(lo, "f", "korea_modern"))
    n = 2
    assert lo["blds"][1]["addr"] == "세로240길 7" and "made" not in lo["blds"][1]
    for b in lo["blds"][n:]:
        assert b["made"] and b["use"] in ("villa", "home") and b["floors"] and b["people"] > 0
        assert not {"name", "addr", "tenants", "street", "no"} & set(b)
    p = _project()
    for i, name in enumerate(["빌라", "단독주택", "꽉찬빌딩"]):
        p.elements.append(StoryElement(id=f"t-{i}", kind="장소", name=name))
    got = {x["name"]: x for x in atlas.find_spots(p, lo)}
    assert set(got) == {"꽉찬빌딩"} and all(o["i"] < n for x in got.values() for o in x["options"])
    info = atlas.building(p, lo, n)
    assert info["made"] and info["name"] == "" and info["addr"] == "" and info["street"] == ""


def test_big_block_gets_apartments():
    side = [[0, 0], [1, 0], [1, 1], [0, 1]]
    lo = {"w": 420.0, "h": 320.0, "generator": "osm", "version": "", "source": osm.SOURCE, "trees": [],
          "roads": [{"kind": "road", "width": 12.0, "points": [side[k], side[(k + 1) % 4]], "name": ""} for k in range(4)],
          "buildings": [], "parts": []}
    out, st = fill.fill(lo, 1)
    assert st["blocks"] == 1 and st["buildings"] >= 4
    assert {pt["use"] for pt in out["parts"]} == {"apartment"} and all(12 <= pt["levels"] <= 25 for pt in out["parts"])
    with pytest.raises(ValueError, match="OpenStreetMap"):
        fill.fill({**lo, "generator": "canon-modern"}, 1)


def test_wide_road_blocks_stay_empty():
    side = [[0, 0], [1, 0], [1, 1], [0, 1]]

    def layout(widths):
        return {"w": 120.0, "h": 100.0, "generator": "osm", "version": "", "source": osm.SOURCE, "trees": [],
                "roads": [{"kind": "road", "width": widths[k], "points": [side[k], side[(k + 1) % 4]], "name": ""} for k in range(4)],
                "buildings": [], "parts": []}

    assert fill.fill(layout([20.0, 16.0, 15.0, 24.0]), 1)[1]["buildings"] == 0  # 큰길로만 둘러싼 블록
    out, st = fill.fill(layout([20.0, 16.0, 6.0, 24.0]), 1)  # 좁은 길이 하나라도 있으면 채운다
    assert st["blocks"] == 1 and st["buildings"] > 0


def test_web_and_cli_fill(tmp_path, monkeypatch, capsys):
    import importlib

    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import cli, store, web

    from .test_mapgen import _project
    importlib.reload(store)
    importlib.reload(web)
    store.save("o", _project())
    c = TestClient(web.app)
    pr = c.put("/api/projects/o/atlas/layout", json={"data": _xml()}).json()
    assert pr["atlas"]["fill"] is None
    path = tmp_path / "o" / "map" / pr["atlas"]["layout"]
    before = path.read_text(encoding="utf-8")
    c.put("/api/projects/o/atlas/buildings/1", json={"name": "우리 집"})
    pv = c.post("/api/projects/o/atlas/layout/fill", json={"mode": "preview", "seed": 5}).json()
    assert pv["seed"] == 5 and pv["had"] == 0 and pv["buildings"] == len(pv["added"]) > 0 and len(pv["areas"]) == pv["blocks"]
    assert path.read_text(encoding="utf-8") == before  # 미리보기는 저장하지 않는다
    r = c.post("/api/projects/o/atlas/layout/fill", json={"mode": "apply", "seed": 5}).json()
    assert r["buildings"] == pv["buildings"] and r["project"]["atlas"]["fill"] == {"seed": 5, "rule": "villa"}
    lo = c.get("/api/projects/o/atlas/layout").json()
    assert len(lo["buildings"]) == 2 + r["buildings"] and lo["blds"][2]["made"] and lo["source"].endswith("Canon 이 지음")
    assert c.get("/api/projects/o/atlas").json()["layout"]["made"] == r["buildings"]
    assert c.get("/api/projects/o/atlas/buildings/1").json()["name"] == "우리 집"  # 고친 OSM 건물은 그대로
    c.put("/api/projects/o/atlas/buildings/3", json={"note": "지은 건물에 단 메모"})
    r2 = c.post("/api/projects/o/atlas/layout/fill", json={"mode": "apply", "seed": 6}).json()
    assert [b["i"] for b in r2["project"]["atlas"]["buildings"]] == [1]  # 전에 지은 건물을 고친 기록은 지운다
    r3 = c.post("/api/projects/o/atlas/layout/fill", json={"mode": "clear"}).json()
    assert r3["removed"] == r2["buildings"] and r3["project"]["atlas"]["fill"] is None
    lo = c.get("/api/projects/o/atlas/layout").json()
    assert len(lo["buildings"]) == 2 and lo["source"] == osm.SOURCE and lo["blds"][1]["addr"] == "세로240길 7"
    assert c.post("/api/projects/o/atlas/layout/fill", json={"mode": "nope"}).status_code == 400

    monkeypatch.setattr(store, "ROOT", tmp_path)
    cli.main(["map", "o", "fill", "--seed", "5", "-y"])
    assert f"건물 {pv['buildings']}채를 지어 채웠어요" in capsys.readouterr().out
    assert store.load("o").atlas.fill.seed == 5
    cli.main(["map", "o", "fill", "--clear", "-y"])
    assert "지웠어요" in capsys.readouterr().out and store.load("o").atlas.fill is None
