"""연구 도구: 모델 서버 점검, 샘플 생성 비교, 단계 시험, 컨텍스트 크기, 블라인드 비교, 실험 기록.

작품 데이터(project.json)와 분리한다. 실험 결과는 projects/<이름>/research/log.jsonl 에,
블라인드 비교본은 projects/<이름>/compare/ 에 둔다. 블라인드 비교에서 본문으로 채택할 때만 작품이 바뀐다.
웹 연구 화면과 CLI compare 명령이 이 함수들을 같이 쓴다.
"""
from __future__ import annotations

import json
import random
import re
import socket
import time
import urllib.error
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from . import context, metrics, pipeline, prompts, settings, store
from .judge import make_judge
from .llm import LLM, GeminiLLM, LocalLLM, make_llm
from .schema import ConsistencyReport, PlantSet, Project

CHARS_PER_TOKEN = context.CHARS_PER_TOKEN
JSON_OUTPUT_RESERVE = 2000  # 검수, 상태 변경안 출력에 남겨 둘 토큰 (추정)
STAGES = {"setup": "설정 제안", "style": "문체 분석", "arc": "기승전결"}
_RANGE_RE = re.compile(r"(-?\d+(?:\.\d+)?)[^\d~-]{0,10}~\s*(-?\d+(?:\.\d+)?)")


class Backend(BaseModel):
    """실험에 쓸 백엔드. model, url 이 비면 설정 화면 값을 쓴다."""
    provider: str = "local"
    model: str = ""
    url: str = ""


def label(b: Backend) -> str:
    return f"{b.provider}:{b.model}" if b.model else b.provider


def make_backend(b: Backend, temperature: float | None = None) -> LLM:
    if b.provider == "local":
        sampling = settings.local_sampling()
        if temperature is not None:
            sampling = {**sampling, "temperature": temperature}
        return LocalLLM(base_url=b.url or None, model=b.model or None, sampling=sampling)
    if b.provider == "gemini":
        return GeminiLLM(model=b.model or None)
    if b.provider == "mock":
        return make_llm("mock")
    raise ValueError(f"알 수 없는 백엔드: {b.provider} (gemini | local | mock)")


def _model_name(llm: LLM) -> str:
    return getattr(llm, "model", "") or "mock"


# ---------- 기록 ----------

def _log_path(name: str) -> Path:
    return store.project_dir(name) / "research" / "log.jsonl"


def record(name: str, kind: str, data: dict) -> dict:
    entry = {"id": uuid.uuid4().hex[:8], "time": datetime.now().isoformat(timespec="seconds"), "kind": kind, **data}
    path = _log_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def history(name: str, limit: int = 30) -> list[dict]:
    path = _log_path(name)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in reversed(lines[-limit:])]


# ---------- 서버 점검 ----------

def probe(url: str = "", key: str | None = None) -> dict:
    """로컬 서버의 모델 목록, 컨텍스트 길이, 서버 종류. 생성 호출은 하지 않는다."""
    llm = LocalLLM(base_url=url or None, api_key=key)
    t = time.perf_counter()
    try:
        info = llm.server_info()
    except RuntimeError as e:
        raise RuntimeError(_probe_reason(llm.base_url, e)) from e
    info["seconds"] = round(time.perf_counter() - t, 2)
    return info


def _probe_reason(url: str, e: RuntimeError) -> str:
    """연결 실패의 원인을 고칠 곳으로 바꿔 말한다 (Errno 같은 내부 문구 대신). HTTP 오류는 서버 답을 그대로 둔다."""
    cause = e.__cause__
    if not isinstance(cause, urllib.error.URLError) or isinstance(cause, urllib.error.HTTPError):
        return str(e)
    reason = cause.reason
    if isinstance(reason, ConnectionRefusedError):
        why = "서버가 꺼져 있거나 주소의 포트가 틀렸어요. 서버를 켜고 주소를 확인하세요"
    elif isinstance(reason, socket.gaierror):
        why = "주소의 서버 이름을 찾지 못했어요. 호스트 이름이나 IP를 확인하세요"
    elif isinstance(reason, (TimeoutError, socket.timeout)):
        why = "서버가 응답하지 않아요. 방화벽이 막고 있거나 주소가 틀렸을 수 있어요"
    elif isinstance(reason, OSError) and "No route to host" in str(reason):
        why = "그 주소로 가는 길이 없어요. 같은 네트워크에 있는지, 방화벽을 확인하세요"
    else:
        why = f"연결하지 못했어요 ({reason})"
    return f"{url} 에 연결하지 못했어요. {why}"


# ---------- 샘플 생성 ----------

def sample(runs: list[Backend], system: str, prompt: str, temperature: float | None = None) -> list[dict]:
    """같은 요청을 백엔드마다 차례로 보낸다. 한 쪽이 실패해도 나머지는 돌린다."""
    out = []
    for b in runs:
        row: dict[str, Any] = {"backend": label(b)}
        t = time.perf_counter()
        try:
            llm = make_backend(b, temperature)
            text = llm.text(system, prompt)
            m = metrics.measure(text)
            row.update(ok=True, model=_model_name(llm), text=text, chars=len(text), usage=getattr(llm, "last_usage", None),
                       sentence_len_mean=m.sentence_len_mean, dialogue_ratio=m.dialogue_ratio, mattr=m.mattr)
        except Exception as e:  # 백엔드마다 오류 종류가 달라 메시지만 남긴다
            row.update(ok=False, error=f"{type(e).__name__}: {e}")
        row["seconds"] = round(time.perf_counter() - t, 2)
        out.append(row)
    return out


# ---------- 단계 시험 ----------

def empty_fields(obj: Any, path: str = "") -> list[str]:
    """빈 문자열, 빈 목록인 필드 경로. 모델이 스키마 필드를 건너뛰었는지 본다."""
    if isinstance(obj, BaseModel):
        obj = obj.model_dump()
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in empty_fields(v, f"{path}.{k}" if path else k)]
    if isinstance(obj, list):
        if not obj:
            return [path]
        return [p for i, v in enumerate(obj) for p in empty_fields(v, f"{path}[{i}]")]
    return [path] if obj == "" else []


def count_fields(obj: Any) -> int:
    if isinstance(obj, BaseModel):
        obj = obj.model_dump()
    if isinstance(obj, dict):
        return sum(count_fields(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(count_fields(v) for v in obj) or 1
    return 1


def out_of_range(m: BaseModel | type[BaseModel], data: Any = None, path: str = "") -> list[str]:
    """설명에 'a ~ b' 로 적힌 숫자 필드가 범위를 벗어났는지.

    스키마 검증이 범위 밖 값을 잘라 넣으므로(schema._clamp) 모델이 실제로 낸 값을 보려면
    검증 전 원본 JSON(data)을 넘긴다. data 가 없으면 인스턴스의 현재 값을 본다.
    """
    cls = m if isinstance(m, type) else type(m)
    if data is None:
        data = m.model_dump() if isinstance(m, BaseModel) else {}
    if not isinstance(data, dict):
        return []
    found = []
    for name, field in cls.model_fields.items():
        if name not in data:
            continue
        v, here = data[name], f"{path}.{name}" if path else name
        sub = _model_of(field.annotation)
        if sub and isinstance(v, dict):
            found += out_of_range(sub, v, here)
        elif sub and isinstance(v, list):
            for i, x in enumerate(v):
                found += out_of_range(sub, x, f"{here}[{i}]")
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and field.description:
            r = _RANGE_RE.search(field.description)
            if r and not float(r.group(1)) <= v <= float(r.group(2)):
                found.append(f"{here}={v} (범위 {r.group(1)}~{r.group(2)})")
    return found


def _model_of(annotation: Any) -> type[BaseModel] | None:
    """BaseModel 이거나 list[BaseModel] 이면 그 모델 클래스."""
    from typing import get_args

    for t in (annotation, *get_args(annotation)):
        if isinstance(t, type) and issubclass(t, BaseModel):
            return t
    return None


def _raw(llm: Any) -> Any:
    """검증 전 원본 JSON (로컬 백엔드만 남긴다). 없으면 None."""
    try:
        return json.loads(getattr(llm, "last_raw", None) or "null")
    except ValueError:
        return None


def stage_trial(p: Project, b: Backend, stage: str, sample_text: str = "") -> dict:
    """계획 단계를 저장 없이 돌려 빈 필드, 범위 밖 값, 재시도 횟수를 본다."""
    if stage not in STAGES:
        raise ValueError(f"알 수 없는 단계: {stage} ({' | '.join(STAGES)})")
    if stage == "style":
        sample_text = sample_text.strip() or "\n\n".join(p.style.sample_passages)
        if not sample_text:
            raise ValueError("문체 분석에 쓸 원문이 없어요. 원문을 붙여 넣거나 문체 레퍼런스를 먼저 채우세요")
    row: dict[str, Any] = {"backend": label(b), "stage": stage}
    t = time.perf_counter()
    try:
        llm = make_backend(b)
        if stage == "setup":
            result: BaseModel = pipeline.suggest_setup(llm, p)
        elif stage == "style":
            result = pipeline.analyze_style(llm, sample_text)
        else:
            result = pipeline.plan_arc(llm, p)
        empty = empty_fields(result)
        row.update(ok=True, model=_model_name(llm), attempts=getattr(llm, "last_attempts", 1) or 1,
                   usage=getattr(llm, "last_usage", None), fields=count_fields(result), empty=empty,
                   out_of_range=out_of_range(type(result), _raw(llm)) or out_of_range(result),
                   result=result.model_dump())
    except Exception as e:
        row.update(ok=False, error=f"{type(e).__name__}: {e}")
    row["seconds"] = round(time.perf_counter() - t, 2)
    return row


# ---------- 컨텍스트 크기 ----------

def _filler(p: Project, length: int) -> str:
    """아직 안 쓴 화의 자리를 채울 글. 쓴 본문이나 문체 예시를 이어 붙여 토큰 비율을 실제와 비슷하게 맞춘다."""
    src = "\n\n".join(e.text for e in p.episodes if e.text) or "\n\n".join(p.style.sample_passages) or "가나다라마바사. "
    return (src * (length // max(len(src), 1) + 1))[:length]


def budget(p: Project, b: Backend) -> dict:
    """화별 프롬프트 크기를 모델 컨텍스트 한도와 비교한다.

    본문이 있는 화는 실제 프롬프트를 잰다. 아직 안 쓴 화는 앞선 화가 모두 목표 분량으로 쓰였다고 가정해 잰다.
    """
    llm = make_backend(b)
    try:
        limit = llm.context_limit() if hasattr(llm, "context_limit") else None
    except Exception:
        limit = None
    counter = getattr(llm, "count_tokens", None)
    probe_ok = True

    def tokens(text: str) -> tuple[int, bool]:
        nonlocal probe_ok
        if counter and probe_ok:
            try:
                n = counter(text)
            except Exception:
                n = None
            if n is not None:
                return n, True
            probe_ok = False  # 토크나이저가 없으면 다시 묻지 않는다
        return round(len(text) / CHARS_PER_TOKEN), False

    length = p.meta.words_per_episode
    proj = p.model_copy(deep=True)
    for e in proj.episodes:
        if not e.text:
            e.text = _filler(p, length)
    out_tokens = tokens(_filler(p, length))[0]
    rows = []
    for e in p.episodes:
        n = e.plot.number
        real = bool(e.text)
        src = p if real else proj
        row: dict[str, Any] = {"episode": n, "status": e.status, "measured": real}
        for kind, system, fn, reserve in (("write", prompts.writer_system(p), prompts.episode_prompt, out_tokens),
                                          ("check", prompts.SYSTEM_CHECKER, prompts.check_prompt, JSON_OUTPUT_RESERVE),
                                          ("state", prompts.SYSTEM_EDITOR, prompts.state_prompt, JSON_OUTPUT_RESERVE)):
            text = system + fn(src, n)
            t, exact = tokens(text)
            # over: 입력만으로 넘침 (서버가 400 을 낸다). tight: 출력 여유까지 더하면 넘침 (출력이 잘릴 수 있다)
            row[kind] = {"chars": len(text), "tokens": t, "exact": exact, "total": t + reserve,
                         "over": bool(limit and t > limit), "tight": bool(limit and t + reserve > limit),
                         "blocks": context.blocks(text, 6)}
        rows.append(row)
    def first(flag: str) -> int | None:
        return next((r["episode"] for r in rows if any(r[k][flag] for k in ("write", "check", "state"))), None)

    return {"backend": label(b), "model": _model_name(llm), "limit": limit, "write_reserve": out_tokens,
            "json_reserve": JSON_OUTPUT_RESERVE, "tokenizer": probe_ok and counter is not None,
            "first_over": first("over"), "first_tight": first("tight"), "rows": rows}


# ---------- 검수 시험 ----------
# 본문에 모순을 몇 개 심고 검수 방식(prompts.CHECK_MODES)마다 찾아내는지 본다. 장편 검수는 입력을 줄인 budget 이
# 기본이라, 줄인 만큼 놓치는 것이 없는지 실제 모델로 확인하려는 것. 작품 데이터는 바꾸지 않는다.

HIT_OVERLAP = 0.5  # 검수가 짚은 문장이 심은 문장의 글 조각을 이만큼 덮으면 찾은 것으로 본다


def _hit(found: str, planted: str) -> bool:
    g = context.grams(planted)
    return bool(g) and len(context.grams(found) & g) / len(g) >= HIT_OVERLAP


TRIAL_MODES = {**prompts.CHECK_MODES,
               "widen": "budget 검수 뒤 진술마다 옛 화를 더 찾아, 첫 검수에 없던 단락이 근거로 나온 진술만 다시 판정 (검수 넓히기)",
               "twostep": "진술 뽑기 → 판단기가 옛 화 전부와 견줘 거르기 → 의심만 검수 모델이 판정 (판단기 시험)"}


def check_trial(p: Project, n: int, b: Backend, plants: int = 3, modes: list[str] | None = None, seed: int | None = None,
                judge: Backend | None = None) -> dict:
    """모순 plants 개를 심은 n화를 검수 방식마다 검수한다. 심은 것과 검수 호출은 같은 백엔드를 쓴다.
    장편은 검수 넓히기(widen)도 기본으로 돌린다. judge 를 주면 두 걸음 검수(twostep)도 돌린다. 판단기는 local 또는 mock."""
    ep = p.episode(n)
    if not ep.text:
        raise ValueError(f"{n}화 본문이 없어요")
    modes = modes or list(prompts.CHECK_MODES) + (["widen"] if p.serial else []) + (["twostep"] if judge else [])
    bad = [m for m in modes if m not in TRIAL_MODES]
    if bad:
        raise ValueError(f"알 수 없는 검수 방식: {', '.join(bad)} ({' | '.join(TRIAL_MODES)})")
    if "twostep" in modes and judge is None:
        judge = Backend(provider="mock" if b.provider == "mock" else "local")
    seed = random.randrange(1 << 30) if seed is None else seed
    llm = make_backend(b)
    t = time.perf_counter()
    plan = llm.json(prompts.SYSTEM_PLANTER, prompts.plant_prompt(p, n, plants, seed), PlantSet,
                    hint={"episode": n, "count": plants, "text": ep.text})
    q = p.model_copy(deep=True)
    text, used, skipped = ep.text, [], []
    for x in plan.items:
        if x.quote and x.replacement and x.replacement != x.quote and x.quote in text:
            text = text.replace(x.quote, x.replacement, 1)
            used.append(x)
        else:
            skipped.append(x.quote)
    if not used:
        raise ValueError("모델이 본문 문장을 그대로 옮기지 않아 모순을 심지 못했어요. 다시 시험해 보세요")
    q.episode(n).text = text
    planted = [{**x.model_dump(), "distance": n - x.source_episode if x.source_episode else None} for x in used]
    runs = []
    for mode in modes:
        if mode == "twostep":
            runs.append(_two_step_run(llm, judge, q, n, used))
            continue
        prompt = prompts.check_prompt(q, n, "budget" if mode == "widen" else mode)
        row: dict[str, Any] = {"mode": mode, "chars": len(prompt), "tokens": context.est_tokens(prompts.SYSTEM_CHECKER + prompt)}
        t1 = time.perf_counter()
        try:
            rep = llm.json(prompts.SYSTEM_CHECKER, prompt, ConsistencyReport,
                           hint={"episode": n, "plants": [x.replacement for x in used]})
            if mode == "widen":  # tokens 는 첫 검수 + 진술 뽑기 + 다시 묻기 (추정)
                first_found = [any(_hit(i.current_quote, x.replacement) for i in rep.issues) for x in used]
                rep, st = pipeline.widen_check(llm, q, n, rep, hint={"plants": [x.replacement for x in used]})
                # 심은 문장이 다시 묻는 진술에 들었는지 (넓혀 찾기가 그 문장의 근거를 새로 찾았는지)
                raised = [any(r["widened"] and _hit(r["quote"], x.replacement) for r in st["rows"]) for x in used]
                row.update(first_found=first_found, raised=raised, **st)
                row["tokens"] += st["claims_tokens"] + st["verdict_tokens"]
            hits = [any(_hit(i.current_quote, x.replacement) for i in rep.issues) for x in used]
            extra = [i.model_dump() for i in rep.issues if not any(_hit(i.current_quote, x.replacement) for x in used)]
            row.update(ok=True, hits=hits, found=sum(hits), other=extra, usage=getattr(llm, "last_usage", None))
        except Exception as e:  # 한 방식이 실패해도 다른 방식은 돌린다
            row.update(ok=False, error=f"{type(e).__name__}: {e}")
        row["seconds"] = round(time.perf_counter() - t1, 2)
        runs.append(row)
    return {"backend": label(b), "model": _model_name(llm), "episode": n, "seed": seed, "planted": planted,
            "skipped": skipped, "runs": runs, "seconds": round(time.perf_counter() - t, 2),
            "judge": label(judge) if judge and "twostep" in modes else None}


def _two_step_run(llm: LLM, jb: Backend, q: Project, n: int, used: list) -> dict:
    """두 걸음 검수 한 번. tokens 는 검수 모델 입력(진술 뽑기 + 의심 판정), judge_tokens 는 판단기 입력 (모두 추정)."""
    row: dict[str, Any] = {"mode": "twostep", "judge": label(jb)}
    t1 = time.perf_counter()
    try:
        jg = make_judge(jb.provider, jb.model or None, jb.url or None, contradicts=[x.replacement for x in used])
        rep, st = pipeline.check_two_step(llm, jg, q, n, hint={"plants": [x.replacement for x in used]})
        hits = [any(_hit(i.current_quote, x.replacement) for i in rep.issues) for x in used]
        extra = [i.model_dump() for i in rep.issues if not any(_hit(i.current_quote, x.replacement) for x in used)]
        # 판단기가 심은 문장을 의심으로 올렸는지 (검수 모델이 놓쳤어도 판단기 단계에서 걸렀는지 본다)
        raised = [any(j["flagged"] and _hit(j["quote"], x.replacement) for j in st["judged"]) for x in used]
        row.update(ok=True, hits=hits, found=sum(hits), other=extra, raised=raised,
                   tokens=st["first_tokens"] + st["verdict_tokens"], **st)
    except Exception as e:
        row.update(ok=False, error=f"{type(e).__name__}: {e}")
    row["seconds"] = round(time.perf_counter() - t1, 2)
    return row


# ---------- 블라인드 비교 ----------

def compare_dir(name: str, n: int) -> Path:
    return store.project_dir(name) / "compare" / f"{n:02d}"


def run_compare(name: str, p: Project, n: int, a: Backend, b: Backend) -> dict:
    """같은 화를 두 백엔드로 쓰고 1, 2 번으로 가려 저장한다. 프롬프트는 write_episode 와 같다."""
    la, lb = label(a), label(b)
    if la == lb and a.url == b.url:
        raise ValueError("두 백엔드가 같아요")
    drafts = pipeline.compare_drafts({la: make_backend(a), lb: make_backend(b)}, p, n)
    return save_compare(name, n, drafts)


def run_opening_compare(name: str, p: Project, n: int, llm: LLM, approaches: list[str] | None = None) -> dict:
    """1~3화를 여는 방식마다 하나씩 써서 가려 저장한다. 고르기 전에는 어느 방식인지 보이지 않는다."""
    return save_compare(name, n, pipeline.opening_drafts(llm, p, n, approaches), kind="opening")


def save_compare(name: str, n: int, drafts: dict[str, str], kind: str = "backend") -> dict:
    """kind: backend(백엔드 비교) 또는 opening(여는 방식 비교)."""
    order = random.sample(list(drafts), len(drafts))  # 1, 2 번에 누가 들어갔는지 가린다
    out = compare_dir(name, n)
    out.mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("*.md"), *out.glob("hook-*.json")]:
        old.unlink()  # 앞 비교의 남은 안과 판정이 새 번호에 섞이지 않게
    for i, key in enumerate(order, 1):
        (out / f"{i}.md").write_text(drafts[key], encoding="utf-8")
    (out / "key.json").write_text(json.dumps({"order": order, "kind": kind, "created": datetime.now().isoformat(timespec="seconds")},
                                             ensure_ascii=False), encoding="utf-8")
    return load_compare(name, n)


def load_compare(name: str, n: int) -> dict | None:
    """비교본과 지표. 고르기 전에는 어느 백엔드인지 돌려주지 않는다."""
    out = compare_dir(name, n)
    key = out / "key.json"
    if not key.exists():
        return None
    k = json.loads(key.read_text(encoding="utf-8"))
    p = store.load(name)
    base = pipeline.style_baseline(p)
    drafts = []
    for i in range(1, len(k["order"]) + 1):
        text = (out / f"{i}.md").read_text(encoding="utf-8")
        m = metrics.measure(text, p.style.banned_phrases)
        hook = out / f"hook-{i}.json"
        drafts.append({"n": i, "text": text, "chars": m.chars, "sentence_len_mean": m.sentence_len_mean,
                       "dialogue_ratio": m.dialogue_ratio, "mattr": m.mattr, "warnings": metrics.drift(base, m),
                       "opening": pipeline.opening_metrics(p, n, text)[1] if prompts.is_opening(n) else [],
                       "hook": json.loads(hook.read_text(encoding="utf-8")) if hook.exists() else None})
    res = {"episode": n, "kind": k.get("kind", "backend"), "created": k.get("created"), "drafts": drafts, "picked": k.get("picked")}
    if k.get("picked"):
        res["order"] = k["order"]
    return res


def compare_text(name: str, n: int, k: int) -> str:
    path = compare_dir(name, n) / f"{k}.md"
    if not path.exists():
        raise ValueError(f"{n}화 비교본 {k}번이 없어요")
    return path.read_text(encoding="utf-8")


def save_compare_hook(name: str, n: int, k: int, report: BaseModel) -> None:
    """비교본 하나의 흡입력 판정. 다음 비교를 만들면 지운다."""
    (compare_dir(name, n) / f"hook-{k}.json").write_text(report.model_dump_json(), encoding="utf-8")


def pick_compare(name: str, p: Project, n: int, k: int, adopt: bool = True) -> dict:
    """고른 번호를 공개하고 compare/log.jsonl 에 누적한다. adopt 면 그 본문을 그 화 본문으로 쓴다 (저장은 호출자)."""
    out = compare_dir(name, n)
    key_path = out / "key.json"
    if not key_path.exists():
        raise ValueError(f"{n}화 비교본이 없어요. 비교를 먼저 실행하세요")
    key = json.loads(key_path.read_text(encoding="utf-8"))
    order = key["order"]
    if not 1 <= k <= len(order):
        raise ValueError(f"고를 수 있는 번호는 1~{len(order)} 이에요")
    if adopt:
        pipeline.adopt_draft(p, n, (out / f"{k}.md").read_text(encoding="utf-8"))
    key["picked"] = k
    key_path.write_text(json.dumps(key, ensure_ascii=False), encoding="utf-8")
    log = out.parent / "log.jsonl"
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"episode": n, "kind": key.get("kind", "backend"), "options": order, "picked": order[k - 1],
                            "time": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
    wins: dict[str, int] = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        prov = json.loads(line)["picked"]
        wins[prov] = wins.get(prov, 0) + 1
    return {"picked": order[k - 1], "others": [o for o in order if o != order[k - 1]], "order": order,
            "adopted": adopt, "wins": wins}
