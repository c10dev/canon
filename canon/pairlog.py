"""두 사람 사이 이력: 승인된 관계 사건 로그(Project.events)를 쌍마다 모아 쓰기 · 검수 블록으로 만든다.

새로 저장하는 데이터는 없다. 사건은 상태 변경안이 뽑고 작가가 승인한 것(StoryEvent)이고, 이 모듈은 읽기만 한다.
쓰기에는 이번 화 플롯 인물끼리의 쌍만 한 줄 라벨로 넣는다(예산 context.BUDGET['pairs']). 문장으로 쓴 이력은 본문에 그대로 옮겨지고
(쇠맛 연구 2026-10-30), 규칙 문장은 쓰기에서 지키기보다 검수에서 대조하는 편이 낫다.
검수에는 쌍마다 사건 갈래별 처음 일어난 화와 근거 문장을 넣고(예산 'check_pairs'), '처음 · 다시'가 앞 일과 맞는지 보게 한다.
장편 경로만 쓴다. LLM 호출 없음.
"""
from __future__ import annotations

from .schema import Project, StoryEvent

QUOTE_LIMIT = 80  # 검수 블록에 넣는 근거 문장 글자


def _pair(e: StoryEvent) -> tuple[str, str]:
    return tuple(sorted((e.actor, e.target)))  # type: ignore[return-value]


def history(p: Project, before: int) -> dict[tuple[str, str], list[StoryEvent]]:
    """before 화 전에 일어난 쌍별 사건 (수동보정 빼고), 일어난 순서대로."""
    out: dict[tuple[str, str], list[StoryEvent]] = {}
    for e in p.events:
        if e.episode >= before or e.kind == "수동보정" or e.actor == e.target:
            continue
        out.setdefault(_pair(e), []).append(e)
    return out


def _names(p: Project) -> dict[str, str]:
    return {c.id: c.name or c.id for c in p.characters}


def write_lines(p: Project, n: int, ids: set[str], budget: int) -> tuple[list[str], int]:
    """쓰기 블록 줄: ids(이번 화 플롯 인물) 끼리의 쌍마다 한 줄. 최근에 사건이 있던 쌍부터 예산(글자)까지. (줄, 뺀 쌍 수)"""
    nm = _names(p)
    rows = []
    for (a, b), evs in history(p, n).items():
        if a not in ids or b not in ids:
            continue
        first, last = evs[0], evs[-1]
        big = [e for e in evs if e.intensity >= 3]
        parts = [f"사건 {len(evs)}번", f"처음 {first.episode}화 {first.kind}"]
        if big:
            marks = list(dict.fromkeys(f"{e.episode}화 {e.kind}" for e in big))
            parts.append("결정적 " + ", ".join(marks[-3:]))
        if last is not first:
            parts.append(f"마지막 {last.episode}화 {last.kind}")
        rows.append((last.episode, f"- {nm.get(a, a)} ↔ {nm.get(b, b)}: " + " · ".join(parts)))
    rows.sort(key=lambda r: -r[0])
    out, used = [], 0
    for _, line in rows:
        if used + len(line) + 1 > budget:
            continue
        out.append(line)
        used += len(line) + 1
    return out, len(rows) - len(out)


def write_block(p: Project, n: int, ids: set[str], budget: int) -> str:
    """쓰기 프롬프트 블록. 이번 화 플롯 인물끼리 지난 사건이 없으면 빈 글."""
    lines, cut = write_lines(p, n, ids, budget)
    if not lines:
        return ""
    return ("\n\n# 두 사람 사이에 있었던 일 (승인된 관계 사건, 이번 화 인물끼리)\n" + "\n".join(lines)
            + (f"\n(그 밖 {cut}쌍 생략)" if cut else ""))


def check_block(p: Project, n: int, ids: set[str], budget: int) -> str:
    """검수 블록: ids 가 낀 쌍마다 사건 갈래별로 처음 일어난 화와 근거 문장. 최근에 사건이 있던 쌍부터 예산까지. 없으면 빈 글."""
    nm = _names(p)
    groups = []
    for (a, b), evs in history(p, n).items():
        if a not in ids or b not in ids:
            continue
        firsts: dict[str, StoryEvent] = {}
        for e in evs:
            firsts.setdefault(e.kind, e)
        rows = [f"  - {e.kind}: 처음 {e.episode}화" + (f" «{e.quote.strip()[:QUOTE_LIMIT]}»" if e.quote.strip() else "")
                for e in sorted(firsts.values(), key=lambda x: x.episode)]
        groups.append((evs[-1].episode, f"- {nm.get(a, a)} ↔ {nm.get(b, b)} (사건 {len(evs)}번)\n" + "\n".join(rows)))
    groups.sort(key=lambda g: -g[0])
    out, used, cut = [], 0, 0
    for _, text in groups:
        if used + len(text) + 1 > budget:
            cut += 1
            continue
        out.append(text)
        used += len(text) + 1
    if not out:
        return ""
    return ("\n\n# 두 사람 사이에 이미 있었던 일 (갈래별 처음 일어난 화와 근거)\n" + "\n".join(out)
            + (f"\n(그 밖 {cut}쌍 생략)" if cut else ""))


def check_rule(block: str) -> str:
    """검수 요구사항 한 줄. 블록이 비면 빈 글."""
    if not block:
        return ""
    return ("\n- 처음 · 다시: 본문이 '처음', '다시', '또', '오랜만에'로 적은 두 사람 사이의 일이 "
            "[두 사람 사이에 이미 있었던 일]과 맞는지 봅니다. 예: 이미 고백한 사이인데 첫 고백처럼 씀. "
            "근거는 그 블록의 화와 근거 문장입니다.")
