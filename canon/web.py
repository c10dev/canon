"""웹 UI 서버. `python -m canon serve` 로 실행한다.

CLI 와 같은 store / pipeline / prompts 를 그대로 쓰고, 화면은 canon/static/ 의 정적 파일이다.
AI 가 만든 제안(설정, 문체, 구조, 상태 변경안)은 바로 저장하지 않고 돌려주며,
사용자가 화면에서 고르거나 고친 뒤 저장 요청을 보낼 때 반영한다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import pipeline, prompts, store
from .llm import get_llm
from .schema import ArcPlan, Meta, Project, SetupSuggestion, StateDelta, StyleProfile

STATIC = Path(__file__).parent / "static"
NAME_RE = re.compile(r"^[^/\\.][^/\\]{0,63}$")

app = FastAPI(title="Canon")


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


def _save(name: str, p: Project) -> Project:
    store.save(name, p)
    return p


# ---------- 프로젝트 ----------

class NewProject(BaseModel):
    name: str
    meta: Meta


@app.get("/api/config")
def config() -> dict:
    provider = os.environ.get("CANON_LLM", "gemini").lower()
    return {
        "provider": provider,
        "model": "mock" if provider == "mock" else os.environ.get("CANON_MODEL", "gemini-2.5-pro"),
        "has_key": provider == "mock" or bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
    }


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
    return _save(name, p)


@app.get("/api/projects/{name}")
def get_project(name: str) -> Project:
    return _load(name)


@app.put("/api/projects/{name}")
def put_project(name: str, p: Project) -> Project:
    """화면에서 고친 프로젝트 전체를 저장한다. 구조(arc)가 있으면 화수와 맞는지 검사한다."""
    _load(name)
    if p.arc:
        pipeline.validate_arc(ArcPlan(acts=p.arc), p.meta.target_episodes)
    pipeline._init_states(p)
    return _save(name, p)


# ---------- 1. 설정 도우미 ----------

@app.post("/api/projects/{name}/suggest")
def suggest(name: str) -> SetupSuggestion:
    return pipeline.suggest_setup(get_llm(), _load(name))


@app.post("/api/projects/{name}/suggest/apply")
def apply_suggestion(name: str, s: SetupSuggestion) -> Project:
    p = _load(name)
    pipeline.apply_setup(p, s)
    return _save(name, p)


# ---------- 2. 문체 ----------

class Sample(BaseModel):
    text: str


@app.post("/api/projects/{name}/style")
def analyze_style(name: str, body: Sample) -> StyleProfile:
    _load(name)
    if len(body.text.strip()) < 200:
        raise HTTPException(400, "예시 원문은 200자 이상 넣어 주세요")
    return pipeline.analyze_style(get_llm(), body.text)


# ---------- 3. 구조와 플롯 ----------

@app.post("/api/projects/{name}/arc")
def plan_arc(name: str) -> ArcPlan:
    return pipeline.plan_arc(get_llm(), _load(name))


class Range(BaseModel):
    start: int | None = None
    end: int | None = None


@app.post("/api/projects/{name}/plots")
def draft_plots(name: str, r: Range) -> Project:
    """확정되지 않은 화만 새 초안으로 바꾼다."""
    p = _load(name)
    batch = pipeline.draft_plots(get_llm(), p, r.start or 1, r.end or p.meta.target_episodes)
    pipeline.apply_plots(p, batch)
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


# ---------- 4. 본문 ----------

@app.post("/api/projects/{name}/episodes/{n}/write")
def write_episode(name: str, n: int) -> Project:
    p = _load(name)
    text = pipeline.write_episode(get_llm(), p, n)
    ep = p.episode(n)
    ep.text, ep.status = text, "written"
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
    ep.text = body.text.strip()
    ep.status = "written" if ep.text else "confirmed"
    return _save(name, p)


@app.get("/api/projects/{name}/episodes/{n}/context")
def context(name: str, n: int) -> list[dict]:
    """본문 생성에 들어가는 컨텍스트를 섹션별 글자 수로 보여준다."""
    p = _load(name)
    text = prompts.build_episode_context(p, n)
    out = []
    for block in re.split(r"^# ", text, flags=re.M):
        if block.strip():
            title, _, body = block.partition("\n")
            out.append({"title": title.strip(), "chars": len(body.strip())})
    return out


@app.get("/api/projects/{name}/episodes/{n}/prompt")
def prompt(name: str, n: int) -> dict:
    p = _load(name)
    return {"system": prompts.SYSTEM_WRITER, "prompt": prompts.episode_prompt(p, n)}


# ---------- 5. 상태 변경안 ----------

@app.post("/api/projects/{name}/episodes/{n}/state")
def extract_state(name: str, n: int) -> StateDelta:
    return pipeline.extract_state(get_llm(), _load(name), n)


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
    ep = p.episode(n)
    if ep.status != "written":
        raise ValueError(f"{n}화는 본문이 작성된 상태가 아닙니다 (현재: {ep.status})")
    d.episode = n
    pipeline.apply_delta(p, d)
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


# ---------- 화면 ----------

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    print(f"Canon 웹 UI: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
