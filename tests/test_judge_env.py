"""두 걸음 검수의 판단기를 환경 변수(CANON_JUDGE · _MODEL · _URL)로 정한다."""
from canon import judge, research
from canon.research import Backend


def test_env_picks_judge_when_screen_chose_none(monkeypatch):
    for k in ("CANON_JUDGE", "CANON_JUDGE_MODEL", "CANON_JUDGE_URL"):
        monkeypatch.delenv(k, raising=False)
    assert research.judge_backend(None, Backend(provider="mock")) == Backend(provider="mock")
    assert research.judge_backend(None, Backend(provider="gemini")) == Backend(provider="local")
    monkeypatch.setenv("CANON_JUDGE", "mock")
    assert research.judge_backend(None, Backend(provider="gemini")) == Backend(provider="mock")
    assert isinstance(judge.get_judge(), judge.MockJudge)


def test_env_fills_empty_local_model_and_url(monkeypatch):
    monkeypatch.delenv("CANON_JUDGE", raising=False)
    monkeypatch.setenv("CANON_JUDGE_MODEL", "gemma")
    monkeypatch.setenv("CANON_JUDGE_URL", "http://judge:8001/v1")
    got = research.judge_backend(None, Backend(provider="gemini"))
    assert (got.provider, got.model, got.url) == ("local", "gemma", "http://judge:8001/v1")
    # 화면에서 고른 값은 그대로 둔다
    mine = Backend(provider="local", model="qwen", url="")
    assert research.judge_backend(mine, Backend()) == Backend(provider="local", model="qwen", url="http://judge:8001/v1")
    assert research.judge_backend(Backend(provider="mock"), Backend()) == Backend(provider="mock")
    j = judge.get_judge()
    assert isinstance(j, judge.LocalJudge)
