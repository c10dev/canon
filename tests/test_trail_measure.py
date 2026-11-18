"""인물 자취 측정 스크립트 (scripts/trail_measure.py, docs/trail/specs/01-measure.md). LLM 호출 없음."""
import importlib.util
from pathlib import Path

from canon import refs, store
from canon.schema import Character, Project, RefBook, RefCut, RefEp, SettingRecord, StateDelta
from tests.test_context_measure import _project


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "trail_measure.py"
    spec = importlib.util.spec_from_file_location("trail_measure", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tm = _script()


def _eps(n_marks=30):
    text = "".join(f"{'가' * 50}지난번에 {'나' * 40}\n" for _ in range(n_marks))
    return [(11, text[: len(text) // 2]), (12, text[len(text) // 2:])]


def test_find_markers():
    for bad in ("그때서야 알았다", "그때부터 달랐다", "그때야 웃었다"):
        assert tm.find_markers(bad) == []
    got = [m for _, m in tm.find_markers("그때 그는 지난번 일을 했었다")]
    assert got == ["그때", "지난번", "했었"]


def test_sample_work():
    eps = _eps()
    a = tm.sample_work("w", "ref", eps, 10, 1)
    b = tm.sample_work("w", "ref", eps, 10, 1)
    c = tm.sample_work("w", "ref", eps, 10, 2)
    assert [(i["id"], i["ep"], i["at"]) for i in a["items"]] == [(i["id"], i["ep"], i["at"]) for i in b["items"]]
    assert [i["at"] for i in a["items"]] != [i["at"] for i in c["items"]] or [i["ep"] for i in a["items"]] != [i["ep"] for i in c["items"]]
    assert a["markers"] > 10 and len(a["items"]) == 10 and a["items"][0]["id"] == "w-01"
    assert all(len(i["before"]) <= 200 and i["after"].startswith(i["marker"]) for i in a["items"])
    few = tm.sample_work("w", "canon", [(1, "지난번에 그랬다 예전에 그랬다")], 10, 1)
    assert len(few["items"]) == few["markers"] == 2 and few["per10k"] > 0 and few["first"] == few["last"] == 1


def _work(key, kind, n, per10k=100.0):
    return {"key": key, "kind": kind, "eps": 5, "chars": 1000, "markers": 10, "per10k": per10k,
            "items": [{"id": f"{key}-{i:02d}"} for i in range(1, n + 1)]}


def test_tally_and_group():
    w = _work("a", "ref", 5)
    labels = {"a-01": 5, "a-02": {"cat": 8, "dist": 3, "who": "doer", "shift": "shifted"}, "a-03": 1,
              "a-04": {"cat": 6, "who": "witness", "shift": "same"}, "a-05": None}
    t = tm.tally(w, labels)
    assert (t["n"], t["known"], t["unknown"], t["char"]) == (5, 4, 1, 3)
    assert t["share"] == 0.75 and t["char_per10k"] == 75.0
    assert t["who"] == {"doer": 1, "witness": 1} and t["shift"] == {"same": 1, "shifted": 1} and t["dist"] == [3]
    assert t["cats"][1] == 1 and t["cats"][5] == 1 and t["share_ci"][0] < 0.75 < t["share_ci"][1]
    t2 = tm.tally(_work("b", "ref", 2), {"b-01": 5, "b-02": 1})
    g = tm.group([t, t2, tm.tally(_work("c", "canon", 1), {"c-01": 5})], "ref")
    assert (g["n"], g["known"], g["char"], g["markers"], g["chars"]) == (7, 6, 4, 20, 2000)
    assert g["per10k"] == 100.0 and g["char_per10k"] == round(100 * 4 / 6, 2)
    assert "| a |" in tm.table_md([t], [g])


def test_kappa():
    a = {"x1": 1, "x2": 5, "x3": 6, "x4": None}
    same = tm.kappa(a, dict(a))
    assert same["n"] == 3 and same["raw"] == 1.0 and same["kappa"] == 1.0
    k = tm.kappa({"1": 1, "2": 1, "3": 5, "4": 5}, {"1": 1, "2": 5, "3": 5, "4": 5})
    # po 0.75, pe = 0.5*0.25 + 0.5*0.75 = 0.5 → kappa 0.5
    assert k["n"] == 4 and k["agree"] == 3 and k["kappa"] == 0.5 and k["pairs"] == {"1→5": 1}
    assert k["char_raw"] == 0.75
    assert tm.kappa({}, {})["kappa"] is None


def test_verdict():
    low = tm.verdict(tm.m2_tally({"a": "근거", "b": "없음"}), {})
    assert "가르지 않는다" in low[0] and "못 미친다" in low[1]
    short = tm.m2_tally({f"i{i}": ("없음" if i < 8 else "요약" if i < 10 else "근거") for i in range(14)})
    assert short["known"] == 14 and short["short"] > 0.5
    assert "재료가 모자란" in tm.verdict(short, {"a": 2, "b": 3})[0]
    assert "검수 일감(4)을 앞으로" in tm.verdict(short, {"a": 2, "b": 3})[1]
    has = tm.m2_tally({f"i{i}": ("근거" if i < 9 else "없음") for i in range(12)} | {"m": "모름"})
    assert has["known"] == 12 and "모델이 쓰지 않는" in tm.verdict(has, {"a": 1})[0]
    assert "반을 넘지 않는다" in tm.verdict({"known": 10, "short": 0.5, "has": 0.5}, {})[0]


def test_fact_groups():
    p = Project()
    p.characters.append(Character(id="ellen", name="엘렌 하트", role="x", tier="main", speech_style="x"))
    p.facts = ["엘렌은 어릴 때 불에 데어 왼팔에 흉터가 남았다", "엘렌의 왼팔 흉터는 어릴 때 불에 데어 생겼다", "엘렌은 북쪽 항구에서 태어났다"]
    p.history = [StateDelta(episode=9, summary="s", new_facts=[p.facts[0]]), StateDelta(episode=37, summary="s", new_facts=[p.facts[1]])]
    gs = tm.fact_groups(p)
    assert len(gs) == 1 and gs[0]["id"] == "ellen" and gs[0]["span"] == 28
    assert [x["ep"] for x in gs[0]["lines"]] == [9, 37]
    p.setting_log.append(SettingRecord(episode=53, character_id="ellen", field="외모", before="어릴 때 불에 데어 왼팔에 흉터가 남았다", after="왼팔에 흉터가 없다"))
    assert any(x["text"].startswith("[설정 외모]") for g in tm.fact_groups(p) for x in g["lines"])


def test_label_html():
    items = [{"id": "w-01", "ep": 12, "at": 5, "marker": "그때", "before": "<script>alert(1)</script> 앞", "after": "그때 뒤"}]
    h = tm.label_html(items)
    assert "w-01" in h and "&lt;script&gt;alert(1)" in h and "<script>alert(1)" not in h
    assert "<mark>그때</mark>" in h and "labels-author.json" in h and "저장" in h and h.count('type="radio"') == 10


def test_ref_episodes(tmp_path, monkeypatch):
    lines = ["1화", "그때 본문 하나", "2화", "둘째 본문", "외전", "외전 글", "3화", "셋째"]
    cuts = [RefCut(line=0, body=1, label="1"), RefCut(line=2, body=3, label="2"), RefCut(line=4, body=5, label="외전 1", kind="side"),
            RefCut(line=6, body=7, label="3")]
    b = RefBook(id="r", name="r", cuts=cuts, eps=[RefEp(order=i) for i in range(1, 5)])
    monkeypatch.setattr(refs, "load", lambda rid: b)
    monkeypatch.setattr(refs, "source", lambda rid: lines)
    assert tm.ref_episodes("r", 1, 3) == [(1, "그때 본문 하나"), (2, "둘째 본문"), (3, "셋째")]
    assert tm.ref_episodes("r", 2, 2) == [(2, "둘째 본문")]


def test_rebuild_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _project()
    assert "4화" in tm.rebuild_prompt(p, 4)
    assert 4 in tm.snapshot_eps(p)
    p.snapshots = [s for s in p.snapshots if s.episode != 3]
    assert tm.rebuild_prompt(p, 4) is None
    assert 4 not in tm.snapshot_eps(p)
