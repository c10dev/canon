"""자동 집필의 서술 다듬기 (autorun.Policy.polish): 쓴 뒤 다듬은 판으로 바꾸고, 검수 · 상태 변경안은 다듬은 글을 본다.

    CANON_HOME=$(mktemp -d) python -m pytest -q tests/test_auto_polish.py
"""

from canon import autorun, pipeline, store

from .test_autorun import Policy, demo  # noqa: F401  (pytest fixture)


def test_polish_replaces_text_and_keeps_written_version(demo):
    run = autorun.start(demo, 1, False, Policy(polish=True), foreground=True)
    assert run.status == "done" and run.polish_due == []
    e = store.load(demo).episode(1)
    assert e.status == "finalized" and e.made_by is not None and e.made_by.mode == "polish"
    old = [v for v in e.versions if v.kind == "previous"]
    assert old and old[-1].text != e.text  # 쓴 판은 이전 판에 남는다
    assert pipeline.fixed_lines(old[-1].text) == pipeline.fixed_lines(e.text)  # 대사 줄은 그대로
    steps = [x.step for x in run.log]
    assert steps.index("write") < steps.index("polish") < steps.index("review")  # 쓰기 → 다듬기 → 검수
    assert any("서술 다듬기:" in x.message for x in run.log)


def test_polish_off_by_default(demo):
    assert autorun.Policy().polish is False
    autorun.start(demo, 1, False, Policy(), foreground=True)
    e = store.load(demo).episode(1)
    assert e.made_by is None and not e.versions


def test_polish_failure_keeps_written_text(demo, monkeypatch):
    def fail(llm, p, n, cut=None, sent=None):
        raise ValueError("대사 · 효과음 줄이 바뀌었어요")
    monkeypatch.setattr(pipeline, "polish_episode", fail)
    run = autorun.start(demo, 1, False, Policy(polish=True), foreground=True)
    assert run.status == "done" and run.polish_due == []
    e = store.load(demo).episode(1)
    assert e.made_by is None and e.status == "finalized"
    assert any(x.level == "warn" and "서술 다듬기를 건너뛰고" in x.message for x in run.log)


def test_author_written_episode_is_not_polished(demo):
    p = store.load(demo)
    e = p.episode(1)
    e.text, e.status = "작가가 직접 쓴 1화 본문이에요. " * 20, "written"
    store.save(demo, p)
    autorun.start(demo, 1, False, Policy(polish=True), foreground=True)
    e = store.load(demo).episode(1)
    assert e.made_by is None and e.text.startswith("작가가 직접 쓴")


def test_estimate_counts_polish(demo, monkeypatch):
    p = store.load(demo)
    monkeypatch.setenv("CANON_LLM", "gemini")
    off = autorun.estimate(p, 6, False, Policy())
    on = autorun.estimate(p, 6, False, Policy(polish=True))
    assert off["calls"]["revise"] == 0 and on["calls"]["revise"] == 6
    assert on["cost"] > off["cost"] and on["seconds_max"] > off["seconds_max"]
    assert autorun.estimate(p, 6, True, Policy(polish=True))["batch_rounds"] == 18  # 본문 6 + 다듬기 6 + 검수 · 상태 6
