"""가려 읽기 판별 묶음 (blindset mode 'ident'): 만들기 · 답(확신 · 초) · 가림 · 결과 · 통계 · API · 명령줄 · 화면."""
import json
from math import comb

import pytest

from canon import blindset, blindstats, cli, labstats
from canon.schema import BlindSet

from .jsvm import needs_node, run_js


def _rows(pieces=3, arms=("ref", "canon")):
    items, key = [], []
    for p in range(1, pieces + 1):
        for arm in arms:
            no = f"{len(items) + 1:02d}"
            items.append({"no": no, "text": f"{p}번째 이야기의 {len(items) % 3}번 글이다. 둘째 문장이다.\n\n새 문단이다."})
            key.append({"no": no, "arm": arm, "piece": f"P{p}"})
    return items, key


def _set(pieces=3):
    items, key = _rows(pieces)
    return blindset.create("판별", items, key, mode="ident", answer_arm="ref")


def _answer(s, corrects, conf=3, seconds=60):
    """duels 차례대로 corrects[i] 가 참이면 정답 판(ref) 글을, 거짓이면 다른 글을 고른다."""
    arm = {k.no: k.arm for k in s.key}
    for i, d in enumerate(blindset.duels(s)):
        ref = d["a"] if arm[d["a"]] == "ref" else d["b"]
        other = d["b"] if ref == d["a"] else d["a"]
        c = conf[i] if isinstance(conf, list) else conf
        blindset.duel(s.id, d["a"], d["b"], ref if corrects[i] else other, c, seconds)
    return blindset.load(s.id)


def test_create_ident():
    s = _set()
    assert s.mode == "ident" and s.answer_arm == "ref"
    assert len(blindset.duels(s)) == 3
    items, key = _rows()
    assert blindset.create("보통", items, key, answer_arm="ref").answer_arm == ""  # ident 가 아니면 무시한다


def test_create_ident_refuses_bad_sets():
    items, key = _rows()
    with pytest.raises(ValueError, match="answer_arm"):
        blindset.create("x", items, key, mode="ident")
    with pytest.raises(ValueError, match="열쇠에 없는 정답 판"):
        blindset.create("x", items, key, mode="ident", answer_arm="없는판")
    with pytest.raises(ValueError, match="대목 이름"):
        blindset.create("x", items, [{**k, "piece": ""} for k in key], mode="ident", answer_arm="ref")
    with pytest.raises(ValueError, match="대목 이름"):
        blindset.create("x", items, mode="ident", answer_arm="ref")
    # 한 대목에 canon 두 편만: 정답 판 글이 없는 쌍
    items2, key2 = _rows(2)
    items2 += [{"no": "05", "text": "셋째 이야기의 첫째 글이다."}, {"no": "06", "text": "셋째 이야기의 둘째 글이다."}]
    key2 += [{"no": "05", "arm": "canon", "piece": "P3"}, {"no": "06", "arm": "canon", "piece": "P3"}]
    with pytest.raises(ValueError):
        blindset.create("x", items2, key2, mode="ident", answer_arm="ref")
    # 세 판이 섞여 정답 판 글이 없는 쌍이 생기는 경우
    items3, key3 = _rows(1, arms=("ref", "canon", "other"))
    items3 += [{"no": "04", "text": "첫 이야기의 넷째 글이다."}]
    key3 += [{"no": "04", "arm": "other", "piece": "P1"}]
    with pytest.raises(ValueError, match="하나씩"):
        blindset.create("x", items3, key3, mode="ident", answer_arm="ref")


def test_duel_answers(client):
    s = _set()
    d = blindset.duels(s)[0]
    a, b = d["a"], d["b"]
    with pytest.raises(ValueError, match="비슷해요"):
        blindset.duel(s.id, a, b, blindset.TIE, 3)
    for bad in (0, 5):
        with pytest.raises(ValueError, match="확신"):
            blindset.duel(s.id, a, b, a, bad)
    blindset.duel(s.id, a, b, a, 3, 99999)
    got = blindset.duels(blindset.load(s.id))[0]
    assert got["pick"] == a and got["confidence"] == 3
    assert blindset.load(s.id).duels[0].seconds == blindset.SECONDS_MAX
    blindset.duel(s.id, a, b, "", 0, 0)  # 지움
    s2 = blindset.load(s.id)
    assert s2.duels == [] and blindset.duels(s2)[0]["pick"] == "" and blindset.duels(s2)[0]["confidence"] == 0


def test_score_flag_mark_are_refused():
    s = _set()
    with pytest.raises(ValueError, match="고르기만"):
        blindset.score(s.id, "01", 3)
    with pytest.raises(ValueError, match="고르기만"):
        blindset.flag(s.id, "01", blindset.CRITERIA[0])
    with pytest.raises(ValueError, match="고르기만"):
        blindset.mark(s.id, "01", 0)


def test_view_hides_arms_until_reveal():
    s = _set()
    v = blindset.view(s)
    dumped = json.dumps(v, ensure_ascii=False)
    assert "ref" not in dumped and "canon" not in dumped and "P1" not in dumped and "answer_arm" not in v
    assert v["criteria"] == [] and v["pieces"] == [] and v["result"] is None and v["duels"][0]["left"]["text"]
    assert "answer_arm" not in dumped
    with pytest.raises(ValueError, match="아직 고르지 않은"):
        blindset.reveal(s.id)
    _answer(s, [True, False, True])
    blindset.reveal(s.id)
    r = blindset.view(blindset.load(s.id))["result"]
    assert r["ident"]["n"] == 3 and {x["arm"] for x in r["rows"]} == {"ref", "canon"}


def test_ident_stats_hand_computed():
    s = _set(10)
    s = _answer(s, [True] * 8 + [False] * 2, conf=2)
    st = blindstats.ident_stats(s)
    assert (st["n"], st["correct"], st["accuracy"]) == (10, 8, 0.8)
    assert st["p"] == 56 / 1024 == sum(comb(10, i) for i in range(8, 11)) / 2 ** 10
    assert st["wilson"] == list(labstats.wilson(8, 10))
    assert st["by_confidence"][1] == {"confidence": 2, "n": 10, "correct": 8} and st["by_confidence"][0]["n"] == 0
    assert [b["n"] for b in st["blocks"]] == [5, 5] and st["verdict"] == "short"
    assert st["by_arm"] == [{"arm": "canon", "n": 10, "correct": 8}] and st["repeat"] is None
    assert blindstats.stats(s) == st  # stats 는 ident 묶음에 ident_stats 를 돌려준다


def test_auc_blocks_and_marks():
    def u(x_conf, pick_left, ans_left):
        return {"conf": x_conf, "pick_left": pick_left, "ans_left": ans_left, "correct": pick_left == ans_left}
    assert blindstats._auc([u(4, True, True), u(1, False, True), u(3, False, False)]) == 1.0
    assert blindstats._auc([u(2, True, True), u(2, True, False)]) == 0.5
    assert blindstats._auc([u(1, False, True), u(3, True, False), u(1, False, False)]) == 0.25
    assert blindstats._auc([u(2, True, True)]) is None and blindstats._auc([u(0, True, True), u(1, True, False)]) is None
    s = _answer(_set(12), [True] * 12)
    assert [(b["from"], b["to"], b["n"]) for b in blindstats.ident_stats(s)["blocks"]] == [(1, 5, 5), (6, 10, 5), (11, 15, 2)]
    assert blindstats.ident_stats(s)["checkpoints"] == [{"n": 20, "need": 16, "correct": None}, {"n": 37, "need": 24, "correct": None}]


def test_repeat_counts_one_unit_and_time():
    items, key = _rows(2)
    items += [{"no": "05", "text": items[0]["text"]}]  # 01 과 글자가 같은 정답 판 글
    key += [{"no": "05", "arm": "ref", "piece": "P1"}]
    s = blindset.create("반복", items, key, mode="ident", answer_arm="ref")
    ds = blindset.duels(s)
    assert len(ds) == 3
    arm = {k.no: k.arm for k in s.key}
    text = {x.no: x.text for x in s.items}
    seen = 0
    for d in ds:
        ref = d["a"] if arm[d["a"]] == "ref" else d["b"]
        other = d["b"] if ref == d["a"] else d["a"]
        twin = text[ref] == items[0]["text"]  # 글자가 같은 정답 판 글이 낀 쌍: 첫 쌍은 정답, 둘째 쌍은 오답
        seen += twin
        blindset.duel(s.id, d["a"], d["b"], other if twin and seen == 2 else ref, 2, 40)
    st = blindstats.ident_stats(blindset.load(s.id))
    assert st["total"] == 3 and st["answered"] == 3 and st["n"] == 2  # 글자가 같은 두 쌍은 한 단위
    assert st["repeat"] == {"same": 0, "of": 1}


def test_fast_and_median():
    s = _set(3)
    arm = {k.no: k.arm for k in s.key}
    for d, sec in zip(blindset.duels(s), (10, 50, 20)):
        blindset.duel(s.id, d["a"], d["b"], d["a"] if arm[d["a"]] == "ref" else d["b"], 4, sec)
    st = blindstats.ident_stats(blindset.load(s.id))
    assert st["fast"] == 2 and st["median_seconds"] == 20.0
    assert any("30초 안에" in w for w in st["warnings"]) and any("20쌍에 못 미쳐" in w for w in st["warnings"])


def test_verdicts():
    def units(n, first20, total=None):
        us = [{"correct": i < first20} for i in range(min(n, 20))]
        rest = (total if total is not None else first20) - first20
        us += [{"correct": i < rest} for i in range(max(0, n - 20))]
        return us
    assert blindstats._verdict(units(19, 19)) == "short"
    assert blindstats._verdict(units(20, 16)) == "gap"
    assert blindstats._verdict(units(20, 15)) == "more"
    assert blindstats._verdict(units(30, 15)) == "more"
    assert blindstats._verdict(units(37, 15, 24)) == "gap"
    assert blindstats._verdict(units(37, 15, 23)) == "not_shown"
    assert blindstats._checkpoints(units(37, 15, 24)) == [{"n": 20, "need": 16, "correct": 15}, {"n": 37, "need": 24, "correct": 24}]


def test_old_json_still_loads():
    old = {"id": "abc12345", "items": [{"no": "01", "text": "글"}], "duels": [{"a": "01", "b": "02", "pick": "01"}], "mode": "side"}
    s = BlindSet.model_validate(old)
    assert s.answer_arm == "" and s.duels[0].confidence == 0 and s.duels[0].seconds == 0


def test_api(client):
    items, key = _rows()
    r = client.post("/api/blind", json={"title": "API 판별", "items": items, "key": key, "mode": "ident", "answer_arm": "ref"})
    assert r.status_code == 200
    bid = r.json()["id"]
    assert client.post("/api/blind", json={"items": items, "key": key, "mode": "ident"}).status_code == 400
    arm = {k["no"]: k["arm"] for k in key}
    for d in r.json()["duels"]:
        ref = d["a"] if arm[d["a"]] == "ref" else d["b"]
        assert client.post(f"/api/blind/{bid}/reveal").status_code == 400
        got = client.put(f"/api/blind/{bid}/duels", json={"a": d["a"], "b": d["b"], "pick": ref, "confidence": 4, "seconds": 12})
        assert got.status_code == 200
    assert client.put(f"/api/blind/{bid}/duels", json={"a": d["a"], "b": d["b"], "pick": "=", "confidence": 1}).status_code == 400
    assert client.post(f"/api/blind/{bid}/reveal").status_code == 200
    res = client.get(f"/api/blind/{bid}").json()["result"]
    assert res["ident"]["correct"] == 3 and res["ident"]["accuracy"] == 1.0 and len(res["rows"]) == 6


def test_cli(client, tmp_path, capsys):
    items, key = _rows()
    d = tmp_path / "blind"
    d.mkdir()
    for x in items:
        (d / f"{x['no']}.txt").write_text(x["text"], encoding="utf-8")
    (d / "blind_key.json").write_text(json.dumps(key, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="함께 쓸 수 없어요"):
        cli.main(["blind", "import", str(d), "--side", "--ident", "ref"])
    cli.main(["blind", "import", str(d), "--ident", "ref"])
    assert "고르세요" in capsys.readouterr().out
    s = blindset.sets()[0]
    assert s.mode == "ident"
    cli.main(["blind", "list"])
    assert "0/3쌍 고름" in capsys.readouterr().out
    _answer(s, [True, True, False])
    blindset.reveal(s.id)
    cli.main(["blind", "stats", s.id])
    out = capsys.readouterr().out
    assert "정답 2/3" in out and "판정:" in out and "확신 AUC" in out
    cli.main(["blind", "stats", s.id, "--json"])
    assert json.loads(capsys.readouterr().out)["mode"] == "ident"


@needs_node
def test_js_ident_buttons():
    got = run_js(["app.js", "blindset.js"], """(() => {
      const d = { a: '01', b: '02', pick: '01', confidence: 3 };
      return { none: blIdentButtons({ a: '01', b: '02', pick: '', confidence: 0 }), now: blIdentButtons(d) };
    })()""", {})
    order = ["a:4", "a:3", "a:2", "a:1", "b:1", "b:2", "b:3", "b:4"]
    assert [x["arg"] for x in got["now"]] == order
    assert [x["label"] for x in got["now"]] == ["왼쪽 4", "왼쪽 3", "왼쪽 2", "왼쪽 1", "오른쪽 1", "오른쪽 2", "오른쪽 3", "오른쪽 4"]
    assert [x["arg"] for x in got["now"] if x["on"]] == ["a:3"]
    assert not any(x["on"] for x in got["none"])


@needs_node
def test_js_ident_views():
    got = run_js(["app.js", "blindset.js"], """(() => {
      fmtDateTime = () => '';
      const duels = [{ a: '01', b: '02', pick: '01', confidence: 3, left: { text: '첫 글.\\n\\n둘째 문단.' }, right: { text: '다른 글.' } }];
      const base = { id: 's1', title: '판별', mode: 'ident', items: 2, scored: 0, picked: 1, pairs: 1, scale: 5, criteria: [], has_key: true, revealed_at: '', result: null, pieces: [], texts: [], duels };
      S.bl = base; S.blNo = ''; S.blPiece = -1; S.blDuel = 0;
      const pair = viewBlind();
      const ident = { id: 's1', n: 1, correct: 1, accuracy: 1, wilson: [0.2, 1], p: 0.5, auc: null, by_confidence: [1, 2, 3, 4].map((c) => ({ confidence: c, n: 0, correct: 0 })),
        blocks: [{ from: 1, to: 5, n: 1, correct: 1 }], repeat: null, fast: 0, verdict: 'short', warnings: ['20쌍에 못 미쳐 판정하지 않아요 (지금 1쌍)'] };
      S.bl = { ...base, revealed_at: 'x', result: { ident, rows: [{ no: '01', arm: '가', piece: 'P1' }] } }; S.blDuel = -1;
      const res = viewBlind();
      const n = (h, re) => (h.match(re) || []).length;
      return { buttons: n(pair, /data-action="blIdent"/g), pressed: n(pair, /aria-pressed="true" data-action="blIdent" data-arg="a:3"/g), paras: n(pair, /<p>/g), primary: n(pair, /btn primary/g),
        res: [res.includes('정답 1 / 1쌍'), res.includes('20쌍에 못 미쳐'), res.includes('<td>가</td>'), n(res, /btn primary/g)] };
    })()""", {})
    assert got["buttons"] == 8 and got["pressed"] == 1 and got["paras"] == 3 and got["primary"] == 1
    assert got["res"] == [True, True, True, 0]
