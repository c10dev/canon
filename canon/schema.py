"""소설 프로젝트 데이터 스키마.

모든 상태는 하나의 Project 객체(project.json)에 저장된다.
LLM 이 직접 채우는 모델(SetupSuggestion, StyleProfile, ArcPlan, PlotBatch, PlotRevision, NameOptions, StateDelta, ConsistencyReport, ImpactReport)은
Gemini 구조화 출력에 그대로 넘기므로 dict 타입 필드를 쓰지 않는다.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .metrics import StyleMetrics

ActName = Literal["기", "승", "전", "결"]
EpisodeStatus = Literal["draft", "confirmed", "written", "finalized"]


# ---------- 기본 설정 ----------

class LoglineParts(BaseModel):
    """로그라인을 다섯 칸으로 나눈 것. 합친 문장은 Meta.logline 에 둔다 (canon/logline.py)."""
    who: str = Field("", description="누가: 이름보다 특징이 먼저 보이는 주인공")
    why: str = Field("", description="무엇 때문에: 이야기를 시작하게 만드는 일")
    goal: str = Field("", description="무엇을 하려 하나: 눈에 보이는 행동, '~한다'로 끝남")
    block: str = Field("", description="무엇이 막나: 사람이나 힘")
    stake: str = Field("", description="무엇이 걸렸나: 실패하거나 진실을 알면 잃는 것 (선택)")


class ToneDials(BaseModel):
    """톤을 양 끝 사이에서 고른 값. 0 은 고르지 않음, 1~4 는 왼쪽 끝에서 오른쪽 끝."""
    dark: int = Field(0, description="1 밝다 ~ 4 어둡다")
    serious: int = Field(0, description="1 가볍다 ~ 4 진지하다")
    slow: int = Field(0, description="1 빠르다 ~ 4 느리다")


class Meta(BaseModel):
    title: str = ""
    genre: str = Field("", description="장르 한 줄 표시. genres 를 고르면 그 이름으로 맞춘다")
    genres: list[str] = Field(default_factory=list, description="canon/genres.py 의 장르 id, 목록에 없으면 직접 적은 이름")
    adult: bool = Field(False, description="성인 독자 대상 작품인지")
    logline: str = Field("", description="한두 문장 요약: 누가, 무엇을 원하고, 무엇이 막는가")
    logline_parts: LoglineParts = Field(default_factory=LoglineParts, description="설정 화면의 로그라인 다섯 칸")
    theme: str = Field("", description="이 이야기가 끝까지 묻는 질문 하나")
    tone: str = ""
    tone_dials: ToneDials = Field(default_factory=ToneDials, description="설정 화면에서 고른 톤 다이얼. tone 문장을 만든다")
    target_episodes: int = 16
    words_per_episode: int = Field(5000, description="화당 목표 분량(글자 수, 공백 포함)")
    notes: str = ""

    @model_validator(mode="after")
    def _genres_from_text(self) -> "Meta":
        """genres 가 없던 예전 project.json: 적어 둔 장르를 직접 적은 장르 하나로 본다."""
        if not self.genres and self.genre.strip():
            self.genres = [self.genre.strip()]
        return self


class WorldSetting(BaseModel):
    setting: str = Field("", description="배경 개요")
    era: str = ""
    rules: list[str] = Field(default_factory=list, description="세계관 규칙, 깨지면 안 되는 설정")
    locations: list[str] = Field(default_factory=list)
    name_style: str = Field("", description="이름 스타일 id (korea_modern, joseon, wuxia, western_fantasy, japan, sf). 비우면 장르와 배경으로 짐작")
    name_rules: list[str] = Field(default_factory=list, description="이 세계의 이름 짓는 규칙 (예: 북부 귀족은 성 앞에 '폰')")


class Character(BaseModel):
    id: str = Field(description="영문 소문자 식별자, 예: hero, rival")
    name: str
    role: str = Field(description="주인공 / 조연 / 적대자 등")
    age: str = ""
    gender: str = Field("", description="남 / 여, 정하지 않았으면 빈칸")
    appearance: str = ""
    personality: str = ""
    background: str = ""
    goal: str = Field("", description="작품 전체에서 원하는 것")
    wound: str = Field("", description="결핍, 트라우마, 약점")
    speech_style: str = Field("", description="말투, 어미, 호칭, 자주 쓰는 표현")
    secrets: list[str] = Field(default_factory=list)
    arc: str = Field("", description="시작 상태에서 결말 상태로의 변화")


def _range(lo: float, hi: float) -> dict:
    """LLM 에게 범위를 알리는 JSON 스키마 표시. 검증은 _clamp 가 한다 (예전 project.json 도 읽히게 거부 대신 자른다)."""
    return {"minimum": lo, "maximum": hi}


def _clamp(v, lo, hi):
    return v if v is None else type(v)(min(max(v, lo), hi))


class Relationship(BaseModel):
    """쌍 단위 관계 설정. 방향별 수치는 Tie 에 있고, affinity/tension 은 Tie 에서 계산해 동기화한다."""
    a: str = Field(description="인물 id")
    b: str = Field(description="인물 id")
    type: str = Field(description="연인, 라이벌, 사제, 가족 등")
    description: str = ""
    affinity: int = Field(0, description="-5(적대) ~ 5(깊은 신뢰)", json_schema_extra=_range(-5, 5))
    tension: int = Field(0, description="0(평온) ~ 10(폭발 직전)", json_schema_extra=_range(0, 10))
    goal_conflict: float = Field(0.0, description="두 인물의 목표가 부딪치는 정도 0~1", json_schema_extra=_range(0, 1))
    a_view: list[str] = Field(default_factory=list, description="a 가 b 를 보는 방식, dynamics.VIEWS 의 말 (믿는다, 경계한다 등). 설정 단계 전용")
    b_view: list[str] = Field(default_factory=list, description="b 가 a 를 보는 방식, dynamics.VIEWS 의 말. 설정 단계 전용")

    @model_validator(mode="after")
    def _in_range(self) -> "Relationship":
        # 로컬 모델이 40, 90 같은 백분율이나 음수 충돌도를 내면 관계 역학 계산이 뒤집힌다
        self.affinity = _clamp(self.affinity, -5, 5)
        self.tension = _clamp(self.tension, 0, 10)
        self.goal_conflict = _clamp(self.goal_conflict, 0.0, 1.0)
        return self


# ---------- 관계 역학 (canon/dynamics.py 가 계산) ----------

RelStage = Literal["낯섦", "경계", "호감", "신뢰", "균열", "적대", "화해"]

EventKind = Literal[
    "도움", "희생", "약속이행", "칭찬", "진심고백", "사과", "공동경험",
    "거짓말발각", "배신", "모욕", "위협", "거절", "경쟁승리", "비밀폭로", "수동보정",
]


class Tie(BaseModel):
    """방향 있는 관계: source 가 target 을 어떻게 보는가."""
    source: str
    target: str
    warmth: float = Field(0.0, description="-1(적대) ~ 1(깊은 애정)")
    trust_pos: float = Field(1.0, description="신뢰 베타 분포 α (긍정 증거 + 1)")
    trust_neg: float = Field(1.0, description="신뢰 베타 분포 β (부정 증거 + 1)")
    status: float = Field(0.0, description="source 가 느끼는 자신의 상대적 위치 -1 ~ 1")
    familiarity: float = Field(0.0, description="함께 겪은 정도 0~1")
    grievance: float = Field(0.0, description="풀리지 않은 원한 0~1")
    stage: RelStage = "낯섦"

    @property
    def trust(self) -> float:
        return self.trust_pos / (self.trust_pos + self.trust_neg)

    @property
    def evidence(self) -> float:
        return self.trust_pos + self.trust_neg - 2


class Secret(BaseModel):
    id: str = Field(description="예: sec-doheon-letter")
    owner: str = Field(description="비밀을 가진 인물 id")
    content: str
    hidden_from: list[str] = Field(default_factory=list, description="아직 모르는 인물 id")
    weight: float = Field(0.5, description="이야기에서의 무게 0~1", json_schema_extra=_range(0, 1))

    @model_validator(mode="after")
    def _in_range(self) -> "Secret":
        self.weight = _clamp(self.weight, 0.0, 1.0)
        return self


class StoryEvent(BaseModel):
    """본문에서 일어난 관계 사건. AI 는 사건만 적고, 수치 변화는 dynamics 가 계산한다."""
    episode: int
    actor: str = Field(description="행동한 인물 id")
    target: str = Field(description="행동을 받은 인물 id")
    kind: EventKind
    intensity: int = Field(2, description="1(가벼움) ~ 3(결정적)", json_schema_extra=_range(1, 3))
    witnesses: list[str] = Field(default_factory=list, description="현장에서 본 다른 인물 id")
    reveals_secret: str = Field("", description="이 사건으로 드러난 비밀 id")
    quote: str = Field("", description="근거가 되는 본문 한 문장")
    set_warmth: Optional[float] = Field(None, description="수동보정 전용. AI 는 비워 둔다")
    set_trust: Optional[float] = Field(None, description="수동보정 전용. AI 는 비워 둔다")

    @model_validator(mode="after")
    def _in_range(self) -> "StoryEvent":
        self.intensity = _clamp(self.intensity, 1, 3)
        return self


class ModelParams(BaseModel):
    """관계 역학 계수. 장르별 프리셋은 이 값을 바꾸는 방식으로 넣는다."""
    trust_decay: float = Field(0.85, description="화가 바뀔 때 신뢰 증거가 남는 비율")
    grievance_decay: float = Field(0.95, description="화가 바뀔 때 원한이 남는 비율")
    reciprocity: float = Field(0.1, description="상대의 온기 쪽으로 끌리는 정도")
    witness_factor: float = Field(0.5, description="목격자가 받는 사건 강도 비율")
    familiarity_step: float = Field(0.1, description="같은 화에 등장할 때 친숙도 증가율")
    w_dislike: float = 2.5
    w_asymmetry: float = 1.5
    w_goal: float = 1.5
    w_secret: float = 1.5
    w_grievance: float = 2.0
    w_triad: float = 1.0
    w_distrust: float = 2.0
    tension_bias: float = -2.0


class Snapshot(BaseModel):
    """n화 상태 반영 직후의 상태. revert 와 추세 계산에 쓴다. episode 0 은 1화 시작 전."""
    episode: int
    states: list["CharacterState"] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    ties: list[Tie] = Field(default_factory=list)
    secrets: list[Secret] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    foreshadows: list["Foreshadow"] = Field(default_factory=list)


class Settings(BaseModel):
    show_numbers: bool = Field(False, description="CLI 에서 관계를 숫자로 보여줄지(True), 말로 보여줄지(False)")


# ---------- 스타일 레퍼런스 ----------

class StyleProfile(BaseModel):
    narration_pov: str = Field("", description="서술 시점: 1인칭 주인공, 3인칭 제한 등")
    tense: str = Field("", description="시제: 과거형, 현재형")
    sentence_rhythm: str = Field("", description="문장 길이와 리듬")
    description_density: str = Field("", description="묘사 밀도와 감각 묘사 경향")
    dialogue_ratio: str = Field("", description="대사 대 서술 비율")
    dialogue_style: str = Field("", description="대사 처리 방식: 따옴표, 대사 태그, 대화 템포")
    inner_monologue: str = Field("", description="내면 독백 처리 방식")
    pacing: str = Field("", description="전개 속도, 장면 길이")
    scene_transition: str = Field("", description="장면 전환 방식")
    vocabulary: str = Field("", description="어휘 수준, 한자어/외래어, 비유 경향")
    dos: list[str] = Field(default_factory=list, description="반드시 지킬 문체 규칙")
    donts: list[str] = Field(default_factory=list, description="피해야 할 표현이나 습관")
    banned_phrases: list[str] = Field(default_factory=list, description="본문에 나오면 안 되는 구체적 표현 (문자열 그대로 검사)")
    sample_passages: list[str] = Field(default_factory=list, description="본문 생성 때 그대로 보여줄 대표 문단 2~4개 (원문 발췌)")


class StyleEntry(BaseModel):
    """문체 라이브러리 항목 (canon/library.py). 작품과 따로 저장해 여러 작품에서 다시 쓴다."""
    id: str
    name: str
    source: str = Field("", description="원문 출처: 작가, 작품 등 사용자 메모")
    notes: str = ""
    sample: str = Field("", description="분석에 쓴 원문 전체. 기준 지표와 다시 분석에 쓴다")
    profile: StyleProfile = Field(default_factory=StyleProfile)
    baseline: Optional[StyleMetrics] = Field(None, description="원문 전체로 잰 문체 지표")
    created_at: str = ""
    updated_at: str = ""


# ---------- 계층형 플롯 ----------

class Act(BaseModel):
    name: ActName
    start_ep: int
    end_ep: int
    goal: str = Field(description="이 구간이 끝났을 때 이야기가 도달해야 하는 상태")
    key_turn: str = Field("", description="구간의 핵심 전환점 또는 클라이맥스")


class ArcPlan(BaseModel):
    acts: list[Act]


class EpisodePlot(BaseModel):
    number: int
    act: ActName
    title: str
    summary: str
    events: list[str] = Field(description="순서대로 일어나는 사건 3~6개")
    characters: list[str] = Field(description="등장 인물 id")
    emotional_shift: str = Field(description="주요 인물의 감정 변화가 겉으로 드러나는 행동이나 대사 (감정 이름이 아니라 보이는 것)")
    ending_hook: str = Field(description="다음 화로 이어지는 엔딩 훅")
    foreshadow_plant: list[str] = Field(default_factory=list, description="이번 화에 심는 복선")
    foreshadow_payoff: list[str] = Field(default_factory=list, description="이번 화에 회수하는 복선 id")


class PlotBatch(BaseModel):
    episodes: list[EpisodePlot]


# ---------- 대화형 다듬기 ----------

class PlotRevision(BaseModel):
    """플롯 대화에서 AI 가 내는 답과 변경안. 사용자가 고른 부분만 반영한다 (pipeline.apply_revision)."""
    reply: str = Field(description="작가에게 하는 대답. 무엇을 왜 바꿨는지, 또는 되묻는 말")
    total_episodes: int = Field(0, description="총 화수를 바꿀 때만 새 화수. 바꾸지 않으면 0")
    acts: list[Act] = Field(default_factory=list, description="구조를 바꿀 때만 네 구간 모두. 바꾸지 않으면 빈 목록")
    episodes: list[EpisodePlot] = Field(default_factory=list, description="바뀌는 화만, 모든 칸을 채운 전체 플롯")


ChatTopic = Literal["plot"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    revision: Optional[PlotRevision] = Field(None, description="assistant 가 낸 변경안")
    outcome: Literal["", "applied", "dismissed"] = Field("", description="변경안을 반영했는지, 버렸는지")
    applied: list[str] = Field(default_factory=list, description="반영한 부분: 'acts' 또는 화 번호")
    at: str = ""


class Chat(BaseModel):
    """화면별 대화 기록. 지금은 플롯 화면(topic='plot')만 쓴다."""
    topic: ChatTopic
    messages: list[ChatMessage] = Field(default_factory=list)


# ---------- 검수 ----------

IssueType = Literal["사실", "시간", "인물 정보", "말투", "세계관", "플롯"]


class ConsistencyIssue(BaseModel):
    type: IssueType = Field(description="사실: 확정 사실·세부 모순 / 시간: 순서·인과 / 인물 정보: 모르는 것을 앎 / 말투 / 세계관 규칙 / 플롯: 사건 누락")
    description: str = Field(description="무엇이 어긋났는지 한 문장")
    source_episode: int = Field(0, description="앞선 근거가 나온 화. 설정·확정 사실·인물 상태가 근거면 0")
    source_quote: str = Field(description="앞선 근거 원문 그대로 (설정이면 해당 설정 문장)")
    current_quote: str = Field(description="이번 화에서 어긋난 문장 원문 그대로")
    suggestion: str = Field("", description="고치는 방법 제안")


class ConsistencyReport(BaseModel):
    """본문 검수 결과. 상태를 바꾸지 않는 참고용 경고라 승인 없이 저장한다."""
    episode: int
    issues: list[ConsistencyIssue] = Field(default_factory=list, description="근거가 분명한 모순만. 없으면 빈 목록")


class Episode(BaseModel):
    plot: EpisodePlot
    status: EpisodeStatus = "draft"
    text: str = ""
    summary: str = ""
    issues: list[ConsistencyIssue] = Field(default_factory=list, description="마지막 검수 결과")
    auto: bool = Field(False, description="자동 집필이 사람 검토 없이 반영한 화. 사용자가 다시 반영하면 False")


# ---------- 회차 진행 상태 ----------

class CharacterState(BaseModel):
    character_id: str
    emotional_state: str = ""
    current_goal: str = ""
    location: str = ""
    knows: list[str] = Field(default_factory=list, description="이 인물이 알게 된 핵심 정보")
    notes: str = ""


class Foreshadow(BaseModel):
    id: str = Field(description="예: fs-03-locket")
    description: str
    planted_ep: int
    payoff_ep: Optional[int] = None
    status: Literal["open", "resolved"] = "open"


class StateDelta(BaseModel):
    """한 화를 쓴 뒤 AI 가 제안하는 상태 변경안. 사용자가 승인하면 반영된다."""
    episode: int
    summary: str = Field(description="이번 화 요약 (다음 화 생성용, 5~8문장)")
    character_updates: list[CharacterState] = Field(default_factory=list, description="변화가 있는 인물만")
    events: list[StoryEvent] = Field(default_factory=list, description="인물 사이에 일어난 관계 사건, 일어난 순서대로")
    relationship_updates: list[Relationship] = Field(default_factory=list, description="관계 유형이나 설명이 바뀐 쌍만. 수치는 사건으로 계산하므로 events 가 있으면 무시")
    secrets_added: list[Secret] = Field(default_factory=list, description="이번 화에 새로 생긴 비밀")
    new_facts: list[str] = Field(default_factory=list, description="본문에서 새로 확정된 사실 (이름, 장소, 과거사 등)")
    foreshadow_planted: list[Foreshadow] = Field(default_factory=list)
    foreshadow_resolved: list[str] = Field(default_factory=list, description="회수된 복선 id")
    warnings: list[str] = Field(default_factory=list, description="플롯, 설정, 말투와 어긋난 부분")


class NameOption(BaseModel):
    name: str
    reason: str = Field("", description="이 인물이나 장소에 맞는 이유 한 줄")


class NameOptions(BaseModel):
    """이름·지명 AI 추천. 코드가 뽑은 후보에서 고르거나 같은 결로 새로 짓는다 (naming.py)."""
    options: list[NameOption]


# ---------- 인과율: 언제든 더하는 이야기 요소와 그 영향 ----------

ElementKind = Literal["세계 규칙", "장소", "물건", "세력", "인물 특징", "과거 사건", "예정 사건", "기타"]


class ImpactConflict(BaseModel):
    target: Literal["본문", "플롯", "설정", "확정 사실"] = Field(description="새 요소와 부딪치는 것이 있는 곳")
    episode: int = Field(0, description="본문이나 플롯이면 그 화 번호, 설정이나 확정 사실이면 0")
    quote: str = Field(description="부딪치는 기존 내용을 원문 그대로 (본문이면 본문 문장, 플롯이면 플롯 문구)")
    problem: str = Field(description="무엇이 어긋나는지 한 문장")
    fix: Literal["본문 수정", "플롯 수정", "설명 추가", "시점 변경", "그대로 둠"] = Field(
        description="권하는 처리: 본문 수정(patches), 플롯 수정(episodes), 설명 추가(new_facts), 시점 변경(요소의 since_ep 를 늦춤), 그대로 둠")


class TextPatch(BaseModel):
    episode: int = Field(description="본문이 있는 화 번호")
    quote: str = Field(description="바꿀 본문 문장을 원문 그대로 (한두 문장)")
    replacement: str = Field(description="새 요소와 맞게 최소로 고친 문장")
    reason: str = Field("", description="왜 바꾸는지 한 문장")


class ImpactReport(BaseModel):
    """요소 하나를 더하거나 바꿨을 때 AI 가 내는 영향 보고서. 작가가 고른 부분만 반영한다 (pipeline.apply_impact)."""
    summary: str = Field(description="작가에게 하는 설명 2~5문장: 어느 화와 플롯이 어떻게 흔들리고 무엇을 권하는지")
    conflicts: list[ImpactConflict] = Field(default_factory=list, description="근거를 인용할 수 있는 모순과 어긋남만")
    episodes: list[EpisodePlot] = Field(default_factory=list, description="바뀌는 화의 전체 플롯. 본문이 없는 화만")
    patches: list[TextPatch] = Field(default_factory=list, description="이미 쓴 화의 최소 본문 수정안")
    new_facts: list[str] = Field(default_factory=list, description="모순을 설명으로 덮을 때 더할 확정 사실")


class ElementImpact(BaseModel):
    """요소에 붙여 두는 마지막 영향 분석. 반영 결과와, 분석할 때의 요소 내용(basis)을 함께 남긴다."""
    report: ImpactReport
    basis: str = Field("", description="분석한 요소 내용의 지문. 요소를 고치면 달라져 다시 분석하라고 알린다")
    at: str = ""
    outcome: Literal["", "applied", "dismissed"] = ""
    applied: list[str] = Field(default_factory=list, description="반영한 부분: 'ep:3', 'patch:0', 'fact:1'")


class StoryElement(BaseModel):
    """작가가 언제든 더하는 요소, 특징, 설정, 사건 (인과율 화면). 작가 입력이라 바로 저장한다."""
    id: str
    kind: ElementKind = "기타"
    name: str = ""
    aliases: list[str] = Field(default_factory=list, description="본문과 플롯에서 언급을 찾을 다른 이름")
    description: str = ""
    characters: list[str] = Field(default_factory=list, description="관련 인물 id")
    since_ep: int = Field(0, description="0 이면 처음부터 사실, n 이면 n화부터 생긴다")
    episodes: list[int] = Field(default_factory=list, description="일어나거나 꼭 나와야 하는 화 (예정 사건 등)")
    reveal_ep: int = Field(0, description="독자에게 드러나는 화. 0 이면 숨기지 않는다")
    context: Literal["auto", "always", "off"] = Field("auto", description="본문 프롬프트에 넣기: 관련 있을 때, 항상, 넣지 않음")
    created_at: str = ""
    added_after: int = Field(0, description="더할 때 본문이 있던 마지막 화. 0 이면 연재 전에 더함")
    impact: Optional[ElementImpact] = None


class SetupSuggestion(BaseModel):
    """설정 도우미: 사용자가 채운 기본 정보를 바탕으로 빈칸을 제안."""
    theme: str
    tone: str
    world: WorldSetting
    characters: list[Character]
    relationships: list[Relationship]


# ---------- 전체 프로젝트 ----------

class Project(BaseModel):
    meta: Meta = Field(default_factory=Meta)
    world: WorldSetting = Field(default_factory=WorldSetting)
    characters: list[Character] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    style: StyleProfile = Field(default_factory=StyleProfile)
    style_baseline: Optional[StyleMetrics] = Field(None, description="레퍼런스 원문 전체로 잰 문체 지표 (style 명령 때 저장)")
    style_id: str = Field("", description="문체 라이브러리에서 가져온 항목 id. 비어 있으면 이 작품에서 직접 만든 문체")
    arc: list[Act] = Field(default_factory=list)
    episodes: list[Episode] = Field(default_factory=list)
    states: list[CharacterState] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    foreshadows: list[Foreshadow] = Field(default_factory=list)
    history: list[StateDelta] = Field(default_factory=list, description="승인된 상태 변경 기록")
    ties: list[Tie] = Field(default_factory=list, description="방향 관계 (dynamics 가 계산)")
    secrets: list[Secret] = Field(default_factory=list)
    events: list[StoryEvent] = Field(default_factory=list, description="승인된 사건 로그")
    params: ModelParams = Field(default_factory=ModelParams)
    snapshots: list[Snapshot] = Field(default_factory=list)
    settings: Settings = Field(default_factory=Settings)
    chats: list[Chat] = Field(default_factory=list, description="화면별 AI 대화 기록")
    elements: list[StoryElement] = Field(default_factory=list, description="인과율: 언제든 더하는 요소, 특징, 설정, 사건")

    def episode(self, n: int) -> Episode:
        for ep in self.episodes:
            if ep.plot.number == n:
                return ep
        raise KeyError(f"{n}화 플롯이 없습니다")

    def act_for(self, n: int) -> Optional[Act]:
        return next((a for a in self.arc if a.start_ep <= n <= a.end_ep), None)

    def state_of(self, cid: str) -> Optional[CharacterState]:
        return next((s for s in self.states if s.character_id == cid), None)

    def snapshot(self, n: int) -> Optional[Snapshot]:
        return next((s for s in self.snapshots if s.episode == n), None)

    def chat(self, topic: str) -> Chat:
        c = next((c for c in self.chats if c.topic == topic), None)
        if c is None:
            c = Chat(topic=topic)  # type: ignore[arg-type]
            self.chats.append(c)
        return c


Snapshot.model_rebuild()
