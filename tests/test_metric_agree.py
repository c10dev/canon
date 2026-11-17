"""지표 검증 스크립트 (scripts/metric_agree.py). 지어낸 글과 지어낸 묶음만 쓴다."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from canon import blindset, labstats, metrics, refs
from canon.schema import BlindDuel, BlindItem, BlindKey, BlindSet

REF_ARM = "SECRETARM_ref"
BASE_ARM = "SECRETARM_base"
TOKENS = ("SECRETARM", "SECRETPIECE", "ridsecret", "ZQXTOKEN")


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "metric_agree.py"
    spec = importlib.util.spec_from_file_location("metric_agree", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["metric_agree"] = mod  # dataclass 가 문자열 주석을 풀 때 모듈을 찾는다
    spec.loader.exec_module(mod)
    return mod


def _ref_text(tag: str, i: int) -> str:
    return " ".join(f"조용한 아침이 밝았다 {tag}{i}번째 ZQXTOKEN 마을은 고요했다{j}." for j in range(8))


def _base_text(tag: str, i: int) -> str:
    return " ".join(f"손가락이 떨렸다 {tag}{i}번째 어깨를 폈다 두려웠다 불안했다{j}." for j in range(8))


def _picker(s: BlindSet, arm: str):
    """쌍에서 그 판의 글 번호를 고르는 함수."""
    arm_of = {k.no: k.arm for k in s.key}
    return lambda a, b: a if arm_of[a] == arm else b


def _set(sid: str, mode: str, tag: str, pieces: int = 4, pick_arm: str = REF_ARM, tie_first: bool = False) -> BlindSet:
    items, key = [], []
    for i in range(pieces):
        for kind, text, arm in (("r", _ref_text(tag, i), REF_ARM), ("b", _base_text(tag, i), BASE_ARM)):
            no = f"{i}{kind}"
            items.append(BlindItem(no=no, text=text))
            key.append(BlindKey(no=no, arm=arm, piece=f"SECRETPIECE{i}"))
    s = BlindSet(id=sid, mode=mode, items=items, key=key, answer_arm=REF_ARM if mode == "ident" else "", revealed_at="2026-11-17")
    pick = _picker(s, pick_arm)
    duels = []
    for n, (a, b) in enumerate(blindset.duel_pairs(s)):
        duels.append(BlindDuel(a=a, b=b, pick="=" if tie_first and n == 0 else pick(a, b), confidence=2 if mode == "ident" else 0))
    s.duels = duels
    return s


@pytest.fixture()
def mod():
    return _script()


def _install(monkeypatch, *sets: BlindSet):
    by = {s.id: s for s in sets}

    def load(sid):
        if sid not in by:
            raise KeyError(sid)
        return by[sid]

    monkeypatch.setattr(blindset, "load", load)


def test_unrevealed_set_stops(mod, monkeypatch):
    s = _set("s1", "ident", "x")
    s.revealed_at = ""
    _install(monkeypatch, s)
    with pytest.raises(SystemExit):
        mod.load_sets(["s1"])


def test_other_mode_stops(mod, monkeypatch):
    s = _set("s1", "ident", "x")
    s.mode = ""
    _install(monkeypatch, s)
    with pytest.raises(SystemExit):
        mod.load_sets(["s1"])


def test_sets_with_same_text_stop(mod, monkeypatch):
    one, two = _set("s1", "ident", "x"), _set("s2", "side", "x")
    _install(monkeypatch, one, two)
    with pytest.raises(SystemExit):
        mod.load_sets(["s1", "s2"])
    other = _set("s3", "side", "y")
    _install(monkeypatch, one, other)
    assert len(mod.load_sets(["s1", "s3"])) == 2


def test_repeat_pair_counts_first_answer_only(mod):
    t1, t2 = _ref_text("r", 0), _base_text("r", 0)
    items = [BlindItem(no=n, text=t) for n, t in (("1", t1), ("2", t2), ("3", t1), ("4", t2))]
    key = [BlindKey(no=n, arm=a, piece="SECRETPIECE0") for n, a in (("1", REF_ARM), ("2", BASE_ARM), ("3", REF_ARM), ("4", BASE_ARM))]
    s = BlindSet(id="s1", mode="ident", items=items, key=key, answer_arm=REF_ARM, revealed_at="x")
    pairs = blindset.duel_pairs(s)
    assert len(pairs) == 2
    first, second = pairs
    arm_of = {k.no: k.arm for k in key}
    s.duels = [BlindDuel(a=first[0], b=first[1], pick=first[0] if arm_of[first[0]] == REF_ARM else first[1]),
               BlindDuel(a=second[0], b=second[1], pick=second[0] if arm_of[second[0]] == BASE_ARM else second[1])]
    units, ties, skipped = mod.units_of(s)
    assert (len(units), ties, skipped) == (1, 0, 0)
    assert units[0].truth_a == (arm_of[first[0]] == REF_ARM)
    assert units[0].pick_a == units[0].truth_a


def test_side_tie_is_counted_and_removed(mod, monkeypatch):
    s = _set("s1", "side", "x", pieces=3, tie_first=True)
    units, ties, skipped = mod.units_of(s)
    assert (len(units), ties, skipped) == (2, 1, 0)
    _install(monkeypatch, s)
    res = mod.run(["s1"], [], [])
    assert res["sets"][0]["ties"] == 1
    assert res["sets"][0]["units"] == 2


def test_ident_body_metric_matches_truth(mod, monkeypatch):
    _install(monkeypatch, _set("s1", "ident", "x"))
    res = mod.run(["s1"], [], [])
    ent = res["results"]["all"]["ident/truth"]
    body = ent["metrics"]["body_per_1k"]
    assert (body["n"], body["agree"], body["rate"]) == (4, 4, 1.0)
    assert ent["metrics"]["body_per_1k"]["vs_majority"] is None
    assert "length_note" in ent
    assert ent["author_vs_truth_differ"] == 0
    assert any("거의 갈리지 않아요" in w for w in res["warnings"])
    assert res["split"] == "none"
    assert any("기준선이 유리해요" in w for w in res["warnings"])


def test_emotion_direction_is_high(mod, monkeypatch):
    assert mod.METRICS["emotion_per_1k"] == "high"
    assert mod.choose(0.0, 3.0, "high") == "b"
    assert mod.choose(3.0, 0.0, "high") == "a"
    assert mod.choose(0.0, 3.0, "low") == "a"
    assert mod.choose(None, 1.0, "low") == "missing"
    assert mod.choose(1.0, 1.0, "low") == "equal"
    _install(monkeypatch, _set("s1", "side", "x", pick_arm=BASE_ARM))
    emo = mod.run(["s1"], [], [])["results"]["all"]["side/author"]["metrics"]["emotion_per_1k"]
    assert (emo["n"], emo["agree"]) == (4, 4)


def test_mcnemar_hand_count(mod):
    flags = [(True, False)] * 6 + [(False, True)] + [(True, True)] * 2 + [(False, False)]
    res = mod.mcnemar(flags)
    assert (res["b"], res["c"], res["baseline_agree"]) == (6, 1, 3)
    assert res["p"] == labstats.sign_test(6, 7)
    assert mod.mcnemar([(True, True)])["p"] == 1.0


def _fake_refs(monkeypatch):
    eps = {
        "rid_one": {e: " ".join(f"일화{e}번의 장면{j}번째 이야기가 이어진다 rid_one" for j in range(12)) for e in (1, 2, 3)},
        "rid_two": {e: " ".join(f"다른{e}번 대목{j}번째 소식이 흘러간다 rid_two" for j in range(12)) for e in (1, 2)},
    }
    monkeypatch.setattr(refs, "texts", lambda rid: eps.get(rid))
    return eps


def test_refs_group_and_reference_skip_found_episode(mod, monkeypatch):
    eps = _fake_refs(monkeypatch)
    unit = mod.Unit("s1", "ident", eps["rid_one"][1], _base_text("z", 9), REF_ARM, BASE_ARM, True, True, "s1:p")
    other = mod.Unit("s1", "side", _base_text("q", 1), _base_text("q", 2), "a", "b", True, None, "s1:q")
    labels, found = mod.assign_groups([unit, other], ["rid_one", "rid_two"])
    assert unit.group == "rid_one"
    assert other.group == "s1:q"
    assert found == {"rid_one": {1}}
    assert sorted(labels.values()) == ["W1", "W2"]
    assert mod.reference_eps(eps["rid_one"], {1}) == [2, 3]
    seen = []
    monkeypatch.setattr(metrics, "measure", lambda text, banned=None: seen.append(text) or metrics.StyleMetrics())
    mod.reference_metrics(found)
    assert seen == ["\n\n".join(eps["rid_one"][e] for e in (2, 3))]


def test_refs_two_rids_in_one_pair_stop(mod, monkeypatch):
    eps = _fake_refs(monkeypatch)
    unit = mod.Unit("s1", "side", eps["rid_one"][1], eps["rid_two"][1], "a", "b", True, None, "s1:p")
    with pytest.raises(SystemExit):
        mod.assign_groups([unit], ["rid_one", "rid_two"])


def test_missing_ref_stops(mod, monkeypatch):
    _fake_refs(monkeypatch)
    unit = mod.Unit("s1", "side", "가나다 " * 20, "라마바 " * 20, "a", "b", True, None, "s1:p")
    with pytest.raises(SystemExit):
        mod.assign_groups([unit], ["nope"])


def test_output_hides_names_and_text(mod, monkeypatch, capsys, tmp_path):
    ident, side = _set("s1", "ident", "x"), _set("s2", "side", "y", pick_arm=BASE_ARM)
    _install(monkeypatch, ident, side)
    eps = {"ridsecret": {i + 1: _ref_text("x", i) for i in range(4)}}
    monkeypatch.setattr(refs, "texts", lambda rid: eps.get(rid))
    out = tmp_path / "res.json"
    assert mod.main(["run", "s1", "s2", "--refs", "ridsecret", "--held", "W1", "--json", "--out", str(out)]) == 0
    as_json = capsys.readouterr().out
    assert mod.main(["run", "s1", "s2", "--refs", "ridsecret", "--held", "W1"]) == 0
    as_table = capsys.readouterr().out
    assert mod.main(["groups", "s1", "s2", "--refs", "ridsecret"]) == 0
    as_groups = capsys.readouterr().out
    for shown in (as_json, as_table, as_groups, out.read_text(encoding="utf-8")):
        assert shown.strip()
        for token in TOKENS:
            assert token not in shown
    assert json.loads(as_json)["groups"]
    assert "W1" in as_groups


def test_held_scopes_and_unknown_label(mod, monkeypatch):
    _install(monkeypatch, _set("s1", "side", "x"))
    with pytest.raises(SystemExit):
        mod.run(["s1"], [], ["W9"])
    res = mod.run(["s1"], [], ["W1"])
    assert set(res["results"]) == {"all", "dev", "held"}
    assert res["split"] == "held"
    assert res["results"]["held"]["side/author"]["n_units"] == 1
    assert res["results"]["dev"]["side/author"]["n_units"] == 3
    assert res["results"]["all"]["side/author"]["n_units"] == 4
    assert not any("기준선이 유리해요" in w for w in res["warnings"])
    assert any("held: 작품 묶음이 1개뿐이라 구간이 좁게 나와요" in w for w in res["warnings"])
    assert mod.run(["s1"], [], [])["results"]["all"]["side/author"]["metrics"]["body_per_1k"]["boot95"] is not None


def test_gap_sizes_hand_count(mod):
    g = mod.gap_sizes([(1.0, 3.0), (2.0, 2.0), (3.0, 7.0), (None, 1.0)])
    assert g["n"] == 3
    assert g["ref"] == {"median": 2.0, "q1": 1.5, "q3": 2.5}
    assert g["other"]["median"] == 3.0
    assert g["diff_median"] == 2.0
    assert (g["in_ref_iqr"], g["in_ref_iqr_rate"]) == (1, 0.3333)
    assert mod.gap_sizes([]) is None
    assert mod.gap_sizes([(None, 1.0), (2.0, None)]) is None


def _vunit(mod, truth_a, va, vb):
    u = mod.Unit("s", "ident" if truth_a is not None else "side", "", "", "", "", True, truth_a)
    u.values = {name: (va, vb) for name in mod.METRICS}
    return u


def test_sizes_for_picks_sides_by_truth(mod):
    units = [_vunit(mod, True, 1.0, 5.0), _vunit(mod, False, 9.0, 3.0), _vunit(mod, None, 100.0, 200.0)]
    sz = mod.sizes_for(units)
    assert set(sz) == set(mod.METRICS)
    body = sz["body_per_1k"]
    assert body["n"] == 2
    assert body["ref"]["median"] == 2.0
    assert body["other"]["median"] == 7.0
    assert sz["emotion_per_1k"]["note"] == mod.UNVERIFIED_NOTE
    assert "note" not in body


def test_run_sizes_only_on_ident_truth(mod, monkeypatch, capsys):
    _install(monkeypatch, _set("s1", "ident", "x"), _set("s2", "side", "y"))
    res = mod.run(["s1", "s2"], [], [])["results"]["all"]
    assert set(res["ident/truth"]["sizes"]) == set(mod.METRICS)
    assert "sizes" not in res["ident/author"]
    assert "sizes" not in res["side/author"]
    emo = res["ident/truth"]["sizes"]["emotion_per_1k"]
    assert emo is None or "note" in emo
    assert mod.main(["run", "s1", "s2"]) == 0
    shown = capsys.readouterr().out
    assert "크기 " in shown
    assert mod.main(["run", "s1", "s2", "--json"]) == 0
    as_json = capsys.readouterr().out
    for text in (shown, as_json):
        for token in TOKENS:
            assert token not in text


# ---------- pairs 하위 명령 ----------

def _pair(i: int, rid: str = "ridsecret", names=("라온",)) -> dict:
    return {"ref": _ref_text("r", i), "base": _base_text("b", i), "names": list(names), "rid": rid, "order": i}


def _write_pairs(tmp_path, name: str, pairs: list) -> str:
    p = tmp_path / name
    p.write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_load_pair_file(mod, tmp_path):
    good = _write_pairs(tmp_path, "g.json", [_pair(1), _pair(2)])
    assert len(mod.load_pair_file(good)) == 2
    bad = _write_pairs(tmp_path, "b.json", [{"ref": "a", "base": "b", "rid": "r"}])
    with pytest.raises(SystemExit):
        mod.load_pair_file(bad)
    with pytest.raises(SystemExit):
        mod.load_pair_file(_write_pairs(tmp_path, "d.json", {"ref": 1}))


def test_file_summary_sizes_and_length_ratio(mod):
    pairs = [_pair(i) for i in (1, 2, 3)]
    res = mod.file_summary(pairs, {})
    body = res["sizes"]["body_per_1k"]
    assert body["other"]["median"] > body["ref"]["median"]
    ratios = sorted(len(p["base"].strip()) / len(p["ref"].strip()) for p in pairs)
    assert res["length_ratio_median"] == round(ratios[1], 4)
    assert res["n"] == 3
    assert res["sizes"]["style_distance"] is None


def _vals(body, emo, dist=1.0):
    return {"body_per_1k": (0.0, body), "emotion_per_1k": (0.0, emo), "style_distance": (0.0, dist)}


def test_compare_files_hand_count(mod):
    first = {("r", 1): _vals(5, 5), ("r", 2): _vals(5, 5), ("r", 3): _vals(5, 5), ("r", 4): _vals(1, 1)}
    other = {("r", 1): _vals(3, 8), ("r", 2): _vals(7, 2), ("r", 3): _vals(5, 5), ("r", 5): _vals(1, 1)}
    other[("r", 3)]["style_distance"] = (0.0, None)
    res = mod.compare_files([first, other])
    assert len(res) == 1
    c = res[0]
    assert c["common"] == 3
    body = c["body_per_1k"]
    assert (body["better"], body["worse"], body["equal"], body["missing"]) == (1, 1, 1, 0)
    emo = c["emotion_per_1k"]
    assert (emo["better"], emo["worse"], emo["equal"]) == (1, 1, 1)
    assert (c["style_distance"]["equal"], c["style_distance"]["missing"]) == (2, 1)
    assert (body["base_median"], body["cand_median"]) == (5.0, 5.0)


def test_pairs_command_hides_text_and_names(mod, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(refs, "texts", lambda rid: None)
    names = ("ZQXTOKEN인물",)
    f1 = _write_pairs(tmp_path, "one.json", [_pair(i, names=names) for i in (1, 2, 3)])
    f2 = _write_pairs(tmp_path, "two.json", [_pair(i, names=names) for i in (2, 3, 4)])
    assert mod.main(["pairs", f1, f2]) == 0
    text = capsys.readouterr().out
    assert "F2 대 F1" in text and "W1" in text
    out = tmp_path / "o.json"
    assert mod.main(["pairs", f1, f2, "--json", "--out", str(out)]) == 0
    dumped = capsys.readouterr().out + out.read_text(encoding="utf-8")
    assert json.loads(out.read_text(encoding="utf-8"))["compare"][0]["common"] == 2
    for blob in (text, dumped):
        for token in (*TOKENS, "인물", "손가락이", "조용한"):
            assert token not in blob
