"""보는 눈: 한 인물이 다른 인물을 어떻게 보는지, 본문에 드러난 평가를 화마다 쌓은 기록 (Project.views, CharView).

지금은 자리만 있다. 채우는 길은 docs/trail 일감 8-2 의 상태 변경안이고, 승인한 것만 쌓인다.
되돌리기(features.REVERT_LAST)와 다시 짜기(reshape)가 n화 뒤 줄과 지워진 인물의 줄을 지운다.
LLM 을 부르지 않는다.
"""
from __future__ import annotations

from .schema import CharView, Project


def live(p: Project) -> list[CharView]:
    """보는 사람과 대상이 모두 p.characters 에 있는 줄만, 저장 차례 그대로."""
    ids = {c.id for c in p.characters}
    return [v for v in p.views if v.viewer in ids and v.target in ids]


def revert(p: Project, n: int) -> None:
    """되돌리기 훅. n화 뒤 줄과, 보는 사람 · 대상이 없는 인물인 줄을 지운다."""
    ids = {c.id for c in p.characters}
    p.views = [v for v in p.views if v.episode <= n and v.viewer in ids and v.target in ids]
