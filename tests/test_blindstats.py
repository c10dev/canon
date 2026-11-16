"""가려 읽기 묶음의 쌍 비교 통계 (canon/blindstats.py, canon blind stats)."""
import json

import pytest

from canon import blindset, blindstats, cli, labstats


def _make(pieces, answers=None, reveal=True, no_arm=()):
    """pieces: {대목: [(판, 글)]}. answers: {대목: 이긴 판 | '='} 를 쌍마다 적는다(글 중복이면 쌍을 차례대로 적는 목록)."""
    items, key = [], []
    for piece, arms in pieces.items():
        for arm, text in arms:
            no = f"{len(items) + 1:02d}"
            items.append({"no": no, "text": text})
            key.append({"no": no, "arm": "" if no in no_arm else arm, "piece": piece})
    s = blindset.create("통계 시험", items, key)
    for x in s.items:
        blindset.score(s.id, x.no, 3)
    arm = {k["no"]: k["arm"] for k in key}
    piece = {k["no"]: k["piece"] for k in key}
    left = {p: list(v) if isinstance(v, list) else [v] for p, v in (answers or {}).items()}
    for d in blindset.duels(blindset.load(s.id)):
        want = left.get(piece[d["a"]], [None]).pop(0) if left.get(piece[d["a"]]) else None
        if want is None:
            continue
        pick = blindset.TIE if want == "=" else d["a"] if arm[d["a"]] == want else d["b"]
        blindset.duel(s.id, d["a"], d["b"], pick)
    return blindset.reveal(s.id) if reveal else blindset.load(s.id)


def _base_v2(wins, losses, ties=0):
    """base 대 v2 한 짝: 대목마다 글 둘. 앞에서부터 base 가 이김 · 짐 · 비김."""
    names = [f"장면 {i}" for i in range(wins + losses + ties)]
    pieces = {n: [("base", f"{n} base 글"), ("v2", f"{n} v2 글")] for n in names}
    won = (["base"] * wins) + (["v2"] * losses) + (["="] * ties)
    return pieces, dict(zip(names, won))


def test_counts_rate_and_wilson(client):
    pieces, answers = _base_v2(8, 2)
    st = blindstats.stats(_make(pieces, answers))
    p = st["pairs"][0]
    assert (p["a"], p["b"], p["win"], p["loss"], p["tie"], p["n"], p["rate"]) == ("base", "v2", 8, 2, 0, 10, 0.8)
    assert p["wilson"] == list(labstats.wilson(8, 10)) and p["p"] == labstats.sign_test(8, 10)
    assert p["boot"] and 0 <= p["boot"][0] <= p["boot"][1] <= 1 and p["null"] is False
    assert (st["total"], st["answered"], st["skipped"]) == (10, 10, 0) and st["repeat"] is None
    assert [(r["arm"], r["win"], r["loss"], r["n"]) for r in st["arms"]] == [("base", 8, 2, 10), ("v2", 2, 8, 10)]


def test_ties_are_not_in_n_but_in_tie_rate(client):
    pieces, answers = _base_v2(6, 2, 2)
    p = blindstats.stats(_make(pieces, answers))["pairs"][0]
    assert (p["win"], p["loss"], p["tie"], p["n"]) == (6, 2, 2, 8)
    assert p["tie_rate"] == pytest.approx(2 / 10) and p["rate"] == 0.75


def test_repeated_pair_counts_first_answer_and_repeat(client):
    pieces = {"장면 1": [("base", "가 글"), ("v2", "나 글"), ("base", "가 글"), ("v2", "나 글")],
              "장면 2": [("base", "다 글"), ("v2", "라 글")]}
    s = _make(pieces, {"장면 1": ["base", "v2", "base", "base"], "장면 2": ["v2"]})
    st = blindstats.stats(s)
    p = st["pairs"][0]
    assert (p["win"] + p["loss"], st["answered"], st["total"]) == (2, 5, 5)
    assert st["repeat"]["of"] == 3 and st["repeat"]["same"] == 1
    assert st["repeat"]["flip_rate"] == pytest.approx(2 / 3) and st["repeat"]["flip_wilson"] == list(labstats.wilson(2, 3))


def test_null_pair_is_flagged_and_left_out_of_arms(client):
    names = [f"장면 {i}" for i in range(6)]
    s = _make({n: [("base", f"{n} base"), ("base2", f"{n} base2")] for n in names},
              {n: ("base" if i % 2 else "base2") for i, n in enumerate(names)})
    for order in (("base", "base2"), ("base2", "base")):
        st = blindstats.stats(s, [order])
        assert st["pairs"][0]["null"] is True and st["arms"] == []
    assert blindstats.stats(s)["arms"] != []
    st = blindstats.stats(s, [("base", "v9")])
    assert any("v9" in w for w in st["warnings"])


def test_pair_without_arm_name_is_skipped(client):
    pieces, answers = _base_v2(3, 1)
    s = _make(pieces, answers, no_arm=("01",))
    st = blindstats.stats(s)
    assert st["skipped"] == 1 and st["pairs"][0]["n"] == 3 and any("세지 않은" in w for w in st["warnings"])


def test_short_of_marks():
    def line(n):
        return blindstats._pair_line("a", "b", [{"outs": ["win"], "piece": str(i)} for i in range(n)], False)["short_of"]
    assert (line(16), line(40), line(70)) == (37, 69, None)


def test_cli_stats_refuses_unrevealed_and_prints_json(client, capsys):
    pieces, answers = _base_v2(4, 1)
    open_ = _make(pieces, answers)
    shut = _make(pieces, answers, reveal=False)
    with pytest.raises(SystemExit) as e:
        cli.main(["blind", "stats", shut.id])
    assert e.value.code not in (0, None) and "결과를 열기 전" in str(e.value.code)
    with pytest.raises(SystemExit, match="없는 항목"):
        cli.main(["blind", "stats", "0" * 12])
    with pytest.raises(SystemExit, match="--null"):
        cli.main(["blind", "stats", open_.id, "--null", "base"])
    cli.main(["blind", "stats", open_.id, "--json"])
    assert json.loads(capsys.readouterr().out)["pairs"][0]["win"] == 4
    cli.main(["blind", "stats", open_.id])
    out = capsys.readouterr().out
    assert "base 대 v2: 4승 1패 0비김" in out and "판마다 이긴 비율:" in out
    cli.main(["blind", "stats", "--json"])
    assert [x["id"] for x in json.loads(capsys.readouterr().out)] == [open_.id]
