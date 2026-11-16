"""내용 맞춘 짝 목록 스크립트 (scripts/blind_scene_pairs.py). 지어낸 원고와 가짜 LLM만 쓴다. 실제 LLM 은 만들지 않는다."""
import importlib.util
import json
import random
import threading
from pathlib import Path

import pytest

from canon import refs
from canon.schema import DrillFacts, DrillPerson, RefCut, StudioCandidate, StudioDraft

NAME = "REFNAME_ZZ"
FIELDS = ("line", "body", "head", "label", "title", "kind")
PEOPLE = ("서도윤", "한채린")


def _load(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ep(tag: str) -> str:
    """약 1,300자, 한 줄이 짧은 화. 대목 하나로 잡힌다."""
    return "\n".join(f"M{tag}_{i} 서도윤이 한채린에게 조용히 이렇게 말했다." for i in range(75))


class FakeLLM:
    def __init__(self, fail_facts: bool = False):
        self.calls: list[str] = []
        self.fail_facts = fail_facts
        self.lock = threading.Lock()

    def json(self, system, prompt, schema, hint=None):
        with self.lock:
            self.calls.append(schema.__name__)
            n = len(self.calls)
        if schema is DrillFacts:
            if self.fail_facts:
                raise RuntimeError("실패")
            return DrillFacts(people=[DrillPerson(name=x, note="동료") for x in PEOPLE], pov=PEOPLE[0], place="사무실", time="밤",
                              before="회의가 끝났다", inner=[], events=["도윤이 채린을 찾아간다", "둘이 말다툼한다", "도윤이 자리를 뜬다"])
        assert schema is StudioDraft
        text = "\n".join(" ".join(f"B{n}_{i}_{j} 서도윤은 창가에 서서 오래 기다렸다." for j in range(3)) for i in range(23))
        return StudioDraft(candidates=[StudioCandidate(text=text.replace("창가에", "**창가에**", 1))])


@pytest.fixture()
def home(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_REFS", str(tmp_path / "refs"))
    return tmp_path


def _book(k: int):
    text = "\n\n".join(f"{n}화\n{_ep(f'{k}{n}')}" for n in range(1, 5))
    d = refs.preview(text, repeats=[])
    cuts = [RefCut(**{f: c[f] for f in FIELDS}) for c in d["cuts"] if c["on"]]
    return refs.create(f"{NAME}_{k}", text, cuts, rights=True)


def _run(m, rids, n=3, reps=2, llm=None):
    llm = llm or FakeLLM()
    rows, ps = m.pick_passages(rids, n, llm, random.Random(m.SEED))
    done = m.write_scenes(rows, llm, reps, {})
    return rows, ps, done, llm


def test_pick_write_pairs(home):
    m = _load("blind_scene_pairs")
    rids = [_book(1).id, _book(2).id]
    rows, ps, done, llm = _run(m, rids)
    assert ps == {"draws": ps["draws"], "failed": 0, "kept": 3} and len(rows) == 3
    assert {r["rid"] for r in rows} == set(rids)  # 원고마다 돌아가며
    assert len({(r["rid"], r["order"], r["part"]) for r in rows}) == 3
    assert all(set(r) == {"id", "rid", "order", "part", "source", "lead", "facts"} and r["facts"]["pov"] == PEOPLE[0] for r in rows)
    assert sorted(done) == sorted(f"{r['id']}|{k}" for r in rows for k in (1, 2))
    assert all("**" not in v["text"] for v in done.values())
    assert llm.calls.count("DrillFacts") == 3 and llm.calls.count("StudioDraft") == 6
    pairs, st = m.make_pairs(rows, done)
    assert st == {"rows": 3, "pairs": 3, "missing": 0, "copied": 0}
    for p, r in zip(pairs, rows):
        assert p["ref"] == r["source"] and p["base"] == done[f"{r['id']}|1"]["text"] and p["base2"] == done[f"{r['id']}|2"]["text"]
        assert set(p["names"]) == set(PEOPLE) and p["rid"] == r["rid"] and p["order"] == r["order"] and "work" not in p
    json.dumps(pairs, ensure_ascii=False)


def test_joined_passages_do_not_overlap(home):
    m = _load("blind_scene_pairs")
    rid = _book(1).id
    rows, ps = m.pick_passages([rid], 12, FakeLLM(), random.Random(3))
    by_ep: dict[int, list[int]] = {}
    for r in rows:
        by_ep.setdefault(r["order"], []).append(r["part"])
    assert rows and all(len(v) == 1 for v in by_ep.values())  # 화마다 셋뿐이라 이음은 하나만 들어간다
    assert all(1700 <= len(r["source"]) <= 2400 for r in rows)


def test_card_for(home):
    m = _load("blind_scene_pairs")
    rows, _, _, _ = _run(m, [_book(1).id], n=1, reps=1)
    c = m.card_for(rows[0])
    assert c.length == round(len(rows[0]["source"]) / 50) * 50 and 1700 <= len(rows[0]["source"]) <= 2400 and c.extra == "" and c.pov == PEOPLE[0]
    assert "도윤이 채린을 찾아간다" in c.action and "만 아는 속사정" not in c.action
    assert rows[0]["source"] not in c.action


def test_resume_does_not_call_again(home):
    m = _load("blind_scene_pairs")
    rows, _, done, _ = _run(m, [_book(1).id], n=2, reps=2)
    llm = FakeLLM()
    same = m.write_scenes(rows, llm, 2, done)
    assert same == done and llm.calls == []
    partial = {k: v for k, v in done.items() if not k.endswith("|2")}
    more = m.write_scenes(rows, llm, 2, partial)
    assert llm.calls == ["StudioDraft"] * 2 and sorted(more) == sorted(done)
    assert all(more[k] == partial[k] for k in partial)  # 이미 있는 글은 그대로


def test_pick_failures(home):
    m = _load("blind_scene_pairs")
    rid = _book(1).id
    llm = FakeLLM(fail_facts=True)
    rows, ps = m.pick_passages([rid], 3, llm, random.Random(1))
    assert rows == [] and ps["kept"] == 0 and ps["failed"] > 0 and ps["draws"] <= m.MAX_DRAWS_PER_RID
    rows, ps = m.pick_passages([rid], 10, FakeLLM(), random.Random(1))
    assert 1 <= len(rows) <= 4  # 화가 4개뿐이고 화마다 대목 셋이라 겹치는 이음은 다시 고르지 않는다
    assert ps["draws"] <= m.MAX_DRAWS_PER_RID


def test_write_error_is_kept(home):
    m = _load("blind_scene_pairs")

    class Bad:
        def json(self, *a, **k):
            raise RuntimeError("끊김 " * 100)

    rows, _, _, _ = _run(m, [_book(1).id], n=1, reps=1)
    got = m.write_scenes(rows, Bad(), 1, {})
    assert list(got) == [f"{rows[0]['id']}|1"] and len(got[f"{rows[0]['id']}|1"]["error"]) <= 200
    pairs, st = m.make_pairs(rows, got)
    assert pairs == [] and st["missing"] == 1


def test_make_pairs_copied(home):
    m = _load("blind_scene_pairs")
    rows, _, done, _ = _run(m, [_book(1).id], n=2, reps=1)
    done[f"{rows[0]['id']}|1"] = {"text": rows[0]["source"]}  # 대목을 그대로 옮긴 글
    pairs, st = m.make_pairs(rows, done)
    assert st["copied"] == 1 and st["pairs"] == 1 and "base2" not in pairs[0]
    assert pairs[0]["ref"] == rows[1]["source"]


def test_pairs_feed_blind_ident(home):
    m = _load("blind_scene_pairs")
    ident = _load("blind_ident")
    rows, _, done, _ = _run(m, [_book(1).id, _book(2).id], n=3, reps=2)
    pairs, _ = m.make_pairs(rows, done)
    f = home / "pairs.json"
    f.write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
    s = ident.check([f])
    assert s["pairs_in"] == 3 and s["pairs_used"] >= 1
    assert not any(n in json.dumps(s, ensure_ascii=False) for n in PEOPLE)


def test_estimate(home):
    m = _load("blind_scene_pairs")
    rid = _book(1).id
    e = m.estimate([rid], 10, 2, "gemini", "gemini-4-argon-001")
    assert e["calls"] == {"facts": 10, "write": 20} and e["tokens"]["in"] > 0 and e["tokens"]["out"] > 0
    assert e["model"] == "gemini:gemini-4-argon-001"
    assert e["usd"] is None or e["usd"] > 0
    none = m.estimate([rid], 5, 1, "gemini", "no-such-model-zz")
    assert none["usd"] is None and none["note"] == "가격표에 없어요" and none["calls"] == {"facts": 5, "write": 5}
    assert 5 * m.OUT_TOKENS_FACTS + 5 * 1700 / m.KO_CHARS_PER_TOKEN < none["tokens"]["out"] < 5 * m.OUT_TOKENS_FACTS + 5 * 2400 / m.KO_CHARS_PER_TOKEN


def test_estimate_priced(home, monkeypatch):
    from canon import usage
    from canon.usage import Price

    m = _load("blind_scene_pairs")
    rid = _book(1).id
    monkeypatch.setattr(usage, "prices", lambda: [Price(model="priced-zz", input=1.0, output=2.0)])
    e = m.estimate([rid], 4, 2, "gemini", "priced-zz")
    assert e["usd"] == pytest.approx((e["tokens"]["in"] * 1.0 + e["tokens"]["out"] * 2.0) / 1e6, abs=1e-4)


def test_model_option_required(home):
    m = _load("blind_scene_pairs")
    with pytest.raises(SystemExit):
        m.main(["gen", "--dir", str(home)])
    with pytest.raises(SystemExit):
        m._split_model("nomodel")
    assert m._split_model("gemini:x:y") == ("gemini", "x:y")


def test_commands_files(home, monkeypatch, capsys):
    m = _load("blind_scene_pairs")
    rid = _book(1).id
    monkeypatch.setattr(m, "_llm", lambda text: FakeLLM())
    d = home / "work"
    assert m.main(["pick", "--rid", rid, "--n", "2", "--model", "fake:x", "--dir", str(d)]) == 0
    assert json.loads(capsys.readouterr().out)["kept"] == 2
    with pytest.raises(SystemExit):
        m.main(["pick", "--rid", rid, "--n", "2", "--model", "fake:x", "--dir", str(d)])
    assert m.main(["gen", "--dir", str(d), "--model", "fake:x", "--reps", "2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"new": 4, "errors": 0, "total": 4}
    assert m.main(["gen", "--dir", str(d), "--model", "fake:x"]) == 0
    assert json.loads(capsys.readouterr().out)["new"] == 0
    assert m.main(["pairs", "--dir", str(d), "--out", str(home / "p.json")]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["pairs"] == 2 and not any(n in printed for n in PEOPLE)
    assert len(json.loads((home / "p.json").read_text(encoding="utf-8"))) == 2
    with pytest.raises(SystemExit):
        m.main(["pairs", "--dir", str(d), "--out", str(home / "p.json")])
