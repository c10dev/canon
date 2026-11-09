"""판단기 평가 세트 스크립트 (scripts/judge_eval.py). mock LLM · mock 판단기, 실제 호출 없음."""
import importlib.util
import json
from pathlib import Path

from canon.schema import Finding
from tests.test_serial import _plan_arc, _serial


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "judge_eval.py"
    spec = importlib.util.spec_from_file_location("judge_eval", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _work(src: Path) -> None:
    """1~8화에 본문이 있고, 8화에 고친 사실 지적(근거 2화) 하나와 고친 동선 지적 하나가 있는 장편."""
    p = _serial()
    a = _plan_arc(p)
    for n in range(a.start_ep, a.start_ep + 8):
        e = p.episode(n)
        e.status = "written"
        e.text = (f"{n}화 본문. 서윤은 낡은 등대 아래에서 오래 기다렸다. 바람이 거세게 불어 파도가 높았다.\n"
                  f"서윤은 동생 민재가 열일곱 살이라고 말했다. 그녀는 손에 든 등불을 내려놓았다.\n"
                  f"멀리서 배 한 척이 천천히 다가오고 있었다. 민재는 아무 말 없이 고개를 끄덕였다.")
    last = p.episode(a.start_ep + 7)
    last.findings = [
        Finding(id="f1", type="사실", description="나이", source_episode=a.start_ep + 1,
                source_quote="서윤은 동생 민재가 열일곱 살이라고 말했다.", current_quote="서윤은 동생 민재가 스무 살이라고 말했다.", status="fixed"),
        Finding(id="f2", type="동선", description="손", source_episode=a.start_ep + 7,
                source_quote="등불을 내려놓았다", current_quote="그녀는 등불을 높이 들었다.", status="fixed"),
    ]
    (src / "work").mkdir(parents=True)
    (src / "work" / "project.json").write_text(p.model_dump_json(), encoding="utf-8")


def test_sentences_and_has_source():
    m = _script()
    assert m.sentences("짧다. 서윤은 낡은 등대 아래에서 오래 기다렸다. \"정말 그랬어?\" 민재가 물었다.") == [
        "짧다. 서윤은 낡은 등대 아래에서 오래 기다렸다.", "\"정말 그랬어?\" 민재가 물었다."]
    assert m.has_source("민재가 열일곱 살이라고 말했다", "[2화 발췌]\n서윤은 동생 민재가 열일곱 살이라고 말했다.") is True
    assert m.has_source("민재가 열일곱 살이라고 말했다", "자료 없음") is False
    assert m.has_source("abc", "자료") is None


def test_build_and_run_with_mock(tmp_path, capsys):
    m = _script()
    _work(tmp_path / "src")
    out = tmp_path / "set.jsonl"
    m.main(["build", "--src", str(tmp_path / "src"), "--project", "work", "--provider", "mock",
            "--episodes", "2", "--plants", "2", "--random", "2", "--out", str(out)])
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    src = {r["source"] for r in rows}
    assert {"plant", "original", "random", "finding"} <= src
    assert sum(r["source"] == "plant" for r in rows) == sum(r["source"] == "original" for r in rows)
    finding = [r for r in rows if r["source"] == "finding"]
    assert len(finding) == 1 and finding[0]["type"] == "사실"  # 같은 화 근거의 동선 지적은 넣지 않는다
    assert finding[0]["cross"] is True and finding[0]["has_source"] is True  # 근거 묶음이 2화 단락을 찾았다
    assert all(r["evidence"] for r in rows)
    assert all(r["claimed"] is True for r in rows if r["source"] == "random")  # mock 진술 뽑기는 문장을 그대로 진술로 낸다
    assert finding[0]["claimed"] is None
    assert len({r["id"] for r in rows}) == len(rows)
    capsys.readouterr()
    m.main(["run", str(out), "--judge", "mock", "--out", str(tmp_path / "probs.jsonl")])
    res = json.loads(capsys.readouterr().out)
    assert res["rows"] == len(rows) and res["low_mass"] == 0
    assert "random" in res["flag_rate"] and "finding·옛근거·근거에 듦" in res["flag_rate"]
    assert len((tmp_path / "probs.jsonl").read_text(encoding="utf-8").splitlines()) == len(rows)
    assert (tmp_path / "src" / "work" / "project.json").exists()  # 원본은 그대로


def test_metrics_and_auc():
    m = _script()
    rows = [{"label": "어긋남", "source": "plant", "cross": True, "has_source": True},
            {"label": "ok", "source": "original", "cross": True, "has_source": True},
            {"label": "ok", "source": "random", "cross": None, "has_source": None}]
    res = m.metrics(rows, [0.9, 0.2, 0.3])
    assert res["flag_rate"]["plant·옛근거·근거에 듦"]["≥0.5"] == 1.0
    assert res["flag_rate"]["original"]["≥0.25"] == 0.0
    assert res["auc_plant_in_evidence_vs_ok"] == 1.0


def test_shuffled_takes_other_episode_evidence():
    m = _script()
    rows = [{"episode": 1, "evidence": "가"}, {"episode": 2, "evidence": "나"}, {"episode": 2, "evidence": "다"}]
    out = m.shuffled(rows, 7)
    assert out[0]["evidence"] in ("나", "다") and out[1]["evidence"] == "가" and out[2]["evidence"] == "가"
    assert rows[0]["evidence"] == "가"  # 원본은 그대로
