"""쓰기 재료 '조율'(Settings.write_material = coord).

감독이 장면마다 무엇이 바뀌어야 하는지만 정하고, 인물이 어떤 동작을 하는지는 본문을 쓰는 AI 가 정한다.
고정점만(board.fixed_only)에 더해 쓰기 요청을 이렇게 바꾼다 (prompts.board_block · write_plot · episode_parts).
- 플롯 summary · events · ending_hook 대신 조율 메모(Episode.coord, pipeline.make_coord)를 넣는다. 핵심 대사는 그대로다.
- 이어받을 것의 몸 · 물건 줄을 뺀다 (DROP_HANDOVER).
- 끝 차림은 어긋나지만 않게 지키고 본문에 꺼내지 않는다 (ATTIRE_HEAD).
- 쓰기 요청 끝에 조율 메모 단락(NOTE)을 붙인다. 조율 메모가 없거나 낡았으면 붙이지 않는다.

실측(2026-11-09, subway 79화, Claude Opus 5.5, reports/action-justify-2026-11-09): 작가 블라인드에서 조율판이 지금 판보다
두 회차 모두 높았다(3.23 대 3.0, 3.5 대 3.25). 같은 사건을 70분 · 장면 3개로 모은 판은 2.83 으로 낮았다.
LLM 호출 없음 (만들기는 pipeline.make_coord).
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from .schema import CoordMemo, EpisodePlot, Project

# 이어받을 것에서 빼는 종류. 손에 든 것 · 몸 상태를 본문이 다시 보여 주게 만드는 줄이다
DROP_HANDOVER = ("몸", "물건")
ATTIRE_HEAD = "끝 차림 (바뀐 인물만. 어긋나지만 않게 지키고, 본문에 일부러 보여 주거나 정리하는 장면을 넣지 않습니다):"
# 조율판 실측의 글 그대로 (2026-11-09)
NOTE = ("[조율 메모] 이번 화 플롯은 사건마다 무엇이 바뀌는지만 정했습니다. 그것을 어떤 동작과 대사로 보여 줄지, "
        "어느 사건을 장면으로 펼치고 어느 것을 한두 문장으로 넘길지는 직접 정합니다. 이동, 옷 갈아입기, 물건을 넣고 빼는 일은 "
        "그 동작이 사건을 바꿀 때만 씁니다. 장면과 장면 사이는 건너뛰어도 됩니다.")


def on(p: Project) -> bool:
    """쓰기 재료가 조율인지."""
    return p.settings.write_material == "coord"


def basis(plot: EpisodePlot) -> str:
    """조율 메모를 만드는 입력(플롯 summary · events · ending_hook)의 지문."""
    raw = json.dumps([plot.summary, plot.events, plot.ending_hook], ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def fresh(p: Project, n: int) -> bool:
    """n화 조율 메모가 있고 지금 플롯으로 만든 것인지."""
    ep = p.episode(n)
    m = ep.coord
    return bool(m and m.events and m.basis == basis(ep.plot) and len(m.events) == len(ep.plot.events))


def memo(p: Project, n: int) -> Optional[CoordMemo]:
    """쓰기 요청에 넣을 조율 메모. 조율이 아니거나, 없거나, 낡았으면 None (원래 플롯을 넣는다)."""
    return p.episode(n).coord if on(p) and fresh(p, n) else None


def remake(p: Project, n: int) -> bool:
    """쓰기 전에 조율 메모를 새로 만들지 (웹 쓰기 작업 · 자동 집필). 조율이고 메모가 없거나 낡았으면 참."""
    return on(p) and not fresh(p, n)


def plot(plot_: EpisodePlot, m: Optional[CoordMemo]) -> EpisodePlot:
    """플롯의 summary · events · ending_hook 을 조율 메모로 바꾼 사본. 메모가 없으면 그대로."""
    if m is None:
        return plot_
    return plot_.model_copy(update={"summary": m.summary, "events": list(m.events), "ending_hook": m.ending_hook})


def handover(rows: list) -> list:
    """쓰기 요청에 남길 이어받을 것. 몸 · 물건 줄을 뺀다."""
    return [h for h in rows if h.kind.strip() not in DROP_HANDOVER]
