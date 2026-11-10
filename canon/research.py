"""연구 도구: 모델 서버 점검, 샘플 생성 비교, 단계 시험, 컨텍스트 크기, 블라인드 비교, 실험 기록.

작품 데이터(project.json)와 분리한다. 실험 결과는 projects/<이름>/research/log.jsonl 에,
블라인드 비교본은 projects/<이름>/compare/ 에 둔다. 블라인드 비교에서 본문으로 채택할 때만 작품이 바뀐다.
웹 연구 화면과 CLI compare 명령이 이 함수들을 같이 쓴다.
"""
from __future__ import annotations

import contextvars
import json
import random
import re
import socket
import time
import urllib.error
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from . import context, metrics, pipeline, prompts, settings, store
from .judge import env_choice, make_judge
from .llm import LLM, GeminiLLM, LocalLLM, make_llm, out_cap
from .schema import ConsistencyReport, ConsistencyReportEn, Episode, PlantSet, Project, plant_kind

CHARS_PER_TOKEN = context.CHARS_PER_TOKEN
JSON_OUTPUT_RESERVE = 2000  # 검수, 상태 변경안 출력에 남겨 둘 토큰 (추정)
STAGES = {"setup": "설정 제안", "style": "문체 분석", "arc": "기승전결"}
_RANGE_RE = re.compile(r"(-?\d+(?:\.\d+)?)[^\d~-]{0,10}~\s*(-?\d+(?:\.\d+)?)")


# 실험에서 고를 수 있는 백엔드. claude 는 설치된 Claude Code 의 구독 로그인, claude-api 는 Anthropic API 키다 (llm.make_llm)
PROVIDERS = ("gemini", "local", "claude", "claude-api", "mock")


class Backend(BaseModel):
    """실험에 쓸 백엔드. model, url 이 비면 설정 화면 값을 쓴다. provider 는 PROVIDERS 중 하나다."""
    provider: str = "local"
    model: str = ""
    url: str = ""


def label(b: Backend) -> str:
    return f"{b.provider}:{b.model}" if b.model else b.provider


def stage_defaults(b: Backend, stage: str = "", preset: dict | None = None) -> tuple[str, str]:
    """그 단계의 (모델, 추론 강도). 모델 칸을 적었으면 그 모델. 단계 모델은 그 단계 백엔드가 b 와 같을 때만 쓴다 (다른 백엔드의 모델 이름이라서).
    추론 강도는 Gemini · Claude 만 받는다(settings.provider_effort). 단계가 없으면 둘 다 빈칸(설정 값 · 모델 기본값)."""
    if not stage or b.provider == "mock":
        return b.model, ""
    model = b.model or (settings.stage_model(stage, preset)[0] if settings.stage_provider(stage, preset)[0] == b.provider else "")
    return model, settings.provider_effort(b.provider, settings.stage_effort(stage, preset)[0])


def make_backend(b: Backend, temperature: float | None = None, stage: str = "", preset: dict | None = None) -> LLM:
    """stage 를 주면 모델 칸이 빈 백엔드는 그 단계의 모델 · 추론 강도로 만든다 (stage_defaults, 프롬프트 놀이터가 불러온 갈래의 단계).
    temperature 는 Gemini · 로컬만 받는다. Claude 는 받지 않는다(Opus 5.5 는 temperature 를 400 으로 거절한다)."""
    model, effort = stage_defaults(b, stage, preset)
    if b.provider == "local":
        sampling = settings.local_sampling()
        if temperature is not None:
            sampling = {**sampling, "temperature": temperature}
        return LocalLLM(base_url=b.url or None, model=model or None, sampling=sampling)
    if b.provider == "gemini":
        return GeminiLLM(model=model or None, effort=effort, temperature=temperature)
    if b.provider in settings.CLAUDE_PROVIDERS:
        return make_llm(b.provider, model or None, effort)
    if b.provider == "mock":
        return make_llm("mock")
    raise ValueError(f"알 수 없는 백엔드: {b.provider} ({' | '.join(PROVIDERS)})")


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
    rows = [x for x in map(_row, path.read_text(encoding="utf-8").splitlines()) if x is not None]
    return rows[::-1][:limit]


def _row(line: str) -> dict | None:
    """기록 한 줄. 빈 줄이나 쓰다 끊긴 줄(프로세스가 죽었거나 두 작업이 함께 덧붙임)은 None 이라 건너뛴다."""
    if not line.strip():
        return None
    try:
        x = json.loads(line)
    except ValueError:
        return None
    return x if isinstance(x, dict) else None


def stopped_note(done: int, total: int, e: BaseException) -> str:
    """시험이 도중에 멈췄을 때 기록에 남길 말 (stattrial · blocktrial 이 그때까지 쓴 본문을 남긴다)."""
    from .cancel import Cancelled

    why = "멈췄어요" if isinstance(e, (Cancelled, KeyboardInterrupt)) else " ".join(str(e).split())[:200] or type(e).__name__
    return f"{total}개 가운데 {done}개를 쓰고 멈춤: {why}"


def latest(name: str) -> dict[str, dict]:
    """갈래(kind)마다 마지막 기록. 연구 개요와 목차가 history 한도(30개) 밖의 실험도 마지막 결과를 보이게 한다."""
    path = _log_path(name)
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    for x in map(_row, path.read_text(encoding="utf-8").splitlines()):
        if x is not None:
            out[x.get("kind", "")] = x
    return out


def open_compares(name: str) -> list[dict]:
    """아직 고르지 않은 블라인드 비교본: [{episode, kind, created, drafts}] (화 차례)."""
    root = store.project_dir(name) / "compare"
    if not root.exists():
        return []
    out = []
    keys = [k for k in root.glob("*/key.json") if k.parent.name.isdigit()]
    for key in sorted(keys, key=lambda k: int(k.parent.name)):  # 이름 차례면 100화가 99화 앞에 온다
        k = json.loads(key.read_text(encoding="utf-8"))
        if not k.get("picked"):
            out.append({"episode": int(key.parent.name), "kind": k.get("kind", "backend"), "created": k.get("created"),
                        "drafts": len(k.get("order", []))})
    return out


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

RAW_MAX = 30000  # 실패한 결과에 남기는 원문 글자 수 상한 (세션 파일이 너무 커지지 않게)


def sample(runs: list[Backend], system: str, prompt: str, temperature: float | None = None, schema: type[BaseModel] | None = None,
           stage: str = "", preset: dict | None = None, out_tokens: int = 0) -> list[dict]:
    """같은 요청을 백엔드마다 동시에 보내고, 결과는 runs 차례로 돌려준다. 한 쪽이 실패해도 나머지는 돌린다.
    schema 를 주면 실제 호출처럼 llm.json(구조화 출력)으로 받아 검증한 JSON 을 글로 돌려준다. 검증에 실패하면 그 백엔드는 실패다.
    mock 은 부른 쪽의 hint 로 응답을 지어 hint 없이는 스키마 응답을 못 만든다. 그래서 mock 은 schema 를 받아도 글로 받는다(row 의 schema 가 빈칸).
    stage 는 모델 칸이 빈 백엔드에 그 단계의 모델 · 추론 강도를 쓰게 하고(make_backend), out_tokens 는 출력 한도(llm.out_cap)다.
    스레드마다 부른 쪽의 컨텍스트 사본을 넘겨 사용량 기록(usage.scope)의 작품 · 작업 정보가 따라가게 한다."""
    if len(runs) <= 1:
        return [_sample_one(b, system, prompt, temperature, schema, stage, preset, out_tokens) for b in runs]
    with ThreadPoolExecutor(max_workers=len(runs)) as pool:
        futures = [pool.submit(contextvars.copy_context().run, _sample_one, b, system, prompt, temperature, schema, stage, preset, out_tokens)
                   for b in runs]
        return [f.result() for f in futures]


def _sample_one(b: Backend, system: str, prompt: str, temperature: float | None, schema: type[BaseModel] | None,
                stage: str, preset: dict | None, out_tokens: int) -> dict:
    """sample 의 백엔드 하나. 오류는 던지지 않고 줄에 남긴다."""
    structured = schema is not None and b.provider != "mock"  # 형식은 pipeline 이 쓰는 것과 같아 test_schema_nodict 가 따로 보지 않는다
    row: dict[str, Any] = {"backend": label(b), "schema": schema.__name__ if structured else ""}
    t = time.perf_counter()
    llm = None
    try:
        llm = make_backend(b, temperature, stage, preset)
        with out_cap(out_tokens) if out_tokens else nullcontext():
            text = llm.json(system, prompt, schema).model_dump_json(indent=2) if structured else llm.text(system, prompt)
        m = metrics.measure(text)
        row.update(ok=True, model=_model_name(llm), effort=getattr(llm, "effort", "") or "", text=text, chars=len(text),
                   usage=getattr(llm, "last_usage", None),
                   sentence_len_mean=m.sentence_len_mean, dialogue_ratio=m.dialogue_ratio, mattr=m.mattr)
    except Exception as e:  # 백엔드마다 오류 종류가 달라 메시지만 남긴다
        row.update(ok=False, error=f"{type(e).__name__}: {e}")
        # 받은 원문과 끝난 이유: 구조화 출력이 어긋나 실패했을 때 모델이 실제로 낸 글을 본다 (형식 고치기 재요청의 답)
        row.update(raw=str(getattr(llm, "last_raw", "") or "")[:RAW_MAX], finish=str(getattr(llm, "last_finish", "") or ""))
    row["seconds"] = round(time.perf_counter() - t, 2)
    return row


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
            result = pipeline.analyze_style(llm, sample_text, [c.name for c in p.characters])
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
               "twostep": "진술 뽑기 → 판단기가 옛 화 전부와 견줘 거르기 → 의심만 검수 모델이 판정 (판단기 시험)",
               "motion": "이번 화 인물 이름과 본문만 넣고 동선만 따로 찾음 (동선 따로 보기, 동선 외 갈래는 보지 않음)",
               "stage": "사건마다 본문에서 장면 연출(자리 · 자세 · 향함 · 손 · 접촉)을 뽑고 규칙 판정(stage.judge)으로 동선만 검수 (동선 외 갈래는 보지 않음)"}
TRIAL_LANGS = prompts.CHECK_LANGS  # 검수 지시문 언어. 영어판은 full · budget 에만 붙고 다른 방식은 한국어로 한 번만 돈다


def check_trial(p: Project, n: int, b: Backend, plants: int = 3, modes: list[str] | None = None, seed: int | None = None,
                judge: Backend | None = None, stage: bool = False, langs: list[str] | None = None) -> dict:
    """모순 plants 개를 심은 n화를 검수 방식마다 검수한다. 심은 것과 검수 호출은 같은 백엔드를 쓴다.
    장편은 검수 넓히기(widen)도 기본으로 돌린다. judge 를 주면 두 걸음 검수(twostep)도, stage 면 장면 연출 규칙 검수도 돌린다.
    판단기는 local 또는 mock. langs 에 en 을 넣으면 같은 사본의 full · budget 을 검수 지시문 영어판으로도 검수해 한 줄씩 더 낸다."""
    ep = p.episode(n)
    if not ep.text:
        raise ValueError(f"{n}화 본문이 없어요")
    modes = modes or list(prompts.CHECK_MODES) + (["widen"] if p.serial else []) + ["motion"] + (["twostep"] if judge else []) + (["stage"] if stage else [])
    bad = [m for m in modes if m not in TRIAL_MODES]
    if bad:
        raise ValueError(f"알 수 없는 검수 방식: {', '.join(bad)} ({' | '.join(TRIAL_MODES)})")
    langs = list(dict.fromkeys(["ko", *(langs or [])]))
    bad = [x for x in langs if x not in TRIAL_LANGS]
    if bad:
        raise ValueError(f"알 수 없는 지시문 언어: {', '.join(bad)} ({' | '.join(TRIAL_LANGS)})")
    if "twostep" in modes:
        judge = judge_backend(judge, b)
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
    planted = [{**x.model_dump(), "kind": plant_kind(x), "distance": n - x.source_episode if x.source_episode else None} for x in used]
    kinds = [x["kind"] for x in planted]
    runs = []
    for mode in modes:
        if mode == "twostep":
            runs.append(_by_kind(_two_step_run(llm, judge, q, n, used), kinds))
            continue
        if mode == "stage":
            runs.append(_by_kind(_stage_run(llm, q, n, used), kinds))
            continue
        if mode == "motion":
            runs.append(_by_kind(_motion_run(llm, q, n, used), kinds))
            continue
        for lang in langs if mode in prompts.CHECK_MODES else ["ko"]:
            runs.append(_by_kind(_check_run(llm, q, n, mode, lang, used), kinds))
    return {"backend": label(b), "model": _model_name(llm), "episode": n, "seed": seed, "planted": planted,
            "skipped": skipped, "runs": runs, "seconds": round(time.perf_counter() - t, 2),
            "judge": label(judge) if judge and "twostep" in modes else None, "langs": langs}


def _check_run(llm: LLM, q: Project, n: int, mode: str, lang: str, used: list) -> dict:
    """본 검수 한 번 (full · budget · widen). 영어판은 시스템 프롬프트 · 지시문 · 응답 스키마 설명만 다르고 찾음을 세는 규칙은 같다."""
    system = prompts.checker_system(lang)
    prompt = prompts.check_prompt(q, n, "budget" if mode == "widen" else mode, lang=lang)
    row: dict[str, Any] = {"mode": mode, "chars": len(prompt), "tokens": context.est_tokens(system + prompt)}
    if lang != "ko":
        row["lang"] = lang
    t1 = time.perf_counter()
    try:
        rep = llm.json(system, prompt, ConsistencyReportEn if lang == "en" else ConsistencyReport,
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
    return row


def _by_kind(row: dict, kinds: list[str]) -> dict:
    """심은 모순의 갈래(schema.plant_kind)마다 찾은 수. 갈래는 처음 나온 차례대로."""
    if row.get("ok"):
        row["by_kind"] = [{"kind": k, "found": sum(h for h, x in zip(row["hits"], kinds) if x == k), "planted": kinds.count(k)}
                          for k in dict.fromkeys(kinds)]
    return row


def check_totals(name: str) -> list[dict]:
    """기록에 남은 검수 시험 전부를 검수 방식 · 갈래마다 더한 찾은 수. 한 번으로는 우연이 커서 여러 번을 모아 본다.
    갈래를 적기 전 기록은 모순 종류(type)로 센다."""
    path = _log_path(name)
    if not path.exists():
        return []
    sums: dict[tuple[str, str], list[int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        x = json.loads(line)
        if x.get("kind") != "check":
            continue
        kinds = [y.get("kind") or y.get("type", "") for y in x.get("planted", [])]
        for m in x.get("runs", []):
            if not m.get("ok") or m.get("lang", "ko") != "ko":  # 영어판 시험 줄은 lang_tally 가 따로 센다
                continue
            for k, h in zip(kinds, m.get("hits", [])):
                c = sums.setdefault((m["mode"], k), [0, 0, 0])
                c[0] += bool(h)
                c[1] += 1
            for k in dict.fromkeys(kinds):
                sums.setdefault((m["mode"], k), [0, 0, 0])[2] += 1
    return [{"mode": mode, "kind": k, "found": f, "planted": n, "trials": t} for (mode, k), (f, n, t) in sums.items()]


def lang_tally(name: str) -> list[dict]:
    """검수 시험 기록 전체에서 한국어판과 영어판을 짝지어 센다. 같은 시험 · 같은 방식에서 두 언어가 모두 성공한 것만 넣어
    실패가 한쪽 비율을 흔들지 않게 한다. only_ko · only_en 은 심은 모순 하나를 한쪽만 찾은 수 (두 판의 차이는 여기서 나온다)."""
    path = _log_path(name)
    rows: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        x = json.loads(line)
        if x.get("kind") != "check" or "en" not in (x.get("langs") or []):
            continue
        by = {(m["mode"], m.get("lang", "ko")): m for m in x["runs"] if m.get("ok")}
        for mode in dict.fromkeys(m["mode"] for m in x["runs"]):
            ko, en = by.get((mode, "ko")), by.get((mode, "en"))
            if not ko or not en:
                continue
            r = rows.setdefault(mode, {"mode": mode, "trials": 0, "planted": 0, "ko_found": 0, "en_found": 0,
                                       "only_ko": 0, "only_en": 0, "ko_other": 0, "en_other": 0})
            r["trials"] += 1
            r["planted"] += len(ko["hits"])
            r["ko_found"] += ko["found"]
            r["en_found"] += en["found"]
            r["only_ko"] += sum(a and not b for a, b in zip(ko["hits"], en["hits"]))
            r["only_en"] += sum(b and not a for a, b in zip(ko["hits"], en["hits"]))
            r["ko_other"] += len(ko["other"])
            r["en_other"] += len(en["other"])
    return list(rows.values())


def _motion_run(llm: LLM, q: Project, n: int, used: list) -> dict:
    """동선 따로 보기 한 번 (pipeline.motion_check). 실제 검수에서는 본 검수와 동시에 불러 지적을 합친다."""
    prompt = prompts.motion_prompt(q, n)
    row: dict[str, Any] = {"mode": "motion", "chars": len(prompt), "tokens": context.est_tokens(prompts.SYSTEM_MOTION + prompt)}
    t1 = time.perf_counter()
    try:
        issues = pipeline.motion_check(llm, q, n, hint={"plants": [x.replacement for x in used]})
        hits = [any(_hit(i.current_quote, x.replacement) for i in issues) for x in used]
        extra = [i.model_dump() for i in issues if not any(_hit(i.current_quote, x.replacement) for x in used)]
        row.update(ok=True, hits=hits, found=sum(hits), other=extra, usage=getattr(llm, "last_usage", None))
    except Exception as e:
        row.update(ok=False, error=f"{type(e).__name__}: {e}")
    row["seconds"] = round(time.perf_counter() - t1, 2)
    return row


def _stage_run(llm: LLM, q: Project, n: int, used: list) -> dict:
    """장면 연출 규칙 검수 한 번: 사건마다 본문 장면을 뽑아(pipeline.extract_stage) 사본에 넣고 규칙 판정 지적(stage.episode_issues)을 센다.
    scenes 는 뽑은 장면의 박자 수라 무엇을 그렸는지 화면에서 본다. tokens 는 뽑기 호출 입력의 합 (추정)."""
    from . import stage
    row: dict[str, Any] = {"mode": "stage"}
    t1 = time.perf_counter()
    try:
        w = q.model_copy(deep=True)
        ep = w.episode(n)
        ep.stage = [s for s in ep.stage if s.role != "text"]
        props, tokens = [], 0
        for i in range(len(ep.plot.events)):
            room, prev = pipeline._stage_context(w, ep, i, "text")
            tokens += context.est_tokens(prompts.SYSTEM_STAGE + prompts.stage_extract_prompt(w, n, i, room, prev))
            prop = pipeline.extract_stage(llm, w, n, i, hint={"plants": [x.replacement for x in used]})
            pipeline.apply_stage(w, prop)
            props.append(prop)
        issues = stage.episode_issues(w, ep)
        hits = [any(_hit(i.current_quote, x.replacement) for i in issues) for x in used]
        extra = [i.model_dump() for i in issues if not any(_hit(i.current_quote, x.replacement) for x in used)]
        row.update(ok=True, hits=hits, found=sum(hits), other=extra, usage=getattr(llm, "last_usage", None), tokens=tokens,
                   scenes=[{"event": x.event, "beats": [b.quote or b.note for b in x.scene.beats], "dropped": x.dropped} for x in props])
    except Exception as e:
        row.update(ok=False, error=f"{type(e).__name__}: {e}")
    row["seconds"] = round(time.perf_counter() - t1, 2)
    return row


def judge_backend(judge: Backend | None, b: Backend) -> Backend:
    """두 걸음 검수의 판단기. 화면에서 고르지 않았으면 CANON_JUDGE(없으면 검수 백엔드가 mock 일 때 mock, 아니면 local).
    로컬 판단기의 비어 있는 모델 · 주소는 CANON_JUDGE_MODEL · CANON_JUDGE_URL 로 채운다. 그것도 비면 로컬 서버 설정."""
    provider, model, url = env_choice()
    if judge is None:
        judge = Backend(provider=provider or ("mock" if b.provider == "mock" else "local"))
    if judge.provider == "local" and (not judge.model or not judge.url):
        judge = judge.model_copy(update={"model": judge.model or model, "url": judge.url or url})
    return judge


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
    return store.compare_dir(name, n)


def kept_draft(ep: Episode, model: str) -> tuple[str, dict] | None:
    """이 화에 model 이 이미 쓴 본문: 지금 본문 → 고르기를 기다리는 새 판 → 남겨 둔 판(최근 것부터). 없으면 None.
    돌려주는 dict 는 출처(source: text · candidate · version), 판 id, 지금 본문이면 그 판이 생긴 뒤 고친 수(edits)."""
    if not model or model in ("import", "mock:mock") or model.endswith(":default"):
        return None
    if ep.text.strip() and ep.written_by == model:
        since = pipeline.text_since(ep)
        return ep.text, {"source": "text", "id": "", "edits": sum(1 for e in ep.edits if e.at >= since)}
    if ep.candidate and ep.candidate.text.strip() and ep.candidate.model == model:
        return ep.candidate.text, {"source": "candidate", "id": ep.candidate.id, "edits": 0}
    for v in reversed(ep.versions):
        if v.text.strip() and v.model == model:
            return v.text, {"source": "version", "id": v.id, "edits": 0}
    return None


def kept_drafts(ep: Episode, models: dict[str, str]) -> dict[str, tuple[str, dict]]:
    """안마다(이름 → 모델) 가져올 기존 본문. 두 안이 같은 모델이면 같은 글이 두 번 들어가므로 아무것도 가져오지 않는다."""
    named = [m for m in models.values() if m]
    if len(set(named)) < len(named):
        return {}
    return {k: got for k, m in models.items() if (got := kept_draft(ep, m))}


def _may_have_kept(ep: Episode, provider: str) -> bool:
    """이 백엔드가 쓴 판이 이 화에 있을 수 있나. 없으면 모델 이름을 묻지 않는다 (로컬은 서버에 물어야 한다)."""
    models = [ep.written_by if ep.text.strip() else "", ep.candidate.model if ep.candidate else "", *(v.model for v in ep.versions)]
    return any(m.startswith(f"{provider}:") for m in models)


def run_compare(name: str, p: Project, n: int, a: Backend, b: Backend) -> dict:
    """같은 화를 두 백엔드로 쓰고 1, 2 번으로 가려 저장한다. 프롬프트는 write_episode 와 같다.
    이 화에 그 모델이 이미 쓴 본문이 있으면 다시 쓰지 않고 가져온다(kept_draft). 두 백엔드가 같은 모델이면 둘 다 새로 쓴다."""
    la, lb = label(a), label(b)
    if la == lb and a.url == b.url:
        raise ValueError("두 백엔드가 같아요")
    llms = {la: make_backend(a), lb: make_backend(b)}
    ep = p.episode(n)
    models = {k: pipeline.writer_of(x) if _may_have_kept(ep, bk.provider) else "" for (k, x), bk in zip(llms.items(), (a, b))}
    kept = kept_drafts(ep, models)
    drafts = {k: kept[k][0] for k in kept}
    drafts.update(pipeline.compare_drafts({k: x for k, x in llms.items() if k not in kept}, p, n))
    drafts = {k: drafts[k] for k in llms}  # 차례는 A, B
    # 새로 쓴 안은 쓴 뒤의 이름을 쓴다 (Claude 구독은 호출한 뒤에야 실제 모델 이름을 안다)
    return save_compare(name, n, drafts, models={k: models[k] if k in kept else pipeline.writer_of(x) for k, x in llms.items()},
                        kept={k: v[1] for k, v in kept.items()})


def run_opening_compare(name: str, p: Project, n: int, llm: LLM, approaches: list[str] | None = None) -> dict:
    """1~3화를 여는 방식마다 하나씩 써서 가려 저장한다. 고르기 전에는 어느 방식인지 보이지 않는다."""
    drafts = pipeline.opening_drafts(llm, p, n, approaches)
    return save_compare(name, n, drafts, kind="opening", models=dict.fromkeys(drafts, pipeline.writer_of(llm)))


def save_compare(name: str, n: int, drafts: dict[str, str], kind: str = "backend", models: dict[str, str] | None = None,
                 kept: dict[str, dict] | None = None) -> dict:
    """kind: backend(백엔드 비교) 또는 opening(여는 방식 비교). models: 안마다 쓴 모델 (pipeline.writer_of), 고르면 본문 기록에 따라간다.
    kept: 새로 쓰지 않고 이 화의 기존 본문을 가져온 안과 그 출처 (kept_draft). 고르기 전에는 어느 안인지 돌려주지 않는다."""
    order = random.sample(list(drafts), len(drafts))  # 1, 2 번에 누가 들어갔는지 가린다
    out = compare_dir(name, n)
    out.mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("*.md"), *out.glob("hook-*.json")]:
        old.unlink()  # 앞 비교의 남은 안과 판정이 새 번호에 섞이지 않게
    for i, key in enumerate(order, 1):
        store.write_atomic(out / f"{i}.md", drafts[key])
    store.write_atomic(out / "key.json", json.dumps({"order": order, "kind": kind, "created": datetime.now().isoformat(timespec="seconds"),
                                                     "models": models or {}, "kept": kept or {}}, ensure_ascii=False))
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
    kept = k.get("kept") or {}
    res = {"episode": n, "kind": k.get("kind", "backend"), "created": k.get("created"), "drafts": drafts, "picked": k.get("picked"),
           "kept_count": len(kept)}
    if k.get("picked"):
        res["order"] = k["order"]
        res["kept"] = kept  # 고른 뒤에만: 어느 백엔드가 기존 본문을 가져왔는지
    return res


def _adopt(p: Project, n: int, text: str, model: str) -> None:
    """고른 비교본을 본문으로. 이 화에 남은 판과 글이 같으면(기존 본문을 가져온 안) 규칙을 다시 걸지 않고 그 판을 쓴다:
    지금 본문이면 그대로, 새 판이면 새 판 고르기, 남겨 둔 판이면 그 판으로 되돌리기. 아니면 새 안처럼 adopt_draft."""
    ep = p.episode(n)
    if ep.status == "finalized" or not text.strip():
        pipeline.adopt_draft(p, n, text, model)  # 같은 오류 문구를 쓴다
        return
    if text == ep.text:
        return
    if ep.candidate and ep.candidate.text == text:
        pipeline.adopt_candidate(p, n)
        return
    v = next((x for x in reversed(ep.versions) if x.text == text), None)
    if v is not None:
        pipeline.restore_version(p, n, v.id)
        return
    pipeline.adopt_draft(p, n, text, model)


def compare_text(name: str, n: int, k: int) -> str:
    path = compare_dir(name, n) / f"{k}.md"
    if not path.exists():
        raise ValueError(f"{n}화 비교본 {k}번이 없어요")
    return path.read_text(encoding="utf-8")


def save_compare_hook(name: str, n: int, k: int, report: BaseModel) -> None:
    """비교본 하나의 흡입력 판정. 다음 비교를 만들면 지운다."""
    store.write_atomic(compare_dir(name, n) / f"hook-{k}.json", report.model_dump_json())


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
        _adopt(p, n, (out / f"{k}.md").read_text(encoding="utf-8"), key.get("models", {}).get(order[k - 1], ""))
    key["picked"] = k
    store.write_atomic(key_path, json.dumps(key, ensure_ascii=False))
    log = out.parent / "log.jsonl"
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"episode": n, "kind": key.get("kind", "backend"), "options": order, "picked": order[k - 1],
                            "kept": sorted(key.get("kept") or {}),
                            "time": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
    wins: dict[str, int] = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        prov = json.loads(line)["picked"]
        wins[prov] = wins.get(prov, 0) + 1
    return {"picked": order[k - 1], "others": [o for o in order if o != order[k - 1]], "order": order,
            "adopted": adopt, "wins": wins, "kept": (key.get("kept") or {}).get(order[k - 1])}
