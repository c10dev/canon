"""호칭이 빈 쌍 알림과 본문에서 호칭 찾기 (canon/address.py gaps · material · clean_found, pipeline.suggest_addresses, 작업 address_ai). mock LLM, 실제 호출 없음."""
from canon import address, pipeline, store
from canon.mock import MockLLM
from canon.mock_address import MOCK_MADE_UP_QUOTE
from canon.schema import AddressChange, AddressFind, AddressForm, Character, Project

from .jsvm import STATIC, dump, episode, needs_node, run_js

LLM = MockLLM()
TOGETHER = '서윤이 "도현, 오늘도 늦었네!" 하고 웃었다.\n\n도현은 "서윤아, 미안." 하고 답했다.'


def _p(finalized: int = 12) -> Project:
    """서윤 · 도현 · 하린. 확정 finalized 화 가운데 1~11화에 서윤과 도현이 함께 나오고, 하린은 1~3화에만 나온다."""
    p = Project.model_validate({"meta": {"title": "등대", "form": "serial", "target_episodes": 20}})
    p.characters = [Character(id="hero", name="강서윤", role="주인공"), Character(id="rival", name="도현", role="라이벌"),
                    Character(id="ally", name="이하린", role="조연")]
    eps = []
    for n in range(1, finalized + 1):
        text = TOGETHER if n <= 11 else "바다가 조용했다."
        if n <= 3:
            text += "\n\n하린이 멀리서 보았다."
        eps.append(episode(n, text=text, status="finalized"))
    p.episodes = eps + [episode(finalized + 1, status="draft")]
    return p


# ---------- gaps ----------

def test_gaps_lists_both_directions_of_frequent_pair():
    got = address.gaps(_p())
    assert got == [{"speaker": "hero", "listener": "rival", "together": 11}, {"speaker": "rival", "listener": "hero", "together": 11}]


def test_gaps_skip_direction_with_calls():
    p = _p()
    p.address_forms = [AddressForm(speaker="hero", listener="rival", calls="도현"), AddressForm(speaker="rival", listener="hero", speech="해요체")]
    assert address.gaps(p) == [{"speaker": "rival", "listener": "hero", "together": 11}]  # 말씨만 있고 부르는 말이 빈 방향은 남는다


def test_gaps_empty_below_minimum_finalized():
    assert address.gaps(_p(9)) == []


def test_gaps_counts_only_recent_window():
    assert address.gaps(_p(), recent=10) == []  # 3~12화: 함께 나온 화 9 < GAP_MIN
    assert address.gaps(_p(), recent=11) and address.gaps(_p(), recent=11)[0]["together"] == 10  # 2~12화: 함께 나온 화 10


def test_gaps_find_character_by_alias():
    p = _p()
    p.characters[1] = Character(id="rival", name="한지후", role="라이벌", aliases=["도현"])
    assert [g["together"] for g in address.gaps(p)] == [11, 11]


# ---------- material ----------

def test_material_picks_quote_paragraphs_near_both_names_recent_first():
    p = _p()
    p.episodes[0].text = '서윤은 "1화 대사" 하고 말했다.\n\n도현이 들었다.'
    p.episodes[1].text = '서윤과 도현이 걸었다.\n\n"이름 없는 대사"'  # 따옴표 문단 앞에 두 이름이 있다
    p.episodes[2].text = '서윤은 "혼자 한 말" 하고 말했다.\n\n하린이 보았다.'  # 도현이 없다
    p.episodes[3].text = '서윤과 도현이 웃었다.'  # 따옴표가 없다
    for e in p.episodes[4:]:
        e.text = "바다가 조용했다."
    got = address.material(p, "hero", "rival").split("\n")
    assert got == ['[2화] "이름 없는 대사"', '[1화] 서윤은 "1화 대사" 하고 말했다.']


def test_material_far_names_and_budget():
    p = _p()
    far = '서윤이 왔다.\n\n' + '\n\n'.join(['바람.'] * 5) + '\n\n도현은 "멀리 있는 대사" 했다.'
    p.episodes = [episode(1, text=far, status="finalized")]
    assert address.material(p, "hero", "rival") == ""  # 앞뒤 MATERIAL_NEAR 문단 안에 서윤이 없다
    q = _p()
    whole = address.material(q, "hero", "rival")
    assert whole.startswith("[11화] ") and len(whole.split("\n")) == 22
    cut = address.material(q, "hero", "rival", budget=60)
    assert len(cut) <= 60 and cut and cut.startswith("[11화] ")
    assert address.material(q, "hero", "hero") == "" and address.material(q, "hero", "nobody") == ""


# ---------- clean_found ----------

def test_clean_found_drops_other_pair_missing_quote_and_empty_calls():
    p = _p()
    mat = {("rival", "hero"): address.material(p, "rival", "hero")}
    items = [AddressChange(speaker="hero", listener="rival", calls="도현", quote="도현, 오늘도 늦었네!"),  # 묻지 않은 방향
             AddressChange(speaker="rival", listener="hero", calls="서윤아", quote="지어낸 대사"),  # 재료에 없다
             AddressChange(speaker="rival", listener="hero", calls=" ", quote="서윤아, 미안."),  # 부르는 말이 비었다
             AddressChange(speaker="rival", listener="hero", calls="서윤아", quote=""),  # 근거가 없다
             AddressChange(speaker="rival", listener="hero", calls=" 서윤아 ", speech="해체(반말)", quote="“서윤아, 미안.”"),
             AddressChange(speaker="rival", listener="hero", calls="서윤 씨", quote="서윤아, 미안.")]  # 같은 방향 두 번째
    got = address.clean_found(p, items, mat)
    assert [(x.speaker, x.listener, x.calls, x.speech, x.episode) for x in got] == [("rival", "hero", "서윤아", "해체(반말)", 12)]


# ---------- pipeline ----------

def test_suggest_addresses_with_mock():
    p = _p()
    got = pipeline.suggest_addresses(LLM, p, [("hero", "rival"), ("rival", "hero")])
    assert [(x.speaker, x.listener, x.calls, x.quote) for x in got] == [("hero", "rival", "도현", "도현, 오늘도 늦었네!"), ("rival", "hero", "도현", "도현, 오늘도 늦었네!")]  # 가짜 응답은 재료의 첫 대사를 고른다
    assert all(x.quote != MOCK_MADE_UP_QUOTE for x in got)
    assert p.address_forms == []  # 저장하지 않는다


class _NoCall:
    def json(self, *a, **k):
        raise AssertionError("재료가 없으면 LLM 을 부르지 않는다")


def test_no_call_without_material_and_pair_cap():
    p = _p()
    p.characters.append(Character(id="ghost", name="유령선장", role="조연"))  # 본문에 나오지 않는다
    assert pipeline.suggest_addresses(_NoCall(), p, [("hero", "ghost"), ("ghost", "rival")]) == []
    seen: list[str] = []

    class Spy:
        def json(self, system, prompt, schema, hint=None):
            assert schema is AddressFind
            seen.extend(hint["material"])
            return LLM.json(system, prompt, schema, hint=hint)
    pipeline.suggest_addresses(Spy(), p, [("hero", "ghost")] + [("hero", "rival")] * 5 + [("rival", "hero")])
    assert seen == ["hero>rival"]  # 앞 여섯 방향만 묻고, 재료가 빈 방향은 묻지 않는다


# ---------- 작업 · 라우트 ----------

def _wait(client, jid):
    import time
    for _ in range(200):
        j = next(x for x in client.get("/api/jobs").json() if x["id"] == jid)
        if j["status"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("작업이 끝나지 않았어요")


def test_job_suggests_without_saving_and_put_applies(client):
    store.save("ad", _p())
    raw = (store.project_dir("ad") / "project.json").read_text(encoding="utf-8")
    gaps = client.get("/api/projects/ad/address-gaps").json()
    assert gaps["recent"] == 12 and [(g["speaker_name"], g["listener_name"], g["together"]) for g in gaps["items"]] == [("강서윤", "도현", 11), ("도현", "강서윤", 11)]
    r = client.post("/api/projects/ad/jobs", json={"kind": "address_ai", "target": ""})
    assert r.status_code == 200, r.text
    j = _wait(client, r.json()["id"])
    assert j["status"] == "done", j
    assert j["label"] == "호칭이 빈 쌍 2개 찾기"
    assert [(x["speaker"], x["calls"]) for x in j["result"]["items"]] == [("hero", "도현"), ("rival", "도현")]
    assert j["result"]["notices"] == []
    r = client.post("/api/projects/ad/jobs", json={"kind": "address_ai", "target": "rival>hero"})
    j = _wait(client, r.json()["id"])
    assert j["target"] == "rival>hero" and j["label"] == "도현 → 강서윤 호칭 찾기" and len(j["result"]["items"]) == 1
    assert (store.project_dir("ad") / "project.json").read_text(encoding="utf-8") == raw  # 제안은 저장하지 않는다
    x = j["result"]["items"][0]
    out = client.put("/api/projects/ad/address", json={"speaker": x["speaker"], "listener": x["listener"], "calls": x["calls"], "speech": x["speech"]}).json()
    assert [(f["speaker"], f["calls"], f["speech"]) for f in out["address_forms"]] == [("rival", "도현", "해체(반말)")]
    assert [g["speaker"] for g in client.get("/api/projects/ad/address-gaps").json()["items"]] == ["hero"]


def test_job_target_errors(client):
    store.save("ae", _p())
    for target, msg in (("hero>nobody", "인물이 없어요"), ("hero", "인물이 없어요"), ("hero>hero", "같은 인물")):
        r = client.post("/api/projects/ae/jobs", json={"kind": "address_ai", "target": target})
        assert r.status_code == 400 and msg in r.json()["detail"], r.text
    store.save("af", _p(9))
    r = client.post("/api/projects/af/jobs", json={"kind": "address_ai", "target": ""})
    assert r.status_code == 400 and "호칭이 빈 쌍이 없어요" in r.json()["detail"]
    r = client.post("/api/projects/af/jobs", json={"kind": "address_ai", "target": "hero>rival"})
    j = _wait(client, r.json()["id"])
    assert j["status"] == "done" and j["result"]["items"]  # 확정 화가 적어도 방향 하나는 물을 수 있다


# ---------- 화면 (static/address.js) ----------

FILES = __import__("re").findall(r'src="/static/([^"]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))
PRIMARY = __import__("re").compile(r'class="(?=[^"]*\bbtn\b)(?=[^"]*\bprimary\b)[^"]*"')


@needs_node
def test_gap_card_only_with_gaps_and_no_new_primary():
    p = _p()
    gaps = {"recent": 12, "items": address.gaps(p)}
    expr = """(() => { S.name = 'ad'; S.project = data.project; S.addrSug = {};
      const none = addressGapCard(); const pairNone = addressCard('hero', 'rival');
      S.addrGaps = data.gaps;
      const card = addressGapCard(); const pair = addressCard('hero', 'rival'); const other = addressCard('hero', 'ally');
      S.addrSug = { 'rival>hero': data.sug };
      return { none, pairNone, card, pair, other, sug: addressCard('hero', 'rival'), job: JOB_LINK.address_ai({ project: 'ad', target: 'rival>hero' }) }; })()"""
    sug = {"speaker": "rival", "listener": "hero", "calls": "서윤아", "speech": "해체(반말)", "reason": "", "quote": "서윤아, 미안.", "episode": 12}
    got = run_js(FILES, expr, {"project": dump(p), "gaps": gaps, "sug": sug})
    assert got["none"] == ""
    assert "호칭이 빈 쌍 1개" in got["card"] and "본문에서 모두 찾기" in got["card"] and 'data-arg="p:hero|rival"' in got["card"]
    assert "최근 11화에 함께 나왔는데 부르는 말이 비어 있어요" in got["pair"] and got["pair"].count("본문에서 찾기") == 2
    assert "본문에서 찾기" not in got["pairNone"] and "본문에서 찾기" not in got["other"]
    for k in ("card", "pair"):
        assert len(PRIMARY.findall(got[k])) == 0  # 알림 줄의 버튼은 주 버튼이 아니다
    assert "부르는 말 → <strong>서윤아</strong> · 말씨 → <strong>해체(반말)</strong>" in got["sug"] and "“서윤아, 미안.”" in got["sug"]
    assert 'data-action="addrSugApply" data-arg="rival&gt;hero"' in got["sug"]
    assert got["job"] == "#/p/ad/cast/p%3Ahero%7Crival"

