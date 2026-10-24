"""소설 프로젝트 데이터 스키마.

모든 상태는 하나의 Project 객체(project.json)에 저장된다.
LLM 이 직접 채우는 모델(SetupSuggestion, StyleProfile, ArcPlan, PlotBatch, PlotRevision, NameOptions, StateDelta, ConsistencyReport,
ImpactReport, SeriesPlan, ArcProposal, Recap, StorylineProposal, SerialConversion,
PassageRevision, SerialRebuild, Rework, HookReport, OpeningPlots, IllustDraft, LookSuggestion)은
Gemini 구조화 출력에 그대로 넘기므로 dict 타입 필드를 쓰지 않는다.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .metrics import StyleMetrics

ActName = Literal["기", "승", "전", "결"]
EpisodeStatus = Literal["draft", "confirmed", "written", "finalized"]
Form = Literal["short", "serial"]


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
    form: Form = Field("short", description="short: 작품 전체를 기승전결 하나로 / serial: 부 → 아크 → 화로 나눠 아크씩 굴러가며 기획하는 장편 연재")
    arc_length: int = Field(0, description="장편: 아크 하나의 기본 화수. 0 이면 AI 가 내용에 맞게 정한다")
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
    narration_voice: str = Field("", description="이 인물이 시점 인물인 화의 서술 말투 (서술 어미, 내면 독백 버릇, 자주 쓰는 표현, 예시 문장). "
                                 "작가가 정하거나 서술 말투 제안으로만 채우고, 다른 제안에서는 비워 둔다")
    secrets: list[str] = Field(default_factory=list)
    arc: str = Field("", description="시작 상태에서 결말 상태로의 변화")
    tier: Literal["main", "support", "minor"] = Field(
        "main", description="main 주역(매 화 설정 전체를 넣음) / support 조연 / minor 단역 (나오는 화에만 넣음)")
    first_ep: int = Field(0, description="처음 나온 화. 설정 단계 인물은 0")


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

class StyleMarker(BaseModel):
    text: str = Field(description="원문에 되풀이해 나오는 어미, 조사, 말버릇을 원문에 적힌 그대로 (예: '것이었다', '하더라'). 원문에서 글자 그대로 찾을 수 있어야 한다")
    note: str = Field("", description="어디에 어떻게 쓰는지 한 줄")
    per_1k: float = Field(0, description="원문 1,000자당 횟수. Canon 이 원문에서 세어 덮어쓴다")


class StyleDevice(BaseModel):
    """특정 상황에만, 가끔 쓰는 장면 장치 (예: 자문자답으로 꼬리를 무는 망상). 프로그램이 최근 화에서 쓴 화를 세어 이번 화 지시를 바꾼다."""
    name: str = Field(description="장치 이름 (예: 자문자답 망상)")
    when: str = Field("", description="쓰는 상황 (예: 상대의 작은 반응에 혼자 설렐 때)")
    cues: list[str] = Field(default_factory=list, description="이 장치를 알아보는 글자를 원문에 적힌 그대로 1~3개 (예: '다는 건', '거지?'). 한 화에 합쳐 두 번 이상 나오면 쓴 화로 본다")
    every: int = Field(0, description="최소 간격(화). 3 이면 3화에 한 번까지. 0 은 간격 없이 상황이 올 때만")
    example: str = Field("", description="짧은 원문 예시. 써도 되는 화에만 보여 준다")


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
    markers: list[StyleMarker] = Field(default_factory=list, description="이 문체를 알아보게 하는 표지 5~10개와 원문 빈도. 빈도 안팎으로 쓰고 몰아 쓰지 않는다")
    devices: list[StyleDevice] = Field(default_factory=list, description="특정 상황에만 가끔 쓰는 장면 장치 0~3개. 매 화 쓰면 버릇이 되는 것")
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
    version: int = Field(0, description="지금 버전 번호. 0 은 버전 기록이 생기기 전 항목")
    versions: list["StyleVersion"] = Field(default_factory=list, description="프로필 · 기준 지표가 바뀔 때마다 남긴 버전 (최근 것만)")


class StyleVersion(BaseModel):
    """문체 라이브러리 항목의 한 버전. 원문은 넣지 않는다 (되돌리기는 프로필과 기준 지표만)."""
    number: int
    at: str = ""
    note: str = Field("", description="무엇을 바꿨는지 한 줄")
    profile: StyleProfile = Field(default_factory=StyleProfile)
    baseline: Optional[StyleMetrics] = None


# ---------- 내 수정에서 배우기 ----------
# 작가가 본문을 고친 기록(TextEdit)에서 되풀이되는 고침을 찾아 문체 규칙 후보로 낸다. 고른 것만 작품 문체에 넣는다.

StyleRuleKind = Literal["do", "dont", "banned", "marker", "device"]


class EditPair(BaseModel):
    """규칙 후보의 근거가 된 수정 하나 (프로그램이 채운다)."""
    ref: str = Field(description="'화:수정 id' 예: '3:e5'")
    before: str = ""
    after: str = ""


class StyleRuleSuggestion(BaseModel):
    kind: StyleRuleKind = Field(description="do: 지킬 것 / dont: 피할 것 / banned: 금지 표현(글자 그대로) / marker: 문체 표지(어미 · 말버릇, 글자 그대로) / device: 가끔만 쓸 장면 장치")
    text: str = Field(description="규칙 한 문장. banned · marker 는 본문에 적힌 글자 그대로, device 는 장치 이름")
    note: str = Field("", description="marker: 어디에 어떻게 쓰는지 한 줄 / device: 써도 되는 상황. 다른 종류는 빈칸")
    cues: list[str] = Field(default_factory=list, description="device 일 때만: 장치를 알아보는 글자를 고치기 전 글에 적힌 그대로 1~3개")
    every: int = Field(0, description="device 일 때만: 몇 화에 한 번까지 (예: 5)")
    replaces: str = Field("", description="이 후보와 부딪혀 바꿔야 할 기존 규칙을 지금 프로필에 적힌 그대로. 새로 더하는 것이면 빈칸")
    reason: str = Field("", description="작가가 어떻게 고쳤는지 한두 문장")
    evidence: list[str] = Field(default_factory=list, description="근거가 된 수정의 [화:id] 를 적힌 그대로 (예: '3:e5'). 두 개 이상")
    pairs: list[EditPair] = Field(default_factory=list, description="프로그램이 채운다. 빈 목록으로 둔다")
    applied: bool = Field(False, description="프로그램이 채운다. false 로 둔다")


class StyleLearning(BaseModel):
    summary: str = Field("", description="작가가 AI 문장을 고치는 경향을 두세 문장으로")
    suggestions: list[StyleRuleSuggestion] = Field(default_factory=list, description="규칙 후보, 많아야 8개. 근거가 두 번 이상인 것만")
    edits_used: int = Field(0, description="프로그램이 채운다. 0 으로 둔다")
    at: str = Field("", description="프로그램이 채운다. 빈칸으로 둔다")


# ---------- 계층형 플롯 ----------

class Act(BaseModel):
    name: ActName
    start_ep: int
    end_ep: int
    goal: str = Field(description="이 구간이 끝났을 때 이야기가 도달해야 하는 상태")
    key_turn: str = Field("", description="구간의 핵심 전환점 또는 클라이맥스")
    pov: str = Field("", description="이 구간의 서술 시점 운용 한 줄 (예: 도현 1인칭, 서윤 3인칭 제한). 작품 기본 시점 그대로면 비움")


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
    storyline: str = Field("", description="이 화가 주로 따라가는 이야기 줄기 id. 메인 줄기 화면 비움")
    threads: list[str] = Field(default_factory=list, description="이 화 안에 장면으로 끼어드는 다른 이야기 줄기 id")
    opening: str = Field("", description="이 화를 여는 첫 장면 한 줄. 1~3화는 꼭 적는다")
    reader_question: str = Field("", description="이 화를 읽은 독자가 다음 화로 들고 갈 질문 하나. 1~3화는 꼭 적는다")
    pov: str = Field("", description="이 화의 시점 인물 id. 작품 기본 시점 그대로면 비움")
    pov_mode: str = Field("", description="이 화의 서술 방식 (1인칭, 3인칭 제한, 3인칭 전지). 작품 기본과 같으면 비움")


NEW_CAST_DESC = ("인물 목록에 없는 새 인물이 이 플롯에 꼭 필요할 때만, 전체 설정(speech_style 포함)과 함께. "
                 "그 화의 characters 에 이 id 를 넣는다. 이미 있는 인물은 넣지 않는다. 조연은 support, 지나가는 인물은 minor")


class PlotBatch(BaseModel):
    episodes: list[EpisodePlot]
    new_characters: list[Character] = Field(default_factory=list, description=NEW_CAST_DESC)


class OpeningOption(BaseModel):
    approach: str = Field(description="여는 방식 id (요청에 적힌 것 그대로)")
    pitch: str = Field(description="이 안이 독자를 붙잡는 방법 한두 문장")
    plot: EpisodePlot


class OpeningPlots(BaseModel):
    """1~3화 플롯을 여는 방식만 달리해 여러 안으로 낸 것. 작가가 하나를 골라 반영한다."""
    options: list[OpeningOption]


# ---------- 장편 연재: 작품 → 부 → 아크 → 화 ----------

class Part(BaseModel):
    """부(권, 시즌). 무대와 판이 바뀌는 큰 단위. 장편(form='serial')에서만 쓴다."""
    number: int
    title: str
    start_ep: int
    end_ep: int
    goal: str = Field(description="이 부가 끝날 때 이야기가 도달해야 하는 상태")
    key_turn: str = Field("", description="부를 마무리하는 큰 사건이나 드러나는 비밀")
    arc_ideas: list[str] = Field(default_factory=list, description="이 부에서 다룰 아크 후보를 순서대로 한 줄씩. 다음 아크를 기획할 때 참고")
    summary: str = Field("", description="부가 끝난 뒤의 요약. 작가가 승인한 것만 넣는다")


class SeriesPlan(BaseModel):
    """부 구성 제안."""
    parts: list[Part]


class StoryArc(BaseModel):
    """아크: 화 5~30개로 된 작은 이야기. 하나의 문제를 열고 해결하며, 자체 기승전결과 클라이맥스 보상을 가진다."""
    number: int
    title: str
    start_ep: int
    end_ep: int
    goal: str = Field(description="아크가 끝날 때 바뀌어 있어야 하는 것")
    conflict: str = Field("", description="이번 아크에서 주인공을 막는 문제나 상대")
    payoff: str = Field("", description="아크 클라이맥스에서 독자가 받는 보상(사이다)")
    acts: list[Act] = Field(default_factory=list, description="아크 안의 기승전결. start_ep 부터 end_ep 까지 빈틈없이")
    cast: list[str] = Field(default_factory=list, description="이 아크에 주로 나오는 인물 id")
    payoffs: list[str] = Field(default_factory=list, description="이 아크에서 회수할 열린 복선 id")
    pov: str = Field("", description="이 아크의 서술 시점 운용 한 줄 (예: 여주 서윤 1인칭으로 바뀜). 작품 기본 시점 그대로면 비움")
    summary: str = Field("", description="아크가 끝난 뒤의 요약. 작가가 승인한 것만 넣는다")


class ArcProposal(BaseModel):
    """다음 아크 제안. 작가가 고쳐서 반영한다 (pipeline.apply_arc)."""
    arc: StoryArc
    new_characters: list[Character] = Field(default_factory=list, description="이 아크에서 새로 등장하는 인물. 기존 인물은 넣지 않는다")
    reply: str = Field("", description="작가에게 하는 설명: 왜 이 아크인지, 어떤 복선을 회수하고 무엇을 남기는지 2~4문장")


StorylineKind = Literal["서브플롯", "과거 회상", "외전", "인물 이야기"]


class Storyline(BaseModel):
    """메인 줄기에서 갈라졌다 합류하는 이야기 줄기. 메인 줄기는 따로 두지 않는다 (화의 storyline 이 비어 있으면 메인)."""
    id: str = Field(description="sl-01 처럼 짧은 id")
    kind: StorylineKind = "서브플롯"
    title: str = ""
    focus: list[str] = Field(default_factory=list, description="중심 인물 id")
    when: str = Field("", description="이야기 속 시점. 메인과 같은 시간이면 비움 (예: 10년 전, 본편 3년 뒤)")
    goal: str = Field("", description="이 줄기가 풀어 가는 질문이나 목표")
    branch_ep: int = Field(0, description="메인에서 갈라지는 화: 이 줄기를 부르는 계기가 나오는 화. 0 이면 정하지 않음")
    join_ep: int = Field(0, description="메인에 다시 합류하는 화. 0 이면 아직 열려 있음")
    rejoin: str = Field("", description="합류할 때 메인에 남기는 것 (드러나는 비밀, 바뀐 관계, 얻거나 잃는 것)")
    summary: str = Field("", description="작가가 정리한 줄기 요약. 비면 화별 요약을 쓴다")


class StorylineProposal(BaseModel):
    """AI 가 제안하는 이야기 줄기 하나와 그 줄기가 들어갈 화."""
    storyline: Storyline
    episodes: list[int] = Field(default_factory=list, description="이 줄기를 주로 따라갈 화 번호. 이미 플롯이 있는 화 중에서")
    threads: list[int] = Field(default_factory=list, description="메인 화 안에 이 줄기 장면을 끼워 넣을 화 번호")
    reply: str = Field("", description="작가에게 하는 설명: 왜 이 줄기인지, 어디서 갈라져 어디서 합류하는지 2~4문장")


class Recap(BaseModel):
    """아크나 부가 끝난 뒤의 요약 제안."""
    summary: str = Field(description="다음 화를 쓸 때 참고할 요약")


# ---------- 단편 → 장편 전환 ----------

class ScopeChange(BaseModel):
    id: str = Field(description="이미 열려 있는 복선 id")
    scope: Literal["arc", "part", "series"] = Field(description="장편에서의 회수 범위")
    reason: str = Field("", description="왜 더 멀리(또는 가까이) 끌고 가는지 한 줄")


class TierChange(BaseModel):
    id: str = Field(description="인물 id")
    tier: Literal["main", "support", "minor"] = Field(description="main 작품 전체를 끄는 주역 / support 조연 / minor 단역")
    reason: str = Field("", description="한 줄 이유")


class SerialConversion(BaseModel):
    """단편을 장편 연재로 바꾸는 제안. 단편 전체는 아크 1이 된다. 작가가 고른 부분만 반영한다 (pipeline.apply_conversion)."""
    reply: str = Field(description="작가에게 하는 설명 3~5문장: 결말을 어떻게 처리했는지, 장편 전체를 끄는 갈등, 1부가 어디서 끝나는지")
    ending: Literal["keep", "reopen"] = Field(
        description="keep: 단편 결말을 아크 1의 결말로 닫고 그 뒤에 새 문제를 연다 / reopen: 결말이 진짜 끝이 아니었다는 장치로 큰 갈등을 다시 연다")
    total_episodes: int = Field(description="장편 총 화수")
    arc: StoryArc = Field(description="아크 1: 단편 전체. acts 는 비워 두면 단편 기승전결을 그대로 쓴다")
    parts: list[Part] = Field(default_factory=list, description="1화부터 총 화수까지의 부 구성. 1부가 아크 1을 품는다")
    foreshadows: list[Foreshadow] = Field(default_factory=list, description="장편을 끌고 갈 새 장기 떡밥 (scope part 나 series)")
    scopes: list[ScopeChange] = Field(default_factory=list, description="기존 열린 복선 중 회수 범위를 바꿀 것")
    facts: list[str] = Field(default_factory=list, description="결말을 다시 열 때 이미 쓴 본문과 맞게 더할 확정 사실")
    episodes: list[EpisodePlot] = Field(default_factory=list, description="본문이 없는 단편 화의 바뀐 전체 플롯 (결말을 열어 둘 때)")
    tiers: list[TierChange] = Field(default_factory=list, description="인물 비중 조정. 바꾸는 인물만")


class Conversion(BaseModel):
    """단편에서 장편으로 바꾼 기록. 되돌릴 백업은 projects/<이름>/before-serial.json 에 따로 둔다 (store.save_backup)."""
    at: str = ""
    from_total: int = Field(0, description="전환 전 총 화수")
    arc_end: int = Field(0, description="아크 1이 된 단편의 마지막 화. 구조가 없던 작품이면 0")
    ending: str = Field("", description="keep 또는 reopen")
    history: int = Field(0, description="전환할 때까지 반영된 화 수. 이보다 늘면 되돌리지 않는다")
    mode: Literal["continue", "rebuild"] = Field("continue", description="continue: 단편을 아크 1로 이어 쓰기 / rebuild: 단편을 씨앗으로 다시 짜기")


# ---------- 단편 → 장편 재구성 ----------

RebuildUse = Literal["keep", "revise", "rewrite", "new"]


class RebuildEpisode(BaseModel):
    """재구성 지도의 한 줄: 새 화 하나와 그 화에 쓰는 옛 단편 화."""
    number: int = Field(description="새 화 번호")
    title: str
    summary: str = Field(description="이 화에서 일어나는 일 2~3문장")
    sources: list[int] = Field(default_factory=list, description="이 화에 쓰는 옛 단편 화 번호. 새로 만드는 화면 빈 목록")
    use: RebuildUse = Field(description="keep: 옛 화 본문 그대로 / revise: 옛 화 본문을 조금 고침 / rewrite: 옛 화를 재료로 새로 씀 / new: 새 화")
    note: str = Field("", description="revise 는 무엇을 고칠지, rewrite 는 옛 화에서 무엇을 살릴지 한두 문장")


class SerialRebuild(BaseModel):
    """단편을 씨앗으로 장편 앞부분을 다시 짠 제안. 작가가 고친 뒤 반영한다 (pipeline.apply_rebuild)."""
    reply: str = Field(description="작가에게 하는 설명 3~5문장: 단편을 어떻게 늘렸는지, 결말을 어디로 옮겼는지, 1~3화 훅")
    total_episodes: int = Field(description="장편 총 화수")
    ending_at: Literal["arc", "part", "series"] = Field(description="단편 결말이 가는 곳: arc 첫 아크 끝 / part 1부 끝 / series 작품 끝")
    parts: list[Part] = Field(default_factory=list, description="1화부터 총 화수까지의 부 구성")
    arcs: list[StoryArc] = Field(description="1화부터 이어지는 앞 아크들. 옛 단편 화를 모두 담는다. 아크마다 acts 를 채운다")
    episodes: list[RebuildEpisode] = Field(description="1화부터 마지막 아크 끝까지 빠짐없이")
    dropped: list[int] = Field(default_factory=list, description="쓰지 않는 옛 단편 화 번호")
    foreshadows: list["Foreshadow"] = Field(default_factory=list, description="새 장기 떡밥. planted_ep 는 새 화 번호")
    tiers: list[TierChange] = Field(default_factory=list, description="인물 비중 조정. 바꾸는 인물만")


class Rework(BaseModel):
    """재구성에서 '다듬기'로 고른 화를 AI 가 고친 본문. 작가가 비교해 보고 받아들인다."""
    text: str = Field(description="고친 본문 전체")
    reply: str = Field("", description="무엇을 고쳤는지 2~3문장")


class ShortArchive(BaseModel):
    """재구성 전 단편. 새로 쓰는 화의 원고 재료와, 그대로 둔 화의 옛 상태 변경안 재사용에 쓴다."""
    episodes: list["Episode"] = Field(default_factory=list)
    arc: list[Act] = Field(default_factory=list)
    history: list["StateDelta"] = Field(default_factory=list)
    map: list[RebuildEpisode] = Field(default_factory=list, description="새 화 → 옛 화 지도")
    dropped: list[int] = Field(default_factory=list)

    def entry(self, n: int) -> Optional[RebuildEpisode]:
        return next((x for x in self.map if x.number == n), None)

    def source(self, old: int) -> Optional["Episode"]:
        return next((e for e in self.episodes if e.plot.number == old), None)


# ---------- 대화형 다듬기 ----------

class PlotRevision(BaseModel):
    """플롯 대화에서 AI 가 내는 답과 변경안. 사용자가 고른 부분만 반영한다 (pipeline.apply_revision)."""
    reply: str = Field(description="작가에게 하는 대답. 무엇을 왜 바꿨는지, 또는 되묻는 말")
    total_episodes: int = Field(0, description="총 화수를 바꿀 때만 새 화수. 바꾸지 않으면 0")
    acts: list[Act] = Field(default_factory=list, description="구조를 바꿀 때만 네 구간 모두. 바꾸지 않으면 빈 목록")
    episodes: list[EpisodePlot] = Field(default_factory=list, description="바뀌는 화만, 모든 칸을 채운 전체 플롯")
    new_characters: list[Character] = Field(default_factory=list, description=NEW_CAST_DESC)


class PassageCandidate(BaseModel):
    text: str = Field(description="고칠 부분을 대신할 새 글. 앞뒤 본문은 되풀이하지 않는다")
    note: str = Field("", description="무엇을 어떻게 바꿨는지 한 줄")


class PassageRevision(BaseModel):
    """본문 부분 수정: 작가가 고른 부분을 AI 가 다시 쓴 후보. 작가가 하나를 골라야 본문에 들어간다 (pipeline.apply_passage)."""
    reply: str = Field(description="작가에게 하는 짧은 답 1~3문장. 후보들이 어떻게 다른지")
    candidates: list[PassageCandidate] = Field(default_factory=list, description="2~3개, 서로 다른 방향으로 고친 후보")


class Selection(BaseModel):
    """본문에서 고른 부분. start 는 본문 안 글자 위치, text 는 고를 때의 원문 (위치가 밀려도 원문으로 다시 찾는다)."""
    start: int = 0
    text: str


# 'plot'(기승전결 · 플롯 화면) 또는 'text:<화>'(집필 화면의 본문 부분 수정). web._chat 이 검사한다
ChatTopic = str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    revision: Optional[PlotRevision] = Field(None, description="assistant 가 낸 플롯 변경안")
    passage: Optional[PassageRevision] = Field(None, description="assistant 가 낸 본문 부분 수정 후보")
    selection: Optional[Selection] = Field(None, description="본문 부분 수정: 고친 대상")
    preset: str = Field("", description="본문 부분 수정: 고른 빠른 요청 (prompts.PASSAGE_PRESETS)")
    outcome: Literal["", "applied", "dismissed"] = Field("", description="변경안을 반영했는지, 버렸는지")
    applied: list[str] = Field(default_factory=list, description="반영한 부분: 'acts' 또는 화 번호, 본문 수정이면 후보 번호(0부터)")
    at: str = ""


class Chat(BaseModel):
    """화면별 대화 기록. 플롯 화면은 'plot', 본문 부분 수정은 화마다 'text:<화>'."""
    topic: ChatTopic
    messages: list[ChatMessage] = Field(default_factory=list)


# ---------- 검수 ----------

IssueType = Literal["사실", "시간", "인물 정보", "말투", "세계관", "플롯", "동선", "시점"]


class ConsistencyIssue(BaseModel):
    type: IssueType = Field(description="사실: 확정 사실·세부 모순 / 시간: 순서·인과 / 인물 정보: 모르는 것을 앎 / 말투 / 세계관 규칙 / 플롯: 사건 누락 / 동선: 한 장면 안에서 위치·몸이 향한 쪽·자세·손에 든 것·가려진 곳이 행동 없이 바뀜 / 시점: 시점 인물이 볼 수 없거나 모르는 것을 서술, 1인칭의 나가 다른 인물로 바뀜, 표시 없이 시점 인물이 바뀜")
    description: str = Field(description="무엇이 어긋났는지 한 문장")
    source_episode: int = Field(0, description="앞선 근거가 나온 화. 설정·확정 사실·인물 상태가 근거면 0, 같은 화 앞 문장이면 이번 화")
    source_quote: str = Field(description="앞선 근거 원문 그대로 (설정이면 해당 설정 문장)")
    current_quote: str = Field(description="이번 화에서 어긋난 문장 원문 그대로")
    suggestion: str = Field("", description="고치는 방법 제안")


HookAspect = Literal["첫 문단", "주인공", "전제", "설명 부담", "걸린 것", "장르 약속", "엔딩"]
HOOK_ASPECTS: list[str] = ["첫 문단", "주인공", "전제", "설명 부담", "걸린 것", "장르 약속", "엔딩"]


class HookItem(BaseModel):
    aspect: HookAspect
    score: int = Field(description="1(약함)~5(강함). 근거 없이 후하게 주지 않는다")
    quote: str = Field("", description="판단의 근거가 되는 본문 문장을 그대로. 없으면 빈칸")
    note: str = Field("", description="한 줄 평과 고칠 방향")


class HookReport(BaseModel):
    """1~3화 흡입력 판정. 참고용이라 승인 없이 화에 붙인다. 인용은 프로그램이 본문에서 확인한다."""
    episode: int
    items: list[HookItem] = Field(default_factory=list)
    premise_quote: str = Field("", description="작품의 핵심 장치가 일어나거나 확정되는 문장을 본문에서 그대로. 없으면 빈칸")
    reader_question: str = Field("", description="마지막 장면을 읽은 독자가 들고 갈 질문 한 문장. 쓸 수 없으면 빈칸")
    next_click: bool = Field(False, description="이 화를 무료로 읽은 독자가 다음 화를 누를지")
    reason: str = Field("", description="next_click 의 가장 큰 이유 한두 문장")
    premise_at: int = Field(-1, description="프로그램이 계산한다 (전제 문장이 나오는 글자 위치). -1 로 둔다")
    basis: str = Field("", description="프로그램이 채운다 (판정한 본문의 지문). 빈칸으로 둔다")
    checked_at: str = Field("", description="프로그램이 채운다. 빈칸으로 둔다")


class ConsistencyReport(BaseModel):
    """본문 검수 결과. 상태를 바꾸지 않는 참고용 경고라 승인 없이 저장한다."""
    episode: int
    issues: list[ConsistencyIssue] = Field(default_factory=list, description="근거가 분명한 모순만. 없으면 빈 목록")


EditSource = Literal["manual", "ai", "typed"]


class TextEdit(BaseModel):
    """본문 부분 수정 기록. 되돌리기에 쓰고, 고치기 전후 쌍은 나중에 선호 · 미세 조정 자료로 쓸 수 있게 남긴다."""
    id: str
    at: str = ""
    source: EditSource = Field("manual", description="manual: 고른 부분을 직접 고침 / ai: AI 후보를 고름 / typed: 본문을 직접 고쳐 저장")
    start: int = Field(0, description="고친 자리 (본문 안 글자 위치)")
    before: str = ""
    after: str = ""
    instruction: str = Field("", description="AI 에게 한 요청")
    preset: str = ""
    proposed: str = Field("", description="작가가 손보기 전 AI 후보 원문. 손보지 않았으면 비움")
    rejected: list[str] = Field(default_factory=list, description="고르지 않은 AI 후보")
    undone: bool = False


RewriteMode = Literal["fresh", "revise"]
RewriteMaterial = Literal["issues", "hook", "style", "edits"]


class RewriteRequest(BaseModel):
    """다시 생성할 때 작가가 준 것. 새 판과 함께 남겨 어떤 요청으로 나온 판인지 보인다."""
    feedback: str = Field("", description="작가가 적은 피드백")
    presets: list[str] = Field(default_factory=list, description="빠른 요청 id (prompts.REWRITE_PRESETS)")
    materials: list[RewriteMaterial] = Field(default_factory=list, description="함께 넣을 것: 검수 결과, 흡입력 판정, 문체 지표 경고, 작가가 고친 곳")
    mode: RewriteMode = Field("fresh", description="fresh: 처음부터 새로 / revise: 지난 판을 넣고 고쳐 쓰기")
    keep: list[str] = Field(default_factory=list, description="살릴 부분 (지난 판에서 고른 글 그대로)")


VersionKind = Literal["previous", "rejected"]


class TextVersion(BaseModel):
    """한 화 본문의 다른 판. 다시 생성으로 나와 고르기를 기다리는 새 판, 바꾸기 전 판, 고르지 않은 새 판."""
    id: str
    at: str = ""
    text: str = ""
    kind: VersionKind = Field("previous", description="previous: 새 판으로 바꾸기 전 본문 / rejected: 고르지 않은 새 판")
    request: Optional[RewriteRequest] = Field(None, description="이 판을 만든 다시 생성 요청 (처음 쓴 판이면 비움)")


class Episode(BaseModel):
    plot: EpisodePlot
    status: EpisodeStatus = "draft"
    text: str = ""
    summary: str = ""
    issues: list[ConsistencyIssue] = Field(default_factory=list, description="마지막 검수 결과")
    checked_at: str = Field("", description="마지막 검수 시각. 그 뒤에 본문을 고쳤으면 검수 결과가 오래된 것")
    edits: list[TextEdit] = Field(default_factory=list, description="본문 부분 수정 기록 (최근 것만)")
    auto: bool = Field(False, description="자동 집필이 사람 검토 없이 반영한 화. 사용자가 다시 반영하면 False")
    hook: Optional[HookReport] = Field(None, description="1~3화 흡입력 판정 (마지막 것). basis 가 지금 본문과 다르면 오래된 것")
    illustrations: list["Illustration"] = Field(default_factory=list, description="삽화 프롬프트 (NovelAI)")
    candidate: Optional[TextVersion] = Field(None, description="다시 생성으로 나와 지금 본문과 비교해 고르기를 기다리는 새 판")
    versions: list[TextVersion] = Field(default_factory=list, description="바꾸기 전 판과 고르지 않은 새 판 (최근 것만)")
    made_by: Optional[RewriteRequest] = Field(None, description="지금 본문을 만든 다시 생성 요청 (처음 쓴 판이나 직접 쓴 본문이면 비움)")


# ---------- 회차 진행 상태 ----------

class StatValue(BaseModel):
    """상태창 한 줄 (canon/statwin.py)."""
    name: str = Field(description="항목 이름 (예: 레벨, HP, 힘, 스킬)")
    value: str = Field("", description="값. 변경안에서는 새 값을 적거나, 바뀐 양만 알면 +3, -10 처럼. 항목이 사라졌으면 빈 값")


class CharacterState(BaseModel):
    character_id: str
    emotional_state: str = ""
    current_goal: str = ""
    location: str = ""
    knows: list[str] = Field(default_factory=list, description="이 인물이 알게 된 핵심 정보")
    notes: str = ""
    stats: list[StatValue] = Field(default_factory=list, description="상태창 수치. 작가가 상태창을 만든 인물만. 변경안에는 바뀐 항목만 넣는다")


class Foreshadow(BaseModel):
    id: str = Field(description="예: fs-03-locket")
    description: str
    planted_ep: int
    payoff_ep: Optional[int] = None
    status: Literal["open", "resolved"] = "open"
    scope: Literal["arc", "part", "series"] = Field("arc", description="회수 범위: arc 이번 아크 안 / part 이번 부 안 / series 작품 끝까지 가는 큰 복선")
    due_ep: Optional[int] = Field(None, description="회수 예정 화. 정하지 않았으면 비움")


class ForeshadowClue(BaseModel):
    """복선이 본문에 걸린 자리. 본문은 바꾸지 않고 근거 문장만 기억한다 (canon/foreshadows.py)."""
    foreshadow: str = Field(description="복선 id")
    kind: Literal["plant", "payoff"] = Field("plant", description="plant: 심거나 다시 떠올린 문장 / payoff: 회수한 문장")
    quote: str = Field(description="근거가 되는 문장을 본문에서 그대로")
    episode: int = Field(0, description="문장이 있는 화. 프로그램이 채운다")
    by: Literal["ai", "author"] = Field("ai", description="상태 변경안에서 왔는지(ai), 작가가 본문에서 골라 붙였는지(author). 프로그램이 채운다")


class StatRecord(BaseModel):
    """상태창 수치가 바뀐 기록. 화별 비교는 이 기록으로 다시 그린다 (canon/statwin.py)."""
    episode: int = Field(description="바뀐 화. 1화 전에 정한 처음 값은 0")
    character_id: str
    name: str
    value: str = Field("", description="바뀐 뒤 값. 빈 값이면 항목이 사라짐")
    before: str = ""
    source: Literal["ai", "author"] = Field("ai", description="ai: 승인한 상태 변경안 / author: 작가가 직접 고침")


class StatWindow(BaseModel):
    """본문에 넣는 상태창 서식. {name} 은 인물 이름, {rows} 는 항목 줄들."""
    template: str = "【 상태창 】\n이름: {name}\n{rows}"
    row: str = "{key}: {value}"


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
    foreshadow_clues: list[ForeshadowClue] = Field(default_factory=list, description="복선 근거 문장: 새로 심은 복선, 다시 떠올린 열린 복선, 회수한 복선마다 본문 문장 그대로")
    new_characters: list[Character] = Field(default_factory=list, description="인물 설정에 없는데 이번 화에 이름을 갖고 처음 나온 인물. 조연은 support, 지나가는 인물은 minor")
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



# ---------- 삽화 프롬프트 (NovelAI 이미지 생성용, canon/illust.py 가 조립) ----------

Subject = Literal["girl", "boy", "other"]


class IllustCharacter(BaseModel):
    """장면에 나오는 인물 하나. 외형은 저장된 외형 태그(CharacterVisual)를 쓰고, AI 는 이 장면의 모습만 적는다."""
    id: str = Field("", description="인물 id. 설정에 없는 인물(행인, 군중 속 한 명)이면 빈칸")
    subject: Subject = Field(description="girl / boy / other (사람이 아니거나 성별을 알 수 없음)")
    look: list[str] = Field(default_factory=list, description="외형 태그 (머리, 눈, 체형, 나이대). 외형 태그가 저장된 인물은 빈 목록")
    outfit: list[str] = Field(default_factory=list, description="이 장면의 옷차림 태그. 저장된 기본 옷차림과 같으면 빈 목록")
    expression: list[str] = Field(default_factory=list, description="표정 태그 (smile, frown, tears, open mouth)")
    action: list[str] = Field(default_factory=list, description="자세 · 동작 · 시선 · 손에 든 것 태그. 다른 인물과 주고받는 행동은 source#hug / target#hug / mutual#hug 처럼")
    position: str = Field("", description="화면 속 자리: left / center / right. 정하지 않으면 빈칸")


class IllustDraft(BaseModel):
    """AI 가 본문 장면을 태그로 옮긴 원안. 인물 수 태그, 외형, 등급, 품질 태그는 프로그램이 붙인다."""
    quote: str = Field(description="그릴 장면의 본문 문장을 원문 그대로 1~3문장")
    scene: str = Field(description="그릴 장면을 한국어 한 문장으로")
    characters: list[IllustCharacter] = Field(default_factory=list, description="그림에 보이는 인물. 화면에 안 보이면 넣지 않는다")
    setting: list[str] = Field(default_factory=list, description="장소 · 배경 · 시간대 · 날씨 태그 (indoors, classroom, night, rain)")
    lighting: list[str] = Field(default_factory=list, description="빛 태그 (sunlight, backlighting, dim lighting, moonlight)")
    composition: list[str] = Field(default_factory=list, description="구도 · 카메라 태그 (cowboy shot, upper body, from above, wide shot, close-up)")
    mood: list[str] = Field(default_factory=list, description="분위기 · 소품 · 효과 태그 (falling petals, steam, blood splatter)")
    caption: str = Field("", description="장면을 영어 한 문장으로. 인물 이름 대신 the girl, the man 처럼")
    negative: list[str] = Field(default_factory=list, description="이 장면에 나오면 안 되는 것 태그 (예: 모자를 벗은 장면이면 hat)")
    rating: Literal["general", "sensitive", "questionable", "explicit"] = Field(
        "general", description="장면의 노출 · 폭력 수위. general 일반 / sensitive 약한 노출 / questionable 노출 / explicit 성인")


class VoiceSuggestion(BaseModel):
    """인물 설정으로 쓴 시점 서술 말투 초안. 작가가 고쳐 저장한다 (Character.narration_voice)."""
    voice: str = Field(description="서술 어미와 문장 끝맺음, 문장 길이와 리듬, 내면 독백 처리, 자주 쓰는 표현, 피할 것을 3~6줄로. "
                       "마지막 줄은 '예: ' 뒤에 이 말투로 쓴 서술 문장 두 개 (대사가 아닌 지문)")
    note: str = Field("", description="작가에게 하는 한두 문장: 이 말투를 고른 까닭, 작품 문체와 부딪히는 곳")


class LookSuggestion(BaseModel):
    """인물 설정(외모, 나이, 성별)을 NovelAI 외형 태그로 옮긴 제안. 작가가 고쳐 저장한다."""
    subject: Subject
    look: list[str] = Field(description="바뀌지 않는 외형 태그: 머리 색과 길이, 머리 모양, 눈 색, 체형, 나이대, 특징 (흉터, 안경 등)")
    outfit: list[str] = Field(default_factory=list, description="평소 옷차림 태그")
    note: str = Field("", description="작가에게 하는 한두 문장: 설정에서 태그로 옮기기 어려웠던 것")


class CharacterVisual(BaseModel):
    """삽화마다 똑같이 넣는 인물 외형 태그. 작가가 정하고, AI 는 덮지 않는다."""
    character_id: str
    subject: Literal["", "girl", "boy", "other"] = Field("", description="비우면 성별로 정한다")
    look: list[str] = Field(default_factory=list, description="외형 태그 (영어, NovelAI · Danbooru 태그)")
    outfit: list[str] = Field(default_factory=list, description="기본 옷차림 태그. 장면에서 다른 옷을 입으면 그 장면 것을 쓴다")
    negative: list[str] = Field(default_factory=list, description="이 인물에게 섞여 들면 안 되는 것 (인물 프롬프트의 부정 태그)")


class IllustSettings(BaseModel):
    model: str = Field("v4.5-full", description="NovelAI 모델 id (canon/illust.py MODELS)")
    style: list[str] = Field(default_factory=list, description="모든 삽화에 넣는 화풍 태그 (예: watercolor, flat color)")
    negative: list[str] = Field(default_factory=list, description="모든 삽화에 넣는 부정 태그")
    quality: bool = Field(False, description="품질 태그를 프롬프트에 직접 넣는다 (NovelAI 의 Add Quality Tags 를 끈 경우)")
    basic_negative: bool = Field(False, description="기본 부정 태그를 넣는다 (NovelAI 의 UC 프리셋을 끈 경우)")


class IllustCharPrompt(BaseModel):
    id: str = ""
    name: str = ""
    prompt: str = ""
    negative: str = ""
    position: str = ""


class Illustration(BaseModel):
    """화에 저장한 삽화 프롬프트. draft 에서 언제든 다시 조립할 수 있다 (모델이나 외형 태그를 바꿨을 때)."""
    id: str
    at: str = ""
    model: str = ""
    selection: Optional["Selection"] = Field(None, description="작가가 고른 부분. 비면 AI 가 장면을 골랐다 (draft.quote)")
    request: str = Field("", description="작가가 덧붙인 요청")
    draft: IllustDraft
    base: str = ""
    characters: list[IllustCharPrompt] = Field(default_factory=list)
    negative: str = ""
    combined: str = Field("", description="한 칸에 붙여 넣는 프롬프트 (V4 이상은 | 로 인물을 나눔)")
    rating: str = ""
    missing_look: list[str] = Field(default_factory=list, description="외형 태그가 저장되지 않아 AI 태그를 쓴 인물 id")
    notes: list[str] = Field(default_factory=list, description="조립하며 알릴 것")


# ---------- 전체 프로젝트 ----------

class Project(BaseModel):
    meta: Meta = Field(default_factory=Meta)
    world: WorldSetting = Field(default_factory=WorldSetting)
    characters: list[Character] = Field(default_factory=list)
    cast_candidates: list[Character] = Field(
        default_factory=list, description="AI 플롯이 제안한 새 인물. 작가가 등록하거나 그 인물이 나오는 화를 확정하면 characters 로 옮긴다")
    relationships: list[Relationship] = Field(default_factory=list)
    style: StyleProfile = Field(default_factory=StyleProfile)
    style_baseline: Optional[StyleMetrics] = Field(None, description="레퍼런스 원문 전체로 잰 문체 지표 (style 명령 때 저장)")
    style_id: str = Field("", description="문체 라이브러리에서 가져온 항목 id. 비어 있으면 이 작품에서 직접 만든 문체")
    style_version: int = Field(0, description="가져오거나 올린 라이브러리 항목의 버전 번호. 0 은 모름")
    style_learning: Optional[StyleLearning] = Field(None, description="수정 기록에서 찾은 문체 규칙 후보 (마지막 것)")
    arc: list[Act] = Field(default_factory=list, description="단편: 작품 전체의 기승전결. 장편에서는 비워 두고 아크마다 기승전결을 둔다")
    parts: list[Part] = Field(default_factory=list, description="장편: 부 구성")
    story_arcs: list[StoryArc] = Field(default_factory=list, description="장편: 지금까지 기획한 아크. 다음 아크를 하나씩 붙인다")
    episodes: list[Episode] = Field(default_factory=list)
    states: list[CharacterState] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    foreshadows: list[Foreshadow] = Field(default_factory=list)
    foreshadow_clues: list[ForeshadowClue] = Field(default_factory=list, description="복선이 본문에 걸린 문장 (복선 센터)")
    stat_log: list[StatRecord] = Field(default_factory=list, description="상태창 수치가 바뀐 기록")
    stat_window: StatWindow = Field(default_factory=StatWindow, description="본문에 넣는 상태창 서식")
    history: list[StateDelta] = Field(default_factory=list, description="승인된 상태 변경 기록")
    ties: list[Tie] = Field(default_factory=list, description="방향 관계 (dynamics 가 계산)")
    secrets: list[Secret] = Field(default_factory=list)
    events: list[StoryEvent] = Field(default_factory=list, description="승인된 사건 로그")
    params: ModelParams = Field(default_factory=ModelParams)
    snapshots: list[Snapshot] = Field(default_factory=list)
    settings: Settings = Field(default_factory=Settings)
    chats: list[Chat] = Field(default_factory=list, description="화면별 AI 대화 기록")
    elements: list[StoryElement] = Field(default_factory=list, description="인과율: 언제든 더하는 요소, 특징, 설정, 사건")
    conversion: Optional[Conversion] = Field(None, description="단편에서 장편으로 바꾼 기록. 되돌리면 지운다")
    archive: Optional[ShortArchive] = Field(None, description="재구성 전 단편 원고와 새 화 지도")
    storylines: list[Storyline] = Field(default_factory=list, description="메인에서 갈라지는 이야기 줄기 (서브플롯, 과거 회상, 외전, 인물 이야기)")
    visuals: list[CharacterVisual] = Field(default_factory=list, description="삽화용 인물 외형 태그")
    illust: IllustSettings = Field(default_factory=IllustSettings, description="삽화 프롬프트 설정")

    def episode(self, n: int) -> Episode:
        for ep in self.episodes:
            if ep.plot.number == n:
                return ep
        raise KeyError(f"{n}화 플롯이 없습니다")

    @property
    def serial(self) -> bool:
        return self.meta.form == "serial"

    def beats(self) -> list[Act]:
        """화마다 소속 구간(기승전결)을 정하는 목록. 단편은 작품 전체 구조, 장편은 기획한 아크들의 구간을 이은 것."""
        if not self.serial:
            return self.arc
        return [a for s in sorted(self.story_arcs, key=lambda s: s.start_ep) for a in s.acts]

    def act_for(self, n: int) -> Optional[Act]:
        return next((a for a in self.beats() if a.start_ep <= n <= a.end_ep), None)

    def acts_for(self, n: int) -> list[Act]:
        """n 화에 걸친 구간들. 4화보다 짧은 작품은 한 화에 두 구간 이상이 들어갈 수 있다."""
        return [a for a in self.beats() if a.start_ep <= n <= a.end_ep]
    def arc_for(self, n: int) -> Optional[StoryArc]:
        return next((s for s in self.story_arcs if s.start_ep <= n <= s.end_ep), None)

    def part_for(self, n: int) -> Optional[Part]:
        return next((s for s in self.parts if s.start_ep <= n <= s.end_ep), None)

    def planned_until(self) -> int:
        """장편에서 아크로 기획한 마지막 화. 아크가 없으면 0."""
        return max((s.end_ep for s in self.story_arcs), default=0)

    def storyline(self, sid: str) -> Optional[Storyline]:
        return next((s for s in self.storylines if s.id == sid), None) if sid else None

    def state_of(self, cid: str) -> Optional[CharacterState]:
        return next((s for s in self.states if s.character_id == cid), None)

    def snapshot(self, n: int) -> Optional[Snapshot]:
        return next((s for s in self.snapshots if s.episode == n), None)

    def visual(self, cid: str) -> Optional[CharacterVisual]:
        return next((v for v in self.visuals if v.character_id == cid), None)

    def chat(self, topic: str) -> Chat:
        c = next((c for c in self.chats if c.topic == topic), None)
        if c is None:
            c = Chat(topic=topic)  # type: ignore[arg-type]
            self.chats.append(c)
        return c


Snapshot.model_rebuild()
SerialRebuild.model_rebuild()
ShortArchive.model_rebuild()
Episode.model_rebuild()
StyleEntry.model_rebuild()
