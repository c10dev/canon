"""Gemini 명시 캐시: 플롯 대화 단계(chat)만 겹치는 앞부분을 caches.create 로 캐시하고, 오류는 일반 호출로 넘어간다.
google-genai 클라이언트는 가짜로 바꾼다 (네트워크 없음)."""
from types import SimpleNamespace

import pytest

from canon import claude, llm, settings, usage
from canon.llm import GeminiLLM


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("CANON_USAGE", str(tmp_path / "usage.jsonl"))
    monkeypatch.delenv("CANON_GEMINI_CACHE", raising=False)
    llm.gemini_cache_reset()
    claude._SEEN.clear()
    yield
    llm.gemini_cache_reset()
    claude._SEEN.clear()


class Err(Exception):
    def __init__(self, code: int, status: str = ""):
        super().__init__(f"{code} {status}")
        self.code, self.status = code, status


def _fake(stage: str = "chat", vertex: bool = False):
    g = object.__new__(GeminiLLM)
    g.model, g.effort, g.stage, g.vertex = "gemini-4-argon", "", stage, vertex
    sent, made = [], []
    g.fail_create = None
    g.fail_cached = None

    def generate(model, contents, config):
        if config.cached_content and g.fail_cached is not None:
            raise g.fail_cached
        sent.append((contents, config))
        cached = 9000 if config.cached_content else 0
        u = SimpleNamespace(prompt_token_count=10000, candidates_token_count=5, thoughts_token_count=0,
                            cached_content_token_count=cached)
        return SimpleNamespace(text="답", usage_metadata=u, candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))])

    def create(model, config):
        if g.fail_create is not None:
            raise g.fail_create
        made.append((model, config))
        return SimpleNamespace(name=f"cachedContents/c{len(made)}", expire_time=None)

    g.client = SimpleNamespace(models=SimpleNamespace(generate_content=generate), caches=SimpleNamespace(create=create))
    return g, sent, made


PREFIX = "\n\n".join(f"고정 블록 {i} " + "가" * 2000 for i in range(10))  # 약 2만 자


def _step(i: int) -> str:
    return f"{PREFIX}\n\n이번 턴에 한 일 {i}\n\n요청"


def test_agent_steps_create_one_cache_and_send_only_the_rest():
    g, sent, made = _fake()
    assert g.text("시스템", _step(1)) == "답"
    assert not made and sent[-1][1].cached_content is None  # 첫 단계는 비교할 직전 요청이 없다
    assert g.text("시스템", _step(2)) == "답"
    assert len(made) == 1
    model, cfg = made[0]
    assert model == "gemini-4-argon" and cfg.ttl == f"{llm.GEMINI_CACHE_TTL}s"
    assert cfg.system_instruction == "시스템"
    assert cfg.contents[0].parts[0].text == PREFIX  # 겹치는 앞부분은 단락 경계에서 끊는다
    contents, config = sent[-1]
    assert config.cached_content == "cachedContents/c1"
    assert config.system_instruction is None  # 캐시와 함께 보내면 API 가 거절한다
    assert contents.startswith("이번 턴에 한 일 2") and "고정 블록" not in contents
    assert g.text("시스템", _step(3)) == "답"
    assert len(made) == 1 and sent[-1][1].cached_content == "cachedContents/c1"  # 같은 캐시를 다시 쓴다
    rows = usage.read()
    assert [r["cached"] for r in rows] == [0, 9000, 9000]  # 사용량은 평소대로 기록한다
    assert rows[-1]["in"] == 10000


def test_other_stages_and_setting_off_do_not_cache(monkeypatch):
    g, sent, made = _fake(stage="write")
    for i in range(3):
        g.text("시스템", _step(i))
    assert not made and all(c.cached_content is None for _, c in sent)
    monkeypatch.setenv("CANON_GEMINI_CACHE", "0")
    g, sent, made = _fake()
    for i in range(3):
        g.text("시스템", _step(i))
    assert not made


def test_setting_values(monkeypatch):
    assert settings.gemini_cache() == ("agent", "default")
    settings.config_path().write_text('{"gemini_cache": "off"}', encoding="utf-8")
    assert settings.gemini_cache() == ("off", "file")
    for v, want in (("0", "off"), ("off", "off"), ("false", "off"), ("1", "agent"), ("agent", "agent")):
        monkeypatch.setenv("CANON_GEMINI_CACHE", v)
        assert settings.gemini_cache() == (want, "env")


def test_short_prefix_is_not_cached():
    g, sent, made = _fake()
    g.text("시스템", "짧은 앞부분\n\n하나")
    g.text("시스템", "짧은 앞부분\n\n둘")
    assert not made


def test_create_error_falls_back_and_backs_off():
    g, sent, made = _fake()
    g.fail_create = Err(400, "INVALID_ARGUMENT")
    g.text("시스템", _step(1))
    assert g.text("시스템", _step(2)) == "답"
    assert sent[-1][1].cached_content is None and sent[-1][1].system_instruction == "시스템"
    g.fail_create = None
    g.text("시스템", _step(3))
    assert not made  # 한 번 실패한 모델은 GEMINI_CACHE_BACKOFF 동안 다시 만들지 않는다


def test_create_rate_limit_does_not_back_off():
    g, sent, made = _fake()
    g.fail_create = Err(429, "RESOURCE_EXHAUSTED")
    g.text("시스템", _step(1))
    g.text("시스템", _step(2))
    g.fail_create = None
    g.text("시스템", _step(3))
    assert len(made) == 1


def test_cached_call_error_falls_back_to_the_normal_call():
    g, sent, made = _fake()
    g.text("시스템", _step(1))
    g.text("시스템", _step(2))
    g.fail_cached = Err(400, "INVALID_ARGUMENT")
    assert g.text("시스템", _step(3)) == "답"
    contents, config = sent[-1]
    assert config.cached_content is None and contents.startswith(PREFIX)
    assert [r["ok"] for r in usage.read()] == [True, True, True]  # 넘어간 호출 하나만 기록한다


def test_expired_cache_404_is_forgotten_without_back_off():
    g, sent, made = _fake()
    g.text("시스템", _step(1))
    g.text("시스템", _step(2))
    g.fail_cached = Err(404, "NOT_FOUND")
    assert g.text("시스템", _step(3)) == "답"
    g.fail_cached = None
    g.text("시스템", _step(4))
    assert len(made) == 2 and sent[-1][1].cached_content == "cachedContents/c2"


def test_cached_call_rate_limit_is_left_to_the_retry_loop():
    g, sent, made = _fake()
    g.text("시스템", _step(1))
    g.text("시스템", _step(2))
    g.fail_cached = Err(429, "RESOURCE_EXHAUSTED")
    with pytest.raises(Err):
        g._once("시스템", _step(3))
    g.fail_cached = None
    g.text("시스템", _step(4))
    assert len(made) == 1 and sent[-1][1].cached_content == "cachedContents/c1"  # 캐시는 그대로 쓴다


def test_cache_near_expiry_is_not_used(monkeypatch):
    g, sent, made = _fake()
    g.text("시스템", _step(1))
    g.text("시스템", _step(2))
    now = llm.time.time()
    monkeypatch.setattr(llm.time, "time", lambda: now + llm.GEMINI_CACHE_TTL - llm.GEMINI_CACHE_MARGIN + 1)
    g.text("시스템", _step(3))
    assert len(made) == 2 and sent[-1][1].cached_content == "cachedContents/c2"


def test_different_system_prompt_does_not_share_a_cache():
    g, sent, made = _fake()
    g.text("시스템 A", _step(1))
    g.text("시스템 A", _step(2))
    g.text("시스템 B", _step(3))
    assert len(made) == 1 and sent[-1][1].cached_content is None


def test_vertex_uses_the_same_path():
    g, sent, made = _fake(vertex=True)
    g.text("시스템", _step(1))
    g.text("시스템", _step(2))
    assert len(made) == 1 and sent[-1][1].cached_content == "cachedContents/c1"
