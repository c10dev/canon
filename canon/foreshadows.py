"""복선 센터: 복선마다 심은 자리와 회수한 자리를 본문 문장에 걸어 두고, 회수율과 끊어진 연결을 계산한다.

근거 문장(ForeshadowClue)은 Project.foreshadow_clues 에 사건 로그처럼 쌓인다. 본문은 바꾸지 않는다.
AI 는 상태 변경안의 foreshadow_clues 로 문장을 내고, 작가는 본문에서 골라 직접 붙인다.
작가가 고친 복선은 지금 상태와 그 화 이후의 스냅샷에 함께 적어, 되돌려도 작가 입력이 남게 한다. LLM 을 부르지 않는다.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional

from .schema import Foreshadow, ForeshadowClue, Project, StateDelta

LONG_OPEN = 50  # 이 화수 넘게 다시 떠올리지 않은 열린 복선은 오래 묵었다고 본다 (아크 화면의 경고와 같은 값)
SCOPES = {"arc": "이번 아크", "part": "이번 부", "series": "작품 전체"}

_SKIP = re.compile(r"[\s\"'“”‘’「」『』《》〈〉.,!?…·~\-–—()\[\]]+")


def norm(s: str) -> str:
    """띄어쓰기, 따옴표, 문장 부호를 뺀 글자. 본문을 조금 다듬어도 근거 문장을 다시 찾게 한다."""
    return _SKIP.sub("", s or "")


def found(text: str, quote: str) -> bool:
    q = norm(quote)
    return bool(q) and q in norm(text)


def _text(p: Project, n: int) -> str:
    try:
        return p.episode(n).text
    except KeyError:
        return ""


def _key(c: ForeshadowClue) -> tuple:
    return (c.foreshadow, c.episode, c.kind, norm(c.quote))


def last_done(p: Project) -> int:
    return max((e.plot.number for e in p.episodes if e.status == "finalized"), default=0)


# ---------- AI 변경안 ----------

def clean_delta(p: Project, d: StateDelta) -> None:
    """AI 가 낸 근거 문장을 다듬는다. 모르는 복선, 본문에서 찾을 수 없는 문장, 겹친 문장은 뺀다.
    회수 목록(foreshadow_resolved)에 없는 복선의 회수 문장은 다시 떠올린 문장(plant)으로 본다."""
    text = _text(p, d.episode)
    ids = {f.id for f in p.foreshadows} | {f.id for f in d.foreshadow_planted}
    resolved = set(d.foreshadow_resolved)
    out, seen = [], set()
    for c in d.foreshadow_clues:
        c.episode, c.by, c.quote = d.episode, "ai", c.quote.strip()
        if c.foreshadow not in ids or not found(text, c.quote):
            continue
        if c.kind == "payoff" and c.foreshadow not in resolved:
            c.kind = "plant"
        if _key(c) in seen:
            continue
        seen.add(_key(c))
        out.append(c)
    d.foreshadow_clues = out


def apply_delta(p: Project, d: StateDelta) -> None:
    """pipeline.apply_delta 가 복선을 심고 회수한 뒤 부른다. 고른 복선에 걸린 문장만 남긴다."""
    have = {f.id for f in p.foreshadows}
    resolved = set(d.foreshadow_resolved)
    known = {_key(c) for c in p.foreshadow_clues}
    for c in d.foreshadow_clues:
        if c.foreshadow not in have or (c.kind == "payoff" and c.foreshadow not in resolved):
            continue
        c = c.model_copy(update={"episode": d.episode, "by": "ai"})
        if _key(c) not in known:
            known.add(_key(c))
            p.foreshadow_clues.append(c)


def revert(p: Project, n: int) -> None:
    """pipeline.revert 뒤에 부른다. n화 뒤의 AI 근거는 지우고, 작가가 붙인 근거는 복선이 남아 있으면 둔다."""
    ids = {f.id for f in p.foreshadows}
    p.foreshadow_clues = [c for c in p.foreshadow_clues
                          if c.foreshadow in ids and (c.episode <= n or c.by == "author")]


def state_rule(p: Project) -> str:
    """상태 정리 요구사항에 붙는 한 줄."""
    return ("\n- foreshadow_clues 에는 복선이 본문에 걸린 문장을 적습니다. 새로 심은 복선과 [열린 복선] 가운데 이번 화에서 다시 떠올린 것은 kind 를 plant, "
            "foreshadow_resolved 에 넣은 복선은 payoff 로 두고, quote 에는 그 문장을 본문에서 글자 그대로 옮깁니다. 복선 하나에 한두 문장이면 됩니다.")


# ---------- 작가가 고치기 ----------

def _copies(p: Project, n: int) -> Iterator[list[Foreshadow]]:
    """지금 복선 목록과 n화 이후 스냅샷의 복선 목록. 작가가 n화에 한 일을 되돌려도 남게 함께 고친다."""
    yield p.foreshadows
    for s in p.snapshots:
        if s.episode >= n:
            yield s.foreshadows


def _find(fs: list[Foreshadow], fid: str) -> Optional[Foreshadow]:
    return next((f for f in fs if f.id == fid), None)


def get(p: Project, fid: str) -> Foreshadow:
    f = _find(p.foreshadows, fid)
    if f is None:
        raise KeyError(f"없는 복선이에요: {fid}")
    return f


def _check_ep(p: Project, n: int) -> None:
    try:
        p.episode(n)
    except KeyError:
        raise ValueError(f"{n}화가 없어요") from None


def new_id(p: Project, n: int) -> str:
    have = {f.id for f in p.foreshadows}
    k = 1
    while f"fs-{n:02d}-a{k}" in have:
        k += 1
    return f"fs-{n:02d}-a{k}"


def add(p: Project, description: str, n: int, scope: str = "arc", due_ep: Optional[int] = None) -> Foreshadow:
    """작가가 복선을 직접 더한다. n화에 심은 것으로 본다."""
    description = description.strip()
    if not description:
        raise ValueError("복선 내용을 적어 주세요")
    _check_ep(p, n)
    if scope not in SCOPES:
        raise ValueError(f"회수 범위는 {', '.join(SCOPES)} 중 하나예요")
    if due_ep is not None and due_ep < n:
        raise ValueError("회수 예정 화가 심은 화보다 앞이에요")
    f = Foreshadow(id=new_id(p, n), description=description, planted_ep=n, scope=scope, due_ep=due_ep)  # type: ignore[arg-type]
    for fs in _copies(p, n):
        fs.append(f.model_copy(deep=True))
    return f


def update(p: Project, fid: str, description: Optional[str] = None, scope: Optional[str] = None,
           due_ep: Optional[int] = None, clear_due: bool = False) -> Foreshadow:
    """내용, 회수 범위, 회수 예정 화를 고친다. 기록이 어긋나지 않게 모든 스냅샷에 같이 적는다."""
    f = get(p, fid)
    if scope is not None and scope not in SCOPES:
        raise ValueError(f"회수 범위는 {', '.join(SCOPES)} 중 하나예요")
    if due_ep is not None and due_ep < f.planted_ep:
        raise ValueError("회수 예정 화가 심은 화보다 앞이에요")
    if description is not None and not description.strip():
        raise ValueError("복선 내용을 비울 수 없어요")
    for fs in _copies(p, 0):
        x = _find(fs, fid)
        if x is None:
            continue
        if description is not None:
            x.description = description.strip()
        if scope is not None:
            x.scope = scope  # type: ignore[assignment]
        if due_ep is not None or clear_due:
            x.due_ep = due_ep
    return f


def resolve(p: Project, fid: str, n: int) -> None:
    f = get(p, fid)
    if n < f.planted_ep:
        raise ValueError(f"{f.planted_ep}화에 심은 복선을 {n}화에서 회수할 수 없어요")
    for fs in _copies(p, n):
        x = _find(fs, fid)
        if x is not None:
            x.status, x.payoff_ep = "resolved", n


def reopen(p: Project, fid: str) -> None:
    """회수를 취소한다. 회수 문장도 지운다."""
    f = get(p, fid)
    for fs in _copies(p, 0):
        x = _find(fs, fid)
        if x is not None:
            x.status, x.payoff_ep = "open", None
    p.foreshadow_clues = [c for c in p.foreshadow_clues if not (c.foreshadow == f.id and c.kind == "payoff")]


def remove(p: Project, fid: str) -> None:
    """복선을 지운다. 걸린 문장도 함께. 플롯에 적힌 id 는 그대로 둔다."""
    get(p, fid)
    for fs in _copies(p, 0):
        fs[:] = [x for x in fs if x.id != fid]
    p.foreshadow_clues = [c for c in p.foreshadow_clues if c.foreshadow != fid]


def add_clue(p: Project, n: int, quote: str, fid: str, kind: str = "plant") -> ForeshadowClue:
    """작가가 본문에서 고른 문장을 복선에 건다. 회수 문장이면 그 화에 회수한 것으로 표시한다."""
    if kind not in ("plant", "payoff"):
        raise ValueError("kind는 plant나 payoff예요")
    f = get(p, fid)
    quote = quote.strip()
    if not found(_text(p, n), quote):
        raise ValueError(f"{n}화 본문에서 고른 문장을 찾지 못했어요")
    if n < f.planted_ep and kind == "plant":
        for fs in _copies(p, 0):  # 더 앞 화에서 실마리를 찾았다: 심은 화를 당긴다
            x = _find(fs, fid)
            if x is not None:
                x.planted_ep = n
    if kind == "payoff":
        resolve(p, fid, n)
    c = ForeshadowClue(foreshadow=fid, kind=kind, quote=quote, episode=n, by="author")  # type: ignore[arg-type]
    if _key(c) not in {_key(x) for x in p.foreshadow_clues}:
        p.foreshadow_clues.append(c)
    return c


def remove_clue(p: Project, fid: str, n: int, quote: str) -> None:
    before = len(p.foreshadow_clues)
    q = norm(quote)
    p.foreshadow_clues = [c for c in p.foreshadow_clues if not (c.foreshadow == fid and c.episode == n and norm(c.quote) == q)]
    if len(p.foreshadow_clues) == before:
        raise KeyError("그 문장이 걸려 있지 않아요")


def broken(p: Project) -> list[ForeshadowClue]:
    """본문을 고쳐 문장이 사라졌거나 화가 없어진 연결."""
    texts: dict[int, str] = {}
    out = []
    for c in p.foreshadow_clues:
        if c.episode not in texts:
            texts[c.episode] = norm(_text(p, c.episode))
        q = norm(c.quote)
        if not q or q not in texts[c.episode]:
            out.append(c)
    return out


def prune(p: Project) -> int:
    gone = {id(c) for c in broken(p)}
    p.foreshadow_clues = [c for c in p.foreshadow_clues if id(c) not in gone]
    return len(gone)


# ---------- 보기 ----------

def center(p: Project) -> dict:
    """복선 센터 화면과 CLI 가 쓰는 계산값."""
    done = last_done(p)
    bad = {id(c) for c in broken(p)}
    planned: dict[str, list[int]] = {}
    for e in p.episodes:
        if e.status != "finalized":
            for fid in e.plot.foreshadow_payoff:
                planned.setdefault(fid, []).append(e.plot.number)
    items = []
    for f in p.foreshadows:
        cs = sorted((c for c in p.foreshadow_clues if c.foreshadow == f.id), key=lambda c: (c.episode, c.kind))
        row = lambda c: {"episode": c.episode, "quote": c.quote, "by": c.by, "broken": id(c) in bad}  # noqa: E731
        plants = [row(c) for c in cs if c.kind == "plant"]
        payoffs = [row(c) for c in cs if c.kind == "payoff"]
        seen = max([f.planted_ep] + [c["episode"] for c in plants])
        items.append({
            **f.model_dump(),
            "plants": plants,
            "payoffs": payoffs,
            "last_seen": seen,
            "planned": planned.get(f.id, []),
            "overdue": f.status == "open" and f.due_ep is not None and f.due_ep <= done,  # 예정 화까지 반영했는데 회수하지 않았다
            "stale": f.status == "open" and done - seen > LONG_OPEN,
            "broken": sum(1 for c in plants + payoffs if c["broken"]),
        })
    items.sort(key=lambda x: (x["planted_ep"], x["id"]))
    total = len(items)
    resolved = sum(1 for x in items if x["status"] == "resolved")
    last = max([e.plot.number for e in p.episodes] + [x["due_ep"] or 0 for x in items] + [1])
    return {
        "total": total,
        "open": total - resolved,
        "resolved": resolved,
        "rate": round(resolved / total, 3) if total else None,
        "broken": len(bad),
        "overdue": sum(1 for x in items if x["overdue"]),
        "stale": sum(1 for x in items if x["stale"]),
        "done": done,
        "last_ep": last,
        "items": items,
    }


def describe(p: Project, show_all: bool = False) -> str:
    """명령줄 출력."""
    c = center(p)
    if not c["total"]:
        return "복선이 아직 없습니다."
    rate = f"{round(c['rate'] * 100)}%" if c["rate"] is not None else "-"
    lines = [f"복선 {c['total']}개 · 회수 {c['resolved']} · 열림 {c['open']} · 회수율 {rate}"
             + (f" · 끊어진 연결 {c['broken']}" if c["broken"] else "")
             + (f" · 예정 지남 {c['overdue']}" if c["overdue"] else "")]
    for x in c["items"]:
        if not show_all and x["status"] == "resolved":
            continue
        mark = "회수" if x["status"] == "resolved" else "열림"
        when = f"{x['planted_ep']}화 → {x['payoff_ep']}화" if x["payoff_ep"] else f"{x['planted_ep']}화~"
        flags = [s for s, on in (("예정 지남", x["overdue"]), (f"{LONG_OPEN}화 넘게 묵음", x["stale"]),
                                 (f"끊어진 연결 {x['broken']}", x["broken"])) if on]
        due = f" · 예정 {x['due_ep']}화" if x["due_ep"] else ""
        lines.append(f"\n[{mark}] {x['description']} ({x['id']}, {SCOPES.get(x['scope'], x['scope'])}) {when}{due}"
                     + (f"  ! {', '.join(flags)}" if flags else ""))
        for k, label in (("plants", "심음"), ("payoffs", "회수")):
            for q in x[k]:
                lines.append(f"    {q['episode']}화 {label}{' (작가)' if q['by'] == 'author' else ''}{' [끊어짐]' if q['broken'] else ''}: \"{q['quote']}\"")
    if not show_all and c["resolved"]:
        lines.append(f"\n(회수한 복선 {c['resolved']}개는 --all 로 봅니다)")
    return "\n".join(lines)
