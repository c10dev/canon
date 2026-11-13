"""지시 연습 (canon/drill.py, docs/drill) 시험 (mock LLM). 실행: python -m pytest tests/test_drill.py"""
import random

import pytest

from canon import drill, mock, pipeline, prompts, refdigest, refs, store, studio
from canon.schema import DrillBrief, DrillFacts, DrillGap, DrillInvented, DrillLineVerdict, DrillPerson, DrillReview, DrillRound, DrillVerdict, RefCut

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
    assert drill.stats([]) == {"rounds": 0, "lines": 0, "worked": None, "picks": {"new": 0, "old": 0, "skip": 0}, "shrink": {"new": 0, "old": 0, "skip": 0}, "recent_n": 5, "recent": None, "before": None, "trend": [],
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
