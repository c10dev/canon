"""쓰기 프롬프트를 작게 · 부딪히지 않게 두는 규칙 (쇠맛 연구 2026-10-30). 실행: python -m pytest tests/test_write_budget.py"""
import re

from canon import context, dynamics, prompts, statwin
from canon.schema import Character, CharacterState, StatValue, Tie
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
    big = ["아는 정보 " + "가" * 60 for _ in range(30)]
    states = [CharacterState(character_id="hero", knows=list(big)), CharacterState(character_id="side", knows=list(big)),
              CharacterState(character_id="far", knows=list(big))]
    same, note = prompts.fit_states(states, {"hero"}, 100_000)
    assert same == states and note == ""
    out, note = prompts.fit_states(states, {"hero"}, len(prompts.dump(states[:1])) + 900)
    assert out[0].knows == big  # 플롯 인물은 그대로
    assert all(len(s.knows) <= prompts.STATES_KNOWS_SHORT for s in out[1:])
    assert "아는 정보를 최근" in note
    tiny, note = prompts.fit_states(states, {"hero"}, 10)
    assert [s.character_id for s in tiny] == ["hero"] and "2명 상태 생략" in note


def test_serial_relations_puts_plot_pairs_first_and_cuts_rest():
    p = _serial()
    p.characters += [Character(id=f"x{i}", name=f"조연{i}", role="조연", tier="support") for i in range(30)]
    ids = {c.id for c in p.characters}
    p.ties += [Tie(source=a, target=b) for a in ids for b in ids if a != b and (a.startswith("x") or b.startswith("x"))]
    plot = {c.id for c in p.characters if not c.id.startswith("x")}
    text = prompts.serial_relations(p, ids, plot, [])
    assert len(text) <= context.BUDGET["relations"] + 200 and "줄 생략" in text
    core = dynamics.describe_relations(p, plot, secrets=[]).splitlines()
    assert core and text.splitlines()[:len(core)] == core


def test_styled_profile_is_clipped_and_samples_come_first():
    p = _serial()
    p.style.sentence_rhythm = "짧은 문장. " * 100
    assert len(prompts.style_rules_view(p)["sentence_rhythm"]) == len("짧은 문장. " * 100)  # 예시 문단이 없으면 그대로
    p.style.sample_passages = ["예시 문단 하나."]
    assert len(prompts.style_rules_view(p)["sentence_rhythm"]) <= prompts.STYLE_FIELD_LIMIT
    ctx = prompts.static_context(p)
    assert ctx.index("# 문체 예시") < ctx.index("# 스타일 프로필")
    assert p.style.sentence_rhythm == "짧은 문장. " * 100  # 저장된 프로필은 그대로
    assert prompts.clip_sentences("가" * 500, 10) == "가" * 500  # 첫 문장은 길어도 남긴다


def test_stat_format_once_when_board_shows_windows():
    p = _serial()
    p.states = [CharacterState(character_id=p.characters[0].id, stats=[StatValue(name="HP", value="10")])]
    assert "아래 서식으로" in statwin.write_rule(p, 1)
    off = statwin.write_rule(p, 1, show_format=False)
    assert "아래 서식으로" not in off and "스토리보드의 창 글" in off
