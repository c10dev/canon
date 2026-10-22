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
from typing import Any, Iterator, Optional

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
]

_ctx: ContextVar[dict] = ContextVar("canon_usage", default={})
_lock = threading.Lock()


# ---------- 기록 ----------

@contextmanager
def scope(**kw: Any) -> Iterator[None]:
    """안에서 일어나는 호출에 project, episode, stage, task, source, attempt 를 붙인다. None 인 값은 바깥 값을 둔다."""
    token = _ctx.set({**_ctx.get(), **{k: v for k, v in kw.items() if v is not None}})
    try:
        yield
    finally:
        _ctx.reset(token)


def context() -> dict:
    return dict(_ctx.get())


def log_path() -> Path:
    env = os.environ.get("CANON_USAGE")
    if env:
        return Path(env).expanduser()
    from . import store

    return store.ROOT / ".usage" / "usage.jsonl"


def backend_of(llm: Any) -> Optional[str]:
    """기록할 백엔드 이름. mock 처럼 실제로 부르지 않는 것은 None."""
    name = type(llm).__name__
    return {"GeminiLLM": "gemini", "LocalLLM": "local"}.get(name)


def record(llm: Any, tokens: Optional[dict], started: Optional[float] = None, *, ok: bool = True,
           error: Any = None, attempt: Optional[int] = None, batch: bool = False) -> None:
    """호출 하나를 기록한다. 기록이 실패해도 생성은 계속돼야 하므로 오류를 내지 않는다."""
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
    try:
        path = log_path()
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _model_name(llm: Any) -> str:
    try:
        return str(getattr(llm, "_model", None) or llm.model or "")
    except Exception:  # 로컬 모델 이름을 서버에 물어야 하는데 서버가 없을 때
        return ""


def _error_text(e: Any) -> str:
    from pydantic import ValidationError

    if isinstance(e, ValidationError):
        return f"응답 형식 불일치 ({e.title})"
    return (getattr(e, "message", None) or str(e) or type(e).__name__)[:300]


def read(path: Optional[Path] = None) -> list[dict]:
    path = path or log_path()
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 쓰다 끊긴 줄
    return out


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
            raise ValueError(f"{r.model}: 적용 시작일은 YYYY-MM-DD 로 적어 주세요 ({r.since})")
        if min(r.input, r.output, r.cached or 0, r.batch_input or 0, r.batch_output or 0) < 0:
            raise ValueError(f"{r.model}: 가격은 0 이상이어야 합니다")
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
    """자동 집필 추정용. 로컬은 0, 가격을 모르는 Gemini 모델이면 None."""
    if backend != "gemini":
        return 0.0
    p = rate(model)
    return None if p is None else cost(p, tin, tout, batch=batch)


def row_cost(r: dict, table: list[Price]) -> tuple[Optional[float], float]:
    """(실제 추정 비용, 배치로 아낀 비용). 가격을 모르면 (None, 0)."""
    if r.get("backend") != "gemini":
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


def summary(days: Optional[int] = 30, project: Optional[str] = None, limit: int = 60) -> dict:
    """기간(최근 days 일, None 이면 전체)과 작품으로 거른 기록을 날짜, 작품, 화, 단계, 모델, 용도별로 모은다."""
    table = prices()
    start = _since(days)
    rows = read()
    projects = sorted({r.get("project") or "" for r in rows} - {""})
    rows = [r for r in rows if r.get("at", "")[:10] >= start and (project is None or r.get("project", "") == project)]

    def bucket() -> dict:
        return {"calls": 0, "failed": 0, "retries": 0, "in": 0, "out": 0, "cached": 0, "cost": 0.0,
                "saved": 0.0, "unpriced": 0, "seconds": 0.0, "batch": 0}

    total = bucket()
    groups: dict[str, dict[Any, dict]] = {k: defaultdict(bucket) for k in ("day", "project", "episode", "stage", "model", "source")}
    unpriced: set[str] = set()
    wasted = 0.0
    trouble, recent = [], []
    for r in rows:
        c, saved = row_cost(r, table)
        out = r.get("out", 0) + r.get("thought", 0)
        keys = {
            "day": r.get("at", "")[:10],
            "project": r.get("project") or "",
            "episode": (r.get("project") or "", r.get("episode")) if r.get("episode") is not None else None,
            "stage": r.get("stage") or "",
            "model": (r.get("backend", ""), r.get("model", "")),
            "source": r.get("source") or "",
        }
        for b in [total] + [groups[k][v] for k, v in keys.items() if v is not None]:
            b["calls"] += 1
            b["failed"] += not r.get("ok", True)
            b["retries"] += r.get("attempt", 1) > 1
            b["in"] += r.get("in", 0)
            b["out"] += out
            b["cached"] += r.get("cached", 0)
            b["cost"] += c or 0.0
            b["saved"] += saved
            b["unpriced"] += c is None
            b["seconds"] += r.get("seconds") or 0.0
            b["batch"] += bool(r.get("batch"))
        if c is None:
            unpriced.add(r.get("model", ""))
        item = {**r, "cost": c, "saved": saved}
        if not r.get("ok", True) or r.get("attempt", 1) > 1:
            wasted += c or 0.0
            trouble.append(item)
        recent.append(item)

    def listing(name: str, sort: str = "cost") -> list[dict]:
        out = []
        for k, b in groups[name].items():
            row = {**b, "cost": round(b["cost"], 6), "saved": round(b["saved"], 6), "seconds": round(b["seconds"], 1)}
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
                  "wasted": round(wasted, 6), "seconds": round(total["seconds"], 1)},
        "by_day": listing("day", "key"), "by_project": listing("project"), "by_episode": listing("episode"),
        "by_stage": listing("stage"), "by_model": listing("model"), "by_source": listing("source"),
        "unpriced": sorted(unpriced),
        "trouble": trouble[::-1][:limit], "recent": recent[::-1][:limit],
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
