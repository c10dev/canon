"""화별 서술 시점 테스트 (mock LLM): 화 · 구간 · 아크 시점, 전환 안내, 검수 · 기획 규칙. 실행: python -m pytest tests"""
from canon import cli, prompts
from canon.schema import ConsistencyIssue, Project

from .test_storylines import _short
from .test_web import client  # noqa: F401  (pytest fixture)


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
    assert "본문이 있는 화는 플롯을 바꾸지 않아요: [1]화" in out and "시점 적음: [2, 3]화" in out
    q = store.load("t")
    assert (q.episode(2).plot.pov, q.episode(2).plot.pov_mode) == ("ally", "1인칭") and q.episode(1).plot.pov == ""
    cli.main(["pov", "t", "3", "--clear"])
    assert store.load("t").episode(3).plot.pov == ""
    cli.main(["pov", "t", "4"])
    assert "시점 바뀜" not in capsys.readouterr().out.split("4화")[-1]


VOICE = "서술 어미는 ~했어요, ~인 걸까요?"


def test_voice_only_on_pov_episodes():
    p = _short()
    p.characters[1].narration_voice = VOICE  # 도현(ally)
    _pov(p, range(6, 13))
    assert VOICE in prompts.pov_block(p, 6) and VOICE in prompts.pov_block(p, 7)
    assert prompts.pov_block(p, 5) == ""  # 서윤(기본) 시점 화에는 들어가지 않는다
    assert VOICE not in prompts.static_context(p)  # 앞쪽 캐시 블록과 다른 화로 옮아오지 않는다
    assert VOICE in prompts.check_prompt(p, 6) and "서술 말투가 정해진 화" in prompts.check_prompt(p, 6)


def test_voice_follows_default_and_plan():
    p = _short()
    p.style.narration_pov = "1인칭 주인공"
    p.characters[0].role, p.characters[0].narration_voice = "주인공", VOICE  # 서윤
    assert prompts.pov_character(p, 1).id == "hero" and VOICE in prompts.pov_block(p, 1)
    p.arc[2].pov = "도현 1인칭"
    n = p.arc[2].start_ep
    assert prompts.pov_character(p, n).id == "ally" and VOICE not in prompts.pov_block(p, n)
    p.arc[2].pov = "3인칭 전지"
    assert prompts.pov_character(p, n) is None


def test_voice_skips_ending_warnings(monkeypatch):
    from canon import metrics, pipeline
    p = _short()
    p.episodes[5].text = "바람이 차가웠어요."
    monkeypatch.setattr(metrics, "drift", lambda b, c: ["과거형 서술 비율: 기준 0.9 → 0.1 (-0.80)", "문체 거리: 2.0", "대사 비율: x"])
    monkeypatch.setattr(metrics, "marker_warnings", lambda m, t: ["'것이었다' 0회"])
    assert len(pipeline.style_drift(p, 6)[1]) == 4
    p.characters[1].narration_voice = VOICE
    _pov(p, [6])
    assert pipeline.style_drift(p, 6)[1] == ["대사 비율: x"]


def test_suggest_voice_and_setup_strip(monkeypatch):
    from canon import pipeline
    from canon.mock import MockLLM
    p = _short()
    s = pipeline.suggest_voice(MockLLM(), p, "ally")
    assert "예:" in s.voice and s.note
    assert "도현" in prompts.voice_prompt(p, "ally")
    assert all(c.narration_voice == "" for c in pipeline.suggest_setup(MockLLM(), p).characters)


def test_cli_voice(tmp_path, monkeypatch, capsys):
    from canon import store
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setenv("CANON_LLM", "mock")
    store.save("t", _short())
    cli.main(["voice", "t", "도현", "--set", VOICE])
    assert store.load("t").characters[1].narration_voice == VOICE
    cli.main(["voice", "t", "ally", "-y"])
    assert "예:" in store.load("t").characters[1].narration_voice


def test_web_voice(client):
    from .test_plot_chat import _project
    _project(client)
    s = client.post("/api/projects/lh/characters/ally/voice").json()
    assert "예:" in s["voice"]
    assert client.post("/api/projects/lh/characters/nobody/voice").status_code == 400


def test_half_set_episode_pov_inherits_the_rest_and_first_name_wins():
    p = _short()
    names = {c.id: c.name for c in p.characters}
    p.arc[2].pov = f"{names['ally']} 3인칭 제한, {names['hero']} 등장"
    n = p.arc[2].start_ep
    assert prompts.char_in_text(p, p.arc[2].pov).id == "ally"  # 글에 먼저 나온 인물
    _pov(p, [n], "", "1인칭")  # 서술 방식만 적은 화: 시점 인물은 구간에서
    assert prompts.pov_character(p, n).id == "ally" and "시점 인물" in prompts.pov_of(p, n)[1]
    _pov(p, [n], "hero", "")  # 시점 인물만 적은 화: 서술 방식은 구간에서
    assert "서술 3인칭 제한" in prompts.pov_of(p, n)[1]
