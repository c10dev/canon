"""쇠맛 실험실 (canon/soelab.py, 작품 밖 화면 #/soelab) 라우트. canon/web.py 에서 옮겼다.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Literal
from .. import soelab

router = APIRouter()

# 쇠맛 지표가 사람 글과 AI 글 · 작가 판정을 가르는지 잰다. AI 를 부르지 않는다. 저장은 작품 밖 <CANON_HOME>/.soelab/.
# 가린 조각(soelab.masked_ids)의 출처 · 원천 · 묶음 · 모델 · 지표 값 · 정규식 밑줄은 어느 응답에도 싣지 않는다.
# 정답은 '이번 10개'가 끝난 뒤에만(GET /soelab/batch/<번호>), 다시 읽기 예정 조각은 재판정 뒤에만 보인다.

class SoeSourceIn(BaseModel):
    kind: Literal["revlab", "episode", "edit", "research", "paste"]
    lab: int = 0
    project: str = ""
    first: int = 0
    last: int = 0
    path: str = ""
    genre: Literal["webnovel", "literary", "other", ""] = ""
    text: str = ""
    title: str = ""
    origin: Literal["human", "ai", "unknown"] = "human"
    model: Literal["claude", "gemini", "other", ""] = ""
    known: bool = False  # 작가가 읽은 적 있는 작품: 가려 읽기 대기열에 넣지 않는다


class SoeCollectIn(BaseModel):
    sources: list[SoeSourceIn]


class SoeSpanIn(BaseModel):
    start: int
    end: int
    kind: str
    note: str = ""


class SoeJudgeIn(BaseModel):
    piece: str
    verdict: Literal["ai", "human", "unsure"]
    spans: list[SoeSpanIn] = []
    clean: bool = False  # 표시할 곳 없이 다 읽었어요
    seconds: int = 0


class SoeStateIn(BaseModel):
    goal: int | None = None
    stopped: bool | None = None
    seen: int | None = None


class SoeCheckIn(BaseModel):
    hit: str
    ok: Literal["yes", "no", "skip"]


class SoeOriginIn(BaseModel):
    origin: Literal["human", "ai", "unknown"]
    model: Literal["claude", "gemini", "other", ""] = ""


def _soe_sources(body: SoeCollectIn) -> list[dict]:
    if not body.sources:
        raise ValueError("모을 원천을 하나 넘게 골라 주세요")
    return [x.model_dump() for x in body.sources]


@router.get("/api/soelab")
def soe_view() -> dict:
    """화면 값: 말뭉치 · 판정 · 다시 읽기 진행, 최근 보고서(조각별 줄 없음), 다음 할 일을 고를 값."""
    return soelab.screen()


@router.get("/api/soelab/sources")
def soe_sources() -> dict:
    """모으기 카드의 원천 후보 (역설계 실험 · 작품 · 연구 말뭉치 폴더)."""
    return soelab.sources()


@router.post("/api/soelab/collect/preview")
def soe_collect_preview(body: SoeCollectIn) -> dict:
    """모으기 미리보기: 저장하지 않고 새 조각 수 · 이미 있는 글 · 상한 · 서로 다른 화 · 모델별 화를 센다."""
    return soelab.plan_add(soelab.gather(_soe_sources(body)))


@router.post("/api/soelab/collect")
def soe_collect(body: SoeCollectIn) -> dict:
    """모으고 보고서를 다시 채점한다 (AI 없음)."""
    return {**soelab.collect(_soe_sources(body)), "screen": soelab.screen()}


@router.get("/api/soelab/pieces")
def soe_pieces() -> dict:
    """조각 목록. 가린 조각은 출처 · 원천 · 묶음 · 모델을 뺀다."""
    return soelab.pieces_view()


@router.get("/api/soelab/pieces/{pid}")
def soe_piece(pid: str) -> dict:
    """조각 하나. 가린 조각은 글만."""
    return soelab.piece_view(pid)


@router.delete("/api/soelab/pieces/{pid}")
def soe_piece_remove(pid: str) -> dict:
    """붙여 넣은 조각 빼기 (판정하지 않은 것만)."""
    soelab.remove_piece(pid)
    return soelab.pieces_view()


@router.put("/api/soelab/pieces/{pid}/origin")
def soe_piece_origin(pid: str, body: SoeOriginIn) -> dict:
    """붙여 넣은 조각의 출처 고치기 (가리지 않은 것만)."""
    soelab.set_origin(pid, body.origin, body.model)
    return soelab.pieces_view()


@router.get("/api/soelab/judge")
def soe_judge_view() -> dict:
    """가려 읽기: 다음 조각(글 · id · 글자 수만)과 진행."""
    return soelab.judge_view()


@router.post("/api/soelab/judge")
def soe_judge(body: SoeJudgeIn) -> dict:
    """가려 읽기 판정 저장. 이번 10개를 마치면 보고서를 다시 채점한다."""
    out = soelab.save_judge(body.piece, body.verdict, [x.model_dump() for x in body.spans], body.clean, body.seconds)
    return {**out, **soelab.judge_view()}


@router.get("/api/soelab/batch/{k}")
def soe_batch(k: int) -> dict:
    """끝난 '이번 10개'의 정답. 끝나기 전에는 막는다."""
    return soelab.batch_reveal(k)


@router.get("/api/soelab/redo")
def soe_redo_view() -> dict:
    """다시 읽기: 열린 조각 하나(글만)와 진행. 7일 전이면 piece 가 비고 열리는 날을 준다."""
    return soelab.redo_view()


@router.post("/api/soelab/redo")
def soe_redo(body: SoeJudgeIn) -> dict:
    """다시 읽기(재판정) 저장. 첫 판정 7일 전이면 막는다."""
    out = soelab.save_judge(body.piece, body.verdict, [x.model_dump() for x in body.spans], body.clean, body.seconds, redo_too=True)
    return {**out, **soelab.redo_view()}


@router.put("/api/soelab/state")
def soe_state(body: SoeStateIn) -> dict:
    """가려 읽기 목표(40 · 60 · 90) · 여기서 멈추기 · 정답 카드를 넘긴 '이번 10개'."""
    soelab.set_state(**{k: v for k, v in body.model_dump().items() if v is not None})
    return soelab.screen()


@router.post("/api/soelab/spares/open")
def soe_spares_open() -> dict:
    """판정 일관성이 보류일 때 판정한 예비를 다시 읽기 대기열로 옮긴다(15개까지). 7일 규칙은 그대로."""
    n = soelab.open_spares()
    return {"opened": n, **soelab.screen()}


@router.post("/api/soelab/report")
def soe_report() -> dict:
    """다시 채점하기 (AI 없음). 새 보고서를 저장한다."""
    soelab.report()
    return soelab.screen()


@router.get("/api/soelab/reports")
def soe_reports() -> list[dict]:
    """기록: 보고서 목록."""
    return soelab.reports()


@router.get("/api/soelab/metrics/{mid}")
def soe_metric(mid: str) -> dict:
    """지표 하나. 점 그림 · 곡선 · 끝 조각은 가린 조각을 빼고."""
    return soelab.metric_view(mid)


@router.get("/api/soelab/patterns")
def soe_patterns() -> dict:
    """패턴 혼동표."""
    return soelab.patterns_view()


@router.get("/api/soelab/check")
def soe_check(kind: str = "", hit: str = "") -> dict:
    """패턴 확인: 패턴별 진행과 다음 문장."""
    return soelab.check_view(kind, hit)


@router.post("/api/soelab/check")
def soe_check_save(body: SoeCheckIn, kind: str = "") -> dict:
    """패턴 확인 하나 매기기. 다음 문장을 함께 준다."""
    soelab.save_check(body.hit, body.ok)
    return soelab.check_view(kind)


EXPORTS = (
    "SoeCheckIn",
    "SoeCollectIn",
    "SoeJudgeIn",
    "SoeOriginIn",
    "SoeSourceIn",
    "SoeSpanIn",
    "SoeStateIn",
    "_soe_sources",
    "soe_batch",
    "soe_check",
    "soe_check_save",
    "soe_collect",
    "soe_collect_preview",
    "soe_judge",
    "soe_judge_view",
    "soe_metric",
    "soe_patterns",
    "soe_piece",
    "soe_piece_origin",
    "soe_piece_remove",
    "soe_pieces",
    "soe_redo",
    "soe_redo_view",
    "soe_report",
    "soe_reports",
    "soe_sources",
    "soe_spares_open",
    "soe_state",
    "soe_view",
)
