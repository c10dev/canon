"""장편 프롬프트 크기 관리(canon/context.py)와 그것을 쓰는 프롬프트 테스트 (mock LLM). 실행: python -m pytest tests"""
from canon import context, dynamics, prompts, usage
from canon.schema import Character, Foreshadow, Secret, StoryElement
from tests.test_serial import _finish, _plan_arc, _serial


def test_blocks_split_by_headings():
    text = "머리말\n# 확정된 사실\n" + "가" * 500 + "\n[관계]\n" + "나" * 200 + "\n# 12화 본문 (검수 대상)\n" + "다" * 50
    rows = dict(context.blocks(text))
    assert rows["확정된 사실"] > 500 and rows["관계"] > 200 and "N화 본문" in rows
    assert sum(v for _, v in context.blocks(text)) == len(text)
    many = "".join(f"# 블록{i}\n" + "가" * (i + 1) + "\n" for i in range(20))
    rows = context.blocks(many, top=5)
    assert len(rows) == 5 and rows[-1][0] == "그 밖" and sum(v for _, v in rows) == len(many)


def test_foreshadow_rank_keeps_old_series_hooks():
    p = _serial()
    a = _plan_arc(p)
    big = Foreshadow(id="fs-big", description="세계의 비밀", planted_ep=1, scope="series")
    due = Foreshadow(id="fs-due", description="기한", planted_ep=2, due_ep=3)
    p.foreshadows = [big, due] + [Foreshadow(id=f"fs-{i}", description=f"작은 떡밥 {i}", planted_ep=i) for i in range(3, 60)]
    picked = context.rank_foreshadows(p, p.foreshadows, a.start_ep + 5, 10)
    ids = [f.id for f in picked]
    assert "fs-big" in ids and "fs-due" in ids and len(ids) == 10
    assert [f.planted_ep for f in picked] == sorted(f.planted_ep for f in picked)  # 심은 순서로 돌려준다
    assert "fs-59" in ids and "fs-3" not in ids  # 나머지는 최근 것


def test_pick_facts_prefers_side_characters_and_terms():
    p = _serial()
    p.characters.append(Character(id="smith", name="대장장이", role="조연", tier="support"))
    p.facts = ["대장장이는 왼손잡이다", "등대 열쇠는 둘이다", "아무 상관 없는 이야기"] + [f"최근 사실 {i}" for i in range(40)]
    facts, cut = context.pick_facts(p, {"hero", "smith"}, "", 10_000, ["열쇠"])
    assert "대장장이는 왼손잡이다" in facts and "등대 열쇠는 둘이다" in facts
    assert "아무 상관 없는 이야기" not in facts and "최근 사실 0" not in facts and "최근 사실 39" in facts
    assert cut == len(p.facts) - len(facts)
    small, _ = context.pick_facts(p, {"hero", "smith"}, "", 1, ["열쇠"])
    assert small == p.facts[-context.FACTS_RECENT:]  # 예산이 없어도 최근 것은 넣는다


def test_pick_secrets_budget_and_relevance():
    p = _serial()
    p.secrets = [Secret(id=f"s{i}", owner="hero", content=f"평범한 비밀 {i} " + "가" * 200, hidden_from=["ally"]) for i in range(30)]
    p.secrets.append(Secret(id="s-key", owner="hero", content="등대 지하에 오빠의 편지가 있다", hidden_from=["ally"], weight=0.2))
    p.secrets.append(Secret(id="s-open", owner="hero", content="모두 아는 비밀", hidden_from=[]))
    got, cut = context.pick_secrets(p, {"hero", "ally"}, "서윤은 등대 지하에서 편지를 찾았다", 1_500)
    ids = [s.id for s in got]
    assert "s-key" in ids and "s-open" not in ids and cut == 31 - len(got)
    assert sum(len(s.content) + 60 for s in got) <= 1_500
    text = dynamics.describe_relations(p, {"hero", "ally"}, secrets=got)
    assert text.count("숨긴 비밀") == len(got)
    assert "숨긴 비밀" not in dynamics.describe_relations(p, {"hero", "ally"}, secrets=[])
    assert dynamics.describe_relations(p, {"hero", "ally"}).count("숨긴 비밀") == 31  # 주지 않으면 예전처럼 전부


def test_unrecapped_arcs_fold_to_first_sentences():
    p = _serial(300)
    arcs = []
    for _ in range(4):
        a = _plan_arc(p, length=24)
        _finish(p, a)
        arcs.append(a)
    nxt = _plan_arc(p, length=12)
    text = prompts.story_so_far(p, nxt.start_ep + 3)
    assert "아크 요약 대기" in text  # 요약이 없는 아크는 화마다 첫 문장으로
    assert len(text) < context.BUDGET["story_past"] + context.BUDGET["story_arc"] + 2_000
    assert len(text) < sum(len(e.summary) for e in p.episodes) / 3


def test_serial_write_context_order_and_size():
    p = _serial(300)
    for _ in range(5):
        _finish(p, _plan_arc(p, length=24))
    a = _plan_arc(p, length=12)
    n = a.start_ep + 2
    for m in range(a.start_ep, n):
        e = p.episode(m)
        e.text, e.status, e.summary = "본문", "finalized", "요약"
    p.facts = [f"사실 {i} " + "가" * 80 for i in range(400)]
    ctx = prompts.build_episode_context(p, n)
    heads = ["# 현재 부와 아크", "# 지금까지의 줄거리 (끝난 부와 아크)", "# 이번 화 위치", "# 확정된 사실", "# 관계 현재 상태", "# 열린 복선",
             "# 지금까지의 줄거리 (이번 아크)", "# 직전 화 마지막 부분", "# 이번 화 플롯"]
    pos = [ctx.index(h) for h in heads]
    assert pos == sorted(pos)  # 아크 동안 그대로인 것이 앞, 화마다 바뀌는 것이 뒤
    assert ctx.index(prompts.static_context(p)) == 0
    assert "현재 아크 안 구간" not in ctx[:ctx.index("# 이번 화 위치")]  # 아크 안에서 바뀌는 줄이 접은 줄거리 앞을 깨지 않게
    facts = ctx[ctx.index("# 확정된 사실"):ctx.index("# 이번 화 등장 인물")]
    assert len(facts) < context.BUDGET["facts"] + 4_000 and "개 생략" in facts


def test_check_budget_mode_reads_recent_text_and_recalls_old_passages():
    p = _serial(300)
    a = _plan_arc(p, length=24)
    for m in range(a.start_ep, a.end_ep + 1):
        e = p.episode(m)
        e.text, e.status, e.summary = f"{m}화 평범한 하루였다. " * 40, "finalized", f"{m}화 요약"
    p.episode(3).text += "\n\n서윤은 은빛 나침반을 바다에 던졌다."
    n = 20
    p.episode(n).text = "서윤은 주머니에서 은빛 나침반을 꺼냈다."
    full = prompts.check_prompt(p, n, "full")
    budget = prompts.check_prompt(p, n)  # 장편 기본은 budget
    assert budget == prompts.check_prompt(p, n, "budget") and len(budget) < len(full)
    assert "## 17화 " in budget and "## 19화 " in budget and "## 16화 " not in budget  # 직전 3화만 원문
    assert "## 16화까지의 줄거리" in budget and "## 5화 " not in budget
    assert "옛 화에서 찾은 관련 단락" in budget and "은빛 나침반을 바다에 던졌다" in budget
    assert "### 3화" in budget


def test_planning_cast_skips_old_support_cast():
    p = _serial(300)
    p.characters.append(Character(id="old", name="옛 조연", role="조연", tier="support"))
    for _ in range(4):
        _finish(p, _plan_arc(p, length=24))
    nxt = p.planned_until() + 1
    ids = context.planning_cast(p, nxt)
    assert "hero" in ids and "old" not in ids
    p.episode(nxt - 2).plot.characters.append("old")
    assert "old" in context.planning_cast(p, nxt)


def test_impact_caps_open_foreshadows_in_serial():
    p = _serial(300)
    _finish(p, _plan_arc(p, length=24))
    p.foreshadows = [Foreshadow(id=f"fs-{i}", description=f"떡밥 {i}", planted_ep=1 + i % 20) for i in range(100)]
    el = StoryElement(id="el-1", name="저주", description="등대지기의 저주", since_ep=0)
    text = prompts.impact_prompt(p, el, {3})
    assert f"{100 - context.PLAN_FORESHADOW_CAP}개 생략" in text


def test_usage_record_keeps_prompt_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_USAGE", str(tmp_path / "u.jsonl"))

    class GeminiLLM:  # 기록은 백엔드를 클래스 이름으로 가린다
        model = "gemini-4-argon"

    usage.record(GeminiLLM(), {"prompt_tokens": 10}, prompt="# 확정된 사실\n" + "가" * 300 + "\n# 이번 화 플롯\n" + "나" * 50)
    row = usage.read()[-1]
    assert row["chars"] > 350 and row["blocks"][0][0] == "확정된 사실"
    usage.record(GeminiLLM(), {"prompt_tokens": 10})
    assert "blocks" not in usage.read()[-1]
