"""문단 연습장 (canon/studio.py, 작품 밖 화면 #/studio) 라우트. canon/web.py 에서 옮겼다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .. import pipeline, studio, usage
from ..llm import get_llm
from ..schema import SceneCard, StudioSession

router = APIRouter()

# 한 문단짜리 장면을 상황 카드로 AI 에게 여러 안 쓰게 하거나 작가가 직접 써 본다. 저장은 작품 밖 <CANON_HOME>/.studio/.
# AI 안은 짧은 요청이라 작업 목록을 거치지 않고 문체 예시(style_example)처럼 바로 돌려준다.

class StudioIn(BaseModel):
    title: str = ""
    card: SceneCard = SceneCard()


class StudioDraftIn(BaseModel):
    n: int = 3


class StudioTryIn(BaseModel):
    text: str
    base: int = 0  # 고쳐 쓴 시도 번호


class StudioTryEdit(BaseModel):
    text: str | None = None
    star: bool | None = None


def _studio(sid: str) -> StudioSession:
    try:
        return studio.load(sid)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


@router.get("/api/studio")
def list_studio() -> dict:
    return {"sessions": [studio.summary(x) for x in studio.sessions()], "drills": studio.drills(), "beats": studio.beats(),
            "length": list(studio.LENGTH), "max_tries": studio.MAX_TRIES, "variants": list(studio.VARIANTS)}


@router.post("/api/studio")
def create_studio(body: StudioIn) -> dict:
    return studio.view(studio.create(body.card, body.title))


@router.get("/api/studio/{sid}")
def get_studio(sid: str) -> dict:
    return studio.view(_studio(sid))


@router.put("/api/studio/{sid}")
def put_studio(sid: str, body: StudioIn) -> dict:
    _studio(sid)
    return studio.view(studio.update(sid, body.card, body.title))


@router.delete("/api/studio/{sid}")
def delete_studio(sid: str) -> dict:
    _studio(sid)
    studio.delete(sid)
    return {"ok": True}


@router.post("/api/studio/{sid}/duplicate")
def duplicate_studio(sid: str) -> dict:
    _studio(sid)
    return studio.view(studio.duplicate(sid))


@router.post("/api/studio/{sid}/draft")
def draft_studio(sid: str, body: StudioDraftIn) -> dict:
    """AI 안 n 개를 써서 시도로 남긴다. 쓰는 동안 바뀐 시도를 덮지 않게 저장 직전에 다시 읽는다."""
    s = _studio(sid)
    studio.room(s, max(studio.DRAFTS[0], min(studio.DRAFTS[1], body.n)))
    llm = get_llm("write")
    with usage.scope(task="studio"):
        cands = pipeline.draft_paragraph(llm, s.card, body.n)
    s = _studio(sid)
    studio.add_ai(s, cands, getattr(llm, "model", "") or "")
    return studio.view(studio.save(s))


class StudioVariantsIn(BaseModel):
    k: int = 4


@router.post("/api/studio/{sid}/anatomy")
def anatomy_studio(sid: str) -> dict:
    """본보기 문단을 문장마다 박자로 뜯어본다 (pipeline.anatomize_paragraph, plan 단계). 카드에는 적용하지 않는다."""
    s = _studio(sid)
    with usage.scope(task="studio"):
        a = pipeline.anatomize_paragraph(get_llm("plan"), s.card)
    s = _studio(sid)
    studio.set_anatomy(s, a)
    return studio.view(studio.save(s))


@router.post("/api/studio/{sid}/anatomy/apply")
def apply_anatomy_studio(sid: str) -> dict:
    """뜯어본 문장 차례 · 가릴 것 · 감각 전환을 카드에 적용한다."""
    s = _studio(sid)
    studio.apply_anatomy(s)
    s.card = studio.clean_card(s.card)
    return studio.view(studio.save(s))


@router.post("/api/studio/{sid}/variants")
def variants_studio(sid: str, body: StudioVariantsIn) -> dict:
    """같은 구조로 쓸 다른 상황을 받는다 (pipeline.vary_scene, plan 단계). 세션에는 마지막 제안만 둔다."""
    s = _studio(sid)
    with usage.scope(task="studio"):
        vs = pipeline.vary_scene(get_llm("plan"), s.card, body.k)
    s = _studio(sid)
    s.variants = vs
    return studio.view(studio.save(s))


@router.post("/api/studio/{sid}/variants/{i}")
def from_variant_studio(sid: str, i: int) -> dict:
    """고른 상황(0부터)으로 새 연습을 만든다. 원래 연습은 그대로 둔다."""
    _studio(sid)
    try:
        return studio.view(studio.from_variant(sid, i))
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


@router.post("/api/studio/{sid}/tries/{no}/reader")
def reader_studio(sid: str, no: int) -> dict:
    """시도 하나를 독자 질문으로 점검한다 (pipeline.reader_check, check 단계): 독자가 채울 것이 이미 적혀 있나."""
    s = _studio(sid)
    try:
        text = studio.find(s, no).text
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None
    with usage.scope(task="studio"):
        r = pipeline.reader_check(get_llm("check"), text)
    s = _studio(sid)
    studio.set_reader(s, no, r)
    return studio.view(studio.save(s))


@router.post("/api/studio/{sid}/tries")
def add_studio_try(sid: str, body: StudioTryIn) -> dict:
    s = _studio(sid)
    studio.add_author(s, body.text, body.base)
    return studio.view(studio.save(s))


@router.put("/api/studio/{sid}/tries/{no}")
def edit_studio_try(sid: str, no: int, body: StudioTryEdit) -> dict:
    s = _studio(sid)
    studio.edit(s, no, body.text, body.star)
    return studio.view(studio.save(s))


@router.delete("/api/studio/{sid}/tries/{no}")
def delete_studio_try(sid: str, no: int) -> dict:
    s = _studio(sid)
    studio.remove(s, no)
    return studio.view(studio.save(s))


EXPORTS = (
    "StudioDraftIn",
    "StudioIn",
    "StudioTryEdit",
    "StudioTryIn",
    "StudioVariantsIn",
    "_studio",
    "add_studio_try",
    "anatomy_studio",
    "apply_anatomy_studio",
    "create_studio",
    "delete_studio",
    "delete_studio_try",
    "draft_studio",
    "duplicate_studio",
    "edit_studio_try",
    "from_variant_studio",
    "get_studio",
    "list_studio",
    "put_studio",
    "reader_studio",
    "variants_studio",
)
