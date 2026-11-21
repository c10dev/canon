"""지시 연습 (canon/drill.py, 작품 밖 화면 #/drill, docs/drill) 라우트.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import cancel, drill, jobs, pipeline, usage
from ..llm import get_llm
from ..schema import REF_DIGEST_KINDS, DrillBrief, DrillRound, WriteMark

router = APIRouter()

# 판 하나가 <CANON_HOME>/.drill/<id>.json 하나다. AI 호출(사실 뽑기 · 두 판 쓰기 · 되짚기 · 고쳐서 다시 쓰기 · 줄여서 쓰기 · 맞힐 두 판 쓰기)은 백그라운드 작업으로 돈다.
# 작품 밖이라 작업 목록의 project 자리는 DR_JOBS 이고 대상(target)은 판 id 다.
DR_JOBS = ".drill"  # 작업 목록의 project 자리 (작품 폴더는 점으로 시작하지 않아 겹치지 않는다). 화면은 '지시 연습'으로 보인다


class DrillIn(BaseModel):
    ref_id: str
    order: int = 0  # 화 차례. 0 이면 도구가 고른다
    part: int = 0  # 대목 번호. 0 이면 도구가 고른다
    kind: str = ""  # 도구가 고를 때: 화 카드의 성격
    tension: int = 0  # 도구가 고를 때: 화 카드의 긴장 (이상)
    style_id: str = ""
    mode: Literal["", "shrink", "match", "write"] = ""  # 연습 종류 (drill.MODES)


class DrillEdit(BaseModel):
    brief: DrillBrief
    rival: Optional[DrillBrief] = None  # 거꾸로 맞히기 판의 둘째 쓰는 방식. 없으면 그대로 둔다


class DrillPick(BaseModel):
    side: Literal["left", "right", "skip"]


class WriteSubmit(BaseModel):
    brief: DrillBrief
    text: str


class WriteMarks(BaseModel):
    marks: list[WriteMark] = []


class WriteFinish(BaseModel):
    next_try: str = ""


class DrillJobIn(BaseModel):
    kind: Literal["facts", "write", "review", "revise", "shrink", "match", "ai_write"]
    no: int = 0  # review: 되짚을 시도 번호. 0 이면 마지막 시도


def _drill(did: str) -> DrillRound:
    try:
        return drill.load(did)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


@router.get("/api/drill")
def list_drill() -> dict:
    rs = drill.rounds()
    return {"rounds": [drill.summary(r) for r in rs], "stats": drill.stats(rs), "sources": drill.sources(), "layers": drill.layers(), "results": drill.RESULTS,
            "boxes": drill.BOXES, "kinds": list(REF_DIGEST_KINDS), "method_max": drill.METHOD_MAX, "modes": drill.MODES, "shrink_max": drill.SHRINK_MAX}


@router.get("/api/drill/sources/{rid}")
def drill_source(rid: str, mode: str = "") -> dict:
    """원고의 화 목록 (원문 없음). 작가가 화와 대목 번호를 직접 고를 때 쓴다. 대목 수는 연습 종류(mode)의 크기로 센다."""
    try:
        return {"episodes": drill.episodes(rid, mode)}
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


@router.post("/api/drill")
def create_drill(body: DrillIn) -> dict:
    try:
        return drill.view(drill.create(body.ref_id, body.order, body.part, body.kind, body.tension, body.style_id, mode=body.mode))
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


@router.get("/api/drill/{did}")
def get_drill(did: str) -> dict:
    return drill.view(_drill(did))


@router.put("/api/drill/{did}")
def put_drill(did: str, body: DrillEdit) -> dict:
    """작가가 고친 지시를 남긴다. 쓰는 방식이 줄 수 상한을 넘으면 막는다 (ValueError → 400)."""
    _drill(did)

    def fn(r: DrillRound) -> None:
        drill.can_edit_facts(r)
        r.brief = drill.write_brief(body.brief) if r.mode == "write" else drill.clean_brief(body.brief)  # 직접 쓰기 판은 쓰는 방식 칸을 받지 않는다
        if body.rival is not None and r.mode == "match" and not r.attempts:  # 쓴 뒤에는 둘째 쓰는 방식을 바꾸지 않는다 (맞힌 짝이 달라진다)
            r.rival = drill.clean_rival(body.rival)
    return drill.view(drill.update(did, fn))


@router.post("/api/drill/{did}/pick")
def pick_drill(did: str, body: DrillPick) -> dict:
    """고쳐 쓴 판과 앞 지시로 다시 쓴 판을 가려 읽고 고른 쪽을 남긴다. 고른 뒤에는 어느 쪽인지와 되짚기가 보인다."""
    r = _drill(did)
    drill.pick_side(r, body.side)
    return drill.view(drill.save(r))


@router.post("/api/drill/{did}/submit")
def submit_drill(did: str, body: WriteSubmit) -> dict:
    """직접 쓰기 판: 작가의 글을 낸다. 낸 순간 AI 판 쓰기(작업 ai_write)가 뒤에서 시작한다. 작업을 시작하지 못해도 글은 남고, 화면이 다시 쓰기를 권한다."""
    _drill(did)

    def fn(r: DrillRound) -> None:
        b = drill.write_brief(body.brief)
        drill.can_submit(r, b, body.text)
        drill.add_own(r, b, body.text)
        r.brief = b
    r = drill.update(did, fn)
    job = None
    try:
        fn, label, total = _ai_write_job(did, r, r.title or "지시 연습")
        job = _run_job("dr_ai_write", label, fn, total, did)
    except Exception:  # 글은 남았다. 화면의 '다시 쓰기'가 같은 작업을 다시 보낸다
        logging.getLogger("canon").exception("지시 연습 %s AI 판 쓰기 시작 실패", did)
    return {**drill.view(r), "job": job}


@router.post("/api/drill/{did}/marks")
def marks_drill(did: str, body: WriteMarks) -> dict:
    """직접 쓰기 판: 작가의 짚기를 저장한다 (빈 목록도 된다). 저장하면 AI 판이 보인다."""
    _drill(did)
    return drill.view(drill.update(did, lambda r: drill.set_marks(r, body.marks)))


@router.post("/api/drill/{did}/finish")
def finish_drill(did: str, body: WriteFinish) -> dict:
    """직접 쓰기 판: '다음엔 해 볼 것'을 남기고 판을 끝낸다."""
    _drill(did)
    return drill.view(drill.update(did, lambda r: drill.finish(r, body.next_try)))


@router.delete("/api/drill/{did}")
def delete_drill(did: str) -> dict:
    _drill(did)
    drill.delete(did)
    return {"ok": True}


def _review(did: str, no: int, llm) -> bool:
    """시도 하나를 되짚어 남긴다. 저장 직전에 판을 다시 읽는다."""
    r = drill.load(did)
    a = drill.find(r, no)
    lines = drill.author_lines(a.brief, drill.facts_brief(r.facts))
    rv = pipeline.drill_review(llm, lines, drill.brief_text(a.brief), a.with_text, a.bare_text, r.source)
    q = drill.load(did)
    drill.set_review(q, no, rv, getattr(llm, "model", "") or "")
    drill.save(q)
    return True


def _ai_write_job(did: str, r: DrillRound, name: str):
    """직접 쓰기 판의 AI 판 쓰기 작업 (fn, label, total). 사실 · 일어나는 일만 담은 카드(쓰는 방식 없음, 원문 없음)로 한 번 쓴다.
    결과는 drill.update 로 남긴다: 같은 판의 저장과 한 번에 하나씩 돌고, 판을 다시 읽어 AI 판만 채우므로 그 사이 저장한 짚기를 덮지 않는다."""
    if r.mode != "write":
        raise ValueError("직접 쓰기 판이 아니에요")
    a = r.attempts[-1] if r.attempts else None
    if a is None or not a.own_text:
        raise ValueError("먼저 글을 내세요")
    if a.bare_text:
        raise ValueError("AI 판을 이미 썼어요")
    card = drill.card_of(r, a.brief, bare=True)
    llm = get_llm("write")
    model = getattr(llm, "model", "") or ""

    def fn(job: jobs.Job):
        text = pipeline.draft_paragraph(llm, card, 1)[0].text
        drill.update(did, lambda q: drill.set_ai_text(q, text, model))  # 읽고 고치고 저장하는 사이 다른 저장이 끼지 않는다
        return {"id": did}
    return fn, f"{name} · AI 판 쓰기", 1


def _run_job(kind: str, label: str, fn, total: int, did: str) -> dict:
    """작업을 시작한다. 같은 판에서 이미 도는 같은 작업이 있으면 그 작업에 already 를 달아 돌려준다."""
    try:
        with usage.scope(project="", episode=None, task="drill"):
            return jobs.start(DR_JOBS, kind, None, label, fn, total=total, target=did).public()
    except jobs.Busy as b:
        return {**b.job.public(), "already": True}


@router.post("/api/drill/{did}/jobs")
def drill_job(did: str, body: DrillJobIn) -> dict:
    """지시 연습의 AI 호출을 작업으로 돌린다 (작업 종류 dr_<kind>, 대상은 판 id).
    facts: 원문 대목에서 사실과 일어나는 일을 뽑는다. write: 두 판을 쓰고 이어서 되짚는다 (되짚기가 실패해도 쓴 글은 남는다).
    revise: 고친 지시의 판과 앞 지시로 다시 쓴 판을 쓰고 이어서 되짚는다 (한 판에 한 번). review: 시도 하나를 다시 되짚는다.
    shrink: 줄이기 판에서 줄인 지시의 판과 AI가 뽑은 지시의 판을 쓴다 (쓰는 방식 없음, 되짚지 않는다).
    match: 거꾸로 맞히기 판에서 쓰는 방식 둘로 한 판씩 쓴다 (되짚지 않는다).
    지시는 시작할 때 것을 쓴다."""
    r = _drill(did)
    name = r.title or "지시 연습"
    kind = f"dr_{body.kind}"
    if body.kind == "facts":
        drill.can_edit_facts(r)
        llm = get_llm("plan")
        source, lead, label, total = r.source, r.lead, f"{name} · 사실 뽑기", 1

        def fn(job: jobs.Job):
            f = pipeline.drill_facts(llm, source, lead)
            q = drill.update(did, lambda x: drill.set_facts(x, f, getattr(llm, "model", "") or ""))
            return {"id": did, "events": len(q.facts.events), "mode": q.mode}
    elif body.kind == "shrink":
        short, dense = drill.shrink_briefs(r, drill.clean_brief(r.brief))
        card, old = drill.card_of(r, short, bare=True), drill.card_of(r, dense, bare=True)
        llm = get_llm("write")
        label, total = f"{name} · 줄여서 쓰기", 1

        def fn(job: jobs.Job):
            w, o = pipeline.drill_write(llm, card, old)
            q = drill.load(did)
            a = drill.add_shrink(q, short, w, o, getattr(llm, "model", "") or "")
            drill.save(q)
            return {"id": did, "no": a.no}
    elif body.kind == "match":
        first, second = drill.match_briefs(r, drill.clean_brief(r.brief))
        card, old = drill.card_of(r, first), drill.card_of(r, second)
        llm = get_llm("write")
        label, total = f"{name} · 맞힐 두 판 쓰기", 1

        def fn(job: jobs.Job):
            w, o = pipeline.drill_write(llm, card, old)
            q = drill.load(did)
            a = drill.add_match(q, first, w, o, getattr(llm, "model", "") or "")
            drill.save(q)
            return {"id": did, "no": a.no}
    elif body.kind == "ai_write":
        fn, label, total = _ai_write_job(did, r, name)
    elif body.kind == "write":
        if r.mode:
            raise ValueError("이 판은 지시 적기 판이 아니에요")
        if r.attempts:
            raise ValueError("이 판은 이미 썼어요. 새 판을 시작하세요")
        brief = drill.clean_brief(r.brief)
        drill.can_write(r, brief)
        card, bare = drill.card_of(r, brief), drill.card_of(r, brief, bare=True)
        llm, judge = get_llm("write"), get_llm("check")
        label, total = f"{name} · 두 판 쓰기", 2

        def fn(job: jobs.Job):
            w, b = pipeline.drill_write(llm, card, bare)
            q = drill.load(did)
            a = drill.add_attempt(q, brief, w, b, getattr(llm, "model", "") or "")
            drill.save(q)
            job.done = 1
            try:
                reviewed = _review(did, a.no, judge)
            except cancel.Cancelled:
                raise
            except Exception:  # 쓴 글은 남았다. 화면이 '되짚기'를 다시 권한다
                logging.getLogger("canon").exception("지시 연습 %s 되짚기 실패", did)
                reviewed = False
            return {"id": did, "no": a.no, "reviewed": reviewed}
    elif body.kind == "revise":
        brief = drill.clean_brief(r.brief)
        prev = drill.can_revise(r, brief)
        card, old = drill.card_of(r, brief), drill.card_of(r, drill.clean_brief(prev.brief))
        llm, judge = get_llm("write"), get_llm("check")
        label, total = f"{name} · 고쳐서 다시 쓰기", 2

        def fn(job: jobs.Job):
            w, o = pipeline.drill_write(llm, card, old)
            q = drill.load(did)
            a = drill.add_revision(q, brief, w, o, getattr(llm, "model", "") or "")
            drill.save(q)
            job.done = 1
            try:
                reviewed = _review(did, a.no, judge)
            except cancel.Cancelled:
                raise
            except Exception:  # 쓴 글은 남았다. 고른 뒤 화면이 '되짚기'를 다시 권한다
                logging.getLogger("canon").exception("지시 연습 %s 되짚기 실패", did)
                reviewed = False
            return {"id": did, "no": a.no, "reviewed": reviewed}
    else:
        if not r.attempts:
            raise ValueError("먼저 두 판을 쓰세요")
        if drill.pending(r):
            raise ValueError("먼저 두 글 가운데 하나를 고르세요")
        if r.mode:
            raise ValueError("이 연습은 되짚지 않아요")
        no = body.no or r.attempts[-1].no
        try:
            drill.find(r, no)
        except KeyError as e:
            raise HTTPException(404, str(e.args[0])) from None
        judge = get_llm("check")
        label, total = f"{name} · 되짚기", 1

        def fn(job: jobs.Job):
            return {"id": did, "no": no, "reviewed": _review(did, no, judge)}
    return _run_job(kind, label, fn, total, did)


EXPORTS = (
    "DR_JOBS",
    "DrillEdit",
    "DrillPick",
    "DrillIn",
    "DrillJobIn",
    "WriteFinish",
    "WriteMarks",
    "WriteSubmit",
    "_drill",
    "create_drill",
    "delete_drill",
    "drill_job",
    "drill_source",
    "finish_drill",
    "get_drill",
    "list_drill",
    "marks_drill",
    "pick_drill",
    "put_drill",
    "submit_drill",
)
