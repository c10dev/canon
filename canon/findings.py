"""검수 세션: 회차마다 받은 검수 결과를 한 화의 지적 목록(Episode.findings)에 합치고, 작가가 정한 상태를 지킨다.

세션은 한 화의 검수 일 전체다. 첫 회차로 열리고, 새 판을 고르거나 본문을 지우면 비운다(clear).
지적 상태: open(열림) · fixed(고침) · kept(그대로 둠) · wrong(잘못 짚음). 다시 검수하면(merge)
- 같은 문장을 짚은 옛 지적에 이어 붙인다. kept · wrong 은 그대로 두고, fixed 가 다시 나오면 다시 연다.
- 짚지 않은 열린 지적은 그 문장이 본문에 없으면 고침으로 닫는다. 문장이 그대로면 열어 둔다.
그대로 둠 · 잘못 짚음은 검수 프롬프트에 넣지 않는다(합치기에서만 거른다). LLM 호출 없음.
"""
from __future__ import annotations

from typing import Optional

from .schema import FINDING_STATUS, CheckRound, CheckSource, ConsistencyIssue, Episode, Finding

ROUNDS_KEEP = 10  # 남기는 회차 수
DECIDED = ("kept", "wrong")


def same_quote(a: str, b: str) -> bool:
    """두 인용이 같은 문장을 짚는지: 짧은 쪽 글 조각의 절반 이상이 겹친다."""
    from .context import grams

    ga, gb = grams(a), grams(b)
    small = min(len(ga), len(gb))
    return a.strip() == b.strip() or (small > 0 and len(ga & gb) / small >= 0.5)


def same(a: ConsistencyIssue, b: ConsistencyIssue) -> bool:
    """두 지적이 같은 문장을 짚는지. 문장이 없으면 설명이 같아야 같다."""
    qa, qb = a.current_quote.strip(), b.current_quote.strip()
    if not qa or not qb:
        return not qa and not qb and a.description.strip() == b.description.strip()
    return same_quote(qa, qb)


def _match(ep: Episode, x: ConsistencyIssue, taken: set[str]) -> Optional[Finding]:
    """x 와 같은 문장을 짚은 옛 지적. 같은 갈래를 먼저 찾는다. 이번 회차에 이미 이은 지적은 건너뛴다."""
    cands = [f for f in ep.findings if f.id not in taken and same(f, x)]
    return next((f for f in cands if f.type == x.type), cands[0] if cands else None)


def _next_id(ep: Episode) -> str:
    nums = [int(f.id[1:]) for f in ep.findings if f.id[:1] == "f" and f.id[1:].isdigit()]
    return f"f{max(nums, default=0) + 1}"


def merge(ep: Episode, issues: list[ConsistencyIssue], at: str, basis: str,
          source: CheckSource = "api", widen: bool = False) -> CheckRound:
    """새 회차의 검수 결과를 지적 목록에 합친다. issues · checked_at 은 이 회차 결과 그대로 둔다."""
    no = (ep.rounds[-1].no if ep.rounds else 0) + 1
    taken: set[str] = set()
    found = added = kept = 0
    for x in issues:
        f = _match(ep, x, taken)
        found += 1
        if f is None:
            ep.findings.append(Finding(**x.model_dump(), id=_next_id(ep), first=no, last=no))
            taken.add(ep.findings[-1].id)
            added += 1
            continue
        taken.add(f.id)
        for k in ConsistencyIssue.model_fields:  # 근거 · 문장 · 고칠 방향은 새 회차 것으로
            setattr(f, k, getattr(x, k))
        f.last = no
        if f.status == "fixed":
            f.status, f.closed_by, f.decided_at = "open", "", ""
        elif f.status in DECIDED:
            kept += 1
    for f in ep.findings:
        if f.id in taken or f.status != "open":
            continue
        quote = f.current_quote.strip()
        if quote and quote not in ep.text:  # 문장을 고쳐 다시 검수에서 사라졌다
            f.status, f.closed_by, f.decided_at = "fixed", "recheck", at
    r = CheckRound(no=no, at=at, basis=basis, source=source, widen=widen, found=found, added=added, kept_again=kept)
    ep.rounds = [*ep.rounds, r][-ROUNDS_KEEP:]
    ep.issues, ep.checked_at = list(issues), at
    return r


def open_findings(ep: Episode) -> list[Finding]:
    return [f for f in ep.findings if f.status == "open"]


def counted(ep: Episode, issues: list[ConsistencyIssue]) -> list[ConsistencyIssue]:
    """검수 결과 가운데 작가가 그대로 둠 · 잘못 짚음으로 정해 두지 않은 것 (자동 집필 허용 개수가 센다).
    합치기 전후 어느 쪽에서 불러도 같다."""
    decided = [f for f in ep.findings if f.status in DECIDED]
    return [x for x in issues if not any(same(f, x) for f in decided)]


def find(ep: Episode, fid: str) -> Finding:
    f = next((f for f in ep.findings if f.id == fid), None)
    if f is None:
        raise ValueError(f"{ep.plot.number}화에 그런 지적이 없어요: {fid}")
    return f


def set_status(ep: Episode, fid: str, status: str, note: Optional[str], at: str) -> Finding:
    """작가가 지적 상태를 정한다. note 를 비우면(None) 메모는 그대로 둔다."""
    if status not in FINDING_STATUS:
        raise ValueError(f"지적 상태는 {', '.join(FINDING_STATUS)} 중 하나예요: {status}")
    f = find(ep, fid)
    f.status = status  # type: ignore[assignment]
    f.closed_by = "" if status == "open" else "author"
    f.decided_at = "" if status == "open" else at
    if note is not None:
        f.note = note.strip()
    return f


def clear(ep: Episode) -> None:
    """세션을 비운다 (새 판을 고르거나 본문을 지울 때)."""
    ep.issues, ep.checked_at, ep.findings, ep.rounds = [], "", [], []


def line(ep: Episode, f: Finding) -> str:
    """명령줄 한 줄: id, 상태, 갈래, 설명, 짚지 않은 회차 표시."""
    last = ep.rounds[-1].no if ep.rounds else f.last
    miss = " · 이번 회차에서 안 짚음" if f.status == "open" and f.last < last else ""
    return f"{f.id} [{FINDING_STATUS[f.status]}] [{f.type}] {f.description}{miss}"
