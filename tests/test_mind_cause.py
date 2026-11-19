"""심리 이어짐 원인 가르기 스크립트 (scripts/mind_cause.py). 지어낸 자료와 가짜 LLM 으로 시험한다."""
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from canon import llm as llm_mod
from canon import prompts


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "mind_cause.py"
    spec = importlib.util.spec_from_file_location("mind_cause", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mc = _script()
FLASH = "coralbricks:deepseek-v4.1-flash"
NAME = "작품갑"
HIDE = ("작품갑", "인물갑", "본문구절갑", "요청구절갑")


# ---------- 가짜 자료 ----------

def _prompt(n: int) -> str:
    shift = prompts.WRITE_SHIFT_LINE
    return ("# 확정된 사실 (이번 화와 관련된 것만, 3개 생략)\n"
            f"- ({n - 1}화) 요청구절갑 일\n- ({n - 5}화) 요청구절갑 이전 일\n- ({n - 20}화) 요청구절갑 먼 일\n"
            f"# 직전 화 끝부분\n본문구절갑\n# 지시\n인물갑 {shift}다른 인물의 속마음은 행동과 대사로만\n")


def _q(n: int):
    plot = SimpleNamespace(carry=[1, 2])
    ep = SimpleNamespace(plot=plot)
    chars = [SimpleNamespace(name="인물갑", id="c1"), SimpleNamespace(name="없는이", id="c2")]
    states = [SimpleNamespace(character_id="c1", emotional_state=" 불안 "), SimpleNamespace(character_id="c2", emotional_state="")]
    return SimpleNamespace(episode=lambda k: ep, trails=[1], characters=chars, states=states)


def _fake_p(nums, words=100):
    eps = [SimpleNamespace(plot=SimpleNamespace(number=n), text=f"본문구절갑 {n}") for n in nums]
    return SimpleNamespace(episodes=eps, meta=SimpleNamespace(words_per_episode=words), style_baseline=None)


@pytest.fixture
def fake_world(monkeypatch):
    nums = list(range(1, 31))
    p = _fake_p(nums)
    monkeypatch.setattr(mc.store, "load", lambda name: p)
    monkeypatch.setattr(mc.tm, "snapshot_eps", lambda pp: list(nums))
    monkeypatch.setattr(mc.tm, "canon_episodes", lambda name, start: [(n, f"본문구절갑 {n} 아마 그는 생각했다.\n'속말'\n" + "가" * 60) for n in nums])
    monkeypatch.setattr(mc.cm, "exact_ok", lambda pp, n: n != 7)
    monkeypatch.setattr(mc.cm, "rebuild", lambda pp, n, mode: _q(n))
    monkeypatch.setattr(mc.cm, "body_of", lambda pp, n: f"본문구절갑 {n} 아마 그는 생각했다.\n'속말'\n" + "가" * 60)
    monkeypatch.setattr(mc.prompts, "episode_prompt", lambda q, n, *a, **k: _prompt(n))
    monkeypatch.setattr(mc.prompts, "write_head", lambda q, n: "# 확정된 사실")
    monkeypatch.setattr(mc.prompts, "writer_system", lambda q: "시스템")
    return p


def _assert_clean(*texts):
    for t in texts:
        for h in HIDE:
            assert h not in t


# ---------- 작은 함수 ----------

def test_block_name_examples():
    assert mc.block_name("확정된 사실 (이번 화와 관련된 것만, 222개 생략)") == "확정된 사실"
    assert mc.block_name("인물 현재 상태 (87화 종료 시점) (…)") == "인물 현재 상태"
    assert mc.block_name("현재 구간: 무엇 (1~3화)") == "현재 구간"
    assert mc.block_name("12화 본문") == "N화 본문"


def test_work_keys_uses_keymap_then_numbers(tmp_path):
    km = tmp_path / "keymap.json"
    km.write_text(json.dumps({"C2": {"kind": "canon", "ident": "을"}, "R1": {"kind": "ref", "ident": "x"}}), encoding="utf-8")
    assert mc.work_keys(["갑", "을", "병"], str(km)) == {"을": "C2", "갑": "C1", "병": "C3"}
    assert mc.work_keys(["갑", "을"], None) == {"갑": "C1", "을": "C2"}


def test_arm_prompts():
    base = "앞 " + prompts.WRITE_SHIFT_LINE + "뒤"
    got = mc.arm_prompts(base)
    assert got["B1"] == base and got["B2"] == base
    assert got["S"] == base.replace(prompts.WRITE_SHIFT_LINE, "", 1)
    assert got["M"] == base + "\n" + mc.M_LINE
    assert mc.arm_prompts("그 글자열 없음")["S"] is None


def test_arm_prompts_p_and_t():
    base = "앞 문장. " + mc.P_SENTENCE + " 뒤"
    got = mc.arm_prompts(base)
    assert got["P"] == "앞 문장. 뒤"
    assert got["T"] == base + "\n" + mc.T_LINE
    assert mc.arm_prompts("문장 없음")["P"] is None
    assert mc.ARMS == ("B1", "B2", "S", "M") and mc.ALL_ARMS == mc.ARMS + ("P", "T")


def test_line_blocks_p_or_t_alone():
    assert mc._line_blocks({"B1": 1.0, "B2": 1.2, "P": 3.0})[0] is True
    assert mc._line_blocks({"B1": 1.0, "B2": 1.2, "T": 3.0})[0] is True
    assert mc._line_blocks({"B1": 1.0, "B2": 1.2, "T": 1.1})[0] is False


def test_dry_run_p_not_applicable_dropped(abl_world, monkeypatch):
    monkeypatch.setattr(mc.prompts, "episode_prompt", lambda q, n, *a, **k: "# 지시\n줄 없음")
    got = mc.ablate_dry_run(mc.store.load(NAME), [70], list(mc.ALL_ARMS), FLASH, FLASH, set())
    assert got["write"]["calls"] == 4


def _item(src, block="인물 현재 상태", kind="마음"):
    return {"block": block, "source_ep": src, "kind": kind}


def _label(src, kind="마음"):
    return {"ep": 20, "at": 0, "kind": kind, "source_ep": src, "who": "본인"}


def test_match_ep_within_one_ep():
    got = mc.match_ep(20, [_item(19), _item(5), _item(None)], [_label(18), _label(8)])
    assert got["mat"] == {"near": 1, "mid": 0, "far": 1, "unknown": 1}
    assert got["used"] == {"near": 1, "mid": 0, "far": 0}
    assert got["body"] == {"near": 1, "far": 1}
    assert got["grounded"] == {"near": 1, "far": 0}
    two = mc.match_ep(20, [_item(19)], [_label(17)])
    assert two["used"]["near"] == 0 and two["grounded"]["near"] == 0


def test_match_ep_ignores_non_mind_labels():
    got = mc.match_ep(20, [_item(19)], [_label(19, "줄거리")])
    assert got["used"]["near"] == 0 and got["body"] == {"near": 0, "far": 0}


def _use(median, expected, used, eps=20, unknown=0.1, jit=0.1):
    cell = {"median": median, "q1": median, "q3": median, "used_ratio": used, "grounded": 0.5, "ungrounded": 0.5, "expected": expected}
    return {"all": {"eps": eps, "v2": cell, "v3": cell, "unknown_share": unknown, "jitter": {"v2": jit, "v3": jit}}}


def _abl(**vals):
    return {"arms": {arm: {"summary": {"v2": v, "v3": v}} for arm, v in vals.items()}}


def test_verdict_no_material_and_unused():
    assert mc.verdicts(_use(1, 3, 0.9), None)["v2"]["verdict"] == "재료 없음"
    unused = mc.verdicts(_use(5, 3, 0.2), None)["v2"]
    assert unused["unused"] and not unused["no_material"] and unused["verdict"] == "있는데 안 씀"
    fine = mc.verdicts(_use(5, 3, 0.9), None)["v2"]
    assert fine["verdict"] == "해당 없음" and fine["line_blocks"] is None


def test_verdict_line_blocks_and_undecided():
    use = _use(5, 3, 0.9)
    yes = mc.verdicts(use, _abl(B1=1.0, B2=1.2, S=3.0, M=1.0, X=1.1))["v2"]
    assert yes["line_blocks"] and yes["verdict"] == "줄이 막음" and not yes["old_vs_new"]
    no = mc.verdicts(use, _abl(B1=1.0, B2=2.0, S=1.8, M=1.0, X=1.5))["v2"]
    assert no["line_blocks"] is False
    only_m = mc.verdicts(use, {"arms": {"B1": {"summary": {"v2": 1.0}}, "B2": {"summary": {"v2": 1.0}},
                                         "S": {"summary": None}, "M": {"summary": {"v2": 2.0}}}})["v2"]
    assert only_m["line_blocks"]
    for bad in (_use(5, 3, 0.9, eps=5), _use(5, 3, 0.9, unknown=0.6), _use(5, 3, 0.9, jit=9)):
        assert mc.verdicts(bad, None)["v2"]["verdict"] == "못 가름"
    assert mc.verdicts(None, None)["v2"]["verdict"] == "자료 없음"


def test_verdict_old_vs_new_line():
    got = mc.verdicts(None, _abl(B1=1.0, B2=1.1, X=3.0))["v3"]
    assert got["old_vs_new"] is True
    assert mc.verdicts(None, _abl(B1=1.0, B2=1.5, X=1.2))["v3"]["old_vs_new"] is False


# ---------- scan ----------

def _scan_args(tmp_path, samples=True):
    return SimpleNamespace(projects=[NAME], keymap=None, out=str(tmp_path / "scan.json"),
                           samples_out=str(tmp_path / "samples" / "samples.json") if samples else None)


def test_scan_ep_fields(fake_world):
    row = mc.scan_ep(fake_world, 25)
    assert row["facts"] == {"1-3": 1, "4-10": 1, "10+": 1}
    assert row["carry"] == 2 and row["trails"] == 1
    assert row["emo_chars"] == 1 and row["emo_len_median"] == 2
    assert row["shift_line"] == 1 and row["pov_line"] == 1
    assert row["blocks"]["직전 화 끝부분"] == row["tail_chars"] > 0
    assert mc.scan_ep(fake_world, 7) is None


def test_scan_writes_clean_json_and_samples(fake_world, tmp_path, capsys):
    mc.cmd_scan(_scan_args(tmp_path))
    out = capsys.readouterr().out
    scan = (tmp_path / "scan.json").read_text(encoding="utf-8")
    samples = (tmp_path / "samples" / "samples.json").read_text(encoding="utf-8")
    keymap = json.loads((tmp_path / "samples" / "keymap.json").read_text(encoding="utf-8"))
    _assert_clean(out, scan, samples)
    assert out.strip() == "C1 대상 화 26 모름 1"
    data = json.loads(scan)["works"]["C1"]
    assert data["unknown"] == [7] and data["targets"] == 26
    assert keymap == {"C1": {"kind": "canon", "ident": NAME}}
    s = json.loads(samples)["works"]["C1"]
    assert 7 not in s["eps"] and not s["can3"] and set(s["v1"][str(s["eps"][0])]) == {"thought_per_1k", "inner_line_share"}


def test_samples_feed_mind_measure_dry_run(fake_world, tmp_path):
    mc.cmd_scan(_scan_args(tmp_path))
    mm = mc.mm
    samples = json.loads((tmp_path / "samples" / "samples.json").read_text(encoding="utf-8"))
    loaded = {"C1": mc.tm.canon_episodes(NAME, 1)}
    got = mm.dry_run(samples, loaded, FLASH, 2)
    assert got["calls"] > 0


def test_samples_keymap_conflict_stops(fake_world, tmp_path):
    (tmp_path / "samples").mkdir()
    (tmp_path / "samples" / "keymap.json").write_text(json.dumps({"C1": {"kind": "canon", "ident": "다른"}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="keymap.json"):
        mc.cmd_scan(_scan_args(tmp_path))


# ---------- material ----------

class MatLLM:
    def __init__(self, items=None, cut=False, fail=False):
        self.items = items if items is not None else [mc.MaterialItem(block="인물 현재 상태 (87화)", source_ep=1, kind="마음")]
        self.last_finish = ""
        self.cut = cut
        self.fail = fail
        self.calls = 0

    def json(self, system, prompt, schema, hint=None):
        self.calls += 1
        self.last_finish = "length" if self.cut else "stop"
        if self.fail:
            raise ValueError("bad")
        return mc.MaterialItems(items=self.items)


def test_material_schema_has_no_dict():
    for model in (mc.MaterialItems, mc.MaterialItem):
        assert "additionalProperties" not in json.dumps(model.model_json_schema())


def test_material_ep_cleans_source_and_block():
    items = [mc.MaterialItem(block="12화 본문", source_ep=n, kind="마음") for n in (5, 9, 10, 0, None)]
    got = mc.material_ep(MatLLM(items), 9, "요청구절갑", None)
    assert [x["source_ep"] for x in got] == [5, None, None, None, None]
    assert all(set(x) == {"block", "source_ep", "kind"} and x["block"] == "N화 본문" for x in got)


def test_material_ep_cut_response_is_error():
    with pytest.raises(llm_mod.OutputCut):
        mc.material_ep(MatLLM(cut=True), 9, "p", None)
    res, err = mc._try_material(MatLLM(cut=True), 9, "p", 1, None)
    assert res is None and err == "OutputCut"


def _mat_args(tmp_path, **kw):
    a = SimpleNamespace(projects=[NAME], keymap=None, model=FLASH, repeat=2, workers=1, retries=0, timeout=None,
                        max_out=4000, resume=False, dry_run=False, out=str(tmp_path / "material.json"))
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_material_run_is_clean_and_counts(fake_world, tmp_path, capsys):
    assert mc.cmd_material(_mat_args(tmp_path), MatLLM()) == 0
    text = (tmp_path / "material.json").read_text(encoding="utf-8")
    _assert_clean(text, capsys.readouterr().out)
    doc = json.loads(text)
    assert doc["errors"] == 0 and doc["calls"] == 26 + 2
    row = doc["works"]["C1"]["eps"]["4"]
    assert row["items"] == [{"block": "인물 현재 상태", "source_ep": 1, "kind": "마음"}] and "again" in row


def test_material_stops_on_format_errors(fake_world, tmp_path):
    assert mc.cmd_material(_mat_args(tmp_path), MatLLM(fail=True)) == 2


def test_material_full_list_counts_as_capped(fake_world, tmp_path):
    items = [mc.MaterialItem(block="b", source_ep=1, kind="마음")] * mc.MATERIAL_MAX
    assert mc.cmd_material(_mat_args(tmp_path), MatLLM(items)) == 2
    doc = json.loads((tmp_path / "material.json").read_text(encoding="utf-8"))
    assert doc["works"]["C1"]["eps"]["4"]["err"] == "Capped"


def test_material_resume_skips_done(fake_world, tmp_path):
    mc.cmd_material(_mat_args(tmp_path), MatLLM())
    llm = MatLLM()
    mc.cmd_material(_mat_args(tmp_path, resume=True), llm)
    assert llm.calls == 0


def test_material_dry_run_does_not_call_llm(fake_world, capsys):
    by_ep = {n: "가" * 100 for n in range(4, 14)}
    got = mc.material_dry_run({"C1": by_ep, "C2": {4: "가", 5: "가"}}, FLASH, 5)
    assert got["calls"] == (10 + 5) + (2 + 2) and 0 < got["cost_usd"] < 5
    assert got["chars"] == 15 * (100 + len(mc.MATERIAL_SYSTEM)) + 4 * (1 + len(mc.MATERIAL_SYSTEM))
    mc.cmd_material(_mat_args(Path("."), dry_run=True, out=None), llm=None)
    assert json.loads(capsys.readouterr().out)["calls"] == 26 + 2


def test_out_is_required_without_dry_run():
    with pytest.raises(SystemExit, match="--out"):
        mc.main(["material", "--projects", "갑"])
    with pytest.raises(SystemExit, match="--out"):
        mc.main(["ablate", "--project", "갑"])


# ---------- use · table ----------

def _material_doc():
    return {"works": {"C1": {"eps": {"20": {"items": [_item(19), _item(5), _item(None)], "again": [_item(19)]},
                                     "21": {"items": None, "err": "OutputCut"}}}}}


def _labels_doc():
    lab = {"labels": [_label(18), _label(5)]}
    return {"works": {"C1": {"chars": {"20": 10000, "21": 10000}, "eps": {"20": lab, "21": lab}}}}


def test_use_table_counts_and_missing():
    m1 = {"works": {"R1": {"kind": "ref", "v2": {"value": 2.0}, "v3": {"value": 1.0}}, "C1": {"kind": "canon", "v2": {"value": 0.1}}}}
    u = mc.use_table(_material_doc(), _labels_doc(), m1)
    w = u["works"]["C1"]
    assert w["eps"] == 1 and w["missing"] == 1
    assert w["v2"]["median"] == 1 and w["v2"]["used_ratio"] == 1.0 and w["v2"]["expected"] == 2.0
    assert w["v3"]["used_ratio"] == 1.0 and w["v3"]["expected"] == 1.0
    assert u["all"]["unknown_share"] == round(1 / 3, 3)
    assert u["all"]["jitter"]["v2"] == 0.0 and u["all"]["jitter"]["v3"] == 1.0
    assert u["rows"] == [{"key": "C1", "ep": 20, "chars": 10000, "near": 1, "far": 1, "unknown": 1}]
    assert mc.use_table(_material_doc(), _labels_doc(), None)["all"]["v2"]["expected"] is None


def test_outputs_have_no_names(fake_world, tmp_path, capsys):
    mc.cmd_scan(_scan_args(tmp_path, samples=False))
    (tmp_path / "m.json").write_text(json.dumps(_material_doc()), encoding="utf-8")
    (tmp_path / "l.json").write_text(json.dumps(_labels_doc()), encoding="utf-8")
    mc.cmd_use(SimpleNamespace(material=str(tmp_path / "m.json"), labels=str(tmp_path / "l.json"), m1=None,
                               out_md=str(tmp_path / "U.md"), out_json=str(tmp_path / "U.json")))
    mc.cmd_table(SimpleNamespace(scan=str(tmp_path / "scan.json"), use=str(tmp_path / "U.json"), ablate=None, m1=None,
                                 out_md=str(tmp_path / "C.md"), out_json=str(tmp_path / "C.json")))
    texts = [(tmp_path / f).read_text(encoding="utf-8") for f in ("scan.json", "U.md", "U.json", "C.md", "C.json")]
    _assert_clean(capsys.readouterr().out, *texts)
    md = texts[3]
    assert md.index("판정 규칙") < md.index("## 요청 훑기") and "원인 가르기 표" in md
    assert json.loads(texts[4])["verdicts"]["v2"]["verdict"] == "못 가름"


def test_table_fills_expected_from_m1(tmp_path):
    m1 = {"works": {"R1": {"kind": "ref", "v2": {"value": 5.0}, "v3": {"value": 5.0}}}}
    u = mc.use_table(_material_doc(), _labels_doc(), None)
    t = mc.table({"works": {}}, u, None, m1)
    assert t["use"]["v2"]["expected"] == 5.0


# ---------- ablate ----------

class WriteBox:
    def __init__(self, fail_eps=()):
        self.calls = []
        self.fail_eps = set(fail_eps)

    def __call__(self, llm, q, n, prompt, *a, **k):
        self.calls.append((n, prompt))
        if n in self.fail_eps:
            raise ValueError("거절")
        return f"새 본문 {n} " + "나" * 50


class LabLLM:
    last_finish = "stop"

    def json(self, system, prompt, schema, hint=None):
        n = int(re.search(r"(\d+)화 본문", prompt).group(1))
        if schema is mc.mm.EpSummary:
            return mc.mm.EpSummary(line="요약")
        return mc.mm.MindLabels(items=[mc.mm.MindLabel(event="e", kind="마음", source_ep=n - 2, who="본인", at=1)])


def _abl_args(tmp_path, **kw):
    a = SimpleNamespace(project=NAME, keymap=None, eps=[70, 75, 80, 86], arms=list(mc.ARMS), write_model=FLASH, label_model=FLASH,
                        summaries=None, workers=1, retries=0, timeout=None, max_out=4000, resume=False, dry_run=False,
                        out=str(tmp_path / "abl"))
    for k, v in kw.items():
        setattr(a, k, v)
    return a


@pytest.fixture
def abl_world(fake_world, monkeypatch):
    nums = list(range(1, 91))
    monkeypatch.setattr(mc.store, "load", lambda name: _fake_p(nums))
    monkeypatch.setattr(mc.tm, "canon_episodes", lambda name, start: [(n, f"본문구절갑 {n} 아마 그는 생각했다.\n'속말'\n" + "가" * 60) for n in nums])
    box = WriteBox()
    monkeypatch.setattr(mc.pipeline, "_write", box)
    return box


def test_ablate_writes_texts_only_under_out(abl_world, tmp_path, capsys):
    assert mc.cmd_ablate(_abl_args(tmp_path), None, LabLLM()) == 0
    out = tmp_path / "abl"
    texts = sorted(p.name for p in (out / "texts").iterdir())
    assert len(texts) == 16 and "C1-70-B1.txt" in texts and "C1-86-M.txt" in texts
    assert sorted(p.name for p in tmp_path.iterdir()) == ["abl"]
    doc = json.loads((out / "ablate.json").read_text(encoding="utf-8"))
    assert doc["key"] == "C1" and doc["eps"] == [70, 75, 80, 86] and set(doc["arms"]) == {"X", "B1", "B2", "S", "M"}
    assert doc["arms"]["B1"]["head_kept"] is True and doc["errors"] == {}
    row = doc["arms"]["B1"]["eps"]["70"]
    assert row["c2"] == 1 and row["chars"] > 0 and doc["arms"]["B1"]["summary"]["v2"] > 0
    _assert_clean(capsys.readouterr().out, json.dumps(doc, ensure_ascii=False))
    assert {p for _, p in abl_world.calls if mc.M_LINE in p}


def test_ablate_stops_when_more_than_half_fail(abl_world, tmp_path, monkeypatch):
    box = WriteBox(fail_eps={70, 75, 80})
    monkeypatch.setattr(mc.pipeline, "_write", box)
    assert mc.cmd_ablate(_abl_args(tmp_path), None, LabLLM()) == 3
    doc = json.loads((tmp_path / "abl" / "ablate.json").read_text(encoding="utf-8"))
    assert doc["errors"]["B1-70"] == "ValueError"
    assert not (tmp_path / "abl" / "texts" / "C1-70-B1.txt").exists()


def test_ablate_keeps_going_when_half_fail(abl_world, tmp_path, monkeypatch):
    monkeypatch.setattr(mc.pipeline, "_write", WriteBox(fail_eps={70, 75}))
    assert mc.cmd_ablate(_abl_args(tmp_path), None, LabLLM()) == 0
    doc = json.loads((tmp_path / "abl" / "ablate.json").read_text(encoding="utf-8"))
    assert doc["arms"]["B1"]["eps"]["70"] == {"err": "NoText"}


def test_ablate_resume_does_not_rewrite(abl_world, tmp_path):
    mc.cmd_ablate(_abl_args(tmp_path), None, LabLLM())
    n = len(abl_world.calls)
    mc.cmd_ablate(_abl_args(tmp_path, resume=True), None, LabLLM())
    assert len(abl_world.calls) == n


def test_ablate_stops_when_stage_write_is_mock(abl_world, tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    with pytest.raises(SystemExit, match="CANON_LLM"):
        mc.cmd_ablate(_abl_args(tmp_path, write_model=mc.WRITE_MODEL), None, LabLLM())
    assert not (tmp_path / "abl").exists()
    assert abl_world.calls == []


def test_ablate_mock_write_model_is_allowed(abl_world, tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    assert mc.cmd_ablate(_abl_args(tmp_path, write_model="mock"), None, LabLLM()) == 0


def test_ablate_dry_run_counts_and_no_llm(abl_world, capsys):
    p = mc.store.load(NAME)
    got = mc.ablate_dry_run(p, [70, 75], list(mc.ARMS), FLASH, FLASH, set())
    assert got["write"]["calls"] == 8 and got["shift_eps"] == 2
    assert got["label"]["calls"] == 74 + 5 * 2 and got["head_kept"]["S"] is True
    assert got["total_usd"] == round(got["write"]["cost_usd"] + got["label"]["cost_usd"], 4)
    fewer = mc.ablate_dry_run(p, [70, 75], list(mc.ARMS), FLASH, FLASH, {1, 2, 3})
    assert fewer["label"]["calls"] == got["label"]["calls"] - 3
    assert abl_world.calls == []
    assert mc.cmd_ablate(_abl_args(Path("."), dry_run=True, out=None), None, None) == 0
    assert json.loads(capsys.readouterr().out.split("\n", 1)[1])["write"]["calls"] == 16
    assert abl_world.calls == []


def test_ablate_dry_run_skips_s_when_not_applicable(abl_world, monkeypatch):
    monkeypatch.setattr(mc.prompts, "episode_prompt", lambda q, n, *a, **k: "# 지시\n줄 없음")
    got = mc.ablate_dry_run(mc.store.load(NAME), [70], list(mc.ARMS), FLASH, FLASH, set())
    assert got["write"]["calls"] == 3 and got["shift_eps"] == 0
