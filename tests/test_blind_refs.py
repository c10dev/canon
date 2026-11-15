"""가려 읽기 묶음 스크립트 (scripts/blind_refs.py). 지어낸 원고만 쓴다."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from canon import blindset, refs, revlab
from canon.schema import RefCut, RevEpisode, RevLab, RevSource

NAME = "REFNAME_ZZ"
FIELDS = ("line", "body", "head", "label", "title", "kind")


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "blind_refs.py"
    spec = importlib.util.spec_from_file_location("blind_refs", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _para(tag: str, i: int, n: int = 20) -> str:
    return " ".join(f"MARK_{tag}_{i}_{j} 문장입니다." for j in range(n))


def _ep_text(tag: str, paras: int = 8) -> str:
    return "\n\n".join(_para(tag, i) for i in range(paras))


@pytest.fixture()
def home(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_REFS", str(tmp_path / "refs"))
    return tmp_path


def _book(k: int, eps: int = 12, short: tuple[int, ...] = ()):
    text = "\n\n".join(f"{n}화\n" + (_para(f"{k}_{n}", 0, 5) if n in short else _ep_text(f"{k}_{n}")) for n in range(1, eps + 1))
    d = refs.preview(text, repeats=[])
    cuts = [RefCut(**{f: c[f] for f in FIELDS}) for c in d["cuts"] if c["on"]]
    return refs.create(f"{NAME}_{k}", text, cuts, rights=True)


def test_passage():
    m = _script()
    paras = [c * 600 for c in "가나다라마바사아"]
    a = "\n\n".join(paras)
    got = m.passage(a)
    assert got == "\n\n".join(paras[3:5])  # 시작은 30% 뒤 첫 빈 줄 다음, 끝은 CUT_MIN 뒤 첫 빈 줄 앞
    assert a.index(got) > len(a) * m.START_FRAC
    b = "나" * 1_500 + "\n \n" + "다" * 950 + "\n\n" + "라" * 1_000 + ".\n\n" + "마" * 800  # 공백만 있는 줄도 빈 줄
    assert m.passage(b) == "다" * 950
    c = "가" * 5_000 + "\n\n" + "나" * 1_400 + "다. 이어지는 글\n\n" + "마" * 500  # 빈 줄이 CUT_MAX 안에 없음
    assert m.passage("가" * 4_000 + c) .endswith("다.")
    d = "가" * 1_000 + "\n\n" + "나" * 1_500 + "다. 이어지는 글" + "라" * 500
    assert m.passage(d) == "나" * 1_500 + "다."
    assert m.passage("가" * 5_000) is None  # 빈 줄이 없음
    assert m.passage("가" * 2_000 + "\n\n" + "나" * 500) is None  # 남은 글이 CUT_MIN 미만


def test_schedule():
    m = _script()
    arms = [f"a{i}" for i in range(6)]
    got = m.schedule(arms)
    assert len(got) == 28 and got == m.schedule(list(reversed(arms)))
    count = {a: sum(a in p for p in got) for a in arms}
    assert set(count.values()) <= {9, 10} and sum(count.values()) == 56
    one = [p for p in got if got.count(p) == 1]
    assert len(one) == 2 and not set(one[0]) & set(one[1])  # 빠진 짝 둘은 판을 나누지 않는다
    assert len(set(got)) == 15
    with pytest.raises(SystemExit):
        m.schedule(["a", "b", "c"])


def test_sent_to_revlab(home):
    m = _script()
    revlab.save(RevLab(id=1, title="t", episodes=[
        RevEpisode(number=1, text="가 나\n다", source=RevSource(ref="ab" * 4, order=3)),
        RevEpisode(number=2, text="라 마\n바"),
        RevEpisode(number=3, text="  "),
    ]))
    sent, plain = m.sent_to_revlab()
    assert sent == {("ab" * 4, 3)} and plain == ["라마바"]


def test_pool(home):
    m = _script()
    one, two, three = _book(1, short=(2,)), _book(2), _book(3, eps=4)
    revlab.save(RevLab(id=1, title="t", episodes=[
        RevEpisode(number=1, text="x", source=RevSource(ref=one.id, order=4)),
        RevEpisode(number=2, text=refs.texts(one.id)[5]),
        RevEpisode(number=3, text=refs.texts(two.id)[7][:2_000]),  # 일부만 넘겨도 가운데 PROBE 자가 들어 있으면 뺀다
    ]))
    arms, counts = m.pool([[two.id, three.id]])
    assert sorted(arms) == [f"{NAME}_1", f"{NAME}_2"]  # 둘째 묶음은 첫 원고 이름의 한 판
    one_orders = [e["order"] for e in arms[f"{NAME}_1"]]
    assert one_orders == [1, 3, 6, 7, 8, 9, 10, 11, 12]  # 2 는 짧고, 4 는 RevSource, 5 는 글이 같다
    two_rows = arms[f"{NAME}_2"]
    assert {e["rid"] for e in two_rows} == {two.id, three.id}
    assert [(e["rid"], e["order"]) for e in two_rows if e["rid"] == three.id] == [(three.id, n) for n in range(1, 5)]
    assert 7 not in [e["order"] for e in two_rows if e["rid"] == two.id] and len(two_rows) == 11 + 4
    assert all(e["chars"] == len(e["text"]) and e["text"].startswith("MARK_") for e in two_rows)
    c1 = counts[m._sha(f"{NAME}_1")]
    assert c1 == {"episodes": 9, "dropped_short": 1, "dropped_revlab": 2, "dropped_cut": 0}
    assert counts[m._sha(f"{NAME}_2")]["dropped_revlab"] == 1
    with pytest.raises(SystemExit):
        m.pool([["deadbeef"]])
    with pytest.raises(SystemExit):
        m.pool([[one.id], [one.id]])


def test_build(home):
    m = _script()
    books = [_book(k) for k in range(1, 8)]
    out = home / "out"
    s = m.build(out, [[books[0].id, books[1].id]])
    assert (s["arms"], s["pairs"], s["items"], s["repeats"]) == (6, 28, 59, 3)
    folder = out / "set1"
    key = json.loads((folder / "blind_key.json").read_text(encoding="utf-8"))
    assert len(key) == 59 and len(list(folder.glob("*.txt"))) == 59 and len({k["piece"] for k in key}) == 28
    assert not any(a["piece"] == b["piece"] for a, b in zip(key, key[1:]))
    text = {k["no"]: (folder / f"{k['no']}.txt").read_text(encoding="utf-8") for k in key}
    uniq = set(text.values())
    assert len(uniq) == 56  # 한 화는 한 번, 같은 글은 repeat 셋뿐
    firsts = [re.search(r"MARK_(\d+_\d+)_", t).group(1) for t in uniq]
    assert len(set(firsts)) == 56
    summary = (out / "summary.json").read_text(encoding="utf-8")
    assert "MARK_" not in summary and NAME not in summary and "문장입니다" not in summary and books[0].id not in summary
    assert json.loads(summary) == s and s["key_sha256"] == m._sha((folder / "blind_key.json").read_text(encoding="utf-8"))
    assert sorted(v["duels"] for v in s["per_arm"].values()) == [9, 9, 9, 9, 10, 10]
    got = blindset.import_folder(str(folder), mode="side")
    assert len(blindset.duel_pairs(got)) == 31 and len(got.items) == 59
    again = m.build(home / "out2", [[books[0].id, books[1].id]])
    assert again == s and (home / "out2" / "set1" / "01.txt").read_text(encoding="utf-8") == text["01"]


def test_build_short_of_episodes(home):
    m = _script()
    for k in range(1, 7):
        _book(k, eps=6)
    with pytest.raises(SystemExit):
        m.build(home / "out", [])


def test_build_refuses_nonempty(home):
    m = _script()
    out = home / "out"
    out.mkdir()
    (out / "x.txt").write_text("a", encoding="utf-8")
    with pytest.raises(SystemExit):
        m.build(out, [])
    assert [p.name for p in out.iterdir()] == ["x.txt"]


def test_main(home, capsys):
    m = _script()
    books = [_book(k) for k in range(1, 6)]
    assert m.main(["build", "--out", str(home / "out"), "--same", books[0].id, books[1].id]) == 0
    assert json.loads(capsys.readouterr().out)["arms"] == 4
    with pytest.raises(SystemExit):
        m.main(["build", "--out", str(home / "out3"), "--same", "deadbeef"])
