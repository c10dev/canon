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
    a: str = Field(description="인물 id")
    b: str = Field(description="인물 id")
    type: str = Field(description="연인, 라이벌, 사제, 가족 등")
    description: str = ""
    affinity: int = Field(0, description="-5(적대) ~ 5(깊은 신뢰)")
    tension: int = Field(0, description="0(평온) ~ 10(폭발 직전)")


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
    relationship_updates: list[Relationship] = Field(default_factory=list, description="변화가 있는 관계만, 변경 후 값")
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

    def episode(self, n: int) -> Episode:
        for ep in self.episodes:
            if ep.plot.number == n:
                return ep
        raise KeyError(f"{n}화 플롯이 없습니다")

    def act_for(self, n: int) -> Optional[Act]:
        return next((a for a in self.arc if a.start_ep <= n <= a.end_ep), None)

    def state_of(self, cid: str) -> Optional[CharacterState]:
        return next((s for s in self.states if s.character_id == cid), None)
