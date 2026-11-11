"""레퍼런스 원고 전체 읽히기 (canon/refdigest.py): 화 카드 만들기 · 지문으로 낡음 판정 · 실패한 화 건너뛰기 · 읽힐 AI · API.
원고는 tests/fixtures/refs_story.txt (직접 지은 글)."""
import time
from pathlib import Path

import pytest

from canon import mock_refdigest, prompts, refdigest, refs
from canon.llm import MissingKey, make_llm
from canon.schema import RefCut, RefDigest

STORY = (Path(__file__).parent / "fixtures" / "refs_story.txt").read_text(encoding="utf-8")
FIELDS = ("line", "body", "head", "label", "title", "kind")


def _book(text=STORY, name="등대"):
    d = refs.preview(text, repeats=[])
    cuts = [RefCut(**{k: c[k] for k in FIELDS}) for c in d["cuts"] if c["on"]]
    return refs.create(name, text, cuts, rights=True)


def _wait(client, jid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = next(x for x in client.get("/api/jobs").json() if x["id"] == jid)
        if j["status"] != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("작업이 끝나지 않았어요")


def test_reads_every_episode_once(client):
    b = _book()
    st = refdigest.state(b)
    assert st["total"] == 14 and st["read"] == 0 and len(st["todo"]) == 14  # 제외한 '완결 후기'는 읽히지 않는다
    out = refdigest.run(b.id, refdigest.llm_for(b.id))
    assert out == {"read": 14, "failed": [], "error": "", "stopped": False, "left": 0}
    v = refdigest.view(b.id)
    assert (v["read"], v["todo"], v["stale"]) == (14, 0, 0) and v["at"]
    card = v["cards"]["2"]
    assert card["events"] and card["kind"] in refdigest.REF_DIGEST_KINDS and 1 <= card["tension"] <= 5 and card["model"] == "mock"
    # 다시 돌리면 부를 화가 없다
    assert refdigest.run(b.id, refdigest.llm_for(b.id))["read"] == 0
    assert refdigest.estimate(b.id)["calls"] == 0


def test_same_text_is_sent_once(client):
    b = _book()  # 지은 원고는 화마다 같은 문단을 되풀이해 글이 같은 화가 있다

    class Count:
        calls = 0

        def json(self, system, prompt, schema, hint=None):
            Count.calls += 1
            return make_llm("mock").json(system, prompt, schema, hint)

    distinct = len({t["basis"] for t in refdigest._texts(b)})
    assert distinct < 14 and refdigest.estimate(b.id)["calls"] == distinct
    assert refdigest.run(b.id, Count())["read"] == 14 and Count.calls == distinct
    assert len(refdigest.view(b.id)["cards"]) == 14


def test_only_changed_text_is_read_again(client):
    b = _book()
    refdigest.run(b.id, refdigest.llm_for(b.id))
    # 셋째 경계를 꺼 둘째 · 셋째 화를 합친다. 뒤 화는 차례가 하나씩 당겨지지만 글은 그대로다
    cuts = sorted(b.cuts, key=lambda c: c.line)
    b2 = refs.update(b.id, cuts=cuts[:2] + cuts[3:])
    st = refdigest.state(b2)
    assert st["total"] == 13 and st["todo"] == [2] and st["read"] == 12 and st["stale"] == 1
    v = refdigest.view(b.id)
    assert "2" not in v["cards"] and "3" in v["cards"]  # 차례가 바뀐 화도 지문으로 찾는다
    assert refdigest.run(b.id, refdigest.llm_for(b.id))["read"] == 1
    assert refdigest.state(refs.load(b.id))["todo"] == []


def test_new_prompt_version_makes_all_stale(client, monkeypatch):
    b = _book()
    refdigest.run(b.id, refdigest.llm_for(b.id))
    monkeypatch.setattr(prompts, "REF_DIGEST_VERSION", prompts.REF_DIGEST_VERSION + 1)
    st = refdigest.state(b)
    assert st["read"] == 0 and st["stale"] == 14 and refdigest.view(b.id)["cards"] == {}


def test_failed_episode_is_skipped(client):
    text = "\n\n".join(f"{n}화\n\n서윤은 등대로 걸었다. 서윤은 문을 열었다.\n\n" + ("도현은 웃었다. " * 30)
                       + (mock_refdigest.FAIL_MARK if n == 2 else "") for n in range(1, 5))
    b = _book(text, "짧은 글")
    out = refdigest.run(b.id, refdigest.llm_for(b.id))
    assert out["read"] == 3 and out["failed"] == [2] and "사건 줄" in out["error"] and not out["stopped"]
    assert sorted(refdigest.view(b.id)["cards"]) == ["1", "3", "4"]


def test_stops_after_repeated_failures_and_key_errors(client):
    b = _book()

    class Broken:
        calls = 0

        def json(self, system, prompt, schema, hint=None):
            Broken.calls += 1
            raise RuntimeError("서버 오류 500")

    out = refdigest.run(b.id, Broken())
    assert out["stopped"] and out["read"] == 0 and refdigest.FAIL_STOP <= Broken.calls < 14 and "500" in out["error"]
    assert out["left"] == 14

    class NoKey:
        def json(self, system, prompt, schema, hint=None):
            raise MissingKey("키가 없어요")

    with pytest.raises(MissingKey):
        refdigest.run(b.id, NoKey())


def test_clip_and_norm():
    text, cut = refdigest.clip("가" * (refdigest.TEXT_MAX + 500))
    assert cut == 500 and "가운데 500자 줄임" in text and len(text) < refdigest.TEXT_MAX + 40
    assert refdigest.clip("짧은 글") == ("짧은 글", 0)
    g = refdigest._norm(RefDigest(events=[" 한  일 ", "", "x" * 999], cast=["서윤", "서윤", " "], place=" 등대 ", ending="끝",
                                  kind="로맨스", tension=9, hook="반전"))
    assert g.events == ["한 일", "x" * refdigest.LINE_MAX] and g.cast == ["서윤"] and g.place == "등대"
    assert (g.kind, g.tension, g.hook) == ("", 5, "반전")


def test_prompt_puts_source_last_and_has_no_dict_field():
    p = prompts.ref_digest_prompt("원문 글")
    assert p.endswith("[원문]\n원문 글") and "전투" in p and "여운" in p and "6개를 넘기지 않습니다" in p
    assert len(refdigest._norm(RefDigest(events=[f"일 {i}" for i in range(9)], cast=[], place="", ending="", kind="", tension=3, hook="")).events) == 6
    assert set(RefDigest.model_json_schema()["required"]) == set(RefDigest.model_fields)


def test_ai_choice_follows_plan_stage_or_the_book(client, monkeypatch):
    b = _book()
    assert refdigest.ai_view(refdigest.load(b.id))["use"]["source"] == "mock"
    monkeypatch.setenv("CANON_LLM", "gemini")
    monkeypatch.setenv("CANON_MODEL_PLAN", "gemini-3.8-flash")
    monkeypatch.delenv("CORAL_API_KEY", raising=False)
    d = refdigest.load(b.id)
    assert refdigest.ai_choice(d) == {"provider": "gemini", "model": "gemini-3.8-flash", "source": "settings"}
    v = refdigest.set_ai(b.id, "coralbricks", "deepseek-v4.1-flash-value")
    assert v["use"] == {"provider": "coralbricks", "model": "deepseek-v4.1-flash-value", "source": "book", "name": "deepseek-v4.1-flash-value"}
    assert v["follow"]["provider"] == "gemini" and v["coral"] is False
    est = refdigest.estimate(b.id)
    assert 0 < est["calls"] <= 14 and est["priced"] and est["usd"] is not None and est["usd"] < 0.01
    with pytest.raises(ValueError, match="고를 수 없는"):
        refdigest.set_ai(b.id, "mock")
    assert refdigest.set_ai(b.id)["use"]["source"] == "settings"


def test_api_flow(client):
    b = _book()
    v = client.get(f"/api/refs/{b.id}/digest").json()
    assert v["total"] == 14 and v["read"] == 0 and v["cards"] == {} and "coralbricks" in v["ai"]["providers"]
    est = client.get(f"/api/refs/{b.id}/digest/estimate").json()
    assert 0 < est["calls"] <= 14 and est["provider"] == "mock"
    assert client.put(f"/api/refs/{b.id}/digest/ai", json={"provider": "없는것"}).status_code == 400
    j = client.post(f"/api/refs/{b.id}/digest").json()
    assert j["kind"] == "ref_digest" and j["target"] == b.id
    done = _wait(client, j["id"])
    assert done["status"] == "done" and done["result"]["read"] == 14
    v = client.get(f"/api/refs/{b.id}/digest").json()
    assert v["read"] == 14 and len(v["cards"]) == 14
    assert client.post(f"/api/refs/{b.id}/digest").status_code == 400  # 읽힐 화가 없다
    assert client.get("/api/refs/00000000/digest").status_code == 404
    # 원고를 지우면 화 카드도 함께 지워진다
    assert client.delete(f"/api/refs/{b.id}").status_code == 200 and not refdigest._path(b.id).exists()


def test_llm_for_marks_the_stage(client):
    b = _book()
    llm = refdigest.llm_for(b.id)
    assert llm.stage == "plan" and type(llm) is type(make_llm("mock"))
