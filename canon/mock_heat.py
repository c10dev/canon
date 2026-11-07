"""열 계획 가짜 응답 (CANON_LLM=mock). 기승전결과 함께 받는 열 계획(HeatArcPlan)을 mock.RESPONDERS 에 등록한다."""
from __future__ import annotations

from .mock import _arc, _next_arc, responds
from .schema import Foreshadow, HeatArcPlan, HeatArcProposal, HeatProposal, HeatStep, HeatTurn


def shape(total: int, start: int = 1) -> list[HeatStep]:
    """start~total 화. 앞쪽은 쌓기, 13화 이상이면 승 끝에 낮은 정점, 전 끝 두 화(짧으면 한 화)에 큰 정점, 결은 뒷날 · 쉬기."""
    acts = {a.name: a for a in _arc(total, start)}
    seung, jeon, gyeol = acts["승"], acts["전"], acts["결"]
    hot = 2 if jeon.end_ep - jeon.start_ep >= 2 else 1
    out: list[HeatStep] = []
    for n in range(start, total + 1):
        if seung.start_ep <= n <= seung.end_ep and total - start + 1 >= 13 and n == seung.end_ep:
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
            s = HeatStep(ep=n, level=0 if n == start else 1, role="build")
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


def _proposal(start: int, end: int) -> HeatProposal:
    steps = shape(end, start)
    peak = next(s.ep for s in steps if s.role == "peak")
    return HeatProposal(heat=steps, heat_rule=f"{start}~{end}화: 앞은 쌓고 전 구간 끝에 터뜨린다",
                        heat_turn=HeatTurn(plant_ep=max(start, peak - 2), fail_ep=max(start, peak - 1), gain="새 약점"),
                        stakes=[Foreshadow(id="x", description=f"{start}화의 새 판돈", planted_ep=start, kind="stake"),
                                Foreshadow(id="y", description=f"{start}화의 관객", planted_ep=start, kind="audience")])


@responds(HeatProposal)
def _r_heat_proposal(prompt: str, hint: dict) -> HeatProposal:
    """이미 있는 기승전결 위에 받는 열 계획 (hint: start, end). 1화는 일부러 열 5 로 보내 본문 있는 화 지키기를 시험한다."""
    prop = _proposal(int(hint["start"]), int(hint["end"]))
    prop.heat[0] = prop.heat[0].model_copy(update={"level": 5, "role": "peak"})
    return prop


@responds(HeatArcProposal)
def _r_heat_arc_proposal(prompt: str, hint: dict) -> HeatArcProposal:
    """열 계획을 함께 받는 다음 아크 (hint 는 ArcProposal 과 같다)."""
    base = _next_arc(hint)
    heat = _proposal(base.arc.start_ep, base.arc.end_ep)
    return HeatArcProposal(**base.model_dump(), **heat.model_dump())
