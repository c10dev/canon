"""지도(canon/atlas.py) 테스트 (mock LLM): 장소 목록, 위치 글 맞추기, 화별 자리, 맞지 않은 위치, 자리 저장, CLI, 웹. 실행: python -m pytest tests"""
import base64
import importlib
import os
import tempfile

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())  # 다른 테스트 파일보다 먼저 store 를 불러와도 저장소를 더럽히지 않게
os.environ.setdefault("CANON_LLM", "mock")  # 이 파일만 돌려도 가짜 LLM 으로

from fastapi.testclient import TestClient  # noqa: E402

from canon import atlas, cli, pipeline, prompts, store
from canon.llm import get_llm
from canon.schema import CharacterState, MapPin, Project, StoryElement

from .test_storylines import _short

# 화별 인물 위치 (상태 변경안이 적었다고 치는 글)
WALK = {
    1: {"hero": "등대 앞 방파제", "ally": "수산시장"},
    2: {"hero": "흑송촌 여관", "ally": "수산시장 생선 가게"},
    3: {"hero": "흑송촌에서 등대로 가는 버스 안", "ally": "어딘지 모를 지하실"},
}


def _project() -> Project:
    p = _short(6)
    p.world.locations = ["등대: 마을 끝 하얀 등대", "수산시장"]
    p.elements.append(StoryElement(id="el-1", kind="장소", name="흑송촌", aliases=["흑송 마을"], description="산 아래 마을", found_in="본문", found_ep=2))
    p.elements.append(StoryElement(id="el-2", kind="장소", name="등대", description="요소로도 적은 등대", reveal_ep=4))
    p.elements.append(StoryElement(id="el-3", kind="물건", name="수산시장 열쇠"))
    return p


def _played(n_eps=3) -> Project:
    p = _project()
    for n in range(1, n_eps + 1):
        pipeline.confirm_plot(p, n)
        p.episode(n).text = pipeline.write_episode(get_llm("write"), p, n) + ("\n흑송촌 사람들은 말이 없었다." if n == 2 else "")
        p.episode(n).status = "written"
        d = pipeline.extract_state(get_llm("state"), p, n)
        d.new_places = []
        d.character_updates = [CharacterState(character_id=cid, location=loc) for cid, loc in WALK[n].items()]
        pipeline.apply_delta(p, d)
    return p


def test_places_merge_elements_and_setting():
    pls = atlas.places(_project())
    assert [pl["key"] for pl in pls] == ["el-1", "el-2", "w:수산시장"]  # 설정의 '등대'는 같은 이름 요소가 있어 뺀다
    by = {pl["key"]: pl for pl in pls}
    assert by["el-1"]["known_from"] == 2 and by["el-2"]["known_from"] == 4 and by["w:수산시장"]["known_from"] == 0
    p = Project()
    p.world.locations = ["등대: 마을 끝 하얀 등대"]
    pl = atlas.places(p)[0]
    assert (pl["key"], pl["name"], pl["description"], pl["source"]) == ("w:등대", "등대", "마을 끝 하얀 등대", "설정")


def test_match_location_text():
    p = _project()
    assert atlas.match(p, "등대 앞 방파제") == ["el-2"]
    assert atlas.match(p, "흑송 마을 어귀") == ["el-1"]  # 다른 이름
    assert atlas.match(p, "흑송촌에서 등대로 가는 버스 안") == ["el-1", "el-2"]  # 떠난 곳, 갈 곳 순
    assert atlas.match(p, "흑 송 촌") == ["el-1"]  # 띄어쓰기 무시
    assert atlas.match(p, "어딘지 모를 지하실") == [] and atlas.match(p, "") == []
    p.elements.append(StoryElement(id="el-4", kind="장소", name="수산시장 2층"))
    assert atlas.match(p, "수산시장 2층 사무실") == ["el-4"]  # 긴 이름 안의 짧은 이름은 뺀다
    atlas.set_link(p, "어딘지 모를 지하실", "el-1")
    assert atlas.match(p, "어딘지 모를 지하실") == ["el-1"]
    atlas.set_link(p, "어딘지 모를 지하실", "")
    assert atlas.match(p, "어딘지 모를 지하실") == []


def test_frames_follow_locations():
    p = _played()
    fs = atlas.frames(p)
    assert [f["episode"] for f in fs] == [0, 1, 2, 3]
    row = lambda f, cid: next(r for r in f["rows"] if r["cid"] == cid)  # noqa: E731
    assert row(fs[1], "hero")["place"] == "el-2" and not row(fs[1], "hero")["moved"]
    assert row(fs[2], "hero")["place"] == "el-1" and row(fs[2], "hero")["moved"]
    h3 = row(fs[3], "hero")
    assert h3["place"] == "el-2" and h3["via"] == ["el-1"] and h3["moved"]
    assert row(fs[2], "ally")["place"] == "w:수산시장" and not row(fs[2], "ally")["moved"]
    assert row(fs[3], "ally")["place"] == "" and row(fs[3], "ally")["location"] == "어딘지 모를 지하실"
    assert "el-1" in fs[2]["mentioned"]


def test_unmatched_and_links():
    p = _played()
    s = atlas.summary(p)
    assert [u["text"] for u in s["unmatched"]] == ["어딘지 모를 지하실"]
    assert s["unmatched"][0]["episodes"] == [3] and s["unmatched"][0]["characters"] == ["ally"]
    atlas.set_link(p, "어딘지 모를 지하실", "")  # 지도에 그리지 않음
    assert atlas.summary(p)["unmatched"] == []
    atlas.set_link(p, "어딘지 모를 지하실", None)  # 잇기 지우기
    assert len(atlas.summary(p)["unmatched"]) == 1
    try:
        atlas.set_link(p, "어딘지 모를 지하실", "el-404")
        raise AssertionError("없는 장소에 이었다")
    except ValueError:
        pass


def test_pins_are_clamped_and_pruned():
    p = _project()
    atlas.set_pins(p, [MapPin(place="el-1", x=1.4, y=-0.2), MapPin(place="nope", x=0.5, y=0.5), MapPin(place="el-1", x=0.3, y=0.4),
                       MapPin(place="w:수산시장", x=0.1, y=0.9)])
    assert [(x.place, x.x, x.y) for x in p.atlas.pins] == [("el-1", 0.3, 0.4), ("w:수산시장", 0.1, 0.9)]
    p.world.locations = []
    atlas.prune(p)
    assert [x.place for x in p.atlas.pins] == ["el-1"]
    assert {pl["key"]: pl["pin"] for pl in atlas.summary(p)["places"]}["el-1"] == [0.3, 0.4]


def test_old_project_has_empty_atlas():
    p = Project.model_validate({"meta": {"title": "옛 작품"}})
    assert p.atlas.pins == [] and p.atlas.image == "" and p.atlas.aspect == 1.5
    assert atlas.summary(p)["frames"][0]["episode"] == 0


def test_state_prompt_asks_for_place_names():
    p = _played(1)
    assert "location 에는 [이미 있는 장소]" in prompts.state_prompt(p, 1)


def test_cli_map(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    store.save("mapdemo", _played())
    cli.main(["map", "mapdemo"])
    out = capsys.readouterr().out
    assert "흑송촌 (요소) · 2화부터 독자가 앎 · 지도에 아직 안 놓음" in out
    assert "1화 등대 → 2화 흑송촌 → 3화 등대" in out
    assert "'어딘지 모를 지하실'" in out


PNG = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                  "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()


def test_web_atlas(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store as st, web

    importlib.reload(st)
    importlib.reload(web)
    st.save("w", _played())
    c = TestClient(web.app)
    r = c.get("/api/projects/w/atlas").json()
    assert [f["episode"] for f in r["frames"]] == [0, 1, 2, 3] and r["image"] == "" and len(r["unmatched"]) == 1

    pr = c.put("/api/projects/w/atlas/pins", json={"pins": [{"place": "el-1", "x": 0.2, "y": 0.3}]}).json()
    assert pr["atlas"]["pins"] == [{"place": "el-1", "x": 0.2, "y": 0.3, "spot": ""}]  # 마을 데이터가 없으면 건물 한 줄이 비어 있다
    pr = c.put("/api/projects/w/atlas/links", json={"text": "어딘지 모를 지하실", "place": "w:수산시장"}).json()
    assert pr["atlas"]["links"] == [{"text": "어딘지 모를 지하실", "place": "w:수산시장"}]
    assert c.put("/api/projects/w/atlas/links", json={"text": "x", "place": "nope"}).status_code == 400

    assert c.put("/api/projects/w/atlas/image", json={"data": "data:image/svg+xml;base64,PHN2Zy8+", "aspect": 1}).status_code == 400
    assert c.get("/api/projects/w/atlas/image").status_code == 404
    pr = c.put("/api/projects/w/atlas/image", json={"data": PNG, "aspect": 1.75}).json()
    name = pr["atlas"]["image"]
    assert name.endswith(".png") and pr["atlas"]["aspect"] == 1.75
    got = c.get("/api/projects/w/atlas/image")
    assert got.status_code == 200 and got.content.startswith(b"\x89PNG")
    pr = c.delete("/api/projects/w/atlas/image").json()
    assert pr["atlas"]["image"] == "" and not (tmp_path / "w" / "map" / name).exists()
    assert pr["atlas"]["pins"]  # 자리는 그대로

    # 저장한 그림 · 마을 이름이 map/ 밖을 가리켜도 지우는 길이 그 파일을 지우지 않는다
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    c.put("/api/projects/w/atlas/image", json={"data": PNG, "aspect": 1})
    for bad in ["../../victim.txt", str(victim)]:
        pj = c.get("/api/projects/w").json()
        pj["atlas"]["image"], pj["atlas"]["layout"] = bad, bad
        assert c.put("/api/projects/w?force=true", json=pj).status_code == 200
        assert c.delete("/api/projects/w/atlas/image").status_code == 200
        pj = c.get("/api/projects/w").json()
        pj["atlas"]["layout"] = bad
        assert c.put("/api/projects/w?force=true", json=pj).status_code == 200
        assert c.delete("/api/projects/w/atlas/layout").status_code == 200
        assert victim.read_text(encoding="utf-8") == "keep"


def test_clean_and_apply_sort():
    from canon.schema import NewPlace, PlaceGuess, PlaceSort

    p = _played()
    items = [{"text": "어딘지 모를 지하실", "characters": ["ally"], "episodes": [3]},
             {"text": "서재", "characters": ["hero"], "episodes": [2, 3]},
             {"text": "폐교 운동장", "characters": ["hero"], "episodes": [4]},
             {"text": "폐교 교실", "characters": ["ally"], "episodes": [5]},
             {"text": "꿈속", "characters": ["hero"], "episodes": [2]}]
    out = PlaceSort(matches=[PlaceGuess(text="서재", place="흑송 마을"),  # 다른 이름도 키로
                             PlaceGuess(text="폐교 운동장", new_place="폐 교"),
                             PlaceGuess(text="폐교 교실", new_place="폐교"),
                             PlaceGuess(text="꿈속", skip=True, note="꿈"),
                             PlaceGuess(text="없던 글", place="등대")],
                    new_places=[NewPlace(name="폐교", kind="학교", description="산 너머 문 닫은 학교"),
                                NewPlace(name="수산시장", description="이미 있는 곳")])
    s = atlas.clean_sort(p, items, [out])
    rows = {r["text"]: r for r in s["rows"]}
    assert rows["서재"]["place"] == "el-1" and rows["어딘지 모를 지하실"]["place"] == "" and not rows["어딘지 모를 지하실"]["skip"]
    assert rows["폐교 운동장"]["new_place"] == "폐교" and rows["폐교 교실"]["new_place"] == "폐교"
    assert rows["꿈속"]["skip"] and rows["꿈속"]["note"] == "꿈"
    assert [(x["name"], x["first_ep"]) for x in s["new_places"]] == [("폐교", 4)]  # 이미 있는 수산시장은 뺀다

    picks = [("서재", "el-1", ""), ("폐교 운동장", "", "폐교"), ("꿈속", "", "")]
    done = atlas.apply_sort(p, [(NewPlace(**{k: v for k, v in x.items() if k != "first_ep"}), x["first_ep"]) for x in s["new_places"]], picks)
    assert done == {"added": ["폐교"], "linked": 3}
    el = next(e for e in p.elements if e.name == "폐교")
    assert (el.kind, el.found_in, el.found_ep) == ("장소", "본문", 4) and "학교" in el.description
    assert atlas.match(p, "서재") == ["el-1"] and atlas.match(p, "폐교 운동장") == [el.id] and atlas.match(p, "꿈속") == []
    assert atlas.match(p, "폐교 교실") == [el.id]  # 등록한 이름이 들어 있으면 잇지 않아도 맞는다
    try:
        atlas.apply_sort(p, [], [("x", "el-404", "")])
        raise AssertionError("없는 장소에 이었다")
    except ValueError:
        pass


def test_sort_places_prompt_and_mock():
    p = _played()
    p.episode(3).summary = "도현이 지하 창고에 갇힌다."
    items = atlas.unmatched(p, atlas.frames(p))
    text = prompts.place_sort_prompt(p, items, atlas.places(p))
    assert "어딘지 모를 지하실 — 도현 · 3화" in text and "3화: 도현이 지하 창고에 갇힌다." in text and "- 흑송촌 (다른 이름: 흑송 마을)" in text
    s = pipeline.sort_places(get_llm("state"), p)
    assert [r["text"] for r in s["rows"]] == ["어딘지 모를 지하실"] and s["rows"][0]["skip"]
    try:
        pipeline.sort_places(get_llm("state"), p, ["없는 글"])
        raise AssertionError("맞지 않은 글이 없는데 불렀다")
    except ValueError:
        pass


def test_web_atlas_sort(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store as st, web

    importlib.reload(st)
    importlib.reload(web)
    p = _played()
    p.characters[0].name = p.characters[0].name or "서윤"
    st.save("s", p)
    c = TestClient(web.app)
    r = c.post("/api/projects/s/atlas/sort", json={}).json()
    assert r["rows"][0]["text"] == "어딘지 모를 지하실" and r["rows"][0]["skip"]
    body = {"picks": [{"text": "어딘지 모를 지하실", "new_place": "지하 창고"}],
            "new_places": [{"name": "지하 창고", "kind": "건물", "description": "시장 밑 창고", "first_ep": 3}]}
    r = c.post("/api/projects/s/atlas/sort/apply", json=body).json()
    assert r["added"] == ["지하 창고"] and r["linked"] == 1
    v = c.get("/api/projects/s/atlas").json()
    assert v["unmatched"] == [] and any(pl["name"] == "지하 창고" and pl["known_from"] == 3 for pl in v["places"])
    assert c.post("/api/projects/s/atlas/sort", json={}).status_code == 400  # 이제 정리할 글이 없다


# ---------- 마을 데이터 (Watabou 생성기 JSON) ----------

def _village() -> dict:
    """Watabou 마을 생성기 내보내기와 같은 모양. -50~50 정사각형, 가운데 (0, 0) 에서 만나는 십자 길,
    다른 길과 닿지 않는 다리 하나, 건물 둘."""
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "values", "generator": "vg", "version": "1.6.9", "roadWidth": 7},
        {"type": "Polygon", "id": "earth", "coordinates": [[[-50, -50], [50, -50], [50, 50], [-50, 50], [-50, -50]]]},
        {"type": "MultiPolygon", "id": "buildings", "coordinates": [
            [[[-44, -14], [-36, -14], [-36, -6], [-44, -6], [-44, -14]]],
            [[[6, 36], [14, 36], [14, 44], [6, 44], [6, 36]]]]},
        {"type": "MultiPoint", "id": "trees", "coordinates": [[20, -20], [25, -25]]},
        {"type": "GeometryCollection", "id": "roads", "geometries": [
            {"type": "LineString", "width": 1.4, "coordinates": [[-50, 0], [0, 0], [50, 0]]},
            {"type": "LineString", "width": 1.4, "coordinates": [[0, -50], [0, 0]]},
            {"type": "LineString", "width": 1.4, "coordinates": [[0, 0], [0, 50]]}]},
        {"type": "GeometryCollection", "id": "planks", "geometries": [
            {"type": "LineString", "width": 3.5, "coordinates": [[30, 30], [35, 30]]}]},
        {"type": "MultiPolygon", "id": "water", "coordinates": [[[[30, 20], [40, 20], [40, 40], [30, 40], [30, 20]]]]},
        {"type": "MultiPolygon", "id": "fields", "coordinates": []},
    ]}


def test_read_layout_and_route():
    lo = atlas.read_layout(_village())
    assert (lo["w"], lo["h"], lo["generator"]) == (100, 100, "vg")
    assert [r["kind"] for r in lo["roads"]] == ["road", "road", "road", "bridge"]
    assert lo["roads"][0]["points"] == [[0, 0.5], [0.5, 0.5], [1, 0.5]]  # 0~1, y 는 아래로
    assert len(lo["buildings"]) == 2 and len(lo["water"]) == 1 and lo["trees"] == [[0.7, 0.3], [0.75, 0.25]]
    g = atlas.road_graph(lo)
    assert len(g["segs"]) == 4  # 닿지 않은 다리는 뺀다
    # 건물 가운데 (-40, -10) → 길 (-40, 0) → (0, 0) → (0, 40) → 건물 가운데 (10, 40)
    r = atlas.route(g, [0.1, 0.4], [0.6, 0.9])
    assert round(r["length"], 6) == 100
    assert r["points"] == [[0.1, 0.4], [0.1, 0.5], [0.5, 0.5], [0.5, 0.9], [0.6, 0.9]]
    assert atlas.route(g, [0.1, 0.4], [0.1, 0.4])["length"] == 0
    for bad in ({}, {"type": "FeatureCollection", "features": [{"type": "Polygon", "id": "earth", "coordinates": [[[0, 0], [1, 0], [1, 1]]]}]}):
        try:
            atlas.read_layout(bad)
            raise AssertionError("잘못된 파일을 읽었다")
        except ValueError:
            pass



def test_route_walks_around_buildings_and_water():
    """길까지 가는 구간이 다른 건물 · 물을 지나면 돌아간다. 출발 건물은 지나갈 수 있다."""
    v = _village()
    blocks = v["features"][2]["coordinates"]
    blocks.append([[[-48, -5], [-32, -5], [-32, -2], [-48, -2], [-48, -5]]])  # 집 (-40, -10) 과 길 (y=0) 사이를 막는 긴 건물
    lo = atlas.read_layout(v)
    g = atlas.road_graph(lo)
    r = atlas.route(g, [0.1, 0.4], [0.6, 0.9])
    assert r["length"] > 101  # 곧장 내려가면 100
    inside = lambda q: 0.02 < q[0] < 0.18 and 0.45 < q[1] < 0.48  # noqa: E731  막는 건물 (0~1)
    for (ax, ay), (bx, by) in zip(r["points"], r["points"][1:]):
        assert not any(inside((ax + (bx - ax) * s / 50, ay + (by - ay) * s / 50)) for s in range(51))
    assert r["points"][0] == [0.1, 0.4] and r["points"][-1] == [0.6, 0.9]
    # 물 (30~40, 20~40) 건너편 두 자리는 길을 타지 않고 물을 돌아간다
    pts, length = atlas._walk(g, (78, 75), (92, 75))
    assert length > 14 and all(not (80 < x < 90 and 70 < y < 90) for x, y in pts)
    # 물 한가운데 놓인 자리는 나갈 빈 땅이 가까이 없으니 곧장 걷는다
    assert atlas._walk(g, (85, 80), (60, 80)) == ([(85, 80), (60, 80)], 25)

def test_routes_on_frames():
    p = _played()
    atlas.set_pins(p, [MapPin(place="el-2", x=0.1, y=0.4), MapPin(place="el-1", x=0.6, y=0.9)])  # 등대, 흑송촌
    s = atlas.summary(p, atlas.read_layout(_village()))
    row = lambda f, cid: next(r for r in f["rows"] if r["cid"] == cid)  # noqa: E731
    assert "route" not in row(s["frames"][1], "hero")  # 처음 자리는 옮긴 게 아니다
    assert row(s["frames"][2], "hero")["route"] == {"points": [[0.1, 0.4], [0.1, 0.5], [0.5, 0.5], [0.5, 0.9], [0.6, 0.9]],
                                                     "meters": 100, "minutes": 1}
    assert row(s["frames"][3], "hero")["route"]["points"][0] == [0.6, 0.9]  # 흑송촌에서 등대로 돌아온다
    assert s["aspect"] == 1 and s["layout"]["roads"] == 3 and s["layout"]["bridges"] == 1 and s["layout"]["width_m"] == 100
    atlas.set_meters(p, 2.5)
    s = atlas.summary(p, atlas.read_layout(_village()))
    assert row(s["frames"][2], "hero")["route"]["meters"] == 250 and row(s["frames"][2], "hero")["route"]["minutes"] == 3
    assert "길 따라 250m · 약 3분" in atlas.describe(p, atlas.read_layout(_village()))
    try:
        atlas.set_meters(p, 0)
        raise AssertionError("0m 축척을 받았다")
    except ValueError:
        pass
    q = Project.model_validate({"meta": {"title": "옛 작품"}})
    assert q.atlas.layout == "" and q.atlas.meters == 1.0 and atlas.summary(q)["layout"] is None


def test_web_atlas_layout(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store as st, web

    importlib.reload(st)
    importlib.reload(web)
    st.save("v", _played())
    c = TestClient(web.app)
    assert c.get("/api/projects/v/atlas/layout").status_code == 404
    assert c.put("/api/projects/v/atlas/layout", json={"data": "{not json"}).status_code == 400
    assert c.put("/api/projects/v/atlas/layout", json={"data": json.dumps({"type": "Feature"})}).status_code == 400
    pr = c.put("/api/projects/v/atlas/layout", json={"data": json.dumps(_village())}).json()
    name = pr["atlas"]["layout"]
    assert name.startswith("layout-") and (tmp_path / "v" / "map" / name).is_file()
    assert c.get("/api/projects/v/atlas/layout").json()["roads"][0]["kind"] == "road"
    c.put("/api/projects/v/atlas/pins", json={"pins": [{"place": "el-2", "x": 0.1, "y": 0.4}, {"place": "el-1", "x": 0.6, "y": 0.9}]})
    v = c.get("/api/projects/v/atlas").json()
    hero = next(r for r in v["frames"][2]["rows"] if r["cid"] == "hero")
    assert v["layout"]["file"] == name and hero["route"]["meters"] == 100
    assert c.put("/api/projects/v/atlas/meters", json={"meters": 2}).json()["atlas"]["meters"] == 2
    assert c.put("/api/projects/v/atlas/meters", json={"meters": -1}).status_code == 400
    pr = c.delete("/api/projects/v/atlas/layout").json()
    assert pr["atlas"]["layout"] == "" and not (tmp_path / "v" / "map" / name).exists() and len(pr["atlas"]["pins"]) == 2
    assert c.get("/api/projects/v/atlas").json()["layout"] is None
