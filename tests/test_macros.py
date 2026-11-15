"""CBS 읽기 매크로 (docs/context/specs/05-macros.md, canon/macros.py). LLM 비용 없음.
실행: CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_macros.py"""
import json

from canon import elements, echoes, macros, prompts, store
from canon.macros import MacroEnv
from canon.schema import Character, CharacterState, Episode, EpisodePlot, Project, Snapshot, StatValue, StoryElement


def _env(**kw):
    base = dict(user="서윤", pov="도현", names=[("hero", "서윤"), ("ally", "도현")], episode=3,
                stats=[("hero", "서윤", "레벨", "7"), ("hero", "서윤", "HP", "80/100"), ("ally", "도현", "기술.검", "5")])
    return MacroEnv(**{**base, **kw})


def x(text, env=None, char=""):
    return macros.expand(text, env or _env(), "칸", char)


def test_no_macros_is_identity():
    assert x("그냥 글 { } {중괄호}") == ("그냥 글 { } {중괄호}", [])
    assert x("닫지 않은 {{user 는 그대로")[0] == "닫지 않은 {{user 는 그대로"


def test_basic_macros_and_case():
    text, uses = x("{{user}} · {{User}} · {{char}} · {{bot}} · {{episode}} · {{getvar::서윤.레벨}} · {{getvar::hero.HP}} · {{getvar::ally.기술.검}}")
    assert text == "서윤 · 서윤 · 도현 · 도현 · 3 · 7 · 80/100 · 5"
    assert all(u.where == "칸" and u.value and not u.note for u in uses)
    assert x("{{char}}", char="민지")[0] == "민지"  # 항목에 이어진 인물이 먼저


def test_left_as_is_with_warnings():
    text, uses = x("{{roll::6}} {{chatindex}} {{setvar::a::1}} {{getvar::도현.레벨}} {{getvar::누구.레벨}}")
    assert text == "{{roll::6}} {{chatindex}} {{setvar::a::1}} {{getvar::도현.레벨}} {{getvar::누구.레벨}}"
    notes = [u.note for u in uses]
    assert notes[0] == "'{{roll::6}}'은(는) Canon이 모르는 매크로라 그대로 보냈어요."
    assert "'{{episode}}'를 쓰세요" in notes[1] and "값을 읽기만 해요" in notes[2]
    assert notes[3] == "도현의 상태창에 '레벨'이(가) 없어 그대로 보냈어요." and "인물을 찾지 못해" in notes[4]
    assert all(not u.value for u in uses)


def test_block_kept_whole_and_nested_inner_first():
    text, uses = x("앞 {{#when::{{user}}::is::서윤}}안 {{char}}{{/when}} 뒤 {{getvar::{{char}}.기술.검}}")
    assert text == "앞 {{#when::{{user}}::is::서윤}}안 {{char}}{{/when}} 뒤 5"
    assert "조건 블록은 쓰지 않아요" in uses[0].note
    assert [u.raw for u in uses[1:]] == ["{{char}}", "{{getvar::{{char}}.기술.검}}"]


def test_expanded_values_are_not_rescanned():
    env = _env(stats=[("hero", "서윤", "메모", "{{user}}")])
    assert x("{{getvar::서윤.메모}}", env)[0] == "{{user}}"


def test_pov_fallback_and_static_env():
    text, uses = x("{{char}}", _env(pov="서윤", pov_fallback=True))
    assert text == "서윤" and uses[0].note == "시점 인물이 없어 '{{char}}'에 주인공을 넣었어요."
    text, uses = x("{{user}} {{episode}} {{char}} {{getvar::서윤.레벨}}", _env(dynamic=False))
    assert text == "서윤 {{episode}} {{char}} {{getvar::서윤.레벨}}"
    assert all("앞쪽 블록이라" in u.note for u in uses[1:])


def _plot(n, chars=("hero",), pov=""):
    return EpisodePlot(number=n, act="기", title=f"{n}화", summary="요약", events=["사건"], characters=list(chars), emotional_shift="",
                       ending_hook="", pov=pov)


def _project() -> Project:
    p = Project()
    p.characters = [Character(id="hero", name="서윤", role="주인공", tier="main"), Character(id="ally", name="도현", role="친구")]
    p.episodes = [Episode(plot=_plot(1), status="finalized", text="서윤이 섰다."), Episode(plot=_plot(2, pov="ally"), status="confirmed"),
                  Episode(plot=_plot(3), status="draft")]
    p.states = [CharacterState(character_id="hero", stats=[StatValue(name="레벨", value="7")])]
    p.elements = [StoryElement(id="e1", name="각인", description="{{char}}의 각인은 레벨 {{getvar::서윤.레벨}}부터 빛난다. {{episode}}화",
                               characters=["ally"], context="always"),
                  StoryElement(id="e2", name="밤", description="{{char}}는 밤에 강하다", context="always")]
    p.meta.notes = "{{user}}의 이야기. {{episode}}화"
    return p


def test_prompts_expand_elements_and_notes_without_touching_data():
    p = _project()
    before = p.model_dump()
    text = prompts.episode_prompt(p, 2)
    assert "도현의 각인은 레벨 7부터 빛난다. 2화" in text and "도현는 밤에 강하다" in text  # 2화 시점 인물 도현
    assert "서윤의 이야기. {{episode}}화" in text  # 메모는 {{user}} 만
    assert prompts.static_context(p) == prompts.static_context(p) and "{{episode}}화" in prompts.static_context(p)
    assert prompts.episode_brief(p, 2).count("레벨 7부터") == 1  # 작업지시서도 같은 펼친 글
    assert "레벨 7부터" in prompts.passage_head(p, 2)
    assert p.model_dump() == before


def test_value_time_uses_snapshot_and_warns_when_missing():
    p = _project()
    p.episode(2).status, p.episode(2).text = "finalized", "글"
    p.states[0].stats[0].value = "9"  # 2화 반영 뒤 값
    env = prompts.macro_env(p, 2)
    assert ("hero", "서윤", "레벨", "9") in env.stats and "1화 직전 스냅샷이 없어" in env.note
    p.snapshots = [Snapshot(episode=1, states=[CharacterState(character_id="hero", stats=[StatValue(name="레벨", value="7")])])]
    env = prompts.macro_env(p, 2)
    assert ("hero", "서윤", "레벨", "7") in env.stats and env.note == ""
    assert prompts.macro_env(p, 3).stats[0][3] == "9"


def test_no_macro_project_gets_no_env_and_same_block():
    p = _project()
    for el in p.elements:
        el.description = el.description.replace("{{", "").replace("}}", "")
    assert prompts.macro_env(p, 2) is None and prompts.plan_env(p) is None
    assert elements.episode_block(p, 2, None) == elements.episode_block(p, 2)


def test_places_budget_counts_expanded_text(monkeypatch):
    from canon import context
    p = _project()
    p.meta.form = "serial"
    p.elements = [StoryElement(id=f"pl{i}", kind="장소", name=f"곳{i}", description="{{getvar::서윤.레벨}}" + "가" * 10,
                               found_in="본문", found_ep=1) for i in range(3)]
    p.states[0].stats[0].value = "7" * 200  # 펼치면 길어진다
    monkeypatch.setitem(context.BUDGET, "places", 400)
    env = prompts.macro_env(p, 2)
    lines = elements.found_lines(p, p.elements, "", 2, env)
    assert len([x for x in lines if x.startswith("- [장소]")]) == 1 and "2곳은 덜 관련돼 뺐다" in lines[-1]  # 펼친 길이(약 220자)로 센다
    assert len([x for x in elements.found_lines(p, p.elements, "", 2) if x.startswith("- [장소]")]) == 3


def test_echoes_strip_macros():
    p = _project()
    assert "getvar" not in echoes._canon_text(p) and "episode" not in " ".join(echoes._canon_text(p))


def test_prompt_view_lists_macros(client):
    p = _project()
    store.save("mc", p)
    rows = client.get("/api/projects/mc/episodes/2/context").json()
    els = next(r for r in rows if r["id"] == "elements")
    assert {"where": "이야기 요소 '각인' 설명", "raw": "{{getvar::서윤.레벨}}", "value": "7", "note": ""} in els["macros"]
    work = next(r for r in rows if r["id"] == "work")
    assert [m["raw"] for m in work["macros"]] == ["{{user}}", "{{episode}}"] and "앞쪽 블록이라" in work["macros"][1]["note"]
    assert json.loads((store.project_dir("mc") / "project.json").read_text(encoding="utf-8"))["elements"][0]["description"].startswith("{{char}}")  # 저장한 글은 그대로


from .jsvm import needs_node, run_js  # noqa: E402


@needs_node
def test_prompt_view_js_lists_macros():
    """프롬프트 보기의 블록 안(write.js ctxMore)이 '어느 칸 · 원문 → 값'과 경고를 한 줄씩 보인다. 매크로가 없으면 그 칸을 그리지 않는다."""
    row = {"id": "elements", "title": "이야기 요소", "chars": 10, "tokens": 6, "on": True, "items": [], "dropped": [], "text": "글",
           "macros": [{"where": "이야기 요소 '각인' 설명", "raw": "{{getvar::서윤.레벨}}", "value": "7", "note": ""},
                      {"where": "이야기 요소 '각인' 설명", "raw": "{{roll::6}}", "value": "", "note": "모르는 매크로라 그대로 보냈어요."}]}
    got = run_js(["app.js", "write.js"], "[ctxMore(data), ctxMore({ ...data, macros: [] })]", row)
    assert "매크로 2개" in got[0] and "이야기 요소 &#39;각인&#39; 설명 · <code>{{getvar::서윤.레벨}}</code> → 7" in got[0]
    assert "모르는 매크로라 그대로 보냈어요." in got[0] and "매크로" not in got[1]
