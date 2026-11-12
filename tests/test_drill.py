"""지시 연습 (canon/drill.py, docs/drill) 시험 (mock LLM). 실행: python -m pytest tests/test_drill.py"""
import random

import pytest

from canon import drill, mock, pipeline, prompts, refdigest, refs, store, studio
from canon.schema import DrillBrief, DrillFacts, DrillGap, DrillInvented, DrillLineVerdict, DrillPerson, DrillReview, DrillRound, RefCut

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
    j = done({"kind": "write"})
    assert j["result"] == {"id": did, "no": 1, "reviewed": True} and j["kind"] == "dr_write"
    r = client.get(url).json()
    a = r["attempts"][0]
    assert r["stage"] == "reviewed" and r["source"] and a["with_text"] != a["bare_text"] and a["with_text"].endswith("목소리는 끝까지 낮았다.")
    assert [v["result"] for v in a["verdicts"]] == ["applied", "unsure", "ignored"] and a["verdicts"][0]["quote"] and a["verdicts"][0]["layer"] == "change"
    assert len(a["invented"]) == 1 and len(a["gaps"]) == 1 and a["dropped"] == 3
    assert client.post(f"{url}/jobs", json={"kind": "write"}).status_code == 400  # 한 판은 한 번 쓴다
    assert done({"kind": "review"})["result"]["reviewed"] is True
    assert client.get("/api/drill").json()["rounds"][0]["results"]["applied"] == 1
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
