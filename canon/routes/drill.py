"""지시 연습 (canon/drill.py, 작품 밖 화면 #/drill, docs/drill) 라우트.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import cancel, drill, jobs, pipeline, usage
from ..llm import get_llm
from ..schema import REF_DIGEST_KINDS, DrillBrief, DrillRound

router = APIRouter()

# 판 하나가 <CANON_HOME>/.drill/<id>.json 하나다. AI 호출(사실 뽑기 · 두 판 쓰기 · 되짚기 · 고쳐서 다시 쓰기 · 줄여서 쓰기)은 백그라운드 작업으로 돈다.
# 작품 밖이라 작업 목록의 project 자리는 DR_JOBS 이고 대상(target)은 판 id 다.
DR_JOBS = ".drill"  # 작업 목록의 project 자리 (작품 폴더는 점으로 시작하지 않아 겹치지 않는다). 화면은 '지시 연습'으로 보인다


class DrillIn(BaseModel):
    ref_id: str
    order: int = 0  # 화 차례. 0 이면 도구가 고른다
    part: int = 0  # 대목 번호. 0 이면 도구가 고른다
    kind: str = ""  # 도구가 고를 때: 화 카드의 성격
    tension: int = 0  # 도구가 고를 때: 화 카드의 긴장 (이상)
    style_id: str = ""
    mode: Literal["", "shrink"] = ""  # 연습 종류 (drill.MODES)


class DrillEdit(BaseModel):
    brief: DrillBrief


class DrillPick(BaseModel):
    side: Literal["left", "right", "skip"]


class DrillJobIn(BaseModel):
    kind: Literal["facts", "write", "review", "revise", "shrink"]
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
def drill_source(rid: str) -> dict:
    """원고의 화 목록 (원문 없음). 작가가 화와 대목 번호를 직접 고를 때 쓴다."""
    try:
        return {"episodes": drill.episodes(rid)}
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
    r = _drill(did)
    r.brief = drill.clean_brief(body.brief)
    return drill.view(drill.save(r))


@router.post("/api/drill/{did}/pick")
def pick_drill(did: str, body: DrillPick) -> dict:
    """고쳐 쓴 판과 앞 지시로 다시 쓴 판을 가려 읽고 고른 쪽을 남긴다. 고른 뒤에는 어느 쪽인지와 되짚기가 보인다."""
    r = _drill(did)
    drill.pick_side(r, body.side)
    return drill.view(drill.save(r))


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


@router.post("/api/drill/{did}/jobs")
def drill_job(did: str, body: DrillJobIn) -> dict:
    """지시 연습의 AI 호출을 작업으로 돌린다 (작업 종류 dr_<kind>, 대상은 판 id).
    facts: 원문 대목에서 사실과 일어나는 일을 뽑는다. write: 두 판을 쓰고 이어서 되짚는다 (되짚기가 실패해도 쓴 글은 남는다).
    revise: 고친 지시의 판과 앞 지시로 다시 쓴 판을 쓰고 이어서 되짚는다 (한 판에 한 번). review: 시도 하나를 다시 되짚는다.
    shrink: 줄이기 판에서 줄인 지시의 판과 AI가 뽑은 지시의 판을 쓴다 (쓰는 방식 없음, 되짚지 않는다).
    지시는 시작할 때 것을 쓴다."""
    r = _drill(did)
    name = r.title or "지시 연습"
    kind = f"dr_{body.kind}"
    if body.kind == "facts":
        llm = get_llm("plan")
        source, lead, label, total = r.source, r.lead, f"{name} · 사실 뽑기", 1

        def fn(job: jobs.Job):
            f = pipeline.drill_facts(llm, source, lead)
            q = drill.load(did)
            drill.set_facts(q, f, getattr(llm, "model", "") or "")
            drill.save(q)
            return {"id": did, "events": len(q.facts.events)}
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
    try:
        with usage.scope(project="", episode=None, task="drill"):
            return jobs.start(DR_JOBS, kind, None, label, fn, total=total, target=did).public()
    except jobs.Busy as b:
        return {**b.job.public(), "already": True}


EXPORTS = (
    "DR_JOBS",
    "DrillEdit",
    "DrillPick",
    "DrillIn",
    "DrillJobIn",
    "_drill",
    "create_drill",
    "delete_drill",
    "drill_job",
    "drill_source",
    "get_drill",
    "list_drill",
    "pick_drill",
    "put_drill",
)
