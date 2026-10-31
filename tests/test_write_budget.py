"""쓰기 프롬프트를 작게 · 부딪히지 않게 두는 규칙 (쇠맛 연구 2026-10-30). 실행: python -m pytest tests/test_write_budget.py"""
import re

from canon import context, dynamics, prompts, statwin
from canon.schema import Character, CharacterState, Secret, StatValue, Tie
from tests.test_char_context import _long
from tests.test_serial import _serial

# 쓰기 프롬프트에서 지시로 세는 문장 끝. 따옴표 · JSON 줄(데이터)은 세지 않는다.
_DIRECTIVE = re.compile(r"(합니다|습니다|않습니다|세요|말 것|할 것|따를 것|씁니다|둡니다|드러냅니다|끝납니다)[.)」\"]?$")
DIRECTIVE_CAP = 12  # mock 장편 쓰기 프롬프트(시스템 빼고)의 지시 문장 상한. 2026-10-30 에 8개
WRITE_CAP = 12_000  # mock 장편 쓰기 프롬프트 글자 상한. 2026-10-30 에 약 9,500자


def directives(text: str) -> int:
    n = 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in '{}[]"':
            continue
        n += sum(1 for sent in re.split(r"(?<=[.!?])\s+", s) if _DIRECTIVE.search(sent))
    return n


def test_mock_serial_write_prompt_stays_under_caps():
    p = _long()
    n = next(e.plot.number for e in p.episodes if not e.text)
    text = prompts.episode_prompt(p, n)
    assert len(text) <= WRITE_CAP, context.blocks(text)
    assert directives(text) <= DIRECTIVE_CAP


def test_priority_line_once_instead_of_headers():
    p = _long()
    n = next(e.plot.number for e in p.episodes if not e.text)
    p.episode(n).plot.pov = p.characters[0].id
    text = prompts.episode_prompt(p, n)
    assert "(스타일 프로필보다 우선)" not in text and "예시 문단보다 우선" not in text
    assert text.count("자료가 서로 부딪히면") == 1 and "이번 화 플롯, 서술 시점" in text
    p.episode(n).plot.pov = ""
    assert prompts.priority_line(p, n, False) == ""  # 차례를 정할 블록이 없으면 넣지 않는다


def test_fit_states_trims_off_plot_people_first():
    p = _serial()
    big = ["아는 정보 " + "가" * 60 for _ in range(30)]
    states = [CharacterState(character_id="hero", knows=list(big)), CharacterState(character_id="side", knows=list(big)),
              CharacterState(character_id="far", knows=list(big))]
    same, note = prompts.fit_states(p, states, {"hero"}, 100_000)
    assert same == states and note == ""
    out, note = prompts.fit_states(p, states, {"hero"}, len(prompts.dump(states[:1])) + 900)
    assert out[0].knows == big  # 플롯 인물은 그대로
    assert all(len(s.knows) <= prompts.STATES_KNOWS_SHORT for s in out[1:])
    assert "아는 정보를 최근" in note
    tiny, note = prompts.fit_states(p, states, {"hero"}, 10)
    assert [s.character_id for s in tiny] == ["hero"] and "2명 상태 · 관계 생략" in note


def test_fit_states_keeps_folded_lines():
    p = _serial()
    p.states = [CharacterState(character_id="side", knows_folded=["접은 줄 하나", "접은 줄 둘"])]
    view = CharacterState(character_id="side", knows=["(요약) 접은 줄 하나", "(요약) 접은 줄 둘"] + [f"새 정보 {i} " + "가" * 60 for i in range(20)])
    hero = CharacterState(character_id="hero", knows=["가" * 900])
    out, _ = prompts.fit_states(p, [hero, view], {"hero"}, len(prompts.dump([hero])) + 600)
    side = next(s for s in out if s.character_id == "side")
    assert side.knows[:2] == ["(요약) 접은 줄 하나", "(요약) 접은 줄 둘"]  # 접은 줄은 남긴다
    assert len(side.knows) == 2 + prompts.STATES_KNOWS_SHORT and side.knows[-1].startswith("새 정보 19")


def test_serial_relations_puts_plot_pairs_first_and_cuts_rest():
    p = _serial()
    p.characters += [Character(id=f"x{i}", name=f"조연{i}", role="조연", tier="support") for i in range(30)]
    ids = {c.id for c in p.characters}
    p.ties += [Tie(source=a, target=b) for a in ids for b in ids if a != b and (a.startswith("x") or b.startswith("x"))]
    plot = {c.id for c in p.characters if not c.id.startswith("x")}
    hero = sorted(plot)[0]
    secret = Secret(id="s1", owner=hero, content="정체를 숨긴다", hidden_from=[x for x in sorted(plot) if x != hero] + ["x0"])
    text = prompts.serial_relations(p, ids, plot, [secret])
    assert len(text) <= context.BUDGET["relations"] + 400 and "줄 생략" in text
    core = dynamics.describe_relations(p, plot, secrets=[]).splitlines()
    assert core and all(x in text.splitlines() for x in core)  # 플롯 인물끼리 줄은 늘 넣는다
    assert text.count("숨긴 비밀") == 1 and "정체를 숨긴다" in text  # 고른 비밀은 한 번만, 자르지 않는다


def test_styled_profile_is_clipped_and_samples_come_first():
    p = _serial()
    p.style.sentence_rhythm = "짧은 문장. " * 100
    assert len(prompts.style_rules_view(p)["sentence_rhythm"]) == len("짧은 문장. " * 100)  # 예시 문단이 없으면 그대로
    p.style.sample_passages = ["예시 문단 하나."]
    assert len(prompts.style_rules_view(p)["sentence_rhythm"]) <= prompts.STYLE_FIELD_LIMIT
    ctx = prompts.static_context(p)
    assert ctx.index("# 문체 예시") < ctx.index("# 스타일 프로필")
    assert p.style.sentence_rhythm == "짧은 문장. " * 100  # 저장된 프로필은 그대로
    assert prompts.clip_sentences("가" * 500, 10) == "가" * 10 + "…"  # 문장 끝이 없으면 자르고 표시
    assert prompts.clip_sentences("첫 줄\n" + "둘째 줄 " * 50, 10) == "첫 줄"  # 줄바꿈도 문장 경계


def test_stat_format_once_when_board_shows_windows():
    p = _serial()
    p.states = [CharacterState(character_id=p.characters[0].id, stats=[StatValue(name="HP", value="10")])]
    assert "아래 서식으로" in statwin.write_rule(p, 1)
    off = statwin.write_rule(p, 1, show_format=False)
    assert "아래 서식으로" not in off and "스토리보드의 창 글" in off


def test_old_prose_emotional_shift_stays_out_of_the_write_prompt():
    p = _long()
    n = next(e.plot.number for e in p.episodes if not e.text)
    p.episode(n).plot.emotional_shift = "서윤이 문을 걸어 잠그고 등을 돌린 채 한참을 서 있다"
    text = prompts.episode_prompt(p, n)
    assert "등을 돌린 채" not in text and "emotional_shift 는 감정 이름으로" not in text
    assert "등을 돌린 채" in prompts.check_prompt(p, n)  # 검수는 그대로 본다
    p.episode(n).plot.emotional_shift = "서윤: 문을 잠금 → 문을 엶 (도현의 사과)"
    text = prompts.episode_prompt(p, n)
    assert "문을 잠금 → 문을 엶" in text and "emotional_shift 는 감정 이름으로" in text
    arrow = p.episode(n).plot.model_copy(update={"emotional_shift": "a -> b"})
    assert prompts.write_plot(arrow).emotional_shift == "a -> b"


def test_dropped_states_leave_relations_and_returns_too(monkeypatch):
    p = _long()
    n = next(e.plot.number for e in p.episodes if not e.text)
    side = Character(id="side", name="옆사람", role="조연", tier="support")
    p.characters.append(side)
    p.states.append(CharacterState(character_id="side", knows=["가" * 80 for _ in range(10)]))
    p.ties.append(Tie(source="side", target=p.episode(n).plot.characters[0]))
    monkeypatch.setitem(context.BUDGET, "states", 1)
    monkeypatch.setattr(context, "named_ids", lambda *a, **k: {"side"})
    text = prompts.episode_prompt(p, n)
    assert "옆사람 →" not in text and "상태 · 관계 생략" in text
