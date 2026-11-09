"""AI 사용량과 비용: 모든 LLM 호출을 기록하고, 가격표로 비용을 추정해 모아 보여 준다.

호출 기록은 작품 데이터와 따로 projects/.usage/usage.jsonl 에 한 줄씩 붙인다 (CANON_USAGE 로 경로 변경).
GeminiLLM, LocalLLM, BatchLLM 이 실제 API 를 부를 때마다 record 를 부른다. mock 은 기록하지 않는다.
어느 작품의 몇 화, 어떤 작업인지는 호출하는 쪽이 scope(...) 로 감싸 알려 준다 (웹 요청, 백그라운드 작업,
자동 집필, 명령줄). 스레드는 컨텍스트를 물려받지 않으므로 jobs.start 처럼 스레드를 띄우는 곳은 복사해 넘긴다.

비용은 기록할 때 박아 두지 않고 볼 때마다 지금 가격표로 계산한다. 가격표를 고치면 지난 기록도 다시 계산되고,
가격이 바뀌는 날짜(since)를 적어 두면 호출한 날의 가격을 쓴다. 어디까지나 추정이며 Google 청구서와 다를 수 있다.
"""
from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple, Optional

from pydantic import BaseModel, Field

PRICES_URL = "https://ai.google.dev/gemini-api/docs/pricing"
BILLING_URL = "https://aistudio.google.com/usage"
PRICES_CHECKED = "2026-10-22"  # 아래 기본 가격을 Google 가격표에서 확인한 날


class Price(BaseModel):
    """USD / 100만 토큰. since 부터 적용한다 (비면 처음부터). 생각(thinking) 토큰은 출력 요금이다."""
    model: str = Field(description="모델 이름. 정확히 같거나 이 이름으로 시작하는 모델에 쓴다")
    since: str = Field("", description="적용 시작일 YYYY-MM-DD")
    input: float = 0.0
    output: float = 0.0
    cached: Optional[float] = Field(None, description="캐시된 입력. 비면 입력 가격")
    batch_input: Optional[float] = Field(None, description="배치 입력. 비면 입력의 절반")
    batch_output: Optional[float] = Field(None, description="배치 출력. 비면 출력의 절반")
    note: str = ""


def _p(model: str, since: str, i: float, o: float, c: float, note: str = "") -> Price:
    return Price(model=model, since=since, input=i, output=o, cached=c, batch_input=i / 2, batch_output=o / 2, note=note)


# Google 공식 가격표(유료 등급, 표준 요금)를 PRICES_CHECKED 에 옮긴 값. 날짜가 있는 줄은 예고된 인상이다.
# Pro 모델의 20만 토큰 초과 프롬프트 요금 단계는 반영하지 않는다 (Canon 의 프롬프트는 그보다 훨씬 작다).
DEFAULT_PRICES: list[Price] = [
    _p("gemini-4-argon", "", 2.0, 10.0, 0.10),
    _p("gemini-4-argon", "2026-12-01", 4.0, 20.0, 0.20, "2026-12-01 인상 예고"),
    _p("gemini-3.8-flash", "", 0.75, 3.75, 0.075),
    _p("gemini-3.8-flash", "2027-01-01", 1.50, 7.50, 0.15, "2027-01-01 인상 예고"),
    _p("gemini-3.6-flash", "", 0.75, 3.75, 0.075),
    _p("gemini-3.6-flash", "2027-01-01", 1.50, 7.50, 0.15, "2027-01-01 인상 예고"),
    _p("gemini-3.5-flash-lite", "", 0.30, 2.50, 0.03),
    _p("gemini-3.1-flash-lite", "", 0.25, 1.50, 0.025),
    _p("gemini-3.1-pro-preview", "", 2.0, 12.0, 0.20, "20만 토큰 이하 프롬프트 기준"),
    # Anthropic API 키(claude-api)로 부를 때. 구독 로그인(claude)은 요금제에 포함돼 0원으로 센다.
    _p("claude-opus-5-5", "", 4.0, 20.0, 0.20, "Anthropic API"),
    _p("claude-sonnet-5-5", "", 2.0, 10.0, 0.20, "Anthropic API"),
    _p("claude-haiku-5-5", "", 0.10, 0.50, 0.01, "Anthropic API, 10만 토큰 이하 프롬프트 기준"),
]
PRICED = ("gemini", "claude-api")  # 토큰 요금을 매기는 백엔드. 로컬과 Claude 구독은 0원

_ctx: ContextVar[dict] = ContextVar("canon_usage", default={})
_acc: ContextVar[Optional[list]] = ContextVar("canon_usage_acc", default=None)  # collect() 가 여는 누적기
_held: ContextVar[Optional[list]] = ContextVar("canon_usage_held", default=None)  # hold() 가 파일에 쓰기를 미룬 줄
_lock = threading.Lock()


# ---------- 기록 ----------

@contextmanager
def scope(**kw: Any) -> Iterator[None]:
    """안에서 일어나는 호출에 project, episode, stage, task, source, attempt, target 을 붙인다. None 인 값은 바깥 값을 둔다.
    다른 키는 줄에 실리지 않는다 (record 가 정해진 키와 SCOPED 만 담는다)."""
    token = _ctx.set({**_ctx.get(), **{k: v for k, v in kw.items() if v is not None}})
    try:
        yield
    finally:
        _ctx.reset(token)


def context() -> dict:
    return dict(_ctx.get())


# 작품 이름 → 성인 독자 대상 작품(Meta.adult)인지. store 가 정한다 (usage 는 store 를 모른다).
adult_of: Callable[[str], bool] | None = None


def adult() -> bool:
    """지금 호출의 작품(scope 의 project)이 성인 독자 대상 작품인지. 작품을 모르거나 읽지 못하면 False (줄을 넣지 않는 쪽)."""
    name = _ctx.get().get("project")
    if not name or adult_of is None:
        return False
    try:
        return bool(adult_of(name))
    except Exception:
        return False


@contextmanager
def collect() -> Iterator[list[dict]]:
    """안에서 record 한 줄을 모두 모은다. copy_context 로 넘긴 스레드의 호출도 같은 목록에 모인다.
    한 단계 안의 형식 고치기 재시도 · 여러 호출을 빠짐없이 세려는 것 (자동 집필의 토큰 · 비용 합계)."""
    rows: list[dict] = []
    token = _acc.set(rows)
    try:
        yield rows
    finally:
        _acc.reset(token)


@contextmanager
def hold() -> Iterator[list[dict]]:
    """안에서 record 한 줄을 파일에 바로 쓰지 않고 모았다가 끝날 때 쓴다. 끝나기 전에 줄을 고칠 수 있다 (discard).
    기록 파일은 덧붙이기만 하므로, 응답을 받은 뒤에 버릴지 정하는 쪽(pipeline._write)이 버린 줄 자체에 까닭을 달려는 것.
    collect() 에는 record 할 때 바로 더한다 (같은 dict 라 고친 값도 보인다). 겹쳐 열면 안쪽 줄은 바깥 목록으로 넘긴다."""
    rows: list[dict] = []
    token = _held.set(rows)
    try:
        yield rows
    finally:
        _held.reset(token)
        outer = _held.get()
        if outer is not None:
            outer.extend(rows)
        else:
            for r in rows:
                _append(r)


def discard(rows: list[dict], why: str) -> None:
    """hold() 로 모은 줄 가운데 마지막 줄(응답을 낸 호출)에 버린 까닭을 단다. 이미 까닭이 있으면 두고, 줄이 없으면 아무것도 하지 않는다.
    마지막 줄만 다는 것은 한 번 부르는 사이에 요청 한도 · 서버 오류로 실패한 줄이 앞에 있을 수 있어서다."""
    if rows and why and not rows[-1].get("discarded"):
        rows[-1]["discarded"] = why


def cache_rate(rows: list[dict]) -> float | None:
    """캐시로 읽은 입력의 비율. 한 호출 안에서 다시 보낸 입력(resent)은 캐시로 읽혔다고 보고 입력과 캐시 양쪽에서 뺀다.
    실측(2026-11, 서버 기록 Claude 842번): 그대로 세면 캐시 비율이 14.7%, 다시 보낸 것으로 보이는 호출(캐시가 입력의 절반)을 빼면 8~10%.
    입력이 없으면 None."""
    tin = sum(r.get("in", 0) for r in rows)
    cached = sum(r.get("cached", 0) for r in rows)
    resent = sum(min(r.get("resent", 0), r.get("cached", 0)) for r in rows)
    return (cached - resent) / (tin - resent) if tin - resent > 0 else None


def totals(rows: list[dict]) -> tuple[int, int, Optional[float]]:
    """collect 로 모은 줄의 (입력 토큰, 출력 + 생각 토큰, 비용). 비용은 사용량 화면과 같은 row_cost 로 센다.
    가격을 모르는 줄이 하나라도 있으면 비용은 None."""
    table = prices()
    tin = sum(int(r.get("in") or 0) for r in rows)
    tout = sum(int(r.get("out") or 0) + int(r.get("thought") or 0) for r in rows)
    total: Optional[float] = 0.0
    for r in rows:
        c, _ = row_cost(r, table)
        if c is None:
            total = None
        elif total is not None:
            total += c
    return tin, tout, total


def log_path() -> Path:
    env = os.environ.get("CANON_USAGE")
    if env:
        return Path(env).expanduser()
    from . import store

    return store.ROOT / ".usage" / "usage.jsonl"


def backend_of(llm: Any) -> Optional[str]:
    """기록할 백엔드 이름. mock 처럼 실제로 부르지 않는 것은 None."""
    name = type(llm).__name__
    return {"GeminiLLM": "gemini", "LocalLLM": "local", "ClaudeCodeLLM": "claude", "ClaudeAPILLM": "claude-api",
            "LocalJudge": "local"}.get(name)


# 있을 때만 남기는 칸. turns 턴 수, stop 끝난 이유 (모든 백엔드: STOP · MAX_TOKENS · end_turn · max_tokens · length 등),
# api_seconds 모델 API 시간, models 모델별 토큰,
# resent 한 호출 안에서 다시 보낸 입력 어림값 (in 에 들어 있음. 캐시 비율을 셀 때 in · cached 에서 뺀다).
# written 캐시에 새로 쓴 입력 (in 에 들어 있음), written_1h 그 가운데 1시간 캐시 몫. 옛 줄에는 없다.
# out_chars 응답 전체 글자 수 (본문에서 뗀 작업 설명도 든다). 응답이 오지 않았으면 칸이 없다.
# cache_note 캐시를 쓰거나 못 쓴 까닭 낱말 (llm.CACHE_NOTES: hit · made · short · not_worth 등).
EXTRA = ("turns", "stop", "api_seconds", "models", "resent", "written", "written_1h", "out_chars", "cache_note")
# scope 로 넣으면 줄에 싣는 칸. target 은 본문 쓰기 호출이 받은 목표 분량 글자 수 (pipeline._write)
SCOPED = ("target",)
CUT_STOPS = ("max_tokens", "length")  # 출력 길이 한도에 걸려 끊긴 끝난 이유. 소문자로 견준다 (llm.CUT_FINISH 와 Claude 의 max_tokens)


def record(llm: Any, tokens: Optional[dict], started: Optional[float] = None, *, ok: bool = True,
           error: Any = None, attempt: Optional[int] = None, batch: bool = False, prompt: str = "") -> None:
    """호출 하나를 기록한다. 기록이 실패해도 생성은 계속돼야 하므로 오류를 내지 않는다.
    prompt 를 주면 글자 수와 머리글별 블록 크기(context.blocks)를 함께 남긴다. 어떤 블록이 커지는지 보려는 것."""
    backend = backend_of(llm)
    if backend is None:
        return
    ctx = _ctx.get()
    u = tokens or {}
    now = datetime.now().astimezone()
    row = {
        "at": now.isoformat(timespec="seconds"),
        "project": ctx.get("project") or "",
        "episode": ctx.get("episode"),
        "stage": ctx.get("stage") or getattr(llm, "stage", None) or "",
        "task": ctx.get("task") or "",
        "source": ctx.get("source") or "",
        "backend": backend,
        "model": _model_name(llm),
        "batch": batch,
        "attempt": attempt or ctx.get("attempt") or 1,
        "in": int(u.get("prompt_tokens") or 0),
        "out": int(u.get("completion_tokens") or 0),
        "thought": int(u.get("thought_tokens") or 0),
        "cached": int(u.get("cached_tokens") or 0),
        "seconds": round(now.timestamp() - started, 2) if started else None,
        "ok": ok,
        "error": _error_text(error) if error is not None else "",
    }
    for k in EXTRA:  # 백엔드가 더 알려 준 값(끝난 이유 · 응답 글자 수 · Claude Code 의 턴 수 등). 없으면 칸이 없다
        if u.get(k) not in (None, "", {}):
            row[k] = u[k]
    for k in SCOPED:  # 부른 쪽이 scope 로 알려 준 값 (본문 쓰기의 목표 분량)
        if ctx.get(k) not in (None, ""):
            row[k] = ctx[k]
    if getattr(llm, "effort", ""):
        row["effort"] = llm.effort  # 넘긴 추론 강도(Claude · Gemini). 정하지 않았으면 칸이 없다 (모델 기본값)
    if prompt:
        from .context import blocks
        row["chars"] = len(prompt)
        row["blocks"] = blocks(prompt, 8)
    acc = _acc.get()
    if acc is not None:
        acc.append(row)  # 파일에 쓰지 못해도 합계는 맞게 먼저 더한다
    held = _held.get()
    if held is not None:
        held.append(row)  # hold() 가 끝날 때 쓴다
    else:
        _append(row)


def with_extra(tokens: Optional[dict], **kw: Any) -> dict:
    """백엔드가 record 에 넘길 토큰 dict 에 칸(stop · out_chars 등)을 더한 새 dict. 값이 None 이거나 빈 글이면 넣지 않는다.
    last_usage 를 고치지 않으려고 새 dict 를 만든다."""
    return {**(tokens or {}), **{k: v for k, v in kw.items() if v is not None and v != ""}}


def _append(row: dict) -> None:
    """기록 파일에 한 줄을 덧붙인다. 실패해도 오류를 내지 않는다."""
    try:
        path = log_path()
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def model_id(llm: Any) -> str:
    """본문을 쓴 모델의 이름 '<백엔드>:<모델>' (Episode.written_by). 사용량 기록의 backend · model 과 같은 값이다.
    배치는 안쪽 LLM 으로, mock 은 'mock:mock'. 모델 이름이 비면 'default'."""
    llm = getattr(llm, "inner", llm)
    if type(llm).__name__ == "MockLLM":
        return "mock:mock"
    return f"{backend_of(llm) or type(llm).__name__}:{_model_name(llm) or 'default'}"


def _model_name(llm: Any) -> str:
    try:
        return str(getattr(llm, "_model", None) or llm.model or "")
    except Exception:  # 로컬 모델 이름을 서버에 물어야 하는데 서버가 없을 때
        return ""


def _error_text(e: Any) -> str:
    from pydantic import ValidationError

    if isinstance(e, ValidationError):
        return f"응답 형식 불일치 ({e.title})"
    text = getattr(e, "message", None) or str(e) or type(e).__name__
    if getattr(e, "code", None) == 429 or getattr(e, "status", None) == "RESOURCE_EXHAUSTED":
        text = f"요청 한도 (429): {text}"
    else:
        from .llm import is_timeout, is_transient

        if isinstance(e, BaseException) and is_timeout(e):
            text = f"응답 시간 초과: {text}"
        elif isinstance(e, BaseException) and is_transient(e):
            text = f"서버 오류 ({getattr(e, 'code', None) or getattr(e, 'status', '')}): {text}"
    return text[:300]


# 경로별로 읽은 줄과 읽은 끝 위치를 기억한다. 기록은 붙이기만 하므로 다음에는 늘어난 부분만 읽는다.
# 파일이 바뀌었으면(다른 inode, 줄어든 크기) 처음부터 읽는다. {경로: (inode, 읽은 바이트, 줄들)}
_read_cache: dict[Path, tuple[int, int, list[dict]]] = {}
_read_lock = threading.Lock()


def read(path: Optional[Path] = None) -> list[dict]:
    """기록 전체. 돌려준 목록과 그 안의 dict 는 고치지 않는다 (다음 호출과 함께 쓴다)."""
    path = path or log_path()
    try:
        st = path.stat()
    except OSError:
        return []
    with _read_lock:
        ino, done, rows = _read_cache.get(path, (st.st_ino, 0, []))
        if ino != st.st_ino or st.st_size < done:
            done, rows = 0, []
        if st.st_size > done:
            with path.open("rb") as f:
                f.seek(done)
                chunk = f.read()
            end = chunk.rfind(b"\n") + 1  # 마지막 줄을 아직 쓰는 중이면 다음에 읽는다
            rows = rows + [r for r in map(_row, chunk[:end].splitlines()) if r is not None]
            done += end
        _read_cache[path] = (st.st_ino, done, rows)
        return list(rows)


def _row(line: bytes) -> Optional[dict]:
    try:
        return json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None  # 쓰다 끊긴 줄


# ---------- 입력 토큰 추정 ----------

class TokenRate(NamedTuple):
    """호출 하나의 입력 토큰 ≈ slope × 요청 글자 수 + intercept. 출력 본문은 slope × 글자 수로 센다."""
    slope: float
    intercept: float
    source: str = "default"  # default: 아래 기본값 / measured: 최근 사용량 기록에서 잰 값 / fallback: 기본값이 없는 백엔드
    rows: int = 0  # measured 일 때 잰 기록 줄 수


# 백엔드별 (모델 이름에 든 낱말, 토큰/글자, 호출마다 붙는 토큰). 낱말이 빈 줄은 그 백엔드의 기본값이다.
# 2026-11 서버 사용량 기록(성공한 호출 중 글자 수가 있는 줄)의 최소제곱 직선. 기록의 글자 수는 시스템 프롬프트를 뺀 요청이고,
# 시스템 프롬프트와 Claude Code 가 더하는 앞부분은 붙는 토큰에 들어간다.
# Opus(Claude Code) 654줄 1.035/3805, Sonnet 77줄 0.995/5793, argon 709줄 0.568/1579, flash 238줄 0.599/2508.
# claude-api 는 기록이 없어 같은 토크나이저의 기울기만 쓰고 붙는 토큰은 0으로 둔다.
TOKEN_RATES: dict[str, list[tuple[str, float, float]]] = {
    "claude": [("opus", 1.035, 3805), ("sonnet", 0.995, 5793), ("", 1.035, 3805)],
    "claude-api": [("opus", 1.035, 0), ("sonnet", 0.995, 0), ("", 1.035, 0)],
    "gemini": [("flash", 0.599, 2508), ("argon", 0.568, 1579), ("", 0.568, 1579)],
}
FALLBACK_CHARS_PER_TOKEN = 1.7  # 기본값이 없는 백엔드(로컬, mock). context.CHARS_PER_TOKEN 과 같은 값
REFINE_ROWS = 200  # 다시 잴 때 보는 최근 기록 줄 수
REFINE_MIN = 20  # 쓸 수 있는 기록이 이보다 적으면 기본값을 쓴다
REFINE_SPAN = 5_000  # 가장 짧은 요청과 가장 긴 요청의 글자 수 차이가 이보다 작으면 직선을 긋지 않는다
REFINE_SLOPE = (0.2, 3.0)  # 잰 기울기가 이 밖이면 버리고 기본값을 쓴다
_rate_cache: dict[tuple, TokenRate] = {}


def backend_for(model: str) -> str:
    """백엔드를 모를 때 모델 이름으로 고른다. Claude 는 구독(claude)으로 본다."""
    low = (model or "").lower()
    if "claude" in low or low in ("opus", "sonnet", "haiku"):
        return "claude"
    return "gemini" if "gemini" in low else ""


def default_rate(backend: str, model: str = "") -> TokenRate:
    low = (model or "").lower()
    for word, slope, intercept in TOKEN_RATES.get(backend, []):
        if word in low:
            return TokenRate(slope, intercept)
    return TokenRate(1 / FALLBACK_CHARS_PER_TOKEN, 0.0, "fallback")


CLI_ALIASES = ("opus", "sonnet", "haiku")  # Claude Code 가 받는 모델 별칭. 기록에는 실제로 답한 모델 이름이 남는다
DOUBLED = 1.5  # 기본 직선보다 이만큼 넘게 많고 캐시가 입력의 절반쯤이면 캐시 읽기를 두 번 센 기록으로 본다


def _same_model(row_model: str, model: str, backend: str) -> bool:
    """기록의 모델이 고른 모델인지. Claude Code 는 별칭(opus)을 넘겨도 기록에 실제 이름(claude-opus-5-5)이 남는다."""
    if row_model == model:
        return True
    return backend == "claude" and model in CLI_ALIASES and model in (row_model or "").lower()


def _usable(r: dict, backend: str, model: str, base: TokenRate) -> bool:
    if r.get("backend") != backend or not r.get("ok") or not _same_model(r.get("model") or "", model, backend):
        return False
    chars, tin = r.get("chars") or 0, r.get("in") or 0
    if chars <= 0 or tin <= 0:
        return False
    if backend != "claude":
        return True
    # 예전 Claude Code 기록 가운데 캐시 읽기를 입력에 두 번 센 줄은 뺀다: 캐시가 입력의 절반쯤 이상이고 입력이 직선의 1.5배를 넘는다.
    # 앞부분을 시스템 프롬프트로 옮겨 캐시가 맞은 정상 기록(캐시가 입력 대부분, 입력은 직선 근처)은 남긴다
    return not ((r.get("cached") or 0) * 2 >= 0.9 * tin and tin > DOUBLED * est_input(chars, base))


def _fit(pairs: list[tuple[float, float]], base: TokenRate) -> TokenRate:
    xs = [x for x, _ in pairs]
    if len(pairs) < REFINE_MIN or max(xs) - min(xs) < REFINE_SPAN:
        return base
    mx = sum(xs) / len(xs)
    my = sum(y for _, y in pairs) / len(pairs)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in pairs) / sxx
    intercept = my - slope * mx
    if intercept < 0:  # 붙는 토큰이 음수면 원점을 지나는 비율로 센다
        slope, intercept = sum(y for _, y in pairs) / sum(xs), 0.0
    if not REFINE_SLOPE[0] <= slope <= REFINE_SLOPE[1]:
        return base
    return TokenRate(round(slope, 4), round(intercept), "measured", len(pairs))


def _pairs(rows: list[dict], backend: str, model: str, base: TokenRate) -> list[tuple[float, float]]:
    return [(r["chars"], r["in"]) for r in rows if _usable(r, backend, model, base)][-REFINE_ROWS:]


def _default_model(rows: list[dict], backend: str) -> str:
    """Claude Code 기본 모델(설정이 빔)은 이름을 몰라 최근 성공 기록에 가장 많이 남은 모델로 본다."""
    if backend != "claude":
        return ""
    recent = [r.get("model") for r in rows if r.get("backend") == backend and r.get("ok") and r.get("chars")][-REFINE_ROWS:]
    names = [m for m in recent if m and m != "claude-code"]
    return max(set(names), key=names.count) if names else ""


def token_rate(backend: str, model: str = "", rows: Optional[list[dict]] = None) -> TokenRate:
    """백엔드 · 모델의 입력 토큰 추정 직선. 같은 백엔드 · 모델의 최근 성공 기록이 REFINE_MIN 줄 이상이면 그 기록으로 다시 잰다.
    backend 가 비면 모델 이름으로 고른다(backend_for). rows 를 주지 않으면 사용량 기록(read)을 읽는다.
    Claude Code 별칭(opus)은 그 이름이 든 기록과, 빈 모델(기본 모델)은 최근 기록에 가장 많은 모델과 맞춘다."""
    backend = backend or backend_for(model)
    if rows is None:
        rows = read()
        key = (backend, model, str(log_path()), len(rows))
        if key not in _rate_cache:
            _rate_cache[key] = _refit(rows, backend, model)
        return _rate_cache[key]
    return _refit(rows, backend, model)


def _refit(rows: list[dict], backend: str, model: str) -> TokenRate:
    model = model or _default_model(rows, backend)
    base = default_rate(backend, model)
    if not model:
        return base  # 이름도 기록도 없으면 기록과 맞춰 볼 수 없다
    return _fit(_pairs(rows, backend, model, base), base)


def est_input(chars: float, rate: TokenRate, system: float = 0, calls: int = 1) -> float:
    """요청(chars 글자, 시스템 프롬프트 뺌)의 입력 토큰 추정. 호출마다 붙는 토큰(intercept)에 시스템 프롬프트가 이미 들어 있다.
    붙는 토큰을 모르는 백엔드(0)나 시스템 프롬프트(system 글자)가 그보다 길면 시스템 프롬프트를 기울기로 센다. calls 는 호출 수."""
    return rate.slope * chars + calls * max(rate.intercept, rate.slope * system)


def est_output(chars: float, rate: TokenRate) -> float:
    """chars 글자를 내는 출력 토큰 추정. 붙는 토큰은 입력 쪽에만 있다."""
    return rate.slope * chars


def stage_llm(stage: str) -> tuple[str, str]:
    """단계가 쓰는 (백엔드, 모델). 단계 모델이 비면 그 백엔드의 기본 모델. Claude Code 기본 모델은 이름을 몰라 비운다."""
    from . import settings

    backend = settings.stage_provider(stage)[0]
    model = settings.stage_model(stage)[0]
    if model:
        return backend, model
    if backend == "gemini":
        model = settings.model()[0]
    elif backend in ("claude", "claude-api"):
        model = settings.claude_model()[0]
        if not model and backend == "claude-api":
            from .claude import DEFAULT_API_MODEL

            model = DEFAULT_API_MODEL
    elif backend == "local":
        model = settings.local_model()[0]
    return backend, model


def stage_rate(stage: str) -> TokenRate:
    """단계 백엔드 · 모델의 입력 토큰 추정 직선 (token_rate)."""
    return token_rate(*stage_llm(stage))


# ---------- 가격표 ----------

def prices() -> list[Price]:
    """기본 가격표에 사용자가 설정에서 고친 모델을 덮은 것. 사용자가 적은 모델은 그 모델의 기본 줄을 모두 대신한다."""
    from . import settings

    custom = [Price.model_validate(x) for x in settings.prices()]
    mine = {x.model for x in custom}
    return [x for x in DEFAULT_PRICES if x.model not in mine] + custom


def custom_models() -> set[str]:
    from . import settings

    return {x.get("model") for x in settings.prices()}


def save_prices(rows: list[Price]) -> None:
    """화면에서 고친 표 전체를 받아, 기본값과 다른 모델만 설정 파일에 남긴다 (기본값이 바뀌면 따라가게)."""
    from . import settings

    by: dict[str, list[Price]] = defaultdict(list)
    for r in rows:
        r.model = r.model.strip()
        if not r.model:
            continue
        if r.since and not _is_date(r.since):
            raise ValueError(f"{r.model}: 적용 시작일은 YYYY-MM-DD로 적어 주세요 ({r.since})")
        if min(r.input, r.output, r.cached or 0, r.batch_input or 0, r.batch_output or 0) < 0:
            raise ValueError(f"{r.model}: 가격은 0 이상이어야 해요")
        by[r.model].append(r)
    defaults: dict[str, list[dict]] = defaultdict(list)
    for d in DEFAULT_PRICES:
        defaults[d.model].append(_key(d))
    keep = [r for m, rs in by.items() if sorted(map(_key, rs), key=str) != sorted(defaults.get(m, []), key=str) for r in rs]
    settings.set_prices([r.model_dump(exclude_defaults=True) | {"model": r.model} for r in keep])


def _key(p: Price) -> dict:
    return p.model_dump(exclude={"note"})


def _is_date(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def rate(model: str, day: str = "", table: Optional[list[Price]] = None) -> Optional[Price]:
    """그날 그 모델에 쓰는 가격 줄. 정확히 같은 이름이 없으면 가장 긴 접두어로 찾는다 (gemini-4-argon-001 등)."""
    table = prices() if table is None else table
    model = model.removeprefix("models/")
    day = day or date.today().isoformat()
    names = {p.model for p in table}
    name = model if model in names else max((n for n in names if model.startswith(n)), key=len, default=None)
    if name is None:
        return None
    rows = sorted((p for p in table if p.model == name and (not p.since or p.since <= day)), key=lambda p: p.since)
    return rows[-1] if rows else None


def cost(p: Price, tin: float, tout: float, cached: float = 0.0, batch: bool = False) -> float:
    """USD. tin 은 캐시된 토큰을 포함한 입력 전체, tout 은 생각 토큰을 포함한 출력."""
    inp, out = p.input, p.output
    cin = p.cached if p.cached is not None else p.input
    if batch:
        inp = p.batch_input if p.batch_input is not None else p.input / 2
        out = p.batch_output if p.batch_output is not None else p.output / 2
        cin = cin * (inp / p.input) if p.input else cin / 2
    cached = min(cached, tin)
    return ((tin - cached) * inp + cached * cin + tout * out) / 1e6


def stage_cost(backend: str, model: str, tin: float, tout: float, batch: bool = False) -> Optional[float]:
    """자동 집필 추정용. 로컬과 Claude 구독은 0, 가격을 모르는 모델이면 None."""
    if backend not in PRICED:
        return 0.0
    if backend == "claude-api":
        from .claude import api_model

        model = api_model(model)
    p = rate(model)
    return None if p is None else cost(p, tin, tout, batch=batch)


def row_cost(r: dict, table: list[Price]) -> tuple[Optional[float], float]:
    """(실제 추정 비용, 배치로 아낀 비용). 가격을 모르면 (None, 0)."""
    if r.get("backend") not in PRICED:
        return 0.0, 0.0
    p = rate(r.get("model", ""), r.get("at", "")[:10], table)
    if p is None:
        return None, 0.0
    tin, tout, cached = r.get("in", 0), r.get("out", 0) + r.get("thought", 0), r.get("cached", 0)
    c = cost(p, tin, tout, cached, bool(r.get("batch")))
    saved = cost(p, tin, tout, cached) - c if r.get("batch") else 0.0
    return c, saved


# ---------- 모아 보기 ----------

def _since(days: Optional[int]) -> str:
    return (date.today() - timedelta(days=days - 1)).isoformat() if days else ""


EFFORT_DEFAULT = "기본"  # 추론 강도를 정하지 않은 호출(모델 기본값)의 묶음 이름


def _rates(b: dict) -> dict:
    """묶음의 캐시 비율(캐시 / 입력, 0~1, 입력이 없으면 0)과 호출당 평균 초.
    한 호출 안에서 다시 보낸 입력(resent)은 cache_rate 처럼 입력과 캐시 양쪽에서 뺀다.
    분량 달성률(len_ratio)은 목표 분량이 있는 호출의 응답 글자 수 합 / 목표 합이다. 그런 호출이 없으면 None."""
    resent = min(b.get("resent", 0), b["cached"])
    tin, cached = b["in"] - resent, b["cached"] - resent
    return {"cache_rate": round(cached / tin, 4) if tin > 0 else 0.0,
            "seconds_avg": round(b["seconds"] / b["calls"], 1) if b["calls"] else 0.0,
            "len_ratio": round(b["len_out"] / b["len_target"], 3) if b.get("len_target") else None}


def is_cut(r: dict) -> bool:
    """기록 줄이 출력 길이 한도에 걸려 끊긴 호출인지. 끝난 이유(stop)나 본문 쓰기가 버린 까닭(discarded cut)으로 안다. 옛 줄은 거짓."""
    return r.get("discarded") == "cut" or str(r.get("stop") or "").lower() in CUT_STOPS


def len_pair(r: dict) -> tuple[int, int] | None:
    """분량 달성률에 넣을 (응답 글자 수, 목표 분량). 목표 분량과 응답 글자 수가 있고, 실패하지 않았고 버리지 않은 줄만.
    버린 줄(끊김 · 다른 글)은 끊김 · 버림 수로 따로 센다. 옛 줄은 None."""
    target, chars = r.get("target"), r.get("out_chars")
    if not isinstance(target, int) or target <= 0 or not isinstance(chars, int):
        return None
    if not r.get("ok", True) or r.get("discarded"):
        return None
    return chars, target


def summary(days: Optional[int] = 30, project: Optional[str] = None, limit: int = 60) -> dict:
    """기간(최근 days 일, None 이면 전체)과 작품으로 거른 기록을 날짜, 작품, 화, 단계, 모델, 용도, 작업, 추론 강도별로 모은다.

    묶음마다 캐시 비율(`cache_rate` = 캐시 토큰 / 입력 토큰)과 호출당 평균 시간(`seconds_avg`)을 붙인다."""
    table = prices()
    start = _since(days)
    rows = read()
    projects = sorted({r.get("project") or "" for r in rows} - {""})
    rows = [r for r in rows if r.get("at", "")[:10] >= start and (project is None or r.get("project", "") == project)]

    def bucket() -> dict:
        return {"calls": 0, "failed": 0, "retries": 0, "in": 0, "out": 0, "cached": 0, "resent": 0, "cost": 0.0,
                "saved": 0.0, "unpriced": 0, "seconds": 0.0, "batch": 0,
                "discarded": 0, "cut": 0, "len_calls": 0, "len_out": 0, "len_target": 0}

    total = bucket()
    groups: dict[str, dict[Any, dict]] = {k: defaultdict(bucket) for k in ("day", "project", "episode", "stage", "model", "source", "task", "effort")}
    unpriced: set[str] = set()
    wasted = 0.0
    trouble, recent = [], []
    for r in rows:
        c, saved = row_cost(r, table)
        out = r.get("out", 0) + r.get("thought", 0)
        pair = len_pair(r)
        cut = is_cut(r)
        keys = {
            "day": r.get("at", "")[:10],
            "project": r.get("project") or "",
            "episode": (r.get("project") or "", r.get("episode")) if r.get("episode") is not None else None,
            "stage": r.get("stage") or "",
            "model": (r.get("backend", ""), r.get("model", "")),
            "source": r.get("source") or "",
            "task": r.get("task") or "",
            "effort": r.get("effort") or EFFORT_DEFAULT,
        }
        for b in [total] + [groups[k][v] for k, v in keys.items() if v is not None]:
            b["calls"] += 1
            b["failed"] += not r.get("ok", True)
            b["retries"] += r.get("attempt", 1) > 1
            b["in"] += r.get("in", 0)
            b["out"] += out
            b["cached"] += r.get("cached", 0)
            b["resent"] += min(r.get("resent", 0), r.get("cached", 0))  # cache_rate 처럼 줄마다 캐시 안으로 자른다
            b["cost"] += c or 0.0
            b["saved"] += saved
            b["unpriced"] += c is None
            b["seconds"] += r.get("seconds") or 0.0
            b["batch"] += bool(r.get("batch"))
            b["discarded"] += bool(r.get("discarded"))
            b["cut"] += cut
            if pair:
                b["len_calls"] += 1
                b["len_out"] += pair[0]
                b["len_target"] += pair[1]
        if c is None:
            unpriced.add(r.get("model", ""))
        item = {**r, "cost": c, "saved": saved}
        if not r.get("ok", True) or r.get("attempt", 1) > 1 or r.get("discarded"):  # 버린 응답도 낭비다
            wasted += c or 0.0
            trouble.append(item)
        recent.append(item)

    def listing(name: str, sort: str = "cost") -> list[dict]:
        out = []
        for k, b in groups[name].items():
            row = {**b, "cost": round(b["cost"], 6), "saved": round(b["saved"], 6), "seconds": round(b["seconds"], 1), **_rates(b)}
            if name == "episode":
                row["project"], row["episode"] = k
            elif name == "model":
                row["backend"], row["model"] = k
            else:
                row[name] = k
            out.append(row)
        if sort == "key":
            return sorted(out, key=lambda x: x[name])
        if name == "episode":
            return sorted(out, key=lambda x: (x["project"], x["episode"]))
        return sorted(out, key=lambda x: (-x["cost"], -x["calls"]))

    return {
        "days": days, "since": start, "project": project, "projects": projects,
        "total": {**total, "cost": round(total["cost"], 6), "saved": round(total["saved"], 6),
                  "wasted": round(wasted, 6), "seconds": round(total["seconds"], 1), **_rates(total)},
        "by_day": listing("day", "key"), "by_project": listing("project"), "by_episode": listing("episode"),
        "by_stage": listing("stage"), "by_model": listing("model"), "by_source": listing("source"),
        "by_task": listing("task"), "by_effort": listing("effort"),
        "unpriced": sorted(unpriced),
        "trouble": trouble[::-1][:limit], "recent": recent[::-1][:limit],
        "trouble_total": len(trouble), "limit": limit,
        "billing_url": BILLING_URL, "prices_url": PRICES_URL,
    }


def price_table() -> dict:
    """설정 화면에 보여 줄 가격표. 오늘 적용되는 줄과 사용자가 고친 모델을 표시한다."""
    table = prices()
    today = date.today().isoformat()
    mine = custom_models()
    current = {id(rate(m, today, table)) for m in {p.model for p in table}}
    rows = [{**p.model_dump(), "custom": p.model in mine, "current": id(p) in current,
             "upcoming": bool(p.since and p.since > today)}
            for p in sorted(table, key=lambda p: (p.model, p.since))]
    return {"rows": rows, "checked": PRICES_CHECKED, "url": PRICES_URL, "billing_url": BILLING_URL}
