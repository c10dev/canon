"""지도 만들기의 장소 종류가 지도 종류의 시대를 따르는지 (atlas.gen_places · gen_info, static/atlas-gen.js, 명령줄 map gen).
계약은 docs/map/specs/08-modern-kinds.md '종류 표'. node 시험은 node 가 있을 때만 돈다."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())
os.environ.setdefault("CANON_LLM", "mock")

import pytest  # noqa: E402

from canon import atlas, cli, store  # noqa: E402
from canon.maps import kinds as placekinds  # noqa: E402
from canon.schema import MapPlace, MapSpec, StoryElement  # noqa: E402

from .test_mapgen import _project  # noqa: E402

GEN = Path(__file__).resolve().parent.parent / "canon" / "static" / "atlas-gen.js"


def _modern_project():
    p = _project()
    p.elements.append(StoryElement(id="el-20", kind="장소", name="골목 편의점"))
    p.elements.append(StoryElement(id="el-21", kind="장소", name="강남역"))
    p.elements.append(StoryElement(id="el-22", kind="장소", name="보리밭"))
    return p


def _rows(p, spec=None) -> dict:
    return {x["key"]: x for x in atlas.gen_places(p, spec)}


def test_modern_place_table_uses_modern_ids():
    p = _modern_project()
    rows = _rows(p, MapSpec(kind="modern"))
    ids = set(placekinds.kind_ids("modern"))
    assert all(r["kind"] in ids and r["found"] in ids for r in rows.values())
    assert rows["el-20"]["kind"] == "convenience" and rows["el-20"]["word"] == "편의점"
    assert rows["el-21"]["kind"] == "station" and rows["el-10"]["kind"] == "far" and not rows["el-10"]["put"]
    assert rows["el-20"]["found_in"] == {"old": "home", "modern": "convenience"}
    # 마을 · 도시 · 지도 종류를 모를 때(spec 없음)는 옛 종류 그대로
    for spec in (None, MapSpec(kind="village"), MapSpec(kind="city")):
        rows = _rows(p, spec)
        assert rows["el-1"]["kind"] == "center" and rows["el-9"]["kind"] == "inn" and rows["el-20"]["kind"] == "home"


def test_saved_old_ids_are_read_through_the_map_table():
    p = _modern_project()
    old = [MapPlace(key="el-9", kind="inn"), MapPlace(key="el-1", kind="temple"), MapPlace(key="el-22", kind="field"),
           MapPlace(key="el-20", kind=""), MapPlace(key="el-21", kind="nope"), MapPlace(key="el-2", kind="shore")]
    rows = _rows(p, MapSpec(kind="modern", places=old))
    assert rows["el-9"]["kind"] == "hotel" and rows["el-1"]["kind"] == "church" and rows["el-2"]["kind"] == "shore"
    assert rows["el-22"]["kind"] == rows["el-22"]["found"] == "house"  # 밭은 현대 대응이 없어 찾은 값
    assert rows["el-20"]["kind"] == "convenience" and rows["el-21"]["kind"] == "station"  # 빈 값 · 모르는 id 도 찾은 값
    # 거꾸로: 현대 id 로 저장한 입력을 마을로 읽는다
    new = [MapPlace(key="el-9", kind="hotel"), MapPlace(key="el-20", kind="convenience"), MapPlace(key="el-1", kind="park")]
    rows = _rows(p, MapSpec(kind="village", places=new))
    assert (rows["el-9"]["kind"], rows["el-20"]["kind"], rows["el-1"]["kind"]) == ("inn", "home", "forest")


def test_gen_info_sends_kinds_per_map():
    info = atlas.gen_info(_modern_project())
    assert set(info["kinds"]) == set(atlas.MAKERS) and info["eras"] == {"village": "old", "city": "old", "modern": "modern"}
    for k in atlas.MAKERS:
        assert [x["id"] for x in info["kinds"][k]] == placekinds.kind_ids(k)
        assert all(x["label"] == placekinds.label(x["id"]) for x in info["kinds"][k])
    assert {"id": "convenience", "label": "편의점"} in info["kinds"]["modern"] and {"id": "inn", "label": "여관 · 주막"} not in info["kinds"]["modern"]
    for era in placekinds.ERAS:
        assert info["kind_to"][era] == {k.id: placekinds.to_era(k.id, era) for k in placekinds.KINDS}


def test_modern_title_falls_back_to_station():
    p = _modern_project()
    p.atlas.spec = MapSpec(kind="modern")
    assert atlas.village_title(p, {"buildings": []})["title"] == "강남역"
    p.atlas.spec = MapSpec(kind="village")
    assert atlas.village_title(p, {"buildings": []})["title"] == "흑송촌"


def test_cli_prints_kind_label_of_any_era(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    store.save("k", _modern_project())
    real = atlas.generate

    def fake(p, spec):  # 생성기(08b)가 현대 id 를 내는 것처럼
        out = real(p, spec)
        for s in out["pins"]:
            s["kind"] = {"el-20": "convenience", "el-21": "station"}.get(s["place"], s["kind"])
        return out
    monkeypatch.setattr(atlas, "generate", fake)
    cli.main(["map", "k", "gen", "modern", "--seed", "4", "--size", "작음", "-y"])
    out = capsys.readouterr().out
    assert "골목 편의점 → 편의점 자리" in out and "강남역 → 역 자리" in out


# ---------- atlas-gen.js 의 atlasKindShift (지도 종류를 바꿀 때 장소 종류 옮기기) ----------

SHIFT = """
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const part = src.slice(src.indexOf('// ----- 지도 종류를 바꿀 때'), src.indexOf('// ----- 지도 만들기 칸 -----'));
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const fn = eval(part + ';atlasKindShift');
process.stdout.write(JSON.stringify(fn(...data.args)));
"""


def _shift(*args):
    if not shutil.which("node"):
        pytest.skip("node 가 없어요")
    out = subprocess.run(["node", "-e", SHIFT, str(GEN)], input=json.dumps({"args": list(args)}), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_shift_follows_to_era_for_chosen_kinds():
    info = atlas.gen_info(_modern_project())
    kind_to = info["kind_to"]
    # 이름에서 찾은 값과 다른(작가가 고른) 종류는 to_era 대응표, 대응이 없으면 그 시대에서 찾은 값
    for k in placekinds.KINDS:
        for frm, to in (("old", "modern"), ("modern", "old")):
            rows = [{"key": "x", "kind": k.id, "put": True}]
            places = [{"key": "x", "found_in": {"old": "zz-old", "modern": "zz-modern"}}]
            got = _shift(rows, places, frm, to, kind_to)[0]
            want = placekinds.to_era(k.id, to) or f"zz-{to}"
            assert got == {"key": "x", "kind": want, "put": True}, (k.id, frm, to)


def test_shift_moves_found_kinds_to_the_new_era_and_back():
    info = atlas.gen_info(_modern_project())
    places = info["places"]
    rows = [{"key": x["key"], "kind": x["kind"], "put": x["put"]} for x in places]
    rows[[x["key"] for x in places].index("el-9")]["kind"] = "temple"  # 작가가 고친 줄
    modern = _shift(rows, places, "old", "modern", info["kind_to"])
    by = {r["key"]: r["kind"] for r in modern}
    assert by["el-20"] == "convenience" and by["el-21"] == "station" and by["el-9"] == "church" and by["el-22"] == "house"
    assert all(r["kind"] in placekinds.kind_ids("modern") for r in modern)
    back = {r["key"]: r["kind"] for r in _shift(modern, places, "modern", "old", info["kind_to"])}
    assert back["el-20"] == "home" and back["el-9"] == "temple" and back["el-1"] == "center" and back["el-22"] == "field"
    same = _shift(rows, places, "old", "old", info["kind_to"])
    assert same == rows


def test_shift_keeps_author_put_and_follows_default_put():
    kind_to = atlas.gen_info(_modern_project())["kind_to"]
    places = [{"key": "a", "found_in": {"old": "center", "modern": "far"}}, {"key": "b", "found_in": {"old": "center", "modern": "far"}},
              {"key": "c", "found_in": {"old": "far", "modern": "station"}}]
    rows = [{"key": "a", "kind": "center", "put": True}, {"key": "b", "kind": "center", "put": False}, {"key": "c", "kind": "far", "put": False}]
    got = _shift(rows, places, "old", "modern", kind_to)
    assert got == [{"key": "a", "kind": "far", "put": False}, {"key": "b", "kind": "far", "put": False},
                   {"key": "c", "kind": "station", "put": True}]
