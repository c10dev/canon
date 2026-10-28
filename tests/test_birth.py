"""무작위 출생과 새 세계 시험 (mock LLM): 시드로 굴리기, 이름 · 장소, 성인 작품 나이, 배경 채우기, 인물 만들기, 새 세계 저장.
실행: python -m pytest tests"""
import pytest

from canon import archetypes, birth, cast, mock, naming, prompts, store
from canon.schema import Birth, Character, Meta, Project, StoryElement, WorldSetting

from .test_restate import _two_done
from .test_web import client  # noqa: F401  (pytest fixture)


def _world() -> Project:
    return Project(
        meta=Meta(title="항구", genres=["fantasy"]),
        world=WorldSetting(setting="안개 낀 항구 도시", era="중세풍", locations=["등대: 바다 끝의 흰 탑", "수산시장"]),
        characters=[Character(id="hero", name="서윤", role="주인공", gender="여", age="24세"),
                    Character(id="ally", name="도현", role="조연", gender="남", age="30세")],
        cast_candidates=[Character(id="cand", name="하람", role="상인")],
    )


def test_same_seed_same_birth():
    p = _world()
    assert birth.roll(p, 7) == birth.roll(p, 7)
    assert len({birth.roll(p, s).model_dump_json() for s in range(20)}) > 10
    b = birth.roll(p, 7)
    assert b.seed == 7 and b.archetype in archetypes.BY_ID and b.wound in archetypes.WOUND_BY_ID
    assert b.speech in archetypes.SPEECH_BY_ID and b.gender in ("남", "여") and naming.age_years(b.age)


def test_fixed_gender_and_age():
    p = _world()
    for s in range(30):
        b = birth.roll(p, s, gender="여", age="33세")
        assert b.gender == "여" and b.age == "33세"
        assert archetypes.get(b.archetype).gender in ("", "여")
    # 성별을 정해도 태어난 곳은 그대로 (갈래마다 따로 둔 난수원)
    assert {birth.roll(p, s).place for s in range(5)} and all(
        birth.roll(p, s).place == birth.roll(p, s, gender="남").place for s in range(10))
    with pytest.raises(ValueError):
        birth.roll(p, 1, gender="모름")


def test_name_avoids_world_people():
    p = _world()
    taken = {c.name for c in [*p.characters, *p.cast_candidates]}
    for s in range(30):
        b = birth.roll(p, s)
        assert b.name and b.name not in taken


def test_place_from_world():
    p = _world()
    p.elements = [StoryElement(id="e1", kind="장소", name="검은 숲", description="늑대가 사는 숲"),
                  StoryElement(id="e2", kind="장소", name="잠긴 지하실", reveal_ep=5),  # 아직 드러나지 않은 곳
                  StoryElement(id="e3", kind="장소", name="새 성채", since_ep=3)]  # 아직 생기지 않은 곳
    places = {birth.roll(p, s).place for s in range(60)}
    assert places <= {"등대", "수산시장", "검은 숲"} and len(places) == 3


def test_world_without_places():
    p = Project(meta=Meta(title="빈 세계"))
    b = birth.roll(p, 3)
    assert b.place == "" and b.name and b.archetype
    assert "정하지 않음" in prompts.birth_prompt(p, b)


def test_adult_world_has_no_minors():
    p = _world()
    p.meta.genres = ["academy"]
    assert any(cast.is_minor_age(birth.roll(p, s).age) for s in range(30))  # 전연령 학원물은 미성년이 나온다
    p.meta.adult = True
    assert not any(cast.is_minor_age(birth.roll(p, s).age) for s in range(60))
    with pytest.raises(ValueError):
        birth.roll(p, 1, age="17세")


def test_prompt_has_world_and_rolled_values():
    p = _world()
    p.elements = [StoryElement(id="f1", kind="세력", name="항만 길드", description="부두를 쥔 상인 조합")]
    b = birth.roll(p, 5)
    text = prompts.birth_prompt(p, b)
    a = archetypes.get(b.archetype)
    for part in (b.name, b.place, b.age, a.name, archetypes.WOUND_BY_ID[b.wound].name, archetypes.SPEECH_BY_ID[b.speech].name,
                 "바다 끝의 흰 탑", "항만 길드", "서윤", "바꾸지 않습니다"):
        assert part in text, part
    assert text.index("[굴린 값]") > text.index("[세계관]")  # 바뀌지 않는 세계 블록이 앞


def test_sketch_and_character():
    p = _world()
    p.characters.append(Character(id="player", name="여울", role="조연"))
    b = birth.roll(p, 11)
    s = birth.sketch(mock.MockLLM(), p, b)
    assert b.name in s.background and b.place in s.opening
    c = birth.to_character(p, b, s)
    assert c.id == "player2" and c.id not in {x.id for x in [*p.characters, *p.cast_candidates]}
    assert c.name == b.name and c.age == b.age and c.gender == b.gender and c.role == "주인공" and c.tier == "main"
    assert c.first_ep == 0 and c.background == s.background
    assert c.speech_style == archetypes.speech_text(archetypes.SPEECH_BY_ID[b.speech])  # mock 이 비운 말투는 말투 틀로
    assert c.wound == archetypes.wound_text(archetypes.WOUND_BY_ID[b.wound])
    if b.twist:
        assert archetypes.twist_line(b.twist) in c.arc
    assert len(p.characters) == 3 and p.cast_archetypes == []  # 세계는 바꾸지 않는다


def test_birth_in_written_world(client):
    _two_done(client)
    p = store.load("lh")
    b = birth.roll(p, 2)
    assert b.place in {x["name"] for x in birth.birth_places(p)} and birth.last_finalized(p) == 2
    assert b.name not in {c.name for c in p.characters}
    assert "도윤" in prompts.birth_prompt(p, Birth(seed=1, name="도윤", place="등대"))  # 굴리지 않은 칸이 비어도 된다


def test_new_world(client):
    p = birth.new_world(mock.MockLLM(), "안개항", ["fantasy"], "안개 속 항구 도시에서 사라진 배를 찾는다")
    q = store.load("안개항")
    assert q == p and q.meta.title == "안개항" and q.meta.genres == ["fantasy"] and q.meta.genre == "판타지"
    assert q.meta.logline.startswith("안개 속") and not q.meta.adult and q.meta.form == "short"
    assert q.world.locations and q.characters and len(q.states) == len(q.characters) and q.ties
    assert client.get("/api/projects/안개항").status_code == 200  # 일반 작품으로 읽힌다
    assert birth.roll(q, 1).place in naming.known_places(q)
    with pytest.raises(ValueError, match="이미 있는 작품"):
        birth.new_world(mock.MockLLM(), "안개항", [], "다른 한 줄")
    with pytest.raises(ValueError):
        birth.new_world(mock.MockLLM(), ".숨김", [], "한 줄")
    with pytest.raises(ValueError):
        birth.new_world(mock.MockLLM(), "빈줄", [], " ")
    assert not store.exists("빈줄")


def test_new_world_fills_missing_places(client, monkeypatch):
    from canon import pipeline

    real = pipeline.suggest_setup

    def no_places(llm, p):
        s = real(llm, p)
        s.world.locations = []
        return s

    monkeypatch.setattr(pipeline, "suggest_setup", no_places)
    p = birth.new_world(mock.MockLLM(), "빈 땅", ["fantasy"], "지도에 없는 땅", adult=True)
    assert len(p.world.locations) == birth.WORLD_PLACES and store.load("빈 땅").meta.adult
    assert birth.roll(p, 4).place in p.world.locations
