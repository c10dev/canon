"""무작위 출생과 새 세계: 플레이 모드에서 세계의 무작위 인물로 태어나거나, 장르 · 한 줄로 새 세계를 만든다.

굴리는 값(원형 · 상처 · 말투 · 비틀기 · 성별 · 나이 · 이름 · 태어난 곳)은 코드가 시드로 정하고(roll, archetypes.roll · naming 재사용),
AI 는 그 값에 맞춰 배경만 채운다(sketch). 같은 시드 · 같은 세계면 같은 출생이다.
갈래마다 시드에서 난수원을 따로 만들어, 성별이나 나이를 정해 줘도 태어난 곳은 그대로다.
새 세계는 설정 제안(pipeline.suggest_setup)으로 만든 일반 작품이다(new_world).
"""
from __future__ import annotations

import random
import re

from . import archetypes, atlas, cast, genres, naming, pipeline, prompts, store
from .llm import LLM
from .schema import Birth, BirthSketch, Character, Meta, Project

# 장르별로 굴리는 나이 (세). 앞에 있는 장르가 먼저다. 성인 작품은 19세부터
AGE_RANGES: dict[str, tuple[int, int]] = {"academy": (16, 19), "sports": (17, 30), "light_novel": (16, 25)}
AGE_DEFAULT = (17, 40)
ADULT_AGE = 19

PLAYER_ID = "player"
WORLD_PLACES = 3  # 설정 제안에 장소가 없을 때 코드로 지어 넣는 장소 수

# web.NAME_RE · NAME_ERR 와 같은 규칙 (web 을 부르지 않으려고 따로 둔다)
NAME_RE = re.compile(r'^[^/\\.:*?"<>|][^/\\:*?"<>|]{0,63}$')
NAME_ERR = '폴더 이름에 / \\ : * ? " < > | 는 쓸 수 없고, . 으로 시작할 수 없어요 (64자까지)'


def _rng(seed: int, part: str) -> random.Random:
    """갈래마다 따로 둔 난수원. 문자열 시드는 실행마다 같은 값이다."""
    return random.Random(f"birth:{seed}:{part}")


def last_finalized(p: Project) -> int:
    """세계에서 반영이 끝난 마지막 화. 플레이는 그 직후에서 시작한다."""
    return max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)


def birth_places(p: Project) -> list[dict]:
    """태어날 수 있는 장소 (atlas.places 와 같은 모양). 아직 생기지 않았거나 독자에게 드러나지 않은 장소 요소는 뺀다."""
    n = last_finalized(p)
    return [x for x in atlas.places(p) if x["since_ep"] <= n and x["reveal_ep"] <= n]


def _archetype(p: Project, gender: str, rng: random.Random) -> archetypes.Archetype:
    """작품 장르에 맞는 원형과 공통 원형(archetypes.match) 중 주역에서 고른다. 적대자 원형은 플레이어로 태어나지 않는다.
    성별을 정했으면 다른 성별의 원형은 뺀다. 장르 원형만 고르면 장르마다 두세 개뿐이라 공통 원형도 함께 굴린다."""
    pool = archetypes.match(p.meta.genres)
    ok = [a for a in pool if not (gender and a.gender and a.gender != gender)] or pool
    lead = [a for a in ok if a.tier == "main" and a.role != "적대자"] or ok
    return rng.choice(lead)


def _age(p: Project, rng: random.Random) -> str:
    lo, hi = next((AGE_RANGES[g] for g in p.meta.genres if g in AGE_RANGES), AGE_DEFAULT)
    if p.meta.adult:
        lo, hi = max(lo, ADULT_AGE), max(hi, ADULT_AGE + 4)
    return f"{rng.randint(lo, hi)}세"


def _name(p: Project, gender: str, age: str, rng: random.Random) -> str:
    """세계 인물 · 인물 후보와 겹치거나 헷갈리지 않는 이름. 헷갈리는 이름만 남으면 겹치지 않는 것 중 첫 번째."""
    world = p.model_copy(update={"characters": [*p.characters, *p.cast_candidates]})
    taken = {c.name.strip() for c in world.characters if c.name.strip()}
    probe = Character(id="_birth", name="", role="주인공", gender=gender, age=age)
    names = [x.name for x in naming.character_candidates(world, probe, n=8, rng=rng) if x.name not in taken]
    return names[0] if names else ""


def roll(p: Project, seed: int, gender: str = "", age: str = "") -> Birth:
    """p 세계에서 시드로 출생을 굴린다. LLM 호출 없음. gender · age 를 주면 그 값을 쓴다.
    성인 작품은 19세 이상으로만 굴리고, 미성년 나이를 주면 막는다."""
    gender, age = gender.strip(), age.strip()
    if gender and gender not in ("남", "여"):
        raise ValueError("성별은 '남'이나 '여'로 적어 주세요")
    if age and p.meta.adult and cast.is_minor_age(age):
        raise ValueError("성인 작품에서는 미성년으로 태어날 수 없어요")
    a = _archetype(p, gender, _rng(seed, "archetype"))
    parts = archetypes.roll(p.meta.genres, n=1, rng=_rng(seed, "parts"), archetype=a.id)[0]
    gender = gender or a.gender or _rng(seed, "gender").choice(["남", "여"])
    age = age or _age(p, _rng(seed, "age"))
    places = birth_places(p)
    return Birth(
        seed=seed, gender=gender, age=age, archetype=a.id, wound=parts.wound, speech=parts.speech, twist=parts.twist,
        name=_name(p, gender, age, _rng(seed, "name")),
        place=_rng(seed, "place").choice(places)["name"] if places else "",
    )


def sketch(llm: LLM, p: Project, b: Birth) -> BirthSketch:
    """굴린 값에 맞춰 AI 가 배경을 채운다 (prompts.birth_prompt). 저장하지 않는다."""
    s = llm.json(prompts.SYSTEM_PLANNER, prompts.birth_prompt(p, b), BirthSketch, hint={"name": b.name, "place": b.place})
    for field in BirthSketch.model_fields:
        setattr(s, field, getattr(s, field).strip())
    return s


def player_id(p: Project) -> str:
    """세계 인물 · 인물 후보와 겹치지 않는 영문 소문자 id: player, player2, ..."""
    ids = {c.id for c in [*p.characters, *p.cast_candidates]}
    cid, k = PLAYER_ID, 2
    while cid in ids:
        cid, k = f"{PLAYER_ID}{k}", k + 1
    return cid


def to_character(p: Project, b: Birth, s: BirthSketch) -> Character:
    """플레이어 인물로 쓸 Character. p 는 바꾸지 않는다. 처음 나온 화(first_ep)는 엔진이 정한다.
    AI 배경이 비운 칸은 원형 · 상처 · 말투 틀 · 비틀기로 채운다 (archetypes.fill, 빈 칸만)."""
    c = Character(id=player_id(p), name=b.name, role="주인공", age=b.age, gender=b.gender, tier="main", first_ep=0,
                  appearance=s.appearance, personality=s.personality, background=s.background, goal=s.goal,
                  speech_style=s.speech_style)
    archetypes.fill(c, archetypes.BY_ID.get(b.archetype), archetypes.WOUND_BY_ID.get(b.wound),
                    archetypes.SPEECH_BY_ID.get(b.speech), b.twist)
    c.role = "주인공"  # 원형의 역할(남주 · 적대자 등)이 아니라 플레이의 주인공
    return c


def new_world(llm: LLM, name: str, genre_ids: list[str], logline: str, adult: bool = False) -> Project:
    """장르와 한 줄로 새 세계 작품을 만들어 name 폴더에 저장한다 (웹 새 작품 만들기 + 설정 제안 적용과 같은 규칙).
    AI 제안이 끝난 뒤에만 저장한다. 제안에 장소가 없으면 이름 · 지명 생성기로 장소 이름을 지어 넣는다."""
    name, logline = name.strip(), logline.strip()
    if not NAME_RE.match(name):
        raise ValueError(NAME_ERR)
    if store.exists(name):
        raise ValueError(f"이미 있는 작품이에요: {name}")
    if not logline:
        raise ValueError("어떤 세계인지 한 줄로 적어 주세요")
    meta = Meta(title=name, genres=list(dict.fromkeys(g.strip() for g in genre_ids if g.strip())), adult=adult, logline=logline)
    meta.genre = genres.label(meta)
    p = Project(meta=meta)
    pipeline.apply_setup(p, pipeline.suggest_setup(llm, p))
    if not p.world.locations:
        p.world.locations = [x.name for x in naming.location_candidates(p, WORLD_PLACES)]
    store.save(name, p)
    return p
