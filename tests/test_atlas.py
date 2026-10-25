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
    assert pr["atlas"]["pins"] == [{"place": "el-1", "x": 0.2, "y": 0.3}]
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
