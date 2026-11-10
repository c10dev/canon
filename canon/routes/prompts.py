"""프롬프트 관리 페이지 (작품 밖 화면 #/prompts) 라우트. 갈래 표(prompts.KINDS)와 조각 표(prompts.PIECES)를 보이고,
조립 보기가 있는 갈래는 견본 작품으로 요청을 조립해 조각마다 글을 붙인다. 견본은 놀이터의 예시 작품이 기본이고, 고른 작품은 읽기만 한다.
실험 판(promptset.py)은 작품 밖에 저장하고, 견본 요청 · 놀이터 세션에만 끼운다. LLM 을 부르지 않는다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import context, promptlab, prompts, promptset
from ..schema import Project, PromptSet, PromptSetChange

router = APIRouter()

SERIAL = ":serial"  # 견본 고르기 값: 예시 장편. 빈 값은 예시 작품(단편), 그 밖은 작품 폴더 이름


def _kind_row(k: str) -> dict:
    v = prompts.KINDS[k]
    b = v.brief
    return {"id": k, "label": v.label, "group": v.group, "stage": v.stage, "system": v.system, "request": v.request,
            "response": v.response, "caller": v.caller, "pieces": list(v.pieces), "also": list(v.also), "view": v.view,
            "brief": {"need": b.need, "scope": b.scope, "form": b.form} if b else None}


def _piece_row(pid: str) -> dict:
    pc = prompts.PIECES[pid]
    return {"id": pid, "title": pc.title, "tags": list(pc.tags), "place": pc.place, "source": pc.source, "when": pc.when,
            "kinds": prompts.kinds_of(pid)}


def registry() -> dict:
    return {"kinds": [_kind_row(k) for k in prompts.KINDS], "pieces": [_piece_row(x) for x in prompts.PIECES],
            "tags": list(prompts.TAGS.items()), "places": list(prompts.PLACES.items()), "groups": list(prompts.KIND_GROUPS),
            "send": list(prompts.SEND_PIECES)}


def _sample(project: str, kind: str) -> tuple[Project, str]:
    """(견본 작품, 작품 이름). 장편에만 있는 갈래는 예시 작품 대신 예시 장편으로 조립한다."""
    b = prompts.KINDS[kind].brief
    if project and project != SERIAL:
        try:
            return promptlab._project(project), project
        except KeyError as e:
            raise HTTPException(404, str(e.args[0])) from None
    if project == SERIAL or (b and b.form == "serial"):
        return promptlab.example_serial(), SERIAL
    return promptlab.example_project(), ""


def _default_n(p: Project, project: str, kind: str) -> int:
    if kind in prompts.BRIEF_KINDS:  # 놀이터 불러오기와 같은 기본 화 (예시 장편 · 고른 작품은 default_n)
        return promptlab._default(p, project, kind)
    return max((e.plot.number for e in p.episodes if e.text), default=0)  # VIEW_NEED: 본문이 있는 마지막 화


def _pieces(p: Project, n: int, kind: str, system: str, prompt: str) -> list[dict]:
    out = []
    for pid in (*prompts.KINDS[kind].pieces, *prompts.SEND_PIECES):
        text = prompts.piece_text(p, n, pid, kind, prompt)
        if pid in prompts.SEND_PIECES:
            found = None  # 보내기 직전에 붙어 조립한 글에는 없다
        else:
            found = prompts.found_in(text, system, prompt) if text else None
        out.append({**_piece_row(pid), "text": text, "chars": len(text), "tokens": context.est_tokens(text) if text else 0,
                    "found": found})
    return out


def assemble(kind: str, project: str = "", n: int = 0) -> dict:
    """한 갈래의 조립 보기. 만들 수 없는 견본(장편 갈래를 단편에, 본문이 없는 화)은 error 에 까닭을 담는다."""
    p, project = _sample(project, kind)
    title = p.meta.title or project
    n = n or _default_n(p, project, kind)
    base = {"kind": _kind_row(kind), "sample": {"project": project, "title": title, "n": n, "serial": p.serial}}
    try:
        system, prompt, schema = prompts.view_request(p, n, kind)
    except (ValueError, KeyError) as e:
        return {**base, "error": str(e.args[0]) if e.args else str(e)}
    return {**base, "system": system, "prompt": prompt, "schema": schema.__name__ if schema else "",
            "chars": len(system) + len(prompt), "tokens": context.est_tokens(system + prompt),
            "pieces": _pieces(p, n, kind, system, prompt)}


def _sample_text(pid: str, project: str) -> tuple[str, str]:
    """조각 하나의 견본 글과 그 글을 조립한 갈래. 조립 보기가 있는 첫 갈래로 만든다. 없으면 상수 글 그대로."""
    pc = prompts.PIECES[pid]
    for k in prompts.kinds_of(pid):
        if not prompts.KINDS[k].view or pid.endswith("_req"):
            continue
        p, proj = _sample(project, k)
        n = _default_n(p, proj, k)
        try:
            return prompts.piece_text(p, n, pid, k), k
        except (ValueError, KeyError):
            continue
    v = prompts.resolve_name(pc.source)
    return (v if isinstance(v, str) else ""), ""


@router.get("/api/prompts/kinds")
def prompt_kinds() -> dict:
    """갈래 표 · 조각 표 · 주제 꼬리표 · 자리 이름."""
    return registry()


@router.get("/api/prompts/kinds/{kind}")
def prompt_kind(kind: str, project: str = "", n: int = 0) -> dict:
    """한 갈래. 조립 보기가 있으면 견본 작품(project 가 비면 예시 작품, ':serial' 이면 예시 장편)으로 요청을 조립한다."""
    if kind not in prompts.KINDS:
        raise HTTPException(404, f"모르는 프롬프트 갈래예요: {kind}")
    if not prompts.KINDS[kind].view:
        return {"kind": _kind_row(kind), "pieces": [_piece_row(x) for x in prompts.KINDS[kind].pieces]}
    return assemble(kind, project, n)


@router.get("/api/prompts/topics/{tag}")
def prompt_topic(tag: str, project: str = "") -> dict:
    """한 주제 꼬리표를 단 조각을 모든 갈래에서 모은다. 조각마다 견본 글(조립 보기가 있는 첫 갈래로 만든 것)을 붙인다."""
    if tag not in prompts.TAGS:
        raise HTTPException(404, f"모르는 주제예요: {tag}")
    rows = []
    for pid, pc in prompts.PIECES.items():
        if tag not in pc.tags:
            continue
        text, made = ("", "") if pid.endswith("_req") else _sample_text(pid, project)
        rows.append({**_piece_row(pid), "text": text, "chars": len(text), "sample_kind": made})
    return {"tag": tag, "label": prompts.TAGS[tag], "pieces": rows}


@router.get("/api/prompts/pieces/{piece}")
def prompt_piece(piece: str, project: str = "") -> dict:
    if piece not in prompts.PIECES:
        raise HTTPException(404, f"모르는 프롬프트 조각이에요: {piece}")
    text, made = ("", "") if piece.endswith("_req") else _sample_text(piece, project)
    return {**_piece_row(piece), "text": text, "chars": len(text), "sample_kind": made}


# ---------- 실험 판 ----------

class PromptSetIn(BaseModel):
    name: str = ""
    kind: str = "episode"
    changes: list[PromptSetChange] = Field(default_factory=list)
    note: str = ""


class PromptSetOpenIn(BaseModel):
    project: str = ""  # 비면 예시 작품, ':serial' 은 예시 장편
    n: int = 0
    blind: bool = True  # 원래 판과 함께 돌려 블라인드로 견준다


def _set(sid: str) -> PromptSet:
    try:
        return promptset.load(sid)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


def _set_row(ps: PromptSet) -> dict:
    return {**ps.model_dump(), "kind_label": prompts.KINDS[ps.kind].label if ps.kind in prompts.KINDS else ps.kind,
            "missing": [c.piece for c in ps.changes if c.piece not in prompts.PIECES]}


def editable(kind: str) -> list[str]:
    """실험 판에서 바꿀 수 있는 그 갈래의 조각: 보내기 직전 줄과 요청 전체를 만드는 조각은 뺀다."""
    return [x for x in prompts.KINDS[kind].pieces if prompts.PIECES[x].place not in promptset.FIXED_PLACES and not x.endswith("_req")]


def set_preview(ps: PromptSet, project: str = "", n: int = 0) -> dict:
    """판을 고른 갈래의 견본 요청에 끼운 글. 원래 글 · 끼운 글 · 조각마다 결과(바꿈 · 같음 · 이 견본에 없음 · 없는 조각)와 고를 수 있는 조각."""
    kind = ps.kind if ps.kind in prompts.KINDS and prompts.KINDS[ps.kind].view else "episode"
    p, project = _sample(project, kind)
    n = n or _default_n(p, project, kind)
    base = {"set": _set_row(ps), "kind": _kind_row(kind), "sample": {"project": project, "title": p.meta.title or project, "n": n, "serial": p.serial}}
    try:
        system, prompt, _ = prompts.view_request(p, n, kind)
    except (ValueError, KeyError) as e:
        return {**base, "error": str(e.args[0]) if e.args else str(e)}
    new_system, new_prompt, rows = promptset.apply(p, n, kind, system, prompt, ps)
    pieces = [{"id": x, "title": prompts.PIECES[x].title, "place": prompts.PIECES[x].place, "text": prompts.piece_text(p, n, x, kind, prompt)}
              for x in editable(kind)]
    return {**base, "original": {"system": system, "prompt": prompt}, "applied": {"system": new_system, "prompt": new_prompt},
            "rows": rows, "pieces": pieces, "chars": len(new_system) + len(new_prompt), "tokens": context.est_tokens(new_system + new_prompt)}


@router.get("/api/promptsets")
def list_promptsets() -> dict:
    return {"sets": [_set_row(x) for x in promptset.sets()], "max_changes": promptset.MAX_CHANGES}


@router.post("/api/promptsets")
def create_promptset(body: PromptSetIn) -> dict:
    ps = promptset.create(body.name, body.kind)
    if body.changes:
        ps = promptset.update(ps.id, ps.name, ps.kind, body.changes, body.note)
    return _set_row(ps)


@router.get("/api/promptsets/{sid}")
def get_promptset(sid: str, project: str = "", n: int = 0) -> dict:
    """판과, 고른 갈래의 견본 요청에 끼운 미리보기."""
    return set_preview(_set(sid), project, n)


@router.put("/api/promptsets/{sid}")
def put_promptset(sid: str, body: PromptSetIn, project: str = "", n: int = 0) -> dict:
    _set(sid)
    return set_preview(promptset.update(sid, body.name, body.kind, body.changes, body.note), project, n)


@router.delete("/api/promptsets/{sid}")
def delete_promptset(sid: str) -> dict:
    _set(sid)
    promptset.delete(sid)
    return {"ok": True}


@router.post("/api/promptsets/{sid}/duplicate")
def duplicate_promptset(sid: str) -> dict:
    _set(sid)
    return _set_row(promptset.duplicate(sid))


@router.post("/api/promptsets/{sid}/playground")
def open_promptset(sid: str, body: PromptSetOpenIn) -> dict:
    """판을 끼운 프롬프트로 새 놀이터 세션을 만든다 (promptlab.load_prompt). blind 면 원래 판도 함께 돌려 가려 읽는다."""
    ps = _set(sid)
    s = promptlab.create()
    try:
        promptlab.load_prompt(s, ps.kind, body.project, body.n, ps.id, body.blind)
    except Exception:
        promptlab.delete(s.id)  # 불러오지 못하면 빈 세션을 남기지 않는다
        raise
    return promptlab.view(promptlab.save(s))


EXPORTS = (
    "create_promptset",
    "delete_promptset",
    "duplicate_promptset",
    "get_promptset",
    "list_promptsets",
    "open_promptset",
    "prompt_kind",
    "prompt_kinds",
    "prompt_piece",
    "prompt_topic",
    "put_promptset",
)
