"""삽화 프롬프트 테스트 (mock LLM): 태그 정리, 조립 규칙, 외형 태그 고정, 웹 흐름. 실행: python -m pytest tests"""
from canon import illust, prompts
from canon.schema import Character, CharacterVisual, IllustCharacter, IllustDraft, Illustration, Meta, Project

from .test_passage import TEXT, _written
from .test_web import client  # noqa: F401  (pytest fixture)


def test_clean_tags():
    assert illust.clean(["Black_hair, long hair", "long hair", "2girls", "rating:explicit", "girl", "검은 머리", "1.2::rain ::", "^_^"]) == [
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
    assert "뒷모습" in text and "source#" in text and "전연령" in text and "saved_look_tags" in text


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
