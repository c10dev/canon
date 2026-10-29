"""지도 장소 종류: 모든 지도 생성기(마을 · 도시 · 현대 동네)가 같은 종류 표를 쓴다. 종류마다 시대(old · modern · both)가 있고,
지도 종류가 고른 시대의 종류만 보인다(kinds_for). 이름 · 설명의 단어로 종류를 고르고(classify), 옛 id 와 현대 id 를 대응표로 옮기고(to_era),
놓을 장소가 바라는 물(water_for)을 지도 만들기 물 칸의 기본값으로 준다. 계약은 docs/map/specs/08-modern-kinds.md '종류 표'. LLM 을 부르지 않는다.
"""
from __future__ import annotations

from typing import NamedTuple, Optional


class Kind(NamedTuple):
    id: str
    label: str
    era: str  # old | modern | both
    words: tuple[str, ...]  # 이름 · 설명에서 찾을 단어. 가장 긴 단어가 이긴다 (촌장 > 촌)


KINDS: list[Kind] = [
    # 옛 종류 (마을 · 도시). 차례와 단어는 옛 CATEGORIES 그대로
    Kind("center", "마을 가운데", "old", ("마을", "촌", "동네", "부락", "읍내", "마을회관")),
    Kind("market", "장터 · 광장", "old", ("장터", "시장", "광장", "장마당")),
    Kind("well", "우물", "old", ("우물", "샘터")),
    Kind("temple", "신전 · 사당", "old", ("신전", "사당", "교회", "성당", "예배당", "사원", "사찰", "신당", "수도원", "암자", "서낭당")),
    Kind("inn", "여관 · 주막", "old", ("여관", "주막", "객잔", "여인숙", "주점", "술집", "선술집", "객주", "숙소")),
    Kind("smith", "대장간 · 공방", "old", ("대장간", "공방", "마구간", "대장장이", "작업장")),
    Kind("mill", "방앗간", "old", ("방앗간", "물레방아", "풍차", "제분소")),
    Kind("manor", "저택 · 관아", "old", ("저택", "영주", "관아", "장원", "대감", "촌장", "이장", "지주", "별장")),
    Kind("home", "집 · 가게", "old", ("집", "가게", "상점", "빵집", "약방", "의원", "학당", "서당", "학교", "댁")),
    # 두 시대 모두
    Kind("shore", "나루 · 부두", "both", ("나루", "부두", "포구", "선착장", "항구", "등대", "해변", "바닷가", "어시장", "수산시장", "어판장", "방파제", "갯벌", "염전")),
    Kind("bridge", "다리", "both", ("다리", "징검다리")),
    Kind("river", "강가", "both", ("강", "강가", "개울", "냇가", "시냇가", "하천", "시내")),
    Kind("pond", "호수 · 연못", "both", ("호수", "연못", "늪", "저수지")),
    Kind("forest", "숲", "both", ("숲", "숲속", "숲길", "수풀")),
    Kind("field", "밭 · 농장", "old", ("밭", "논", "들판", "농장", "과수원", "목장")),
    Kind("far", "마을 밖", "both", ("왕국", "제국", "도시", "수도", "산맥", "대륙", "국경", "왕궁", "황궁", "성", "산", "고개", "바다")),
    # 현대 종류 (현대 동네). id 가 bldgs.MODERN 에 있으면 같은 id
    Kind("station", "역", "modern", ("역", "지하철역", "기차역", "전철역", "정류장", "버스정류장", "터미널", "버스터미널", "광장", "역전")),
    Kind("convenience", "편의점", "modern", ("편의점", "슈퍼", "슈퍼마켓", "구멍가게")),
    Kind("cafe", "카페", "modern", ("카페", "커피", "다방", "찻집", "빵집", "베이커리")),
    Kind("restaurant", "식당", "modern", ("식당", "음식점", "레스토랑", "밥집", "맛집", "분식", "분식집", "국밥집", "고깃집", "횟집", "중국집",
                                         "술집", "주점", "포차", "호프")),
    Kind("mart", "시장 · 마트", "modern", ("시장", "전통시장", "재래시장", "마트", "대형마트", "백화점", "상가", "쇼핑몰", "아울렛")),
    Kind("school", "학교", "modern", ("학교", "초등학교", "중학교", "고등학교", "대학", "대학교", "캠퍼스", "유치원", "교실")),
    Kind("academy", "학원", "modern", ("학원", "교습소", "독서실", "스터디카페")),
    Kind("hospital", "병원", "modern", ("병원", "의원", "한의원", "치과", "약국", "응급실", "보건소", "의료원")),
    Kind("police", "경찰서", "modern", ("경찰서", "파출소", "지구대", "경찰")),
    Kind("church", "교회 · 성당 · 절", "modern", ("교회", "성당", "예배당", "성전", "절", "사찰", "법당")),
    Kind("company", "회사", "modern", ("회사", "사무실", "오피스", "본사", "지사", "사옥", "빌딩", "은행")),
    Kind("factory", "공장 · 정비소", "modern", ("공장", "공업사", "정비소", "카센터", "창고", "물류센터", "작업장", "공방")),
    Kind("hotel", "호텔 · 모텔", "modern", ("호텔", "모텔", "여관", "여인숙", "게스트하우스", "펜션", "숙소")),
    Kind("apartment", "아파트", "modern", ("아파트", "단지", "오피스텔", "맨션", "주상복합")),
    Kind("villa", "빌라 · 원룸", "modern", ("빌라", "연립", "다세대", "원룸", "고시원", "하숙", "자취방", "옥탑방", "반지하")),
    Kind("house", "집 · 단독주택", "modern", ("집", "주택", "단독주택", "댁", "가게", "상점")),
    Kind("park", "공원", "modern", ("공원", "놀이터", "운동장", "산책로")),
]
ERAS = ("old", "modern")
MAP_ERA = {"village": "old", "city": "old", "realm": "old", "modern": "modern"}  # MapSpec.kind → 시대
FALLBACK = {"old": "home", "modern": "house"}  # 단어를 못 찾으면
# 옛 id → 현대 id, 현대 id → 옛 id. 두 시대 모두인 종류는 그대로라 적지 않는다. 대응이 없으면 ""
OLD_TO_MODERN = {"center": "station", "market": "mart", "well": "station", "temple": "church", "inn": "hotel", "smith": "factory",
                 "mill": "factory", "manor": "house", "home": "house", "field": ""}
MODERN_TO_OLD = {"station": "center", "convenience": "home", "cafe": "home", "restaurant": "inn", "mart": "market", "school": "home",
                 "academy": "home", "hospital": "home", "police": "manor", "church": "temple", "company": "home", "factory": "smith",
                 "hotel": "inn", "apartment": "home", "villa": "home", "house": "home", "park": "forest"}

_BY_ID = {k.id: k for k in KINDS}


def _era(era: str) -> str:
    if era not in ERAS:
        raise ValueError(f"모르는 시대예요: {era}")
    return era


def era_of(map_kind: str) -> str:
    """지도 종류(MapSpec.kind)의 시대. 모르는 지도 종류는 old."""
    return MAP_ERA.get(map_kind, "old")


def _in_era(k: Kind, era: str) -> bool:
    return k.era in (era, "both")


def _kinds(era: str) -> list[Kind]:
    """그 시대의 종류. 옛 시대는 KINDS 차례, 현대는 현대 종류 뒤에 두 시대 모두인 종류."""
    if era == "old":
        return [k for k in KINDS if _in_era(k, "old")]
    return [k for k in KINDS if k.era == era] + [k for k in KINDS if k.era == "both"]


def kinds_for(map_kind: str) -> list[Kind]:
    """그 지도에서 보이는 종류 (드롭다운 · 프롬프트 차례)."""
    return _kinds(era_of(map_kind))


def kind_ids(map_kind: str) -> list[str]:
    return [k.id for k in kinds_for(map_kind)]


def label(kind: str) -> str:
    """종류의 화면 이름. 모르는 id 는 그대로."""
    k = _BY_ID.get(kind)
    return k.label if k else kind


# 옛 시대 (id, 화면 이름, 단어) 목록. 옛 호출부(마을 · 도시 생성기, 화면 · 명령줄 종류 이름)가 쓴다
CATEGORIES: list[tuple[str, str, tuple[str, ...]]] = [(k.id, k.label, k.words) for k in _kinds("old")]
CATEGORY_IDS = [c[0] for c in CATEGORIES]


def classify(name: str, description: str = "", era: str = "old") -> tuple[str, str]:
    """장소 종류 (종류 id, 찾은 단어). 그 시대 종류(두 시대 모두 포함)에서만 찾는다.
    이름에서 먼저 찾고 없으면 설명에서. 같은 길이면 앞 차례가 이긴다. 못 찾으면 (FALLBACK[era], '')."""
    kinds = _kinds(_era(era))
    for text in (name, description):
        best: Optional[tuple[int, int, str, str]] = None
        for order, k in enumerate(kinds):
            for w in k.words:
                if w in text and (best is None or (len(w), -order) > (best[0], best[1])):
                    best = (len(w), -order, k.id, w)
        if best:
            return best[2], best[3]
    return FALLBACK[era], ""


def to_era(kind: str, era: str) -> str:
    """저장된 종류를 그 시대 id 로. 이미 그 시대(두 시대 모두 포함)면 그대로, 아니면 대응표. 대응이 없거나 모르는 id 면 ''."""
    k = _BY_ID.get(kind)
    if not k:
        return ""
    if _in_era(k, _era(era)):
        return kind
    return (OLD_TO_MODERN if era == "modern" else MODERN_TO_OLD).get(kind, "")


def default_put(kind: str) -> bool:
    return kind != "far"


RIVER_SHORE = ("나루", "선착장")  # 물가 종류 가운데 강에 어울리는 단어 (나머지는 바다)


def water_for(rows: list[dict]) -> str:
    """놓을 장소가 물을 바라면 그 물 (sea | river | lake), 아니면 none. 지도 만들기 물 칸의 기본값.
    rows: [{kind, word, put}]. 여러 물을 바라면 많이 바라는 쪽, 같으면 바다 > 강 > 호수.
    물 종류(shore · bridge · river · pond)는 두 시대 모두라서 현대 행도 그대로 센다."""
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
