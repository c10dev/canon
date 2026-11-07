"""프롬프트 놀이터: 시스템 · 요청 프롬프트를 직접 써서 여러 백엔드로 돌리고, 결과 · 시간 · 토큰 · 어림 비용을 시도로 남겨 견준다.

작품(project.json)과 상관없고 세션 파일 <CANON_HOME>/.promptlab/<id>.json 에 둔다 (CANON_PROMPTLAB 으로 경로 변경, 문단 연습장처럼 작품 밖).
호출은 연구 화면의 샘플 생성(research.sample)을 그대로 쓴다. 백엔드는 gemini · local · mock 이고, 한 쪽이 실패해도 나머지는 돌린다.
시도마다 그때의 프롬프트를 함께 남겨, 고치기 전 판으로 되돌아가거나 판끼리 견줄 수 있다.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import research, store, usage
from .schema import PromptBackend, PromptRun, PromptSession, PromptTrial

ID_RE = re.compile(r"^[0-9a-f]{8,32}$")
PROVIDERS = ("gemini", "local", "mock")
MAX_BACKENDS = 4  # 한 번에 돌리는 백엔드 수. 차례로 부르므로 많으면 오래 걸린다
MAX_TRIALS = 40  # 세션마다 남기는 시도. 저절로 지우지 않고, 차면 작가가 지울 시도를 고른다
TEXT_MAX = 60000  # 시스템 · 요청 프롬프트 한 칸의 글자 수 상한
TITLE_MAX = 60
NOTE_MAX = 400
TEMPERATURE = (0.0, 2.0)


def root() -> Path:
    return Path(os.environ.get("CANON_PROMPTLAB") or store.ROOT / ".promptlab")


def _missing(sid: str) -> KeyError:
    return KeyError(f"프롬프트 놀이터에 없는 세션이에요: {sid}")


def _path(sid: str) -> Path:
    if not ID_RE.match(sid):
        raise _missing(sid)
    return root() / f"{sid}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load(sid: str) -> PromptSession:
    path = _path(sid)
    if not path.exists():
        raise _missing(sid)
    return PromptSession.model_validate_json(path.read_text(encoding="utf-8"))


def save(s: PromptSession) -> PromptSession:
    s.created_at = s.created_at or _now()
    s.updated_at = _now()
    path = _path(s.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    store.write_atomic(path, s.model_dump_json(indent=2))
    return s


def sessions() -> list[PromptSession]:
    d = root()
    if not d.exists():
        return []
    out = []
    for f in d.glob("*.json"):
        try:
            out.append(PromptSession.model_validate_json(f.read_text(encoding="utf-8")))
        except ValueError:
            continue  # 깨진 파일은 목록에서 뺀다 (지우지 않는다)
    return sorted(out, key=lambda s: s.updated_at, reverse=True)


# ---------- 세션 ----------

def clean_backends(bs: list[PromptBackend]) -> list[PromptBackend]:
    """알 수 없는 백엔드는 거절하고, 같은 백엔드 · 모델 · 주소는 한 번만 남긴다."""
    out: list[PromptBackend] = []
    for b in bs:
        b = PromptBackend(provider=b.provider.strip(), model=b.model.strip(), url=b.url.strip() if b.provider.strip() == "local" else "")
        if b.provider not in PROVIDERS:
            raise ValueError(f"알 수 없는 백엔드예요: {b.provider} (gemini · local · mock)")
        if b not in out:
            out.append(b)
    if len(out) > MAX_BACKENDS:
        raise ValueError(f"백엔드는 한 번에 {MAX_BACKENDS}개까지 돌려요")
    return out


def clean_temperature(t: Optional[float]) -> Optional[float]:
    if t is None:
        return None
    lo, hi = TEMPERATURE
    return round(max(lo, min(hi, float(t))), 2)


def title_of(prompt: str) -> str:
    first = next((x.strip() for x in prompt.splitlines() if x.strip()), "")
    return (first or "새 프롬프트")[:TITLE_MAX]


def _fill(s: PromptSession, title: str, system: str, prompt: str, temperature: Optional[float], backends: list[PromptBackend]) -> None:
    """title 이 비었거나 프롬프트로 지은 제목을 그대로 보냈으면 새 프롬프트로 다시 짓는다 (작가가 적은 제목만 남는다)."""
    auto = s.title == title_of(s.prompt)
    s.system, s.prompt = system[:TEXT_MAX], prompt[:TEXT_MAX]
    s.temperature = clean_temperature(temperature)
    s.backends = clean_backends(backends)
    title = title.strip()
    s.title = (title if title and not (auto and title == s.title) else title_of(s.prompt))[:TITLE_MAX]


def create(title: str = "", system: str = "", prompt: str = "", temperature: Optional[float] = None,
           backends: Optional[list[PromptBackend]] = None) -> PromptSession:
    s = PromptSession(id=uuid.uuid4().hex[:12])
    _fill(s, title, system, prompt, temperature, s.backends if backends is None else backends)
    return save(s)


def update(sid: str, title: str, system: str, prompt: str, temperature: Optional[float], backends: list[PromptBackend]) -> PromptSession:
    s = load(sid)
    _fill(s, title, system, prompt, temperature, backends)
    return save(s)


def delete(sid: str) -> None:
    path = _path(sid)
    if not path.exists():
        raise _missing(sid)
    path.unlink()


def duplicate(sid: str) -> PromptSession:
    """프롬프트 · 백엔드만 복사한 새 세션. 시도는 옮기지 않는다."""
    s = load(sid)
    return save(PromptSession(id=uuid.uuid4().hex[:12], title=f"{s.title} 사본"[:TITLE_MAX], system=s.system, prompt=s.prompt,
                              temperature=s.temperature, backends=[b.model_copy() for b in s.backends]))


# ---------- 시도 ----------

def room(s: PromptSession) -> None:
    if len(s.trials) >= MAX_TRIALS:
        raise ValueError(f"시도는 세션마다 {MAX_TRIALS}개까지 남겨요. 지울 시도를 고르거나 세션을 복제해 새로 시작하세요")


def can_run(s: PromptSession) -> None:
    if not s.prompt.strip():
        raise ValueError("요청 프롬프트를 적어 주세요")
    if not s.backends:
        raise ValueError("돌릴 백엔드를 하나 이상 골라 주세요")
    room(s)


def find(s: PromptSession, no: int) -> PromptTrial:
    t = next((x for x in s.trials if x.no == no), None)
    if t is None:
        raise KeyError(f"{no}번 시도가 없어요")
    return t


def run_cost(provider: str, model: str, tokens: Optional[dict]) -> Optional[float]:
    """가격표(usage.rate)로 어림한 USD. 토큰 요금을 매기지 않는 백엔드는 0, 가격 · 토큰을 모르면 None."""
    if provider not in usage.PRICED:
        return 0.0
    p = usage.rate(model)
    if p is None or not tokens:
        return None
    tin = tokens.get("prompt_tokens") or 0
    tout = (tokens.get("completion_tokens") or 0) + (tokens.get("thought_tokens") or 0)
    return usage.cost(p, tin, tout, tokens.get("cached_tokens") or 0)


def to_run(b: PromptBackend, row: dict) -> PromptRun:
    tokens = row.get("usage") or {}
    return PromptRun(backend=row.get("backend", research.label(research.Backend(**b.model_dump()))), model=row.get("model", ""),
                     ok=bool(row.get("ok")), text=row.get("text", ""), error=row.get("error", ""), seconds=row.get("seconds", 0.0),
                     chars=row.get("chars", 0), tokens_in=tokens.get("prompt_tokens") or 0,
                     tokens_out=(tokens.get("completion_tokens") or 0) + (tokens.get("thought_tokens") or 0),
                     cost=run_cost(b.provider, row.get("model", ""), tokens) if row.get("ok") else None)


def run(s: PromptSession) -> list[PromptRun]:
    """지금 프롬프트를 고른 백엔드마다 차례로 보낸다. 세션은 바꾸지 않는다 (저장 직전에 다시 읽어 add_trial 로 붙인다)."""
    can_run(s)
    rows = research.sample([research.Backend(**b.model_dump()) for b in s.backends], s.system, s.prompt, s.temperature)
    return [to_run(b, r) for b, r in zip(s.backends, rows)]


def add_trial(s: PromptSession, system: str, prompt: str, temperature: Optional[float], runs: list[PromptRun]) -> PromptTrial:
    room(s)
    t = PromptTrial(no=max((x.no for x in s.trials), default=0) + 1, at=_now(), system=system, prompt=prompt, temperature=temperature, runs=runs)
    s.trials.append(t)
    return t


def edit(s: PromptSession, no: int, star: Optional[bool] = None, note: Optional[str] = None) -> PromptTrial:
    t = find(s, no)
    if star is not None:
        t.star = star
    if note is not None:
        t.note = note.strip()[:NOTE_MAX]
    return t


def remove(s: PromptSession, no: int) -> None:
    find(s, no)
    s.trials = [x for x in s.trials if x.no != no]


def restore(s: PromptSession, no: int) -> PromptSession:
    """그 시도의 프롬프트 · 온도를 지금 칸으로 되돌린다. 백엔드는 그대로 둔다."""
    t = find(s, no)
    s.system, s.prompt, s.temperature = t.system, t.prompt, t.temperature
    return s


# ---------- 화면 ----------

def summary(s: PromptSession) -> dict:
    costs = [r.cost for t in s.trials for r in t.runs if r.cost is not None]
    return {"id": s.id, "title": s.title, "trials": len(s.trials), "stars": sum(t.star for t in s.trials),
            "backends": [research.label(research.Backend(**b.model_dump())) for b in s.backends],
            "cost": round(sum(costs), 6), "updated_at": s.updated_at}


def view(s: PromptSession) -> dict:
    return {**s.model_dump(), **{"summary": summary(s)}}


def limits() -> dict:
    return {"providers": list(PROVIDERS), "max_backends": MAX_BACKENDS, "max_trials": MAX_TRIALS, "text_max": TEXT_MAX,
            "temperature": list(TEMPERATURE)}
