"""문단 연습장 (canon/studio.py, mock LLM). 실행: python -m pytest tests/test_studio.py"""
import importlib

import pytest
from fastapi.testclient import TestClient

from canon import pipeline, prompts, studio
from canon.mock import MockLLM
from canon.schema import Project, SceneCard, StudioCandidate, StudioPerson, StyleMarker, StyleProfile


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_STUDIO", str(tmp_path / "studio"))
    monkeypatch.setenv("CANON_STYLES", str(tmp_path / "styles"))
    return tmp_path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("CANON_STYLES", raising=False)
    monkeypatch.delenv("CANON_STUDIO", raising=False)
    from canon import library, store, web

    importlib.reload(store)
    importlib.reload(library)
    importlib.reload(web)
    return TestClient(web.app)


def card(**kw) -> SceneCard:
    base = {"people": [StudioPerson(name="서연", speech="짧은 반말")], "action": "우산을 건넨다"}
    return SceneCard(**{**base, **kw})


def test_clean_card(home):
    c = studio.clean_card(SceneCard(people=[StudioPerson(name=" 서연 "), StudioPerson()], action=" 비 ", drills=["show", "show", "없는 연습"],
                                    length=5, source="가" * (studio.TEXT_MAX + 10)))
    assert [x.name for x in c.people] == ["서연"] and c.action == "비"
    assert c.drills == ["show"] and c.length == studio.LENGTH[0] and len(c.source) == studio.TEXT_MAX
    assert studio.clean_card(SceneCard(length=99999)).length == studio.LENGTH[1]
    with pytest.raises(ValueError, match="문체 라이브러리"):
        studio.clean_card(SceneCard(style_id="abcdef12"))


def test_measure_counts_and_drills(home):
    c = card(drills=["show", "no_dialogue", "senses", "less_ai"], length=200)
    m = studio.measure("서연은 불안을 느꼈다. 숨을 내쉬었다. \"가.\"", c)
    checks = {x["id"]: x for x in m["checks"]}
    assert checks["length"]["ok"] is False and "목표 200자" in checks["length"]["why"]
    assert checks["show"]["ok"] is False and "불안" in checks["show"]["why"]
    assert checks["no_dialogue"]["ok"] is False
    assert checks["senses"]["ok"] is None  # 지표로 잴 수 없는 연습은 작가가 판단한다
    assert checks["less_ai"]["ok"] is False
    assert {h["quote"] for h in m["hits"]} >= {"불안을 느꼈다", "숨을 내쉬었다"}
    assert m["sentence_len_cv"] is None  # 문장이 적으면 변화폭을 재지 않는다

    ok = studio.measure("빗물이 처마 끝에서 떨어졌다. 서연은 젖은 소매를 비틀어 짰다.", card(drills=["show", "three"]))
    got = {x["id"]: x["ok"] for x in ok["checks"]}
    assert got == {"show": True, "three": True}  # 세 문장 연습이면 길이 확인을 빼고
    # 감정 이름은 대사 안에서는 세지 않는다
    assert studio.measure("\"불안해?\" 서연이 물었다.", card(drills=["show"]))["checks"][1]["ok"] is True


def test_measure_style_markers_and_banned(home):
    st = StyleProfile(banned_phrases=["우산을 건넸다"], markers=[StyleMarker(text="것이었다", per_1k=2)])
    m = studio.measure("서연은 우산을 건넸다. 그것은 오래된 것이었다.", card(), st)
    assert any(h["kind"] == "cliche" and h["quote"] == "우산을 건넸다" for h in m["hits"])
    assert m["markers"] == [{"text": "것이었다", "count": 1}]


def test_session_crud_and_tries(home):
    s = studio.create(card(), "")
    assert s.title == "우산을 건넨다" and studio.load(s.id).card.action == "우산을 건넨다"
    studio.add_ai(s, [StudioCandidate(text="가", note="첫"), StudioCandidate(text="나")], "m")
    t = studio.add_author(s, "가를 고쳤다", base=1)
    assert (t.no, t.by, t.base) == (3, "author", 1)
    with pytest.raises(ValueError, match="고친 곳"):
        studio.add_author(s, " 가 ", base=1)
    with pytest.raises(ValueError, match="AI 안은 고치지"):
        studio.edit(s, 1, text="다")
    studio.edit(s, 3, text="새 글", star=True)
    studio.edit(s, 1, star=True)
    studio.remove(s, 1)
    assert [x.no for x in s.tries] == [2, 3] and s.tries[1].base == 0  # 지운 시도를 고쳐 쓴 글은 처음부터 쓴 글이 된다
    assert studio.add_author(s, "또").no == 4  # 번호는 다시 쓰지 않는다
    studio.save(s)
    v = studio.view(studio.load(s.id))
    assert set(v["measures"]) == {"2", "3", "4"} and v["style_name"] == ""
    # 카드로 지은 제목은 카드를 따라가고, 작가가 적은 제목은 남는다
    e = studio.create(SceneCard())
    assert e.title == "새 연습"
    assert studio.update(e.id, card(), e.title).title == "우산을 건넨다"
    assert studio.update(e.id, card(action="비"), "우산을 건넨다").title == "비"
    assert studio.update(e.id, card(action="눈"), "내 제목").title == "내 제목"
    assert studio.update(e.id, card(action="해"), "내 제목").title == "내 제목"
    studio.delete(e.id)
    d = studio.duplicate(s.id)
    assert d.tries == [] and d.card == s.card and d.title.endswith("사본")
    assert {x.id for x in studio.sessions()} == {s.id, d.id}
    studio.delete(s.id)
    with pytest.raises(KeyError):
        studio.load(s.id)
    with pytest.raises(KeyError):
        studio.load("../x")


def test_room(home):
    s = studio.create(card())
    studio.add_ai(s, [StudioCandidate(text=str(i)) for i in range(studio.MAX_TRIES)])
    with pytest.raises(ValueError, match="지울 시도"):
        studio.add_author(s, "하나 더")


def test_draft_paragraph_cleans(home):
    c = studio.clean_card(card(drills=["show"]))
    out = pipeline.draft_paragraph(MockLLM(), c, 3)
    assert len(out) == 3 and len({x.text for x in out}) == 3 and all(x.text.strip() for x in out)
    out = pipeline.draft_paragraph(MockLLM(), c, 4)
    assert len(out) == 4 and all("**" not in x.text for x in out)
    with pytest.raises(ValueError, match="무슨 일"):
        pipeline.draft_paragraph(MockLLM(), SceneCard(), 3)


def test_paragraph_prompt(home):
    c = studio.clean_card(card(drills=["show", "rhythm"], aim="미안함", length=300, extra="마지막은 대사로"))
    text = prompts.paragraph_prompt(Project(), c, 3, [studio.DRILLS[k].rule for k in c.drills])
    assert "고른 문체가 없습니다" in text and "# 스타일 프로필" not in text
    assert "서연 / 말투: 짧은 반말" in text and "독자에게 남길 것: 미안함" in text and "장소: 빈칸" in text
    assert studio.DRILLS["show"].rule in text and "마지막은 대사로" in text and "약 300자" in text and "안 3개" in text
    st = StyleProfile(dos=["짧게 끊는다"], markers=[StyleMarker(text="것이었다", per_1k=5)])
    text = prompts.paragraph_prompt(Project(style=st), c, 2, [])
    assert "짧게 끊는다" in text and "이 문단에 2번 안팎" in text and "한 화에" not in text
    assert text.index("# 스타일 프로필") < text.index("# 상황")  # 문체가 같으면 앞부분이 같다 (캐시)
    assert "[문체 기본 규칙]" in prompts.paragraph_system(Project())


def test_style_block_keeps_static_context():
    p = Project(style=StyleProfile(dos=["a"], sample_passages=["예시 문단"]))
    ctx = prompts.static_context(p)
    assert prompts.style_block(p) in ctx and ctx.index("# 문체 예시") < ctx.index("# 스타일 프로필")


def test_web_flow(client, tmp_path):
    home = client.get("/api/studio").json()
    assert home["sessions"] == [] and {d["id"] for d in home["drills"]} == set(studio.DRILLS)
    assert client.get("/api/studio/abcdef123456").status_code == 404
    lib = client.post("/api/styles", json={"name": "건조체", "profile": {"dos": ["짧게"]}}).json()
    s = client.post("/api/studio", json={"card": {"action": "우산을 건넨다", "people": [{"name": "서연"}], "style_id": lib["id"]}}).json()
    assert (tmp_path / ".studio" / f"{s['id']}.json").exists() and s["style_name"] == "건조체"
    assert client.post("/api/studio", json={"card": {"style_id": "abcdef12"}}).status_code == 400

    s = client.post(f"/api/studio/{s['id']}/draft", json={"n": 2}).json()
    assert [t["by"] for t in s["tries"]] == ["ai", "ai"] and s["tries"][0]["note"]
    assert s["measures"]["1"]["checks"][0]["id"] == "length"
    s = client.post(f"/api/studio/{s['id']}/tries", json={"text": "서연은 우산을 내밀었다.", "base": 1}).json()
    assert s["tries"][-1]["base"] == 1
    assert client.put(f"/api/studio/{s['id']}/tries/1", json={"text": "x"}).status_code == 400
    s = client.put(f"/api/studio/{s['id']}/tries/1", json={"star": True}).json()
    assert s["tries"][0]["star"] is True
    s = client.put(f"/api/studio/{s['id']}", json={"title": "", "card": {**s["card"], "drills": ["three"]}}).json()
    assert s["title"] == "우산을 건넨다" and s["card"]["drills"] == ["three"]
    s = client.delete(f"/api/studio/{s['id']}/tries/3").json()
    assert len(s["tries"]) == 2
    d = client.post(f"/api/studio/{s['id']}/duplicate").json()
    assert d["tries"] == [] and len(client.get("/api/studio").json()["sessions"]) == 2
    assert client.delete(f"/api/studio/{d['id']}").json() == {"ok": True}
    empty = client.post("/api/studio", json={"card": {}}).json()
    assert client.post(f"/api/studio/{empty['id']}/draft", json={}).status_code == 400
    # 작품 목록에는 섞이지 않는다
    assert client.get("/api/projects").json() == []


MODEL = "서연은 버스 맨 뒷자리에 앉아 있었다. 차가 덜컹이자 우산 끝이 바닥을 긁었다. 젖은 손잡이에 빗물이 맺혀 있었다. 쥐면 손바닥까지 차가워질 것 같았다. 서연은 주먹을 쥐었다 폈다."


def test_clean_card_structure(home):
    c = studio.clean_card(card(beats=["setup", "없는 박자", "focus"] + ["cut"] * 20, withhold=" 속마음 ", sense=" 보는 것 → 촉감 ", show_model=True))
    assert c.beats[:2] == ["setup", "focus"] and len(c.beats) == studio.BEATS_MAX
    assert c.withhold == "속마음" and c.sense == "보는 것 → 촉감" and c.show_model is False  # 본보기가 없으면 보이지 않는다
    assert studio.clean_card(card(model=MODEL, show_model=True)).show_model is True
    assert {b["id"] for b in studio.beats()} == set(studio.BEATS)


def test_imagine_drill_and_copied(home):
    c = card(drills=["imagine"], model=MODEL)
    ok = {x["id"]: x for x in studio.measure("빗물이 맺혀 있었다. 쥐면 차가울 것 같았다.", c)["checks"]}["imagine"]
    assert ok["ok"] is True and "것 같" in ok["why"]
    no = {x["id"]: x for x in studio.measure("빗물이 맺혀 있었다. \"차가울 것 같아.\"", c)["checks"]}["imagine"]
    assert no["ok"] is False  # 대사 안의 가정은 세지 않는다
    m = studio.measure("창밖이 어두웠다. 젖은 손잡이에 빗물이 맺혀 있었다.", c)
    assert m["copied"] == ["젖은 손잡이에 빗물이 맺혀 있었다."]
    assert studio.measure(MODEL, c)["copied"] == []  # 본보기 자신은 재지 않는다
    assert studio.measure("다른 글.", card())["copied"] == []


def test_structure_prompt(home):
    c = studio.clean_card(card(beats=["setup", "imagine", "react"], withhold="속마음", sense="보는 것 → 촉감", model=MODEL))
    text = prompts.paragraph_prompt(Project(), c, 2, [])
    assert "1. 깔기:" in text and "2. 가정:" in text and "# 가릴 것" in text and "속마음" in text and "보는 것 → 촉감" in text
    assert "구조의 문장 차례는 지키고" in text and MODEL not in text  # 본보기는 보이기를 켜야 넣는다
    c.show_model = True
    text = prompts.paragraph_prompt(Project(), c, 2, [])
    assert MODEL in text and "옮기지 않습니다" in text and text.index("# 구조") < text.index("# 본보기 문단") < text.index("# 할 일")
    assert prompts.structure_block(SceneCard()) == ""


def test_anatomy_clean_and_apply(home):
    s = studio.create(card(model=MODEL))
    a = pipeline.anatomize_paragraph(MockLLM(), s.card)
    studio.set_anatomy(s, a)
    assert len(s.anatomy.lines) == 5 and all(x.quote in MODEL for x in s.anatomy.lines)  # 지어낸 문장은 빠진다
    assert s.anatomy.withhold == "인물의 속마음" and studio.view(s)["anatomy_stale"] is False
    studio.apply_anatomy(s)
    assert s.card.beats == ["setup", "trigger", "focus", "imagine", "react"] and s.card.sense == "보는 것 → 촉감"
    s.card.model = MODEL + " 버스가 섰다."
    assert studio.view(s)["anatomy_stale"] is True
    from canon.schema import AnatomyLine, ParagraphAnatomy
    with pytest.raises(ValueError, match="본보기에 없는"):
        studio.clean_anatomy(ParagraphAnatomy(lines=[AnatomyLine(quote="없는 문장", beat="cut", note="")], withhold="", sense="", reader=""), MODEL)
    with pytest.raises(ValueError, match="본보기 문단이 없어요"):
        pipeline.anatomize_paragraph(MockLLM(), SceneCard())
    with pytest.raises(ValueError, match="뜯어보세요"):
        studio.apply_anatomy(studio.create(card()))


def test_variants_make_new_session(home):
    s = studio.create(card(beats=["setup", "focus"], withhold="속마음", model=MODEL, place="정류장", drills=["show"], source="옛 글"))
    vs = pipeline.vary_scene(MockLLM(), s.card, 3)
    assert len(vs) == 3 and vs[0].pov == "" and vs[1].pov == "인물2"  # 인물 목록에 없는 시점은 비운다
    assert all(v.action and v.people and all(p.name.strip() for p in v.people) for v in vs)
    s.variants = vs
    studio.save(s)
    n = studio.from_variant(s.id, 1)
    assert n.id != s.id and n.card.action == vs[1].action and n.card.place == vs[1].place and [p.name for p in n.card.people] == ["인물2"]
    assert n.card.beats == ["setup", "focus"] and n.card.withhold == "속마음" and n.card.drills == ["show"] and n.card.model == MODEL
    assert n.card.source == "" and n.tries == [] and studio.load(s.id).card.place == "정류장"
    with pytest.raises(KeyError):
        studio.from_variant(s.id, 9)
    with pytest.raises(ValueError, match="문장 차례"):
        pipeline.vary_scene(MockLLM(), SceneCard(), 3)


def test_reader_check_and_edit_clears(home):
    s = studio.create(card())
    t = studio.add_author(s, "서연은 우산을 접었다. 빗소리가 멀어졌다.")
    studio.set_reader(s, t.no, pipeline.reader_check(MockLLM(), t.text))
    g = t.reader.gaps
    assert [x.imagined for x in g] == ["장소의 분위기", "인물의 표정", "다음에 일어날 일"]
    assert g[0].written and g[0].quote == t.text[:8].strip() and g[1].quote == "" and g[2].quote == ""  # 본문에 없는 인용 · 독자 몫의 인용은 비운다
    studio.edit(s, t.no, star=True)
    assert t.reader is not None
    studio.edit(s, t.no, text="서연은 우산을 폈다.")
    assert t.reader is None


def test_web_structure_flow(client):
    s = client.post("/api/studio", json={"card": {"action": "우산을 건넨다", "model": MODEL}}).json()
    assert {b["id"] for b in client.get("/api/studio").json()["beats"]} == set(studio.BEATS)
    s = client.post(f"/api/studio/{s['id']}/anatomy").json()
    assert len(s["anatomy"]["lines"]) == 5 and s["card"]["beats"] == []  # 적용은 따로
    s = client.post(f"/api/studio/{s['id']}/anatomy/apply").json()
    assert s["card"]["beats"][0] == "setup"
    s = client.post(f"/api/studio/{s['id']}/variants", json={"k": 2}).json()
    assert len(s["variants"]) == 2
    n = client.post(f"/api/studio/{s['id']}/variants/0").json()
    assert n["id"] != s["id"] and n["card"]["beats"] == s["card"]["beats"] and n["anatomy"]
    assert client.post(f"/api/studio/{s['id']}/variants/7").status_code == 404
    s = client.post(f"/api/studio/{s['id']}/draft", json={"n": 1}).json()
    s = client.post(f"/api/studio/{s['id']}/tries/1/reader").json()
    assert len(s["tries"][0]["reader"]["gaps"]) == 3
    assert client.post(f"/api/studio/{s['id']}/tries/9/reader").status_code == 404
    e = client.post("/api/studio", json={"card": {}}).json()
    assert client.post(f"/api/studio/{e['id']}/anatomy").status_code == 400
