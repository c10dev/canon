"""문단 연습장 (canon/studio.py, 작품 밖 화면 #/studio) 라우트. canon/web.py 에서 옮겼다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .. import jobs, pipeline, studio, usage
from ..llm import get_llm
from ..schema import SceneCard, StudioSession

router = APIRouter()

# 한 문단짜리 장면을 상황 카드로 AI 에게 여러 안 쓰게 하거나 작가가 직접 써 본다. 저장은 작품 밖 <CANON_HOME>/.studio/.
# 화면은 AI 호출 넷(AI 안 쓰기 · 박자 짚기 · 다른 상황 · 독자로 읽기)을 백그라운드 작업(POST /studio/<id>/jobs)으로 부른다 (UX 02c).
# 작품 밖이라 작업 목록의 project 자리는 STU_JOBS 이고 대상(target)은 세션 id 다. 옛 동기 경로는 시험이 쓰는 동안 남긴다.
STU_JOBS = ".studio"  # 작업 목록의 project 자리 (작품 폴더는 점으로 시작하지 않아 겹치지 않는다). 화면은 '문단 연습장'으로 보인다

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


class StudioJobIn(BaseModel):
    kind: Literal["draft", "anatomy", "variants", "reader"]
    n: int = 3  # draft: 쓸 AI 안 수
    k: int = 4  # variants: 받을 상황 수
    no: int = 0  # reader: 점검할 시도 번호


@router.post("/api/studio/{sid}/jobs")
def studio_job(sid: str, body: StudioJobIn) -> dict:
    """문단 연습장의 AI 호출을 작업으로 돌린다 (작업 종류 stu_<kind>, 대상은 세션 id, reader 는 화 자리에 시도 번호).
    결과는 옛 동기 경로처럼 세션 파일에 남기고, 쓰는 동안 바뀐 세션을 덮지 않게 저장 직전에 다시 읽는다. 카드는 시작할 때 것을 쓴다."""
    s = _studio(sid)
    card, name = s.card, s.title or "문단 연습"
    kind, ep = f"stu_{body.kind}", None
    if body.kind == "draft":
        n = max(studio.DRAFTS[0], min(studio.DRAFTS[1], body.n))
        studio.room(s, n)  # 시도가 꽉 찼으면 여기서 바로 알린다
        llm = get_llm("write")
        label = f"{name} · AI 안 {n}개"

        def fn(job: jobs.Job):
            cands = pipeline.draft_paragraph(llm, card, n)
            q = studio.load(sid)
            studio.add_ai(q, cands, getattr(llm, "model", "") or "")
            studio.save(q)
            return {"sid": sid, "added": len(cands)}
    elif body.kind == "anatomy":
        if not card.model.strip():
            raise ValueError("본보기 문단이 없어요")
        llm = get_llm("plan")
        label = f"{name} · 구조 뜯어보기"

        def fn(job: jobs.Job):
            a = pipeline.anatomize_paragraph(llm, card)
            q = studio.load(sid)
            studio.set_anatomy(q, a)
            studio.save(q)
            return {"sid": sid, "lines": len(a.lines)}
    elif body.kind == "variants":
        llm = get_llm("plan")
        k = body.k
        label = f"{name} · 다른 상황"

        def fn(job: jobs.Job):
            vs = pipeline.vary_scene(llm, card, k)
            q = studio.load(sid)
            q.variants = vs
            studio.save(q)
            return {"sid": sid, "variants": len(vs)}
    else:
        try:
            text = studio.find(s, body.no).text
        except KeyError as e:
            raise HTTPException(404, str(e.args[0])) from None
        llm = get_llm("check")
        no, ep = body.no, body.no
        label = f"{name} · {no}번 시도 독자로 읽기"

        def fn(job: jobs.Job):
            r = pipeline.reader_check(llm, text)
            q = studio.load(sid)
            studio.set_reader(q, no, r)
            studio.save(q)
            return {"sid": sid, "no": no}
    try:
        with usage.scope(project="", episode=None, task="studio"):
            return jobs.start(STU_JOBS, kind, ep, label, fn, target=sid).public()
    except jobs.Busy as b:
        return {**b.job.public(), "already": True}


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
    "STU_JOBS",
    "StudioDraftIn",
    "StudioIn",
    "StudioJobIn",
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
