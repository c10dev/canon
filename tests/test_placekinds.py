"""장소 종류 표 테스트 (LLM 없음): 시대별 목록, 현대 단어 찾기, 옛 id 와 현대 id 대응.
계약은 docs/map/specs/08-modern-kinds.md '종류 표'. 실행: python -m pytest tests"""
import pytest

from canon.maps import kinds as pk

OLD = ["center", "market", "well", "temple", "inn", "smith", "mill", "manor", "home", "shore", "bridge", "river", "pond",
       "forest", "field", "far"]
BOTH = ["shore", "bridge", "river", "pond", "forest", "far"]
MODERN = ["station", "convenience", "cafe", "restaurant", "mart", "school", "academy", "hospital", "police", "church", "company",
          "factory", "hotel", "apartment", "villa", "house", "park"]


def test_old_view_is_unchanged():
    assert pk.CATEGORY_IDS == OLD and [c[0] for c in pk.CATEGORIES] == OLD
    assert all(len(c) == 3 for c in pk.CATEGORIES)
    assert pk.kind_ids("village") == pk.kind_ids("city") == pk.kind_ids("realm") == OLD
    assert [(k.id, k.label, k.words) for k in pk.kinds_for("village")] == pk.CATEGORIES


def test_kinds_by_era():
    assert len({k.id for k in pk.KINDS}) == len(pk.KINDS)
    assert pk.kind_ids("modern") == MODERN + BOTH  # 현대 종류 뒤에 두 시대 모두인 종류
    assert {k.id for k in pk.KINDS if k.era == "both"} == set(BOTH)
    assert not set(MODERN) & set(OLD)
    assert pk.era_of("modern") == "modern" and pk.era_of("village") == pk.era_of("city") == pk.era_of("모름") == "old"
    assert pk.label("station") == "역" and pk.label("inn") == "여관 · 주막" and pk.label("모름") == "모름"


def test_classify_modern_words():
    cases = {"편의점": "convenience", "강남역": "station", "서울역": "station", "스타벅스 카페": "cafe", "학교 앞 분식집": "restaurant",
             "전통시장": "mart", "푸른 고등학교": "school", "수학 학원": "academy", "한빛 병원": "hospital", "중앙 파출소": "police",
             "성당": "church", "본사 사무실": "company", "정비소": "factory", "모텔": "hotel", "래미안 아파트": "apartment",
             "반지하 원룸": "villa", "우리 집": "house", "한강공원": "park", "수산시장": "shore", "한강": "river", "돌다리": "bridge",
             "부산": "far", "": "house"}
    assert {n: pk.classify(n, era="modern")[0] for n in cases} == cases
    assert pk.classify("검은 문", "동네 끝 편의점", era="modern") == ("convenience", "편의점")  # 이름에 없으면 설명에서
    # 한 글자 '역' 은 다른 단어 안에도 있다: 이름이 먼저라 이름의 단어가 이기고, 설명만 보면 '구역' 도 역이 된다
    assert pk.classify("작은 카페", "주택가 구역의 가게", era="modern")[0] == "cafe"
    assert pk.classify("검은 문", "옛 구역", era="modern")[0] == "station"


def test_classify_era_keeps_old_words_apart():
    # 옛 지도는 지금처럼 '학교' 를 집, '교회' 를 신전으로 본다. 현대 단어는 옛 지도에서 찾지 않는다
    assert pk.classify("학교") == ("home", "학교") and pk.classify("학교", era="old") == ("home", "학교")
    assert pk.classify("학교", era="modern") == ("school", "학교")
    assert pk.classify("교회")[0] == "temple" and pk.classify("교회", era="modern")[0] == "church"
    assert pk.classify("편의점") == ("home", "")
    assert pk.classify("대장간", era="modern") == ("house", "")
    with pytest.raises(ValueError):
        pk.classify("역", era="modern2")


def test_to_era_maps_ids():
    assert {k: pk.to_era(k, "modern") for k in OLD} == {
        "center": "station", "market": "mart", "well": "station", "temple": "church", "inn": "hotel", "smith": "factory",
        "mill": "factory", "manor": "house", "home": "house", "field": "", **{b: b for b in BOTH}}
    assert all(pk.to_era(m, "modern") == m for m in MODERN + BOTH)
    assert all(pk.to_era(k, "old") == k for k in OLD)
    old_of = {m: pk.to_era(m, "old") for m in MODERN}
    assert set(old_of.values()) <= set(OLD) and old_of["church"] == "temple" and old_of["park"] == "forest"
    assert pk.to_era("모름", "modern") == "" and pk.to_era("", "old") == ""
    # 대응표는 그 시대 id 로만 간다
    assert set(pk.OLD_TO_MODERN.values()) - {""} <= set(MODERN) and set(pk.OLD_TO_MODERN) == set(OLD) - set(BOTH)
    assert set(pk.MODERN_TO_OLD) == set(MODERN)


def test_put_and_water_for_modern_rows():
    assert all(pk.default_put(k) for k in MODERN) and not pk.default_put("far")
    rows = [{"kind": pk.classify(n, era="modern")[0], "word": pk.classify(n, era="modern")[1], "put": True}
            for n in ("강남역", "한강 둔치", "편의점")]
    assert pk.water_for(rows) == "river"
