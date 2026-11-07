"""열 계획 가짜 응답 (CANON_LLM=mock). 기승전결과 함께 받는 열 계획(HeatArcPlan)을 mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import _arc, responds
from .schema import Foreshadow, HeatArcPlan, HeatStep, HeatTurn


def shape(total: int) -> list[HeatStep]:
    """앞쪽은 쌓기, 13화 이상이면 승 끝에 낮은 정점, 전 끝 두 화(짧으면 한 화)에 큰 정점, 결은 뒷날 · 쉬기."""
    acts = {a.name: a for a in _arc(total)}
    seung, jeon, gyeol = acts["승"], acts["전"], acts["결"]
    hot = 2 if jeon.end_ep - jeon.start_ep >= 2 else 1
    out: list[HeatStep] = []
    for n in range(1, total + 1):
        if seung.start_ep <= n <= seung.end_ep and total >= 13 and n == seung.end_ep:
            s = HeatStep(ep=n, level=3, role="peak", kind="맨정신의 흥정")
        elif jeon.start_ep <= n <= jeon.end_ep and n > jeon.end_ep - hot:
            s = HeatStep(ep=n, level=5 if n == jeon.end_ep else 4, role="peak", kind="관객 앞 들킴")
        elif out and out[-1].role == "peak":
            s = HeatStep(ep=n, level=1, role="after")
        elif gyeol.start_ep <= n:
            s = HeatStep(ep=n, level=1, role="rest")
        elif seung.start_ep <= n:
            s = HeatStep(ep=n, level=2, role="hold")
        else:
            s = HeatStep(ep=n, level=0 if n == 1 else 1, role="build")
        out.append(s.model_copy(update={"note": f"{n}화 열 몫"}))
    return out


@responds(HeatArcPlan)
def _r_heat_arc_plan(prompt: str, hint: dict) -> HeatArcPlan:
    total = int(hint["total"])
    steps = shape(total)
    peak = next(s.ep for s in steps if s.role == "peak")
    return HeatArcPlan(acts=_arc(total), heat=steps, heat_rule="앞 절반은 열 없이 쌓고, 큰 정점은 전 구간 끝",
                       heat_turn=HeatTurn(plant_ep=max(1, peak - 2), fail_ep=max(1, peak - 1), gain="지운 줄 알았던 녹음의 백업"),
                       stakes=[Foreshadow(id="x", description="잃을 수 있는 비밀", planted_ep=1, kind="stake"),
                               Foreshadow(id="y", description="볼 수 있는 동생", planted_ep=min(2, total), kind="audience"),
                               Foreshadow(id="z", description="단서로 잘못 온 것", planted_ep=1, kind="clue"),
                               Foreshadow(id="w", description="커진 판돈", planted_ep=total + 5, kind="stake", public=True)])
