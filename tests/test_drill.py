"""지시 연습 (canon/drill.py, docs/drill) 시험 (mock LLM). 실행: python -m pytest tests/test_drill.py"""
import json
import math
import random

import pytest

from canon import drill, mock, pipeline, prompts, refdigest, refs, store, studio
from canon.schema import DrillBrief, DrillFacts, DrillGap, DrillInvented, DrillLineVerdict, DrillPerson, DrillReview, DrillRound, DrillVerdict, RefCut, WriteMark

from .test_ai_jobs import _wait

L = mock.MockLLM()
LINES = ["서연은 가게 문을 밀고 들어섰다. 종이 길게 울렸다.", "\"어서 오세요.\" 도윤이 고개도 들지 않고 말했다.", "계산대 위에는 식은 컵라면이 놓여 있었다.",
         "\"여기 원래 이 시간에도 열어요?\" 서연이 물었다.", "도윤은 대답 대신 진열대 쪽으로 걸어갔다.", "형광등 하나가 깜빡였다. 서연은 그 아래에 섰다."]


def _text(n: int, seed: int) -> str:
    return "\n".join(f"{LINES[(i + seed) % len(LINES)]} {seed}-{i}번째 줄이다." for i in range(n))


@pytest.fixture()
def book(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setattr(store, "ROOT", tmp_path)
    text = "\n\n".join(f"{i}화\n\n{_text(60, i)}" for i in range(1, 5))
    d = refs.preview(text, repeats=[])
    cuts = [RefCut(**{k: c[k] for k in ("line", "body", "head", "label", "title", "kind")}) for c in d["cuts"] if c["on"]]
    return refs.create("가게", text, cuts, rights=True)


def test_passages_cover_the_episode_at_line_bounds():
    text = _text(60, 1)
    ps = drill.passages(text)
    assert len(ps) >= 3 and all(drill.PASSAGE_MIN <= len(p["text"]) <= drill.PASSAGE + 200 for p in ps)
    assert "".join(p["text"] for p in ps).replace("\n", "") == text.replace("\n", "")  # 빠진 글 · 겹친 글이 없다
    assert all(p["text"].split("\n")[0] in text.split("\n") for p in ps)  # 줄 가운데에서 자르지 않는다
    assert drill.passages(text) == ps and drill.passages("") == []
    short = drill.passages(_text(3, 2))
    assert len(short) == 1 and short[0]["text"] == _text(3, 2)


def test_pick_by_choice_and_by_card(book):
    eps = drill.episodes(book.id)
    assert [e["order"] for e in eps] == [1, 2, 3, 4] and all(e["parts"] >= 3 and e["kind"] == "" for e in eps)
    x = drill.pick(book.id, order=2, part=2)
    assert (x["order"], x["part"]) == (2, 2) and x["lead"] and x["lead"] in refs.episode_text(book.id, 2) and x["text"] not in x["lead"]
    assert drill.pick(book.id, order=2, part=1)["lead"] == ""
    with pytest.raises(KeyError):
        drill.pick(book.id, order=9)
    with pytest.raises(KeyError):
        drill.pick(book.id, order=1, part=99)
    with pytest.raises(ValueError, match="화 카드"):  # 화 카드가 없는데 성격을 골랐다
        drill.pick(book.id, kind="대화")
    assert drill.pick(book.id, rng=random.Random(1))["order"] in (1, 2, 3, 4)  # 조건이 없으면 화 카드 없이도 고른다
    refdigest.run(book.id, refdigest.llm_for(book.id))
    kinds = {e["order"]: (e["kind"], e["tension"]) for e in drill.episodes(book.id)}
    assert all(k for k, _ in kinds.values())
    kind, tension = kinds[3]
    got = {drill.pick(book.id, kind=kind, tension=tension, rng=random.Random(i))["order"] for i in range(12)}
    assert got and all(kinds[o][0] == kind and kinds[o][1] >= tension for o in got)


def _round(book, **kw) -> DrillRound:
    r = drill.create(book.id, order=1, part=2, **kw)
    drill.set_facts(r, pipeline.drill_facts(L, r.source, r.lead), "mock")
    return drill.save(r)


def test_facts_drop_copied_lines_and_fill_the_brief(book):
    r = _round(book)
    assert [p.name for p in r.facts.people] == ["서연", "도윤"] and len(r.facts.events) == 4  # 이름 없는 인물 · 빈 줄 · 원문을 옮긴 줄이 빠졌다
    assert not any(refs.overlap(e, [r.source]) for e in r.facts.events)
    assert r.brief.events.split("\n") == r.facts.events and r.brief.people.startswith("서연: ") and r.brief.change == ""
    r.brief.avoid, r.brief.events = "목소리를 높이지 않는다", r.brief.events + "\n서연이 먼저 나간다"
    drill.set_facts(r, pipeline.drill_facts(L, r.source, r.lead))  # 작가가 고친 칸은 다시 뽑아도 덮지 않는다
    assert r.brief.events.endswith("서연이 먼저 나간다") and r.brief.avoid == "목소리를 높이지 않는다"
    lead = "도윤은 계산대 뒤에서 삼 년째 밤을 새우는 사람이었다. 손님은 드물었다."
    f = drill.clean_facts(DrillFacts(people=[DrillPerson(name="도윤", note="계산대 뒤에서 삼 년째 밤을 새우는 사람이었다")], pov="", place="", time="",
                                     before="손님은 드물었다. 도윤은 계산대 뒤에서 삼 년째 밤을 새우는 사람이었다.", events=["서연이 들어온다"]), r.source, lead)
    assert f.people[0].note == "" and f.before == ""  # 대목 앞의 글을 옮긴 줄도 버린다
    with pytest.raises(ValueError, match="뽑지 못했"):
        drill.clean_facts(DrillFacts(people=[], pov="", place="", time="", before="", events=[" ", r.source[:40]]), r.source)


def test_brief_limits_and_author_lines(book):
    r = _round(book)
    base = drill.facts_brief(r.facts)
    b = drill.clean_brief(r.brief.model_copy(update={"change": " 서연이 물러서던 사람에서 버티는 사람으로 \n\n", "avoid": "손대기\n목소리 높이기", "manner": "짧은 존댓말",
                                                     "place": "편의점", "events": r.brief.events + "\n도윤이 컵라면을 치운다"}))
    assert b.change == "서연이 물러서던 사람에서 버티는 사람으로"
    rows = drill.author_lines(b, base)
    assert [(x.no, x.box) for x in rows] == [(1, "place"), (2, "events"), (3, "change"), (4, "avoid"), (5, "avoid"), (6, "manner")]
    assert rows[1].text == "도윤이 컵라면을 치운다"  # AI가 뽑은 줄은 작가가 쓴 줄이 아니다
    with pytest.raises(ValueError, match="5줄까지"):
        drill.clean_brief(b.model_copy(update={"manner": "하나\n둘\n셋"}))
    with pytest.raises(ValueError, match="쓰는 방식"):
        drill.can_write(r, drill.clean_brief(r.brief))
    with pytest.raises(ValueError, match="일어나는 일"):
        drill.can_write(r, b.model_copy(update={"events": ""}))
    with pytest.raises(ValueError, match="원문 문장"):  # 원문을 본 뒤 고쳐 쓸 때 원문을 옮겨 적지 못하게
        drill.can_write(r, b.model_copy(update={"manner": r.source[5:45].split("\n")[0]}))
    with pytest.raises(ValueError, match="'직전 상황' 칸에 원문"):  # 사실 뽑기에 넣은 앞부분도 원문이다
        drill.can_write(r, b.model_copy(update={"before": r.lead[-60:].split("\n")[-1]}))
    drill.can_write(r, b)


def test_write_prompt_has_no_source(book):
    """쓰기 요청에는 원문 대목과 앞부분이 들어가지 않는다. 두 판의 요청은 쓰는 방식만 다르다."""
    r = _round(book)
    b = drill.clean_brief(r.brief.model_copy(update={"avoid": "목소리를 높이지 않는다", "manner": "짧은 존댓말"}))
    seen = []

    class Spy(mock.MockLLM):
        def json(self, system, prompt, schema, hint=None):
            seen.append(system + "\n" + prompt)
            return super().json(system, prompt, schema, hint)

    card, bare = drill.card_of(r, b), drill.card_of(r, b, bare=True)
    w, x = pipeline.drill_write(Spy(), card, bare)
    assert len(seen) == 2 and w != x
    for p in seen:
        assert not refs.overlap(p, [r.source, r.lead])
    assert "- 하지 않는 것: 목소리를 높이지 않는다\n- 방식: 짧은 존댓말" in seen[0] and "하지 않는 것" not in seen[1]
    assert "일어나는 일 (이 차례대로):\n1. " in seen[1] and "직전 상황: " in seen[1]
    assert seen[0].replace(prompts.paragraph_prompt(studio.world(card), card, 1, []), "") != seen[0]  # 문단 연습장 요청 그대로다
    assert card.people[0].name == "서연" and card.people[0].note and card.pov == "서연" and card.length == round(len(r.source) / 50) * 50


def test_review_keeps_only_quotes_found_in_the_text(book):
    r = _round(book)
    b = drill.clean_brief(r.brief.model_copy(update={"change": "서연이 물러서던 사람에서 버티는 사람으로", "avoid": "손대기", "manner": "짧은 존댓말\n낮은 목소리"}))
    a = drill.add_attempt(r, b, "서연은 “그래요⋯.” 하고 말했다. 목소리는 끝까지 낮았다.", "서연은 소리를 질렀다. 도윤의 팔을 잡았다.", "mock")
    rv = DrillReview(lines=[
        DrillLineVerdict(no=1, layer="change", result="ignored", why="무엇이 바뀌는지 글에 없어요"),
        DrillLineVerdict(no=2, layer="ban", result="applied", bare_quote="도윤의 팔을 잡았다", why="지시 없는 판만 손을 댔어요"),
        DrillLineVerdict(no=3, layer="manner", result="applied", quote='"그래요…" 하고 말했다', in_bare=False),  # 따옴표 · 줄임표 모양이 달라도 찾는다
        DrillLineVerdict(no=4, layer="manner", result="overdone", quote="본문에 없는 문장이에요", same_as=3),
        DrillLineVerdict(no=4, layer="manner", result="applied", quote="목소리는 끝까지 낮았다"),  # 같은 줄을 두 번 판정하면 처음 것만
        DrillLineVerdict(no=7, layer="manner", result="applied", quote="서연은")],
        invented=[DrillInvented(side="bare", quote="도윤의 팔을 잡았다", what="없던 몸싸움"), DrillInvented(side="with", quote="도윤의 팔을 잡았다", what="다른 판의 문장")],
        gaps=[DrillGap(what="가게의 소리", quote=r.source[:12]), DrillGap(what="근거 없음", quote="원문에 없는 말")])
    drill.set_review(r, a.no, rv, "judge")
    got = {v.no: v for v in a.verdicts}
    assert [got[n].result for n in (1, 2, 3, 4)] == ["ignored", "applied", "applied", "unsure"]
    assert got[2].bare_quote and got[3].quote and got[4].quote == "" and got[4].same_as == 3 and got[1].box == "change" and got[2].text == "손대기"
    assert [x.what for x in a.invented] == ["없던 몸싸움"] and [g.what for g in a.gaps] == ["가게의 소리"]
    assert a.dropped == 3 and a.review_model == "judge" and a.reviewed_at
    drill.set_review(r, a.no, DrillReview(lines=[]))  # AI가 빠뜨린 줄은 판정 못 함으로 남는다
    assert [v.result for v in a.verdicts] == ["unsure"] * 4 and "판정하지 않았" in a.verdicts[0].why
    assert [v.layer for v in a.verdicts] == ["change", "ban", "manner", "manner"]  # 층은 적은 칸으로 어림한다
    assert not drill.quoted("서연", a.with_text) and drill.quoted("목소리는 끝까지", a.with_text)


def test_view_hides_the_source_until_written(book):
    r = _round(book)
    v = drill.view(r)
    assert v["source"] == "" and "lead" not in v and v["source_chars"] == len(r.source) and v["stage"] == "brief" and not v["revealed"]
    assert v["base"]["events"] == r.brief.events and v["lines"] == [] and v["source_measure"] is None
    drill.add_attempt(r, r.brief, "지시 있는 판이다.", "지시 없는 판이다.")
    v = drill.view(r)
    assert v["source"] == r.source and "lead" not in v and v["stage"] == "written" and v["measures"]["1"]["with"]["chars"] > 0
    assert v["source_measure"]["chars"] > 0


def test_web_round_runs_to_the_review(client, book, monkeypatch):
    home = client.get("/api/drill").json()
    assert home["sources"] == [{"id": book.id, "name": "가게", "eps": 4}] and home["rounds"] == [] and home["method_max"] == 5
    assert [x["id"] for x in home["layers"]] == list(drill.LAYERS) and len(client.get(f"/api/drill/sources/{book.id}").json()["episodes"]) == 4
    assert client.get("/api/drill/sources/abcdef123456").status_code == 404
    assert client.post("/api/drill", json={"ref_id": "abcdef123456"}).status_code == 404
    assert client.post("/api/drill", json={"ref_id": book.id, "style_id": "abcdef123456"}).status_code == 400
    r = client.post("/api/drill", json={"ref_id": book.id, "order": 2, "part": 2}).json()
    did, url = r["id"], f"/api/drill/{r['id']}"
    assert r["stage"] == "facts" and r["source"] == "" and r["title"].startswith("가게 2화")
    assert client.post(f"{url}/jobs", json={"kind": "review"}).status_code == 400

    def done(body):
        res = client.post(f"{url}/jobs", json=body)
        assert res.status_code == 200, res.text
        j = _wait(client, res.json()["id"])
        assert j["status"] == "done" and j["project"] == ".drill" and j["target"] == did, j
        return j

    assert done({"kind": "facts"})["result"]["events"] == 4
    r = client.get(url).json()
    assert r["stage"] == "brief" and r["source"] == "" and r["brief"]["events"]
    assert client.post(f"{url}/jobs", json={"kind": "write"}).status_code == 400  # 쓰는 방식이 비었다
    brief = {**r["brief"], "change": "서연이 묻는 사람에서 버티는 사람으로", "avoid": "목소리 높이기", "manner": "짧은 존댓말"}
    assert client.put(url, json={"brief": {**brief, "manner": "1\n2\n3\n4"}}).status_code == 400
    r = client.put(url, json={"brief": brief}).json()
    assert r["method_lines"] == 3 and [x["box"] for x in r["lines"]] == ["change", "avoid", "manner"]
    assert r["hints"] == [] and client.get("/api/drill").json()["rounds"][0]["style_id"] == ""
    j = done({"kind": "write"})
    assert j["result"] == {"id": did, "no": 1, "reviewed": True} and j["kind"] == "dr_write"
    r = client.get(url).json()
    a = r["attempts"][0]
    assert r["stage"] == "reviewed" and r["source"] and a["with_text"] != a["bare_text"] and a["with_text"].startswith(a["bare_text"])
    assert [v["result"] for v in a["verdicts"]] == ["applied", "unsure", "ignored"] and a["verdicts"][0]["quote"] and a["verdicts"][0]["layer"] == "change"
    assert len(a["invented"]) == 1 and len(a["gaps"]) == 1 and a["dropped"] == 3
    assert client.post(f"{url}/jobs", json={"kind": "write"}).status_code == 400  # 한 판은 한 번 쓴다
    assert done({"kind": "review"})["result"]["reviewed"] is True
    home = client.get("/api/drill").json()
    assert home["rounds"][0]["results"]["applied"] == 1 and home["stats"]["rounds"] == 1 and home["stats"]["lines"] == 3

    # 한 번 고치기: 고친 지시로 다시 쓰고, 고르기 전에는 어느 글이 어느 쪽인지와 되짚기를 싣지 않는다
    assert client.post(f"{url}/jobs", json={"kind": "revise"}).status_code == 400  # 고친 곳이 없다
    assert client.post(f"{url}/pick", json={"side": "left"}).status_code == 400  # 고를 것이 없다
    fixed = {**brief, "change": "서연이 묻던 사람에서 대답을 받아 내는 사람으로 바뀐다", "manner": "짧은 존댓말\n말 사이를 길게 둔다"}
    client.put(url, json={"brief": fixed})
    j = done({"kind": "revise"})
    assert j["kind"] == "dr_revise" and j["result"] == {"id": did, "no": 2, "reviewed": True}
    r = client.get(url).json()
    b = r["attempts"][1]
    assert r["stage"] == "pick" and set(r["blind"]) == {"left", "right"} and r["blind"]["left"] != r["blind"]["right"]
    assert b["with_text"] == "" and b["old_text"] == "" and b["verdicts"] == [] and b["flip"] is False and b["versus"] == 1 and "2" not in r["measures"]
    assert client.post(f"{url}/jobs", json={"kind": "review"}).status_code == 400 and client.get("/api/drill").json()["rounds"][0]["pick"] == ""
    saved = drill.load(did).attempts[1]
    side = "left" if saved.flip else "right"  # 고친 지시로 쓴 판이 있는 쪽
    assert r["blind"][side] == saved.with_text and saved.old_text and saved.bare_text == a["bare_text"]
    r = client.post(f"{url}/pick", json={"side": side}).json()
    b = r["attempts"][1]
    assert r["stage"] == "done" and r["blind"] is None and b["pick"] == "new" and b["with_text"] == saved.with_text and len(b["verdicts"]) == 4
    assert r["changed"]["added"] == [{"box": "change", "text": fixed["change"]}, {"box": "manner", "text": "말 사이를 길게 둔다"}]
    assert r["changed"]["removed"] == [{"box": "change", "text": brief["change"]}] and r["measures"]["2"]["old"]["chars"] > 0
    assert client.post(f"{url}/pick", json={"side": "skip"}).status_code == 400 and client.post(f"{url}/jobs", json={"kind": "revise"}).status_code == 400
    st = client.get("/api/drill").json()["stats"]
    assert st["picks"] == {"new": 1, "old": 0, "skip": 0} and client.get("/api/drill").json()["rounds"][0]["pick"] == "new"
    assert not (store.ROOT / "projects").exists() and (store.ROOT / ".drill" / f"{did}.json").exists()
    monkeypatch.setenv("CANON_DRILL", str(store.ROOT / "elsewhere"))
    assert client.get(url).status_code == 404 and client.get("/api/drill").json()["rounds"] == []
    monkeypatch.delenv("CANON_DRILL")
    assert client.delete(url).json() == {"ok": True} and client.get(url).status_code == 404


def test_write_keeps_the_texts_when_the_review_fails(client, book, monkeypatch):
    r = client.post("/api/drill", json={"ref_id": book.id, "order": 1, "part": 1}).json()
    url = f"/api/drill/{r['id']}"
    _wait(client, client.post(f"{url}/jobs", json={"kind": "facts"}).json()["id"])
    client.put(url, json={"brief": {**client.get(url).json()["brief"], "avoid": "목소리 높이기"}})

    def boom(*a, **k):
        raise RuntimeError("판정 실패")

    monkeypatch.setattr(pipeline, "drill_review", boom)
    j = _wait(client, client.post(f"{url}/jobs", json={"kind": "write"}).json()["id"])
    assert j["status"] == "done" and j["result"]["reviewed"] is False
    r = client.get(url).json()
    assert r["stage"] == "written" and r["attempts"][0]["with_text"] and r["attempts"][0]["verdicts"] == []


def test_prompts_are_registered():
    assert prompts.KINDS["drill_facts"].response == "DrillFacts" and prompts.KINDS["drill_review"].caller == "pipeline.drill_review"
    p = prompts.drill_review_prompt(drill.author_lines(DrillBrief(avoid="손대기")), "사실", "지시 있는 판 글", "지시 없는 판 글", "원문 글")
    assert "1. [하지 않는 것] 손대기" in p and all(v[0] in p for v in drill.LAYERS.values())
    assert p.index("# 지시 있는 판") < p.index("# 지시 없는 판") < p.index("# 원문") < p.index("# 할 일")
    q = prompts.drill_facts_prompt("대목 글", "")
    assert "화의 첫 대목" in q and "대목 글" in q
    assert DrillPerson(name="서연").note == ""


def _judged(book, results, pick="", layer="manner", added=None):
    """줄 판정을 손으로 채운 판. results 는 첫 시도의 줄마다 (결과, 지시 없는 판도 같음)."""
    r = drill.create(book.id, order=1, part=1)
    a = drill.add_attempt(r, DrillBrief(events="말을 건다", manner="\n".join(f"줄 {i}" for i in range(len(results)))), "글", "글")
    a.verdicts = [DrillVerdict(no=i, text=f"줄 {i}", layer=layer, result=res, in_bare=same) for i, (res, same) in enumerate(results, 1)]
    if pick:
        b = drill.add_revision(r, DrillBrief(events="말을 건다", manner="새 줄"), "새 글", "옛 글")
        b.verdicts = [DrillVerdict(no=1, text="새 줄", layer=added or layer, result="applied"), DrillVerdict(no=2, text="줄 1", layer="ban", result="applied")]
        drill.pick_side(r, "skip" if pick == "skip" else "left" if (pick == "new") == b.flip else "right")
        assert b.pick == pick
    return drill.save(r)


def test_stats_count_layers_results_and_revision_wins(book):
    assert drill.stats([]) == {"rounds": 0, "lines": 0, "worked": None, "picks": {"new": 0, "old": 0, "skip": 0}, "shrink": {"new": 0, "old": 0, "skip": 0}, "match": {"new": 0, "old": 0, "skip": 0},
                               "write": {"rounds": 0, "chars": 0, "next_tries": []}, "recent_n": 5, "recent": None, "before": None, "trend": [],
                               "layers": [{"id": k, "label": v[0], "lines": 0, "applied": 0, "overdone": 0, "ignored": 0, "unsure": 0, "worked": 0, "added": 0, "won": 0,
                                           "share": 0.0} for k, v in drill.LAYERS.items()]}
    rs = [_judged(book, [("applied", False), ("applied", True), ("ignored", False), ("unsure", False)], pick="new", added="change"),
          _judged(book, [("overdone", False)], layer="background", pick="old", added="change"),
          _judged(book, [("applied", False)], layer="ban", pick="skip", added="change"),
          drill.create(book.id, order=1, part=1)]  # 쓰지 않은 판은 세지 않는다
    for i, r in enumerate(rs):
        r.created_at = f"2026-11-1{i}T09:00:00"
    st = drill.stats(rs)
    by = {x["id"]: x for x in st["layers"]}
    assert st["rounds"] == 3 and st["lines"] == 6 and st["picks"] == {"new": 1, "old": 1, "skip": 1}
    assert (by["manner"]["lines"], by["manner"]["applied"], by["manner"]["ignored"], by["manner"]["unsure"], by["manner"]["worked"]) == (4, 2, 1, 1, 1)
    assert by["manner"]["share"] == round(4 / 6, 3) and by["background"]["overdone"] == 1 and by["ban"]["worked"] == 1
    assert (by["change"]["added"], by["change"]["won"]) == (2, 1) and by["ban"]["added"] == 0  # 비슷함은 빼고, 앞 시도에 있던 줄도 뺀다
    assert st["worked"] == round(2 / 5, 3)  # 판정 못 함은 분모에서 뺀다
    assert [x["created_at"][:10] for x in st["trend"]] == ["2026-11-12", "2026-11-11", "2026-11-10"] and st["trend"][2]["layers"] == [{"id": "manner", "n": 3}]
    assert st["recent"] == st["worked"] and st["before"] is None
    many = [rs[1]] * 4 + [rs[2]] * drill.RECENT
    assert drill.stats(many)["recent"] == 1.0 and drill.stats(many)["before"] == 0.0


def test_revise_guards(book):
    r = _round(book)
    b = drill.clean_brief(r.brief.model_copy(update={"avoid": "손대기"}))
    with pytest.raises(ValueError, match="먼저 두 판"):
        drill.can_revise(r, b)
    drill.add_attempt(r, b, "지시 있는 판", "지시 없는 판")
    with pytest.raises(ValueError, match="고친 곳이 없"):
        drill.can_revise(r, b)
    with pytest.raises(ValueError, match="원문 문장"):  # 원문을 본 뒤라 원문을 옮겨 적을 수 있다
        drill.can_revise(r, b.model_copy(update={"manner": r.source.split("\n")[1][:40]}))
    new = b.model_copy(update={"avoid": "손대기\n다가서기"})
    assert drill.can_revise(r, new).no == 1
    a = drill.add_revision(r, new, "고친 판", "다시 쓴 앞 판", rng=random.Random(3))
    assert (a.versus, a.old_text, a.bare_text, a.pick) == (1, "다시 쓴 앞 판", "지시 없는 판", "") and drill.pending(r) is a and drill.stage(r) == "pick"
    with pytest.raises(ValueError, match="한 번만"):
        drill.can_revise(r, new.model_copy(update={"manner": "짧게"}))
    with pytest.raises(ValueError, match="가운데 고르세요"):
        drill.pick_side(r, "middle")
    drill.pick_side(r, "left" if not a.flip else "right")
    assert a.pick == "old" and a.picked_at and drill.pending(r) is None and drill.stage(r) == "done"


def test_card_writes_in_lines_with_inner_facts_and_no_invention(book):
    """2026-11-12 작가의 세 판: AI 글이 한 덩어리로 나왔고, 원문의 속사정이 사실에서 빠졌고, 없는 과거를 지어냈다."""
    r = _round(book)
    assert r.facts.inner == ["서연은 물건을 사러 온 것이 아니다"] and r.brief.inner == r.facts.inner[0]  # 빈 줄 · 원문을 옮긴 줄은 빠진다
    b = drill.clean_brief(r.brief.model_copy(update={"avoid": "주변 묘사", "inner": r.brief.inner + "\n도윤을 전에 본 적이 있다"}))
    card, bare = drill.card_of(r, b), drill.card_of(r, b, bare=True)
    assert card.lines and bare.lines and card.action == bare.action and card.action.endswith(drill.NO_INVENT)
    assert "서연만 아는 속사정:\n· 서연은 물건을 사러 온 것이 아니다\n· 도윤을 전에 본 적이 있다\n일어나는 일" in card.action
    p = prompts.paragraph_prompt(studio.world(card), card, 1, [])
    assert "장면 한 토막" in p and prompts.PARAGRAPH_LINES in p and "한 덩어리로 씁니다" not in p
    plain = card.model_copy(update={"lines": False})
    q = prompts.paragraph_prompt(studio.world(plain), plain, 1, [])
    assert "문단 하나(약" in q and "빈 줄 없이 한 덩어리로 씁니다" in q and prompts.PARAGRAPH_LINES not in q  # 문단 연습장은 그대로다
    assert [(x.box, x.text) for x in drill.author_lines(b, drill.facts_brief(r.facts))] == [("inner", "도윤을 전에 본 적이 있다"), ("avoid", "주변 묘사")]
    assert "시점 인물의 속사정:\n- 서연은 물건을 사러 온 것이 아니다" in drill.brief_text(b)
    old = DrillRound.model_validate({"id": "a" * 12, "facts": {"people": [], "pov": "", "place": "", "time": "", "before": "", "events": ["말을 건다"]}})
    assert old.facts.inner == [] and drill.facts_brief(old.facts).inner == ""  # 속사정이 없던 때의 판 파일도 읽힌다


def test_hints_point_at_lines_that_do_not_change_the_text():
    b = DrillBrief(events="강주혁이 순수하게 고마워서 사는 것이라며 식사를 권한다\n서하은이 한 번뿐이라며 승낙한다", change="서하은의 태도, 성격", manner="짧게 끊는다")
    got = {(h["box"], h["text"]): h["hint"] for h in drill.hints(b)}
    assert "무엇에서 무엇으로" in got[("change", "서하은의 태도, 성격")] and "비었어요" in got[("avoid", "")] and ("manner", "짧게 끊는다") not in got
    again = b.model_copy(update={"change": "순수하게 고마워서 사는 것이라며 식사를 권한다", "avoid": "주변 묘사"})
    assert [(h["box"], h["hint"][:10]) for h in drill.hints(again)] == [("change", "일어나는 일에 이미")]
    assert drill.hints(again.model_copy(update={"change": "", "avoid": "식사를 권한다고 순수하게 고마워서 사는 것이라며"})) == []  # 금지 줄은 겹쳐도 짚지 않는다
    good = b.model_copy(update={"change": "하은이 겁먹은 사람에서 다시 쏘아붙이는 사람으로 돌아온다\n주혁이 자기가 위협하는 쪽임을 알아챈다", "avoid": "손대기"})
    assert drill.hints(good) == [] and drill.hints(DrillBrief(events="말을 건다")) == []


def test_shrink_round_writes_the_short_and_the_dense_brief_and_picks_blind(client, book):
    assert client.get("/api/drill").json()["modes"] == drill.MODES and client.post("/api/drill", json={"ref_id": book.id, "mode": "nope"}).status_code == 422
    r = client.post("/api/drill", json={"ref_id": book.id, "order": 3, "part": 2, "mode": "shrink"}).json()
    did, url = r["id"], f"/api/drill/{r['id']}"
    assert r["mode"] == "shrink" and r["stage"] == "facts" and r["dense"] == [] and r["shrink_max"] == 3

    def done(body):
        j = _wait(client, client.post(f"{url}/jobs", json=body).json()["id"])
        assert j["status"] == "done", j
        return j

    done({"kind": "facts"})
    r = client.get(url).json()
    dense = [x["text"] for x in r["dense"]]
    assert r["stage"] == "brief" and r["brief"]["events"] == "" and r["brief"]["before"] == "" and r["brief"]["people"] and len(dense) >= 5 and r["hints"] == []
    assert {x["box"] for x in r["dense"]} == {"before", "inner", "events"}
    assert client.post(f"{url}/jobs", json={"kind": "shrink"}).status_code == 400  # 줄인 지시가 비었다
    assert client.post(f"{url}/jobs", json={"kind": "write"}).status_code == 400  # 줄이기 판은 두 판 쓰기를 받지 않는다
    client.put(url, json={"brief": {**r["brief"], "events": "1\n2\n3\n4"}})
    assert "3줄까지" in client.post(f"{url}/jobs", json={"kind": "shrink"}).json()["detail"]
    client.put(url, json={"brief": {**r["brief"], "events": drill.load(did).source.split("\n")[0]}})
    assert "원문 문장" in client.post(f"{url}/jobs", json={"kind": "shrink"}).json()["detail"]
    client.put(url, json={"brief": {**r["brief"], "events": "서연이 가게에 들어와 묻는다\n도윤이 대답을 피한다", "manner": "짧게"}})
    j = done({"kind": "shrink"})
    assert j["kind"] == "dr_shrink" and j["result"] == {"id": did, "no": 1}
    r = client.get(url).json()
    a = r["attempts"][0]
    assert r["stage"] == "pick" and r["source"] == "" and not r["revealed"] and r["source_measure"] is None  # 고르기 전에는 원문도 가린다
    assert a["with_text"] == "" and a["old_text"] == "" and r["measures"] == {} and r["blind"]["left"] != r["blind"]["right"]
    saved = drill.load(did).attempts[0]
    assert saved.brief.events == "서연이 가게에 들어와 묻는다\n도윤이 대답을 피한다" and saved.brief.before == "" and saved.brief.manner == "" and not saved.verdicts
    assert "도윤이 대답을 피한다" in saved.with_text and dense[-1] in saved.old_text and dense[-1] not in saved.with_text  # 줄인 지시의 판에는 뽑은 줄이 들어가지 않았다
    assert client.post(f"{url}/jobs", json={"kind": "review"}).status_code == 400 and client.post(f"{url}/jobs", json={"kind": "shrink"}).status_code == 400
    assert client.post(f"{url}/jobs", json={"kind": "revise"}).status_code == 400
    side = "right" if saved.flip else "left"  # 뽑은 지시로 쓴 판이 있는 쪽
    r = client.post(f"{url}/pick", json={"side": side}).json()
    assert r["stage"] == "done" and r["attempts"][0]["pick"] == "old" and r["source"] and r["measures"]["1"]["old"]["chars"] > 0
    home = client.get("/api/drill").json()
    assert home["stats"]["shrink"] == {"new": 0, "old": 1, "skip": 0} and home["stats"]["rounds"] == 0  # 줄이기 판은 층 기록에 넣지 않는다
    assert home["rounds"][0]["mode"] == "shrink" and home["rounds"][0]["pick"] == "old"


def test_shrink_cards_share_the_facts_and_have_no_method(book):
    r = drill.create(book.id, order=1, part=2, mode="shrink")
    drill.set_facts(r, pipeline.drill_facts(L, r.source, r.lead), "mock")
    with pytest.raises(ValueError, match="한 줄은"):
        drill.shrink_briefs(r, r.brief)
    r.brief.events = "서연이 묻고 도윤이 피한다"
    short, dense = drill.shrink_briefs(r, drill.clean_brief(r.brief))
    a, b = drill.card_of(r, short, bare=True), drill.card_of(r, dense, bare=True)
    assert (a.people, a.pov, a.place, a.time, a.extra, a.lines) == (b.people, b.pov, b.place, b.time, "", True) and b.extra == ""
    assert "서연이 묻고 도윤이 피한다" in a.action and "속사정" not in a.action and "직전 상황" not in a.action and drill.NO_INVENT in a.action
    assert all(e in b.action for e in r.facts.events) and "속사정" in b.action
    with pytest.raises(ValueError, match="줄이기 판이 아니에요"):
        drill.shrink_briefs(_round(book), DrillBrief(events="한 줄"))
    with pytest.raises(ValueError, match="모르는 연습"):
        drill.create(book.id, mode="other")


def test_match_round_writes_two_methods_and_checks_the_guess(client, book):
    r = client.post("/api/drill", json={"ref_id": book.id, "order": 2, "part": 1, "mode": "match"}).json()
    did, url = r["id"], f"/api/drill/{r['id']}"
    assert r["mode"] == "match" and r["stage"] == "facts" and r["sides"] == [{"name": "가", "lines": []}, {"name": "나", "lines": []}]

    def done(body):
        j = _wait(client, client.post(f"{url}/jobs", json=body).json()["id"])
        assert j["status"] == "done", j
        return j

    def err(body):
        res = client.post(f"{url}/jobs", json=body)
        assert res.status_code == 400, res.text
        return res.json()["detail"]

    done({"kind": "facts"})
    r = client.get(url).json()
    first = {**r["brief"], "avoid": "목소리 높이기", "manner": "짧은 존댓말"}
    assert r["stage"] == "brief" and r["brief"]["events"] and "둘째 쓰는 방식" in err({"kind": "match"})
    assert client.put(url, json={"brief": first, "rival": {"manner": "1\n2\n3\n4\n5\n6"}}).status_code == 400
    client.put(url, json={"brief": first, "rival": {"avoid": "목소리 높이기", "manner": "짧은 존댓말", "events": "버려질 줄"}})
    assert "두 쓰는 방식이 같아요" in err({"kind": "match"}) and drill.load(did).rival.events == ""  # 둘째는 쓰는 방식 칸만 남긴다
    client.put(url, json={"brief": first, "rival": {"manner": drill.load(did).source.split("\n")[0]}})
    assert "원문 문장" in err({"kind": "match"})
    r = client.put(url, json={"brief": first, "rival": {"change": "서연이 묻는 사람에서 따지는 사람으로", "manner": "길게 늘어지는 반말로"}}).json()
    assert [[x["box"] for x in s["lines"]] for s in r["sides"]] == [["avoid", "manner"], ["change", "manner"]]
    assert client.put(url, json={"brief": first}).json()["rival"]["manner"] == "길게 늘어지는 반말로"  # rival 없이 보내면 그대로 둔다
    assert "지시 적기 판이 아니에요" in err({"kind": "write"}) and "줄이기 판이 아니에요" in err({"kind": "shrink"})
    j = done({"kind": "match"})
    assert j["kind"] == "dr_match" and j["result"] == {"id": did, "no": 1}
    r = client.get(url).json()
    assert r["stage"] == "pick" and r["source"] == "" and r["attempts"][0]["with_text"] == "" and r["blind"]["left"] != r["blind"]["right"] and len(r["sides"][1]["lines"]) == 2
    client.put(url, json={"brief": first, "rival": {"manner": "쓴 뒤에 바꾼 줄"}})
    saved = drill.load(did)
    a = saved.attempts[0]
    assert saved.rival.manner == "길게 늘어지는 반말로" and a.with_text != a.old_text and a.brief.manner == "짧은 존댓말" and not a.verdicts and a.bare_text == ""
    assert "하나를 고르세요" in err({"kind": "review"}) and err({"kind": "revise"}) and err({"kind": "match"})
    wrong = "right" if a.flip else "left"  # 지시 나로 쓴 글이 있는 쪽
    r = client.post(f"{url}/pick", json={"side": wrong}).json()
    assert r["stage"] == "done" and r["attempts"][0]["pick"] == "old" and r["source"] and r["measures"]["1"]["old"]["chars"] > 0
    st = client.get("/api/drill").json()["stats"]
    assert "되짚지 않아요" in err({"kind": "review"})
    assert st["match"] == {"new": 0, "old": 1, "skip": 0} and st["shrink"] == {"new": 0, "old": 0, "skip": 0} and st["rounds"] == 0


def test_match_cards_differ_only_in_the_method(book):
    r = drill.create(book.id, order=1, part=2, mode="match")
    drill.set_facts(r, pipeline.drill_facts(L, r.source, r.lead), "mock")
    r.brief.manner, r.rival = "짧게 끊는다", DrillBrief(avoid="손대기", people="버려질 사람")
    first, second = drill.match_briefs(r, drill.clean_brief(r.brief))
    a, b = drill.card_of(r, first), drill.card_of(r, second)
    assert (a.people, a.pov, a.place, a.time, a.action) == (b.people, b.pov, b.place, b.time, b.action) and r.facts.events[0] in a.action
    assert a.extra == "방식: 짧게 끊는다" and b.extra == "하지 않는 것: 손대기"
    with pytest.raises(ValueError, match="거꾸로 맞히기 판이 아니에요"):
        drill.match_briefs(_round(book), DrillBrief())
    x = drill.add_match(r, first, "가의 글", "나의 글", rng=random.Random(3))
    side = "left" if x.flip else "right"
    assert drill.pick_side(r, side).pick == "new" and drill.stage(r) == "done"  # 지시 가의 글이 있는 쪽을 고르면 맞힘


# ---------- 직접 쓰기 (docs/drill/write.md 일감 8) ----------

def _leaks(needle: str, v) -> bool:
    """needle 이 응답 JSON 에 글자 그대로 들어 있나. json.dumps 가 줄바꿈 · 따옴표를 이스케이프하므로 needle 도 같은 꼴로 바꿔 찾는다."""
    return json.dumps(needle, ensure_ascii=False)[1:-1] in json.dumps(v, ensure_ascii=False)


def test_leak_helper_sees_escaped_text():
    assert _leaks('그가 말했다.\n"가자."', {"a": '그가 말했다.\n"가자."'}) and not _leaks('그가 말했다.\n"가자."', {"a": "다른 글"})
    assert '그가 말했다.\n"가자."' not in json.dumps({"a": '그가 말했다.\n"가자."'}, ensure_ascii=False)  # 이스케이프 때문에 날것으로는 못 찾는다


def _write_round(book, **kw) -> DrillRound:
    r = drill.create(book.id, order=1, part=2, mode="write", **kw)
    drill.set_facts(r, pipeline.drill_facts(L, r.source, r.lead), "mock")
    return drill.save(r)


def _own(r: DrillRound, n: int | None = None) -> str:
    """허용 범위 안의 작가 글 (공백을 뺀 글자 수 n)."""
    n = n or drill._chars(r.source)
    return ("서연은 문턱에서 한참 서 있다가 결국 안으로 들어갔다. " * 40).replace(" ", "")[:n]


def _submitted(book) -> DrillRound:
    r = _write_round(book)
    drill.add_own(r, r.brief, _own(r))
    return drill.save(r)


def test_write_passages_are_about_450_and_the_default_stays_900(book):
    text = _text(60, 1)
    short, long = drill.passages(text, drill.WRITE_PASSAGE, drill.WRITE_PASSAGE_MIN), drill.passages(text)
    assert len(short) > len(long) and all(drill.WRITE_PASSAGE_MIN <= len(p["text"]) <= drill.WRITE_PASSAGE + 200 for p in short)
    assert "".join(p["text"] for p in short).replace("\n", "") == text.replace("\n", "")
    assert drill._sizes("write") == (450, 225) and drill._sizes("") == (drill.PASSAGE, drill.PASSAGE_MIN) == (900, 450) and drill._sizes("shrink") == (900, 450)
    assert drill.passages(text) == drill.passages(text, 900, 450)
    eps, eps_w = drill.episodes(book.id), drill.episodes(book.id, "write")
    assert all(w["parts"] > e["parts"] for e, w in zip(eps, eps_w, strict=True))
    r = drill.create(book.id, order=1, part=1, mode="write")
    assert r.parts == eps_w[0]["parts"] and 300 < len(r.source) < 700
    assert drill.create(book.id, order=1, part=1).parts == eps[0]["parts"]
    with pytest.raises(KeyError):  # 지시 적기 판의 대목 수를 넘는 번호도 직접 쓰기 판에는 있다
        drill.pick(book.id, order=1, part=eps_w[0]["parts"] + 1, mode="write")
    assert drill.pick(book.id, order=1, part=eps[0]["parts"] + 1, mode="write")["part"] == eps[0]["parts"] + 1


def test_write_range_edges_can_be_submitted(book):
    r = _write_round(book)
    n = drill._chars(r.source)
    lo, hi = drill.write_range(r)
    assert (lo, hi) == (math.floor(n * 0.7), math.ceil(n * 1.3))
    b = drill.write_brief(r.brief)
    for k in (lo, hi):
        drill.can_submit(r, b, _own(r, k))  # 경계값은 낼 수 있다
    for k in (lo - 1, hi + 1):
        with pytest.raises(ValueError, match="공백을 빼고"):
            drill.can_submit(r, b, _own(r, k))
    spaced = " ".join(_own(r, lo))  # 공백은 세지 않는다
    drill.can_submit(r, b, spaced)
    with pytest.raises(ValueError, match="일어나는 일"):
        drill.can_submit(r, b.model_copy(update={"events": ""}), _own(r))
    with pytest.raises(ValueError, match="원문 문장"):
        drill.can_submit(r, b.model_copy(update={"before": r.source.split("\n")[0]}), _own(r))
    with pytest.raises(ValueError, match="직접 쓰기 판이 아니에요"):
        drill.can_submit(drill.create(book.id, order=1, part=1), b, _own(r))


def test_write_view_hides_source_and_ai_text_until_their_stage(book):
    r = _write_round(book)
    v = drill.view(r)
    assert v["stage"] == "writing" and v["source"] == "" and "lead" not in v and v["measures"] == {} and v["write_range"] == list(drill.write_range(r))
    assert v["source_chars"] == len(r.source) and v["base"]["events"] == r.brief.events and v["ai_ready"] is False
    assert not any(_leaks(x, v) for x in r.source.split("\n") if x.strip()) and not _leaks(r.source, v)
    own = _own(r)
    drill.add_own(r, r.brief, own)
    ai_text = 'AI가 쓴 글이다.\n"서연은 문을 밀었다."'
    drill.set_ai_text(r, ai_text, "mock")  # AI 판이 이미 쓰였어도
    v = drill.view(r)
    assert v["stage"] == "marking" and v["source"] == r.source and "lead" not in v and v["ai_ready"] is True
    assert set(v["measures"]) == {"own", "source"} and v["attempts"][0]["own_text"] == own and v["attempts"][0]["bare_text"] == ""
    assert not _leaks(ai_text, v) and not _leaks("서연은 문을 밀었다", v)  # 짚기를 저장하기 전에는 응답 어디에도 없다
    drill.set_marks(r, [])
    v = drill.view(r)
    assert v["stage"] == "compare" and _leaks(ai_text, v) and v["attempts"][0]["bare_text"] == ai_text and set(v["measures"]) == {"own", "source", "ai"}
    for m in v["measures"].values():
        assert {"chars", "sentences", "sentence_len_cv", "dialogue_pct", "body_per_1k", "emotion_per_1k"} <= set(m)
    assert v["measures"]["own"]["sentence_len_cv"] is None or isinstance(v["measures"]["own"]["sentence_len_cv"], float)
    for k in ("hints", "blind", "dense", "sides"):
        assert k not in v
    # AI 판이 아직 없으면 지표도 없다
    q = _submitted(book)
    drill.set_marks(q, [])
    v = drill.view(q)
    assert v["stage"] == "compare" and v["ai_ready"] is False and "ai" not in v["measures"]


def test_write_stage_walks_through_the_five_steps(book):
    r = drill.create(book.id, order=1, part=2, mode="write")
    assert drill.stage(r) == "facts"
    drill.set_facts(r, pipeline.drill_facts(L, r.source, r.lead), "mock")
    assert drill.stage(r) == "writing"
    drill.add_own(r, r.brief, _own(r))
    assert drill.stage(r) == "marking"
    drill.set_marks(r, [])
    assert drill.stage(r) == "compare"
    drill.finish(r, "")
    assert drill.stage(r) == "done"
    assert drill.summary(r)["stage"] == "done" and drill.summary(r)["results"] == {} and drill.summary(r)["pick"] == ""


def test_write_marks_need_quotes_found_in_the_texts(book):
    r = _submitted(book)
    own = r.attempts[0].own_text
    src_quote = r.source.split("\n")[0][:20]
    with pytest.raises(ValueError, match="한 줄 글"):
        drill.set_marks(r, [WriteMark(note="  ")])
    with pytest.raises(ValueError, match="원문 인용"):
        drill.set_marks(r, [WriteMark(note="원문은 말을 줄였다", source_quote="원문에 없는 문장이 여기 들어 있다")])
    with pytest.raises(ValueError, match="내 글 인용"):
        drill.set_marks(r, [WriteMark(note="내 글은 길다", own_quote="내 글에 없는 문장이 여기 들어 있다")])
    with pytest.raises(ValueError, match="5개까지"):
        drill.set_marks(r, [WriteMark(note=f"곳 {i}") for i in range(drill.WRITE_MARKS_MAX + 1)])
    assert r.attempts[0].marked_at == "" and r.attempts[0].marks == []  # 받지 않은 짚기는 남지 않는다
    a = drill.set_marks(r, [WriteMark(note=" 원문은  장면을 짧게 끝냈다 ", source_quote=src_quote, own_quote=own[:10]), WriteMark(note="그냥 다르다")])
    assert a.marked_at and [m.note for m in a.marks] == ["원문은 장면을 짧게 끝냈다", "그냥 다르다"] and a.marks[1].source_quote == ""
    with pytest.raises(ValueError, match="한 번만"):
        drill.set_marks(r, [])
    with pytest.raises(ValueError, match="먼저 글을"):
        drill.set_marks(_write_round(book), [])


def test_write_round_takes_one_attempt_only(book):
    r = _write_round(book)
    b = drill.write_brief(r.brief)
    drill.can_submit(r, b, _own(r))
    a = drill.add_own(r, DrillBrief(**{**r.brief.model_dump(), "manner": "짧게", "avoid": "손대기"}), _own(r))
    assert a.no == 1 and a.brief.manner == "" and a.brief.avoid == "" and a.own_at and a.bare_text == "" and a.with_text == ""
    with pytest.raises(ValueError, match="이미 글을 냈"):
        drill.can_submit(r, b, _own(r))
    with pytest.raises(ValueError, match="먼저 짚기"):
        drill.finish(r, "다음엔 대사를 줄인다")
    drill.set_marks(r, [])
    drill.finish(r, "  다음엔   대사를 줄인다 ")
    assert r.attempts[0].next_try == "다음엔 대사를 줄인다" and len(r.attempts) == 1
    with pytest.raises(ValueError, match="이미 끝낸"):
        drill.finish(r, "또")


def test_ai_write_request_has_no_source(book):
    """AI 판의 쓰기 요청에는 원문 대목과 앞부분이 들지 않는다 (가짜 LLM이 받은 프롬프트로 본다)."""
    r = _submitted(book)
    seen = []

    class Spy(mock.MockLLM):
        def json(self, system, prompt, schema, hint=None):
            seen.append(system + "\n" + prompt)
            return super().json(system, prompt, schema, hint)

    a = r.attempts[0]
    text = pipeline.draft_paragraph(Spy(), drill.card_of(r, a.brief, bare=True), 1)[0].text
    assert len(seen) == 1 and text and not refs.overlap(seen[0], [r.source, r.lead]) and a.own_text not in seen[0]
    assert "일어나는 일 (이 차례대로):\n1. " in seen[0] and "하지 않는 것" not in seen[0]


def test_write_rounds_stay_out_of_the_layer_stats(book):
    r = _submitted(book)
    drill.set_ai_text(r, "AI 판이다.", "mock")
    drill.set_marks(r, [])
    drill.finish(r, "대사를 줄인다")
    r.created_at = "2026-11-20T09:00:00"
    st = drill.stats([r, _judged(book, [("applied", False)])])
    assert st["rounds"] == 1 and st["lines"] == 1 and st["picks"] == {"new": 0, "old": 0, "skip": 0}
    assert st["shrink"] == {"new": 0, "old": 0, "skip": 0} and st["match"] == {"new": 0, "old": 0, "skip": 0}
    assert st["write"] == {"rounds": 1, "chars": drill._chars(r.attempts[0].own_text), "next_tries": ["대사를 줄인다"]}


def test_write_stats_count_done_rounds_chars_and_the_latest_five_tries(book):
    rs = []
    for i in range(7):
        r = _submitted(book)
        r.created_at = f"2026-11-1{i}T09:00:00"
        if i < 6:  # 여섯 판은 끝내고, 한 판은 짚기까지만
            drill.set_marks(r, [])
            drill.finish(r, "" if i == 2 else f"해 볼 것 {i}")
        rs.append(r)
    rs.append(drill.create(book.id, order=1, part=1, mode="write"))  # 글을 내지 않은 판은 세지 않는다
    st = drill.stats(rs)["write"]
    assert st["rounds"] == 6 and st["chars"] == 7 * drill._chars(rs[0].attempts[0].own_text)
    assert st["next_tries"] == ["해 볼 것 5", "해 볼 것 4", "해 볼 것 3", "해 볼 것 1", "해 볼 것 0"]  # 빈 것은 빼고 최근 다섯 개, 새것부터
    assert drill.stats([])["write"] == {"rounds": 0, "chars": 0, "next_tries": []}


def test_new_write_round_view_carries_the_last_next_try(book):
    first = _submitted(book)
    drill.set_marks(first, [])
    drill.finish(first, "대사 사이에 동작을 넣는다")
    drill.save(first)
    first.created_at = "2026-11-01T09:00:00"
    drill.save(first)
    second = _write_round(book)
    second.created_at = "2026-11-03T09:00:00"
    drill.save(second)
    assert drill.view(second)["next_try_prev"] == "대사 사이에 동작을 넣는다"
    assert drill.view(first)["next_try_prev"] == ""  # 자기 판은 뺀다
    older = _write_round(book)  # 이 판보다 나중에 만든 판의 것은 보이지 않는다
    older.created_at = "2026-10-01T09:00:00"
    assert drill.view(older)["next_try_prev"] == ""
    other = _submitted(book)
    drill.set_marks(other, [])
    drill.finish(other, "더 나중에 끝낸 판의 것")
    other.created_at = "2026-11-02T09:00:00"
    first.attempts[0].done_at, other.attempts[0].done_at = "2026-11-05T09:00:00", "2026-11-06T09:00:00"
    assert drill.last_next_try([first, other]) == "더 나중에 끝낸 판의 것"
    assert drill.last_next_try([first, other], exclude=other.id) == "대사 사이에 동작을 넣는다"
    assert drill.last_next_try([first, other], before="2026-11-02T00:00:00") == "대사 사이에 동작을 넣는다"  # 먼저 만든 판만
    assert drill.last_next_try([first, other], before="2026-11-01T00:00:00") == ""
    first.attempts[0].done_at = "2026-11-09T09:00:00"  # 만든 순서가 아니라 끝낸 순서로 가장 최근 것을 고른다
    assert drill.last_next_try([first, other]) == "대사 사이에 동작을 넣는다"
    assert drill.last_next_try([_write_round(book)]) == "" and drill.last_next_try([]) == ""


def test_old_round_file_without_mode_still_loads(book):
    r = drill.create(book.id, order=1, part=1)
    path = drill.root() / f"{r.id}.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    for k in ("mode", "rival"):
        d.pop(k, None)
    d["attempts"] = [{"no": 1, "brief": {}, "with_text": "글", "bare_text": "글", "at": "2026-11-01T09:00:00"}]
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    q = drill.load(r.id)
    a = q.attempts[0]
    assert q.mode == "" and a.own_text == "" and a.marks == [] and a.marked_at == "" and a.next_try == "" and a.done_at == ""
    assert drill.view(q)["stage"] == "written" and drill.summary(q)["mode"] == ""


def test_web_write_round_hides_the_ai_text_until_the_marks_are_saved(client, book):
    assert client.post("/api/drill", json={"ref_id": book.id, "mode": "write"}).status_code == 200
    eps = client.get(f"/api/drill/sources/{book.id}").json()["episodes"]
    eps_w = client.get(f"/api/drill/sources/{book.id}", params={"mode": "write"}).json()["episodes"]
    assert all(w["parts"] > e["parts"] for e, w in zip(eps, eps_w, strict=True))
    r = client.post("/api/drill", json={"ref_id": book.id, "order": 2, "part": 2, "mode": "write"}).json()
    did, url = r["id"], f"/api/drill/{r['id']}"
    assert r["mode"] == "write" and r["stage"] == "facts" and r["source"] == "" and r["next_try_prev"] == ""
    for k in ("review", "write", "revise", "shrink", "match", "ai_write"):  # 직접 쓰기 판이 받지 않는 작업
        assert client.post(f"{url}/jobs", json={"kind": k}).status_code == 400, k
    j = _wait(client, client.post(f"{url}/jobs", json={"kind": "facts"}).json()["id"])
    assert j["status"] == "done" and j["result"]["events"] == 4
    r = client.get(url).json()
    assert r["stage"] == "writing" and r["source"] == "" and r["brief"]["events"] and r["brief"]["manner"] == ""
    assert not _leaks(drill.load(did).source, r) and not any(_leaks(x, r) for x in drill.load(did).source.split("\n") if x.strip())
    put = client.put(url, json={"brief": {**r["brief"], "change": "바뀐다", "avoid": "손대기", "manner": "짧게"}}).json()  # 쓰는 방식 칸은 받지 않는다
    assert (put["brief"]["change"], put["brief"]["avoid"], put["brief"]["manner"]) == ("", "", "") and put["brief"]["events"] == r["brief"]["events"]
    lo, hi = r["write_range"]
    short = {"brief": put["brief"], "text": "가" * (lo - 1)}
    assert client.post(f"{url}/submit", json=short).status_code == 400
    assert client.post(f"{url}/marks", json={"marks": []}).status_code == 400 and client.post(f"{url}/finish", json={}).status_code == 400
    own = _own(drill.load(did))
    sub = client.post(f"{url}/submit", json={"brief": {**put["brief"], "manner": "짧게"}, "text": own})
    assert sub.status_code == 200, sub.text
    body = sub.json()
    assert not _leaks(drill.load(did).attempts[0].bare_text or "없는 글", body)
    assert body["stage"] == "marking" and body["source"] and body["attempts"][0]["own_text"] == own and body["attempts"][0]["bare_text"] == ""
    assert body["job"]["kind"] == "dr_ai_write" and body["job"]["target"] == did and body["job"]["label"].endswith("AI 판 쓰기")
    assert body["attempts"][0]["brief"]["manner"] == ""
    assert client.post(f"{url}/submit", json={"brief": put["brief"], "text": own}).status_code == 400  # 한 판에 시도 하나
    j = _wait(client, body["job"]["id"])
    assert j["status"] == "done", j
    ai = drill.load(did).attempts[0].bare_text
    assert ai and ai != own
    r = client.get(url).json()  # AI 판은 이미 쓰였지만 짚기를 저장하기 전에는 응답에 없다
    assert r["stage"] == "marking" and r["ai_ready"] is True and not _leaks(ai, r)
    assert client.post(f"{url}/jobs", json={"kind": "ai_write"}).status_code == 400  # 이미 쓴 AI 판은 다시 쓰지 않는다
    assert client.post(f"{url}/finish", json={}).status_code == 400  # 짚기 전에는 끝내지 못한다
    bad = client.post(f"{url}/marks", json={"marks": [{"note": "다르다", "source_quote": "원문에 없는 인용이 들어 있다"}]})
    assert bad.status_code == 400 and not _leaks(ai, client.get(url).json())
    mk = client.post(f"{url}/marks", json={"marks": [{"note": "원문은 장면을 짧게 끝냈다", "own_quote": own[:12]}]})
    assert mk.status_code == 200 and mk.json()["stage"] == "compare"
    r = mk.json()
    assert _leaks(ai, r) and r["attempts"][0]["bare_text"] == ai and r["measures"]["ai"]["chars"] > 0 and len(r["attempts"][0]["marks"]) == 1
    assert client.post(f"{url}/marks", json={"marks": []}).status_code == 400
    fin = client.post(f"{url}/finish", json={"next_try": "대사 사이에 동작을 넣는다"})
    assert fin.status_code == 200 and fin.json()["stage"] == "done" and fin.json()["attempts"][0]["next_try"] == "대사 사이에 동작을 넣는다"
    assert client.post(f"{url}/finish", json={}).status_code == 400
    home = client.get("/api/drill").json()
    mine = next(x for x in home["rounds"] if x["id"] == did)  # 맨 앞의 판은 같은 초에 만든 다른 판일 수 있다
    assert mine["mode"] == "write" and mine["stage"] == "done" and home["modes"]["write"] == "직접 쓰기"
    assert home["stats"]["write"] == {"rounds": 1, "chars": drill._chars(own), "next_tries": ["대사 사이에 동작을 넣는다"]} and home["stats"]["rounds"] == 0
    drill.update(did, lambda q: setattr(q, "created_at", "2026-11-01T09:00:00"))  # 같은 초에 만든 판은 앞 판으로 보지 않는다
    nxt = client.post("/api/drill", json={"ref_id": book.id, "order": 1, "part": 1, "mode": "write"}).json()
    assert nxt["next_try_prev"] == "대사 사이에 동작을 넣는다"


def test_web_ai_write_can_be_retried_and_keeps_the_marks(client, book, monkeypatch):
    r = client.post("/api/drill", json={"ref_id": book.id, "order": 1, "part": 2, "mode": "write"}).json()
    did, url = r["id"], f"/api/drill/{r['id']}"
    _wait(client, client.post(f"{url}/jobs", json={"kind": "facts"}).json()["id"])
    brief = client.get(url).json()["brief"]
    own = _own(drill.load(did))
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("쓰기 실패")

    real = pipeline.draft_paragraph
    monkeypatch.setattr(pipeline, "draft_paragraph", boom)
    body = client.post(f"{url}/submit", json={"brief": brief, "text": own}).json()
    assert _wait(client, body["job"]["id"])["status"] == "error" and calls
    assert drill.load(did).attempts[0].own_text == own and drill.load(did).attempts[0].bare_text == ""  # 글은 남았다

    def slow_save(llm, card, n):  # 짚기를 저장한 뒤에 AI 판이 끝나도 짚기를 덮지 않는다
        out = real(llm, card, n)
        assert client.post(f"{url}/marks", json={"marks": [{"note": "다르다"}]}).status_code == 200
        return out

    monkeypatch.setattr(pipeline, "draft_paragraph", slow_save)
    j = _wait(client, client.post(f"{url}/jobs", json={"kind": "ai_write"}).json()["id"])
    assert j["status"] == "done", j
    a = drill.load(did).attempts[0]
    assert a.bare_text and [m.note for m in a.marks] == ["다르다"] and a.marked_at


def test_update_runs_one_writer_at_a_time_and_both_orderings_keep_both_results(book):
    import threading
    import time

    # 순서 1: 짚기를 저장하는 사이 AI 판 작업이 저장한다 -> 짚기가 남는다
    r = _submitted(book)
    did = r.id
    started, go = threading.Event(), threading.Event()

    def slow_marks(q):
        started.set()
        go.wait(2)
        drill.set_marks(q, [WriteMark(note="다르다")])

    t = threading.Thread(target=lambda: drill.update(did, slow_marks))
    t.start()
    assert started.wait(2)
    done = []
    u = threading.Thread(target=lambda: done.append(drill.update(did, lambda q: drill.set_ai_text(q, "AI 판이다.", "mock"))))
    u.start()
    time.sleep(0.1)
    assert not done  # 앞 update 가 끝나기를 기다린다
    go.set()
    t.join(2)
    u.join(2)
    a = drill.load(did).attempts[0]
    assert a.marked_at and [m.note for m in a.marks] == ["다르다"] and a.bare_text == "AI 판이다."

    # 순서 2: AI 판이 먼저 저장되고 그 뒤에 (먼저 읽은) 짚기 저장이 온다 -> AI 판이 남는다
    q = _submitted(book)
    started, go = threading.Event(), threading.Event()

    def slow_ai(x):
        started.set()
        go.wait(2)
        drill.set_ai_text(x, "AI 판이다.", "mock")

    t = threading.Thread(target=lambda: drill.update(q.id, slow_ai))
    t.start()
    assert started.wait(2)
    u = threading.Thread(target=lambda: drill.update(q.id, lambda x: drill.set_marks(x, [])))
    u.start()
    time.sleep(0.1)
    go.set()
    t.join(2)
    u.join(2)
    b = drill.load(q.id).attempts[0]
    assert b.bare_text == "AI 판이다." and b.marked_at
    with pytest.raises(ValueError):  # fn 이 막으면 저장하지 않는다
        drill.update(q.id, lambda x: (setattr(x, "title", "바뀜"), drill.set_marks(x, [])))
    assert drill.load(q.id).title != "바뀜"


def test_write_round_facts_are_locked_after_the_text_is_submitted(client, book):
    r = client.post("/api/drill", json={"ref_id": book.id, "order": 1, "part": 2, "mode": "write"}).json()
    did, url = r["id"], f"/api/drill/{r['id']}"
    brief0 = {"events": "서연이 들어온다"}
    own = _own(drill.load(did))
    assert "먼저 사실을 뽑으세요" in client.post(f"{url}/submit", json={"brief": brief0, "text": own}).json()["detail"]  # 사실을 뽑기 전에는 못 낸다
    _wait(client, client.post(f"{url}/jobs", json={"kind": "facts"}).json()["id"])
    brief = client.get(url).json()["brief"]
    assert client.post(f"{url}/submit", json={"brief": brief, "text": own}).status_code == 200
    for res in (client.put(url, json={"brief": brief}), client.post(f"{url}/jobs", json={"kind": "facts"})):
        assert res.status_code == 400 and "글을 낸 뒤에는 사실을 고칠 수 없어요" in res.json()["detail"]
    assert drill.load(did).brief.events == brief["events"]


def test_write_marks_validation_messages(client, book):
    r = _submitted(book)
    url = f"/api/drill/{r.id}"
    res = client.post(f"{url}/marks", json={"marks": [{}]})  # 빈 한 줄 글은 422 가 아니라 한국어 400 이다
    assert res.status_code == 400 and "한 줄 글" in res.json()["detail"]
    res = client.post(f"{url}/marks", json={"marks": [{"note": "다르다", "source_quote": "짧음"}]})
    assert res.status_code == 400 and f"{drill.QUOTE_MIN}자 이상" in res.json()["detail"] and "공백과 문장부호를 빼고" in res.json()["detail"]
    res = client.post(f"{url}/marks", json={"marks": [{"note": "다르다", "own_quote": "! ? 가 . ."}]})  # 문장부호 · 공백을 빼면 짧다
    assert res.status_code == 400 and "이상이에요" in res.json()["detail"]
    assert drill.load(r.id).attempts[0].marked_at == "" and client.get(url).json()["quote_min"] == drill.QUOTE_MIN


def test_web_ai_write_prompt_has_no_source(client, book, monkeypatch):
    r = client.post("/api/drill", json={"ref_id": book.id, "order": 2, "part": 2, "mode": "write"}).json()
    did, url = r["id"], f"/api/drill/{r['id']}"
    _wait(client, client.post(f"{url}/jobs", json={"kind": "facts"}).json()["id"])
    brief = client.get(url).json()["brief"]
    own = _own(drill.load(did))
    seen = []
    real = pipeline.draft_paragraph

    def spy(llm, card, n=3):
        p = studio.world(card)
        seen.append(prompts.paragraph_system(p) + "\n" + prompts.paragraph_prompt(p, card, n, [k for k in card.drills if k in studio.DRILLS]))
        return real(llm, card, n)

    monkeypatch.setattr(pipeline, "draft_paragraph", spy)
    sub = client.post(f"{url}/submit", json={"brief": brief, "text": own}).json()
    assert _wait(client, sub["job"]["id"])["status"] == "done"
    q = drill.load(did)
    assert len(seen) == 1 and not refs.overlap(seen[0], [q.source, q.lead]) and own not in seen[0]
    assert not any(x in seen[0] for x in q.source.split("\n") if len(x.strip()) > 8)
    assert "일어나는 일 (이 차례대로):" in seen[0] and q.attempts[0].bare_text
