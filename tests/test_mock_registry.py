"""가짜 LLM 은 스키마별 응답을 등록표(RESPONDERS)로만 찾는다. json() 안에 스키마 분기가 다시 늘지 않게 본다."""
import inspect

from canon import mock
from canon.schema import ConsistencyReport, EpisodeDraft, PlotBatch, SetupSuggestion


def test_no_schema_branches_in_mock():
    assert "schema is" not in inspect.getsource(mock.MockLLM.json)


def test_core_schemas_registered():
    for s in (SetupSuggestion, PlotBatch, EpisodeDraft, ConsistencyReport):
        assert s in mock.RESPONDERS
