"""이름으로 켜는 인물(context.named_ids)과 오랜만에 다시 나오는 인물(prompts.return_block), 말투가 빈 새 인물 경고 (mock LLM).
플롯 인물 목록에 없는 조연이 본문에 나오면 장편 쓰기 · 검수 · 상태 변경안에 그 인물의 설정 · 말투 · 상태가 없던 빈틈을 막는다."""
from canon import context, features, pipeline, prompts
from canon.schema import Character, CharacterState, StateDelta
from tests.jsvm import dump, episode, needs_node, run_js
from tests.test_serial import _plan_arc, _serial

SMITH = Character(id="smith", name="마르타 부인", role="대장장이", tier="support", speech_style="걸걸한 반말. \"쇠는 식기 전에 두드려.\"")


def _project():
    """1~12화를 쓰고 반영한 장편. 대장장이는 인물이지만 어느 화 플롯 인물 목록에도 없다."""
    p = _serial()
    a = _plan_arc(p)
    p.characters.append(SMITH.model_copy())
    p.states.append(CharacterState(character_id="smith", location="북문 대장간", knows=["서윤이 검을 맡겼다"]))
    for n in range(a.start_ep, a.end_ep + 1):
        e = p.episode(n)
        e.text, e.status, e.summary = f"{n}화 본문. 서윤은 길을 걸었다.", "finalized", f"{n}화 요약. 서윤이 길을 걸었다."
    return p, a


def test_named_ids_skip_names_inside_other_names():
    p = _serial()
    p.characters += [Character(id="a", name="윤민정", role=""), Character(id="b", name="김민정", role=""),
                     Character(id="t", name="톰", role=""), SMITH.model_copy()]
    assert context.named_ids(p, "김민정이 웃었다.") == {"b"}
    assert context.named_ids(p, "민정이 고개를 들었다.") == {"a", "b"}  # 성을 뗀 이름이 같으면 둘 다 (이름 점검이 따로 알린다)
    assert context.named_ids(p, "톰은 문을 닫았다. 마르타가 불렀다.") == {"t", "smith"}  # 띄어 쓴 이름은 첫 낱말도
    assert context.named_ids(p, "아톰이라는 말") == set()  # 한글 바로 뒤에 붙은 이름은 다른 낱말


def test_write_context_adds_side_character_named_in_plot():
    p, a = _project()
    n = a.end_ep + 1
    p.episodes.append(episode(n, status="confirmed", plot={"characters": ["hero"], "events": ["서윤이 마르타 부인에게 검을 찾으러 간다"]}))
    ctx = prompts.build_episode_context(p, n)
    assert "이름이 나온 인물 설정" in ctx and "걸걸한 반말" in ctx
    assert "북문 대장간" in ctx  # 상태도 함께

    p.episode(n).plot.events = ["서윤이 혼자 길을 떠난다"]
    ctx = prompts.build_episode_context(p, n)
    assert "걸걸한 반말" not in ctx and "북문 대장간" not in ctx


def test_write_context_named_respects_cast_budget():
    p, a = _project()
    n = a.end_ep + 1
    p.episodes.append(episode(n, status="confirmed", plot={"characters": ["hero"], "events": ["마르타 부인을 만난다"]}))
    budget = context.BUDGET["cast"]
    context.BUDGET["cast"] = 10
    try:
        ctx = prompts.build_episode_context(p, n)
    finally:
        context.BUDGET["cast"] = budget
    assert "1명은 설정을 뺐습니다" in ctx and "걸걸한 반말" not in ctx


def test_short_write_context_unchanged():
    p, a = _project()
    p.meta.form = "short"
    n = a.end_ep + 1
    p.episodes.append(episode(n, status="confirmed", plot={"characters": ["hero"], "events": ["마르타 부인을 만난다"]}))
    assert "걸걸한 반말" not in prompts.build_episode_context(p, n)


def test_check_and_state_prompts_see_side_character_in_text():
    p, a = _project()
    n = a.end_ep
    e = p.episode(n)
    e.text = "마르타 부인이 망치를 내려놓았다. \"쇠는 식기 전에 두드려요.\""
    assert n not in [x for x in e.plot.characters if x == "smith"]
    check = prompts.check_material(p, n)
    assert "조연 · 단역 설정" in check and "걸걸한 반말" in check and "북문 대장간" in check
    state = prompts.state_prompt(p, n)
    assert "걸걸한 반말" in state.split("[이전 인물 상태]")[0]  # 한 줄 목록이 아니라 [인물 설정]에


def test_return_block_marks_long_absence():
    p, a = _project()
    p.episode(2).text = "마르타 부인이 검을 받았다."
    p.episode(2).summary = "서윤이 길을 떠났다. 마르타 부인이 서윤의 검을 맡아 두었다."
    n = a.end_ep + 1
    rows = prompts.return_lines(p, {"hero", "smith"}, n)
    assert rows == [f"- 마르타 부인: 마지막으로 나온 화 2화 ({n - 2}화 전). 2화 요약: 마르타 부인이 서윤의 검을 맡아 두었다."]
    assert prompts.return_lines(p, {"smith"}, 2 + context.RETURN_GAP - 1) == []  # 공백이 짧으면 없다
    p.episode(2).summary = "서윤이 길을 떠났다."
    assert prompts.return_lines(p, {"smith"}, n) == [f"- 마르타 부인: 마지막으로 나온 화 2화 ({n - 2}화 전)"]  # 이름이 없는 요약 문장은 옮기지 않는다
    p.episodes.append(episode(n, status="confirmed", plot={"characters": ["hero", "smith"]}))
    assert "오랜만에 다시 나오는 인물" in prompts.build_episode_context(p, n)


def test_new_character_without_speech_warns():
    p, a = _project()
    d = StateDelta(episode=a.end_ep, summary="", new_characters=[
        Character(id="guard", name="문지기", role="단역", tier="minor"),
        Character(id="cook", name="요리사", role="단역", tier="minor", speech_style="느릿한 존댓말"),
    ])
    features.clean(p, d)
    assert [w for w in d.warnings if "말투" in w] == ["새 인물 문지기의 말투(speech_style)가 비었어요. 반영한 뒤 인물 화면에서 채워 주세요."]


@needs_node
def test_home_todo_lists_speech_gaps():
    p, a = _project()
    p.characters.append(Character(id="guard", name="문지기", role="단역", tier="minor"))
    p.episodes.append(episode(a.end_ep + 1, status="confirmed", plot={"characters": ["hero", "guard"]}))
    todos = run_js(["app.js", "home.js"], "homeTodos(data.p, '#/p/x')", {"p": dump(p)})
    got = [t for t in todos if t["tag"] == "인물"]
    assert [(t["label"], t["href"]) for t in got] == [(f"{a.end_ep + 1}화 인물 1명의 말투가 비었어요", "#/p/x/cast/guard")]
    p.characters[-1].speech_style = "짧은 반말"
    todos = run_js(["app.js", "home.js"], "homeTodos(data.p, '#/p/x')", {"p": dump(p)})
    assert not [t for t in todos if t["tag"] == "인물"]
    assert pipeline  # mock 경로를 함께 불러 둔다
