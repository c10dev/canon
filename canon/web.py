"""웹 UI 서버. `python -m canon serve` 로 실행한다.

CLI 와 같은 store / pipeline / prompts 를 그대로 쓰고, 화면은 canon/static/ 의 정적 파일이다.
AI 가 만든 제안(설정, 문체, 구조, 상태 변경안)은 바로 저장하지 않고 돌려주며,
사용자가 화면에서 고르거나 고친 뒤 저장 요청을 보낼 때 반영한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import dynamics, genres, library, pipeline, prompts, settings, store
from .llm import GeminiLLM, get_llm
from .schema import ArcPlan, Meta, Project, SetupSuggestion, StateDelta, StyleEntry, StyleProfile

STATIC = Path(__file__).parent / "static"
NAME_RE = re.compile(r"^[^/\\.][^/\\]{0,63}$")

app = FastAPI(title="Canon")
_active = 0  # 처리 중인 요청 수. 자동 업데이트는 이 값이 0일 때만 다시 시작한다.


@app.middleware("http")
async def _count_active(request: Request, call_next):
    global _active
    _active += 1
    try:
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


def _save(name: str, p: Project) -> Project:
    store.save(name, p)
    return p


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


@app.put("/api/config")
def put_config(body: SettingsIn) -> dict:
    if body.provider is not None and body.provider not in ("gemini", "mock"):
        raise HTTPException(400, "provider 는 gemini 또는 mock 입니다")
    settings.update(provider=body.provider, model=body.model, api_key=body.api_key, clear_key=body.clear_key)
    return settings.public()


@app.post("/api/config/test")
def test_config() -> dict:
    """키와 모델로 Gemini 에 연결되는지 확인한다. 본문 생성 비용은 들지 않는다."""
    if settings.provider()[0] == "mock":
        return {"ok": True, "message": "mock 모드입니다. 실제 AI 를 호출하지 않습니다."}
    llm = GeminiLLM()
    try:
        llm.check()
    except Exception as e:  # SDK 오류 종류가 많아 메시지만 보여준다
        raise HTTPException(400, f"연결 실패: {getattr(e, 'message', None) or e}")
    return {"ok": True, "message": f"{llm.model} 에 연결됐습니다."}


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
def put_project(name: str, p: Project) -> Project:
    """화면에서 고친 프로젝트 전체를 저장한다. 구조(arc)가 있으면 화수와 맞는지 검사한다."""
    _load(name)
    if p.arc:
        pipeline.validate_arc(ArcPlan(acts=p.arc), p.meta.target_episodes)
    pipeline._init_states(p)
    p.meta.genre = genres.label(p.meta)
    if p.snapshot(0) is None:  # 첫 반영 전에는 설정 화면의 시작 호감이 시작 관계다
        p.ties = []
        dynamics.seed_ties(p)
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
    update: bool = False  # 새 항목 대신 연결된 항목을 갱신


@app.post("/api/projects/{name}/style/library")
def keep_style(name: str, body: StyleKeep) -> dict:
    """작품의 지금 문체를 라이브러리에 저장한다 (작품 화면에서 저장한 뒤 부른다)."""
    p = _load(name)
    if body.update:
        e = library.push_project(p)
    else:
        e = library.from_project(p, body.name or f"{p.meta.title or name} 문체", body.sample, body.source)
        if body.sample.strip():  # 웹에서 분석한 원문의 기준 지표를 작품에도 남긴다
            p.style_baseline = e.baseline
        _save(name, p)
    return {"entry": library.summary(e), "project": p}


# ---------- 문체 라이브러리 ----------

class StyleIn(BaseModel):
    name: str
    source: str = ""
    notes: str = ""
    sample: str = ""
    profile: StyleProfile = StyleProfile()


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
    return pipeline.analyze_style(get_llm(), body.text)


@app.post("/api/styles")
def create_style(body: StyleIn) -> StyleEntry:
    return library.create(body.name, body.profile, body.sample, body.source, body.notes)


@app.get("/api/styles/{sid}")
def get_style(sid: str) -> dict:
    e = library.load(_style_id(sid))
    return {**e.model_dump(), "used_by": library.used_by(sid)}


@app.put("/api/styles/{sid}")
def put_style(sid: str, body: StyleIn) -> dict:
    e = library.update(_style_id(sid), body.name, body.profile, body.sample, body.source, body.notes)
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
            while _active and not server.should_exit:
                time.sleep(1)
            restart.set()
            server.should_exit = True
            return

    if open_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    if update_interval > 0:
        threading.Thread(target=watch_updates, daemon=True).start()
    server.run()
    if restart.is_set():
        updater.restart(no_browser=True)
