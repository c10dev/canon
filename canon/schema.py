"""소설 프로젝트 데이터 스키마.

모든 상태는 하나의 Project 객체(project.json)에 저장된다.
LLM 이 직접 채우는 모델(SetupSuggestion, StyleProfile, ArcPlan, PlotBatch, PlotRevision, NameOptions, StateDelta, ConsistencyReport,
ImpactReport, SeriesPlan, ArcProposal, Recap, StorylineProposal, SerialConversion,
PassageRevision, SerialRebuild, Rework, HookReport, OpeningPlots, IllustDraft, LookSuggestion, PlaceSort, FieldIdeas)은
Gemini 구조화 출력에 그대로 넘기므로 dict 타입 필드를 쓰지 않는다.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, PrivateAttr, SerializationInfo, SerializerFunctionWrapHandler, field_validator, model_serializer, model_validator
from pydantic.json_schema import SkipJsonSchema

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


class CharacterBody(BaseModel):
    """신체 프로필. 작가가 정하고 인물 카드에만 보인다. 프롬프트에 넣지 않고 AI 응답 형식에서도 뺀다 (Character.body)."""
    height: str = ""
    weight: str = ""
    build: str = ""
    measurements: str = ""
    features: str = ""


class BodySuggestion(BaseModel):
    """신체 프로필 AI 제안. 작가가 칸별로 골라 적용한다 (pipeline.suggest_body). 미성년 인물은 measurements 를 비운다."""
    height: str = Field("", description="키 (예: 165cm)")
    weight: str = Field("", description="몸무게 (예: 48kg)")
    build: str = Field("", description="체형 한 줄 (예: 마른 근육형, 어깨가 넓다)")
    measurements: str = Field("", description="쓰리사이즈 가슴-허리-엉덩이 cm (예: 84-58-86). 미성년 인물이면 빈칸")
    features: str = Field("", description="바뀌지 않는 신체 특징 1~3개를 쉼표로 (손잡이, 점 · 흉터 위치, 목소리 등)")
    note: str = Field("", description="작가에게 하는 한두 문장: 설정에서 무엇을 근거로 정했는지")


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
    # 작가만 채운다. JSON 스키마에서 빼서 AI 가 채우지 않게 한다 (저장 · 화면 검증은 그대로)
    body: SkipJsonSchema[CharacterBody] = Field(default_factory=CharacterBody)
    # 프롬프트에 넣기 (작가만 정한다): auto 비중 · 등장 화 · 장편 예산대로, always 늘 앞 블록에, off 설정 · 상태 · 관계를 빼고 이름만.
    # 고르는 규칙은 context.core_ids · off_ids
    context: SkipJsonSchema[Literal["auto", "always", "off"]] = Field(
        "auto", description="프롬프트에 넣기: auto 등장할 때(비중대로), always 항상, off 넣지 않음(이름만)")

    @model_serializer(mode="wrap")
    def _prompt_view(self, handler: SerializerFunctionWrapHandler, info: SerializationInfo):
        """프롬프트용 직렬화(llm.dump 의 context prompt)에서는 신체 프로필과 넣기 방식을 뺀다. 저장과 화면 응답은 그대로."""
        data = handler(self)
        if isinstance(data, dict) and info.context and info.context.get("prompt"):
            data.pop("body", None)
            data.pop("context", None)
        return data


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
    deadlines: Optional[list["Deadline"]] = Field(None, description="작품 속 기한. 기한이 생기기 전에 찍은 스냅샷이면 비움 (timeline.revert 가 화 번호로 거른다)")


class Settings(BaseModel):
    show_numbers: bool = Field(False, description="CLI 에서 관계를 숫자로 보여줄지(True), 말로 보여줄지(False)")
    check_widen: bool = Field(False, description="장편 검수 넓히기: 검수 뒤 진술마다 옛 화를 더 찾아, 첫 검수에 없던 근거가 나온 진술만 다시 묻는다 (검수 호출 2번 더)")
    stage_extract: bool = Field(True, description="검수 때 본문에서 장면 연출을 함께 뽑는다 (사건마다 check 호출 1번 더, 본문이 그대로인 사건은 건너뜀)")
    storyboard: Optional[bool] = Field(None, description="화마다 쓰기 전에 스토리보드를 만들고, 쓰기 프롬프트에 직전 화 본문 전체를 넣는다. 비우면 장편 켬 · 단편 끔 (board.on)")
    cue_sheet: Optional[bool] = Field(None, description="화마다 쓰기 전에 큐 시트(큐마다 기능 · 긴장 · 템포 · 편성 · 핵심 대사 · 분량)를 만들어 쓰기 프롬프트 끝에 넣는다. 비우면 장편 켬 · 단편 끔 (cue.on)")
    keep_snapshots: bool = Field(False, description="장편에서도 화별 스냅샷을 지우지 않고 모두 남긴다 (연구용 작품: 어느 화로든 되돌릴 수 있다). 끄면 0화 · 아크 끝 · 최근 20화만 남긴다 (pipeline.prune_snapshots)")
    model_preset: str = Field("", description="이 작품이 쓰는 단계 프리셋 id (settings.presets: 단계별 백엔드 · 모델 묶음). 비우면 전체 설정을 따른다. 고른 프리셋이 지워졌으면 전체 설정을 따른다 (settings.project_preset)")


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


# ---------- 대화로 문체 다듬기 ----------
# 작가가 문체 화면에서 말로 바라는 것을 말하면 AI 가 스타일 프로필에서 바꿀 칸과 시험 문단을 낸다. 고른 칸만 작품 문체에 넣는다
# (pipeline.revise_style · apply_style_chat). 대표 문단은 원문 발췌라 AI 가 고치지 않는다.

StyleKey = Literal["narration_pov", "tense", "sentence_rhythm", "description_density", "dialogue_ratio", "dialogue_style",
                   "inner_monologue", "pacing", "scene_transition", "vocabulary", "dos", "donts", "banned_phrases",
                   "markers", "devices"]


class StyleEdit(BaseModel):
    """스타일 프로필 한 칸의 바뀐 뒤 값. 칸 종류에 맞는 자리 하나만 채운다."""
    key: StyleKey = Field(description="바꿀 칸 이름")
    text: str = Field("", description="글 칸(narration_pov ~ vocabulary)일 때: 바뀐 뒤 글 전체")
    items: list[str] = Field(default_factory=list, description="dos · donts · banned_phrases 일 때: 바뀐 뒤 목록 전체 (그대로 둘 항목도 모두 넣는다)")
    markers: list[StyleMarker] = Field(default_factory=list, description="markers 일 때: 바뀐 뒤 표지 목록 전체. per_1k 는 지금 값 그대로, 새 표지는 0")
    devices: list[StyleDevice] = Field(default_factory=list, description="devices 일 때: 바뀐 뒤 장치 목록 전체")
    why: str = Field("", description="왜 이렇게 바꾸는지 한 줄")


class StyleRevision(BaseModel):
    """문체 대화에서 AI 가 내는 답과 변경안 (pipeline.clean_style_revision 이 지금 값과 같은 칸을 뺀다)."""
    reply: str = Field(description="작가에게 하는 대답 2~5문장. 무엇을 왜 바꿨는지, 또는 되묻는 말")
    edits: list[StyleEdit] = Field(default_factory=list, description="바뀌는 칸만. 질문에 답하거나 되물을 때는 빈 목록")
    preview_source: str = Field("", description="참고할 화가 주어졌을 때만: 시험 문단으로 고쳐 쓸 그 화 본문 한 대목을 적힌 그대로 (200~500자). 아니면 빈칸")
    preview: str = Field("", description="바뀐 문체로 쓴 시험 문단 4~8문장. preview_source 가 있으면 그 대목을 같은 내용으로 고쳐 쓴 글")

    def has_changes(self) -> bool:
        return bool(self.edits)


class StyleSample(BaseModel):
    """지금 문체로 쓴 예시 글 (AI 가 채운다). 작가가 문체가 실제로 어떻게 읽히는지 보는 용도이고 본문에는 들어가지 않는다."""
    text: str = Field(description="이 문체로 쓴 예시 글. 문단은 빈 줄로 나눈다")
    source: str = Field("", description="참고할 화가 주어졌을 때만: 고쳐 쓴 그 화 본문 대목을 적힌 그대로. 아니면 빈칸")


class StyleExample(BaseModel):
    """문체 화면의 '이 문체로 쓴 예시' 칸 (Project.style_example). 쓸 때의 프로필을 남겨 문체가 바뀌었는지 본다."""
    text: str = ""
    source: str = Field("", description="고쳐 쓴 원래 대목 (참고한 화가 있을 때)")
    episode: int = Field(0, description="참고한 화. 0 이면 새 장면")
    scene: str = Field("", description="작가가 청한 장면")
    by: Literal["", "example", "chat"] = Field("", description="example: 예시 칸에서 씀, chat: 문체 대화의 시험 문단을 적용과 함께 옮김")
    profile: StyleProfile = Field(default_factory=StyleProfile, description="쓸 때의 스타일 프로필")
    at: str = ""


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
    time: str = Field("", description="이 화가 시작하는 작품 속 시점: 직전 화에서 얼마나 지났는지나 시간대 (예: 다음 날 아침, 사흘 뒤 밤, 1년 뒤). 직전 화에서 바로 이어지면 비움")

    @field_validator("events")
    @classmethod
    def _drop_blank_events(cls, v: list[str]) -> list[str]:
        # 화 플롯 페이지는 사건을 한 칸씩 고친다. 비워 둔 칸은 저장하지 않는다
        return [x.strip() for x in v if x.strip()]


NEW_CAST_DESC = ("인물 목록에 없는 새 인물이 이 플롯에 꼭 필요할 때만, 전체 설정(speech_style 포함)과 함께. "
                 "그 화의 characters 에 이 id 를 넣는다. 이미 있는 인물은 넣지 않는다. 조연은 support, 지나가는 인물은 minor")


class NewPlace(BaseModel):
    """본문이나 플롯에 이름을 갖고 처음 나온 장소. 등록하면 인과율 '장소' 요소가 된다 (elements.add_places)."""
    name: str = Field(description="본문이나 플롯에 쓴 그대로의 이름")
    kind: str = Field("", description="종류 한 단어 (마을, 산, 강, 고개, 숲, 건물, 가게, 학교, 문파 등)")
    description: str = Field("", description="드러난 것만 한 줄: 어디에 있고 어떤 곳인지")
    aliases: list[str] = Field(default_factory=list, description="같은 곳을 달리 부른 이름")


NEW_PLACE_DESC = ("장소 목록, 이야기 요소, 새 장소 후보에 없는 지형 · 마을 · 건물 · 가게 등이 이 플롯에 이름을 갖고 새로 나올 때만. "
                  "플롯 글에 쓴 이름 그대로. 이름 없는 길이나 방은 넣지 않는다")


class PlaceGuess(BaseModel):
    """장소와 맞지 않은 인물 위치 글 하나를 어디에 이을지 (지도 화면의 'AI로 한 번에 정리')."""
    text: str = Field(description="받은 위치 글 그대로")
    place: str = Field("", description="이 글이 가리키는 [장소 목록]의 이름 그대로. 새 장소나 그리지 않음이면 비운다")
    new_place: str = Field("", description="장소 목록에 없는 곳이면 new_places 에 넣은 이름 그대로")
    skip: bool = Field(False, description="이동 중, 알 수 없음, 꿈속처럼 지도의 한 곳으로 그릴 수 없으면 true")
    note: str = Field("", description="애매할 때만 한 줄: 왜 그렇게 봤는지")


class PlaceSort(BaseModel):
    """위치 글 묶음을 장소에 맞춘 제안. 저장하지 않고 작가가 골라 적용한다 (atlas.apply_sort)."""
    matches: list[PlaceGuess] = Field(default_factory=list)
    new_places: list[NewPlace] = Field(default_factory=list, description="여러 위치 글이 가리키는데 장소 목록에 없는 곳만. 방 하나, 길 위 같은 곳은 넣지 않는다")


class MapPlaceGuess(BaseModel):
    """지도 만들기 제안의 장소 하나."""
    name: str = Field(description="[장소 목록]의 이름 그대로")
    kind: str = Field(description="[종류]의 id 하나")
    put: bool = Field(True, description="이 마을 지도 안에 놓을 곳이면 true. 다른 도시, 먼 산, 나라처럼 이 마을 밖이면 false")
    note: str = Field("", description="애매할 때만 한 줄: 왜 그렇게 봤는지")


class MapSuggestion(BaseModel):
    """지도 만들기 설정 제안 (pipeline.suggest_map). 저장하지 않고 작가가 지도 화면 칸에 채워 본다. 좌표는 생성기가 정한다."""
    kind: Literal["village", "city", "modern"] = Field("village", description="지도 종류: village 마을 / city 성벽이 있는 도시 / "
                                                                         "modern 현대 동네 (대로 격자, 아파트 · 빌라 · 상가)")
    size: Literal["small", "medium", "large"] = Field(description="크기. 마을: small 집 25~30채 / medium 60~70채 / large 100~140채. "
                                                      "도시: small 500~750채 / medium 1,000~1,300채 / large 2,000~2,500채. "
                                                      "현대 동네: small 건물 400~900채 / medium 650~1,350채 / large 1,550~2,300채")
    roads: Literal["line", "cross", "square"] = Field(description="길 모양 (마을만): line 한길을 따라 / cross 교차로 / square 가운데 광장")
    water: Literal["none", "river", "lake", "sea"] = Field(description="물: none 없음 / river 강 · 하천 / lake 호수(마을만) / sea 바다(현대 동네는 없음)")
    fields: Literal["few", "some", "many"] = Field(description="밭 양 (현대 동네는 쓰지 않음)")
    forest: Literal["few", "some", "many"] = Field(description="숲 양 (현대 동네는 공원 수)")
    places: list[MapPlaceGuess] = Field(default_factory=list, description="[장소 목록]의 장소마다 하나")
    reason: str = Field("", description="왜 이 설정인지 한두 문장. 작품 설정 · 장소 설명에서 근거를 든다")


class PlotBatch(BaseModel):
    episodes: list[EpisodePlot]
    new_characters: list[Character] = Field(default_factory=list, description=NEW_CAST_DESC)
    new_places: list[NewPlace] = Field(default_factory=list, description=NEW_PLACE_DESC)


class EpisodeDraft(PlotBatch):
    """화 하나를 작가가 적은 것 우선으로 채운 것 (pipeline.draft_episode, 뒤 화에 맞추지 않을 때)."""
    next_gap: str = Field("", description="이 화를 작가 뜻대로 마무리하면서 바로 뒤 화 플롯과 어긋나게 된 점. 뒤 화에서 고칠 것을 한두 문장으로. 어긋나지 않으면 비움")


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


class ArcUndo(BaseModel):
    """아크를 붙일 때 바꾼 것. 그 아크를 지우면(remove_last_arc) 되돌린다. 프로그램이 채운다."""
    number: int
    characters: list[str] = Field(default_factory=list, description="이 아크가 더한 인물 id")
    foreshadows: list[str] = Field(default_factory=list, description="회수 예정 화를 바꾼 복선 id")
    due_before: list[Optional[int]] = Field(default_factory=list, description="foreshadows 와 같은 순서로, 바꾸기 전 회수 예정 화 (정하지 않았으면 null)")


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


class KnowsFold(BaseModel):
    """인물 하나의 오래된 아는 정보를 접은 줄 (canon/knows.py)."""
    character_id: str = Field(description="인물 id")
    lines: list[str] = Field(description="접은 뒤 남길 줄. 한 줄에 한 가지, 뒤 화에서 이 인물이 행동할 때 기준이 되는 것만")


class KnowsFoldSet(BaseModel):
    """아크 요약 뒤 아는 정보 접기 제안. 작가가 인물마다 골라 적용한다 (pipeline.fold_knows, knows.apply_fold)."""
    folds: list[KnowsFold] = Field(default_factory=list)


class KnowsFoldRecord(BaseModel):
    """적용한 접기 기록. 되돌리기에 쓴다."""
    arc: int
    character_id: str
    removed: list[str] = Field(default_factory=list, description="접어서 knows 에서 뺀 줄")
    before: list[str] = Field(default_factory=list, description="접기 전 knows_folded")
    after: list[str] = Field(default_factory=list, description="접은 뒤 knows_folded")


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
    notes: list[str] = Field(default_factory=list, description="전환하며 옮기지 못해 작가가 볼 것 (재구성 화면에 다시 보인다)")


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

class ArcEdit(BaseModel):
    """플롯 대화에서 고치거나 새로 짜는 아크의 칸 (장편). 바꾸지 않으면 title 을 비운다."""
    title: str = Field("", description="아크 칸을 바꿀 때만 채운다. 바꾸지 않으면 비움")
    goal: str = Field("", description="아크가 끝날 때 바뀌어 있어야 하는 것")
    conflict: str = Field("", description="주인공을 막는 문제나 상대")
    payoff: str = Field("", description="아크 클라이맥스에서 독자가 받는 보상(사이다)")
    cast: list[str] = Field(default_factory=list, description="이 아크에 주로 나오는 인물 id")
    payoffs: list[str] = Field(default_factory=list, description="이 아크에서 회수할 열린 복선 id")
    pov: str = Field("", description="이 아크의 서술 시점 운용 한 줄. 작품 기본 시점 그대로면 비움")
    end_ep: int = Field(0, description="아크 끝 화를 바꿀 때만 새 끝 화. 그대로면 0. 다음 아크를 짤 때는 꼭 넣는다")


class Direction(BaseModel):
    """플롯 대화의 '방향 여러 안': 변경안을 만들기 전에 작가가 고르거나 섞을 방향 하나."""
    title: str = Field(description="방향 이름 한 줄")
    idea: str = Field(description="이 방향이면 이야기가 어떻게 되는지 2~3문장")
    changes: list[str] = Field(default_factory=list, description="바뀌는 부 · 아크 · 구간 · 화를 한 줄씩 (예: '승 구간: 배신을 중반으로 당김')")
    tradeoff: str = Field("", description="얻는 것과 잃는 것 한 줄")


class PlotRevision(BaseModel):
    """플롯 대화에서 AI 가 내는 답과 변경안. 사용자가 고른 부분만 반영한다 (pipeline.apply_revision)."""
    reply: str = Field(description="작가에게 하는 대답. 무엇을 왜 바꿨는지, 또는 되묻는 말")
    total_episodes: int = Field(0, description="총 화수를 바꿀 때만 새 화수. 바꾸지 않으면 0")
    acts: list[Act] = Field(default_factory=list, description="구조를 바꿀 때만 네 구간 모두. 바꾸지 않으면 빈 목록")
    episodes: list[EpisodePlot] = Field(default_factory=list, description="바뀌는 화만, 모든 칸을 채운 전체 플롯")
    new_characters: list[Character] = Field(default_factory=list, description=NEW_CAST_DESC)
    new_places: list[NewPlace] = Field(default_factory=list, description=NEW_PLACE_DESC)
    arc: ArcEdit = Field(default_factory=ArcEdit, description="장편: 아크 칸을 바꾸거나 다음 아크를 짤 때만 모든 칸을 채운다. 그대로면 title 을 비움")
    parts: list[Part] = Field(default_factory=list, description="장편: 부 구성을 바꿀 때만 모든 부. 그대로면 빈 목록")
    options: list[Direction] = Field(default_factory=list, description="작가가 방향 여러 안을 청했을 때만 서로 다른 방향 2~3개. 그때는 다른 변경 칸을 모두 비움")

    def has_changes(self) -> bool:
        return bool(self.acts or self.episodes or self.arc.title or self.parts)


# ---------- 설정 도우미 대화 (canon/setupchat.py 가 정리 · 적용 · 적용 취소) ----------

SetupKey = Literal["title", "logline.who", "logline.why", "logline.goal", "logline.block", "logline.stake", "theme", "tone", "notes",
                   "world.setting", "world.era", "world.rules", "world.locations", "world.name_rules"]
CharField = Literal["name", "role", "age", "gender", "appearance", "personality", "background", "goal", "wound", "speech_style",
                    "secrets", "arc"]


class SetupEdit(BaseModel):
    """기본 정보 · 세계관 한 칸의 바뀐 뒤 값."""
    key: SetupKey = Field(description="바꿀 칸 이름")
    text: str = Field("", description="글 칸일 때: 바뀐 뒤 글 전체")
    items: list[str] = Field(default_factory=list, description="world.rules · world.locations · world.name_rules 일 때: 바뀐 뒤 목록 전체 (그대로 둘 항목도 모두 넣는다)")
    why: str = Field("", description="왜 이렇게 바꾸는지 한 줄")


class CharacterEdit(BaseModel):
    """이미 있는 인물 한 칸의 바뀐 뒤 값."""
    id: str = Field(description="[인물]에 있는 인물 id")
    field: CharField = Field(description="바꿀 칸 이름")
    text: str = Field("", description="글 칸일 때: 바뀐 뒤 글 전체")
    items: list[str] = Field(default_factory=list, description="secrets 일 때: 바뀐 뒤 목록 전체")
    why: str = Field("", description="왜 이렇게 바꾸는지 한 줄")


class SetupRevision(BaseModel):
    """설정 도우미 대화에서 AI 가 내는 답과 변경안. 작가가 고른 칸만 적용한다 (setupchat.clean · apply)."""
    reply: str = Field(description="작가에게 하는 대답 2~5문장. 무엇을 왜 바꿨는지, 또는 되묻는 말")
    edits: list[SetupEdit] = Field(default_factory=list, description="바뀌는 기본 정보 · 세계관 칸만")
    characters: list[CharacterEdit] = Field(default_factory=list, description="바뀌는 이미 있는 인물의 칸만")
    new_characters: list[Character] = Field(default_factory=list, description="새로 더할 인물만, 모든 칸을 채운 설정. id 는 이미 있는 인물과 겹치지 않는 영문 소문자")
    relationships: list[Relationship] = Field(default_factory=list, description="바뀌는 관계나 새 관계만, 바뀐 뒤 값 전체. 같은 두 인물이면 그 관계를 바꾼다")
    options: list[Direction] = Field(default_factory=list, description="작가가 방향 여러 안을 청했을 때만 서로 다른 방향 2~3개. 그때는 다른 변경 칸을 모두 비움")

    def has_changes(self) -> bool:
        return bool(self.edits or self.characters or self.new_characters or self.relationships)


class SetupBefore(BaseModel):
    """설정 대화 변경안을 적용하기 전 설정 (적용 취소용)."""
    meta: Meta = Field(default_factory=Meta)
    world: WorldSetting = Field(default_factory=WorldSetting)
    characters: list[Character] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)


class ChatScope(BaseModel):
    """플롯 대화를 보낼 때 화면이 알려 주는 것 (AI 가 채우지 않는다).
    target: '' 기본(단편은 작품 전체, 장편은 본문이 없는 첫 아크), 'arc:3' 그 아크, 'next' 다음 아크 기획."""
    target: str = ""
    act: str = ""  # 화면에서 연 구간 이름 (기 · 승 · 전 · 결)
    episode: int = 0  # 화면에서 연 화
    mode: Literal["", "options"] = ""  # options: 변경안 대신 방향 여러 안을 받는다
    draft: Optional[ArcProposal] = None  # target 'next': 화면에 있는 다음 아크 초안 (적용 전)


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


# 'plot'(기승전결 · 플롯 화면), 'text:<화>'(집필 화면의 본문 부분 수정), 'style'(문체 화면), 'setup'(설정 도우미). web._chat 이 검사한다
ChatTopic = str


class ForeshadowDue(BaseModel):
    """복선 하나의 회수 예정 화 (플롯 대화 적용 취소용)."""
    id: str
    due_ep: Optional[int] = None


class PlotUndo(BaseModel):
    """플롯 대화 변경안을 적용하기 전이나 뒤의 값 (적용 취소용, AI 가 채우지 않는다).
    episodes 는 적용 전이면 바뀌거나 빠진 화, 적용 뒤면 바뀐 화다. 적용 전에 없던 화(새 화)는 적용 전 쪽에 없다."""
    target_episodes: int = 0
    acts: list[Act] = Field(default_factory=list, description="단편 기승전결 구조")
    arc: Optional[StoryArc] = Field(None, description="장편: 변경안이 겨냥한 아크")
    parts: list[Part] = Field(default_factory=list)
    foreshadows: list[ForeshadowDue] = Field(default_factory=list, description="아직 회수하지 않은 복선의 회수 예정 화")
    episodes: list["Episode"] = Field(default_factory=list)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    revision: Optional[PlotRevision] = Field(None, description="assistant 가 낸 플롯 변경안")
    passage: Optional[PassageRevision] = Field(None, description="assistant 가 낸 본문 부분 수정 후보")
    style: Optional[StyleRevision] = Field(None, description="assistant 가 낸 문체 변경안")
    style_before: Optional[StyleProfile] = Field(None, description="문체 대화: 변경안을 적용하기 전 작품 문체 (적용 취소용)")
    setup: Optional[SetupRevision] = Field(None, description="assistant 가 낸 설정 변경안이나 방향 여러 안")
    setup_before: Optional[SetupBefore] = Field(None, description="설정 대화: 변경안을 적용하기 전 설정 (적용 취소용)")
    plot_before: Optional[PlotUndo] = Field(None, description="플롯 대화: 변경안을 적용하기 전 값 (적용 취소용)")
    plot_after: Optional[PlotUndo] = Field(None, description="플롯 대화: 변경안을 적용한 직후 값. 그 뒤에 다시 고친 부분은 취소할 때 남긴다")
    episode: int = Field(0, description="문체 대화: 작가가 참고하라고 고른 화")
    selection: Optional[Selection] = Field(None, description="본문 부분 수정: 고친 대상")
    preset: str = Field("", description="본문 부분 수정: 고른 빠른 요청 (prompts.PASSAGE_PRESETS)")
    outcome: Literal["", "applied", "dismissed"] = Field("", description="변경안을 반영했는지, 버렸는지")
    applied: list[str] = Field(default_factory=list, description="반영한 부분: 'acts' 구조, 'arc' 아크 칸, 'parts' 부 구성, 화 번호. 본문 수정이면 후보 번호(0부터), 문체 대화면 칸 이름, "
                                                                 "설정 대화면 부분 id (setupchat.part_ids)")
    target: str = Field("", description="플롯 대화: 변경안이 겨냥한 곳 (ChatScope.target, 기본이면 기록할 때의 실제 대상)")
    where: str = Field("", description="플롯 대화: 작가가 보낼 때 보고 있던 곳 (예: 아크 3 · 승 구간 · 15화)")
    mode: str = Field("", description="플롯 · 설정 대화: 'options' 면 방향 여러 안을 청한 말")
    at: str = ""


class Chat(BaseModel):
    """화면별 대화 기록. 플롯 화면은 'plot', 본문 부분 수정은 화마다 'text:<화>', 문체 화면은 'style', 설정 도우미는 'setup'."""
    topic: ChatTopic
    messages: list[ChatMessage] = Field(default_factory=list)


# ---------- 대화 에이전트 (canon/agent.py) ----------
# 대화로 다듬기를 세션 단위로 둔다. AI 는 한 턴에 도구를 몇 번 부르고, 권한 모드 안의 쓰기는 바로 저장하며, 나머지는 작가에게 묻는다.

AgentMode = Literal["ask", "draft", "all"]  # 물어보기 · 빈 곳 · 초안만 자동 · 모두 자동


class ToolArg(BaseModel):
    name: str = Field(description="인자 이름")
    value: str = Field("", description="인자 값")


class PlotAgentStep(BaseModel):
    """플롯 대화 에이전트의 한 단계. 도구 하나를 부르거나, tool 을 비우고 reply 로 턴을 끝낸다 (agent.run_turn)."""
    thought: str = Field("", description="작가에게 보일 한 줄: 이 단계에서 무엇을 왜 하는지")
    tool: str = Field("", description="부를 도구 이름 ([도구] 목록에 있는 것). 비우면 reply 로 턴을 끝낸다")
    args: list[ToolArg] = Field(default_factory=list, description="읽기 도구의 인자")
    edit: PlotRevision = Field(default_factory=lambda: PlotRevision(reply=""),
                               description="edit_plot 일 때만: 바꿀 것만 채운 변경안. reply 는 한 줄 설명. 다른 도구면 비워 둔다")
    question: str = Field("", description="ask 일 때만: 작가에게 묻는 말")
    options: list[Direction] = Field(default_factory=list, description="ask 일 때만: 고를 방향 2~3개 (방향을 물을 때)")
    reply: str = Field("", description="tool 이 비었을 때: 작가에게 하는 답 2~5문장. 무엇을 바꿨고 무엇을 물었는지")


class StepRecord(BaseModel):
    """턴의 한 단계 (화면의 단계 줄). result 는 다음 단계 프롬프트에 넣는 결과로, 턴이 끝나면 비운다."""
    kind: Literal["read", "write", "wait", "block", "ask", "note"] = "read"
    tool: str = ""
    label: str = Field("", description="화면에 보일 대상 (예: '25~30화')")
    why: str = Field("", description="작은 글: AI 의 생각이나 막힌 까닭")
    result: str = ""


class WriteItem(BaseModel):
    """바로 쓴 것 한 부분. key 는 'parts' · 'arc' · 'acts' · 'draft'(다음 아크 초안) · 화 번호."""
    key: str
    label: str = ""
    state: Literal["done", "reverted", "kept"] = "done"
    reason: str = Field("", description="kept 일 때: 되돌리지 않은 까닭")


class WriteRecord(BaseModel):
    """한 번에 쓴 것. 되돌리기는 before · after 로 지금 값이 쓴 직후 값과 같은 부분만 돌린다 (pipeline.plot_undo)."""
    tool: str = "edit_plot"
    target: str = Field("", description="ChatScope.target: 쓸 때의 대상")
    revision: Optional[PlotRevision] = Field(None, description="쓴 부분이 들어 있는 변경안 (다음 아크 초안을 화면에 놓을 때 쓴다)")
    items: list[WriteItem] = Field(default_factory=list)
    before: Optional[PlotUndo] = None
    after: Optional[PlotUndo] = None


class Approval(BaseModel):
    """권한 모드 밖이라 작가에게 묻는 쓰기. 승인하면 고른 부분만 쓰고 같은 턴을 이어 간다."""
    tool: str = "edit_plot"
    target: str = ""
    revision: Optional[PlotRevision] = None
    keys: list[str] = Field(default_factory=list, description="묻는 부분 ('parts' · 'arc' · 'acts' · 화 번호)")
    kinds: list[str] = Field(default_factory=list, description="묻는 까닭이 된 종류 (agent.KIND_LABELS). '이 세션에서 묻지 않기'가 auto_kinds 에 더한다")
    state: Literal["wait", "approved", "denied"] = "wait"
    picked: list[str] = Field(default_factory=list)


class AskCard(BaseModel):
    """되묻기 (방향 여러 안 포함). 작가가 답하면 새 턴이 된다."""
    question: str = ""
    options: list[Direction] = Field(default_factory=list)


class AgentTurn(BaseModel):
    user: str = ""
    mode: str = Field("", description="'options': 방향 여러 안으로 물어 달라고 한 말")
    where: str = Field("", description="작가가 보낼 때 보고 있던 곳 (pipeline.chat_where)")
    act: str = ""
    episode: int = 0
    draft: Optional[ArcProposal] = Field(None, description="다음 아크 대상일 때 보낼 때의 화면 초안")
    steps: list[StepRecord] = Field(default_factory=list)
    reply: str = ""
    writes: list[WriteRecord] = Field(default_factory=list)
    approval: Optional[Approval] = None
    ask: Optional[AskCard] = None
    end: Literal["", "done", "wait", "ask", "cap", "stopped", "error"] = Field("", description="'' 은 돌아가는 중")
    error: str = ""
    job: str = Field("", description="이 턴을 돌리는 작업 id")
    at: str = ""


class AgentSession(BaseModel):
    """대화 세션. 주제(topic)마다 여럿 둘 수 있고, 기본 대상(target)과 권한 모드를 기억한다."""
    id: str
    topic: ChatTopic = "plot"
    title: str = ""
    target: str = Field("", description="ChatScope.target: '' 기본, 'arc:N', 'next'")
    mode: AgentMode = "draft"
    auto_kinds: list[str] = Field(default_factory=list, description="승인 카드에서 '이 세션에서 묻지 않기'로 고른 종류")
    archived: bool = False
    turns: list[AgentTurn] = Field(default_factory=list)
    created: str = ""
    updated: str = ""


# ---------- 검수 ----------

IssueType = Literal["사실", "시간", "인물 정보", "말투", "세계관", "플롯", "동선", "시점"]
Severity = Literal["crit", "mid", "low"]
SEVERITY: dict[str, str] = {"crit": "치명", "mid": "보통", "low": "사소"}


class ConsistencyIssue(BaseModel):
    type: IssueType = Field(description="사실: 확정 사실·세부 모순 / 시간: 순서·인과 / 인물 정보: 모르는 것을 앎 / 말투 / 세계관 규칙 / 플롯: 사건 누락 / 동선: 한 장면 안에서 위치·몸이 향한 쪽·자세·손에 든 것·가려진 곳이 행동 없이 바뀜 / 시점: 시점 인물이 볼 수 없거나 모르는 것을 서술, 1인칭의 나가 다른 인물로 바뀜, 표시 없이 시점 인물이 바뀜")
    description: str = Field(description="무엇이 어긋났는지 한 문장")
    source_episode: int = Field(0, description="앞선 근거가 나온 화. 설정·확정 사실·인물 상태가 근거면 0, 같은 화 앞 문장이면 이번 화")
    source_quote: str = Field(description="앞선 근거 원문 그대로 (설정이면 해당 설정 문장)")
    current_quote: str = Field(description="이번 화에서 어긋난 문장 원문 그대로")
    suggestion: str = Field("", description="고치는 방법 제안")
    severity: Severity = Field("mid", description="crit: 독자가 바로 알아챌 모순이거나 뒤 화 전개를 흔듦 / mid: 눈여겨 읽으면 보이는 어긋남 / low: 사소한 세부")
    # 프로그램이 채운다 (LLM 응답 형식에서 뺀다). 장면 연출 규칙 판정(stage.to_issues)이 낸 지적은 rule
    origin: SkipJsonSchema[Literal["ai", "rule"]] = Field("ai", description="ai: 검수 모델 / rule: 장면 연출 규칙 판정")
    stage_event: SkipJsonSchema[int] = Field(-1, description="규칙 지적의 플롯 사건 번호 (0부터). 장면 연출 화면 링크")
    stage_beat: SkipJsonSchema[int] = Field(0, description="규칙 지적의 본문 장면 박자 (1부터)")


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


class PlantedContradiction(BaseModel):
    """검수 시험: 본문에 일부러 심는 모순 하나. 연구 화면에서만 쓰고 작품에는 저장하지 않는다."""
    quote: str = Field(description="이번 화 본문에서 바꿀 문장 원문 그대로 (한 문장)")
    replacement: str = Field(description="앞선 근거와 어긋나게 바꾼 문장. 같은 문체, 비슷한 길이")
    type: IssueType = Field("사실", description="어떤 종류의 모순인지")
    part: Literal["", "몸", "접촉", "물건"] = Field("", description="type 이 동선일 때만: 몸(한 인물의 위치 · 몸이 향한 쪽 · 자세 · 가려진 곳) / 접촉(두 인물이 맞닿은 상태, 그동안 쓸 수 있는 손) / 물건(인물과 가방 · 무기 · 문 같은 물건의 상태, 옷과 멘 것의 겹침 순서, 밀착한 몸 사이의 자리). 동선이 아니면 빈칸")
    source_episode: int = Field(0, description="어긋나는 근거가 나온 화. 설정 · 확정 사실이면 0, 같은 화 앞 문장이면 이번 화")
    source_quote: str = Field("", description="어긋나는 근거 원문 그대로")


PLANT_PARTS = ["몸", "접촉", "물건"]


def plant_kind(x: PlantedContradiction) -> str:
    """검수 시험 집계에 쓰는 갈래. 동선은 몸 · 접촉 · 물건으로 나눈다 (갈래를 비우면 몸)."""
    return f"동선 · {x.part or '몸'}" if x.type == "동선" else x.type


class PlantSet(BaseModel):
    items: list[PlantedContradiction] = Field(default_factory=list)


class Claim(BaseModel):
    """두 걸음 검수 1단계: 이번 화 본문에서 뽑은 사실 진술 하나. 판단기가 옛 내용과 맞는지 따로 본다."""
    quote: str = Field(description="이번 화 본문의 문장 원문 그대로 (한 문장)")
    claim: str = Field(description="그 문장이 단정하는 사실을 짧은 평서문 하나로. 인물은 이름으로 쓴다")


class ClaimSet(BaseModel):
    claims: list[Claim] = Field(default_factory=list)


class ConsistencyReport(BaseModel):
    """본문 검수 결과. 상태를 바꾸지 않는 참고용 경고라 승인 없이 저장한다."""
    episode: int
    issues: list[ConsistencyIssue] = Field(default_factory=list, description="근거가 분명한 모순만. 없으면 빈 목록")
    # 검수 때 뽑은 본문 장면 (pipeline.stage_extract_all, StageProposal). apply_check 가 장면에 넣고 규칙 판정을 합친다.
    # 작가가 손본 본문 장면을 덮지 않아 넣지 못한 것은 _stage_held (웹은 장면 연출 화면의 비교로 남긴다)
    _stage: list = PrivateAttr(default_factory=list)
    _stage_held: list = PrivateAttr(default_factory=list)


EditSource = Literal["manual", "ai", "typed", "impact", "fix"]


class TextEdit(BaseModel):
    """본문 부분 수정 기록. 되돌리기에 쓰고, 고치기 전후 쌍은 나중에 선호 · 미세 조정 자료로 쓸 수 있게 남긴다."""
    id: str
    at: str = ""
    source: EditSource = Field("manual", description="manual: 고른 부분을 직접 고침 / ai: AI 후보를 고름 / typed: 본문을 직접 고쳐 저장 / impact: 인과율 영향 분석의 본문 수정 / fix: 검수 지적의 고침안")
    group: str = Field("", description="한 번에 넣은 수정 묶음 id (검수 고침안의 주 문장과 딸린 곳). 되돌리기도 묶음으로 한다")
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


FindingStatus = Literal["open", "fixed", "kept", "wrong"]
FINDING_STATUS: dict[str, str] = {"open": "열림", "fixed": "고침", "kept": "그대로 둠", "wrong": "잘못 짚음"}


class FixPatch(BaseModel):
    """고침안이 함께 고치는 이 화의 다른 문장 하나 (딸린 곳)."""
    quote: str = Field(description="함께 바꿀 이 화 본문 문장을 원문 그대로 (한두 문장)")
    replacement: str = Field(description="고침안과 맞게 최소로 고친 문장")
    reason: str = Field("", description="왜 함께 바꿔야 하는지 한 문장")


class FixOption(BaseModel):
    """지적 하나의 고침안: 지적한 문장을 대신할 글과, 그 때문에 함께 고칠 이 화의 다른 문장."""
    label: str = Field(description="고침안 이름 2~8자 (예: 오른손으로 바꾸기)")
    text: str = Field(description="지적한 문장(current_quote)을 대신할 새 글. 앞뒤 본문은 되풀이하지 않는다")
    note: str = Field("", description="무엇을 어떻게 바꿨는지 한 줄")
    extra: list[FixPatch] = Field(default_factory=list, description="이 고침 때문에 함께 바꿔야 하는 이 화의 다른 문장. 없으면 빈 목록")


class FixSet(BaseModel):
    """검수 지적 하나의 AI 고침안. 작가가 하나를 골라야 본문에 들어간다 (pipeline.apply_fix)."""
    reply: str = Field("", description="작가에게 하는 짧은 답 1~2문장. 고침안들이 어떻게 다른지")
    options: list[FixOption] = Field(default_factory=list, description="2~3개, 서로 다른 방향으로 고친 안")


class FindingRecheck(BaseModel):
    """지적 하나만 다시 검수한 결과. 회차를 늘리지 않는다 (pipeline.recheck_finding)."""
    resolved: bool = Field(description="지적한 어긋남이 지금 본문에서 풀렸는지")
    reason: str = Field(description="그렇게 본 까닭 한두 문장. 풀리지 않았으면 무엇이 아직 어긋나는지")
    new_issues: list[ConsistencyIssue] = Field(default_factory=list, description="작가가 고친 문장 때문에 새로 어긋난 곳만. 원래 있던 다른 어긋남은 넣지 않는다")


FindingEventKind = Literal["found", "again", "gone", "author", "fix", "undo", "recheck"]


class FindingEvent(BaseModel):
    """지적의 처리 기록 한 줄 (화면의 처리 기록)."""
    at: str = ""
    kind: FindingEventKind
    text: str = ""


class Finding(ConsistencyIssue):
    """검수 세션에 남는 지적 하나. 다시 검수해도 작가가 정한 상태와 메모를 지킨다 (findings.merge).
    LLM 이 채우지 않는다."""
    id: str = ""
    status: FindingStatus = Field("open", description="open: 열림 / fixed: 고침 / kept: 그대로 둠 / wrong: 잘못 짚음")
    note: str = Field("", description="작가 메모 (그대로 두거나 잘못 짚었다고 본 이유)")
    first: int = Field(1, description="처음 짚은 회차")
    last: int = Field(1, description="마지막으로 짚은 회차. 마지막 회차보다 작으면 그 회차가 짚지 않은 것")
    closed_by: Literal["", "author", "recheck", "one"] = Field(
        "", description="author: 작가가 정함 / recheck: 다시 검수에서 문장이 사라져 고침 / one: 이 지적만 다시 검수해 풀림")
    decided_at: str = ""
    severity_by_author: bool = Field(False, description="작가가 심각도를 바꿨다. 다시 검수해도 AI 값으로 덮지 않는다")
    parent: str = Field("", description="딸린 지적: 이 지적을 낳은 지적 id (그 지적을 고친 문장 때문에 새로 어긋남)")
    fixes: list[FixOption] = Field(default_factory=list, description="마지막으로 받은 AI 고침안")
    fixes_basis: str = Field("", description="고침안을 받을 때 본문 지문 (pipeline.text_basis). 지금 본문과 다르면 오래된 고침안")
    fix_group: str = Field("", description="마지막으로 적용한 고침안의 수정 묶음 id (TextEdit.group)")
    log: list[FindingEvent] = Field(default_factory=list, description="처리 기록 (최근 것만)")


CheckSource = Literal["api", "chat", "auto"]


class CheckRound(BaseModel):
    """검수 회차 하나: 한 번 검수한 결과를 지적 목록에 합친 기록."""
    no: int
    at: str = ""
    basis: str = Field("", description="검수한 본문의 지문 (pipeline.text_basis). 비면 모름 (옛 작품)")
    source: CheckSource = Field("api", description="api: 화면 · 명령줄 검수 / chat: 채팅 앱에서 받은 JSON / auto: 자동 집필")
    widen: bool = Field(False, description="넓혀 찾기를 함께 했는지")
    stage: bool = Field(False, description="장면 연출 규칙 판정을 함께 넣었는지 (본문 장면이 있는 사건이 하나라도)")
    found: int = Field(0, description="이 회차가 짚은 수")
    added: int = Field(0, description="그중 새 지적")
    kept_again: int = Field(0, description="그중 그대로 둠 · 잘못 짚음으로 정해 둔 지적 (상태는 그대로)")
    added_ids: list[str] = Field(default_factory=list, description="이 회차에 새로 나온 지적 id")
    again_ids: list[str] = Field(default_factory=list, description="이 회차가 다시 짚은 옛 지적 id")
    gone_ids: list[str] = Field(default_factory=list, description="이 회차에 문장이 사라져 고침으로 닫은 지적 id")
    superseded: bool = Field(False, description="이 회차 뒤에 본문을 새 판으로 바꿨다 (화면의 '새 판' 구분선)")


class ToFix(BaseModel):
    """작가가 본문 문장에 단 '고칠 곳' 표시 (tofix.py). 본문은 바꾸지 않고 프롬프트에도 넣지 않는다.
    자동 집필이 도는 동안에도 달 수 있다. LLM 이 채우지 않는다."""
    id: str = ""
    quote: str = Field("", description="표시한 본문 글")
    note: str = Field("", description="작가 메모 (무엇이 어색한지)")
    start: int = Field(0, description="표시할 때 글이 있던 자리. 같은 글이 여럿이면 이 자리에 가까운 것을 짚는다")
    status: Literal["open", "done"] = Field("open", description="open: 남음 / done: 고침")
    at: str = Field("", description="표시한 시각")
    done_at: str = Field("", description="고침으로 바꾼 시각")


# ---------- 장면 연출 (canon/stage.py, docs/stage/) ----------
# 작가 자료라 스냅샷 · 반영 취소 대상이 아니다. 좌표는 방 · 기준점에만 있고 인물 자리는 기준점 + 관계 말이다.

class StageAnchor(BaseModel):
    """방 안의 기준점: 가구 · 문 · 창. 자리 단위는 m, 방 왼쪽 위가 0."""
    id: str
    name: str
    kind: str = Field("other", description="bed · door · window · desk · chair · sofa · table · wall · seat · vehicle · landmark · ground · other (stage.ANCHOR_KINDS)")
    x: float = 0
    y: float = 0
    w: float = 0.5
    h: float = 0.5
    rot: int = Field(0, description="앞쪽 방향: 0 아래(+y) · 90 왼쪽 · 180 위 · 270 오른쪽 (평면도 기준)")
    sit: bool = False
    lie: bool = False
    parent: str = Field("", description="붙은 곳: 기준점 id, 방 벽이면 'room'. 비면 붙지 않음 (stage.resolve). 붙으면 x · y · w · h · rot 는 부모 기준이다")
    face: str = Field("", description="붙은 면: 기준점이면 inside · top · front · back · left · right, 방 벽이면 n · e · s · w (stage.FACES · WALLS)")


class StageRoom(BaseModel):
    """장면이 벌어지는 방. 지도 장소에 묶으면 여러 장면이 다시 쓴다."""
    id: str
    name: str
    place: str = Field("", description="지도 장소 이름 (atlas.places). 비면 장면 전용 방")
    template: str = Field("", description="고른 틀 id (stage.ROOMS)")
    w: float = 4.0
    h: float = 3.0
    anchors: list[StageAnchor] = Field(default_factory=list)
    attached: bool = Field(False, description="옛 방의 붙은 곳 짐작(stage.attach_guess)을 마친 방")
    _world: bool = PrivateAttr(False)  # stage.resolve 가 세계 좌표로 푼 사본. 저장하지 않는다

    @model_validator(mode="after")
    def _guess(self):
        if not self.attached:
            from . import stage  # 순환 import 를 피해 늦게 읽는다
            stage.attach_guess(self)
        return self


class StageSpot(BaseModel):
    ref: str = Field(description="기준점 id, 또는 '@' + 인물 id")
    rel: str = Field("beside", description="on · in · front · back · left · right · beside (stage.RELS)")


class StageContact(BaseModel):
    id: str
    by: str = Field(description="left · right · both, 또는 손 아닌 부위 id (stage.PARTS)")
    to: str = Field(description="닿는 인물 id")
    part: str = Field(description="닿는 부위 id (stage.PARTS)")
    act: str = Field(description="접촉 동작 id (stage.ACTS)")


class StageBody(BaseModel):
    """한 인물의 상태. 시작 상태는 모든 칸, 박자는 바뀐 칸만 (None · 빈칸은 앞 그대로)."""
    who: str = Field(description="인물 id")
    at: Optional[StageSpot] = None
    posture: str = Field("", description="자세 id (stage.POSTURES)")
    facing: str = Field("", description="8방향(n ne e se s sw w nw), '@' + 인물 id, '#' + 기준점 id")
    left: Optional[str] = Field(None, description="왼손에 쥔 것. 빈칸은 빈손, '?' 는 모름, None 은 앞 그대로")
    right: Optional[str] = Field(None, description="오른손에 쥔 것 (left 와 같은 규칙)")
    contacts: list[StageContact] = Field(default_factory=list, description="이 박자에 새로 시작한 접촉")
    ends: list[str] = Field(default_factory=list, description="이 박자에 끝난 접촉 id")
    memo: str = Field("", description="고정 목록 밖의 것")


class StageBeat(BaseModel):
    quote: str = Field("", description="본문 문장 원문 (쓰기 전에는 빈칸)")
    note: str = Field("", description="작가 한 줄 설명")
    bodies: list[StageBody] = Field(default_factory=list, description="바뀐 인물만")


class StageScene(BaseModel):
    """플롯 사건 하나의 장면 연출."""
    id: str
    event: int = Field(0, description="플롯 사건 번호 (0부터)")
    event_text: str = Field("", description="사건 글 사본. 사건을 찾을 때 번호보다 먼저 본다 (stage.find_event)")
    room: str = Field("", description="StageRoom.id")
    cast: list[str] = Field(default_factory=list, description="인물 id")
    start: list[StageBody] = Field(default_factory=list, description="시작 상태: 인물마다 모든 칸")
    beats: list[StageBeat] = Field(default_factory=list)
    source: Literal["manual", "plot", "text"] = Field("manual", description="마지막으로 통째 적용한 출처: 작가 · 플롯 초안 · 본문 추출")
    basis: str = Field("", description="본문에서 뽑았을 때 본문 지문 (pipeline.text_basis)")
    prompt: bool = Field(True, description="쓰기 프롬프트에 넣기")
    role: Literal["plan", "text"] = Field("plan", description="계획 장면(쓰기 전 작가가 짠 것) · 본문 장면(본문에서 뽑은 것). 한 사건에 역할마다 하나")
    prev: Optional["StageScene"] = Field(None, description="마지막 AI 적용 전 장면 (적용 취소 한 번)")
    room_prev: Optional[StageRoom] = Field(None, description="마지막 AI 적용이 기준점을 더한 공용 방의 적용 전 모습 (적용 취소가 되돌린다)")
    room_made: str = Field("", description="마지막 AI 적용이 새로 만든 방 id (적용 취소 때 다른 장면이 쓰지 않으면 뺀다)")


# LLM 이 채우는 장면 연출 (pipeline.draft_stage · extract_stage). 이름으로 적고 stage.from_draft 가 id 로 바꾼다. dict 필드를 쓰지 않는다.

class DraftContact(BaseModel):
    by: str = Field(description="닿게 한 쪽: left · right · both (손), 또는 손 아닌 부위 id")
    to: str = Field(description="닿는 인물 이름")
    part: str = Field(description="닿는 부위 id (부위 목록)")
    act: str = Field(description="접촉 동작 id (접촉 동작 목록)")


class DraftEnd(BaseModel):
    to: str = Field(description="끝난 접촉의 대상 인물 이름")
    part: str = Field(description="끝난 접촉의 부위 id")


class DraftBody(BaseModel):
    """한 인물의 상태. 박자에는 바뀐 칸만 적고 나머지는 빈칸으로 둔다."""
    name: str = Field(description="인물 이름 (등장 인물 목록 그대로)")
    at_ref: str = Field("", description="자리의 기준: 기준점 이름, 또는 인물 이름. 바뀌지 않았거나 모르면 빈칸")
    at_rel: str = Field("", description="자리 관계 id (관계 목록). at_ref 가 있을 때만")
    posture: str = Field("", description="자세 id (자세 목록). 바뀌지 않았거나 모르면 빈칸")
    facing: str = Field("", description="향한 쪽: 8방향 id, 또는 인물 이름 · 기준점 이름. 바뀌지 않았거나 모르면 빈칸")
    left: str = Field("", description="왼손에 쥔 것. 바뀌지 않았으면 빈칸, 빈손이 되면 '빈손', 모르면 '?'")
    right: str = Field("", description="오른손에 쥔 것 (left 와 같은 규칙)")
    contacts: list[DraftContact] = Field(default_factory=list, description="이 박자에 새로 시작한 접촉")
    ends: list[DraftEnd] = Field(default_factory=list, description="이 박자에 끝난 접촉")
    memo: str = Field("", description="목록에 없는 것을 짧게")


class DraftAnchor(BaseModel):
    """방에 없는 장소를 기준점으로 더하자는 제안. 자리는 다른 기준점과의 관계 말로만 적고 좌표는 코드가 정한다 (stage.place_anchors)."""
    name: str = Field(description="기준점 이름 (박자 자리 at_ref 에 이 이름을 그대로 씀)")
    kind: str = Field("other", description="기준점 종류 id (기준점 종류 목록)")
    near: str = Field("", description="가까이 있는 기준점 이름: 방에 있는 것이나 이 목록 앞에 적은 것. 모르면 빈칸")
    rel: str = Field("", description="near 에서 본 이 기준점의 쪽: front · back · left · right · beside (near 가 있을 때만)")
    part: bool = Field(False, description="near 의 한 부분이면 참 (차의 짐칸 · 트렁크 · 보닛 · 운전석, 가구의 서랍처럼). 코드가 near 에 붙인다")


class DraftBeat(BaseModel):
    quote: str = Field("", description="본문에서 뽑을 때: 이 박자를 정한 본문 문장 원문 그대로 한 문장. 쓰기 전 초안이면 빈칸")
    note: str = Field("", description="이 박자에 일어나는 일 한 줄")
    bodies: list[DraftBody] = Field(description="바뀐 인물만")


class StageDraft(BaseModel):
    """플롯 사건 하나의 장면 연출 초안 또는 본문에서 뽑은 장면. 좌표는 적지 않는다."""
    room: str = Field("", description="방: 방 목록의 이름 또는 방 틀 id. 방이 정해져 있으면 빈칸")
    # 기본값을 두지 않는다: 기본값이 있으면 응답 형식에서 필수가 빠져 Gemini 가 beats 를 통째로 건너뛴다 (2026-10-29 측정)
    cast: list[str] = Field(description="이 장면에 나오는 인물 이름")
    start: list[DraftBody] = Field(description="시작 상태: 인물마다 아는 칸을 모두")
    beats: list[DraftBeat] = Field(description="박자 차례. 장면이 있으면 비우지 않는다")
    new_anchors: list[DraftAnchor] = Field(description="방에 없어 더할 기준점. 더할 것이 없으면 빈 목록")


class AnchorAdd(BaseModel):
    """방에 더할 기준점 하나와 화면에 보일 자리 말."""
    anchor: StageAnchor
    where: str = ""


class StageProposal(BaseModel):
    """AI 가 만든 장면을 정리한 결과. 적용 전에는 pending.json(웹)에 두고, 검수 때 뽑은 것은 바로 넣는다. LLM 이 채우지 않는다."""
    episode: int
    event: int
    role: Literal["plan", "text"] = "plan"
    scene: StageScene
    room: Optional[StageRoom] = Field(None, description="새로 만들 방 (이미 있는 방을 쓰면 None)")
    adds: list["AnchorAdd"] = Field(default_factory=list, description="AI 가 더하자고 한 기준점 (좌표는 코드가 정함)")
    grown: Optional[StageRoom] = Field(None, description="이미 있는 방에 adds 를 더하고 넓힌 모습 (방 id 는 그대로). 새 방이면 room 에 이미 들어 있다")
    shift_x: float = Field(0, description="grown 이 넓히며 옛 기준점을 옮긴 거리 m")
    shift_y: float = 0
    dropped: int = Field(0, description="막은 접촉 수 (미성년 인물이 낀 성적 접촉)")
    notes: list[str] = Field(default_factory=list, description="정리하며 메모로 옮기거나 뺀 것")
    at: str = ""


class Episode(BaseModel):
    plot: EpisodePlot
    status: EpisodeStatus = "draft"
    text: str = ""
    summary: str = ""
    issues: list[ConsistencyIssue] = Field(default_factory=list, description="마지막 회차의 검수 결과 그대로. 처리 상태는 findings")
    checked_at: str = Field("", description="마지막 검수 시각. 그 뒤에 본문을 고쳤으면 검수 결과가 오래된 것")
    findings: list[Finding] = Field(default_factory=list, description="검수 세션의 지적 (회차를 합친 것)")
    rounds: list[CheckRound] = Field(default_factory=list, description="검수 회차 (최근 것만)")
    edits: list[TextEdit] = Field(default_factory=list, description="본문 부분 수정 기록 (최근 것만)")
    auto: bool = Field(False, description="자동 집필이 사람 검토 없이 반영한 화. 사용자가 다시 반영하면 False")
    hook: Optional[HookReport] = Field(None, description="1~3화 흡입력 판정 (마지막 것). basis 가 지금 본문과 다르면 오래된 것")
    illustrations: list["Illustration"] = Field(default_factory=list, description="삽화 프롬프트 (NovelAI)")
    candidate: Optional[TextVersion] = Field(None, description="다시 생성으로 나와 지금 본문과 비교해 고르기를 기다리는 새 판")
    versions: list[TextVersion] = Field(default_factory=list, description="바꾸기 전 판과 고르지 않은 새 판 (최근 것만)")
    made_by: Optional[RewriteRequest] = Field(None, description="지금 본문을 만든 다시 생성 요청 (처음 쓴 판이나 직접 쓴 본문이면 비움)")
    final_text: str = Field("", description="상태 반영이 끝난 뒤 본문을 처음 고치기 직전의 본문. 지금 본문과 다르면 반영된 요약 · 상태가 고치기 전 본문 기준이다. 다시 맞추거나 그대로 두기로 하면 비운다")
    time: "StoryTime" = Field(default_factory=lambda: StoryTime(), description="이 화가 끝난 작품 속 시점. 상태 반영 때 채운다")
    realign: str = Field("", description="앞 화 플롯을 뒤 화에 맞추지 않고 다시 짜면서 이 화와 어긋나게 된 점. 이 화 플롯을 다시 짜거나 작가가 확인하면 비운다")
    opening_prev: Optional[EpisodePlot] = Field(None, description="1~3화 여는 방식 안을 처음 고르기 전 플롯 (되돌리기용). 되돌리면 비운다")
    events_done: list[str] = Field(default_factory=list, description="집필 화면 플롯 띠에서 작가가 다 썼다고 체크한 사건의 글. 사건 글을 고치면 그 체크는 풀린다. 프롬프트에 넣지 않는다")
    to_fix: list[ToFix] = Field(default_factory=list, description="작가가 본문에 단 '고칠 곳' 표시. 프롬프트에 넣지 않는다")
    stage: list[StageScene] = Field(default_factory=list, description="플롯 사건마다 짠 장면 연출 (canon/stage.py). 작가 자료라 스냅샷에 넣지 않는다")
    storyboard: Optional["Storyboard"] = Field(None, description="쓰기 재료: 장면 순서와 이번 화 확정 값 (pipeline.make_storyboard). 상태 승인 대상이 아니다")
    cue_sheet: Optional["CueSheet"] = Field(None, description="쓰기 재료: 큐 시트 (pipeline.make_cue_sheet, cue.set_episode). 쓰기 프롬프트 끝에 넣는다 (prompts.cue_write_block). 상태 승인 대상이 아니다")

    @model_validator(mode="after")
    def _old_check(self) -> "Episode":
        # 검수 세션 전 작품: 마지막 검수 결과를 1회차의 열린 지적으로 옮긴다 (본문 지문은 모른다)
        if self.issues and not self.findings and not self.rounds:
            self.findings = [Finding(**x.model_dump(), id=f"f{k}") for k, x in enumerate(self.issues, 1)]
            self.rounds = [CheckRound(no=1, at=self.checked_at, found=len(self.issues), added=len(self.issues))]
        return self


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
    attire: str = Field("", description="지금 차림: 옷, 몸에 남은 상처 · 얼룩 · 찢어짐, 지니고 다니는 물건. 변경안에는 바뀐 인물만, 이어지는 것까지 다시 적는다")
    knows: list[str] = Field(default_factory=list, description="이 인물이 알게 된 핵심 정보")
    notes: str = ""
    stats: list[StatValue] = Field(default_factory=list, description="상태창 수치. 작가가 상태창을 만든 인물만. 변경안에는 바뀐 항목만 넣는다")
    # 아크 요약 뒤 오래된 knows 를 접은 줄 (canon/knows.py). 작가가 고른 AI 제안만 들어온다. AI 응답 형식과 프롬프트 직렬화에서는 뺀다
    knows_folded: SkipJsonSchema[list[str]] = Field(default_factory=list, description="접은 아는 정보 (knows.apply_fold)")

    @model_serializer(mode="wrap")
    def _prompt_view(self, handler: SerializerFunctionWrapHandler, info: SerializationInfo):
        """프롬프트용 직렬화(llm.dump 의 context prompt)에서는 접은 줄 칸을 뺀다. 프롬프트는 knows.view 가 접은 줄을 knows 앞에 붙인다."""
        data = handler(self)
        if isinstance(data, dict) and info.context and info.context.get("prompt"):
            data.pop("knows_folded", None)
        return data


class Foreshadow(BaseModel):
    id: str = Field(description="예: fs-03-locket")
    description: str
    planted_ep: int
    payoff_ep: Optional[int] = None
    status: Literal["open", "resolved"] = "open"
    scope: Literal["arc", "part", "series"] = Field("arc", description="회수 범위: arc 이번 아크 안 / part 이번 부 안 / series 작품 끝까지 가는 큰 복선")
    due_ep: Optional[int] = Field(None, description="회수 예정 화. 정하지 않았으면 비움")


class StoryTime(BaseModel):
    """작품 속 시점. 날수는 1화가 시작한 날을 1일째로 센다 (timeline.py)."""
    day: int = Field(0, description="1화가 시작한 날을 1일째로 센 날수. 모르면 0")
    part: str = Field("", description="시간대 (새벽, 아침, 낮, 오후, 저녁, 밤, 한밤) 또는 '오후 3시쯤'")
    label: str = Field("", description="본문이나 기준에서 드러난 날짜 · 요일 · 계절 (예: 3월 5일 화요일, 늦봄). 모르면 비움")


class Deadline(BaseModel):
    """작품 속 기한: 축제, 결혼식, 계약 만료, 사흘 안에 갚을 빚처럼 앞으로 올 날."""
    id: str = Field(description="예: dl-05-festival")
    what: str = Field(description="무엇의 기한인지 한 줄 (예: 왕성 축제 첫날, 빚 갚을 날)")
    day: int = Field(0, description="그 일이 오는 날의 날수 (StoryTime.day 와 같은 셈). 모르면 0")
    note: str = Field("", description="본문에 나온 말 그대로 (예: 사흘 뒤 자정까지)")
    set_ep: int = Field(0, description="기한이 생긴 화. 프로그램이 채운다")
    done_ep: int = Field(0, description="기한이 닫힌 화 (그날이 와서 일이 일어났거나 없어짐). 열려 있으면 0. 프로그램이 채운다")


class Timeline(BaseModel):
    """작품 속 시간: 화가 끝난 시점(Episode.time)과 기한을 기록해 쓰기 · 검수 프롬프트에 넣는다."""
    enabled: bool = Field(True, description="켜면 상태 변경안에 이 화가 끝난 시점과 기한을 적고, 쓰기 · 검수에 시간 블록을 넣는다")
    start: str = Field("", description="1일째가 언제인지 글로 (예: 늦겨울, 왕국력 312년). start_date 가 없으면 여기 적은 날짜 · 요일을 읽는다")
    start_date: str = Field("", description="1일째 날짜 YYYY-MM-DD. 있으면 화마다 날짜로 보이고 날짜 · 요일 · 남은 날을 Canon 이 계산한다. 비면 날수(며칠째)로 센다")
    deadlines: list[Deadline] = Field(default_factory=list)


# ---------- 화별 스토리보드 ----------
# 플롯과 집필 사이에 두는 쓰기 재료 (pipeline.make_storyboard). 직전 화를 반영한 뒤 쓰기 바로 전에 만든다.
# 장면 순서와 이번 화 확정 값만 담고 대사 · 본문 문장은 담지 않는다. 상태 변경안이 아니라 상태 승인 대상이 아니다.
# 바뀐 양만 적고 날수 · 수치 결과 · 창 글은 Canon 이 매번 센다 (prompts.board_block). 화 번호를 품은 칸은 두지 않는다.

BoardWarnKind = Literal["plot_vs_state", "plot_vs_text", "time", "setting", "next_plot"]


class BoardScene(BaseModel):
    """장면 하나. 대사와 본문 문장은 넣지 않는다."""
    place: str = Field("", description="장소. [장소 목록]의 이름 그대로. 목록에 없으면 새 이름")
    spot: str = Field("", description="그 장소 안 자리 (예: 부두 끝 창고, 마차 안)")
    time: str = Field("", description="장면 시각. 시간대나 '해 뜨기 약 40분 전' 처럼")
    present: list[str] = Field(default_factory=list, description="이 장면에 함께 있는 인물 id")
    events: list[int] = Field(default_factory=list, description="이 장면이 맡는 이번 화 플롯 events 번호 (1부터)")
    goal: str = Field("", description="장면 목표: 시점 인물이 이 장면에서 얻으려는 것")
    turn: str = Field("", description="전환점: 장면의 흐름이 바뀌는 일 한 줄")
    end_state: str = Field("", description="장면 끝 상태: 다음 장면이 이어받는 것 (자리, 물건, 감정, 결정)")


class BoardTime(BaseModel):
    """이 화의 시간. 날수는 적지 않고 Canon 이 직전 화 끝에서 이어 센다 (prompts.board_days)."""
    after: int = Field(0, description="직전 화가 끝난 때에서 며칠 뒤에 시작하는지. 같은 날 0. 회상 · 외전처럼 메인 시간 밖이면 -1")
    part: str = Field("", description="시작 시간대")
    days: int = Field(1, description="걸치는 날 수. 하루 안이면 1")
    end_part: str = Field("", description="끝나는 시간대")


class BoardStat(BaseModel):
    """상태창 수치 변화 한 단계. 단계를 차례로 쌓아 창마다 값을 Canon 이 센다 (prompts.board_steps)."""
    character_id: str = ""
    scene: int = Field(0, description="몇 번째 장면에서 바뀌는지 (1부터). 0 이면 화 끝")
    changes: list[StatValue] = Field(default_factory=list, description="바뀐 항목만. 상태 변경안과 같은 말: -0.7, +300, 13, +독 내성")
    window: bool = Field(False, description="이 순간 본문에 상태창이 뜨면 true. 뜬 창은 이 단계까지의 값을 모두 보인다")
    notice: str = Field("", description="창에 함께 뜨는 시스템 알림 한 줄. 값이 아닌 문구")


class BoardMove(BaseModel):
    """장소 이동 하나."""
    character_id: str = ""
    to: str = Field("", description="옮겨 가는 곳. [장소 목록]의 이름 그대로")
    scene: int = Field(0, description="몇 번째 장면에서 옮겨 가는지. 0 이면 장면 사이")
    ok: SkipJsonSchema[bool] = False  # 작가가 '괜찮아요'로 둔 이동. AI 응답 형식과 프롬프트에서 뺀다


class BoardAttire(BaseModel):
    character_id: str = ""
    end: str = Field("", description="화가 끝날 때 차림. 바뀐 인물만, 이어지는 상처와 물건까지 다시 적는다")
    why: str = Field("", description="바뀐 장면과 까닭")


class BoardHandover(BaseModel):
    kind: str = Field("", description="장면, 시간, 몸, 물건, 인물, 숨긴 것, 숫자, 질문 중 하나")
    text: str = Field("", description="직전 화 끝에서 이어받아야 하는 사실 한 줄. 대사를 옮기지 않는다")


class BoardWarning(BaseModel):
    kind: BoardWarnKind = "plot_vs_state"
    target: Literal["this", "next"] = Field("this", description="this: 이번 화 플롯, next: 다음 화 플롯")
    field: str = Field("", description="걸린 플롯 칸 (예: events[4], ending_hook, time)")
    text: str = Field("", description="무엇이 어긋나는지")
    resolution: str = Field("", description="이 스토리보드가 택한 처리. 플롯 칸은 바꾸지 않는다")


class StoryboardDraft(BaseModel):
    """LLM 응답 형식 (pipeline.make_storyboard)."""
    scenes: list[BoardScene] = Field(default_factory=list, description="장면 3~7개, 이번 화 events 를 빠짐없이 나눠 맡는다")
    time: BoardTime = Field(default_factory=BoardTime)
    stats: list[BoardStat] = Field(default_factory=list, description="상태창을 쓰는 작품만")
    stat_basis: list[str] = Field(default_factory=list, description="수치를 정한 근거 한 줄씩 (어느 상태 · 사실에서 셈했는지)")
    moves: list[BoardMove] = Field(default_factory=list, description="다른 장소로 옮겨 가는 인물만")
    attire: list[BoardAttire] = Field(default_factory=list)
    handover: list[BoardHandover] = Field(default_factory=list, description="직전 화 본문 끝에서 이어받을 것")
    protect: list[str] = Field(default_factory=list, description="다음 화 플롯이 전제하는 것. 이번 화에서 깨지 않는다")
    warnings: list[BoardWarning] = Field(default_factory=list)


class Storyboard(StoryboardDraft):
    """저장 형식. 계산 결과(날수, 창 값)는 저장하지 않고 화면 · 프롬프트가 매번 센다. LLM 이 채우지 않는 칸은 응답 형식에서 뺀다."""
    made_at: SkipJsonSchema[str] = ""
    made_by: SkipJsonSchema[Literal["ai", "author", "both"]] = "ai"
    basis: SkipJsonSchema[str] = Field("", description="만들 때 입력의 지문 (pipeline.board_basis). 지금 값과 다르면 낡은 것")
    checks: SkipJsonSchema[list[str]] = Field(default_factory=list, description="Canon 이 센 경고 (값 범위). AI 가 쓰지 않는다")


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


StatSkin = Literal["system", "parchment", "scroll", "neon", "plain"]


class StatWindow(BaseModel):
    """본문에 넣는 상태창 서식. {name} 은 인물 이름, {rows} 는 항목 줄들. 화면에서 상태창을 그리는 모양(창 이름 · 스킨)과 작품 틀도 둔다."""
    template: str = "【 상태창 】\n이름: {name}\n{rows}"
    row: str = "{key}: {value}"
    title: str = Field("상태창", description="화면의 상태창 머리에 보이는 창 이름 (예: 상태창, 무공록)")
    skin: StatSkin = Field("system", description="화면에서 상태창을 그리는 모양 (statwin.SKINS)")
    names: list[str] = Field(default_factory=list, description="작품 틀: 인물 상태창에 넣을 항목 이름. 비면 기본 틀만 보인다")
    prompt: Literal["json", "lines", "none"] = Field("json", description="쓰기 프롬프트에 상태창 수치를 넣는 방식: json 인물 상태 안에 그대로 / lines 이번 화 인물만 줄 형식과 도감 줄 / none 넣지 않음 (statwin.write_rule, 연구 화면 상태창 시험)")


class StatWindowOption(BaseModel):
    """세계관에 맞춘 상태창 꾸미기 한 안 (pipeline.suggest_stat_window). 작가가 골라 적용한다."""
    label: str = Field(description="안 이름 한두 낱말 (예: 무공록, 헌터 협회 등록증)")
    title: str = Field(description="상태창 창 이름. 본문 서식 머리와 같게 (예: 무공록)")
    template: str = Field(description="본문에 넣는 상태창 전체 서식. {name} 은 인물 이름, {rows} 는 항목 줄들이 들어갈 자리. 줄바꿈은 \\n")
    row: str = Field(description="항목 한 줄 서식. {key} 는 항목 이름, {value} 는 값 (예: ▸ {key} ┃ {value})")
    names: list[str] = Field(default_factory=list, description="이 세계관에 맞는 항목 이름 4~8개 (예: 경지, 내공, 무공, 독문 절기)")
    skin: StatSkin = Field(description="화면 스킨: system 시스템 창 / parchment 양피지 / scroll 두루마리 / neon 네온 / plain 담백한 서류")
    why: str = Field("", description="작품 설정의 무엇에 맞췄는지 한국어 한 문장")


class StatWindowSuggestion(BaseModel):
    options: list[StatWindowOption] = Field(default_factory=list, description="서로 다른 분위기의 안 2~3개")


class AbilityGrade(BaseModel):
    """스킬 등급 하나의 효과 (canon/abilities.py). grade 는 상태창 조각의 꼬리와 같게 (Lv3, B급, 3성)."""
    grade: str
    effect: str = ""


class Ability(BaseModel):
    """스킬 · 특성 · 칭호 도감 한 항목 (canon/abilities.py). 정의는 인물 사이에 하나로 두고,
    누가 어느 등급을 가졌는지와 얻은 화는 상태창 값(CharacterState.stats)과 기록(stat_log)에서 계산한다."""
    id: str
    name: str = Field(description="상태창 목록에 쓰는 이름 (등급 꼬리 없이, 예: 화염구)")
    aliases: list[str] = Field(default_factory=list, description="다른 이름. 상태창 조각과 본문에서 같은 것으로 본다")
    stat: str = Field("", description="속하는 상태창 항목 (스킬, 특성, 칭호). 비면 어느 목록이든")
    description: str = ""
    effect: str = Field("", description="효과")
    cost: str = Field("", description="대가 · 제약 (쿨타임, 마력 소모, 수명 등)")
    grades: list[AbilityGrade] = Field(default_factory=list, description="등급별 효과")
    context: Literal["auto", "always", "off"] = Field("auto", description="프롬프트에 넣기: 관련 있을 때, 항상, 넣지 않음")
    source: Literal["author", "ai"] = "author"
    created_ep: int = Field(0, description="상태 변경안에서 생겼으면 그 화. 작가가 만들면 0")


class StatInitCharacter(BaseModel):
    """한 인물의 1화 시작 상태창 수치 제안."""
    character_id: str = Field(description="인물 id")
    stats: list[StatValue] = Field(default_factory=list, description="1화 시작 때 값. +3 같은 바뀐 양이 아니라 값 그대로")
    note: str = Field("", description="설정의 무엇을 근거로 정했는지 한국어 한 문장")


class StatInitSuggestion(BaseModel):
    """1화 전 상태창 처음 수치 제안 (pipeline.suggest_initial_stats). 작가가 인물마다 골라 적용한다."""
    names: list[str] = Field(default_factory=list, description="항목 이름. 작품 틀이 있으면 그대로, 없으면 세계관에 맞게 4~8개")
    characters: list[StatInitCharacter] = Field(default_factory=list, description="상태창이 있는 인물만")


SettingField = Literal["age", "role", "appearance", "personality", "speech_style", "background", "goal", "wound"]


class SettingChange(BaseModel):
    """본문에서 뒤 화까지 이어지게 바뀐 인물 설정 한 칸. 작가가 상태 승인 화면에서 골라야 반영한다 (canon/charlog.py)."""
    character_id: str
    field: SettingField = Field(description="바뀐 인물 설정 칸 이름 ([인물 설정]의 키 그대로)")
    value: str = Field(description="바뀐 뒤 이 칸 전체. 바뀌지 않은 부분도 이어서 다시 적는다")
    reason: str = Field("", description="무엇이 왜 바뀌었는지 한 줄")
    quote: str = Field("", description="근거가 되는 본문 문장 그대로")
    episode: int = Field(0, description="바뀐 화. 프로그램이 채운다")


class SettingRecord(BaseModel):
    """인물 설정이 바뀐 기록. 전후 비교, 되돌리기, 인물 화면 타임라인에 쓴다 (canon/charlog.py)."""
    episode: int = Field(description="바뀐 화. 작가가 고쳤으면 그때 마지막으로 반영한 화")
    character_id: str
    field: str
    before: str = ""
    after: str = ""
    source: Literal["ai", "author"] = Field("ai", description="ai: 승인한 설정 바꾸기 제안 / author: 작가가 설정 화면에서 고침")
    reason: str = ""
    quote: str = ""


class AddressForm(BaseModel):
    """한 인물이 다른 인물을 부르는 말과 그에게 쓰는 말씨. 방향이 있다 (A→B 와 B→A 가 따로). 작가가 인물 · 관계 화면에서 정하고,
    본문에서 바뀐 것은 상태 변경안의 address_changes 로 와서 작가가 골라야 반영한다 (canon/address.py)."""
    speaker: str = Field(description="말하는 인물 id")
    listener: str = Field(description="듣는 인물 id")
    calls: str = Field("", description="speaker 가 listener 를 부르는 말 (예: 도현 씨, 오라버니, 대장님)")
    speech: str = Field("", description="speaker 가 listener 에게 쓰는 말씨 (예: 해요체, 해체(반말), 하오체)")


class AddressChange(BaseModel):
    """본문에서 뒤 화까지 이어지게 바뀐 호칭 · 말씨 한 방향. 작가가 상태 승인 화면에서 골라야 반영한다 (canon/address.py)."""
    speaker: str = Field(description="말하는 인물 id")
    listener: str = Field(description="듣는 인물 id")
    calls: str = Field("", description="바뀐 뒤 speaker 가 listener 를 부르는 말. 그대로면 빈칸")
    speech: str = Field("", description="바뀐 뒤 말씨: 하십시오체 · 해요체 · 하오체 · 하게체 · 해체(반말) · 해라체 중 하나나 짧은 설명. 그대로면 빈칸")
    reason: str = Field("", description="무엇이 왜 바뀌었는지 한 줄")
    quote: str = Field("", description="근거가 되는 대사를 본문 그대로")
    episode: int = Field(0, description="바뀐 화. 프로그램이 채운다")


class AddressRecord(BaseModel):
    """호칭 · 말씨가 바뀐 기록. 되돌리기와 인물 화면에 쓴다 (canon/address.py)."""
    episode: int = Field(description="바뀐 화. 작가가 고쳤으면 그때 마지막으로 반영한 화")
    speaker: str
    listener: str
    field: Literal["calls", "speech"]
    before: str = ""
    after: str = ""
    source: Literal["ai", "author"] = Field("ai", description="ai: 승인한 바뀜 제안 / author: 작가가 인물 · 관계 화면에서 고침")
    reason: str = ""
    quote: str = ""


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
    new_places: list[NewPlace] = Field(default_factory=list, description="장소 목록과 이야기 요소에 없는데 이번 화에 이름을 갖고 처음 나온 장소 (지형, 마을, 건물, 가게 등)")
    setting_changes: list[SettingChange] = Field(default_factory=list, description="인물 설정(외모, 성격, 말투 등)이 뒤 화까지 이어지게 바뀐 칸만. 대부분의 화는 비어 있다")
    address_changes: list[AddressChange] = Field(default_factory=list, description="인물끼리 부르는 말이나 말씨(존댓말 · 반말)가 뒤 화까지 이어지게 바뀐 방향만. 대부분의 화는 비어 있다")
    time: StoryTime = Field(default_factory=StoryTime, description="이번 화가 끝난 작품 속 시점")
    deadlines_added: list[Deadline] = Field(default_factory=list, description="이번 화에 새로 생기거나 날이 바뀐 기한. 바뀐 기한은 같은 id 로")
    deadlines_done: list[str] = Field(default_factory=list, description="이번 화에 닫힌 기한 id (그날이 와서 일이 일어났거나 기한이 없어짐)")
    warnings: list[str] = Field(default_factory=list, description="플롯, 설정, 말투와 어긋난 부분")
    # 프로그램이 채운다 (cast.clean_delta). AI 응답 형식에서 뺀다. 반영 뒤에는 실제로 붙인 id 만 남아 되돌리기가 그것만 뺀다
    cast_added: SkipJsonSchema[list[str]] = Field(
        default_factory=list, description="반영하면 그 화 등장 인물(EpisodePlot.characters)에 붙일 인물 id: 본문에 이름이 나오고 이 변경안이 상태나 관계 사건을 다룬 인물")


class NameOption(BaseModel):
    name: str
    reason: str = Field("", description="이 인물이나 장소에 맞는 이유 한 줄")


class NameOptions(BaseModel):
    """이름·지명 AI 추천. 코드가 뽑은 후보에서 고르거나 같은 결로 새로 짓는다 (naming.py)."""
    options: list[NameOption]


class FieldIdea(BaseModel):
    text: str = Field(description="칸에 그대로 넣을 값")
    reason: str = Field("", description="이 후보가 작품에 맞는 이유 한 줄")


class FieldIdeas(BaseModel):
    """설정 칸 하나의 AI 후보 (✦). 작가가 하나를 골라야 칸이 바뀐다 (pipeline.suggest_field)."""
    options: list[FieldIdea]


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
    found_in: Literal["", "본문", "플롯"] = Field("", description="본문(상태 반영)이나 플롯(화 확정)에서 처음 나와 등록된 장소. 비면 작가가 더한 요소")
    found_ep: int = Field(0, description="처음 나와 등록된 화")


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


class ArchetypePick(BaseModel):
    """설정 화면에서 인물에게 고른 원형 도감 카드 (canon/archetypes.py). 작가가 고른 것만 남고 프롬프트에는 넣지 않는다."""
    character_id: str
    archetype: str = Field(description="archetypes.CATALOG 의 id")
    twist: str = Field("", description="고른 비틀기. 아크 칸에도 한 줄로 붙는다")


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

# ---------- 지도 (canon/atlas.py) ----------
# 장소는 설정의 장소 칸과 인과율 '장소' 요소다. 지도는 그 위에 자리와 배경 그림, 위치 글 잇기만 더한다.

class BuildingNote(BaseModel):
    """작가가 고친 건물 하나 (지금 마을 · 도시 데이터의 건물 번호 기준). 빈 칸은 생성기가 정한 값(canon/bldgs.py)을 쓴다."""
    i: int = Field(description="건물 번호 (마을 데이터 buildings 의 순서)")
    use: str = Field("", description="쓰임 id (bldgs.USES). 비면 생성기 값")
    name: str = Field("", description="집 이름 · 간판. 비면 생성기 값")
    note: str = Field("", description="작가 메모")
    residents: list[str] = Field(default_factory=list, description="여기 사는 · 일하는 인물 id")


class MapPin(BaseModel):
    """장소의 지도 위 자리. 0~1 비율 좌표라 배경 그림 크기와 상관없다."""
    place: str = Field(description="장소 키: 인과율 장소 요소 id, 설정 장소 칸이면 'w:' + 이름")
    x: float = 0.5
    y: float = 0.5
    spot: str = Field("", description="놓인 건물 · 표지 한 줄 (atlas.spot_line, 쓰기 · 검수 프롬프트의 atlas.episode_block). 핀 · 마을 데이터 · 건물을 바꿀 때 다시 쓴다")


class PlaceLink(BaseModel):
    """작가가 정한 '이 위치 글은 이 장소'. 이름으로 맞추지 못한 인물 위치(CharacterState.location)를 잇는다."""
    text: str
    place: str = Field("", description="장소 키. 비우면 지도에 그리지 않는 위치 (이동 중, 알 수 없음 등)")


class MapPlace(BaseModel):
    """지도 만들기에서 작가가 고친 장소 하나: 종류와 이 지도에 놓을지."""
    key: str = Field(description="장소 키 (atlas.places)")
    kind: str = Field("", description="종류 id (placekinds.KINDS). 지도 종류의 시대와 다른 id 는 placekinds.to_era 로 읽는다. 비면 이름 · 설명에서 찾는다")
    put: Optional[bool] = Field(None, description="이 지도에 놓을지. 비면 종류로 정한다 (마을 밖 장소는 놓지 않음)")


class MapSpec(BaseModel):
    """지도 생성기 입력 (canon/towngen.py). 같은 값이면 언제나 같은 지도가 나온다."""
    kind: Literal["village", "city", "modern", "realm"] = "village"
    seed: int = Field(1, ge=0, le=2**31 - 1)
    version: int = Field(0, description="이 지도를 만든 생성기 알고리즘 버전 (적용할 때 적는다)")
    size: Literal["small", "medium", "large"] = "medium"
    roads: Literal["line", "cross", "square"] = "cross"
    water: Literal["none", "river", "lake", "sea"] = "none"
    fields: Literal["few", "some", "many"] = "some"
    forest: Literal["few", "some", "many"] = "some"
    places: list[MapPlace] = Field(default_factory=list)


class TravelSetting(BaseModel):
    """이동 시간 검사 설정 (canon/travel.py). 지도 거리와 작품 속 시간을 견줘 너무 빠른 이동을 찾는다."""
    enabled: bool = Field(True, description="끄면 지도 화면 · 상태 변경안 경고 · 프롬프트의 이동 거리를 모두 뺀다 (순간 이동이 흔한 작품 등)")
    mode: str = Field("horse", description="이 세계에서 인물이 쓰는 가장 빠른 탈것 (travel.MODES 의 id). transit(대중교통)은 걸어서와 지하철(Atlas.transit) 가운데 빠른 쪽")
    kmh: float = Field(0, description="작가가 정한 이동 빠르기 (km/시). 0 이면 탈것의 기본값")
    day_km: float = Field(0, description="작가가 정한 하루 이동 거리 (km). 0 이면 탈것의 기본값")
    ok: list[str] = Field(default_factory=list, description="작가가 '괜찮아요'로 둔 이동 ('인물 id:화'). 경고에서 뺀다")


class TransitStation(BaseModel):
    """지하철 역 하나 (지도 데이터 transit.stations 의 사본). x · y 는 지도 비율이고 지도 밖 역은 0~1 밖일 수 있다."""
    name: str = Field("", description="역 이름 (OpenStreetMap name 태그 그대로)")
    x: float = 0
    y: float = 0
    lines: list[str] = Field(default_factory=list, description="이 역을 지나는 노선 이름")


class TransitLine(BaseModel):
    """지하철 노선 하나: 지도 데이터에 든 역을 차례로. 방향이 다른 relation 은 하나로 묶었다."""
    name: str = ""
    stations: list[int] = Field(default_factory=list, description="TransitStation 번호를 노선 차례로")
    gaps: list[int] = Field(default_factory=list, description="stations[i] 와 stations[i+1] 사이에 파일에 없는 역 수. 비면 모두 0")


class Transit(BaseModel):
    """지도 데이터의 지하철(osm 의 transit 키)을 작품에 적어 둔 사본. 상태 변경안 정리 · 프롬프트처럼 작품 폴더를 모르는 곳에서
    이동 시간 검사(travel.py)가 읽는다. 지도 파일을 놓거나 바꿀 때 atlas.fill_spots 가 다시 쓴다."""
    stations: list[TransitStation] = Field(default_factory=list)
    lines: list[TransitLine] = Field(default_factory=list)


class MapFill(BaseModel):
    """OpenStreetMap 지도의 빈 블록 채우기 입력 (canon/fill.py). 지울 때와 다시 만들 때 쓴다."""
    seed: int = Field(1, description="채우기 시드. 같은 지도 · 같은 시드면 같은 건물")
    rule: str = Field("villa", description="채우는 규칙 (fill.RULES): villa 는 빌라촌, 큰 블록은 아파트 단지")


class Atlas(BaseModel):
    image: str = Field("", description="배경 그림 파일 이름 (projects/<작품>/map/ 아래). 비면 빈 캔버스")
    aspect: float = Field(1.5, description="지도 가로 / 세로. 배경 그림을 올리면 그림 비율")
    pins: list[MapPin] = Field(default_factory=list)
    links: list[PlaceLink] = Field(default_factory=list)
    layout: str = Field("", description="마을 · 도시 데이터 파일 이름 (projects/<작품>/map/ 아래, atlas.read_layout 으로 바꾼 길 · 건물). 비면 없음")
    meters: float = Field(1.0, description="마을 데이터 1단위가 몇 m 인지 (거리 · 걷는 시간 계산)")
    spec: Optional[MapSpec] = Field(None, description="지도 만들기로 만든 마을이면 그 입력. 파일을 올렸거나 지도가 없으면 비움")
    fill: Optional[MapFill] = Field(None, description="빈 블록을 채운 OpenStreetMap 지도면 그 입력. 채우지 않았거나 지도 파일이 바뀌면 비움")
    title: str = Field("", description="지도 위에 적는 마을 이름. 비면 '마을 가운데' 종류의 장소 이름")
    buildings: list[BuildingNote] = Field(default_factory=list, description="작가가 고친 건물. 마을 데이터 파일이 바뀌면 비운다")
    span_km: float = Field(0, description="지도 가로가 몇 km 인지 (마을 데이터가 없을 때 이동 거리 계산). 0 이면 모름")
    layout_size: list[float] = Field(default_factory=list, description="마을 데이터의 [가로, 세로] (원래 단위). 마을 데이터를 놓을 때 채운다")
    travel: TravelSetting = Field(default_factory=TravelSetting)
    transit: Optional[Transit] = Field(None, description="지도 데이터의 지하철 역 · 노선 사본 (OpenStreetMap 지도만). 없으면 None")


class ReleasePlan(BaseModel):
    """연재 일정. 작가가 적는 값이라 프롬프트에 넣지 않는다. 비축분 · 하루 목표는 화면이 계산한다 (static/home.js releasePlan)."""
    per_week: int = Field(0, description="일주일에 올리는 화 수. 0 이하면 정하지 않음 (화면이 0~70 으로 맞춰 셈)")
    released: int = Field(0, description="연재처에 올린 마지막 화. 0 이하면 아직 올린 화가 없음")


class Project(BaseModel):
    meta: Meta = Field(default_factory=Meta)
    world: WorldSetting = Field(default_factory=WorldSetting)
    characters: list[Character] = Field(default_factory=list)
    cast_candidates: list[Character] = Field(
        default_factory=list, description="AI 플롯이 제안한 새 인물. 작가가 등록하거나 그 인물이 나오는 화를 확정하면 characters 로 옮긴다")
    cast_archetypes: list[ArchetypePick] = Field(default_factory=list, description="인물마다 원형 도감에서 고른 원형. 프롬프트에는 넣지 않는다")
    place_candidates: list[NewPlace] = Field(
        default_factory=list, description="AI 플롯이 지은 새 장소. 그 장소가 나오는 화를 확정하면 인과율 '장소' 요소로 옮긴다")
    relationships: list[Relationship] = Field(default_factory=list)
    style: StyleProfile = Field(default_factory=StyleProfile)
    style_baseline: Optional[StyleMetrics] = Field(None, description="레퍼런스 원문 전체로 잰 문체 지표 (style 명령 때 저장)")
    style_id: str = Field("", description="문체 라이브러리에서 가져온 항목 id. 비어 있으면 이 작품에서 직접 만든 문체")
    style_version: int = Field(0, description="가져오거나 올린 라이브러리 항목의 버전 번호. 0 은 모름")
    style_example: Optional[StyleExample] = Field(None, description="문체 화면의 '이 문체로 쓴 예시'")
    style_learning: Optional[StyleLearning] = Field(None, description="수정 기록에서 찾은 문체 규칙 후보 (마지막 것)")
    arc: list[Act] = Field(default_factory=list, description="단편: 작품 전체의 기승전결. 장편에서는 비워 두고 아크마다 기승전결을 둔다")
    parts: list[Part] = Field(default_factory=list, description="장편: 부 구성")
    story_arcs: list[StoryArc] = Field(default_factory=list, description="장편: 지금까지 기획한 아크. 다음 아크를 하나씩 붙인다")
    arc_undo: list[ArcUndo] = Field(default_factory=list, description="아크마다 붙일 때 바꾼 것 (마지막 아크를 지우면 되돌린다)")
    episodes: list[Episode] = Field(default_factory=list)
    states: list[CharacterState] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    foreshadows: list[Foreshadow] = Field(default_factory=list)
    foreshadow_clues: list[ForeshadowClue] = Field(default_factory=list, description="복선이 본문에 걸린 문장 (복선 센터)")
    stat_log: list[StatRecord] = Field(default_factory=list, description="상태창 수치가 바뀐 기록")
    stat_window: StatWindow = Field(default_factory=StatWindow, description="본문에 넣는 상태창 서식")
    abilities: list[Ability] = Field(default_factory=list, description="스킬 · 특성 · 칭호 도감 (canon/abilities.py)")
    setting_log: list[SettingRecord] = Field(default_factory=list, description="인물 설정이 바뀐 기록 (승인한 설정 바꾸기 제안, 1화 반영 뒤 작가가 고친 것)")
    setting_held: list[SettingChange] = Field(default_factory=list, description="자동 집필이 반영하지 않고 남겨 둔 설정 바꾸기 제안. 작가가 인물 화면에서 적용하거나 버린다")
    address_forms: list[AddressForm] = Field(default_factory=list, description="인물끼리 부르는 말과 말씨 (방향마다 하나, canon/address.py)")
    address_log: list[AddressRecord] = Field(default_factory=list, description="호칭 · 말씨가 바뀐 기록 (승인한 바뀜 제안, 1화 반영 뒤 작가가 고친 것)")
    knows_folds: list[KnowsFoldRecord] = Field(default_factory=list, description="아는 정보를 접은 기록 (canon/knows.py)")
    address_held: list[AddressChange] = Field(default_factory=list, description="자동 집필이 반영하지 않고 남겨 둔 호칭 · 말씨 바뀜 제안. 작가가 인물 화면에서 적용하거나 버린다")
    history: list[StateDelta] = Field(default_factory=list, description="승인된 상태 변경 기록")
    ties: list[Tie] = Field(default_factory=list, description="방향 관계 (dynamics 가 계산)")
    secrets: list[Secret] = Field(default_factory=list)
    events: list[StoryEvent] = Field(default_factory=list, description="승인된 사건 로그")
    params: ModelParams = Field(default_factory=ModelParams)
    snapshots: list[Snapshot] = Field(default_factory=list)
    settings: Settings = Field(default_factory=Settings)
    chats: list[Chat] = Field(default_factory=list, description="화면별 AI 대화 기록 (옛 단발 대화. 에이전트 세션의 '이전 대화')")
    agent_sessions: list[AgentSession] = Field(default_factory=list, description="대화 에이전트 세션 (canon/agent.py)")
    elements: list[StoryElement] = Field(default_factory=list, description="인과율: 언제든 더하는 요소, 특징, 설정, 사건")
    conversion: Optional[Conversion] = Field(None, description="단편에서 장편으로 바꾼 기록. 되돌리면 지운다")
    archive: Optional[ShortArchive] = Field(None, description="재구성 전 단편 원고와 새 화 지도")
    storylines: list[Storyline] = Field(default_factory=list, description="메인에서 갈라지는 이야기 줄기 (서브플롯, 과거 회상, 외전, 인물 이야기)")
    visuals: list[CharacterVisual] = Field(default_factory=list, description="삽화용 인물 외형 태그")
    illust: IllustSettings = Field(default_factory=IllustSettings, description="삽화 프롬프트 설정")
    atlas: Atlas = Field(default_factory=Atlas, description="지도: 장소 자리, 배경 그림, 위치 글 잇기")
    timeline: Timeline = Field(default_factory=Timeline, description="작품 속 시간: 기준 날짜와 기한")
    release: ReleasePlan = Field(default_factory=ReleasePlan, description="연재 일정: 일주일에 올리는 화 수와 올린 마지막 화")
    rooms: list[StageRoom] = Field(default_factory=list, description="장면 연출의 방 (canon/stage.py). 여러 화 · 장면이 다시 쓴다")
    # 아래 두 칸은 맨 끝에 둔다. store.save 가 파일 끝만 읽어 디스크 값을 찾는다 (store._saved_mark)
    edit_rev: int = Field(0, description="화면(브라우저 탭)이 저장한 횟수. 오래된 화면이 다른 화면의 저장을 덮지 않게 비교한다 (store.writer)")
    saved_by: str = Field("", description="마지막으로 저장한 화면(브라우저 탭) id")

    def episode(self, n: int) -> Episode:
        for ep in self.episodes:
            if ep.plot.number == n:
                return ep
        raise KeyError(f"{n}화 플롯이 없어요")

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


# ---------- 갈래 (canon/branches.py) ----------

ForkMode = Literal["clear", "keep"]


class BranchInfo(BaseModel):
    """갈래 정보. project.json 밖의 projects/<폴더>/branch.json 에 둬서 화면이 작품을 통째로 저장해도 덮지 않는다.
    파일이 없으면 갈래가 없는 작품이다. 갈래끼리는 폴더 이름이 아니라 id 로 잇는다."""
    id: str = Field(description="이 작품의 id. 폴더 이름을 바꿔도 그대로다")
    family: str = Field(description="본편과 모든 갈래가 함께 쓰는 id")
    parent: str = Field("", description="갈라져 나온 작품의 id. 본편은 빈 값")
    from_ep: int = Field(0, description="이 화부터 parent 와 다르다 (1~(from_ep-1)화를 함께 쓴다). 본편은 0")
    label: str = Field("", description="갈래 이름 (예: B안 - 세린이 떠난다)")
    note: str = ""
    at: str = Field("", description="갈라진 시각")
    base: str = Field("", description="갈라질 때 1~(from_ep-1)화 본문의 해시. 함께 쓰는 앞 화가 나중에 달라졌는지 본다")


class BranchSide(BaseModel):
    """갈래 비교에서 한 화의 한쪽."""
    title: str = ""
    status: str = ""
    summary: str = ""
    chars: int = Field(0, description="본문 글자 수")


class BranchEpisode(BaseModel):
    number: int
    a: Optional[BranchSide] = Field(None, description="그 화가 없으면 비움")
    b: Optional[BranchSide] = None


BranchRowKind = Literal["character", "tie", "fact", "foreshadow", "time", "setting"]


class BranchDiffRow(BaseModel):
    """두 갈래의 같은 화 반영 직후 상태에서 다른 칸 하나."""
    kind: BranchRowKind
    who: str = Field("", description="인물 이름, 관계 쌍, 복선 id")
    field: str = ""
    a: str = ""
    b: str = ""


class BranchDiff(BaseModel):
    from_ep: int = Field(description="이 화부터 두 갈래가 다르다")
    episode: int = Field(description="상태를 견준 화")
    ready_a: bool = Field(False, description="a 갈래에 그 화 반영 직후 스냅샷이 있다")
    ready_b: bool = False
    episodes: list[BranchEpisode] = Field(default_factory=list, description="갈라진 화부터 화별 제목 · 요약")
    text_a: str = Field("", description="a 갈래의 그 화 본문")
    text_b: str = ""
    rows: list[BranchDiffRow] = Field(default_factory=list, description="양쪽 모두 반영한 화일 때만 채운다")


# ---------- 플레이 모드 (canon/play.py, canon/birth.py) ----------
# 플레이는 세계 작품을 복사한 작품 폴더다. 한 턴은 Episode 하나, 플레이 정보는 project.json 밖의 play.json.

PlayPerson = Literal["first", "second", "third"]
TurnKind = Literal["start", "choice", "free", "skip", "flow", "auto"]
PlayUnit = Literal["auto", "hour", "day", "month", "year"]


class PlayChoice(BaseModel):
    """장면 끝에 붙는 다음 행동 선택지 하나."""
    text: str = Field(description="플레이어 인물이 할 행동 한 줄 (예: 문을 열고 들어간다)")
    # 턴제 때 시간 건너뛰기 선택지의 길이. 시간 흐름 모델에서는 쓰지 않아 AI 응답 형식에서 뺀다 (옛 play.json 은 읽힌다)
    skip: SkipJsonSchema[str] = ""


class PlayBeat(BaseModel):
    """구간 안에서 흘러간 일 한 줄. 화면 시계가 한 줄씩 보인다."""
    time: StoryTime = Field(default_factory=StoryTime, description="이 일이 일어난 작품 속 시점")
    text: str = Field(description="흘러간 일 한두 문장")


class PlayScene(BaseModel):
    """플레이 구간 하나: 흘러간 일과, 있으면 결정 장면. AI 가 쓴다 (play 단계). 상태 변경안은 뒤에서 따로 만든다 (play.settle)."""
    beats: list[PlayBeat] = Field(default_factory=list, description="결정할 순간까지, 또는 정해진 시간 칸까지 흘러간 일. 시간 순서대로")
    text: str = Field("", description="결정 장면 본문. 플레이어 인물이 무언가 정해야 하는 순간을 장면으로. 그런 순간이 없으면 빈칸")
    choices: list[PlayChoice] = Field(default_factory=list, description="결정 장면의 선택지 3~4개. 결정 장면이 없으면 빈 목록")
    lean: int = Field(0, description="플레이어 인물의 성격과 목표라면 고를 선택지 번호 (1부터). 선택지가 없으면 0")
    ending: str = Field("", description="플레이어 인물의 이야기가 이 구간에서 끝나면 그 까닭 한 줄 (죽음, 목표를 이룸, 떠남 등). 이어지면 빈칸")


class Birth(BaseModel):
    """무작위 출생: 코드가 시드로 굴린 값 (birth.roll). AI 는 BirthSketch 로 배경만 채운다."""
    seed: int = 0
    name: str = ""
    gender: str = ""
    age: str = ""
    archetype: str = Field("", description="원형 도감 id (archetypes.CATALOG)")
    wound: str = Field("", description="상처 id (archetypes.WOUNDS)")
    speech: str = Field("", description="말투 틀 id (archetypes.SPEECH)")
    twist: str = ""
    place: str = Field("", description="태어난 곳 (world.locations 나 '장소' 요소의 이름)")


class BirthSketch(BaseModel):
    """무작위 출생의 배경. 코드가 굴린 값(Birth)에 맞춰 AI 가 세계에 맞게 채운다 (birth.sketch)."""
    appearance: str = ""
    personality: str = ""
    background: str = Field("", description="집안, 자란 곳, 지금까지의 삶 3~5문장")
    goal: str = ""
    speech_style: str = ""
    opening: str = Field("", description="첫 장면의 실마리 한두 문장: 플레이를 시작하는 순간 이 인물이 어디서 무엇을 하고 있는지")


class PlayTurn(BaseModel):
    """플레이 기록의 턴 하나. 본문은 같은 번호의 Episode 에 있다."""
    number: int = Field(description="Episode 번호")
    kind: TurnKind = "choice"
    action: str = Field("", description="플레이어가 고르거나 적은 행동. 첫 턴은 비움")
    luck: int = Field(0, description="코드가 굴린 운: -2 아주 나쁨 ~ 2 아주 좋음. 화면에는 숨기고 기록에만 둔다")
    beats: list[PlayBeat] = Field(default_factory=list, description="이 구간에 흘러간 일. 본문(Episode.text)에도 이어 넣는다")
    choices: list[PlayChoice] = Field(default_factory=list, description="이 구간 끝 결정 장면의 선택지. 비면 결정 없이 다음 구간으로 흐른다")
    lean: int = Field(0, description="AI 가 이 인물이라면 고를 것이라 한 선택지 번호. 자동 결정에 쓴다")
    state: Literal["pending", "applied", "failed"] = Field("pending", description="뒤에서 만드는 상태 변경안의 반영 여부")
    error: str = Field("", description="상태 반영이 실패한 까닭")
    ending: str = Field("", description="이 턴 장면이 낸 결말 까닭 (PlayScene.ending). 상태 반영이 끝나면 플레이를 끝낸다")
    at: str = ""


class PlayInfo(BaseModel):
    """플레이 정보. project.json 밖의 projects/<폴더>/play.json 에 둔다. 이 파일이 있으면 그 작품은 플레이 사본이다."""
    world: str = Field(description="세계 작품 폴더 이름")
    world_ep: int = Field(0, description="세계 작품에서 이어받은 마지막 반영 화. 턴은 world_ep+1 화부터")
    player: str = Field(description="플레이어 인물 id")
    title: str = Field("", description="플레이 이름 (예: 은재의 삶). 비면 화면이 '<인물 이름>의 삶'으로 부른다")
    opening: str = Field("", description="첫 구간 실마리 (무작위 출생 BirthSketch.opening). 첫 구간을 다시 쓸 때도 넘긴다")
    origin: Literal["character", "random"] = Field("character", description="character 세계의 인물이 됨 / random 무작위 출생")
    birth: Optional[Birth] = None
    person: PlayPerson = Field("second", description="서술 시점: first 나 / second 당신 / third 이름")
    seed: int = 0
    max_turns: int = Field(0, description="구간 수 한도. 0 이면 없음")
    chapter_len: int = Field(20, description="장 하나의 구간 수. 장이 끝나면 요약으로 접는다")
    unit: PlayUnit = Field("day", description="시간 단위. 새 플레이에서 auto 를 고르면 시작할 때 세계에 맞는 단위로 바꿔 둔다 (play.pick_unit)")
    segment_units: int = Field(7, description="구간 하나의 최대 시간 칸 수. 결정 장면이 먼저 오면 거기서 끝난다")
    focus: str = Field("", description="흘러가는 동안 따라갈 것 (예: 수련, 사람, 생업). 비면 AI 가 정한다")
    auto_decide: bool = Field(False, description="결정 장면에서 기다리지 않고 AI 가 낸 lean 을 고른다 (화면이 몇 초 기다린 뒤 부른다)")
    end_days: int = Field(0, description="작품 속 날수 한도: 시작부터 이만큼 지나면 끝. 0 이면 없음")
    end_decisions: int = Field(0, description="결정 수 한도. 0 이면 없음")
    start_day: int = Field(0, description="시작할 때의 작품 속 날수 (세계의 마지막 반영 화가 끝난 날)")
    seen: int = Field(0, description="플레이어가 화면에서 닿은 마지막 구간 번호. 서버는 이보다 한 구간 넘게 앞서 쓰지 않는다 (play.see)")
    turns: list[PlayTurn] = Field(default_factory=list)
    ending: str = Field("", description="끝난 까닭. 비면 진행 중")
    ended_ep: int = 0
    at: str = ""



# ---------- 큐 시트 집필 실험 (canon/cue.py) ----------
# 한 화를 음악의 악보처럼 큐(연주 단위)로 나눈다. 큐마다 화성 기능(안정 · 쌓기 · 긴장), 긴장도, 템포, 편성(대사 · 행동 · 묘사 · 속생각),
# 일어나는 일, 핵심 대사, 다음 큐로 넘기는 것을 정한다. 작품(project.json)에 넣지 않고 실험 파일 cuelab/<화>.json 에 둔다.

CueFunction = Literal["T", "S", "D"]
CueTempo = Literal["slow", "mid", "fast"]
CueVoice = Literal["dialogue", "action", "description", "interior"]
CueCadence = Literal["full", "half", "deceptive"]


class CueLine(BaseModel):
    """핵심 대사 하나. 본문에 글자 그대로 넣는다."""
    speaker: str = Field("", description="말하는 인물 id")
    text: str = Field("", description="대사 글. 따옴표 없이")


class Cue(BaseModel):
    """큐 하나 (연주 단위). 본문 문장과 묘사는 적지 않는다. 대사는 핵심 대사만."""
    scene: int = Field(0, description="이 큐가 속한 스토리보드 장면 번호 (1부터). 스토리보드가 없으면 0")
    function: CueFunction = Field("S", description="화성 기능. T 안정(기준선, 숨 고르기) · S 쌓기(정보, 갈등의 씨) · D 긴장(위기, 결정 직전)")
    tension: int = Field(3, description="긴장도 1~5")
    tempo: CueTempo = Field("mid", description="템포. slow 장면을 늘임 · mid · fast 사건을 몰아침")
    voice: CueVoice = Field("action", description="주로 무엇으로 쓰는지 (편성). dialogue 대사 · action 행동 · description 묘사 · interior 속생각")
    beat: str = Field("", description="이 큐에서 바뀌는 일 한 줄")
    lines: list[CueLine] = Field(default_factory=list, description="이 큐에 반드시 들어갈 핵심 대사 0~3개")
    exit: str = Field("", description="이 큐가 끝날 때의 상태. 다음 큐가 여기서 이어받는다")
    length: int = Field(0, description="목표 글자 수")


class CueSheetDraft(BaseModel):
    """LLM 응답 형식 (pipeline.make_cue_sheet)."""
    key: str = Field("", description="조성: 이번 화 정서의 기준선 한 줄 (예: 억눌린 불안, 들뜬 기대)")
    cadence: CueCadence = Field("half", description="화 끝 종지. full 이 화 안에서 풀림 · half 긴장이 가장 높은 곳에서 끊음 · deceptive 풀릴 듯하다 뒤집음")
    cues: list[Cue] = Field(default_factory=list, description="큐 4~10개, 순서대로")


class CueSheet(CueSheetDraft):
    """저장 형식. 실험 파일(CueLab.sheet)과 화(Episode.cue_sheet)가 함께 쓴다."""
    made_at: SkipJsonSchema[str] = ""
    made_by: SkipJsonSchema[Literal["ai", "board", "author", "both"]] = "ai"
    basis: SkipJsonSchema[str] = Field("", description="화에 붙인 큐 시트를 만들 때 입력의 지문 (cue.ep_basis). 지금 값과 다르면 낡은 것. 실험 시트는 비움")


class CueTake(BaseModel):
    """조건 하나로 쓴 본문 (cue.CONDITIONS). parts 는 큐마다 따로 쓴 조건(cues)의 큐별 본문."""
    condition: str
    text: str = ""
    parts: list[str] = Field(default_factory=list)
    calls: int = 1
    prompt_chars: int = Field(0, description="보낸 요청 글자 수의 합 (시스템 지시 포함)")
    sheet_basis: str = Field("", description="이 본문을 쓸 때 쓴 큐 시트의 지문 (cue.basis). 지금 시트와 다르면 낡은 본문")
    at: str = ""


class CueLab(BaseModel):
    """한 화의 큐 시트 실험. projects/<폴더>/cuelab/<화>.json. 작품 데이터가 아니다."""
    episode: int
    sheet: Optional[CueSheet] = None
    takes: list[CueTake] = Field(default_factory=list)
    model: str = ""
    run_at: str = ""


# ---------- 역설계 실험 (canon/revlab.py) ----------
# 작가가 넣은 소설(사람이 쓴 글)을 거꾸로 화별 플롯 · 스토리보드 · 큐 시트 · 이야기 줄기로 푼다. 작품(project.json)에 넣지 않고
# 실험 파일 <CANON_HOME>/.revlab/<번호>.json 에 둔다. 큐 경계는 원문 글자 그대로의 시작 인용으로 받고, 글자 수는 Canon 이 잰다.

# 응답 형식(Rev*)의 칸은 모두 required 다 (기본값을 두지 않는다). 기본값이 있으면 JSON 스키마에서 선택 칸이 되어
# Gemini 가 칸을 통째로 빼고 짧게 끝낸다 (2026-10-30 실측: 5,861자 원문에 출력 36토큰, title 만 채움).
# 그래서 스토리보드 · 큐 대사도 칸이 같은 Rev 전용 형식(RevScene · RevTime · RevHandover · RevQuote)을 두고 저장할 때 바꾼다.

class RevQuote(BaseModel):
    """핵심 대사 하나. 원문 대사를 글자 그대로 (CueLine 으로 저장)."""
    speaker: str = Field(description="말하는 인물 이름")
    text: str = Field(description="원문 대사 글자 그대로, 따옴표 없이")


class RevCue(BaseModel):
    """역설계한 큐 하나. 원문을 나누는 자리(start)를 원문 글자 그대로 적는다. 글자 수는 적지 않는다 (Canon 이 경계로 잰다)."""
    start: str = Field(description="이 큐가 시작하는 원문 문장의 앞부분을 원문 글자 그대로 15~40자. 첫 큐는 원문 첫 문장")
    scene: int = Field(description="이 큐가 속한 장면 번호 (scenes 의 1부터)")
    function: CueFunction = Field(description="화성 기능. T 안정(기준선, 숨 고르기) · S 쌓기(정보, 갈등의 씨) · D 긴장(위기, 결정 직전)")
    tension: int = Field(description="긴장도 1~5")
    tempo: CueTempo = Field(description="템포. slow 장면을 늘임 · mid · fast 사건을 몰아침")
    voice: CueVoice = Field(description="이 구간을 주로 무엇으로 썼는지 (편성). dialogue 대사 · action 행동 · description 묘사 · interior 속생각")
    beat: str = Field(description="이 큐에서 바뀌는 일 한 줄")
    lines: list[RevQuote] = Field(description="이 큐에서 정보가 밝혀지거나 관계가 바뀌는 핵심 대사 0~3개. 없으면 빈 목록")
    exit: str = Field(description="이 큐가 끝날 때의 상태. 다음 큐가 여기서 이어받는다")


class RevPerson(BaseModel):
    """원문에 이름이 나온 인물 하나. 이름이 곧 id 다."""
    name: str = Field(description="원문에 쓴 이름 그대로")
    role: str = Field(description="이 글에서 맡은 몫 한 줄 (주인공, 조연, 적대자 등)")
    speech: str = Field(description="원문 대사에서 보이는 말투 한 줄 (어미, 호칭, 자주 쓰는 표현). 대사가 없으면 빈 글")


class RevScene(BaseModel):
    """장면 하나 (BoardScene 으로 저장). 대사와 본문 문장은 넣지 않는다."""
    place: str = Field(description="장소. 원문의 장소 이름, 없으면 짧은 설명")
    spot: str = Field(description="그 장소 안 자리. 모르면 빈 글")
    time: str = Field(description="장면 시각이나 시간대. 모르면 빈 글")
    present: list[str] = Field(description="이 장면에 있는 인물 이름")
    events: list[int] = Field(description="이 장면이 맡은 events 번호 (1부터)")
    goal: str = Field(description="시점 인물이 이 장면에서 얻으려는 것")
    turn: str = Field(description="장면의 흐름이 바뀌는 일 한 줄")
    end_state: str = Field(description="장면 끝 상태: 다음 장면이 이어받는 것")


class RevTime(BaseModel):
    """이 화의 시간 (BoardTime 으로 저장)."""
    after: int = Field(description="직전 화가 끝난 때에서 며칠 뒤에 시작하는지. 같은 날이거나 알 수 없으면 0")
    part: str = Field(description="시작 시간대. 모르면 빈 글")
    days: int = Field(description="걸친 날 수. 하루 안이면 1")
    end_part: str = Field(description="끝나는 시간대. 모르면 빈 글")


class RevHandover(BaseModel):
    """직전 화 끝에서 이어받은 사실 하나 (BoardHandover 로 저장)."""
    kind: str = Field(description="장면, 시간, 몸, 물건, 인물, 숨긴 것, 숫자, 질문 중 하나")
    text: str = Field(description="이어받은 사실 한 줄. 대사를 옮기지 않는다")


class RevEpisodeDraft(BaseModel):
    """LLM 응답 형식 (pipeline.reverse_episode). 원문 한 화를 플롯 · 스토리보드 · 큐 시트로 푼다. 원문에 없는 것은 짓지 않는다."""
    title: str = Field(description="원문 안에 화 제목 줄이 있으면 그대로, 없으면 빈 글")
    summary: str = Field(description="이 화 줄거리 2~4문장")
    events: list[str] = Field(description="순서대로 일어나는 사건 3~6개")
    cast: list[RevPerson] = Field(description="이 화에 이름이 나오는 인물")
    emotional_shift: str = Field(description="주요 인물의 감정 변화가 겉으로 드러난 행동이나 대사")
    ending_hook: str = Field(description="이 화를 끝내는 엔딩 훅")
    opening: str = Field(description="이 화를 여는 첫 장면 한 줄")
    time: str = Field(description="이 화가 시작하는 작품 속 시점 (직전 화에서 얼마나 지났는지나 시간대). 원문에서 알 수 없으면 빈 글")
    threads: list[str] = Field(description="이 화가 따라가는 이야기 줄기 이름 1~3개 (예: 등대 실종 사건, 두 사람의 관계)")
    scenes: list[RevScene] = Field(description="장면 순서. 장소나 시간이 바뀌는 곳에서 나눈다")
    board_time: RevTime = Field(description="이 화의 시간")
    handover: list[RevHandover] = Field(description="직전 화 끝에서 이어받은 것. 첫 화거나 없으면 빈 목록")
    key: str = Field(description="조성: 이 화 정서의 기준선 한 줄")
    cadence: CueCadence = Field(description="화 끝 종지. full 화 안에서 풀림 · half 긴장이 가장 높은 곳에서 끊음 · deceptive 풀릴 듯하다 뒤집음")
    cues: list[RevCue] = Field(description="원문을 앞에서부터 빈틈없이 나눈 큐 4~10개, 순서대로")


class RevLine(BaseModel):
    """여러 화에 걸친 이야기 줄기 하나 (메인 밖). 저장할 때 Storyline 으로 바꾼다."""
    kind: StorylineKind = Field(description="줄기 종류")
    title: str = Field(description="줄기 이름")
    focus: list[str] = Field(description="중심 인물 이름")
    goal: str = Field(description="이 줄기가 풀어 가는 질문이나 목표")
    when: str = Field(description="이야기 속 시점. 메인과 같은 시간이면 빈 글")
    episodes: list[int] = Field(description="이 줄기를 주로 따라가는 화 번호")
    threads: list[int] = Field(description="다른 줄기를 따라가는 화 안에 이 줄기 장면이 끼어드는 화 번호")
    rejoin: str = Field(description="메인에 합류하며 남기는 것. 아직 합류하지 않았으면 빈 글")


class RevLineSet(BaseModel):
    """LLM 응답 형식 (pipeline.reverse_lines)."""
    main: str = Field(description="메인 줄기가 풀어 가는 질문 한 줄")
    lines: list[RevLine] = Field(description="메인 밖 줄기 0~4개")


class RevBound(BaseModel):
    """큐 하나가 원문에서 차지하는 자리 [start, end). found 가 거짓이면 시작 인용을 원문에서 찾지 못해 길이를 재지 못했다."""
    start: int = 0
    end: int = 0
    found: bool = True
    quote: str = ""


class RevTake(BaseModel):
    """역설계한 재료(플롯 · 스토리보드 · 큐 시트)로 같은 화를 다시 쓴 본문 (되돌려 쓰기)."""
    text: str = ""
    prompt_chars: int = 0
    sheet_basis: str = Field("", description="쓸 때 큐 시트의 지문 (cue.basis). 지금 시트와 다르면 낡은 본문")
    model: str = ""
    at: str = ""


class RevEpisode(BaseModel):
    """원문 한 화와 그 역설계 결과. 플롯 · 스토리보드의 인물 id 와 핵심 대사의 speaker 는 인물 이름이다."""
    number: int
    head: str = Field("", description="원문의 화 제목 줄")
    text: str = ""
    plot: Optional[EpisodePlot] = None
    storyboard: Optional[Storyboard] = None
    sheet: Optional[CueSheet] = None
    bounds: list[RevBound] = Field(default_factory=list, description="큐마다 원문 자리. 큐 수와 같아야 쓴다")
    dropped: list[str] = Field(default_factory=list, description="원문에 없어 뺀 핵심 대사")
    threads: list[str] = Field(default_factory=list)
    model: str = ""
    made_at: str = ""
    take: Optional[RevTake] = None
    blind: list[str] = Field(default_factory=list, description="블라인드 비교 차례 (original · rewrite). 고르기 전에는 화면에 알리지 않는다")
    picked: str = Field("", description="블라인드 비교에서 고른 것 (original · rewrite), 건너뛰면 skip")


class RevLab(BaseModel):
    """역설계 실험 하나. <CANON_HOME>/.revlab/<id>.json. 작품 데이터가 아니다."""
    id: int
    title: str = ""
    created: str = ""
    split: str = Field("one", description="화를 나눈 규칙 (revlab.SPLITS)")
    preface: str = Field("", description="첫 화 제목 줄 앞의 짧은 글 (작품 제목 · 작가 줄). 역설계하지 않는다")
    episodes: list[RevEpisode] = Field(default_factory=list)
    cast: list[RevPerson] = Field(default_factory=list)
    main: str = ""
    lines: list[Storyline] = Field(default_factory=list)
    lines_at: str = ""

Snapshot.model_rebuild()
SerialRebuild.model_rebuild()
ShortArchive.model_rebuild()
StageScene.model_rebuild()
Episode.model_rebuild()
PlotUndo.model_rebuild()
ChatMessage.model_rebuild()
WriteRecord.model_rebuild()
AgentTurn.model_rebuild()
AgentSession.model_rebuild()
StyleEntry.model_rebuild()
