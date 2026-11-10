"""지킬 것 · 피할 것의 층 (Settings.rule_layers): write 는 본문 쓰기 프롬프트, plan 은 스토리보드 만들기 요청 끝."""

from canon import pipeline, prompts
from canon.schema import RuleLayer
from tests.test_cache_family import _next, _project

WRITE_DO = "시각은 '8시 25분'처럼 아라비아 숫자로 적는다."
PLAN_DO = "아크마다 새 갈등을 하나 더한다."
PLAN_DONT = "같은 갈등을 화마다 되풀이하지 않는다."


def _layered():
    p = _project()
    p.style.dos = [WRITE_DO, PLAN_DO]
    p.style.donts = [PLAN_DONT]
    return p, _next(p)


def test_empty_layers_keep_prompts_the_same():
    p, n = _layered()
    before = (prompts.episode_prompt(p, n), prompts.storyboard_prompt(p, n))
    p.settings.rule_layers = [RuleLayer(text=WRITE_DO, layer="write")]  # write 줄만 있으면 비운 것과 같다
    assert (prompts.episode_prompt(p, n), prompts.storyboard_prompt(p, n)) == before
    assert PLAN_DO in before[0] and prompts.PLAN_RULES_HEAD not in before[0]


def test_plan_rules_leave_head_and_go_to_storyboard_end():
    p, n = _layered()
    p.settings.rule_layers = [RuleLayer(text=PLAN_DO, layer="plan"), RuleLayer(text=PLAN_DONT, layer="plan")]
    head = prompts.write_head(p, n)
    assert WRITE_DO in head and PLAN_DO not in head and PLAN_DONT not in head
    board = prompts.storyboard_prompt(p, n)
    assert board.startswith(head)  # 쓰기 가족 앞부분 캐시는 그대로
    tail = board[board.index(prompts.PLAN_RULES_HEAD):]
    assert f"- 지킬 것: {PLAN_DO}" in tail and f"- 피할 것: {PLAN_DONT}" in tail
    assert board.rstrip().endswith(tail.rstrip())


def test_plan_rules_fall_back_to_write_request_without_storyboard():
    p, n = _layered()
    p.settings.rule_layers = [RuleLayer(text=PLAN_DO, layer="plan")]
    out = prompts.episode_prompt(p, n)
    assert out.count(PLAN_DO) == 1 and prompts.PLAN_RULES_HEAD in out
    assert out.index(PLAN_DO) > len(prompts.write_head(p, n))  # 앞부분이 아니라 지시문에


def test_plan_rules_skip_write_request_with_storyboard():
    from canon.mock import MockLLM
    p, n = _layered()
    p.settings.rule_layers = [RuleLayer(text=PLAN_DO, layer="plan")]
    pipeline.set_storyboard(p, n, pipeline.make_storyboard(MockLLM(), p, n), by="ai")
    out = prompts.episode_prompt(p, n)
    assert PLAN_DO not in out and prompts.PLAN_RULES_HEAD not in out


def test_rule_limit_counts_write_layer_only():
    p, _ = _layered()
    p.style.dos = [f"규칙 {i}" for i in range(pipeline.RULE_LIMIT + 1)]
    p.style.donts = []
    assert "21개" in pipeline.rule_limit_note(p)
    p.settings.rule_layers = [RuleLayer(text="규칙 0", layer="plan")]
    assert pipeline.rule_limit_note(p) == ""


def test_prune_drops_missing_and_write_rows():
    p, _ = _layered()
    p.settings.rule_layers = [RuleLayer(text=PLAN_DO, layer="plan"), RuleLayer(text="지운 규칙", layer="plan"),
                              RuleLayer(text=WRITE_DO, layer="write")]
    pipeline.prune_rule_layers(p)
    assert [(r.text, r.layer) for r in p.settings.rule_layers] == [(PLAN_DO, "plan")]


def test_save_prunes_layers(client):
    from canon import store
    p, _ = _layered()
    p.settings.rule_layers = [RuleLayer(text=PLAN_DO, layer="plan"), RuleLayer(text="지운 규칙", layer="plan")]
    store.save("layers", p)
    body = client.get("/api/projects/layers").json()
    body["settings"]["rule_layers"].append({"text": PLAN_DONT, "layer": "plan"})
    r = client.put("/api/projects/layers", json=body)
    assert r.status_code == 200, r.text
    assert {x["text"] for x in r.json()["settings"]["rule_layers"]} == {PLAN_DO, PLAN_DONT}
