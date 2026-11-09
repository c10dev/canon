"""웹 UI 서버. `python -m canon serve` 로 실행한다.

CLI 와 같은 store / pipeline / prompts 를 그대로 쓰고, 화면은 canon/static/ 의 정적 파일이다.
AI 가 만든 제안(설정, 문체, 구조, 상태 변경안)은 바로 저장하지 않고 돌려주며,
사용자가 화면에서 고르거나 고친 뒤 저장 요청을 보낼 때 반영한다.
"""
from __future__ import annotations

import contextvars
import functools
import hashlib
import ipaddress
import json
import logging
import os
import random
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Literal, NamedTuple, NoReturn
from urllib.parse import quote, unquote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.routing import APIRoute, request_response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import address, agent, archetypes, autorun, board, cancel, cast, charlog, dynamics, elements, genres, illust, jobs, knows, library, metrics, naming, pipeline, prompts, publish, refs, research, settings, store, usage
from .llm import BadKey, GeminiLLM, LocalLLM, MissingKey, explain_error, get_llm, make_llm
from . import claude  # Claude 백엔드 (구독 로그인 상태, 모델 목록)
from .schema import (Ability, ArcPlan, BodySuggestion, StatInitSuggestion, StatSkin, StatWindowSuggestion, Character, WorldSetting, ArcProposal, EpisodePlot, LookSuggestion, VoiceSuggestion, Meta, Project, RewriteRequest, Selection, SerialConversion, SerialRebuild, SeriesPlan, SetupSuggestion, StateDelta,
                     StorylineProposal, StyleEntry, StyleProfile)
from . import abilities, anchor, atlas, findings, foreshadows, heatplan, setupchat, stattrial, statwin, timeline
from .schema import AgentSession, ChatScope, HeatArcProposal, KnowsFoldSet, Deadline, Storyboard, StoryTime, Foreshadow, StatValue
from .metrics import StyleMetrics
from .schema import CharacterState, ConsistencyReport, FindingStatus, Severity, StoryEvent
from .schema import FieldIdeas, NameOption, Recap, StateDeltaAI, to_delta
from . import branches
from .schema import BranchDiff, BranchInfo, Episode, ForkMode, Snapshot
from . import play
from . import cue
from .schema import CueSheetDraft
from . import stage, tofix
from .schema import PlayInfo, StageProposal, StageRoom, StageScene
from .logline import josa

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
    saved_tok = store.saved.set({})
    try:
        with usage.scope(**_usage_scope(request.url.path)):
            response = await call_next(request)
        # 이 요청이 주소의 작품을 저장했으면 그 판을 붙인다. 응답이 작품 전체면 화면이 이 판으로 보관한다 (api 의 projectCache)
        m = _PROJECT_PATH.match(request.url.path)
        got = store.saved.get()
        if m and response.status_code == 200 and unquote(m[1]) in got:
            name = unquote(m[1])
            response.headers["X-Project-ETag"] = got[name]
            # 응답이 작품 전체면 화면이 이 판으로 보관하고, 한 화 작업이 끝날 때 화만 받는다 (app.js touchedEpisodes)
            rest = await run_in_threadpool(_saved_rest, name, got[name])
            if rest:
                response.headers["X-Project-Rest"] = rest
        return response
    finally:
        store.saved.reset(saved_tok)
        store.writer.reset(tok)
        _active -= 1


_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _split_host(value: str) -> str:
    """Host 헤더 값(이름[:포트], [IPv6][:포트])에서 포트를 떼고 소문자 이름만 돌려준다."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else value[1:]
    if value.count(":") == 1:
        value = value.split(":", 1)[0]
    return value.rstrip(".")


@functools.lru_cache(maxsize=1)
def _machine_names() -> frozenset[str]:
    try:
        name = socket.gethostname().lower().rstrip(".")
    except OSError:
        return frozenset()
    short = name.split(".", 1)[0]
    return frozenset(n for n in (name, short, f"{short}.local") if n)


def _host_allowed(host: str) -> bool:
    """DNS 리바인딩은 공격자의 도메인 이름으로 들어온다. 그래서 IP 주소 · localhost · Tailscale(*.ts.net) ·
    이 컴퓨터 이름 · CANON_ALLOWED_HOSTS(쉼표로 나눔) 의 이름만 받는다."""
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".ts.net"):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if host in _machine_names():
        return True
    extra = {_split_host(h) for h in os.environ.get("CANON_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return host in extra


def _origin_ok(request: Request) -> bool:
    """쓰기 요청에 Origin 이 있으면 그 이름이 요청의 Host(프록시 뒤면 X-Forwarded-Host)와 같아야 한다.
    Origin 이 없는 요청(명령줄, curl, 시험)은 받는다. 포트는 프록시가 바꿀 수 있어 보지 않는다."""
    origin = request.headers.get("origin")
    if origin is None or request.method not in _UNSAFE_METHODS:
        return True
    name = (urlsplit(origin).hostname or "").lower().rstrip(".")
    if not name:  # "null"(샌드박스 iframe, file://) 같은 값
        return False
    same = {_split_host(request.headers.get("host", ""))}
    same.update(_split_host(h) for h in request.headers.get("x-forwarded-host", "").split(",") if h.strip())
    return name in same


@app.middleware("http")
async def _guard_host(request: Request, call_next):
    # 맨 바깥 미들웨어(마지막에 붙임). 로그인이 없으니 DNS 리바인딩과 다른 사이트의 쓰기 요청(CSRF)을 여기서 막는다
    host = _split_host(request.headers.get("host", ""))
    if not _host_allowed(host):
        return JSONResponse({"detail": f"허용하지 않은 주소({host or '빈 Host'})로 들어온 요청이에요. "
                                       "이 이름으로 열려면 CANON_ALLOWED_HOSTS 에 더해 주세요"}, status_code=403)
    if not _origin_ok(request):
        return JSONResponse({"detail": "다른 사이트에서 보낸 쓰기 요청은 받지 않아요"}, status_code=403)
    return await call_next(request)


@app.exception_handler(ValueError)
@app.exception_handler(KeyError)
async def _bad_request(_: Request, e: Exception) -> JSONResponse:
    msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
    return JSONResponse({"detail": str(msg)}, status_code=400)


@app.exception_handler(settings.ConfigBroken)
async def _config_broken(_: Request, e: Exception) -> JSONResponse:
    # 깨진 설정 파일 위에 덮어쓰지 않았다. 화면은 설정 맨 위 안내의 '기본값으로 새로 시작'으로 풀게 한다
    return JSONResponse({"detail": str(e), "code": "config_broken"}, status_code=409)


@app.exception_handler(BadKey)
async def _bad_key(_: Request, e: BadKey) -> JSONResponse:
    # 키가 틀리거나 만료됐다: 영어 원문 대신 설정으로 가는 안내 (화면 showError 가 설정을 열지 묻는다)
    return JSONResponse({"detail": str(e), "code": "bad_key"}, status_code=400)


@app.exception_handler(MissingKey)
async def _no_key(_: Request, e: MissingKey) -> JSONResponse:
    # 첫 실행에 흔한 상황이라 서버 오류가 아니라 설정 안내로 보인다
    # 백엔드마다 없는 키가 다르다(Gemini · Vertex · Anthropic). 문구는 낸 곳의 것을 쓴다
    return JSONResponse({"detail": str(e) or "API 키가 없어요. 설정의 AI 연결에서 넣으세요", "code": "no_key"}, status_code=400)


@app.exception_handler(Exception)
async def _server_error(_: Request, e: Exception) -> JSONResponse:
    # 응답 실패 등은 원인과 할 일로 바꿔 보여 준다 (llm.explain_error). 예외 이름과 자세한 내용은 서버 로그에만 남긴다
    logging.getLogger("canon").exception("요청 처리 중 오류")
    return JSONResponse({"detail": explain_error(e) if str(e) else "서버에서 오류가 났어요. 서버 로그를 확인하세요"}, status_code=500)


def _need(name: str) -> None:
    """작품이 있는지만 본다. 없으면 404."""
    if not NAME_RE.match(name) or not store.exists(name):
        raise HTTPException(404, f"작품을 찾을 수 없어요: {name}. 작품 목록에서 다시 골라 주세요")


def _load(name: str) -> Project:
    _need(name)
    return store.load(name)


def _view(name: str) -> Project:
    """읽기만 하는 엔드포인트용 _load. 같은 판이면 전에 검증한 것을 함께 쓰므로 돌려받은 작품을 고치지 않는다 (store.load_view)."""
    _need(name)
    return store.load_view(name)


def _save(name: str, p: Project, merged: set[str] | None = None, kept: list[dict] | None = None) -> Project:
    """저장한다. 화면이 보낸 작품 전체를 저장할 때(merged 를 넘길 때)는 백그라운드 작업이 맡은 화를
    디스크에 있는 내용(작업 결과)으로 지킨다. 다른 엔드포인트는 방금 읽은 디스크 내용을 고쳐 저장하므로 그대로 쓴다.
    kept 를 넘기면 화면 값 대신 디스크 것으로 둔 칸을 담는다 (autorun.protected 와 같은 모양)."""
    with jobs.project_lock(name):
        return _save_locked(name, p, merged, kept)


def _save_locked(name: str, p: Project, merged: set[str] | None = None, kept: list[dict] | None = None) -> Project:
    """_save 의 몸통. 부르는 쪽이 jobs.project_lock(name) 을 이미 잡았을 때 쓴다 (잠금은 재진입하지 않는다)."""
    kept = kept if kept is not None else []
    owned = jobs.owned_episodes(name, merged) if merged is not None else set()
    disk = store.load(name) if merged is not None and store.exists(name) else None  # 잠근 뒤 한 번만 읽는다
    if owned and disk:
        have = {e.plot.number: e for e in disk.episodes}
        mine = {e.plot.number: e for e in p.episodes}
        for n in owned:
            if n in have:
                if n in mine and mine[n].plot != have[n].plot:
                    kept.append({"field": "plot", "ep": n})
                mine[n] = have[n]
        p.episodes = [mine[k] for k in sorted(mine)]
    if disk:
        # 스냅샷은 화면이 고치지 않고, 작품 응답은 화 번호만 보낸다 (_SNAPSHOT_LIGHT)
        p.snapshots = disk.snapshots
        # 자동 집필이 반영한 진행을 오래된 화면이 덮지 않게
        kept += [k for k in autorun.protected(name, disk, p) if k not in kept]
        # 본문이 있는 화의 플롯은 화면이 막아도 서버에서 한 번 더 지킨다 (줄기 표시만 받는다)
        kept += [{"field": "plot", "ep": n, "why": "locked"} for n in pipeline.keep_locked_plots(disk, p)]
        # 본문이 있던 화가 빠지거나 본문이 빈 글이 되는 저장은 화면 버그로 본다. 화 지우기는 전용 라우트가 있어 force 로도 풀지 않는다
        kept += _keep_texts(disk, p)
        # 화면이 열린 동안 플롯 작업이 더한 새 인물 후보도 지킨다. 안 쓰이거나 등록된 후보는 sync 가 지운다
        have = {c.id for c in p.cast_candidates}
        p.cast_candidates += [c for c in disk.cast_candidates if c.id not in have]
        have = {x.name for x in p.place_candidates}
        p.place_candidates += [x for x in disk.place_candidates if x.name not in have]
        pipeline.sync_candidates(p)
        _keep_job_fields(disk, p)
        p.rooms = disk.rooms
    store.save(name, p)
    return p


def _keep_texts(disk: Project, p: Project) -> list[dict]:
    """디스크에서 본문이 있는 화를 화면 저장이 빼거나 본문을 비우면 디스크 화를 통째로 되돌린다.
    본문만 되돌리면 화면이 보낸 옛 상태(confirmed 등)가 남아 본문이 있는데 안 쓴 화로 보이므로 상태 · 플롯도 디스크 것을 둔다.
    빠진 화는 {"field": "episode", "ep": n} 를, 비운 본문은 {"field": "text", "ep": n} 를 돌려준다. 총 화수 밖의 화는 "why": "over_target" 을 붙인다.
    빠지거나 비운 화의 디스크 본문이 화면이 보낸 다른 화의 본문과 같으면 화 번호가 밀린 옛 사본(화 끼워 넣기 · 화 지우기 뒤)이라 되돌리지 않는다.
    화 지우기 · 본문 비우기는 전용 라우트(remove_episode · delete_episode)가 한다."""
    mine = {e.plot.number: e for e in p.episodes}
    kept: list[dict] = []
    for d in disk.episodes:
        if not d.text:
            continue
        n = d.plot.number
        if any(e.text == d.text for e in p.episodes if e.plot.number != n):  # 같은 본문이 화면의 다른 화에 있다: 번호가 밀린 사본
            continue
        if n not in mine:
            mine[n] = _restored(d, None, disk, p)
            kept.append({"field": "episode", "ep": n})
        elif not mine[n].text:
            mine[n] = _restored(d, mine[n], disk, p)
            kept.append({"field": "text", "ep": n})
        else:
            continue
        if n > p.meta.target_episodes:
            kept[-1]["why"] = "over_target"
    if kept:
        p.episodes = [mine[k] for k in sorted(mine)]
    return kept


def _restored(d: Episode, e: Episode | None, disk: Project, p: Project) -> Episode:
    """_keep_texts 가 되돌릴 디스크 화 사본. 줄기 표시(LOCKED_FREE)는 화면 것을 받고(pipeline.keep_locked_plots 와 같다),
    이번 저장이 지운 인물과 없는 줄기는 플롯에서 뺀다. 되돌림은 검사(validate_storylines) 뒤에 오므로 여기서 맞춘다."""
    keep = d.model_copy(deep=True)
    if e is not None:
        keep.plot = keep.plot.model_copy(update={k: getattr(e.plot, k) for k in pipeline.LOCKED_FREE})
    gone = {c.id for c in disk.characters} - {c.id for c in p.characters}
    keep.plot.characters = [c for c in keep.plot.characters if c not in gone]
    if keep.plot.pov in gone:
        keep.plot.pov = ""
    lines = {s.id for s in p.storylines}
    if keep.plot.storyline not in lines:
        keep.plot.storyline = ""
    keep.plot.threads = [t for t in keep.plot.threads if t in lines]
    return keep


# 화의 칸 중 작업 · 전용 엔드포인트만 쓰고 화면의 작품 저장(PUT · PATCH)은 바꾸지 않는 칸.
# 화면이 작업 전에 읽은 화를 통째로 보내도 이 칸은 디스크 값을 둔다. 작업이 화에 새 칸을 쓰면 여기에 더한다
JOB_EP_FIELDS = (
    "checked_at",  # 검수 작업 (pipeline.apply_check)
    "findings",  # 검수 · 고침안 작업, 지적 라우트
    "hook",  # 흡입력 판정 작업
    "issues",  # 검수 작업
    "realign",  # 플롯 작업이 쓰고 clear_realign 만 지운다
    "rounds",  # 검수 작업
    "stage",  # 장면 연출 라우트 (stage.py)
    "to_fix",  # 고칠 곳 라우트. 자동 집필 중에 단 표시를 옛 목록이 덮지 않게
)


def _keep_job_fields(disk: Project, p: Project) -> None:
    """화면이 보낸 화 중 디스크에도 있는 화는 JOB_EP_FIELDS 칸을 디스크 값으로 둔다. 화면에만 있는 새 화는 그대로 둔다."""
    have = {e.plot.number: e for e in disk.episodes}
    for e in p.episodes:
        d = have.get(e.plot.number)
        if d is not None:
            for f in JOB_EP_FIELDS:
                setattr(e, f, getattr(d, f))


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
    effort: str = ""  # 추론 강도(그 백엔드가 받는 값). Claude · Gemini 단계가 아니거나 정하지 않았으면 "" (모델 기본값)
    effort_source: str = "default"
    effort_env: str = ""


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
    claude_config_dir: str = Field("", description="Canon 전용 Claude Code 설정 폴더. 비우면 평소 Claude Code 로그인을 같이 쓴다")
    claude_config_dir_source: str = Field("default", description="env(CANON_CLAUDE_CONFIG_DIR) | file(claude_separate) | default")
    anthropic_key_hint: str
    anthropic_key_source: str
    stages: dict[str, StageConfig]
    stage_settings: dict[str, str]  # 설정 파일에 적은 단계별 백엔드
    stage_model_settings: dict[str, str]
    stage_effort_settings: dict[str, str] = {}
    efforts: list[str] = []  # Claude 단계에서 고르는 추론 강도
    gemini_efforts: list[str] = []  # Gemini 단계에서 고르는 추론 강도 (thinking_level)
    stage_presets: list[StagePreset] = []
    local_sampling: dict[str, float] = {}  # 로컬 본문 생성 샘플링 (설정 파일 local_sampling 이 기본값을 덮는다). 화면은 읽기만
    path: str  # 설정 파일 경로
    config_broken: bool = Field(False, description="설정 파일이 깨져 있어 기본값으로 읽고 저장은 막았다 (POST /api/config/reset 으로 새로 시작)")
    config_unreadable: bool = Field(False, description="설정 파일을 권한 · 입출력 오류로 읽지 못했다 (config_broken 도 참). 새로 시작(POST /api/config/reset)은 400 으로 거절한다")
    config_backup: str = Field("", description="깨진 설정 파일의 보관본 경로 (config.json.corrupt-<시각>). 못 남겼거나 깨지지 않았으면 \"\"")


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
    claude_api: bool | None = Field(None, description="claude-api 단계가 있으면 Anthropic API 키가 있는지. 쓰지 않으면 null")
    claude: str | None = Field(None, description="claude(구독) 단계가 있으면 claude.status 의 reason (ok | login | metered | install | error). 쓰지 않으면 null")
    claude_message: str = ""


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
    separate: bool = Field(False, description="Canon 전용 Claude Code 설정 폴더로 로그인한다 (settings.claude_config_dir)")
    config_dir: str = ""
    login_running: bool = Field(False, description="'로그인 시작'으로 띄운 claude auth login 이 아직 기다리는 중")


class ClaudeLoginResult(_Out):
    """POST /api/claude/login · logout 결과. ok 는 띄웠거나(login) 끝냈는지(logout)."""
    ok: bool
    message: str


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
    stage_efforts: dict[str, str] | None = None  # {"check": "high"}, 추론 강도(Claude · Gemini). 빈 값이면 모델 기본값
    claude_model: str | None = None
    claude_bin: str | None = None
    anthropic_api_key: str | None = None  # Claude Console API 키. 구독 로그인은 Claude Code 가 따로 관리
    clear_anthropic_key: bool = False
    claude_separate: bool | None = None  # Canon 전용 Claude Code 설정 폴더로 따로 로그인 (claude.py)
    gemini_auth: str | None = None  # key | vertex
    vertex_credentials: str | None = None  # 서비스 계정 JSON 키 파일 경로 (내용이 아니라 경로)
    vertex_project: str | None = None
    vertex_location: str | None = None


@app.put("/api/config")
def put_config(body: SettingsIn) -> ConfigView:
    global _claude_seen
    _claude_seen = None  # claude 실행 파일 · 백엔드가 바뀌었을 수 있다. 상태 확인이 다시 읽게 한다
    choices = settings.PROVIDERS
    if body.provider is not None and body.provider not in choices:
        raise HTTPException(400, f"provider는 {' / '.join(choices)} 중 하나예요")
    for step, value in (body.stages or {}).items():
        if step not in settings.STAGES or (value and value not in choices):
            raise HTTPException(400, f"단계 설정이 잘못됐어요: {step}={value}")
    for step in body.stage_models or {}:
        if step not in settings.STAGES:
            raise HTTPException(400, f"알 수 없는 단계예요: {step}")
    for step, value in (body.stage_efforts or {}).items():
        if step not in settings.STAGES or (value and value.strip().lower() not in settings.EFFORTS):
            raise HTTPException(400, f"추론 강도는 {' / '.join(settings.EFFORTS)} 중 하나예요: {step}={value}")
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
                    vertex_location=body.vertex_location, stage_efforts=body.stage_efforts,
                    claude_separate=body.claude_separate)
    return settings.public()


@app.post("/api/config/reset")
def reset_config() -> ConfigView:
    """깨진 설정 파일을 빈 설정으로 새로 시작한다. 보관본(config.json.corrupt-<시각>)은 그대로 둔다. 깨지지 않았으면 400."""
    settings.reset_broken()
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
    except settings.ConfigBroken:
        raise  # 409 (_config_broken)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return settings.public()


@app.delete("/api/config/presets/{preset_id}")
def delete_stage_preset(preset_id: str) -> ConfigView:
    try:
        settings.delete_preset(preset_id)
    except settings.ConfigBroken:
        raise  # 409 (_config_broken)
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
            raise HTTPException(400, f"{prov} {model or ''} 연결을 확인하지 못했어요: {getattr(e, 'message', None) or e}. API 키와 모델 이름을 확인해 주세요")
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
    if "claude-api" in provs:
        out["claude_api"] = bool(settings.anthropic_key()[0])
    if "claude" in provs:  # 첫 작업이 실패하기 전에 설치 · 로그인을 알린다. claude 를 띄우는 확인이라 잠시 기억해 둔다
        st = _claude_status_cached()
        out["claude"], out["claude_message"] = st["reason"], st["message"]
    return out


_claude_seen: tuple[float, dict] | None = None
CLAUDE_STATUS_TTL = 60  # 초. 화면을 옮길 때마다 claude 를 다시 띄우지 않는다


def _claude_status_cached() -> dict:
    """claude.status 를 잠시 기억한다. 설정을 바꾸면(put_config) 지우고, 상태를 못 읽은 결과(error)는 기억하지 않는다."""
    global _claude_seen
    now = time.time()
    if _claude_seen is None or now - _claude_seen[0] > CLAUDE_STATUS_TTL:
        st = claude.status()
        _claude_seen = (now, st) if st.get("reason") != "error" else None
        return st
    return _claude_seen[1]


class UpdateCheck(_Out):
    """POST /api/update/check 결과. started 는 자동 업데이트가 돌고 있어 바로 확인을 시작했는지."""
    started: bool
    message: str


@app.post("/api/update/check")
def update_check() -> UpdateCheck:
    """main 에 새 커밋이 들어왔다는 알림. 확인 간격을 기다리지 않고 바로 origin/main 을 확인하게 깨운다.
    코드는 origin/main 에서만 받으므로 누가 불러도 확인을 앞당길 뿐이다."""
    from . import updater

    if not updater.watching:
        return UpdateCheck(started=False, message="자동 업데이트가 꺼져 있어요 (--no-update)")
    updater.wake.set()
    return UpdateCheck(started=True, message="새 코드를 확인할게요")


@app.get("/api/claude/status")
def claude_status() -> ClaudeStatus:
    """Claude Code 설치와 구독 로그인 상태. 로그인은 Claude Code 가 하고 Canon 은 상태만 본다 (claude.py).
    새로 읽은 상태로 상태 확인(config_health)의 기억도 바꾼다 (로그인한 뒤 '확인'을 누르면 경고가 바로 사라지게)."""
    global _claude_seen
    st = claude.status()
    _claude_seen = (time.time(), st) if st.get("reason") != "error" else None
    return st


def _same_machine(request: Request) -> bool:
    """Canon 을 실행하는 컴퓨터의 브라우저에서 온 요청인지. 프록시를 거친 요청(X-Forwarded-For)은 아니라고 본다."""
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost") and not request.headers.get("x-forwarded-for")


@app.post("/api/claude/login")
def claude_login(request: Request) -> ClaudeLoginResult:
    """Claude Code 의 로그인(`claude auth login`)을 띄운다. 로그인 화면은 Canon 을 실행하는 컴퓨터의 브라우저에
    열리므로 그 컴퓨터에서 접속했을 때만 받는다. Canon 은 계정 정보 · 코드 · 토큰을 받지 않는다 (claude.start_login)."""
    global _claude_seen
    if not _same_machine(request):
        raise HTTPException(400, "로그인 화면은 Canon을 실행하는 컴퓨터에서 열려요. 그 컴퓨터의 터미널에서 "
                                 f"`{claude.login_command()}` 을 실행하거나 `claude setup-token` 토큰을 서버 환경 변수 "
                                 "CLAUDE_CODE_OAUTH_TOKEN에 두세요.")
    _claude_seen = None
    r = claude.start_login()
    return ClaudeLoginResult(ok=r["started"], message=r["message"])


@app.post("/api/claude/logout")
def claude_logout() -> ClaudeLoginResult:
    """Canon 전용 폴더의 Claude Code 로그인만 끝낸다. 평소 Claude Code 로그인은 건드리지 않는다."""
    global _claude_seen
    _claude_seen = None
    r = claude.logout()
    return ClaudeLoginResult(ok=r["ok"], message=r["message"])


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


class ProjectAlert(BaseModel):
    """작품 목록의 확인할 것 한 줄 (projects/<이름>/pending.json). 화면은 작품 줄의 배지와 이어 쓰기 카드에 보인다."""
    kind: Literal["fail", "result"] = Field(description="fail 멈춘 AI 작업 / result 검토를 기다리는 결과")
    job: str = Field(description="작업 종류 (check, write, state 등). 화면이 가서 볼 주소를 고른다")
    ep: int | None = None
    label: str
    error: str = ""


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
    open_checked: bool = Field(False, description="다음에 할 화가 본문을 쓴 화(written)일 때 검수가 끝났는지 (findings.check_done). 화면은 검수 대기 · 상태 승인 대기를 가른다")
    setup_ready: bool = Field(True, description="설정 도우미 필수 칸(제목 · 장르 · 한 줄 소개 · 세계 · 인물 둘 · 관계 하나)이 다 찼는지 (setup.js setupReqs 와 같은 규칙). 플롯 전 작품의 다음 할 일을 고른다")
    updated_at: str
    branch: BranchInfo | None = Field(None, description="갈래 정보. 갈래가 없는 작품이면 비움 (같은 family 끼리 묶어 보인다)")
    play: PlayCard | None = Field(None, description="플레이 정보. 플레이 사본이 아니면 비움 (화면은 세계 작품 카드 안에 묶는다)")
    alerts: list[ProjectAlert] = Field(default_factory=list, description="멈춘 작업과 검토를 기다리는 결과. 멈춘 작업이 앞")
    where: str = Field("", description="장편: 다음에 할 화가 든 부 · 아크 한 줄 (예: 2부 별의 바다 · 3아크 겨울 노선). 단편 · 기획 전은 비움")
    strip_from: int = Field(0, description="strip 의 첫 화 번호. 띠가 없으면 0")
    strip: list[str] = Field(default_factory=list, description="화 칸 띠: 화마다 상태(draft · confirmed · written · finalized, 플롯 없는 화는 none). 장편은 지금 아크, 단편은 전체(40화까지)")


@app.get("/api/projects")
def list_projects() -> list[ProjectCard]:
    """작품 카드: 형식, 다음에 할 화(open_ep · open_status, 없으면 0 · ''), 고친 시각, 갈래 정보. 최근에 고친 작품부터."""
    from datetime import datetime, timezone
    out = []
    seen: set[str] = set()
    tree = branches.infos()
    if store.ROOT.exists():
        for d in sorted(store.ROOT.iterdir()):
            f = d / "project.json"
            try:
                st = f.stat()
                key = (st.st_mtime_ns, st.st_size, st.st_ino)
                hit = _cards.get(d.name)
                if not hit or hit[0] != key:
                    q = store.peek(d.name)
                    hit = (key, *_card_base(q), _state_live(q))
                    _cards[d.name] = hit
            except (FileNotFoundError, NotADirectoryError):  # 지우는 중이거나 작품 폴더가 아니다
                continue
            seen.add(d.name)
            base, basis = hit[1], hit[2]
            mtime = st.st_mtime
            out.append({"name": d.name, **base,
                        "updated_at": datetime.fromtimestamp(mtime, timezone.utc).isoformat(), "_mtime": mtime,
                        "branch": tree.get(d.name), "play": (_play_card(basis, info) if (info := store.load_play(d.name)) else None),
                        "alerts": _card_alerts(d.name, hit[3])})
    for gone in set(_cards) - seen:
        _cards.pop(gone, None)
    out.sort(key=lambda x: -x["_mtime"])
    return [{k: v for k, v in x.items() if k != "_mtime"} for x in out]  # play.json 은 project.json 보다 자주 바뀌지만 고친 때는 작품 기준


# 작품 목록 카드의 project.json 몫 {이름: (파일 판, 칸, 플레이 카드 재료)}. 판(수정 시각 · 크기 · inode)이 같으면 다시 읽지 않는다.
# store 캐시는 작품 4개까지라 작품이 많으면 목록 요청마다 모든 작품을 다시 검증했다. play.json · pending.json · 갈래는 요청마다 읽는다
# 마지막 칸은 상태 변경안을 아직 쓸 수 있는 화(_state_live)다
_cards: dict[str, tuple[tuple[int, int, int], dict, PlayBasis, dict[int, str]]] = {}


class PlayBasis(NamedTuple):
    """플레이 카드가 쓰는 작품 몫: 인물 id → 이름, (화 번호, 작품 속 날) 목록."""
    names: dict[str, str]
    days: list[tuple[int, int]]


def _card_base(p: Project) -> tuple[dict, PlayBasis]:
    """작품 카드에서 project.json 으로만 정해지는 칸과 플레이 카드 재료."""
    done = sum(e.status == "finalized" for e in p.episodes)
    todo = next((e for e in sorted(p.episodes, key=lambda e: e.plot.number) if e.status != "finalized"), None)
    base = {"title": p.meta.title, "genre": p.meta.genre, "form": p.meta.form,
            "episodes": p.meta.target_episodes, "finalized": done, "planned": len(p.episodes),
            "open_ep": todo.plot.number if todo else 0, "open_status": todo.status if todo else "",
            "open_checked": bool(todo and todo.status == "written" and findings.check_done(todo)), "setup_ready": _setup_ready(p),
            **_card_strip(p, todo)}
    return base, _play_basis(p)


STRIP_MAX = 40  # 화 칸 띠에 그리는 가장 많은 화 (app.js WORK_STRIP_MAX 와 같다)


def _setup_ready(p: Project) -> bool:
    """설정 도우미 필수 칸이 다 찼는가. static/setup.js 의 setupReqs 와 같은 규칙 (tests/test_web.py)."""
    ids = {c.id for c in p.characters}
    return bool(p.meta.title.strip() and p.meta.genres and p.meta.logline.strip() and p.world.setting.strip()
                and sum(1 for c in p.characters if (c.name or "").strip()) >= 2
                and any(r.a != r.b and r.a in ids and r.b in ids for r in p.relationships))


def _card_alerts(name: str, live: dict[int, str]) -> list[dict]:
    """작품 목록의 확인할 것: pending.json 의 실패와 결과. 실패가 앞.
    이미 쓸 수 없게 된 상태 변경안(get_pending 이 지우는 것, _stale_state)은 작품을 열기 전에도 보이지 않는다."""
    pend = store.load_pending(name)
    stale = set(_stale_state(pend["results"], live))
    fails = [{"kind": "fail", "job": f.get("kind", ""), "ep": f.get("ep"), "label": f.get("label", ""), "error": f.get("error", "")}
             for f in pend["failures"].values()]
    results = [{"kind": "result", "job": r.get("kind", ""), "ep": r.get("ep"), "label": r.get("label", "")}
               for k, r in pend["results"].items() if k not in stale]
    return fails + results


def _card_strip(p, todo) -> dict:
    """작품 목록의 부 · 아크 줄과 화 칸 띠. 장편은 다음에 할 화(없으면 마지막 화)가 든 아크, 단편은 전체 화."""
    by_n = {e.plot.number: e.status for e in p.episodes}
    cur = todo.plot.number if todo else max(by_n, default=1)
    where, lo, hi = "", 1, p.meta.target_episodes
    if p.meta.form == "serial":
        part = next((x for x in p.parts if x.start_ep <= cur <= x.end_ep), None)
        arc = next((x for x in p.story_arcs if x.start_ep <= cur <= x.end_ep), None)
        where = " · ".join(t for t in [part and f"{part.number}부 {part.title}".strip(), arc and f"{arc.number}아크 {arc.title}".strip()] if t)
        lo, hi = (arc.start_ep, arc.end_ep) if arc else (0, -1)
    if not 0 < hi - lo + 1 <= STRIP_MAX:
        return {"where": where, "strip_from": 0, "strip": []}
    return {"where": where, "strip_from": lo, "strip": [by_n.get(n, "none") for n in range(lo, hi + 1)]}


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
    _need(name)
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
    _need(name)
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
    _need(name)
    _need(other)
    return branches.compare_saved(name, other, ep)


@app.post("/api/projects/{name}/promote")
def promote_branch(name: str) -> BranchFamily:
    """이 갈래를 본편으로 올린다. 갈래 정보만 바꾸고 폴더 이름과 작품 데이터는 그대로다."""
    _need(name)
    branches.promote_saved(name)
    return _family(name)


@app.post("/api/projects/{name}/detach")
def detach_branch(name: str) -> BranchFamily:
    """갈래를 끊어 따로 선 작품으로 만든다. 이 작품에서 갈라진 갈래는 이 작품의 부모에 다시 잇는다. 작품 데이터는 그대로다."""
    _need(name)
    fam = branches.family(branches.infos(), name)
    if name not in fam:
        raise ValueError("갈래가 없는 작품이에요")
    _relink(fam, name)
    store.drop_branch(name)
    return _family(name)


@app.post("/api/projects/{name}/rename")
def rename_project(name: str, body: NewName) -> dict:
    """작품 폴더 이름(주소)을 바꾼다. 작품 제목은 설정 도우미에서 바꾼다."""
    _need(name)
    _free(name)
    new = _new_name(body)
    store.project_dir(name).rename(store.project_dir(new))
    return {"name": new}


@app.delete("/api/projects/{name}")
def delete_project(name: str) -> dict:
    """작품을 지운다. 바로 없애지 않고 projects/.trash/<이름>-<시각> 로 옮겨 서버에서 되살릴 수 있게 한다."""
    _need(name)
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
        raise HTTPException(409, f"이미 있는 폴더 이름이에요: {name}. 폴더 이름을 바꿔 주세요")
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
    """작품 전체. 화면이 가진 판(ETag)과 같으면 304 로 본문 없이 답한다 (장편은 수 MB 라 화면 이동마다 받지 않게).
    스냅샷은 화 번호만 보낸다: 화면은 스냅샷이 있는지만 보고, 장편 작품의 절반 가까이가 스냅샷이다. 작품 저장(PUT)은 디스크 스냅샷을 지킨다."""
    path = store.project_dir(name) / "project.json"
    tag = None
    if NAME_RE.match(name) and path.exists():
        tag = store.tag(path)
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers={"ETag": tag})
    p = _view(name)
    out = p.model_dump(mode="json", exclude={"snapshots"})
    out["snapshots"] = [{"episode": s.episode} for s in p.snapshots]
    head = {"X-Project-Rest": _rest_tag(name, tag, p)}
    if tag:
        head["ETag"] = tag
    return JSONResponse(out, headers=head)


# 작품 이름 → (파일 판, 화를 뺀 나머지의 판). 저장 응답 · 작품 GET · 화 GET 이 같은 판을 한 번만 계산한다
_rests: dict[str, tuple[str, str]] = {}
_rests_lock = threading.Lock()


def _rest_tag(name: str, tag: str | None, p: Project) -> str:
    """작품에서 화(episodes)를 뺀 나머지의 판. 화만 받아 맞출 때 나머지가 화면이 가진 것과 같은지 본다 (get_episodes).
    작품 GET 이 보내는 모양(스냅샷은 화 번호만)으로 계산한다. tag 는 p 를 읽은 파일 판이다."""
    with _rests_lock:
        hit = _rests.get(name)
    if tag and hit and hit[0] == tag:
        return hit[1]
    rest = p.model_dump(mode="json", exclude={"snapshots", "episodes"})
    rest["snapshots"] = [{"episode": s.episode} for s in p.snapshots]
    body = json.dumps(rest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    out = hashlib.blake2b(body.encode("utf-8"), digest_size=12).hexdigest()
    if tag:
        with _rests_lock:
            _rests[name] = (tag, out)
    return out


def _saved_rest(name: str, tag: str) -> str:
    """저장한 요청이 남긴 판(tag)의 나머지 판. 그사이 다른 저장이 끼어 파일 판이 달라졌으면 빈 값 (화면은 작품 전체를 받는다)."""
    path = store.project_dir(name) / "project.json"
    try:
        if store.tag(path) != tag:
            return ""
        p = store.load_view(name)
        if store.tag(path) != tag:
            return ""
    except (OSError, ValueError):
        return ""
    return _rest_tag(name, tag, p)


@app.get("/api/projects/{name}/episodes")
def get_episodes(name: str, nums: str = "") -> JSONResponse:
    """고른 화만. 한 화 작업이 끝날 때 화면이 작품 전체(장편은 수 MB) 대신 받는다 (app.js mergeEpisodes).
    rest 는 화를 뺀 나머지의 판(작품 GET 의 X-Project-Rest 와 같은 값), numbers 는 모든 화 번호다. 화면은 둘 중 하나라도 다르면 작품 전체를 받는다."""
    try:
        want = sorted({int(x) for x in nums.split(",") if x.strip()})
    except ValueError:
        raise HTTPException(400, "화 번호를 쉼표로 이어 적으세요 (예: 3,4)") from None
    if not want or len(want) > 50:
        raise HTTPException(400, "화 번호를 1~50개 적으세요")
    _need(name)
    path = store.project_dir(name) / "project.json"
    tag = store.tag(path)
    p = _view(name)
    keep = set(want)
    out = {"etag": tag, "edit_rev": p.edit_rev, "saved_by": p.saved_by, "rest": _rest_tag(name, tag, p),
           "numbers": [e.plot.number for e in p.episodes],
           "episodes": [e.model_dump(mode="json") for e in p.episodes if e.plot.number in keep]}
    return JSONResponse(out, headers={"ETag": tag})


@app.put("/api/projects/{name}")
def put_project(name: str, p: Project, response: Response, merged: str = "", force: bool = False) -> Project:
    """화면에서 고친 프로젝트 전체를 저장한다. 구조(arc)가 있으면 화수와 맞는지 검사한다.
    장편은 부 구성과 아크(아크 안 기승전결 포함)가 이어지는지 검사한다.
    다른 화면(탭 · 기기)이 이 화면이 읽은 뒤에 저장했으면 덮지 않고 409 를 돌려준다. force 면 그래도 덮는다.
    디스크 읽기 · 충돌 검사 · 저장을 한 잠금 안에서 해서, 그 사이 다른 저장이나 작업이 끼어 서로 덮지 않게 한다."""
    _need(name)
    with jobs.project_lock(name):
        return _put_locked(name, p, store.load(name), response, merged, force)


def _put_locked(name: str, p: Project, disk: Project, response: Response, merged: str, force: bool) -> Project:
    """put_project 의 몸통. disk 는 jobs.project_lock(name) 을 잡은 뒤 읽은 작품이다."""
    # 장편 총 화수를 바꾸면 마지막 부 끝 화도 따라간다 (둘은 다른 화면에서 고치지만 한 번에 맞아야 저장된다)
    last = p.parts[-1] if p.serial and p.parts else None
    if last and last.end_ep == disk.meta.target_episodes != p.meta.target_episodes and p.meta.target_episodes >= last.start_ep:
        last.end_ep = p.meta.target_episodes
    me = store.writer.get()
    if me and not force and disk.edit_rev > p.edit_rev and disk.saved_by != me:
        raise HTTPException(409, "다른 탭이나 기기에서 이 작품을 먼저 저장했어요. 다시 불러와 그 변경을 보거나, 내 변경으로 덮어쓰세요")
    if p.arc and not p.serial:
        pipeline.validate_arc(ArcPlan(acts=p.arc), p.meta.target_episodes)
    if not p.serial:  # 화수를 바꿔도 열 계획이 1화부터 끝 화까지 빈틈없이 맞게 (heatplan.fit)
        p.heat, _ = heatplan.fit(p.heat, 1, p.meta.target_episodes)
        p.heat_turn, _ = heatplan.fit_turn(p.heat_turn, 1, p.meta.target_episodes)
    for a in p.story_arcs if p.serial else []:  # 장편은 아크마다 그 아크 범위로
        a.heat, _ = heatplan.fit(a.heat, a.start_ep, a.end_ep)
        a.heat_turn, _ = heatplan.fit_turn(a.heat_turn, a.start_ep, a.end_ep)
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
    _keep_impacts(disk, p)
    _keep_spots(disk, p)
    # 설정 변경 기록과 남겨 둔 제안은 화면이 직접 고치지 않는다. 디스크 것에 이번 저장이 고친 인물 설정만 작가 기록으로 더한다
    p.setting_log, p.setting_held = disk.setting_log, disk.setting_held
    p.address_forms, p.address_log, p.address_held = disk.address_forms, disk.address_log, disk.address_held  # 호칭 · 말씨는 /address 라우트만 고친다
    p.agent_sessions = disk.agent_sessions  # 대화 세션은 대화 라우트와 에이전트 작업만 고친다 (화면의 옛 사본이 덮지 않게)
    charlog.record_author(disk, p)
    archetypes.prune(p)
    kept: list[dict] = []
    out = _save_locked(name, p, merged={m for m in merged.split(",") if m}, kept=kept)
    if kept:  # 화면이 '저장했습니다' 대신 무엇을 저장하지 않았는지 알린다
        response.headers["X-Canon-Kept"] = quote(json.dumps(kept, ensure_ascii=False))
    return out


class ProjectPatch(BaseModel):
    """화면이 고친 칸만 보내는 작품 저장. fields 는 Project 의 최상위 칸 이름 → 값이다.
    episodes 안에서 고치지 않은 화는 {"$same": 화 번호} 로 보내고, 서버가 디스크의 그 화로 채운다."""
    edit_rev: int = 0
    fields: dict[str, Any] = Field(default_factory=dict)


# 화면이 고치지 않는 칸. 보내도 받지 않는다 (스냅샷은 화면이 화 번호만 가진다, 저장 기록은 서버가 정한다)
_PATCH_SKIP = {"snapshots", "edit_rev", "saved_by"}


@app.patch("/api/projects/{name}")
def patch_project(name: str, body: ProjectPatch, response: Response, merged: str = "", force: bool = False) -> Project:
    """작품 저장(PUT)과 같지만 바뀐 칸만 받는다. 보내지 않은 칸은 디스크 것을 그대로 쓰고, 그 뒤 검사와 지키기는 PUT 과 같다.
    장편은 작품이 수 MB 라 칸 하나를 고칠 때마다 통째로 올리지 않게 한다.
    보내지 않은 칸을 채울 디스크도 잠근 뒤 읽는다. 그 사이 작업이 쓴 칸을 옛 사본으로 되돌리지 않게."""
    _need(name)
    with jobs.project_lock(name):
        return _patch_locked(name, body, store.load(name), response, merged, force)


def _patch_locked(name: str, body: ProjectPatch, disk: Project, response: Response, merged: str, force: bool) -> Project:
    data = disk.model_dump(mode="json")
    for k, v in body.fields.items():
        if k not in Project.model_fields:
            raise HTTPException(400, f"작품에 없는 칸이에요: {k}")
        if k in _PATCH_SKIP:
            continue
        if k == "episodes":
            have = {e["plot"]["number"]: e for e in data["episodes"]}
            if not isinstance(v, list):
                raise HTTPException(400, "episodes는 목록이어야 해요")
            try:
                v = [have[x["$same"]] if isinstance(x, dict) and "$same" in x else x for x in v]
            except KeyError as e:
                raise HTTPException(409, f"{e.args[0]}화가 서버에 없어요. 다시 불러온 뒤 저장해 주세요") from None
        data[k] = v
    data["edit_rev"] = body.edit_rev
    try:
        p = Project.model_validate(data)
    except ValidationError as e:
        from fastapi.exceptions import RequestValidationError
        raise RequestValidationError(e.errors(include_url=False)) from None
    return _put_locked(name, p, disk, response, merged, force)


def _keep_spots(disk: Project, p: Project) -> None:
    """옛 핀의 건물 한 줄은 쓰기 · 검수 작업이 채워 디스크에 쓴다 (_fill_old_spots). 그 전에 읽은 화면이 빈 값으로 덮지 않게
    같은 자리 핀의 디스크 값을 둔다."""
    have = {(pin.place, pin.x, pin.y): pin.spot for pin in disk.atlas.pins if pin.spot}
    for pin in p.atlas.pins:
        if not pin.spot:
            pin.spot = have.get((pin.place, pin.x, pin.y), "")


def _keep_impacts(saved: Project, p: Project) -> None:
    """영향 분석은 백그라운드 작업이 디스크에 쓴다. 화면이 그 전에 읽은 작품을 저장해도 새 분석을 덮지 않게 한다."""
    disk = {el.id: el.impact for el in saved.elements if el.impact}
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
    p = _load(name)
    if len(body.text.strip()) < 200:
        raise HTTPException(400, "예시 원문은 200자 이상 넣어 주세요")
    return pipeline.analyze_style(get_llm("plan"), body.text, [c.name for c in p.characters])


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


# ---------- 2-0. 작품 정착 문체 ----------
# 작가가 고른 반영한 화를 이 작품의 문체 기준으로 고정한다 (canon/anchor.py). 작가 입력이라 바로 저장한다. LLM 호출 없음.

class AnchorMetrics(BaseModel):
    chars: int
    sentence_len: float
    dialogue_ratio: float
    past_tense_ratio: float | None = None
    distance_ready: bool = False


class AnchorInfo(BaseModel):
    episodes: list[int]
    passages: list[str] = []
    later: float | None = None
    at: str = ""
    stale: bool = False
    metrics: AnchorMetrics | None = None


class AnchorPoint(BaseModel):
    """화 하나의 정착 문체 거리 (anchor.trend). 서술 말투 화는 distance 가 없다."""
    n: int
    distance: float | None = None
    rolling: float | None = None
    voiced: bool = False
    anchor: bool = False
    auto: bool = False
    changed: bool = False


class AnchorView(BaseModel):
    """문체 화면의 정착 문체 카드 (anchor.view). band 는 사람 연재가 머문 거리 범위, warn 은 흐름 경고 기준."""
    anchor: AnchorInfo | None = None
    reference: AnchorMetrics | None = None
    usable: list[int] = []
    suggest: list[int] = []
    trend: list[AnchorPoint] = []
    window: int
    warn: float
    band: list[float]
    other: float
    min_chars: int
    per_episode_warn: float


class AnchorPick(BaseModel):
    episodes: list[int]
    passages: list[str] = []


class AnchorCandidates(BaseModel):
    passages: list[str]
    chars: int
    later: float | None = None


@app.get("/api/projects/{name}/style/anchor")
def anchor_view(name: str) -> AnchorView:
    return anchor.view(_load(name))


@app.post("/api/projects/{name}/style/anchor/candidates")
def anchor_candidates(name: str, body: AnchorPick) -> AnchorCandidates:
    """고를 화로 대표 문단 후보와 그 화의 글자 수, 뒤 화가 떨어진 거리를 미리 본다. 저장하지 않는다."""
    p = _load(name)
    a = anchor.measure(p, body.episodes)
    return {"passages": anchor.candidates(p, body.episodes), "chars": a.metrics.chars if a.metrics else 0, "later": a.later}


@app.put("/api/projects/{name}/style/anchor")
def anchor_save(name: str, body: AnchorPick) -> Project:
    """정착 문체를 고른 화와 대표 문단으로 잰다 (다시 재기도 같다)."""
    p = _load(name)
    anchor.set_anchor(p, body.episodes, body.passages)
    return _save(name, p)


@app.delete("/api/projects/{name}/style/anchor")
def anchor_drop(name: str) -> Project:
    p = _load(name)
    anchor.clear(p)
    return _save(name, p)


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
    ref: str = ""  # 레퍼런스 원고에서 원문을 가져왔으면 그 원고 id (만든 것에 남긴다)
    ref_eps: str = ""  # 가져온 화 범위 이름 ('1~10화')


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


LIB_JOBS = ".styles"  # 문체 라이브러리 분석 작업의 project 자리 (작품 폴더는 점으로 시작하지 않아 겹치지 않는다)


class LibAnalyzeIn(BaseModel):
    text: str
    lib: str = ""  # 결과를 놓을 라이브러리 항목 id. 새 항목은 비운다 (화면이 'new' 로 받는다)


@app.post("/api/styles/analyze/job")
def analyze_library_style_job(body: LibAnalyzeIn) -> dict:
    """문체 라이브러리 분석을 화면을 막지 않는 작업(lib_style)으로 돌린다. 결과(profile, lib)는 화면이 그 항목에 제안으로 놓는다."""
    if len(body.text.strip()) < 200:
        raise HTTPException(400, "예시 원문은 200자 이상 넣어 주세요")
    llm, text, lib = get_llm("plan"), body.text, body.lib or "new"

    def fn(job: jobs.Job):
        return {"profile": pipeline.analyze_style(llm, text).model_dump(), "lib": lib}
    try:
        with usage.scope(project="", episode=None, task="lib_style"):
            job = jobs.start(LIB_JOBS, "lib_style", None, "문체 분석 (라이브러리)", fn)
    except jobs.Busy as b:
        return {**b.job.public(), "already": True}
    return job.public()


@app.post("/api/styles")
def create_style(body: StyleIn) -> StyleEntry:
    e = library.create(body.name, body.profile, body.sample, body.source, body.notes)
    if body.ref and refs.exists(body.ref):
        refs.made(body.ref, "style", e.id, body.ref_eps)
    return e


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
def apply_arc(name: str, prop: HeatArcProposal) -> Project:
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


@app.post("/api/projects/{name}/knows-fold/{number}")
def apply_knows_fold(name: str, number: int, body: KnowsFoldSet) -> Project:
    """아크 요약 뒤 아는 정보 접기 제안(작업 fold_knows) 가운데 작가가 고르고 고친 인물만 적용한다 (knows.apply_fold)."""
    p = _load(name)
    _not_auto(name)
    if not knows.apply_fold(p, number, body):
        raise ValueError("적용할 접기가 없어요. 인물을 고르거나 줄을 적으세요")
    return _save(name, p)


@app.delete("/api/projects/{name}/knows-fold/{number}")
def undo_knows_fold(name: str, number: int) -> Project:
    """아크 number 에서 접은 아는 정보를 되돌린다 (knows.undo_fold)."""
    p = _load(name)
    _not_auto(name)
    knows.undo_fold(p, number)
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


def _renumber_ready(name: str, first: int = 0) -> None:
    """번호를 옮기기 전에: 자동 집필 · 돌고 있는 AI 작업, first 화부터 검토를 기다리는 결과 · 실패한 작업이 있으면 막는다."""
    autorun.check_renumber(name)
    busy = [j.label for j in jobs.listing(name) if j.status == "running"]
    if busy:
        raise ValueError(f"AI 작업({', '.join(busy)})이 끝난 뒤에 하세요. 화 번호가 바뀌면 작업 결과가 엉뚱한 화에 들어가요")
    if first:
        held = store.pending_eps(name, first)
        if held:
            raise ValueError(f"{', '.join(f'{n}화' for n in held)}에 검토를 기다리는 AI 결과나 실패한 작업이 있어요. "
                             "먼저 확인하거나 버린 뒤에 하세요. 화 번호가 바뀌면 결과가 엉뚱한 화에 들어가요")




class Renumbered(BaseModel):
    """화를 넣거나 뺀 뒤의 작품과 무엇을 옮겼는지."""
    project: Project
    notes: list[str]


@app.post("/api/projects/{name}/episodes/insert")
def insert_episode(name: str, body: InsertIn) -> Renumbered:
    """새 화를 넣고 뒤 화를 한 칸씩 민다. 무엇을 옮겼는지(notes)를 함께 돌려준다."""
    at = body.at
    _renumber_ready(name, at)
    with jobs.project_lock(name):
        p = _load(name)
        notes = pipeline.insert_episode(p, at, body.title, body.summary, body.storyline, not store.shares_text(name))
        store.save(name, p)
        notes += store.renumber_side_files(name, lambda x: x + 1 if x >= at else x)
    autorun.renumber(name, lambda x: x + 1 if x >= at else x)
    return {"project": p, "notes": notes}


@app.delete("/api/projects/{name}/episodes/{n}")
def remove_episode(name: str, n: int) -> Renumbered:
    """아직 안 쓴 화를 빼고 뒤 화를 한 칸씩 당긴다."""
    _renumber_ready(name, n)
    with jobs.project_lock(name):
        p = _load(name)
        notes = pipeline.remove_episode(p, n, not store.shares_text(name))
        store.save(name, p)
        notes += store.renumber_side_files(name, lambda x: x - 1 if x >= n else x, [n])
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
        if not body.keep_plot:
            notes = [*notes, *store.renumber_side_files(name, lambda x: x - 1 if x >= n else x, [n])]
    if before.episode(n).status == "finalized":
        autorun.after_revert(name, n)
    if not body.keep_plot:
        autorun.renumber(name, lambda x: x - 1 if x >= n else x)
    return {"project": p, "notes": [*notes, f"지우기 전 작품은 {path.name} 으로 남겨 뒀어요. 설정 › 백업에서 되돌릴 수 있어요."]}


# ---------- 백업에서 되돌리기 ----------
# store.backup_list: 시간별 백업 · 직전 판 · 화를 지우기 전 · 장편 전환 전 · 되돌리기 전 판.

@app.get("/api/projects/{name}/backups")
def list_backups(name: str) -> list[dict]:
    _need(name)
    return store.backup_list(name)


class RestoreIn(BaseModel):
    id: str  # backup_list 의 id


@app.post("/api/projects/{name}/backups/restore")
def restore_backup(name: str, body: RestoreIn) -> Project:
    """백업으로 작품을 되돌린다. 지금 판은 먼저 backups/before-restore.<시각>.json 으로 남겨 다시 되돌릴 수 있다.
    자동 집필 · AI 작업이 도는 중이거나 검토를 기다리는 결과(pending.json)가 있으면 막는다. 반영한 화가 줄면 자동 집필 기록을 화 지우기처럼 맞춘다(autorun.after_revert)."""
    autorun.check_renumber(name)
    busy = [j.label for j in jobs.listing(name) if j.status == "running"]
    if busy:
        raise ValueError(f"AI 작업({', '.join(busy)})이 끝난 뒤에 되돌리세요. 작업 결과가 되돌린 작품을 덮어요")
    if held := store.pending_eps(name):
        raise ValueError(f"{', '.join(f'{n}화' for n in held)}에 검토를 기다리는 AI 결과나 실패한 작업이 있어요. 먼저 확인하거나 버린 뒤에 되돌리세요")
    with jobs.project_lock(name):
        before = branches.last_finalized(_load(name))
        try:
            p = store.restore_backup(name, body.id)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from None
    if branches.last_finalized(p) < before:
        autorun.after_revert(name, branches.last_finalized(p) + 1)
    return p


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
        _text_guard(name, n)  # 넣기(chat_apply)에서 막힐 요청이면 AI를 부르기 전에 막는다
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


class FixNowIn(BaseModel):
    message: str
    selection: Selection


@app.post("/api/projects/{name}/episodes/{n}/fix-now")
def fix_now(name: str, n: int, body: FixNowIn) -> dict:
    """고른 부분을 요청대로 AI가 고치고 첫 후보를 바로 본문에 넣는다 (상태 정리 경고의 'AI에게 고치기').
    대화에 남기기와 넣기를 한 잠금 안에서 한다. edit 는 넣은 수정 id, 후보가 없으면 ''."""
    _text_guard(name, n)
    p = _load(name)
    _chat(p, f"text:{n}")
    sel = Selection(start=pipeline.locate(p.episode(n).text, body.selection.text, body.selection.start), text=body.selection.text)
    rev = pipeline.revise_passage(get_llm("revise"), p, n, sel, body.message)
    _text_guard(name, n)  # AI를 기다리는 사이 자동 집필이나 본문 작업이 시작했을 수 있다
    out: dict = {}
    q = _edit(name, lambda x: out.update(edit=pipeline.apply_first(x, n, sel, body.message, rev)))
    return {"project": q, "edit": out["edit"].id if out["edit"] else ""}


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
    model: str = ""  # 상태 줄에 보일 모델 이름 (chat 단계)
    max_steps: int = agent.MAX_STEPS


def _model_label() -> str:
    try:
        m = getattr(get_llm("chat"), "model", "")
        m = m() if callable(m) else m
    except Exception:
        m = ""
    return m if isinstance(m, str) and m else settings.stage_provider("chat")[0]


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
    _need(name)
    out: list[AgentSession] = []
    _session_edit(name, lambda p: out.append(agent.new_session(p, body.topic, body.target, body.title)))
    return out[0]


def _session_edit(name: str, fn) -> None:
    """대화 세션 칸(만들기 · 이름 · 대상 · 권한 모드 · 보관)만 바꾼다. 화면 저장으로 치지 않는다(store.writer 를 비움):
    저장하지 않은 변경이 있는 탭이 세션만 고쳐도 다른 탭이 먼저 저장한 것을 덮지 않고 충돌(409)을 그대로 받게"""
    tok = store.writer.set("")
    try:
        _edit(name, fn)
    finally:
        store.writer.reset(tok)


class SessionPatch(BaseModel):
    title: str | None = None
    mode: str | None = None
    target: str | None = None
    archived: bool | None = None


@app.patch("/api/projects/{name}/sessions/{sid}")
def agent_session_update(name: str, sid: str, body: SessionPatch) -> AgentSession:
    _need(name)
    out: list[AgentSession] = []
    _session_edit(name, lambda p: out.append(agent.update_session(p, sid, **body.model_dump())))
    return out[0]


class TurnIn(BaseModel):
    message: str
    mode: Literal["", "options"] = ""  # options: 방향 여러 안으로 물어 달라 (/여러안)
    act: str = ""  # 화면에서 연 구간
    episode: int = 0  # 화면에서 연 화
    draft: ArcProposal | None = None  # 다음 아크 대상: 화면의 초안


def _run_agent(name: str, sid: str, t: int) -> dict:
    """턴을 백그라운드 작업으로 돌린다. 같은 작품의 대화 작업은 한 번에 하나다."""
    llm = get_llm("chat")  # 플롯 대화 단계 (비우면 계획 단계). 키가 없으면 여기서 바로 오류를 보여 준다
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
    _need(name)
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
    """승인 카드에 답하고 같은 턴을 이어 돌린다. 쓴 작품을 함께 돌려준다.
    화 넣기 · 빼기 카드는 화 끼워 넣기 화면과 같은 검사(_renumber_ready)를 거치고 자동 집필 기록의 화 번호도 옮긴다."""
    _need(name)
    _, turn = agent.turn_of(_load(name), sid, t)
    op = turn.approval.op if body.approve and turn.approval else None
    if op:
        _renumber_ready(name, op.at)
    with jobs.project_lock(name):  # 화 번호 바깥 파일도 같은 잠금 안에서 옮긴다 (insert_episode · remove_episode 와 같다)
        p = store.load(name)
        agent.decide(p, sid, t, body.approve, body.picked, body.remember, not store.shares_text(name))
        store.save(name, p)
        if op:
            aside: list[str] = []
            store.renumber_side_files(name, agent.shift(op), agent.dropped(op), aside)
            rec = agent.turn_of(p, sid, t)[1].writes[-1]
            if aside and rec.op:
                rec.op.aside = aside  # 되돌릴 때 removed/ 에서 다시 옮겨 온다
                store.save(name, p)
    if op:
        autorun.renumber(name, agent.shift(op))
    return {"project": p, "job": _run_agent(name, sid, t)}


@app.post("/api/projects/{name}/sessions/{sid}/turns/{t}/continue")
def agent_continue(name: str, sid: str, t: int) -> dict:
    """상한에 닿았거나 멈춘 턴을 이어 돌린다."""
    _need(name)
    _edit(name, lambda q: agent.resume(q, sid, t))
    return _run_agent(name, sid, t)


class AgentUndoIn(BaseModel):
    write: int | None = None  # 쓴 기록 번호 (비우면 턴 전체)
    key: str | None = None  # 그 기록의 한 부분 ('parts' · 'arc' · 'acts' · 'draft' · 화 번호)


@app.post("/api/projects/{name}/sessions/{sid}/turns/{t}/undo")
def agent_undo(name: str, sid: str, t: int, body: AgentUndoIn) -> dict:
    """바로 쓴 것을 되돌린다. 그 뒤에 다시 고치거나 확정한 것은 남기고 까닭을 돌려준다."""
    _need(name)
    ops = agent.undo_ops(_load(name), sid, t, body.write, body.key)
    if ops:
        _renumber_ready(name, min(op.at for op in ops))
    done: list = []
    with jobs.project_lock(name):  # 화 번호 바깥 파일도 같은 잠금 안에서 옮긴다
        p = store.load(name)
        restored, kept, reasons = agent.undo(p, sid, t, body.write, body.key, not store.shares_text(name), done)
        store.save(name, p)
        for op in done:
            store.renumber_side_files(name, agent.shift(op, inverse=True), agent.dropped(op, inverse=True))
            if op.kind == "remove":
                store.restore_side_files(name, op.aside, op.at)
    for op in done:
        autorun.renumber(name, agent.shift(op, inverse=True))
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
    kind: str  # JOB_MAKERS 의 이름 하나 (suggest, arc, plots, write, check …)
    ep: int | None = None  # 화 번호. plots 는 장편에서 아크 번호(없으면 초안이 있는 모든 아크), recap_* 는 아크·부 번호
    element: str = ""  # impact 일 때 요소 id
    note: str = ""  # arc, series, plots, nextarc, storyline, convert, rebuild: 작가가 바라는 것. board: 있으면 지금 스토리보드를 이 요청대로 AI 가 고친다
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
    conditions: list[str] = []  # stattrial: none | json | lines (비우면 셋 다). cue_run: oneshot | score | cues (비우면 셋 다)
    event: int = 0  # stage_draft, stage_extract: 플롯 사건 번호 (0부터)
    stage_room: str = ""  # stage_draft: 아직 방이 없을 때 이 틀(보통 empty)로 새 방을 만들어 초안을 받는다 (AI 가 기준점을 더하자고 한다)
    board: Literal["", "make", "none"] = ""  # write: make 면 스토리보드를 새로 만든 뒤 쓴다(바로 쓰기), none 이면 스토리보드 없이 쓴다
    cues: Literal["", "none"] = ""  # write: 큐 시트를 쓰는 작품(cue.on)인데 그 화에 없으면 만든 뒤 쓴다. none 이면 큐 시트 없이 쓴다
    text: str = ""  # style: 분석할 예시 원문 (200자 이상)


def _edit(name: str, fn) -> Project:
    """작업 결과를 최신 project.json 에 반영해 저장한다 (작업이 도는 동안 사용자가 저장했을 수 있다)."""
    with jobs.project_lock(name):
        p = store.load(name)
        fn(p)
        store.save(name, p)
    return p


def _fill_old_spots(name: str) -> None:
    """쓰기 · 검수 작업을 시작할 때: 건물 한 줄이 빈 옛 핀을 채워 저장한다 (프롬프트의 '장소가 놓인 건물' 블록).
    빈 핀이 모두 건물 밖이면 저장하지 않는다."""
    if atlas.fill_old_spots(store.load(name), _map_dir(name)):
        _edit(name, lambda q: atlas.fill_old_spots(q, _map_dir(name)))


def _plot_ranges(p: Project, arc: int | None = None) -> list[tuple[str, int, int]]:
    """초안이거나 아직 없는 화가 있는 구간만 다시 만든다. 장편은 arc 번호를 주면 그 아크만."""
    status = {e.plot.number: e.status for e in p.episodes}
    beats = p.beats()
    if p.serial and arc is not None:
        s = next((x for x in p.story_arcs if x.number == arc), None)
        if s is None:
            raise ValueError(f"아크 {arc}{josa(str(arc), '이', '가')} 없어요")
        beats = s.acts
    # 화를 함께 쓰는 구간(짧은 작품)은 한 번에 만든다 (pipeline.act_groups)
    return [(names, a, b) for names, a, b in pipeline.act_groups(beats) if any(status.get(n, "draft") == "draft" for n in range(a, b + 1))]


def _waiting_409(old: jobs.Job) -> NoReturn:
    """멈춘 작업 old 가 아직 AI 응답을 기다린다. 그 응답이 올 때까지 새 작업을 막는다."""
    mins = max(1, round((time.time() - old.started) / 60))
    raise HTTPException(409, f"앞에서 멈춘 '{old.label}'{josa(old.label, '이', '가')} 아직 AI 응답을 기다려요 ({mins}분째). "
                             "이미 보낸 호출은 끊을 수 없어요. 응답이 오거나 시간이 다 되면 다시 시작할 수 있어요")


def _keep_late_board(name: str, n: int, b: Storyboard) -> bool:
    """멈춘 스토리보드 작업의 늦은 응답 b 를 n 화에 남긴다. 그 사이 스토리보드나 본문이 생겼거나 플롯 확정을 풀었으면 버린다."""
    kept = False

    def put(q: Project) -> None:
        nonlocal kept
        e = q.episode(n)
        if e.storyboard is None and not e.text and e.status != "draft":
            pipeline.set_storyboard(q, n, b, by="ai")
            kept = True
    with cancel.ignored():
        _edit(name, put)
    return kept


# ---------- 작업 종류별 준비 (start_job 이 JOB_MAKERS 에서 찾는다) ----------
# 함수마다 (이름표, 전체 걸음, 맡은 화, 할 일 fn(job)) 을 돌려준다. 새 작업은 함수를 더하고 JOB_MAKERS 에 이름을 넣는다.

def _job_suggest(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 suggest: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    label, total, owned = "설정 제안", 1, set()

    def fn(job: jobs.Job):
        return pipeline.suggest_setup(llm, store.load(name)).model_dump()
    return label, total, owned, fn


def _job_style(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 style: 예시 원문으로 문체 프로필을 뽑고 원문 전체의 기준 지표를 잰다. 결과는 화면이 작품 문체에 넣고 작가가 저장한다."""
    if len(body.text.strip()) < 200:
        raise HTTPException(400, "예시 원문은 200자 이상 넣어 주세요")
    text, names = body.text, [c.name for c in p.characters]

    def fn(job: jobs.Job):
        prof = pipeline.analyze_style(llm, text, names)
        return {"profile": prof.model_dump(), "baseline": metrics.measure(text).model_dump()}
    return "문체 분석", 1, set(), fn


def _job_arc(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 arc: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    label, total, owned = "기승전결 구조 제안", 1, set()
    note = body.note

    def fn(job: jobs.Job):
        return pipeline.plan_arc(llm, store.load(name), note).model_dump()
    return label, total, owned, fn


def _job_series(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 series: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    label, total, owned = "부 구성 제안", 1, set()
    note = body.note

    def fn(job: jobs.Job):
        return pipeline.plan_series(llm, store.load(name), note).model_dump()
    return label, total, owned, fn


def _job_nextarc(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 nextarc: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    label, total, owned = f"{pipeline.next_arc_start(p)}화부터 다음 아크 제안", 1, set()
    note, length = body.note, body.length

    def fn(job: jobs.Job):
        return pipeline.plan_next_arc(llm, store.load(name), length, note).model_dump()
    return label, total, owned, fn


def _job_heat(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 heat: 이미 있는 기승전결 위에 열 계획만 받는다. 장편은 ep 가 아크 번호(없으면 다 쓰지 않은 첫 아크)."""
    start, end, _acts, _where, arc = pipeline.heat_target(p, n or 0)
    label = f"아크 {arc.number} 열 계획 제안" if arc else "열 계획 제안"
    note, number = body.note, arc.number if arc else 0

    def fn(job: jobs.Job):
        return pipeline.propose_heat(llm, store.load(name), number, note).model_dump() | {"arc": number}
    return label, 1, set(), fn


def _job_convert(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 convert: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    _not_auto(name)
    size, ending, note = body.length, body.ending, body.note
    pipeline.check_convertible(p, size)  # 화수가 맞지 않으면 작업을 시작하기 전에 알린다
    label, total, owned = f"장편 {size}화로 전환 계획", 1, set()

    def fn(job: jobs.Job):
        return pipeline.propose_conversion(llm, store.load(name), size, ending, note).model_dump()
    return label, total, owned, fn


def _job_rebuild(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 rebuild: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    _not_auto(name)
    size, ending, note = body.length, body.ending, body.note
    span = pipeline.check_rebuild(p, size, body.span, ending)
    label, total, owned = f"장편 {size}화로 재구성 계획", 1, set()

    def fn(job: jobs.Job):
        return pipeline.propose_rebuild(llm, store.load(name), size, span, ending, note).model_dump()
    return label, total, owned, fn


def _job_rework(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 rework: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    _not_auto(name)
    if n is None:
        raise ValueError("화 번호(ep)가 필요해요")
    x = p.archive.entry(n) if p.archive else None
    if x is None or x.use != "revise":
        raise ValueError(f"{n}화는 재구성에서 다듬기로 고른 화가 아니에요")
    label, total, owned = f"{n}화 다듬기", 1, set()

    def fn(job: jobs.Job):
        return pipeline.propose_rework(llm, store.load(name), n).model_dump()
    return label, total, owned, fn


_WRITE_CHECKS: set[tuple[str, int]] = set()  # 쓴 뒤 바로 검수하는 쓰기 작업이 도는 (작품, 화). 그동안 따로 검수를 시작하지 않는다
_WRITE_CHECKS_LOCK = threading.Lock()


def _run_check(name: str, n: int, llm) -> dict:
    """한 화를 검수해 지적 목록에 회차 하나로 합치고 작업 결과를 돌려준다 (작업 check, 쓴 뒤 바로 검수)."""
    _fill_old_spots(name)
    q0 = store.load(name)
    rep = pipeline.check_episode(llm, q0, n)
    r = _edit(name, lambda q: pipeline.apply_check(q, rep, "api", pipeline.widen_on(q0))).episode(n).rounds[-1]
    for prop in rep._stage_held:  # 작가가 손본 본문 장면은 덮지 않고 장면 연출 화면의 비교로 남긴다
        _stage_keep(name, prop)
    return {"issues": r.found, "round": r.no, "added": r.added, "stage": len(rep._stage),  # 짚은 곳: 검수 모델 + 장면 연출 규칙
            "scoped": r.scoped, "outside": r.outside}  # 다시 검수: 바뀌지 않은 문단에서 새로 나와 넣지 않은 지적 수


def _job_check(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 check: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    # 한 화 검수: 앞선 본문 전체와 설정에 어긋난 곳을 찾아 그 화에 붙인다 (집필 화면이 보여 주고 고칠 문장을 고르게 한다)
    if n is None or not p.episode(n).text:
        raise ValueError("본문이 있는 화만 검수해요")
    if (name, n) in _WRITE_CHECKS:
        raise ValueError(f"{n}화는 본문을 쓴 뒤 바로 검수하는 중이에요. 끝나면 결과가 검수 화면에 놓여요")
    label, total, owned = f"{n}화 검수", 1, set()

    def fn(job: jobs.Job):
        return _run_check(name, n, llm)
    return label, total, owned, fn


def _job_fixes(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 fixes: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    # 열린 지적마다 AI 고침안을 받아 그 지적에 남긴다. 본문은 바꾸지 않는다 (작가가 검수 화면의 '한꺼번에 검토'에서 고른 것만 넣는다)
    if n is None or not p.episode(n).text:
        raise ValueError("본문이 있는 화만 고침안을 받아요")
    pipeline._editable(p, n)
    todo = pipeline.fix_targets(p.episode(n))
    if not todo:
        raise ValueError("고침안을 받을 열린 지적이 없어요. 지적한 문장이 지금 본문에 있고 넣을 수 있는 고침안이 없는 지적만 받아요")
    label, total, owned = f"{n}화 지적 {len(todo)}개 고침안", len(todo), set()

    def fn(job: jobs.Job):
        # 지적을 FIX_BATCH 개씩 묶어 한 번에 묻는다 (같은 검수 자료를 지적마다 보내지 않는다). 답에서 빠진 지적만 따로 묻는다
        q0 = store.load(name)
        failed: list[dict] = []
        missing: list[str] = []
        why = explain_error

        def keep(fid: str, got) -> None:
            if isinstance(got, str):
                failed.append({"id": fid, "error": got})
            else:
                cancel.check()
                _edit(name, lambda q: pipeline.store_fixes(q, n, fid, got))
            job.done += 1

        groups = [todo[i:i + pipeline.FIX_BATCH] for i in range(0, len(todo), pipeline.FIX_BATCH)]
        with ThreadPoolExecutor(max_workers=min(pipeline.FIX_WORKERS, len(groups))) as pool:
            futures = {pool.submit(contextvars.copy_context().run, pipeline.propose_fixes_batch, llm, q0, n, ids): ids for ids in groups}
            for fut in as_completed(futures):
                ids = futures[fut]
                try:
                    got = fut.result()
                except cancel.Cancelled:
                    raise
                except Exception as e:  # 한 묶음이 실패하면 (거절, 시간 초과, 형식 오류) 그 묶음의 지적을 하나씩 다시 묻는다. 지적 하나뿐인 묶음은 같은 호출이라 다시 묻지 않는다
                    if len(ids) > 1:
                        missing.extend(ids)
                    else:
                        keep(ids[0], why(e))
                    continue
                for fid in ids:
                    if fid in got:
                        keep(fid, got[fid])
                    else:
                        missing.append(fid)
        if missing:
            with ThreadPoolExecutor(max_workers=min(pipeline.FIX_WORKERS, len(missing))) as pool:
                futures = {pool.submit(contextvars.copy_context().run, pipeline.propose_fixes, llm, q0, n, fid): fid for fid in missing}
                for fut in as_completed(futures):
                    fid = futures[fut]
                    try:
                        opts = fut.result()
                    except cancel.Cancelled:
                        raise
                    except Exception as e:  # 한 지적이 실패해도 나머지는 남긴다
                        keep(fid, why(e))
                    else:
                        keep(fid, opts)
        if len(failed) == len(todo):
            raise ValueError(f"고침안을 하나도 받지 못했어요: {failed[0]['error']}")
        return {"done": len(todo) - len(failed), "failed": failed}
    return label, total, owned, fn


def _job_recheck(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 recheck: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    # 고친 곳만 다시 보기: 지난 검수 뒤 수정이 모두 고침안이면 그 지적들을 한 번에 다시 본다. 회차는 늘지 않는다
    if n is None or not p.episode(n).text:
        raise ValueError("본문이 있는 화만 다시 봐요")
    pipeline._editable(p, n)
    todo = findings.fix_recheck_targets(p.episode(n))
    if not todo:
        raise ValueError("고친 곳만 다시 볼 지적이 없어요. 지난 검수 뒤 고침안 말고도 고친 곳이 있으면 다시 검수하세요")
    label, total, owned = f"{n}화 고친 곳만 다시 보기 · 지적 {len(todo)}개", 1, set()
    want = [f.id for f in todo]

    def fn(job: jobs.Job):
        p0 = store.load(name)
        basis = pipeline.fix_recheck_basis(p0.episode(n))  # 늦게 온 결과가 그사이 한 검수 · 되돌리기를 덮지 않게 본 상태를 남긴다
        rep = pipeline.recheck_fixed(llm, p0, n)
        cancel.check()
        kids: list = []
        settled: list = []
        _edit(name, lambda q: kids.extend(pipeline.apply_fix_recheck(q, n, rep, basis, settled)))
        got = {x.id for x in rep.results}
        done = sum(1 for x in settled if x.resolved)  # 실제로 넣은 결과만 센다 (그사이 작가가 닫은 지적은 빼고)
        return {"asked": len(want), "resolved": done, "open": len(settled) - done, "added": len(kids),
                "missing": [i for i in want if i not in got]}
    return label, total, owned, fn


def _job_stage_draft(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 stage_draft · stage_extract: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    # 장면 연출 AI: 플롯 사건에서 계획 장면 초안, 본문에서 본문 장면 뽑기. 결과는 장면 연출 화면이 비교한 뒤 적용한다
    if n is None:
        raise ValueError("화 번호(ep)가 필요해요")
    e = p.episode(n)
    if not 0 <= body.event < len(e.plot.events):
        raise ValueError(f"{n}화에 {body.event + 1}번째 사건이 없어요")
    if kind == "stage_extract" and not e.text:
        raise ValueError("본문이 있는 화만 뽑아요")
    event, fresh = body.event, body.stage_room if body.stage_room in pipeline.stage.ROOMS else ""  # 이 함수 안의 stage 는 LLM 단계 이름이다
    label, total, owned = f"{n}화 사건 {event + 1} {'연출 초안' if kind == 'stage_draft' else '본문에서 연출 뽑기'}", 1, set()

    def fn(job: jobs.Job):
        q = store.load(name)
        prop = pipeline.draft_stage(llm, q, n, event, fresh) if kind == "stage_draft" else pipeline.extract_stage(llm, q, n, event)
        _stage_keep(name, prop)
        return {"event": event, "role": prop.role, "beats": len(prop.scene.beats), "dropped": prop.dropped}
    return label, total, owned, fn


def _job_storyline(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 storyline: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    label, total, owned = "이야기 줄기 제안", 1, set()
    note, line_kind = body.note, body.line_kind

    def fn(job: jobs.Job):
        return pipeline.suggest_storyline(llm, store.load(name), note, line_kind).model_dump()
    return label, total, owned, fn


def _job_recap_arc(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 recap_arc · recap_part: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    unit = kind.removeprefix("recap_")
    if n is None:
        raise ValueError("아크나 부 번호(ep)가 필요해요")
    label, total, owned = (f"아크 {n} 요약" if unit == "arc" else f"{n}부 요약"), 1, set()  # 화면과 같은 이름 ('1부')

    def fn(job: jobs.Job):
        return pipeline.recap(llm, store.load(name), unit, n).model_dump()
    return label, total, owned, fn


def _job_fold_knows(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 fold_knows: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    if n is None:
        raise ValueError("아크 번호(ep)가 필요해요")
    label, total, owned = f"아크 {n} 아는 정보 접기", 1, set()

    def fn(job: jobs.Job):
        return pipeline.fold_knows(llm, store.load(name), n).model_dump()
    return label, total, owned, fn


def _job_plots(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 plots: (이름표, 전체 걸음, 맡은 화, 할 일)."""
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
    return label, total, owned, fn


def _job_plot_one(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 plot_one: (이름표, 전체 걸음, 맡은 화, 할 일)."""
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
    return label, total, owned, fn


def _job_write(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 write · state: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    if n is None:
        raise ValueError("화 번호(ep)가 필요해요")
    e = p.episode(n)
    if kind == "write":
        if e.status == "draft":
            raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요")
        if body.rewrite is not None and e.text:  # 다시 생성: 새 판은 본문을 덮지 않고 고르기를 기다린다 (반영이 끝난 화도)
            req = pipeline.clean_rewrite(body.rewrite)
            polish = req.mode == "polish"  # 서술 다듬기는 revise 단계 모델 (설정 화면에서 다듬기만 다른 모델로 고를 수 있다)
            use = get_llm("revise") if polish else llm
            label, total, owned = f"{n}화 {'서술 다듬기' if polish else '새 판'}", 1, {n}

            def fn(job: jobs.Job):
                cut: list = []
                text = pipeline.rewrite_episode(use, store.load(name), n, req, cut)
                _edit(name, lambda q: pipeline.set_candidate(q, n, text, req, pipeline.writer_of(use), cut))
                return {"candidate": True}
        else:
            make = body.board == "make"
            use_cues = body.cues != "none"
            make_cues = use_cues and cue.on(p) and not e.text and cue.remake(p, n)  # 없거나 낡은 AI · 뼈대 시트
            plan = get_llm("board") if make or make_cues else None  # 스토리보드 · 큐 시트 단계 (비우면 계획 단계)
            then_check = p.settings.check_after_write and not e.text  # 처음 쓰는 본문만 바로 검수한다 (Settings.check_after_write)
            checker = get_llm("check") if then_check else None  # 키가 없으면 시작할 때 바로 알린다
            label = f"{n}화 {'스토리보드와 ' if make else ''}{'큐 시트와 ' if make_cues else ''}본문{'과 검수' if then_check else ''}"
            total, owned = 1 + make + make_cues + then_check, {n}

            def fn(job: jobs.Job):
                if not then_check:
                    return write(job)
                with _WRITE_CHECKS_LOCK:
                    _WRITE_CHECKS.add((name, n))
                try:
                    write(job)
                    # 본문은 저장했다. 맡은 화를 내려놓아 검수하는 동안에도 작가가 읽고 고칠 수 있게 하고, 화면이 본문을 먼저 받게 알린다.
                    # 그사이 고친 곳은 검수 회차가 시작 시각으로 남아 '검수 뒤 고침'으로 보인다 (pipeline.check_episode)
                    job.done += 1
                    job.release({n})
                    job.step_ep = n
                    job.note = f"{n}화 검수 중"
                    try:
                        with usage.scope(episode=n, task="check"):
                            return {"check": _run_check(name, n, checker)}
                    except cancel.Cancelled:
                        raise
                    except Exception as err:  # 검수가 실패해도 쓴 본문은 남는다. 까닭만 알린다
                        logging.getLogger("canon").warning("%s %s화 쓴 뒤 검수 실패", name, n, exc_info=True)
                        return {"check_error": explain_error(err)}
                finally:
                    with _WRITE_CHECKS_LOCK:
                        _WRITE_CHECKS.discard((name, n))

            def write(job: jobs.Job):
                _fill_old_spots(name)
                lead: list[str] = []
                made_at = ""
                if make:
                    job.note = f"{n}화 스토리보드 만드는 중"
                    b = pipeline.make_storyboard(plan, store.load(name), n, lead=lead)
                    _edit(name, lambda q: pipeline.set_storyboard(q, n, b, by="ai"))
                    made_at = b.made_at
                    job.done = 1
                if make_cues:  # 스토리보드 다음: 큐 시트는 스토리보드 장면 순서를 받아 만든다
                    job.note = f"{n}화 큐 시트 만드는 중"
                    q = store.load(name)  # 방금 만든 스토리보드면 그 요청 글로 시작해 캐시가 맞게 한다 (pipeline.cue_lead)
                    s = pipeline.make_cue_sheet(plan, q, n, lead=pipeline.cue_lead(q, n, lead, made_at))
                    _edit(name, lambda q: cue.set_episode(q, n, s, by="ai"))
                    job.done += 1
                job.note = f"{n}화 본문 쓰는 중"
                cut: list = []
                text = pipeline.write_episode(llm, store.load(name), n, use_board=body.board != "none", use_cues=use_cues, cut=cut)

                def save(q):
                    pipeline.replace_text(q.episode(n), text, written_by=pipeline.writer_of(llm), meta_cut=cut)  # 지금 본문이 있으면 '이전 판'에 남는다
                    anchor.stamp(q, n)
                    if q.episode(n).storyboard is not None:  # 스토리보드 없이 쓴 본문은 검수가 그 전제를 대조하지 않는다
                        q.episode(n).storyboard.skipped = body.board == "none"
                    cue.mark_used(q, n, use_cues)  # 큐 시트 없이 쓴 본문: 다시 생성도 넣지 않고 화면이 '쓴 큐 시트'로 보이지 않는다
                _edit(name, save)
                return None
    else:
        if not e.text:
            raise ValueError(f"{n}화 본문이 없어요")
        label, total, owned = f"{n}화 {'고친 본문 다시 맞추기' if e.status == 'finalized' else '상태 변경안'}", 1, set()

        def fn(job: jobs.Job):
            return pipeline.extract_state(llm, store.load(name), n).model_dump()
    return label, total, owned, fn


def _job_board(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 board: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    if n is None:
        raise ValueError("화 번호(ep)가 필요해요")
    if p.episode(n).status == "draft":
        raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요")
    pipeline.require_previous(p, n)
    ask = body.note.strip()
    if ask:
        if p.episode(n).storyboard is None:
            raise ValueError(f"{n}화 스토리보드가 없어요. 먼저 만드세요")
        label, total, owned = f"{n}화 스토리보드 고친 안", 1, {n}

        def fn(job: jobs.Job):
            b = pipeline.revise_storyboard(llm, store.load(name), n, ask)
            if cancel.stopped():  # 멈춘 고치기의 늦은 응답은 버린다 (작가가 그사이 다르게 고쳤을 수 있다)
                return {"kept": False}
            _edit(name, lambda q: pipeline.apply_storyboard_revision(q, n, b))
            return {"revised": True}
    else:
        label, total, owned = f"{n}화 스토리보드", 1, {n}

        def fn(job: jobs.Job):
            b = pipeline.make_storyboard(llm, store.load(name), n)
            if cancel.stopped():  # 멈춘 뒤 온 응답도 값을 치렀다
                return {"kept": _keep_late_board(name, n, b)}
            _edit(name, lambda q: pipeline.set_storyboard(q, n, b, by="ai"))
            return None
    return label, total, owned, fn


def _job_cues(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 cues: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    if n is None:
        raise ValueError("화 번호(ep)가 필요해요")
    if p.episode(n).status == "draft":
        raise ValueError(f"{n}화 플롯이 아직 확정되지 않았어요")
    pipeline.require_previous(p, n)
    label, total, owned = f"{n}화 큐 시트", 1, {n}

    def fn(job: jobs.Job):
        s = pipeline.make_cue_sheet(llm, store.load(name), n)
        _edit(name, lambda q: cue.set_episode(q, n, s, by="ai"))
        return {"cues": len(s.cues)}
    return label, total, owned, fn


def _job_hook(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 hook · openings · opening_drafts: (이름표, 전체 걸음, 맡은 화, 할 일)."""
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
    return label, total, owned, fn


def _job_impact(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 impact: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    el = elements.get(p, body.element)
    eid = el.id
    if not el.name.strip() or not el.description.strip():
        raise ValueError("요소의 이름과 설명을 적고 저장한 뒤 분석하세요")
    label, total, owned = f"인과율: {el.name} 영향 분석", 1, set()

    def fn(job: jobs.Job):
        rep = pipeline.analyze_impact(llm, store.load(name), eid)
        _edit(name, lambda q: pipeline.record_impact(q, eid, rep))
        return {"element": eid}
    return label, total, owned, fn


def _job_stattrial(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 stattrial: (이름표, 전체 걸음, 맡은 화, 할 일)."""
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
    return label, total, owned, fn


def _job_cue_sheet(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 cue_sheet: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    cue.check_episode(p, n)
    label, total, owned = f"{n}화 큐 시트 만들기", 1, set()

    def fn(job: jobs.Job):
        sheet = pipeline.make_cue_sheet(llm, cue.before(store.load(name), n), n)
        cue.with_lock(name, n, lambda lab: cue.set_sheet(lab, sheet, p, by="ai"))
        return {"cues": len(sheet.cues)}
    return label, total, owned, fn


def _job_cue_run(name: str, body: "JobIn", p: Project, kind: str, n: int | None, llm) -> tuple[str, int, set[int], Callable]:
    """작업 cue_run: (이름표, 전체 걸음, 맡은 화, 할 일)."""
    conds = cue._conds(body.conditions or None)
    cue.check_episode(p, n)
    sheet = store.load_cuelab(name, n).sheet
    if sheet is None and cue.NEEDS_SHEET & set(conds):
        raise ValueError("큐 시트를 먼저 만드세요")
    total = sum(len(sheet.cues) if c == "cues" else 1 for c in conds)
    label, owned = f"{n}화 큐 시트 실험 (조건 {len(conds)}개 · 쓰기 {total}번)", set()

    def fn(job: jobs.Job):
        def step(done: int, _total: int, note: str) -> None:
            job.done, job.note = done, note
        res = cue.run(name, store.load(name), llm, n, conds, progress=step)
        return {"takes": len(res["summary"]), "id": res["id"]}
    return label, total, owned, fn


JOB_MAKERS: dict[str, Callable] = {
    "suggest": _job_suggest,
    "style": _job_style,
    "arc": _job_arc,
    "series": _job_series,
    "nextarc": _job_nextarc,
    "heat": _job_heat,
    "convert": _job_convert,
    "rebuild": _job_rebuild,
    "rework": _job_rework,
    "check": _job_check,
    "fixes": _job_fixes,
    "recheck": _job_recheck,
    "stage_draft": _job_stage_draft,
    "stage_extract": _job_stage_draft,
    "storyline": _job_storyline,
    "recap_arc": _job_recap_arc,
    "recap_part": _job_recap_arc,
    "fold_knows": _job_fold_knows,
    "plots": _job_plots,
    "plot_one": _job_plot_one,
    "write": _job_write,
    "state": _job_write,
    "board": _job_board,
    "cues": _job_cues,
    "hook": _job_hook,
    "openings": _job_hook,
    "opening_drafts": _job_hook,
    "impact": _job_impact,
    "stattrial": _job_stattrial,
    "cue_sheet": _job_cue_sheet,
    "cue_run": _job_cue_run,
}


@app.post("/api/projects/{name}/jobs")
def start_job(name: str, body: JobIn) -> dict:
    """오래 걸리는 AI 작업을 시작하고 바로 돌아온다. 결과는 GET /api/jobs 로 본다."""
    p = _load(name)
    kind, n = body.kind, body.ep
    if kind in ("write", "state", "plots", "plot_one", "check", "board", "recheck"):
        _not_auto(name)
    if kind in jobs.EP_AI_KINDS and (old := jobs.waiting_on(name, n)):  # 같은 화에 호출이 겹치면 요청 한도(429)에 더 걸린다
        _waiting_409(old)
    stage = {"write": "write", "state": "state", "recap_arc": "state", "recap_part": "state", "fold_knows": "state", "rework": "revise", "fixes": "revise",
             "hook": "check", "check": "check", "recheck": "check", "opening_drafts": "write", "stattrial": "write", "stage_extract": "check", "cue_run": "write",
             "board": "board", "cues": "board"}.get(kind, "plan")  # 나머지는 plan
    llm = get_llm(stage)  # 키가 없으면 여기서 바로 오류를 보여 준다

    maker = JOB_MAKERS.get(kind)
    if maker is None:
        raise ValueError(f"모르는 작업이에요: {kind}")
    label, total, owned, fn = maker(name, body, p, kind, n, llm)

    try:
        with usage.scope(episode=n if kind in ("write", "board", "state", "check", "fixes", "recheck", "rework", "hook", "openings", "opening_drafts", "plot_one", "cue_sheet", "cue_run", "cues") else None, task=kind):
            job = jobs.start(name, kind, n, label, _keep_pending(name, kind, n, label, fn), total=total, owned=owned)
    except jobs.Busy as b:
        return {**b.job.public(), "already": True}
    return job.public()


# 결과가 반영 전 제안인 작업. 화면이 반영하거나 버릴 때까지 pending.json 에 둔다
# (본문 · 플롯 · 판정 같은 작업은 서버가 이미 작품에 썼다)
PENDING_KINDS = {"arc", "heat", "suggest", "style", "series", "nextarc", "convert", "rebuild", "rework", "storyline", "recap_arc", "recap_part", "fold_knows", "state", "openings"}


def _keep_pending(name: str, kind: str, n: int | None, label: str, fn):
    """작업 fn 을 감싸, 끝나면 제안 결과를, 실패하면 오류를 작품의 pending.json 에 남긴다. 같은 작업이 성공하면 지난 실패를 지운다."""
    key = f"{kind}:{n if n is not None else ''}"

    def run(job: jobs.Job):
        try:
            out = fn(job)
        except cancel.Cancelled:
            raise  # 멈춘 작업은 실패로 남기지 않는다
        except Exception as e:
            fail = {"key": key, "kind": kind, "ep": n, "label": label, "error": explain_error(e), "at": _now()}

            def put_fail(d: dict) -> None:
                d["failures"][key] = fail
            store.edit_pending(name, put_fail)
            raise
        if cancel.stopped():
            return out  # 멈춘 작업은 성공으로 남기지 않는다. 늦은 응답을 남긴 작업(스토리보드)은 결과만 싣는다
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


def _state_live(p: Project) -> dict[int, str]:
    """상태 변경안을 아직 쓸 수 있는 화 → 쓸 수 없는 변경안의 본문 지문.
    본문 작성 상태인 화는 ''(어느 변경안이든 쓴다), 반영 뒤 고친 화는 고치기 전 본문(final_text)의 지문이다."""
    out: dict[int, str] = {}
    for e in p.episodes:
        if e.status == "written":
            out[e.plot.number] = ""
        elif pipeline.edited_after_final(e):
            out[e.plot.number] = pipeline.text_basis(e.final_text)
    return out


def _stale_state(results: dict, live: dict[int, str]) -> list[str]:
    """이미 쓸 수 없게 된 상태 변경안(state:<화>)의 키. 본문 작성 상태도, 반영 뒤 고친 화도 아닌 화의 변경안이다.
    반영 뒤 고친 화는 고치기 전 본문에서 뽑은 변경안도 낡았다. 다시 맞추기 후보는 고친 본문에서 뽑은 것만 둔다 (restate.js restateCard)."""
    out = []
    for k, r in results.items():
        if r.get("kind") != "state":
            continue
        n = r.get("ep")
        if n not in live:
            out.append(k)
            continue
        base = r.get("base")
        made = pipeline.text_basis(base) if base is not None else (r.get("result") or {}).get("basis") or ""
        if live[n] and made == live[n]:
            out.append(k)
    return out


@app.get("/api/projects/{name}/pending")
def get_pending(name: str) -> dict:
    """검토를 기다리는 AI 결과와 실패한 작업. 이미 쓸 수 없게 된 상태 변경안(_stale_state)은 지운다."""
    p = _view(name)
    stale = _stale_state(store.load_pending(name)["results"], _state_live(p))

    def prune(d: dict) -> None:
        for k in stale:
            d["results"].pop(k, None)
    return store.edit_pending(name, prune) if stale else store.load_pending(name)


@app.delete("/api/projects/{name}/pending/{key}")
def drop_pending(name: str, key: str, failure: bool = False, id: str = "") -> dict:
    """화면이 반영하거나 버린 결과(또는 닫은 실패)를 지운다. id 를 주면 그 작업의 결과일 때만 지운다:
    화면이 옛 결과를 반영하는 사이 같은 키에 새 결과가 들어왔으면 새 결과를 남긴다."""
    _need(name)

    def drop(d: dict) -> None:
        box = d["failures" if failure else "results"]
        if id and not failure and (box.get(key) or {}).get("id") not in (None, id):
            return
        box.pop(key, None)
    return store.edit_pending(name, drop)


class StateDraftIn(BaseModel):
    """상태 승인 화면에서 고르던 체크와 고친 변경안. 화면이 보내는 값이라 LLM 스키마가 아니다."""
    delta: dict
    picks: dict[str, bool] | None = None  # None: 화면의 체크가 다른 화의 것이라 보내지 않았다. 남긴 체크를 그대로 둔다
    id: str | None = None  # 받은 결과의 작업 id. 그사이 새 변경안으로 바뀌었으면 남기지 않는다


@app.put("/api/projects/{name}/pending/{key}/draft")
def save_state_draft(name: str, key: str, body: StateDraftIn) -> dict:
    """상태 변경안 결과(state:<화>)에 작가가 고르던 체크와 고친 칸을 초안으로 붙인다. 새로고침 · 다른 탭이 이어 받는다.
    pending.json 만 고치고 작품은 저장하지 않는다. 결과가 없거나(반영 · 버림 뒤 늦게 온 저장) 다른 결과로 바뀌었으면 그대로 둔다."""
    _need(name)

    def put(d: dict) -> None:
        rec = d["results"].get(key)
        if rec and rec.get("kind") == "state" and (body.id is None or body.id == rec.get("id")):
            picks = body.picks if body.picks is not None else (rec.get("draft") or {}).get("picks")
            rec["draft"] = {"delta": body.delta, "picks": picks, "at": _now()}
    return store.edit_pending(name, put)


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
    llm, cut = get_llm("write"), []
    text = pipeline.write_episode(llm, p, n, cut=cut)
    pipeline.replace_text(p.episode(n), text, written_by=pipeline.writer_of(llm), meta_cut=cut)  # 지금 본문이 있으면 '이전 판'에 남는다
    cue.mark_used(p, n, True)
    anchor.stamp(p, n)
    return _save(name, p)


class Text(BaseModel):
    text: str
    base: str | None = None  # 이 고침을 시작한 저장 본문. 주면 지금 저장 본문과 맞춰 보고, 없으면(옛 화면 · 명령줄) 맞춰 보지 않는다


@app.put("/api/projects/{name}/episodes/{n}/text")
def put_text(name: str, n: int, body: Text, force: bool = False) -> Project:
    """직접 고친 본문이나 채팅 앱에서 받은 본문을 저장한다. 그 화를 쓰는 작업이나 자동 집필이 도는 중이면 막는다
    (작업이 끝나며 쓰는 본문과 서로 덮지 않게, 고친 본문에 옛 본문 기준 변경안이 반영되지 않게).
    base 가 지금 저장 본문과 다르면(다른 탭 · 기기가 먼저 저장) 덮지 않고 409(code stale_text)를 돌려준다. force 면 그래도 덮는다."""
    _text_guard(name, n)
    p = _load(name)
    ep = p.episode(n)
    if body.base is not None and not force and body.base.strip() != ep.text.strip():
        return JSONResponse({"detail": f"다른 탭이나 기기에서 {n}화 본문을 먼저 저장했어요. 다시 불러와 그 본문을 보거나, 내 고침으로 덮어쓰세요",
                             "code": "stale_text"}, status_code=409)
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
    if not ep.text or not text:  # 빈 화에 넣은 본문은 직접 쓴 것인지 채팅 앱에서 붙여 넣은 것인지 몰라 모델을 비운다
        ep.written_by, ep.meta_cut = "", []
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


@app.post("/api/projects/{name}/episodes/{n}/storyboard/undo")
def undo_storyboard(name: str, n: int) -> Project:
    """AI 가 요청대로 고치기 전 스토리보드로 되돌린다 (Episode.storyboard_prev)."""
    _board_guard(name, n)
    _load(name).episode(n)
    return _edit(name, lambda p: pipeline.undo_storyboard(p, n))


# ---------- 4-0. 화별 큐 시트 ----------
# 쓰기 직전의 큐 시트 (cue.py 의 집필 경로). 만들기는 작업 cues (start_job), 작가 수정 · 뼈대 · 지우기는 여기서.
# 스토리보드처럼 상태 승인 대상이 아니라 바로 저장한다. 그 화를 맡은 작업이나 자동 집필이 도는 동안은 막는다.

@app.get("/api/projects/{name}/episodes/{n}/cue-sheet")
def get_cue_sheet(name: str, n: int) -> dict:
    """Canon 이 센 값: 켜짐, 낡음, 핵심 대사가 들어간 수 (cue.ep_view)."""
    p = _load(name)
    p.episode(n)
    return cue.ep_view(p, n)


@app.put("/api/projects/{name}/episodes/{n}/cue-sheet")
def put_cue_sheet(name: str, n: int, body: CueSheetDraft) -> Project:
    """작가가 고친 큐 시트를 저장한다. AI · 뼈대 시트를 고치면 made_by 가 both 가 된다."""
    _board_guard(name, n)
    _load(name).episode(n)
    return _edit(name, lambda p: cue.set_episode(p, n, body))


@app.post("/api/projects/{name}/episodes/{n}/cue-sheet/board")
def board_cue_sheet(name: str, n: int) -> Project:
    """AI 없이 스토리보드 장면(없으면 플롯 사건)마다 큐 하나인 뼈대를 넣는다."""
    _board_guard(name, n)
    _load(name).episode(n)
    return _edit(name, lambda p: cue.set_episode(p, n, cue.from_board(p, n), by="board"))


@app.delete("/api/projects/{name}/episodes/{n}/cue-sheet")
def drop_cue_sheet(name: str, n: int) -> Project:
    _board_guard(name, n)
    _load(name).episode(n)
    return _edit(name, lambda p: cue.set_episode(p, n, None))


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


# ---------- 장면 연출 (stage.py, 화면 static/stage.js) ----------
# 장면은 작가 자료라 이 엔드포인트로만 바꾼다. 화면의 작품 전체 저장(_save)은 디스크의 장면 · 방을 지킨다.
# 자동 집필이 돌거나 그 화를 맡은 작업이 있으면 막는다 (작업이 저장하는 작품이 장면 저장을 덮지 않게).

class StageNewIn(BaseModel):
    event: int
    room: str = ""      # 이미 있는 방 id. 비면 template 로 새 방
    template: str = ""
    room_name: str = ""
    place: str = ""
    role: Literal["plan", "text"] = "plan"  # 본문 장면은 보통 추출(일감 03)이 만든다


class StageSaveIn(BaseModel):
    scene: StageScene
    room: StageRoom | None = None


def _stage_free(name: str, n: int) -> None:
    _not_auto(name)
    if n in jobs.owned_episodes(name):
        raise ValueError(f"{n}화를 맡은 작업이 도는 중이에요. 끝난 뒤에 저장하세요")


@app.get("/api/projects/{name}/stage/{n}")
def stage_view(name: str, n: int) -> dict:
    return _stage_view(name, _load(name), n)


@app.post("/api/projects/{name}/stage/{n}")
def stage_new(name: str, n: int, body: StageNewIn) -> dict:
    _load(name).episode(n)
    _stage_free(name, n)
    made = {}

    def fn(p: Project):
        e = p.episode(n)
        room = next((r for r in p.rooms if r.id == body.room), None) if body.room else None
        if room is None:
            room = stage.new_room(p, body.template or "empty", body.room_name, body.place)
        made["id"] = stage.new_scene(p, e, body.event, room, body.role).id

    p = _edit(name, fn)
    return {**_stage_view(name, p, n), "made": made["id"]}


@app.put("/api/projects/{name}/stage/{n}/{sid}")
def stage_save(name: str, n: int, sid: str, body: StageSaveIn) -> dict:
    _load(name).episode(n)
    _stage_free(name, n)
    if body.scene.id != sid:
        raise ValueError("장면 번호가 주소와 달라요")
    out = {}
    p = _edit(name, lambda p: out.update(dropped=stage.save_scene(p, p.episode(n), body.scene, body.room)))
    return {**_stage_view(name, p, n), **out}


# AI 장면(StageProposal)은 pending.json 의 results 에 'stage:<화>:<사건>:<역할>' 로 둔다 (화면 app.js 의 pendingShown 이 지우지 않는다).
# 장면 연출 화면이 지금 장면과 나란히 보이고, 적용하면 통째로 넣고 지운다.

def _stage_key(n: int, event: int, role: str) -> str:
    return f"stage:{n}:{event}:{role}"


def _stage_keep(name: str, prop: StageProposal) -> None:
    key = _stage_key(prop.episode, prop.event, prop.role)
    rec = {"key": key, "kind": "stage", "ep": prop.episode, "label": f"{prop.episode}화 사건 {prop.event + 1} 연출", "result": prop.model_dump(), "at": _now()}
    store.edit_pending(name, lambda d: d["results"].__setitem__(key, rec))


def _stage_proposals(name: str, n: int) -> list[dict]:
    return [r["result"] for r in store.load_pending(name)["results"].values() if r.get("kind") == "stage" and r.get("ep") == n]


def _stage_view(name: str, p: Project, n: int) -> dict:
    """장면 연출 화면 값 + 검토를 기다리는 AI 장면 (비교 보기는 그 장면도 판정해 보인다)."""
    out = stage.view(p, n)
    e = p.episode(n)
    props = []
    for x in _stage_proposals(name, n):
        prop = StageProposal.model_validate(x)
        room = prop.room or prop.grown or stage.room_of(p, prop.scene)
        shared = bool(prop.adds and prop.grown) and stage.room_shared(p, prop.grown.id, n, prop.event, prop.role)
        props.append({**prop.model_dump(), "violations": [v.model_dump() for v in stage.judge_all(prop.scene, room, p)] if room else [],
                      "moves": stage.move_gaps(prop.scene, room, p), "stale": stage.stale(prop.scene, e.text), "room_shared": shared})
    return {**out, "proposals": props}


class StageApplyIn(BaseModel):
    event: int
    role: Literal["plan", "text"] = "plan"
    shared: bool = False  # AI 가 더하자는 기준점을 공용 방에 바로 더한다 (거짓이면 공용 방을 복사한 장면 전용 방에)


@app.post("/api/projects/{name}/stage/{n}/apply")
def stage_apply(name: str, n: int, body: StageApplyIn) -> dict:
    """검토를 기다리는 AI 장면을 통째로 넣는다. 같은 사건 · 역할의 장면은 적용 취소 한 번으로 되돌릴 수 있다."""
    _load(name).episode(n)
    _stage_free(name, n)
    key = _stage_key(n, body.event, body.role)
    rec = store.load_pending(name)["results"].get(key)
    if rec is None:
        raise ValueError("적용할 AI 장면이 없어요. 다시 받아 주세요")
    prop = StageProposal.model_validate(rec["result"])
    made = {}
    p = _edit(name, lambda q: made.update(id=pipeline.apply_stage(q, prop, body.shared).id))
    store.edit_pending(name, lambda d: d["results"].pop(key, None))
    return {**_stage_view(name, p, n), "made": made["id"]}


@app.delete("/api/projects/{name}/stage/{n}/proposal/{event}/{role}")
def stage_discard(name: str, n: int, event: int, role: str) -> dict:
    """AI 장면을 버린다 (장면은 그대로)."""
    store.edit_pending(name, lambda d: d["results"].pop(_stage_key(n, event, role), None))
    return _stage_view(name, _load(name), n)


@app.post("/api/projects/{name}/stage/{n}/{sid}/undo")
def stage_undo(name: str, n: int, sid: str) -> dict:
    """마지막 AI 적용을 되돌린다. 적용 전에 장면이 없었으면 장면을 뺀다."""
    _load(name).episode(n)
    _stage_free(name, n)
    return _stage_view(name, _edit(name, lambda q: pipeline.undo_stage(q, n, sid)), n)


@app.post("/api/projects/{name}/stage/{n}/check")
def stage_check(name: str, n: int, body: StageSaveIn) -> dict:
    """저장하지 않고 판정만 (화면이 고치는 동안). 막을 접촉 수도 센다."""
    p = _load(name)
    e = p.episode(n)
    scene = body.scene.model_copy(deep=True)
    room = body.room or stage.room_of(p, scene)
    dropped = stage.clean_scene(scene, room, p)
    return {**stage.check(p, e, scene, room), "dropped": dropped}


def _frames(p: Project, scene: StageScene, room: StageRoom | None) -> dict:
    """3D 보기 값: 박자마다 관절 좌표(stage3d.frames), 3D 판정, 아직 모듈이 없는 자세 · 틀.
    3D 판정은 자세 · 틀이 다 등록됐을 때만 낸다 (docs/stage/3d/README.md 정할 것 10). 같은 지적이 stage.check 의 violations 에도 있다."""
    from . import stage3d
    from .stage3d import judge as judge3d

    if room is None:
        raise ValueError("장면의 방을 찾지 못했어요")
    fr = stage3d.frames(scene, room, p)
    found = [v.model_dump() for v in judge3d.judge3d(scene, room, p, frames=fr)] if stage3d.ready() else []
    return {"frames": fr.to_dict(), "violations3d": found, "missing": stage3d.missing()}


@app.get("/api/projects/{name}/stage/{n}/{sid}/frames")
def stage_frames(name: str, n: int, sid: str) -> dict:
    """저장된 장면 하나의 3D 보기 값 (화면 static/stage3d.js)."""
    p = _load(name)
    scene = next((s for s in p.episode(n).stage if s.id == sid), None)
    if scene is None:
        raise HTTPException(404, "그 장면이 없어요")
    return _frames(p, scene, stage.room_of(p, scene))


@app.post("/api/projects/{name}/stage/{n}/{sid}/frames")
def stage_frames_draft(name: str, n: int, sid: str, body: StageSaveIn) -> dict:
    """저장하지 않은 장면의 3D 보기 값 (화면이 고치는 중일 때 '다시 그리기')."""
    p = _load(name)
    p.episode(n)
    if body.scene.id != sid:
        raise ValueError("장면 번호가 주소와 달라요")
    scene = body.scene.model_copy(deep=True)
    room = body.room or stage.room_of(p, scene)
    if room:
        stage.clean_scene(scene, room, p)
    return _frames(p, scene, room)


@app.delete("/api/projects/{name}/stage/{n}/{sid}")
def stage_delete(name: str, n: int, sid: str) -> dict:
    _load(name).episode(n)
    _stage_free(name, n)
    return _stage_view(name, _edit(name, lambda p: stage.remove_scene(p.episode(n), sid)), n)


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


@app.post("/api/projects/{name}/episodes/{n}/meta-cut/{k}/restore")
def restore_meta_cut(name: str, n: int, k: int) -> Project:
    """쓰기가 뗀 작업 설명 문단 하나를 본문 앞이나 뒤에 되살린다. 수정 기록에 남아 되돌릴 수 있다."""
    _load(name).episode(n)
    _text_guard(name, n)
    return _edit(name, lambda p: pipeline.restore_cut(p, n, k))


@app.delete("/api/projects/{name}/episodes/{n}/meta-cut/{k}")
def drop_meta_cut(name: str, n: int, k: int) -> Project:
    """쓰기가 뗀 작업 설명 문단 하나를 지운다. 본문은 그대로다."""
    return _edit(name, lambda p: pipeline.drop_cut(p, n, k))


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
    _need(name)
    _not_auto(name)
    return _edit(name, lambda p: pipeline.apply_opening(p, n, body.plot))


@app.post("/api/projects/{name}/episodes/{n}/opening-plot/undo")
def opening_plot_undo(name: str, n: int) -> Project:
    """n화 플롯을 여는 방식 안을 처음 고르기 전으로 되돌린다 (Episode.opening_prev). 화는 초안이 된다."""
    _need(name)
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
        delta = to_delta(StateDeltaAI.model_validate(data), n)  # 예전 JSON 의 관계 수치 칸은 버린다
    except ValidationError as e:
        raise HTTPException(400, _validation_text(e))
    pipeline.clean_delta(p, delta)
    delta.basis = pipeline.text_basis(p.episode(n).text)
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
    _need(name)

    def fn(q: Project) -> None:
        ep, now = q.episode(n), pipeline._now()
        f = findings.find(ep, fid)
        if body.severity is not None:
            findings.set_severity(ep, fid, body.severity, now)
        if body.status is not None or body.note is not None:
            findings.set_status(ep, fid, body.status or f.status, body.note, now)
    return _edit(name, fn)


class FindingsIn(BaseModel):
    ids: list[str] = Field(..., min_length=1, description="상태를 정할 지적 id 목록")
    status: Literal["kept", "wrong"] = Field(..., description="한꺼번에 정할 상태: 그대로 둠(kept) · 잘못 짚음(wrong)")


@app.put("/api/projects/{name}/episodes/{n}/findings")
def set_findings(name: str, n: int, body: FindingsIn) -> Project:
    """열린 지적 여러 개를 한꺼번에 그대로 둠 · 잘못 짚음으로 정한다 (검수 목록의 거르기 뒤 한꺼번에 정하기).
    없는 id 나 열리지 않은 지적이 하나라도 있으면 아무것도 바꾸지 않는다."""
    _need(name)

    def fn(q: Project) -> None:
        ep, now = q.episode(n), pipeline._now()
        picked = [findings.find(ep, fid) for fid in dict.fromkeys(body.ids)]
        shut = [f.id for f in picked if f.status != "open"]
        if shut:
            raise HTTPException(400, f"열린 지적만 한꺼번에 정할 수 있어요: {', '.join(shut)}")
        for f in picked:
            findings.set_status(ep, f.id, body.status, None, now)
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


class FixPick(BaseModel):
    fid: str = Field(description="지적 id")
    k: int = Field(description="넣을 고침안 번호 (0부터)")
    skip: list[int] = Field(default_factory=list, description="넣지 않을 딸린 곳 번호 (0부터)")


class FixBatchIn(BaseModel):
    items: list[FixPick] = Field(description="작가가 고른 고침안. 이 차례대로 넣는다")
    confirm: bool = Field(False, description="그대로 둠 · 잘못 짚음 지적의 문장도 바꾸는 줄 알고 적용한다")


class FixFail(_Out):
    fid: str
    error: str = Field(description="넣지 못한 까닭 (화면에 그대로 보인다)")


class FixBatchOut(_Out):
    project: Project
    applied: list[str] = Field(description="넣은 지적 id")
    failed: list[FixFail] = Field(description="넣지 못한 지적과 까닭. 나머지는 넣었다")


@app.post("/api/projects/{name}/episodes/{n}/fixes/apply")
def apply_finding_fixes(name: str, n: int, body: FixBatchIn) -> FixBatchOut:
    """고른 고침안 여러 개를 차례로 본문에 넣는다 (검수 화면의 한꺼번에 검토). 지적마다 한 묶음이라 하나씩 되돌릴 수 있다.
    앞 고침안이 같은 문장을 바꿔 못 넣은 것은 까닭과 함께 돌려준다."""
    if not body.items:
        raise ValueError("넣을 고침안을 고르세요")
    _load(name).episode(n)
    _text_guard(name, n)
    out: list = []
    p = _edit(name, lambda q: out.extend(pipeline.apply_fixes(q, n, [(x.fid, x.k, x.skip) for x in body.items], body.confirm)))
    done, failed = out
    return {"project": p, "applied": done, "failed": [{"fid": f, "error": e} for f, e in failed]}


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
    "float_type": "숫자여야 해요", "float_parsing": "숫자여야 해요", "bool_type": "true나 false여야 해요",
    "bool_parsing": "true나 false여야 해요", "list_type": "목록([ ])이어야 해요", "model_type": "{ } 로 묶인 객체여야 해요",
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
def apply_state(name: str, n: int, d: StateDelta, force: bool = False) -> Project:
    """화면에서 고른 항목만 담긴 변경안을 반영하고 그 화를 끝낸다.
    누구의 것도 아닌 데이터가 남는 항목(pipeline.validate_delta)이 있으면 400 으로 막는다.
    변경안을 만든 본문(d.basis)이 지금 본문과 다르면 409(code stale_delta)로 막는다. 작가가 확인하면 force 로 다시 보낸다."""
    p = _load(name)
    _not_auto(name)
    ep = p.episode(n)
    pipeline.check_applicable(p, n)
    d.episode = n
    bad = pipeline.validate_delta(p, d)
    if bad:
        raise ValueError(f"반영할 수 없는 항목이 {len(bad)}개 있어요. 체크를 빼고 다시 반영하세요\n" + "\n".join(f"- {m}" for m in bad))
    if d.basis and not force and d.basis != pipeline.text_basis(ep.text):
        return JSONResponse({"detail": f"변경안을 만든 뒤 {n}화 본문을 고쳤어요. 옛 본문 기준의 요약 · 인물 상태 · 사건이 들어가요",
                             "code": "stale_delta"}, status_code=409)
    pipeline.apply_delta(p, d)
    return _save(name, p)


@app.post("/api/projects/{name}/episodes/{n}/restate")
def apply_restate(name: str, n: int, d: StateDelta, force: bool = False) -> Project:
    """반영 뒤 고친 화: 고친 본문에서 다시 뽑은 변경안 중 고른 요약 · 새 사실 · 새 복선만 반영한다.
    변경안을 만든 본문(d.basis)이 지금 본문과 다르면 apply_state 처럼 409(code stale_delta)로 막는다. 작가가 확인하면 force 로 다시 보낸다."""
    p = _load(name)
    _not_auto(name)
    ep = p.episode(n)
    if ep.status == "finalized" and d.basis and not force and d.basis != pipeline.text_basis(ep.text):
        return JSONResponse({"detail": f"변경안을 만든 뒤 {n}화 본문을 또 고쳤어요. 옛 본문 기준의 요약 · 사실 · 복선이 들어가요",
                             "code": "stale_delta"}, status_code=409)
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
    kept = _revert_kept(p, n)
    edited = {f"state:{e.plot.number}" for e in p.episodes if e.plot.number > n and pipeline.edited_after_final(e)}
    pipeline.revert(p, n)
    out = _save(name, p)

    def put(d: dict) -> None:
        for key, rec in kept.items():
            # 반영 뒤 고친 화를 다시 맞추려고 뽑아 둔 변경안은 지금 본문에서 뽑은 것이라 그대로 둔다 (화면도 그것을 보고 있다)
            if not (key in edited and key in d["results"]):
                d["results"][key] = rec
    store.edit_pending(name, put)
    autorun.after_revert(name, n + 1)  # 자동 집필 실행 기록(자동 반영 목록, 로그, 끝남 상태)도 n+1화부터 맞춘다
    return out


def _revert_kept(p: Project, n: int) -> dict:
    """반영 취소로 지울 n+1화부터의 반영 기록을 검토를 기다리는 상태 변경안(pending.json 의 state:<화>)으로 바꾼다.
    상태 승인 화면이 다시 고를 수 있게 놓아, AI로 다시 뽑지 않아도 된다. base 는 반영할 때의 본문(반영 뒤 고쳤으면 고치기 전)이다."""
    last = {d.episode: d for d in p.history if d.episode > n}
    at, out = _now(), {}
    for m, d in sorted(last.items()):
        e = next((x for x in p.episodes if x.plot.number == m and x.status == "finalized"), None)
        if e is None:
            continue
        key = f"state:{m}"
        out[key] = {"key": key, "id": f"revert:{at}:{m}", "kind": "state", "ep": m, "label": f"{m}화 상태 변경안",
                    "result": d.model_dump(), "base": e.final_text or e.text, "at": at}
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
    want: str = Field("", description="도는 실행에 받아 둔 요청(pause | stop). 지금 단계가 끝날 때까지 화면이 '멈추는 중'을 보인다")
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
    return {"run": out, "active": autorun.active(name), "want": autorun.wanted(name),
            "batch_stages": [s for s in ("write", "check", "state") if autorun.batchable(s)], "policy_defaults": autorun.Policy()}


@app.get("/api/projects/{name}/auto")
def auto_get(name: str) -> AutoView:
    return _auto(name)


@app.post("/api/projects/{name}/auto/estimate")
def auto_estimate(name: str, body: AutoIn) -> AutoEstimate:
    return autorun.estimate(_load(name), body.target, body.batch, body.policy, name)


@app.post("/api/projects/{name}/auto/start")
def auto_start(name: str, body: AutoIn) -> AutoView:
    _need(name)
    autorun.start(name, body.target, body.batch, body.policy)
    return _auto(name)


class AutoResume(BaseModel):
    approve: bool = False  # 검토 대기 변경안을 그대로 반영
    rewrite: bool = False  # 검토 대기 화를 다시 쓰기


@app.post("/api/projects/{name}/auto/resume")
def auto_resume(name: str, body: AutoResume) -> AutoView:
    _need(name)
    run = autorun.get_run(name)
    n = run.ep if run and run.status == "review" and (body.approve or body.rewrite) else None
    autorun.resume(name, approve=body.approve, rewrite=body.rewrite)
    if n is not None:  # 그 화는 반영했거나 다시 쓴다. 검토하기로 둔 결과(auto_review)는 쓸 데가 없으니 지운다
        def drop(d: dict) -> None:
            if str((d["results"].get(f"state:{n}") or {}).get("id", "")).startswith("auto:"):
                d["results"].pop(f"state:{n}")
        store.edit_pending(name, drop)
    return _auto(name)


@app.post("/api/projects/{name}/auto/review")
def auto_review(name: str) -> AutoView:
    """검토 대기 변경안을 검토를 기다리는 결과(pending.json 의 state:<화>)로 둔다. 상태 승인 화면이 작업 결과처럼 읽는다.
    웹(auto.js autoOpenReview)과 앱 모두 이것을 부른 뒤 상태 승인 화면으로 간다. 그래서 고르던 체크 · 고친 칸이 초안으로 남는다.
    id 는 실행 · 화 · 변경안 내용으로 정해 같은 변경안이면 같다. 같은 변경안을 다시 두면 작가가 남긴 초안을 지키고, 다시 쓰기로 바뀐 변경안은 새로 둔다."""
    p = _load(name)
    run = autorun.get_run(name)
    if run is None or run.status != "review" or run.pending is None or run.ep is None or p.episode(run.ep).status != "written":
        raise ValueError("검토를 기다리는 변경안이 없어요")
    n, key = run.ep, f"state:{run.ep}"
    result = run.pending.model_dump()
    tag = hashlib.sha1(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:10]
    rec = {"key": key, "id": f"auto:{run.started}:{n}:{tag}", "kind": "state", "ep": n, "label": f"{n}화 상태 변경안",
           "result": result, "base": run.pending_text or None, "at": _now()}

    def put(d: dict) -> None:
        old = d["results"].get(key)
        if old and old.get("id") == rec["id"]:
            return  # 이미 둔 같은 변경안: 초안(draft)을 지킨다
        d["results"][key] = rec
    store.edit_pending(name, put)
    return _auto(name)


@app.post("/api/projects/{name}/auto/{what}")
def auto_request(name: str, what: str) -> AutoView:
    """what: pause | stop"""
    _need(name)
    if what not in ("pause", "stop"):
        raise HTTPException(404, "pause 또는 stop만 돼요")
    autorun.request(name, what)
    return _auto(name)


class AutoBatch(BaseModel):
    batch: bool


@app.put("/api/projects/{name}/auto/batch")
def auto_batch(name: str, body: AutoBatch) -> AutoView:
    _need(name)
    autorun.set_batch(name, body.batch)
    return _auto(name)


@app.put("/api/projects/{name}/auto/policy")
def auto_policy(name: str, body: autorun.Policy) -> AutoView:
    """멈춘 실행의 승인 정책을 바꾼다. 검토 대기와 기다리던 배치는 그대로 두고 다음 판정부터 적용된다."""
    _need(name)
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


# 작품에서만 계산하는 큰 화면 값의 JSON {(작품, 종류): (판, JSON)}. 장편 인물 화면은 화별 관계 프레임을 처음부터
# 다시 계산해 0.2초가 넘고 응답이 수 MB 다. 판이 같으면 기억한 JSON 을 보내고, 화면이 같은 판을 들고 있으면 304 로 답한다
_json_views: dict[tuple[str, str], tuple[str, bytes]] = {}
_json_views_lock = threading.Lock()
_BOOT = f"{time.time_ns():x}"  # 판에 서버 시작 시각을 넣는다: 코드가 바뀌어 다시 시작하면 같은 작품도 다시 계산한다


def _json_view(request: Request, name: str, kind: str, build, sig: str = "") -> Response:
    """build() 가 내는 JSON 글을 작품 파일 판(+ sig)으로 기억해 보낸다. build 는 작품(과 sig 가 가리키는 파일)만 읽어야 한다."""
    _need(name)
    tag = f'"{kind}-{_BOOT}-{store.tag(store.project_dir(name) / "project.json").strip(chr(34))}{sig}"'
    head = {"ETag": tag, **NO_CACHE}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=head)
    with _json_views_lock:
        hit = _json_views.get((name, kind))
    if hit and hit[0] == tag:
        body = hit[1]
    else:
        body = build()
        with _json_views_lock:
            _json_views[(name, kind)] = (tag, body)
    return Response(body, media_type="application/json", headers=head)


@app.get("/api/projects/{name}/cast", response_model_exclude_unset=True)
def cast_view(name: str, request: Request) -> CastView:
    """인물 화면: 화별 관계 프레임(관계도 재생), 인물별 등장 화와 타임라인 (canon/cast.py). 작품이 그대로면 기억한 결과를 보낸다 (_json_view)."""
    return _json_view(request, name, "cast", lambda: CastView.model_validate(cast.summary(_load(name))).model_dump_json(exclude_unset=True).encode())


class HeldIn(BaseModel):
    value: str | None = None  # 고친 값으로 적용할 때만


@app.post("/api/projects/{name}/setting-held/{i}")
def take_held_setting(name: str, i: int, body: HeldIn) -> Project:
    """자동 집필이 남겨 둔 설정 바꾸기 제안 하나를 적용한다. 그 화의 설정 변경 기록으로 남는다."""
    p = _load(name)
    _not_auto(name)
    charlog.take_held(p, i, body.value)
    return _save(name, p)


@app.post("/api/projects/{name}/episodes/{n}/dismissed-facts/{i}")
def take_dismissed_fact(name: str, n: int, i: int) -> Project:
    """n화 반영 기록에서 빼 둔 새 사실 하나를 확정 사실에 넣는다 (자동 반영이 비슷한 사실이라 뺀 것을 나중에 고를 때)."""
    p = _load(name)
    _not_auto(name)
    pipeline.take_dismissed_fact(p, n, i)
    return _save(name, p)


@app.delete("/api/projects/{name}/setting-held/{i}")
def drop_held_setting(name: str, i: int) -> Project:
    """남겨 둔 설정 바꾸기 제안 하나를 버린다."""
    p = _load(name)
    _not_auto(name)
    charlog.drop_held(p, i)
    return _save(name, p)


class AddressIn(BaseModel):
    speaker: str
    listener: str
    calls: str = ""
    speech: str = ""


@app.put("/api/projects/{name}/address")
def set_address(name: str, body: AddressIn) -> Project:
    """한 방향의 부르는 말 · 말씨를 정한다 (두 칸이 모두 비면 지운다). 1화 반영 뒤에는 작가 기록으로 남는다 (address.set_form)."""
    p = _load(name)
    _not_auto(name)
    address.set_form(p, body.speaker, body.listener, body.calls, body.speech)
    return _save(name, p)


@app.post("/api/projects/{name}/address-held/{i}")
def take_held_address(name: str, i: int) -> Project:
    """자동 집필이 남겨 둔 호칭 · 말씨 바뀜 제안 하나를 적용한다. 그 화의 기록으로 남는다."""
    p = _load(name)
    _not_auto(name)
    address.take_held(p, i)
    return _save(name, p)


@app.delete("/api/projects/{name}/address-held/{i}")
def drop_held_address(name: str, i: int) -> Project:
    """남겨 둔 호칭 · 말씨 바뀜 제안 하나를 버린다."""
    p = _load(name)
    _not_auto(name)
    address.drop_held(p, i)
    return _save(name, p)


def _map_dir(name: str) -> Path:
    return store.project_dir(name) / "map"


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
    kind: str = "clue"
    public: bool = False


@app.post("/api/projects/{name}/foreshadows")
def foreshadow_add(name: str, body: ForeshadowIn) -> Project:
    p = _load(name)
    _not_auto(name)
    foreshadows.add(p, body.description, body.episode, body.scope, body.due_ep, body.kind, body.public)
    return _save(name, p)


class ForeshadowEdit(BaseModel):
    description: str | None = None
    scope: str | None = None
    due_ep: int | None = None
    clear_due: bool = False
    kind: str | None = None
    public: bool | None = None


@app.put("/api/projects/{name}/foreshadows/{fid}")
def foreshadow_edit(name: str, fid: str, body: ForeshadowEdit) -> Project:
    p = _load(name)
    _not_auto(name)
    foreshadows.update(p, fid, body.description, body.scope, body.due_ep, body.clear_due, body.kind, body.public)
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
    scope: str = "arc"  # 새 복선의 회수 범위
    due_ep: int | None = None  # 새 복선의 회수 예정 화


@app.post("/api/projects/{name}/foreshadows/clues")
def foreshadow_clue(name: str, body: ClueIn) -> Project:
    """본문에서 고른 문장을 복선에 건다. 작가 입력이라 승인 단계 없이 저장한다."""
    p = _load(name)
    _not_auto(name)
    if not body.foreshadow and body.kind == "payoff":
        raise ValueError("회수할 복선을 골라 주세요")
    fid = body.foreshadow or foreshadows.add(p, body.description, body.episode, body.scope, body.due_ep).id
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



# ---------- 큐 시트 집필 실험 (canon/cue.py, 사이드바 '본편과 분리') ----------
# 작품에 저장하지 않는다. 큐 시트와 조건별 본문은 cuelab/<화>.json, AI 작업은 POST /jobs 의 cue_sheet · cue_run.

class CueEstimateIn(BaseModel):
    conditions: list[str] = []


def _cue_labels() -> dict:
    """화면 이름: 조건과 큐 칸 값 (prompts.CUE_* 의 화면 이름)."""
    pick = lambda d: [{"key": k, "label": v[0], "about": v[1]} for k, v in d.items()]  # noqa: E731
    return {"conditions": [{"key": k, "label": v, "about": cue.ABOUT[k]} for k, v in cue.CONDITIONS.items()],
            "functions": pick(prompts.CUE_FUNCTIONS), "tempos": pick(prompts.CUE_TEMPOS),
            "voices": pick(prompts.CUE_VOICES), "cadences": pick(prompts.CUE_CADENCES),
            "max_cues": cue.MAX_CUES, "max_lines": cue.MAX_LINES}


@app.get("/api/projects/{name}/cue")
def cue_home(name: str) -> dict:
    """큐 시트 실험 화면: 시험할 수 있는 화, 실험 파일이 있는 화, 화면 이름, 지난 실험(실험 기록 kind cue, 최근 10개)."""
    p = _load(name)
    runs = [r for r in research.history(name, 200) if r.get("kind") == "cue"][:10]
    return {"candidates": cue.candidates(p), "labs": store.cuelab_episodes(name), "runs": runs, **_cue_labels()}


@app.get("/api/projects/{name}/cue/{n}")
def cue_lab(name: str, n: int) -> dict:
    """n화 큐 시트와 조건별 본문 · 채점."""
    p = _load(name)
    p.episode(n)
    return cue.view(name, p, n)


@app.put("/api/projects/{name}/cue/{n}/sheet")
def cue_put_sheet(name: str, n: int, body: CueSheetDraft) -> dict:
    """작가가 고친 큐 시트를 저장한다."""
    p = _load(name)
    p.episode(n)
    cue.with_lock(name, n, lambda lab: cue.set_sheet(lab, body, p))
    return cue.view(name, p, n)


@app.post("/api/projects/{name}/cue/{n}/sheet/board")
def cue_board_sheet(name: str, n: int) -> dict:
    """AI 없이 스토리보드 장면(없으면 플롯 사건)마다 큐 하나인 뼈대를 만든다. 지금 시트를 덮는다."""
    p = _load(name)
    cue.check_episode(p, n)
    sheet = cue.from_board(p, n)
    cue.with_lock(name, n, lambda lab: cue.set_sheet(lab, sheet, p, by="board"))
    return cue.view(name, p, n)


@app.post("/api/projects/{name}/cue/{n}/estimate")
def cue_estimate(name: str, n: int, body: CueEstimateIn) -> dict:
    """쓰기 호출 수와 비용 추정. AI 를 부르지 않는다."""
    p = _load(name)
    return cue.estimate(p, n, store.load_cuelab(name, n).sheet, body.conditions or None)





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


@app.put("/api/projects/{name}/check-motion")
def set_check_motion(name: str, body: CheckWiden) -> Project:
    """동선 따로 보기 켜기 · 끄기 (Settings.check_motion). 자동 집필 검수도 따른다."""
    p = _load(name)
    p.settings.check_motion = body.on
    return _save(name, p)


@app.put("/api/projects/{name}/check-after-write")
def set_check_after_write(name: str, body: CheckWiden) -> Project:
    """쓴 뒤 바로 검수 켜기 · 끄기 (Settings.check_after_write). 웹 쓰기 작업만 따른다."""
    p = _load(name)
    p.settings.check_after_write = body.on
    return _save(name, p)


@app.put("/api/projects/{name}/check-scope")
def set_check_scope(name: str, body: CheckWiden) -> Project:
    """다시 검수는 바뀐 문단만 새로 짚기 켜기 · 끄기 (Settings.check_scope). 자동 집필 검수도 따른다."""
    p = _load(name)
    p.settings.check_scope = body.on
    return _save(name, p)


@app.put("/api/projects/{name}/stage-extract")
def set_stage_extract(name: str, body: CheckWiden) -> Project:
    """검수 때 함께 뽑기 켜기 · 끄기 (Settings.stage_extract). 자동 집필 검수도 따른다."""
    p = _load(name)
    p.settings.stage_extract = body.on
    return _save(name, p)


class BoardSetting(BaseModel):
    on: bool


@app.put("/api/projects/{name}/storyboard-setting")
def set_storyboard_setting(name: str, body: BoardSetting) -> Project:
    """화별 스토리보드 켜기 · 끄기 (Settings.storyboard). 켜면 쓰기 프롬프트에 직전 화 본문 전체가 들어간다."""
    p = _load(name)
    p.settings.storyboard = body.on
    return _save(name, p)


class WriteMaterial(BaseModel):
    mode: Literal["", "scenes", "fixed"]


@app.put("/api/projects/{name}/write-material")
def set_write_material(name: str, body: WriteMaterial) -> Project:
    """쓰기 재료의 양 (Settings.write_material). fixed 면 스토리보드 장면 · 큐 시트를 빼고 고정점만 넣는다 (board.fixed_only)."""
    p = _load(name)
    p.settings.write_material = body.mode
    return _save(name, p)


@app.put("/api/projects/{name}/cue-setting")
def set_cue_setting(name: str, body: BoardSetting) -> Project:
    """화별 큐 시트 켜기 · 끄기 (Settings.cue_sheet). 켜면 쓰기 전에 큐 시트를 만들어 쓰기 프롬프트 끝에 넣는다."""
    p = _load(name)
    p.settings.cue_sheet = body.on
    return _save(name, p)


@app.put("/api/projects/{name}/recent-echoes")
def set_recent_echoes(name: str, body: BoardSetting) -> Project:
    """장편 쓰기 요청의 '최근 화에서 되풀이한 구절' 블록 켜기 · 끄기 (Settings.recent_echoes, prompts.echo_block)."""
    p = _load(name)
    p.settings.recent_echoes = body.on
    return _save(name, p)


class KeepSnapshots(BaseModel):
    on: bool


@app.put("/api/projects/{name}/keep-snapshots")
def set_keep_snapshots(name: str, body: KeepSnapshots) -> Project:
    """장편 스냅샷 모두 남기기 켜기 · 끄기 (Settings.keep_snapshots). 끄면 다음 반영 때 오래된 스냅샷을 지운다."""
    p = _load(name)
    p.settings.keep_snapshots = body.on
    return _save(name, p)


class TimelineSetting(BaseModel):
    on: bool


@app.put("/api/projects/{name}/timeline-setting")
def set_timeline_setting(name: str, body: TimelineSetting) -> Project:
    """작품 속 시간 기록 켜기 · 끄기 (Timeline.enabled). 끄면 상태 변경안에 시점을 적지 않고 쓰기 · 검수에 시간 블록을 넣지 않는다."""
    p = _load(name)
    p.timeline.enabled = body.on
    return _save(name, p)


class StatPromptIn(BaseModel):
    mode: Literal["json", "lines", "none"]


@app.put("/api/projects/{name}/stat-prompt")
def set_stat_prompt(name: str, body: StatPromptIn) -> Project:
    """쓰기 프롬프트에 상태창 수치를 넣는 방식 (StatWindow.prompt: json · lines · none, statwin.write_rule)."""
    p = _load(name)
    p.stat_window.prompt = body.mode
    return _save(name, p)


class ModelPresetIn(BaseModel):
    preset: str = ""  # 단계 프리셋 id (settings.presets). 비우면 전체 설정을 따른다


@app.put("/api/projects/{name}/model-preset")
def set_model_preset(name: str, body: ModelPresetIn) -> Project:
    """작품이 쓸 단계 프리셋을 고른다. 이 작품의 AI 호출은 그 프리셋의 단계별 백엔드 · 모델을 쓴다 (settings.project_preset)."""
    preset = body.preset.strip()
    if preset and not settings.find_preset(preset):
        raise HTTPException(404, "그 프리셋이 없어요")
    p = _load(name)
    p.settings.model_preset = preset
    return _save(name, p)


def _play_basis(p: Project) -> PlayBasis:
    names: dict[str, str] = {}
    for c in p.characters:
        names.setdefault(c.id, c.name)
    return PlayBasis(names=names, days=[(e.plot.number, e.time.day) for e in p.episodes])


def _play_days(p: Project, info: PlayInfo) -> int:
    return _days_after(_play_basis(p).days, info)


def _days_after(days: list[tuple[int, int]], info: PlayInfo) -> int:
    day = max((d for n, d in days if n > info.world_ep), default=0)
    return max(0, day - info.start_day) if day else 0


def _play_card(b: PlayBasis, info: PlayInfo) -> PlayCard:
    who = b.names.get(info.player, info.player)
    return PlayCard(world=info.world, title=info.title or f"{who}의 삶", player=who, origin=info.origin, ending=info.ending,
                    turns=len(info.turns), decisions=sum(t.kind in play.DECIDED for t in info.turns), days=_days_after(b.days, info),
                    waiting=play.waiting(info) and not info.ending)


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




# ---------- 기능별 라우트 (canon/routes/) ----------
# 각 모듈은 위의 도우미를 web 에서 불러 쓰므로 맨 끝 가까이에서 부른다. 시험이 web 을 다시 불러오면(reload) 라우트 모듈도 다시 불러온다.
# 모듈이 정한 이름은 web 에도 둔다(web.<이름> 으로 부르는 코드와 시험이 그대로 돈다). 붙이는 차례는 옮기기 전 web.py 의 차례다
ROUTES = ("studio", "promptlab", "refs", "atlas", "revlab", "soelab", "play", "research")


_ROUTERS: list = []  # 붙인 라우트 모듈의 router. app.routes 에는 감싼 모양(_IncludedRouter)으로만 들어간다


def _attach_routes() -> None:
    import importlib
    import sys

    for mod in ROUTES:
        full = f"{__package__}.routes.{mod}"
        m = importlib.reload(sys.modules[full]) if full in sys.modules else importlib.import_module(full)
        app.include_router(m.router)
        _ROUTERS.append(m.router)
        globals().update({k: getattr(m, k) for k in m.EXPORTS})


_attach_routes()


# ---------- 화면 ----------

NO_CACHE = {"Cache-Control": "no-cache"}  # 쓰기 전에 매번 ETag 로 새 판인지 묻는다 (안 바뀌었으면 304)


class _Static(StaticFiles):
    """화면 파일. 서버를 업데이트한 뒤에도 브라우저가 캐시의 옛 화면 코드를 쓰지 않게 한다."""

    def file_response(self, *args, **kwargs) -> Response:
        r = super().file_response(*args, **kwargs)
        r.headers.update(NO_CACHE)
        return r


app.mount("/static", _Static(directory=STATIC), name="static")


# 화면 스크립트 묶음. index.html 의 /static/*.js 태그 68개를 파일을 이은 스크립트 하나로 바꿔 보낸다 (요청과 재확인이 하나로 준다).
# 주소에 내용 해시가 있어 오래 캐시해도 된다. 파일을 고치면(서버는 화면 파일을 디스크에서 바로 읽는다) 해시와 주소가 바뀐다.
# 모두 일반 스크립트라 전역을 함께 쓰고, 따로 읽을 때와 차례가 같다. CANON_NO_BUNDLE=1 이면 파일마다 따로 보낸다 (고칠 때 오류 위치 보기)
_SCRIPT_TAG = re.compile(r'<script src="/static/([A-Za-z0-9_./-]+\.js)"></script>\n?')
_bundle_cache: dict[str, Any] = {}


def _bundle() -> tuple[str, str, str]:
    """(묶은 index.html, 해시, 묶은 스크립트). 화면 파일의 판(수정 시각 · 크기)이 같으면 전에 만든 것을 쓴다."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    files = _SCRIPT_TAG.findall(html)
    sig = (html, tuple((f, (st := (STATIC / f).stat()).st_mtime_ns, st.st_size) for f in files))
    if _bundle_cache.get("sig") != sig:
        body = "".join(f"/* ---------- {f} ---------- */\n{(STATIC / f).read_text(encoding='utf-8')}\n;\n" for f in files)
        h = hashlib.sha1(body.encode()).hexdigest()[:16]
        first = True

        def one(m: re.Match) -> str:
            nonlocal first
            if first:
                first = False
                return f'<script src="/bundle/{h}.js"></script>\n'
            return ""
        _bundle_cache.update(sig=sig, out=(_SCRIPT_TAG.sub(one, html), h, body))
    return _bundle_cache["out"]


@app.get("/")
def index() -> Response:
    if os.environ.get("CANON_NO_BUNDLE"):
        return FileResponse(STATIC / "index.html", headers=NO_CACHE)
    return Response(_bundle()[0], media_type="text/html; charset=utf-8", headers=NO_CACHE)


@app.get("/bundle/{h}.js")
def script_bundle(h: str) -> Response:
    """묶은 화면 스크립트. 지금 판의 해시면 오래 캐시하고, 옛 해시면(그 사이 파일을 고쳤다) 지금 판을 캐시하지 않고 보낸다."""
    _, now, body = _bundle()
    cache = {"Cache-Control": "public, max-age=31536000, immutable"} if h == now else NO_CACHE
    return Response(body, media_type="text/javascript; charset=utf-8", headers=cache)


# 작품 전체를 돌려주는 응답도 스냅샷은 화 번호만 보낸다 (get_project 와 같은 모양). 장편은 스냅샷이 작품의 절반 가까이라
# 반영 같은 저장 응답이 크게 준다. 경로를 모두 만든 뒤 응답 모양을 바꾸고 처리기를 다시 만든다
_SNAPSHOT_LIGHT = {"snapshots": {"__all__": set(Snapshot.model_fields) - {"episode"}}}
for _route in [*app.routes, *(r for rt in _ROUTERS for r in rt.routes)]:
    if isinstance(_route, APIRoute) and _route.response_model in (Project, FixBatchOut):
        _route.response_model_exclude = _SNAPSHOT_LIGHT if _route.response_model is Project else {"project": _SNAPSHOT_LIGHT}
        _route.app = request_response(_route.get_route_handler())



def _drain(should_exit: Callable[[], bool], limit: float | None = None, tick: float = 1) -> bool:
    """다시 시작하기 전에 처리 중인 요청과 도는 작업이 끝나기를 기다린다. 그동안 새 작업은 받지 않는다(jobs.Draining).
    자동 집필은 다음 단계 전에 멈추고 다시 시작한 서버가 이어 간다. 다 끝났으면 True,
    jobs.DRAIN_LIMIT 초를 넘겨 그대로 다시 시작하면 False."""
    log = logging.getLogger("canon")
    jobs.draining.set()
    limit = jobs.DRAIN_LIMIT if limit is None else limit
    deadline = time.monotonic() + limit
    while not should_exit():
        try:
            left = _active + jobs.running()
        except Exception:  # 세다 오류가 나도 기다림은 이어 간다 (기한은 지킨다)
            log.exception("[업데이트] 도는 작업을 세다 오류가 났어요")
            left = 1
        if not left:
            return True
        if time.monotonic() >= deadline:
            log.warning("[업데이트] %d분을 기다려도 요청 · 작업 %d개가 끝나지 않아 그대로 다시 시작해요", round(limit / 60), left)
            return False
        time.sleep(tick)
    return True

def serve(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = False,
          update_interval: float = 0) -> None:
    """update_interval(초)이 0보다 크면 그 간격으로 origin/main 을 확인하고,
    새 코드를 받으면 진행 중인 요청이 끝난 뒤 다시 시작한다."""
    import threading
    import time
    import webbrowser

    import uvicorn

    from . import updater

    log = logging.getLogger("canon")
    if not logging.getLogger().handlers:  # 서버 로그(journalctl)에 시각과 수준을 붙인다. 시험 · 다른 프로그램이 정한 설정은 그대로 둔다
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
        updater.watching = True
        while not server.should_exit:
            updater.wake.wait(update_interval)  # POST /api/update/check 가 깨우면 바로 확인한다
            updater.wake.clear()
            r = updater.update()
            if not r.updated:
                if r.message != last:  # 같은 사유를 매번 찍지 않는다
                    log.info("[업데이트] %s", r.message)
                last = r.message
                continue
            log.info("[업데이트] %s. 진행 중인 작업이 끝나면 다시 시작해요", r.message)
            _drain(lambda: server.should_exit)
            restart.set()
            server.should_exit = True
            return

    def watch_safely() -> None:
        # 확인 중 오류가 나도 감시를 이어 간다. 스레드가 끝나면 다시 시작하지 못하고 draining 이 남는다
        while not server.should_exit:
            try:
                watch_updates()
                return
            except Exception:
                log.exception("[업데이트] 새 코드를 확인하다 오류가 났어요")
                time.sleep(1)

    if open_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    if update_interval > 0:
        threading.Thread(target=watch_safely, daemon=True).start()
    for name in autorun.resume_all():
        log.info("[자동 집필] %s 을(를) 이어 가요", name)
    server.run()
    if restart.is_set():
        updater.restart(no_browser=True)
