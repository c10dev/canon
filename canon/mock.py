"""API 키 없이 전체 흐름을 확인하기 위한 가짜 LLM (CANON_LLM=mock)."""
from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel

from .schema import (
    Act,
    ArcEdit,
    ArcPlan,
    ArcProposal,
    Character,
    CharacterState,
    Claim,
    ClaimSet,
    ConsistencyIssue,
    ConsistencyReport,
    FindingRecheck,
    FixOption,
    FixPatch,
    FixSet,
    Direction,
    PlantedContradiction,
    SceneBeat,
    SceneCheck,
    BodyState,
    PlantSet,
    MapPlaceGuess,
    MapSuggestion,
    PlaceGuess,
    PlaceSort,
    EpisodePlot,
    NewPlace,
    Foreshadow,
    ForeshadowClue,
    HookItem,
    HookReport,
    IllustCharacter,
    IllustDraft,
    ImpactConflict,
    ImpactReport,
    LookSuggestion,
    BodySuggestion,
    StatInitCharacter,
    StatInitSuggestion,
    StatWindowOption,
    StatWindowSuggestion,
    VoiceSuggestion,
    NameOption,
    NameOptions,
    FieldIdea,
    FieldIdeas,
    OpeningOption,
    OpeningPlots,
    PassageCandidate,
    PassageRevision,
    EpisodeDraft,
    PlotBatch,
    Part,
    PlotRevision,
    Recap,
    RebuildEpisode,
    Relationship,
    Rework,
    ScopeChange,
    Secret,
    SerialConversion,
    SerialRebuild,
    SeriesPlan,
    SetupRevision,
    SetupSuggestion,
    SetupEdit,
    CharacterEdit,
    Deadline,
    SettingChange,
    StateDelta,
    StatValue,
    StoryTime,
    StoryArc,
    StoryEvent,
    Storyline,
    StorylineProposal,
    StyleLearning,
    StyleEdit,
    StyleRevision,
    StyleSample,
    StyleMarker,
    StyleProfile,
    StyleRuleSuggestion,
    TextPatch,
    TierChange,
    WorldSetting,
)

T = TypeVar("T", bound=BaseModel)


def _delay() -> None:
    """CANON_MOCK_DELAY=초 로 실제 호출처럼 기다리게 한다 (화면의 진행 표시 확인용)."""
    import os
    import time

    time.sleep(float(os.environ.get("CANON_MOCK_DELAY", "0") or 0))
    from . import cancel
    cancel.check()  # 실제 LLM 처럼 멈춘 작업은 응답을 쓰지 않는다


def _arc(total: int, start: int = 1) -> list[Act]:
    """start 화부터 total 화까지를 기승전결로 나눈다. 장편 아크는 start 가 아크 첫 화."""
    size = total - start + 1
    if size < 4:  # 짧은 작품은 이웃 구간이 한 화를 함께 쓴다
        from .pipeline import act_ranges
        r = act_ranges(total, start)
        goals = [("주인공과 세계 소개, 사건 발생", "계기 사건"), ("갈등 심화", "중간 반전"), ("위기와 클라이맥스", "최대 위기"), ("해결과 여운", "결말")]
        return [Act(name=nm, start_ep=s, end_ep=e, goal=g, key_turn=k) for nm, (s, e), (g, k) in zip("기승전결", r, goals)]
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


def _conversion(hint: dict) -> SerialConversion:
    """전환 흉내: 단편 뒤로 100화 안팎씩 부를 나누고, 결말을 다시 열면 떡밥·사실·마지막 미작성 화 플롯을 낸다.
    검증 규칙을 시험하도록 없는 인물과 이미 있는 복선 id 를 섞는다."""
    total, end, ending = hint["total"], hint["end"], hint["ending"] or "reopen"
    parts = _series(total).parts
    if parts and parts[0].end_ep < end:
        parts[0].end_ep = end + (parts[1].end_ep - end) // 2 if len(parts) > 1 else total
        if len(parts) > 1:
            parts[1].start_ep = parts[0].end_ep + 1
    conv = SerialConversion(
        reply="단편을 아크 1로 두고 장편으로 늘렸어요.", ending=ending, total_episodes=total,
        arc=StoryArc(number=9, title="등대의 여름", start_ep=1, end_ep=end, goal="오빠의 행방을 안다", conflict="숨긴 편지",
                     payoff="편지의 진실", cast=["hero", "ally", "nobody"], summary="아크 1 요약: 서윤이 진실에 닿았다."),
        parts=parts,
        tiers=[TierChange(id="ally", tier="support", reason="장편에서는 조연"), TierChange(id="nobody", tier="minor")],
        scopes=[ScopeChange(id=f, scope="series") for f in hint["open"][:1]],
    )
    if ending == "reopen":
        conv.foreshadows = [Foreshadow(id="fs-s-shadow", description="등대지기의 그림자", planted_ep=end + 5, scope="series"),
                            *([Foreshadow(id=hint["open"][0], description="이미 있는 복선", planted_ep=1)] if hint["open"] else [])]
        conv.facts = ["오빠의 배는 끝내 발견되지 않았다"]
        last = hint["unlocked"][-1:] if hint["unlocked"] else []
        conv.episodes = [e.model_copy(update={"ending_hook": "수평선에 낯선 불빛이 켜졌다"}) for e in last]
    return conv


def _rebuild(hint: dict) -> SerialRebuild:
    """재구성 흉내: 앞부분을 아크 둘로 나누고, 1화는 새 훅 · 옛 1화는 그대로 · 옛 2화는 다듬기 · 나머지는 재료로 새로 쓴다.
    단편 결말(마지막 옛 화)은 첫 아크 끝으로 옮긴다. 검증 규칙을 시험하도록 옛 화 둘을 그대로 두겠다는 줄을 섞는다."""
    total, span, old = hint["total"], hint["span"], [n for n, _ in hint["old"]]
    cut = span // 2 if span >= 8 else span
    arcs = [StoryArc(number=1, title="등대의 여름", start_ep=1, end_ep=cut, goal="오빠의 행방을 안다", conflict="숨긴 편지",
                     payoff="편지의 진실", acts=_arc(cut), cast=["hero", "ally", "nobody"])]
    if cut < span:
        arcs.append(StoryArc(number=2, title="북쪽 항구", start_ep=cut + 1, end_ep=span, goal="오빠의 배를 쫓는다",
                             conflict="밀수 조직", payoff="첫 단서", acts=_arc(span, cut + 1), cast=["hero", "ally"]))
    rows: dict[int, RebuildEpisode] = {1: RebuildEpisode(number=1, title="불 꺼진 등대", summary="사건부터 연다.", use="new")}
    plan = [("keep", [old[0]], "")] if old else []
    if len(old) > 1:
        plan.append(("revise", [old[1]], "도현이 무언가 숨긴다는 기색을 미리 흘린다"))
    if len(old) > 3:
        plan.append(("keep", [old[2], old[3]], ""))  # 옛 화 둘을 그대로 둘 수는 없다 → rewrite 로 바뀐다
    middle = old[4:-1] if len(old) > 4 else []
    plan += [("rewrite", [o], "옛 화의 장면을 살린다") for o in middle]
    slot = 2
    for use, src, note in plan:
        if slot >= cut:
            break
        rows[slot] = RebuildEpisode(number=slot, title=f"{slot}화", summary=f"옛 {src}화를 쓴다.", sources=src, use=use, note=note)
        slot += 1
    if len(old) > 4:
        rows[cut] = RebuildEpisode(number=cut, title="편지의 진실", summary="단편의 결말.", sources=[old[-1]], use="rewrite",
                                   note="단편 결말을 첫 아크 끝으로 옮긴다")
    eps = [rows.get(n) or RebuildEpisode(number=n, title=f"{n}화", summary=f"{n}화 새 이야기", use="new") for n in range(1, span + 1)]
    parts = _series(total).parts
    if len(parts) > 1 and parts[0].end_ep < span:
        parts[0].end_ep = span
        parts[1].start_ep = span + 1
    return SerialRebuild(
        reply="단편을 씨앗으로 앞부분을 다시 짰어요. 1화는 사건부터 열고, 단편 결말은 첫 아크 끝으로 옮겼어요.",
        total_episodes=total, ending_at=hint["ending_at"] or "arc", parts=parts, arcs=arcs, episodes=eps,
        foreshadows=[Foreshadow(id="fs-r-door", description="등대 아래 잠긴 문", planted_ep=1, scope="series")],
        tiers=[TierChange(id="ally", tier="support", reason="장편에서는 조연"), TierChange(id="nobody", tier="minor")],
    )


NEW_CAST_EP = 2  # 플롯 초안이 새 인물 후보를 데려오는 화
NEW_PLACE = NewPlace(name="물새집", kind="여관", description="항구 뒤 골목의 낡은 여관")  # 그 화에 함께 나오는 새 장소
NEW_CAST = Character(id="innkeeper", name="곽노인", role="여관 주인", age="60대", gender="남", tier="minor",
                     personality="말수가 적고 셈이 빠르다", speech_style="짧은 하게체. \"방은 하나 남았네.\"")


def _plot(n: int, act: str, note: str = "") -> EpisodePlot:
    early = n <= 3  # 초반 1~3화는 여는 장면과 독자 질문을 채운다
    return EpisodePlot(number=n, act=act, title=f"{n}화 제목", summary=f"{n}화 요약{note}",
                       events=["사건 1", "사건 2", "사건 3"], characters=["hero", "ally"],
                       emotional_shift="불안 → 결심", ending_hook="문이 열렸다",
                       opening=f"{n}화 여는 장면" if early else "", reader_question=f"{n}화 뒤에 무엇이 있나?" if early else "")


def _plants(hint: dict) -> PlantSet:
    """본문 앞쪽 문장들의 끝에 한 마디를 붙여 '바꾼' 문장으로 낸다. 첫째는 설정 모순, 둘째부터는 같은 화 동선(접촉 · 물건)."""
    import re
    sents = [x for x in re.findall(r"[^.!?\n]+[.!?]", hint.get("text", "")) if len(x.strip()) > 4]
    n = hint.get("episode", 0)
    items = []
    for i, x in enumerate(sents[:hint.get("count", 1)]):
        x = x.strip()
        if i == 0:
            items.append(PlantedContradiction(quote=x, replacement=x[:-1] + ", 사실 그는 처음 보는 사람이었다.",
                                              type="사실", source_episode=0, source_quote="설정"))
        else:
            part = "접촉" if i % 2 else "물건"
            items.append(PlantedContradiction(quote=x, replacement=x[:-1] + (", 잡은 손을 놓지 않은 채 두 손으로 문을 밀었다." if part == "접촉" else ", 내려놓은 가방에서 열쇠를 꺼냈다."),
                                              type="동선", part=part, source_episode=n, source_quote=sents[0].strip()))
    return PlantSet(items=items)


def _hook(hint: dict) -> HookReport:
    """판정 흉내: 첫 문장을 근거로, 하나는 본문에 없는 인용을 넣어 걸러지는지 시험한다."""
    text = hint["text"].strip()
    first = re.split(r"(?<=[.!?])\s+|\n+", text)[0].strip()
    items = [HookItem(aspect="첫 문단", score=4, quote=first, note="움직임으로 시작한다"),
             HookItem(aspect="주인공", score=5, quote="본문에 없는 지어낸 문장", note="걸러져야 한다"),
             HookItem(aspect="엔딩", score=2, quote="", note="여운으로 끝나 훅이 약하다")]
    return HookReport(episode=hint["episode"], items=items, premise_quote=first, reader_question="등대에 누가 있나?",
                      next_click=True, reason="주인공이 바로 움직인다", premise_at=99, basis="x")


def _openings(hint: dict) -> OpeningPlots:
    """여는 방식마다 하나씩, 검증을 시험하도록 요청하지 않은 방식과 중복을 섞는다."""
    n, act = hint["episode"], hint["act"]
    opts = [OpeningOption(approach=a, pitch=f"{a} 로 붙잡는다",
                          plot=_plot(n, act).model_copy(update={"opening": f"{a} 장면", "number": 99})) for a in hint["approaches"]]
    opts += [OpeningOption(approach="unknown", pitch="", plot=_plot(n, act)), opts[0]]
    return OpeningPlots(options=opts)


def _serial_revision(hint: dict, rev: PlotRevision) -> bool:
    """장편 흉내. 다음 아크: 'N화짜리' 길이로 새로 짜거나 '갈등' 으로 초안을 고친다.
    고른 아크: '갈등' 은 아크 칸, '끝 화 N' 은 끝 화. '부 구성' 은 1부 목표를 고친다. 처리했으면 True."""
    msg, focus, draft = hint["message"], hint.get("focus"), hint.get("draft")
    done = False
    if "부 구성" in msg and hint.get("parts"):
        rev.parts = [x.model_copy(update={"goal": x.goal + " (대화로 고침)"} if x.number == 1 else {}) for x in hint["parts"]]
        done = True
    if hint.get("target") == "next":
        start, limit = hint["start"], hint["limit"]
        size = re.search(r"(\d+)화짜리", msg)
        if draft and not size:
            a = draft.arc
            rev.arc = ArcEdit(**a.model_dump(include={"title", "goal", "conflict", "payoff", "cast", "payoffs", "pov"}), end_ep=a.end_ep)
            if "갈등" in msg:
                rev.arc.conflict = "옛 동료의 배신"
            rev.acts = [x.model_copy(deep=True) for x in a.acts]
        else:
            end = min(start + (int(size.group(1)) if size else 10) - 1, limit)
            rev.arc = ArcEdit(title="대화로 짠 아크", goal="시험을 통과한다", conflict="라이벌", payoff="역전승",
                              cast=["hero", "rival9"], end_ep=end)
            rev.acts = _arc(end, start)
            rev.new_characters = [Character(id="rival9", name="라이벌", role="라이벌", tier="main", speech_style="짧은 반말")]
        return True
    if focus and ("갈등" in msg or "끝 화" in msg):
        rev.arc = ArcEdit(**focus.model_dump(include={"title", "goal", "conflict", "payoff", "cast", "payoffs", "pov"}))
        if "갈등" in msg:
            rev.arc.conflict = "옛 동료의 배신"
        hit = re.search(r"끝 화 (\d+)", msg)
        if hit:
            rev.arc.end_ep = int(hit.group(1))
        done = True
    return done


def _revision(hint: dict) -> PlotRevision:
    """플롯 대화 흉내: 'N화로' 는 화수 변경, '결말' 은 결 구간 목표, 'N화' 는 그 화를 고친다.
    방향 여러 안을 청하면 세 방향을 낸다 (구조 칸도 함께 채워 걸러지는지 본다)."""
    msg, arc, eps, total = hint["message"], hint["arc"], hint["episodes"], hint["total"]
    rev = PlotRevision(reply=f"'{msg}' 를 반영해 고쳐 봤어요.")
    if hint.get("mode") == "options":
        rev.reply = "갈등의 출처로 나눠 봤어요."
        rev.options = [Direction(title=t, idea=f"{t} 쪽으로 간다.", changes=["승 구간: 사건 순서 바꿈"], tradeoff="속도 대신 깊이")
                       for t in ("배신", "추격", "고백")]
        rev.acts = list(arc)
        return rev
    if hint.get("serial") and _serial_revision(hint, rev):
        return rev
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
    if target and "새 인물" in msg:  # 그 화에 새 조연을 들인다 (주역으로 내도 조연으로 내려야 한다)
        rev.episodes = [target.model_copy(update={"characters": target.characters + ["courier"], "events": target.events + ["낯선 배달부"]})]
        rev.new_characters = [Character(id="courier", name="반석", role="배달부", tier="main", speech_style="빠른 반말")]
    elif target:
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


def _illust(hint: dict) -> IllustDraft:
    """고른 부분(없으면 본문 첫 문장)을 장면으로, 등장 인물 앞 두 명을 그린다. 첫 인물은 외형 태그도 적는다(저장 안 된 경우)."""
    quote = hint.get("selection") or next((s for s in re.split(r"(?<=[.!?])\s+", hint.get("text", "")) if s.strip()), "")
    cast = list(hint.get("cast") or [])[:2]
    chars = [IllustCharacter(id=cid, subject="girl" if i == 0 else "boy", look=["black hair", "long hair", "brown eyes"] if i == 0 else [],
                             expression=["serious"], action=["standing", "looking at another"] if len(cast) > 1 else ["standing"],
                             position=("left", "right")[i] if len(cast) > 1 else "")
             for i, cid in enumerate(cast)]
    return IllustDraft(quote=quote[:200], scene="등대 앞에 선 두 사람", characters=chars, setting=["outdoors", "lighthouse", "Night"],
                       lighting=["moonlight"], composition=["wide_shot"], mood=["wind", "1girl", "rating:explicit"],
                       caption="A girl stands before a lighthouse at night.", negative=["umbrella"], rating="general")


def _fixes(hint: dict) -> FixSet:
    """지적 문장을 두 방향으로 고친 척한다. 둘째 안은 바로 뒤 문장을 딸린 곳으로 함께 고친다. 원문 그대로인 안은 걸러져야 한다."""
    quote, text = hint["quote"].strip(), hint.get("text", "")
    base = quote.rstrip(".!?”\"")  # 고친 글에 원래 문장이 그대로 남지 않게 끝을 바꾼다
    sents = [x.strip() for x in re.findall(r"[^.!?\n]+[.!?”\"]*", text) if x.strip()]
    after = next((sents[i + 1] for i, x in enumerate(sents) if quote in x and i + 1 < len(sents)), "")
    extra = [FixPatch(quote=after, replacement=f"{after} (함께 고침)", reason="고친 문장과 맞춘다")] if after and after not in quote else []
    return FixSet(reply="두 방향으로 고쳤어요.", options=[
        FixOption(label="짧게 고치기", text=f"{base} — 고침", note="문장만 고침"),
        FixOption(label="뒤 문장까지", text=f"{base} — 고침 2", note="뒤 문장도 맞춤", extra=extra),
        FixOption(label="그대로", text=quote, note="원문 그대로 (걸러져야 함)"),
    ])


def _passage(hint: dict) -> PassageRevision:
    """고른 부분을 두 방향으로 바꾼 척한다: 요청을 덧붙인 것과, 앞 절반만 남긴 것."""
    src = hint["selection"].strip()
    ask = hint.get("preset") or hint.get("message", "").strip() or "다듬음"
    short = src[: max(1, len(src) // 2)].rstrip() + "."
    return PassageRevision(reply=f"요청({ask})대로 두 가지로 고쳤어요.", candidates=[
        PassageCandidate(text=f"{src} ({ask})", note="요청을 덧붙임"),
        PassageCandidate(text=short, note="절반으로 줄임"),
        PassageCandidate(text=src, note="원문 그대로 (걸러져야 함)"),
    ])


def _learning(hint: dict) -> StyleLearning:
    """수정 기록에서 배운 척한다: 모든 수정을 근거로 한 규칙, 두 번 이상 지운 낱말, 지운 장치, 근거 없는 후보 하나."""
    edits = hint.get("edits", [])
    refs = [r for r, _, _ in edits]
    out = [StyleRuleSuggestion(kind="do", text="짧은 문장으로 끊어 쓴다", reason="작가가 긴 문장을 나눴다", evidence=refs[:3])]
    words = {}
    for r, before, after in edits:
        for w in set(before.split()):
            if len(w) >= 2 and w not in after:
                words.setdefault(w, []).append(r)
    gone = sorted(((w, rs) for w, rs in words.items() if len(rs) >= 2), key=lambda x: -len(x[1]))
    if gone:
        out.append(StyleRuleSuggestion(kind="banned", text=gone[0][0], reason="작가가 매번 지웠다", evidence=gone[0][1]))
    dev = [r for r, before, after in edits if "다는 건" in before and "다는 건" not in after]
    if dev:
        out.append(StyleRuleSuggestion(kind="device", text="자문자답 망상", note="설렐 때", cues=["다는 건", "없는글자"],
                                       every=5, reason="작가가 망상 연쇄를 줄였다", evidence=dev))
    out.append(StyleRuleSuggestion(kind="marker", text="것이었다", reason="근거 없음 (걸러져야 함)", evidence=["99:e1", "98:e2"]))
    return StyleLearning(summary="작가는 긴 문장을 끊고 군더더기 낱말을 지운다.", suggestions=out)


def _style_revision(hint: dict) -> StyleRevision:
    """문체 대화: 문장 리듬을 바꾸고 지킬 것을 하나 더한 척한다. 지금 값과 같은 시제 칸도 섞어 걸러지는지 본다."""
    msg = hint.get("message", "").strip()
    st = hint.get("style", {})
    ref = hint.get("ref", "")
    if msg.endswith("?"):  # 질문에는 대답만
        return StyleRevision(reply="지금 프로필은 짧은 문장 위주예요. 바꾸고 싶은 쪽을 말해 주세요.")
    return StyleRevision(
        reply=f"'{msg}' 에 맞춰 문장 리듬과 규칙을 고쳤어요.",
        edits=[StyleEdit(key="sentence_rhythm", text=f"짧은 문장 위주, 감정이 터질 때만 길게 ({msg})", why="요청"),
               StyleEdit(key="dos", items=list(st.get("dos", [])) + ["대사는 한 줄을 넘기지 않는다"], why="대사 템포"),
               StyleEdit(key="tense", text=st.get("tense", ""), why="그대로 (걸러져야 함)")],
        preview_source=ref[:120].strip() if ref else "",
        preview="그는 문을 열었다. 바람이 들었다.\n\n\"왔어?\" 그녀가 물었다.")


def _setup_revision(hint: dict) -> SetupRevision:
    """설정 대화: 주제를 채우고, 규칙 하나와 첫 인물의 약점을 고치고, 조력자 한 명과 관계를 더한 척한다.
    지금 값과 같은 톤 칸도 섞어 걸러지는지 본다. '?' 로 끝나면 대답만, 방향 여러 안이면 안 세 개."""
    msg = hint.get("message", "").strip()
    p = hint.get("project", {})
    if hint.get("mode") == "options":
        return SetupRevision(reply="갈등의 축으로 나눠 봤어요.", options=[
            Direction(title="복수", idea="주인공이 잃은 것을 되찾으려 한다.", changes=["주인공 원하는 것: 복수"], tradeoff="속도는 빠르지만 어두워진다"),
            Direction(title="구원", idea="주인공이 적을 이해하게 된다.", changes=["주제: 용서할 수 있나"], tradeoff="여운은 크지만 느리다"),
            Direction(title="비밀", idea="세계의 규칙이 거짓이었다.", changes=["규칙: 바다는 사람을 돌려보낸다"], tradeoff="반전이 크지만 설명이 는다"),
        ])
    if msg.endswith("?"):
        return SetupRevision(reply="지금 설정은 주인공의 결핍이 아직 흐려요. 어느 쪽으로 다듬고 싶은지 말해 주세요.")
    meta, world, chars = p.get("meta", {}), p.get("world", {}), p.get("characters", [])
    edits = [SetupEdit(key="theme", text=f"잃은 것을 놓아줄 수 있나 ({msg})", why="요청"),
             SetupEdit(key="tone", text=meta.get("tone", ""), why="그대로 (걸러져야 함)"),
             SetupEdit(key="logline.block", text="바다를 지키는 마을 사람들", why="막는 힘을 분명히"),
             SetupEdit(key="world.rules", items=list(world.get("rules", [])) + ["밤에는 등대 불을 끄지 않는다"], why="규칙 하나 더")]
    out = SetupRevision(reply=f"'{msg}' 에 맞춰 주제와 규칙, 인물을 다듬었어요.", edits=edits)
    if chars:
        hero = chars[0]
        out.characters = [CharacterEdit(id=hero["id"], field="wound", text=f"버려질까 두렵다 ({msg})", why="결핍을 분명히"),
                          CharacterEdit(id="nobody", field="goal", text="없는 인물")]
        out.new_characters = [Character(id="mentor", name="한결", role="조력자", gender="남", age="60대", goal="마을의 비밀을 지킨다",
                                        speech_style="느린 반말. \"물때를 봐라.\"", tier="support", narration_voice="걸러져야 함")]
        out.relationships = [Relationship(a=hero["id"], b="mentor", type="사제", a_view=["믿는다"], b_view=["빚졌다", "없는 말"])]
    return out


# 상태 변경안의 지금 차림: 1화에 처음 적고 2화에 찢어진다. 그 밖의 화는 비워 그대로 둔다
MOCK_LOOK = "어깨에 닿던 머리를 짧게 자른 단발"  # 2화 설정 바꾸기 제안 (외모)
MOCK_ATTIRE = {1: "젖은 회색 코트, 손전등", 2: "젖은 회색 코트(오른쪽 소매 찢어짐), 손전등, 녹슨 열쇠"}

# 설정 칸 하나 AI 후보 (prompts.FIELD_IDEAS 키마다)
MOCK_FIELD_IDEAS = {
    "meta.title": ["등대지기의 마지막 여름", "불이 꺼지지 않는 섬", "물때"],
    "meta.logline_parts.who": ["빚을 갚으려 고향에 돌아온 스물아홉 살 사서", "기억을 잃은 등대지기의 딸", "말을 더듬는 수산시장 경매사"],
    "meta.logline_parts.why": ["실종된 동생의 편지가 도착하자", "등대 불이 사흘째 꺼지지 않자", "마을 축제 날 낯선 배가 들어오자"],
    "meta.logline_parts.goal": ["동생이 사라진 밤을 되짚는다", "등대의 주인을 찾아 섬을 뒤진다", "축제가 끝나기 전에 배를 돌려보낸다"],
    "meta.logline_parts.block": ["마을 사람들은 그 밤을 없던 일로 하려 한다", "등대 열쇠를 가진 이는 이미 죽었다", "배를 부른 것은 그녀의 아버지다"],
    "meta.logline_parts.stake": ["진실을 알면 돌아갈 집이 사라진다", "실패하면 동생을 영영 잃는다", "들키면 마을이 그녀를 내쫓는다"],
    "world.setting": ["안개가 잦은 남해의 작은 섬마을. 등대와 수산시장이 생활의 중심이다.",
                      "관광객이 끊긴 바닷가 소도시. 오래된 가족들이 서로의 비밀을 쥐고 산다.",
                      "썰물 때만 길이 열리는 섬. 물때표가 마을의 시계다."],
}


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
                                markers=[StyleMarker(text="않았다", note="부정으로 끝맺는 서술"),
                                         StyleMarker(text="원문에없는표지", per_1k=9)],
                                sample_passages=["바람이 불었다. 서윤은 고개를 들지 않았다."])  # type: ignore[return-value]
        if schema is ArcPlan:
            return ArcPlan(acts=_arc(hint["total"]))  # type: ignore[return-value]
        if schema is SeriesPlan:
            return _series(hint["total"])  # type: ignore[return-value]
        if schema is ArcProposal:
            return _next_arc(hint)  # type: ignore[return-value]
        if schema is SerialConversion:
            return _conversion(hint)  # type: ignore[return-value]
        if schema is SerialRebuild:
            return _rebuild(hint)  # type: ignore[return-value]
        if schema is Rework:
            return Rework(text=hint["text"].rstrip() + "\n\n도현은 대답 대신 시선을 피했다.", reply="새 자리에 맞게 끝을 고쳤어요.")  # type: ignore[return-value]
        if schema is Recap:
            return Recap(summary=f"{'아크' if hint['kind'] == 'arc' else '부'} {hint['number']} 요약: 주인공이 시험을 넘겼다.")  # type: ignore[return-value]
        if schema is PlotBatch or schema is EpisodeDraft:
            acts: list[Act] = hint["arc"]
            eps = []
            for n in range(hint["start"], hint["end"] + 1):
                act = next(a for a in acts if a.start_ep <= n <= a.end_ep)
                eps.append(_plot(n, act.name))
            new = []
            if hint["start"] <= NEW_CAST_EP <= hint["end"]:  # 새 인물 후보를 시험하도록 한 화에 단역을 데려온다
                eps[NEW_CAST_EP - hint["start"]].characters.append(NEW_CAST.id)
                eps[NEW_CAST_EP - hint["start"]].events.append(f"{NEW_PLACE.name}에 묵는다")
                new = [NEW_CAST]
            places = [NEW_PLACE] if new else []
            if schema is EpisodeDraft:  # 뒤 화에 맞추지 않고 채운 화: 뒤 화와 어긋난 점을 함께 낸다
                return EpisodeDraft(episodes=eps, new_characters=new, new_places=places,
                                    next_gap=f"{hint['end'] + 1}화 첫 장면이 이미 끝난 갈등으로 시작해요.")  # type: ignore[return-value]
            return PlotBatch(episodes=eps, new_characters=new, new_places=places)  # type: ignore[return-value]
        if schema is PlotRevision:
            return _revision(hint)  # type: ignore[return-value]
        if schema is StateDelta:
            n = hint["episode"]
            return StateDelta(
                episode=n, summary=f"{n}화에서 서윤과 도현이 단서를 찾았다.",
                character_updates=[CharacterState(character_id="hero", emotional_state=f"{n}화 이후 조금 더 단단해짐", knows=[f"{n}화 단서"],
                                                  attire=MOCK_ATTIRE.get(n, ""),
                                                  stats=[StatValue(name="레벨", value="+1")] if hint.get("stats") else [])],
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
                foreshadow_clues=[ForeshadowClue(foreshadow="fs-01-key", kind="payoff" if n == 2 else "plant", quote="서윤은 등대 앞에 섰다.")]
                if n in (1, 2) else [],
                setting_changes=[SettingChange(character_id="hero", field="appearance", value=MOCK_LOOK, reason="등대에서 머리를 짧게 잘랐다",
                                               quote="서윤은 등대 앞에 섰다.")] if n == 2 else [],
                time=StoryTime(day=n, part="밤"),
                deadlines_added=[Deadline(id="dl-01-festival", what="등대 축제", day=5, note="닷새 뒤 축제")] if n == 1 else [],
                deadlines_done=["dl-01-festival"] if n == 3 else [],
            )  # type: ignore[return-value]
        if schema is StorylineProposal:
            return _storyline(hint)  # type: ignore[return-value]
        if schema is ImpactReport:
            return _impact(hint)  # type: ignore[return-value]
        if schema is NameOptions:  # 코드 후보에서 앞쪽 n 개를 고른 척한다
            names = hint["candidates"][: hint["n"]]
            return NameOptions(options=[NameOption(name=x, reason="후보 중 인물과 시대에 맞는 이름") for x in names])  # type: ignore[return-value]
        if schema is FieldIdeas:  # 칸마다 다른 결의 후보 셋. 하나는 겹치고 하나는 따옴표를 달아 정리가 고치는지 본다
            base = MOCK_FIELD_IDEAS.get(hint["field"], ["후보 하나", "후보 둘", "후보 셋"])
            return FieldIdeas(options=[FieldIdea(text=f"“{base[0]}”", reason="장르와 로그라인에 맞춰서"),  # type: ignore[return-value]
                                       FieldIdea(text=base[0], reason="겹침"),
                                       *[FieldIdea(text=x, reason="다른 방향") for x in base[1:]]])
        if schema is IllustDraft:
            return _illust(hint)  # type: ignore[return-value]
        if schema is PlaceSort:
            out, new = [], []
            for t in hint.get("texts", []):
                at = next((pl for pl in hint.get("places", []) if pl[:2] in t), "")
                if at:
                    out.append(PlaceGuess(text=t, place=at))
                elif "모를" in t or "가는" in t:
                    out.append(PlaceGuess(text=t, skip=True, note="한 곳으로 그릴 수 없어요"))
                else:
                    name = t.split()[0]
                    out.append(PlaceGuess(text=t, new_place=name))
                    if name not in [x.name for x in new]:
                        new.append(NewPlace(name=name, kind="건물", description="위치 글에서 나온 곳"))
            return PlaceSort(matches=out, new_places=new)  # type: ignore[return-value]
        if schema is MapSuggestion:  # 이름 단어로 종류를 고르고, 바다 쪽 장소가 있으면 바닷가 마을로
            from . import towngen

            guesses = [MapPlaceGuess(name=n, kind=towngen.classify(n)[0], put=towngen.classify(n)[0] != "far") for n in hint.get("places", [])]
            rows = [{"kind": g.kind, "word": towngen.classify(g.name)[1], "put": g.put} for g in guesses]
            water = towngen.water_for(rows)
            return MapSuggestion(size="small", roads="square", water=water, fields="some", forest="few", places=guesses,  # type: ignore[return-value]
                                 reason=f"장소 목록을 보고 물을 {towngen.OPTIONS['water'][water]}(으)로 정했어요.")
        if schema is BodySuggestion:
            return BodySuggestion(height="163cm", weight="50kg", build="마른 근육형", measurements="82-60-86",
                                  features="왼손잡이, 오른쪽 손목에 점", note="외모 칸의 흉터와 성격에 맞춰 활동적인 체형으로 정했어요.")  # type: ignore[return-value]
        if schema is StatInitSuggestion:  # 첫 인물만, 바뀐 양으로 적은 값 하나와 틀 밖 항목 하나 (정리가 고치는지)
            ids = hint.get("characters", [])
            names = hint.get("names") or ["레벨", "HP", "스킬"]
            rows = [StatValue(name=names[0], value="+1"), StatValue(name="HP", value="100/100"), StatValue(name="스킬", value="은신"),
                    StatValue(name="틀 밖", value="1")]
            return StatInitSuggestion(names=["레벨", "HP", "스킬"], characters=[  # type: ignore[return-value]
                StatInitCharacter(character_id=ids[0] if ids else "hero", stats=rows, note="바닥에서 시작하는 주인공이라 낮게 정했어요."),
                StatInitCharacter(character_id="nobody", stats=rows)])
        if schema is StatWindowSuggestion:  # 장식이 붙은 안 하나와 {rows} 를 빠뜨린 안 하나 (정리가 고치는지)
            return StatWindowSuggestion(options=[  # type: ignore[return-value]
                StatWindowOption(label="무공록", title="무공록", template="━━━━━━━━━━━━\\n【 무공록 】 {name}\\n━━━━━━━━━━━━\\n{rows}\\n━━━━━━━━━━━━",
                                 row="▸ {key} ┃ {value}", names=["경지", "내공", "무공"], skin="scroll", why="무협 배경이라 경지와 내공으로 지었어요."),
                StatWindowOption(label="협회 등록증", title="헌터 등록증", template="[헌터 등록증]\n성명: {name}", row="{key} - 값",
                                 names=["등급", "레벨", "스킬", "스킬"], skin="plain", why=hint.get("request") or "협회 서류처럼 담백하게 했어요."),
            ])
        if schema is LookSuggestion:
            return LookSuggestion(subject="girl", look=["Black_hair", "short hair", "brown eyes", "teenage"], outfit=["school uniform"],
                                  note="설정에 눈 색이 없어 갈색으로 정했어요.")  # type: ignore[return-value]
        if schema is VoiceSuggestion:
            return VoiceSuggestion(voice="서술 어미는 ~했어요, ~인 걸까요? 처럼 부드럽게 끝낸다.\n짧은 문장 뒤에 스스로 묻는 문장을 하나 붙인다.\n"
                                   "예: 바람이 차가웠어요. 그 사람도 이 바람을 맞고 있을까요?",
                                   note="대사 말투보다 한 단계 차분하게 잡았어요.")  # type: ignore[return-value]
        if schema is StyleLearning:
            return _learning(hint)  # type: ignore[return-value]
        if schema is StyleRevision:
            return _style_revision(hint)  # type: ignore[return-value]
        if schema is SetupRevision:
            return _setup_revision(hint)  # type: ignore[return-value]
        if schema is StyleSample:  # 참고한 화가 있으면 그 앞부분을 고쳐 쓴 척한다
            ref = hint.get("ref", "")[:80].strip()
            return StyleSample(text=f"바람이 찼다. 그는 걸음을 늦췄다.\n\n\"늦었네.\" {hint.get('scene', '')}".strip(),
                               source=ref)  # type: ignore[return-value]
        if schema is PassageRevision:
            return _passage(hint)  # type: ignore[return-value]
        if schema is FixSet:
            return _fixes(hint)  # type: ignore[return-value]
        if schema is FindingRecheck:  # 지적한 문장이 본문에서 바뀌었으면 풀린 것으로 본다
            gone = hint["quote"].strip() not in hint.get("text", "")
            return FindingRecheck(resolved=gone, reason="문장이 바뀌어 어긋남이 풀렸어요" if gone else "문장이 그대로예요")  # type: ignore[return-value]
        if schema is HookReport:
            return _hook(hint)  # type: ignore[return-value]
        if schema is OpeningPlots:
            return _openings(hint)  # type: ignore[return-value]
        if schema is PlantSet:
            return _plants(hint)  # type: ignore[return-value]
        if schema is ClaimSet:  # 두 걸음 검수: 본문 문장마다 진술 하나
            sents = [x.strip() for x in re.findall(r"[^.!?\n]+[.!?]", hint.get("text", "")) if len(x.strip()) > 4]
            return ClaimSet(claims=[Claim(quote=x, claim=x) for x in sents[:30]])  # type: ignore[return-value]
        if schema is SceneCheck:  # 장면 상태표 검수: 첫 문장 상태 한 줄, 프롬프트에 들어간 심은 문장을 동선으로 짚는다
            sents = [x.strip() for x in re.findall(r"[^.!?\n]+[.!?]", hint.get("text", "")) if len(x.strip()) > 4]
            n = hint.get("episode", 0)
            return SceneCheck(beats=[SceneBeat(quote=sents[0], bodies=[BodyState(name="서윤", facing="문을 향함", hands="한 손 문고리")])] if sents else [],
                              issues=[ConsistencyIssue(type="동선", description="상태표와 어긋남", source_episode=n,
                                                       source_quote=sents[0] if sents else "", current_quote=x)
                                      for x in hint.get("plants", []) if x in prompt])  # type: ignore[return-value]
        if schema is ConsistencyReport and "plants" in hint:  # 검수 시험: 프롬프트에 들어간 심은 문장을 짚는다
            return ConsistencyReport(episode=hint["episode"], issues=[ConsistencyIssue(
                type="사실", description="심은 모순", source_episode=0, source_quote="설정", current_quote=x)
                for x in hint["plants"] if x in prompt])  # type: ignore[return-value]
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
        if "화 다시 쓰기\n" in prompt:  # 다시 생성: 지난 판과 다른 글을 낸다
            return "바람이 멎었다. 서윤은 등대 문을 밀었다.\n\n\"이번엔 내가 먼저 갈게.\"\n\n(mock 다시 쓴 본문)"
        return "바람이 불었다. 서윤은 등대 앞에 섰다.\n\n\"됐어, 내가 할게.\"\n\n(mock 본문)"

    # Batch API 흉내. CANON_MOCK_BATCH_POLLS=n 이면 n 번 물어본 뒤에 끝난다 (기본 0: 바로 끝).
    def batch_submit(self, system: str, prompt: str, schema: type[BaseModel] | None, label: str,
                     hint: dict | None = None) -> str:
        import os
        import uuid

        out = self.json(system, prompt, schema, hint).model_dump_json() if schema else self.text(system, prompt)
        if schema is not None and schema.__name__ in BAD_JSON:
            BAD_JSON.remove(schema.__name__)
            out = _broken(out)
        name = f"batches/mock-{uuid.uuid4().hex[:8]}"
        BATCHES[name] = {"out": out, "polls": int(os.environ.get("CANON_MOCK_BATCH_POLLS", "0") or 0),
                         "label": label, "cancelled": False}
        return name

    def batch_poll(self, name: str) -> str | None:
        b = BATCHES.get(name)
        from .llm import BatchGone
        if b is None:
            raise BatchGone(f"없는 배치 작업: {name}")
        if b["cancelled"]:
            raise BatchGone("배치 작업이 취소됐습니다")
        if b["polls"] > 0:
            b["polls"] -= 1
            return None
        return b["out"]

    def batch_cancel(self, name: str) -> None:
        if name in BATCHES:
            BATCHES[name]["cancelled"] = True


BATCHES: dict[str, dict] = {}  # 프로세스 안에서만 유지되는 가짜 배치 작업
BAD_JSON: list[str] = []  # 여기 넣은 스키마 이름은 다음 배치 응답 한 번을 형식이 틀리게 낸다 (넣은 만큼)


def _broken(out: str) -> str:
    """실제 배치에서 본 모양: 필수 칸이 빠지고 목록 항목이 "a: b=c" 같은 문자열이다."""
    import json

    d = json.loads(out)
    d.pop("summary", None)
    for k, v in d.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            d[k] = [": ".join(str(x) for x in item.values())[:80] for item in v]
    return json.dumps(d, ensure_ascii=False)
