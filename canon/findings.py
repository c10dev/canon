"""검수 세션: 회차마다 받은 검수 결과를 한 화의 지적 목록(Episode.findings)에 합치고, 작가가 정한 상태를 지킨다.

세션은 한 화의 검수 일 전체다. 첫 회차로 열리고, 본문을 지우면 비운다(clear). 새 판을 고르면 결정한 지적만 남긴다(new_version).
지적 상태: open(열림) · fixed(고침) · kept(그대로 둠) · wrong(잘못 짚음). 다시 검수하면(merge)
- 같은 문장을 짚은 옛 지적에 이어 붙인다. kept · wrong 은 그대로 두고, fixed 가 다시 나오면 다시 연다.
- 짚지 않은 열린 지적은 그 문장이 본문에 없으면 고침으로 닫는다. 문장이 그대로면 열어 둔다.
- 작가가 바꾼 심각도는 AI 값으로 덮지 않는다.
지적 하나만 다시 검수하면(settle) 회차는 늘지 않는다. 풀렸으면 고침으로 닫고, 고친 문장 때문에 새로 어긋난 곳은
그 지적에 딸린 지적(Finding.parent)으로 더한다.
그대로 둠 · 잘못 짚음은 검수 프롬프트에 넣지 않는다(합치기에서만 거른다). LLM 호출 없음.
"""
from __future__ import annotations

from typing import Optional

from .schema import (FINDING_STATUS, SEVERITY, CheckRound, CheckSource, ConsistencyIssue, Episode, Finding, FindingEvent,
                     FindingRecheck, FixOption)

ROUNDS_KEEP = 10  # 남기는 회차 수
LOG_KEEP = 20  # 지적마다 남기는 처리 기록 수
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


def log(f: Finding, at: str, kind: str, text: str = "") -> None:
    f.log = [*f.log, FindingEvent(at=at, kind=kind, text=text)][-LOG_KEEP:]  # type: ignore[arg-type]


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
    r = CheckRound(no=no, at=at, basis=basis, source=source, widen=widen)
    taken: set[str] = set()
    for x in issues:
        f = _match(ep, x, taken)
        r.found += 1
        if f is None:
            f = Finding(**x.model_dump(), id=_next_id(ep), first=no, last=no)
            log(f, at, "found", f"{no}회차 · {SEVERITY[f.severity]}")
            ep.findings.append(f)
            taken.add(f.id)
            r.added += 1
            r.added_ids.append(f.id)
            continue
        taken.add(f.id)
        r.again_ids.append(f.id)
        for k in ConsistencyIssue.model_fields:  # 근거 · 문장 · 고칠 방향은 새 회차 것으로
            if k == "severity" and f.severity_by_author:
                continue
            setattr(f, k, getattr(x, k))
        f.last = no
        if f.status == "fixed":
            f.status, f.closed_by, f.decided_at = "open", "", ""
            log(f, at, "again", f"{no}회차 · 다시 열림")
        elif f.status in DECIDED:
            r.kept_again += 1
            log(f, at, "again", f"{no}회차 · 결정 그대로")
        else:
            log(f, at, "again", f"{no}회차")
    for f in ep.findings:
        if f.id in taken or f.status != "open":
            continue
        quote = f.current_quote.strip()
        if quote and quote not in ep.text:  # 문장을 고쳐 다시 검수에서 사라졌다
            f.status, f.closed_by, f.decided_at = "fixed", "recheck", at
            log(f, at, "gone", f"{no}회차 · 문장이 사라져 고침")
            r.gone_ids.append(f.id)
    ep.rounds = [*ep.rounds, r][-ROUNDS_KEEP:]
    ep.issues, ep.checked_at = list(issues), at
    return r


def open_findings(ep: Episode) -> list[Finding]:
    return [f for f in ep.findings if f.status == "open"]


def counted(ep: Episode, issues: list[ConsistencyIssue], ignore_minor: bool = False) -> list[ConsistencyIssue]:
    """검수 결과 가운데 작가가 그대로 둠 · 잘못 짚음으로 정해 두지 않은 것 (자동 집필 허용 개수가 센다).
    ignore_minor 면 심각도 '사소'도 뺀다. 합치기 전후 어느 쪽에서 불러도 같다."""
    decided = [f for f in ep.findings if f.status in DECIDED]
    out = [x for x in issues if not any(same(f, x) for f in decided)]
    return [x for x in out if x.severity != "low"] if ignore_minor else out


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
    if f.status != status:
        log(f, at, "author", f"작가가 {FINDING_STATUS[status]}")
    f.status = status  # type: ignore[assignment]
    f.closed_by = "" if status == "open" else "author"
    f.decided_at = "" if status == "open" else at
    if note is not None:
        f.note = note.strip()
    return f


def set_severity(ep: Episode, fid: str, severity: str, at: str) -> Finding:
    """작가가 심각도를 정한다. 다시 검수해도 AI 값으로 덮지 않는다."""
    if severity not in SEVERITY:
        raise ValueError(f"심각도는 {', '.join(SEVERITY)} 중 하나예요: {severity}")
    f = find(ep, fid)
    if f.severity != severity:
        log(f, at, "author", f"심각도 {SEVERITY[severity]}")
    f.severity, f.severity_by_author = severity, True  # type: ignore[assignment]
    return f


def touches(ep: Episode, f: Finding, opt: FixOption) -> list[str]:
    """고침안 opt 가 바꾸는 문장(지적한 문장과 딸린 곳)이 짚고 있는 다른 지적 id. 지금 본문에 있는 문장만 본다."""
    quotes = [f.current_quote, *(x.quote for x in opt.extra)]
    out = []
    for g in ep.findings:
        q = g.current_quote.strip()
        if g.id == f.id or not q or q not in ep.text:
            continue
        if any(q in x or x in q or same_quote(q, x) for x in quotes if x.strip()):
            out.append(g.id)
    return out


def add_children(ep: Episode, parent: Finding, issues: list[ConsistencyIssue], at: str) -> list[Finding]:
    """parent 를 고친 문장 때문에 새로 어긋난 곳을 딸린 지적으로 더한다. 지금 본문에 없는 문장은 뺀다.
    결정한 지적이나 다른 열린 지적과 같은 문장이면 더하지 않는다 (parent 의 옛 문장과는 겹쳐도 된다)."""
    no = ep.rounds[-1].no if ep.rounds else 1
    keep = [g for g in ep.findings if g.id != parent.id and (g.status in DECIDED or g.status == "open")]
    out = []
    for x in issues:
        q = x.current_quote.strip()
        if not q or q not in ep.text or any(same(g, x) for g in [*keep, *out]):
            continue
        f = Finding(**x.model_dump(), id=_next_id(ep), first=no, last=no, parent=parent.id)
        log(f, at, "found", f"{parent.id}을 고친 뒤 이 지적만 다시 검수에서 생김 · {SEVERITY[f.severity]}")
        ep.findings.append(f)
        out.append(f)
    return out


def settle(ep: Episode, f: Finding, res: FindingRecheck, at: str) -> list[Finding]:
    """지적 하나만 다시 검수한 결과를 넣는다. 풀렸으면 고침(closed_by one)으로 닫는다. 회차는 늘지 않는다.
    작가가 다시 열면(set_status open) 되돌릴 수 있다. 새로 어긋난 곳은 딸린 지적으로 더하고 돌려준다."""
    if res.resolved:
        f.status, f.closed_by, f.decided_at = "fixed", "one", at
    log(f, at, "recheck", ("풀림" if res.resolved else "아직 어긋남") + (f" · {res.reason.strip()}" if res.reason.strip() else ""))
    kids = add_children(ep, f, res.new_issues, at)
    if kids:
        log(f, at, "recheck", f"고친 문장 때문에 새로 어긋난 곳 {len(kids)}개: {', '.join(k.id for k in kids)}")
    return kids


def new_version(ep: Episode) -> None:
    """본문을 새 판으로 바꿀 때: 그대로 둠 · 잘못 짚음 지적과 메모만 남기고 열림 · 고침 지적과 고침안은 지운다.
    회차는 남겨 번호를 잇고, 마지막 회차에 새 판 표시를 단다. 다음 검수가 같은 문장을 짚으면 결정이 그대로 지켜진다."""
    kept = [f for f in ep.findings if f.status in DECIDED]
    for f in kept:
        f.parent, f.fixes, f.fixes_basis, f.fix_group = "", [], "", ""
    ep.findings = kept
    if ep.rounds:
        ep.rounds[-1].superseded = True
    ep.issues, ep.checked_at = [], ""


def clear(ep: Episode) -> None:
    """세션을 비운다 (본문을 지울 때)."""
    ep.issues, ep.checked_at, ep.findings, ep.rounds = [], "", [], []


def line(ep: Episode, f: Finding) -> str:
    """명령줄 한 줄: id, 상태, 심각도, 갈래, 설명, 짚지 않은 회차 · 딸린 지적 표시."""
    last = ep.rounds[-1].no if ep.rounds else f.last
    miss = " · 이번 회차에서 안 짚음" if f.status == "open" and f.last < last and not f.parent else ""
    child = f" · {f.parent}을 고치다 생김" if f.parent else ""
    return f"{f.id} [{FINDING_STATUS[f.status]}] [{SEVERITY[f.severity]}] [{f.type}] {f.description}{miss}{child}"
