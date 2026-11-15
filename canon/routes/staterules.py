"""상태 규칙 (canon/staterules.py, 작품 안 Project.state_rules) 라우트. docs/context/specs/07-rules.md 의 7b.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다.
규칙은 작가가 적는 설정이라 승인 흐름을 거치지 않고 바로 저장한다. 규칙이 만드는 상태 변경 제안은 상태 승인 화면에서만 반영된다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import staterules
from ..schema import StateRule
from ..web import (  # web 의 공용 도우미
    _edit,
    _view,
)

router = APIRouter()


def _find(p, rid: str) -> StateRule:
    r = next((x for x in p.state_rules if x.id == rid), None)
    if r is None:
        raise HTTPException(404, f"없는 상태 규칙이에요: {rid}")
    return r


@router.get("/api/projects/{name}/state-rules")
def list_state_rules(name: str) -> list[StateRule]:
    return _view(name).state_rules


@router.post("/api/projects/{name}/state-rules")
def create_state_rule(name: str, rule: StateRule) -> list[StateRule]:
    """규칙 하나를 목록 끝에 더한다. id 는 서버가 붙인다."""
    def add(p):
        p.state_rules.append(rule.model_copy(update={"id": ""}))
        staterules.fill_ids(p.state_rules)
    return _edit(name, add).state_rules


@router.put("/api/projects/{name}/state-rules/{rid}")
def put_state_rule(name: str, rid: str, rule: StateRule) -> list[StateRule]:
    """규칙 하나를 통째로 바꾼다. id 와 목록 자리는 그대로다."""
    def put(p):
        i = p.state_rules.index(_find(p, rid))
        p.state_rules[i] = rule.model_copy(update={"id": rid})
    return _edit(name, put).state_rules


@router.delete("/api/projects/{name}/state-rules/{rid}")
def delete_state_rule(name: str, rid: str) -> list[StateRule]:
    def drop(p):
        p.state_rules.remove(_find(p, rid))
    return _edit(name, drop).state_rules


EXPORTS = (
    "create_state_rule",
    "delete_state_rule",
    "list_state_rules",
    "put_state_rule",
)
