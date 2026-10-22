"""API 키 없이 전체 흐름을 확인하기 위한 가짜 LLM (CANON_LLM=mock)."""
from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel

from .schema import (
    Act,
    ArcPlan,
    ArcProposal,
    Character,
    CharacterState,
    ConsistencyIssue,
    ConsistencyReport,
    EpisodePlot,
    Foreshadow,
    ImpactConflict,
    ImpactReport,
    NameOption,
    NameOptions,
    PlotBatch,
    Part,
    PlotRevision,
    Recap,
    Relationship,
    Secret,
    SeriesPlan,
    SetupSuggestion,
    StateDelta,
    StoryArc,
    StoryEvent,
    Storyline,
    StorylineProposal,
    StyleProfile,
    TextPatch,
    WorldSetting,
)

T = TypeVar("T", bound=BaseModel)


def _delay() -> None:
    """CANON_MOCK_DELAY=초 로 실제 호출처럼 기다리게 한다 (화면의 진행 표시 확인용)."""
    import os
    import time

    time.sleep(float(os.environ.get("CANON_MOCK_DELAY", "0") or 0))


def _arc(total: int, start: int = 1) -> list[Act]:
    """start 화부터 total 화까지를 기승전결로 나눈다. 장편 아크는 start 가 아크 첫 화."""
    size = total - start + 1
    c = min(start - 1 + max(1, round(size * 0.2)) + max(1, round(size * 0.38)) + max(1, round(size * 0.24)), total - 1)
    b = min(start - 1 + max(1, round(size * 0.2)) + max(1, round(size * 0.38)), c - 1)
    a = min(start - 1 + max(1, round(size * 0.2)), b - 1)
    return [
        Act(name="기", start_ep=start, end_ep=a, goal="주인공과 세계 소개, 사건 발생", key_turn="계기 사건"),
        Act(name="승", start_ep=a + 1, end_ep=b, goal="갈등 심화", key_turn="중간 반전"),
        Act(name="전", start_ep=b + 1, end_ep=c, goal="위기와 클라이맥스", key_turn="최대 위기"),
        Act(name="결", start_ep=c + 1, end_ep=total, goal="해결과 여운", key_turn="결말"),
    ]


def _series(total: int) -> SeriesPlan:
    """100화 안팎으로 부를 나눈다."""
    count = max(1, round(total / 100))
    edges = [round(total * k / count) for k in range(count + 1)]
    return SeriesPlan(parts=[
        Part(number=k + 1, title=f"{k + 1}부", start_ep=edges[k] + 1, end_ep=edges[k + 1],
             goal=f"{k + 1}부 목표", key_turn=f"{k + 1}부 반전", arc_ideas=["시험", "던전", "배신"])
        for k in range(count)
    ])


def _next_arc(hint: dict) -> ArcProposal:
    """다음 아크 흉내: 길이를 정하지 않으면 12화, 부 끝을 넘지 않는다. 두 번째 아크마다 새 인물이 나온다."""
    start, limit, number = hint["start"], hint["limit"], hint["number"]
    end = min(start + (hint["length"] or 12) - 1, limit)
    new = [Character(id=f"guest{number}", name=f"손님{number}", role="조연", tier="main",
                     speech_style="빠른 말투. \"얼른 와.\"")] if number % 2 == 0 else []
    arc = StoryArc(number=number, title=f"아크 {number}", start_ep=start, end_ep=end, goal=f"아크 {number} 목표",
                   conflict="시험관", payoff="통쾌한 역전", acts=_arc(end, start),
                   cast=["hero", "ally"] + [c.id for c in new], payoffs=["fs-01-key"] if number == 2 else [])
    return ArcProposal(arc=arc, new_characters=new, reply=f"{start}화부터 아크 {number}를 제안해요.")


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


def _impact(hint: dict) -> ImpactReport:
    """영향 분석 흉내: 처음 쓴 화의 첫 문장을 모순으로 짚고 고친 문장을, 본문 없는 첫 화에 사건을 더한 플롯을 낸다.
    검증 규칙을 시험하도록 원문에 없는 인용 하나를 함께 넣는다."""
    el, eps = hint["element"], hint["episodes"]
    rep = ImpactReport(summary=f"'{el.name}' 을(를) 더하면 앞 화 몇 곳이 흔들려요.", new_facts=[f"{el.name}: {el.description}"])
    written = next((e for e in eps if e.text), None)
    if written:
        first = written.text.split("\n")[0].split(". ")[0].strip()
        n = written.plot.number
        rep.conflicts = [
            ImpactConflict(target="본문", episode=n, quote=first, problem=f"{el.name} 과(와) 맞지 않는다", fix="본문 수정"),
            ImpactConflict(target="본문", episode=n, quote="원문에 없는 지어낸 문장", problem="검증에서 빠져야 한다", fix="그대로 둠"),
        ]
        rep.patches = [TextPatch(episode=n, quote=first, replacement=first + " " + el.name + "이(가) 떠올랐다.", reason="새 설정과 맞춘다")]
    target = next((e for e in eps if e.status in ("draft", "confirmed")), None)
    if target:
        rep.episodes = [target.plot.model_copy(update={"events": target.plot.events + [f"{el.name} 이(가) 드러난다"]})]
    return rep


def _storyline(hint: dict) -> StorylineProposal:
    """줄기 제안 흉내: 'N화' 가 있으면 그 화, 없으면 앞쪽 두 화를 과거 회상으로, 다음 화에 장면을 끼운다.
    검증 규칙을 시험하도록 없는 인물과 없는 화를 함께 넣는다."""
    eps = hint["episodes"]
    hit = re.search(r"(\d+)화", hint["note"])
    pick = [int(hit.group(1))] if hit else eps[1:3]
    s = Storyline(id="아무거나", kind=hint["kind"] or "과거 회상", title="서윤의 오빠가 떠난 밤", focus=["hero", "nobody"],
                  when="10년 전", goal="오빠가 왜 떠났는지", branch_ep=pick[0] if pick else 0,
                  join_ep=(pick[-1] + 2) if pick else 0, rejoin="서윤이 오빠의 편지를 기억해 낸다")
    nxt = [n for n in eps if pick and n == pick[-1] + 1]
    return StorylineProposal(storyline=s, episodes=pick + [999], threads=nxt, reply="서윤의 결핍에서 출발하는 과거 회상이에요.")


class MockLLM:
    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        _delay()
        hint = hint or {}
        if schema is SetupSuggestion:
            return SetupSuggestion(
                theme="상실을 받아들이는 용기", tone="잔잔하지만 긴장감 있는",
                world=WorldSetting(setting="바닷가 소도시", era="현대", rules=["초자연 요소 없음"], locations=["등대", "수산시장"]),
                characters=[
                    Character(id="hero", name="서윤", role="주인공", gender="여", age="19세", goal="사라진 오빠를 찾는다", speech_style="짧고 건조한 반말. \"됐어, 내가 할게.\""),
                    Character(id="ally", name="도현", role="조연", gender="남", age="24세", goal="서윤을 돕는다", speech_style="느긋한 존댓말. \"천천히 해요.\""),
                ],
                relationships=[Relationship(a="hero", b="ally", type="동료", affinity=1, tension=3, a_view=["경계한다"], b_view=["좋아한다", "빚졌다"])],
            )  # type: ignore[return-value]
        if schema is StyleProfile:
            return StyleProfile(narration_pov="3인칭 제한", tense="과거형", sentence_rhythm="짧은 문장 위주",
                                dos=["감각 묘사로 장면 시작"], donts=["설명조 대사"],
                                sample_passages=["바람이 불었다. 서윤은 고개를 들지 않았다."])  # type: ignore[return-value]
        if schema is ArcPlan:
            return ArcPlan(acts=_arc(hint["total"]))  # type: ignore[return-value]
        if schema is SeriesPlan:
            return _series(hint["total"])  # type: ignore[return-value]
        if schema is ArcProposal:
            return _next_arc(hint)  # type: ignore[return-value]
        if schema is Recap:
            return Recap(summary=f"{'아크' if hint['kind'] == 'arc' else '부'} {hint['number']} 요약: 주인공이 시험을 넘겼다.")  # type: ignore[return-value]
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
        if schema is StorylineProposal:
            return _storyline(hint)  # type: ignore[return-value]
        if schema is ImpactReport:
            return _impact(hint)  # type: ignore[return-value]
        if schema is NameOptions:  # 코드 후보에서 앞쪽 n 개를 고른 척한다
            names = hint["candidates"][: hint["n"]]
            return NameOptions(options=[NameOption(name=x, reason="후보 중 인물과 시대에 맞는 이름") for x in names])  # type: ignore[return-value]
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
