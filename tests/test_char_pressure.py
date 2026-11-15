"""인물 압력 칸(Character.pressure, 웹소설 일감 11a).

- 옛 project.json 은 압력 칸 없이 읽힌다.
- 압력을 적지 않은 작품의 쓰기 · 설정 요청 글은 칸을 더하기 전과 글자까지 같다.
- 압력을 적으면 쓰기 요청의 바뀌지 않는 앞 블록(인물 블록)에 들어간다.
- 설정 제안 · 설정 대화 · 무작위 출생의 응답 형식이 압력 칸을 받고, 적용하면 인물에 들어간다.
"""
from __future__ import annotations

from canon import birth, charlog, llm, pipeline, prompts, setupchat
from canon.mock import MockLLM
from canon.schema import Birth, BirthSketch, Character, CharacterEdit, Project, SetupRevision, SetupSuggestion

L = MockLLM()
CAST_EXCLUDE = {"narration_voice", "body", "context", "aliases", "marks"}


def _written() -> Project:
    p = Project()
    p.meta.title, p.meta.target_episodes = "단편", 4
    pipeline.apply_setup(p, pipeline.suggest_setup(L, p))
    p.arc = pipeline.plan_arc(L, p).acts
    pipeline.apply_plots(p, pipeline.draft_plots(L, p, 1, 4))
    pipeline.confirm_plot(p, 1)
    p.episode(1).text = pipeline.write_episode(L, p, 1)
    p.episode(1).status = "written"
    pipeline.apply_delta(p, pipeline.extract_state(L, p, 1))
    pipeline.confirm_plot(p, 2)
    return p


def _legacy_cast_view(cs: list[Character]) -> list[dict]:
    """압력 칸을 더하기 전의 cast_view: 같은 칸, 같은 차례에서 압력만 없다."""
    return [{k: v for k, v in c.model_dump(exclude=CAST_EXCLUDE).items() if k != "pressure"} for c in cs]


def test_old_project_reads_without_pressure():
    p = Project.model_validate({"meta": {"title": "x"}, "characters": [{"id": "a", "name": "A", "role": "주인공"}]})
    assert p.characters[0].pressure == ""
    assert '"pressure"' not in llm.dump(p.characters) and '"pressure"' not in llm.dump(p.characters[0])


def test_empty_pressure_keeps_write_prompt_unchanged(monkeypatch):
    p = _written()
    for c in p.characters:
        c.pressure = ""
    now = {"static": prompts.static_context(p), "episode": prompts.episode_prompt(p, 2), "setup": prompts.setup_prompt(p),
           "chat": prompts.setup_chat_prompt(p, "말투를 다듬어 줘")}
    assert all('"pressure"' not in v for v in now.values())
    monkeypatch.setattr(prompts, "cast_view", _legacy_cast_view)
    assert prompts.static_context(p) == now["static"]
    assert prompts.episode_prompt(p, 2) == now["episode"]


def test_pressure_goes_in_front_cast_block():
    p = _written()
    hero = p.characters[0]
    hero.pressure = "압력시험문장. 흔들리면 문을 잠근다."
    front = prompts.static_context(p)
    text = prompts.episode_prompt(p, 2)
    assert hero.pressure in front and text.count(hero.pressure) == 1
    assert text.index(hero.pressure) < text.index(p.episode(2).plot.summary)  # 화마다 바뀌는 플롯보다 앞
    view = prompts.cast_view([hero])[0]
    keys = list(view)
    assert keys.index("wound") < keys.index("pressure") < keys.index("speech_style")
    assert all("pressure" not in v for v in prompts.cast_view(p.characters[1:]))


def test_setup_prompts_ask_pressure_not_habit_or_line():
    p = Project()
    p.meta.title = "x"
    text = prompts.setup_prompt(p)
    assert "pressure" in text and "무엇을 지키려 하는지, 흔들리면 어디로 가는지" in text
    assert "버릇 하나" not in text and "대사 예시 한 줄" not in text
    chat = prompts.setup_chat_prompt(p, "인물 다듬기")
    assert "wound, pressure, speech_style" in chat and "대사 예시 한 줄" not in chat
    b = Birth(name="해솔", gender="여", age="20세", archetype="", wound="", speech="", twist="", place="")
    roll = prompts.birth_prompt(p, b)
    assert "- pressure:" in roll and "대사 예시 한 줄" not in roll
    assert "버릇" not in prompts.FIELD_IDEAS["characters.*.personality"][1]
    assert "대사 예시" not in prompts.FIELD_IDEAS["characters.*.speech_style"][1]
    assert "characters.*.pressure" in prompts.FIELD_IDEAS
    assert "버릇" not in Character.model_fields["personality"].description


def test_setup_suggestion_fills_pressure_only_when_empty():
    p = Project()
    p.meta.title = "x"
    p.characters = [Character(id="hero", name="서윤", role="주인공", pressure="작가가 적은 압력")]
    s = pipeline.suggest_setup(L, p)
    assert "pressure" in SetupSuggestion.model_json_schema()["$defs"]["Character"]["properties"]
    assert next(c for c in s.characters if c.id == "hero").pressure  # 가짜 응답은 압력을 채운다
    pipeline.apply_setup(p, s)
    assert p.characters[0].pressure == "작가가 적은 압력"  # 작가가 적은 칸은 덮지 않는다
    q = Project()
    q.meta.title = "y"
    pipeline.apply_setup(q, pipeline.suggest_setup(L, q))
    assert next(c for c in q.characters if c.id == "hero").pressure


def test_setup_chat_edits_pressure():
    p = Project()
    p.characters = [Character(id="hero", name="서윤", role="주인공")]
    rev = SetupRevision(reply="압력을 적었어요.", characters=[CharacterEdit(id="hero", field="pressure", text="지키는 것. 흔들리면 숨는다.")])
    assert setupchat.label(p, rev, "c:hero:pressure").endswith("압력")
    setupchat.apply_revision(p, rev, ["c:hero:pressure"])
    assert p.characters[0].pressure == "지키는 것. 흔들리면 숨는다."
    assert charlog.label("pressure") == "압력"


def test_birth_sketch_carries_pressure():
    p = Project()
    b = Birth(name="해솔", gender="여", age="20세", archetype="", wound="", speech="", twist="", place="")
    s = BirthSketch(personality="말이 적다", pressure="떠나지 않는 사람. 흔들리면 일에 매달린다.")
    assert birth.to_character(p, b, s).pressure == s.pressure
    assert "pressure" in BirthSketch.model_json_schema()["properties"]
