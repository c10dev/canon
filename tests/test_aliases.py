"""다른 이름 채우기 (canon/aliases.py, docs/context/specs/04-key-suggest.md). mock LLM, 실제 호출 없음."""
import json
import time

from canon import aliases, context, pipeline, prompts, store
from canon.mock import MockLLM
from canon.mock_aliases import MOCK_MADE_UP
from canon.schema import AddressForm, AliasIdea, AliasSuggestion, Character, Project, SetupSuggestion, StoryElement

from .jsvm import dump, episode, needs_node, run_js

LLM = MockLLM()


def _p(form: str = "serial") -> Project:
    """서윤(주인공) · 도현 · 마력 요소. 서윤은 4화에서 '꼬맹이'로만 나오고, 마력은 '마력핵'으로만 나온다."""
    p = Project.model_validate({"meta": {"title": "등대", "form": form, "target_episodes": 6}})
    p.characters = [Character(id="hero", name="강서윤", role="주인공", personality="겉은 차갑고 속은 여리다"),
                    Character(id="rival", name="도현", role="라이벌")]
    p.elements = [StoryElement(id="el-1", kind="인물 특징", name="몸속 힘", description="서윤의 몸속 마력핵은 신성력과 부딪친다")]
    p.address_forms = [AddressForm(speaker="rival", listener="hero", calls="꼬맹이")]
    texts = {1: "서윤은 등대에 올랐다.\n\n도현이 아래에서 불렀다.",
             2: "서윤은 바다를 보았다.\n\n마력핵이 뜨겁게 울렸다.",
             3: "꼬맹이가 또 왔다.\n\n서윤은 고개를 숙였다.\n\n도현은 웃었다.",
             4: "꼬맹이는 대답하지 않았다.\n\n밤이 깊었다."}
    p.episodes = [episode(n, text=t, status="written") for n, t in texts.items()] + [episode(5, status="draft")]
    return p


# ---------- 찾기 (context.name_pattern) ----------

def test_name_pattern_finds_whole_aliases_only():
    c = Character(id="hero", name="강서윤", role="", aliases=["꼬맹이", "달", " 등대지기 "])
    pat = context.name_pattern(c)
    assert pat.search("꼬맹이가 왔다") and pat.search("등대지기는 잠들었다")
    assert not pat.search("작은꼬맹이가 왔다")  # 앞이 한글이면 다른 낱말의 일부
    assert not pat.search("달이 떴다")  # 한 글자 다른 이름은 받지 않는다
    assert context.name_pattern(Character(id="x", name="", role="", aliases=["달"])) is None


def test_named_ids_picks_character_found_only_by_alias():
    p = _p()
    assert context.named_ids(p, "꼬맹이가 손을 흔들었다") == set()
    p.characters[0].aliases = ["꼬맹이"]
    assert context.named_ids(p, "꼬맹이가 손을 흔들었다") == {"hero"}


def test_aliases_stay_out_of_prompts_and_setup_schema():
    c = Character(id="hero", name="강서윤", role="주인공", aliases=["꼬맹이"])
    assert "aliases" not in prompts.cast_view([c])[0]
    assert "aliases" not in json.dumps(SetupSuggestion.model_json_schema(), ensure_ascii=False)
    assert "aliases" not in json.loads(c.model_dump_json(context={"prompt": True}))


def test_old_project_json_reads_without_character_aliases():
    p = Project.model_validate({"characters": [{"id": "hero", "name": "서윤", "role": "주인공"}]})
    assert p.characters[0].aliases == []


# ---------- 항목 · 재료 ----------

def test_targets_one_batch_and_errors():
    p = _p()
    assert [it.key for it in aliases.targets(p, "c:hero")] == ["c:hero"]
    assert [it.key for it in aliases.targets(p, "")] == ["c:hero", "c:rival", "e:el-1"]
    p.characters[1].aliases = ["도현 형"]
    assert [it.key for it in aliases.targets(p, "c:")] == ["c:hero"]
    assert [it.key for it in aliases.targets(p, "e:")] == ["e:el-1"]
    for bad, err in (("c:nobody", KeyError), ("x:", ValueError)):
        try:
            aliases.targets(p, bad)
            raise AssertionError(bad)
        except err:
            pass
    assert aliases.item(p, "c:hero").calls == ["꼬맹이"]


def test_material_takes_hit_paragraphs_and_recall_for_elements():
    p = _p()
    hero = aliases.item(p, "c:hero")
    paras, cut = aliases.material(p, hero)
    assert [n for n, _ in paras] == [1, 1, 2, 2, 3, 3, 3] and cut == 0  # 이름이 맞은 단락과 그 앞뒤 단락
    el = aliases.item(p, "e:el-1")
    paras, _ = aliases.material(p, el)
    assert any("마력핵" in t for _, t in paras)  # 이름이 본문에 없어 설명과 겹치는 단락을 찾았다
    text = prompts.alias_prompt(p, [hero, el])
    assert text.index("# 모든 항목의 이름") < text.index("## c:hero") < text.index("## e:el-1") < text.index("요구사항:")
    assert "호칭(씨앗): 꼬맹이" in text


# ---------- 정리 · 화 수 ----------

def test_clean_rules():
    p = _p()
    p.characters[0].aliases = ["서윤이"]
    mat = {"c:hero": "꼬맹이가 왔다. 서윤이 웃었다. 열세글자가넘는아주긴별명이다", "e:el-1": "마력핵"}
    s = AliasSuggestion(items=[
        AliasIdea(target="c:hero", aliases=["‘꼬맹이’", "꼬", "열세글자가넘는아주긴별명이다", "서윤", "서윤이", "꼬맹이", MOCK_MADE_UP], reason="3화에서"),
        AliasIdea(target="e:el-1", aliases=["마력핵"]),
        AliasIdea(target="c:nobody", aliases=["없음"]),
    ])
    out = aliases.clean(p, s, mat)
    assert [(x.target, x.aliases) for x in out.items] == [("c:hero", ["꼬맹이"]), ("e:el-1", ["마력핵"])]
    assert out.items[0].reason == "3화에서"
    assert out.notices == ["근거가 없어 뺀 말이 1개 있어요", "이름이나 이미 있는 다른 이름과 같아 뺀 말이 3개 있어요",
                           "두 글자보다 짧거나 12자를 넘어 뺀 말이 2개 있어요", "목록에 없는 항목을 가리킨 제안 1개는 뺐어요"]


def test_hits_counts_episodes_only_and_clash():
    p = _p()
    s = AliasSuggestion(items=[AliasIdea(target="c:hero", aliases=["꼬맹이", "도현"]), AliasIdea(target="e:el-1", aliases=["마력핵"])])
    out = aliases.hits(p, s)
    h = {x.alias: x for x in out.items[0].hits}
    assert out.recent == 4
    assert h["꼬맹이"].episodes == [3, 4] and h["꼬맹이"].only == [4] and h["꼬맹이"].clash == ""  # 3화에는 이름도 나온다
    assert h["도현"].episodes == [1, 3] and h["도현"].only == [] and h["도현"].clash == "도현"
    assert out.items[1].hits[0].episodes == [2] and out.items[1].hits[0].only == [2]


# ---------- 작업 (mock) ----------

def _wait(client, jid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않았어요")


def _job(client, name, target):
    r = client.post(f"/api/projects/{name}/jobs", json={"kind": "aliases", "target": target})
    assert r.status_code == 200, r.text
    j = _wait(client, r.json()["id"])
    assert j["status"] == "done", j
    return j


def test_job_suggests_without_saving(client):
    store.save("al", _p())
    raw = (store.project_dir("al") / "project.json").read_text(encoding="utf-8")
    j = _job(client, "al", "c:hero")
    assert j["target"] == "c:hero" and j["label"] == "강서윤 다른 이름 제안"
    item = j["result"]["items"][0]
    assert item["target"] == "c:hero" and item["aliases"] == ["꼬맹이"]  # 재료에 있는 말만 남고 지어낸 말은 빠졌다
    assert item["hits"][0]["episodes"] == [3, 4]
    assert "근거가 없어 뺀 말이 1개 있어요" in j["result"]["notices"]
    j = _job(client, "al", "")
    assert j["label"] == "빈 다른 이름 제안 3개" and {x["target"] for x in j["result"]["items"]} >= {"c:hero", "e:el-1"}
    assert (store.project_dir("al") / "project.json").read_text(encoding="utf-8") == raw
    r = client.post("/api/projects/al/jobs", json={"kind": "aliases", "target": "c:nobody"})
    assert r.status_code == 400 and "항목이 없어요" in r.json()["detail"]


def test_job_runs_for_short_work(client):
    store.save("sh", _p("short"))
    j = _job(client, "sh", "e:el-1")
    assert j["result"]["items"][0]["aliases"] == ["마력핵"]


def test_pipeline_uses_plan_prompt_and_mock():
    p = _p()
    out = pipeline.suggest_aliases(LLM, p, aliases.targets(p, "c:"))
    assert [x.target for x in out.items] == ["c:hero", "c:rival"] and all(x.hits for x in out.items)


class _NoCall:
    def json(self, *a, **k):
        raise AssertionError("재료가 없으면 LLM 을 부르지 않는다")


def test_no_llm_call_without_material():
    p = _p()
    p.episodes = [episode(1, status="draft")]  # 쓴 화가 없다
    out = pipeline.suggest_aliases(_NoCall(), p, aliases.targets(p, "c:"))
    assert out.items == [] and out.notices == ["본문에서 찾은 단락이 없어 제안을 받지 않았어요"]


def test_items_without_material_are_not_asked():
    p = _p()
    p.characters.append(Character(id="ghost", name="유령선장", role="조연"))  # 본문에 나오지 않는다
    seen: list[str] = []

    class Spy:
        def json(self, system, prompt, schema, hint=None):
            seen.extend(hint["material"])
            return LLM.json(system, prompt, schema, hint=hint)
    out = pipeline.suggest_aliases(Spy(), p, aliases.targets(p, "c:"))
    assert "c:ghost" not in seen and "본문에서 찾은 단락이 없는 1개는 묻지 않았어요" in out.notices


def test_clean_drops_first_word_of_spaced_name():
    p = _p()
    p.characters.append(Character(id="m", name="마르타 부인", role="조연"))
    s = AliasSuggestion(items=[AliasIdea(target="c:m", aliases=["마르타", "부인님"])])
    out = aliases.clean(p, s, {"c:m": "마르타가 왔다. 부인님이라 불렀다."})
    assert [x.aliases for x in out.items] == [["부인님"]]


# ---------- 고르기 카드 (static/aliases.js) ----------

@needs_node
def test_pick_card_has_no_default_check_and_shows_counts():
    p = _p()
    p.characters[0].aliases = ["서윤이"]
    s = aliases.hits(p, AliasSuggestion(items=[AliasIdea(target="c:hero", aliases=["꼬맹이", "도현", "서윤이"], reason="3화")]))
    expr = """(() => { S.name = 'al'; S.project = data.project; S.aliasSug = { 'c:hero': data.sug, 'c:': data.sug };
      return { one: aliasCard('c:hero'), many: aliasCard('c:'), none: aliasCard('e:'), zero: aliasHitText(null, 0) }; })()"""
    got = run_js(["app.js", "aliases.js"], expr, {"project": dump(p), "sug": json.loads(s.model_dump_json())})
    one = got["one"]
    assert " checked" not in one and one.count('data-alias-pick="c:hero"') == 3
    assert "최근 4화 중 2화에서 나와요 · 이름 없이 1화" in one and "‹도현›과 겹쳐요" in one
    assert "이미 있어요" in one and "지금 본문에서 센 값이에요" in one and "고른 다른 이름 적용" in one
    assert "<strong>강서윤</strong>" in got["many"] and "<strong>강서윤</strong>" not in one
    assert got["none"] == "" and got["zero"] == "쓴 화가 없어 세지 못했어요"


def test_clean_drops_aliases_that_contain_the_name():
    p = _p()
    s = AliasSuggestion(items=[AliasIdea(target="c:hero", aliases=["서윤이", "서윤 씨", "꼬맹이"]),
                               AliasIdea(target="e:el-1", aliases=["몸속 힘의 근원", "마력핵"])])
    out = aliases.clean(p, s, {"c:hero": "서윤이 서윤 씨 꼬맹이", "e:el-1": "몸속 힘의 근원 마력핵"})
    assert [x.aliases for x in out.items] == [["꼬맹이"], ["마력핵"]]
    assert "이름을 품고 있어 이름으로 이미 찾히는 말 3개는 뺐어요" in out.notices
