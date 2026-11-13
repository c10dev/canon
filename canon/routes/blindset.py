"""가려 읽기 묶음 (canon/blindset.py, 작품 밖 화면 #/blind) 라우트.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import blindset

router = APIRouter()

# 묶음 하나가 <CANON_HOME>/.blind/<id>.json 하나다. AI 를 부르지 않는다. 열쇠는 결과를 연 뒤에만 응답에 싣는다 (blindset.view).


class BlindTextIn(BaseModel):
    no: str = ""
    text: str


class BlindKeyIn(BaseModel):
    no: str
    arm: str
    piece: str = ""


class BlindIn(BaseModel):
    title: str = ""
    note: str = ""
    items: list[BlindTextIn]
    key: list[BlindKeyIn] = []


class BlindScoreIn(BaseModel):
    score: int  # 1 ~ blindset.SCALE, 0 은 지움
    note: str = ""


class BlindMarkIn(BaseModel):
    idx: int  # blindset.sentences 로 나눈 문장의 차례 (0 부터)
    on: bool = True


def _set(bid: str):
    try:
        return blindset.load(bid)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))


@router.get("/api/blind")
def list_blind() -> dict:
    return {"sets": [blindset.summary(s) for s in blindset.sets()]}


@router.post("/api/blind")
def create_blind(body: BlindIn) -> dict:
    """묶음을 넣는다 (실험 스크립트용. 화면에는 넣는 칸이 없다)."""
    try:
        s = blindset.create(body.title, [x.model_dump() for x in body.items], [k.model_dump() for k in body.key], body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return blindset.view(s)


@router.get("/api/blind/{bid}")
def get_blind(bid: str) -> dict:
    return blindset.view(_set(bid))


@router.put("/api/blind/{bid}/items/{no}")
def score_blind(bid: str, no: str, body: BlindScoreIn) -> dict:
    _set(bid)
    try:
        return blindset.view(blindset.score(bid, no, body.score, body.note))
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/blind/{bid}/items/{no}/marks")
def mark_blind(bid: str, no: str, body: BlindMarkIn) -> dict:
    """결과를 연 묶음에서 거슬린 문장을 긋거나 지운다 (열기 전에는 400)."""
    _set(bid)
    try:
        return blindset.view(blindset.mark(bid, no, body.idx, body.on))
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/blind/{bid}/reveal")
def reveal_blind(bid: str) -> dict:
    _set(bid)
    try:
        return blindset.view(blindset.reveal(bid))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/blind/{bid}")
def delete_blind(bid: str) -> dict:
    _set(bid)
    blindset.delete(bid)
    return {"ok": True}


EXPORTS = (
    "BlindIn",
    "BlindKeyIn",
    "BlindMarkIn",
    "BlindScoreIn",
    "BlindTextIn",
    "create_blind",
    "delete_blind",
    "get_blind",
    "list_blind",
    "mark_blind",
    "reveal_blind",
    "score_blind",
)
