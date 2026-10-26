"""인물 신체 프로필(Character.body): 작가만 채우고 인물 상태창에만 보인다. AI 응답 형식과 프롬프트에는 들어가지 않는다."""
import json

from canon import prompts
from canon.schema import Character, PlotBatch, Project, SetupRevision, SetupSuggestion

from .test_web import client  # noqa: F401  (pytest fixture)


def _hero(**body):
    return Character.model_validate({"id": "hero", "name": "서윤", "role": "주인공", "age": "24세", "body": body})


def test_old_character_gets_empty_body():
    c = Character.model_validate({"id": "hero", "name": "서윤", "role": "주인공"})
    assert c.body.height == "" and c.body.measurements == ""


def test_body_round_trips_in_project():
    p = Project(characters=[_hero(height="165cm", measurements="84-58-86")])
    again = Project.model_validate_json(p.model_dump_json())
    assert again.characters[0].body.height == "165cm"
    assert again.characters[0].body.measurements == "84-58-86"


def test_llm_schemas_have_no_body():
    for schema in (SetupSuggestion, SetupRevision, PlotBatch):
        text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        assert "measurements" not in text and "CharacterBody" not in text, schema.__name__


def test_prompts_leave_body_out():
    p = Project(characters=[_hero(height="165cm", measurements="84-58-86", features="왼손잡이")])
    text = json.dumps(prompts.cast_view(p.characters), ensure_ascii=False)
    assert "84-58-86" not in text and "왼손잡이" not in text
    assert "84-58-86" not in prompts.setup_prompt(p)


MINOR_CASES = ["17세", "19세", "18", "10대 후반", "20대 초반", "고등학생", "대학생", "", "천 살 먹은 용", "1000세", "어린 왕자", "40대"]


def test_minor_age():
    from canon import cast
    got = {a: cast.is_minor_age(a) for a in MINOR_CASES}
    assert got == {"17세": True, "19세": False, "18": True, "10대 후반": True, "20대 초반": False, "고등학생": True, "대학생": False,
                   "": False, "천 살 먹은 용": False, "1000세": False, "어린 왕자": True, "40대": False}


def test_suggest_body_keeps_measurements_for_adults_only():
    from canon import pipeline
    from canon.mock import MockLLM
    p = Project(characters=[_hero(height="165cm"), Character(id="kid", name="하나", role="동생", age="15세")])
    s = pipeline.suggest_body(MockLLM(), p, "hero")
    assert s.height and s.measurements and s.note
    assert pipeline.suggest_body(MockLLM(), p, "kid").measurements == ""
    assert "measurements 는 반드시 빈 문자열" in prompts.body_prompt(p, "kid", True)
    assert "165cm" in prompts.body_prompt(p, "hero", False)  # 작가가 적은 값은 이 제안에만 보인다


def test_web_body(client):
    from .test_plot_chat import _project
    _project(client)
    s = client.post("/api/projects/lh/characters/ally/body").json()
    assert s["height"] and "measurements" in s
    assert client.post("/api/projects/lh/characters/nobody/body").status_code == 400
