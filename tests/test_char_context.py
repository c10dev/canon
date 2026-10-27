"""인물 프롬프트 넣기 방식(Character.context: auto | always | off) 테스트 (mock LLM). 실행: python -m pytest tests

auto 스냅샷: 모든 인물이 auto 인 단편 · 장편 작품에서 프롬프트마다 sha256 앞 16자를 tests/snapshots/char_context_auto.json 과 견준다.
이 값은 넣기 방식을 더하기 전 코드로 만든 프롬프트에서 뽑았다. 프롬프트 문구를 일부러 바꾸면
CANON_UPDATE_SNAPSHOT=1 python -m pytest tests/test_char_context.py 로 다시 만든다.
"""
import hashlib
import json
import os
import random
from pathlib import Path

import pytest

from canon import context, llm, naming, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Character, CharacterState, Project, Relationship, SetupSuggestion, Selection, StateDelta
from tests.test_serial import _finish, _plan_arc, _serial

SNAPSHOT = Path(__file__).parent / "snapshots" / "char_context_auto.json"
L = MockLLM()


def _short() -> Project:
    p = Project()
    p.meta.title, p.meta.target_episodes = "단편", 6
    pipeline.apply_setup(p, pipeline.suggest_setup(L, p))
    p.arc = pipeline.plan_arc(L, p).acts
    pipeline.apply_plots(p, pipeline.draft_plots(L, p, 1, 6))
    for n in (1, 2, 3):
        pipeline.confirm_plot(p, n)
        p.episode(n).text = pipeline.write_episode(L, p, n)
        p.episode(n).status = "written"
        pipeline.apply_delta(p, pipeline.extract_state(L, p, n))
    return p


def _long() -> Project:
    p = _serial()
    _finish(p, _plan_arc(p))
    _plan_arc(p)
    return p


def _prompts(p: Project) -> dict[str, str]:
    """작품 하나의 프롬프트 모음. 이름 후보는 무작위라 씨앗을 고정한다."""
    out: dict[str, str] = {}
    nums = sorted(e.plot.number for e in p.episodes)
    written = [e.plot.number for e in p.episodes if e.text]
    picks = sorted({nums[0]} | set(written[:1] + written[-1:]) | ({max(written) + 1} & set(nums))
                   | {written[len(written) // 2]})

    def run(key, f):
        random.seed(0)
        naming._rng = lambda rng: rng or random.Random(0)
        out[key] = f()

    run("dump_characters", lambda: llm.dump(p.characters))
    run("static_context", lambda: prompts.static_context(p))
    run("setup_prompt", lambda: prompts.setup_prompt(p))
    run("setup_chat_prompt", lambda: prompts.setup_chat_prompt(p, "더 다듬어 줘"))
    run("arc_prompt", lambda: prompts.arc_prompt(p))
    if p.serial:
        run("series_prompt", lambda: prompts.series_prompt(p))
        run("next_arc_prompt", lambda: prompts.next_arc_prompt(p, (p.planned_until() or 0) + 1, 0, "메모"))
    run("storyline_prompt", lambda: prompts.storyline_prompt(p, "메모", "subplot"))
    run("plot_chat_prompt", lambda: prompts.plot_chat_prompt(p, "고쳐 줘"))
    for n in picks:
        e = p.episode(n)
        run(f"plot_prompt:{n}", lambda: prompts.plot_prompt(p, n, min(n + 2, max(nums))))
        run(f"episode_prompt:{n}", lambda: prompts.episode_prompt(p, n))
        run(f"episode_brief:{n}", lambda: prompts.episode_brief(p, n))
        if e.text:
            run(f"state_prompt:{n}", lambda: prompts.state_prompt(p, n))
            run(f"state_brief:{n}", lambda: prompts.state_brief(p, n))
            run(f"check_full:{n}", lambda: prompts.check_prompt(p, n, "full"))
            run(f"check_budget:{n}", lambda: prompts.check_prompt(p, n, "budget"))
            run(f"check_brief:{n}", lambda: prompts.check_brief(p, n))
            run(f"plant_prompt:{n}", lambda: prompts.plant_prompt(p, n, 3, 1))
            run(f"claims_prompt:{n}", lambda: prompts.claims_prompt(p, n))
            run(f"hook_prompt:{n}", lambda: prompts.hook_prompt(p, n, e.text[:2000]))
            run(f"passage_prompt:{n}", lambda: prompts.passage_prompt(p, n, Selection(start=0, text=e.text[:40]), "다듬어 줘"))
    return out


def _digest(texts: dict[str, str]) -> dict[str, str]:
    return {k: hashlib.sha256(v.encode()).hexdigest()[:16] for k, v in sorted(texts.items())}


@pytest.fixture
def keep_rng():
    rng = naming._rng
    yield
    naming._rng = rng


def test_auto_prompts_match_snapshot(keep_rng):
    got = {"short": _digest(_prompts(_short())), "serial": _digest(_prompts(_long()))}
    if os.environ.get("CANON_UPDATE_SNAPSHOT"):
        SNAPSHOT.write_text(json.dumps(got, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    want = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for form in ("short", "serial"):
        assert set(got[form]) == set(want[form]), form
        changed = [k for k in want[form] if got[form][k] != want[form][k]]
        assert not changed, f"{form}: 모두 auto 인데 프롬프트가 바뀜 {changed}"


def test_ai_schemas_have_no_context():
    assert "context" not in Character.model_json_schema()["properties"]
    for model in (SetupSuggestion, StateDelta):
        chars = model.model_json_schema()["$defs"]["Character"]["properties"]
        assert "context" not in chars and "body" not in chars
    assert '"context"' not in prompts._schema_text(StateDelta)


def test_old_project_reads_as_auto_and_prompt_dump_hides_it():
    p = Project.model_validate({"meta": {"title": "x"}, "characters": [{"id": "a", "name": "A", "role": "주인공"}]})
    assert p.characters[0].context == "auto"
    p.characters[0].context = "off"
    assert Project.model_validate_json(p.model_dump_json()).characters[0].context == "off"  # 저장하면 남는다
    assert "context" not in llm.dump(p.characters) and "context" not in llm.dump(p.characters[0])
    assert "context" not in json.dumps(prompts.cast_view(p.characters), ensure_ascii=False)


def _with_side(p: Project) -> Project:
    """주역 hero · ally 에 조연 '대장장이'(smith)와 단역 '행인'(walker)을 더한다. 설정 글은 프롬프트에서 찾기 쉬운 말."""
    p.characters += [Character(id="smith", name="대장장이", role="조연", tier="support", personality="쇳물냄새성격"),
                     Character(id="walker", name="행인", role="단역", tier="minor", personality="지나가는성격")]
    p.states += [CharacterState(character_id="smith", emotional_state="대장장이감정"), CharacterState(character_id="walker")]
    p.relationships.append(Relationship(a="hero", b="smith", type="대장장이사이", description="오랜 단골"))
    return p


def test_always_side_character_goes_in_front_block():
    p = _with_side(_short())
    n = 4
    assert "smith" not in p.episode(n).plot.characters
    assert "쇳물냄새성격" not in prompts.episode_prompt(p, n)  # auto 조연은 나오지 않는 화에 없다
    p.characters[-2].context = "always"
    static = prompts.static_context(p)
    assert "쇳물냄새성격" in static and "주역과 늘 넣는 인물" in static
    assert "지나가는성격" not in static
    assert prompts.episode_prompt(p, n).startswith(static)  # 앞 블록이라 캐시가 맞는다
    assert "smith" in context.episode_cast(p, n) and "smith" in context.planning_cast(p, n)
    p.episode(n).text = "본문"
    assert "쇳물냄새성격" in prompts.state_prompt(p, n) and "쇳물냄새성격" in prompts.check_prompt(p, n)
    assert prompts.episode_prompt(p, n) in prompts.episode_brief(p, n)  # 작업지시서도 같은 함수


def test_off_character_keeps_name_only():
    p = _with_side(_short())
    n = 2
    p.episode(n).plot.characters = ["hero", "smith"]
    p.episode(n).text = "본문"
    before = prompts.episode_prompt(p, n)
    assert "쇳물냄새성격" in before and "대장장이감정" in before and "대장장이사이" in before
    p.characters[-2].context = "off"
    for text in (prompts.episode_prompt(p, n), prompts.episode_brief(p, n), prompts.check_prompt(p, n, "full"),
                 prompts.check_prompt(p, n, "budget"), prompts.state_prompt(p, n), prompts.plot_prompt(p, n, n),
                 prompts.arc_prompt(p), prompts.passage_prompt(p, n, Selection(text="본문"), "")):
        assert "쇳물냄새성격" not in text and "대장장이감정" not in text and "대장장이사이" not in text
    assert "대장장이(smith)" in prompts.episode_prompt(p, n)  # 등장 인물 줄에는 이름이 남는다
    assert "smith: 대장장이(조연)" in prompts.state_prompt(p, n)  # 상태 정리가 다시 만들지 않게 한 줄 목록에
    assert "smith: 대장장이(조연)" in prompts.plot_prompt(p, n, n)
    assert "smith" not in context.episode_cast(p, n) and "smith" not in context.planning_cast(p, n)


def test_off_main_character_leaves_front_block():
    p = _with_side(_long())
    ally = next(c for c in p.characters if c.id == "ally")
    ally.personality = "도현만의성격"
    assert "도현만의성격" in prompts.static_context(p)
    ally.context = "off"
    n = p.episode(1).plot.number
    assert "도현만의성격" not in prompts.static_context(p)
    assert "ally: 도현(조연)" in prompts.roster_line(p, set())
    start = (p.planned_until() or 0) + 1
    plan = prompts.next_arc_prompt(p, start, 0, "")
    assert "도현만의성격" not in plan and "ally: 도현" in plan
    assert "ally" not in context.planning_cast(p, start) and "ally" not in context.episode_cast(p, n)


def test_serial_always_over_budget_drops_side_characters(monkeypatch):
    p = _with_side(_long())
    n = next(e.plot.number for e in p.episodes if not e.text)
    p.episode(n).plot.characters = ["hero", "smith", "walker"]
    p.characters.append(Character(id="sage", name="현자", role="조연", tier="support", background="현자배경" + "가" * 500))
    big = prompts.episode_prompt(p, n)
    assert "쇳물냄새성격" in big and "지나가는성격" in big  # auto 만 있으면 예산을 보지 않는다
    monkeypatch.setitem(context.BUDGET, "cast", 1)
    assert prompts.episode_prompt(p, n) == big  # '항상' 인물이 없으면 예산이 작아도 그대로
    p.characters[-1].context = "always"
    size = lambda c: len(llm.dump(prompts.cast_view([c])))  # noqa: E731
    sage, smith = (next(c for c in p.characters if c.id == x) for x in ("sage", "smith"))
    monkeypatch.setitem(context.BUDGET, "cast", size(sage) + size(smith) + 10)
    text = prompts.episode_prompt(p, n)
    assert "현자배경" in prompts.static_context(p) and "쇳물냄새성격" in text
    assert "지나가는성격" not in text and "1명은 설정을 뺐습니다" in text  # 단역부터 뺀다
    assert "행인(walker)" in text  # 이름은 등장 인물 줄에 남는다
    monkeypatch.setitem(context.BUDGET, "cast", 1)
    text = prompts.episode_prompt(p, n)
    assert "쇳물냄새성격" not in text and "2명은 설정을 뺐습니다" in text and "현자배경" in text


def test_short_always_has_no_budget(monkeypatch):
    p = _with_side(_short())
    p.episode(2).plot.characters = ["hero", "smith", "walker"]
    p.characters[-1].context = "always"
    monkeypatch.setitem(context.BUDGET, "cast", 1)
    text = prompts.episode_prompt(p, 2)
    assert "쇳물냄새성격" in text and "지나가는성격" in text and "설정을 뺐습니다" not in text
