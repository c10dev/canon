"""장소 종류 기호와 범례 (static/atlas-icons.js, atlas.summary 의 장소 kind). 명세는 docs/map/specs/15-place-icons.md.
node 시험은 node 가 있을 때만 돈다."""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())
os.environ.setdefault("CANON_LLM", "mock")

import pytest  # noqa: E402

from canon import atlas, placekinds  # noqa: E402
from canon.schema import MapPin, MapPlace, MapSpec, StoryElement  # noqa: E402

from .test_mapgen import _project  # noqa: E402

ICONS = Path(__file__).resolve().parent.parent / "canon" / "static" / "atlas-icons.js"

# 기호 표 ~ 범례 칸 나누기 구간만 잘라 돌린다: 입력 { expr: 돌릴 식 }
CALC = """
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const part = src.slice(src.indexOf('// ----- 기호 표'), src.indexOf('// ----- 범례 그리기'));
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(eval(part + ';' + data.expr)));
"""


def _js(expr: str):
    if not shutil.which("node"):
        pytest.skip("node 가 없어요")
    out = subprocess.run(["node", "-e", CALC, str(ICONS)], input=json.dumps({"expr": expr}), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_icon_table_matches_kind_table():
    t = _js("({ of: ATLAS_ICON_OF, icons: ATLAS_ICONS })")
    # 종류 id 마다 기호가 하나 (차례도 placekinds.KINDS), 쓰지 않는 기호는 없다
    assert list(t["of"]) == [k.id for k in placekinds.KINDS]
    assert set(t["of"].values()) == set(t["icons"])
    for name, d in t["icons"].items():
        assert d.startswith("M") and d.endswith("Z"), name
        nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", d)]
        assert nums and max(abs(v) for v in nums) <= 10.5, name  # −10~10 칸 안


def test_icon_for_shares_similar_kinds():
    got = _js("['inn', 'hotel', 'home', 'house', 'market', 'mart', 'station', 'temple', 'church', '', 'zz'].map(atlasIconFor)")
    assert got == ["bed", "bed", "house", "house", "stall", "stall", "train", "temple", "steeple", "", ""]


def test_holes_wind_against_solid_parts():
    # 구멍은 시계 반대, 채운 조각은 시계 방향 (nonzero 한 path 로 칠한다)
    area = "(r) => r.reduce((s, q, i) => { const n = r[(i + 1) % r.length]; return s + q[0] * n[1] - n[0] * q[1]; }, 0)"
    got = _js(f"[atlasGlyphRing(['r', -5, -5, 10, 10]), atlasGlyphRing(['-c', 0, 0, 3]), atlasGlyphRing(['p', [[0, 0], [0, 5], [5, 0]]])]"
              f".map((rs) => Math.sign(({area})(rs[0])))")
    assert got == [1, -1, 1]


def test_legend_lists_only_kinds_on_the_map_once():
    pins = [{"kind": "hotel", "kind_label": "호텔 · 모텔"}, {"kind": "inn", "kind_label": "여관 · 주막"}, {"kind": "inn", "kind_label": "여관 · 주막"},
            {"kind": "station", "kind_label": "역"}, {"kind": "", "kind_label": ""}, {"kind": "zz", "kind_label": "zz"}]
    rows = _js(f"atlasLegendKinds({json.dumps(pins, ensure_ascii=False)})")
    # 기호 표 차례, 같은 기호는 한 줄에 이름을 잇고, 모르는 종류 · 빈 종류는 빠진다
    assert rows == [{"icon": "bed", "kinds": ["inn", "hotel"], "label": "여관 · 주막, 호텔 · 모텔"},
                    {"icon": "train", "kinds": ["station"], "label": "역"}]
    assert _js("atlasLegendKinds([])") == []


def test_legend_fit_adds_columns_then_cuts():
    rows = "[...Array(10).keys()].map((i) => ({ icon: 'house', kinds: ['k' + i, 'q' + i], label: 'x' }))"
    fit = lambda maxw: _js(f"(() => {{ const f = atlasLegendFit({rows}, 10, () => 50, {maxw}, 40, 5); "  # noqa: E731
                           "return { cols: f.cols.map((c) => c.map((r) => r.label)), more: f.more, w: f.w }; })()")
    # 높이에 네 줄 → 세 열이면 다 들어간다
    wide = fit(200)
    assert [len(c) for c in wide["cols"]] == [4, 4, 2] and wide["more"] == 0 and wide["w"] == 160
    # 폭이 모자라면 두 열로 줄이고 마지막 칸을 '외 n종'으로 (못 보인 줄 셋 = 종류 여섯)
    narrow = fit(110)
    assert [len(c) for c in narrow["cols"]] == [4, 4] and narrow["more"] == 6 and narrow["cols"][1][-1] == "외 6종"
    # 한 열도 모자라면 한 열에 넣을 만큼만
    one = fit(20)
    assert [len(c) for c in one["cols"]] == [4] and one["cols"][0][-1] == "외 14종"


# ----- 서버: 장소 값의 kind -----


def _places_project():
    p = _project()
    for i, name in enumerate(["강남역", "골목 편의점", "달빛 주막"]):
        p.elements.append(StoryElement(id=f"el-3{i}", kind="장소", name=name))
    return p


def _kinds(s: dict) -> dict:
    return {x["name"]: (x["kind"], x["kind_label"]) for x in s["places"]}


def test_map_era_follows_layout_then_spec_then_style():
    p = _places_project()
    assert atlas.map_era(p, {"generator": "osm"}) == "modern"
    assert atlas.map_era(p, {"generator": "canon-modern"}) == "modern"
    assert atlas.map_era(p, {"generator": "canon-village"}) == "old"
    assert atlas.map_era(p, {"generator": ""}) == "old"  # Watabou 마을 데이터
    p.atlas.spec = MapSpec(kind="modern")
    assert atlas.map_era(p, None) == "modern"
    assert atlas.map_era(p, {"generator": "canon-city"}) == "old"  # 지도 데이터가 먼저
    p.atlas.spec = None
    p.world.name_style = "korea_modern"
    assert atlas.map_era(p, None) == "modern"
    p.world.name_style = "western_fantasy"
    assert atlas.map_era(p, None) == "old"


def test_summary_sends_kind_of_the_map_era():
    p = _places_project()
    lo = atlas.generate(p, MapSpec(kind="modern", seed=3))["layout"]
    modern = _kinds(atlas.summary(p, lo))
    assert modern["강남역"] == ("station", "역") and modern["골목 편의점"] == ("convenience", "편의점")
    assert modern["달빛 주막"] == ("house", "집 · 단독주택")  # 현대 종류에는 '주막' 낱말이 없어 현대 기본값
    assert all(k in placekinds.kind_ids("modern") for k, _ in modern.values())
    lo = atlas.generate(p, MapSpec(kind="village", seed=3))["layout"]
    old = _kinds(atlas.summary(p, lo))
    assert old["달빛 주막"] == ("inn", "여관 · 주막") and all(k in placekinds.kind_ids("village") for k, _ in old.values())


def test_chosen_kind_wins_and_moves_to_the_map_era():
    p = _places_project()
    # 작가가 마을 지도에서 '달빛 주막'을 대장간으로 골랐다: 마을 지도는 smith, 현대 지도는 대응표로 factory
    p.atlas.spec = MapSpec(kind="village", places=[MapPlace(key="el-32", kind="smith"), MapPlace(key="el-30", kind="field")])
    p.atlas.pins = [MapPin(place="el-32", x=0.5, y=0.5)]
    assert _kinds(atlas.summary(p, None))["달빛 주막"] == ("smith", "대장간 · 공방")
    era_kinds = atlas.place_kinds(p, "modern")
    assert era_kinds["el-32"] == "factory"
    assert era_kinds["el-30"] == "station"  # 밭은 현대 대응이 없어 이름에서 찾는다
