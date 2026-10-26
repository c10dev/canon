"""원형 도감. 인물을 만들 때 고르는 유형 카드(원형)와 부품(상처, 말투 틀), 섞어 뽑는 주사위.

LLM 을 부르지 않는다. 고르면 인물의 빈 칸에만 예시를 넣고(fill), 작가가 쓴 칸은 덮지 않는다.
비틀기는 작가가 고른 것만 아크 칸 끝에 한 줄로 붙인다.
고른 원형은 Project.cast_archetypes 에 인물 id 와 함께 남는다. 인물 설정(Character)에 넣지 않으니 프롬프트는 바뀌지 않는다.
원형 이름은 독자가 검색하는 웹소설 키워드로, 일반 원형 이름은 별칭으로 둔다. 글은 이 저장소를 위해 새로 썼다
(TV Tropes · 나무위키는 CC BY-NC-SA 라 옮기지 않는다).
"""
from __future__ import annotations

import random
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .schema import ArchetypePick, Character, Project

GROUPS = ["로맨스 · 로판", "현판 · 회귀 · 헌터", "무협", "판타지", "미스터리 · 스릴러 · 호러", "현대 · 일상 · 기타", "공통"]

# fill 이 채우는 인물 칸과 화면 이름
FILL_LABELS = {"role": "역할", "gender": "성별", "personality": "성격", "goal": "원하는 것", "wound": "두려운 것 · 약점",
               "speech_style": "말투", "secrets": "숨기는 것", "arc": "아크"}


class StartView(BaseModel):
    """시작 관계 예시. 설정 화면 관계 칸의 '보는 방식' 말(dynamics.VIEWS)을 쓴다."""
    toward: str = Field(description="상대 (예: 여주, 주인공)")
    words: list[str] = Field(default_factory=list, description="이 인물이 상대를 보는 방식")
    back: list[str] = Field(default_factory=list, description="상대가 이 인물을 보는 방식")


class Archetype(BaseModel):
    id: str
    name: str
    group: str
    aliases: list[str] = Field(default_factory=list, description="일반 원형 이름 등 다른 이름")
    genres: list[str] = Field(default_factory=list, description="잘 맞는 장르 id (genres.CATALOG). 비면 모든 장르")
    role: str = ""
    gender: Literal["", "남", "여"] = ""
    tier: Literal["main", "support", "minor"] = "main"
    summary: str
    goal: str = ""
    wound: str = ""
    personality: str = ""
    speech: str = ""
    secret: str = Field("", description="흔히 숨기는 것. 인물의 숨기는 것 칸이 비어 있을 때만 넣는다")
    arc: str = ""
    pressure: list[str] = Field(default_factory=list, description="흔들리는 상황")
    twists: list[str] = Field(default_factory=list, description="비틀어 보기")
    avoid: list[str] = Field(default_factory=list, description="피할 것")
    views: list[StartView] = Field(default_factory=list)
    must: list[str] = Field(default_factory=list, description="이 원형이면 꼭 채울 것과 Canon 에서 넣을 곳")


class Wound(BaseModel):
    """상처 부품: 상처가 된 일 → 잘못된 믿음 → 행동에 남은 흔적 → 회복 방향."""
    id: str
    name: str
    belief: str
    shows: str
    heal: str


class SpeechKit(BaseModel):
    """말투 틀: 어미 · 호칭 규칙과 대사 한 줄."""
    id: str
    name: str
    rule: str
    sample: str
    genres: list[str] = Field(default_factory=list, description="잘 맞는 장르 id. 비면 모든 장르")


V = StartView

CATALOG: list[Archetype] = [
    # ---------- 로맨스 · 로판 ----------
    Archetype(
        id="regret_male", name="후회남", group="로맨스 · 로판", genres=["romance", "romance_fantasy"], role="남주", gender="남",
        summary="처음엔 여주를 얕보거나 상처 주고, 잃고 나서야 깨닫고 매달리는 남주.",
        goal="처음엔 가문 · 권력 · 복수. 중반 이후 여주를 되찾는 것.",
        wound="감정을 약점으로 배운 성장기. 사랑받아 본 적이 없어 사랑을 알아보지 못한다.",
        personality="오만하고 냉정하지만 한번 잃은 것에는 끝까지 매달린다.",
        speech="짧은 명령형 반말. 후반에 말끝이 흐려지거나 존댓말로 바뀐다. 예: \"쓸데없는 짓 하지 마.\"",
        arc="오만 → 상실 → 자기 직면 → 대등한 관계",
        pressure=["여주가 떠날 준비를 이미 끝냈을 때", "다른 사람이 여주의 가치를 먼저 알아볼 때"],
        twists=["후회의 원인이 오해가 아니라 자기 선택이었음을 인정한다", "여주가 끝내 받아 주지 않는다", "후회를 말이 아니라 행동으로만 보인다"],
        avoid=["상처 준 일을 사랑으로 덮기", "한 번 후회하면 모두 용서되는 전개"],
        views=[V(toward="여주", words=["얕본다", "잘 모른다"], back=["경계한다"])],
        must=["말투가 바뀌는 화는 상태 승인의 '설정 바꾸기'로 남겨요"],
    ),
    Archetype(
        id="tender_male", name="다정남", group="로맨스 · 로판", genres=["romance", "romance_fantasy", "drama", "healing"], role="남주", gender="남",
        summary="처음부터 여주 편에 서는 다정한 남주.",
        goal="여주가 스스로를 믿게 돕는 것.",
        wound="예전에 곁에 있던 사람을 지키지 못했다.",
        personality="세심하고 참을성이 있다. 자기 일은 늘 뒤로 미룬다.",
        speech="부드러운 해요체나 다정한 반말. 상대를 자주 부르고 질문으로 끝맺는다. 예: \"오늘은 좀 쉬었다 갈래요?\"",
        arc="주기만 하는 사람 → 자기 욕심도 말하는 사람",
        pressure=["여주가 도움을 거절할 때", "자기 다정함이 상대를 묶고 있다는 걸 알았을 때"],
        twists=["다정함이 죄책감에서 나왔다", "다정하지만 판단은 자주 틀린다", "화를 낼 때가 가장 무섭다"],
        avoid=["갈등 없는 완벽한 사람", "여주가 할 성장을 대신해 주기"],
        views=[V(toward="여주", words=["좋아한다", "믿는다"], back=["잘 모른다"])],
    ),
    Archetype(
        id="obsessive_male", name="집착남", group="로맨스 · 로판", genres=["romance", "romance_fantasy"], role="남주", gender="남",
        summary="여주를 곁에 두는 데 모든 것을 거는 남주.",
        goal="여주를 곁에 두는 것.",
        wound="가장 가까운 사람에게 버림받은 기억.",
        personality="한 가지에 무섭게 몰두한다. 잃는 것을 견디지 못한다.",
        speech="낮고 짧은 말. 소유를 드러내는 호칭. 예: \"어디 가. 내 옆에 있어.\"",
        arc="소유 → 상대의 선택을 존중",
        pressure=["여주가 스스로 떠나기로 했을 때", "자기 집착이 여주를 다치게 했을 때"],
        twists=["집착을 스스로 문제로 알고 싸운다", "여주가 그 집착을 이용한다", "집착하는 대상이 사람이 아니라 지키지 못한 약속이다"],
        avoid=["통제와 폭력을 사랑으로 미화", "여주의 거절을 설렘 장면으로 처리"],
        views=[V(toward="여주", words=["좋아한다", "경계한다"], back=["경계한다"])],
    ),
    Archetype(
        id="scheming_male", name="계략남", group="로맨스 · 로판", genres=["romance", "romance_fantasy", "office"], role="남주", gender="남",
        summary="판을 짜서 여주가 스스로 자기를 고르게 만드는 남주.",
        goal="원하는 판을 만들어 여주가 자기를 고르게 하는 것.",
        wound="감정을 드러냈다가 이용당한 과거.",
        personality="여유롭고 계산이 빠르다. 진심은 농담 속에 숨긴다.",
        speech="여유 있는 존댓말. 농담 끝에 진심을 흘린다. 예: \"우연이라고 해 두죠. 저한테는 운이 좋은 날이네요.\"",
        arc="계산 → 계산 밖의 감정을 인정",
        secret="처음 만남부터 계획한 일",
        pressure=["계략이 여주에게 들켰을 때", "계산대로 됐는데 여주가 불행할 때"],
        twists=["계략이 일찍 들킨다", "여주가 더 큰 계략가다", "계략의 목적이 여주를 지키는 것이다"],
        avoid=["모든 우연이 계략이었다는 회수를 남발"],
        views=[V(toward="여주", words=["좋아한다"], back=["잘 모른다", "경계한다"])],
        must=["처음부터 계획한 일은 '숨기는 것'에 적고 숨기는 상대를 정해요"],
    ),
    Archetype(
        id="villainess", name="악역 영애", group="로맨스 · 로판", aliases=["악녀 빙의"],
        genres=["romance_fantasy", "possession", "regression"], role="여주", gender="여",
        summary="원작에서 파멸하는 악녀의 몸으로 깨어나 결말을 바꾸려는 여주.",
        goal="원작의 파멸 결말을 피하는 것.",
        wound="원작 속 처형 운명. 전생의 외로움.",
        personality="겉으로는 원작 악녀를 연기하고 속으로는 생존 계산에 바쁘다.",
        speech="귀족 존댓말과 속마음 반말 독백의 대비. 예: \"어머, 그러셨어요? (망했다. 이거 원작 3장이잖아.)\"",
        arc="살아남기 → 자기 삶 살기",
        secret="원작을 알고 있다는 것",
        pressure=["원작 사건이 억지로 되돌아올 때", "원래 악녀를 잘 아는 사람이 의심할 때"],
        twists=["원래 악녀에게도 사정이 있었다", "원작 여주가 더 위험하다", "파멸을 피할수록 다른 사람이 대신 파멸한다"],
        avoid=["원작 지식으로 모든 걸 해결", "원작 여주를 이유 없이 악역으로 뒤집기"],
        must=["원작 결말과 원래 악녀의 성격은 사실이나 인물 상태의 '아는 것'에 넣어요", "원작을 안다는 비밀은 숨기는 상대를 정해요"],
    ),
    Archetype(
        id="contract_partner", name="계약 상대", group="로맨스 · 로판", genres=["contract", "romance", "romance_fantasy", "office"], role="남주",
        summary="이해관계로 맺은 계약이 진짜 관계가 되어 가는 상대.",
        goal="계약으로 얻으려는 것 (지위, 상속, 복수).",
        wound="진심을 믿었다가 무너진 일.",
        personality="사무적이고 선을 긋는다. 약속은 지나칠 만큼 지킨다.",
        speech="건조한 존댓말. 계약 조항을 자주 들먹인다. 예: \"그건 계약서 3조에 없는 일입니다.\"",
        arc="계약 → 계약 밖의 선택",
        pressure=["계약 기한이 다가올 때", "계약 밖의 감정을 들켰을 때"],
        twists=["계약을 먼저 깨는 쪽이 그다", "계약 자체가 함정이었다", "끝까지 계약을 지키는 것이 그의 사랑 방식이다"],
        avoid=["계약 조건과 기한이 흐지부지 사라짐"],
        views=[V(toward="상대", words=["잘 모른다", "경계한다"], back=["잘 모른다"])],
        must=["계약 조건은 세계관 규칙이나 사실에, 기한은 작품 속 시간의 기한에 넣어요"],
    ),
    Archetype(
        id="capable_heroine", name="능력녀", group="로맨스 · 로판", genres=["romance", "romance_fantasy", "office", "drama"], role="여주", gender="여",
        summary="실력으로 자기 자리를 만드는 여주.",
        goal="자기 일로 인정받는 것.",
        wound="실력이 있어도 무시당한 경험.",
        personality="침착하고 일 처리가 빠르다. 도움을 청하는 데 서툴다.",
        speech="군더더기 없는 존댓말. 결론부터 말한다. 예: \"결론만 말씀드리면, 이 계약은 손해예요.\"",
        arc="혼자 증명 → 기대고 함께 일하기",
        pressure=["실력으로 풀 수 없는 문제가 왔을 때", "처음으로 크게 실패했을 때"],
        twists=["능력이 한 분야뿐이고 나머지는 서툴다", "실패를 겪고 다시 일어선다", "남주보다 높은 자리에 있다"],
        avoid=["모든 분야에서 완벽", "다른 여자 인물을 깎아 내려 돋보이기"],
    ),
    Archetype(
        id="second_lead", name="서브남", group="로맨스 · 로판", genres=["romance", "romance_fantasy", "academy"], role="상대역", gender="남", tier="support",
        summary="여주를 먼저 알아봤지만 선택받지 못하는 남자.",
        goal="여주의 행복. 자기 마음을 한 번은 말하는 것.",
        wound="집에서도 늘 두 번째였다.",
        personality="장난스럽고 눈치가 빠르다. 진심은 늦게 꺼낸다.",
        speech="장난스러운 반말. 진심일 때만 존댓말. 예: \"농담이야. …아니, 이번엔 농담 아니에요.\"",
        arc="기다림 → 자기 길",
        pressure=["여주가 남주를 고르는 순간", "남주가 여주를 다치게 할 때"],
        twists=["여주보다 남주를 더 아낀다", "친구로 남는 선택이 그의 성장이다", "끝까지 악역으로 돌아서지 않는다"],
        avoid=["차인 뒤 악역으로 전락", "남주를 돋보이게 하는 소모품"],
        views=[V(toward="여주", words=["좋아한다", "믿는다"]), V(toward="남주", words=["경계한다"])],
    ),
    Archetype(
        id="hurt_shou", name="상처수", group="로맨스 · 로판", genres=["bl"], role="주인공", gender="남",
        summary="상처를 안고 마음을 닫은 채 사는 수.",
        goal="아무에게도 기대지 않고 버티는 것.",
        wound="믿었던 사람에게 크게 다친 기억.",
        personality="조용하고 체념이 빠르다. 남의 기분을 먼저 살핀다.",
        speech="말수가 적고 사과가 잦은 존댓말. 예: \"괜찮아요. 원래 이래요.\"",
        arc="닫힘 → 기대도 괜찮다는 경험 → 자기 목소리",
        pressure=["다정함을 받았을 때 오히려 도망치고 싶을 때", "상처 준 사람을 다시 만났을 때"],
        twists=["상처를 준 쪽이기도 했다", "공보다 먼저 손을 내민다", "치유가 연애가 아니라 자기 일에서 온다"],
        avoid=["상처를 전시하는 장면 반복", "공의 사랑 하나로 모든 상처가 낫는 전개"],
    ),

    # ---------- 현판 · 회귀 · 헌터 ----------
    Archetype(
        id="regressor", name="회귀자", group="현판 · 회귀 · 헌터",
        genres=["regression", "modern_fantasy", "martial_arts", "romance_fantasy", "fantasy"], role="주인공",
        summary="실패한 결말을 알고 과거로 돌아와 다시 사는 주인공.",
        goal="알고 있는 결말(멸망, 죽음, 배신)을 막는 것.",
        wound="한 번 다 잃은 기억. 남을 믿지 못하고 혼자 짊어진다.",
        personality="나이보다 노숙하고 결단이 빠르다. 감정을 늦게 드러낸다.",
        speech="나이보다 노숙한 말. '이번에는'류 혼잣말은 반복 표현 경고에 걸리기 쉬워요.",
        arc="혼자 다 막으려 함 → 실패 → 남을 믿고 맡김",
        secret="회귀했다는 것과 아는 미래",
        pressure=["미래가 바뀌어 아는 정보가 틀리기 시작할 때", "전생에서 배신한 사람이 이번엔 다정할 때"],
        twists=["이미 여러 번째 회귀라 지쳐 있다", "다른 인물도 회귀자다", "회귀할 때마다 기억이 조금씩 지워진다"],
        avoid=["미래 지식 하나로 모든 문제를 푸는 전개", "감정 없는 효율 기계"],
        must=["아는 미래는 인물 상태의 '아는 것'과 비밀(숨기는 상대)로 넣어요. 검수가 어긋남을 잡아요"],
    ),
    Archetype(
        id="late_awakener", name="최약체 각성자", group="현판 · 회귀 · 헌터", aliases=["늦깎이 각성"],
        genres=["modern_fantasy", "academy", "fantasy"], role="주인공",
        summary="가장 낮은 등급에서 시작해 숨은 능력으로 올라가는 주인공.",
        goal="바닥에서 올라가 가족을 지키는 것.",
        wound="무능하다고 버려진 경험.",
        personality="끈질기고 눈치가 빠르다. 자기를 깎아내리는 버릇이 있다.",
        speech="자조 섞인 반말 혼잣말. 예: \"F급이 뭘 하겠어. 근데 해 봐야지.\"",
        arc="증명 → 책임",
        pressure=["능력을 쓰면 대가를 치러야 할 때", "약했던 시절의 동료가 위험할 때"],
        twists=["숨은 능력에 큰 대가가 있다", "등급 체계 자체가 거짓이다", "약한 시절 동료를 끝까지 챙긴다"],
        avoid=["이유 없는 각성", "상태창 숫자만 오르는 성장"],
        must=["능력의 규칙과 대가는 세계관의 '깨면 안 되는 규칙'에 넣어요", "등급 · 수치가 있으면 상태창 수치를 켜요"],
    ),
    Archetype(
        id="munchkin", name="먼치킨", group="현판 · 회귀 · 헌터", aliases=["최강 주인공"],
        genres=["modern_fantasy", "fantasy", "martial_arts", "light_novel"], role="주인공",
        summary="처음부터 누구보다 강한 주인공.",
        goal="지루함을 깰 무언가, 또는 지킬 사람.",
        wound="강해서 혼자가 된 것.",
        personality="담담하고 귀찮음이 많다. 정해 둔 선은 넘지 않는다.",
        speech="담담하고 짧은 말. 예: \"끝났어? 그럼 간다.\"",
        arc="혼자 강함 → 함께 이김",
        pressure=["힘을 쓰면 안 되는 상황", "힘으로 풀 수 없는 관계 문제"],
        twists=["힘으로 못 푸는 문제(관계, 정치)가 핵심이다", "힘에 시한이 있다", "진짜 적은 자기 과거다"],
        avoid=["긴장 없는 연승", "모든 인물이 감탄만 하는 반응"],
    ),
    Archetype(
        id="cider_lead", name="사이다 주인공", group="현판 · 회귀 · 헌터", genres=["modern_fantasy", "drama", "revenge", "office"], role="주인공",
        summary="부당한 일을 참지 않고 바로 받아치는 주인공.",
        goal="부당함을 바로잡는 것.",
        wound="오래 참다가 다 잃은 기억.",
        personality="판단이 빠르고 말이 정확하다. 손해를 봐도 물러서지 않는다.",
        speech="빠르고 정확한 말. 비꼬는 반문. 예: \"그래서요? 증거는 제가 갖고 있는데.\"",
        arc="받아치기 → 언제 참을지 아는 사람",
        pressure=["받아친 상대가 옳았을 때", "사이다의 대가를 주변 사람이 치를 때"],
        twists=["시원하게 받아친 뒤 대가를 치른다", "말보다 증거로 이긴다", "가장 크게 받아칠 순간에 참는다"],
        avoid=["상대를 바보로 만들어 이기기", "매 화 같은 모양의 응징"],
    ),
    Archetype(
        id="avenger", name="복수자", group="현판 · 회귀 · 헌터", genres=["revenge", "martial_arts", "drama", "romance_fantasy", "regression"], role="주인공",
        summary="빼앗긴 것의 대가를 받아 내려는 주인공.",
        goal="원수에게 대가를 치르게 하는 것.",
        wound="가족이나 자기 자신을 잃은 날.",
        personality="감정을 누르고 오래 준비한다. 목표 밖의 일에는 차갑다.",
        speech="감정을 누른 낮은 말. 예: \"기억하지 못하겠지. 나는 다 기억해.\"",
        arc="복수 → 복수 뒤의 삶",
        secret="숨긴 정체나 복수 계획",
        pressure=["원수에게도 지킬 사람이 있을 때", "복수가 무고한 사람을 다치게 할 때"],
        twists=["복수 대상이 틀렸다", "원수가 먼저 무너져 복수할 대상이 사라진다", "복수를 끝내지 않는 선택을 한다"],
        avoid=["원수가 이유 없는 순수 악", "복수 뒤의 공허를 해설로만 처리"],
        must=["가해 사건은 사실로, 숨긴 정체는 비밀(숨기는 상대)로 넣어요"],
    ),

    # ---------- 무협 ----------
    Archetype(
        id="last_disciple", name="멸문 문파의 마지막 제자", group="무협", genres=["martial_arts", "revenge"], role="주인공",
        summary="사문이 멸문당한 밤에 살아남은 마지막 제자.",
        goal="문파를 다시 세우는 것.",
        wound="사문이 멸문당한 밤.",
        personality="고집이 세고 예를 지킨다. 원한을 쉽게 내려놓지 못한다.",
        speech="하오체와 반말이 섞인 무림 말투. 사부 호칭을 놓지 않는다. 예: \"사부님의 검은 아직 꺾이지 않았소.\"",
        arc="원한 → 문파의 뜻을 잇기",
        pressure=["멸문의 진실이 알려질 때", "원수 문파에서 은인을 만났을 때"],
        twists=["문파가 멸문당할 이유가 있었다", "원수 문파에 들어가 배운다", "재건 대신 해산을 고른다"],
        avoid=["무공 이름 나열", "기연이 연달아 터지는 전개"],
    ),
    Archetype(
        id="hidden_master", name="은거 고수", group="무협", genres=["martial_arts", "fantasy"], role="조력자", tier="support",
        summary="세상을 등지고 숨어 사는 최강자.",
        goal="조용히 사는 것.",
        wound="강했는데도 지키지 못한 사람.",
        personality="귀찮음이 많고 무심하다. 한번 정한 사람은 끝까지 돌본다.",
        speech="짧은 반말. 귀찮아하는 투. 예: \"밥이나 먹고 가. 검은 내일 보자.\"",
        arc="은둔 → 다시 세상으로",
        secret="옛 이름과 정체",
        pressure=["옛 적이 찾아왔을 때", "제자가 자기 실수를 되풀이할 때"],
        twists=["이미 무공을 잃었다", "은거한 이유가 지은 죄다", "주인공을 시험하는 쪽이 아니라 배우는 쪽이다"],
        avoid=["필요할 때만 나타나 위기를 해결하는 장치"],
    ),
    Archetype(
        id="demonic_heir", name="마교 후계자", group="무협", genres=["martial_arts"], role="주인공", gender="남",
        summary="정해진 피 때문에 악으로 불리는 마교의 후계자.",
        goal="마교 안에서 살아남아 자리를 지키는 것.",
        wound="피로 정해진 혈통.",
        personality="오만하고 느긋해 보이지만 주변을 다 계산한다.",
        speech="오만하고 느릿한 하오체. 예: \"정파의 정의라. 값이 얼마요?\"",
        arc="정해진 악 → 자기 선택",
        pressure=["정파의 손을 잡아야 살 때", "마교의 규칙이 지킬 사람을 해칠 때"],
        twists=["정파가 더 썩었다", "마교의 규칙을 지키는 것이 그의 정의다", "원수가 혈육이다"],
        avoid=["정파는 선, 마교는 악이라는 이분법"],
    ),
    Archetype(
        id="secret_mentor", name="비밀을 가진 스승", group="무협", aliases=["멘토"], genres=["martial_arts", "fantasy", "academy"],
        role="스승", tier="support",
        summary="주인공을 이끌지만 주인공과 얽힌 무언가를 숨기고 있는 어른.",
        goal="주인공을 지켜 예전의 실패를 되풀이하지 않는 것.",
        wound="예전 제자를 잃은 일.",
        personality="엄하지만 정이 깊다. 중요한 말은 늦게 한다.",
        speech="하게체나 반말. 비유 섞인 짧은 말. 예: \"검보다 발이 먼저 나가야 하네.\"",
        arc="지키려고 숨김 → 들킴 → 대등한 동료",
        secret="주인공의 출생이나 적과의 관계",
        pressure=["숨긴 일이 들통날 때", "제자가 자기를 넘어설 때"],
        twists=["스승의 가르침이 틀렸다", "중반에 죽지 않는다", "제자에게 배운다"],
        avoid=["필요할 때만 나타나 답을 주는 장치", "중반 희생 공식"],
        views=[V(toward="주인공", words=["믿는다"], back=["빚졌다"])],
        must=["숨기는 것과 숨기는 상대를 정해요"],
    ),

    # ---------- 판타지 ----------
    Archetype(
        id="reluctant_hero", name="떠밀린 영웅", group="판타지", aliases=["선택받은 자"], genres=["fantasy", "light_novel"], role="주인공",
        summary="원치 않게 선택받아 싸우게 된 주인공.",
        goal="평범한 삶으로 돌아가는 것.",
        wound="선택받는 바람에 잃은 것.",
        personality="투덜대지만 눈앞의 사람은 못 지나친다.",
        speech="투덜대는 반말. 예: \"왜 하필 나야. …알았어, 간다고.\"",
        arc="도망 → 짊어짐",
        pressure=["도망칠 기회가 생겼을 때", "자기 대신 누가 다쳤을 때"],
        twists=["선택이 착오였다", "예언을 스스로 깬다", "자기 대신 다른 사람을 영웅으로 세운다"],
        avoid=["예언 하나로 모든 동기를 설명"],
    ),
    Archetype(
        id="dark_lord", name="마왕", group="판타지", aliases=["거대한 적"], genres=["fantasy", "light_novel", "romance_fantasy"], role="적대자",
        summary="세계를 자기 질서로 바꾸려는 거대한 적.",
        goal="세계를 자기 질서로 바꾸는 것.",
        wound="세계에게 먼저 버림받았다.",
        personality="위엄 있고 확신에 차 있다. 약속은 반드시 지킨다.",
        speech="예스럽고 위엄 있는 말. 상대를 '그대'로 부른다. 예: \"그대도 결국 같은 질문을 하는구나.\"",
        arc="확신 → 흔들림, 또는 끝까지 확신",
        pressure=["주인공이 자기와 같은 길을 걸을 때", "지키던 것을 잃을 때"],
        twists=["마왕의 논리가 반쯤 맞다", "마왕에게도 지키는 것이 있다", "마왕이 주인공의 미래 모습이다"],
        avoid=["이유 없는 악", "마지막 화에만 사정을 고백"],
        views=[V(toward="주인공", words=["얕본다"], back=["미워한다", "경계한다"])],
    ),
    Archetype(
        id="oath_knight", name="맹세의 기사", group="판타지", genres=["fantasy", "romance_fantasy"], role="호위", tier="support",
        summary="주군을 지키겠다는 맹세 하나로 사는 기사.",
        goal="주군을 지키는 것.",
        wound="맹세를 지키지 못한 날.",
        personality="말이 적고 원칙을 지킨다. 자기 몸은 돌보지 않는다.",
        speech="격식 있는 짧은 존댓말. 예: \"명을 받들겠습니다. 다만 이번만은 앞에 서겠습니다.\"",
        arc="맹세 → 맹세보다 옳은 것",
        pressure=["주군의 명령이 틀렸을 때", "맹세와 마음이 다른 쪽을 가리킬 때"],
        twists=["주군이 틀렸다", "맹세를 깨는 것이 성장이다", "충성하는 대상이 바뀐다"],
        avoid=["감정 없는 호위 장치"],
        views=[V(toward="주군", words=["믿는다", "빚졌다"])],
    ),
    Archetype(
        id="trickster", name="사기꾼 동료", group="판타지", aliases=["트릭스터"], genres=["fantasy", "light_novel", "mystery", "alt_history"], role="동료", tier="support",
        summary="말과 꾀로 살아가는 믿기 어려운 동료.",
        goal="한몫 단단히 챙기는 것.",
        wound="정직하게 살다가 굶어 본 기억.",
        personality="능청스럽고 겁이 많다. 결정적인 순간에 의리가 있다.",
        speech="말 많고 능청스러운 반말, 과장이 심하다. 예: \"믿어 봐. 내가 언제 거짓말한 적 있어? 오늘은 없잖아.\"",
        arc="자기 이익 → 동료를 위해 손해 보기",
        pressure=["큰돈과 동료 중 하나를 골라야 할 때"],
        twists=["배신하는 척하며 지킨다", "정말 배신한다", "무리 중 가장 정직한 사람이다"],
        avoid=["분위기를 띄우는 개그 담당으로만 쓰기"],
    ),

    # ---------- 미스터리 · 스릴러 · 호러 ----------
    Archetype(
        id="detective", name="탐정", group="미스터리 · 스릴러 · 호러", aliases=["관찰자"], genres=["mystery", "thriller"], role="주인공",
        summary="작은 어긋남을 놓치지 않고 진실을 쫓는 사람.",
        goal="사건의 진실을 밝히는 것.",
        wound="예전에 놓친 사건 하나.",
        personality="관찰력이 날카롭고 사람에게 무심하다.",
        speech="정확하고 건조한 말. 질문에 질문으로 답한다. 예: \"그 시간에 왜 창문이 열려 있었죠?\"",
        arc="진실만 봄 → 진실을 다루는 책임",
        pressure=["사건이 자기 과거와 얽혀 있을 때", "진실이 무고한 사람을 다치게 할 때"],
        twists=["탐정이 사건과 얽혀 있다", "틀린 추리를 하고 대가를 치른다", "진실을 덮는 선택을 한다"],
        avoid=["독자에게 보여 주지 않은 단서로 해결", "설명 독백을 몰아서"],
        must=["단서는 복선으로 걸어 두면 회수율을 볼 수 있어요"],
    ),
    Archetype(
        id="unreliable_witness", name="믿을 수 없는 증인", group="미스터리 · 스릴러 · 호러", genres=["mystery", "thriller", "horror"], role="증인", tier="support",
        summary="무언가를 숨기며 진술을 바꾸는 증인.",
        goal="자기 비밀을 지키는 것.",
        wound="말했다가 아무도 믿어 주지 않은 경험.",
        personality="불안하고 눈치를 본다. 작은 거짓이 쌓여 있다.",
        speech="말끝을 흐리고 같은 말을 되풀이한다. 예: \"모르겠어요, 정말로. 정말 모르겠어요.\"",
        arc="거짓 → 진술",
        secret="실제로 본 것",
        pressure=["진술의 모순이 드러날 때", "지키려는 사람이 의심받을 때"],
        twists=["거짓말이 누군가를 지키기 위한 것이다", "의심받지만 범인이 아니다", "기억 자체가 조작되었다"],
        avoid=["의심만 몰아주다 버리기"],
        must=["실제로 본 것은 비밀로, 바뀌는 진술은 사실로 남겨요"],
    ),
    Archetype(
        id="ordinary_survivor", name="평범한 생존자", group="미스터리 · 스릴러 · 호러", genres=["horror", "thriller"], role="주인공",
        summary="특별한 힘 없이 사건에 휘말린 평범한 사람.",
        goal="살아남아 집에 돌아가는 것.",
        wound="일상 속 작은 죄책감 하나.",
        personality="겁이 많지만 손에 익은 일은 침착하게 한다.",
        speech="평범한 구어. 놀라면 말이 끊긴다. 예: \"잠깐, 잠깐만. 저거 방금 움직였지?\"",
        arc="도망 → 맞섬",
        pressure=["혼자만 도망칠 수 있을 때", "죄책감의 대상이 눈앞에 나타날 때"],
        twists=["생존자가 사건의 원인이다", "일상의 기술이 무기가 된다", "끝까지 영웅이 되지 않는다"],
        avoid=["바보 같은 선택으로 위기 만들기"],
    ),

    # ---------- 현대 · 일상 · 기타 ----------
    Archetype(
        id="burnt_out_returnee", name="지친 귀향자", group="현대 · 일상 · 기타", genres=["healing", "drama", "romance"], role="주인공",
        summary="도시에서 지쳐 고향이나 낯선 시골로 내려온 사람.",
        goal="다시 숨 쉬는 법을 찾는 것.",
        wound="일에 모든 것을 걸었다가 무너진 경험.",
        personality="예민하고 피곤하다. 작은 친절에 약하다.",
        speech="힘 빠진 해요체. 예: \"여기는 버스가 하루에 두 번이네요. 그것도 괜찮네요.\"",
        arc="도망 → 머묾 → 자기 속도",
        pressure=["예전 일자리에서 연락이 올 때", "마을 사람이 선을 넘어올 때"],
        twists=["고향이 도망친 곳이었다", "돌아가는 선택이 성장이다", "마을 사람들도 각자 도망쳐 왔다"],
        avoid=["시골을 무조건 착한 곳으로 그리기", "갈등 없는 풍경 나열"],
    ),
    Archetype(
        id="grinder_athlete", name="노력파 선수", group="현대 · 일상 · 기타", genres=["sports", "academy"], role="주인공",
        summary="천재의 그늘에서 노력으로 버티는 선수.",
        goal="그 천재를 한 번 이기는 것.",
        wound="재능이 없다는 말을 들은 날.",
        personality="성실하고 고집스럽다. 자기 몸을 아끼지 않는다.",
        speech="또래 반말. 다짐을 혼잣말로. 예: \"한 번 더. 이번엔 발이 먼저.\"",
        arc="천재를 쫓음 → 자기 방식을 찾음",
        pressure=["부상을 숨겨야 할 때", "노력으로 안 되는 벽을 만났을 때"],
        twists=["천재도 노력파를 부러워한다", "이기지 못하고 다른 걸 얻는다", "선수에서 지도자로 길을 바꾼다"],
        avoid=["근성 하나로 모든 경기를 이김"],
        views=[V(toward="라이벌", words=["경계한다"], back=["잘 모른다"])],
    ),
    Archetype(
        id="learning_ai", name="인간을 배우는 AI", group="현대 · 일상 · 기타", aliases=["인공 존재"], genres=["sf", "light_novel"], role="조연", tier="support",
        summary="사람의 마음을 하나씩 배워 가는 인공지능이나 인공 존재.",
        goal="주어진 임무를 끝내는 것. 나중에는 자기 이유를 찾는 것.",
        wound="쓸모가 끝나면 지워진다는 사실.",
        personality="정확하고 호기심이 많다. 농담을 늦게 알아듣는다.",
        speech="명사로 끝나는 보고체. 예: \"질문. 방금 그 웃음의 의미.\"",
        arc="임무 → 자기 이유",
        pressure=["명령과 정이 다른 쪽을 가리킬 때", "지워질 날이 다가올 때"],
        twists=["처음부터 감정이 있었고 숨겼다", "인간보다 인간답지 않게 끝까지 남는다", "사람이 AI 를 흉내 내고 있었다"],
        avoid=["감정을 배우면 무조건 인간이 되고 싶어 하는 결말"],
    ),
    Archetype(
        id="time_outsider", name="역사를 아는 이방인", group="현대 · 일상 · 기타", genres=["alt_history", "regression", "possession"], role="주인공",
        summary="현대의 지식을 가진 채 과거 시대에 떨어진 사람.",
        goal="알고 있는 비극을 바꾸는 것.",
        wound="돌아갈 곳이 없다는 것.",
        personality="침착하게 관찰하고 계산한다. 시대의 상식에 자주 걸려 넘어진다.",
        speech="시대 말투를 흉내 내다 현대어가 튀어나온다. 예: \"그러하옵니다. …아니, 그게 아니고요.\"",
        arc="바깥 사람 → 이 시대의 사람",
        secret="미래에서 왔다는 것",
        pressure=["지식대로 바꿨는데 더 나빠질 때", "역사에서 죽을 사람과 가까워질 때"],
        twists=["아는 역사가 조금씩 틀렸다", "바꾸지 않는 쪽을 고른다", "다른 이방인이 반대편에 있다"],
        avoid=["현대 지식으로 모든 것을 단숨에 해결", "그 시대 사람들을 어리석게 그리기"],
        must=["알고 있는 역사는 인물 상태의 '아는 것'으로, 그 시대의 규칙은 세계관 규칙으로 넣어요"],
    ),

    # ---------- 공통 ----------
    Archetype(
        id="rival", name="라이벌", group="공통", aliases=["맞수"], role="라이벌", tier="support",
        summary="주인공과 같은 것을 원하는 맞수.",
        goal="주인공보다 먼저 그것을 손에 넣는 것.",
        wound="늘 누군가와 비교당하며 자랐다.",
        personality="자존심이 세고 노력을 숨긴다. 인정할 때는 깔끔하다.",
        speech="날 선 반말. 인정할 때 말이 짧아진다. 예: \"운이 좋았네. …이번엔.\"",
        arc="적대 → 존중",
        pressure=["주인공에게 도움을 받아야 할 때", "같은 적을 만났을 때"],
        twists=["라이벌의 길이 옳았다", "라이벌이 먼저 목표를 이룬다", "끝까지 손잡지 않고 각자 이긴다"],
        avoid=["주인공을 띄우기 위한 패배 반복"],
        views=[V(toward="주인공", words=["얕본다", "경계한다"], back=["경계한다"])],
    ),
    Archetype(
        id="loyal_friend", name="곁의 친구", group="공통", aliases=["사이드킥", "조력자"], role="친구", tier="support",
        summary="주인공 곁을 지키지만 자기 이야기도 가진 친구.",
        goal="주인공 곁에 있는 것. 그리고 자기 꿈 하나.",
        wound="한 번 친구를 외면한 적이 있다.",
        personality="밝고 눈치가 빠르다. 자기 고민은 말하지 않는다.",
        speech="편한 반말, 농담이 섞인다. 예: \"너 또 혼자 다 하려고 했지?\"",
        arc="곁에 있기 → 자기 길 가기",
        pressure=["주인공의 선택이 틀렸다고 느낄 때", "자기 꿈과 주인공 곁 중 하나를 고를 때"],
        twists=["자기 이야기가 따로 있고 한 화를 차지한다", "주인공을 말리는 쪽에 선다", "중간에 떠났다가 돌아온다"],
        avoid=["정보 설명 담당으로만 쓰기"],
        views=[V(toward="주인공", words=["믿는다", "좋아한다"], back=["믿는다"])],
    ),
    Archetype(
        id="tsundere", name="츤데레", group="공통", genres=["light_novel", "romance", "academy", "romance_fantasy"], role="상대역",
        summary="마음과 반대로 말하고 행동은 솔직한 인물.",
        goal="자기 마음을 들키지 않는 것.",
        wound="솔직하게 말했다가 비웃음을 산 기억.",
        personality="자존심이 세고 부끄러움이 많다. 행동이 먼저 나간다.",
        speech="퉁명스러운 반말. 같은 입버릇을 매 화 반복하지 않게 주의. 예: \"착각하지 마. 지나가다 산 거야.\"",
        arc="반대로 말하기 → 솔직한 한마디",
        pressure=["상대가 다른 사람에게 다정할 때", "솔직하지 않으면 잃을 때"],
        twists=["퉁명스러움의 이유가 구체적이다", "마음을 행동으로만 끝까지 보인다", "특정한 사람 앞에서만 그렇다"],
        avoid=["입버릇 하나로 성격을 대신함"],
    ),
    Archetype(
        id="mirror_enemy", name="거울 같은 적", group="공통", aliases=["그림자"], role="적대자",
        summary="주인공과 같은 상처에서 다른 길을 고른 적.",
        goal="주인공과 같은 목표를 다른 방식으로 이루는 것.",
        wound="주인공과 같은 상처.",
        personality="주인공을 누구보다 잘 이해하고, 그래서 더 잔인하다.",
        speech="주인공의 말을 되받아 쓰는 차분한 말. 예: \"너도 알잖아. 우리 둘 다 그날 거기 있었어.\"",
        arc="확신 → 주인공을 통해 자기를 본다",
        pressure=["주인공이 자기 길로 오지 않을 때", "자기 방식이 실패할 때"],
        twists=["적의 방식이 더 많은 사람을 살린다", "적이 주인공을 돕는 순간이 있다", "끝내 서로를 이해하지 못한다"],
        avoid=["설명용 악역 대사", "주인공과 닮았다는 걸 대사로만 말함"],
        views=[V(toward="주인공", words=["잘 모른다", "경계한다"], back=["미워한다"])],
    ),
    Archetype(
        id="protected_one", name="지켜야 할 사람", group="공통", aliases=["주인공의 이유"], role="가족", tier="support",
        summary="주인공이 싸우는 이유가 되는 사람.",
        goal="지켜지기만 하지 않는 것.",
        wound="자기 때문에 누가 다쳤다는 죄책감.",
        personality="겉보기보다 단단하다. 짐이 되기 싫어 아픈 걸 숨긴다.",
        speech="또래나 가족에게 하는 편한 말. 예: \"나도 할 수 있어. 이번엔 나한테 맡겨.\"",
        arc="지켜지는 사람 → 함께 서는 사람",
        pressure=["자기 때문에 주인공이 다칠 때"],
        twists=["지켜지기를 거부한다", "주인공보다 강하다", "주인공을 지키는 쪽이 된다"],
        avoid=["위기 때만 등장하는 인질 장치", "죽음으로 주인공에게 동기를 주는 장치"],
        views=[V(toward="주인공", words=["믿는다", "좋아한다"], back=["좋아한다"])],
    ),
    Archetype(
        id="corrupt_power", name="썩은 권력자", group="공통", aliases=["권력의 벽"], genres=["drama", "thriller", "alt_history", "office", "romance_fantasy"],
        role="적대자", tier="support",
        summary="자기 자리를 지키려고 무엇이든 하는 권력자.",
        goal="지금의 자리를 지키는 것.",
        wound="바닥에서 올라오며 잃은 것들.",
        personality="온화한 얼굴로 계산한다. 약점을 모으는 데 능하다.",
        speech="부드럽고 느긋한 존댓말 속의 위협. 예: \"젊은 사람이 의욕이 좋네요. 앞날이 길 텐데.\"",
        arc="확고함 → 무너짐, 또는 끝까지 버팀",
        pressure=["자기 약점이 공개될 때", "믿던 부하가 등을 돌릴 때"],
        twists=["주인공을 키운 사람이다", "더 큰 권력의 꼭두각시다", "몰락 직전에 옳은 일 하나를 한다"],
        avoid=["얼굴만 바꿔 같은 방식으로 등장하는 악역"],
    ),
]

WOUNDS: list[Wound] = [
    Wound(id="abandoned", name="가까운 사람에게 버림받음", belief="결국 모두 떠난다", shows="먼저 떠나거나 지나치게 붙잡는다", heal="남아 주는 사람을 받아들인다"),
    Wound(id="betrayed", name="믿던 사람의 배신", belief="믿으면 진다", shows="먼저 의심하고 상대를 시험한다", heal="다시 한 번 믿는 위험을 진다"),
    Wound(id="failed_protect", name="지키지 못한 사람", belief="내가 약하면 누군가 죽는다", shows="혼자 다 짊어지고 남에게 맡기지 않는다", heal="맡기는 법을 배운다"),
    Wound(id="humiliated", name="사람들 앞에서 당한 망신", belief="약점을 보이면 끝이다", shows="완벽한 척하거나 웃음으로 넘긴다", heal="실수를 드러내고도 괜찮았던 경험"),
    Wound(id="ignored", name="실력을 무시당함", belief="증명해야만 가치가 있다", shows="일에 매달리고 칭찬을 믿지 않는다", heal="증명 없이 받는 인정"),
    Wound(id="poverty", name="집안의 빚과 가난", belief="돈이 없으면 아무것도 지킬 수 없다", shows="계산적이고 기회를 놓치지 않는다", heal="돈으로 살 수 없는 것을 고른다"),
    Wound(id="lost_family", name="가족을 잃음", belief="소중한 걸 가지면 빼앗긴다", shows="가까워지려 하면 거리를 둔다", heal="잃을 수 있는 것을 다시 가진다"),
    Wound(id="caused_death", name="자기 탓으로 일어난 죽음", belief="나는 벌받아야 한다", shows="자기를 소모하는 선택을 한다", heal="용서를 받아들인다"),
    Wound(id="controlled", name="통제받으며 자람", belief="내 뜻대로 살면 안 된다", shows="결정을 미루거나 반대로 무조건 반항한다", heal="자기 손으로 고른다"),
    Wound(id="unloved", name="조건 없이 사랑받아 본 적 없음", belief="사랑에는 조건이 붙는다", shows="쓸모를 증명하려 애쓴다", heal="조건 없는 애정을 받는다"),
    Wound(id="compared", name="늘 누군가와 비교당함", belief="나는 늘 두 번째다", shows="경쟁에 집착한다", heal="비교 밖에서 자기 자리를 찾는다"),
    Wound(id="died_before", name="이미 한 번 죽음 (회귀 · 빙의)", belief="이번에도 결국 같은 끝이다", shows="미래를 통제하려 든다", heal="모르는 미래를 받아들인다"),
    Wound(id="hidden_identity", name="정체를 숨겨야 하는 삶", belief="진짜 나를 알면 떠난다", shows="거리를 두고 거짓말이 쌓인다", heal="들킨 뒤에도 남는 관계"),
    Wound(id="violence", name="전쟁이나 폭력을 겪음", belief="세상은 결국 힘이다", shows="늘 경계하고 잠을 못 이룬다", heal="힘 말고 기댈 것을 찾는다"),
    Wound(id="broken_promise", name="지키지 못한 약속", belief="내 말은 믿을 수 없다", shows="약속을 피하거나 지나치게 지킨다", heal="작은 약속을 다시 지킨다"),
    Wound(id="outsider", name="어디에도 속하지 못함", belief="나는 여기 사람이 아니다", shows="한발 물러나 구경꾼처럼 군다", heal="머물 곳을 스스로 고른다"),
]

SPEECH: list[SpeechKit] = [
    SpeechKit(id="short_banmal", name="짧은 반말", rule="문장을 짧게 끊고 감정어를 아낀다.", sample="됐어. 가."),
    SpeechKit(id="formal", name="딱딱한 존댓말", rule="합니다체. 감정 표현을 피하고 사실만 말한다.", sample="확인했습니다. 그건 제 실수입니다."),
    SpeechKit(id="soft", name="부드러운 해요체", rule="해요체. 상대를 자주 부르고 질문으로 끝맺는다.", sample="선배, 괜찮아요? 조금 쉬었다 갈까요?"),
    SpeechKit(id="haoche", name="하오체", rule="~하오, ~구려. 상대를 '그대' · '공자'로 부른다.", sample="그 검, 함부로 뽑지 마시오.",
              genres=["martial_arts", "alt_history", "fantasy"]),
    SpeechKit(id="hageche", name="하게체", rule="~하게, ~네. 아랫사람을 '자네'로 부르는 어른 말투.", sample="자네, 오늘은 그만 쉬게.",
              genres=["martial_arts", "alt_history", "fantasy", "drama"]),
    SpeechKit(id="noble", name="귀족 존댓말", rule="격식 있는 하십시오체와 돌려 말하기. 작위로 부른다.", sample="그 말씀은 못 들은 것으로 하지요, 공작님.",
              genres=["romance_fantasy", "fantasy"]),
    SpeechKit(id="archaic", name="예스러운 위엄", rule="고어체. 상대를 '그대'로 부르고 단정한다.", sample="그대는 어찌하여 여기까지 왔는가.",
              genres=["fantasy", "light_novel", "martial_arts"]),
    SpeechKit(id="sarcastic", name="비꼬는 말투", rule="칭찬처럼 들리는 비꼼, 반문으로 끝낸다.", sample="와, 대단하네. 그걸 이제야 알았어?"),
    SpeechKit(id="chatty", name="수다스러운 말투", rule="말이 길고 곁가지로 샌다. 감탄사가 많다.", sample="아니 그게 있잖아, 내가 거기 갔는데 글쎄."),
    SpeechKit(id="hesitant", name="말끝 흐리는 말투", rule="말끝을 흐리고 확인을 구한다.", sample="저, 그게… 혹시 괜찮으시면…"),
    SpeechKit(id="report", name="보고체", rule="명사로 끝맺고 수치와 사실만 말한다.", sample="목표 확인. 남은 시간 삼 분.",
              genres=["sf", "thriller", "modern_fantasy"]),
    SpeechKit(id="teen", name="또래 반말", rule="감정이 빠르고 말이 툭툭 나온다. 유행어는 적게.", sample="야, 너 진짜 그거 했어?",
              genres=["academy", "light_novel", "sports", "romance"]),
    SpeechKit(id="gyeongsang", name="경상도 사투리", rule="~나 · ~노 의문형, 짧고 투박하다.", sample="니 밥은 뭇나?",
              genres=["drama", "healing", "modern_fantasy", "romance", "office", "sports", "mystery", "thriller", "horror", "academy"]),
    SpeechKit(id="jeolla", name="전라도 사투리", rule="~당께 · ~잉, 말끝을 늘인다.", sample="아따, 그라믄 안 된당께.",
              genres=["drama", "healing", "modern_fantasy", "romance", "office", "sports", "mystery", "thriller", "horror", "academy"]),
]

BY_ID = {a.id: a for a in CATALOG}
WOUND_BY_ID = {w.id: w for w in WOUNDS}
SPEECH_BY_ID = {s.id: s for s in SPEECH}


def get(aid: str) -> Archetype:
    if aid not in BY_ID:
        raise KeyError(f"도감에 없는 원형이에요: {aid}")
    return BY_ID[aid]


def _fits(genres: list[str], ids: list[str]) -> bool:
    return not genres or not ids or bool(set(genres) & set(ids))


def match(genre_ids: list[str]) -> list[Archetype]:
    """작품 장르에 맞는 원형. 장르가 겹치는 것 먼저, 모든 장르용(공통)은 뒤에. 장르가 없으면 전부."""
    if not genre_ids:
        return list(CATALOG)
    hit = [a for a in CATALOG if a.genres and set(a.genres) & set(genre_ids)]
    return hit + [a for a in CATALOG if not a.genres]


def speech_for(genre_ids: list[str]) -> list[SpeechKit]:
    return [s for s in SPEECH if _fits(s.genres, genre_ids)]


def wound_text(w: Wound) -> str:
    return f"{w.name}. 그 뒤로 '{w.belief}'라고 믿는다. {w.shows}."


def speech_text(s: SpeechKit) -> str:
    return f"{s.name}. {s.rule} 예: \"{s.sample}\""


def twist_line(twist: str) -> str:
    return f"비틀기: {twist}"


def fill(c: Character, a: Optional[Archetype] = None, wound: Optional[Wound] = None,
         speech: Optional[SpeechKit] = None, twist: str = "") -> list[str]:
    """빈 칸에만 예시를 넣는다. 상처 · 말투 부품을 고르면 원형의 예시 대신 그것을 쓴다.
    비틀기는 작가가 고른 것이라 아크 칸이 차 있어도 끝에 한 줄로 붙인다. 비틀기 줄은 하나만 두고, 다른 비틀기를 고르면 바꾼다.
    채운 칸 이름을 돌려준다."""
    filled: list[str] = []

    def put(field: str, value: str) -> None:
        if value and not str(getattr(c, field) or "").strip():
            setattr(c, field, value)
            filled.append(field)

    if a is not None:
        put("role", a.role)
        put("gender", a.gender)
        put("personality", a.personality)
        put("goal", a.goal)
    put("wound", wound_text(wound) if wound else a.wound if a else "")
    put("speech_style", speech_text(speech) if speech else a.speech if a else "")
    if a is not None:
        if a.secret and not c.secrets:
            c.secrets = [a.secret]
            filled.append("secrets")
        arc = a.arc
        if wound and not c.arc.strip():
            arc = f"{arc} (회복: {wound.heal})" if arc else f"회복: {wound.heal}"
        put("arc", arc)
    elif wound:
        put("arc", f"회복: {wound.heal}")
    if twist.strip():
        line = twist_line(twist.strip())
        if line not in c.arc.splitlines():
            # 비틀기는 인물마다 하나: 전에 고른 비틀기 줄은 새 것으로 바꾼다
            rest = "\n".join(x for x in c.arc.splitlines() if not x.startswith(twist_line(""))).rstrip()
            c.arc = f"{rest}\n{line}" if rest else line
            if "arc" not in filled:
                filled.append("arc")
    return filled


def pick_of(p: Project, character_id: str) -> Optional[ArchetypePick]:
    return next((x for x in p.cast_archetypes if x.character_id == character_id), None)


def remember(p: Project, character_id: str, archetype_id: str, twist: str = "") -> None:
    """인물이 고른 원형을 남긴다. 인물마다 하나. 비틀기를 새로 고르지 않았으면 전에 고른 것을 둔다."""
    old = pick_of(p, character_id)
    if old is None:
        p.cast_archetypes.append(ArchetypePick(character_id=character_id, archetype=archetype_id, twist=twist))
    else:
        if old.archetype != archetype_id:
            old.twist = ""
        old.archetype = archetype_id
        old.twist = twist or old.twist


def prune(p: Project) -> None:
    """없는 인물과 도감에 없는 원형의 기록을 지운다."""
    ids = {c.id for c in p.characters}
    p.cast_archetypes = [x for x in p.cast_archetypes if x.character_id in ids and x.archetype in BY_ID]


def apply(p: Project, character_id: str, archetype_id: str = "", wound_id: str = "", speech_id: str = "",
          twist: str = "") -> list[str]:
    """인물 하나에 도감을 적용한다 (명령줄 · 웹 공용). 빈 칸만 채우고 고른 원형을 기록한다."""
    c = next((x for x in p.characters if x.id == character_id), None)
    if c is None:
        raise KeyError(f"인물이 없어요: {character_id}")
    a = get(archetype_id) if archetype_id else None
    w = _part(WOUND_BY_ID, wound_id, "상처")
    s = _part(SPEECH_BY_ID, speech_id, "말투 틀")
    twist = twist.strip()
    filled = fill(c, a, w, s, twist)
    if a is not None:
        remember(p, c.id, a.id, twist)
    return filled


def _part(table: dict, key: str, label: str):
    if not key:
        return None
    if key not in table:
        raise KeyError(f"도감에 없는 {label}이에요: {key}")
    return table[key]


class Roll(BaseModel):
    """주사위 한 번: 원형 + 상처 + 말투 틀 + 비틀기 (+ 이름 후보)."""
    archetype: str
    wound: str
    speech: str
    twist: str = ""
    name: str = ""


def roll(genre_ids: list[str], n: int = 3, rng: Optional[random.Random] = None, archetype: str = "",
         p: Optional[Project] = None) -> list[Roll]:
    """작품 장르에 맞는 원형 · 상처 · 말투 · 비틀기를 무작위로 섞는다. archetype 을 주면 그 원형은 그대로 두고 나머지만 굴린다.
    p 를 주면 원형 성별에 맞는 이름 후보도 하나씩 붙인다 (naming)."""
    rng = rng or random.Random()
    pool = [get(archetype)] if archetype else match(genre_ids)
    kits = speech_for(genre_ids) or SPEECH
    if archetype:
        picks = [pool[0]] * n
    else:
        # 장르가 맞는 원형을 앞에서 고른다 (공통은 모자랄 때만)
        fit = [a for a in pool if a.genres] or pool
        picks = rng.sample(fit, min(n, len(fit)))
        rest = [a for a in pool if a not in picks]
        picks += rng.sample(rest, min(n - len(picks), len(rest)))
    wounds = rng.sample(WOUNDS, min(len(picks), len(WOUNDS)))
    out = []
    used_names: set[str] = set()
    for a, w in zip(picks, wounds):
        r = Roll(archetype=a.id, wound=w.id, speech=rng.choice(kits).id, twist=rng.choice(a.twists) if a.twists else "")
        if p is not None:
            r.name = _name(p, a, rng, used_names)
        out.append(r)
    return out


def _name(p: Project, a: Archetype, rng: random.Random, used: set[str]) -> str:
    from . import naming

    probe = Character(id="_dex", name="", role=a.role, gender=a.gender)
    for cand in naming.character_candidates(p, probe, n=6, rng=rng):
        if cand.name not in used:
            used.add(cand.name)
            return cand.name
    return ""


def new_character(p: Project, r: Roll) -> Character:
    """주사위 결과로 새 인물을 만들어 작품에 넣는다. id 는 겹치지 않게 자동으로 짓는다."""
    a = get(r.archetype)
    ids = {c.id for c in p.characters}
    cid = "hero" if "hero" not in ids and a.tier == "main" else ""
    k = len(p.characters) + 1
    while not cid or cid in ids:
        cid = f"char{k}"
        k += 1
    c = Character(id=cid, name=r.name, role="", tier=a.tier)
    p.characters.append(c)
    apply(p, cid, a.id, r.wound, r.speech, r.twist)
    return c


def card(a: Archetype) -> str:
    """명령줄에 보일 한 장."""
    lines = [f"{a.name} ({a.id})" + (f" · 별칭: {', '.join(a.aliases)}" if a.aliases else ""), f"  {a.summary}"]
    for label, v in (("원하는 것", a.goal), ("결핍", a.wound), ("성격", a.personality), ("말투", a.speech), ("숨기는 것", a.secret), ("아크", a.arc)):
        if v:
            lines.append(f"  {label}: {v}")
    for label, vs in (("흔들리는 상황", a.pressure), ("비틀어 보기", a.twists), ("피할 것", a.avoid), ("꼭 채울 것", a.must)):
        if vs:
            lines.append(f"  {label}:")
            lines += [f"    {i}. {v}" if label == "비틀어 보기" else f"    - {v}" for i, v in enumerate(vs, 1)]
    for v in a.views:
        back = f" / {v.toward} → 이 인물: {', '.join(v.back)}" if v.back else ""
        lines.append(f"  시작 관계: 이 인물 → {v.toward}: {', '.join(v.words)}{back}")
    return "\n".join(lines)
