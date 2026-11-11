"""레퍼런스 원고 (canon/refs.py, 작품 밖) 라우트. canon/web.py 에서 옮겼다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .. import jobs, refdigest, refs
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
    repeats: list[str] | None = None  # 뗄 되풀이 줄. 비우면(None) 찾은 줄을 모두 뗀다


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
    strip_repeats: list[str] = []
    cuts: list[RefCut] = []
    files: list[RefFile] = []


class RefPutIn(BaseModel):
    name: str | None = None
    source: str | None = None
    notes: str | None = None
    cuts: list[RefCut] | None = None
    strip_tails: bool | None = None
    strip_repeats: list[str] | None = None
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
    return refs.preview(body.text, body.rule, body.example, body.unit, body.strip_tails, body.files, body.repeats)


class RefInboxDelIn(BaseModel):
    ids: list[str] | None = None  # 비우면 모두 뺀다


REF_JOBS = ".refs"  # newto 가져오기 작업의 project 자리 (작품 폴더는 점으로 시작하지 않아 겹치지 않는다)


class RefNewtoIn(BaseModel):
    work: str  # newto 작품 번호


@router.get("/api/refs/inbox")
def ref_inbox() -> dict:
    """newto 로 가져온 화 (원고가 되기 전 대기열)와 newto 폴더가 있는지."""
    return {"items": refs.inbox(), "newto": refs.newto_dir() is not None}


@router.delete("/api/refs/inbox")
def ref_inbox_clear(body: RefInboxDelIn | None = None) -> dict:
    return {"count": refs.inbox_clear(body.ids if body else None)}


@router.post("/api/refs/newto")
def ref_newto(body: RefNewtoIn) -> dict:
    """newto 로 작품을 받는 작업(ref_newto)을 시작한다. 한 번에 하나만 돈다. 끝나면 합본의 화가 받은 화에 들어간다."""
    work = body.work.strip()
    if not refs.WORK_RE.match(work):
        raise HTTPException(400, "작품 번호는 숫자만 넣어 주세요")
    if refs.newto_dir() is None:
        raise HTTPException(400, "newto 폴더를 찾지 못했어요. CANON_NEWTO에 newto 폴더 경로를 넣어 주세요")
    try:
        job = jobs.start(REF_JOBS, "ref_newto", None, f"newto 가져오기 ({work})", lambda j: refs.newto_fetch(work, j))
    except jobs.Busy as b:
        return {**b.job.public(), "already": True}
    return job.public()


@router.post("/api/refs")
def create_ref(body: RefCreateIn) -> dict:
    b = refs.create(body.name, body.text, body.cuts, body.source, body.notes, body.rights, body.encoding, body.rule,
                    body.example, body.unit, body.common_head, body.strip_tails, body.files, body.strip_repeats)
    return _ref_view(b)


@router.get("/api/refs/{rid}")
def get_ref(rid: str) -> dict:
    return _ref_view(refs.load(_ref_id(rid)))


@router.put("/api/refs/{rid}")
def put_ref(rid: str, body: RefPutIn) -> dict:
    b = refs.update(_ref_id(rid), body.name, body.source, body.notes, body.cuts, body.strip_tails, body.rule, body.example, body.unit, body.strip_repeats)
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


class RefDigestAIIn(BaseModel):
    provider: str = ""  # 비우면 설정의 계획 단계를 따른다
    model: str = ""


@router.get("/api/refs/{rid}/digest")
def ref_digest_view(rid: str) -> dict:
    """화 카드: 읽힌 정도, 화마다 카드, 읽힐 AI (canon/refdigest.py). AI 를 부르지 않는다."""
    return refdigest.view(_ref_id(rid))


@router.get("/api/refs/{rid}/digest/estimate")
def ref_digest_estimate(rid: str) -> dict:
    """전체 읽히기의 호출 수와 비용 추정 (AI 를 부르지 않는다)."""
    return refdigest.estimate(_ref_id(rid))


@router.put("/api/refs/{rid}/digest/ai")
def ref_digest_ai(rid: str, body: RefDigestAIIn) -> dict:
    """이 원고를 읽힐 AI 를 고른다. 다음 읽히기부터 쓴다."""
    try:
        return refdigest.set_ai(_ref_id(rid), body.provider, body.model)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/refs/{rid}/digest")
def ref_digest_start(rid: str) -> dict:
    """전체 읽히기 작업(ref_digest)을 시작한다. 읽히지 않았거나 글이 바뀐 화만 읽힌다. 원고 하나에 하나만 돈다."""
    rid = _ref_id(rid)
    b = refs.load(rid)
    if not refdigest.state(b)["todo"]:
        raise HTTPException(400, "읽힐 화가 없어요. 모든 화가 지금 글로 읽혀 있어요")
    llm = refdigest.llm_for(rid)  # 키가 없으면 작업을 띄우기 전에 알린다 (MissingKey → code no_key)
    try:
        job = jobs.start(REF_JOBS, "ref_digest", None, f"전체 읽히기 ({b.name})", lambda j: refdigest.run(rid, llm, j), target=rid)
    except jobs.Busy as busy:
        return {**busy.job.public(), "already": True}
    return job.public()


EXPORTS = (
    "RefDigestAIIn",
    "ref_digest_ai",
    "ref_digest_estimate",
    "ref_digest_start",
    "ref_digest_view",
    "RefCreateIn",
    "RefInboxDelIn",
    "RefNewtoIn",
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
    "ref_inbox",
    "ref_inbox_clear",
    "ref_newto",
    "ref_revlab",
    "ref_sample",
    "ref_source",
    "ref_text",
    "split_ref",
)
