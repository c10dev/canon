"""프롬프트 놀이터: 시스템 · 요청 프롬프트를 직접 써서 여러 백엔드로 돌리고, 결과 · 시간 · 토큰 · 어림 비용을 시도로 남겨 견준다.

작품(project.json)과 상관없고 세션 파일 <CANON_HOME>/.promptlab/<id>.json 에 둔다 (CANON_PROMPTLAB 으로 경로 변경, 문단 연습장처럼 작품 밖).
호출은 연구 화면의 샘플 생성(research.sample)을 그대로 쓴다. 백엔드는 gemini · local · mock 이고, 한 쪽이 실패해도 나머지는 돌린다.
'불러오기'는 Canon 의 실제 프롬프트를 작업지시서와 같은 함수(prompts.brief_parts)로 조립해 칸에 채운다.
재료는 예시 작품(mock LLM 으로 만든, 저장하지 않는 작품)이나 작가가 고른 작품이고, 작품은 읽기만 한다.
시도마다 그때의 프롬프트를 함께 남겨, 고치기 전 판으로 되돌아가거나 판끼리 견줄 수 있다.
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import prompts, research, store, usage
from .schema import Project, PromptBackend, PromptRun, PromptSession, PromptSource, PromptTrial

ID_RE = re.compile(r"^[0-9a-f]{8,32}$")
NAME_RE = re.compile(r'^[^/\\.:*?"<>|][^/\\:*?"<>|]{0,63}$')  # 작품 폴더 이름 (web.NAME_RE 와 같다)
PROVIDERS = ("gemini", "local", "mock")
MAX_BACKENDS = 4  # 한 번에 돌리는 백엔드 수. 차례로 부르므로 많으면 오래 걸린다
MAX_TRIALS = 40  # 세션마다 남기는 시도. 저절로 지우지 않고, 차면 작가가 지울 시도를 고른다
TEXT_MAX = 300000  # 시스템 · 요청 프롬프트 한 칸의 글자 수 상한 (검수 프롬프트는 앞 화 본문을 다 넣어 길다)
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


def add_trial(s: PromptSession, system: str, prompt: str, temperature: Optional[float], runs: list[PromptRun],
              source: Optional[PromptSource] = None) -> PromptTrial:
    """source 는 돌릴 때 칸을 불러온 출처. 지문이 다르면 고쳐 돌린 것으로 적는다."""
    room(s)
    t = PromptTrial(no=max((x.no for x in s.trials), default=0) + 1, at=_now(), system=system, prompt=prompt, temperature=temperature, runs=runs,
                    source=source.model_copy() if source else None, source_edited=bool(source) and source.sig != sig(system, prompt))
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
    """그 시도의 프롬프트 · 온도 · 출처를 지금 칸으로 되돌린다. 백엔드는 그대로 둔다."""
    t = find(s, no)
    s.system, s.prompt, s.temperature = t.system, t.prompt, t.temperature
    s.source = t.source.model_copy() if t.source else None
    return s


# ---------- Canon 프롬프트 불러오기 ----------

EXAMPLE_TITLE = "예시 작품"
# 예시 작품에서 갈래마다 조립하는 화. 1 · 2화는 본문을 쓰고 상태까지 반영했고, 3화는 플롯만 확정했다
EXAMPLE_N = {"episode": 3, "plot": 3, "check": 2, "state": 2}
_example: Optional[Project] = None


def sig(system: str, prompt: str) -> str:
    return hashlib.sha1(f"{system}\0{prompt}".encode()).hexdigest()[:12]


def example_project() -> Project:
    """mock LLM 으로 만든 6화 단편(저장하지 않음). 한 번 만들어 두고, 쓸 때마다 사본을 준다."""
    global _example
    if _example is None:
        from . import pipeline
        from .mock import MockLLM

        llm, p = MockLLM(), Project()
        p.meta.title, p.meta.target_episodes = EXAMPLE_TITLE, 6
        pipeline.apply_setup(p, pipeline.suggest_setup(llm, p))
        p.arc = pipeline.plan_arc(llm, p).acts
        pipeline.apply_plots(p, pipeline.draft_plots(llm, p, 1, 6))
        for n in (1, 2):
            pipeline.confirm_plot(p, n)
            p.episode(n).text = pipeline.write_episode(llm, p, n)
            p.episode(n).status = "written"
            pipeline.apply_delta(p, pipeline.extract_state(llm, p, n))
        pipeline.confirm_plot(p, 3)
        _example = p
    return _example.model_copy(deep=True)


def _project(name: str) -> Project:
    if not name:
        return example_project()
    if not NAME_RE.match(name) or not store.exists(name):
        raise KeyError(f"작품을 찾을 수 없어요: {name}")
    return store.load(name)  # 읽기만 한다. 저장하지 않는다


def default_n(p: Project, kind: str) -> int:
    """갈래마다 조립할 화의 기본값. 본문이 있어야 하는 갈래는 본문이 있는 마지막 화, 나머지는 본문이 없는 첫 화."""
    nums = sorted(e.plot.number for e in p.episodes)
    written = [e.plot.number for e in p.episodes if e.text]
    if prompts.BRIEF_KINDS[kind][1]:
        return max(written, default=0)
    return next((n for n in nums if n not in written), nums[-1] if nums else 0)


def sources(project: str = "") -> dict:
    """불러오기 고르기 칸: 갈래 목록과 그 작품의 화(본문이 있는지)와 갈래별 기본 화."""
    p = _project(project)
    kinds = [{"id": k, "label": label, "needs_text": need} for k, (label, need) in prompts.BRIEF_KINDS.items()]
    eps = [{"n": e.plot.number, "title": e.plot.title, "has_text": bool(e.text)} for e in sorted(p.episodes, key=lambda e: e.plot.number)]
    defaults = EXAMPLE_N if not project else {k: default_n(p, k) for k in prompts.BRIEF_KINDS}
    return {"project": project, "title": p.meta.title or project, "kinds": kinds, "episodes": eps, "defaults": defaults}


def load_prompt(s: PromptSession, kind: str, project: str = "", n: int = 0) -> PromptSession:
    """Canon 프롬프트를 조립해 시스템 · 요청 칸에 채우고 출처를 남긴다. 작품은 읽기만 한다."""
    if kind not in prompts.BRIEF_KINDS:
        raise ValueError(f"모르는 프롬프트 갈래예요: {kind}")
    p = _project(project)
    n = n or (EXAMPLE_N[kind] if not project else default_n(p, kind))
    try:
        p.episode(n)
    except KeyError:
        raise ValueError(f"{n}화 플롯이 없어 프롬프트를 만들 수 없어요") from None
    label, need = prompts.BRIEF_KINDS[kind]
    if need and not p.episode(n).text:
        raise ValueError(f"{n}화 본문이 없어 {label} 프롬프트를 만들 수 없어요")
    system, prompt = prompts.brief_parts(p, n, kind)
    label = f"{prompts.BRIEF_KINDS[kind][0]} · {p.meta.title or project or EXAMPLE_TITLE} {n}화"
    if max(len(system), len(prompt)) > TEXT_MAX:
        raise ValueError(f"조립한 프롬프트가 {TEXT_MAX:,}자를 넘어 불러올 수 없어요. 앞쪽 화를 고르세요")
    if s.title == title_of(s.prompt):  # 요청 첫 줄로 지은 제목이면 불러온 프롬프트 이름으로 (작가가 적은 제목은 남긴다)
        s.title = label[:TITLE_MAX]
    s.system, s.prompt = system, prompt
    s.source = PromptSource(kind=kind, label=label, project=project, n=n, sig=sig(s.system, s.prompt))
    return s


# ---------- 화면 ----------

def summary(s: PromptSession) -> dict:
    costs = [r.cost for t in s.trials for r in t.runs if r.cost is not None]
    return {"id": s.id, "title": s.title, "trials": len(s.trials), "stars": sum(t.star for t in s.trials),
            "backends": [research.label(research.Backend(**b.model_dump())) for b in s.backends],
            "cost": round(sum(costs), 6), "updated_at": s.updated_at}


def view(s: PromptSession) -> dict:
    edited = bool(s.source) and s.source.sig != sig(s.system, s.prompt)
    return {**s.model_dump(), **{"summary": summary(s), "source_edited": edited}}


def limits() -> dict:
    return {"providers": list(PROVIDERS), "max_backends": MAX_BACKENDS, "max_trials": MAX_TRIALS, "text_max": TEXT_MAX,
            "temperature": list(TEMPERATURE)}
