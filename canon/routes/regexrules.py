"""정규식 규칙 묶음 (canon/regexrules.py, 작품 밖) 라우트와 작품의 켠 묶음 · 고침 되돌리기 라우트.

web 이 맨 끝에서 이 모듈을 불러 router 를 app 에 붙이고, 여기서 정한 이름(EXPORTS)을 web 에도 둔다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import regexrules
from ..schema import Project, RegexRule, RuleBundle
from ..web import (  # web 의 공용 도우미
    _edit,
    _load,
    _text_guard,
    _view,
)

router = APIRouter()


class RuleBundleIn(BaseModel):
    name: str
    notes: str = ""
    rules: list[RegexRule] = []
    note: str = ""  # 이번 버전 메모. 비우면 더한 · 뺀 · 고친 규칙 이름


class RuleTestIn(BaseModel):
    """규칙 시험. rules 를 주면 그 규칙(저장 전 편집 중인 것), 비우면 bundle 의 저장된 규칙을 건다.
    text 를 주면 그 글, 비우면 project 의 episode 화 본문에 건다. 저장하지 않는다."""
    rules: list[RegexRule] | None = None
    bundle: str = ""
    text: str = ""
    project: str = ""
    episode: int = 0


class RuleBundlesIn(BaseModel):
    bundles: list[str] = []  # 켤 묶음 id (거는 차례)


def _bundle_id(bid: str) -> str:
    if not regexrules.exists(bid):
        raise HTTPException(404, f"규칙 묶음이 없어요: {bid}")
    return bid


def _notices(rules: list[RegexRule]) -> list[str]:
    """저장은 막지 않는 알림. '<규칙 이름> · 알림'."""
    return [f"{r.comment or f'{k}번 규칙'} · {x}" for k, r in enumerate(rules, 1) for x in regexrules.notices(r)]


def _out(b: RuleBundle) -> dict:
    """묶음 전체 (규칙의 in_ 은 JSON 키 in) · 켠 작품 이름 · 저장을 막지 않는 알림."""
    return {**b.model_dump(by_alias=True), "used_by": regexrules.used_by(b.id), "notices": _notices(b.rules)}


@router.get("/api/rules")
def list_rules() -> list[dict]:
    return [regexrules.summary(b) for b in regexrules.entries()]


@router.post("/api/rules")
def create_rules(body: RuleBundleIn) -> dict:
    """새 묶음. 규칙 검사에 걸리면 400 과 '<규칙 이름> · 이 정규식은 저장할 수 없어요: …' 줄들."""
    return _out(regexrules.create(body.name, body.notes, body.rules, body.note or "처음 만듦"))


@router.post("/api/rules/test")
def test_rules(body: RuleTestIn) -> dict:
    """규칙을 글에 걸어 본다 (regexrules.trial). 고친 글 · 바뀐 곳 · 걸린 곳 · 내보내기 규칙까지 건 글 · 건너뛴 묶음. 저장하지 않는다."""
    if body.rules is not None:
        rules, bid, name = body.rules, body.bundle if regexrules.exists(body.bundle) else "", "시험"
        errors = regexrules.check(rules)
        if errors:
            raise ValueError("\n".join(errors))
        if bid:
            name = regexrules.load(bid).name
    elif body.bundle:
        b = regexrules.load(_bundle_id(body.bundle))
        rules, bid, name = b.rules, b.id, b.name
    else:
        raise ValueError("시험할 규칙이나 묶음을 고르세요")
    text = body.text
    if not text.strip():
        if not body.project:
            raise ValueError("시험할 글을 붙여 넣거나 작품의 화를 고르세요")
        text = _view(body.project).episode(body.episode).text
        if not text.strip():
            raise ValueError(f"{body.episode}화 본문이 없어요")
    return regexrules.trial(rules, text, bid, name)


@router.get("/api/rules/{bid}")
def get_rules(bid: str) -> dict:
    return _out(regexrules.load(_bundle_id(bid)))


@router.put("/api/rules/{bid}")
def put_rules(bid: str, body: RuleBundleIn) -> dict:
    """묶음을 통째로 고친다. 규칙 목록이 바뀌면 새 버전을 남긴다. 켠 작품 모두에 다음 걸기부터 적용된다."""
    return _out(regexrules.update(_bundle_id(bid), body.name, body.notes, body.rules, body.note))


@router.delete("/api/rules/{bid}")
def delete_rules(bid: str) -> dict:
    """묶음을 지운다. 켠 작품의 설정에는 id 가 남고 화면이 '찾을 수 없는 묶음이에요' 로 보인다."""
    regexrules.delete(_bundle_id(bid))
    return {"ok": True}


@router.get("/api/rules/{bid}/versions")
def rules_versions(bid: str) -> list[dict]:
    return regexrules.versions(regexrules.load(_bundle_id(bid)))


@router.post("/api/rules/{bid}/versions/{number}/restore")
def restore_rules(bid: str, number: int) -> dict:
    return _out(regexrules.restore(_bundle_id(bid), number))


@router.put("/api/projects/{name}/rule-bundles")
def put_rule_bundles(name: str, body: RuleBundlesIn) -> Project:
    """작품이 켤 묶음과 거는 차례를 통째로 바꾼다. 없는 묶음 id 는 거절한다.
    다만 이미 켜 둔 id 는 묶음이 지워졌어도 그대로 받는다 (화면이 '찾을 수 없는 묶음이에요' 로 보이며 작가가 끌 때까지 둔다).
    설정은 규칙을 걸 때 읽으므로 자동 집필 중이면 다음 걸기부터 따른다."""
    have = set(_view(name).settings.rule_bundles)
    ids: list[str] = []
    for bid in body.bundles:
        if bid in ids:
            continue
        if bid not in have and not regexrules.exists(bid):
            raise ValueError(f"규칙 묶음이 없어요: {bid}")
        ids.append(bid)

    def put(q: Project) -> None:
        q.settings.rule_bundles = ids
    return _edit(name, put)


@router.post("/api/projects/{name}/episodes/{n}/rule-runs/{rid}/undo")
def undo_rule_run(name: str, n: int, rid: str) -> dict:
    """규칙 걸기 한 번을 모두 되돌린다. 그 뒤에 같은 자리를 또 고쳐 찾지 못한 곳은 남긴다.
    undone · left 는 되돌린 곳 · 남긴 곳 수."""
    _load(name).episode(n)
    _text_guard(name, n)
    out: list = []
    p = _edit(name, lambda q: out.extend(regexrules.undo_run(q, n, rid)))
    done, left = out
    return {"project": p, "undone": len(done), "left": len(left)}


@router.post("/api/projects/{name}/episodes/{n}/rule-runs/{rid}/changes/{k}/undo")
def undo_rule_change(name: str, n: int, rid: str, k: int) -> Project:
    """규칙이 바꾼 곳 하나(k 번째, 0부터)를 되돌린다."""
    _load(name).episode(n)
    _text_guard(name, n)
    return _edit(name, lambda q: regexrules.undo_change(q, n, rid, k))


EXPORTS = (
    "RuleBundleIn",
    "RuleBundlesIn",
    "RuleTestIn",
    "create_rules",
    "delete_rules",
    "get_rules",
    "list_rules",
    "put_rule_bundles",
    "put_rules",
    "restore_rules",
    "rules_versions",
    "test_rules",
    "undo_rule_change",
    "undo_rule_run",
)
