"""원형 도감: 목록 점검, 빈 칸만 채우기, 비틀기 한 줄, 주사위, 고른 원형 기록, 웹 · 명령줄."""
import importlib
import random
import typing

import pytest
from fastapi.testclient import TestClient

from canon import archetypes, dynamics, genres, prompts
from canon.schema import Character, Meta, Project


def test_catalog_is_consistent():
    ids = [a.id for a in archetypes.CATALOG]
    assert len(ids) == len(set(ids)) and len(ids) >= 30
    for a in archetypes.CATALOG:
        assert a.group in archetypes.GROUPS, a.id
        assert set(a.genres) <= set(genres.BY_ID), a.id
        assert len(a.twists) >= 2 and a.avoid and a.summary and a.goal and a.wound and a.speech and a.arc, a.id
        for v in a.views:
            assert set(v.words + v.back) <= set(dynamics.VIEWS), a.id
    assert len({w.id for w in archetypes.WOUNDS}) == len(archetypes.WOUNDS)
    assert len({s.id for s in archetypes.SPEECH}) == len(archetypes.SPEECH)
    assert all(set(s.genres) <= set(genres.BY_ID) for s in archetypes.SPEECH)
    assert set(archetypes.FILL_LABELS) <= set(Character.model_fields)
    # 모든 장르에 공통 원형이 붙는다
    assert {g for g in archetypes.GROUPS if any(a.group == g for a in archetypes.CATALOG)} == set(archetypes.GROUPS)


def test_match_puts_genre_first_then_common():
    got = archetypes.match(["martial_arts"])
    names = [a.id for a in got]
    assert "last_disciple" in names and "villainess" not in names
    first_common = next(i for i, a in enumerate(got) if not a.genres)
    assert all(a.genres for a in got[:first_common]) and not any(a.genres for a in got[first_common:])
    assert len(archetypes.match([])) == len(archetypes.CATALOG)


def test_fill_only_empty_fields():
    c = Character(id="hero", name="", role="주인공", goal="왕이 되는 것")
    filled = archetypes.fill(c, archetypes.get("regret_male"))
    assert c.role == "주인공" and c.goal == "왕이 되는 것"  # 쓴 칸은 그대로
    assert c.gender == "남" and c.personality and c.speech_style.startswith("짧은 명령형")
    assert set(filled) == {"gender", "personality", "wound", "speech_style", "arc"}
    assert archetypes.fill(c, archetypes.get("regret_male")) == []  # 다시 해도 덮지 않는다


def test_parts_replace_archetype_examples():
    c = Character(id="a", name="", role="")
    archetypes.fill(c, archetypes.get("regressor"), archetypes.WOUND_BY_ID["betrayed"], archetypes.SPEECH_BY_ID["haoche"])
    assert "믿으면 진다" in c.wound and c.speech_style.startswith("하오체")
    assert "회복: 다시 한 번 믿는 위험을 진다" in c.arc
    assert c.secrets == ["회귀했다는 것과 아는 미래"]


def test_twist_is_one_line_even_on_filled_arc():
    a = archetypes.get("villainess")
    c = Character(id="a", name="", role="", arc="생존 → 행복")
    assert "arc" in archetypes.fill(c, a, twist=a.twists[0])
    assert c.arc == f"생존 → 행복\n비틀기: {a.twists[0]}"
    archetypes.fill(c, a, twist=a.twists[1])
    assert c.arc == f"생존 → 행복\n비틀기: {a.twists[1]}"
    assert archetypes.fill(c, a, twist=a.twists[1]) == []


def test_apply_remembers_pick_and_prune():
    p = Project(characters=[Character(id="hero", name="가", role=""), Character(id="b", name="나", role="")])
    archetypes.apply(p, "hero", "regressor", twist="다른 인물도 회귀자다")
    archetypes.apply(p, "b", "rival")
    assert [(x.character_id, x.archetype, x.twist) for x in p.cast_archetypes] == [("hero", "regressor", "다른 인물도 회귀자다"), ("b", "rival", "")]
    archetypes.apply(p, "hero", "regressor")  # 비틀기를 새로 고르지 않으면 전 것을 둔다
    assert archetypes.pick_of(p, "hero").twist == "다른 인물도 회귀자다"
    archetypes.apply(p, "hero", "avenger")  # 원형을 바꾸면 전 비틀기는 지운다
    assert archetypes.pick_of(p, "hero").twist == ""
    p.characters.pop()
    archetypes.prune(p)
    assert [x.character_id for x in p.cast_archetypes] == ["hero"]
    with pytest.raises(KeyError):
        archetypes.apply(p, "hero", "nope")


def test_pick_stays_out_of_prompts():
    p = Project(meta=Meta(title="t", genres=["romance"]), characters=[Character(id="hero", name="가", role="")])
    before = prompts.static_context(p)
    archetypes.apply(p, "hero", "regret_male", twist="")
    p.characters[0] = Character(id="hero", name="가", role="")  # 채운 칸은 빼고 기록만 남긴 상태
    assert p.cast_archetypes and prompts.static_context(p) == before
    assert "archetype" not in typing.get_type_hints(Character)


def test_roll_is_seeded_and_genre_aware():
    p = Project(meta=Meta(title="t", genres=["martial_arts"], ))
    a = archetypes.roll(p.meta.genres, 3, random.Random(7), p=p)
    b = archetypes.roll(p.meta.genres, 3, random.Random(7), p=p)
    assert a == b and len(a) == 3 and len({r.archetype for r in a}) == 3
    assert all(archetypes.get(r.archetype).genres for r in a)  # 장르가 맞는 원형부터
    assert all(r.name for r in a) and len({r.name for r in a}) == 3
    assert all(r.twist in archetypes.get(r.archetype).twists for r in a)
    kits = {s.id for s in archetypes.speech_for(["martial_arts"])}
    assert all(r.speech in kits for r in a) and "gyeongsang" not in kits
    same = archetypes.roll([], 3, random.Random(1), archetype="rival")
    assert {r.archetype for r in same} == {"rival"}


def test_new_character_from_roll():
    p = Project(meta=Meta(title="t"), characters=[Character(id="hero", name="가", role="주인공")])
    r = archetypes.Roll(archetype="secret_mentor", wound="lost_family", speech="hageche", twist="제자에게 배운다", name="노인")
    c = archetypes.new_character(p, r)
    assert c.id == "char2" and c.tier == "support" and c.role == "스승" and c.name == "노인"
    assert c.speech_style.startswith("하게체") and c.arc.endswith("비틀기: 제자에게 배운다")
    assert archetypes.pick_of(p, "char2").archetype == "secret_mentor"


def test_old_project_loads_without_picks():
    p = Project.model_validate({"meta": {"title": "t"}})
    assert p.cast_archetypes == []


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store, web

    importlib.reload(store)
    importlib.reload(web)
    return TestClient(web.app)


def test_web_catalog_fill_roll_and_prune(client):
    cat = client.get("/api/archetypes").json()
    assert cat["groups"] == archetypes.GROUPS and len(cat["archetypes"]) == len(archetypes.CATALOG)
    assert cat["fill_labels"]["speech_style"] == "말투"

    c = {"id": "hero", "name": "가", "role": "주인공"}
    r = client.post("/api/archetypes/fill", json={"character": c, "archetype": "munchkin", "speech": "report", "twist": "힘에 시한이 있다"}).json()
    assert r["character"]["role"] == "주인공" and r["character"]["speech_style"].startswith("보고체")
    assert r["character"]["arc"].endswith("비틀기: 힘에 시한이 있다") and "speech_style" in r["filled"]
    assert client.post("/api/archetypes/fill", json={"character": c, "archetype": "nope"}).status_code == 404

    meta = {"title": "검", "genres": ["martial_arts"], "logline": "x", "target_episodes": 10}
    client.post("/api/projects", json={"name": "m", "meta": meta})
    rolls = client.post("/api/projects/m/archetypes/roll", json={"n": 2, "seed": 3}).json()
    assert len(rolls) == 2 and all(x["name"] for x in rolls)
    assert rolls == client.post("/api/projects/m/archetypes/roll", json={"n": 2, "seed": 3}).json()
    assert client.post("/api/projects/m/archetypes/roll", json={"archetype": "nope"}).status_code == 404

    p = client.get("/api/projects/m").json()
    p["characters"] = [dict(c, gender="", tier="main")]
    p["cast_archetypes"] = [{"character_id": "hero", "archetype": "munchkin"}, {"character_id": "gone", "archetype": "rival"}]
    p = client.put("/api/projects/m", json=p).json()
    assert p["cast_archetypes"] == [{"character_id": "hero", "archetype": "munchkin", "twist": ""}]
