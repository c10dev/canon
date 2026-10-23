"""화별 서술 시점 테스트 (mock LLM): 화 · 구간 · 아크 시점, 전환 안내, 검수 · 기획 규칙. 실행: python -m pytest tests"""
from canon import cli, prompts
from canon.schema import ConsistencyIssue, Project

from .test_storylines import _short


def _pov(p: Project, nums, who="ally", mode="1인칭"):
    for e in p.episodes:
        if e.plot.number in nums:
            e.plot.pov, e.plot.pov_mode = who, mode


def test_old_project_has_no_pov_block():
    p = Project.model_validate({"arc": [{"name": "기", "start_ep": 1, "end_ep": 1, "goal": "g"}],
                                "episodes": [{"plot": {"number": 1, "act": "기", "title": "t", "summary": "s", "events": [],
                                                        "characters": [], "emotional_shift": "", "ending_hook": ""}}]})
    assert p.episodes[0].plot.pov == "" and p.arc[0].pov == ""
    assert prompts.pov_block(p, 1) == ""
    assert "서술 시점 (스타일" not in prompts.build_episode_context(p, 1)


def test_episode_pov_overrides_and_marks_switch():
    p = _short()
    p.style.narration_pov = "1인칭 주인공"
    _pov(p, range(6, 13))
    assert prompts.pov_block(p, 5) == ""  # 앞뒤 모두 기본이면 블록 없음
    six = prompts.pov_block(p, 6)
    assert "도현(ally)" in six and "'나'는 도현" in six and "시점이 바뀝니다" in six and "직전 5화: 작품 기본 시점(1인칭 주인공)" in six
    seven = prompts.pov_block(p, 7)
    assert "'나'는 도현" in seven and "시점이 바뀝니다" not in seven  # 같은 시점이 이어지면 전환 안내는 없다
    ctx = prompts.build_episode_context(p, 6)
    assert ctx.index("# 이번 화 플롯") < ctx.index("# 이번 화 서술 시점")  # 화마다 바뀌는 뒤쪽 블록
    assert prompts.static_context(p) in ctx  # 앞쪽 캐시 블록은 그대로
    assert "# 6화 서술 시점" in prompts.check_prompt(p, 6)


def test_back_to_default_is_announced():
    p = _short()
    _pov(p, [4])
    five = prompts.pov_block(p, 5)
    assert five.startswith("이번 화: 작품 기본 시점") and "직전 4화: 시점 인물 도현(ally)" in five


def test_act_and_arc_plan_fill_in():
    p = _short()
    p.arc[2].pov = "도현 1인칭"
    n = p.arc[2].start_ep
    assert prompts.pov_of(p, n) == ("도현 1인칭", "도현 1인칭")
    assert "시점이 바뀝니다" in prompts.pov_block(p, n)
    _pov(p, [n], "hero", "3인칭 전지")  # 화에 적은 시점이 구간보다 우선
    block = prompts.pov_block(p, n)
    assert "서윤(hero)" in block and "보고 듣고 아는 것만" not in block


def test_rules_and_issue_type():
    p = _short()
    p.style.narration_pov = "3인칭 제한"
    assert "pov 에는 이 화의 시점 인물 id" in prompts.plot_rules(p) and "'3인칭 제한'" in prompts.plot_rules(p)
    assert "pov 에는 그 구간의" in prompts.arc_prompt(p)
    assert "- 시점:" in prompts.check_prompt(p, 1)
    assert ConsistencyIssue(type="시점", description="x", source_quote="a", current_quote="b").type == "시점"


def test_cli_pov(tmp_path, monkeypatch, capsys):
    from canon import store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _short()
    p.episodes[0].text, p.episodes[0].status = "본문", "written"
    store.save("t", p)
    cli.main(["pov", "t", "1-3", "도현", "--mode", "1인칭"])
    out = capsys.readouterr().out
    assert "본문이 있는 화는 플롯을 바꾸지 않습니다: [1]화" in out and "시점 적음: [2, 3]화" in out
    q = store.load("t")
    assert (q.episode(2).plot.pov, q.episode(2).plot.pov_mode) == ("ally", "1인칭") and q.episode(1).plot.pov == ""
    cli.main(["pov", "t", "3", "--clear"])
    assert store.load("t").episode(3).plot.pov == ""
    cli.main(["pov", "t", "4"])
    assert "시점 바뀜" not in capsys.readouterr().out.split("4화")[-1]
