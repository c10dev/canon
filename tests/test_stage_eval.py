"""장면 연출 추출 측정 세트 (tests/fixtures/stage_eval.json, scripts/stage_eval.py). 실행: python -m pytest tests
기본 시험은 정답 장면이 맞게 적혔는지와 가짜 LLM 흐름만 본다. 실제 Gemini 측정은 CANON_STAGE_LIVE=1 일 때만 돈다(키는 Canon 설정)."""
import importlib.util
import os
from pathlib import Path

import pytest

from canon.mock import MockLLM

_spec = importlib.util.spec_from_file_location("stage_eval", Path(__file__).resolve().parents[1] / "scripts" / "stage_eval.py")
se = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(se)


def test_gold_scenes_are_consistent():
    """정답은 본문 문장을 그대로 인용하고, 모순판 정답은 심은 규칙에 걸린다. 정답끼리 견주면 모두 맞다."""
    cs = se.cases()
    assert len(cs) == 6 and all(300 <= len(c["text"]) <= 600 for c in cs)
    for c in cs:
        for variant in ("orig", "plant"):
            text, gold = (c["text"], c["gold"]) if variant == "orig" else se.planted(c)
            assert text != c["text"] or variant == "orig"
            p, ep = se.project(c, text)
            g = se.gold_scene(p, ep, gold)
            assert all(b.quote in text for b in g.beats)
            assert all(a == b for a, b in se.score(g, g, p, text).values())
            if variant == "plant":
                assert se.hit(se.rule_issues(p, ep, g), c["plant"]["expect"]), c["id"]


def test_mock_run_shapes_result():
    res = se.run(MockLLM(), tries=1, log=lambda *_: None)
    assert len(res["rows"]) == 12 and res["recall"][1] == 6 and set(res["rate"]) >= {"ref_rel", "upright", "contact_recall"}


@pytest.mark.skipif(not os.environ.get("CANON_STAGE_LIVE"), reason="실제 Gemini 측정은 CANON_STAGE_LIVE=1 일 때만")
def test_live_gemini_extraction(tmp_path, monkeypatch):
    from canon.llm import get_llm

    monkeypatch.setenv("CANON_USAGE", str(tmp_path / "usage.jsonl"))
    res = se.run(get_llm("check"), tries=2, log=print)
    cost = se.cost("")
    print(res["rate"], res["recall"], res["false_alarms"], cost)
    assert cost["calls"] >= 12 and sum("score" in r for r in res["rows"]) >= 10
