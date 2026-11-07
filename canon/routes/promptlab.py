"""프롬프트 놀이터 (canon/promptlab.py, 작품 밖 화면 #/promptlab) 라우트.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import promptlab, usage
from ..schema import PromptBackend, PromptSession

router = APIRouter()

# 돌리기는 문단 연습장의 AI 안처럼 작업 목록을 거치지 않고 바로 돌려준다. 백엔드는 차례로 부른다.


class PromptIn(BaseModel):
    title: str = ""
    system: str = ""
    prompt: str = ""
    temperature: Optional[float] = None
    backends: list[PromptBackend] = Field(default_factory=lambda: [PromptBackend()])


class PromptTrialEdit(BaseModel):
    star: Optional[bool] = None
    note: Optional[str] = None


def _lab(sid: str) -> PromptSession:
    try:
        return promptlab.load(sid)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


def _trial(s: PromptSession, no: int):
    try:
        return promptlab.find(s, no)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None


@router.get("/api/promptlab")
def list_promptlab() -> dict:
    return {"sessions": [promptlab.summary(x) for x in promptlab.sessions()], **promptlab.limits()}


@router.post("/api/promptlab")
def create_promptlab(body: PromptIn) -> dict:
    return promptlab.view(promptlab.create(body.title, body.system, body.prompt, body.temperature, body.backends))


@router.get("/api/promptlab/{sid}")
def get_promptlab(sid: str) -> dict:
    return promptlab.view(_lab(sid))


@router.put("/api/promptlab/{sid}")
def put_promptlab(sid: str, body: PromptIn) -> dict:
    _lab(sid)
    return promptlab.view(promptlab.update(sid, body.title, body.system, body.prompt, body.temperature, body.backends))


@router.delete("/api/promptlab/{sid}")
def delete_promptlab(sid: str) -> dict:
    _lab(sid)
    promptlab.delete(sid)
    return {"ok": True}


@router.post("/api/promptlab/{sid}/duplicate")
def duplicate_promptlab(sid: str) -> dict:
    _lab(sid)
    return promptlab.view(promptlab.duplicate(sid))


@router.post("/api/promptlab/{sid}/run")
def run_promptlab(sid: str, body: PromptIn) -> dict:
    """받은 프롬프트를 먼저 저장하고 고른 백엔드마다 돌린다. 도는 동안 바뀐 시도(별표 · 메모)를 덮지 않게 저장 직전에 다시 읽는다."""
    _lab(sid)
    s = promptlab.update(sid, body.title, body.system, body.prompt, body.temperature, body.backends)
    with usage.scope(task="promptlab"):
        runs = promptlab.run(s)
    fresh = _lab(sid)
    promptlab.add_trial(fresh, s.system, s.prompt, s.temperature, runs)
    return promptlab.view(promptlab.save(fresh))


@router.put("/api/promptlab/{sid}/trials/{no}")
def edit_promptlab_trial(sid: str, no: int, body: PromptTrialEdit) -> dict:
    s = _lab(sid)
    _trial(s, no)
    promptlab.edit(s, no, body.star, body.note)
    return promptlab.view(promptlab.save(s))


@router.delete("/api/promptlab/{sid}/trials/{no}")
def delete_promptlab_trial(sid: str, no: int) -> dict:
    s = _lab(sid)
    _trial(s, no)
    promptlab.remove(s, no)
    return promptlab.view(promptlab.save(s))


@router.post("/api/promptlab/{sid}/trials/{no}/restore")
def restore_promptlab_trial(sid: str, no: int) -> dict:
    """그 시도의 프롬프트 · 온도를 지금 칸으로 되돌려 저장한다."""
    s = _lab(sid)
    _trial(s, no)
    return promptlab.view(promptlab.save(promptlab.restore(s, no)))


EXPORTS = (
    "create_promptlab",
    "delete_promptlab",
    "delete_promptlab_trial",
    "duplicate_promptlab",
    "edit_promptlab_trial",
    "get_promptlab",
    "list_promptlab",
    "put_promptlab",
    "restore_promptlab_trial",
    "run_promptlab",
)
