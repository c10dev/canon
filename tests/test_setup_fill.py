"""설정 도우미의 인물 칸 AI: 인물 칸 ✦ 후보(pipeline.suggest_field 의 characters.<번호>.<칸>)와
빈칸 AI 제안이 이미 있는 인물의 빈 칸만 채우기(pipeline.apply_setup · fill_character)."""
import pytest

from canon import pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Character, Project, Relationship, SetupSuggestion, WorldSetting

from .jsvm import dump, episode, needs_node, run_js

FILES = ["app.js", "home.js", "setup.js", "ideas.js"]


def cast() -> Project:
    p = Project()
    p.meta.title = "등대"
    p.characters = [Character(id="hero", name="서윤", role="주인공", goal="오빠를 찾는다"),
                    Character(id="ally", name="도현", role="조연", personality="느긋하다")]
    p.relationships = [Relationship(a="hero", b="ally", type="동료")]
    return p


def suggestion(*chars: Character) -> SetupSuggestion:
    return SetupSuggestion(theme="", tone="", world=WorldSetting(), characters=list(chars), relationships=[])


def test_character_idea_keys():
    assert prompts.idea_key("characters.12.arc") == "characters.*.arc"
    assert prompts.idea_key("meta.title") == "meta.title"
    p = cast()
    assert prompts.field_value(p, "characters.1.personality") == "느긋하다"
    text = prompts.field_prompt(p, "characters.0.personality")
    # 칸 이름에 인물 이름이 붙고, 그 인물의 설정과 관계가 들어간다
    assert "[채울 칸] 서윤의 성격" in text and "[이 인물]" in text and "오빠를 찾는다" in text and "동료" in text
    assert "[이 인물]" not in prompts.field_prompt(p, "world.setting")


def test_character_ideas_from_pipeline():
    p = cast()
    ideas = pipeline.suggest_field(MockLLM(), p, "characters.0.arc")
    assert len(ideas.options) == 3 and all("→" in o.text for o in ideas.options)
    with pytest.raises(KeyError, match="없는 인물"):
        pipeline.suggest_field(MockLLM(), p, "characters.5.arc")
    with pytest.raises(KeyError, match="받을 수 없는 칸"):
        pipeline.suggest_field(MockLLM(), p, "characters.0.name")


def test_fill_only_blank_fields_of_existing_character():
    p = cast()
    pipeline.apply_setup(p, suggestion(
        Character(id="hero", name="서윤", role="조연", goal="다른 목표", personality="고집이 세다", secrets=["편지를 숨겼다", " "],
                  arc="혼자 → 함께", narration_voice="안 넣는다"),
        Character(id="ally", name="", role="조연", personality="다른 성격", appearance="키가 크다"),
    ))
    hero, ally = p.characters
    assert len(p.characters) == 2  # 같은 인물이라 새로 넣지 않는다
    assert (hero.role, hero.goal) == ("주인공", "오빠를 찾는다")  # 적어 둔 칸은 그대로
    assert (hero.personality, hero.secrets, hero.arc) == ("고집이 세다", ["편지를 숨겼다"], "혼자 → 함께")
    assert hero.narration_voice == ""  # 채우는 칸이 아니다
    assert (ally.personality, ally.appearance) == ("느긋하다", "키가 크다")
    assert p.setting_log == []  # 1화 반영 전에는 기록하지 않는다


def test_fill_after_first_episode_is_logged():
    p = cast()
    p.episodes = [episode(1, status="finalized")]
    pipeline.apply_setup(p, suggestion(Character(id="hero", name="서윤", role="주인공", appearance="짧은 머리")))
    assert [(r.character_id, r.field, r.before, r.after, r.source) for r in p.setting_log] == [("hero", "appearance", "", "짧은 머리", "author")]


@needs_node
def test_js_fill_fields_match_server():
    assert sorted(run_js(FILES, "SUG_FILL_FIELDS.map(([k]) => k)", {})) == sorted(pipeline.FILL_CHAR_FIELDS)


@needs_node
def test_js_character_ideas():
    """인물 칸 ✦: 키는 번호를 * 로, 이름이 붙은 칸 이름, 그사이 인물이 바뀌면 칸에 넣지 않는다."""
    expr = """(() => {
      S.project = data.project;
      S.name = 'demo';
      render = () => {};
      toast = (m) => { S.lastToast = m; };
      const btn = ideaBtn('characters.1.personality');
      const none = ideaBtn('characters.1.name');
      S.ideas = { 'characters.1.personality': { cid: 'ally', options: [{ text: '고집이 세다', reason: '' }] } };
      actions.useIdea('characters.1.personality|0');
      const ok = P().characters[1].personality;
      S.ideas = { 'characters.1.arc': { cid: 'gone', options: [{ text: 'A → B', reason: '' }] } };
      actions.useIdea('characters.1.arc|0');
      return { key: ideaKey('characters.3.arc'), btn, none, ok, stale: [P().characters[1].arc, 'characters.1.arc' in S.ideas, S.lastToast] };
    })()"""
    got = run_js(FILES, expr, {"project": dump(cast())})
    assert got["key"] == "characters.*.arc"
    assert 'aria-label="도현 성격 AI 후보 세 개 받기"' in got["btn"] and 'aria-controls="ideas-characters-1-personality"' in got["btn"]
    assert got["none"] == ""
    assert got["ok"] == "고집이 세다"
    assert got["stale"][:2] == ["", False] and "다시" in got["stale"][2]


@needs_node
def test_js_suggestion_fills_existing_character():
    """제안 화면: 이미 있는 인물은 빈 칸마다 고르고, 고르지 않은 칸은 비워 보낸다."""
    sug = suggestion(Character(id="hero", name="서윤", role="주인공", goal="다른 목표", personality="고집이 세다", arc="혼자 → 함께"),
                     Character(id="mina", name="미나", role="조연"))
    expr = """(() => {
      S.project = data.project;
      S.name = 'demo';
      S.suggestion = data.sug;
      S.picks = { sc1: true };
      const card = sugFillCard(S.suggestion.characters[0], 0);
      S.picks['scf:0:arc'] = false;
      return { card, sent: sugPayload().characters.map((c) => [c.id, c.personality, c.arc, c.goal]) };
    })()"""
    got = run_js(FILES, expr, {"project": dump(cast()), "sug": dump(sug)})
    # 적어 둔 원하는 것은 채울 칸이 아니다
    assert "빈칸 2개 채움" in got["card"] and 'data-pick="scf:0:personality"' in got["card"] and "scf:0:goal" not in got["card"]
    assert got["sent"] == [["hero", "고집이 세다", "", "다른 목표"], ["mina", "", "", ""]]
