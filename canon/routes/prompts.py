"""프롬프트 관리 페이지 (작품 밖 화면 #/prompts) 라우트. 갈래 표(prompts.KINDS)와 조각 표(prompts.PIECES)를 보이고,
조립 보기가 있는 갈래는 견본 작품으로 요청을 조립해 조각마다 글을 붙인다. 견본은 놀이터의 예시 작품이 기본이고, 고른 작품은 읽기만 한다.
LLM 을 부르지 않고 아무것도 저장하지 않는다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import context, promptlab, prompts
from ..schema import Project

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


EXPORTS = (
    "prompt_kind",
    "prompt_kinds",
    "prompt_piece",
    "prompt_topic",
)
