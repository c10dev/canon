"""쓰기 요청 블록 설정과 예산 (docs/context/specs/03-prompt-view.md).

설정이 빈 작품의 요청이 고치기 전과 같은지는 tests/test_char_context.py 의 스냅숏이 본다. 여기서는 블록 조각과 설정을 본다."""
from canon import context, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import BlockSetting, BudgetSetting, Character, CharacterState, Project, Relationship
from tests.jsvm import episode
from tests.test_cache_family import _next, _project
from tests.test_char_context import _short


def _set(p: Project, off=(), budgets=None) -> Project:
    p.settings.blocks = [BlockSetting(id=x, on=False) for x in off]
    p.settings.budgets = [BudgetSetting(key=k, value=v) for k, v in (budgets or {}).items()]
    return p


def _ids(parts) -> list[str]:
    out = []
    for x in parts:
        if not out or out[-1] != x.id:
            out.append(x.id)
    return out


def _with_board(p: Project, n: int) -> None:
    if p.episode(n).status == "draft":
        pipeline.confirm_plot(p, n)
    pipeline.set_storyboard(p, n, pipeline.make_storyboard(MockLLM(), p, n), by="ai")


def test_parts_cover_the_whole_request_and_ids_are_blocks():
    for p in (_short(), _project()):
        n = _next(p)
        for use_board in (False, True):
            if use_board:
                _with_board(p, n)
            parts = prompts.episode_parts(p, n)
            assert "".join(x.text for x in parts) == prompts.episode_prompt(p, n)
            assert all(x.text for x in parts)
            assert {x.id for x in parts} <= set(prompts.BLOCK_BY_ID)
            assert parts[-1].id in ("instructions", "cues", "direction")
        pre, between = "# 장소 목록\n가\n\n", "\n\n# 다음 화 플롯\n나"
        for kw in ({}, {"use_board": False, "pre": pre, "between": between, "full_prev": True}):
            parts = prompts.context_parts(p, n, **kw)
            assert "".join(x.text for x in parts) == prompts.build_episode_context(p, n, **kw)
            assert {x.id for x in parts} <= set(prompts.BLOCK_BY_ID)
        assert "".join(x.text for x in prompts.static_parts(p)) == prompts.static_context(p)


def test_block_table_is_consistent():
    ids = [b.id for b in prompts.BLOCKS]
    assert len(ids) == len(set(ids))
    keys = {k for b in prompts.BLOCKS for k in b.keys}
    assert keys <= set(context.WRITE_KEYS)
    assert set(context.WRITE_KEYS) <= keys  # 화면에 보이는 예산 키는 모두 어느 블록이 쓴다
    for locked in ("style", "characters", "cast", "states", "plot", "instructions", "extra", "direction"):
        assert prompts.BLOCK_BY_ID[locked].locked
    assert not prompts.toggleable(prompts.BLOCK_BY_ID["board"])
    assert prompts.toggleable(prompts.BLOCK_BY_ID["named"])


def test_empty_settings_and_default_values_change_nothing():
    for p in (_short(), _project()):
        n = _next(p)
        before = prompts.episode_prompt(p, n)
        _set(p, budgets={k: context.BUDGET[k] for k in context.WRITE_KEYS})
        p.settings.blocks = [BlockSetting(id=b.id, on=True) for b in prompts.BLOCKS]
        assert prompts.episode_prompt(p, n) == before


def test_turning_a_block_off_drops_its_heading_and_keeps_order():
    p = _project()
    n = _next(p)
    full = prompts.episode_parts(p, n)
    assert "# 확정된 사실" in prompts.episode_prompt(p, n)
    _set(p, off=["facts", "world"])
    parts = prompts.episode_parts(p, n)
    text = prompts.episode_prompt(p, n)
    assert "# 확정된 사실" not in text and "# 세계관" not in text
    assert "# 작품 정보" in text and "# 이번 화 플롯" in text
    assert _ids(parts) == [x for x in _ids(full) if x not in ("facts", "world")]
    assert text == "".join(x.text for x in full if x.id not in ("facts", "world"))


def test_first_block_off_leaves_no_leading_blank():
    p = _project()
    n = _next(p)
    _set(p, off=["work"])
    assert prompts.episode_prompt(p, n).startswith("# 세계관")
    assert prompts.static_context(p, follow=True).startswith("# 세계관")


def test_locked_blocks_stay_even_if_stored_off():
    p = _project()
    n = _next(p)
    before = prompts.episode_prompt(p, n)
    _set(p, off=["style", "characters", "cast", "states", "plot", "instructions", "extra", "direction", "board", "echo", "cues", "story"])
    assert prompts.episode_prompt(p, n) == before
    assert all(prompts.block_on(p, x) for x in ("style", "plot", "board", "nope"))


def test_budget_changes_items_and_trace_names_dropped():
    p = _project()
    n = _next(p)
    main = [c.name for c in p.characters if c.tier == "main"][0]
    p.facts = [f"{main}이 {i}번째로 본 일" for i in range(90)]
    t0 = context.Trace()
    before = prompts.episode_prompt(p, n)
    prompts.episode_parts(p, n, trace=t0)
    lo, _ = context.budget_range("facts")
    _set(p, budgets={"facts": lo})
    assert context.budget(p, "facts") == lo
    t1 = context.Trace()
    after = prompts.episode_prompt(p, n)
    prompts.episode_parts(p, n, trace=t1)
    assert len(after) < len(before)
    kept0 = [x for x, _ in t0.items["facts"]]
    kept1 = [x for x, _ in t1.items["facts"]]
    assert len(kept1) < len(kept0)
    dropped = [x for x, why in t1.dropped["facts"] if why == context.DROP_BUDGET]
    assert dropped and set(dropped) <= set(kept0)
    assert all(f"- {x}" not in after.split("# 확정된 사실")[1].split("\n\n#")[0] for x in dropped)


def test_trace_has_reasons_for_people_and_story():
    p = _project()
    n = _next(p)
    t = context.Trace()
    prompts.episode_parts(p, n, trace=t)
    assert t.items["characters"] and all(why == context.REASON_ALWAYS for _, why in t.items["characters"])
    assert any(why == context.REASON_PLOT for _, why in t.items["cast"])
    assert "states" in t.items
    reasons = {why for v in t.items.values() for _, why in v} | {why for v in t.dropped.values() for _, why in v}
    allowed = {v for k, v in vars(context).items() if k.startswith(("REASON_", "DROP_"))}
    assert reasons <= allowed
    assert set(t.items) | set(t.dropped) <= set(prompts.BLOCK_BY_ID)


def test_short_form_ignores_settings_and_budgets():
    p = _short()
    n = _next(p)
    before = prompts.episode_prompt(p, n)
    t0 = context.Trace()
    prompts.episode_parts(p, n, trace=t0)
    _set(p, off=["facts", "world", "states"], budgets={"facts": 100, "deadlines": 300, "stat_lines": 500})
    assert prompts.episode_prompt(p, n) == before
    assert all(context.budget(p, k) == context.BUDGET[k] for k in context.WRITE_KEYS)
    assert all(prompts.block_on(p, b.id) for b in prompts.BLOCKS)


def test_brief_follows_the_same_settings():
    p = _project()
    n = _next(p)
    _set(p, off=["facts", "pov"], budgets={"states": 1700})
    system, prompt = prompts.brief_parts(p, n, "episode")
    assert prompt == prompts.episode_prompt(p, n)
    assert system == prompts.writer_system(p)


def test_write_head_stays_a_prefix_with_settings():
    p = _project()
    n = _next(p)
    _set(p, off=["facts", "returns", "story_past"], budgets={"relations": 800, "story_arc": 1500})
    head = prompts.write_head(p, n)
    assert head and "# 확정된 사실" not in head
    assert prompts.storyboard_prompt(p, n).startswith(head)
    _with_board(p, n)
    assert prompts.write_head(p, n) == head
    assert prompts.cue_sheet_prompt(p, n).startswith(head)
    assert prompts.episode_prompt(p, n).startswith(head)


def test_static_context_default_ignores_settings():
    p = _project()
    before = prompts.static_context(p)
    _set(p, off=["work", "world"])
    assert prompts.static_context(p) == before
    assert "# 작품 정보" not in prompts.static_context(p, follow=True)
    assert "# 작품 정보" in prompts.check_prompt(p, 1, "budget")  # 검수는 설정을 따르지 않는다


def test_unknown_ids_and_keys_load_and_are_ignored():
    p = _project()
    n = _next(p)
    before = prompts.episode_prompt(p, n)
    data = p.model_dump()
    data["settings"]["blocks"] = [{"id": "old_block", "on": False}]
    data["settings"]["budgets"] = [{"key": "old_key", "value": 5}, {"key": "check_facts", "value": 100}]
    q = Project.model_validate(data)
    assert q.settings.blocks[0].id == "old_block"
    assert prompts.block_on(q, "old_block")
    assert context.budget(q, "check_facts") == context.BUDGET["check_facts"]  # 쓰기 키가 아니면 무시한다
    assert prompts.episode_prompt(q, n) == before
    assert Project.model_validate(q.model_dump()).settings.budgets[0].key == "old_key"  # 지우지 않는다
    assert Project.model_validate({"meta": {"title": "x"}}).settings.blocks == []


def test_budget_range():
    for k in context.WRITE_KEYS:
        lo, hi = context.budget_range(k)
        assert 100 <= lo <= context.BUDGET[k] <= hi
        assert lo % 100 == 0 and hi % 100 == 0
        assert context.budget_ok(k, context.BUDGET[k])  # 기본값은 늘 받는 값이다
        assert not context.budget_ok(k, 0)
        assert not context.budget_ok(k, hi + 100)
    assert context.budget_range("facts") == (800, 14_000)
    assert context.budget_range("pairs") == (100, 2_400)
    assert not context.budget_ok("facts", 850)
    assert not context.budget_ok("check_facts", 6_000)


def test_stored_budget_out_of_range_is_ignored():
    p = _project()
    n = _next(p)
    before = prompts.episode_prompt(p, n)
    _set(p, budgets={"facts": 850, "states": 0, "pairs": 99_900})
    assert all(context.budget(p, k) == context.BUDGET[k] for k in ("facts", "states", "pairs"))
    assert prompts.episode_prompt(p, n) == before


# ---------- 이름이 나온 인물 · 조연 예산 ----------

SMITH = Character(id="smith", name="마르타 부인", role="대장장이", tier="support", speech_style="걸걸한 반말. \"쇠는 식기 전에 두드려.\"")
GUARD = Character(id="guard", name="문지기 오토", role="성문지기", tier="support", speech_style="딱딱한 존댓말. " + "가" * 300)
CLERK = Character(id="clerk", name="서기 한스", role="서기", tier="minor", speech_style="느릿한 말. " + "나" * 300)
ALWAYS = Character(id="always", name="늘 곁 노아", role="길동무", tier="support", context="always", speech_style="밝은 말. " + "다" * 300)


def _named_project():
    """플롯 인물 목록 밖의 대장장이가 플롯 글에 이름으로 나오는 장편 화. 대장장이는 상태 · 관계가 있다."""
    from tests.test_named_cast import _project as named
    p, a = named()
    hero = next(c.id for c in p.characters if c.tier == "main")
    p.relationships.append(Relationship(a=hero, b="smith", type="단골", description="검을 맡기는 사이"))
    n = a.end_ep + 1
    p.episodes.append(episode(n, status="confirmed", plot={"characters": [hero], "events": ["서윤이 마르타 부인에게 검을 찾으러 간다"]}))
    return p, n


def test_named_block_off_removes_named_characters_everywhere():
    p, n = _named_project()
    on = prompts.episode_prompt(p, n)
    t0 = context.Trace()
    prompts.episode_parts(p, n, trace=t0)
    assert "걸걸한 반말" in on and "북문 대장간" in on and "검을 맡기는 사이" in on
    assert any(x == "마르타 부인" for x, _ in t0.items["named"])
    _set(p, off=["named"])
    off = prompts.episode_prompt(p, n)
    t1 = context.Trace()
    prompts.episode_parts(p, n, trace=t1)
    assert "걸걸한 반말" not in off and "북문 대장간" not in off and "검을 맡기는 사이" not in off  # 설정 · 상태 · 관계 모두
    assert "마르타 부인" not in off.split("# 이번 화 플롯")[0]
    assert "named" not in t1.items and "named" not in t1.dropped
    assert all("마르타 부인" not in x for v in t1.items.values() for x, _ in v)


def test_lower_cast_budget_keeps_plot_side_characters():
    p, n = _named_project()
    hero = p.episode(n).plot.characters[0]
    p.characters += [GUARD.model_copy(), CLERK.model_copy(), ALWAYS.model_copy()]
    p.states += [CharacterState(character_id="guard", location="성문"), CharacterState(character_id="clerk", location="서고")]
    p.episode(n).plot.characters = [hero, "guard", "clerk"]

    def cast(q):
        t = context.Trace()
        prompts.episode_parts(q, n, trace=t)
        text = prompts.episode_prompt(q, n)
        return text, t

    text0, t0 = cast(p)
    assert "딱딱한 존댓말" in text0 and "느릿한 말" in text0 and "걸걸한 반말" in text0
    lo, hi = context.budget_range("cast")
    _set(p, budgets={"cast": lo})
    text1, t1 = cast(p)
    assert "딱딱한 존댓말" in text1 and "느릿한 말" in text1  # 플롯에 적힌 조연 · 단역은 낮춰도 빠지지 않는다
    assert "걸걸한 반말" not in text1  # 이름이 나온 인물만 작가 예산을 그대로 따른다
    assert any(x == "마르타 부인" and why == context.DROP_BUDGET for x, why in t1.dropped["named"])
    assert "cast" not in t1.dropped

    # 기본 예산에 들지 않는 큰 단역은 예산을 높이면 들어간다 (높이면 플롯 조연 · 단역과 이름이 나온 인물 둘 다 넓어진다)
    p.settings.budgets = []
    p.characters = [c.model_copy(update={"speech_style": "느릿한 말. " + "나" * 9_000}) if c.id == "clerk" else c for c in p.characters]
    text2, t2 = cast(p)
    assert "느릿한 말" not in text2 and any(x == "서기 한스" for x, _ in t2.dropped["cast"])
    _set(p, budgets={"cast": hi})
    text3, _ = cast(p)
    assert "딱딱한 존댓말" in text3 and "느릿한 말" in text3 and "걸걸한 반말" in text3


# ---------- 보기 기록(trace) ----------

def test_trace_none_changes_nothing():
    for p in (_short(), _project()):
        n = _next(p)
        assert prompts.join_parts(prompts.episode_parts(p, n, trace=context.Trace())) == prompts.episode_prompt(p, n)


def test_trace_forgets_off_blocks():
    p, n = _named_project()
    _set(p, off=["facts", "relations", "named", "foreshadows"])
    t = context.Trace()
    parts = prompts.episode_parts(p, n, trace=t)
    on = {x.id for x in parts}
    for bid in ("facts", "relations", "named", "foreshadows"):
        assert bid not in t.items and bid not in t.dropped and bid not in on


def test_trace_off_characters_are_not_cast_items():
    p, n = _named_project()
    hero = p.episode(n).plot.characters[0]
    p.characters.append(GUARD.model_copy(update={"context": "off"}))
    p.episode(n).plot.characters = [hero, "guard"]
    t = context.Trace()
    prompts.episode_parts(p, n, trace=t)
    names = [x for x, _ in t.items["cast"]]
    assert "문지기 오토" not in names and names


def test_trace_states_without_plot_cast_are_always():
    p = _project()
    n = _next(p)
    p.episode(n).plot.characters = []
    t = context.Trace()
    prompts.episode_parts(p, n, trace=t)
    assert t.items["states"] and all(why == context.REASON_ALWAYS for _, why in t.items["states"])


def test_trace_unrelated_old_facts_are_one_line():
    p = _project()
    n = _next(p)
    main = [c.name for c in p.characters if c.tier == "main"][0]
    p.facts = [f"아무 관계 없는 옛 일 {i}" for i in range(60)] + [f"{main}이 {i}번째로 본 일 " + "라" * 50 for i in range(80)]
    _set(p, budgets={"facts": context.budget_range("facts")[0]})
    t = context.Trace()
    prompts.episode_parts(p, n, trace=t)
    unrelated = [x for x, why in t.dropped["facts"] if why == context.DROP_UNRELATED]
    assert unrelated == ["옛 사실 60개"]
    assert any(why == context.DROP_BUDGET and main in x for x, why in t.dropped["facts"])


def test_foreshadow_reasons_follow_rank():
    assert context.FORESHADOW_REASONS == {0: context.REASON_ARC, 1: context.REASON_ARC, 2: context.REASON_ARC,
                                          3: context.REASON_SCOPE, 4: context.REASON_SCOPE,
                                          5: context.REASON_RECENT, 6: context.REASON_RECENT}
    p = _project()
    n = _next(p)
    t = context.Trace()
    fs, _ = prompts.relevant_foreshadows(p, n, trace=t)
    for f in fs:
        name = prompts._fs_name(f)
        assert (name, context.foreshadow_reason(p, f, n)) in t.items["foreshadows"]


def test_trace_budget_cuts_name_dropped_lines():
    from canon import pairlog, timeline
    from canon.maps import prompt as mapprompt
    p = _project()
    n = _next(p)
    t = context.Trace()
    lines = [f"- 아주 긴 줄 {i} " + "가" * 80 for i in range(5)]
    context.trace_drops(t, "pairs", lines[:2])
    assert t.dropped["pairs"][0] == (context.trace_label(lines[0]), context.DROP_BUDGET)
    assert len(t.dropped["pairs"][0][0]) <= context.TRACE_LABEL and not t.dropped["pairs"][0][0].startswith("- ")
    context.trace_drops(None, "pairs", lines)  # trace 가 없으면 아무 일도 없다
    # 함께 쓰는 함수는 trace 를 받아도 같은 글을 낸다
    assert timeline.episode_block(p, n, 100, trace=context.Trace()) == timeline.episode_block(p, n, 100)
    assert mapprompt.travel_block(p, n, 100, trace=context.Trace()) == mapprompt.travel_block(p, n, 100)
    assert mapprompt.spot_block(p, n, 100, trace=context.Trace()) == mapprompt.spot_block(p, n, 100)
    assert prompts.stage_block(p, n, 100, trace=context.Trace()) == prompts.stage_block(p, n, 100)
    ids = {c.id for c in p.characters}
    assert pairlog.write_block(p, n, ids, 10, context.Trace()) == pairlog.write_block(p, n, ids, 10)


def test_trace_story_arc_folding():
    from tests.test_named_cast import _project as named
    p, a = named()
    n = a.end_ep
    t = context.Trace()
    past, cur = prompts.story_parts(p, n, arc_budget=100, trace=t)
    assert (past, cur) == prompts.story_parts(p, n, arc_budget=100)
    assert cur != prompts.story_parts(p, n)[1]
    assert t.dropped["story_arc"][0] == ("1화 1화 제목 (첫 문장만)", context.DROP_BUDGET)
    assert len(t.dropped["story_arc"]) == 3  # 최근 8화는 줄이지 않는다


def test_priority_line_drops_off_blocks():
    p = _project()
    n = _next(p)
    p.episode(n).plot.pov = p.characters[0].id
    assert "서술 시점" in prompts.priority_line(p, n, False)
    _set(p, off=["pov"])
    assert prompts.priority_line(p, n, False) == ""  # 차례를 정할 블록이 플롯 하나만 남는다
    assert "# 이번 화 서술 시점" not in prompts.episode_prompt(p, n)


def test_trace_deadline_and_stage_cuts():
    from canon import timeline
    from canon.schema import Deadline
    from tests.test_stage_prompt import _project as staged, _scene
    from tests.test_timeline import _play, _short as short8
    p = _play(short8(8), 1, 1)
    for k in range(80):
        timeline.upsert(p, Deadline(id="", what=f"먼 약속 {k} " + "가" * 20, day=10 + k))
    t = context.Trace()
    rows, cut = timeline.deadline_lines(p, 2, trace=t)
    assert (rows, cut) == timeline.deadline_lines(p, 2)
    assert len(t.dropped["time"]) == cut and all(why == context.DROP_BUDGET for _, why in t.dropped["time"])
    assert all(len(x) <= context.TRACE_LABEL and x.startswith("먼 약속") for x, _ in t.dropped["time"])
    t = context.Trace()
    timeline.deadline_lines(p, 2, trace=t, block="board")
    assert set(t.dropped) == {"board"}

    q = staged(scenes=[_scene("s2", event=1), _scene("s1", event=0)])
    full = prompts.stage_block(q, 1)
    t = context.Trace()
    one = prompts.stage_block(q, 1, budget=len(full) // 2, trace=t)
    assert one == prompts.stage_block(q, 1, budget=len(full) // 2)
    assert len(t.dropped["stage"]) == 1 and t.dropped["stage"][0][1] == context.DROP_BUDGET


def test_states_block_is_locked_because_rules_point_at_it():
    """상태창 줄 · 스토리보드 · 옷차림 규칙이 '[인물 현재 상태]'를 가리키므로 끌 수 없다 (예산은 바꿀 수 있다)"""
    p = _project()
    n = _next(p)
    before = prompts.episode_prompt(p, n)
    _set(p, off=["states"])
    assert prompts.block_on(p, "states") and not prompts.toggleable(prompts.BLOCK_BY_ID["states"])
    assert prompts.episode_prompt(p, n) == before and "# 인물 현재 상태" in before
    assert "states" in context.WRITE_KEYS and prompts.BLOCK_BY_ID["states"].keys == ("states",)


def test_cast_budget_drop_is_not_also_a_cast_item():
    """예산으로 뺀 플롯 조연 · 단역은 'cast' 블록의 뺀 항목에만 있고 넣은 항목에는 없다 (한 사람은 한 목록에만)"""
    p, n = _named_project()
    hero = p.episode(n).plot.characters[0]
    big = CLERK.model_copy(update={"speech_style": "느릿한 말. " + "나" * 9_000})  # 플롯 조연은 max(작가, 기본) 예산을 쓰므로 기본 8000자를 넘긴다
    p.characters += [GUARD.model_copy(), big, ALWAYS.model_copy()]
    p.episode(n).plot.characters = [hero, "guard", "clerk"]
    lo, _ = context.budget_range("cast")
    _set(p, budgets={"cast": lo})
    t = context.Trace()
    text = prompts.join_parts(prompts.episode_parts(p, n, trace=t))
    assert "느릿한 말" not in text and "딱딱한 존댓말" in text
    kept = [x for x, _ in t.items["cast"]]
    gone = [x for x, _ in t.dropped["cast"]]
    assert "서기 한스" in gone and "서기 한스" not in kept
    assert "문지기 오토" in kept and not set(kept) & set(gone)


def test_trace_secrets_are_the_printed_ones():
    """'고른 비밀' 항목은 요청의 관계 블록에 실제로 찍힌 비밀만: 상태 예산으로 인물을 뺀 뒤, 주인과 모르는 인물이 함께 있을 때"""
    from canon.schema import Secret
    p, n = _named_project()
    hero = p.episode(n).plot.characters[0]
    p.characters += [GUARD.model_copy(), CLERK.model_copy()]
    p.secrets = [Secret(id="s1", owner=hero, content="왕의 인장을 숨겼다", hidden_from=["smith"]),
                 Secret(id="s2", owner=hero, content="문지기에게 빚이 있다", hidden_from=["guard"]),  # guard 는 이번 화 인물이 아니다
                 Secret(id="s3", owner="clerk", content="서기는 첩자다", hidden_from=[hero])]  # 주인이 이번 화 인물이 아니다
    t = context.Trace()
    text = prompts.join_parts(prompts.episode_parts(p, n, trace=t))
    rel = text.split("# 관계 현재 상태")[1].split("\n\n#")[0]
    printed = [x for x in ("왕의 인장을 숨겼다", "문지기에게 빚이 있다", "서기는 첩자다") if x in rel]
    listed = [x for x, why in t.items.get("relations", []) if why == context.REASON_SECRET]
    assert printed == ["왕의 인장을 숨겼다"] and listed == printed
    assert all(x not in printed for x, _ in t.dropped.get("relations", []))

    # 상태 예산으로 대장장이 상태를 빼면 그 비밀도 요청에서 빠진다. 비밀은 예산 안에서 골랐어도 항목에 남지 않는다
    smith = p.state_of("smith")
    smith.location = "북문 대장간 " + "쇠" * 2_000
    lo, _ = context.budget_range("states")
    _set(p, budgets={"states": lo})
    assert context.pick_secrets(p, {hero, "smith"}, "", context.budget(p, "secrets"))[1] == 0
    t2 = context.Trace()
    text2 = prompts.join_parts(prompts.episode_parts(p, n, trace=t2))
    rel2 = text2.split("# 관계 현재 상태")[1].split("\n\n#")[0]
    assert any(x == "마르타 부인" for x, _ in t2.dropped["states"])
    assert "왕의 인장을 숨겼다" not in rel2
    assert all("왕의 인장을 숨겼다" != x for v in (t2.items, t2.dropped) for x, _ in v.get("relations", []))


def test_structure_title_follows_the_form():
    assert prompts.block_title(_project(), "structure") == "현재 부와 아크"
    assert prompts.block_title(_short(), "structure") == "현재 구간"
    assert prompts.block_title(_project(), "facts") == "확정된 사실"
