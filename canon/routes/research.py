"""연구 화면 (모델 실험, canon/research.py) 라우트. canon/web.py 에서 옮겼다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from .. import prompts, research, settings, usage
from ..web import (  # web 의 공용 도우미
    _Out,
    _load,
    _need,
    _save,
)

router = APIRouter()

class UsageBucket(_Out):
    """사용량 묶음 하나의 합계 (usage.summary 의 bucket)."""
    calls: int = 0
    failed: int = 0
    retries: int = 0
    in_: int = Field(0, alias="in")
    out: int = Field(0, description="생각 토큰을 포함한 출력")
    cached: int = 0
    cost: float = 0.0
    saved: float = 0.0
    unpriced: int = 0
    seconds: float = 0.0
    batch: int = 0
    cache_rate: float = Field(0.0, description="캐시 토큰 / 입력 토큰 (0~1). 입력이 없으면 0")
    seconds_avg: float = Field(0.0, description="호출당 평균 초")


class UsageTotal(UsageBucket):
    wasted: float = Field(0.0, description="실패 · 재시도 호출의 비용")


class UsageGroup(UsageBucket):
    """날짜 · 작품 · 화 · 단계 · 모델 · 부른 곳 · 작업 · 추론 강도별 줄. 그 묶음의 열쇠 칸만 값이 있다."""
    day: str | None = None
    project: str | None = None
    episode: int | None = None
    stage: str | None = None
    backend: str | None = None
    model: str | None = None
    source: str | None = None
    task: str | None = None
    effort: str | None = Field(None, description="추론 강도. 정하지 않은 호출은 '기본'")


class UsageCall(_Out):
    """AI 호출 기록 한 줄 (usage.record) 과 볼 때 계산한 비용. 옛 기록에 없는 칸은 기본값."""
    at: str = ""
    project: str = ""
    episode: int | None = None
    stage: str = ""
    task: str = ""
    source: str = ""
    backend: str = ""
    model: str = ""
    batch: bool = False
    attempt: int = 1
    in_: int = Field(0, alias="in")
    out: int = 0
    thought: int = 0
    cached: int = 0
    seconds: float | None = None
    ok: bool = True
    error: str = ""
    chars: int | None = None
    blocks: list[list[str | int]] | None = Field(None, description="프롬프트 머리글별 글자 수 [이름, 글자 수], 큰 것부터")
    cost: float | None = Field(None, description="추정 비용 USD. 가격을 모르면 null")
    saved: float = 0.0


class UsageSummary(_Out):
    days: int | None
    since: str
    project: str | None
    projects: list[str]
    total: UsageTotal
    by_day: list[UsageGroup]
    by_project: list[UsageGroup]
    by_episode: list[UsageGroup]
    by_stage: list[UsageGroup]
    by_model: list[UsageGroup]
    by_source: list[UsageGroup]
    by_task: list[UsageGroup] = []
    by_effort: list[UsageGroup] = []
    unpriced: list[str]
    trouble: list[UsageCall]
    recent: list[UsageCall]
    trouble_total: int
    limit: int
    billing_url: str
    prices_url: str


class PriceRow(usage.Price, _Out):
    custom: bool = Field(False, description="사용자가 고친 모델")
    current: bool = Field(False, description="오늘 적용되는 줄")
    upcoming: bool = Field(False, description="적용 시작일이 아직 오지 않은 줄")


class PriceTable(_Out):
    rows: list[PriceRow]
    checked: str
    url: str
    billing_url: str


@router.get("/api/usage")
def usage_summary(days: int = 30, project: str | None = None, limit: int = 60) -> UsageSummary:
    """AI 호출 기록을 기간과 작품으로 걸러 모은다. days 가 0 이면 전체. limit 은 최근 호출 목록의 길이 (1~1000)."""
    return usage.summary(days or None, project or None, max(1, min(limit, 1000)))


@router.get("/api/usage/prices")
def usage_prices() -> PriceTable:
    return usage.price_table()


class PricesIn(BaseModel):
    rows: list[usage.Price]


@router.put("/api/usage/prices")
def put_usage_prices(body: PricesIn) -> PriceTable:
    usage.save_prices(body.rows)
    return usage.price_table()


@router.delete("/api/usage/prices")
def reset_usage_prices() -> PriceTable:
    """가격표를 기본값(Google 가격표에서 옮긴 값)으로 되돌린다."""
    settings.set_prices([])
    return usage.price_table()


class Probe(BaseModel):
    url: str = ""
    key: str | None = None


@router.post("/api/research/probe")
def research_probe(body: Probe) -> dict:
    """로컬 서버 점검. 작품과 무관하게 쓴다."""
    try:
        return research.probe(body.url, body.key)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get("/api/projects/{name}/research")
def research_log(name: str) -> dict:
    _need(name)
    return {"log": research.history(name), "stages": research.STAGES, "check_modes": research.TRIAL_MODES,
            "check_totals": research.check_totals(name), "latest": research.latest(name),
            "open_compares": research.open_compares(name),
            "check_langs": research.TRIAL_LANGS, "check_lang_tally": research.lang_tally(name)}


class SampleIn(BaseModel):
    runs: list[research.Backend]
    system: str = prompts.SYSTEM_WRITER
    prompt: str
    temperature: float | None = None


@router.post("/api/projects/{name}/research/sample")
def research_sample(name: str, body: SampleIn) -> dict:
    _need(name)
    if not body.runs or not body.prompt.strip():
        raise ValueError("백엔드와 요청 문장을 넣으세요")
    rows = research.sample(body.runs, body.system, body.prompt, body.temperature)
    return research.record(name, "sample", {"system": body.system, "prompt": body.prompt,
                                            "temperature": body.temperature, "rows": rows})


class StageIn(BaseModel):
    backend: research.Backend
    stage: str
    sample: str = ""


@router.post("/api/projects/{name}/research/stage")
def research_stage(name: str, body: StageIn) -> dict:
    """설정 제안, 문체 분석, 기승전결을 저장하지 않고 돌린다."""
    row = research.stage_trial(_load(name), body.backend, body.stage, body.sample)
    return research.record(name, "stage", row)


@router.post("/api/projects/{name}/research/budget")
def research_budget(name: str, b: research.Backend) -> dict:
    res = research.budget(_load(name), b)
    summary = {k: res[k] for k in ("backend", "model", "limit", "first_over", "first_tight", "tokenizer")}
    return {**research.record(name, "budget", summary), **res}


class CheckTrialIn(BaseModel):
    backend: research.Backend
    episode: int
    plants: int = 3
    modes: list[str] = []
    judge: research.Backend | None = None  # 주면 두 걸음 검수(판단기)도 시험한다
    stage: bool = False  # 켜면 장면 연출 규칙 검수도 시험한다
    langs: list[str] = []  # 검수 지시문 언어(research.TRIAL_LANGS). 비우면 한국어만, en 을 넣으면 영어판도 돌린다


@router.post("/api/projects/{name}/research/check")
def research_check(name: str, body: CheckTrialIn) -> dict:
    """검수 시험: n화에 모순을 심고 검수 방식마다 찾는지 본다. 작품에는 저장하지 않는다."""
    if not 1 <= body.plants <= 5:
        raise ValueError("심을 모순은 1~5개예요")
    res = research.check_trial(_load(name), body.episode, body.backend, body.plants, body.modes or None, judge=body.judge, stage=body.stage,
                               langs=body.langs or None)
    return research.record(name, "check", res)


class CompareIn(BaseModel):
    a: research.Backend
    b: research.Backend


@router.get("/api/projects/{name}/research/compare/{n}")
def research_compare_get(name: str, n: int) -> dict:
    _need(name)
    return {"compare": research.load_compare(name, n)}


@router.post("/api/projects/{name}/research/compare/{n}")
def research_compare(name: str, n: int, body: CompareIn) -> dict:
    p = _load(name)
    c = research.run_compare(name, p, n, body.a, body.b)
    research.record(name, "compare", {"episode": n, "backends": [research.label(body.a), research.label(body.b)]})
    return {"compare": c}


class Pick(BaseModel):
    k: int
    adopt: bool = True


@router.post("/api/projects/{name}/research/compare/{n}/pick")
def research_pick(name: str, n: int, body: Pick) -> dict:
    """고른 번호를 공개한다. adopt 면 그 본문을 그 화 본문으로 저장한다."""
    p = _load(name)
    r = research.pick_compare(name, p, n, body.k, body.adopt)
    if body.adopt:
        _save(name, p)
    research.record(name, "pick", {"episode": n, **r})
    return {"compare": research.load_compare(name, n), "result": r, "project": p}


EXPORTS = (
    "CheckTrialIn",
    "CompareIn",
    "Pick",
    "PriceRow",
    "PriceTable",
    "PricesIn",
    "Probe",
    "SampleIn",
    "StageIn",
    "UsageBucket",
    "UsageCall",
    "UsageGroup",
    "UsageSummary",
    "UsageTotal",
    "put_usage_prices",
    "research_budget",
    "research_check",
    "research_compare",
    "research_compare_get",
    "research_log",
    "research_pick",
    "research_probe",
    "research_sample",
    "research_stage",
    "reset_usage_prices",
    "usage_prices",
    "usage_summary",
)
