"""삽화 프롬프트 테스트 (mock LLM): 태그 정리, 조립 규칙, 외형 태그 고정, 웹 흐름. 실행: python -m pytest tests"""
from canon import illust, prompts
from canon.schema import Character, CharacterVisual, IllustCharacter, IllustDraft, Illustration, Meta, Project

from .test_passage import TEXT, _written


def test_clean_tags():
    assert illust.clean(["Black_hair, long hair", "long hair", "2girls", "rating:explicit", "girl", "검은 머리", "fluorescent照明", "1.2::rain ::", "^_^"]) == [
        "black hair", "long hair", "1.2::rain ::", "^_^"]


def test_counts_and_subject():
    assert illust.counts([]) == ["no humans"]
    assert illust.counts(["girl", "boy", "girl", "other"]) == ["2girls", "1boy", "1other"]
    p = Project(characters=[Character(id="a", name="가", role="", gender="여성"), Character(id="b", name="나", role="", gender="")],
                visuals=[CharacterVisual(character_id="b", subject="boy")])
    assert (illust.subject_of(p, "a"), illust.subject_of(p, "b"), illust.subject_of(p, "x")) == ("girl", "boy", "other")


def _ill(p, **kw):
    d = IllustDraft(quote="q", scene="s", characters=[
        IllustCharacter(id="a", subject="girl", look=["red hair"], expression=["smile"], action=["source#hug"], position="left"),
        IllustCharacter(id="b", subject="boy", outfit=["pajamas"], action=["target#hug"], position="right"),
    ], setting=["indoors"], lighting=["dim lighting"], composition=["upper body"], caption="Two people hug.", negative=["hat"], **kw)
    return Illustration(id="i1", draft=d)


def test_assemble_multi_character_uses_saved_look():
    p = Project(characters=[Character(id="a", name="가", role="", gender="여"), Character(id="b", name="나", role="", gender="남")],
                visuals=[CharacterVisual(character_id="b", look=["black hair", "glasses"], outfit=["suit"], negative=["long hair"])])
    p.illust.style = ["watercolor"]
    ill = illust.assemble(p, _ill(p), "v4.5-full")
    assert ill.base == "1girl, 1boy, watercolor, indoors, upper body, dim lighting, rating:general"  # V4.5 는 영어 문장을 넣지 않는다
    a, b = ill.characters
    assert a.prompt == "girl, red hair, smile, source#hug" and a.position == "왼쪽"
    assert b.prompt == "boy, black hair, glasses, pajamas, target#hug"  # 장면 옷이 기본 옷차림을 대신한다
    assert b.negative == "long hair"
    assert ill.missing_look == ["a"]  # 외형 태그가 없어 AI 태그를 썼다
    assert ill.negative == "nsfw, hat"
    assert ill.combined == " | ".join([ill.base, a.prompt, b.prompt])

    p.illust.quality = True
    ill = illust.assemble(p, ill, "v5-full")
    assert ill.base.endswith("Two people hug, rating:general, very aesthetic, masterpiece, no text")

    ill = illust.assemble(p, ill, "v3")  # 인물 칸이 없는 모델은 한 줄로
    assert not ill.characters and ill.base.startswith("1girl, 1boy, red hair, smile, source#hug, black hair")
    assert "long hair" in ill.negative and ill.notes


def test_rating_follows_adult_flag():
    p = Project(characters=[Character(id="a", name="가", role="", gender="여")])
    ill = illust.assemble(p, _ill(p, rating="explicit"))
    assert ill.rating == "sensitive" and "nsfw" in ill.negative.split(", ") and ill.notes
    p.meta = Meta(adult=True)
    ill = illust.assemble(p, _ill(p, rating="explicit"))
    assert ill.rating == "explicit" and "rating:explicit, nsfw" in ill.base and "nsfw" not in ill.negative.split(", ")


def test_illust_prompt_has_rules(client):
    _written(client)
    from canon import store
    p = store.load("lh")
    text = prompts.illust_prompt(p, 1, None, "뒷모습")
    assert "뒷모습" in text and "source#" in text and "전연령" not in text and "saved_look_tags" in text


def test_web_flow(client):
    _written(client)
    quote = "서윤은 등대 앞에 섰다."
    sel = {"start": TEXT.index(quote), "text": quote}
    assert client.post("/api/projects/lh/episodes/1/illust", json={"selection": sel, "model": "nope"}).status_code == 400
    p = client.post("/api/projects/lh/episodes/1/illust", json={"selection": sel, "request": "밤"}).json()
    ill = p["episodes"][0]["illustrations"][-1]
    assert ill["id"] == "i1" and ill["selection"]["text"] == quote and ill["request"] == "밤"
    assert ill["base"].startswith("1girl, 1boy, outdoors, lighthouse, night, wide shot, moonlight, wind")  # 지저분한 태그는 정리된다
    assert "rating:explicit" not in ill["base"] and ill["rating"] == "general"
    assert [c["id"] for c in ill["characters"]] == ["hero", "ally"]
    assert ill["missing_look"] == ["hero"]

    # AI 가 채운 외형 태그를 인물 외형으로 저장하면 그 인물 외형이 비어 있던 삽화가 모두 다시 조립된다
    client.post("/api/projects/lh/episodes/1/illust", json={"selection": sel})
    p = client.post("/api/projects/lh/episodes/1/illust/i1/keep-look", json={"character_id": "hero"}).json()
    assert p["visuals"][0]["look"] == ["black hair", "long hair", "brown eyes"]
    assert [x["missing_look"] for x in p["episodes"][0]["illustrations"]] == [[], []]
    assert client.post("/api/projects/lh/episodes/1/illust/i1/keep-look", json={"character_id": "ally"}).status_code == 400
    # 이미 저장된 외형 태그는 확인(force) 없이 덮지 않는다
    assert client.post("/api/projects/lh/episodes/1/illust/i1/keep-look", json={"character_id": "hero"}).status_code == 400
    assert client.post("/api/projects/lh/episodes/1/illust/i1/keep-look", json={"character_id": "hero", "force": True}).status_code == 200

    # AI 가 장면을 고르기, 모델 바꿔 다시 조립, 지우기
    p = client.post("/api/projects/lh/episodes/1/illust", json={}).json()
    second = p["episodes"][0]["illustrations"][-1]
    assert second["id"] == "i3" and second["selection"] is None and second["draft"]["quote"]
    p = client.post("/api/projects/lh/episodes/1/illust/i3/rebuild", json={"model": "v5-full"}).json()
    assert p["episodes"][0]["illustrations"][-1]["model"] == "v5-full"
    assert "A girl stands before a lighthouse at night" in p["episodes"][0]["illustrations"][-1]["base"]
    p = client.delete("/api/projects/lh/episodes/1/illust/i1").json()
    assert [x["id"] for x in p["episodes"][0]["illustrations"]] == ["i2", "i3"]
    assert client.delete("/api/projects/lh/episodes/1/illust/i1").status_code == 400

    s = client.post("/api/projects/lh/characters/ally/look").json()
    assert s["look"][0] == "black hair" and s["subject"] == "girl"
    assert client.post("/api/projects/lh/characters/nobody/look").status_code == 400
    assert [m["id"] for m in client.get("/api/illust/models").json()][0] == "v5-full"


def test_finalized_episode_can_illustrate(client):
    _written(client)
    from canon import store
    p = store.load("lh")
    p.episodes[0].status = "finalized"
    store.save("lh", p)
    r = client.post("/api/projects/lh/episodes/1/illust", json={})
    assert r.status_code == 200 and r.json()["episodes"][0]["text"] == TEXT


SCENE = ("파도가 방파제를 때렸다. 서윤은 등대 계단 아래에서 손전등을 켰다.\n\n"
        "\"오빠, 거기 있어?\" 대답 대신 위층에서 유리 깨지는 소리가 났다. 그녀는 숨을 고르고 첫 계단에 발을 올렸다.")


def test_match_quote_keeps_exact_and_fixes_spacing():
    assert illust.match_quote(SCENE, "서윤은 등대 계단 아래에서 손전등을 켰다.") == ("서윤은 등대 계단 아래에서 손전등을 켰다.", "")
    # 줄바꿈 · 띄어쓰기만 다르면 원문 그대로 바꾼다. 알릴 것은 없다
    q, note = illust.match_quote(SCENE, "손전등을 켰다.  \"오빠, 거기 있어?\"")
    assert q == "손전등을 켰다.\n\n\"오빠, 거기 있어?\"" and note == ""
    assert illust.match_quote(SCENE, "  ") == ("", "")


def test_match_quote_window_and_drop():
    # 따옴표 모양만 바꿔 옮겼으면 그 문장을 담은 가장 짧은 창(원문)으로
    q, note = illust.match_quote(SCENE, "“오빠, 거기 있어?” 대답 대신 위층에서 유리 깨지는 소리가 났다.")
    assert q == "\"오빠, 거기 있어?\" 대답 대신 위층에서 유리 깨지는 소리가 났다." and note == illust.QUOTE_FIXED
    # 낱말 몇 개를 바꿔 옮겼으면 같은 문장으로 보는 창 가운데 길이가 가장 가까운 것
    q, note = illust.match_quote(SCENE, "서윤은 등대 계단 밑에서 손전등을 켰다.")
    assert q == "서윤은 등대 계단 아래에서 손전등을 켰다." and note == illust.QUOTE_FIXED
    # 짧은 인용은 비슷한 문장으로 바꾸지 않는다
    assert illust.match_quote(SCENE, "서윤이 웃었다.") == ("", illust.QUOTE_DROPPED)
    assert illust.match_quote(SCENE, "바닷가 마을에 눈이 소복이 쌓여 아이들이 썰매를 탔다.") == ("", illust.QUOTE_DROPPED)


def test_illustrate_checks_quote_against_prompt_scope(monkeypatch):
    from canon import pipeline
    from canon.mock import MockLLM
    from .jsvm import episode
    p = Project(meta=Meta(title="등대"), episodes=[episode(1, text=SCENE)])
    assert pipeline.illustrate(MockLLM(), p, 1).draft.quote == "파도가 방파제를 때렸다."  # mock: 본문 첫 문장
    # 프롬프트에 넣지 않은 뒤쪽 본문의 문장은 인용으로 두지 않는다
    monkeypatch.setattr(prompts, "ILLUST_FULL_LIMIT", 5)
    ill = pipeline.illustrate(MockLLM(), p, 1)
    assert prompts.illust_scope(SCENE, None) == "파도가 방" and ill.draft.quote == ""
    assert ill.notes[0] == illust.QUOTE_DROPPED and illust.assemble(p, ill).notes[0] == illust.QUOTE_DROPPED


def test_age_tag_from_age_field():
    assert illust.age_tag("20", "girl") == "adult"
    assert illust.age_tag("31", "girl") == "0.6::mature female::"
    assert illust.age_tag("34", "boy") == "0.6::mature male::"
    assert illust.age_tag("40대 후반", "girl") == "mature female"
    assert illust.age_tag("72", "boy") == "old man"
    assert illust.age_tag("30", "other") == "adult"
    assert illust.age_tag("17", "girl") == "" and illust.age_tag("고등학생", "girl") == ""  # 미성년은 붙이지 않는다
    assert illust.age_tag("", "girl") == "" and illust.age_tag("나이 모름", "boy") == ""


def test_assemble_adds_age_and_drops_young_tags():
    p = Project(characters=[Character(id="a", name="가", role="", gender="여", age="20"),
                            Character(id="b", name="나", role="", gender="남", age="34")])
    d = IllustDraft(quote="q", scene="s", characters=[
        IllustCharacter(id="a", subject="girl", look=["black hair", "young adult"], position="left"),
        IllustCharacter(id="b", subject="boy", look=["brown hair", "mature male"], position="right")])
    a, b = illust.assemble(p, Illustration(id="i1", draft=d), "v4.5-full").characters
    assert a.prompt == "girl, black hair, adult"  # AI 가 적은 young adult 는 빼고 나이 칸으로 붙인다
    assert b.prompt == "boy, brown hair, mature male"  # 나이대 태그가 이미 있으면 붙이지 않는다

    p.visuals = [CharacterVisual(character_id="a", look=["black hair", "young adult"])]
    ill = illust.assemble(p, Illustration(id="i1", draft=d), "v4.5-full")
    assert ill.characters[0].prompt == "girl, black hair, young adult"  # 작가가 저장한 외형은 바꾸지 않고 알린다
    assert any("young adult" in n for n in ill.notes)


def test_check_draft_drops_broken_tags():
    d = IllustDraft(quote="q", scene="s", setting=["subway station", "lighting fluorescent lighting dim lighting", "rating sensitive"],
                    mood=["garment bag", "mood garment bag modified school uniform zipper tense"], characters=[
                        IllustCharacter(id="a", subject="girl", action=["holding garment bag", "source#hand on another's shoulder"],
                                        position="centerbox action standing holding garment bag"),
                        IllustCharacter(id="b", subject="boy", position="Right")])
    notes = illust.check_draft(d)
    assert d.setting == ["subway station"] and d.mood == ["garment bag"]
    assert d.characters[0].action == ["holding garment bag", "source#hand on another's shoulder"]
    assert d.characters[0].position == "" and d.characters[1].position == "Right"
    assert len(notes) == 2 and "3개" in notes[0] and "1개" in notes[1]
    assert illust.check_draft(d) == []
