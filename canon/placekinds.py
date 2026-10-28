"""지도 장소 종류: 모든 지도 생성기(마을 · 도시 · 현대 동네)가 같은 종류 id 를 쓴다. 이름 · 설명의 단어로 종류를 고르고(classify),
놓을 장소가 바라는 물(water_for)을 지도 만들기 물 칸의 기본값으로 준다. LLM 을 부르지 않는다.
"""
from __future__ import annotations

from typing import Optional

# (종류 id, 화면 이름, 이름 · 설명에서 찾을 단어). 가장 긴 단어가 이긴다 (촌장 > 촌)
CATEGORIES: list[tuple[str, str, tuple[str, ...]]] = [
    ("center", "마을 가운데", ("마을", "촌", "동네", "부락", "읍내", "마을회관")),
    ("market", "장터 · 광장", ("장터", "시장", "광장", "장마당")),
    ("well", "우물", ("우물", "샘터")),
    ("temple", "신전 · 사당", ("신전", "사당", "교회", "성당", "예배당", "사원", "사찰", "신당", "수도원", "암자", "서낭당")),
    ("inn", "여관 · 주막", ("여관", "주막", "객잔", "여인숙", "주점", "술집", "선술집", "객주", "숙소")),
    ("smith", "대장간 · 공방", ("대장간", "공방", "마구간", "대장장이", "작업장")),
    ("mill", "방앗간", ("방앗간", "물레방아", "풍차", "제분소")),
    ("manor", "저택 · 관아", ("저택", "영주", "관아", "장원", "대감", "촌장", "이장", "지주", "별장")),
    ("home", "집 · 가게", ("집", "가게", "상점", "빵집", "약방", "의원", "학당", "서당", "학교", "댁")),
    ("shore", "나루 · 부두", ("나루", "부두", "포구", "선착장", "항구", "등대", "해변", "바닷가", "어시장", "수산시장", "어판장", "방파제", "갯벌", "염전")),
    ("bridge", "다리", ("다리", "징검다리")),
    ("river", "강가", ("강", "강가", "개울", "냇가", "시냇가", "하천", "시내")),
    ("pond", "호수 · 연못", ("호수", "연못", "늪", "저수지")),
    ("forest", "숲", ("숲", "숲속", "숲길", "수풀")),
    ("field", "밭 · 농장", ("밭", "논", "들판", "농장", "과수원", "목장")),
    ("far", "마을 밖", ("왕국", "제국", "도시", "수도", "산맥", "대륙", "국경", "왕궁", "황궁", "성", "산", "고개", "바다")),
]
CATEGORY_IDS = [c[0] for c in CATEGORIES]


def classify(name: str, description: str = "") -> tuple[str, str]:
    """장소 종류 (종류 id, 찾은 단어). 이름에서 먼저 찾고 없으면 설명에서. 못 찾으면 ('home', '')."""
    for text in (name, description):
        best: Optional[tuple[int, int, str, str]] = None
        for order, (cid, _, words) in enumerate(CATEGORIES):
            for w in words:
                if w in text and (best is None or (len(w), -order) > (best[0], best[1])):
                    best = (len(w), -order, cid, w)
        if best:
            return best[2], best[3]
    return "home", ""


def default_put(kind: str) -> bool:
    return kind != "far"


RIVER_SHORE = ("나루", "선착장")  # 물가 종류 가운데 강에 어울리는 단어 (나머지는 바다)


def water_for(rows: list[dict]) -> str:
    """놓을 장소가 물을 바라면 그 물 (sea | river | lake), 아니면 none. 지도 만들기 물 칸의 기본값.
    rows: [{kind, word, put}]. 여러 물을 바라면 많이 바라는 쪽, 같으면 바다 > 강 > 호수."""
    votes = {"sea": 0, "river": 0, "lake": 0}
    for r in rows:
        if not r.get("put"):
            continue
        if r["kind"] == "shore":
            votes["river" if r.get("word") in RIVER_SHORE else "sea"] += 1
        elif r["kind"] in ("bridge", "river"):
            votes["river"] += 1
        elif r["kind"] == "pond":
            votes["lake"] += 1
    best = max(votes, key=lambda k: (votes[k], -list(votes).index(k)))
    return best if votes[best] else "none"
