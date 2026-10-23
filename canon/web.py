"""웹 UI 서버. `python -m canon serve` 로 실행한다.

CLI 와 같은 store / pipeline / prompts 를 그대로 쓰고, 화면은 canon/static/ 의 정적 파일이다.
AI 가 만든 제안(설정, 문체, 구조, 상태 변경안)은 바로 저장하지 않고 돌려주며,
사용자가 화면에서 고르거나 고친 뒤 저장 요청을 보낼 때 반영한다.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import autorun, dynamics, elements, genres, illust, jobs, library, metrics, naming, pipeline, prompts, publish, research, settings, store, usage
from .llm import GeminiLLM, LocalLLM, get_llm, make_llm
from .schema import (ArcPlan, ArcProposal, EpisodePlot, LookSuggestion, Meta, Project, RewriteRequest, Selection, SerialConversion, SerialRebuild, SeriesPlan, SetupSuggestion, StateDelta,
                     StorylineProposal, StyleEntry, StyleProfile)

STATIC = Path(__file__).parent / "static"
NAME_RE = re.compile(r"^[^/\\.][^/\\]{0,63}$")

app = FastAPI(title="Canon")
_active = 0  # 처리 중인 요청 수. 자동 업데이트는 이 값이 0일 때만 다시 시작한다.


_PROJECT_PATH = re.compile(r"^/api/projects/([^/]+)/?(.*)$")
_EPISODE_PATH = re.compile(r"(?:^episodes/|^research/compare/|^chat/text:)(\d+)")


def _usage_scope(path: str) -> dict:
    """요청 경로에서 사용량 기록에 붙일 작품, 화, 작업 이름을 읽는다. 연구 화면 호출은 단계를 research 로 적는다."""
    if path.startswith("/api/research"):
        return {"source": "research", "stage": "research", "task": "probe"}
    m = _PROJECT_PATH.match(path)
    if not m:
        return {"source": "web"}
    rest = m[2]
    ep = _EPISODE_PATH.search(rest)
    parts = rest.split("/")
    task = parts[2] if parts[0] == "episodes" and len(parts) > 2 else parts[0].split(":")[0]
    out = {"source": "web", "project": unquote(m[1]), "episode": int(ep[1]) if ep else None, "task": task or None}
    if parts[0] == "research":
        out.update(source="research", stage="research", task=parts[1] if len(parts) > 1 else "research")
    return out


@app.middleware("http")
async def _count_active(request: Request, call_next):
    global _active
    _active += 1
    try:
        with usage.scope(**_usage_scope(request.url.path)):
            return await call_next(request)
    finally:
        _active -= 1


@app.exception_handler(ValueError)
@app.exception_handler(KeyError)
async def _bad_request(_: Request, e: Exception) -> JSONResponse:
    msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
    return JSONResponse({"detail": str(msg)}, status_code=400)


@app.exception_handler(Exception)
async def _server_error(_: Request, e: Exception) -> JSONResponse:
    # Gemini 키 누락, 응답 실패 등을 화면에 그대로 보여준다
    return JSONResponse({"detail": f"{type(e).__name__}: {e}"}, status_code=500)


def _load(name: str) -> Project:
    if not NAME_RE.match(name) or not store.exists(name):
        raise HTTPException(404, f"프로젝트가 없습니다: {name}")
    return store.load(name)


def _save(name: str, p: Project, merged: set[str] | None = None) -> Project:
    """저장한다. 화면이 보낸 작품 전체를 저장할 때(merged 를 넘길 때)는 백그라운드 작업이 맡은 화를
    디스크에 있는 내용(작업 결과)으로 지킨다. 다른 엔드포인트는 방금 읽은 디스크 내용을 고쳐 저장하므로 그대로 쓴다."""
    with jobs.project_lock(name):
        owned = jobs.owned_episodes(name, merged) if merged is not None else set()
        if owned and store.exists(name):
            disk = {e.plot.number: e for e in store.load(name).episodes}
            mine = {e.plot.number: e for e in p.episodes}
            for n in owned:
                if n in disk:
                    mine[n] = disk[n]
            p.episodes = [mine[k] for k in sorted(mine)]
        if merged is not None and store.exists(name):
            autorun.protected(name, store.load(name), p)  # 자동 집필이 반영한 진행을 오래된 화면이 덮지 않게
        store.save(name, p)
    return p


def _not_auto(name: str) -> None:
    if autorun.active(name):
        raise ValueError("자동 집필이 도는 중입니다. 일시정지한 뒤에 하세요")


# ---------- 프로젝트 ----------

class NewProject(BaseModel):
    name: str
    meta: Meta
    style_id: str = ""  # 문체 라이브러리에서 고른 항목


@app.get("/api/config")
def config() -> dict:
    return settings.public()


class SettingsIn(BaseModel):
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None  # None 이면 그대로, 값이 있으면 교체
    clear_key: bool = False
    local_url: str | None = None
    local_model: str | None = None
    local_key: str | None = None
    stages: dict[str, str] | None = None  # {"write": "local"}, 빈 값이면 전체 설정을 따름
    stage_models: dict[str, str] | None = None  # {"state": "gemini-3.8-flash"}, 빈 값이면 백엔드 기본 모델


@app.put("/api/config")
def put_config(body: SettingsIn) -> dict:
    choices = settings.PROVIDERS
    if body.provider is not None and body.provider not in choices:
        raise HTTPException(400, f"provider 는 {' / '.join(choices)} 중 하나입니다")
    for stage, value in (body.stages or {}).items():
        if stage not in settings.STAGES or (value and value not in choices):
            raise HTTPException(400, f"단계 설정이 잘못됐습니다: {stage}={value}")
    for stage in body.stage_models or {}:
        if stage not in settings.STAGES:
            raise HTTPException(400, f"알 수 없는 단계입니다: {stage}")
    settings.update(provider=body.provider, model=body.model, api_key=body.api_key, clear_key=body.clear_key,
                    local_url=body.local_url, local_model=body.local_model, local_key=body.local_key,
                    stages=body.stages, stage_models=body.stage_models)
    return settings.public()


@app.post("/api/config/test")
def test_config() -> dict:
    """단계에서 쓰는 백엔드와 모델마다 연결을 확인한다. 본문 생성 비용은 들지 않는다."""
    used = {(settings.stage_provider(s)[0], settings.stage_model(s)[0]) for s in settings.STAGES}
    used = {u for u in used if u[0] != "mock"}
    if not used:
        return {"ok": True, "message": "mock 모드입니다. 실제 AI 를 호출하지 않습니다."}
    done = []
    for prov, model in sorted(used):
        try:
            llm = make_llm(prov, model)
            llm.check()
        except Exception as e:  # SDK 오류 종류가 많아 메시지만 보여준다
            raise HTTPException(400, f"{prov} {model or ''} 연결 실패: {getattr(e, 'message', None) or e}")
        done.append(llm.model)
    return {"ok": True, "message": f"{', '.join(dict.fromkeys(done))} 에 연결됐습니다."}


@app.get("/api/config/models")
def config_models() -> dict:
    """설정 화면의 모델 목록. 백엔드마다 실제로 쓸 수 있는 모델을 묻고, 실패하면 이유만 돌려준다."""
    out = {}
    for prov, make in (("gemini", GeminiLLM), ("local", lambda: LocalLLM(timeout=5))):
        try:
            out[prov] = {"models": make().models(), "error": ""}
        except Exception as e:  # 키가 없거나 서버가 꺼져 있어도 화면은 열려야 한다
            out[prov] = {"models": [], "error": str(getattr(e, "message", None) or e)}
    return out


@app.get("/api/projects")
def list_projects() -> list[dict]:
    out = []
    if store.ROOT.exists():
        for d in sorted(store.ROOT.iterdir()):
            if (d / "project.json").exists():
                p = store.load(d.name)
                done = sum(e.status == "finalized" for e in p.episodes)
                out.append({"name": d.name, "title": p.meta.title, "genre": p.meta.genre,
                            "episodes": p.meta.target_episodes, "finalized": done})
    return out


@app.post("/api/projects")
def create_project(body: NewProject) -> Project:
    name = body.name.strip()
    if not NAME_RE.match(name):
        raise HTTPException(400, "프로젝트 이름에 / \\ 를 쓰거나 . 으로 시작할 수 없습니다")
    if store.exists(name):
        raise HTTPException(409, f"이미 있는 프로젝트입니다: {name}")
    p = Project(meta=body.meta)
    if not p.meta.title:
        p.meta.title = name
    if p.meta.genre and p.meta.genres == [p.meta.genre.strip()]:  # 장르를 글로만 보낸 경우: '로맨스, 회귀'
        p.meta.genres = genres.parse(p.meta.genre)
    p.meta.genre = genres.label(p.meta)
    if body.style_id:
        library.apply(p, library.load(body.style_id))
    return _save(name, p)


@app.get("/api/genres")
def genre_list() -> list[genres.Genre]:
    return genres.CATALOG


@app.get("/api/projects/{name}")
def get_project(name: str) -> Project:
    return _load(name)


@app.put("/api/projects/{name}")
def put_project(name: str, p: Project, merged: str = "") -> Project:
    """화면에서 고친 프로젝트 전체를 저장한다. 구조(arc)가 있으면 화수와 맞는지 검사한다.
    장편은 부 구성과 아크(아크 안 기승전결 포함)가 이어지는지 검사한다."""
    _load(name)
    if p.arc and not p.serial:
        pipeline.validate_arc(ArcPlan(acts=p.arc), p.meta.target_episodes)
    if p.serial:
        pipeline.validate_parts(p.parts, p.meta.target_episodes)
        pipeline.validate_story_arcs(p)
    pipeline.validate_storylines(p)
    pipeline._init_states(p)
    p.meta.genre = genres.label(p.meta)
    if p.snapshot(0) is None:  # 첫 반영 전에는 설정 화면의 시작 호감이 시작 관계다
        p.ties = []
        dynamics.seed_ties(p)
    elements.stamp(p)
    _keep_impacts(name, p)
    _keep_hooks(name, p)
    return _save(name, p, merged={m for m in merged.split(",") if m})


def _keep_hooks(name: str, p: Project) -> None:
    """흡입력 판정도 백그라운드 작업이 디스크에 쓴다. 화면이 그 전에 읽은 작품을 저장해도 새 판정을 덮지 않게 한다."""
    disk = {e.plot.number: e.hook for e in store.load(name).episodes if e.hook}
    for e in p.episodes:
        d = disk.get(e.plot.number)
        if d and (e.hook is None or e.hook.checked_at < d.checked_at):
            e.hook = d


def _keep_impacts(name: str, p: Project) -> None:
    """영향 분석은 백그라운드 작업이 디스크에 쓴다. 화면이 그 전에 읽은 작품을 저장해도 새 분석을 덮지 않게 한다."""
    disk = {el.id: el.impact for el in store.load(name).elements if el.impact}
    for el in p.elements:
        d = disk.get(el.id)
        if d and (el.impact is None or el.impact.at < d.at or (el.impact.at == d.at and d.outcome and not el.impact.outcome)):
            el.impact = d


# ---------- 1. 설정 도우미 ----------

@app.post("/api/projects/{name}/suggest")
def suggest(name: str) -> SetupSuggestion:
    return pipeline.suggest_setup(get_llm("plan"), _load(name))


@app.post("/api/projects/{name}/suggest/apply")
def apply_suggestion(name: str, s: SetupSuggestion) -> Project:
    p = _load(name)
    pipeline.apply_setup(p, s)
    return _save(name, p)


# ---------- 이름 · 지명 ----------

@app.get("/api/naming/styles")
def naming_styles() -> list[dict]:
    return [{**st.model_dump(), "place_kinds": naming.place_kinds(st.id)} for st in naming.STYLES]


class NamesIn(BaseModel):
    character: str = ""  # 인물 id. 비우면 지명
    place_kind: str = ""
    n: int = 8
    ai: bool = False      # True 면 '이름·지명' 단계 모델이 후보에서 골라 이유를 붙인다
    project: Project | None = None  # 저장 전 화면의 값 (나이, 성별, 이름 스타일을 고친 직후에도 맞게)


@app.post("/api/projects/{name}/names")
def names(name: str, body: NamesIn) -> dict:
    p = body.project or _load(name)
    n = max(1, min(body.n, 20))
    out: dict = {"style": naming.resolve_style(p), "detected": naming.detect_style(p)}
    out["style_label"] = naming.style_label(out["style"])
    if body.ai:
        cands, opts = pipeline.suggest_names(get_llm("name"), p, body.character, body.place_kind, min(n, 8))
        out["candidates"] = [c.model_dump() for c in cands]
        out["options"] = [o.model_dump() for o in opts.options]
    else:
        out["candidates"] = [c.model_dump() for c in pipeline.name_candidates(p, body.character, body.place_kind, n)]
    return out


@app.post("/api/projects/{name}/names/check")
def names_check(name: str, p: Project | None = None) -> dict:
    p = p or _load(name)
    return {"warnings": naming.cast_warnings(p), "style": naming.resolve_style(p), "detected": naming.detect_style(p)}


# ---------- 2. 문체 ----------

class Sample(BaseModel):
    text: str


@app.post("/api/projects/{name}/style")
def analyze_style(name: str, body: Sample) -> StyleProfile:
    _load(name)
    if len(body.text.strip()) < 200:
        raise HTTPException(400, "예시 원문은 200자 이상 넣어 주세요")
    return pipeline.analyze_style(get_llm("plan"), body.text)


@app.post("/api/metrics")
def measure(body: Sample) -> metrics.StyleMetrics:
    """원문 전체로 문체 기준 지표를 잰다 (LLM 없음). 웹에서 분석한 원문의 기준값을 작품에 남길 때 쓴다."""
    return metrics.measure(body.text)


@app.get("/api/projects/{name}/style/link")
def style_link(name: str) -> dict:
    return library.link_state(_load(name))


class StyleUse(BaseModel):
    style_id: str


@app.post("/api/projects/{name}/style/apply")
def apply_library_style(name: str, body: StyleUse) -> Project:
    """라이브러리 문체를 작품에 복사한다. 지금 작품의 문체는 바뀐다."""
    p = _load(name)
    library.apply(p, library.load(body.style_id))
    return _save(name, p)


class StyleKeep(BaseModel):
    name: str = ""
    source: str = ""
    sample: str = ""   # 방금 분석한 원문. 있으면 기준 지표를 이 원문으로 잰다
    update: bool = False  # 새 항목 대신 연결된 항목을 새 버전으로 갱신
    note: str = ""  # 갱신할 때 버전 메모


@app.post("/api/projects/{name}/style/library")
def keep_style(name: str, body: StyleKeep) -> dict:
    """작품의 지금 문체를 라이브러리에 저장한다 (작품 화면에서 저장한 뒤 부른다)."""
    p = _load(name)
    if body.update:
        e = library.push_project(p, body.note)
        _save(name, p)
    else:
        e = library.from_project(p, body.name or f"{p.meta.title or name} 문체", body.sample, body.source)
        if body.sample.strip():  # 웹에서 분석한 원문의 기준 지표를 작품에도 남긴다
            p.style_baseline = e.baseline
        _save(name, p)
    return {"entry": library.summary(e), "project": p}


# ---------- 2-1. 내 수정에서 배우기 ----------

@app.get("/api/projects/{name}/style/edits")
def style_edit_stats(name: str) -> dict:
    return pipeline.edit_stats(_load(name))


@app.post("/api/projects/{name}/style/learn")
def learn_style(name: str) -> Project:
    """수정 기록에서 문체 규칙 후보를 찾아 작품에 붙인다. 문체는 바꾸지 않는다 (고른 것만 apply 로)."""
    p = _load(name)
    r = pipeline.learn_style(get_llm("plan"), p)
    p = _load(name)  # AI 를 기다리는 사이 저장된 내용을 덮지 않는다
    p.style_learning = r
    return _save(name, p)


class LearnPicks(BaseModel):
    picks: list[int]
    push: bool = False  # 연결된 라이브러리 항목에도 새 버전으로 올린다


@app.post("/api/projects/{name}/style/learn/apply")
def apply_learning(name: str, body: LearnPicks) -> dict:
    p = _load(name)
    done, notes = pipeline.apply_learning(p, body.picks)
    entry = None
    if body.push and p.style_id and library.exists(p.style_id):
        entry = library.summary(library.push_project(p, f"수정 기록에서 배운 규칙 {len(done)}개 반영"))
    return {"project": _save(name, p), "applied": len(done), "notes": notes, "entry": entry}


@app.post("/api/projects/{name}/style/learn/dismiss")
def dismiss_learning(name: str) -> Project:
    p = _load(name)
    p.style_learning = None
    return _save(name, p)


# ---------- 문체 라이브러리 ----------

class StyleIn(BaseModel):
    name: str
    source: str = ""
    notes: str = ""
    sample: str = ""
    profile: StyleProfile = StyleProfile()
    note: str = ""  # 이번 버전 메모. 비우면 바뀐 칸 이름


def _style_id(sid: str) -> str:
    if not library.exists(sid):
        raise HTTPException(404, f"문체 라이브러리에 없는 항목입니다: {sid}")
    return sid


@app.get("/api/styles")
def list_styles() -> list[dict]:
    return [library.summary(e) for e in library.entries()]


@app.post("/api/styles/analyze")
def analyze_library_style(body: Sample) -> StyleProfile:
    """원문을 분석해 프로필 제안만 돌려준다. 저장은 사용자가 고친 뒤 따로 한다."""
    if len(body.text.strip()) < 200:
        raise HTTPException(400, "예시 원문은 200자 이상 넣어 주세요")
    return pipeline.analyze_style(get_llm("plan"), body.text)


@app.post("/api/styles")
def create_style(body: StyleIn) -> StyleEntry:
    return library.create(body.name, body.profile, body.sample, body.source, body.notes)


@app.get("/api/styles/{sid}")
def get_style(sid: str) -> dict:
    e = library.load(_style_id(sid))
    return {**e.model_dump(), "used_by": library.used_by(sid)}


@app.put("/api/styles/{sid}")
def put_style(sid: str, body: StyleIn) -> dict:
    e = library.update(_style_id(sid), body.name, body.profile, body.sample, body.source, body.notes, body.note)
    return {**e.model_dump(), "used_by": library.used_by(sid)}


@app.get("/api/styles/{sid}/versions")
def style_versions(sid: str) -> list[dict]:
    return library.versions(library.load(_style_id(sid)))


@app.post("/api/styles/{sid}/versions/{number}/restore")
def restore_style(sid: str, number: int) -> dict:
    e = library.restore(_style_id(sid), number)
    return {**e.model_dump(), "used_by": library.used_by(sid)}


@app.delete("/api/styles/{sid}")
def delete_style(sid: str) -> dict:
    library.delete(_style_id(sid))
    return {"ok": True}


@app.post("/api/styles/{sid}/duplicate")
def duplicate_style(sid: str) -> StyleEntry:
    return library.duplicate(_style_id(sid))


# ---------- 3. 구조와 플롯 ----------

@app.post("/api/projects/{name}/arc")
def plan_arc(name: str) -> ArcPlan:
    return pipeline.plan_arc(get_llm("plan"), _load(name))


class Range(BaseModel):
    start: int | None = None
    end: int | None = None


@app.post("/api/projects/{name}/plots")
def draft_plots(name: str, r: Range) -> Project:
    """확정되지 않은 화만 새 초안으로 바꾼다."""
    p = _load(name)
    end = r.end or (p.planned_until() if p.serial else p.meta.target_episodes)
    batch = pipeline.draft_plots(get_llm("plan"), p, r.start or 1, end)
    pipeline.apply_plots(p, batch)
    return _save(name, p)


# ---------- 3-0. 장편 연재: 부 구성, 아크, 요약 ----------
# AI 제안은 백그라운드 작업(series, nextarc, recap_arc, recap_part)으로 받고, 화면에서 고친 뒤 아래로 반영한다.

@app.post("/api/projects/{name}/series/apply")
def apply_series(name: str, plan: SeriesPlan) -> Project:
    p = _load(name)
    pipeline.apply_series(p, plan)
    return _save(name, p)


@app.post("/api/projects/{name}/arcs/apply")
def apply_arc(name: str, prop: ArcProposal) -> Project:
    p = _load(name)
    pipeline.apply_arc(p, prop)
    return _save(name, p)


@app.delete("/api/projects/{name}/arcs/last")
def remove_last_arc(name: str) -> Project:
    p = _load(name)
    pipeline.remove_last_arc(p)
    return _save(name, p)


# 단편 → 장편 전환: 제안은 백그라운드 작업(convert)으로 받고, 화면에서 뺄 것을 빼고 고친 뒤 반영한다.

@app.get("/api/projects/{name}/convert")
def conversion_status(name: str) -> dict:
    """전환 가능한 총 화수 범위, 또는 이미 전환했다면 되돌릴 수 있는지."""
    p = _load(name)
    lo, hi = pipeline.convert_range(p)
    blockers = pipeline.undo_blockers(p, store.load_backup(name, pipeline.BACKUP_TAG)) if p.conversion else []
    span = dict(zip(("min", "default", "max"), pipeline.rebuild_span(p))) if not p.serial and p.episodes else None
    return {"min": lo, "max": hi, "end": pipeline.short_end(p), "conversion": p.conversion, "undo_blockers": blockers,
            "rebuild": span}


@app.post("/api/projects/{name}/convert/apply")
def apply_conversion(name: str, prop: SerialConversion) -> Project:
    _not_auto(name)
    p = _load(name)
    before = pipeline.apply_conversion(p, prop)
    store.save_backup(name, pipeline.BACKUP_TAG, before)
    return _save(name, p)


@app.post("/api/projects/{name}/convert/rebuild/apply")
def apply_rebuild(name: str, prop: SerialRebuild) -> dict:
    """재구성 반영. 옮기지 못해 작가가 볼 것(notes)을 함께 돌려준다."""
    _not_auto(name)
    p = _load(name)
    before, notes = pipeline.apply_rebuild(p, prop)
    store.save_backup(name, pipeline.BACKUP_TAG, before)
    return {"project": _save(name, p), "notes": notes}


class ReworkIn(BaseModel):
    text: str
    proposed: str = ""  # AI 가 낸 글 (작가가 손봤으면 수정 기록에 남긴다)


@app.post("/api/projects/{name}/episodes/{n}/rework")
def accept_rework(name: str, n: int, body: ReworkIn) -> Project:
    """재구성에서 다듬기로 고른 화에 다듬은 본문을 넣는다."""
    _not_auto(name)
    p = _load(name)
    pipeline.accept_rework(p, n, body.text, body.proposed)
    return _save(name, p)


@app.post("/api/projects/{name}/convert/undo")
def undo_conversion(name: str) -> Project:
    _not_auto(name)
    p = _load(name)
    q = pipeline.undo_conversion(p, store.load_backup(name, pipeline.BACKUP_TAG))  # type: ignore[arg-type]
    out = _save(name, q)
    store.drop_backup(name, pipeline.BACKUP_TAG)
    return out


class RecapIn(BaseModel):
    summary: str


@app.post("/api/projects/{name}/recap/{kind}/{number}")
def apply_recap(name: str, kind: str, number: int, body: RecapIn) -> Project:
    p = _load(name)
    pipeline.apply_recap(p, kind, number, body.summary)
    return _save(name, p)


# ---------- 3-2. 이야기 줄기 ----------
# AI 제안은 백그라운드 작업(storyline)으로 받고, 화면에서 고친 뒤 아래로 반영한다. 화에 붙이고 떼는 것은 화면이 저장(PUT)한다.

class StorylineIn(BaseModel):
    proposal: StorylineProposal
    episodes: list[int] = []
    threads: list[int] = []


@app.post("/api/projects/{name}/storylines/apply")
def apply_storyline(name: str, body: StorylineIn) -> Project:
    p = _load(name)
    pipeline.apply_storyline(p, body.proposal, body.episodes, body.threads)
    return _save(name, p)


@app.delete("/api/projects/{name}/storylines/{sid}")
def remove_storyline(name: str, sid: str) -> Project:
    p = _load(name)
    pipeline.remove_storyline(p, sid)
    return _save(name, p)


@app.post("/api/projects/{name}/episodes/{n}/confirm")
def confirm_plot(name: str, n: int) -> Project:
    p = _load(name)
    ep = p.episode(n)
    if ep.status == "draft":
        ep.status = "confirmed"
    return _save(name, p)


@app.post("/api/projects/{name}/episodes/{n}/unconfirm")
def unconfirm_plot(name: str, n: int) -> Project:
    p = _load(name)
    ep = p.episode(n)
    if ep.status != "confirmed":
        raise ValueError(f"{n}화는 본문이 이미 있어 초안으로 되돌릴 수 없습니다")
    ep.status = "draft"
    return _save(name, p)


# ---------- 3-1. 대화로 다듬기 ----------
# 대화 기록은 project.json 의 chats 에 화면(topic)별로 남는다. 플롯 화면은 'plot', 집필 화면의 본문 부분 수정은
# 화마다 'text:<화>' 이다 (4-1 참고).

TEXT_TOPIC = re.compile(r"^text:(\d+)$")


def _chat(p: Project, topic: str):
    m = TEXT_TOPIC.match(topic)
    if topic != "plot" and not (m and any(e.plot.number == int(m.group(1)) for e in p.episodes)):
        raise HTTPException(404, f"대화 주제가 없습니다: {topic}")
    return p.chat(topic)


class ChatIn(BaseModel):
    message: str = ""
    selection: Selection | None = None  # 본문 부분 수정: 고른 부분
    preset: str = ""  # 본문 부분 수정: 빠른 요청 id (prompts.PASSAGE_PRESETS)


@app.post("/api/projects/{name}/chat/{topic}")
def chat_send(name: str, topic: str, body: ChatIn) -> Project:
    """작가의 말을 보내고 AI 답과 변경안을 대화 기록에 남긴다. 구조와 플롯, 본문은 바꾸지 않는다."""
    p = _load(name)
    _chat(p, topic)
    if m := TEXT_TOPIC.match(topic):
        n = int(m.group(1))
        if body.selection is None:
            raise ValueError("본문에서 고칠 부분을 고르세요")
        sel = Selection(start=pipeline.locate(p.episode(n).text, body.selection.text, body.selection.start), text=body.selection.text)
        rev = pipeline.revise_passage(get_llm("revise"), p, n, sel, body.message, body.preset)
        return _edit(name, lambda q: pipeline.record_passage(q, n, sel, body.message, body.preset, rev))
    rev = pipeline.revise_plot(get_llm("plan"), p, body.message)
    # AI 를 기다리는 동안 백그라운드 작업이 저장했을 수 있으니 최신 내용에 대화만 덧붙인다
    return _edit(name, lambda q: pipeline.record_chat(q, topic, body.message, rev))


class ChatApply(BaseModel):
    acts: bool = False
    episodes: list[int] = []
    candidate: int | None = None  # 본문 부분 수정: 넣을 후보 번호 (0부터)
    text: str | None = None  # 본문 부분 수정: 작가가 손본 후보


@app.post("/api/projects/{name}/chat/{topic}/{i}/apply")
def chat_apply(name: str, topic: str, i: int, body: ChatApply) -> Project:
    """i 번째 메시지의 변경안에서 고른 부분만 반영한다."""
    if m := TEXT_TOPIC.match(topic):
        n = int(m.group(1))
        if body.candidate is None:
            raise ValueError("넣을 후보를 고르세요")
        _text_guard(name, n)
        _chat(_load(name), topic)
        return _edit(name, lambda q: pipeline.apply_passage(q, n, i, body.candidate, body.text))
    p = _load(name)
    msgs = _chat(p, topic).messages
    if not 0 <= i < len(msgs) or msgs[i].revision is None:
        raise HTTPException(404, "변경안이 있는 메시지가 아닙니다")
    m = msgs[i]
    if m.outcome:
        raise ValueError("이미 처리한 변경안입니다")
    if not body.acts and not body.episodes:
        raise ValueError("반영할 부분을 고르세요")
    m.applied = pipeline.apply_revision(p, m.revision, body.acts, body.episodes)
    m.outcome = "applied"
    return _save(name, p)


@app.post("/api/projects/{name}/chat/{topic}/{i}/dismiss")
def chat_dismiss(name: str, topic: str, i: int) -> Project:
    _chat(_load(name), topic)

    def fn(p: Project) -> None:
        msgs = p.chat(topic).messages
        if not 0 <= i < len(msgs) or (msgs[i].revision is None and msgs[i].passage is None):
            raise HTTPException(404, "변경안이 있는 메시지가 아닙니다")
        if not msgs[i].outcome:
            msgs[i].outcome = "dismissed"
    return _edit(name, fn)


@app.delete("/api/projects/{name}/chat/{topic}")
def chat_clear(name: str, topic: str) -> Project:
    _chat(_load(name), topic)
    return _edit(name, lambda p: setattr(p.chat(topic), "messages", []))


# ---------- 3-2. 인과율 ----------
# 요소 자체는 작가 입력이라 작품 저장(PUT)으로 저장한다. 영향 분석은 백그라운드 작업(kind 'impact')이 요소에 붙인다.

@app.get("/api/projects/{name}/elements/links")
def element_links(name: str) -> dict:
    """요소마다 관련 화 지도 (AI 없이 이름, 별칭, 관련 인물로 찾음)."""
    p = _load(name)
    return {el.id: [lk.model_dump() for lk in elements.links(p, el)] for el in p.elements}


class ImpactApply(BaseModel):
    episodes: list[int] = []
    patches: list[int] = []
    facts: list[int] = []


@app.post("/api/projects/{name}/elements/{eid}/impact/apply")
def impact_apply(name: str, eid: str, body: ImpactApply) -> Project:
    """플롯과 본문을 바꾸므로 자동 집필이 도는 동안에는 막는다 (상태 반영과 같은 규칙)."""
    _not_auto(name)
    p = _load(name)
    pipeline.apply_impact(p, eid, body.episodes, body.patches, body.facts)
    return _save(name, p)


@app.post("/api/projects/{name}/elements/{eid}/impact/dismiss")
def impact_dismiss(name: str, eid: str) -> Project:
    p = _load(name)
    pipeline.dismiss_impact(p, eid)
    return _save(name, p)


# ---------- 백그라운드 작업 ----------

class JobIn(BaseModel):
    kind: str  # suggest | arc | plots | write | state | impact | series | nextarc | recap_arc | recap_part | storyline | convert | rebuild | rework | hook | openings | opening_drafts
    ep: int | None = None  # 화 번호. plots 는 장편에서 아크 번호(없으면 초안이 있는 모든 아크), recap_* 는 아크·부 번호
    element: str = ""  # impact 일 때 요소 id
    note: str = ""  # nextarc, storyline, convert, rebuild: 작가가 바라는 것
    line_kind: str = ""  # storyline: 원하는 줄기 종류 (비우면 AI 가 고름)
    length: int = 0  # nextarc: 아크 화수 (0 이면 AI 가 정함). convert, rebuild: 장편 총 화수
    ending: str = ""  # convert: keep | reopen, rebuild: arc | part | series (단편 결말이 갈 곳). 비우면 AI 가 고름
    span: int = 0  # rebuild: 다시 짤 앞부분 화수 (0 이면 기본값)
    approaches: list[str] = []  # openings, opening_drafts: 여는 방식 id (비우면 기본 세 가지)
    draft: int = 0  # hook: 0 이면 그 화 본문, k 면 비교본 k 번을 판정
    rewrite: RewriteRequest | None = None  # write: 본문이 있는 화를 다시 생성. 새 판은 본문을 덮지 않고 고르기를 기다린다


def _edit(name: str, fn) -> Project:
    """작업 결과를 최신 project.json 에 반영해 저장한다 (작업이 도는 동안 사용자가 저장했을 수 있다)."""
    with jobs.project_lock(name):
        p = store.load(name)
        fn(p)
        store.save(name, p)
    return p


def _plot_ranges(p: Project, arc: int | None = None) -> list[tuple[str, int, int]]:
    """초안이거나 아직 없는 화가 있는 구간만 다시 만든다. 장편은 arc 번호를 주면 그 아크만."""
    status = {e.plot.number: e.status for e in p.episodes}
    beats = p.beats()
    if p.serial and arc is not None:
        s = next((x for x in p.story_arcs if x.number == arc), None)
        if s is None:
            raise ValueError(f"아크 {arc}이(가) 없습니다")
        beats = s.acts
    groups: list[list] = []  # 화를 함께 쓰는 구간(짧은 작품)은 한 번에 만든다: [이름들, 시작, 끝]
    for a in sorted(beats, key=pipeline.act_order):
        if groups and a.start_ep <= groups[-1][2]:
            groups[-1][0].append(a.name)
            groups[-1][2] = max(groups[-1][2], a.end_ep)
        else:
            groups.append([[a.name], a.start_ep, a.end_ep])
    out = []
    for names, a, b in groups:
        if any(status.get(n, "draft") == "draft" for n in range(a, b + 1)):
            out.append(("·".join(names), a, b))
    return out


@app.post("/api/projects/{name}/jobs")
def start_job(name: str, body: JobIn) -> dict:
    """오래 걸리는 AI 작업을 시작하고 바로 돌아온다. 결과는 GET /api/jobs 로 본다."""
    p = _load(name)
    kind, n = body.kind, body.ep
    if kind in ("write", "state", "plots"):
        _not_auto(name)
    stage = {"write": "write", "state": "state", "recap_arc": "state", "recap_part": "state", "rework": "revise",
             "hook": "check", "opening_drafts": "write"}.get(kind, "plan")  # 나머지는 plan
    llm = get_llm(stage)  # 키가 없으면 여기서 바로 오류를 보여 준다

    if kind == "suggest":
        label, total, owned = "설정 제안", 1, set()

        def fn(job: jobs.Job):
            return pipeline.suggest_setup(llm, store.load(name)).model_dump()
    elif kind == "arc":
        label, total, owned = "기승전결 구조 제안", 1, set()

        def fn(job: jobs.Job):
            return pipeline.plan_arc(llm, store.load(name)).model_dump()
    elif kind == "series":
        label, total, owned = "부 구성 제안", 1, set()

        def fn(job: jobs.Job):
            return pipeline.plan_series(llm, store.load(name)).model_dump()
    elif kind == "nextarc":
        label, total, owned = f"{pipeline.next_arc_start(p)}화부터 다음 아크 제안", 1, set()
        note, length = body.note, body.length

        def fn(job: jobs.Job):
            return pipeline.plan_next_arc(llm, store.load(name), length, note).model_dump()
    elif kind == "convert":
        _not_auto(name)
        size, ending, note = body.length, body.ending, body.note
        pipeline.check_convertible(p, size)  # 화수가 맞지 않으면 작업을 시작하기 전에 알린다
        label, total, owned = f"장편 {size}화로 전환 계획", 1, set()

        def fn(job: jobs.Job):
            return pipeline.propose_conversion(llm, store.load(name), size, ending, note).model_dump()
    elif kind == "rebuild":
        _not_auto(name)
        size, ending, note = body.length, body.ending, body.note
        span = pipeline.check_rebuild(p, size, body.span, ending)
        label, total, owned = f"장편 {size}화로 재구성 계획", 1, set()

        def fn(job: jobs.Job):
            return pipeline.propose_rebuild(llm, store.load(name), size, span, ending, note).model_dump()
    elif kind == "rework":
        _not_auto(name)
        if n is None:
            raise ValueError("화 번호(ep)가 필요합니다")
        x = p.archive.entry(n) if p.archive else None
        if x is None or x.use != "revise":
            raise ValueError(f"{n}화는 재구성에서 다듬기로 고른 화가 아닙니다")
        label, total, owned = f"{n}화 다듬기", 1, set()

        def fn(job: jobs.Job):
            return pipeline.propose_rework(llm, store.load(name), n).model_dump()
    elif kind == "storyline":
        label, total, owned = "이야기 줄기 제안", 1, set()
        note, line_kind = body.note, body.line_kind

        def fn(job: jobs.Job):
            return pipeline.suggest_storyline(llm, store.load(name), note, line_kind).model_dump()
    elif kind in ("recap_arc", "recap_part"):
        unit = kind.removeprefix("recap_")
        if n is None:
            raise ValueError("아크나 부 번호(ep)가 필요합니다")
        label, total, owned = f"{'아크' if unit == 'arc' else '부'} {n} 요약", 1, set()

        def fn(job: jobs.Job):
            return pipeline.recap(llm, store.load(name), unit, n).model_dump()
    elif kind == "plots":
        if not p.beats():
            raise ValueError("다음 아크를 먼저 기획하세요" if p.serial else "기승전결 구조(arc)를 먼저 만들고 저장하세요")
        ranges = _plot_ranges(p, n if p.serial else None)
        if not ranges:
            raise ValueError("모든 화가 확정되어 새로 만들 초안이 없습니다")
        draft = {e.plot.number for e in p.episodes if e.status == "draft"}
        have = {e.plot.number for e in p.episodes}
        owned = {k for _, a, b in ranges for k in range(a, b + 1) if k in draft or k not in have}
        label, total = "화별 플롯 초안", len(ranges)

        def fn(job: jobs.Job):
            # 구간마다 따로 부른다: 한 번에 20화를 받는 것보다 빠르게 첫 결과가 오고, 실패해도 앞 구간은 남는다
            for act, a, b in ranges:
                arc = store.load(name).arc_for(a)
                job.note = f"{f'아크 {arc.number} ' if arc else ''}{act} 구간 ({a}~{b}화) 만드는 중"
                batch = pipeline.draft_plots(llm, store.load(name), a, b)
                _edit(name, lambda q: pipeline.apply_plots(q, batch))
                job.done += 1
            job.note = ""
            return None
    elif kind in ("write", "state"):
        if n is None:
            raise ValueError("화 번호(ep)가 필요합니다")
        e = p.episode(n)
        if kind == "write":
            if e.status == "draft":
                raise ValueError(f"{n}화 플롯이 아직 확정되지 않았습니다")
            if body.rewrite is not None and e.text:  # 다시 생성: 새 판은 본문을 덮지 않고 고르기를 기다린다
                if e.status == "finalized":
                    raise ValueError(f"{n}화는 상태 반영까지 끝나 다시 생성할 수 없습니다")
                req = pipeline.clean_rewrite(body.rewrite)
                label, total, owned = f"{n}화 새 판", 1, {n}

                def fn(job: jobs.Job):
                    text = pipeline.rewrite_episode(llm, store.load(name), n, req)
                    _edit(name, lambda q: pipeline.set_candidate(q, n, text, req))
                    return {"candidate": True}
            else:
                label, total, owned = f"{n}화 본문", 1, {n}

                def fn(job: jobs.Job):
                    text = pipeline.write_episode(llm, store.load(name), n)
                    _edit(name, lambda q: pipeline.replace_text(q.episode(n), text))  # 지금 본문이 있으면 '이전 판'에 남는다
                    return None
        else:
            if not e.text:
                raise ValueError(f"{n}화 본문이 없습니다")
            label, total, owned = f"{n}화 상태 변경안", 1, set()

            def fn(job: jobs.Job):
                return pipeline.extract_state(llm, store.load(name), n).model_dump()
    elif kind in ("hook", "openings", "opening_drafts"):
        if n is None or not prompts.is_opening(n):
            raise ValueError(f"1~{prompts.OPENING_EPISODES}화 번호(ep)가 필요합니다")
        ways, k = body.approaches, body.draft
        if kind == "hook":
            if k:
                research.compare_text(name, n, k)  # 비교본이 없으면 바로 알린다
            elif not p.episode(n).text:
                raise ValueError(f"{n}화 본문이 없습니다")
            label, total, owned = f"{n}화 흡입력 판정" + (f" (비교본 {k}번)" if k else ""), 1, set()

            def fn(job: jobs.Job):
                q = store.load(name)
                rep = pipeline.check_hook(llm, q, n, research.compare_text(name, n, k) if k else None)
                if k:
                    research.save_compare_hook(name, n, k, rep)
                else:
                    _edit(name, lambda q: pipeline.apply_hook(q, rep))
                return rep.model_dump()
        elif kind == "openings":
            label, total, owned = f"{n}화 여는 방식 여러 안", 1, set()

            def fn(job: jobs.Job):
                return pipeline.suggest_openings(llm, store.load(name), n, ways).model_dump()
        else:
            if p.episode(n).status == "draft":
                raise ValueError(f"{n}화 플롯이 아직 확정되지 않았습니다")
            label, total, owned = f"{n}화 여러 안으로 쓰기", 1, set()

            def fn(job: jobs.Job):
                c = research.run_opening_compare(name, store.load(name), n, llm, ways)
                research.record(name, "compare", {"episode": n, "kind": "opening", "backends": [
                    prompts.OPENING_APPROACHES[a][0] for a in (ways or prompts.DEFAULT_APPROACHES) if a in prompts.OPENING_APPROACHES]})
                return {"episode": n, "count": len(c["drafts"])}
    elif kind == "impact":
        el = elements.get(p, body.element)
        eid = el.id
        if not el.name.strip() or not el.description.strip():
            raise ValueError("요소의 이름과 설명을 적고 저장한 뒤 분석하세요")
        label, total, owned = f"인과율: {el.name} 영향 분석", 1, set()

        def fn(job: jobs.Job):
            rep = pipeline.analyze_impact(llm, store.load(name), eid)
            _edit(name, lambda q: pipeline.record_impact(q, eid, rep))
            return {"element": eid}
    else:
        raise ValueError(f"모르는 작업입니다: {kind}")

    try:
        with usage.scope(episode=n if kind in ("write", "state", "rework", "hook", "openings", "opening_drafts") else None, task=kind):
            job = jobs.start(name, kind, n, label, fn, total=total, owned=owned)
    except jobs.Busy as b:
        return {**b.job.public(), "already": True}
    return job.public()


@app.get("/api/jobs")
def list_jobs(project: str | None = None) -> list[dict]:
    return [j.public() for j in jobs.listing(project)]


@app.get("/api/jobs/{jid}")
def get_job(jid: str) -> dict:
    j = jobs.get(jid)
    if j is None:
        raise HTTPException(404, "작업이 없습니다 (서버가 다시 시작됐을 수 있어요)")
    return j.public()


# ---------- 4. 본문 ----------

@app.post("/api/projects/{name}/episodes/{n}/write")
def write_episode(name: str, n: int) -> Project:
    p = _load(name)
    _not_auto(name)
    text = pipeline.write_episode(get_llm("write"), p, n)
    pipeline.replace_text(p.episode(n), text)  # 지금 본문이 있으면 '이전 판'에 남는다
    return _save(name, p)


class Text(BaseModel):
    text: str


@app.put("/api/projects/{name}/episodes/{n}/text")
def put_text(name: str, n: int, body: Text) -> Project:
    """직접 고친 본문이나 채팅 앱에서 받은 본문을 저장한다."""
    p = _load(name)
    ep = p.episode(n)
    if ep.status == "draft":
        raise ValueError(f"{n}화 플롯을 먼저 확정하세요")
    if ep.status == "finalized":
        raise ValueError(f"{n}화는 상태 반영까지 끝나 본문을 바꿀 수 없습니다")
    text = body.text.strip()
    pipeline.record_typed(p, n, ep.text, text)
    ep.text = text
    ep.status = "written" if ep.text else "confirmed"
    return _save(name, p)


# ---------- 4-1. 본문 부분 수정 ----------
# 집필 화면에서 고른 부분을 직접 고치거나(아래), AI 후보로 바꾼다(대화 'text:<화>', 3-1). 모두 Episode.edits 에 남는다.

def _text_guard(name: str, n: int) -> None:
    _not_auto(name)
    if any(j.status == "running" and n in j.owned for j in jobs.listing(name)):
        raise ValueError(f"{n}화 본문을 쓰는 작업이 도는 중입니다. 끝난 뒤에 고치세요")


# ---------- 4-0. 다시 생성 ----------

@app.get("/api/projects/{name}/episodes/{n}/rewrite")
def rewrite_info(name: str, n: int) -> dict:
    """다시 생성 패널: 빠른 요청과 함께 넣을 수 있는 재료(프롬프트에 들어갈 줄 그대로)."""
    p = _load(name)
    e = p.episode(n)
    mats = pipeline.rewrite_materials(p, n)
    last_edit = max((x.at for x in e.edits if not x.undone), default="")
    notes = {"issues": "검수한 뒤 본문을 고쳐서 이미 고친 곳일 수 있어요" if e.issues and last_edit > e.checked_at else "",
             "hook": "판정한 뒤 본문이 바뀌었어요" if mats["hook"] and pipeline.hook_stale(p, n) else ""}
    return {
        "presets": [{"id": k, "label": label} for k, (label, _) in prompts.REWRITE_PRESETS.items()],
        "materials": [{"id": k, "label": label, "lines": mats.get(k, []), "note": notes.get(k, "")}
                      for k, (label, _) in prompts.REWRITE_MATERIALS.items() if k != "hook" or prompts.is_opening(n)],
        "keep_max": prompts.REWRITE_KEEP,
    }


@app.post("/api/projects/{name}/episodes/{n}/rewrite/prompt")
def rewrite_prompt(name: str, n: int, body: RewriteRequest) -> dict:
    """다시 생성 때 보내는 프롬프트 원문 (보내지 않고 보기만)."""
    p = _load(name)
    return {"system": prompts.writer_system(p), "prompt": pipeline.rewrite_prompt(p, n, pipeline.clean_rewrite(body))}


def _no_write_job(name: str, n: int) -> None:
    if any(j.status == "running" and n in j.owned for j in jobs.listing(name)):
        raise ValueError(f"{n}화를 쓰는 작업이 도는 중입니다. 끝난 뒤에 하세요")


@app.post("/api/projects/{name}/episodes/{n}/candidate/adopt")
def adopt_candidate(name: str, n: int) -> Project:
    """새 판을 본문으로 쓴다. 지금 본문은 '이전 판'에 남는다."""
    _not_auto(name)
    _no_write_job(name, n)
    p = _load(name)
    pipeline.adopt_candidate(p, n)
    return _save(name, p)


@app.delete("/api/projects/{name}/episodes/{n}/candidate")
def drop_candidate(name: str, n: int) -> Project:
    p = _load(name)
    pipeline.drop_candidate(p, n)
    return _save(name, p)


@app.post("/api/projects/{name}/episodes/{n}/versions/{vid}/restore")
def restore_version(name: str, n: int, vid: str) -> Project:
    _not_auto(name)
    _no_write_job(name, n)
    p = _load(name)
    pipeline.restore_version(p, n, vid)
    return _save(name, p)


@app.get("/api/passage/presets")
def passage_presets() -> list[dict]:
    return [{"id": k, "label": label} for k, (label, _) in prompts.PASSAGE_PRESETS.items()]


class EditIn(BaseModel):
    selection: Selection
    after: str


@app.post("/api/projects/{name}/episodes/{n}/edits")
def edit_passage(name: str, n: int, body: EditIn) -> Project:
    """고른 부분을 작가가 직접 고친 글로 바꾼다."""
    _load(name).episode(n)
    _text_guard(name, n)
    return _edit(name, lambda p: pipeline.edit_text(p, n, body.selection, body.after.strip(), "manual"))


@app.post("/api/projects/{name}/episodes/{n}/edits/{eid}/undo")
def undo_passage(name: str, n: int, eid: str) -> Project:
    _load(name).episode(n)
    _text_guard(name, n)
    return _edit(name, lambda p: pipeline.undo_edit(p, n, eid))


# ---------- 4-2. 초반 1~3화 ----------

@app.get("/api/opening/approaches")
def opening_approaches() -> list[dict]:
    return [{"id": k, "label": label, "how": how, "default": k in prompts.DEFAULT_APPROACHES}
            for k, (label, how) in prompts.OPENING_APPROACHES.items()]


@app.get("/api/projects/{name}/episodes/{n}/opening")
def opening_check(name: str, n: int) -> dict:
    """1~3화 초반 지표(LLM 없음)와 마지막 흡입력 판정."""
    p = _load(name)
    e = p.episode(n)
    if not prompts.is_opening(n):
        raise ValueError(f"초반 점검은 1~{prompts.OPENING_EPISODES}화만 합니다")
    m, warnings = pipeline.opening_metrics(p, n) if e.text else (None, [])
    return {"metrics": m, "warnings": warnings, "hook": e.hook, "hook_stale": pipeline.hook_stale(p, n),
            "compare": research.load_compare(name, n)}


class OpeningPlotIn(BaseModel):
    plot: EpisodePlot


@app.post("/api/projects/{name}/episodes/{n}/opening-plot")
def opening_plot(name: str, n: int, body: OpeningPlotIn) -> Project:
    """여는 방식 여러 안에서 고른 플롯을 n화 플롯으로 쓴다 (확정했던 화는 초안으로)."""
    _load(name)
    _not_auto(name)
    return _edit(name, lambda p: pipeline.apply_opening(p, n, body.plot))


@app.get("/api/projects/{name}/episodes/{n}/context")
def context(name: str, n: int) -> list[dict]:
    """본문 생성에 들어가는 컨텍스트를 섹션별 글자 수로 보여준다."""
    p = _load(name)
    rules = prompts.opening_rules(p, n)
    text = prompts.build_episode_context(p, n) + (f"\n\n{rules}" if rules else "")
    out = []
    for block in re.split(r"^# ", text, flags=re.M):
        if block.strip():
            title, _, body = block.partition("\n")
            out.append({"title": title.strip(), "chars": len(body.strip())})
    return out


# ---------- 4-2. 복사 · 내보내기 (canon/publish.py) ----------

@app.get("/api/publish/formats")
def publish_formats() -> list[dict]:
    return [{"id": k, "label": label, "hint": hint} for k, (label, hint) in publish.FORMATS.items()]


class ExportIn(BaseModel):
    episodes: list[int] = []  # 비우면 본문이 있는 모든 화
    format: str = "blank"
    title: bool = True
    drafts: dict[int, str] = {}  # 저장 전 화면의 본문


def _export_numbers(p: Project, eps: list[int]) -> list[int]:
    have = {e.plot.number for e in p.episodes}
    bad = [n for n in eps if n not in have]
    if bad:
        raise ValueError(f"없는 화입니다: {', '.join(map(str, bad))}")
    return eps or sorted(e.plot.number for e in p.episodes if e.text)


@app.post("/api/projects/{name}/export")
def export_text(name: str, body: ExportIn) -> dict:
    """다른 곳에 붙여 넣을 글(텍스트와 HTML)을 만든다. 저장하지 않는다."""
    p = _load(name)
    return publish.export(p, _export_numbers(p, body.episodes), body.format, body.title, body.drafts)


@app.get("/api/projects/{name}/export.txt")
def export_file(name: str, start: int = 0, end: int = 0, format: str = "blank", title: bool = True) -> Response:
    """.txt 로 내려받기. start~end 화 (0 이면 처음 · 끝까지)."""
    from urllib.parse import quote

    p = _load(name)
    nums = [e.plot.number for e in p.episodes if e.text and (not start or e.plot.number >= start) and (not end or e.plot.number <= end)]
    out = publish.export(p, nums, format, title)
    return Response(out["text"], media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(out['filename'])}"})


# ---------- 4-3. 삽화 프롬프트 (NovelAI, canon/illust.py) ----------
# 본문을 바꾸지 않으므로 반영한 화에서도 만든다. 인물 외형 태그와 삽화 설정은 작품 저장(PUT)으로 저장한다.

@app.get("/api/illust/models")
def illust_models() -> list[dict]:
    return illust.models()


class IllustIn(BaseModel):
    selection: Selection | None = None  # 비우면 AI 가 이 화에서 장면을 고른다
    request: str = ""
    model: str = ""


@app.post("/api/projects/{name}/episodes/{n}/illust")
def make_illust(name: str, n: int, body: IllustIn) -> Project:
    p = _load(name)
    if body.model and body.model not in illust.MODELS:
        raise ValueError(f"모르는 모델입니다: {body.model}")
    ill = pipeline.illustrate(get_llm("illustration"), p, n, body.selection, body.request, body.model)
    return _edit(name, lambda q: pipeline.add_illustration(q, n, ill))


class IllustModel(BaseModel):
    model: str = ""


@app.post("/api/projects/{name}/episodes/{n}/illust/{iid}/rebuild")
def rebuild_illust(name: str, n: int, iid: str, body: IllustModel) -> Project:
    """모델이나 외형 태그를 바꾼 뒤 AI 없이 다시 조립한다."""
    _load(name).episode(n)
    return _edit(name, lambda p: pipeline.rebuild_illustration(p, n, iid, body.model))


class KeepLook(BaseModel):
    character_id: str


@app.post("/api/projects/{name}/episodes/{n}/illust/{iid}/keep-look")
def keep_illust_look(name: str, n: int, iid: str, body: KeepLook) -> Project:
    """삽화에서 AI 가 채운 외형 태그를 그 인물의 외형 태그로 저장한다."""
    _load(name).episode(n)
    return _edit(name, lambda p: pipeline.keep_illust_look(p, n, iid, body.character_id))


@app.delete("/api/projects/{name}/episodes/{n}/illust/{iid}")
def delete_illust(name: str, n: int, iid: str) -> Project:
    _load(name).episode(n)
    return _edit(name, lambda p: pipeline.remove_illustration(p, n, iid))


@app.post("/api/projects/{name}/characters/{cid}/look")
def suggest_look(name: str, cid: str) -> LookSuggestion:
    """인물 설정을 외형 태그로 옮긴 제안. 저장은 화면에서 고쳐 작품 저장으로 한다."""
    return pipeline.suggest_look(get_llm("illustration"), _load(name), cid)


@app.get("/api/projects/{name}/episodes/{n}/prompt")
def prompt(name: str, n: int) -> dict:
    p = _load(name)
    return {"system": prompts.writer_system(p), "prompt": prompts.episode_prompt(p, n)}


# ---------- 5. 상태 변경안 ----------

@app.post("/api/projects/{name}/episodes/{n}/state")
def extract_state(name: str, n: int) -> StateDelta:
    return pipeline.extract_state(get_llm("state"), _load(name), n)


class Raw(BaseModel):
    raw: str


@app.post("/api/projects/{name}/episodes/{n}/state/parse")
def parse_state(name: str, n: int, body: Raw) -> StateDelta:
    """채팅 앱이 돌려준 JSON 을 검사한다. 코드 블록 표시는 지운다."""
    p = _load(name)
    p.episode(n)
    raw = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", body.raw.strip())
    try:
        delta = StateDelta.model_validate_json(raw)
    except ValidationError as e:
        raise HTTPException(400, f"JSON 형식이 맞지 않습니다: {e.errors()[0]['msg']} ({'.'.join(map(str, e.errors()[0]['loc']))})")
    delta.episode = n
    return delta


@app.post("/api/projects/{name}/episodes/{n}/apply")
def apply_state(name: str, n: int, d: StateDelta) -> Project:
    """화면에서 고른 항목만 담긴 변경안을 반영하고 그 화를 끝낸다."""
    p = _load(name)
    _not_auto(name)
    ep = p.episode(n)
    if ep.status != "written":
        raise ValueError(f"{n}화는 본문이 작성된 상태가 아닙니다 (현재: {ep.status})")
    d.episode = n
    pipeline.apply_delta(p, d)
    return _save(name, p)


@app.post("/api/projects/{name}/revert/{n}")
def revert(name: str, n: int) -> Project:
    """n화 반영 직후로 되돌린다. 뒤 화의 본문은 남기고 반영만 취소한다 (0 이면 1화 시작 전)."""
    p = _load(name)
    _not_auto(name)
    pipeline.revert(p, n)
    return _save(name, p)


# ---------- 자동 집필 (canon/autorun.py) ----------

class AutoIn(BaseModel):
    target: int
    batch: bool = False
    policy: autorun.Policy = autorun.Policy()


def _auto(name: str) -> dict:
    p = _load(name)
    run = autorun.get_run(name)
    out = run.model_dump() if run else None
    if out and run.pending and (run.status != "review" or p.episode(run.ep).status != "written"):
        out["pending"] = None  # 사용자가 검토 화면에서 이미 반영했다
    return {"run": out, "active": autorun.active(name),
            "batch_stages": [s for s in ("write", "check", "state") if autorun.batchable(s)]}


@app.get("/api/projects/{name}/auto")
def auto_get(name: str) -> dict:
    return _auto(name)


@app.post("/api/projects/{name}/auto/estimate")
def auto_estimate(name: str, body: AutoIn) -> dict:
    return autorun.estimate(_load(name), body.target, body.batch, body.policy, name)


@app.post("/api/projects/{name}/auto/start")
def auto_start(name: str, body: AutoIn) -> dict:
    _load(name)
    autorun.start(name, body.target, body.batch, body.policy)
    return _auto(name)


class AutoResume(BaseModel):
    approve: bool = False  # 검토 대기 변경안을 그대로 반영
    rewrite: bool = False  # 검토 대기 화를 다시 쓰기


@app.post("/api/projects/{name}/auto/resume")
def auto_resume(name: str, body: AutoResume) -> dict:
    _load(name)
    autorun.resume(name, approve=body.approve, rewrite=body.rewrite)
    return _auto(name)


@app.post("/api/projects/{name}/auto/{what}")
def auto_request(name: str, what: str) -> dict:
    """what: pause | stop"""
    _load(name)
    if what not in ("pause", "stop"):
        raise HTTPException(404, "pause 또는 stop 만 됩니다")
    autorun.request(name, what)
    return _auto(name)


class AutoBatch(BaseModel):
    batch: bool


@app.put("/api/projects/{name}/auto/batch")
def auto_batch(name: str, body: AutoBatch) -> dict:
    _load(name)
    autorun.set_batch(name, body.batch)
    return _auto(name)


# ---------- 관계 (canon/dynamics.py 계산값) ----------

def _relations(p: Project) -> dict:
    """같은 관계를 말과 숫자 두 가지로 돌려준다. 화면 토글은 둘 중 하나를 보여 준다."""
    return {
        "words": dynamics.describe_relations(p, numbers=False),
        "numbers": dynamics.describe_relations(p, numbers=True),
        "show_numbers": p.settings.show_numbers,
    }


@app.get("/api/projects/{name}/relations")
def relations(name: str) -> dict:
    p = _load(name)
    dynamics.seed_ties(p)  # 아직 반영 전이면 설정값으로 시작 관계를 보여 준다
    dynamics.sync_relationships(p)
    return _relations(p)


@app.post("/api/projects/{name}/episodes/{n}/preview")
def preview(name: str, n: int, d: StateDelta) -> dict:
    """화면에서 고른 변경안을 복사본에 반영해, 반영 후 계산될 관계를 미리 보여 준다. 저장하지 않는다."""
    sim = _load(name)
    d.episode = n
    pipeline.apply_delta(sim, d)
    return _relations(sim)


class View(BaseModel):
    show_numbers: bool


@app.put("/api/projects/{name}/view")
def set_view(name: str, body: View) -> Project:
    p = _load(name)
    p.settings.show_numbers = body.show_numbers
    return _save(name, p)


# ---------- 작업지시서 ----------

@app.get("/api/projects/{name}/episodes/{n}/brief")
def brief(name: str, n: int, kind: str = "episode") -> dict:
    p = _load(name)
    if kind == "state":
        if not p.episode(n).text:
            raise ValueError(f"{n}화 본문이 없어 상태 정리 지시서를 만들 수 없습니다")
        return {"text": prompts.state_brief(p, n)}
    return {"text": prompts.episode_brief(p, n)}


# ---------- 연구 (모델 실험, 작품 데이터와 분리) ----------

@app.get("/api/usage")
def usage_summary(days: int = 30, project: str | None = None) -> dict:
    """AI 호출 기록을 기간과 작품으로 걸러 모은다. days 가 0 이면 전체."""
    return usage.summary(days or None, project or None)


@app.get("/api/usage/prices")
def usage_prices() -> dict:
    return usage.price_table()


class PricesIn(BaseModel):
    rows: list[usage.Price]


@app.put("/api/usage/prices")
def put_usage_prices(body: PricesIn) -> dict:
    usage.save_prices(body.rows)
    return usage.price_table()


@app.delete("/api/usage/prices")
def reset_usage_prices() -> dict:
    """가격표를 기본값(Google 가격표에서 옮긴 값)으로 되돌린다."""
    settings.set_prices([])
    return usage.price_table()


class Probe(BaseModel):
    url: str = ""
    key: str | None = None


@app.post("/api/research/probe")
def research_probe(body: Probe) -> dict:
    """로컬 서버 점검. 작품과 무관하게 쓴다."""
    try:
        return research.probe(body.url, body.key)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/projects/{name}/research")
def research_log(name: str) -> dict:
    _load(name)
    return {"log": research.history(name), "stages": research.STAGES}


class SampleIn(BaseModel):
    runs: list[research.Backend]
    system: str = prompts.SYSTEM_WRITER
    prompt: str
    temperature: float | None = None


@app.post("/api/projects/{name}/research/sample")
def research_sample(name: str, body: SampleIn) -> dict:
    _load(name)
    if not body.runs or not body.prompt.strip():
        raise ValueError("백엔드와 요청 문장을 넣으세요")
    rows = research.sample(body.runs, body.system, body.prompt, body.temperature)
    return research.record(name, "sample", {"system": body.system, "prompt": body.prompt,
                                            "temperature": body.temperature, "rows": rows})


class StageIn(BaseModel):
    backend: research.Backend
    stage: str
    sample: str = ""


@app.post("/api/projects/{name}/research/stage")
def research_stage(name: str, body: StageIn) -> dict:
    """설정 제안, 문체 분석, 기승전결을 저장하지 않고 돌린다."""
    row = research.stage_trial(_load(name), body.backend, body.stage, body.sample)
    return research.record(name, "stage", row)


@app.post("/api/projects/{name}/research/budget")
def research_budget(name: str, b: research.Backend) -> dict:
    res = research.budget(_load(name), b)
    summary = {k: res[k] for k in ("backend", "model", "limit", "first_over", "first_tight", "tokenizer")}
    return {**research.record(name, "budget", summary), **res}


class CompareIn(BaseModel):
    a: research.Backend
    b: research.Backend


@app.get("/api/projects/{name}/research/compare/{n}")
def research_compare_get(name: str, n: int) -> dict:
    _load(name)
    return {"compare": research.load_compare(name, n)}


@app.post("/api/projects/{name}/research/compare/{n}")
def research_compare(name: str, n: int, body: CompareIn) -> dict:
    p = _load(name)
    c = research.run_compare(name, p, n, body.a, body.b)
    research.record(name, "compare", {"episode": n, "backends": [research.label(body.a), research.label(body.b)]})
    return {"compare": c}


class Pick(BaseModel):
    k: int
    adopt: bool = True


@app.post("/api/projects/{name}/research/compare/{n}/pick")
def research_pick(name: str, n: int, body: Pick) -> dict:
    """고른 번호를 공개한다. adopt 면 그 본문을 그 화 본문으로 저장한다."""
    p = _load(name)
    r = research.pick_compare(name, p, n, body.k, body.adopt)
    if body.adopt:
        _save(name, p)
    research.record(name, "pick", {"episode": n, **r})
    return {"compare": research.load_compare(name, n), "result": r, "project": p}


# ---------- 화면 ----------

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


def serve(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = False,
          update_interval: float = 0) -> None:
    """update_interval(초)이 0보다 크면 그 간격으로 origin/main 을 확인하고,
    새 코드를 받으면 진행 중인 요청이 끝난 뒤 다시 시작한다."""
    import threading
    import time
    import webbrowser

    import uvicorn

    from . import updater

    shown = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    url = f"http://{shown}:{port}"
    print(f"Canon 웹 UI: {url}")
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port))
    restart = threading.Event()

    def open_when_ready() -> None:
        # 서버가 포트를 연 뒤에 브라우저를 띄운다. 포트가 이미 쓰이고 있으면 열지 않는다.
        while not server.started:
            if server.should_exit:
                return
            time.sleep(0.1)
        webbrowser.open(url)

    def watch_updates() -> None:
        last = ""
        while not server.should_exit:
            time.sleep(update_interval)
            r = updater.update()
            if not r.updated:
                if r.message != last:  # 같은 사유를 매번 찍지 않는다
                    print(f"[업데이트] {r.message}")
                last = r.message
                continue
            print(f"[업데이트] {r.message}. 진행 중인 작업이 끝나면 다시 시작합니다")
            jobs.draining.set()  # 자동 집필은 다음 단계 전에 멈추고, 다시 시작한 서버가 이어 간다
            while (_active or jobs.running()) and not server.should_exit:
                time.sleep(1)
            restart.set()
            server.should_exit = True
            return

    if open_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    if update_interval > 0:
        threading.Thread(target=watch_updates, daemon=True).start()
    for name in autorun.resume_all():
        print(f"[자동 집필] {name} 을(를) 이어 갑니다")
    server.run()
    if restart.is_set():
        updater.restart(no_browser=True)
