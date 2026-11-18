"""인물 자취: 승인한 본문에서 한 인물이 남긴 선택 · 말 · 드러냄과 뒤 화의 다시 꺼냄 (Project.trails, CharTrail, TrailEcho).

채우는 길은 docs/trail 일감 6, 쓰는 길은 일감 9 다. 지금은 자리만 있다.
되돌리기(features.REVERT_LAST)와 다시 짜기(reshape)가 n화 뒤 자취 · 다시 꺼냄과 지워진 인물을 지운다.
LLM 을 부르지 않는다.
"""
from __future__ import annotations

from .schema import CharTrail, Project


def _clean(t: CharTrail, ids: set[str], n: int | None = None) -> CharTrail:
    """지워진 인물(과 n화 뒤 다시 꺼냄)을 뺀 사본."""
    return t.model_copy(update={
        "witnesses": [w for w in t.witnesses if w in ids],
        "echoes": [e for e in t.echoes if e.character in ids and (n is None or e.episode <= n)],
    })


def live(p: Project) -> list[CharTrail]:
    """주인이 p.characters 에 있는 자취만, 저장 차례 그대로.
    witnesses 와 echoes 에서 지워진 인물(echo.character 가 없는 인물)은 뺀 사본. p.trails 는 바꾸지 않는다."""
    ids = {c.id for c in p.characters}
    return [_clean(t, ids) for t in p.trails if t.character in ids]


def revert(p: Project, n: int) -> None:
    """되돌리기 훅. episode > n 인 자취와, 주인이 없는 인물인 자취를 지운다.
    남은 자취의 echoes 에서 episode > n 인 줄과 character 가 없는 인물인 줄을 지우고, witnesses 에서 없는 인물을 뺀다."""
    ids = {c.id for c in p.characters}
    p.trails = [_clean(t, ids, n) for t in p.trails if t.episode <= n and t.character in ids]


def next_id(p: Project, n: int) -> str:
    """n화 자취의 다음 id: f"tr-{n:03d}-{k}", k = 그 화의 가장 큰 차례 + 1. 없으면 1."""
    prefix = f"tr-{n:03d}-"
    top = 0
    for t in p.trails:
        if t.episode == n and t.id.startswith(prefix) and t.id[len(prefix):].isdigit():
            top = max(top, int(t.id[len(prefix):]))
    return f"{prefix}{top + 1}"
