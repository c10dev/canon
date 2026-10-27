"""상태창 넣기 시험(canon/stattrial.py) 테스트 (mock LLM): 시험할 화 고르기, 사본 되돌리기, LLM 없는 채점, 비용 추정, 실행 기록."""
import os
import tempfile

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())  # store 를 먼저 불러와도 저장소의 projects/ 를 쓰지 않게

from canon import pipeline, statwin, stattrial  # noqa: E402
from canon.mock import MockLLM  # noqa: E402
from canon.schema import StatValue  # noqa: E402

from .test_statwin import _play  # noqa: E402
from .test_storylines import _short  # noqa: E402

LLM = MockLLM()


def _trial():
    p = _short(8)
    statwin.set_stats(p, "hero", [StatValue(name="레벨", value="4"), StatValue(name="골드", value="1,200골드"),
                                  StatValue(name="스킬", value="화염구 Lv3, 은신")])
    return _play(p, 1, 3)  # mock 상태 변경안은 화마다 레벨 +1


def test_candidates_and_changes():
    p = _trial()
    cands = stattrial.candidates(p)
    assert [c["episode"] for c in cands] == [1, 2, 3] and all(c["changed"] for c in cands)
    assert stattrial.changes(p, 2) == {("hero", "레벨"): ("5", "6")}
    assert stattrial.default_pick(cands, 2) == [1, 2]
    q = stattrial.before(p, 3)
    assert {s.name: s.value for s in q.state_of("hero").stats}["레벨"] == "6" and q.episode(3).status != "finalized"
    assert {s.name: s.value for s in p.state_of("hero").stats}["레벨"] == "7"  # 작품은 그대로


def test_score_without_llm():
    p = _trial()
    q, ref = stattrial.before(p, 2), stattrial.changes(p, 2)
    text = """서윤은 숨을 골랐다.

【 상태창 】
이름: 서윤
레벨: 6
골드: 1200 골드
스킬: 은신, 화염구 Lv3
경지: 일류

레벨이 올랐다는 알림이 떴다."""
    s = stattrial.score(q, 2, text, ref)
    assert (s["shown"], s["wrong_unchanged"], s["wrong_changed"]) == (3, 0, 0)  # 레벨 6 은 바뀐 값, 골드 · 스킬은 그대로
    assert s["invented"] == ["경지"] and s["windows"] == 1 and s["unwanted_windows"] == 1 and not s["wants"]
    bad = stattrial.score(q, 2, "[ 상태창 ]\n▸ 레벨 ┃ 9\n▸ 골드 ┃ 900골드", ref)
    assert (bad["wrong_unchanged"], bad["wrong_changed"]) == (1, 1) and len(bad["samples"]) == 2
    assert stattrial.score(q, 2, "레벨이 올랐다. 골드를 잃었다.", ref)["shown"] == 0  # 문장 속 낱말은 값으로 읽지 않는다


def test_estimate_and_run_record(tmp_path, monkeypatch):
    from canon import research, store

    p = _trial()
    est = stattrial.estimate(p, [2, 3], repeats=2)
    assert est["writes"] == 12 and [r["condition"] for r in est["rows"]] == ["none", "json", "lines"]
    assert all(r["input_tokens"] > 0 and r["output_tokens"] > 0 for r in est["rows"]) and est["priced"]
    store.save("st", p)
    res = stattrial.run("st", store.load("st"), LLM, [2], repeats=1)
    assert len(res["drafts"]) == 3 and [s["condition"] for s in res["summary"]] == ["none", "json", "lines"]
    assert research.history("st")[0]["kind"] == "statwin"
    c = research.load_compare("st", 2)
    assert c["kind"] == "statwin" and len(c["drafts"]) == 3
    assert store.load("st").model_dump() == p.model_dump()  # 작품은 바꾸지 않는다
    for bad in ([9], [2] * 0):
        try:
            stattrial.run("st", p, LLM, bad or [], repeats=1)
            raise AssertionError("막혀야 한다")
        except ValueError:
            pass


def test_conditions_change_only_the_write_prompt():
    from canon import abilities, prompts
    from canon.schema import Ability, AbilityGrade

    p = _trial()
    abilities.upsert(p, Ability(id="", name="화염구", stat="스킬", effect="불덩이", grades=[AbilityGrade(grade="Lv3", effect="반경 3m")]))
    q = stattrial.before(p, 3)
    w = {c: prompts.episode_prompt(stattrial.variant(q, c), 3) for c in stattrial.CONDITIONS}
    assert '"레벨"' in w["json"] and "상태창은 아래 서식으로" in w["json"]  # 지금 방식: JSON 안의 수치와 서식 예시
    assert '"레벨"' not in w["none"] and "상태창" not in w["none"]
    assert '"레벨"' not in w["lines"] and "상태창 수치 (2화가 끝났을 때, 이번 화 인물만):\n서윤\n- 레벨: 6" in w["lines"]
    assert "- 화염구 [스킬 · 서윤 Lv3]: 효과 불덩이 / Lv3 반경 3m" in w["lines"] and "꼭 보일 필요는 없습니다" in w["lines"]
    assert "아래 서식으로" not in w["lines"]  # 플롯에 상태창 장면이 없으면 서식 예시를 붙이지 않는다
    q.episode(3).plot.summary += " 서윤의 상태창이 처음으로 떠오른다."
    assert "아래 서식으로" in prompts.episode_prompt(stattrial.variant(q, "lines"), 3)
    for c in ("none", "lines"):  # 검수 · 상태 정리는 어느 방식이든 수치를 모두 본다
        v = stattrial.variant(q, c)
        assert '"레벨"' in prompts.state_prompt(v, 2) and '"레벨"' in prompts.check_prompt(v, 2)


def test_lines_budget_counts_cut(monkeypatch):
    from canon import abilities, context
    from canon.schema import Ability

    p = _trial()
    for i in range(6):
        abilities.upsert(p, Ability(id="", name=f"기술{i}", stat="스킬", effect="가" * 50, context="always"))
    monkeypatch.setitem(context.BUDGET, "stat_lines", 200)
    block = statwin.lines_block(stattrial.variant(p, "lines"), 4)
    assert block.count("- 기술") == 3 and "스킬 · 특성 3개는 분량 때문에 뺐습니다" in block


def test_web(tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    from canon import store

    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    importlib.reload(store)
    store.save("st", _trial())
    from canon import web
    importlib.reload(web)
    c = TestClient(web.app)
    v = c.get("/api/projects/st/stattrial").json()
    assert [x["key"] for x in v["conditions"]] == ["none", "json", "lines"] and [x["episode"] for x in v["candidates"]] == [1, 2, 3]
    est = c.post("/api/projects/st/stattrial/estimate", json={"episodes": [2], "repeats": 1}).json()
    assert est["writes"] == 3
    assert c.post("/api/projects/st/stattrial/estimate", json={"episodes": [9]}).status_code == 400
    assert c.post("/api/projects/st/jobs", json={"kind": "stattrial", "episodes": [9]}).status_code == 400
    assert c.post("/api/projects/st/jobs", json={"kind": "stattrial", "episodes": [2], "conditions": ["xml"]}).status_code == 400
