"""Superlinked 백엔드 (canon/superlinked.py). 실제 서버를 부르지 않고 요청 본문 · 다시 부르기 · 설정 연결만 본다."""
import urllib.error
from email.message import Message

import pytest
from pydantic import BaseModel

from canon import cancel, llm as canon_llm, settings, superlinked, usage
from canon.llm import BadKey, LocalLLM, MissingKey, make_llm
from canon.superlinked import SuperlinkedLLM


class Pick(BaseModel):
    pick: str


@pytest.fixture(autouse=True)
def _no_real_key(monkeypatch):
    monkeypatch.delenv("SUPERLINKED_API_KEY", raising=False)
    monkeypatch.delenv("CANON_SUPERLINKED_MODEL", raising=False)


def _http_error(code, headers=None):
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("https://x/v1/chat/completions", code, "err", msg, None)


def _wrapped(code, headers=None, text="로컬 서버 오류"):
    cause = _http_error(code, headers)
    try:
        raise RuntimeError(f"{text} {code}") from cause
    except RuntimeError as e:
        return e


def _fake(monkeypatch, sent, info=None, reply='{"pick": "사과"}'):
    def request(self, method, path, body=None, timeout=None):
        sent.append((method, path, body, self.base_url, self.api_key))
        if path == "/models":
            return {"data": [{"id": "a/chat"}, {"id": "b/embed"}, {"id": "c/guard"}]}
        if path.startswith("/models/"):
            if info is None:
                raise RuntimeError("로컬 서버 오류 404")
            return info
        return {"choices": [{"finish_reason": "stop", "message": {"content": reply}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
    monkeypatch.setattr(LocalLLM, "_request", request)


def test_no_key_is_missing_key():
    with pytest.raises(MissingKey, match="Superlinked API 키가 없어요"):
        make_llm("superlinked")


def test_request_goes_to_superlinked_with_key_and_model(monkeypatch):
    monkeypatch.setenv("SUPERLINKED_API_KEY", "sl_test_key")
    monkeypatch.setenv("CANON_SUPERLINKED_MODEL", "x/custom-model")
    sent = []
    _fake(monkeypatch, sent, info={"max_output_tokens": 4096})
    llm = make_llm("superlinked")
    assert isinstance(llm, SuperlinkedLLM)
    assert llm.json("시스템", "고르세요", Pick).pick == "사과"
    _, path, body, url, key = sent[-1]
    assert (path, url, key) == ("/chat/completions", superlinked.BASE_URL, "sl_test_key")
    assert body["model"] == "x/custom-model" and "min_p" not in body
    monkeypatch.delenv("CANON_SUPERLINKED_MODEL")
    sent.clear()
    _fake(monkeypatch, sent, info={})
    make_llm("superlinked").text("시스템", "쓰세요")
    assert sent[-1][2]["model"] == superlinked.DEFAULT_MODEL


@pytest.mark.parametrize("code", [503, 429])
def test_retries_with_retry_after(monkeypatch, code):
    monkeypatch.setenv("SUPERLINKED_API_KEY", "sl_test_key")
    calls, slept, said = [], [], []
    monkeypatch.setattr(superlinked.llm, "_pause", slept.append)
    monkeypatch.setattr(superlinked.cancel, "say", said.append)

    def call():
        calls.append(1)
        if len(calls) == 1:
            raise _wrapped(code, {"Retry-After": "1"})
        return {"ok": True}
    assert superlinked.patient(call) == {"ok": True}
    assert len(calls) == 2 and slept == [1.0] and len(said) == 1
    assert ("한도" in said[0]) == (code == 429)


def test_non_integer_retry_after_uses_default():
    assert superlinked.retry_wait(_wrapped(503, {"Retry-After": "Wed, 21 Oct"})) == superlinked.DEFAULT_WAIT_S
    assert superlinked.retry_wait(_wrapped(503)) is None
    assert superlinked.retry_wait(_wrapped(503, {"Retry-After": "0"})) == 1
    assert superlinked.retry_wait(_wrapped(500, {"Retry-After": "1"})) is None


def test_fallback_error_is_not_retried(monkeypatch):
    slept, calls = [], []
    monkeypatch.setattr(superlinked.llm, "_pause", slept.append)

    def call():
        calls.append(1)
        raise _wrapped(503, {"Retry-After": "1", "X-SIE-Fallback-Error": "relay failed"})
    with pytest.raises(RuntimeError):
        superlinked.patient(call)
    assert len(calls) == 1 and not slept


def test_get_is_not_retried(monkeypatch):
    """모델 목록 · 정보(GET)는 503 이어도 기다리지 않는다. 설정 화면이 오래 멈추지 않게."""
    monkeypatch.setenv("SUPERLINKED_API_KEY", "sl_test_key")
    slept, calls = [], []
    monkeypatch.setattr(superlinked.llm, "_pause", slept.append)

    def request(self, method, path, body=None, timeout=None):
        calls.append((method, path))
        raise _wrapped(503, {"Retry-After": "1"})
    monkeypatch.setattr(LocalLLM, "_request", request)
    llm = SuperlinkedLLM()
    with pytest.raises(RuntimeError, match="Superlinked"):
        llm._request("GET", "/models")
    assert llm.info() == {}
    assert len(calls) == 2 and not slept


def test_errors_become_hints():
    assert isinstance(superlinked.explain(RuntimeError("로컬 서버 오류 401 (u): invalid_api_key")), BadKey)
    relay = superlinked.explain(RuntimeError("로컬 서버 오류 403 (u): THIRD_PARTY_SERVING_DISABLED"))
    assert str(relay) == superlinked.RELAY_OFF_HINT and not isinstance(relay, BadKey)
    other = str(superlinked.explain(RuntimeError("로컬 서버에 연결하지 못했어요 (u): x")))
    assert "Superlinked" in other and "로컬 서버" not in other


def test_models_drop_non_chat_and_guard(monkeypatch):
    monkeypatch.setenv("SUPERLINKED_API_KEY", "sl_test_key")
    infos = {"a/chat": {"outputs": ["tokens"], "capabilities": {"guard": False}, "context_length": 16384},
             "d/short": {"outputs": ["tokens"], "context_length": 8192},
             "b/embed": {"outputs": ["vector"]},
             "e/unknown": {"outputs": ["tokens"]},
             "c/guard": {"outputs": ["tokens"], "capabilities": {"guard": True}}}

    def request(self, method, path, body=None, timeout=None):
        if path == "/models":
            return {"data": [{"id": i} for i in infos]}
        return infos[path.removeprefix("/models/")]
    monkeypatch.setattr(LocalLLM, "_request", request)
    assert make_llm("superlinked").models() == ["a/chat", "e/unknown"]


def test_max_tokens_is_always_sent(monkeypatch):
    monkeypatch.setenv("SUPERLINKED_API_KEY", "sl_test_key")
    sent = []
    _fake(monkeypatch, sent, info={"max_output_tokens": 32768})
    llm = make_llm("superlinked")
    llm.text("시스템", "쓰세요")
    assert sent[-1][2]["max_tokens"] == 32768
    assert [s for s in sent if s[1].startswith("/models/")].__len__() == 1
    llm.text("시스템", "또 쓰세요")
    assert len([s for s in sent if s[1].startswith("/models/")]) == 1  # 모델 정보는 한 번만
    llm._chat("시스템", [{"role": "user", "content": "x"}], max_tokens=100)
    assert sent[-1][2]["max_tokens"] == 100
    sent.clear()
    _fake(monkeypatch, sent, info=None)  # 모델 정보를 못 받는다
    make_llm("superlinked").text("시스템", "쓰세요")
    assert sent[-1][2]["max_tokens"] == superlinked.FALLBACK_OUT


def test_usage_backend_name(monkeypatch):
    llm = SuperlinkedLLM(api_key="sl_test_key")
    assert usage.backend_of(llm) == "superlinked"
    assert llm.count_tokens("글") is None


def test_settings_save_and_clear(monkeypatch):
    assert "superlinked" in settings.PROVIDERS
    settings.update(superlinked_api_key="sl_abcdefgh1234", superlinked_model="x/m")
    pub = settings.public()
    assert pub["superlinked_key_hint"] == "…1234" and pub["superlinked_key_source"] == "file"
    assert "sl_abcdefgh1234" not in str(pub) and pub["superlinked_model"] == "x/m"
    monkeypatch.setenv("CANON_LLM", "gemini")
    monkeypatch.setenv("CANON_LLM_NAME", "superlinked")
    monkeypatch.delenv("CANON_MODEL_NAME", raising=False)
    assert usage.stage_llm("name") == ("superlinked", "x/m")
    assert settings.stage_view(None)["name"]["model"] == "x/m"
    settings.update(clear_superlinked_key=True, superlinked_model="")
    assert settings.public()["superlinked_key_source"] == "none"
    assert usage.stage_llm("name")[1] == superlinked.DEFAULT_MODEL


def test_web_config_roundtrip(client):
    r = client.put("/api/config", json={"superlinked_api_key": "sl_abcdefgh5678", "superlinked_model": "x/m"})
    assert r.status_code == 200
    got = client.get("/api/config").json()
    assert got["superlinked_key_hint"] == "…5678" and got["superlinked_model"] == "x/m"
    client.put("/api/config", json={"clear_superlinked_key": True})
    assert client.get("/api/config").json()["superlinked_key_source"] == "none"


def test_max_tokens_is_capped_by_model_limit(monkeypatch):
    monkeypatch.setenv("SUPERLINKED_API_KEY", "sl_test_key")
    sent = []
    _fake(monkeypatch, sent, info={"max_output_tokens": 8192})
    llm = make_llm("superlinked")
    with canon_llm.out_cap(16384):
        llm.text("시스템", "쓰세요")
    assert sent[-1][2]["max_tokens"] == 8192
    with canon_llm.out_cap(4000):
        llm.text("시스템", "쓰세요")
    assert sent[-1][2]["max_tokens"] == 4000
    llm._chat("시스템", [{"role": "user", "content": "x"}], max_tokens=20000)
    assert sent[-1][2]["max_tokens"] == 8192


def test_failed_info_is_not_cached(monkeypatch):
    monkeypatch.setenv("SUPERLINKED_API_KEY", "sl_test_key")
    paths = []

    def request(self, method, path, body=None, timeout=None):
        paths.append(path)
        if len(paths) == 1:
            raise RuntimeError("로컬 서버 오류 500")
        return {"max_output_tokens": 100}
    monkeypatch.setattr(LocalLLM, "_request", request)
    llm = make_llm("superlinked", "a b/m:x")
    assert llm.out_limit() == superlinked.FALLBACK_OUT
    assert llm.out_limit() == 100 and paths == ["/models/a%20b/m:x"] * 2


def test_stop_during_wait_does_not_resend(monkeypatch):
    import threading
    ev = threading.Event()
    calls = []
    monkeypatch.setattr(superlinked.llm, "_pause", lambda s: ev.set())
    tok = cancel.current.set(ev)
    try:
        def call():
            calls.append(1)
            raise _wrapped(503, {"Retry-After": "1"})
        with pytest.raises(cancel.Cancelled):
            superlinked.patient(call)
    finally:
        cancel.current.reset(tok)
    assert len(calls) == 1


def test_unpriced_backend_has_unknown_cost(monkeypatch):
    assert "superlinked" in usage.UNPRICED and "superlinked" not in usage.PRICED
    from canon import promptlab
    assert promptlab.run_cost("superlinked", "m", {"prompt_tokens": 10}) is None
