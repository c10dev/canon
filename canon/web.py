"""웹 UI 서버. `python -m canon serve` 로 실행한다.

CLI 와 같은 store / pipeline / prompts 를 그대로 쓰고, 화면은 canon/static/ 의 정적 파일이다.
AI 가 만든 제안(설정, 문체, 구조, 상태 변경안)은 바로 저장하지 않고 돌려주며,
사용자가 화면에서 고르거나 고친 뒤 저장 요청을 보낼 때 반영한다.
"""
from __future__ import annotations

import json
import logging
import random
import re
import threading
from pathlib import Path
from typing import Literal
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import agent, archetypes, autorun, board, cancel, cast, charlog, dynamics, elements, genres, illust, jobs, library, metrics, naming, pipeline, prompts, publish, research, settings, store, usage
from .llm import GeminiLLM, LocalLLM, MissingKey, get_llm, make_llm
from . import claude  # Claude 백엔드 (구독 로그인 상태, 모델 목록)
from .schema import (Ability, ArcPlan, BodySuggestion, StatInitSuggestion, StatSkin, StatWindowSuggestion, Character, WorldSetting, ArcProposal, EpisodePlot, LookSuggestion, VoiceSuggestion, Meta, Project, RewriteRequest, Selection, SerialConversion, SerialRebuild, SeriesPlan, SetupSuggestion, StateDelta,
                     StorylineProposal, StyleEntry, StyleProfile)
from . import abilities, atlas, findings, foreshadows, setupchat, stattrial, statwin, timeline, travel
from .schema import AgentSession, ChatScope, Deadline, Storyboard, StoryTime, Foreshadow, MapPin, MapSpec, NewPlace, StatValue
from .metrics import StyleMetrics
from .schema import CharacterState, ConsistencyReport, FindingStatus, Severity, StoryEvent
from .schema import FieldIdeas, NameOption, Recap
from . import branches
from .schema import BranchDiff, BranchInfo, ForkMode
from . import birth, play
from . import tofix
from .schema import Birth, BirthSketch, Episode, PlayInfo, PlayPerson, PlayUnit

STATIC = Path(__file__).parent / "static"
# 폴더 이름: / \ 와 운영체제가 막는 : * ? " < > | 는 쓸 수 없고, . 으로 시작하지 않는다
NAME_RE = re.compile(r'^[^/\\.:*?"<>|][^/\\:*?"<>|]{0,63}$')
NAME_ERR = '폴더 이름에 / \\ : * ? " < > | 는 쓸 수 없고, . 으로 시작할 수 없어요 (64자까지)'

# 연산 이름(operationId)은 함수 이름이다. Swift 앱(swift/)이 openapi.json 으로 클라이언트를 만들 때 이 이름을 쓴다
app = FastAPI(title="Canon", generate_unique_id_function=lambda route: route.name)
# 다른 기기(Tailscale)에서 열 때 작품 JSON 과 정적 파일을 줄여 보낸다
# 압축 단계 4: 장편 작품 GET(약 10MB)에서 기본 9 보다 압축이 0.2초 빠르고 크기는 9% 커질 뿐이다 (2026-10-29 실측)
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=4)
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
    # 화면(브라우저 탭)이 보낸 id. 이 요청이 저장하면 그 화면의 저장으로 센다 (store.writer, 오래된 화면 충돌 검사)
    tok = store.writer.set(request.headers.get("x-canon-client", "")[:64])
    try:
        with usage.scope(**_usage_scope(request.url.path)):
            return await call_next(request)
    finally:
        store.writer.reset(tok)
        _active -= 1


@app.exception_handler(ValueError)
@app.exception_handler(KeyError)
async def _bad_request(_: Request, e: Exception) -> JSONResponse:
    msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
    return JSONResponse({"detail": str(msg)}, status_code=400)


@app.exception_handler(MissingKey)
async def _no_key(_: Request, e: MissingKey) -> JSONResponse:
    # 첫 실행에 흔한 상황이라 서버 오류가 아니라 설정 안내로 보인다
    return JSONResponse({"detail": "Gemini API 키가 없어요. 오른쪽 아래 '모델 · API 키 설정'에서 넣으세요", "code": "no_key"}, status_code=400)


@app.exception_handler(Exception)
async def _server_error(_: Request, e: Exception) -> JSONResponse:
    # 응답 실패 등을 화면에 그대로 보여 준다. 예외 이름과 자세한 내용은 서버 로그에만 남긴다
    logging.getLogger("canon").exception("요청 처리 중 오류")
    return JSONResponse({"detail": str(e) or "서버에서 오류가 났어요. 서버 로그를 확인하세요"}, status_code=500)


def _load(name: str) -> Project:
    if not NAME_RE.match(name) or not store.exists(name):
        raise HTTPException(404, f"프로젝트가 없어요: {name}")
    return store.load(name)


def _view(name: str) -> Project:
    """읽기만 하는 엔드포인트용 _load. 같은 판이면 전에 검증한 것을 함께 쓰므로 돌려받은 작품을 고치지 않는다 (store.load_view)."""
    if not NAME_RE.match(name) or not store.exists(name):
        raise HTTPException(404, f"프로젝트가 없어요: {name}")
    return store.load_view(name)


def _save(name: str, p: Project, merged: set[str] | None = None, kept: list[dict] | None = None) -> Project:
    """저장한다. 화면이 보낸 작품 전체를 저장할 때(merged 를 넘길 때)는 백그라운드 작업이 맡은 화를
    디스크에 있는 내용(작업 결과)으로 지킨다. 다른 엔드포인트는 방금 읽은 디스크 내용을 고쳐 저장하므로 그대로 쓴다.
    kept 를 넘기면 화면 값 대신 디스크 것으로 둔 칸을 담는다 (autorun.protected 와 같은 모양)."""
    kept = kept if kept is not None else []
    with jobs.project_lock(name):
        owned = jobs.owned_episodes(name, merged) if merged is not None else set()
        if owned and store.exists(name):
            disk = {e.plot.number: e for e in store.load(name).episodes}
            mine = {e.plot.number: e for e in p.episodes}
            for n in owned:
                if n in disk:
                    if n in mine and mine[n].plot != disk[n].plot:
                        kept.append({"field": "plot", "ep": n})
                    mine[n] = disk[n]
            p.episodes = [mine[k] for k in sorted(mine)]
        if merged is not None and store.exists(name):
            disk = store.load(name)
            # 자동 집필이 반영한 진행을 오래된 화면이 덮지 않게
            kept += [k for k in autorun.protected(name, disk, p) if k not in kept]
            # 화면이 열린 동안 플롯 작업이 더한 새 인물 후보도 지킨다. 안 쓰이거나 등록된 후보는 sync 가 지운다
            have = {c.id for c in p.cast_candidates}
            p.cast_candidates += [c for c in disk.cast_candidates if c.id not in have]
            have = {x.name for x in p.place_candidates}
            p.place_candidates += [x for x in disk.place_candidates if x.name not in have]
            pipeline.sync_candidates(p)
            # 고칠 곳은 전용 엔드포인트로만 바꾼다. 화면이 들고 있던 옛 목록이 자동 집필 중에 단 표시를 덮지 않게
            marks = {e.plot.number: e.to_fix for e in disk.episodes}
            for e in p.episodes:
                e.to_fix = marks.get(e.plot.number, [])
        store.save(name, p)
    return p


def _not_auto(name: str) -> None:
    if autorun.active(name):
        raise ValueError("자동 집필이 도는 중이에요. 일시정지한 뒤에 하세요")


class _Out(BaseModel):
    """응답 모델: 기본값이 있는 칸도 응답에는 늘 있으니 명세에서 필수로 적는다 (Swift 타입이 옵셔널이 되지 않게).
    null 이 될 수 있는 칸은 scripts/make_openapi.py 의 drop_null 이 옵셔널로 바꾼다."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True, populate_by_name=True)


# ---------- 프로젝트 ----------

class NewProject(BaseModel):
    name: str
    meta: Meta
    style_id: str = ""  # 문체 라이브러리에서 고른 항목


class StageConfig(_Out):
    """단계 하나가 지금 쓰는 백엔드와 모델 (settings.public 의 stages)."""
    provider: str
    source: str
    model: str  # 화면에 보일 모델 이름
    model_source: str
    env: str  # 백엔드를 정한 환경 변수 이름. 없으면 ""
    model_env: str


class StagePreset(_Out):
    """단계별 백엔드 · 모델 묶음 (settings.presets). builtin 이면 기본 묶음이라 지울 수 없다."""
    id: str
    name: str
    stages: dict[str, str]
    stage_models: dict[str, str]
    builtin: bool


class ConfigView(_Out):
    """설정 화면이 보는 값 (settings.public). 키 원문은 없고 끝 네 글자(`key_hint`)와 출처만 있다."""
    provider: str
    provider_source: str
    model: str
    model_setting: str
    model_source: str
    has_key: bool
    key_hint: str
    key_source: str
    gemini_auth: str
    gemini_auth_source: str
    vertex_credentials: str  # 키 파일 경로 (내용이 아님)
    vertex_credentials_source: str
    vertex_credentials_found: bool
    vertex_project: str
    vertex_project_source: str
    vertex_location: str
    vertex_location_source: str
    local_url: str
    local_url_source: str
    local_model: str
    local_model_source: str
    has_local_key: bool
    claude_model: str
    claude_model_source: str
    claude_bin: str
    claude_bin_source: str
    anthropic_key_hint: str
    anthropic_key_source: str
    stages: dict[str, StageConfig]
    stage_settings: dict[str, str]  # 설정 파일에 적은 단계별 백엔드
    stage_model_settings: dict[str, str]
    stage_presets: list[StagePreset] = []
    path: str  # 설정 파일 경로


class ConfigTest(_Out):
    ok: bool
    message: str


class ModelList(_Out):
    """백엔드 하나의 모델 목록. 못 불러오면 models 가 비고 error · reason(no_key | unreachable | other)이 찬다."""
    models: list[str] = []
    error: str = ""
    reason: str = ""


class ConfigHealth(_Out):
    """AI 를 쓸 수 있는지 (작품 목록 · 사이드바 경고). local 은 로컬을 쓰지 않으면 null."""
    mock: bool
    gemini: bool
    has_key: bool
    local: bool | None = None
    local_error: str = ""


class ClaudeAccount(_Out):
    """Claude Code `auth status` 에서 화면에 보일 칸만 (claude.STATUS_FIELDS)."""
    loggedIn: bool = False
    authMethod: str = ""
    apiProvider: str = ""
    email: str = ""
    orgName: str = ""
    organizationName: str = ""
    subscriptionType: str = ""


class ClaudeStatus(_Out):
    """Claude Code 설치와 구독 로그인 상태 (claude.status). reason: ok | login | metered | install | error."""
    installed: bool
    path: str
    version: str
    logged_in: bool
    account: ClaudeAccount = ClaudeAccount()
    env_token: bool
    api_key_ignored: bool
    message: str
    reason: str
    login_command: str
    token_command: str
    auth_method: str = ""
    metered: bool = False


@app.get("/api/config")
def config() -> ConfigView:
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
    claude_model: str | None = None
    claude_bin: str | None = None
    anthropic_api_key: str | None = None  # Claude Console API 키. 구독 로그인은 Claude Code 가 따로 관리
    clear_anthropic_key: bool = False
    gemini_auth: str | None = None  # key | vertex
    vertex_credentials: str | None = None  # 서비스 계정 JSON 키 파일 경로 (내용이 아니라 경로)
    vertex_project: str | None = None
    vertex_location: str | None = None


@app.put("/api/config")
def put_config(body: SettingsIn) -> ConfigView:
    choices = settings.PROVIDERS
    if body.provider is not None and body.provider not in choices:
        raise HTTPException(400, f"provider는 {' / '.join(choices)} 중 하나예요")
    for stage, value in (body.stages or {}).items():
        if stage not in settings.STAGES or (value and value not in choices):
            raise HTTPException(400, f"단계 설정이 잘못됐어요: {stage}={value}")
    for stage in body.stage_models or {}:
        if stage not in settings.STAGES:
            raise HTTPException(400, f"알 수 없는 단계예요: {stage}")
    if body.gemini_auth not in (None, "", "key", "vertex"):
        raise HTTPException(400, "Gemini 연결 방식은 key / vertex 중 하나예요")
    if body.vertex_credentials and body.vertex_credentials.lstrip().startswith("{"):
        raise HTTPException(400, "키 파일 내용 말고 파일 경로를 적어 주세요 (예: ~/.canon/vertex-key.json)")
    settings.update(provider=body.provider, model=body.model, api_key=body.api_key, clear_key=body.clear_key,
                    local_url=body.local_url, local_model=body.local_model, local_key=body.local_key,
                    stages=body.stages, stage_models=body.stage_models, claude_model=body.claude_model,
                    claude_bin=body.claude_bin, anthropic_api_key=body.anthropic_api_key,
                    clear_anthropic_key=body.clear_anthropic_key, gemini_auth=body.gemini_auth,
                    vertex_credentials=body.vertex_credentials, vertex_project=body.vertex_project,
                    vertex_location=body.vertex_location)
    return settings.public()


class PresetIn(BaseModel):
    name: str
    stages: dict[str, str] = {}
    stage_models: dict[str, str] = {}


@app.post("/api/config/presets")
def save_stage_preset(body: PresetIn) -> ConfigView:
    """설정 화면 단계 칸을 이름 붙여 내 프리셋으로 저장한다. 단계 설정 자체는 바꾸지 않는다."""
    try:
        settings.save_preset(body.name, body.stages, body.stage_models)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return settings.public()


@app.delete("/api/config/presets/{preset_id}")
def delete_stage_preset(preset_id: str) -> ConfigView:
    try:
        settings.delete_preset(preset_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except KeyError:
        raise HTTPException(404, "그 프리셋이 없어요")
    return settings.public()


@app.post("/api/config/test")
def test_config() -> ConfigTest:
    """단계에서 쓰는 백엔드와 모델마다 연결을 확인한다. 본문 생성 비용은 들지 않는다."""
    used = {(settings.stage_provider(s)[0], settings.stage_model(s)[0]) for s in settings.STAGES}
    used = {u for u in used if u[0] != "mock"}
    if not used:
        return {"ok": True, "message": "mock 모드예요. 실제 AI 를 호출하지 않아요."}
    done = []
    for prov, model in sorted(used):
        try:
            llm = make_llm(prov, model)
            llm.check()
        except Exception as e:  # SDK 오류 종류가 많아 메시지만 보여준다
            raise HTTPException(400, f"{prov} {model or ''} 연결 실패: {getattr(e, 'message', None) or e}")
        done.append(llm.model)
    return {"ok": True, "message": f"{', '.join(dict.fromkeys(done))} 에 연결됐어요."}


@app.get("/api/config/models")
def config_models() -> dict[str, ModelList]:
    """설정 화면의 모델 목록. 백엔드마다 실제로 쓸 수 있는 모델을 묻고, 실패하면 이유만 돌려준다."""
    out = {"claude": {"models": claude.CLI_MODELS, "error": ""}}
    makers = [("gemini", GeminiLLM), ("local", lambda: LocalLLM(timeout=5))]
    if settings.anthropic_key()[0]:
        makers.append(("claude-api", claude.ClaudeAPILLM))
    for prov, make in makers:
        try:
            out[prov] = {"models": make().models(), "error": "", "reason": ""}
        except Exception as e:  # 키가 없거나 서버가 꺼져 있어도 화면은 열려야 한다
            reason = "no_key" if isinstance(e, MissingKey) else "unreachable" if prov == "local" and "연결하지 못했" in str(e) else "other"
            out[prov] = {"models": [], "error": str(getattr(e, "message", None) or e), "reason": reason}
    return out


@app.get("/api/config/health")
def config_health() -> ConfigHealth:
    """AI 를 쓸 수 있는지. 작품 목록 · 사이드바 경고에 쓴다: 키 없음, 로컬 서버 응답 없음, mock(가짜 결과)."""
    pub = settings.public()
    provs = {v["provider"] for v in pub["stages"].values()}
    out = {"mock": "mock" in provs, "gemini": "gemini" in provs, "has_key": pub["has_key"], "local": None, "local_error": ""}
    if "local" in provs:
        try:
            LocalLLM(timeout=2).models()
            out["local"] = True
        except Exception as e:  # 꺼져 있거나 주소가 틀렸다
            out["local"], out["local_error"] = False, str(getattr(e, "message", None) or e)
    return out


@app.get("/api/claude/status")
def claude_status() -> ClaudeStatus:
    """Claude Code 설치와 구독 로그인 상태. 로그인은 Claude Code 가 하고 Canon 은 상태만 본다 (claude.py)."""
    return claude.status()


class PlayCard(_Out):
    """작품 목록의 플레이 정보 (ProjectCard.play). 화면은 플레이 사본을 세계 작품 카드 안에 묶는다."""
    world: str
    title: str
    player: str = Field(description="플레이어 인물 이름")
    origin: str
    ending: str
    turns: int
    decisions: int
    days: int = Field(description="시작부터 지난 작품 속 날수. 모르면 0")
    waiting: bool = Field(description="결정 장면에서 멈춰 있다")


class ProjectCard(BaseModel):
    """작품 목록의 카드 한 장."""
    name: str
    title: str
    genre: str
    form: str
    episodes: int
    finalized: int
    planned: int
    open_ep: int
    open_status: str
    updated_at: str
    branch: BranchInfo | None = Field(None, description="갈래 정보. 갈래가 없는 작품이면 비움 (같은 family 끼리 묶어 보인다)")
    play: PlayCard | None = Field(None, description="플레이 정보. 플레이 사본이 아니면 비움 (화면은 세계 작품 카드 안에 묶는다)")


@app.get("/api/projects")
def list_projects() -> list[ProjectCard]:
    """작품 카드: 형식, 다음에 할 화(open_ep · open_status, 없으면 0 · ''), 고친 시각, 갈래 정보. 최근에 고친 작품부터."""
    from datetime import datetime, timezone
    out = []
    tree = branches.infos()
    if store.ROOT.exists():
        for d in sorted(store.ROOT.iterdir()):
            f = d / "project.json"
            if f.exists():
                p = store.load(d.name)
                done = sum(e.status == "finalized" for e in p.episodes)
                todo = next((e for e in sorted(p.episodes, key=lambda e: e.plot.number) if e.status != "finalized"), None)
                mtime = f.stat().st_mtime
                out.append({"name": d.name, "title": p.meta.title, "genre": p.meta.genre, "form": p.meta.form,
                            "episodes": p.meta.target_episodes, "finalized": done, "planned": len(p.episodes),
                            "open_ep": todo.plot.number if todo else 0, "open_status": todo.status if todo else "",
                            "updated_at": datetime.fromtimestamp(mtime, timezone.utc).isoformat(), "_mtime": mtime,
                            "branch": tree.get(d.name), "play": (_play_card(p, info) if (info := store.load_play(d.name)) else None)})
    out.sort(key=lambda x: -x["_mtime"])
    return [{k: v for k, v in x.items() if k != "_mtime"} for x in out]  # play.json 은 project.json 보다 자주 바뀌지만 고친 때는 작품 기준


class NewName(BaseModel):
    name: str


def _free(name: str) -> None:
    """작업이나 자동 집필이 이 작품을 쓰는 중이면 작품 폴더를 옮기거나 지우지 않는다."""
    _not_auto(name)
    if any(j.status == "running" for j in jobs.listing(name)):
        raise ValueError("이 작품의 AI 작업이 도는 중이에요. 끝나거나 멈춘 뒤에 하세요")


def _new_name(body: NewName) -> str:
    new = body.name.strip()
    if not NAME_RE.match(new):
        raise HTTPException(400, NAME_ERR)
    if store.exists(new):
        raise HTTPException(409, f"이미 있는 이름이에요: {new}")
    return new


@app.post("/api/projects/{name}/duplicate")
def duplicate_project(name: str, body: NewName) -> dict:
    """작품 폴더를 통째로 복사한다 (시험해 볼 사본). 자동 집필 기록과 검토 대기 결과는 옮기지 않는다.
    갈래 정보(branch.json)도 옮기지 않는다. 같은 id 가 둘이 되면 갈래 집안이 꼬인다. 갈래는 make_branch 로 만든다."""
    _load(name)
    new = _new_name(body)
    import shutil
    shutil.copytree(store.project_dir(name), store.project_dir(new),
                    ignore=shutil.ignore_patterns(*branches.COPY_SKIP, "branch.json"))
    return {"name": new}


# ---------- 갈래 (canon/branches.py) ----------
# 갈래 정보는 작품 폴더의 branch.json 에 있어 화면이 작품을 저장해도 덮지 않는다. 원본 project.json 은 바꾸지 않는다.

class BranchIn(BaseModel):
    to: str = Field(description="갈래 작품의 폴더 이름")
    from_ep: int = Field(description="이 화부터 갈라진다")
    mode: ForkMode = Field("clear", description="clear: 이 화부터의 본문을 이전 판으로 남기고 비운다 / keep: 본문을 남기고 상태 승인을 다시 한다")
    label: str = Field("", description="갈래 이름")


class BranchMember(BaseModel):
    """갈래 집안의 작품 하나."""
    name: str
    title: str
    info: BranchInfo
    parent_name: str = Field("", description="갈라져 나온 작품의 폴더 이름. 본편이거나 그 작품을 지웠으면 빈 값")
    depth: int = Field(0, description="본편에서 몇 번 갈라졌는지 (본편 0)")
    finalized: int = 0
    planned: int = 0
    episodes: int = Field(0, description="총 화수")
    shared_edited: bool = Field(False, description="이 갈래에서 함께 쓰는 앞 화(1~(from_ep-1)화)를 갈라진 뒤에 고쳤다")
    parent_edited: bool = Field(False, description="갈라져 나온 작품에서 함께 쓰는 앞 화를 갈라진 뒤에 고쳤다")


class BranchFamily(BaseModel):
    main: str = Field("", description="본편 폴더 이름. 갈래가 없으면 빈 값")
    members: list[BranchMember] = Field(default_factory=list, description="본편부터 차례로. 자식 갈래는 갈라진 화 순서로 부모 바로 뒤에")


def _family(name: str) -> BranchFamily:
    fam = branches.family(branches.infos(), name)
    if not fam:
        return BranchFamily()
    by_id = {v.id: k for k, v in fam.items()}
    loaded = {k: store.load_view(k) for k in fam}
    members = []
    for k, depth in branches.order(fam):
        b, p = fam[k], loaded[k]
        up = by_id.get(b.parent, "")
        members.append(BranchMember(
            name=k, title=p.meta.title, info=b, parent_name=up, depth=depth,
            finalized=sum(e.status == "finalized" for e in p.episodes), planned=len(p.episodes), episodes=p.meta.target_episodes,
            shared_edited=branches.shared_edited(p, b), parent_edited=bool(up) and branches.shared_edited(loaded[up], b)))
    return BranchFamily(main=branches.main_of(fam), members=members)


def _relink(fam: dict[str, BranchInfo], name: str) -> None:
    """name 을 갈래 집안(fam)에서 빼고 남은 갈래를 다시 잇는다. 혼자 남은 작품은 갈래 정보를 지운다."""
    if name not in fam:
        return
    for k, v in branches.remove(fam, name).items():
        store.save_branch(k, v)
    rest = [k for k in fam if k != name]
    if len(rest) == 1:
        store.drop_branch(rest[0])


@app.post("/api/projects/{name}/branch")
def make_branch(name: str, body: BranchIn) -> BranchMember:
    """n화부터 갈래를 만든다. 작품 폴더를 복사하고 사본을 n-1화 반영 직후로 되돌린다. 원본 project.json 은 그대로다."""
    _load(name)
    _free(name)
    to = _new_name(NewName(name=body.to))
    with jobs.project_lock(name):
        branches.make(name, to, body.from_ep, body.mode, body.label)
    return next(m for m in _family(to).members if m.name == to)


@app.get("/api/projects/{name}/branches")
def branch_family(name: str) -> BranchFamily:
    """이 작품이 속한 갈래 집안. 갈래가 없으면 빈 목록."""
    _view(name)
    return _family(name)


@app.get("/api/projects/{name}/compare/{other}")
def compare_branches(name: str, other: str, ep: int = 0) -> BranchDiff:
    """같은 집안의 두 작품을 견준다. ep 를 주지 않으면 두 작품이 함께 반영한 마지막 화(갈라진 화보다 앞이면 갈라진 화)."""
    _load(name)
    _load(other)
    return branches.compare_saved(name, other, ep)


@app.post("/api/projects/{name}/promote")
def promote_branch(name: str) -> BranchFamily:
    """이 갈래를 본편으로 올린다. 갈래 정보만 바꾸고 폴더 이름과 작품 데이터는 그대로다."""
    _load(name)
    branches.promote_saved(name)
    return _family(name)


@app.post("/api/projects/{name}/detach")
def detach_branch(name: str) -> BranchFamily:
    """갈래를 끊어 따로 선 작품으로 만든다. 이 작품에서 갈라진 갈래는 이 작품의 부모에 다시 잇는다. 작품 데이터는 그대로다."""
    _load(name)
    fam = branches.family(branches.infos(), name)
    if name not in fam:
        raise ValueError("갈래가 없는 작품이에요")
    _relink(fam, name)
    store.drop_branch(name)
    return _family(name)


@app.post("/api/projects/{name}/rename")
def rename_project(name: str, body: NewName) -> dict:
    """작품 폴더 이름(주소)을 바꾼다. 작품 제목은 설정 도우미에서 바꾼다."""
    _load(name)
    _free(name)
    new = _new_name(body)
    store.project_dir(name).rename(store.project_dir(new))
    return {"name": new}


@app.delete("/api/projects/{name}")
def delete_project(name: str) -> dict:
    """작품을 지운다. 바로 없애지 않고 projects/.trash/<이름>-<시각> 로 옮겨 서버에서 되살릴 수 있게 한다."""
    _load(name)
    _free(name)
    from datetime import datetime
    fam = branches.family(branches.infos(), name)  # 옮기기 전에 읽는다 (휴지통의 branch.json 은 집안에서 빠진다)
    trash = store.ROOT / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    store.project_dir(name).rename(dest)
    _relink(fam, name)  # 이 작품에서 갈라진 갈래는 이 작품의 부모에 다시 잇는다
    return {"ok": True, "trash": str(dest)}


class TieFix(BaseModel):
    source: str
    target: str
    warmth: float | None = None
    trust: float | None = None


@app.post("/api/projects/{name}/ties/adjust")
def adjust_tie(name: str, body: TieFix) -> Project:
    """관계 수치를 작가가 직접 고친다. AI 가 아니라 '수동보정' 사건으로 기록해 재생할 수 있게 한다 (pipeline.adjust_tie)."""
    _not_auto(name)
    p = _load(name)
    ids = {c.id for c in p.characters}
    if body.source not in ids or body.target not in ids or body.source == body.target:
        raise ValueError("두 인물을 고르세요")
    if body.warmth is not None and not -1 <= body.warmth <= 1 or body.trust is not None and not 0 <= body.trust <= 1:
        raise ValueError("온기는 -1~1, 신뢰는 0~1 이에요")
    pipeline.adjust_tie(p, body.source, body.target, body.warmth, body.trust)
    return _save(name, p)


@app.post("/api/projects")
def create_project(body: NewProject) -> Project:
    name = body.name.strip()
    if not NAME_RE.match(name):
        raise HTTPException(400, NAME_ERR)
    if store.exists(name):
        raise HTTPException(409, f"이미 있는 프로젝트예요: {name}")
    if not 1 <= body.meta.target_episodes <= 1000:
        raise HTTPException(400, "총 화수는 1~1000 사이로 적으세요")
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
def get_project(name: str, request: Request) -> Response:
    """작품 전체. 화면이 가진 판(ETag)과 같으면 304 로 본문 없이 답한다 (장편은 수 MB 라 화면 이동마다 받지 않게)."""
    path = store.project_dir(name) / "project.json"
    tag = None
    if NAME_RE.match(name) and path.exists():
        st = path.stat()
        tag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers={"ETag": tag})
    p = _view(name)
    return JSONResponse(p.model_dump(mode="json"), headers={"ETag": tag} if tag else None)


@app.put("/api/projects/{name}")
def put_project(name: str, p: Project, response: Response, merged: str = "", force: bool = False) -> Project:
    """화면에서 고친 프로젝트 전체를 저장한다. 구조(arc)가 있으면 화수와 맞는지 검사한다.
    장편은 부 구성과 아크(아크 안 기승전결 포함)가 이어지는지 검사한다.
    다른 화면(탭 · 기기)이 이 화면이 읽은 뒤에 저장했으면 덮지 않고 409 를 돌려준다. force 면 그래도 덮는다."""
    disk = _load(name)
    # 장편 총 화수를 바꾸면 마지막 부 끝 화도 따라간다 (둘은 다른 화면에서 고치지만 한 번에 맞아야 저장된다)
    last = p.parts[-1] if p.serial and p.parts else None
    if last and last.end_ep == disk.meta.target_episodes != p.meta.target_episodes and p.meta.target_episodes >= last.start_ep:
        last.end_ep = p.meta.target_episodes
    me = store.writer.get()
    if me and not force and disk.edit_rev > p.edit_rev and disk.saved_by != me:
        raise HTTPException(409, "다른 탭이나 기기에서 이 작품을 먼저 저장했어요. 다시 불러와 그 변경을 보거나, 내 변경으로 덮어쓰세요")
    if p.arc and not p.serial:
        pipeline.validate_arc(ArcPlan(acts=p.arc), p.meta.target_episodes)
    if p.serial:
        pipeline.validate_parts(p.parts, p.meta.target_episodes)
        pipeline.validate_story_arcs(p)
    pipeline.validate_storylines(p)
    pipeline.validate_characters(p, disk)
    pipeline.validate_relationships(p)
    pipeline._init_states(p)
    p.meta.genre = genres.label(p.meta)
    if p.snapshot(0) is None:  # 첫 반영 전에는 설정 화면의 시작 호감이 시작 관계다
        p.ties = []
        dynamics.seed_ties(p)
    elements.stamp(p)
    _keep_impacts(name, p)
    _keep_hooks(name, p)
    _keep_realign(name, p)
    # 설정 변경 기록과 남겨 둔 제안은 화면이 직접 고치지 않는다. 디스크 것에 이번 저장이 고친 인물 설정만 작가 기록으로 더한다
    p.setting_log, p.setting_held = disk.setting_log, disk.setting_held
    p.agent_sessions = disk.agent_sessions  # 대화 세션은 대화 라우트와 에이전트 작업만 고친다 (화면의 옛 사본이 덮지 않게)
    charlog.record_author(disk, p)
    archetypes.prune(p)
    kept: list[dict] = []
    out = _save(name, p, merged={m for m in merged.split(",") if m}, kept=kept)
    if kept:  # 화면이 '저장했습니다' 대신 무엇을 저장하지 않았는지 알린다
        response.headers["X-Canon-Kept"] = quote(json.dumps(kept, ensure_ascii=False))
    return out


def _keep_hooks(name: str, p: Project) -> None:
    """흡입력 판정도 백그라운드 작업이 디스크에 쓴다. 화면이 그 전에 읽은 작품을 저장해도 새 판정을 덮지 않게 한다."""
    disk = {e.plot.number: e.hook for e in store.load(name).episodes if e.hook}
    for e in p.episodes:
        d = disk.get(e.plot.number)
        if d and (e.hook is None or e.hook.checked_at < d.checked_at):
            e.hook = d


def _keep_realign(name: str, p: Project) -> None:
    """뒤 화의 '다시 맞추기' 표시는 플롯 작업이 디스크에 쓰고 지우기는 clear_realign 으로만 한다. 화면 저장이 덮지 않는다."""
    disk = {e.plot.number: e.realign for e in store.load(name).episodes}
    for e in p.episodes:
        e.realign = disk.get(e.plot.number, "")


def _keep_impacts(name: str, p: Project) -> None:
    """영향 분석은 백그라운드 작업이 디스크에 쓴다. 화면이 그 전에 읽은 작품을 저장해도 새 분석을 덮지 않게 한다."""
    disk = {el.id: el.impact for el in store.load(name).elements if el.impact}
    for el in p.elements:
        d = disk.get(el.id)
        if d and (el.impact is None or el.impact.at < d.at or (el.impact.at == d.at and d.outcome and not el.impact.outcome)):
            el.impact = d


# ---------- 1. 설정 도우미 ----------

@app.get("/api/relation_views")
def relation_views() -> list[str]:
    """관계를 말로 고르는 보는 방식 (dynamics.VIEWS 의 말, 순서 그대로). 설정 화면이 시작 관계를 고를 때 쓴다."""
    return list(dynamics.VIEWS)


@app.post("/api/projects/{name}/suggest")
def suggest(name: str) -> SetupSuggestion:
    return pipeline.suggest_setup(get_llm("plan"), _load(name))


@app.post("/api/projects/{name}/suggest/apply")
def apply_suggestion(name: str, s: SetupSuggestion) -> Project:
    p = _load(name)
    pipeline.apply_setup(p, s)
    return _save(name, p)


class FieldIdeasIn(BaseModel):
    field: str  # 화면 칸 경로 (meta.title, meta.logline_parts.who, world.setting, characters.0.personality 등). prompts.idea_key 가 FIELD_IDEAS 키로
    n: int = 3
    project: Project | None = None  # 저장 전 화면의 값 (다른 칸을 고친 직후에도 맞게)


@app.post("/api/projects/{name}/field-ideas")
def field_ideas(name: str, body: FieldIdeasIn) -> FieldIdeas:
    """설정 칸 하나의 AI 후보 (✦). 저장하지 않는다. 작가가 고른 후보만 화면이 칸에 넣는다."""
    p = body.project or _load(name)
    return pipeline.suggest_field(get_llm(pipeline.field_stage(body.field)), p, body.field, max(1, min(body.n, 5)))


# ---------- 이름 · 지명 ----------

class NamingStyleOut(naming.NameStyle):
    """이름 스타일 하나와 고를 수 있는 지명 종류."""
    place_kinds: list[str]


@app.get("/api/naming/styles")
def naming_styles() -> list[NamingStyleOut]:
    return [{**st.model_dump(), "place_kinds": naming.place_kinds(st.id)} for st in naming.STYLES]


class NamesIn(BaseModel):
    character: str = ""  # 인물 id. 비우면 지명
    place_kind: str = ""
    n: int = 8
    ai: bool = False      # True 면 '이름·지명' 단계 모델이 후보에서 골라 이유를 붙인다
    project: Project | None = None  # 저장 전 화면의 값 (나이, 성별, 이름 스타일을 고친 직후에도 맞게)


class NamesOut(BaseModel):
    """이름 · 지명 후보. ai 면 options 에 AI 가 고른 이름과 이유가 있다."""
    style: str
    detected: str
    style_label: str
    candidates: list[naming.Candidate]
    options: list[NameOption] = []


@app.post("/api/projects/{name}/names", response_model_exclude_unset=True)  # options 는 ai 일 때만
def names(name: str, body: NamesIn) -> NamesOut:
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


class NameCheckIn(BaseModel):
    """이름 점검에 쓰는 칸만. 화면은 작품 전체 대신 이것만 보낸다 (장편 본문까지 보내지 않게)."""
    meta: Meta
    world: WorldSetting
    characters: list[Character] = []
    cast_candidates: list[Character] = []


class NameIssue(BaseModel):
    """이름 점검 한 줄 (naming.cast_issues)."""
    kind: str
    level: str  # warn | info
    text: str
    ids: list[str]


class NameCheckOut(BaseModel):
    warnings: list[str]
    issues: list[NameIssue]
    kinds: dict[str, str]
    style: str
    detected: str


@app.post("/api/projects/{name}/names/check")
def names_check(name: str, body: NameCheckIn | None = None) -> NameCheckOut:
    p = _load(name)
    if body is not None:  # 저장 전 화면 값으로 점검한다
        p.meta, p.world, p.characters, p.cast_candidates = body.meta, body.world, body.characters, body.cast_candidates
    issues = naming.cast_issues(p)
    return {"warnings": [i["text"] for i in issues], "issues": issues, "kinds": naming.ISSUE_KINDS,
            "style": naming.resolve_style(p), "detected": naming.detect_style(p)}


# ---------- 원형 도감 ----------

class DexCatalog(BaseModel):
    groups: list[str]
    archetypes: list[archetypes.Archetype]
    wounds: list[archetypes.Wound]
    speech: list[archetypes.SpeechKit]
    fill_labels: dict[str, str]


@app.get("/api/archetypes")
def dex_catalog() -> DexCatalog:
    return DexCatalog(groups=archetypes.GROUPS, archetypes=archetypes.CATALOG, wounds=archetypes.WOUNDS,
                      speech=archetypes.SPEECH, fill_labels=archetypes.FILL_LABELS)


class DexFillIn(BaseModel):
    character: Character
    archetype: str = ""
    wound: str = ""
    speech: str = ""
    twist: str = ""


class DexFillOut(BaseModel):
    character: Character
    filled: list[str]


@app.post("/api/archetypes/fill")
def dex_fill(body: DexFillIn) -> DexFillOut:
    """인물 하나의 빈 칸에 도감 예시를 넣어 돌려준다. 저장하지 않는다 (설정 화면이 받아 저장한다)."""
    p = Project(characters=[body.character])
    try:
        filled = archetypes.apply(p, body.character.id, body.archetype, body.wound, body.speech, body.twist)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    return DexFillOut(character=p.characters[0], filled=filled)


class DexRollIn(BaseModel):
    n: int = 3
    archetype: str = ""  # 비우지 않으면 이 원형은 두고 상처 · 말투 · 비틀기 · 이름만 굴린다
    seed: int | None = None
    meta: Meta | None = None  # 저장 전 화면 값 (장르, 이름 스타일)
    world: WorldSetting | None = None
    characters: list[Character] = []


@app.post("/api/projects/{name}/archetypes/roll")
def dex_roll(name: str, body: DexRollIn) -> list[archetypes.Roll]:
    p = _load(name)
    if body.meta is not None:
        p.meta = body.meta
    if body.world is not None:
        p.world = body.world
    if body.characters:
        p.characters = body.characters
    if body.archetype and body.archetype not in archetypes.BY_ID:
        raise HTTPException(404, f"도감에 없는 원형이에요: {body.archetype}")
    rng = random.Random(body.seed) if body.seed is not None else None
    return archetypes.roll(p.meta.genres, max(1, min(body.n, 6)), rng, body.archetype, p)


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


class StyleFieldDiff(BaseModel):
    """라이브러리와 다른 칸 하나 (library.diff). 글 칸은 before/after, 목록 칸은 added/removed."""
    key: str
    label: str
    before: str = ""
    after: str = ""
    added: list[str] = []
    removed: list[str] = []


class StyleLink(BaseModel):
    """작품 문체와 라이브러리 항목의 관계 (library.link_state). state: none | missing | same | changed"""
    state: str
    id: str = ""
    name: str = ""
    updated_at: str = ""
    version: int = 0
    applied: int = 0
    mine: list[StyleFieldDiff] = []
    theirs: list[StyleFieldDiff] = []
    base_known: bool = False


@app.get("/api/projects/{name}/style/link", response_model_exclude_unset=True)  # state 가 none · missing 이면 그 칸만
def style_link(name: str) -> StyleLink:
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


class StyleSummary(BaseModel):
    """문체 라이브러리 목록의 항목 하나 (library.summary)."""
    id: str
    name: str
    source: str
    notes: str
    narration_pov: str
    tense: str
    passages: int
    rules: int
    banned: int
    markers: int
    devices: int
    sample_chars: int
    created_at: str
    updated_at: str
    version: int
    used_by: list[str]


class StyleKept(BaseModel):
    entry: StyleSummary
    project: Project


@app.post("/api/projects/{name}/style/library")
def keep_style(name: str, body: StyleKeep) -> StyleKept:
    """작품의 지금 문체를 라이브러리에 저장한다 (작품 화면에서 저장한 뒤 부른다)."""
    p = _load(name)
    if body.update:
        e = library.push_project(p, body.note)
        _save(name, p)
    else:
        if library.blank(p.style) and not body.sample.strip():  # 원문만 있으면 라이브러리에서 나중에 분석할 수 있다
            raise HTTPException(400, "문체가 비어 있어요. 원문을 넣거나 문체 분석 · 스타일 프로필을 채운 뒤 저장할 수 있어요")
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


# ---------- 2-2. 이 문체로 쓴 예시 ----------
# 문체 대화(chat 'style')는 3-1 의 대화 엔드포인트를 함께 쓴다.

class ExampleIn(BaseModel):
    scene: str = ""  # 바라는 장면 (비우면 AI 가 고른다)
    episode: int = 0  # 이 화 한 대목을 고쳐 쓴다


@app.post("/api/projects/{name}/style/example")
def write_style_example(name: str, body: ExampleIn) -> Project:
    """지금 문체로 예시 글을 써서 문체 화면의 예시 칸에 둔다. 본문과 문체는 바꾸지 않는다."""
    ex = pipeline.style_example(get_llm("write"), _load(name), body.scene, body.episode)
    return _edit(name, lambda p: setattr(p, "style_example", ex))


@app.delete("/api/projects/{name}/style/example")
def clear_style_example(name: str) -> Project:
    return _edit(name, lambda p: setattr(p, "style_example", None))


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
        raise HTTPException(404, f"문체 라이브러리에 없는 항목이에요: {sid}")
    return sid


@app.get("/api/styles")
def list_styles() -> list[StyleSummary]:
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
    backup = store.load_backup(name, pipeline.BACKUP_TAG) if p.conversion else None
    blockers = pipeline.undo_blockers(p, backup) if p.conversion else []
    # 화면이 막힌 화로 가는 링크를 달 수 있게 이유별 화 번호도 준다
    detail = pipeline.undo_blocker_eps(p, backup) if p.conversion and backup else {}
    span = dict(zip(("min", "default", "max"), pipeline.rebuild_span(p))) if not p.serial and p.episodes else None
    return {"min": lo, "max": hi, "end": pipeline.short_end(p), "conversion": p.conversion, "undo_blockers": blockers,
            "undo_eps": detail, "rebuild": span}


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


@app.post("/api/projects/{name}/recap/{kind}/{number}")
def apply_recap(name: str, kind: str, number: int, body: Recap) -> Project:
    """작가가 고친 요약을 저장한다. 본문 모양은 요약 작업(recap_arc, recap_part)의 결과와 같다."""
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
    if n in jobs.running_owned(name):
        raise ValueError(f"{n}화 플롯을 만드는 작업이 도는 중이에요. 끝난 뒤에 확정하세요")
    p = _load(name)
    pipeline.confirm_plot(p, n)  # 그 화에 나오는 새 인물 후보도 함께 등록된다
    return _save(name, p)


@app.post("/api/projects/{name}/episodes/{n}/unconfirm")
def unconfirm_plot(name: str, n: int) -> Project:
    p = _load(name)
    ep = p.episode(n)
    if ep.status != "confirmed":
        raise ValueError(f"{n}화는 본문이 이미 있어 초안으로 되돌릴 수 없어요")
    ep.status = "draft"
    return _save(name, p)


@app.post("/api/projects/{name}/episodes/{n}/realign/clear")
def clear_realign(name: str, n: int) -> Project:
    """앞 화를 다시 짜며 남긴 '다시 맞추기' 표시를 작가가 확인하고 지운다."""
    _load(name).episode(n)  # 없는 작품 · 화면 알린다
    return _edit(name, lambda p: setattr(p.episode(n), "realign", ""))


# 화 끼워 넣기 · 빼기: 아직 안 쓴 화의 번호를 옮긴다. 작업이 맡은 화 번호가 어긋나지 않게 도는 작업이 없을 때만 한다.

class InsertIn(BaseModel):
    at: int  # 이 화 자리에 넣는다 (지금 이 화부터 뒤로 밀린다)
    title: str = ""
    summary: str = ""
    storyline: str = ""


def _renumber_ready(name: str) -> None:
    autorun.check_renumber(name)
    busy = [j.label for j in jobs.listing(name) if j.status == "running"]
    if busy:
        raise ValueError(f"AI 작업({', '.join(busy)})이 끝난 뒤에 하세요. 화 번호가 바뀌면 작업 결과가 엉뚱한 화에 들어가요")


class Renumbered(BaseModel):
    """화를 넣거나 뺀 뒤의 작품과 무엇을 옮겼는지."""
    project: Project
    notes: list[str]


@app.post("/api/projects/{name}/episodes/insert")
def insert_episode(name: str, body: InsertIn) -> Renumbered:
    """새 화를 넣고 뒤 화를 한 칸씩 민다. 무엇을 옮겼는지(notes)를 함께 돌려준다."""
    _renumber_ready(name)
    at = body.at
    with jobs.project_lock(name):
        p = _load(name)
        notes = pipeline.insert_episode(p, at, body.title, body.summary, body.storyline)
        store.save(name, p)
    autorun.renumber(name, lambda x: x + 1 if x >= at else x)
    return {"project": p, "notes": notes}


@app.delete("/api/projects/{name}/episodes/{n}")
def remove_episode(name: str, n: int) -> Renumbered:
    """아직 안 쓴 화를 빼고 뒤 화를 한 칸씩 당긴다."""
    _renumber_ready(name)
    with jobs.project_lock(name):
        p = _load(name)
        notes = pipeline.remove_episode(p, n)
        store.save(name, p)
    autorun.renumber(name, lambda x: x - 1 if x >= n else x)
    return {"project": p, "notes": notes}


class DeleteIn(BaseModel):
    keep_plot: bool = False  # 화를 빼지 않고 확정된 플롯으로 남긴다


@app.post("/api/projects/{name}/episodes/{n}/delete")
def delete_episode(name: str, n: int, body: DeleteIn) -> dict:
    """본문이 있거나 반영한 마지막 화를 지운다: 반영 취소 → 본문 비우기 → 화 빼기. 지우기 전 작품은 before-delete-<화>.json 으로 남긴다."""
    _renumber_ready(name)
    _text_guard(name, n)
    with jobs.project_lock(name):
        p = _load(name)
        before = p.model_copy(deep=True)
        notes = pipeline.delete_last(p, n, body.keep_plot)
        path = store.save_backup(name, f"before-delete-{n}", before)
        store.save(name, p)
    if before.episode(n).status == "finalized":
        autorun.after_revert(name, n)
    if not body.keep_plot:
        autorun.renumber(name, lambda x: x - 1 if x >= n else x)
    return {"project": p, "notes": [*notes, f"지우기 전 작품은 {path.name} 으로 남겨 뒀어요."]}


# ---------- 3-1. 대화로 다듬기 ----------
# 대화 기록은 project.json 의 chats 에 화면(topic)별로 남는다. 플롯 화면은 'plot', 집필 화면의 본문 부분 수정은
# 화마다 'text:<화>', 문체 화면은 'style', 설정 도우미는 'setup' 이다 (4-1 · 2-2 · canon/setupchat.py 참고).

TEXT_TOPIC = re.compile(r"^text:(\d+)$")


def _chat(p: Project, topic: str):
    m = TEXT_TOPIC.match(topic)
    if topic not in ("plot", "style", setupchat.TOPIC) and not (m and any(e.plot.number == int(m.group(1)) for e in p.episodes)):
        raise HTTPException(404, f"대화 주제가 없어요: {topic}")
    return p.chat(topic)


class ChatIn(BaseModel):
    message: str = ""
    selection: Selection | None = None  # 본문 부분 수정: 고른 부분
    preset: str = ""  # 본문 부분 수정: 빠른 요청 id (prompts.PASSAGE_PRESETS)
    # 플롯 대화: 화면이 알려 주는 대상과 보던 곳 (schema.ChatScope)
    target: str = ""  # '' 기본, 'arc:3' 고른 아크, 'next' 다음 아크 기획
    act: str = ""  # 연 구간 이름
    episode: int = 0  # 연 화. 문체 대화면 참고할 화
    mode: Literal["", "options"] = ""  # options: 방향 여러 안 (플롯 · 설정 대화)
    draft: ArcProposal | None = None  # target 'next': 화면의 다음 아크 초안


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
    if topic == "style":
        rev = pipeline.revise_style(get_llm("plan"), p, body.message, body.episode)
        return _edit(name, lambda q: pipeline.record_style_chat(q, body.message, body.episode, rev))
    if topic == setupchat.TOPIC:
        rev = pipeline.revise_setup(get_llm("plan"), p, body.message, body.mode)
        return _edit(name, lambda q: setupchat.record(q, body.message, body.mode, rev))
    target, _ = pipeline.chat_target(p, body.target)  # 기다리는 동안 아크가 붙어도 처음 대상을 기록한다
    scope = ChatScope(target=target, act=body.act, episode=body.episode, mode=body.mode, draft=body.draft)
    rev = pipeline.revise_plot(get_llm("plan"), p, body.message, scope)
    # AI 를 기다리는 동안 백그라운드 작업이 저장했을 수 있으니 최신 내용에 대화만 덧붙인다
    return _edit(name, lambda q: pipeline.record_chat(q, topic, body.message, rev, scope))


class ChatApply(BaseModel):
    acts: bool = False
    episodes: list[int] = []
    arc: bool = False  # 장편: 아크 칸
    parts: bool = False  # 장편: 부 구성
    draft: list[str] = []  # 다음 아크 변경안: 화면이 초안에 넣은 부분 ('arc'). 작품은 바꾸지 않고 기록만 한다
    candidate: int | None = None  # 본문 부분 수정: 넣을 후보 번호 (0부터)
    text: str | None = None  # 본문 부분 수정: 작가가 손본 후보
    fields: list[str] = []  # 문체 대화: 적용할 칸 이름 (StyleProfile 칸). 설정 대화: 적용할 부분 id (setupchat.part_ids)
    push: bool = False  # 문체 대화: 연결된 라이브러리 항목에도 새 버전으로 올린다


def _style_push(p: Project, note: str) -> None:
    if p.style_id and library.exists(p.style_id):
        library.push_project(p, note)


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
    if topic == "style":
        def fn(q: Project) -> None:
            done = pipeline.apply_style_chat(q, i, body.fields)
            if body.push:
                asked = q.chat("style").messages[i - 1].text if i else ""
                _style_push(q, f"대화로 다듬음: {asked[:60]}" if asked else f"대화로 다듬음 ({len(done)}칸)")
        return _edit(name, fn)
    if topic == setupchat.TOPIC:
        if any(x.startswith("r:") for x in body.fields):  # 자동 집필이 반영하는 관계와 겹치지 않게
            _not_auto(name)
        return _edit(name, lambda q: setupchat.apply(q, i, body.fields))
    p = _load(name)
    _plot_revision(p, topic, i)
    pipeline.apply_plot_chat(p, i, body.acts, body.episodes, arc=body.arc, parts=body.parts, draft=body.draft, topic=topic)
    return _save(name, p)


@app.post("/api/projects/{name}/chat/{topic}/{i}/dismiss")
def chat_dismiss(name: str, topic: str, i: int) -> Project:
    _chat(_load(name), topic)

    def fn(p: Project) -> None:
        msgs = p.chat(topic).messages
        if not 0 <= i < len(msgs) or (msgs[i].revision is None and msgs[i].passage is None and msgs[i].style is None
                                      and msgs[i].setup is None):
            raise HTTPException(404, "변경안이 있는 메시지가 아니에요")
        if not msgs[i].outcome:
            msgs[i].outcome = "dismissed"
    return _edit(name, fn)


@app.post("/api/projects/{name}/chat/{topic}/{i}/reopen")
def chat_reopen(name: str, topic: str, i: int) -> Project:
    """버린 변경안을 다시 검토할 수 있게 한다. 반영한 것은 다시 열지 않는다."""
    _chat(_load(name), topic)

    def fn(p: Project) -> None:
        msgs = p.chat(topic).messages
        if not 0 <= i < len(msgs) or msgs[i].outcome != "dismissed":
            raise ValueError("버린 변경안이 아니에요")
        msgs[i].outcome = ""
    return _edit(name, fn)


class StyleUndo(BaseModel):
    push: bool = False  # 연결된 라이브러리 항목에도 새 버전으로 올린다


@app.post("/api/projects/{name}/chat/style/{i}/undo")
def style_chat_undo(name: str, i: int, body: StyleUndo) -> dict:
    """적용한 문체 변경안을 취소한다. 그 뒤에 다시 고친 칸은 그대로 둔다. 변경안은 다시 고를 수 있게 열린다."""
    out: dict = {}

    def fn(p: Project) -> None:
        out["restored"], out["kept"] = pipeline.undo_style_chat(p, i)
        if body.push and out["restored"]:
            _style_push(p, "대화로 다듬은 것 취소")
    p = _edit(name, fn)
    return {"project": p, **out}


@app.post("/api/projects/{name}/chat/setup/{i}/undo")
def setup_chat_undo(name: str, i: int) -> dict:
    """적용한 설정 변경안을 취소한다. 그 뒤에 다시 고친 부분과 이미 쓰이는 새 인물은 그대로 둔다. 변경안은 다시 고를 수 있게 열린다."""
    out: dict = {}

    def fn(p: Project) -> None:
        msg = setupchat.message(p, i)
        if any(x.startswith("r:") for x in msg.applied):
            _not_auto(name)
        out["restored"], out["kept"] = setupchat.undo(p, i)
    p = _edit(name, fn)
    return {"project": p, **out}


def _plot_revision(p: Project, topic: str, i: int) -> None:
    msgs = _chat(p, topic).messages
    if not 0 <= i < len(msgs) or msgs[i].revision is None:
        raise HTTPException(404, "변경안이 있는 메시지가 아니에요")


@app.post("/api/projects/{name}/chat/plot/{i}/undo")
def plot_chat_undo(name: str, i: int) -> dict:
    """적용한 플롯 변경안을 취소한다. 그 뒤에 다시 고쳤거나 확정한 화, 본문을 쓴 화와 그 때문에 줄일 수 없는 구조는 그대로 두고
    까닭(reasons, kept 와 같은 순서)을 알려 준다. 변경안은 다시 고를 수 있게 열린다."""
    _plot_revision(_load(name), "plot", i)
    out: dict = {}

    def fn(p: Project) -> None:
        out["restored"], out["kept"], out["reasons"] = pipeline.undo_plot_chat(p, i)
    p = _edit(name, fn)
    return {"project": p, **out}


@app.delete("/api/projects/{name}/chat/{topic}")
def chat_clear(name: str, topic: str) -> Project:
    _chat(_load(name), topic)
    return _edit(name, lambda p: setattr(p.chat(topic), "messages", []))


# ---------- 3-1b. 대화 에이전트 (canon/agent.py) ----------
# 세션 목록 · 만들기 · 고치기, 턴 보내기(백그라운드 작업 'agent'), 승인 카드 답, 이어 하기, 되돌리기.
# 화면은 작업 진행(GET /api/jobs)이 바뀔 때 세션 목록만 다시 받는다.

class SessionsOut(BaseModel):
    sessions: list[AgentSession]
    legacy: int = 0  # 옛 단발 대화 메시지 수 (화면의 '이전 대화')
    model: str = ""  # 상태 줄에 보일 모델 이름 (plan 단계)
    max_steps: int = agent.MAX_STEPS


def _model_label() -> str:
    try:
        m = getattr(get_llm("plan"), "model", "")
        m = m() if callable(m) else m
    except Exception:
        m = ""
    return m if isinstance(m, str) and m else settings.stage_provider("plan")[0]


@app.get("/api/projects/{name}/sessions")
def agent_sessions(name: str, topic: str = "plot") -> SessionsOut:
    p = _load(name)
    if agent.reconcile(p):  # 멈추거나 실패한 작업의 턴을 끝낸다
        p = _edit(name, lambda q: agent.reconcile(q))
    return SessionsOut(sessions=agent.sessions(p, topic), legacy=agent.legacy_count(p, topic), model=_model_label())


class SessionIn(BaseModel):
    topic: str = "plot"
    target: str = ""
    title: str = ""


@app.post("/api/projects/{name}/sessions")
def agent_session_new(name: str, body: SessionIn) -> AgentSession:
    _load(name)
    out: list[AgentSession] = []
    _edit(name, lambda p: out.append(agent.new_session(p, body.topic, body.target, body.title)))
    return out[0]


class SessionPatch(BaseModel):
    title: str | None = None
    mode: str | None = None
    target: str | None = None
    archived: bool | None = None


@app.patch("/api/projects/{name}/sessions/{sid}")
def agent_session_update(name: str, sid: str, body: SessionPatch) -> AgentSession:
    _load(name)
    out: list[AgentSession] = []
    _edit(name, lambda p: out.append(agent.update_session(p, sid, **body.model_dump())))
    return out[0]


class TurnIn(BaseModel):
    message: str
    mode: Literal["", "options"] = ""  # options: 방향 여러 안으로 물어 달라 (/여러안)
    act: str = ""  # 화면에서 연 구간
    episode: int = 0  # 화면에서 연 화
    draft: ArcProposal | None = None  # 다음 아크 대상: 화면의 초안


def _run_agent(name: str, sid: str, t: int) -> dict:
    """턴을 백그라운드 작업으로 돌린다. 같은 작품의 대화 작업은 한 번에 하나다."""
    llm = get_llm("plan")  # 키가 없으면 여기서 바로 오류를 보여 준다
    s = agent.session(_load(name), sid)
    try:
        with usage.scope(task="agent"):
            job = jobs.start(name, "agent", None, f"대화 · {s.title or '새 세션'}",
                             lambda j: agent.run_turn(llm, name, sid, t, j), total=agent.MAX_STEPS)
    except jobs.Busy:
        raise ValueError("이 작품에서 이미 대화가 돌아가고 있어요. 끝난 뒤 보내거나 멈추세요") from None
    _edit(name, lambda p: setattr(agent.turn_of(p, sid, t)[1], "job", job.id))
    return job.public()


@app.post("/api/projects/{name}/sessions/{sid}/turns")
def agent_turn(name: str, sid: str, body: TurnIn) -> dict:
    """작가의 말을 새 턴으로 열고 에이전트를 돌린다. 작업 정보를 돌려준다 (진행은 GET /api/jobs)."""
    _load(name)
    if any(j.kind == "agent" and j.status == "running" for j in jobs.listing(name)):
        raise ValueError("이 작품에서 이미 대화가 돌아가고 있어요. 끝난 뒤 보내거나 멈추세요")
    out: list[int] = []
    _edit(name, lambda p: out.append(agent.add_turn(p, sid, body.message, mode=body.mode, act=body.act, episode=body.episode, draft=body.draft)))
    return _run_agent(name, sid, out[0])


class ApprovalIn(BaseModel):
    approve: bool
    picked: list[str] = []  # 쓸 부분 (비우면 카드의 모든 부분)
    remember: bool = False  # 이 세션에서 이 종류는 묻지 않기


@app.post("/api/projects/{name}/sessions/{sid}/turns/{t}/approval")
def agent_approval(name: str, sid: str, t: int, body: ApprovalIn) -> dict:
    """승인 카드에 답하고 같은 턴을 이어 돌린다. 쓴 작품을 함께 돌려준다."""
    _load(name)
    p = _edit(name, lambda q: agent.decide(q, sid, t, body.approve, body.picked, body.remember))
    return {"project": p, "job": _run_agent(name, sid, t)}


@app.post("/api/projects/{name}/sessions/{sid}/turns/{t}/continue")
def agent_continue(name: str, sid: str, t: int) -> dict:
    """상한에 닿았거나 멈춘 턴을 이어 돌린다."""
    _load(name)
    _edit(name, lambda q: agent.resume(q, sid, t))
    return _run_agent(name, sid, t)


class AgentUndoIn(BaseModel):
    write: int | None = None  # 쓴 기록 번호 (비우면 턴 전체)
    key: str | None = None  # 그 기록의 한 부분 ('parts' · 'arc' · 'acts' · 'draft' · 화 번호)


@app.post("/api/projects/{name}/sessions/{sid}/turns/{t}/undo")
def agent_undo(name: str, sid: str, t: int, body: AgentUndoIn) -> dict:
    """바로 쓴 것을 되돌린다. 그 뒤에 다시 고치거나 확정한 것은 남기고 까닭을 돌려준다."""
    _load(name)
    out: list = []
    p = _edit(name, lambda q: out.append(agent.undo(q, sid, t, body.write, body.key)))
    restored, kept, reasons = out[0]
    return {"project": p, "restored": restored, "kept": kept, "reasons": reasons}


# ---------- 3-2. 인과율 ----------
# 요소 자체는 작가 입력이라 작품 저장(PUT)으로 저장한다. 영향 분석은 백그라운드 작업(kind 'impact')이 요소에 붙인다.

class ElementLink(elements.Link):
    """관련 화 지도의 한 화 (elements.Link). snippet 도 응답에는 늘 있다."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


@app.get("/api/projects/{name}/elements/links")
def element_links(name: str) -> dict[str, list[ElementLink]]:
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


@app.post("/api/projects/{name}/elements/{eid}/impact/reopen")
def impact_reopen(name: str, eid: str) -> Project:
    p = _load(name)
    pipeline.reopen_impact(p, eid)
    return _save(name, p)


# ---------- 백그라운드 작업 ----------

class JobIn(BaseModel):
    kind: str  # suggest | arc | plots | write | board | state | impact | series | nextarc | recap_arc | recap_part | storyline | convert | rebuild | rework | hook | openings | opening_drafts
    ep: int | None = None  # 화 번호. plots 는 장편에서 아크 번호(없으면 초안이 있는 모든 아크), recap_* 는 아크·부 번호
    element: str = ""  # impact 일 때 요소 id
    note: str = ""  # arc, series, plots, nextarc, storyline, convert, rebuild: 작가가 바라는 것
    line_kind: str = ""  # storyline: 원하는 줄기 종류 (비우면 AI 가 고름)
    length: int = 0  # nextarc: 아크 화수 (0 이면 AI 가 정함). convert, rebuild: 장편 총 화수
    ending: str = ""  # convert: keep | reopen, rebuild: arc | part | series (단편 결말이 갈 곳). 비우면 AI 가 고름
    span: int = 0  # rebuild: 다시 짤 앞부분 화수 (0 이면 기본값)
    approaches: list[str] = []  # openings, opening_drafts: 여는 방식 id (비우면 기본 세 가지)
    draft: int = 0  # hook: 0 이면 그 화 본문, k 면 비교본 k 번을 판정
    rewrite: RewriteRequest | None = None  # write: 본문이 있는 화를 다시 생성. 새 판은 본문을 덮지 않고 고르기를 기다린다
    fit_next: bool = True  # plot_one: 바로 뒤 화를 바꾸지 않는 화로 보고 맞춘다. 끄면 작가가 적은 것대로 마무리하고 뒤 화에 어긋난 점을 표시한다
    episodes: list[int] = []  # stattrial: 시험할 화
    repeats: int = 1  # stattrial: 조건마다 같은 화를 쓸 횟수
    conditions: list[str] = []  # stattrial: none | json | lines (비우면 셋 다)
    board: Literal["", "make", "none"] = ""  # write: make 면 스토리보드를 새로 만든 뒤 쓴다(바로 쓰기), none 이면 스토리보드 없이 쓴다


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
            raise ValueError(f"아크 {arc}이(가) 없어요")
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
    if kind in ("write", "state", "plots", "plot_one", "check", "board"):
        _not_auto(name)
    stage = {"write": "write", "state": "state", "recap_arc": "state", "recap_part": "state", "rework": "revise",
             "hook": "check", "check": "check", "opening_drafts": "write", "stattrial": "write"}.get(kind, "plan")  # 나머지는 plan
    llm = get_llm(stage)  # 키가 없으면 여기서 바로 오류를 보여 준다

    if kind == "suggest":
        label, total, owned = "설정 제안", 1, set()

        def fn(job: jobs.Job):
            return pipeline.suggest_setup(llm, store.load(name)).model_dump()
    elif kind == "arc":
        label, total, owned = "기승전결 구조 제안", 1, set()
        note = body.note

        def fn(job: jobs.Job):
            return pipeline.plan_arc(llm, store.load(name), note).model_dump()
    elif kind == "series":
        label, total, owned = "부 구성 제안", 1, set()
        note = body.note

        def fn(job: jobs.Job):
            return pipeline.plan_series(llm, store.load(name), note).model_dump()
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
            raise ValueError("화 번호(ep)가 필요해요")
        x = p.archive.entry(n) if p.archive else None
        if x is None or x.use != "revise":
            raise ValueError(f"{n}화는 재구성에서 다듬기로 고른 화가 아니에요")
        label, total, owned = f"{n}화 다듬기", 1, set()

        def fn(job: jobs.Job):
            return pipeline.propose_rework(llm, store.load(name), n).model_dump()
    elif kind == "check":
        # 한 화 검수: 앞선 본문 전체와 설정에 어긋난 곳을 찾아 그 화에 붙인다 (집필 화면이 보여 주고 고칠 문장을 고르게 한다)
        if n is None or not p.episode(n).text:
            raise ValueError("본문이 있는 화만 검수해요")
        label, total, owned = f"{n}화 검수", 1, set()

        def fn(job: jobs.Job):
            q0 = store.load(name)
            rep = pipeline.check_episode(llm, q0, n)
            r = _edit(name, lambda q: pipeline.apply_check(q, rep, "api", pipeline.widen_on(q0))).episode(n).rounds[-1]
            return {"issues": len(rep.issues), "round": r.no, "added": r.added}
    elif kind == "storyline":
        label, total, owned = "이야기 줄기 제안", 1, set()
        note, line_kind = body.note, body.line_kind

        def fn(job: jobs.Job):
            return pipeline.suggest_storyline(llm, store.load(name), note, line_kind).model_dump()
    elif kind in ("recap_arc", "recap_part"):
        unit = kind.removeprefix("recap_")
        if n is None:
            raise ValueError("아크나 부 번호(ep)가 필요해요")
        label, total, owned = (f"아크 {n} 요약" if unit == "arc" else f"{n}부 요약"), 1, set()  # 화면과 같은 이름 ('1부')

        def fn(job: jobs.Job):
            return pipeline.recap(llm, store.load(name), unit, n).model_dump()
    elif kind == "plots":
        if not p.beats():
            raise ValueError("다음 아크를 먼저 기획하세요" if p.serial else "기승전결 구조(arc)를 먼저 만들고 저장하세요")
        ranges = _plot_ranges(p, n if p.serial else None)
        if not ranges:
            raise ValueError("모든 화가 확정되어 새로 만들 초안이 없어요")
        draft = {e.plot.number for e in p.episodes if e.status == "draft"}
        have = {e.plot.number for e in p.episodes}
        owned = {k for _, a, b in ranges for k in range(a, b + 1) if k in draft or k not in have}
        label, total = "화별 플롯 초안", len(ranges)
        note = body.note

        def fn(job: jobs.Job):
            # 구간마다 따로 부른다: 한 번에 20화를 받는 것보다 빠르게 첫 결과가 오고, 실패해도 앞 구간은 남는다
            for act, a, b in ranges:
                arc = store.load(name).arc_for(a)
                job.note = f"{f'아크 {arc.number} ' if arc else ''}{act} 구간 ({a}~{b}화) 만드는 중"
                batch = pipeline.draft_plots(llm, store.load(name), a, b, note)
                _edit(name, lambda q: pipeline.apply_plots(q, batch))
                job.done += 1
                job.release({k for k in owned if a <= k <= b})  # 끝난 구간은 작업이 도는 중에도 확정하고 고칠 수 있다
            job.note = ""
            return None
    elif kind == "plot_one":
        if n is None:
            raise ValueError("화 번호(ep)가 필요해요")
        if p.episode(n).status != "draft":
            raise ValueError(f"{n}화는 확정된 화라 AI 초안으로 바꾸지 않아요. 초안으로 되돌린 뒤 하세요")
        label, total, owned = f"{n}화 플롯 초안", 1, {n}

        def fn(job: jobs.Job):
            batch = pipeline.draft_episode(llm, store.load(name), n, body.fit_next)
            out: dict = {}
            _edit(name, lambda q: out.update(realign=pipeline.apply_draft(q, batch)))
            if not out.get("realign"):
                return None
            return {"realign": out["realign"], "gap": batch.next_gap}  # type: ignore[attr-defined]
    elif kind in ("write", "state"):
        if n is None:
            raise ValueError("화 번호(ep)가 필요해요")
        e = p.episode(n)
        if kind == "write":
            if e.status == "draft":
                raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요")
            if body.rewrite is not None and e.text:  # 다시 생성: 새 판은 본문을 덮지 않고 고르기를 기다린다 (반영이 끝난 화도)
                req = pipeline.clean_rewrite(body.rewrite)
                label, total, owned = f"{n}화 새 판", 1, {n}

                def fn(job: jobs.Job):
                    text = pipeline.rewrite_episode(llm, store.load(name), n, req)
                    _edit(name, lambda q: pipeline.set_candidate(q, n, text, req))
                    return {"candidate": True}
            else:
                make = body.board == "make"
                plan = get_llm("plan") if make else None  # 스토리보드는 plan 단계 모델
                label, total, owned = f"{n}화 {'스토리보드와 ' if make else ''}본문", 2 if make else 1, {n}

                def fn(job: jobs.Job):
                    if make:
                        job.note = f"{n}화 스토리보드 만드는 중"
                        b = pipeline.make_storyboard(plan, store.load(name), n)
                        _edit(name, lambda q: pipeline.set_storyboard(q, n, b, by="ai"))
                        job.done, job.note = 1, f"{n}화 본문 쓰는 중"
                    text = pipeline.write_episode(llm, store.load(name), n, use_board=body.board != "none")
                    _edit(name, lambda q: pipeline.replace_text(q.episode(n), text))  # 지금 본문이 있으면 '이전 판'에 남는다
                    return None
        else:
            if not e.text:
                raise ValueError(f"{n}화 본문이 없어요")
            label, total, owned = f"{n}화 {'고친 본문 다시 맞추기' if e.status == 'finalized' else '상태 변경안'}", 1, set()

            def fn(job: jobs.Job):
                return pipeline.extract_state(llm, store.load(name), n).model_dump()
    elif kind == "board":
        if n is None:
            raise ValueError("화 번호(ep)가 필요해요")
        if p.episode(n).status == "draft":
            raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요")
        pipeline.require_previous(p, n)
        label, total, owned = f"{n}화 스토리보드", 1, {n}

        def fn(job: jobs.Job):
            b = pipeline.make_storyboard(llm, store.load(name), n)
            _edit(name, lambda q: pipeline.set_storyboard(q, n, b, by="ai"))
            return None
    elif kind in ("hook", "openings", "opening_drafts"):
        if n is None or not prompts.is_opening(n):
            raise ValueError(f"1~{prompts.OPENING_EPISODES}화 번호(ep)가 필요해요")
        ways, k = body.approaches, body.draft
        if kind == "hook":
            if k:
                research.compare_text(name, n, k)  # 비교본이 없으면 바로 알린다
            elif not p.episode(n).text:
                raise ValueError(f"{n}화 본문이 없어요")
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
            label, total, owned = f"{n}화 여는 방식 플롯 안", 1, set()

            def fn(job: jobs.Job):
                return pipeline.suggest_openings(llm, store.load(name), n, ways).model_dump()
        else:
            if p.episode(n).status == "draft":
                raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요")
            label, total, owned = f"{n}화 여는 방식 본문 안", 1, set()

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
    elif kind == "stattrial":
        eps, reps, conds = sorted(set(body.episodes)), body.repeats, body.conditions or list(stattrial.CONDITIONS)
        bad = [c for c in conds if c not in stattrial.CONDITIONS]
        if bad:
            raise ValueError(f"알 수 없는 조건이에요: {', '.join(bad)}")
        ok = {c["episode"] for c in stattrial.candidates(p)}
        if not eps or any(x not in ok for x in eps):
            raise ValueError("시험할 화를 고르세요. 상태 반영이 끝난 화만 시험할 수 있어요")
        total = len(eps) * reps * len(conds)
        if not 1 <= reps <= 5 or total > stattrial.MAX_WRITES:
            raise ValueError(f"반복은 1~5번, 본문은 한 번에 {stattrial.MAX_WRITES}개까지예요 (지금 {total}개)")
        label, owned = f"상태창 시험 ({len(eps)}화 · {reps}번 · 조건 {len(conds)}개)", set()

        def fn(job: jobs.Job):
            def step(done: int, _total: int, note: str) -> None:
                job.done, job.note = done, note
            res = stattrial.run(name, store.load(name), llm, eps, reps, conds, progress=step)
            return {"drafts": len(res["drafts"]), "id": res["id"]}
    else:
        raise ValueError(f"모르는 작업이에요: {kind}")

    try:
        with usage.scope(episode=n if kind in ("write", "board", "state", "check", "rework", "hook", "openings", "opening_drafts", "plot_one") else None, task=kind):
            job = jobs.start(name, kind, n, label, _keep_pending(name, kind, n, label, fn), total=total, owned=owned)
    except jobs.Busy as b:
        return {**b.job.public(), "already": True}
    return job.public()


# 결과가 반영 전 제안인 작업. 화면이 반영하거나 버릴 때까지 pending.json 에 둔다
# (본문 · 플롯 · 판정 같은 작업은 서버가 이미 작품에 썼다)
PENDING_KINDS = {"arc", "suggest", "series", "nextarc", "convert", "rebuild", "rework", "storyline", "recap_arc", "recap_part", "state", "openings"}


def _keep_pending(name: str, kind: str, n: int | None, label: str, fn):
    """작업 fn 을 감싸, 끝나면 제안 결과를, 실패하면 오류를 작품의 pending.json 에 남긴다. 같은 작업이 성공하면 지난 실패를 지운다."""
    key = f"{kind}:{n if n is not None else ''}"

    def run(job: jobs.Job):
        try:
            out = fn(job)
        except cancel.Cancelled:
            raise  # 멈춘 작업은 실패로 남기지 않는다
        except Exception as e:
            fail = {"key": key, "kind": kind, "ep": n, "label": label, "error": getattr(e, "message", None) or str(e) or type(e).__name__, "at": _now()}

            def put_fail(d: dict) -> None:
                d["failures"][key] = fail
            store.edit_pending(name, put_fail)
            raise
        rec = None
        if kind in PENDING_KINDS and out is not None:
            # 상태 변경안은 만든 본문을 함께 둔다. 그 뒤 본문을 고쳤으면 화면이 알린다
            base = store.load(name).episode(n).text if kind == "state" else None
            rec = {"key": key, "id": job.id, "kind": kind, "ep": n, "label": label, "result": out, "base": base, "at": _now()}

        def put(d: dict) -> None:
            d["failures"].pop(key, None)
            if rec:
                d["results"][key] = rec
        store.edit_pending(name, put)
        return out
    return run


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@app.get("/api/projects/{name}/pending")
def get_pending(name: str) -> dict:
    """검토를 기다리는 AI 결과와 실패한 작업. 이미 쓸 수 없게 된 상태 변경안(본문 작성 상태도, 반영 뒤 고친 화도 아닌 화)은 지운다."""
    p = _view(name)
    written = {e.plot.number for e in p.episodes if e.status == "written" or pipeline.edited_after_final(e)}
    stale = [k for k, r in store.load_pending(name)["results"].items() if r["kind"] == "state" and r["ep"] not in written]

    def prune(d: dict) -> None:
        for k in stale:
            d["results"].pop(k, None)
    return store.edit_pending(name, prune) if stale else store.load_pending(name)


@app.delete("/api/projects/{name}/pending/{key}")
def drop_pending(name: str, key: str, failure: bool = False) -> dict:
    """화면이 반영하거나 버린 결과(또는 닫은 실패)를 지운다."""
    _load(name)
    return store.edit_pending(name, lambda d: d["failures" if failure else "results"].pop(key, None))


@app.post("/api/jobs/{jid}/stop")
def stop_job(jid: str) -> dict:
    """작업을 멈춘다. 이미 보낸 AI 호출의 응답은 버린다. 자동 집필은 그 화면의 일시정지 · 중지를 쓴다."""
    j = jobs.get(jid)
    if j is None:
        raise HTTPException(404, "작업이 없어요 (서버가 다시 시작됐을 수 있어요)")
    if j.kind == "auto":
        raise ValueError("자동 집필은 자동 집필 화면의 일시정지나 중지를 쓰세요")
    return jobs.stop(jid).public()


@app.get("/api/jobs")
def list_jobs(project: str | None = None) -> list[dict]:
    return [j.public() for j in jobs.listing(project)]


@app.get("/api/jobs/{jid}")
def get_job(jid: str) -> dict:
    j = jobs.get(jid)
    if j is None:
        raise HTTPException(404, "작업이 없어요 (서버가 다시 시작됐을 수 있어요)")
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
    """직접 고친 본문이나 채팅 앱에서 받은 본문을 저장한다. 그 화를 쓰는 작업이나 자동 집필이 도는 중이면 막는다
    (작업이 끝나며 쓰는 본문과 서로 덮지 않게, 고친 본문에 옛 본문 기준 변경안이 반영되지 않게)."""
    _text_guard(name, n)
    p = _load(name)
    ep = p.episode(n)
    if ep.status == "draft":
        raise ValueError(f"{n}화 플롯을 먼저 확정하세요")
    text = body.text.strip()
    if ep.status == "finalized":  # 반영이 끝난 화도 고친다. 반영된 상태는 그대로 두고 반영 뒤 고침으로 표시한다
        if not text:
            raise ValueError(f"{n}화는 상태 반영이 끝나 본문을 비울 수 없어요")
        pipeline.record_typed(p, n, ep.text, text)
        pipeline.before_change(ep)
        ep.text = text
        return _save(name, p)
    if text and ep.status == "confirmed":  # 손으로 쓰거나 붙여 넣은 본문도 AI 쓰기와 같은 순서 규칙을 따른다
        pipeline.require_previous(p, n)
    pipeline.record_typed(p, n, ep.text, text)
    ep.text = text
    ep.status = "written" if ep.text else "confirmed"
    return _save(name, p)


class EventsDone(BaseModel):
    done: list[str]


@app.put("/api/projects/{name}/episodes/{n}/events-done")
def set_events_done(name: str, n: int, body: EventsDone) -> list[str]:
    """집필 화면 플롯 띠의 쓴 사건 체크 (Episode.events_done). 이 화 사건 글에 있는 것만 남긴다.
    플롯 초안 화와, AI 작업 · 자동 집필이 맡은 화는 막는다 (작업이 저장하는 작품과 서로 덮지 않게)."""
    _not_auto(name)
    if any(j.status == "running" and n in j.owned for j in jobs.listing(name)):
        raise ValueError("AI 작업이 끝난 뒤에 체크할 수 있어요")
    p = _load(name)
    ep = p.episode(n)
    if ep.status == "draft":
        raise ValueError(f"{n}화 플롯을 먼저 확정하세요")
    ep.events_done = [x for x in ep.plot.events if x in set(body.done)]
    _save(name, p)
    return ep.events_done


# ---------- 4-0. 화별 스토리보드 ----------
# 쓰기 직전의 장면 목록과 확정 값 (board.py). 만들기는 작업 board (start_job), 작가 수정 · 지우기는 여기서.
# 상태 승인 대상이 아니라 바로 저장한다. 그 화를 맡은 작업이나 자동 집필이 도는 동안은 막는다.

@app.get("/api/projects/{name}/episodes/{n}/storyboard")
def get_storyboard(name: str, n: int) -> dict:
    """Canon 이 센 값: 켜짐, 낡음, 시간 한 줄, 열린 기한, 상태창 단계(창 글 포함), 경고 (board.view)."""
    p = _load(name)
    p.episode(n)
    return board.view(p, n)


def _board_guard(name: str, n: int) -> None:
    _not_auto(name)
    if any(j.status == "running" and n in j.owned for j in jobs.listing(name)):
        raise ValueError("AI 작업이 끝난 뒤에 고칠 수 있어요")


@app.put("/api/projects/{name}/episodes/{n}/storyboard")
def put_storyboard(name: str, n: int, body: Storyboard) -> Project:
    """작가가 고친 스토리보드를 저장한다. AI 가 만든 것을 고치면 made_by 가 both 가 된다."""
    _board_guard(name, n)
    _load(name).episode(n)
    return _edit(name, lambda p: pipeline.set_storyboard(p, n, body))


@app.delete("/api/projects/{name}/episodes/{n}/storyboard")
def drop_storyboard(name: str, n: int) -> Project:
    _board_guard(name, n)
    _load(name).episode(n)
    return _edit(name, lambda p: pipeline.set_storyboard(p, n, None))


# ---------- 4-0. 고칠 곳 ----------
# 작가가 본문 문장에 다는 '나중에 고칠 곳' 표시 (tofix.py). 본문을 바꾸지 않아 자동 집필이 도는 동안에도 받는다.
# 작품 잠금 안에서 최신 project.json 을 읽어 고치므로 자동 집필의 저장과 서로 덮지 않는다.

class ToFixIn(BaseModel):
    quote: str
    note: str = ""
    start: int = 0


class ToFixPatch(BaseModel):
    note: str | None = None
    status: Literal["open", "done"] | None = None


@app.post("/api/projects/{name}/episodes/{n}/tofix")
def add_tofix(name: str, n: int, body: ToFixIn) -> Project:
    _load(name).episode(n)
    return _edit(name, lambda p: tofix.add(p.episode(n), body.quote, body.note, body.start, pipeline._now()))


@app.put("/api/projects/{name}/episodes/{n}/tofix/{mid}")
def update_tofix(name: str, n: int, mid: str, body: ToFixPatch) -> Project:
    _load(name).episode(n)
    return _edit(name, lambda p: tofix.update(p.episode(n), mid, pipeline._now(), body.note, body.status))


@app.delete("/api/projects/{name}/episodes/{n}/tofix/{mid}")
def delete_tofix(name: str, n: int, mid: str) -> Project:
    _load(name).episode(n)
    return _edit(name, lambda p: tofix.remove(p.episode(n), mid))


# ---------- 4-1. 본문 부분 수정 ----------
# 집필 화면에서 고른 부분을 직접 고치거나(아래), AI 후보로 바꾼다(대화 'text:<화>', 3-1). 모두 Episode.edits 에 남는다.

def _text_guard(name: str, n: int) -> None:
    _not_auto(name)
    if any(j.status == "running" and n in j.owned for j in jobs.listing(name)):
        raise ValueError(f"{n}화 본문을 쓰는 작업이 도는 중이에요. 끝난 뒤에 고치세요")


# ---------- 4-0. 다시 생성 ----------

class RewritePreset(BaseModel):
    """빠른 요청 하나 (prompts.REWRITE_PRESETS)."""
    id: str
    label: str


class RewriteMaterialInfo(BaseModel):
    """함께 넣을 수 있는 재료 하나. lines 는 프롬프트에 들어갈 줄 그대로, 비면 넣을 것이 없다."""
    id: str
    label: str
    lines: list[str]
    note: str


class RewriteInfo(BaseModel):
    presets: list[RewritePreset]
    materials: list[RewriteMaterialInfo]
    keep_max: int


class PromptText(BaseModel):
    """보내지 않고 보기만 하는 프롬프트 원문."""
    system: str
    prompt: str


@app.get("/api/projects/{name}/episodes/{n}/rewrite")
def rewrite_info(name: str, n: int) -> RewriteInfo:
    """다시 생성 패널: 빠른 요청과 함께 넣을 수 있는 재료(프롬프트에 들어갈 줄 그대로)."""
    p = _load(name)
    e = p.episode(n)
    mats = pipeline.rewrite_materials(p, n)
    last_edit = max((x.at for x in e.edits if not x.undone), default="")
    notes = {"issues": "검수한 뒤 본문을 고쳐서 이미 고친 곳일 수 있어요" if findings.open_findings(e) and last_edit > e.checked_at else "",
             "hook": "판정한 뒤 본문이 바뀌었어요" if mats["hook"] and pipeline.hook_stale(p, n) else ""}
    return {
        "presets": [{"id": k, "label": label} for k, (label, _) in prompts.REWRITE_PRESETS.items()],
        "materials": [{"id": k, "label": label, "lines": mats.get(k, []), "note": notes.get(k, "")}
                      for k, (label, _) in prompts.REWRITE_MATERIALS.items() if k != "hook" or prompts.is_opening(n)],
        "keep_max": prompts.REWRITE_KEEP,
    }


@app.post("/api/projects/{name}/episodes/{n}/rewrite/prompt")
def rewrite_prompt(name: str, n: int, body: RewriteRequest) -> PromptText:
    """다시 생성 때 보내는 프롬프트 원문 (보내지 않고 보기만)."""
    p = _load(name)
    return {"system": prompts.writer_system(p), "prompt": pipeline.rewrite_prompt(p, n, pipeline.clean_rewrite(body))}


def _no_write_job(name: str, n: int) -> None:
    if any(j.status == "running" and n in j.owned for j in jobs.listing(name)):
        raise ValueError(f"{n}화를 쓰는 작업이 도는 중이에요. 끝난 뒤에 하세요")


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


@app.post("/api/projects/{name}/episodes/{n}/edits/{eid}/redo")
def redo_passage(name: str, n: int, eid: str) -> Project:
    _load(name).episode(n)
    _text_guard(name, n)
    return _edit(name, lambda p: pipeline.redo_edit(p, n, eid))


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
        raise ValueError(f"초반 점검은 1~{prompts.OPENING_EPISODES}화만 해요")
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


@app.post("/api/projects/{name}/episodes/{n}/opening-plot/undo")
def opening_plot_undo(name: str, n: int) -> Project:
    """n화 플롯을 여는 방식 안을 처음 고르기 전으로 되돌린다 (Episode.opening_prev). 화는 초안이 된다."""
    _load(name)
    _not_auto(name)
    return _edit(name, lambda p: pipeline.undo_opening(p, n))


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

class PublishFormat(BaseModel):
    """줄바꿈 형식 하나 (publish.FORMATS)."""
    id: str
    label: str
    hint: str


class ExportOut(BaseModel):
    """붙여 넣을 글. episodes 는 실제로 넣은 화 (본문이 없는 화는 빠진다)."""
    text: str
    html: str
    episodes: list[int]
    filename: str


@app.get("/api/publish/formats")
def publish_formats() -> list[PublishFormat]:
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
        raise ValueError(f"없는 화예요: {', '.join(map(str, bad))}")
    return eps or sorted(e.plot.number for e in p.episodes if e.text)


@app.post("/api/projects/{name}/export")
def export_text(name: str, body: ExportIn) -> ExportOut:
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
        raise ValueError(f"모르는 모델이에요: {body.model}")
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
    force: bool = False  # 이미 저장된 외형 태그를 바꾼다


@app.post("/api/projects/{name}/episodes/{n}/illust/{iid}/keep-look")
def keep_illust_look(name: str, n: int, iid: str, body: KeepLook) -> Project:
    """삽화에서 AI 가 채운 외형 태그를 그 인물의 외형 태그로 저장한다."""
    _load(name).episode(n)
    return _edit(name, lambda p: pipeline.keep_illust_look(p, n, iid, body.character_id, body.force))


@app.delete("/api/projects/{name}/episodes/{n}/illust/{iid}")
def delete_illust(name: str, n: int, iid: str) -> Project:
    _load(name).episode(n)
    return _edit(name, lambda p: pipeline.remove_illustration(p, n, iid))


class VoiceRequest(BaseModel):
    request: str = ""


@app.post("/api/projects/{name}/characters/{cid}/voice")
def suggest_voice(name: str, cid: str, body: VoiceRequest | None = None) -> VoiceSuggestion:
    """인물이 시점 인물인 화의 서술 말투 초안. 저장은 화면에서 고쳐 작품 저장으로 한다."""
    return pipeline.suggest_voice(get_llm("plan"), _load(name), cid, body.request if body else "")


@app.post("/api/projects/{name}/characters/{cid}/body")
def suggest_body(name: str, cid: str) -> BodySuggestion:
    """신체 프로필 제안. 미성년 인물은 쓰리사이즈를 비운다. 작가가 칸별로 골라 작품 저장으로 남긴다."""
    return pipeline.suggest_body(get_llm("plan"), _load(name), cid)


@app.post("/api/projects/{name}/characters/{cid}/look")
def suggest_look(name: str, cid: str) -> LookSuggestion:
    """인물 설정을 외형 태그로 옮긴 제안. 저장은 화면에서 고쳐 작품 저장으로 한다."""
    return pipeline.suggest_look(get_llm("illustration"), _load(name), cid)


@app.get("/api/projects/{name}/episodes/{n}/prompt")
def prompt(name: str, n: int) -> PromptText:
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
    """채팅 앱이 돌려준 JSON 을 검사한다. 앞뒤 설명문과 코드 블록 표시는 버리고 첫 { 부터 마지막 } 까지 읽는다.
    화 번호는 이 화로 채운다 (채팅 앱이 episode 를 빼먹어도 받는다)."""
    p = _load(name)
    p.episode(n)
    data = _json_object(body.raw)
    data["episode"] = n
    try:
        delta = StateDelta.model_validate(data)
    except ValidationError as e:
        raise HTTPException(400, _validation_text(e))
    pipeline.clean_delta(p, delta)
    return delta


@app.post("/api/projects/{name}/episodes/{n}/check/import")
def import_check(name: str, n: int, body: Raw) -> Project:
    """채팅 앱이 돌려준 검수 결과 JSON 을 회차 하나로 합친다 (검수 지시서, 회차 source chat).
    상태 변경안 가져오기와 같은 규칙으로 읽는다."""
    _load(name).episode(n)
    data = _json_object(body.raw)
    data["episode"] = n
    try:
        rep = ConsistencyReport.model_validate(data)
    except ValidationError as e:
        raise HTTPException(400, _validation_text(e))
    return _edit(name, lambda q: pipeline.apply_check(q, rep, "chat"))


class FindingIn(BaseModel):
    status: FindingStatus | None = Field(None, description="처리 상태. 비우면(null) 그대로 둔다")
    note: str | None = Field(None, description="작가 메모. 비우면(null) 그대로 둔다")
    severity: Severity | None = Field(None, description="심각도. 비우면(null) 그대로 둔다. 작가가 정하면 다시 검수해도 덮지 않는다")


@app.put("/api/projects/{name}/episodes/{n}/findings/{fid}")
def set_finding(name: str, n: int, fid: str, body: FindingIn) -> Project:
    """검수 지적의 처리 상태(열림 · 고침 · 그대로 둠 · 잘못 짚음), 메모, 심각도를 정한다."""
    _load(name)

    def fn(q: Project) -> None:
        ep, now = q.episode(n), pipeline._now()
        f = findings.find(ep, fid)
        if body.severity is not None:
            findings.set_severity(ep, fid, body.severity, now)
        if body.status is not None or body.note is not None:
            findings.set_status(ep, fid, body.status or f.status, body.note, now)
    return _edit(name, fn)


@app.post("/api/projects/{name}/episodes/{n}/findings/{fid}/fixes")
def finding_fixes(name: str, n: int, fid: str) -> Project:
    """열린 지적 하나의 AI 고침안(2~3개, 딸린 곳 포함)을 받아 그 지적에 남긴다. 본문은 바꾸지 않는다."""
    p = _load(name)
    opts = pipeline.propose_fixes(get_llm("revise"), p, n, fid)
    return _edit(name, lambda q: pipeline.store_fixes(q, n, fid, opts))


class FixApplyIn(BaseModel):
    skip: list[int] = Field(default_factory=list, description="넣지 않을 딸린 곳 번호 (0부터)")
    confirm: bool = Field(False, description="그대로 둠 · 잘못 짚음 지적의 문장도 바꾸는 줄 알고 적용한다")


@app.post("/api/projects/{name}/episodes/{n}/findings/{fid}/fixes/{k}/apply")
def apply_finding_fix(name: str, n: int, fid: str, k: int, body: FixApplyIn) -> Project:
    """k 번째 고침안을 본문에 넣는다. 지적한 문장과 딸린 곳을 한 묶음으로 기록한다 (되돌리기도 묶음으로)."""
    _load(name).episode(n)
    _text_guard(name, n)
    return _edit(name, lambda q: pipeline.apply_fix(q, n, fid, k, body.skip, body.confirm))


@app.post("/api/projects/{name}/episodes/{n}/fix-groups/{group}/undo")
def undo_finding_fix(name: str, n: int, group: str) -> Project:
    """고침안 묶음을 한 번에 되돌린다. 그 뒤에 같은 자리를 또 고친 곳은 남긴다."""
    _load(name).episode(n)
    _text_guard(name, n)
    return _edit(name, lambda q: pipeline.undo_fix(q, n, group))


@app.post("/api/projects/{name}/episodes/{n}/findings/{fid}/recheck")
def recheck_finding(name: str, n: int, fid: str) -> Project:
    """열린 지적 하나만 다시 검수한다. 회차는 늘지 않는다. 풀렸으면 고침으로 닫고, 고친 문장 때문에 새로 어긋난 곳은 딸린 지적으로 더한다."""
    _not_auto(name)
    p = _load(name)
    res = pipeline.recheck_finding(get_llm("check"), p, n, fid)
    return _edit(name, lambda q: pipeline.apply_recheck(q, n, fid, res))


class StyleDrift(_Out):
    metrics: StyleMetrics
    warnings: list[str]


@app.get("/api/projects/{name}/episodes/{n}/style")
def episode_style(name: str, n: int) -> StyleDrift:
    """이번 화 문체 지표와 기준 대비 경고 (pipeline.style_drift). LLM 없이 부를 때마다 다시 잰다."""
    p = _load(name)
    if not p.episode(n).text:
        raise ValueError(f"{n}화 본문이 없어요")
    m, warns = pipeline.style_drift(p, n)
    return {"metrics": m, "warnings": warns}


def _json_object(raw: str) -> dict:
    """채팅 앱 답에서 첫 { 부터 마지막 } 까지 읽는다. 읽지 못하면 화면에 보일 까닭과 함께 400."""
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b < a:
        raise HTTPException(400, "JSON을 찾지 못했어요. 채팅 앱 답에서 { 로 시작하는 부분을 붙여 넣으세요")
    try:
        data = json.loads(raw[a:b + 1])
    except json.JSONDecodeError as e:
        # 줄 · 글자 번호는 붙여 넣은 원문 기준으로 센다 (앞 설명문이나 코드 블록 표시까지 포함)
        pos = a + e.pos
        line, col = raw.count("\n", 0, pos) + 1, pos - raw.rfind("\n", 0, pos)
        raise HTTPException(400, f"JSON 형식이 맞지 않아요: {line}번째 줄 {col}번째 글자 근처에서 {_json_reason(raw, pos, e.msg)}")
    if not isinstance(data, dict):
        raise HTTPException(400, "JSON이 { } 로 묶인 객체가 아니에요")
    return data


def _validation_text(e: ValidationError) -> str:
    err = e.errors()[0]
    loc = ".".join(map(str, err["loc"]))
    why = _VALIDATION_REASON.get(err["type"], err["msg"])
    return f"JSON 내용이 맞지 않아요: {f'{loc} 칸이 ' if loc else ''}{why}"


# json 모듈의 영어 오류 → 화면 문구
_JSON_REASON = {
    "Expecting ',' delimiter": "쉼표(,)가 빠졌어요",
    "Illegal trailing comma before end of object": "마지막 항목 뒤에 쉼표가 남았어요",
    "Illegal trailing comma before end of array": "마지막 항목 뒤에 쉼표가 남았어요",
    "Expecting ':' delimiter": "쌍점(:)이 빠졌어요",
    "Expecting property name enclosed in double quotes": "칸 이름을 큰따옴표로 감싸지 않았어요",
    "Expecting value": "값이 비었거나 잘못됐어요",
    "Extra data": "JSON이 끝난 뒤에 글이 더 있어요",
    "Unterminated string starting at": "따옴표가 닫히지 않았어요",
    "Invalid control character at": "글자 안에 줄바꿈 같은 제어 문자가 그대로 있어요",
    "Invalid \\escape": "역슬래시(\\) 표기가 잘못됐어요",
}
# pydantic 검증 오류 종류 → 화면 문구 ('… 칸이' 뒤에 붙는다)
_VALIDATION_REASON = {
    "missing": "없어요", "string_type": "글자여야 해요", "int_type": "정수여야 해요", "int_parsing": "정수여야 해요",
    "float_type": "숫자여야 해요", "float_parsing": "숫자여야 해요", "bool_type": "true 나 false 여야 해요",
    "bool_parsing": "true 나 false 여야 해요", "list_type": "목록([ ])이어야 해요", "model_type": "{ } 로 묶인 객체여야 해요",
    "dict_type": "{ } 로 묶인 객체여야 해요", "literal_error": "정해진 값 중 하나여야 해요", "enum": "정해진 값 중 하나여야 해요",
    "extra_forbidden": "필요 없는 칸이에요",
}


def _json_reason(raw: str, pos: int, msg: str) -> str:
    """json 오류를 한국어로. 닫는 괄호 앞에 쉼표가 남은 경우는 따로 알린다 (채팅 앱 답에 흔하다)."""
    before = raw[:pos].rstrip()
    if raw[pos:pos + 1] in ("}", "]") and before.endswith(","):
        return "마지막 항목 뒤에 쉼표가 남았어요"
    return _JSON_REASON.get(msg, msg)


@app.post("/api/projects/{name}/episodes/{n}/apply")
def apply_state(name: str, n: int, d: StateDelta) -> Project:
    """화면에서 고른 항목만 담긴 변경안을 반영하고 그 화를 끝낸다."""
    p = _load(name)
    _not_auto(name)
    ep = p.episode(n)
    if ep.status != "written":
        raise ValueError(f"{n}화는 본문이 작성된 상태가 아니에요 (현재: {ep.status})")
    pipeline.require_previous(p, n)
    d.episode = n
    pipeline.apply_delta(p, d)
    return _save(name, p)


@app.post("/api/projects/{name}/episodes/{n}/restate")
def apply_restate(name: str, n: int, d: StateDelta) -> Project:
    """반영 뒤 고친 화: 고친 본문에서 다시 뽑은 변경안 중 고른 요약 · 새 사실 · 새 복선만 반영한다."""
    p = _load(name)
    _not_auto(name)
    d.episode = n
    pipeline.apply_restate(p, d)
    return _save(name, p)


@app.post("/api/projects/{name}/episodes/{n}/keep-state")
def keep_state(name: str, n: int) -> Project:
    """반영 뒤 고쳤지만 상태는 그대로 둔다 (반영 뒤 고침 표시만 지운다)."""
    p = _load(name)
    _not_auto(name)
    pipeline.keep_state(p, n)
    return _save(name, p)


@app.post("/api/projects/{name}/revert/{n}")
def revert(name: str, n: int) -> Project:
    """n화 반영 직후로 되돌린다. 뒤 화의 본문은 남기고 반영만 취소한다 (0 이면 1화 시작 전)."""
    p = _load(name)
    _not_auto(name)
    pipeline.revert(p, n)
    out = _save(name, p)
    autorun.after_revert(name, n + 1)  # 자동 집필 실행 기록(자동 반영 목록, 로그, 끝남 상태)도 n+1화부터 맞춘다
    return out


# ---------- 자동 집필 (canon/autorun.py) ----------

class AutoIn(BaseModel):
    target: int
    batch: bool = False
    policy: autorun.Policy = autorun.Policy()


# 응답 모델: 기본값이 있는 칸도 응답에는 늘 있으니 명세에서 필수로 적는다 (Swift 타입이 옵셔널이 되지 않게)
_AUTO_OUT = ConfigDict(json_schema_serialization_defaults_required=True, populate_by_name=True)


class AutoLog(autorun.LogEntry):
    model_config = _AUTO_OUT


class AutoRun(autorun.Run):
    """autorun.Run 과 같은 칸. 명세에서 칸을 필수로 적으려고 따로 둔다."""
    model_config = _AUTO_OUT
    log: list[AutoLog] = Field(default_factory=list)


class AutoView(BaseModel):
    """자동 집필 화면이 받는 것: 마지막 실행, 도는 중인지, 배치를 쓸 수 있는 단계, 새로 시작할 때의 서버 기본 정책."""
    model_config = _AUTO_OUT
    run: AutoRun | None = None
    active: bool
    batch_stages: list[str]
    policy_defaults: autorun.Policy = Field(default_factory=autorun.Policy)


class AutoEstimate(BaseModel):
    """남은 화를 끝까지 쓸 때의 추정 (autorun.estimate)."""
    model_config = _AUTO_OUT
    episodes: int
    from_: int | None = Field(None, alias="from")
    to: int
    missing: list[int]
    drafts: list[int]
    calls: dict[str, int]
    tokens_in: int
    tokens_out: int
    cost: float | None = Field(None, description="USD. 가격표에 없는 모델이 있으면 null")
    batch: bool
    batch_rounds: int
    seconds_min: int
    seconds_max: int
    seconds_worst: int
    batch_avg_seconds: int | None = None
    measured: bool
    model: str
    unpriced: list[str]
    stages: dict[str, str]


def _auto(name: str) -> dict:
    p = _view(name)
    run = autorun.get_run(name)
    out = run.model_dump() if run else None
    if out and run.pending and (run.status != "review" or p.episode(run.ep).status != "written"):
        out["pending"] = None  # 사용자가 검토 화면에서 이미 반영했다
    return {"run": out, "active": autorun.active(name),
            "batch_stages": [s for s in ("write", "check", "state") if autorun.batchable(s)], "policy_defaults": autorun.Policy()}


@app.get("/api/projects/{name}/auto")
def auto_get(name: str) -> AutoView:
    return _auto(name)


@app.post("/api/projects/{name}/auto/estimate")
def auto_estimate(name: str, body: AutoIn) -> AutoEstimate:
    return autorun.estimate(_load(name), body.target, body.batch, body.policy, name)


@app.post("/api/projects/{name}/auto/start")
def auto_start(name: str, body: AutoIn) -> AutoView:
    _load(name)
    autorun.start(name, body.target, body.batch, body.policy)
    return _auto(name)


class AutoResume(BaseModel):
    approve: bool = False  # 검토 대기 변경안을 그대로 반영
    rewrite: bool = False  # 검토 대기 화를 다시 쓰기


@app.post("/api/projects/{name}/auto/resume")
def auto_resume(name: str, body: AutoResume) -> AutoView:
    _load(name)
    autorun.resume(name, approve=body.approve, rewrite=body.rewrite)
    return _auto(name)


@app.post("/api/projects/{name}/auto/review")
def auto_review(name: str) -> AutoView:
    """검토 대기 변경안을 검토를 기다리는 결과(pending.json 의 state:<화>)로 둔다. 상태 승인 화면이 작업 결과처럼 읽는다.
    웹은 화면 메모리로 넘기고(auto.js autoOpenReview), 앱은 이것을 부른 뒤 상태 승인 화면으로 간다."""
    p = _load(name)
    run = autorun.get_run(name)
    if run is None or run.status != "review" or run.pending is None or run.ep is None or p.episode(run.ep).status != "written":
        raise ValueError("검토를 기다리는 변경안이 없어요")
    n, key = run.ep, f"state:{run.ep}"
    rec = {"key": key, "id": f"auto:{run.started}:{n}", "kind": "state", "ep": n, "label": f"{n}화 상태 변경안",
           "result": run.pending.model_dump(), "base": run.pending_text or None, "at": _now()}
    store.edit_pending(name, lambda d: d["results"].__setitem__(key, rec))
    return _auto(name)


@app.post("/api/projects/{name}/auto/{what}")
def auto_request(name: str, what: str) -> AutoView:
    """what: pause | stop"""
    _load(name)
    if what not in ("pause", "stop"):
        raise HTTPException(404, "pause 또는 stop만 돼요")
    autorun.request(name, what)
    return _auto(name)


class AutoBatch(BaseModel):
    batch: bool


@app.put("/api/projects/{name}/auto/batch")
def auto_batch(name: str, body: AutoBatch) -> AutoView:
    _load(name)
    autorun.set_batch(name, body.batch)
    return _auto(name)


@app.put("/api/projects/{name}/auto/policy")
def auto_policy(name: str, body: autorun.Policy) -> AutoView:
    """멈춘 실행의 승인 정책을 바꾼다. 검토 대기와 기다리던 배치는 그대로 두고 다음 판정부터 적용된다."""
    _load(name)
    autorun.set_policy(name, body)
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


class CastTie(BaseModel):
    """한 시점의 방향 관계 (cast.frame). 말은 dynamics 의 구간 표현."""
    source: str
    target: str
    stage: str
    warmth: float
    trust: float
    evidence: float
    grievance: float
    status: float
    familiarity: float
    warmth_word: str
    trust_word: str


class CastPair(BaseModel):
    """두 사람 쌍의 긴장. 관계 설정이 없고 사건으로만 생긴 쌍은 type · description 이 빈칸."""
    a: str
    b: str
    type: str
    description: str
    goal_conflict: float
    tension: float
    tension_word: str


class CastSecret(BaseModel):
    id: str
    owner: str
    content: str
    hidden_from: list[str]


class CastFrame(BaseModel):
    """한 시점(0 = 1화 시작 전, n = n화 반영 뒤)의 관계 그림."""
    episode: int
    ties: list[CastTie]
    pairs: list[CastPair]
    triads: list[list[str]]
    secrets: list[CastSecret]
    states: list[CharacterState]


class CastAppearance(BaseModel):
    n: int
    status: str
    pov: bool


class CastChanges(BaseModel):
    """그 화에서 바뀐 상태. 바뀐 칸만 온다 (응답은 exclude_unset)."""
    emotional_state: str = ""
    current_goal: str = ""
    location: str = ""
    attire: str = ""
    knows: list[str] = []


class CastSettingChange(BaseModel):
    """그 화에 바뀐 인물 설정 한 칸 (charlog.history 한 줄)."""
    field: str
    label: str
    before: str
    after: str
    source: str
    reason: str = ""
    quote: str = ""


class CastTimelineRow(BaseModel):
    n: int
    title: str
    appears: bool
    pov: bool
    changes: CastChanges
    events: list[StoryEvent]
    secrets: list[str]
    new: bool
    settings: list[CastSettingChange] = []


class CastView(BaseModel):
    frames: list[CastFrame]
    appearances: dict[str, list[CastAppearance]]
    timelines: dict[str, list[CastTimelineRow]]


@app.get("/api/projects/{name}/cast", response_model_exclude_unset=True)
def cast_view(name: str) -> CastView:
    """인물 화면: 화별 관계 프레임(관계도 재생), 인물별 등장 화와 타임라인 (canon/cast.py)."""
    return cast.summary(_load(name))


class HeldIn(BaseModel):
    value: str | None = None  # 고친 값으로 적용할 때만


@app.post("/api/projects/{name}/setting-held/{i}")
def take_held_setting(name: str, i: int, body: HeldIn) -> Project:
    """자동 집필이 남겨 둔 설정 바꾸기 제안 하나를 적용한다. 그 화의 설정 변경 기록으로 남는다."""
    p = _load(name)
    _not_auto(name)
    charlog.take_held(p, i, body.value)
    return _save(name, p)


@app.delete("/api/projects/{name}/setting-held/{i}")
def drop_held_setting(name: str, i: int) -> Project:
    """남겨 둔 설정 바꾸기 제안 하나를 버린다."""
    p = _load(name)
    _not_auto(name)
    charlog.drop_held(p, i)
    return _save(name, p)


# ---------- 지도 (canon/atlas.py) ----------

@app.get("/api/projects/{name}/atlas")
def atlas_view(name: str) -> dict:
    """지도 화면: 장소와 자리, 화별 인물 자리, 장소와 맞지 않은 위치 글. 마을 데이터가 있으면 길 따라 걸은 경로도."""
    p = _load(name)
    s = atlas.summary(p, atlas.load_layout(_map_dir(name), p))
    return {**s, "travel": travel.view(p, s["frames"], s["places"]), "gen": atlas.gen_info(p)}


@app.post("/api/projects/{name}/atlas/generate/preview")
def atlas_generate_preview(name: str, body: MapSpec) -> dict:
    """지도 만들기 미리보기: 마을과 장소 자리 제안을 돌려준다. 저장하지 않는다."""
    return atlas.generate(_load(name), body)


@app.post("/api/projects/{name}/atlas/generate/suggest")
def atlas_generate_suggest(name: str, body: MapSpec) -> dict:
    """지도 만들기 설정 AI 제안 (크기 · 길 · 물 · 밭 · 숲, 장소마다 종류 · 놓기, 까닭). 저장하지 않는다."""
    return pipeline.suggest_map(get_llm("plan"), _load(name), body)


class GenerateIn(BaseModel):
    spec: MapSpec
    pins: list[str] = []  # 생성기가 고른 자리에 놓을 (이미 놓았으면 옮길) 장소 키


@app.post("/api/projects/{name}/atlas/generate")
def atlas_generate(name: str, body: GenerateIn) -> Project:
    """지도 만들기 적용: 같은 입력으로 마을을 다시 만들어 map/ 에 저장하고, 고른 장소만 새 자리에 놓는다."""
    p = _load(name)
    old = atlas.apply_generated(_map_dir(name), p, body.spec, body.pins)
    out = _save(name, p)
    if old and (_map_dir(name) / old).is_file():
        (_map_dir(name) / old).unlink()
    return out


class TitleIn(BaseModel):
    title: str


@app.put("/api/projects/{name}/atlas/title")
def atlas_title(name: str, body: TitleIn) -> Project:
    """지도 위 마을 이름. 비우면 '마을 가운데' 종류의 장소 이름을 쓴다."""
    p = _load(name)
    atlas.set_title(p, body.title)
    return _save(name, p)


@app.get("/api/projects/{name}/atlas/name-ideas")
def atlas_name_ideas(name: str) -> dict:
    """새 장소 이름 후보 (작품 이름 스타일). 저장하지 않는다."""
    return {"names": atlas.name_ideas(_load(name))}


class PlaceAddIn(BaseModel):
    name: str
    x: float
    y: float
    kind: str = ""  # 종류 한 단어 (설명 앞에 붙는다)


@app.post("/api/projects/{name}/atlas/places")
def atlas_place_add(name: str, body: PlaceAddIn) -> dict:
    """지도에서 고른 자리를 새 장소(인과율 '장소')로 등록하고 놓는다. 돌려주는 것: {key, project}."""
    p = _load(name)
    key = atlas.add_place(p, body.name, body.x, body.y, body.kind)
    atlas.fill_spots(p, atlas.load_layout(_map_dir(name), p))
    return {"key": key, "project": _save(name, p)}


@app.get("/api/projects/{name}/atlas/find-spots")
def atlas_find_spots(name: str) -> dict:
    """이름으로 자리 찾기: 장소 이름과 같은 이름의 건물 · 입점한 곳 · 표지 (atlas.find_spots). 저장하지 않는다."""
    p = _load(name)
    layout = atlas.load_layout(_map_dir(name), p)
    return {"spots": atlas.find_spots(p, layout) if layout else []}


class PinsIn(BaseModel):
    pins: list[MapPin]


@app.put("/api/projects/{name}/atlas/pins")
def atlas_pins(name: str, body: PinsIn) -> Project:
    """장소 자리를 통째로 저장한다 (놓기, 끌어 옮기기, 지도에서 빼기)."""
    p = _load(name)
    atlas.set_pins(p, body.pins)
    atlas.prune(p)
    atlas.fill_spots(p, atlas.load_layout(_map_dir(name), p))
    return _save(name, p)


class LinkIn(BaseModel):
    text: str
    place: str | None = None  # None 이면 잇기를 지운다, "" 이면 지도에 그리지 않는 위치


@app.put("/api/projects/{name}/atlas/links")
def atlas_link(name: str, body: LinkIn) -> Project:
    """장소 이름과 맞지 않은 인물 위치 글을 장소에 잇는다."""
    p = _load(name)
    atlas.set_link(p, body.text, body.place)
    return _save(name, p)


class SortIn(BaseModel):
    texts: list[str] | None = None  # 이 위치 글만 정리 (비우면 맞지 않은 글 모두)


@app.post("/api/projects/{name}/atlas/sort")
def atlas_sort(name: str, body: SortIn) -> dict:
    """장소와 맞지 않은 위치 글을 AI 가 장소에 맞춘 제안. 저장하지 않는다."""
    return pipeline.sort_places(get_llm("state"), _load(name), body.texts)


class SortPlace(NewPlace):
    first_ep: int = 0


class SortPick(BaseModel):
    text: str
    place: str = ""  # 장소 키
    new_place: str = ""  # 함께 등록할 새 장소 이름. 둘 다 비면 지도에 그리지 않음


class SortApplyIn(BaseModel):
    new_places: list[SortPlace] = []
    picks: list[SortPick]


@app.post("/api/projects/{name}/atlas/sort/apply")
def atlas_sort_apply(name: str, body: SortApplyIn) -> dict:
    """고른 위치 글을 한 번에 잇고, 고른 글이 쓰는 새 장소는 인과율 '장소'로 등록한다."""
    p = _load(name)
    done = atlas.apply_sort(p, [(NewPlace(**x.model_dump(exclude={"first_ep"})), x.first_ep) for x in body.new_places],
                            [(x.text, x.place, x.new_place) for x in body.picks])
    return {**done, "project": _save(name, p)}


class MapImageIn(BaseModel):
    data: str  # data:image/png;base64,...
    aspect: float  # 그림 가로 / 세로


def _map_dir(name: str) -> Path:
    return store.project_dir(name) / "map"


@app.put("/api/projects/{name}/atlas/image")
def atlas_image_set(name: str, body: MapImageIn) -> Project:
    """지도 배경 그림을 올린다. 작품 폴더의 map/ 에 파일로 두고 project.json 에는 이름만 적는다."""
    import base64
    import time

    m = re.match(r"data:([\w/+.-]+);base64,(.*)$", body.data, re.S)
    if not m or m.group(1) not in atlas.IMAGE_TYPES:
        raise ValueError("PNG, JPG, WEBP, GIF 그림만 올릴 수 있어요")
    raw = base64.b64decode(m.group(2), validate=False)
    if len(raw) > atlas.IMAGE_LIMIT:
        raise ValueError(f"그림이 너무 커요. {atlas.IMAGE_LIMIT // (1024 * 1024)}MB 이하로 올리세요")
    if not 0.1 <= body.aspect <= 10:
        raise ValueError("그림 비율을 읽지 못했어요")
    p = _load(name)
    d = _map_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    fname = f"map-{int(time.time())}.{atlas.IMAGE_TYPES[m.group(1)]}"
    (d / fname).write_bytes(raw)
    old = p.atlas.image
    p.atlas.image, p.atlas.aspect = fname, round(body.aspect, 4)
    out = _save(name, p)
    if old and old != fname and (d / old).is_file():
        (d / old).unlink()
    return out


@app.delete("/api/projects/{name}/atlas/image")
def atlas_image_drop(name: str) -> Project:
    """배경 그림을 지우고 빈 캔버스로 돌아간다. 장소 자리는 그대로 둔다."""
    p = _load(name)
    old, p.atlas.image = p.atlas.image, ""
    out = _save(name, p)
    if old and (_map_dir(name) / old).is_file():
        (_map_dir(name) / old).unlink()
    return out


@app.get("/api/projects/{name}/atlas/image")
def atlas_image_get(name: str) -> FileResponse:
    p = _load(name)
    path = _map_dir(name) / p.atlas.image if p.atlas.image else None
    if path is None or not path.is_file() or path.parent != _map_dir(name):
        raise HTTPException(404, "지도 그림이 없어요")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


class LayoutIn(BaseModel):
    data: str  # Watabou 생성기가 내보낸 JSON 글, 또는 OpenStreetMap .osm (XML) · GeoJSON 글


@app.put("/api/projects/{name}/atlas/layout")
def atlas_layout_set(name: str, body: LayoutIn) -> Project:
    """마을 · 도시 데이터를 올린다. 그릴 모양으로 바꿔(atlas.parse_upload: Watabou JSON 또는 OpenStreetMap) map/ 에 둔다.
    마을 데이터가 있으면 지도는 배경 그림 대신 마을을 그리고 비율도 마을을 따른다."""
    import time

    if len(body.data.encode("utf-8")) > atlas.LAYOUT_LIMIT:
        raise ValueError(f"파일이 너무 커요. {atlas.LAYOUT_LIMIT // (1024 * 1024)}MB 이하로 올리세요")
    layout = atlas.parse_upload(body.data)
    p = _load(name)
    d = _map_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    fname = f"layout-{int(time.time())}.json"
    atlas.enrich(p, layout, fname)
    (d / fname).write_text(json.dumps(layout, ensure_ascii=False), encoding="utf-8")
    old = p.atlas.layout
    p.atlas.layout, p.atlas.spec, p.atlas.buildings, p.atlas.layout_size, p.atlas.fill = fname, None, [], [layout["w"], layout["h"]], None
    atlas.fill_spots(p, layout)
    out = _save(name, p)
    if old and old != fname and (d / old).is_file():
        (d / old).unlink()
    return out


@app.delete("/api/projects/{name}/atlas/layout")
def atlas_layout_drop(name: str) -> Project:
    """마을 데이터를 지운다. 장소 자리는 그대로 둔다."""
    p = _load(name)
    old, p.atlas.layout, p.atlas.spec, p.atlas.buildings, p.atlas.layout_size, p.atlas.fill = p.atlas.layout, "", None, [], [], None
    atlas.fill_spots(p, None)
    out = _save(name, p)
    if old and (_map_dir(name) / old).is_file():
        (_map_dir(name) / old).unlink()
    return out


class FillIn(BaseModel):
    mode: str = "preview"  # preview 미리보기 | apply 적용 | clear 지은 건물 지우기
    seed: int = 1


@app.post("/api/projects/{name}/atlas/layout/fill")
def atlas_layout_fill(name: str, body: FillIn) -> dict:
    """OpenStreetMap 지도의 빈 블록 채우기 (canon/fill.py). preview 는 저장하지 않고 채울 블록 · 지을 건물을 돌려준다.
    apply 는 지도 파일을 다시 쓰고(지은 건물은 끝에 붙여 OSM 건물 번호를 지킨다) clear 는 지은 건물을 지운다."""
    p = _load(name)
    layout = atlas.load_layout(_map_dir(name), p)
    if layout is None:
        raise HTTPException(404, "마을 데이터가 없어요")
    if body.mode == "preview":
        return atlas.fill_preview(layout, body.seed)
    if body.mode == "apply":
        done = atlas.apply_fill(_map_dir(name), p, layout, body.seed)
        return {**done, "project": _save(name, p)}
    if body.mode == "clear":
        n = atlas.clear_fill(_map_dir(name), p, layout)
        return {"removed": n, "project": _save(name, p)}
    raise ValueError(f"모르는 동작이에요: {body.mode}")


@app.get("/api/projects/{name}/atlas/layout")
def atlas_layout_get(name: str) -> dict:
    """그릴 모양으로 바꾼 마을 데이터 (길 · 건물 · 물 · 밭 · 나무)."""
    p = _load(name)
    layout = atlas.load_layout(_map_dir(name), p)
    if layout is None:
        raise HTTPException(404, "마을 데이터가 없어요")
    return layout


class BuildingIn(BaseModel):
    use: str = ""
    name: str = ""
    note: str = ""
    residents: list[str] = []


@app.get("/api/projects/{name}/atlas/buildings/{i}")
def atlas_building(name: str, i: int) -> dict:
    """건물 하나: 쓰임 · 층수 · 사는 사람 · 주소 · 간판과 작가가 고친 값 (곁채면 본채 정보)."""
    p = _load(name)
    layout = atlas.load_layout(_map_dir(name), p)
    if layout is None:
        raise HTTPException(404, "마을 데이터가 없어요")
    try:
        return atlas.building(p, layout, i)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


@app.put("/api/projects/{name}/atlas/buildings/{i}")
def atlas_building_set(name: str, i: int, body: BuildingIn) -> Project:
    """작가가 건물을 고친다 (쓰임 · 이름 · 메모 · 사는 인물). 모두 비우면 생성기 값으로 돌아간다."""
    p = _load(name)
    layout = atlas.load_layout(_map_dir(name), p)
    if layout is None:
        raise HTTPException(404, "마을 데이터가 없어요")
    try:
        atlas.set_building(p, layout, i, body.use, body.name, body.note, body.residents)
        atlas.fill_spots(p, layout)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None
    return _save(name, p)


class TravelIn(BaseModel):
    enabled: bool = True
    mode: str = "horse"
    kmh: float = 0
    day_km: float = 0
    span_km: float = 0


@app.put("/api/projects/{name}/atlas/travel")
def atlas_travel(name: str, body: TravelIn) -> Project:
    """이동 시간 검사 설정: 켜기, 가장 빠른 탈것, 직접 정한 빠르기, 지도 가로 km (canon/travel.py)."""
    p = _load(name)
    travel.set_setting(p, body.enabled, body.mode, body.kmh, body.day_km, body.span_km)
    return _save(name, p)


class TravelOkIn(BaseModel):
    cid: str
    episode: int
    ok: bool = True


@app.put("/api/projects/{name}/atlas/travel/ok")
def atlas_travel_ok(name: str, body: TravelOkIn) -> Project:
    """이동 하나를 '괜찮아요'(순간 이동 등)로 두거나 되돌린다. 그 이동은 경고에서 빠진다."""
    p = _load(name)
    travel.accept(p, body.cid, body.episode, body.ok)
    return _save(name, p)


class MetersIn(BaseModel):
    meters: float


@app.put("/api/projects/{name}/atlas/meters")
def atlas_meters(name: str, body: MetersIn) -> Project:
    """마을 데이터 1단위가 몇 m 인지 (거리 · 걷는 시간)."""
    p = _load(name)
    atlas.set_meters(p, body.meters)
    return _save(name, p)


# ---------- 복선 센터 (canon/foreshadows.py) ----------

class ForeshadowCenterClue(BaseModel):
    """복선에 걸린 문장 하나."""
    episode: int
    quote: str
    by: str  # ai | author
    broken: bool  # 본문을 고쳐 문장이 사라졌다


class ForeshadowCenterItem(Foreshadow):
    """복선 하나와 계산값. 서버가 늘 채우는 칸은 앱에서 옵셔널이 되지 않게 기본값을 뺀다."""
    status: Literal["open", "resolved"]
    scope: Literal["arc", "part", "series"]
    plants: list[ForeshadowCenterClue]
    payoffs: list[ForeshadowCenterClue]
    last_seen: int  # 마지막으로 다시 떠올린 화
    planned: list[int]  # 플롯에서 회수할 예정인 화
    overdue: bool
    stale: bool
    broken: int  # 끊어진 연결 수


class ForeshadowCenter(BaseModel):
    """복선 센터 계산값 (foreshadows.center)."""
    total: int
    open: int
    resolved: int
    rate: float | None  # 복선이 없으면 비움
    broken: int
    overdue: int
    stale: int
    done: int  # 마지막으로 반영한 화
    last_ep: int  # 화 줄의 끝
    items: list[ForeshadowCenterItem]


@app.get("/api/projects/{name}/foreshadows")
def foreshadow_center(name: str) -> ForeshadowCenter:
    """복선마다 심은 문장 · 회수한 문장, 회수율, 끊어진 연결, 회수 예정이 지난 복선."""
    return foreshadows.center(_load(name))


class ForeshadowIn(BaseModel):
    description: str
    episode: int  # 심은 화
    scope: str = "arc"
    due_ep: int | None = None


@app.post("/api/projects/{name}/foreshadows")
def foreshadow_add(name: str, body: ForeshadowIn) -> Project:
    p = _load(name)
    _not_auto(name)
    foreshadows.add(p, body.description, body.episode, body.scope, body.due_ep)
    return _save(name, p)


class ForeshadowEdit(BaseModel):
    description: str | None = None
    scope: str | None = None
    due_ep: int | None = None
    clear_due: bool = False


@app.put("/api/projects/{name}/foreshadows/{fid}")
def foreshadow_edit(name: str, fid: str, body: ForeshadowEdit) -> Project:
    p = _load(name)
    _not_auto(name)
    foreshadows.update(p, fid, body.description, body.scope, body.due_ep, body.clear_due)
    return _save(name, p)


@app.delete("/api/projects/{name}/foreshadows/{fid}")
def foreshadow_remove(name: str, fid: str) -> Project:
    p = _load(name)
    _not_auto(name)
    foreshadows.remove(p, fid)
    return _save(name, p)


class EpisodeIn(BaseModel):
    episode: int


@app.post("/api/projects/{name}/foreshadows/{fid}/resolve")
def foreshadow_resolve(name: str, fid: str, body: EpisodeIn) -> Project:
    """근거 문장 없이 회수했다고만 표시한다. 문장을 함께 남기려면 /foreshadows/clues 에 payoff 로 건다."""
    p = _load(name)
    _not_auto(name)
    foreshadows.resolve(p, fid, body.episode)
    return _save(name, p)


@app.post("/api/projects/{name}/foreshadows/{fid}/reopen")
def foreshadow_reopen(name: str, fid: str) -> Project:
    p = _load(name)
    _not_auto(name)
    foreshadows.reopen(p, fid)
    return _save(name, p)


class ClueIn(BaseModel):
    episode: int
    quote: str
    foreshadow: str = ""  # 걸 복선 id. 비우고 description 을 주면 새 복선을 만들어 건다
    description: str = ""
    kind: str = "plant"


@app.post("/api/projects/{name}/foreshadows/clues")
def foreshadow_clue(name: str, body: ClueIn) -> Project:
    """본문에서 고른 문장을 복선에 건다. 작가 입력이라 승인 단계 없이 저장한다."""
    p = _load(name)
    _not_auto(name)
    if not body.foreshadow and body.kind == "payoff":
        raise ValueError("회수할 복선을 골라 주세요")
    fid = body.foreshadow or foreshadows.add(p, body.description, body.episode).id
    foreshadows.add_clue(p, body.episode, body.quote, fid, body.kind)
    return _save(name, p)


class ClueKey(BaseModel):
    foreshadow: str
    episode: int
    quote: str


@app.post("/api/projects/{name}/foreshadows/clues/remove")
def foreshadow_clue_remove(name: str, body: ClueKey) -> Project:
    p = _load(name)
    _not_auto(name)
    foreshadows.remove_clue(p, body.foreshadow, body.episode, body.quote)
    return _save(name, p)


@app.post("/api/projects/{name}/foreshadows/prune")
def foreshadow_prune(name: str) -> Project:
    """본문을 고쳐 사라진 문장에 걸린 연결을 지운다."""
    p = _load(name)
    _not_auto(name)
    foreshadows.prune(p)
    return _save(name, p)


# ---------- 상태창 (canon/statwin.py) ----------

class StatChange(BaseModel):
    """화별 비교표에서 그 화에 바뀐 칸 하나. 목록 항목(스킬 · 특성 · 인벤토리)은 더한 것 · 뺀 것도."""
    before: str
    source: Literal["ai", "author", "both"]
    added: list[str] = []
    removed: list[str] = []


class StatColumn(BaseModel):
    """화별 비교표의 한 화. values 는 그 화가 끝났을 때의 값, changed 는 그 화에 바뀐 항목."""
    episode: int
    values: dict[str, str]
    changed: dict[str, StatChange]


class StatwinView(BaseModel):
    """인물 하나의 상태창 화면 (statwin.timeline + render + PRESETS)."""
    names: list[str]
    columns: list[StatColumn]
    current: list[StatValue]
    text: str
    presets: dict[str, list[str]]


@app.get("/api/projects/{name}/statwin/{cid}")
def statwin_view(name: str, cid: str) -> StatwinView:
    """인물 하나의 지금 상태창, 화별 비교표, 본문에 넣을 글."""
    p = _load(name)
    return {**statwin.timeline(p, cid), "text": statwin.render(p, cid), "presets": statwin.PRESETS}


class StatsIn(BaseModel):
    stats: list[StatValue]


@app.put("/api/projects/{name}/statwin/{cid}")
def statwin_set(name: str, cid: str, body: StatsIn) -> Project:
    """작가가 상태창 항목과 값을 고친다. 마지막으로 반영한 화의 작가 기록으로 남는다."""
    p = _load(name)
    _not_auto(name)
    statwin.set_stats(p, cid, body.stats)
    return _save(name, p)


class StatTemplate(BaseModel):
    """상태창 서식. title · skin · names 를 빼고 보내면 지금 값을 둔다."""
    template: str
    row: str = "{key}: {value}"
    title: str | None = None
    skin: StatSkin | None = None
    names: list[str] | None = None


@app.put("/api/projects/{name}/statwin-template")
def statwin_template(name: str, body: StatTemplate) -> Project:
    if "{rows}" not in body.template:
        raise ValueError("서식에 {rows}가 있어야 항목이 들어가요")
    if "{key}" not in body.row or "{value}" not in body.row:
        raise ValueError("항목 한 줄에 {key}와 {value}가 있어야 해요")
    p = _load(name)
    w = p.stat_window
    w.template, w.row = body.template, body.row
    if body.title is not None:
        w.title = body.title.strip() or "상태창"
    if body.skin is not None:
        w.skin = body.skin
    if body.names is not None:
        w.names = list(dict.fromkeys(x.strip() for x in body.names if x.strip()))
    return _save(name, p)


class StatStyleRequest(BaseModel):
    request: str = ""


@app.post("/api/projects/{name}/statwin-suggest")
def statwin_suggest(name: str, body: StatStyleRequest | None = None) -> StatWindowSuggestion:
    """작품 설정에 맞춘 상태창 꾸미기 안. 저장하지 않는다 (작가가 고른 안을 statwin-template 로 저장)."""
    return pipeline.suggest_stat_window(get_llm("plan"), _load(name), body.request if body else "")


@app.post("/api/projects/{name}/statwin-init")
def statwin_init(name: str, body: StatStyleRequest | None = None) -> StatInitSuggestion:
    """1화 전 인물들의 상태창 처음 수치 제안. 저장하지 않는다 (작가가 고른 인물의 값을 PUT .../statwin/<인물> 로 저장)."""
    return pipeline.suggest_initial_stats(get_llm("plan"), _load(name), body.request if body else "")


# ---------- 스킬 · 특성 도감 (canon/abilities.py) ----------

class AbilityEvent(BaseModel):
    episode: int
    kind: Literal["얻음", "바뀜", "잃음"]
    item: str
    before: str


class AbilityOwner(BaseModel):
    """도감 항목을 지금 가진 인물. acquired 는 지금 가진 것을 얻은 화 (0 은 1화 전, 기록이 없으면 null)."""
    character_id: str
    stat: str
    item: str
    grade: str
    grade_effect: str
    acquired: int | None
    history: list[AbilityEvent] = []


class AbilityRow(BaseModel):
    """line 은 AI 에게 보이는 한 줄 (abilities.line). 설명 · 효과 · 대가가 모두 비면 빈 글."""
    ability: Ability
    owners: list[AbilityOwner]
    line: str = ""


class AbilityUnlinked(BaseModel):
    """도감에 없는 상태창 조각. 등급 꼬리를 뗀 이름이 같으면 하나로 묶는다."""
    name: str
    stat: str
    items: list[str]
    characters: list[str]


class AbilitiesView(BaseModel):
    abilities: list[AbilityRow]
    unlinked: list[AbilityUnlinked]
    lists: list[str]


class AbilityLookup(BaseModel):
    """칩 카드: 상태창 조각 하나. ability 가 없으면 도감에 없는 조각."""
    item: str
    name: str
    grade: str
    stat: str
    ability: Ability | None
    grade_effect: str = ""
    acquired: int | None = None
    history: list[AbilityEvent] = []


@app.get("/api/projects/{name}/abilities")
def abilities_view(name: str) -> AbilitiesView:
    """도감 항목마다 가진 인물(등급 · 등급 효과 · 얻은 화)과, 도감에 없는 상태창 조각."""
    return abilities.catalog(_load(name))


@app.get("/api/projects/{name}/abilities/lookup")
def abilities_lookup(name: str, item: str, cid: str = "", stat: str = "") -> AbilityLookup:
    """상태창 조각 하나(예: 화염구 Lv4)의 도감 항목과, 그 인물의 등급 효과 · 얻은 화 · 바뀐 기록."""
    return abilities.lookup(_load(name), item, cid, stat)


@app.put("/api/projects/{name}/abilities")
def abilities_save(name: str, body: Ability) -> Project:
    """도감 항목을 만들거나(id 가 비었거나 없는 id) 고친다. 작가 입력이라 바로 저장한다."""
    p = _load(name)
    abilities.upsert(p, body)
    return _save(name, p)


@app.delete("/api/projects/{name}/abilities/{aid}")
def abilities_delete(name: str, aid: str) -> Project:
    p = _load(name)
    abilities.remove(p, aid)
    return _save(name, p)


# ---------- 상태창 넣기 시험 (canon/stattrial.py, 연구 화면) ----------

class StatTrialCondition(BaseModel):
    key: str
    label: str
    about: str


class StatTrialCandidate(BaseModel):
    """시험할 수 있는 화. changed: 원래 반영에서 수치가 바뀐 화, wants: 플롯에 상태창 장면이 있는 화."""
    episode: int
    title: str
    changed: bool
    wants: bool


class StatTrialView(BaseModel):
    conditions: list[StatTrialCondition]
    candidates: list[StatTrialCandidate]
    pick: list[int]
    runs: list[dict]


class StatTrialIn(BaseModel):
    episodes: list[int]
    repeats: int = 1
    conditions: list[str] = []


@app.get("/api/projects/{name}/stattrial")
def stattrial_view(name: str) -> StatTrialView:
    """상태창 시험 화면: 조건, 시험할 수 있는 화, 추천 고르기, 지난 시험(실험 기록 kind statwin, 최근 10개)."""
    p = _load(name)
    cands = stattrial.candidates(p)
    runs = [r for r in research.history(name, 200) if r.get("kind") == "statwin"][:10]
    return {"conditions": [{"key": k, "label": v, "about": stattrial.ABOUT[k]} for k, v in stattrial.CONDITIONS.items()],
            "candidates": cands, "pick": stattrial.default_pick(cands), "runs": runs}


@app.post("/api/projects/{name}/stattrial/estimate")
def stattrial_estimate(name: str, body: StatTrialIn) -> dict:
    """쓰기 호출 수와 비용 추정. AI 를 부르지 않는다."""
    p = _load(name)
    ok = {c["episode"] for c in stattrial.candidates(p)}
    eps = sorted({x for x in body.episodes if x in ok})
    if not eps:
        raise ValueError("시험할 화를 고르세요")
    return stattrial.estimate(p, eps, body.repeats, body.conditions or None)


# ---------- 작품 속 시간 (canon/timeline.py) ----------
# 켜고 끄기, 기준 날짜, 화가 끝난 시점, 플롯의 시점은 작품 전체 저장(PUT /projects/<이름>)으로 고친다.
# 기한은 스냅샷과 함께 고쳐야 되돌리기와 맞아서 따로 둔다.

class TimelineRow(BaseModel):
    """화 하나의 시점: 플롯의 시점(plan), 끝난 시점(time), 날수를 아는 앞 화에서 지난 날(gap)."""
    episode: int
    title: str
    status: str
    plan: str
    time: StoryTime
    text: str
    gap: int | None  # 날수를 모르면 비움


class TimelineDeadline(Deadline):
    """기한 하나와 남은 날 ('4일 남음', '오늘', '2일 지남'. 닫혔거나 날수를 모르면 빈칸)."""
    left: str


class TimelineView(BaseModel):
    """작품 속 시간 화면 계산값 (timeline.view)."""
    day: int  # 다음에 쓸 화 직전의 날수. 모르면 0
    now: str
    rows: list[TimelineRow]
    deadlines: list[TimelineDeadline]


@app.get("/api/projects/{name}/timeline")
def timeline_view(name: str) -> TimelineView:
    """화별 작품 속 시점과 기한 (남은 날 포함)."""
    return timeline.view(_load(name))


class DeadlineIn(BaseModel):
    id: str = ""  # 비우면 새 기한 (마지막으로 반영한 화에 생긴 것으로)
    what: str
    day: int = 0
    note: str = ""
    done_ep: int = 0


@app.put("/api/projects/{name}/timeline/deadlines")
def deadline_put(name: str, body: DeadlineIn) -> Project:
    """작가가 기한을 더하거나 고친다. 스냅샷에도 같이 적어 되돌려도 남는다."""
    p = _load(name)
    _not_auto(name)
    timeline.upsert(p, Deadline(**body.model_dump()))
    return _save(name, p)


@app.delete("/api/projects/{name}/timeline/deadlines/{did}")
def deadline_remove(name: str, did: str) -> Project:
    p = _load(name)
    _not_auto(name)
    timeline.remove(p, did)
    return _save(name, p)


class Relations(BaseModel):
    """같은 관계를 말과 숫자로 (`_relations`)."""
    words: str
    numbers: str
    show_numbers: bool


class RelationPreview(Relations):
    """상태 승인 화면 미리 보기: 반영하면 계산될 관계와 반영 전 관계."""
    before: Relations


@app.post("/api/projects/{name}/episodes/{n}/preview")
def preview(name: str, n: int, d: StateDelta) -> RelationPreview:
    """화면에서 고른 변경안을 복사본에 반영해, 반영 후 계산될 관계를 미리 보여 준다. 저장하지 않는다."""
    sim = _load(name)
    before = _relations(sim)
    d.episode = n
    pipeline.apply_delta(sim, d)
    return {**_relations(sim), "before": before}  # 반영 전 관계: 화면이 줄마다 지금 → 반영 후를 비교한다


class View(BaseModel):
    show_numbers: bool


@app.put("/api/projects/{name}/view")
def set_view(name: str, body: View) -> Project:
    p = _load(name)
    p.settings.show_numbers = body.show_numbers
    return _save(name, p)


class CheckWiden(BaseModel):
    on: bool


@app.put("/api/projects/{name}/check-widen")
def set_check_widen(name: str, body: CheckWiden) -> Project:
    """장편 검수 넓히기 켜기 · 끄기 (Settings.check_widen). 자동 집필 검수도 따른다."""
    p = _load(name)
    p.settings.check_widen = body.on
    return _save(name, p)


class BoardSetting(BaseModel):
    on: bool


@app.put("/api/projects/{name}/storyboard-setting")
def set_storyboard_setting(name: str, body: BoardSetting) -> Project:
    """화별 스토리보드 켜기 · 끄기 (Settings.storyboard). 켜면 쓰기 프롬프트에 직전 화 본문 전체가 들어간다."""
    p = _load(name)
    p.settings.storyboard = body.on
    return _save(name, p)


class KeepSnapshots(BaseModel):
    on: bool


@app.put("/api/projects/{name}/keep-snapshots")
def set_keep_snapshots(name: str, body: KeepSnapshots) -> Project:
    """장편 스냅샷 모두 남기기 켜기 · 끄기 (Settings.keep_snapshots). 끄면 다음 반영 때 오래된 스냅샷을 지운다."""
    p = _load(name)
    p.settings.keep_snapshots = body.on
    return _save(name, p)


# ---------- 플레이 모드 (canon/play.py, canon/birth.py) ----------
# 플레이 하나는 세계 작품을 복사한 작품 폴더다(play.json 이 있으면 플레이). 시계는 화면에 있고, 서버는 화면이 닿은 구간(see)보다
# 한 구간 넘게 앞서 쓰지 않는다. 구간 작업(play_turn)은 남은 상태 반영 → 장면 → 저장 → 상태 반영 → 저장 순서로 한 스레드에서 돈다.
# 같은 플레이의 구간 작업은 플레이 잠금으로 줄을 세운다. 결정 장면에서 고르면 앞 구간 반영이 끝난 뒤에 쓴다.

class PlayBeatOut(_Out):
    when: str = Field(description="작품 속 시점 (timeline.when). 모르면 빈 값")
    day: int = Field(description="작품 속 날수. 화면 시계가 줄 사이 시간 칸을 센다. 모르면 0")
    text: str


class PlayTurnOut(_Out):
    """구간 하나. 운(luck)은 화면에 보이지 않아 응답에서 뺀다."""
    number: int
    kind: str
    action: str
    beats: list[PlayBeatOut]
    scene: str = Field(description="결정 장면 본문. 없으면 빈 값")
    choices: list[str]
    state: str
    error: str
    ending: str
    when: str = Field(description="구간이 끝난 시점. 상태를 반영하기 전이면 빈 값일 수 있다")
    summary: str


class PlayChapterOut(_Out):
    number: int
    title: str
    start_ep: int
    end_ep: int
    summary: str
    span: str = Field(description="작품 속 시점 범위 ('3일째 ~ 9일째'). 모르면 빈 값")


class PlayMe(_Out):
    id: str
    name: str
    gender: str
    age: str
    role: str
    emotion: str
    goal: str
    location: str
    attire: str


class PlayStatOut(_Out):
    name: str
    value: str


class PlayDeadlineOut(_Out):
    what: str
    left: str = Field(description="'4일 남음' · '오늘' · '2일 지남'. 날을 모르면 빈 값")


class PlayNearOut(_Out):
    """가까운 사람: 그 인물이 플레이어를 보는 관계 (dynamics 계산값을 말로)."""
    id: str
    name: str
    warmth: str
    trust: str
    tension: str
    warmth_value: float = Field(description="-1~1")
    tension_value: float = Field(description="0~10")


class PlayJobOut(_Out):
    id: str
    status: str
    label: str
    ep: int | None = None
    note: str
    error: str
    started: float


class PlayView(_Out):
    """플레이 화면이 보는 값. 플레이 정보와 구간, 옆 패널(내 인물 상태, 상태창, 기한, 가까운 사람), 지금 도는 구간 작업."""
    name: str
    title: str
    world: str
    world_title: str
    world_exists: bool
    world_ep: int
    origin: str
    person: str
    unit: str
    segment_units: int
    focus: str
    auto_decide: bool
    seen: int
    ending: str
    ended_ep: int
    start_day: int
    max_turns: int
    end_days: int
    end_decisions: int
    decisions: int
    days: int
    now: str = Field(description="마지막으로 반영한 구간이 끝난 시점")
    me: PlayMe
    stat_title: str
    stats: list[PlayStatOut]
    deadlines: list[PlayDeadlineOut]
    near: list[PlayNearOut]
    turns: list[PlayTurnOut]
    chapters: list[PlayChapterOut]
    job: PlayJobOut | None = Field(None, description="도는 구간 작업, 또는 마지막 구간 작업이 실패했으면 그 작업")


class PlayRelChange(_Out):
    id: str
    name: str
    before: str = Field(description="처음 (플레이를 시작할 때) 그 인물이 플레이어를 보던 마음. 모르는 사이였으면 빈 값")
    after: str
    trust: str


class PlayLife(_Out):
    """생애 기록: 출생, 장별 요약, 관계 처음 → 끝, 마지막 구간."""
    name: str
    title: str
    world: str
    world_title: str
    player: str
    gender: str
    age: str
    place: str
    origin: str
    seed: int
    ending: str
    days: int
    decisions: int
    free: int = Field(description="직접 적어 해 본 일 수")
    turns: int
    archetype: str
    wound: str
    speech: str
    twist: str
    background: str
    chapters: list[PlayChapterOut]
    relations: list[PlayRelChange]
    last_when: str
    last_text: str


class PlayWorldChar(_Out):
    id: str
    name: str
    role: str
    age: str
    gender: str
    tier: str
    summary: str
    emotion: str
    goal: str


class PlayWorld(_Out):
    """새 플레이 화면이 보는 세계 작품 정보."""
    name: str
    title: str
    genre: str
    form: str
    adult: bool
    world_ep: int = Field(description="플레이가 이어받는 마지막 반영 화")
    unit: str = Field(description="시간 단위 자동 값 (play.pick_unit)")
    characters: list[PlayWorldChar]
    places: int = Field(description="태어날 수 있는 장소 수 (birth.birth_places)")


class BirthIn(BaseModel):
    seed: int | None = None
    gender: str = ""
    age: str = ""


class BirthCard(_Out):
    """굴린 출생과 화면에 보일 이름 (원형 · 상처 · 말투 틀)."""
    birth: Birth
    archetype: str
    wound: str
    speech: str


class SketchIn(BaseModel):
    birth: Birth


class PlayStartIn(BaseModel):
    to: str = Field(description="플레이 폴더 이름")
    title: str = ""
    player: str = Field("", description="세계 인물 id. 무작위 출생이면 비우고 birth · sketch 를 준다")
    birth: Birth | None = None
    sketch: BirthSketch | None = None
    person: PlayPerson = "second"
    unit: PlayUnit = "auto"
    focus: str = ""
    auto_decide: bool = False
    max_turns: int = 0
    end_days: int = 0
    end_decisions: int = 0
    seed: int | None = None


class PlayStarted(_Out):
    name: str
    job: PlayJobOut


class PlayWorldIn(BaseModel):
    name: str
    genres: list[str] = []
    logline: str
    adult: bool = False


class PlayAdvance(BaseModel):
    action: str = Field("", description="직접 적은 행동. 비면 시간이 흐른다 (마지막 구간 반영이 실패했으면 반영을 다시 한다)")
    kind: Literal["flow", "free", "auto"] = Field("flow", description="auto 면 AI 가 낸 lean 을 고른다")
    choice: int = Field(0, description="결정 장면 선택지 번호 (1부터)")


class PlaySee(BaseModel):
    n: int


class PlaySettingsIn(BaseModel):
    title: str | None = None
    focus: str | None = None
    auto_decide: bool | None = None


class PlayRewindIn(BaseModel):
    n: int


class PlayForkIn(BaseModel):
    n: int
    to: str
    title: str = ""


class PlayEndIn(BaseModel):
    reason: str = ""


_play_locks: dict[str, threading.Lock] = {}


def _play_lock(name: str) -> threading.Lock:
    """구간 작업이 플레이 하나를 차례로 쓰게 하는 잠금. LLM 호출 동안 잡으므로 짧은 저장 잠금(jobs.project_lock)과 따로 둔다."""
    with jobs._lock:
        return _play_locks.setdefault(name, threading.Lock())


def _play(name: str) -> tuple[Project, PlayInfo]:
    p = _load(name)
    info = store.load_play(name)
    if info is None:
        raise ValueError(f"플레이가 아닌 작품이에요: {name}")
    return p, info


def _play_save(name: str, p: Project | None, info: PlayInfo) -> None:
    """구간 작업의 저장. 그동안 화면이 고친 play.json 칸(닿은 구간, 이름, 초점, 자동 결정)은 디스크 것을 따른다.
    멈춘 작업이면 저장하지 않는다 (되감기 · 끝내기가 먼저 멈춘다)."""
    with jobs.project_lock(name):
        cancel.check()
        fresh = store.load_play(name)
        if fresh is not None:
            play.see(info, fresh.seen)
            info.title, info.focus, info.auto_decide = fresh.title, fresh.focus, fresh.auto_decide
        if p is not None:
            store.save(name, p)
        store.save_play(name, info)


def _play_running(name: str) -> list[jobs.Job]:
    return [j for j in jobs.listing(name) if j.kind == "play_turn" and j.status == "running"]


def _play_stop(name: str, after: int | None = None) -> None:
    """도는 구간 작업을 멈춘다. after 를 주면 그 구간보다 뒤를 쓰는 작업만 (화면이 아직 닿지 않은 구간)."""
    for j in _play_running(name):
        if after is None or (j.ep or 0) > after:
            jobs.stop(j.id)


def _play_job_out(j: jobs.Job) -> PlayJobOut:
    return PlayJobOut(id=j.id, status=j.status, label=j.label, ep=j.ep, note=j.note, error=j.error, started=j.started)


def _play_settle(name: str, p: Project, info: PlayInfo, n: int, llm) -> None:
    with usage.scope(episode=n):
        try:
            play.settle(llm, p, info, n)
        except cancel.Cancelled:
            raise
        except Exception:
            _play_save(name, None, info)  # 반영 실패(failed)만 남긴다. 구간은 그대로다
            raise
    _play_save(name, p, info)


def _play_start_job(name: str, info: PlayInfo, action: str = "", kind: str | None = None) -> jobs.Job:
    """구간 작업을 시작한다. 마지막 구간 반영이 남았으면 먼저 반영하고(행동이 그 구간을 버리면 건너뜀), 행동이 없고 반영만 남았으면
    반영만 한다. 끝나면 _play_continue 가 다음 흐름 구간을 잇는다."""
    scene_llm, state_llm = get_llm("play"), get_llm("state")  # 키가 없으면 바로 알린다
    last = play.last_turn(info)
    retry = not action and last is not None and last.state != "applied"
    if retry:
        n = last.number
        label = f"{n}구간 상태 반영"
    else:
        n = (max(info.seen, info.world_ep) if action and info.turns else play.next_number(info) - 1) + 1
        label = f"{n}구간 쓰기"

    def fn(job: jobs.Job):
        lock = _play_lock(name)
        while not lock.acquire(timeout=0.5):
            cancel.check()
        try:
            p, info = play.load(name)
            t = play.last_turn(info)
            if t is not None and t.state != "applied" and not info.ending and not (action and t.number > info.seen):
                job.note = f"{t.number}구간 상태 반영 중"
                _play_settle(name, p, info, t.number, state_llm)
            if retry:
                return {"turn": n}
            job.note = f"{n}구간 쓰는 중"
            cancel.check()
            with usage.scope(episode=n):
                play.scene(scene_llm, p, info, action or (info.opening if not info.turns else ""), kind)  # type: ignore[arg-type]
            k = play.last_turn(info).number  # 끼어들면 보지 않은 구간을 버려 번호가 당겨진다
            _play_save(name, p, info)  # 구간 먼저 저장한다. 상태 반영이 실패해도 구간은 남는다
            job.done, job.note = 1, f"{k}구간 상태 반영 중"
            _play_settle(name, p, info, k, state_llm)
            job.note = ""
            return {"turn": k}
        finally:
            lock.release()

    def run(job: jobs.Job):
        out = fn(job)
        _play_continue(name, job.id)
        return out

    with usage.scope(project=name, episode=n, task="play"):
        return jobs.start(name, "play_turn", n, label, run, total=1 if retry else 2, owned={n})


def _play_continue(name: str, exclude: str = "") -> None:
    """시간이 흐르는 중이면 다음 구간을 미리 쓴다: 끝나지 않았고, 마지막 구간을 반영했고, 결정 장면이 아니고, 화면이 그 구간에 닿았다.
    그래서 서버는 화면보다 한 구간 넘게 앞서 쓰지 않는다 (play.scene 이 같은 규칙으로 막는다)."""
    if any(j.id != exclude for j in _play_running(name)):
        return
    info = store.load_play(name)
    t = play.last_turn(info) if info else None
    if info is None or t is None or info.ending or t.state != "applied" or t.choices or info.seen < t.number:
        return
    if info.max_turns and len(info.turns) >= info.max_turns:
        return
    try:
        _play_start_job(name, info)
    except (jobs.Busy, MissingKey):
        pass


def _scene_of(p: Project, t, e: Episode | None) -> str:
    """구간 본문(흘러간 일 줄 + 결정 장면)에서 결정 장면만."""
    if e is None or not e.text:
        return ""
    head = play.segment_text(p, t.beats, "")
    return e.text[len(head):].strip() if e.text.startswith(head) else ("" if not t.choices else e.text)


def _play_chapters(p: Project, info: PlayInfo) -> list[PlayChapterOut]:
    out = []
    for a in sorted(p.story_arcs, key=lambda a: a.start_ep):
        if a.end_ep <= info.world_ep:
            continue
        eps = [e for e in p.episodes if a.start_ep <= e.plot.number <= a.end_ep and timeline.known(e.time)]
        days = [b.time for t in info.turns if a.start_ep <= t.number <= a.end_ep for b in t.beats if b.time.day]
        first = days[0] if days else (eps[0].time if eps else None)
        last = eps[-1].time if eps else (days[-1] if days else None)
        span = " ~ ".join(dict.fromkeys(x for x in (timeline.when(p, first), timeline.when(p, last)) if x))
        out.append(PlayChapterOut(number=a.number, title=a.title, start_ep=a.start_ep, end_ep=a.end_ep, summary=a.summary, span=span))
    return out


def _play_days(p: Project, info: PlayInfo) -> int:
    day = max((e.time.day for e in p.episodes if e.plot.number > info.world_ep), default=0)
    return max(0, day - info.start_day) if day else 0


def _play_card(p: Project, info: PlayInfo) -> PlayCard:
    who = next((c.name for c in p.characters if c.id == info.player), info.player)
    return PlayCard(world=info.world, title=info.title or f"{who}의 삶", player=who, origin=info.origin, ending=info.ending,
                    turns=len(info.turns), decisions=sum(t.kind in play.DECIDED for t in info.turns), days=_play_days(p, info),
                    waiting=play.waiting(info) and not info.ending)


def _play_view(name: str) -> PlayView:
    p, info = _play(name)
    me = next((c for c in p.characters if c.id == info.player), None)
    st = next((s for s in p.states if s.character_id == info.player), None)
    by_n = {e.plot.number: e for e in p.episodes}
    turns = []
    for t in info.turns:
        e = by_n.get(t.number)
        turns.append(PlayTurnOut(
            number=t.number, kind=t.kind, action=t.action, state=t.state, error=t.error, ending=t.ending,
            beats=[PlayBeatOut(when=timeline.when(p, b.time) if timeline.known(b.time) else "", day=b.time.day, text=b.text) for b in t.beats],
            scene=_scene_of(p, t, e), choices=[c.text for c in t.choices],
            when=timeline.when(p, e.time) if e is not None and timeline.known(e.time) else "", summary=e.summary if e else ""))
    done = max((t.number for t in info.turns if t.state == "applied"), default=info.world_ep)
    last_e = by_n.get(done)
    day = timeline.current_day(p, done + 1)
    deadlines = [PlayDeadlineOut(what=d.what, left=timeline.left(d, day)) for d in timeline.open_deadlines(p, done + 1)][:5]
    near = []
    triads = dynamics.unbalanced_triads(p.ties)
    for c in p.characters:
        tie = dynamics.find_tie(p.ties, c.id, info.player) if c.id != info.player else None
        if tie is None:
            continue
        ten = dynamics.tension(p, c.id, info.player, triads)
        near.append(PlayNearOut(id=c.id, name=c.name, warmth=dynamics.warmth_word(tie.warmth), trust=dynamics.trust_word(tie.trust),
                                tension=dynamics.tension_word(ten), warmth_value=round(tie.warmth, 3), tension_value=round(ten, 2)))
    near.sort(key=lambda x: -x.tension_value)
    job = None
    mine = [j for j in jobs.listing(name) if j.kind == "play_turn"]
    if mine and (mine[-1].status == "running" or mine[-1].status == "error"):
        job = _play_job_out(mine[-1])
    w = store.load(info.world) if store.exists(info.world) else None
    return PlayView(
        name=name, title=info.title or f"{me.name if me else info.player}의 삶", world=info.world, world_title=w.meta.title if w else info.world,
        world_exists=w is not None, world_ep=info.world_ep, origin=info.origin, person=info.person, unit=info.unit,
        segment_units=info.segment_units, focus=info.focus, auto_decide=info.auto_decide, seen=info.seen, ending=info.ending,
        ended_ep=info.ended_ep, start_day=info.start_day, max_turns=info.max_turns, end_days=info.end_days,
        end_decisions=info.end_decisions, decisions=sum(t.kind in play.DECIDED for t in info.turns), days=_play_days(p, info),
        now=timeline.when(p, last_e.time) if last_e is not None and timeline.known(last_e.time) else "",
        me=PlayMe(id=info.player, name=me.name if me else info.player, gender=me.gender if me else "", age=me.age if me else "",
                  role=me.role if me else "", emotion=st.emotional_state if st else "", goal=st.current_goal if st else "",
                  location=st.location if st else "", attire=st.attire if st else ""),
        stat_title=p.stat_window.title, stats=[PlayStatOut(name=x.name, value=x.value) for x in (st.stats if st else []) if x.value],
        deadlines=deadlines, near=near[:5], turns=turns, chapters=_play_chapters(p, info), job=job)


@app.get("/api/projects/{world}/play/world")
def play_world(world: str) -> PlayWorld:
    """새 플레이 화면: 세계 작품의 인물(반영 직후 상태), 시간 단위 자동 값, 태어날 수 있는 장소 수."""
    w = _load(world)
    if store.load_play(world) is not None:
        raise ValueError("플레이 사본에서는 새 플레이를 열 수 없어요. 세계 작품에서 여세요")
    states = {s.character_id: s for s in w.states}
    chars = [PlayWorldChar(id=c.id, name=c.name, role=c.role, age=c.age, gender=c.gender, tier=c.tier,
                           summary=(c.background or c.personality).split("\n")[0][:120],
                           emotion=states[c.id].emotional_state if c.id in states else "",
                           goal=states[c.id].current_goal if c.id in states else "") for c in w.characters if c.name]
    return PlayWorld(name=world, title=w.meta.title or world, genre=w.meta.genre, form=w.meta.form, adult=w.meta.adult,
                     world_ep=birth.last_finalized(w), unit=play.pick_unit(w), characters=chars, places=len(birth.birth_places(w)))


@app.post("/api/projects/{world}/play/roll")
def play_roll(world: str, body: BirthIn) -> BirthCard:
    """무작위 출생을 굴린다 (birth.roll, LLM 없음). 시드를 비우면 새로 정한다."""
    w = _load(world)
    seed = body.seed if body.seed is not None else random.randrange(1 << 31)
    b = birth.roll(w, seed, body.gender, body.age)
    a, wd, sp = archetypes.BY_ID.get(b.archetype), archetypes.WOUND_BY_ID.get(b.wound), archetypes.SPEECH_BY_ID.get(b.speech)
    return BirthCard(birth=b, archetype=a.name if a else b.archetype, wound=wd.name if wd else b.wound, speech=sp.name if sp else b.speech)


@app.post("/api/projects/{world}/play/sketch")
def play_sketch(world: str, body: SketchIn) -> dict:
    """굴린 출생의 배경을 AI 가 채운다 (birth.sketch, 작업). 결과는 작업의 result (BirthSketch)."""
    _load(world)
    llm = get_llm("plan")
    for j in jobs.listing(world):
        if j.kind == "play_sketch" and j.status == "running":
            jobs.stop(j.id)  # 다시 굴렸으면 앞 배경은 쓸모없다
    b = body.birth

    def fn(job: jobs.Job):
        return birth.sketch(llm, store.load(world), b).model_dump()
    with usage.scope(project=world, task="play"):
        return jobs.start(world, "play_sketch", None, f"{b.name or '출생'} 배경 쓰기", fn).public()


@app.post("/api/play/worlds")
def play_new_world(body: PlayWorldIn) -> dict:
    """장르와 한 줄로 새 세계 작품을 만든다 (birth.new_world, 작업). 일반 작품으로 남는다."""
    name = body.name.strip()
    if not NAME_RE.match(name):
        raise HTTPException(400, NAME_ERR)
    if store.exists(name):
        raise HTTPException(409, f"이미 있는 이름이에요: {name}")
    if not body.logline.strip():
        raise ValueError("어떤 세계인지 한 줄로 적어 주세요")
    llm = get_llm("plan")

    def fn(job: jobs.Job):
        birth.new_world(llm, name, body.genres, body.logline, body.adult)
        return {"name": name}
    try:
        with usage.scope(project=name, task="play"):
            return jobs.start(name, "play_world", None, f"새 세계 {name} 만들기", fn).public()
    except jobs.Busy as b:
        return {**b.job.public(), "already": True}


@app.post("/api/projects/{world}/play/start")
def play_start(world: str, body: PlayStartIn) -> PlayStarted:
    """세계 작품을 복사해 플레이를 열고(play.start, LLM 없음) 첫 구간 작업을 시작한다. 세계 작품은 바뀌지 않는다."""
    w = _load(world)
    to = _new_name(NewName(name=body.to))
    get_llm("play"), get_llm("state")  # 키가 없으면 폴더를 만들기 전에 알린다
    character, opening, seed = None, "", body.seed
    if body.birth is not None:
        if body.sketch is None:
            raise ValueError("무작위 출생은 배경을 채운 뒤에 시작해요")
        character, opening = birth.to_character(w, body.birth, body.sketch), body.sketch.opening
        seed = body.birth.seed if seed is None else seed
    with jobs.project_lock(world):
        p, info = play.start(world, to, player=body.player, character=character, birth=body.birth, person=body.person,
                             max_turns=body.max_turns, seed=seed, unit=body.unit, focus=body.focus, auto_decide=body.auto_decide,
                             end_days=body.end_days, end_decisions=body.end_decisions, title=body.title, opening=opening)
    return PlayStarted(name=to, job=_play_job_out(_play_start_job(to, info, opening, "start")))


@app.get("/api/projects/{name}/play")
def get_play(name: str) -> PlayView:
    return _play_view(name)


@app.post("/api/projects/{name}/play/advance")
def play_advance(name: str, body: PlayAdvance) -> PlayJobOut:
    """다음 구간. 고르거나(choice) 적거나(action) 자동 결정(kind auto)이면 그 행동으로, 아니면 시간이 흐른다.
    행동이 있으면 화면이 아직 닿지 않은 구간을 쓰는 작업은 멈추고 버린다(끼어들기). 화면이 닿은 구간의 반영은 끝난 뒤 잇는다."""
    _, info = _play(name)
    if info.ending:
        raise ValueError(f"플레이가 끝났어요 ({info.ending}). 이어 가려면 되감으세요")
    action, kind = body.action.strip(), None
    if body.choice:
        action, kind = play.choice_action(info, body.choice)
    elif body.kind == "auto":
        action, kind = play.auto_action(info)
    elif action:
        kind = "free"  # 선택지와 글이 같으면 play.scene 이 choice 로 센다
    if action:
        _play_stop(name, after=info.seen)
    else:
        running = _play_running(name)
        if running:
            return _play_job_out(running[-1])
        t = play.last_turn(info)
        if t is not None and t.state == "applied":
            play.check_turn(info)  # 결정할 차례 · 아직 보지 않은 구간 · 구간 한도
    return _play_job_out(_play_start_job(name, info, action, kind))


@app.post("/api/projects/{name}/play/see")
def play_see(name: str, body: PlaySee) -> dict:
    """화면 시계가 n 구간에 닿았다. 시간이 흐르는 중이면 다음 구간을 미리 쓰기 시작한다."""
    _play(name)
    with jobs.project_lock(name):
        info = store.load_play(name)
        play.see(info, body.n)
        store.save_play(name, info)
    _play_continue(name)
    return {"seen": info.seen}


@app.put("/api/projects/{name}/play/settings")
def play_settings(name: str, body: PlaySettingsIn) -> PlayView:
    """플레이 이름 · 초점 · 자동 결정. 다음에 쓰는 구간부터 따른다."""
    _play(name)
    with jobs.project_lock(name):
        info = store.load_play(name)
        if body.title is not None:
            info.title = body.title.strip()
        if body.focus is not None:
            info.focus = body.focus.strip()
        if body.auto_decide is not None:
            info.auto_decide = body.auto_decide
        store.save_play(name, info)
    return _play_view(name)


@app.post("/api/projects/{name}/play/rewind")
def play_rewind(name: str, body: PlayRewindIn) -> PlayView:
    """n 구간 직후로 되감는다 (play.rewind). 도는 구간 작업은 멈추고 그 결과는 버린다."""
    _play(name)
    _play_stop(name)
    with jobs.project_lock(name):
        p, info = play.load(name)
        play.rewind(p, info, body.n)
        play.save(name, p, info)
    return _play_view(name)


@app.post("/api/projects/{name}/play/fork")
def play_fork(name: str, body: PlayForkIn) -> dict:
    """'여기서 다르게 해 보기': 이 플레이를 남긴 채 사본을 n 구간 직후로 되감는다 (play.fork)."""
    _play(name)
    to = _new_name(NewName(name=body.to))
    with jobs.project_lock(name):
        play.fork(name, to, body.n, body.title)
    return {"name": to}


@app.post("/api/projects/{name}/play/end")
def play_end(name: str, body: PlayEndIn) -> PlayView:
    """플레이를 끝낸다. 되감으면 다시 이어 갈 수 있다."""
    _play(name)
    _play_stop(name)
    with jobs.project_lock(name):
        p, info = play.load(name)
        if info.ending:
            raise ValueError(f"이미 끝난 플레이예요 ({info.ending})")
        play.end(p, info, body.reason)
        store.save_play(name, info)
    return _play_view(name)


@app.get("/api/projects/{name}/play/life")
def play_life(name: str) -> PlayLife:
    """생애 기록: 출생, 장별 요약, 관계 처음 → 끝(그 인물이 플레이어를 보는 마음), 마지막 구간."""
    p, info = _play(name)
    me = next((c for c in p.characters if c.id == info.player), None)
    b = info.birth
    a = archetypes.BY_ID.get(b.archetype) if b else None
    wd = archetypes.WOUND_BY_ID.get(b.wound) if b else None
    sp = archetypes.SPEECH_BY_ID.get(b.speech) if b else None
    snap = p.snapshot(info.world_ep)
    rels = []
    for c in p.characters:
        tie = dynamics.find_tie(p.ties, c.id, info.player) if c.id != info.player else None
        if tie is None:
            continue
        first = dynamics.find_tie(snap.ties, c.id, info.player) if snap else None
        rels.append(PlayRelChange(id=c.id, name=c.name, before=dynamics.warmth_word(first.warmth) if first else "",
                                  after=dynamics.warmth_word(tie.warmth), trust=dynamics.trust_word(tie.trust)))
    t = play.last_turn(info)
    e = p.episode(t.number) if t else None
    last_text = (_scene_of(p, t, e) or "\n".join(x.text for x in t.beats)) if t else ""
    w = store.load(info.world) if store.exists(info.world) else None
    return PlayLife(
        name=name, title=info.title or f"{me.name if me else info.player}의 삶", world=info.world,
        world_title=w.meta.title if w else info.world, player=me.name if me else info.player, gender=me.gender if me else "",
        age=me.age if me else "", place=b.place if b else "", origin=info.origin, seed=info.seed, ending=info.ending,
        days=_play_days(p, info), decisions=sum(x.kind in play.DECIDED for x in info.turns),
        free=sum(x.kind == "free" for x in info.turns), turns=len(info.turns), archetype=a.name if a else "",
        wound=wd.name if wd else "", speech=sp.name if sp else "", twist=b.twist if b else "", background=me.background if me else "",
        chapters=_play_chapters(p, info), relations=rels,
        last_when=timeline.when(p, e.time) if e is not None and timeline.known(e.time) else "", last_text=last_text)


# ---------- 작업지시서 ----------

class BriefText(BaseModel):
    text: str


@app.get("/api/projects/{name}/episodes/{n}/brief")
def brief(name: str, n: int, kind: str = "episode") -> BriefText:
    p = _load(name)
    if kind == "state":
        if not p.episode(n).text:
            raise ValueError(f"{n}화 본문이 없어 상태 정리 지시서를 만들 수 없어요")
        return {"text": prompts.state_brief(p, n)}
    if kind == "check":
        if not p.episode(n).text:
            raise ValueError(f"{n}화 본문이 없어 검수 지시서를 만들 수 없어요")
        return {"text": prompts.check_brief(p, n)}
    return {"text": prompts.episode_brief(p, n)}


# ---------- 연구 (모델 실험, 작품 데이터와 분리) ----------

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


class UsageTotal(UsageBucket):
    wasted: float = Field(0.0, description="실패 · 재시도 호출의 비용")


class UsageGroup(UsageBucket):
    """날짜 · 작품 · 화 · 단계 · 모델 · 부른 곳별 줄. 그 묶음의 열쇠 칸만 값이 있다."""
    day: str | None = None
    project: str | None = None
    episode: int | None = None
    stage: str | None = None
    backend: str | None = None
    model: str | None = None
    source: str | None = None


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


@app.get("/api/usage")
def usage_summary(days: int = 30, project: str | None = None, limit: int = 60) -> UsageSummary:
    """AI 호출 기록을 기간과 작품으로 걸러 모은다. days 가 0 이면 전체. limit 은 최근 호출 목록의 길이 (1~1000)."""
    return usage.summary(days or None, project or None, max(1, min(limit, 1000)))


@app.get("/api/usage/prices")
def usage_prices() -> PriceTable:
    return usage.price_table()


class PricesIn(BaseModel):
    rows: list[usage.Price]


@app.put("/api/usage/prices")
def put_usage_prices(body: PricesIn) -> PriceTable:
    usage.save_prices(body.rows)
    return usage.price_table()


@app.delete("/api/usage/prices")
def reset_usage_prices() -> PriceTable:
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
    return {"log": research.history(name), "stages": research.STAGES, "check_modes": research.TRIAL_MODES,
            "check_totals": research.check_totals(name)}


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


class CheckTrialIn(BaseModel):
    backend: research.Backend
    episode: int
    plants: int = 3
    modes: list[str] = []
    judge: research.Backend | None = None  # 주면 두 걸음 검수(판단기)도 시험한다
    scene: bool = False  # 켜면 장면 상태표 검수도 시험한다


@app.post("/api/projects/{name}/research/check")
def research_check(name: str, body: CheckTrialIn) -> dict:
    """검수 시험: n화에 모순을 심고 검수 방식마다 찾는지 본다. 작품에는 저장하지 않는다."""
    if not 1 <= body.plants <= 5:
        raise ValueError("심을 모순은 1~5개예요")
    res = research.check_trial(_load(name), body.episode, body.backend, body.plants, body.modes or None, judge=body.judge, scene=body.scene)
    return research.record(name, "check", res)


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

NO_CACHE = {"Cache-Control": "no-cache"}  # 쓰기 전에 매번 ETag 로 새 판인지 묻는다 (안 바뀌었으면 304)


class _Static(StaticFiles):
    """화면 파일. 서버를 업데이트한 뒤에도 브라우저가 캐시의 옛 화면 코드를 쓰지 않게 한다."""

    def file_response(self, *args, **kwargs) -> Response:
        r = super().file_response(*args, **kwargs)
        r.headers.update(NO_CACHE)
        return r


app.mount("/static", _Static(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers=NO_CACHE)


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
            print(f"[업데이트] {r.message}. 진행 중인 작업이 끝나면 다시 시작해요")
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
        print(f"[자동 집필] {name} 을(를) 이어 가요")
    server.run()
    if restart.is_set():
        updater.restart(no_browser=True)
