"""API 키 없이 전체 흐름을 확인하기 위한 가짜 LLM (CANON_LLM=mock)."""
from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel

from .schema import (
    Act,
    ArcPlan,
    Character,
    CharacterState,
    ConsistencyIssue,
    ConsistencyReport,
    EpisodePlot,
    Foreshadow,
    PlotBatch,
    PlotRevision,
    Relationship,
    Secret,
    SetupSuggestion,
    StateDelta,
    StoryEvent,
    StyleProfile,
    WorldSetting,
)

T = TypeVar("T", bound=BaseModel)


def _delay() -> None:
    """CANON_MOCK_DELAY=초 로 실제 호출처럼 기다리게 한다 (화면의 진행 표시 확인용)."""
    import os
    import time

    time.sleep(float(os.environ.get("CANON_MOCK_DELAY", "0") or 0))


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


def _plot(n: int, act: str, note: str = "") -> EpisodePlot:
    return EpisodePlot(number=n, act=act, title=f"{n}화 제목", summary=f"{n}화 요약{note}",
                       events=["사건 1", "사건 2", "사건 3"], characters=["hero", "ally"],
                       emotional_shift="불안 → 결심", ending_hook="문이 열렸다")


def _revision(hint: dict) -> PlotRevision:
    """플롯 대화 흉내: 'N화로' 는 화수 변경, '결말' 은 결 구간 목표, 'N화' 는 그 화를 고친다."""
    msg, arc, eps, total = hint["message"], hint["arc"], hint["episodes"], hint["total"]
    rev = PlotRevision(reply=f"'{msg}' 를 반영해 고쳐 봤어요.")
    resize = re.search(r"(\d+)화로", msg)
    if resize or not arc:
        new_total = int(resize.group(1)) if resize else total
        rev.total_episodes = new_total if new_total != total else 0
        rev.acts = _arc(new_total)
        have = {e.number for e in eps}
        rev.episodes = [_plot(n, next(a.name for a in rev.acts if a.start_ep <= n <= a.end_ep))
                        for n in range(1, new_total + 1) if n not in have]
        return rev
    if "결말" in msg:
        rev.acts = [a.model_copy(update={"goal": "비극으로 끝난다"} if a.name == "결" else {}) for a in arc]
    hit = re.search(r"(\d+)화", msg)
    target = next((e for e in eps if hit and e.number == int(hit.group(1))), None)
    if target:
        rev.episodes = [target.model_copy(update={"summary": target.summary + " (천천히)", "events": target.events + ["숨 고르는 장면"]})]
    if not (rev.acts or rev.episodes):
        rev.reply = "어느 화를 바꿀지 알려 주세요."
    return rev


class MockLLM:
    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        _delay()
        hint = hint or {}
        if schema is SetupSuggestion:
            return SetupSuggestion(
                theme="상실을 받아들이는 용기", tone="잔잔하지만 긴장감 있는",
                world=WorldSetting(setting="바닷가 소도시", era="현대", rules=["초자연 요소 없음"], locations=["등대", "수산시장"]),
                characters=[
                    Character(id="hero", name="서윤", role="주인공", goal="사라진 오빠를 찾는다", speech_style="짧고 건조한 반말. \"됐어, 내가 할게.\""),
                    Character(id="ally", name="도현", role="조연", goal="서윤을 돕는다", speech_style="느긋한 존댓말. \"천천히 해요.\""),
                ],
                relationships=[Relationship(a="hero", b="ally", type="동료", affinity=1, tension=3, a_view=["경계한다"], b_view=["좋아한다", "빚졌다"])],
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
                eps.append(_plot(n, act.name))
            return PlotBatch(episodes=eps)  # type: ignore[return-value]
        if schema is PlotRevision:
            return _revision(hint)  # type: ignore[return-value]
        if schema is StateDelta:
            n = hint["episode"]
            return StateDelta(
                episode=n, summary=f"{n}화에서 서윤과 도현이 단서를 찾았다.",
                character_updates=[CharacterState(character_id="hero", emotional_state=f"{n}화 이후 조금 더 단단해짐", knows=[f"{n}화 단서"])],
                events=[
                    StoryEvent(episode=n, actor="ally", target="hero", kind="거짓말발각", intensity=3,
                               reveals_secret="sec-ally-letter", quote="그 편지, 네가 버린 거 아니었잖아.")
                    if n == 2 else
                    StoryEvent(episode=n, actor="ally", target="hero", kind="도움", intensity=2, quote="도현이 손전등을 건넸다."),
                    StoryEvent(episode=n, actor="hero", target="ally", kind="공동경험", intensity=1, quote="둘은 등대 계단을 올랐다."),
                ],
                relationship_updates=[Relationship(a="hero", b="ally", type="동료", description="서로 의지하는 사이")] if n == 3 else [],
                secrets_added=[Secret(id="sec-ally-letter", owner="ally", content="오빠의 편지를 숨겼다", hidden_from=["hero"])] if n == 1 else [],
                new_facts=[f"{n}화: 등대는 10년 전 폐쇄되었다"] if n == 1 else [],
                foreshadow_planted=[Foreshadow(id=f"fs-{n:02d}-key", description="녹슨 열쇠", planted_ep=n)] if n == 1 else [],
                foreshadow_resolved=["fs-01-key"] if n == 2 else [],
            )  # type: ignore[return-value]
        if schema is ConsistencyReport:
            n = hint["episode"]
            issues = [ConsistencyIssue(
                type="말투", description="도현이 서윤에게 반말을 쓴다", source_episode=0,
                source_quote="느긋한 존댓말. \"천천히 해요.\"", current_quote="\"됐어, 내가 할게.\"",
                suggestion="도현의 대사를 존댓말로 바꾼다",
            )] if n == 2 else []
            return ConsistencyReport(episode=n, issues=issues)  # type: ignore[return-value]
        raise NotImplementedError(schema.__name__)

    def text(self, system: str, prompt: str) -> str:
        _delay()
        return "바람이 불었다. 서윤은 등대 앞에 섰다.\n\n\"됐어, 내가 할게.\"\n\n(mock 본문)"

    # Batch API 흉내. CANON_MOCK_BATCH_POLLS=n 이면 n 번 물어본 뒤에 끝난다 (기본 0: 바로 끝).
    def batch_submit(self, system: str, prompt: str, schema: type[BaseModel] | None, label: str,
                     hint: dict | None = None) -> str:
        import os
        import uuid

        out = self.json(system, prompt, schema, hint).model_dump_json() if schema else self.text(system, prompt)
        name = f"batches/mock-{uuid.uuid4().hex[:8]}"
        BATCHES[name] = {"out": out, "polls": int(os.environ.get("CANON_MOCK_BATCH_POLLS", "0") or 0),
                         "label": label, "cancelled": False}
        return name

    def batch_poll(self, name: str) -> str | None:
        b = BATCHES.get(name)
        if b is None:
            raise RuntimeError(f"없는 배치 작업: {name}")
        if b["cancelled"]:
            raise RuntimeError("배치 작업이 취소됐습니다")
        if b["polls"] > 0:
            b["polls"] -= 1
            return None
        return b["out"]

    def batch_cancel(self, name: str) -> None:
        if name in BATCHES:
            BATCHES[name]["cancelled"] = True


BATCHES: dict[str, dict] = {}  # 프로세스 안에서만 유지되는 가짜 배치 작업
