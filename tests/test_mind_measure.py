"""심리 세 값 측정 스크립트 (scripts/mind_measure.py). LLM 은 가짜 객체로 갈음한다."""
import importlib.util
import json
from pathlib import Path

import pytest


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "mind_measure.py"
    spec = importlib.util.spec_from_file_location("mind_measure", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mm = _script()


def _eps(n, size=40):
    return [(i, f"{i}화 지문이다. 아마 그는 생각했다.\n'속말'\n" + "가" * size) for i in range(1, n + 1)]


def test_pick_eps_long_and_short():
    nums, can3 = mm.pick_eps(_eps(80), 20, 7, "R1", 31)
    assert can3 and len(nums) == 20 and nums == sorted(nums) and min(nums) >= 31
    assert mm.pick_eps(_eps(80), 20, 7, "R1", 31)[0] == nums
    assert mm.pick_eps(_eps(80), 20, 8, "R1", 31)[0] != nums
    nums, can3 = mm.pick_eps(_eps(30), 20, 7, "C1", 31)
    assert not can3 and nums == list(range(4, 31))


class FakeLLM:
    def __init__(self, items=None, fail=False):
        self.calls = []
        self.items = items if items is not None else []
        self.fail = fail

    def json(self, system, prompt, schema, hint=None):
        self.calls.append(schema.__name__)
        if schema is mm.EpSummary:
            return mm.EpSummary(line="한 줄")
        if self.fail:
            raise ValueError("bad")
        return mm.MindLabels(items=[mm.MindLabel(**i) for i in self.items])


def test_summarize_caches(tmp_path):
    llm = FakeLLM()
    cache = tmp_path / "s.json"
    got = mm.summarize(llm, _eps(5), cache, upto=4)
    assert sorted(got) == [1, 2, 3] and len(llm.calls) == 3
    mm.summarize(llm, _eps(5), cache, upto=4)
    assert len(llm.calls) == 3
    assert len(mm.summarize(llm, _eps(5), cache)) == 5


def test_label_ep_keeps_only_allowed_keys():
    items = [{"kind": "마음", "source_ep": 3, "who": "본인", "at": 5},
             {"kind": "마음", "source_ep": 9, "who": "남", "at": 10 ** 6},
             {"kind": "줄거리", "who": "남", "at": -4}]
    got = mm.label_ep(FakeLLM(items), 6, "가" * 100, {1: "a"})
    assert all(set(x) == {"ep", "at", "kind", "source_ep", "who"} for x in got)
    assert [x["source_ep"] for x in got] == [3, None, None]
    assert [x["at"] for x in got] == [5, 100, 0]


def test_label_schema_has_no_dict():
    for model in (mm.MindLabels, mm.MindLabel, mm.EpSummary):
        assert "additionalProperties" not in json.dumps(model.model_json_schema())


def _labels():
    def row(*dists, ep):
        return {"labels": [{"ep": ep, "at": 0, "kind": "마음", "source_ep": ep - d, "who": "본인"} for d in dists]}

    def work(kind, can3, eps):
        return {"kind": kind, "can3": can3, "chars": {str(e): 1000 for e in eps},
                "v1": {str(e): {"thought_per_1k": 1.0, "inner_line_share": 0.1} for e in eps},
                "eps": {str(e): row(2, 20, ep=e) for e in eps}}
    return {"works": {"R1": work("ref", True, [40, 41]), "R2": work("ref", True, [40, 41]), "C1": work("canon", False, [10, 11])}}


def test_table_counts_and_labels():
    labels = _labels()
    labels["works"]["C1"]["eps"]["10"]["again"] = [{"ep": 10, "at": 0, "kind": "마음", "source_ep": 8, "who": "본인"}]
    t = mm.table(labels)
    assert t["works"]["R1"]["v2"]["value"] == 10.0   # 화마다 1건 / 1000자 = 1만 자당 10건
    assert t["works"]["R1"]["v3"]["value"] == 10.0
    assert t["works"]["C1"]["v3"]["note"] == "못 잼"
    assert t["jitter"]["pairs"] == 1 and t["jitter"]["v3_gap_mean"] == 1.0
    assert t["v1_verdicts"]["thought_per_1k"]["verdict"] == "검증 값 없음"
    assert t["groups"]["ref"]["v3_eps"] == 4


def test_table_verdict_and_md_order():
    agree = {"thought_per_1k": {"agree": 24, "n": 37}, "inner_line_share": {"agree": 23, "n": 37}}
    t = mm.table(_labels(), agree)
    assert t["v1_verdicts"]["thought_per_1k"]["verdict"] == "가른다"
    assert t["v1_verdicts"]["inner_line_share"]["verdict"] == "못 가른다"
    md = mm.table_md(t)
    assert md.index("판정 규칙") < md.index("| 글 |")
    assert "R1" in md and "C1" in md


def test_agree_rows_reads_metric_agree_json(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"results": {"all": {"ident/truth": {"metrics": {
        "thought_per_1k": {"agree": 25, "n": 37}, "body_per_1k": {"agree": 1, "n": 37}}}}}}), encoding="utf-8")
    assert mm._agree_rows(str(f)) == {"thought_per_1k": {"agree": 25, "n": 37}}


class _Args:
    repeat = 2
    dry_run = False
    model = "mock:x"


def _sampled(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "load_eps", lambda kind, ident: _eps(60))
    out = tmp_path / "out"
    mm.main(["sample", "--projects", "작품가", "--per", "5", "--seed", "1", "--min-ep", "31", "--out", str(out / "samples.json")])
    return out


def _args(out, repeat):
    a = _Args()
    a.samples, a.out, a.repeat = str(out / "samples.json"), str(out / "labels.json"), repeat
    return a


def test_sample_label_table_end_to_end(tmp_path, monkeypatch, capsys):
    out = _sampled(tmp_path, monkeypatch)
    samples = json.loads((out / "samples.json").read_text(encoding="utf-8"))
    assert "가가가" not in json.dumps(samples) and len(samples["works"]["C1"]["eps"]) == 5
    assert "작품가" not in capsys.readouterr().out
    assert mm.main(["label", "--samples", str(out / "samples.json"), "--repeat", "2", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["calls"] > 0
    items = [{"kind": "마음", "source_ep": 2, "who": "본인", "at": 3}]
    assert mm.cmd_label(_args(out, 2), FakeLLM(items)) == 0
    labels = json.loads((out / "labels.json").read_text(encoding="utf-8"))
    assert labels["errors"] == 0 and labels["calls"] == 7
    assert "가가가" not in json.dumps(labels)
    capsys.readouterr()
    mm.main(["table", "--labels", str(out / "labels.json"), "--out-md", str(out / "T.md"), "--out-json", str(out / "T.json")])
    assert "작품가" not in (out / "T.md").read_text(encoding="utf-8")
    assert "작품가" not in (out / "T.json").read_text(encoding="utf-8")
    assert "작품가" not in capsys.readouterr().out


def test_label_stops_on_format_errors(tmp_path, monkeypatch):
    out = _sampled(tmp_path, monkeypatch)
    assert mm.cmd_label(_args(out, 0), FakeLLM(fail=True)) == 2


def test_dry_run_cost_is_small():
    samples = {"works": {"C1": mm.sample_work("C1", "canon", _eps(60), 5, 1, 31)}}
    got = mm.dry_run(samples, {"C1": _eps(60)}, "coralbricks:deepseek-v4.1-flash-value", 2)
    assert got["calls"] > 7 and 0 < got["cost_usd"] < 5
    with pytest.raises(SystemExit):
        mm.dry_run(samples, {"C1": _eps(60)}, "coralbricks:없는모델", 2)


class ByEpLLM:
    """화 번호로 정해진 답을 내는 가짜 LLM. flaky 의 첫 호출은 예외, sum_fail 화의 요약은 늘 예외."""

    def __init__(self, flaky=False, sum_fail=None):
        self.calls = []
        self.flaky = flaky
        self.sum_fail = sum_fail
        self.seen = set()

    def json(self, system, prompt, schema, hint=None):
        import re
        n = int(re.search(r"(\d+)화 본문", prompt).group(1))
        self.calls.append((schema.__name__, n))
        if schema is mm.EpSummary:
            if n == self.sum_fail:
                raise ValueError("bad")
            return mm.EpSummary(line=f"{n}번 요약")
        if self.flaky and (schema.__name__, n) not in self.seen:
            self.seen.add((schema.__name__, n))
            raise ValueError("first")
        return mm.MindLabels(items=[mm.MindLabel(kind="마음", source_ep=n - 1, who="본인", at=n)])


def _run(out, llm, **kw):
    a = _args(out, kw.pop("repeat", 1))
    for k, v in kw.items():
        setattr(a, k, v)
    mm.cmd_label(a, llm)
    return json.loads((out / "labels.json").read_text(encoding="utf-8"))


def test_retries_and_err_field(tmp_path, monkeypatch):
    out = _sampled(tmp_path, monkeypatch)
    ok = _run(out, ByEpLLM(flaky=True), repeat=0, retries=1)
    assert all(r["labels"] is not None and "err" not in r for r in ok["works"]["C1"]["eps"].values())
    bad = _run(out, ByEpLLM(flaky=True), repeat=0, retries=0)
    rows = bad["works"]["C1"]["eps"].values()
    assert all(r["labels"] is None and r["err"] == "ValueError" for r in rows)


def test_workers_do_not_change_result(tmp_path, monkeypatch):
    out = _sampled(tmp_path, monkeypatch)
    one = _run(out, ByEpLLM(), workers=1)
    for f in out.glob("summaries-*.json"):
        f.unlink()
    three = _run(out, ByEpLLM(), workers=3)
    assert one == three


def test_resume_calls_only_missing_ep(tmp_path, monkeypatch):
    out = _sampled(tmp_path, monkeypatch)
    first = _run(out, ByEpLLM(), repeat=0)
    ep = sorted(first["works"]["C1"]["eps"], key=int)[2]
    first["works"]["C1"]["eps"][ep]["labels"] = None
    (out / "labels.json").write_text(json.dumps(first), encoding="utf-8")
    llm = ByEpLLM()
    again = _run(out, llm, repeat=0, resume=True)
    assert [c for c in llm.calls if c[0] == "MindLabels"] == [("MindLabels", int(ep))]
    assert again["works"]["C1"]["eps"][ep]["labels"] is not None


def test_summary_failure_does_not_stop(tmp_path, monkeypatch):
    out = _sampled(tmp_path, monkeypatch)
    low = min(json.loads((out / "samples.json").read_text(encoding="utf-8"))["works"]["C1"]["eps"])
    got = _run(out, ByEpLLM(sum_fail=low - 1), repeat=0)
    assert got["works"]["C1"]["summary_errors"] == 1 and got["summary_errors"] == 1
