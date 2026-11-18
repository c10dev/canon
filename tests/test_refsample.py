"""레퍼런스 원고의 문체 표본 흩기 (canon/refsample.py) 와 전체 원문에서 표지 세기 (pipeline.analyze_style 의 corpus)."""
import json
import time

from canon import metrics, pipeline, refdigest, refs, refsample
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


def test_pieces_keep_double_quotes_in_pairs():
    """따옴표 하나가 남으면 대사 비율이 뒤집혀 재진다. 잘린 조각은 남은 쪽을 잘라 내고, 안 되면 그 문단을 뺀다."""
    assert refsample._even('서윤은 걸었다. "어디 가') == "서윤은 걸었다."
    assert refsample._even('가." 도현이 웃었다. 서윤은 문을 닫았다.', tail=True) == "도현이 웃었다. 서윤은 문을 닫았다."
    assert refsample._even('"짝이 맞는 글."') == '"짝이 맞는 글."'
    odd = '서윤은 걸었다.\n\n"닫히지 않은 대사.\n\n"짝이 맞는 대사." 도현이 말했다.\n\n바람이 불었다. 문이 흔들렸다. 등대 불이 한 번 깜빡였다.'
    assert refsample._even(odd) == '서윤은 걸었다.\n\n"짝이 맞는 대사." 도현이 말했다.\n\n바람이 불었다. 문이 흔들렸다. 등대 불이 한 번 깜빡였다.'
    eps = [_ep(n, dialogue=(n % 7) / 10) for n in range(1, 61)]
    out = refsample.spread(eps, 6_000)
    assert out["text"].count('"') % 2 == 0 and all(x.count('"') % 2 == 0 for x in out["text"].split(refsample.SEP))


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


# ---------- 구간별 표지 빈도 ----------

def test_zone_rates_counts_each_third(monkeypatch):
    monkeypatch.setattr(refsample, "ZONE_MIN", 100)
    texts = ["그는 웃은 것이었다. " * 20] * 3 + ["그는 걸었다. 것이었다. " + "그는 걸었다. " * 20] * 3 + ["그렇게 말하더라. " * 20] * 3
    got = {z["text"]: z for z in refsample.zone_rates(texts, ["것이었다", "하더라", "것이었다", "없는말"])}
    assert list(got) == ["것이었다", "하더라", "없는말"]  # 같은 표지는 한 번만
    assert got["것이었다"]["counts"] == [60, 3, 0] and got["하더라"]["counts"] == [0, 0, 60] and got["없는말"]["rates"] == [0, 0, 0]
    zone = "\n\n".join(texts[:3])
    assert got["것이었다"]["rates"][0] == round(60 * 1000 / len(zone), 4) and round(got["것이었다"]["rates"][0], 2) == metrics.marker_rate(zone, "것이었다")
    assert refsample.zone_rates(texts[:2], ["것이었다"]) == []  # 화가 구간 수보다 적다
    monkeypatch.setattr(refsample, "ZONE_MIN", 10_000)
    assert refsample.zone_rates(texts, ["것이었다"]) == []  # 구간이 너무 짧다


def test_library_job_and_entry_carry_zone_rates(client, monkeypatch):
    """레퍼런스 원고에서 분석하면 작업 결과에 구간별 빈도가 실리고, 저장한 항목은 프로필에 있는 표지 것만 남긴다."""
    from canon import library
    from canon.schema import MarkerZones

    monkeypatch.setattr(refs, "SAMPLE_MAX", 8_000)
    monkeypatch.setattr(refsample, "ZONE_MIN", 1_000)
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
    res = cur["result"]
    marks = [m["text"] for m in res["profile"]["markers"]]
    assert marks and [z["text"] for z in res["zones"]] == marks and all(len(z["rates"]) == refsample.ZONES == len(z["counts"]) for z in res["zones"])
    texts = [c["text"] for c in refs.pick(refs.load(b.id), orders)]
    assert res["zones"] == refsample.zone_rates(texts, marks)
    assert "marker_zones" not in res["profile"] and "zones" not in res["profile"]["markers"][0]  # 모델이 채우는 형식 밖이다
    # 원고 없이 붙여 넣은 글은 구간을 나누지 않는다
    plain = client.post("/api/styles/analyze/job", json={"text": s["text"]}).json()
    while time.time() < end:
        cur = next(x for x in client.get("/api/jobs").json() if x["id"] == plain["id"])
        if cur["status"] != "running":
            break
        time.sleep(0.02)
    assert cur["result"]["zones"] == []
    # 저장: 화면이 받은 값을 그대로 돌려준다 (작가가 손으로 더한 표지 하나를 섞는다)
    res["profile"]["markers"].append({"text": "손표지", "note": "", "per_1k": 0.5})
    res["zones"].append({"text": "손표지", "rates": [0.9, 0.5, 0.1], "counts": [90, 50, 10]})
    marks.append("손표지")
    e = client.post("/api/styles", json={"name": "긴 글 문체", "sample": s["text"], "profile": res["profile"], "marker_zones": res["zones"]}).json()
    assert [z["text"] for z in e["marker_zones"]] == marks
    kept = client.put(f"/api/styles/{e['id']}", json={"name": "긴 글 문체", "sample": s["text"], "profile": res["profile"]}).json()
    assert kept["marker_zones"] == e["marker_zones"]  # 값을 보내지 않으면 그대로 둔다
    less = {**res["profile"], "markers": res["profile"]["markers"][1:]}
    cut = client.put(f"/api/styles/{e['id']}", json={"name": "긴 글 문체", "sample": s["text"], "profile": less, "marker_zones": res["zones"]}).json()
    assert [z["text"] for z in cut["marker_zones"]] == marks[1:]  # 지운 표지의 값은 버린다
    back = library.restore(e["id"], 1)
    assert [z.text for z in back.marker_zones] == marks[1:]  # 되돌린 표지에는 값이 없다 (지어내지 않는다)
    copy = library.duplicate(e["id"])
    assert copy.marker_zones == back.marker_zones and isinstance(copy.marker_zones[-1], MarkerZones) and copy.marker_zones[-1].text == "손표지"
    # 옛 항목 파일(칸 없음)도 읽힌다
    path = library._path(e["id"])
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("marker_zones")
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert library.load(e["id"]).marker_zones == []


def test_zone_rates_stay_out_of_prompts_and_warnings(client, monkeypatch):
    """구간별 빈도는 보기만 한다: 모델 응답 형식 · 작품 문체 · 집필 프롬프트 · 문체 경고에 들어가지 않는다."""
    from canon import library, prompts
    from canon.schema import MarkerZones, Meta, Project

    assert "marker_zones" not in StyleProfile.model_fields and set(StyleMarker.model_fields) == {"text", "note", "per_1k"}
    assert "MarkerZones" not in json.dumps(StyleProfile.model_json_schema())
    prof = StyleProfile(tense="과거형", markers=[StyleMarker(text="것이었다", per_1k=1.0)])
    e = library.create("구간", prof, zones=[MarkerZones(text="것이었다", rates=[9.87, 6.54, 3.21], counts=[987, 654, 321])])
    assert e.marker_zones[0].rates == [9.87, 6.54, 3.21]
    p = Project(meta=Meta(title="t"))
    library.apply(p, e)
    dumped = p.model_dump_json()
    assert "marker_zones" not in dumped and "9.87" not in dumped
    assert "9.87" not in prompts.style_block(p) and "987" not in prompts.style_block(p)
    assert metrics.marker_warnings(p.style.markers, "것이었다. " * 3 + "가나다라 " * 600) == metrics.marker_warnings(prof.markers, "것이었다. " * 3 + "가나다라 " * 600)
