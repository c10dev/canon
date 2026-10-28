"""플레이 턴 프롬프트(prompts.play_scene_prompt · play_state_prompt)의 크기와 고르기 시험 (mock LLM). 실행: python -m pytest tests"""
import functools

from canon import context, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Character, CharacterState, Foreshadow, PlayChoice, PlayInfo, PlayTurn, Secret, StoryElement

from .test_serial import _plan_arc, _serial

LLM = MockLLM()
SCENE = "당신은 등대 계단을 올랐다. 서윤이 난간에 기대어 바다를 보고 있었다. " * 25  # 턴 장면 하나 (약 1,000자)


def _finish_turns(p, a):
    """아크(플레이의 장)의 턴을 모두 쓴 것으로 하고 상태를 반영한다. 턴 요약은 두세 문장 길이."""
    for n in range(a.start_ep, a.end_ep + 1):
        e = p.episode(n)
        e.text, e.status = SCENE, "written"
        d = pipeline.extract_state(LLM, p, n)
        d.summary = f"{n}턴: 당신은 등대에 올라 서윤과 이야기했다. " + "가" * 120
        pipeline.apply_delta(p, d)


@functools.lru_cache(maxsize=None)
def _built(turns: int):
    p = _serial(300)
    while p.planned_until() < turns:
        _finish_turns(p, _plan_arc(p, length=20))
        for kind, num in pipeline.pending_recaps(p):
            pipeline.apply_recap(p, kind, num, pipeline.recap(LLM, p, kind, num).summary)
    nxt = _plan_arc(p, length=20)  # 지금 턴을 덮는 장 (DESIGN 10.1)
    _bulk(p)
    return p, nxt.start_ep


def _big(turns: int):
    """turns 턴까지 반영한 큰 플레이 사본과 다음 턴 번호. 인물 14명, 사실 200개, 비밀 · 복선 다수, 아는 정보 수백 개."""
    p, n = _built(turns)
    return p.model_copy(deep=True), n


def _bulk(p):
    for i in range(10):
        p.characters.append(Character(id=f"npc{i}", name=f"주민{i}호", role="마을 주민", tier="support" if i < 5 else "minor",
                                      personality="말이 많다 " * 20, background="등대 마을에서 자랐다 " * 20, speech_style="반말 " * 10))
        p.states.append(CharacterState(character_id=f"npc{i}", location="시장 골목" if i % 2 else "등대",
                                       knows=[f"주민{i}호가 들은 소문 {k}" for k in range(60)]))
    p.facts = [f"사실 {i}: 주민{i % 10}호는 등대 열쇠를 {i}번 보았다 " + "나" * 40 for i in range(200)]
    p.secrets += [Secret(id=f"sec{i}", owner=f"npc{i % 10}", content=f"주민{i % 10}호의 비밀 {i} " + "다" * 120,
                         hidden_from=["hero", "ally"]) for i in range(60)]
    p.foreshadows += [Foreshadow(id=f"fs-x{i}", description=f"떡밥 {i} " + "라" * 80, planted_ep=1 + i) for i in range(50)]
    p.world.rules = [f"세계 규칙 {i}: 등대의 불은 밤마다 꺼지지 않는다 " + "마" * 60 for i in range(10)]
    p.style.donts = [f"하지 말 것 {i} " + "바" * 60 for i in range(15)]
    p.style.dos = [f"할 것 {i} " + "사" * 60 for i in range(10)]
    p.style.sample_passages = ["예시 문단 " + "아" * 1500]
    p.elements += [StoryElement(id=f"el{i}", kind="물건", name=f"유물{i}", description="오래된 유물 " * 15) for i in range(20)]


def _info(p, n, **kw):
    return PlayInfo(world="w", world_ep=n - 1, player="hero", **kw)


def test_scene_prompt_size_is_bounded_and_flat():
    sizes = {}
    for turns in (80, 200):
        p, n = _big(turns)
        text = prompts.play_scene_prompt(p, _info(p, n), n, "주민0호에게 등대 열쇠를 묻는다", 1)
        sizes[turns] = len(text)
        assert len(text) < 22_000, (turns, len(text), context.blocks(text, 20))
        story = text[text.index("[지금까지의 줄거리]"):text.index("[이야기 요소]")]
        assert len(story) < context.BUDGET["play_story_past"] + context.BUDGET["play_story_arc"] + 300
    assert abs(sizes[200] - sizes[80]) < sizes[80] * 0.1, sizes  # 턴이 쌓여도 거의 그대로


def test_scene_prompt_order_and_stable_front():
    p, n = _big(80)
    a = prompts.play_scene_prompt(p, _info(p, n), n, "등대로 간다", 0)
    heads = ["[진행 규칙]", "[서술 시점]", "[작품 정보]", "[세계관", "[스타일 프로필", "[플레이어 인물]", "[지금까지의 줄거리]",
             "[확정된 사실]", "[장면 인물 설정]", "[인물 현재 상태]", "[관계]", "[숨긴 비밀]", "[열린 복선]",
             "[직전 장면 마지막 부분]", "[이번 턴]", "[이번 행동]", "[이번 턴의 운]"]
    pos = [a.index("\n" + h) if i else a.index(h) for i, h in enumerate(heads)]
    assert pos == sorted(pos)
    b = prompts.play_scene_prompt(p, _info(p, n), n, "시장으로 간다", -2)  # 행동과 운만 다른 같은 턴
    front = a[:a.index("[지금까지의 줄거리]")]
    assert b.startswith(front)  # 턴 사이에 덜 바뀌는 블록이 앞
    assert "운이" not in a and "아주 나쁨" in b


def test_scene_cast_follows_text_place_and_context():
    p, n = _big(80)
    me = p.state_of("hero")
    me.location = "등대 꼭대기"
    p.characters.append(Character(id="far", name="먼곳사람", role="상인", tier="support"))
    p.characters.append(Character(id="hide", name="숨은이", role="첩자", tier="support", context="off"))
    p.states += [CharacterState(character_id="far", location="왕도"), CharacterState(character_id="hide", location="등대 꼭대기")]
    order = prompts.play_cast(p, "hero", "", "주민7호에게 말을 건다")
    assert order[0] == "hero" and order[1] == "npc7"  # 행동에 이름이 나온 인물이 먼저
    assert {"npc0", "npc2"} <= set(order) and "npc1" not in order  # 같은 곳(등대)에 있는 인물
    assert "far" not in order and "hide" not in order  # 멀리 있는 인물, '넣지 않음' 인물은 빠진다
    text = prompts.play_scene_prompt(p, _info(p, n), n, "주민7호에게 말을 건다", 0)
    cast = text[text.index("[장면 인물 설정]"):text.index("[인물 현재 상태]")]
    assert '"name": "주민7호"' in cast and '"id": "far"' not in cast and "far: 먼곳사람" in cast
    assert "hide: 숨은이" in cast and '"character_id": "hide"' not in text
    p.characters[-1].context = "always"
    assert "hide" in prompts.play_cast(p, "hero", "", "")


def test_scene_notes_cuts():
    p, n = _big(80)
    text = prompts.play_scene_prompt(p, _info(p, n), n, "주민3호에게 등대 열쇠를 묻는다", 0)
    for head in ("[확정된 사실]", "[숨긴 비밀]", "[열린 복선]", "[인물 현재 상태]"):
        block = text[text.index(head):text.index(head) + 200]
        assert "개 생략" in block, head
    facts = text[text.index("[확정된 사실]"):text.index("[장면 인물 설정]")]
    assert len(facts) < context.BUDGET["play_facts"] + 200 and "주민3호" in facts


def test_scene_without_turn_episode_and_turn_kinds():
    p, n = _big(80)
    p.episodes = [e for e in p.episodes if e.plot.number < n]  # 턴 Episode 를 아직 만들지 않았어도 된다
    prev = PlayTurn(number=n - 1, choices=[PlayChoice(text="등대로 간다"), PlayChoice(text="사흘 뒤로", skip="사흘")])
    info = _info(p, n - 5, turns=[prev], max_turns=5)
    info.world_ep = n - 5
    skip = prompts.play_scene_prompt(p, info, n, "사흘 뒤로", 0)
    assert "시간 건너뛰기 (사흘)" in skip and "5번째 턴 (턴 한도 5)" in skip and "마지막 턴" in skip
    assert "고른 선택지" in prompts.play_scene_prompt(p, info, n, "등대로 간다", 0)
    assert "(시도)" in prompts.play_scene_prompt(p, info, n, "하늘을 난다", 0)
    first = prompts.play_scene_prompt(p, _info(p, n), n, "", 0)
    assert "첫 장면입니다" in first and "플레이를 시작하기 전" in first


def test_person_rules():
    p, n = _big(80)
    hero = next(c for c in p.characters if c.id == "hero")
    hero.narration_voice = "짧게 끊는다"
    first = prompts.play_scene_prompt(p, _info(p, n, person="first"), n, "", 0)
    assert "1인칭" in first and f"'나'는 {hero.name}입니다" in first and '"narration_voice": "짧게 끊는다"' in first
    third = prompts.play_scene_prompt(p, _info(p, n, person="third"), n, "", 0)
    assert f"이름({hero.name})으로" in third and "narration_voice" not in third
    assert "'당신'" in prompts.play_scene_prompt(p, _info(p, n), n, "", 0)


def test_state_prompt_keeps_scene_cast_and_novel_path():
    p, n = _big(80)
    e = p.episode(n)
    e.text, e.status = "당신은 주민4호에게 열쇠를 건넸다. " * 30, "written"  # 2인칭이라 플레이어 이름이 없다
    e.plot.pov, e.plot.characters = "hero", []
    novel = prompts.state_prompt(p, n)
    before = [c.context for c in p.characters]
    text = prompts.play_state_prompt(p, n)
    assert prompts.state_prompt(p, n) == novel and [c.context for c in p.characters] == before  # 작품은 그대로
    chars = text[text.index("[인물 설정]"):text.index("[다른 인물")]
    assert '"id": "hero"' in chars and '"id": "npc4"' in chars and '"id": "npc5"' not in chars
    assert "npc5: 주민5호" in text[text.index("[다른 인물"):]  # 다시 만들지 않게 이름은 남는다
    assert len(text) < len(novel) * 0.75 and len(text) < 20_000, (len(text), len(novel), context.blocks(text, 20))
    assert "개 생략" in text and "플레이의 한 턴" in text


def test_short_project_state_prompt_is_novel_prompt():
    p, n = _big(80)
    p.meta.form = "short"
    assert not p.serial
    assert prompts.play_state_prompt(p, n - 1) == prompts.state_prompt(p, n - 1)
