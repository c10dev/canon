"""인물 신체 프로필(Character.body): 작가만 채우고 인물 상태창에만 보인다. AI 응답 형식과 프롬프트에는 들어가지 않는다."""
import json

from canon import prompts
from canon.schema import Character, PlotBatch, Project, SetupRevision, SetupSuggestion


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
