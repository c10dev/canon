"""API 키 없이 전체 흐름을 확인하기 위한 가짜 LLM (CANON_LLM=mock)."""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from .schema import (
    Act,
    ArcPlan,
    Character,
    CharacterState,
    EpisodePlot,
    Foreshadow,
    PlotBatch,
    Relationship,
    SetupSuggestion,
    StateDelta,
    StyleProfile,
    WorldSetting,
)

T = TypeVar("T", bound=BaseModel)


def _arc(total: int) -> list[Act]:
    a = max(1, round(total * 0.2))
    b = a + max(1, round(total * 0.38))
    c = b + max(1, round(total * 0.24))
    return [
        Act(name="기", start_ep=1, end_ep=a, goal="주인공과 세계 소개, 사건 발생", key_turn="계기 사건"),
        Act(name="승", start_ep=a + 1, end_ep=b, goal="갈등 심화", key_turn="중간 반전"),
        Act(name="전", start_ep=b + 1, end_ep=c, goal="위기와 클라이맥스", key_turn="최대 위기"),
        Act(name="결", start_ep=c + 1, end_ep=total, goal="해결과 여운", key_turn="결말"),
    ]


class MockLLM:
    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        hint = hint or {}
        if schema is SetupSuggestion:
            return SetupSuggestion(
                theme="상실을 받아들이는 용기", tone="잔잔하지만 긴장감 있는",
                world=WorldSetting(setting="바닷가 소도시", era="현대", rules=["초자연 요소 없음"], locations=["등대", "수산시장"]),
                characters=[
                    Character(id="hero", name="서윤", role="주인공", goal="사라진 오빠를 찾는다", speech_style="짧고 건조한 반말. \"됐어, 내가 할게.\""),
                    Character(id="ally", name="도현", role="조연", goal="서윤을 돕는다", speech_style="느긋한 존댓말. \"천천히 해요.\""),
                ],
                relationships=[Relationship(a="hero", b="ally", type="동료", affinity=1, tension=3)],
            )  # type: ignore[return-value]
        if schema is StyleProfile:
            return StyleProfile(narration_pov="3인칭 제한", tense="과거형", sentence_rhythm="짧은 문장 위주",
                                dos=["감각 묘사로 장면 시작"], donts=["설명조 대사"],
                                sample_passages=["바람이 불었다. 서윤은 고개를 들지 않았다."])  # type: ignore[return-value]
        if schema is ArcPlan:
            return ArcPlan(acts=_arc(hint["total"]))  # type: ignore[return-value]
        if schema is PlotBatch:
            acts: list[Act] = hint["arc"]
            eps = []
            for n in range(hint["start"], hint["end"] + 1):
                act = next(a for a in acts if a.start_ep <= n <= a.end_ep)
                eps.append(EpisodePlot(number=n, act=act.name, title=f"{n}화 제목", summary=f"{n}화 요약",
                                       events=["사건 1", "사건 2", "사건 3"], characters=["hero", "ally"],
                                       emotional_shift="불안 → 결심", ending_hook="문이 열렸다"))
            return PlotBatch(episodes=eps)  # type: ignore[return-value]
        if schema is StateDelta:
            n = hint["episode"]
            return StateDelta(
                episode=n, summary=f"{n}화에서 서윤과 도현이 단서를 찾았다.",
                character_updates=[CharacterState(character_id="hero", emotional_state=f"{n}화 이후 조금 더 단단해짐", knows=[f"{n}화 단서"])],
                relationship_updates=[Relationship(a="hero", b="ally", type="동료", affinity=min(5, 1 + n), tension=3)],
                new_facts=[f"{n}화: 등대는 10년 전 폐쇄되었다"] if n == 1 else [],
                foreshadow_planted=[Foreshadow(id=f"fs-{n:02d}-key", description="녹슨 열쇠", planted_ep=n)] if n == 1 else [],
                foreshadow_resolved=["fs-01-key"] if n == 2 else [],
            )  # type: ignore[return-value]
        raise NotImplementedError(schema.__name__)

    def text(self, system: str, prompt: str) -> str:
        return "바람이 불었다. 서윤은 등대 앞에 섰다.\n\n\"됐어, 내가 할게.\"\n\n(mock 본문)"
