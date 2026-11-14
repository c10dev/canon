"""장르 목록과 프롬프트 장르 안내."""
from canon import genres, prompts
from canon.schema import Meta, Project


def test_catalog_ids_unique():
    ids = [g.id for g in genres.CATALOG]
    assert len(ids) == len(set(ids))
    assert {g.kind for g in genres.CATALOG} == {"장르", "요소"}


def test_parse_names_ids_and_custom():
    assert genres.parse("로맨스 판타지, regression / 오컬트") == ["romance_fantasy", "regression", "오컬트"]
    assert genres.parse("") == []


def test_old_meta_keeps_text_genre():
    m = Meta.model_validate({"title": "등대", "genre": "미스터리 드라마"})
    assert m.genres == ["미스터리 드라마"] and m.adult is False
    assert genres.label(m) == "미스터리 드라마"


def test_guide_in_prompts():
    p = Project(meta=Meta(title="t", genres=["mystery", "오컬트"], adult=True))
    ctx = prompts.static_context(p)
    assert "## 미스터리 · 추리" in ctx and "## 오컬트" in ctx
    assert '"genre": "미스터리 · 추리 · 오컬트"' in ctx and "mystery" not in ctx


def test_no_rating_instruction_in_prompts():
    """수위는 프롬프트에 지시로 넣지 않는다. 성인 · 전연령 작품의 요청이 같다 (화면과 프로그램 규칙만 다르다)."""
    adult, kids = (Project(meta=Meta(title="t", genres=["mystery"], adult=a)) for a in (True, False))
    assert prompts.static_context(adult) == prompts.static_context(kids)
    for fn in (prompts.writer_system, prompts.reviser_system, prompts.paragraph_system):  # 시스템 프롬프트도 같다
        assert fn(adult) == fn(kids)
    for text in (prompts.static_context(kids), prompts.setup_prompt(kids)):
        assert "수위" not in text and "전연령" not in text and "암시로" not in text and "rating" not in text


def test_webnovel_elements():
    """웹소설 일감 2: 요소 장르 하렘 · 시스템. 고른 작품의 장르 안내에만 들어간다."""
    assert genres.BY_ID["harem"].kind == genres.BY_ID["system"].kind == "요소"
    assert genres.parse("하렘, 시스템") == ["harem", "system"]
    picked = genres.guide(Meta(title="t", genres=["light_novel", "harem", "system"]))
    assert "## 하렘 (요소)" in picked and "## 시스템 (요소)" in picked
    plain = genres.guide(Meta(title="t", genres=["light_novel"]))
    assert "하렘 (요소)" not in plain and "시스템 (요소)" not in plain
    for gid in ("harem", "system"):
        assert len(genres.opening_beats(Meta(title="t", genres=[gid]), 3)) == 1


def test_no_per_episode_lines_in_webnovel_genres():
    """라이트노벨의 '캐릭터마다 말버릇' · '화마다 웃음 포인트' 같은 매 화 지시를 뺐고, 새 요소에도 두지 않는다."""
    text = genres.guide(Meta(title="t", genres=["light_novel", "harem", "system"]))
    assert "말버릇" not in text and "웃음 포인트" not in text and "화마다" not in text
    assert "갈등 없이" not in genres.guide(Meta(title="t", genres=["modern_fantasy"]))


def test_untouched_genre_guides_stay_the_same():
    """웹소설 일감 2 는 라이트노벨 · 현대 판타지 안내만 바꾼다. 나머지 장르 안내는 글자까지 그대로다."""
    import hashlib
    ids = ["romance", "romance_fantasy", "fantasy", "martial_arts", "mystery", "thriller", "horror", "sf", "drama", "bl", "gl",
           "alt_history", "healing", "sports", "regression", "possession", "revenge", "contract", "academy", "office"]
    text = "\n\n".join(genres.guide(Meta(title="t", genres=[i])) for i in ids)
    assert hashlib.sha256(text.encode()).hexdigest() == "7689f3e434a6c65ea453111b6f96261ae900f9ff0cda6d82f0d4001412aeef6b"
