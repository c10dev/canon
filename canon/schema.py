"""소설 프로젝트 데이터 스키마.

모든 상태는 하나의 Project 객체(project.json)에 저장된다.
LLM 이 직접 채우는 모델(SetupSuggestion, StyleProfile, ArcPlan, PlotBatch, StateDelta)은
Gemini 구조화 출력에 그대로 넘기므로 dict 타입 필드를 쓰지 않는다.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ActName = Literal["기", "승", "전", "결"]
EpisodeStatus = Literal["draft", "confirmed", "written", "finalized"]


# ---------- 기본 설정 ----------

class Meta(BaseModel):
    title: str = ""
    genre: str = ""
    logline: str = Field("", description="한두 문장 요약: 누가, 무엇을 원하고, 무엇이 막는가")
    theme: str = ""
    tone: str = ""
    target_episodes: int = 16
    words_per_episode: int = Field(5000, description="화당 목표 분량(글자 수, 공백 포함)")
    notes: str = ""


class WorldSetting(BaseModel):
    setting: str = Field("", description="배경 개요")
    era: str = ""
    rules: list[str] = Field(default_factory=list, description="세계관 규칙, 깨지면 안 되는 설정")
    locations: list[str] = Field(default_factory=list)


class Character(BaseModel):
    id: str = Field(description="영문 소문자 식별자, 예: hero, rival")
    name: str
    role: str = Field(description="주인공 / 조연 / 적대자 등")
    age: str = ""
    appearance: str = ""
    personality: str = ""
    background: str = ""
    goal: str = Field("", description="작품 전체에서 원하는 것")
    wound: str = Field("", description="결핍, 트라우마, 약점")
    speech_style: str = Field("", description="말투, 어미, 호칭, 자주 쓰는 표현")
    secrets: list[str] = Field(default_factory=list)
    arc: str = Field("", description="시작 상태에서 결말 상태로의 변화")


class Relationship(BaseModel):
    """쌍 단위 관계 설정. 방향별 수치는 Tie 에 있고, affinity/tension 은 Tie 에서 계산해 동기화한다."""
    a: str = Field(description="인물 id")
    b: str = Field(description="인물 id")
    type: str = Field(description="연인, 라이벌, 사제, 가족 등")
    description: str = ""
    affinity: int = Field(0, description="-5(적대) ~ 5(깊은 신뢰)")
    tension: int = Field(0, description="0(평온) ~ 10(폭발 직전)")
    goal_conflict: float = Field(0.0, description="두 인물의 목표가 부딪치는 정도 0~1")


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
    weight: float = Field(0.5, description="이야기에서의 무게 0~1")


class StoryEvent(BaseModel):
    """본문에서 일어난 관계 사건. AI 는 사건만 적고, 수치 변화는 dynamics 가 계산한다."""
    episode: int
    actor: str = Field(description="행동한 인물 id")
    target: str = Field(description="행동을 받은 인물 id")
    kind: EventKind
    intensity: int = Field(2, description="1(가벼움) ~ 3(결정적)")
    witnesses: list[str] = Field(default_factory=list, description="현장에서 본 다른 인물 id")
    reveals_secret: str = Field("", description="이 사건으로 드러난 비밀 id")
    quote: str = Field("", description="근거가 되는 본문 한 문장")
    set_warmth: Optional[float] = Field(None, description="수동보정 전용. AI 는 비워 둔다")
    set_trust: Optional[float] = Field(None, description="수동보정 전용. AI 는 비워 둔다")


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
    sample_passages: list[str] = Field(default_factory=list, description="본문 생성 때 그대로 보여줄 대표 문단 2~4개 (원문 발췌)")


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
    emotional_shift: str = Field(description="주요 인물의 감정 변화")
    ending_hook: str = Field(description="다음 화로 이어지는 엔딩 훅")
    foreshadow_plant: list[str] = Field(default_factory=list, description="이번 화에 심는 복선")
    foreshadow_payoff: list[str] = Field(default_factory=list, description="이번 화에 회수하는 복선 id")


class PlotBatch(BaseModel):
    episodes: list[EpisodePlot]


class Episode(BaseModel):
    plot: EpisodePlot
    status: EpisodeStatus = "draft"
    text: str = ""
    summary: str = ""


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


Snapshot.model_rebuild()
