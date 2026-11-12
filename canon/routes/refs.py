"""레퍼런스 원고 (canon/refs.py, 작품 밖) 라우트. canon/web.py 에서 옮겼다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .. import jobs, refdigest, refnote, refs
from ..llm import get_llm
from ..schema import RefBook, RefCut, RefFile, RevArc, RevPart
from ..web import (  # web 의 공용 도우미
    _edit,
    _load,
    _need,
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
    spread: bool = True  # 문체 표본: 길면 범위 전체에서 고루 뽑는다. 거짓이면 앞에서 자른다


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
    """문체 만들기에 넣을 원문 (SAMPLE_MAX 자까지, 길면 범위 전체에서 고루 뽑는다). AI 를 부르지 않는다."""
    return refs.sample(_ref_id(rid), body.eps, body.spread)


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


@router.get("/api/refs/{rid}/digest/pace")
def ref_digest_pace(rid: str) -> dict:
    """화 카드로 본 구조: 구간별 긴장 · 성격, 정점 화, 인물이 처음 나온 화, 나눈 아크. AI 를 부르지 않는다."""
    rid = _ref_id(rid)
    return {**refdigest.pace(rid), "arcs": refdigest.arcs_view(rid)}


@router.get("/api/refs/{rid}/digest/arcs/estimate")
def ref_digest_arcs_estimate(rid: str) -> dict:
    try:
        return refdigest.arcs_estimate(_ref_id(rid))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/refs/{rid}/digest/arcs")
def ref_digest_arcs_start(rid: str) -> dict:
    """아크 · 부 나누기 작업(ref_arcs)을 시작한다. 화 카드를 접어 계획 단계 모델에 한 번 보낸다."""
    rid = _ref_id(rid)
    try:
        refdigest.arcs_ready(rid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    llm = get_llm("plan")  # 키가 없으면 작업을 띄우기 전에 알린다
    try:
        job = jobs.start(REF_JOBS, "ref_arcs", None, f"아크 나누기 ({refs.load(rid).name})", lambda j: refdigest.run_arcs(rid, llm), target=rid)
    except jobs.Busy as busy:
        return {**busy.job.public(), "already": True}
    return job.public()


class RefArcsIn(BaseModel):
    parts: list[RevPart] = []
    arcs: list[RevArc]


@router.put("/api/refs/{rid}/digest/arcs")
def ref_digest_arcs_set(rid: str, body: RefArcsIn) -> dict:
    """작가가 고친 아크 · 부 (refdigest.set_arcs). 범위는 제외하지 않은 화를 빈틈없이 덮게 맞추고 맞춘 것을 notes 에 적는다."""
    rid = _ref_id(rid)
    try:
        refdigest.set_arcs(rid, body.parts, body.arcs)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return refdigest.arcs_view(rid)


class RefArcOfferIn(BaseModel):
    take: bool


@router.post("/api/refs/{rid}/digest/arcs/offer")
def ref_digest_arcs_offer(rid: str, body: RefArcOfferIn) -> dict:
    """작가가 고친 아크가 있을 때 받은 새 AI 안을 쓴다(take) · 버린다 (refdigest.take_offer)."""
    rid = _ref_id(rid)
    try:
        refdigest.take_offer(rid, body.take)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return refdigest.arcs_view(rid)


@router.delete("/api/refs/{rid}/digest/arcs")
def ref_digest_arcs_clear(rid: str) -> dict:
    refdigest.clear_arcs(_ref_id(rid))
    return {"ok": True}


# ----- 참고 메모 (canon/refnote.py): 원고에서 설정 구도 요약을 만들어 작가가 넣기를 누르면 작품에 복사한다 -----

class RefNoteMakeIn(BaseModel):
    eps: list[int]
    use: str = "setup"  # setup 설정 메모 · write · plot 박자 메모 (refnote.USE_KIND)
    project: str = ""  # 넣을 작품 (미리보기에 실어 돌려줄 뿐, 만들 때는 작품을 읽거나 쓰지 않는다)


@router.post("/api/refs/{rid}/note/estimate")
def ref_note_estimate(rid: str, body: RefNoteMakeIn) -> dict:
    """설정 메모를 만들 때 보낼 것(화 카드 · 원문)과 비용 추정. AI 를 부르지 않는다."""
    try:
        return refnote.estimate(_ref_id(rid), body.eps, body.use)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/refs/{rid}/note")
def ref_note_start(rid: str, body: RefNoteMakeIn) -> dict:
    """참고 메모 초안 작업(ref_note)을 시작한다. 결과는 미리보기이고 작품에 저장하지 않는다. 원고 하나에 하나만 돈다."""
    rid = _ref_id(rid)
    if body.project:
        _need(body.project)
    try:
        kind = refnote._kind(body.use)
        m = refnote.material(rid, body.eps)
    except ValueError as e:
        raise HTTPException(400, str(e))
    llm = get_llm("plan")  # 키가 없으면 작업을 띄우기 전에 알린다
    try:
        job = jobs.start(REF_JOBS, "ref_note", None, f"{'박자' if kind == 'beats' else '설정'} 메모 ({m['name']} {m['eps']})",
                         lambda j: refnote.run(rid, body.eps, llm, body.project, body.use), target=rid)
    except jobs.Busy as busy:
        return {**busy.job.public(), "already": True}
    return job.public()


class RefNoteMarksIn(BaseModel):
    eps: list[int]
    text: str


@router.post("/api/refs/{rid}/note/marks")
def ref_note_marks(rid: str, body: RefNoteMarksIn) -> dict:
    """고친 메모 글에 든 원문 구절 · 원고의 이름을 다시 센다 (AI 없음)."""
    try:
        return {"marks": refnote.marks(_ref_id(rid), body.eps, body.text)}
    except ValueError as e:
        raise HTTPException(400, str(e))


class RefNoteAddIn(BaseModel):
    text: str
    ref: str = ""  # 만든 원고 id. 있으면 그 원고의 '만든 것'에 남긴다
    from_name: str = ""
    from_eps: str = ""
    kind: str = "setup"
    use: str = "setup"


class RefNotePutIn(BaseModel):
    text: str | None = None
    on: bool | None = None


def _note_edit(name: str, fn) -> dict:
    _need(name)
    try:
        return refnote.view(_edit(name, fn))
    except KeyError:
        raise HTTPException(404, "그 참고 메모가 없어요")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/projects/{name}/ref-notes")
def ref_notes_list(name: str) -> dict:
    return refnote.view(_load(name))


@router.post("/api/projects/{name}/ref-notes")
def ref_notes_add(name: str, body: RefNoteAddIn) -> dict:
    """작가가 미리보기에서 넣기를 누른 참고 메모를 작품에 넣는다. 원고의 '만든 것'에 남긴다."""
    box: dict = {}
    out = _note_edit(name, lambda p: box.update(note=refnote.add(p, body.text, body.from_name, body.from_eps, body.kind, body.use)))
    if body.ref:
        try:
            refs.made(_ref_id(body.ref), "note", f"{name}/{box['note'].id}", body.from_eps)
        except (KeyError, HTTPException):  # 원고를 그 사이 지웠어도 메모는 넣는다
            pass
    return {**out, "id": box["note"].id}


@router.put("/api/projects/{name}/ref-notes/{nid}")
def ref_notes_put(name: str, nid: str, body: RefNotePutIn) -> dict:
    """참고 메모의 글을 고치거나 켜고 끈다."""
    return _note_edit(name, lambda p: refnote.update(p, nid, body.text, body.on))


@router.delete("/api/projects/{name}/ref-notes/{nid}")
def ref_notes_delete(name: str, nid: str) -> dict:
    return _note_edit(name, lambda p: refnote.remove(p, nid))


EXPORTS = (
    "RefNoteAddIn",
    "RefNoteMakeIn",
    "RefNoteMarksIn",
    "RefNotePutIn",
    "ref_note_estimate",
    "ref_note_marks",
    "ref_note_start",
    "ref_notes_add",
    "ref_notes_delete",
    "ref_notes_list",
    "ref_notes_put",
    "ref_digest_arcs_clear",
    "ref_digest_arcs_estimate",
    "ref_digest_arcs_offer",
    "ref_digest_arcs_set",
    "RefArcOfferIn",
    "RefArcsIn",
    "ref_digest_arcs_start",
    "ref_digest_pace",
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
