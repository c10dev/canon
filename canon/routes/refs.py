"""레퍼런스 원고 (canon/refs.py, 작품 밖) 라우트. canon/web.py 에서 옮겼다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from .. import refs
from ..schema import RefBook, RefCut, RefFile
from ..web import (  # web 의 공용 도우미
    _load,
)

router = APIRouter()

# 다른 소설 원고 txt 를 화 표시로 나눠 작품 밖에 둔다 (canon/refs.py). 작품에는 연결하지 않는다.

class RefSplitIn(BaseModel):
    text: str
    rule: str = ""  # 비우면 순서대로 고른다 (화 표시 줄 → 기호 줄 → 빈 줄 → 한 화)
    example: str = ""  # rule custom 의 예시 줄
    unit: str = ""  # 화 표시 단위를 고른다 (규칙 칩)
    strip_tails: bool = True
    files: list[int] = []  # 이어 넣은 파일마다 시작 줄


class RefCreateIn(BaseModel):
    name: str
    source: str = ""
    notes: str = ""
    rights: bool = False
    encoding: str = "utf-8"
    text: str
    rule: str = "heading"
    example: str = ""
    unit: str = ""
    common_head: str = ""
    strip_tails: bool = True
    cuts: list[RefCut] = []
    files: list[RefFile] = []


class RefPutIn(BaseModel):
    name: str | None = None
    source: str | None = None
    notes: str | None = None
    cuts: list[RefCut] | None = None
    strip_tails: bool | None = None
    rule: str | None = None
    example: str | None = None
    unit: str | None = None


class RefPickIn(BaseModel):
    eps: list[int]  # 고른 화의 차례 (1부터)


def _ref_id(rid: str) -> str:
    if not refs.exists(rid):
        raise HTTPException(404, f"레퍼런스 원고에 없는 항목이에요: {rid}")
    return rid


def _ref_view(b: RefBook) -> dict:
    return {**b.model_dump(exclude={"eps"}), "episodes": refs.episodes(b), "labels": refs.labels()}


@router.get("/api/refs")
def list_refs() -> dict:
    return {"refs": [refs.summary(b) for b in refs.entries()], "labels": refs.labels()}


@router.post("/api/refs/split")
def split_ref(body: RefSplitIn) -> dict:
    """경계 후보 미리보기 (저장하지 않는다, 원문을 돌려주지 않는다)."""
    return refs.preview(body.text, body.rule, body.example, body.unit, body.strip_tails, body.files)


class RefInboxIn(BaseModel):
    title: str = ""
    url: str = ""
    text: str


class RefInboxDelIn(BaseModel):
    ids: list[str] | None = None  # 비우면 모두 뺀다


EXT_DIR = Path(__file__).resolve().parent.parent / "extension"  # 크롬 확장 원본 (canon/extension)


@router.get("/api/refs/inbox")
def ref_inbox() -> dict:
    """크롬 확장이 보낸 화 (원고가 되기 전 대기열)."""
    return {"items": refs.inbox()}


@router.post("/api/refs/inbox")
def ref_inbox_add(body: RefInboxIn) -> dict:
    """크롬 확장이 화 하나를 보낸다. 다른 사이트의 쓰기 요청은 막지만 크롬 확장(chrome-extension://)은 이 주소만 받는다 (web._origin_ok)."""
    return refs.inbox_add(body.title, body.url, body.text)


@router.delete("/api/refs/inbox")
def ref_inbox_clear(body: RefInboxDelIn | None = None) -> dict:
    return {"count": refs.inbox_clear(body.ids if body else None)}


@router.get("/api/refs/extension.zip")
def ref_extension(canon: str = "") -> Response:
    """크롬 확장 묶음. canon 은 화면이 보낸 이 서버 주소이고, 확장의 기본 Canon 주소(config.js)로 넣는다."""
    parts = urlsplit(canon)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise HTTPException(400, "Canon 주소가 필요해요")
    origin = f"{parts.scheme}://{parts.netloc}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(EXT_DIR.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                data = f.read_bytes()
                if f.name == "config.js":
                    data = f"const CANON_DEFAULT = {json.dumps(origin)};\n".encode()
                z.writestr(f"canon-extension/{f.name}", data)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="canon-extension.zip"'})


@router.post("/api/refs")
def create_ref(body: RefCreateIn) -> dict:
    b = refs.create(body.name, body.text, body.cuts, body.source, body.notes, body.rights, body.encoding, body.rule,
                    body.example, body.unit, body.common_head, body.strip_tails, body.files)
    return _ref_view(b)


@router.get("/api/refs/{rid}")
def get_ref(rid: str) -> dict:
    return _ref_view(refs.load(_ref_id(rid)))


@router.put("/api/refs/{rid}")
def put_ref(rid: str, body: RefPutIn) -> dict:
    b = refs.update(_ref_id(rid), body.name, body.source, body.notes, body.cuts, body.strip_tails, body.rule, body.example, body.unit)
    return _ref_view(b)


@router.delete("/api/refs/{rid}")
def delete_ref(rid: str) -> dict:
    refs.delete(_ref_id(rid))
    return {"ok": True}


@router.get("/api/refs/{rid}/source")
def ref_source(rid: str) -> dict:
    """원문 전체 (경계 다시 고치기 화면이 브라우저에서 다시 나눠 본다)."""
    return {"text": "\n".join(refs.source(_ref_id(rid)))}


@router.get("/api/refs/{rid}/text")
def ref_text(rid: str, start: int = 0, end: int = 200) -> dict:
    return refs.text_range(_ref_id(rid), start, end)


@router.get("/api/refs/{rid}/eps/{order}")
def ref_episode(rid: str, order: int) -> dict:
    return {"order": order, "text": refs.episode_text(_ref_id(rid), order)}


@router.post("/api/refs/{rid}/sample")
def ref_sample(rid: str, body: RefPickIn) -> dict:
    """문체 만들기에 넣을 원문 (고른 화를 이어 SAMPLE_MAX 자까지). AI 를 부르지 않는다."""
    return refs.sample(_ref_id(rid), body.eps)


@router.post("/api/refs/{rid}/revlab")
def ref_revlab(rid: str, body: RefPickIn) -> dict:
    """고른 화로 역설계 실험을 만든다 (AI 를 부르지 않는다)."""
    return {"id": refs.to_revlab(_ref_id(rid), body.eps)}


@router.get("/api/refs/{rid}/compare")
def ref_compare(rid: str, project: str) -> dict:
    """원고 지표와 작품의 본문 있는 화 지표 (읽기만)."""
    return refs.compare(_ref_id(rid), _load(project))


EXPORTS = (
    "RefCreateIn",
    "RefInboxDelIn",
    "RefInboxIn",
    "RefPickIn",
    "RefPutIn",
    "RefSplitIn",
    "_ref_id",
    "_ref_view",
    "create_ref",
    "delete_ref",
    "get_ref",
    "list_refs",
    "put_ref",
    "ref_compare",
    "ref_episode",
    "ref_extension",
    "ref_inbox",
    "ref_inbox_add",
    "ref_inbox_clear",
    "ref_revlab",
    "ref_sample",
    "ref_source",
    "ref_text",
    "split_ref",
)
