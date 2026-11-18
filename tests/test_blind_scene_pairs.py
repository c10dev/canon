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
    assert st == {"rows": 3, "pairs": 3, "missing": 0, "copied": 0, "style_overlap": 0}
    for p, r in zip(pairs, rows):
        assert p["ref"] == r["source"] and p["base"] == done[f"{r['id']}|1"]["text"] and p["base2"] == done[f"{r['id']}|2"]["text"]
        assert set(p["names"]) == set(PEOPLE) and p["rid"] == r["rid"] and p["order"] == r["order"] and "work" not in p
    json.dumps(pairs, ensure_ascii=False)


def test_make_pairs_names_union_per_rid(home):
    m = _load("blind_scene_pairs")

    def row(i, rid, names):
        facts = DrillFacts(people=[{"name": n, "note": "인물"} for n in names], pov=names[0], place="", time="", before="",
                           inner=[], events=["일"]).model_dump()
        return {"id": f"S{i}", "rid": rid, "order": i, "part": 0, "source": f"원문 {i}번 대목이에요.", "lead": f"앞 {i}", "facts": facts}

    rows = [row(1, "r1", ["가", "나"]), row(2, "r1", ["나", "다"]), row(3, "r2", ["라"])]
    done = {f"{r['id']}|1": {"text": f"새 글 {r['id']}"} for r in rows}
    pairs, st = m.make_pairs(rows, done)
    assert st["pairs"] == 3
    assert pairs[0]["names"] == pairs[1]["names"] == ["가", "나", "다"]
    assert pairs[2]["names"] == ["라"]


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
    assert m.main(["gen", "--dir", str(d), "--path", "paragraph", "--model", "fake:x", "--reps", "2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"new": 4, "errors": 0, "coord_errors": 0, "total": 4}
    assert m.main(["gen", "--dir", str(d), "--path", "paragraph", "--model", "fake:x"]) == 0
    assert json.loads(capsys.readouterr().out)["new"] == 0
    assert m.main(["pairs", "--dir", str(d), "--out", str(home / "p.json")]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["pairs"] == 2 and not any(n in printed for n in PEOPLE)
    assert len(json.loads((home / "p.json").read_text(encoding="utf-8"))) == 2
    with pytest.raises(SystemExit):
        m.main(["pairs", "--dir", str(d), "--out", str(home / "p.json")])


# ---------- 화 쓰기 길 (--path episode) ----------

LONG = "\n".join(" ".join(f"E{i}_{j} 도윤은 창가에 서서 오래 기다렸다." for j in range(3)) for i in range(24))


class CountLLM:
    """canon.mock.MockLLM 을 감싸 부른 횟수를 세고, 본문 쓰기만 약 1,900자 글을 돌려준다."""

    def __init__(self, long_text: bool = True):
        from canon.mock import MockLLM

        self.inner = MockLLM()
        self.calls: list[str] = []
        self.long_text = long_text
        self.knows_cut = True
        self.last_finish = "STOP"
        self.lock = threading.Lock()

    def json(self, system, prompt, schema, hint=None):
        with self.lock:
            self.calls.append(schema.__name__)
        return self.inner.json(system, prompt, schema, hint)

    def _text(self, text: str) -> str:
        with self.lock:
            self.calls.append("text")
        self.last_finish = "STOP"
        return LONG if self.long_text else text

    def text(self, system, prompt):
        return self._text(self.inner.text(system, prompt))

    def text_stream(self, system, prompt, on_chunk):
        return self._text(self.inner.text_stream(system, prompt, on_chunk))


def _style_file(home, passages=(), name="style.json"):
    from canon.schema import StyleProfile

    prof = StyleProfile(sample_passages=list(passages))
    f = home / name
    f.write_text(json.dumps({"profile": prof.model_dump(), "sample": "지은 표본 글"}, ensure_ascii=False), encoding="utf-8")
    return f


def _rows(m, rids, n=2):
    rows, _ = m.pick_passages(rids, n, FakeLLM(), random.Random(m.SEED))
    return rows


def _episode_run(m, home, rows, llm, done=None, passages=(), limit=0):
    from canon.schema import Settings

    styles = {r: m.load_style(str(_style_file(home, passages, f"s{i}.json"))) for i, r in enumerate({x["rid"] for x in rows})}
    return m.write_episode_scenes(rows, Settings(storyboard=True), styles, llm, llm, 1, done or {}, limit), styles


def test_episode_project(home):
    from canon import prompts, store
    from canon.schema import Settings

    m = _load("blind_scene_pairs")
    row = _rows(m, [_book(1).id], 1)[0]
    style = m.load_style(str(_style_file(home)))
    before = sorted(store.ROOT.rglob("*"))
    p = m.episode_project(row, Settings(storyboard=True), style)
    ids = [b.id if hasattr(b, "id") else b[0] for b in prompts.episode_parts(p, m.EP_NO)]
    assert p.serial and "plot" in ids and "instructions" in ids
    assert len(p.characters) == len(PEOPLE) and next(c for c in p.characters if c.name == PEOPLE[0]).tier == "main"
    assert p.episode(m.EP_NO - 1).summary == row["facts"]["before"] and p.episode(m.EP_NO).plot.pov == "c1"
    assert p.meta.words_per_episode == round(len(row["source"]) / 50) * 50
    assert sorted(store.ROOT.rglob("*")) == before
    ghost = dict(row, facts=dict(row["facts"], pov="낯선이"))
    q = m.episode_project(ghost, Settings(), style)
    assert len(q.characters) == len(PEOPLE) + 1 and q.characters[-1].name == "낯선이" and q.characters[-1].tier == "main"


def test_episode_path_end_to_end(home):
    m = _load("blind_scene_pairs")
    rows = _rows(m, [_book(1).id], 2)
    llm = CountLLM()
    done, _ = _episode_run(m, home, rows, llm)
    for r in rows:
        assert done[f"{r['id']}|plan"]["storyboard"] and len(done[f"{r['id']}|1"]["text"]) > 1500
    assert done["_meta"]["path"] == "episode" and done["_meta"]["write_model"] == "mock:mock"
    pairs, st = m.make_pairs(rows, done)
    assert st["pairs"] == 2 and st["style_overlap"] == 0


def test_episode_resume(home):
    m = _load("blind_scene_pairs")
    rows = _rows(m, [_book(1).id], 2)
    done, _ = _episode_run(m, home, rows, CountLLM())
    llm = CountLLM()
    same, _ = _episode_run(m, home, rows, llm, done)
    assert llm.calls == [] and same == done
    key = f"{rows[0]['id']}|1"
    bad = dict(done, **{key: {"error": "끊김"}})
    llm = CountLLM()
    again, _ = _episode_run(m, home, rows, llm, bad)
    assert llm.calls == ["text"] and "text" in again[key]
    only, _ = _episode_run(m, home, rows, CountLLM(), {}, limit=1)
    assert f"{rows[1]['id']}|plan" not in only


def test_episode_style_overlap(home):
    m = _load("blind_scene_pairs")
    rows = _rows(m, [_book(1).id], 2)
    rows[1] = dict(rows[1], source="\n".join(f"Z{i} 전혀 다른 장면의 문장이 {i * 7919} 번째로 이어진다." for i in range(40)))
    llm = CountLLM()
    done, _ = _episode_run(m, home, rows, llm, passages=[rows[0]["source"][100:400]])
    assert done[f"{rows[0]['id']}|plan"] == {"skip": "style_overlap"} and f"{rows[0]['id']}|1" not in done
    assert llm.calls.count("text") == 1  # 겹친 대목은 쓰기를 부르지 않고 나머지 한 대목만 쓴다
    _, st = m.make_pairs(rows, done)
    assert st["style_overlap"] == 1 and st["pairs"] == 1


def test_make_pairs_style_passages_copied(home):
    m = _load("blind_scene_pairs")
    rows = _rows(m, [_book(1).id], 1)
    para = "달빛 아래 오래된 우물가에서 그녀는 아무 말 없이 물동이를 내려놓았다."
    done = {f"{rows[0]['id']}|plan": {"style_passages": [para]}, f"{rows[0]['id']}|1": {"text": "앞 글. " + para + " 뒤 글."}}
    pairs, st = m.make_pairs(rows, done)
    assert pairs == [] and st["copied"] == 1


def test_make_style(home, monkeypatch):
    from canon import library
    from canon.schema import StyleProfile

    m = _load("blind_scene_pairs")
    rid = _book(1).id
    seen = {}

    def fake(llm, sample, names=None, passages=True, corpus=""):
        seen["corpus"] = corpus
        return StyleProfile(sample_passages=["예시"])

    monkeypatch.setattr(m.pipeline, "analyze_style", fake)
    lib_before = library.list_entries() if hasattr(library, "list_entries") else None
    out = m.make_style(rid, object())
    assert out["profile"]["sample_passages"] == ["예시"] and out["sample"] and seen["corpus"]
    assert refs.load(rid).made == []
    if lib_before is not None:
        assert library.list_entries() == lib_before
    prof, base, sample = m.load_style(str(_style_file(home)))
    assert base is None and sample == "지은 표본 글" and prof.sample_passages == []


def test_episode_options_stop(home, monkeypatch):
    m = _load("blind_scene_pairs")
    rid = _book(1).id
    d = home / "work"
    monkeypatch.setattr(m, "_llm", lambda text: FakeLLM())
    m.main(["pick", "--rid", rid, "--n", "1", "--model", "fake:x", "--dir", str(d)])
    with pytest.raises(SystemExit):
        m.main(["gen", "--dir", str(d)])  # --settings-from 없음
    monkeypatch.setattr(m, "_settings_from", lambda name: __import__("canon.schema", fromlist=["Settings"]).Settings())
    with pytest.raises(SystemExit) as e:
        m.main(["gen", "--dir", str(d), "--settings-from", "x"])  # --style 빠짐
    assert "1" in str(e.value) and rid not in str(e.value)


def test_estimate_episode(home):
    from canon.schema import Settings

    m = _load("blind_scene_pairs")
    rid = _book(1).id
    st = {rid: m.load_style(str(_style_file(home)))}
    both = {"board": "gemini:no-such-model-zz", "write": "gemini:no-such-model-zz"}
    e = m.estimate([rid], 6, 2, path="episode", settings=Settings(storyboard=True), styles=st, models=both)
    assert e["calls"]["facts"] == 6 and e["calls"]["board"] == 6 and e["calls"]["write"] == 12
    assert sum(e["calls"].values()) == 6 + 6 + e["calls"]["cue"] + 12
    assert e["tokens"]["in"] > 0 and e["tokens"]["out"] > 0 and e["usd"] is None and e["note"] == "가격표에 없어요"
    assert e["models"]["write"]["usd"] is None
    priced = m.estimate([rid], 6, 2, path="episode", settings=Settings(storyboard=True), styles=st, models=both, assume="gemini-4-argon-001")
    assert priced["assumed"] == "gemini-4-argon-001"
    if priced["usd"] is not None:
        assert priced["usd"] > 0 and priced["usd_worst"] >= priced["usd"]


class PromptLLM(CountLLM):
    """CountLLM 에 본문 쓰기 요청을 남긴다."""

    def __init__(self):
        super().__init__()
        self.prompts: list[str] = []

    def text_stream(self, system, prompt, on_chunk):
        with self.lock:
            self.prompts.append(prompt)
        return super().text_stream(system, prompt, on_chunk)

    def text(self, system, prompt):
        with self.lock:
            self.prompts.append(prompt)
        return super().text(system, prompt)


def _coord_run(m, home, rows, llm, done=None):
    from canon.schema import Settings

    styles = {r: m.load_style(str(_style_file(home, (), f"s{i}.json"))) for i, r in enumerate({x["rid"] for x in rows})}
    return m.write_episode_scenes(rows, Settings(storyboard=True, write_material="coord"), styles, llm, llm, 1, done or {})


def test_episode_coord_memo(home):
    from canon import coord

    m = _load("blind_scene_pairs")
    rows = _rows(m, [_book(1).id], 2)
    llm = PromptLLM()
    done = _coord_run(m, home, rows, llm)
    assert llm.calls.count("CoordDraft") == 2
    assert llm.calls[0] == "CoordDraft"  # 스토리보드보다 먼저
    for r in rows:
        plan = done[f"{r['id']}|plan"]
        assert len(plan["coord"]["events"]) == len(r["facts"]["events"]) and "coord_error" not in plan
    assert len(llm.prompts) == 2
    for prompt in llm.prompts:  # 쓰기 요청 끝(지시 꼬리)에 [조율 메모] 단락
        assert f"\n\n{coord.NOTE}" in prompt and prompt.rindex(coord.NOTE) > len(prompt) // 2
        assert "사건 1에서 주인공의 마음이" in prompt  # 플롯 사건을 조율 메모로 바꿔 넣었다 (mock_coord)
    key = f"{rows[0]['id']}|1"  # 이어 돌리면 남긴 조율 메모를 다시 넣고 부르지 않는다
    again = PromptLLM()
    _coord_run(m, home, rows, again, dict(done, **{key: {"error": "끊김"}}))
    assert again.calls == ["text"] and coord.NOTE in again.prompts[0]


def test_episode_no_coord_without_setting(home):
    from canon import coord

    m = _load("blind_scene_pairs")
    rows = _rows(m, [_book(1).id], 1)
    llm = PromptLLM()
    done, _ = _episode_run(m, home, rows, llm)
    assert "CoordDraft" not in llm.calls and "coord" not in done[f"{rows[0]['id']}|plan"]
    assert coord.NOTE not in llm.prompts[0]


def test_episode_coord_failure_writes_with_plot(home, monkeypatch):
    from canon import coord

    m = _load("blind_scene_pairs")
    rows = _rows(m, [_book(1).id], 1)

    def boom(*a, **k):
        raise ValueError("사건 수가 달라요")
    monkeypatch.setattr(m.pipeline, "make_coord", boom)
    llm = PromptLLM()
    done = _coord_run(m, home, rows, llm)
    plan = done[f"{rows[0]['id']}|plan"]
    assert "사건 수" in plan["coord_error"] and "error" not in plan and plan["storyboard"]
    assert "text" in done[f"{rows[0]['id']}|1"] and coord.NOTE not in llm.prompts[0]
    assert m._gen_summary(done, {})["coord_errors"] == 1


def test_estimate_episode_coord(home):
    from canon.schema import Settings

    m = _load("blind_scene_pairs")
    rid = _book(1).id
    st = {rid: m.load_style(str(_style_file(home)))}
    both = {"board": "gemini:no-such-model-zz", "write": "gemini:no-such-model-zz"}
    off = m.estimate([rid], 6, 1, path="episode", settings=Settings(storyboard=True, cue_sheet=False), styles=st, models=both)
    on = m.estimate([rid], 6, 1, path="episode", settings=Settings(storyboard=True, cue_sheet=False, write_material="coord"), styles=st, models=both)
    assert off["calls"]["coord"] == 0 and on["calls"]["coord"] == 6 and on["calls"]["cue"] == 0
    assert on["tokens"]["out"] - off["tokens"]["out"] == 6 * (m.OUT_TOKENS_COORD + m.THOUGHT_TOKENS["coord"])
