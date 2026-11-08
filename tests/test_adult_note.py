"""성인 작품의 모든 요청 끝에 붙는 ADULT_NOTE (llm.with_note). 프롬프트 글은 성인 · 전연령 작품이 같다."""
from canon import llm, prompts, store, usage
from canon.schema import Meta, Project


def _save(name: str, adult: bool) -> None:
    store.save(name, Project(meta=Meta(title=name, genres=["mystery"], adult=adult)))


def test_adult_note_only_for_adult_projects():
    _save("성인작", True)
    _save("전연령작", False)
    with usage.scope(project="성인작"):
        sent = llm.with_note("요청")
    assert sent == f"요청\n\n{llm.ADULT_NOTE}\n\n{llm.POLICY_NOTE}"
    with usage.scope(project="전연령작"):
        assert llm.with_note("요청") == f"요청\n\n{llm.POLICY_NOTE}"


def test_no_adult_note_without_known_project():
    # 작품을 모르거나 읽지 못하면 줄을 넣지 않는다
    assert llm.ADULT_NOTE not in llm.with_note("요청")
    with usage.scope(project="없는작품"):
        assert llm.ADULT_NOTE not in llm.with_note("요청")


def test_prompt_text_stays_the_same():
    # 줄은 보내기 직전에만 붙는다. 프롬프트 함수와 작업지시서는 두 작품에 같은 글을 만든다 (#272)
    adult, kids = (Project(meta=Meta(title="t", genres=["mystery"], adult=a)) for a in (True, False))
    assert prompts.writer_system(adult) == prompts.writer_system(kids)
    assert llm.ADULT_NOTE not in prompts.static_context(adult)
