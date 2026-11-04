"""서술 다듬기 (다시 생성의 방식 polish, mock LLM): 프롬프트, 대사 · 효과음 줄 보존 검사, 새 판, 명령줄. 실행: python -m pytest tests"""
import pytest

from canon import pipeline, prompts
from canon.schema import RewriteRequest

from .test_passage import TEXT, _ep, _written
from .test_web import _wait, client  # noqa: F401  (pytest fixture)

JOB = "/api/projects/lh/jobs"


def test_prompt_puts_static_first_text_then_rules(client):
    from canon import store

    _written(client)
    p = store.load("lh")
    out = pipeline.rewrite_prompt(p, 1, RewriteRequest(mode="polish"))
    assert out.startswith(prompts.static_context(p))  # 작품 고정 블록이 앞 (쓰기와 같은 캐시)
    assert "\n# 다듬을 본문\n" + TEXT in out
    assert out.index(TEXT) < out.index("# 할 일")
    assert "한 글자도 바꾸지 않고" in out
    assert "열에 여섯쯤만 '~다.'로" in out and "각각 화에 셋까지" in out  # 문장 끝 몫은 쓰기와 같은 글 + 상한


def test_prompt_drops_ending_rule_for_narration_voice(client):
    from canon import store

    _written(client)
    p = store.load("lh")
    hero = p.characters[0]
    hero.narration_voice = "해요체로 서술한다"
    p.episode(1).plot.pov = hero.id
    out = prompts.polish_prompt(p, 1, TEXT)
    assert "'~다.'로 맺고" not in out and "5." not in out.split("# 할 일", 1)[1]


def test_clean_rewrite_keeps_only_mode_for_polish():
    req = pipeline.clean_rewrite(RewriteRequest(feedback="x", presets=["slower"], materials=["style"], mode="polish", keep=["y"]))
    assert req == RewriteRequest(mode="polish")


def test_polish_problem():
    old = "물이 식었다.\n\n“가자.”\n\n─쿠르르…\n\n나는 걸었다."
    assert pipeline.polish_problem(old, old.replace("나는 걸었다.", "걸음을 옮긴다.")) == ""
    assert "대사 · 효과음 줄" in pipeline.polish_problem(old, old.replace("“가자.”", "“가자고.”"))
    assert "대사 · 효과음 줄" in pipeline.polish_problem(old, old.replace("─쿠르르…\n\n", ""))
    assert "글자 수" in pipeline.polish_problem(old, old + "\n\n" + "덧붙인 서술이 길게 이어졌다. " * 4)


class _Changes:
    """대사를 바꿔 내는 가짜 LLM: 다듬기가 다시 부르고 끝내 멈추는지 본다."""
    calls = 0

    def text(self, system, prompt):
        _Changes.calls += 1
        return TEXT.replace("됐어, 내가 할게.", "내가 할게.")


def test_polish_retries_then_stops_when_dialogue_changes(client):
    from canon import store

    _written(client)
    p = store.load("lh")
    _Changes.calls = 0
    with pytest.raises(ValueError, match="서술 다듬기를 쓰지 않았어요"):
        pipeline.polish_episode(_Changes(), p, 1)
    assert _Changes.calls == pipeline.POLISH_TRIES


def test_polish_job_makes_candidate(client):
    _written(client)
    shown = client.post("/api/projects/lh/episodes/1/rewrite/prompt", json={"mode": "polish", "feedback": "무시"}).json()
    assert "# 다듬을 본문" in shown["prompt"] and "무시" not in shown["prompt"]
    j = _wait(client, client.post(JOB, json={"kind": "write", "ep": 1, "rewrite": {"mode": "polish", "feedback": "무시"}}).json()["id"])
    assert j["status"] == "done", j.get("error")
    assert j["label"] == "1화 서술 다듬기"
    e = _ep(client.get("/api/projects/lh").json())
    assert e["text"] == TEXT  # 다듬은 판도 본문을 덮지 않고 고르기를 기다린다
    c = e["candidate"]
    assert c["request"]["mode"] == "polish" and c["request"]["feedback"] == ""
    assert pipeline.fixed_lines(c["text"]) == pipeline.fixed_lines(TEXT) and c["text"] != TEXT


def test_cli_polish(tmp_path, monkeypatch):
    import contextlib
    import io

    from canon import store
    from canon.cli import main

    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["new", "cl", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
        main(["arc", "cl", "-y"])
        main(["plot", "cl"])
        main(["confirm", "cl", "all"])
        main(["write", "cl", "1"])
        before = store.load("cl").episode(1).text
        main(["rewrite", "cl", "1", "--polish", "-y"])
    e = store.load("cl").episode(1)
    assert "서술만 다듬기" in out.getvalue()
    assert e.made_by.mode == "polish" and e.text != before
    assert pipeline.fixed_lines(e.text) == pipeline.fixed_lines(before)
