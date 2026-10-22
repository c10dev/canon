"""장르 목록과 장르별 안내.

설정 화면에서 고르는 목록이자, 프롬프트에 넣는 장르 안내다. 작품에는 고른 장르의 id
(목록에 없으면 사용자가 적은 이름 그대로)를 Meta.genres 에 저장한다.

kind 는 "장르"(큰 갈래)와 "요소"(회귀, 계약 관계 같은 소재)로 나눈다.
dynamics 는 나중에 장르별 관계 역학 프리셋(ModelParams 일부 값 덮어쓰기)을 붙일 자리다.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from .schema import Meta


class Genre(BaseModel):
    id: str
    name: str
    kind: Literal["장르", "요소"] = "장르"
    summary: str
    reader_expects: list[str] = Field(default_factory=list, description="독자가 기대하는 것")
    conventions: list[str] = Field(default_factory=list, description="지키면 좋은 관습")
    tropes: list[str] = Field(default_factory=list, description="자주 쓰는 클리셰. 쓰되 비틀 것")
    pacing: str = ""
    avoid: list[str] = Field(default_factory=list, description="독자가 싫어하는 것")
    dynamics: dict[str, float] = Field(default_factory=dict, description="관계 역학 계수 덮어쓰기 (예정)")


CATALOG: list[Genre] = [
    Genre(
        id="romance", name="로맨스",
        summary="두 사람이 서로에게 끌리고, 장애물을 넘어 관계가 확정되는 이야기.",
        reader_expects=["두 주인공 사이의 설렘과 감정선", "관계가 한 단계씩 진전되는 장면", "확실한 해피엔딩 또는 납득되는 결말"],
        conventions=["남녀(또는 두) 주인공의 시점 비중이 크다", "감정 변화에는 계기가 되는 사건이 있다", "오해는 길게 끌지 않는다"],
        tropes=["계약 연애", "앙숙에서 연인", "재회", "삼각관계", "신분 차이"],
        pacing="초반 2~3화 안에 두 주인공이 만나고, 중반에 관계가 깊어지다 전 구간에서 가장 큰 위기, 결에서 확정.",
        avoid=["이유 없는 집착을 사랑으로 포장", "주인공이 수동적으로만 끌려다님", "오해가 한 번의 대화로 풀릴 수 있는데 계속됨"],
    ),
    Genre(
        id="romance_fantasy", name="로맨스 판타지",
        summary="서양풍 귀족 사회나 마법 세계에서 펼쳐지는 로맨스. 흔히 '로판'.",
        reader_expects=["주인공이 처지를 뒤집는 쾌감", "매력적인 상대역과의 감정선", "화려한 배경 묘사(무도회, 궁, 영지)"],
        conventions=["작위, 가문, 혼약 같은 신분 질서가 갈등의 축", "주인공은 정보나 능력으로 판을 읽는다", "악역은 분명하게, 응징은 확실하게"],
        tropes=["악녀 빙의", "회귀한 영애", "계약 결혼", "북부 대공", "파혼"],
        pacing="1화에 처지(빙의, 회귀, 파혼 등)를 바로 던지고, 3화 안에 상대역 등장. 화마다 작은 반전이나 응징.",
        avoid=["세계관 설명만 길게 이어지는 초반", "주인공의 판단이 설정 없이 늘 맞아떨어짐"],
    ),
    Genre(
        id="modern_fantasy", name="현대 판타지",
        summary="현대 한국을 배경으로 능력, 시스템, 던전 같은 초월적 요소가 들어오는 이야기. 흔히 '현판'.",
        reader_expects=["주인공이 성장하고 인정받는 쾌감", "능력의 규칙이 분명한 성장", "현실 사회와 능력이 맞물리는 재미"],
        conventions=["능력이나 시스템의 규칙을 초반에 분명히 정한다", "보상과 대가가 눈에 보이게 한다", "주변 인물의 반응으로 주인공의 위상을 보여 준다"],
        tropes=["각성", "헌터와 게이트", "상태창", "재벌 회귀", "전문직 성공담"],
        pacing="1화 끝에 각성이나 전환점. 화마다 작은 목표 달성, 3~5화 단위로 큰 성과.",
        avoid=["능력 규칙이 편할 때만 바뀜", "갈등 없이 이기기만 하는 전개"],
    ),
    Genre(
        id="fantasy", name="판타지",
        summary="마법, 이종족, 왕국 같은 이세계를 무대로 한 모험과 성장 이야기.",
        reader_expects=["독창적인 세계와 규칙", "모험과 전투", "동료와의 관계"],
        conventions=["마법이나 힘의 대가를 정한다", "세계 설명은 사건 속에서 조금씩", "지도와 세력 구도를 일관되게 유지"],
        tropes=["선택받은 자", "용사 파티", "마왕", "고대 유물", "몰락한 왕족"],
        pacing="기에서 세계와 목표 제시, 승에서 여정과 동료, 전에서 배신이나 큰 패배, 결에서 대결.",
        avoid=["설정 나열로 시작하는 1화", "힘의 한계가 없는 주인공"],
    ),
    Genre(
        id="martial_arts", name="무협",
        summary="강호와 문파, 무공을 중심으로 한 복수, 성장, 의리 이야기.",
        reader_expects=["무공 수련과 경지 상승", "문파와 세력 사이의 대립", "의리와 은원"],
        conventions=["경지 체계를 일관되게 유지", "말투에 무협 특유의 하오체·하게체를 쓰기도 한다", "은혜와 원한은 반드시 갚는다"],
        tropes=["멸문지화 후 복수", "기연", "정파와 사파", "천하제일", "회귀한 고수"],
        pacing="초반에 원한이나 동기를 세우고, 수련과 실전을 번갈아. 대결 장면은 한 화를 통째로 쓰기도 한다.",
        avoid=["경지 체계가 들쭉날쭉", "무공 묘사가 같은 표현의 반복"],
    ),
    Genre(
        id="mystery", name="미스터리 · 추리",
        summary="수수께끼나 사건의 진상을 단서로 풀어 가는 이야기.",
        reader_expects=["공정하게 제시된 단서", "그럴듯한 오답과 반전", "납득되는 진상"],
        conventions=["진상에 필요한 단서는 미리 독자에게 보여 준다", "용의자마다 동기와 기회를 준다", "탐정 역의 추론 과정을 보여 준다"],
        tropes=["밀실", "폐쇄된 마을", "과거의 사건", "믿을 수 없는 화자", "마지막 반전"],
        pacing="1화에 사건이나 의문을 던지고, 화마다 단서 하나와 의문 하나. 전 구간에서 가설이 무너지고 결에서 진상.",
        avoid=["독자가 볼 수 없던 단서로 해결", "우연에 기대는 해결"],
    ),
    Genre(
        id="thriller", name="스릴러",
        summary="위협과 시간 압박 속에서 살아남거나 막아야 하는 긴장의 이야기.",
        reader_expects=["계속 높아지는 긴장", "화 끝마다 다음이 궁금한 장면", "주인공이 궁지에 몰리는 상황"],
        conventions=["위협의 실체와 시한을 분명히 한다", "주인공의 선택에 대가가 따른다", "정보를 조금씩 흘린다"],
        tropes=["추격", "내부의 배신자", "협박", "카운트다운", "이중생활"],
        pacing="짧은 장면, 빠른 전환. 화마다 끝에 위기나 반전(클리프행어).",
        avoid=["긴장이 풀린 채 설명만 이어지는 화", "적이 이유 없이 어리석어짐"],
    ),
    Genre(
        id="horror", name="호러",
        summary="공포의 대상이 서서히 드러나며 인물을 몰아붙이는 이야기.",
        reader_expects=["불안이 쌓이는 분위기", "규칙이 있는 공포", "인물이 대가를 치르는 순간"],
        conventions=["공포의 실체는 늦게, 조금씩 보여 준다", "일상의 디테일이 어긋나는 데서 시작", "공포에도 규칙을 정해 일관되게"],
        tropes=["저주받은 장소", "괴담 규칙", "빙의", "고립", "반복되는 꿈"],
        pacing="기에서 일상의 균열, 승에서 고조, 전에서 실체, 결은 해소 또는 여운.",
        avoid=["설명으로 공포를 해소", "깜짝 놀래키기에만 기대기"],
    ),
    Genre(
        id="sf", name="SF",
        summary="과학 기술이나 가정된 미래가 사회와 인간을 바꾸는 이야기.",
        reader_expects=["흥미로운 가정(만약 ~라면)", "기술이 만든 새로운 갈등", "설정의 논리적 일관성"],
        conventions=["핵심 가정은 하나를 깊게", "기술의 한계와 부작용을 보여 준다", "용어는 맥락으로 이해되게"],
        tropes=["인공지능", "시간 여행", "우주 탐사", "디스토피아", "기억 조작"],
        pacing="가정을 1~2화 안에 제시하고, 그 가정이 인물의 선택을 압박하도록.",
        avoid=["기술 설명 덤프", "가정이 이야기 중간에 슬그머니 바뀜"],
    ),
    Genre(
        id="drama", name="현대 드라마",
        summary="현대 한국의 일상, 가족, 직장 속 인물들의 갈등과 화해 이야기.",
        reader_expects=["공감되는 인물과 상황", "감정이 쌓였다가 터지는 장면", "현실적인 디테일"],
        conventions=["갈등은 인물의 욕망과 결핍에서 나온다", "대사로 감정을 직접 설명하지 않는다", "작은 사건으로 관계를 보여 준다"],
        tropes=["가족의 비밀", "출생의 비밀", "직장 내 갈등", "귀향", "오래된 친구"],
        pacing="잔잔하게 쌓되, 화마다 감정의 작은 변화. 전 구간에서 숨겨 온 것이 터진다.",
        avoid=["막장 전개의 남발", "모든 갈등을 대화 한 번으로 해결"],
    ),
    Genre(
        id="bl", name="BL",
        summary="남성 인물 사이의 연애를 중심으로 한 로맨스.",
        reader_expects=["두 주인공의 케미와 감정선", "관계의 긴장과 진전", "인물의 매력"],
        conventions=["공수 등 독자층 용어를 쓰더라도 인물성을 먼저", "감정 변화의 계기를 분명히", "로맨스 관습을 따른다"],
        tropes=["앙숙에서 연인", "재회", "계약 관계", "오메가버스", "캠퍼스"],
        pacing="로맨스와 같다. 초반 만남, 중반 진전, 전에서 위기, 결에서 확정.",
        avoid=["동의 없는 관계를 미화", "한 인물이 소품처럼 쓰임"],
    ),
    Genre(
        id="gl", name="GL",
        summary="여성 인물 사이의 연애를 중심으로 한 로맨스.",
        reader_expects=["두 주인공의 케미와 감정선", "관계의 긴장과 진전", "섬세한 감정 묘사"],
        conventions=["로맨스 관습을 따른다", "감정 변화의 계기를 분명히"],
        tropes=["앙숙에서 연인", "재회", "학원", "오피스", "계약 관계"],
        pacing="로맨스와 같다. 초반 만남, 중반 진전, 전에서 위기, 결에서 확정.",
        avoid=["관계를 우정으로 흐리기만 함", "한 인물이 소품처럼 쓰임"],
    ),
    Genre(
        id="alt_history", name="대체역사",
        summary="실제 역사의 한 지점이 달라졌을 때를 그리는 이야기.",
        reader_expects=["고증과 그럴듯함", "주인공의 지식으로 역사를 바꾸는 쾌감", "실존 인물과의 만남"],
        conventions=["바뀐 지점 전까지는 실제 역사를 따른다", "변화의 파급을 단계적으로 보여 준다"],
        tropes=["현대인 회귀", "왕으로 빙의", "기술 전파", "전쟁 회피"],
        pacing="1화에 시대와 처지 확정, 이후 작은 변화가 큰 변화로 이어지게.",
        avoid=["실존 인물을 지나치게 희화화", "현대 지식이 아무 저항 없이 통함"],
    ),
    Genre(
        id="light_novel", name="라이트노벨",
        summary="캐릭터 중심의 가볍고 빠른 전개, 대사 비중이 큰 이야기.",
        reader_expects=["개성 강한 캐릭터", "빠른 템포와 유머", "캐릭터 사이의 티키타카"],
        conventions=["캐릭터마다 말버릇이나 특징을 분명히", "대사와 짧은 서술 위주", "1인칭 서술이 흔하다"],
        tropes=["이세계 전생", "학원", "동거", "츤데레", "하렘"],
        pacing="장면 단위로 빠르게. 화마다 웃음 포인트와 작은 사건.",
        avoid=["캐릭터 말투가 서로 구분되지 않음", "설명 대사"],
    ),
    Genre(
        id="healing", name="일상 · 힐링",
        summary="큰 악역 없이 인물의 회복과 일상의 온기를 그리는 이야기.",
        reader_expects=["편안한 분위기", "작은 성취와 위로", "따뜻한 인간관계"],
        conventions=["갈등은 작고 해결 가능하게", "감각적인 일상 묘사(음식, 계절, 공간)"],
        tropes=["시골 귀향", "가게 운영", "동물", "요리", "이웃"],
        pacing="에피소드형. 화마다 하나의 작은 이야기, 전체로는 주인공의 회복.",
        avoid=["갑작스러운 비극", "긴장감 없는 반복"],
    ),
    Genre(
        id="sports", name="스포츠",
        summary="경기와 훈련을 통해 성장하고 승리를 향해 가는 이야기.",
        reader_expects=["경기 장면의 긴장", "팀과 라이벌", "노력과 성장"],
        conventions=["경기 규칙을 독자가 따라올 수 있게", "결과보다 과정의 선택을 보여 준다"],
        tropes=["약체 팀", "천재 라이벌", "부상과 복귀", "회귀한 선수"],
        pacing="훈련과 경기를 번갈아. 큰 경기는 여러 화에 걸쳐.",
        avoid=["경기 결과가 늘 주인공 편", "규칙 설명이 길게 이어짐"],
    ),
    # ---- 요소 ----
    Genre(
        id="regression", name="회귀", kind="요소",
        summary="주인공이 과거로 돌아가 미래 지식으로 다시 사는 소재.",
        reader_expects=["미래 지식을 활용하는 쾌감", "전생의 후회를 바로잡기"],
        conventions=["회귀 전에 무엇이 일어났는지 일관되게 기록", "주인공이 바꾼 만큼 미래도 달라진다"],
        tropes=["복수", "가족 지키기", "망한 회사 살리기"],
        avoid=["바뀐 미래가 편할 때만 원래대로 흘러감"],
    ),
    Genre(
        id="possession", name="빙의", kind="요소",
        summary="주인공이 소설이나 게임 속 인물, 다른 사람의 몸에 들어가는 소재.",
        reader_expects=["원작 지식으로 운명을 피하는 재미", "원래 인물과 다른 행동이 주는 반응"],
        conventions=["원작 줄거리와 현재 차이를 분명히", "원래 인물을 아는 사람들의 의심"],
        tropes=["악녀 빙의", "엑스트라 빙의", "게임 속 빙의"],
        avoid=["원작 설정이 편할 때만 바뀜"],
    ),
    Genre(
        id="revenge", name="복수", kind="요소",
        summary="부당하게 빼앗긴 것을 되찾고 가해자를 응징하는 소재.",
        reader_expects=["확실한 응징(사이다)", "치밀한 계획"],
        conventions=["가해의 무게를 초반에 충분히 보여 준다", "응징은 단계적으로, 마지막이 가장 크게"],
        tropes=["배신당한 후 회귀", "신분을 숨긴 복귀"],
        avoid=["응징이 가해보다 지나치게 잔혹해 공감을 잃음"],
    ),
    Genre(
        id="contract", name="계약 관계", kind="요소",
        summary="계약 결혼, 계약 연애처럼 조건으로 시작한 관계가 진짜가 되는 소재.",
        reader_expects=["조건과 감정 사이의 줄다리기", "계약이 끝날 때의 긴장"],
        conventions=["계약 조건과 기한을 분명히", "조건을 어기는 순간이 감정의 전환점"],
        tropes=["계약 결혼", "가짜 연인", "1년 기한"],
        avoid=["계약 설정이 중반 이후 잊힘"],
    ),
    Genre(
        id="academy", name="학원 · 아카데미", kind="요소",
        summary="학교나 아카데미를 무대로 한 성장, 경쟁, 관계 소재.",
        reader_expects=["시험과 경쟁", "동기와 라이벌", "교사와 학생 관계"],
        conventions=["학기, 시험, 행사 같은 일정이 전개의 뼈대", "서열과 평판이 갈등의 축"],
        tropes=["낙제생의 역전", "신분을 숨긴 입학", "기숙사"],
        avoid=["학교 설정이 배경으로만 쓰임"],
    ),
    Genre(
        id="office", name="오피스", kind="요소",
        summary="회사와 직장을 무대로 한 일, 경쟁, 관계 소재.",
        reader_expects=["직업의 디테일", "일로 증명하는 성장", "직장 내 관계"],
        conventions=["직급과 권력 관계를 일관되게", "업무 성과가 갈등을 푸는 열쇠"],
        tropes=["상사와의 로맨스", "신입의 성장", "사내 정치"],
        avoid=["업무 묘사가 비현실적으로 쉬움"],
    ),
]

BY_ID = {g.id: g for g in CATALOG}


def names(ids: list[str]) -> list[str]:
    """id 를 이름으로. 목록에 없는 값은 사용자가 직접 적은 장르로 보고 그대로 둔다."""
    return [BY_ID[i].name if i in BY_ID else i for i in ids]


def parse(text: str) -> list[str]:
    """'로맨스, 회귀' 같은 입력을 id 목록으로. 이름이나 id 가 맞지 않으면 적은 그대로 둔다."""
    by_name = {g.name: g.id for g in CATALOG}
    out = []
    for part in re.split(r"[,/·]", text):
        part = part.strip()
        if part:
            out.append(part if part in BY_ID else by_name.get(part, part))
    return list(dict.fromkeys(out))


def label(meta: Meta) -> str:
    """화면과 프롬프트에 쓸 한 줄 장르 이름."""
    return " · ".join(names(meta.genres)) or meta.genre


def guide(meta: Meta) -> str:
    """프롬프트에 넣을 장르 안내와 수위. 고른 장르가 없으면 수위만 적는다."""
    blocks = []
    for gid in meta.genres:
        g = BY_ID.get(gid)
        if g is None:
            blocks.append(f"## {gid}\n작가가 직접 적은 장르입니다. 이 장르의 일반적인 관습을 따르세요.")
            continue
        lines = [f"## {g.name} ({g.kind})", g.summary]
        if g.reader_expects:
            lines.append("독자가 기대하는 것: " + ", ".join(g.reader_expects))
        if g.conventions:
            lines.append("관습: " + " / ".join(g.conventions))
        if g.tropes:
            lines.append("자주 쓰는 소재 (쓰되 뻔하지 않게 비틀 것): " + ", ".join(g.tropes))
        if g.pacing:
            lines.append("전개 속도: " + g.pacing)
        if g.avoid:
            lines.append("피할 것: " + " / ".join(g.avoid))
        blocks.append("\n".join(lines))
    rating = (
        "성인 독자 대상 작품입니다. 성숙한 주제와 수위 있는 연애, 폭력 묘사를 이야기에 필요한 만큼 다룰 수 있습니다."
        if meta.adult else
        "전연령 작품입니다. 노골적인 성적 묘사와 과도하게 잔혹한 묘사는 쓰지 않고 암시로 처리합니다."
    )
    return "\n\n".join(blocks + [f"## 수위\n{rating}"])
