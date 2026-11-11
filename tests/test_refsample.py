"""레퍼런스 원고의 문체 표본 흩기 (canon/refsample.py) 와 전체 원문에서 표지 세기 (pipeline.analyze_style 의 corpus)."""
import time

from canon import pipeline, refdigest, refs, refsample
from canon.schema import RefCut, StyleMarker, StyleProfile

TALK = '"어디 가?" 도현이 물었다.\n\n"등대." 서윤이 답했다.\n\n"지금?" 도현이 다시 물었다.\n\n"지금이야." 서윤이 말했다.'
NARR = "바람이 방파제를 넘어 들이쳤다. 서윤은 외투 깃을 세우고 계단을 올랐다. 녹슨 난간이 손바닥에 차갑게 붙었다."


def _ep(n, kind="", dialogue=0.2, size=12):
    """화 하나: 첫머리 표시 · 서술 덩어리 여럿 · 대사 덩어리 · 끝 표시."""
    body = [f"{n}화의 첫 문단이다. 서윤은 문을 열었다."] + [f"{NARR} ({n}화 {i}번째 문단)" for i in range(size)]
    body.insert(size // 2, TALK)
    body.append(f"{n}화의 마지막 문단이다. 불이 꺼졌다.")
    return {"order": n, "label": f"{n}화", "text": "\n\n".join(body), "kind": kind, "dialogue": dialogue}


def test_short_selection_goes_whole():
    eps = [_ep(1), _ep(2)]
    out = refsample.spread(eps, 30_000)
    assert not out["spread"] and out["text"] == eps[0]["text"] + "\n\n" + eps[1]["text"]
    assert [p["part"] for p in out["pieces"]] == ["all", "all"] and out["episodes"] == 2


def test_long_selection_is_spread_over_the_range():
    eps = [_ep(n, dialogue=(n % 7) / 10) for n in range(1, 61)]
    out = refsample.spread(eps, 6_000)
    assert out["spread"] and len(out["text"]) <= 6_000 and out["chars"] > 6_000
    orders = sorted({p["order"] for p in out["pieces"]})
    assert orders[0] <= 20 and any(20 < o <= 40 for o in orders) and orders[-1] > 40  # 앞 · 가운데 · 뒤가 모두 든다
    assert out["episodes"] == refsample.ZONES * refsample.PER_ZONE
    assert {"head", "tail"} <= {p["part"] for p in out["pieces"]}
    assert sum(p["chars"] for p in out["pieces"]) <= len(out["text"])
    # 조각은 원문에 있는 글 그대로다 (잘라 낸 것이지 고친 것이 아니다)
    whole = "\n\n".join(e["text"] for e in eps)
    assert all(piece.strip() in whole for piece in out["text"].split(refsample.SEP))


def test_pieces_take_head_talk_narration_tail():
    e = _ep(3, size=20)
    ps = refsample.pieces_of(e["text"], 1_200)
    assert [p["part"] for p in ps][0] == "head" and [p["part"] for p in ps][-1] == "tail"
    assert ps[0]["text"].startswith("3화의 첫 문단") and ps[-1]["text"].endswith("불이 꺼졌다.")
    talk = next(p for p in ps if p["part"] == "talk")
    narr = next(p for p in ps if p["part"] == "narr")
    assert '"어디 가?"' in talk["text"] and '"' not in narr["text"]
    assert sum(len(p["text"]) for p in ps) <= 1_200
    assert refsample.pieces_of("짧은 화", 1_200) == [{"part": "all", "text": "짧은 화", "at": 0}]


def test_zone_picks_one_episode_per_kind_then_by_dialogue():
    zone = [_ep(n, kind=k, dialogue=d) for n, k, d in
            [(1, "대화", 0.5), (2, "대화", 0.6), (3, "전투", 0.1), (4, "대화", 0.4), (5, "일상", 0.3), (6, "대화", 0.5), (7, "대화", 0.7)]]
    got = refsample.pick_episodes(zone)
    assert len(got) == 3 and {e["kind"] for e in got} == {"대화", "전투", "일상"}
    plain = [_ep(n, dialogue=d) for n, d in [(1, 0.5), (2, 0.1), (3, 0.3), (4, 0.9), (5, 0.4)]]
    assert {e["order"] for e in refsample.pick_episodes(plain)} == {2, 4, 5}  # 가장 낮음 · 가운데 · 가장 높음
    assert refsample.pick_episodes(plain[:2]) == plain[:2]


def _book(n=30):
    text = "\n\n".join(f"{i}화\n\n" + _ep(i, size=30)["text"] for i in range(1, n + 1))
    d = refs.preview(text, repeats=[])
    cuts = [RefCut(**{k: c[k] for k in ("line", "body", "head", "label", "title", "kind")}) for c in d["cuts"] if c["on"]]
    return refs.create("긴 글", text, cuts, rights=True)


def test_ref_sample_spreads_and_keeps_old_cut(client, monkeypatch):
    monkeypatch.setattr(refs, "SAMPLE_MAX", 8_000)
    b = _book()
    orders = list(range(1, 31))
    s = refs.sample(b.id, orders)
    assert s["spread"] and s["cut"] and len(s["text"]) <= 8_000 and s["source"].startswith("긴 글") and not s["with_cards"]
    assert max(p["order"] for p in s["pieces"]) > 20 and min(p["order"] for p in s["pieces"]) <= 10
    old = refs.sample(b.id, orders, spread=False)
    assert not old["spread"] and old["text"] == refs.corpus(b.id, orders)[:8_000].strip() and old["pieces"] == []
    # 화 카드를 읽힌 뒤에는 성격으로 고른다
    refdigest.run(b.id, refdigest.llm_for(b.id))
    assert refs.sample(b.id, orders)["with_cards"]
    r = client.post(f"/api/refs/{b.id}/sample", json={"eps": orders}).json()
    assert r["spread"] and r["pieces"] and client.post(f"/api/refs/{b.id}/sample", json={"eps": orders, "spread": False}).json()["spread"] is False
    small = refs.sample(b.id, [1])
    assert not small["spread"] and not small["cut"] and small["pieces"][0]["part"] == "all"


def test_markers_are_counted_on_the_corpus():
    sample = "서윤은 걸었던 것이다. " * 5
    corpus = sample + ("도현은 웃었다. " * 200) + "그랬던 것이다. 말이지. "

    class Fake:
        def json(self, system, prompt, schema, hint=None):
            assert "도현은 웃었다" not in prompt  # 모델은 표본만 읽는다
            return StyleProfile(markers=[StyleMarker(text="것이다"), StyleMarker(text="말이지"), StyleMarker(text="하더라")])

    by_sample = pipeline.analyze_style(Fake(), sample)
    assert [m.text for m in by_sample.markers] == ["것이다"] and by_sample.markers[0].per_1k > 50
    by_corpus = pipeline.analyze_style(Fake(), sample, corpus=corpus)
    got = {m.text: m.per_1k for m in by_corpus.markers}
    assert set(got) == {"것이다", "말이지"} and got["것이다"] < 5  # 전체에서는 드문 표지다


def test_library_job_counts_on_chosen_episodes(client, monkeypatch):
    monkeypatch.setattr(refs, "SAMPLE_MAX", 8_000)
    b = _book()
    orders = list(range(1, 31))
    s = refs.sample(b.id, orders)
    j = client.post("/api/styles/analyze/job", json={"text": s["text"], "ref": b.id, "ref_orders": orders}).json()
    end = time.time() + 10
    while time.time() < end:
        cur = next(x for x in client.get("/api/jobs").json() if x["id"] == j["id"])
        if cur["status"] != "running":
            break
        time.sleep(0.02)
    assert cur["status"] == "done" and cur["result"]["counted"] == len(refs.corpus(b.id, orders)) > len(s["text"])
    plain = client.post("/api/styles/analyze/job", json={"text": s["text"]}).json()
    assert plain.get("kind") == "lib_style"
