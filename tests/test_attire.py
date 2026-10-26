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
    assert '"attire_now": "젖은 회색 코트(오른쪽 소매 찢어짐), 손전등, 녹슨 열쇠"' in prompts.illust_prompt(p, 2, None)


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
