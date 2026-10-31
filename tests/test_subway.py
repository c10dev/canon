"""지하철 노선과 역 사이 이동 시간 테스트 (docs/map/specs/06-subway.md): OpenStreetMap 의 역 · 노선 읽기(osm._transit),
작품 사본(Atlas.transit), 대중교통 이동 시간(travel.rail · trip), 프롬프트 줄(mapprompt.travel_block), 지도 화면 역 표지 계산.
실행: python -m pytest tests/test_subway.py"""
import importlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())
os.environ.setdefault("CANON_LLM", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canon import atlas, pipeline  # noqa: E402
from canon.maps import prompt as mapprompt  # noqa: E402
from canon.maps import travel  # noqa: E402
from canon.maps.sources import osm  # noqa: E402
from canon.schema import MapPin, Project  # noqa: E402

from .test_atlas import _played  # noqa: E402

S, N, W, E = 37.500, 37.509, 127.000, 127.034  # 범위 (약 3.0 × 1.0km)
MX = 111320.0 * math.cos(math.radians((S + N) / 2))
MY = 110574.0


def ll(x: float, y: float) -> tuple[float, float]:
    return W + x / MX, N - y / MY


def _xml(route: str = "subway") -> str:
    """역 셋(가 · 나 · 다, 가로 300 · 1500 · 2700m)과 노선 하나(두 방향 relation). 나와 다 사이에 파일에 없는 정차 위치 하나."""
    nodes, rels = [], []
    nid = [0]

    def node(x, y, **tags):
        nid[0] += 1
        lon, lat = ll(x, y)
        t = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        nodes.append(f'<node id="{nid[0]}" lat="{lat:.7f}" lon="{lon:.7f}">{t}</node>')
        return nid[0]

    road = [node(x, 520) for x in (0, 3000)]
    node(300, 480, railway="station", station="subway", name="가역", public_transport="station")
    node(1500, 480, public_transport="station", subway="yes", name="나")
    stops = [node(310, 500, railway="stop", public_transport="stop_position", subway="yes", name="가(시청)"),
             node(1490, 500, railway="stop", public_transport="stop_position", subway="yes", name="나"),
             99999,  # 지도 밖 · 파일에 없는 역
             node(2700, 500, railway="stop", public_transport="stop_position", subway="yes", name="다")]
    node(2400, 300, highway="bus_stop", public_transport="platform", name="큰길 정류장")

    def rel(rid, name, ids):
        members = "".join(f'<member type="node" ref="{i}" role="stop"/>' for i in ids)
        rels.append(f'<relation id="{rid}">{members}<tag k="type" v="route"/><tag k="route" v="{route}"/><tag k="name" v="{name}"/></relation>')

    rel(1, "테스트선: 가 → 다", stops)
    rel(2, "테스트선: 다 → 가", stops[::-1])
    way = f'<way id="500">{"".join(f"<nd ref={chr(34)}{i}{chr(34)}/>" for i in road)}<tag k="highway" v="primary"/></way>'
    return (f'<?xml version="1.0"?><osm version="0.6"><bounds minlat="{S}" minlon="{W}" maxlat="{N}" maxlon="{E}"/>'
            + "".join(nodes) + way + "".join(rels) + "</osm>")


def test_parse_stations_and_line():
    lo = osm.parse(_xml())
    tr = lo["transit"]
    assert [s["name"] for s in tr["stations"]] == ["가역", "나", "다"]  # 역 점 이름 그대로, 역 점이 없으면 정차 위치 이름
    assert tr["lines"] == [{"name": "테스트선", "stations": [0, 1, 2], "gaps": [0, 1]}]  # 두 방향은 하나, 파일에 없는 역 하나
    assert all(s["lines"] == ["테스트선"] for s in tr["stations"])
    assert tr["stations"][0]["x"] == pytest.approx(300 / lo["w"], abs=0.01)  # 역 점이 있으면 역 점 자리
    uses = {m["name"]: m["use"] for m in lo.get("marks", [])}
    assert uses["큰길 정류장"] == "bus" and uses["나"] == "station"  # 역 점은 표지로 남는다 (이름으로 자리 찾기)
    assert "가(시청)" not in uses and "다" not in uses  # 정차 위치는 버스 정류장 표지가 되지 않는다
    tram = osm.parse(_xml(route="tram"))["transit"]  # 지하철이 아닌 노선은 빼고, 역 점은 남긴다
    assert tram["lines"] == [] and [s["name"] for s in tram["stations"]] == ["가역", "나"]


def _transit_project(mode: str = "transit") -> Project:
    """3km × 1km 지도: 집(가역 옆), 회사(다 옆), 카페(집에서 250m)."""
    p = _played()
    lo = osm.parse(_xml())
    p.atlas.layout, p.atlas.layout_size, p.atlas.meters = "layout.json", [lo["w"], lo["h"]], 1.0
    p.atlas.pins = [MapPin(place="el-2", x=330 / lo["w"], y=0.6), MapPin(place="el-1", x=2680 / lo["w"], y=0.6),
                    MapPin(place="w:수산시장", x=580 / lo["w"], y=0.6)]
    atlas.fill_spots(p, lo)
    p.atlas.travel.mode = mode
    return p


def test_rail_faster_than_walking():
    p = _transit_project()
    assert p.atlas.transit and len(p.atlas.transit.stations) == 3
    walk = travel.need(p, travel.km(p, ["el-2", "el-1"]))
    t = travel.trip(p, ["el-2", "el-1"])
    assert t["rail"] == {"stops": 3, "transfers": 0, "path": "가역 → 다"}  # 가 → 나 → (없는 역) → 다
    assert t["normal"] < walk[0] / 2 and t["fast"] <= t["normal"]
    # 걸어서 2.35km × 1.3 = 3.1km 는 37분쯤, 지하철은 걷기 · 역 안 · 기다림 · 2.4km 탐 · 역 안 · 걷기로 15분 안팎
    assert walk[0] * 60 == pytest.approx(36.7, abs=1) and 12 < t["normal"] * 60 < 18
    assert "(지하철 3정거장 · 가역 → 다, 보통" in travel.path_text(p, {**t, "stops": ["el-2", "el-1"], "gap": None},
                                                                {"el-2": "등대", "el-1": "흑송촌"})


def test_walking_wins_when_close():
    p = _transit_project()
    t = travel.trip(p, ["el-2", "w:수산시장"])  # 250m: 역 안 걷기와 기다림만으로도 걷는 게 빠르다
    assert t["rail"] is None and t["normal"] == pytest.approx(travel.need(p, t["km"])[0])


def test_other_modes_and_old_layout():
    p = _transit_project(mode="walk")
    assert travel.trip(p, ["el-2", "el-1"])["rail"] is None  # 대중교통이 아니면 지하철을 보지 않는다
    p = _transit_project()
    lo = osm.parse(_xml())
    del lo["transit"]  # 이 기능 전에 올린 지도 파일
    atlas.fill_spots(p, lo)
    assert p.atlas.transit is None and travel.trip(p, ["el-2", "el-1"])["rail"] is None
    assert travel.view(p)["transit"] is None and "걸어서만 셈해요" in travel.describe(p)
    old = json.loads(p.model_dump_json())
    del old["atlas"]["transit"]  # 이 칸이 생기기 전 project.json
    assert Project.model_validate(old).atlas.transit is None


def test_view_and_prompt_line():
    p = _transit_project()
    v = travel.view(p)
    assert v["transit"] == {"stations": 3, "lines": ["테스트선"]}
    assert v["rail"] and all("지하철 3정거장" in m["text"] for m in v["rail"])  # 1~2화, 2~3화 등대 ↔ 흑송촌
    assert "대중교통" in [m["label"] for m in v["modes"]]
    pipeline.confirm_plot(p, 4)
    p.episode(4).plot.summary = "윤서가 흑송촌 장터로 간다"
    block = mapprompt.travel_block(p, 4)
    assert "등대 → 흑송촌 약 3.1km, 지하철로 약" in block and "(가역 → 다 3정거장, 서둘러도" in block
    assert "지하철은 역까지 걷기 · 기다림 · 갈아타기 포함" in block.splitlines()[0]
    assert len(mapprompt.travel_block(p, 4, budget=10).splitlines()) == 3  # 예산이 작아도 한 줄은 넣는다
    p.atlas.travel.mode = "walk"
    assert "지하철" not in mapprompt.travel_block(p, 4)


def test_transfer_between_lines():
    """두 노선이 나에서 만난다: 가 → 나(갈아타기) → 라."""
    p = _transit_project()
    tr = p.atlas.transit
    tr.stations.append(tr.stations[1].model_copy(update={"name": "라", "y": tr.stations[1].y + 0.9, "lines": ["둘째선"]}))
    tr.stations[1].lines.append("둘째선")
    tr.lines.append(tr.lines[0].model_copy(update={"name": "둘째선", "stations": [1, 3], "gaps": []}))
    r = travel.rail(p, (tr.stations[0].x, tr.stations[0].y), (tr.stations[3].x, tr.stations[3].y))
    assert r[1]["transfers"] == 1 and r[1]["stops"] == 2 and r[1]["lines"] == ["테스트선", "둘째선"]


def test_web_upload_keeps_transit(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store as st, web

    importlib.reload(st)
    importlib.reload(web)
    st.save("t", _played())
    c = TestClient(web.app)
    r = c.put("/api/projects/t/atlas/layout", json={"data": _xml()})
    assert r.status_code == 200 and len(r.json()["atlas"]["transit"]["stations"]) == 3
    assert len(c.get("/api/projects/t/atlas/layout").json()["transit"]["lines"]) == 1
    r = c.put("/api/projects/t/atlas/travel", json={"enabled": True, "mode": "transit", "span_km": 0})
    assert r.status_code == 200 and c.get("/api/projects/t/atlas").json()["travel"]["transit"]["stations"] == 3
    assert c.delete("/api/projects/t/atlas/layout").json()["atlas"]["transit"] is None


CALC = """
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const part = src.slice(src.indexOf('// ----- 되돌리기 · 따라가기 계산'), src.indexOf('// ----- 확대 · 이동, 이름표 -----'));
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const fn = eval(part + ';' + data.call);
process.stdout.write(JSON.stringify(fn(...data.args)));
"""


def test_station_marks_js():
    if not shutil.which("node"):
        pytest.skip("node 가 없어요")
    js = Path(__file__).resolve().parent.parent / "canon" / "static" / "atlas.js"
    transit = osm.parse(_xml())["transit"]
    transit["stations"].append({"name": "밖", "x": 1.4, "y": 0.5, "lines": ["테스트선"]})  # 지도 밖 역은 그리지 않는다
    data = {"call": "atlasStations", "args": [transit, 1000, 333, 7]}
    out = json.loads(subprocess.run(["node", "-e", CALC, str(js)], input=json.dumps(data), capture_output=True, text=True, check=True).stdout)
    assert [s["name"] for s in out] == ["가역", "나", "다"]
    assert out[0]["box"] == pytest.approx([out[0]["x"] - 7, out[0]["y"] - 7, out[0]["x"] + 7, out[0]["y"] + 7])
    data = {"call": "atlasStations", "args": [None, 1000, 333, 7]}
    assert json.loads(subprocess.run(["node", "-e", CALC, str(js)], input=json.dumps(data), capture_output=True, text=True, check=True).stdout) == []
