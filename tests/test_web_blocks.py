"""프롬프트 보기와 블록 설정 웹 엔드포인트 (docs/context/specs/03-prompt-view.md).

GET …/episodes/{n}/context, GET · PUT …/blocks, POST …/episodes/{n}/count-tokens."""
import json
import typing

from canon import agent, context, prompts, store, usage, web
from canon.schema import PlotAgentStep
from tests.test_cache_family import _next, _project
from tests.test_char_context import _short


def _save(name, p):
    store.save(name, p)
    return name


def test_context_rows_match_the_write_request(client):
    p = _project()
    n = _next(p)
    _save("sr", p)
    rows = client.get(f"/api/projects/sr/episodes/{n}/context").json()
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))  # 같은 블록 조각은 한 줄로 합친다
    first = []
    for x in prompts.episode_parts(p, n):  # 요청 차례 (장편은 스토리보드가 없으면 시간 · 연출이 직전 화 뒤로 간다)
        if x.id not in first:
            first.append(x.id)
    assert ids == first
    assert rows[0]["title"] == "작품 정보" and all(r["chars"] > 0 and r["text"] for r in rows)  # 빈 블록은 뺀다
    request = prompts.episode_prompt(p, n)
    for r in rows:
        assert r["text"] in request and r["chars"] == len(r["text"]) and r["tokens"] == context.est_tokens(r["text"])
        assert r["on"] is True and r["toggle"] == prompts.toggleable(prompts.BLOCK_BY_ID[r["id"]])
        assert set(r) >= {"id", "title", "chars", "tokens", "on", "locked", "toggle", "front", "note", "budgets", "items", "dropped", "text"}
    cast = next(r for r in rows if r["id"] == "characters")
    assert cast["locked"] and cast["front"] and cast["items"] and all(i["reason"] == context.REASON_ALWAYS for i in cast["items"])
    facts = next(r for r in rows if r["id"] == "facts")
    assert facts["budgets"] == [{"key": "facts", "value": context.BUDGET["facts"], "default": context.BUDGET["facts"],
                                 "min": context.budget_range("facts")[0], "max": context.budget_range("facts")[1]}]


def test_context_shows_off_blocks_and_changed_budgets(client):
    p = _project()
    n = _next(p)
    _save("sr", p)
    on = [r["id"] for r in client.get(f"/api/projects/sr/episodes/{n}/context").json()]
    off = next(x for x in on if prompts.toggleable(prompts.BLOCK_BY_ID[x]))
    r = client.put("/api/projects/sr/blocks", json={"blocks": [{"id": off, "on": False}], "budgets": [{"key": "facts", "value": 2000}]})
    assert r.status_code == 200, r.text
    rows = client.get(f"/api/projects/sr/episodes/{n}/context").json()
    row = next(x for x in rows if x["id"] == off)
    assert row["on"] is False and row["chars"] == 0 and row["text"] == "" and row["items"] == []
    assert [x["id"] for x in rows if x["id"] != off] == [x for x in on if x != off]  # 끈 블록만 빠지고 나머지 차례는 그대로
    q = store.load("sr")
    assert all(x["text"] in prompts.episode_prompt(q, n) for x in rows)
    facts = next(x for x in rows if x["id"] == "facts")
    assert facts["on"] and facts["budgets"][0]["value"] == 2000 and facts["budgets"][0]["default"] == context.BUDGET["facts"]


def test_off_rows_stay_where_the_all_on_request_puts_them(client, monkeypatch):
    """장편에서 스토리보드가 없으면 시간 · 연출이 직전 화 뒤에 온다. 그 블록을 꺼도 줄은 모두 켰을 때의 자리에 그대로 있다"""
    monkeypatch.setattr(prompts, "stage_block", lambda p, n, budget=0, board=False, **kw: "- 서윤: 창가에 선다")
    p = _project()
    n = _next(p)
    assert p.episode(n).storyboard is None
    _save("sr", p)
    on = [r["id"] for r in client.get(f"/api/projects/sr/episodes/{n}/context").json()]
    assert {"time", "stage", "prev"} <= set(on) and on.index("prev") < on.index("time") < on.index("stage")
    r = client.put("/api/projects/sr/blocks", json={"blocks": [{"id": "time", "on": False}, {"id": "stage", "on": False}]})
    assert r.status_code == 200, r.text
    rows = client.get(f"/api/projects/sr/episodes/{n}/context").json()
    assert [x["id"] for x in rows] == on
    assert [x["id"] for x in rows if not x["on"]] == ["time", "stage"]


def test_structure_title_follows_the_form(client):
    p = _project()
    n = _next(p)
    _save("sr", p)
    _save("sh", _short())
    rows = client.get(f"/api/projects/sr/episodes/{n}/context").json()
    assert next(r for r in rows if r["id"] == "structure")["title"] == "현재 부와 아크"
    rows = client.get("/api/projects/sh/episodes/4/context").json()
    assert next(r for r in rows if r["id"] == "structure")["title"] == "현재 구간"
    assert next(b for b in client.get("/api/projects/sr/blocks").json()["blocks"] if b["id"] == "structure")["title"] == "현재 부와 아크"
    assert next(b for b in client.get("/api/projects/sh/blocks").json()["blocks"] if b["id"] == "structure")["title"] == "현재 구간"


def test_context_short_form_has_no_budgets(client):
    p = _short()
    _save("sh", p)
    rows = client.get("/api/projects/sh/episodes/4/context").json()
    assert rows[0]["title"] == "작품 정보" and all(r["budgets"] == [] for r in rows)
    assert all(r["on"] for r in rows)
    assert any(r["id"] == "story" for r in rows)  # 단편의 '지금까지의 줄거리'


def test_blocks_get(client):
    _save("sr", _project())
    _save("sh", _short())
    got = client.get("/api/projects/sr/blocks").json()
    assert got["serial"] is True and [b["id"] for b in got["blocks"]] == [b.id for b in prompts.BLOCKS]
    assert [g["key"] for g in got["budgets"]] == list(context.WRITE_KEYS)
    style = next(b for b in got["blocks"] if b["id"] == "style")
    assert style["locked"] and not style["toggle"] and style["on"] and style["front"] and style["keys"] == []
    facts = next(b for b in got["blocks"] if b["id"] == "facts")
    assert facts["toggle"] and facts["keys"] == ["facts"]
    for g in got["budgets"]:
        assert g["value"] == g["default"] == context.BUDGET[g["key"]] and (g["min"], g["max"]) == context.budget_range(g["key"])
    short = client.get("/api/projects/sh/blocks").json()
    assert short["serial"] is False and short["budgets"] == [] and all(b["on"] for b in short["blocks"])


def test_blocks_put_stores_only_non_default_entries(client):
    _save("sr", _project())
    body = {"blocks": [{"id": "facts", "on": False}, {"id": "world", "on": True}, {"id": "style", "on": True}],
            "budgets": [{"key": "facts", "value": context.BUDGET["facts"]}, {"key": "cast", "value": 4000}]}
    p = client.put("/api/projects/sr/blocks", json=body).json()
    assert p["settings"]["blocks"] == [{"id": "facts", "on": False}]
    assert p["settings"]["budgets"] == [{"key": "cast", "value": 4000}]
    got = client.get("/api/projects/sr/blocks").json()
    assert next(b for b in got["blocks"] if b["id"] == "facts")["on"] is False
    assert next(g for g in got["budgets"] if g["key"] == "cast")["value"] == 4000
    p = client.put("/api/projects/sr/blocks", json={"blocks": [], "budgets": []}).json()  # 두 목록을 통째로 바꾼다
    assert p["settings"]["blocks"] == [] and p["settings"]["budgets"] == []


def test_blocks_put_rejections(client):
    _save("sr", _project())
    _save("sh", _short())
    lo, hi = context.budget_range("facts")
    bad = [
        ("sh", {"blocks": [{"id": "facts", "on": False}]}, "단편은 블록 설정을 쓰지 않아요"),
        ("sr", {"blocks": [{"id": "nope", "on": False}]}, "블록은 없어요"),
        ("sr", {"blocks": [{"id": "style", "on": False}]}, "끌 수 없어요"),
        ("sr", {"blocks": [{"id": "states", "on": False}]}, "끌 수 없어요"),  # 상태창 · 옷차림 규칙이 가리키는 블록
        ("sr", {"blocks": [{"id": "board", "on": False}]}, "다른 설정"),
        ("sr", {"budgets": [{"key": "nope", "value": 1000}]}, "예산은 없어요"),
        ("sr", {"budgets": [{"key": "plan_facts", "value": 1000}]}, "예산은 없어요"),  # 쓰기 가족 밖 키
        ("sr", {"budgets": [{"key": "facts", "value": 0}]}, "100자 단위"),
        ("sr", {"budgets": [{"key": "facts", "value": lo + 50}]}, "100자 단위"),
        ("sr", {"budgets": [{"key": "facts", "value": lo - 100}]}, "100자 단위"),
        ("sr", {"budgets": [{"key": "facts", "value": hi + 100}]}, "100자 단위"),
    ]
    for name, body, word in bad:
        r = client.put(f"/api/projects/{name}/blocks", json=body)
        assert r.status_code == 400 and word in r.json()["detail"], (body, r.text)
        assert r.json()["detail"].endswith("요")  # 해요체
    assert store.load("sr").settings.blocks == [] and store.load("sr").settings.budgets == []
    assert store.load("sh").settings.blocks == []


def test_count_tokens_mock_has_no_counter(client):
    p = _project()
    n = _next(p)
    _save("sr", p)
    r = client.post(f"/api/projects/sr/episodes/{n}/count-tokens").json()
    assert r["tokens"] is None and r["note"] == "이 백엔드는 토큰을 셀 수 없어요"
    assert r["estimate"] > context.est_tokens(prompts.episode_prompt(p, n))  # 시스템 프롬프트와 덧붙는 줄까지 센다


def test_count_tokens_records_usage_with_zero_tokens(client, monkeypatch, tmp_path):
    p = _project()
    n = _next(p)
    _save("sr", p)
    seen = []

    class GeminiLLM:  # usage.backend_of 가 이름으로 백엔드를 고른다
        model = "fake"

        def count_tokens(self, text):
            seen.append(text)
            return 1234

    monkeypatch.setattr(web, "get_llm", lambda stage: GeminiLLM())
    log = tmp_path / "usage.jsonl"
    monkeypatch.setenv("CANON_USAGE", str(log))
    r = client.post(f"/api/projects/sr/episodes/{n}/count-tokens").json()
    assert r == {"tokens": 1234, "estimate": r["estimate"], "note": ""}
    assert len(seen) == 1 and seen[0].startswith(prompts.writer_system(p)) and prompts.episode_prompt(p, n).strip() in seen[0]
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["task"] == "토큰 세기" and rows[0]["in"] == 0 and rows[0]["out"] == 0
    assert rows[0]["project"] == "sr" and rows[0]["episode"] == n
    assert usage.totals(rows)[:2] == (0, 0)

    class Broken(GeminiLLM):
        def count_tokens(self, text):
            raise RuntimeError("세기 실패")

    monkeypatch.setattr(web, "get_llm", lambda stage: Broken())
    r = client.post(f"/api/projects/sr/episodes/{n}/count-tokens").json()
    assert r["tokens"] is None and r["note"] == "이 백엔드는 토큰을 셀 수 없어요"
    assert len(log.read_text().splitlines()) == 1  # 실패한 세기는 남기지 않는다


def test_agent_has_no_block_or_budget_tool():
    tools = typing.get_args(PlotAgentStep.model_fields["tool"].annotation)
    assert tools and not any("block" in t or "budget" in t for t in tools)
    src = open(agent.__file__, encoding="utf-8").read()
    assert "settings.blocks" not in src and "settings.budgets" not in src and "BlockSetting" not in src
