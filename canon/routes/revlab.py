"""역설계 실험 (canon/revlab.py, 작품 밖 화면 #/revlab) 라우트. canon/web.py 에서 옮겼다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from .. import jobs, refs, revlab, studio, usage
from ..schema import CueSheetDraft, RevArc, RevPart
from ..web import (  # web 의 공용 도우미
    _cue_labels,
    _waiting_409,
)
from .refs import _ref_id

router = APIRouter()

# 작가가 넣은 소설을 거꾸로 플롯 · 스토리보드 · 큐 시트 · 이야기 줄기 · 인물 · 관계 · 배경 · 문체로 푼다.
# 실험은 작품 밖 <CANON_HOME>/.revlab/<번호>.json, AI 작업은 POST /revlab/<번호>/jobs (작품 없이: 작업 목록의 project 는 revlab.JOBS,
# 사용량은 작품 없이 잡히고, 모델은 작품 프리셋이 아니라 전체 단계 설정을 쓴다).

class RevIn(BaseModel):
    title: str = ""
    text: str | None = None  # PUT 에서 비우면 글은 그대로 둔다
    first: int | None = None  # 첫 화 번호. 비우면 만들 때 짐작하고(revlab.guess_first), PUT 에서는 그대로 둔다


class RevAIIn(BaseModel):
    stage: Literal["plan", "write"]
    preset: str = ""  # 단계 프리셋 id. 있으면 provider · model 은 보지 않는다
    provider: str = ""  # 직접 고른 백엔드. preset 과 provider 가 모두 비면 설정을 따른다
    model: str = ""  # 직접 고른 모델. 비면 그 백엔드의 기본 모델


class RevEstimateIn(BaseModel):
    kind: Literal["parse", "write", "style", "arcs"] = "parse"
    episodes: list[int] = []
    style: bool = False  # write: 문체 프로필을 넣고 쓸 때


class RevPickIn(BaseModel):
    choice: int  # 1 · 2 (보인 차례), 0 이면 건너뛰기
    take: int | None = None  # 화면이 가려 읽던 판 번호. 지금 가려 읽을 판과 다르면 400 (낡은 화면)


class RevSplitIn(BaseModel):
    text: str


class RevJobIn(BaseModel):
    kind: Literal["parse", "write", "style", "arcs"]
    episodes: list[int] = []  # parse: 비우면 모든 화, write: 화 하나
    style: bool = False  # write: 역설계한 문체 프로필을 넣고 쓴다


def _rev(lab_id: int):
    try:
        return revlab.load(lab_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


def _rev_edit(lab_id: int, fn) -> dict:
    _rev(lab_id)
    return revlab.view(revlab.with_lock(lab_id, fn))


@router.get("/api/revlab")
def rev_home() -> dict:
    """역설계 실험 목록과 화면 이름 (큐 칸 값은 GET /projects/<이름>/cue 와 같다)."""
    return {"labs": revlab.listing(), **revlab.labels(), **_cue_labels()}


@router.post("/api/revlab/split")
def rev_split(body: RevSplitIn) -> dict:
    """글을 화로 나눈 미리보기 (저장하지 않는다). 화면의 미리보기가 쓴다. 화 글은 돌려주지 않고 글자 수만 준다."""
    v = revlab.split(body.text)
    return {**v, "episodes": [{"head": e["head"], "chars": len(e["text"])} for e in v["episodes"]]}


@router.post("/api/revlab")
def rev_create(body: RevIn) -> dict:
    """새 실험: 글을 화로 나눠 원문만 넣는다. AI 를 부르지 않는다."""
    return revlab.view(revlab.create(body.title, body.text or "", body.first))


@router.get("/api/revlab/{lab_id}")
def rev_get(lab_id: int) -> dict:
    return revlab.view(_rev(lab_id))


@router.put("/api/revlab/{lab_id}")
def rev_put(lab_id: int, body: RevIn) -> dict:
    """제목을 바꾸고, 글을 주면 다시 나눈다 (역설계 결과를 모두 지운다). 첫 화 번호를 주면 화 번호를 옮긴다."""
    return _rev_edit(lab_id, lambda lab: revlab.replace_text(lab, body.title, body.text, body.first))


class RevAppendIn(BaseModel):
    """화 이어 붙이기: 붙여 넣은 글(text) 또는 레퍼런스 원고의 화(ref · eps 차례) 가운데 하나."""
    text: str = ""
    ref: str = ""
    eps: list[int] = Field(default_factory=list)


@router.post("/api/revlab/{lab_id}/episodes")
def rev_append(lab_id: int, body: RevAppendIn) -> dict:
    """글을 나눠, 또는 레퍼런스 원고에서 고른 화를 마지막 화 뒤에 잇는다 (앞 화의 역설계 결과는 그대로). AI 를 부르지 않는다.
    원고 화는 다시 나누지 않고, 이미 이 실험에 있는 화는 뺀다 (refs.to_lab). 응답은 실험 화면 값에 added · skipped 를 더한다."""
    if bool(body.text.strip()) == bool(body.ref):
        raise HTTPException(400, "붙여 넣은 글이나 레퍼런스 원고 가운데 하나만 보내세요")
    if not body.ref:
        return _rev_edit(lab_id, lambda lab: revlab.append_text(lab, body.text))
    _rev(lab_id)
    if not body.eps:
        raise HTTPException(400, "이어 붙일 화를 고르세요")
    lab, out = refs.to_lab(_ref_id(body.ref), body.eps, lab_id)
    return {**revlab.view(lab), **out}


class RevEpisodeIn(BaseModel):
    head: str = ""
    text: str


def _rev_idle(lab_id: int, kinds: set[str] | None = None, msg: str = "이 실험의 작업이 끝난 뒤에 화를 고치거나 뺄 수 있어요") -> None:
    """작업이 도는 실험의 화는 고치거나 빼지 않는다 (작업이 화 번호로 결과를 넣는다). kinds 를 주면 그 작업만 본다."""
    if any(j.ep == lab_id and j.status == "running" and (kinds is None or j.kind in kinds) for j in jobs.listing(revlab.JOBS)):
        raise HTTPException(409, msg)


def _rev_parsing(lab_id: int) -> set[int]:
    """도는 역설계 작업이 아직 저장하지 않은 화 (지금 푸는 화 포함). 작업은 맡은 화(pending)를 앞 화부터 차례로 풀고,
    done 은 지금 푸는 화의 차례라 그 앞 화는 저장을 마쳤다 (revlab.run_parse, 화면 revRunRows 와 같은 셈)."""
    return {n for j in jobs.listing(revlab.JOBS) if j.ep == lab_id and j.kind == "rev_parse" and j.status == "running"
            for n in sorted(j.pending)[j.done:]}


def _rev_writing(lab_id: int) -> set[int]:
    """도는 되돌려 쓰기 작업이 쓰는 화."""
    return {n for j in jobs.listing(revlab.JOBS) if j.ep == lab_id and j.kind == "rev_write" and j.status == "running" for n in j.pending}


@router.put("/api/revlab/{lab_id}/episodes/{n}")
def rev_put_episode(lab_id: int, n: int, body: RevEpisodeIn) -> dict:
    """화 하나의 제목 줄과 글을 고친다. 글이 바뀌면 그 화의 역설계 결과를 지운다 (revlab.edit_episode)."""
    _rev(lab_id)
    _rev_idle(lab_id)
    return _rev_edit(lab_id, lambda lab: revlab.edit_episode(lab, n, body.head, body.text))


@router.delete("/api/revlab/{lab_id}/episodes/{n}")
def rev_delete_episode(lab_id: int, n: int) -> dict:
    """화 하나를 빼고 뒤 화 번호를 당긴다 (revlab.drop_episode)."""
    _rev(lab_id)
    _rev_idle(lab_id)
    return _rev_edit(lab_id, lambda lab: revlab.drop_episode(lab, n))


class RevStyleNoteIn(BaseModel):
    note: str = ""


_REV_STYLE_BUSY = "문체를 역설계하는 동안에는 문체 프로필을 고르거나 지울 수 없어요"


@router.get("/api/revlab/{lab_id}/pace")
def rev_pace(lab_id: int) -> dict:
    """화별 호흡과 실험 전체 요약 (revlab.pace, AI 없음). 구조 · 호흡 칸을 열 때만 받는다."""
    return revlab.pace(_rev(lab_id))


@router.get("/api/revlab/{lab_id}/styles/{sid}")
def rev_style_get(lab_id: int, sid: int, against: int = 0) -> dict:
    """문체 프로필 하나와 against(비우면 지금 프로필)에서 바뀐 칸 (revlab.style_view, library.diff)."""
    return revlab.style_view(_rev(lab_id), sid, against)


@router.post("/api/revlab/{lab_id}/styles/{sid}/select")
def rev_style_select(lab_id: int, sid: int) -> dict:
    """지금 문체 프로필로 고른다. 문체 역설계가 끝나면 새 프로필을 고르므로 그동안은 막는다."""
    _rev(lab_id)
    _rev_idle(lab_id, {"rev_style"}, _REV_STYLE_BUSY)
    return _rev_edit(lab_id, lambda lab: revlab.select_style(lab, sid))


@router.put("/api/revlab/{lab_id}/styles/{sid}")
def rev_style_note(lab_id: int, sid: int, body: RevStyleNoteIn) -> dict:
    return _rev_edit(lab_id, lambda lab: revlab.note_style(lab, sid, body.note))


class RevStyleLibraryIn(BaseModel):
    name: str = ""  # 비우면 '실험 이름 문체 n번'


@router.post("/api/revlab/{lab_id}/styles/{sid}/library")
def rev_style_library(lab_id: int, sid: int, body: RevStyleLibraryIn) -> dict:
    """프로필을 문체 라이브러리 새 항목으로 저장한다 (revlab.to_library). 작품은 2단계 문체에서 그 항목을 고른다."""
    _rev(lab_id)
    e = revlab.to_library(lab_id, sid, body.name)
    return {**revlab.view(revlab.load(lab_id)), "saved": {"id": e.id, "name": e.name}}


class RevParagraphIn(BaseModel):
    text: str  # 원문 칸에서 고른 글


@router.post("/api/revlab/{lab_id}/episodes/{number}/studio")
def rev_paragraph_studio(lab_id: int, number: int, body: RevParagraphIn) -> dict:
    """원문에서 고른 문단으로 문단 연습장 세션을 만든다 (revlab.paragraph_card → studio.create). 실험 파일은 바꾸지 않는다."""
    lab = _rev(lab_id)
    try:
        card, title = revlab.paragraph_card(lab, number, body.text)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return studio.view(studio.create(card, title))


@router.delete("/api/revlab/{lab_id}/styles/{sid}")
def rev_style_delete(lab_id: int, sid: int) -> dict:
    """문체 프로필을 지운다 (revlab.drop_style). 이 프로필로 쓴 판은 남는다."""
    _rev(lab_id)
    _rev_idle(lab_id, {"rev_style"}, _REV_STYLE_BUSY)
    return _rev_edit(lab_id, lambda lab: revlab.drop_style(lab, sid))


class RevArcsIn(BaseModel):
    parts: list[RevPart] = []
    arcs: list[RevArc]


@router.put("/api/revlab/{lab_id}/arcs")
def rev_set_arcs(lab_id: int, body: RevArcsIn) -> dict:
    """작가가 고친 아크 · 부 (revlab.set_arcs). 범위는 화를 빈틈없이 덮게 맞추고 기승전결은 아크 범위에 다시 나눈다."""
    return _rev_edit(lab_id, lambda lab: revlab.set_arcs(lab, body.parts, body.arcs))


class RevArcOfferIn(BaseModel):
    take: bool


@router.post("/api/revlab/{lab_id}/arcs/offer")
def rev_arc_offer(lab_id: int, body: RevArcOfferIn) -> dict:
    """작가가 고친 아크가 있을 때 받은 새 AI 안을 쓰거나(take) 버린다 (revlab.take_offer)."""
    return _rev_edit(lab_id, lambda lab: revlab.take_offer(lab, body.take))


@router.delete("/api/revlab/{lab_id}/arcs")
def rev_clear_arcs(lab_id: int) -> dict:
    """아크 · 부와 기다리는 AI 안을 지운다 (revlab.clear_arcs)."""
    return _rev_edit(lab_id, revlab.clear_arcs)


@router.delete("/api/revlab/{lab_id}")
def rev_delete(lab_id: int) -> dict:
    _rev(lab_id)
    revlab.remove(lab_id)
    return {"ok": True}


@router.put("/api/revlab/{lab_id}/episodes/{n}/sheet")
def rev_put_sheet(lab_id: int, n: int, body: CueSheetDraft) -> dict:
    """작가가 고친 큐 시트. 큐 수가 바뀌면 원문 경계를 지운다."""
    return _rev_edit(lab_id, lambda lab: revlab.set_sheet(lab, n, body))


@router.put("/api/revlab/{lab_id}/ai")
def rev_put_ai(lab_id: int, body: RevAIIn) -> dict:
    """이 실험의 단계 AI 를 고른다 (revlab.set_ai). 도는 작업은 시작할 때 고른 AI 를 그대로 쓴다."""
    return _rev_edit(lab_id, lambda lab: revlab.set_ai(lab, body.stage, body.preset, body.provider, body.model))


@router.post("/api/revlab/{lab_id}/episodes/{n}/pick")
def rev_pick(lab_id: int, n: int, body: RevPickIn) -> dict:
    """가려 읽기가 남은 판에서 고른다. 고르면 어느 쪽이 원문인지와 그 판의 지표를 보인다."""
    return _rev_edit(lab_id, lambda lab: revlab.pick(lab, n, body.choice, body.take))


@router.delete("/api/revlab/{lab_id}/episodes/{n}/takes/{no}")
def rev_delete_take(lab_id: int, n: int, no: int) -> dict:
    """되돌려 쓴 판 하나를 지운다 (revlab.drop_take). 판 번호는 다시 쓰지 않는다."""
    _rev_idle(lab_id)
    return _rev_edit(lab_id, lambda lab: revlab.drop_take(lab, n, no))


@router.post("/api/revlab/{lab_id}/jobs")
def rev_job(lab_id: int, body: RevJobIn) -> dict:
    """역설계(parse) · 되돌려 쓰기(write) · 문체 역설계(style) · 아크 역설계(arcs) 작업을 시작한다. 작품을 읽지 않는다. 같은 실험의 같은 작업은 하나만 돈다.
    다른 작업끼리는 함께 돌 수 있다. 역설계가 도는 중에도 저장을 마친 화는 되돌려 쓰고, 맡은 화가 겹치면 409 로 막는다."""
    lab = _rev(lab_id)
    kind, name = f"rev_{body.kind}", lab.title or f"실험 {lab_id}"
    if old := jobs.lingering(revlab.JOBS, kind, lab_id):  # 다시 시작하면 같은 요청이 겹쳐 요청 한도(429)에 더 걸린다
        _waiting_409(old)
    llm = revlab.llm_for(lab, body.kind)  # 실험이 고른 AI, 없으면 설정의 단계 칸. 키가 없으면 여기서 바로 오류를 보여 준다
    if body.kind == "parse":
        nums = revlab.choose(lab, body.episodes or None)
        if clash := sorted(_rev_writing(lab_id) & set(nums)):
            raise HTTPException(409, f"{clash[0]}화를 되돌려 쓰는 중이에요. 끝난 뒤에 다시 역설계할 수 있어요")
        total = len(nums) + revlab.wants_lines(lab, nums)
        label = f"{name} {len(nums)}화 역설계"

        def fn(job: jobs.Job):
            def step(done: int, _total: int, note: str) -> None:
                job.done, job.note = done, note
            return revlab.run_parse(lab_id, llm, nums, progress=step)
    elif body.kind == "write":
        if len(body.episodes) != 1:
            raise ValueError("되돌려 쓸 화를 하나 고르세요")
        k, use_style = body.episodes[0], body.style
        if k in _rev_parsing(lab_id):  # 역설계가 끝난 앞 화는 역설계가 도는 중에도 쓸 수 있다
            raise HTTPException(409, f"{k}화는 역설계가 끝난 뒤에 되돌려 쓸 수 있어요")
        revlab.world(lab, k, use_style)  # 역설계하지 않은 화, 문체 프로필이 없는 실험은 여기서 바로 알린다
        revlab.room(revlab.episode(lab, k))  # 판이 꽉 찼으면 여기서 바로 알린다
        total, label = 1, f"{name} {k}화 되돌려 쓰기" + (" (문체 넣음)" if use_style else "")

        def fn(job: jobs.Job):
            t = revlab.run_write(lab_id, llm, k, use_style).takes[-1]
            return {"episode": k, "take": t.no, "chars": len(t.text), "style": use_style}
    elif body.kind == "arcs":
        revlab.can_arcs(lab)
        if _rev_parsing(lab_id):
            raise HTTPException(409, "역설계가 끝난 뒤에 아크를 찾을 수 있어요")
        total, label = 1, f"{name} 아크 역설계"

        def fn(job: jobs.Job):
            plan = revlab.run_arcs(lab_id, llm)
            return {"arcs": len(plan.arcs), "parts": len(plan.parts), "offer": revlab.load(lab_id).arc_offer is not None}
    else:
        revlab.style_sample(lab)
        revlab.check_style_room(lab)
        total, label = 1, f"{name} 문체 역설계"

        def fn(job: jobs.Job):
            prof = revlab.run_style(lab_id, llm)
            return {"markers": len(prof.markers), "id": revlab.load(lab_id).style_id}
    try:
        with usage.scope(project="", episode=None, task=kind):
            # 맡은 화(pending)를 보내 화면이 화마다 진행 줄을 그린다 (revlab.js revRunRows). 실험은 작품이 아니라 저장 잠금과 겹치지 않는다
            job = jobs.start(revlab.JOBS, kind, lab_id, label, fn, total=total,
                             owned=set(nums) if body.kind == "parse" else {k} if body.kind == "write" else None)
    except jobs.Busy as b:
        return {**b.job.public(), "already": True}
    return job.public()


@router.post("/api/revlab/{lab_id}/estimate")
def rev_estimate(lab_id: int, body: RevEstimateIn) -> dict:
    """역설계 · 되돌려 쓰기 비용 추정. AI 를 부르지 않는다."""
    return revlab.estimate(_rev(lab_id), body.kind, body.episodes or None, use_style=body.style)


EXPORTS = (
    "RevAIIn",
    "RevAppendIn",
    "RevArcOfferIn",
    "RevArcsIn",
    "RevEpisodeIn",
    "RevEstimateIn",
    "RevIn",
    "RevJobIn",
    "RevParagraphIn",
    "RevPickIn",
    "RevSplitIn",
    "RevStyleLibraryIn",
    "RevStyleNoteIn",
    "_REV_STYLE_BUSY",
    "_rev",
    "_rev_edit",
    "_rev_idle",
    "_rev_parsing",
    "_rev_writing",
    "rev_append",
    "rev_arc_offer",
    "rev_clear_arcs",
    "rev_create",
    "rev_delete",
    "rev_delete_episode",
    "rev_delete_take",
    "rev_estimate",
    "rev_get",
    "rev_home",
    "rev_job",
    "rev_pace",
    "rev_paragraph_studio",
    "rev_pick",
    "rev_put",
    "rev_put_ai",
    "rev_put_episode",
    "rev_put_sheet",
    "rev_set_arcs",
    "rev_split",
    "rev_style_delete",
    "rev_style_get",
    "rev_style_library",
    "rev_style_note",
    "rev_style_select",
)
