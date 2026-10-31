"""건물 정보 테스트 (canon/maps/buildings.py, atlas.enrich · building · set_building): 재현성, 결과 모양, 주소, 쓰임 수, 이야기 장소,
작가가 고친 값, 옛 지도 파일 채우기, 웹 · 명령줄."""
import importlib
import json
import os
from collections import Counter

os.environ.setdefault("CANON_LLM", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from canon import atlas, cli, store  # noqa: E402
from canon.maps import buildings as bldgs  # noqa: E402
from canon.maps.gen import citygen, towngen  # noqa: E402
from canon.schema import Character, MapSpec  # noqa: E402

from .test_mapgen import _project  # noqa: E402

SPOTS = [{"key": "a", "name": "흑송촌", "kind": "center"}, {"key": "i", "name": "달빛 주막", "kind": "inn"},
         {"key": "s", "name": "쇠망치 대장간", "kind": "smith"}]


def _village(seed: int = 3) -> dict:
    return towngen.village(MapSpec(seed=seed, water="river"), SPOTS)


def _city(seed: int = 3) -> dict:
    return citygen.city(MapSpec(kind="city", seed=seed, size="small", water="river"), SPOTS)


@pytest.mark.parametrize("make", [_village, _city])
def test_describe_shape_and_reproducible(make):
    lo = make()
    a = bldgs.describe(lo, 3, "joseon")
    assert json.dumps(a, sort_keys=True) == json.dumps(bldgs.describe(lo, 3, "joseon"), sort_keys=True)
    assert json.dumps(a, sort_keys=True) != json.dumps(bldgs.describe(lo, 4, "joseon"), sort_keys=True)
    assert a["bver"] == bldgs.VERSION and len(a["blds"]) == len(lo["buildings"]) == len(lo["parts"])
    names = [s["name"] for s in a["streets"]]
    assert names and len(names) == len(set(names)) and all(names)  # 거리 이름은 겹치지 않는다
    mains = [b for b in a["blds"] if "of" not in b]
    assert len(mains) >= lo["houses"] and all(b["use"] in bldgs.USES for b in a["blds"])
    assert all(1 <= b["floors"] <= 3 for b in mains)  # Ross: 1~3층
    for b in a["blds"]:
        if "of" in b:  # 곁채 · 헛간은 본채를 가리킨다
            assert "of" not in a["blds"][b["of"]] and b["use"] in ("annex", "barn")
    # 주소: 거리마다 번지가 겹치지 않는다 (한쪽은 홀수, 다른 쪽은 짝수)
    seen = Counter((b["street"], b["no"]) for b in mains if "street" in b)
    assert seen and max(seen.values()) == 1 and all(no >= 1 for _, no in seen)
    # 이야기 장소가 놓인 건물은 그 장소의 이름과 쓰임
    by_place = {b.get("place"): b for b in mains if b.get("place")}
    assert by_place["i"]["use"] == "inn" and by_place["i"]["name"] == "달빛 주막"
    assert by_place["s"]["use"] == "smith"


def test_trade_counts_follow_population():
    """도시는 인구 ÷ SV 만큼 가게가 있다 (Ross). 신발 가게(SV 150)는 많고, 책방(SV 6300)은 작은 도시에 드물다."""
    lo = _city()
    a = bldgs.describe(lo, 3)
    people = sum(b.get("people", 0) for b in a["blds"])
    uses = Counter(b["use"] for b in a["blds"] if "of" not in b)
    assert 2000 < people < 8000
    assert people / 150 * 0.5 <= uses["shoemaker"] <= people / 150 * 1.6
    assert uses["bookseller"] <= 2 and uses["tavern"] >= 3
    v = bldgs.describe(_village(), 3)
    assert sum(b.get("people", 0) for b in v["blds"]) < 600  # 마을은 Ross 의 보통 마을(50~300명) 언저리


def test_street_names_follow_style():
    lo = _village()
    jo = {s["name"] for s in bldgs.describe(lo, 3, "joseon")["streets"]}
    we = {s["name"] for s in bldgs.describe(lo, 3, "western_fantasy")["streets"]}
    assert any(n.endswith("큰길") for n in jo) and any(n.endswith("대로") or n.endswith("거리") for n in we)
    assert bldgs.label("inn", "joseon") == "주막" and bldgs.label("inn", "wuxia") == "객잔" and bldgs.label("inn") == "여관"


def test_uploaded_layout_without_parts():
    """올린 Watabou 파일: 필지 정보가 없으면 모든 건물을 본채로 본다."""
    lo = _village()
    up = {k: v for k, v in lo.items() if k not in ("parts", "spots", "generator")}
    a = bldgs.describe(up, "layout-1.json")
    assert all("of" not in b for b in a["blds"]) and a["streets"]


def test_atlas_building_notes_and_title(tmp_path):
    p = _project()
    p.characters.append(Character(id="hero", name="윤서", role="주인공"))
    out = atlas.generate(p, MapSpec(seed=3, water="river"))
    lo = out["layout"]
    assert lo["bver"] == bldgs.VERSION and out["title"]["population"] == int(round(sum(b.get("people", 0) for b in lo["blds"]), -1))
    i = next(k for k, b in enumerate(lo["blds"]) if b.get("of") is not None)
    info = atlas.building(p, lo, i)
    assert info["main"] == lo["blds"][i]["of"] and info["label"] and info["street"] and not info["edited"]
    atlas.set_building(p, lo, i, "smith", "  윤서네   대장간 ", "주인공 집", ["hero"])  # 곁채를 고르면 본채를 고친다
    info = atlas.building(p, lo, i)
    assert (info["use"], info["label"], info["name"], info["residents"], info["edited"]) == ("smith", "대장간", "윤서네 대장간", ["hero"], True)
    assert [x.i for x in p.atlas.buildings] == [info["main"]]
    with pytest.raises(ValueError):
        atlas.set_building(p, lo, i, "spaceship", "", "", [])
    with pytest.raises(ValueError):
        atlas.set_building(p, lo, i, "", "", "", ["nobody"])
    with pytest.raises(KeyError):
        atlas.building(p, lo, 10 ** 6)
    atlas.set_building(p, lo, i, "", "", "", [])  # 모두 비우면 기록을 지운다
    assert p.atlas.buildings == []
    atlas.set_building(p, lo, i, "inn", "", "", [])
    atlas.apply_generated(tmp_path, p, MapSpec(seed=4, water="river"), [])
    assert p.atlas.buildings == []  # 다른 파일이 되면 건물 번호가 바뀌어 비운다
    assert any(label == "대장간" or n for label, n in atlas.building_counts(p, atlas.load_layout(tmp_path, p)))


def test_old_layout_file_is_filled(tmp_path):
    """이 기능 전에 저장한 지도 파일은 처음 읽을 때 건물 정보를 채워 다시 쓴다."""
    p = _project()
    lo = _village()
    (tmp_path / "gen-village-3.json").write_text(json.dumps(lo, ensure_ascii=False), encoding="utf-8")
    p.atlas.layout = "gen-village-3.json"
    got = atlas.load_layout(tmp_path, p)
    assert got["bver"] == bldgs.VERSION and got["blds"]
    assert json.loads((tmp_path / "gen-village-3.json").read_text(encoding="utf-8"))["bver"] == bldgs.VERSION
    assert "건물 쓰임: " in atlas.describe(p, got)


def test_web_and_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store as st, web

    importlib.reload(st)
    importlib.reload(web)
    p = _project()
    p.characters.append(Character(id="hero", name="윤서", role="주인공"))
    st.save("b", p)
    c = TestClient(web.app)
    assert c.post("/api/projects/b/atlas/generate", json={"spec": {"seed": 5, "water": "river"}, "pins": []}).status_code == 200
    v = c.get("/api/projects/b/atlas").json()
    assert v["gen"]["uses"]["smith"][0] == "대장간"
    lo = c.get("/api/projects/b/atlas/layout").json()
    assert lo["blds"] and lo["streets"]
    b = c.get("/api/projects/b/atlas/buildings/0").json()
    assert b["street"] and b["label"]
    r = c.put("/api/projects/b/atlas/buildings/0", json={"use": "inn", "name": "윤서네 여관", "residents": ["hero"]})
    assert r.status_code == 200 and r.json()["atlas"]["buildings"][0]["residents"] == ["hero"]
    assert c.get("/api/projects/b/atlas/buildings/0").json()["name"] == "윤서네 여관"
    assert c.put("/api/projects/b/atlas/buildings/0", json={"use": "rocket"}).status_code == 400
    assert c.get("/api/projects/b/atlas/buildings/999999").status_code == 404
    assert c.delete("/api/projects/b/atlas/layout").json()["atlas"]["buildings"] == []

    monkeypatch.setattr(store, "ROOT", tmp_path)
    cli.main(["map", "b", "gen", "--seed", "6", "-y"])
    capsys.readouterr()
    cli.main(["map", "b"])
    assert "건물 쓰임: " in capsys.readouterr().out
