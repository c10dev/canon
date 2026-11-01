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
    for text in (prompts.static_context(kids), prompts.setup_prompt(kids)):
        assert "수위" not in text and "전연령" not in text and "암시로" not in text and "rating" not in text
