"""API 키 없이 전체 흐름을 확인하기 위한 가짜 LLM (CANON_LLM=mock)."""
from __future__ import annotations

import re
from typing import Callable, TypeVar

from pydantic import BaseModel

from .schema import (
    AddressChange,
    Act,
    AgentAsk,
    PlotAgentStep,
    ToolArg,
    ArcEdit,
    ArcPlan,
    ArcProposal,
    Character,
    CharacterState,
    Claim,
    ClaimSet,
    ConsistencyIssue,
    ConsistencyIssueEn,
    ConsistencyReport,
    ConsistencyReportEn,
    FindingRecheck,
    FixBatch,
    FixItem,
    FixOption,
    FixPatch,
    FixSet,
    Direction,
    PlantedContradiction,
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
    BlueprintBodyDraft,
    BodyFeatureDraft,
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
    StateDeltaAI,
    ContactReach,
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
    StyleDevice,
    StyleMarker,
    StyleProfile,
    StyleRuleSuggestion,
    TextPatch,
    TierChange,
    WorldSetting,
)

T = TypeVar("T", bound=BaseModel)

# 기능 모듈이 자기 스키마의 가짜 응답을 따로 둔다 (mock_play.py, mock_birth.py). MockLLM.json 이 먼저 찾는다.
# 새 기능의 가짜 응답은 mock_<기능>.py 에 @responds(스키마) 로 두고, 맨 아래에서 불러온다. 이 파일의 응답도 같은 방식이다.
RESPONDERS: dict[type, Callable[[str, dict], BaseModel]] = {}


def responds(schema: type[BaseModel]):
    """fn(prompt, hint) 을 schema 의 가짜 응답으로 등록한다."""
    def wrap(fn: Callable[[str, dict], BaseModel]) -> Callable[[str, dict], BaseModel]:
        RESPONDERS[schema] = fn
        return fn
    return wrap


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


MOCK_SETUP_WORDS = ("날카롭", "다듬", "바꿔", "더해", "채워", "어둡게")  # 설정 도구를 부르는 말 (_agent_step)


def _agent_step(hint: dict) -> PlotAgentStep:
    """대화 에이전트 흉내. 처음엔 플롯을 읽고, 다음 단계에 플롯 대화 흉내(_revision)로 고치고, 쓴 결과를 보면 끝낸다.
    '여러 안' 요청은 되묻고, '?' 로 끝나면 답만 하고, '끝없이' 는 상한 시험으로 늘 읽는다.
    '끝 이름' 은 읽은 뒤 칸 이름 reply 를 도구로 적어 끝낸다 (모델이 실제로 낸 응답 모양).
    대상이 본문 · 설정 · 문체(hint 'aim')이면 '플롯'이 든 말만 고치고 나머지는 읽은 뒤 답만 한다.
    'N화 앞에 M화' 는 화 넣기, 'N화 빼' 는 화 빼기를 묻고, '빈 물음' 은 묻는 말 없는 ask 를 내고, '분석' 은 처음에 예고만 하고, 되돌림 단계(tool 'reply')를 보면 내용을 쓴다.
    대상이 설정이거나 '설정을' 이 든 말이 MOCK_SETUP_WORDS 를 담으면 설정 도구(edit_setup)를 부른다.
    본문 대상에서 «원문» 이 든 말은 본문 고치기(revise_text)를 그 원문으로 부르고, 막혔으면 답만 한다.
    대상이 문체이거나 말에 '문체'가 들면 문체 도구(edit_style)를 부른다. 'N화 참고' 는 episode 인자, 문체 대상의 '?' 물음은 답만 한다.
    말에 '규칙'과 «찾을 글»(또는 'rule=id')이 들면 정규식 규칙 제안(propose_regex)을 부른다 (_regex_args). 막혀 돌아오면 답만 한다."""
    msg, steps, tools = hint["message"], hint.get("steps", []), hint.get("tools", [])
    if "끝없이" in msg:
        return PlotAgentStep(thought="더 읽어 봐요", tool="read_plots",
                             args=[ToolArg(name="from", value="1"), ToolArg(name="to", value=str(len(steps) + 1))])
    if hint.get("mode") == "options" and "ask" not in tools:
        rev = _revision({**hint, "mode": "options"})
        return PlotAgentStep(thought="방향을 먼저 물어요", tool="ask", question="어느 방향으로 갈까요?", options=rev.options, reply=rev.reply)
    hit = re.search(r"(\d+)화 앞에 (\d+)화", msg)
    if hit and "approval" not in tools and not any(t in tools for t in ("insert_episodes", "remove_episode")):
        at, c = int(hit.group(1)), int(hit.group(2))
        return PlotAgentStep(thought="화를 넣어요", tool="insert_episodes", reply="화를 넣어도 될지 물어요.",
                             args=[ToolArg(name="at", value=str(at)), ToolArg(name="count", value=str(c)),
                                   ToolArg(name="titles", value=" | ".join(f"새 화 {k + 1}" for k in range(c)))])
    hit = re.search(r"(\d+)화 빼", msg)
    if hit and "approval" not in tools and "remove_episode" not in tools:
        return PlotAgentStep(thought="화를 빼요", tool="remove_episode", args=[ToolArg(name="n", value=hit.group(1))])
    if "빈 고치기" in msg and "edit_plot" not in tools:  # 도구 이름만 내고 edit 을 비운 응답 (2026-11-04 gemini-4-argon). 채우기는 PlotRevision
        return PlotAgentStep(thought="고쳐요", tool="edit_plot")
    if "빈 채우기" in msg and not steps:  # 묻는 말을 비운 ask. 채우기는 AgentAsk
        return PlotAgentStep(thought="물어요", tool="ask")
    if "빈 물음" in msg:  # 묻는 말 · 안 · 답이 모두 빈 ask (2026-11-04 실제 응답 모양). '계속' 이면 되돌려도 또 빈 ask
        if "ask_empty" in tools and "계속" not in msg:
            return PlotAgentStep(reply="1~7화를 보면 승 구간의 감각 묘사가 4화에서 끊겨요.")
        return PlotAgentStep(tool="ask")
    if "분석" in msg:  # 첫 답은 예고만 한다 (2026-11-04 실제 응답 모양). 되돌림 단계를 보면 내용을 쓴다
        if "reply" in tools:
            return PlotAgentStep(reply="기(1~2화)는 일상이 깨지는 사건이 늦어요. 승(3~5화)은 감각 묘사가 점점 짙어져요.")
        return PlotAgentStep(reply="아크 1(1~7화)의 기승전결 구조를 분석해 작가님께 전달합니다.")
    if "끝 이름" in msg and steps:
        return PlotAgentStep.model_validate({"tool": "reply", "reply": "읽어 보니 고칠 곳이 없어요."})
    if "propose_regex" in tools:  # 막혀서 카드 없이 돌아왔다 (카드를 남기면 턴이 끝난다)
        return PlotAgentStep(reply="규칙을 만들지 못했어요. 막힌 까닭을 보고 다시 말해 주세요.")
    quotes = re.findall(r"«([^»]+)»", msg)
    if "규칙" in msg and (quotes or "rule=" in msg):  # 정규식 규칙 제안 (06b). 본문 대상의 «…» 도 revise_text 보다 먼저 받는다
        return PlotAgentStep(thought="규칙을 제안해요", tool="propose_regex", reply="규칙을 만들어 봤어요. 적용할지 골라 주세요.",
                             args=_regex_args(msg, quotes))
    quote = re.search(r"«([^»]+)»", msg)
    if hint.get("aim") == "text" and quote:
        if "revise_text" in tools:
            return PlotAgentStep(reply="고른 부분을 고치지 못했어요.")
        return PlotAgentStep(thought="고를 부분을 고쳐요", tool="revise_text",
                             args=[ToolArg(name="quote", value=quote.group(1)), ToolArg(name="request", value=msg)])
    if (hint.get("aim") == "setup" or "설정을" in msg) and "플롯" not in msg and any(w in msg for w in MOCK_SETUP_WORDS) \
            and not {"edit_setup", "approval"} & set(tools):  # 설정 도구 (UX 04c). 대상이 설정이 아니어도 '설정을 …' 이면 부른다
        return PlotAgentStep(thought="설정 변경안을 받아요", tool="edit_setup", args=[ToolArg(name="request", value=msg)])
    if "edit_setup" in tools and "approval" not in tools:  # 바뀌는 칸이 없어 카드 없이 돌아왔다
        return PlotAgentStep(reply="설정은 지금 그대로가 좋아 보여요.")
    style_aim = hint.get("aim") == "style" and "플롯" not in msg
    if (style_aim or "문체" in msg) and "edit_style" not in tools and not msg.rstrip().endswith("?"):
        ref = re.search(r"(\d+)화 참고", msg)
        return PlotAgentStep(thought="문체 편집자에게 맡겨요", tool="edit_style",
                             args=[ToolArg(name="request", value=msg), ToolArg(name="episode", value=ref.group(1) if ref else "")])
    if style_aim:  # 문체 도구가 막혔거나 물음이면 답만 한다
        return PlotAgentStep(reply="문체 변경안을 만들지 못했어요. 참고할 화를 바꿔 다시 말해 주세요." if "edit_style" in tools
                             else f"지금 문체를 봤어요: '{msg}'")
    if "approval" in tools:
        return PlotAgentStep(reply="작가의 답대로 마쳤어요.")
    if "edit_plot" in tools or msg.rstrip().endswith("?"):
        return PlotAgentStep(reply=f"'{msg}' 를 반영했어요.")
    if hint.get("aim") in ("text", "setup") and "플롯" not in msg and steps:  # 본문 · 설정 대상: 쓰기 도구가 없어 읽고 답만 한다
        return PlotAgentStep(reply=f"읽어 봤어요. 이 대상은 아직 바로 고치는 도구가 없어 제안만 드려요: '{msg}'")
    if not steps:
        return PlotAgentStep(thought="지금 플롯부터 봐요", tool="read_plots",
                             args=[ToolArg(name="from", value="1"), ToolArg(name="to", value="3")])
    edit = _revision({**hint, "mode": ""})
    return PlotAgentStep(thought="말한 대로 고쳐요", tool="edit_plot", edit=edit)


MOCK_REGEX_ARGS = ("bundle", "rule", "comment", "out", "action", "type", "flag", "enabled")  # 말 속 'k=v' 로 받는 propose_regex 인자


def _js_escape(text: str) -> str:
    """찾을 글을 JavaScript 정규식 글자 그대로로."""
    return re.sub(r"([\\^$.|?*+()\[\]{}/])", r"\\\1", text)


def _regex_args(msg: str, quotes: list[str]) -> list[ToolArg]:
    """propose_regex 인자 흉내: 첫 «…» 는 찾을 글(in), 둘째 «…» 는 바꿀 글(out). '고침' 이 들면 fix, '나쁜 규칙' 이면 겹친 반복 (a+)+.
    'rule=id' · 'enabled=false' · 'type=export' 같은 'k=v' 는 그 인자로 넣는다."""
    args = {"comment": "대화로 만든 규칙"} if quotes else {}
    if quotes:
        args["in"] = _js_escape(quotes[0])
    if len(quotes) > 1:
        args["out"] = quotes[1]
    if "고침" in msg:
        args["action"] = "fix"
    if "나쁜 규칙" in msg:
        args["in"] = "(a+)+"
    for k, v in re.findall(r"(\w+)=(\S+)", msg):
        if k in MOCK_REGEX_ARGS:
            args[k] = v
    return [ToolArg(name=k, value=v) for k, v in args.items()]


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
MOCK_CALLS = "서윤아"  # 3화 호칭 · 말씨 바뀜 제안 (도현 → 서윤, 반말로)
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
    "characters.*.personality": ["말수가 적고 남의 부탁을 거절하지 못한다. 불안하면 손톱 옆 살을 뜯는다.",
                                 "무엇이든 직접 확인해야 믿는다. 웃을 때도 눈은 상대를 살핀다.",
                                 "농담으로 분위기를 풀지만 진짜 속마음은 끝까지 말하지 않는다."],
    "characters.*.background": ["열두 살 때 등대 사고로 아버지를 잃고 이모 손에 컸다.",
                                "도시에서 기자로 일하다 오보 사건으로 그만두고 섬에 돌아왔다.",
                                "수산시장 경매사 집안의 막내로, 가업을 잇기 싫어 집을 나갔었다."],
    "characters.*.appearance": ["짧게 친 머리와 소매가 닳은 회색 코트, 왼손 등의 오래된 화상 자국.",
                                "키가 크고 마른 몸, 늘 목에 건 낡은 필름 카메라.",
                                "햇볕에 그을린 얼굴과 굵은 손마디, 귀 뒤에 꽂은 연필."],
    "characters.*.arc": ["혼자 감당하려 한다 → 도움을 청할 줄 안다",
                         "진실을 덮으려 한다 → 대가를 치르고 밝힌다",
                         "섬을 떠나고 싶어 한다 → 섬에 남기로 스스로 고른다"],
    "characters.*.goal": ["사라진 동생을 찾아 그 밤의 진실을 밝히고 싶다. 속으로는 자기 탓이 아니었다는 말을 듣고 싶다.",
                          "등대를 지켜 아버지가 남긴 자리를 잇고 싶다.",
                          "섬을 떠나 아무도 자기를 모르는 곳에서 다시 시작하고 싶다."],
    "characters.*.wound": ["가까운 사람이 말없이 떠나는 것. 동생이 사라진 밤 붙잡지 못한 기억 때문이다.",
                           "남에게 짐이 되는 것. 그래서 도움을 청하지 못한다.",
                           "자기 판단을 믿지 못한다. 한 번의 오보가 모든 걸 앗아 갔다."],
    "characters.*.secrets": ["동생이 사라진 밤 마지막으로 통화한 사람이 자기다.",
                             "등대 열쇠의 사본을 몰래 가지고 있다.",
                             "섬을 떠날 배표를 이미 사 두었다."],
    "characters.*.speech_style": ["짧은 반말. 상대를 성으로 부르고 질문에 질문으로 답한다. 예: \"그걸 왜 나한테 물어?\"",
                                  "공손한 해요체. 말끝을 흐리고 사과를 먼저 한다. 예: \"죄송해요, 제가 괜히…\"",
                                  "사투리 섞인 반말. 호칭은 늘 '야'. 예: \"야, 니 또 혼자 갈 끼가.\""],
}


class MockLLM:
    knows_cut = True  # 끊긴 응답을 last_finish 로 알린다 (CUT_TEXT). pipeline._write 가 출력 한도를 건다
    last_finish = ""

    def json(self, system: str, prompt: str, schema: type[T], hint: dict | None = None) -> T:
        _delay()
        hint = hint or {}
        if schema in RESPONDERS:
            return RESPONDERS[schema](prompt, hint)  # type: ignore[return-value]
        raise NotImplementedError(schema.__name__)

    def text(self, system: str, prompt: str) -> str:
        out = self._text(system, prompt)
        self.last_finish = "STOP"
        if CUT_TEXT:  # 출력 길이 한도에 걸려 끊긴 응답 흉내: 앞 절반만 낸다
            empty = CUT_TEXT.pop() == "empty"
            self.last_finish = "MAX_TOKENS"
            if empty:  # 생각만 하다 한도에 걸려 글 없이 끝난 응답 (GeminiLLM 은 '응답이 비었어요' 오류를 낸다)
                raise RuntimeError("Gemini 응답이 비었어요: MAX_TOKENS")
            out = out[:max(1, len(out) // 2)]
        return out

    def text_stream(self, system: str, prompt: str, on_chunk: Callable[[str], None]) -> str:
        """text 와 같은 글을 STREAM_PIECES 조각으로 나눠 낸다. 조각마다 지금까지의 글 전체로 on_chunk 를 부르고 멈추기 신호를 본다.
        CANON_MOCK_STREAM_DELAY=초 면 조각 사이에 기다린다 (화면의 부분 글 미리보기 확인용, 기본 0)."""
        import os
        import time

        from . import cancel

        out = self.text(system, prompt)
        pause = float(os.environ.get("CANON_MOCK_STREAM_DELAY", "0") or 0)
        step = max(1, -(-len(out) // STREAM_PIECES))
        for end in range(step, len(out) + step, step):
            cancel.check()
            if pause:
                time.sleep(pause)
            on_chunk(out[:end])
        return out

    def _text(self, system: str, prompt: str) -> str:
        _delay()
        from .mock_cue import text_for
        if (cue := text_for(prompt)) is not None:  # 큐 시트 집필 실험
            return cue
        if "\n# 다듬을 본문\n" in prompt:  # 서술 다듬기: 대사 · 효과음 줄은 그대로, 서술 줄 끝만 바꾼다
            body = prompt.split("\n# 다듬을 본문\n", 1)[1].split("\n\n# 할 일\n", 1)[0]
            from .pipeline import fixed_lines
            keep = set(fixed_lines(body))
            return "\n".join(x if not x.strip() or x.strip() in keep else x.rstrip(".") + "…" for x in body.split("\n"))
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
                         "label": label, "cancelled": False, "finish": self.last_finish if schema is None else "STOP"}
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
        self.last_finish = b.get("finish", "STOP")  # GeminiLLM.batch_poll 처럼 끝난 이유를 남긴다 (CUT_TEXT 면 MAX_TOKENS)
        return b["out"]

    def batch_cancel(self, name: str) -> None:
        if name in BATCHES:
            BATCHES[name]["cancelled"] = True


# ---------- 스키마별 가짜 응답 (MockLLM.json 이 RESPONDERS 에서 찾는다) ----------

@responds(SetupSuggestion)
def _r_setup_suggestion(prompt: str, hint: dict):
    return SetupSuggestion(
        theme="상실을 받아들이는 용기", tone="잔잔하지만 긴장감 있는",
        world=WorldSetting(setting="바닷가 소도시", era="현대", rules=["초자연 요소 없음"], locations=["등대", "수산시장"]),
        characters=[
            Character(id="hero", name="서윤", role="주인공", gender="여", age="19세", goal="사라진 오빠를 찾는다", speech_style="짧고 건조한 반말. \"됐어, 내가 할게.\""),
            Character(id="ally", name="도현", role="조연", gender="남", age="24세", goal="서윤을 돕는다", speech_style="느긋한 존댓말. \"천천히 해요.\""),
        ],
        relationships=[Relationship(a="hero", b="ally", type="동료", affinity=1, tension=3, a_view=["경계한다"], b_view=["좋아한다", "빚졌다"])],
    )


@responds(StyleProfile)
def _r_style_profile(prompt: str, hint: dict):
    return StyleProfile(narration_pov="3인칭 제한", tense="과거형", sentence_rhythm="짧은 문장 위주",
                        dos=["감각 묘사로 장면 시작"], donts=["설명조 대사"],
                        # 있었다 · 대답은 시험 원문(tests/fixtures/revlab_story.txt)에, 않았다는 examples/sample_style.txt 에 있다.
                        # '다'(한글 1자) · '서윤은'(인물 이름) · 원문에 없는 표지와 지어낸 장치 예시는 count_markers 가 거른다
                        markers=[StyleMarker(text="않았다", note="부정으로 끝맺는 서술"), StyleMarker(text="있었다", note="상태 서술"),
                                 StyleMarker(text="다", per_1k=40), StyleMarker(text="서윤은", per_1k=3),
                                 StyleMarker(text="원문에없는표지", per_1k=9)],
                        devices=[StyleDevice(name="대답 없는 침묵", when="물음에 답이 오지 않을 때", cues=["대답", "다"], every=3,
                                             example="대답은 없었다."),
                                 StyleDevice(name="지어낸 장치", cues=["원문에없는글자"], example="지어낸 예시 문장이다.")],
                        sample_passages=["바람이 불었다. 서윤은 고개를 들지 않았다."])


@responds(ArcPlan)
def _r_arc_plan(prompt: str, hint: dict):
    return ArcPlan(acts=_arc(hint["total"]))


@responds(SeriesPlan)
def _r_series_plan(prompt: str, hint: dict):
    return _series(hint["total"])


@responds(ArcProposal)
def _r_arc_proposal(prompt: str, hint: dict):
    return _next_arc(hint)


@responds(SerialConversion)
def _r_serial_conversion(prompt: str, hint: dict):
    return _conversion(hint)


@responds(SerialRebuild)
def _r_serial_rebuild(prompt: str, hint: dict):
    return _rebuild(hint)


@responds(Rework)
def _r_rework(prompt: str, hint: dict):
    return Rework(text=hint["text"].rstrip() + "\n\n도현은 대답 대신 시선을 피했다.", reply="새 자리에 맞게 끝을 고쳤어요.")


@responds(Recap)
def _r_recap(prompt: str, hint: dict):
    return Recap(summary=f"{'아크' if hint['kind'] == 'arc' else '부'} {hint['number']} 요약: 주인공이 시험을 넘겼다.")


def _r_plot_batch(prompt: str, hint: dict, schema: type[BaseModel]):
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
                            next_gap=f"{hint['end'] + 1}화 첫 장면이 이미 끝난 갈등으로 시작해요.")
    return PlotBatch(episodes=eps, new_characters=new, new_places=places)


responds(PlotBatch)(lambda prompt, hint: _r_plot_batch(prompt, hint, PlotBatch))
responds(EpisodeDraft)(lambda prompt, hint: _r_plot_batch(prompt, hint, EpisodeDraft))


@responds(PlotRevision)
def _r_plot_revision(prompt: str, hint: dict):
    return _revision(hint)


@responds(PlotAgentStep)
def _r_plot_agent_step(prompt: str, hint: dict):
    return _agent_step(hint)


@responds(AgentAsk)
def _r_agent_ask(prompt: str, hint: dict):
    # 빈 ask 채우기 (agent.fill). '빈 물음' 은 채워도 빈 채로 둬 되돌림 단계를 시험한다
    if "빈 물음" in hint["message"]:
        return AgentAsk(question="")
    return AgentAsk(question="몇 화로 갈까요?", options=[Direction(title=t, idea=f"{t}로 간다.") for t in ("7화", "15화")])


_CONTACT_LINE = re.compile(r"^  (\S+): .*?\((\S+?)\) ↔ .*?\((\S+?)\) ", re.M)


def _mock_contacts(prompt: str) -> list[ContactReach]:
    """상태 변경안 요청에 닿을 수 있는 사다리 칸 목록(blueprint.state_rule)이 있으면 첫 칸에 닿았다고 낸다."""
    if "contacts 에는" not in prompt:
        return []
    m = _CONTACT_LINE.search(prompt[prompt.index("contacts 에는"):])
    return [ContactReach(a=m.group(2), b=m.group(3), rung=m.group(1), quote="서윤은 등대 앞에 섰다.")] if m else []


@responds(StateDeltaAI)
@responds(StateDelta)
def _r_state_delta(prompt: str, hint: dict):
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
        address_changes=[AddressChange(speaker="ally", listener="hero", calls=MOCK_CALLS, speech="해체(반말)",
                                       reason="등대에서 서로 말을 놓기로 했다", quote="서윤은 등대 앞에 섰다.")] if n == 3 else [],
        contacts=_mock_contacts(prompt),
        time=StoryTime(day=n, part="밤"),
        deadlines_added=[Deadline(id="dl-01-festival", what="등대 축제", day=5, note="닷새 뒤 축제")] if n == 1 else [],
        deadlines_done=["dl-01-festival"] if n == 3 else [],
    )


@responds(StorylineProposal)
def _r_storyline_proposal(prompt: str, hint: dict):
    return _storyline(hint)


@responds(ImpactReport)
def _r_impact_report(prompt: str, hint: dict):
    return _impact(hint)


@responds(NameOptions)
def _r_name_options(prompt: str, hint: dict):
    # 코드 후보에서 앞쪽 n 개를 고른 척한다
    names = hint["candidates"][: hint["n"]]
    return NameOptions(options=[NameOption(name=x, reason="후보 중 인물과 시대에 맞는 이름") for x in names])


@responds(FieldIdeas)
def _r_field_ideas(prompt: str, hint: dict):
    # 칸마다 다른 결의 후보 셋. 하나는 겹치고 하나는 따옴표를 달아 정리가 고치는지 본다
    base = MOCK_FIELD_IDEAS.get(hint["field"], ["후보 하나", "후보 둘", "후보 셋"])
    return FieldIdeas(options=[FieldIdea(text=f"“{base[0]}”", reason="장르와 로그라인에 맞춰서"),
                               FieldIdea(text=base[0], reason="겹침"),
                               *[FieldIdea(text=x, reason="다른 방향") for x in base[1:]]])


@responds(IllustDraft)
def _r_illust_draft(prompt: str, hint: dict):
    return _illust(hint)


@responds(PlaceSort)
def _r_place_sort(prompt: str, hint: dict):
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
    return PlaceSort(matches=out, new_places=new)


@responds(MapSuggestion)
def _r_map_suggestion(prompt: str, hint: dict):
    # 이름 단어로 그 시대 종류를 고르고, 바다 쪽 장소가 있으면 바닷가 마을로. 화면에서 현대 동네를 골랐으면 현대 동네 (물은 하천)
    from . import atlas
    from .maps import kinds as placekinds

    era = placekinds.era_of("modern" if hint.get("kind") == "modern" else "village")
    found = {n: placekinds.classify(n, era=era) for n in hint.get("places", [])}
    guesses = [MapPlaceGuess(name=n, kind=k, put=k != "far") for n, (k, _) in found.items()]
    rows = [{"kind": g.kind, "word": found[g.name][1], "put": g.put} for g in guesses]
    water = placekinds.water_for(rows)
    if hint.get("kind") == "modern":
        water = "none" if water == "none" else "river"
        return MapSuggestion(kind="modern", size="medium", roads="cross", water=water, fields="few", forest="some",
                             places=guesses, reason=f"고른 현대 동네에 맞춰 물을 {atlas.MAKERS['modern'][1].OPTIONS['water'][water]}(으)로 정했어요.")
    return MapSuggestion(size="small", roads="square", water=water, fields="some", forest="few", places=guesses,
                         reason=f"장소 목록을 보고 물을 {atlas.MAKERS['village'][1].OPTIONS['water'][water]}(으)로 정했어요.")


@responds(BodySuggestion)
def _r_body_suggestion(prompt: str, hint: dict):
    return BodySuggestion(height="163cm", weight="50kg", build="마른 근육형", measurements="82-60-86",
                          features="왼손잡이, 오른쪽 손목에 점", note="외모 칸의 흉터와 성격에 맞춰 활동적인 체형으로 정했어요.")


@responds(BlueprintBodyDraft)
def _r_blueprint_body(prompt: str, hint: dict):
    # 재료 줄에서 흉터 · 점 · 문신 · 자국 낱말이 든 구절을 특징으로 (근거 검사 · 겹침 빼기를 시험할 수 있게 그대로 옮긴다)
    feats, seen = [], set()
    for line in hint.get("lines", []):
        for m in re.finditer(r"[^\s,.:()·]*\s?[^\s,.:()·]*(?:흉터|점|문신|자국)", line):
            text = m.group().strip()
            if text and text not in seen:
                seen.add(text)
                feats.append(BodyFeatureDraft(text=text, quote=text))
    return BlueprintBodyDraft(features=feats, note=f"설계도 줄에서 특징 {len(feats)}개를 찾았어요." if feats else "설계도 줄에 신체 특징이 없어요.")


@responds(StatInitSuggestion)
def _r_stat_init_suggestion(prompt: str, hint: dict):
    # 첫 인물만, 바뀐 양으로 적은 값 하나와 틀 밖 항목 하나 (정리가 고치는지)
    ids = hint.get("characters", [])
    names = hint.get("names") or ["레벨", "HP", "스킬"]
    rows = [StatValue(name=names[0], value="+1"), StatValue(name="HP", value="100/100"), StatValue(name="스킬", value="은신"),
            StatValue(name="틀 밖", value="1")]
    return StatInitSuggestion(names=["레벨", "HP", "스킬"], characters=[
        StatInitCharacter(character_id=ids[0] if ids else "hero", stats=rows, note="바닥에서 시작하는 주인공이라 낮게 정했어요."),
        StatInitCharacter(character_id="nobody", stats=rows)])


@responds(StatWindowSuggestion)
def _r_stat_window_suggestion(prompt: str, hint: dict):
    # 장식이 붙은 안 하나와 {rows} 를 빠뜨린 안 하나 (정리가 고치는지)
    return StatWindowSuggestion(options=[
        StatWindowOption(label="무공록", title="무공록", template="━━━━━━━━━━━━\\n【 무공록 】 {name}\\n━━━━━━━━━━━━\\n{rows}\\n━━━━━━━━━━━━",
                         row="▸ {key} ┃ {value}", names=["경지", "내공", "무공"], skin="scroll", why="무협 배경이라 경지와 내공으로 지었어요."),
        StatWindowOption(label="협회 등록증", title="헌터 등록증", template="[헌터 등록증]\n성명: {name}", row="{key} - 값",
                         names=["등급", "레벨", "스킬", "스킬"], skin="plain", why=hint.get("request") or "협회 서류처럼 담백하게 했어요."),
    ])


@responds(LookSuggestion)
def _r_look_suggestion(prompt: str, hint: dict):
    return LookSuggestion(subject="girl", look=["Black_hair", "short hair", "brown eyes", "teenage"], outfit=["school uniform"],
                          note="설정에 눈 색이 없어 갈색으로 정했어요.")


@responds(VoiceSuggestion)
def _r_voice_suggestion(prompt: str, hint: dict):
    return VoiceSuggestion(voice="서술 어미는 ~했어요, ~인 걸까요? 처럼 부드럽게 끝낸다.\n짧은 문장 뒤에 스스로 묻는 문장을 하나 붙인다.\n"
                           "예: 바람이 차가웠어요. 그 사람도 이 바람을 맞고 있을까요?",
                           note="대사 말투보다 한 단계 차분하게 잡았어요.")


@responds(StyleLearning)
def _r_style_learning(prompt: str, hint: dict):
    return _learning(hint)


@responds(StyleRevision)
def _r_style_revision(prompt: str, hint: dict):
    return _style_revision(hint)


@responds(SetupRevision)
def _r_setup_revision(prompt: str, hint: dict):
    return _setup_revision(hint)


@responds(StyleSample)
def _r_style_sample(prompt: str, hint: dict):
    # 참고한 화가 있으면 그 앞부분을 고쳐 쓴 척한다
    ref = hint.get("ref", "")[:80].strip()
    return StyleSample(text=f"바람이 찼다. 그는 걸음을 늦췄다.\n\n\"늦었네.\" {hint.get('scene', '')}".strip(),
                       source=ref)


@responds(PassageRevision)
def _r_passage_revision(prompt: str, hint: dict):
    return _passage(hint)


@responds(FixSet)
def _r_fix_set(prompt: str, hint: dict):
    return _fixes(hint)


@responds(FixBatch)
def _r_fix_batch(prompt: str, hint: dict):
    # 지적마다 한 지적 고침안(_fixes)과 같은 답을 id 를 달아 낸다
    text = hint.get("text", "")
    return FixBatch(items=[FixItem(finding=x["id"], **_fixes({"quote": x["quote"], "text": text}).model_dump())
                           for x in hint.get("findings", [])])


@responds(FindingRecheck)
def _r_finding_recheck(prompt: str, hint: dict):
    # 지적한 문장이 본문에서 바뀌었으면 풀린 것으로 본다
    gone = hint["quote"].strip() not in hint.get("text", "")
    return FindingRecheck(resolved=gone, reason="문장이 바뀌어 어긋남이 풀렸어요" if gone else "문장이 그대로예요")


@responds(HookReport)
def _r_hook_report(prompt: str, hint: dict):
    return _hook(hint)


@responds(OpeningPlots)
def _r_opening_plots(prompt: str, hint: dict):
    return _openings(hint)


@responds(PlantSet)
def _r_plant_set(prompt: str, hint: dict):
    return _plants(hint)


@responds(ClaimSet)
def _r_claim_set(prompt: str, hint: dict):
    # 두 걸음 검수: 본문 문장마다 진술 하나
    sents = [x.strip() for x in re.findall(r"[^.!?\n]+[.!?]", hint.get("text", "")) if len(x.strip()) > 4]
    return ClaimSet(claims=[Claim(quote=x, claim=x) for x in sents[:30]])


@responds(ConsistencyReport)
def _r_consistency_report(prompt: str, hint: dict):
    if hint.get("motion") and "plants" not in hint:  # 동선 따로 보기: 지적 없음 (합치기는 시험이 따로 본다)
        return ConsistencyReport(episode=hint["episode"], issues=[])
    if "plants" in hint:  # 검수 시험: 프롬프트에 들어간 심은 문장을 짚는다
        return ConsistencyReport(episode=hint["episode"], issues=[ConsistencyIssue(
            type="사실", description="심은 모순", source_episode=0, source_quote="설정", current_quote=x)
            for x in hint["plants"] if x in prompt])
    n = hint["episode"]
    issues = [ConsistencyIssue(
        type="말투", description="도현이 서윤에게 반말을 쓴다", source_episode=0,
        source_quote="느긋한 존댓말. \"천천히 해요.\"", current_quote="\"됐어, 내가 할게.\"",
        suggestion="도현의 대사를 존댓말로 바꾼다",
    )] if n == 2 else []
    return ConsistencyReport(episode=n, issues=issues)


@responds(ConsistencyReportEn)
def _r_consistency_report_en(prompt: str, hint: dict):
    # 검수 시험의 영어 지시문판: 한국어판과 같이 프롬프트에 들어간 심은 문장을 짚는다
    return ConsistencyReportEn(episode=hint["episode"], issues=[ConsistencyIssueEn(
        type="사실", description="심은 모순", source_episode=0, source_quote="설정", current_quote=x)
        for x in hint.get("plants", []) if x in prompt])


BATCHES: dict[str, dict] = {}  # 프로세스 안에서만 유지되는 가짜 배치 작업
BAD_JSON: list[str] = []  # 여기 넣은 스키마 이름은 다음 배치 응답 한 번을 형식이 틀리게 낸다 (넣은 만큼)
STREAM_PIECES = 6  # text_stream 이 글을 나눠 내는 조각 수
CUT_TEXT: list[bool | str] = []  # 넣은 만큼 다음 글 응답(text)을 출력 길이 한도에 걸려 끊긴 것으로 낸다 (last_finish MAX_TOKENS). "empty" 는 글 없이 끝난 응답


def _broken(out: str) -> str:
    """실제 배치에서 본 모양: 필수 칸이 빠지고 목록 항목이 "a: b=c" 같은 문자열이다."""
    import json

    d = json.loads(out)
    d.pop("summary", None)
    for k, v in d.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            d[k] = [": ".join(str(x) for x in item.values())[:80] for item in v]
    return json.dumps(d, ensure_ascii=False)


# 기능별 가짜 응답 등록 (RESPONDERS). 위의 responds 를 쓰므로 맨 끝에서 불러온다
from . import mock_aliases, mock_audit, mock_birth, mock_blueprint, mock_board, mock_coord, mock_cue, mock_fixrecheck, mock_foreshadow_judge, mock_heat, mock_knows, mock_offscreen, mock_play, mock_revlab, mock_stage, mock_studio  # noqa: E402,F401
