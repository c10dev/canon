"""지금 차림(CharacterState.attire) 테스트 (mock LLM): 반영 · 덮어쓰기, 쓰기 · 검수 · 상태 변경안 규칙, 인물 화면 타임라인, 삽화 자료. 실행: python -m pytest tests"""
from canon import cast, pipeline, prompts
from canon.schema import CharacterState, StateDelta

from .test_storylines import _short
from .test_timeline import _play


def test_no_attire_keeps_write_and_check_prompt():
    p = _short(8)
    assert not prompts.has_attire(p)
    assert "차림:" not in prompts.episode_prompt(p, 1) and "- 차림:" not in prompts.check_prompt(p, 1)
    assert prompts.ATTIRE_STATE_RULE in prompts.state_prompt(p, 1)  # 상태 변경안은 처음부터 차림을 적게 한다


def test_apply_overwrites_only_when_given():
    p = _play(_short(8), 1, 3)  # mock: 1화 처음 적고, 2화에 찢어지고, 3화는 비움
    st = p.state_of("hero")
    assert st.attire == "젖은 회색 코트(오른쪽 소매 찢어짐), 손전등, 녹슨 열쇠"
    assert p.snapshot(1).states[0].attire == "젖은 회색 코트, 손전등"
    pipeline.apply_delta(p, StateDelta(episode=4, summary="4화",
                                       character_updates=[CharacterState(character_id="hero", attire="마른 셔츠, 오른손 붕대, 녹슨 열쇠")]))
    assert p.state_of("hero").attire == "마른 셔츠, 오른손 붕대, 녹슨 열쇠"


def test_rules_once_recorded():
    p = _play(_short(8), 1, 2)
    w = prompts.episode_prompt(p, 3)
    assert "\"attire\": \"젖은 회색 코트(오른쪽 소매 찢어짐)" in w and "차림: [인물 현재 상태]의 attire" in w
    assert "- 차림: [인물 현재 상태]의 attire" in prompts.check_prompt(p, 3)
    # 2화 삽화는 2화가 시작할 때(1화 반영 뒤) 차림을 쓴다. 3화 삽화는 마지막 반영(2화) 뒤 지금 상태
    assert '"attire_now": "젖은 회색 코트, 손전등"' in prompts.illust_prompt(p, 2, None)
    assert '"attire_now": "젖은 회색 코트(오른쪽 소매 찢어짐), 손전등, 녹슨 열쇠"' in prompts.illust_prompt(p, 3, None)


def test_illust_state_at_episode_start():
    from canon import illust
    p = _play(_short(8), 1, 3)
    attire = lambda n: next(s.attire for s in illust.states_at(p, n)[0] if s.character_id == "hero")  # noqa: E731
    assert attire(4) == p.state_of("hero").attire and illust.states_at(p, 4)[1] == ""
    assert attire(3) == p.snapshot(2).states[0].attire and attire(2) == "젖은 회색 코트, 손전등"
    p.snapshots = [s for s in p.snapshots if s.episode in (0, 1, 3)]  # 장편처럼 2화 스냅샷을 지움 → 2화 이하 가장 가까운 1화
    assert attire(3) == "젖은 회색 코트, 손전등" and illust.states_at(p, 3)[1] == ""
    p.snapshots = []  # 스냅샷이 없으면 지금 상태를 쓰고 알린다
    states, note = illust.states_at(p, 2)
    assert states is p.states and note == "2화보다 뒤 상태(3화 반영 뒤)의 차림 · 위치를 썼어요"


def test_illustrate_keeps_late_state_note_after_rebuild():
    from canon import illust
    from canon.mock import MockLLM
    p = _play(_short(8), 1, 3)
    p.snapshots = []
    ill = pipeline.illustrate(MockLLM(), p, 2)
    assert ill.notes[0] == "2화보다 뒤 상태(3화 반영 뒤)의 차림 · 위치를 썼어요"
    assert illust.assemble(p, ill).notes[0] == ill.notes[0]  # 다시 조립해도 남는다


def test_cast_timeline_shows_change():
    p = _play(_short(8), 1, 3)
    rows = {r["n"]: r["changes"] for r in cast.timeline(p, "hero")}
    assert rows[1]["attire"] == "젖은 회색 코트, 손전등"
    assert rows[2]["attire"].startswith("젖은 회색 코트(오른쪽 소매 찢어짐)")
    assert "attire" not in rows[3]  # 3화는 그대로
    assert "차림: 젖은 회색 코트(오른쪽 소매 찢어짐)" in cast.describe(p, "hero")


def test_cast_replays_attire_without_snapshot():
    p = _play(_short(8), 1, 3)
    p.snapshots = [s for s in p.snapshots if s.episode in (0, 3)]  # 장편처럼 지워진 화는 변경안으로 다시 계산한다
    rows = {r["n"]: r["changes"] for r in cast.timeline(p, "hero")}
    assert rows[1]["attire"] == "젖은 회색 코트, 손전등"


def test_rules_ask_for_kind_of_bag():
    p = _play(_short(8), 1, 2)
    assert "백팩 · 숄더백 · 핸드백" in prompts.ATTIRE_STATE_RULE and "메는 자리" in prompts.ATTIRE_STATE_RULE
    assert "백팩을 핸드백 · 숄더백으로" in prompts.episode_prompt(p, 3)
    assert "백팩이 핸드백 · 숄더백으로" in prompts.check_prompt(p, 3)


def test_vague_items():
    from canon import attire
    assert attire.vague("검은 가방(지퍼 고장), 젖은 옷 · 신발") == ["검은 가방(지퍼 고장)", "젖은 옷", "신발"]
    for ok in ("남색 백팩", "등에 멘 가방", "가방(등에 멤)", "서류 가방", "책가방", "잠옷", "젖은 회색 코트, 손전등"):
        assert attire.vague(ok) == [], ok


def test_clean_delta_warns_vague_bag():
    p = _play(_short(8), 1, 2)
    d = StateDelta(episode=3, summary="3화", character_updates=[CharacterState(character_id="hero", attire="젖은 코트, 검은 가방")])
    pipeline.clean_delta(p, d)
    name = next(c.name for c in p.characters if c.id == "hero")
    assert any(w.startswith(f"{name}의 차림 '검은 가방'") for w in d.warnings)
    d = StateDelta(episode=3, summary="3화", character_updates=[CharacterState(character_id="hero", attire="젖은 코트, 등에 멘 검은 백팩")])
    pipeline.clean_delta(p, d)
    assert not any("차림" in w for w in d.warnings)
