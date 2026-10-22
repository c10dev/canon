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
    assert "## 미스터리 · 추리" in ctx and "## 오컬트" in ctx and "성인 독자 대상" in ctx
    assert '"genre": "미스터리 · 추리 · 오컬트"' in ctx and "mystery" not in ctx
    assert "전연령" in prompts.setup_prompt(Project(meta=Meta(title="t")))
