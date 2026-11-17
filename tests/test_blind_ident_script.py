"""판별 묶음 조립 스크립트 (scripts/blind_ident.py). 지어낸 원고만 쓴다."""
import hashlib
import importlib.util
import json
import random
from pathlib import Path

import pytest

from canon import blindset, refdigest, refs
from canon.schema import RefCut, RefDigest, RefDigestBook, RefDigestItem

NAME = "REFNAME_ZZ"
FIELDS = ("line", "body", "head", "label", "title", "kind")
CAST = ["김민수", "한채린"]


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "blind_ident.py"
    spec = importlib.util.spec_from_file_location("blind_ident", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ref(tag: str, paras: int = 14) -> str:
    return "\n".join(" ".join(f"R{tag}_{i}_{j} 김민수는 한채린에게 조용히 말했다." for j in range(3)) for i in range(paras))


def _base(tag: str, paras: int = 14) -> str:
    return "\n".join(" ".join(f"B{tag}_{i}_{j} 민수는 창가에 서서 오래 기다렸다." for j in range(3)) for i in range(paras))


@pytest.fixture()
def home(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_REFS", str(tmp_path / "refs"))
    return tmp_path


def _book(k: int, text_of):
    text = "\n\n".join(f"{n}화\n{text_of(f'{k}{n}')}" for n in range(1, 4))
    d = refs.preview(text, repeats=[])
    cuts = [RefCut(**{f: c[f] for f in FIELDS}) for c in d["cuts"] if c["on"]]
    return refs.create(f"{NAME}_{k}", text, cuts, rights=True)


def _digest(book, cast=CAST) -> None:
    items = [RefDigestItem(basis=t["basis"], order=t["order"], digest=RefDigest(
        events=["일"], cast=list(cast), place="방", ending="끝", kind="대화", tension=3, hook="없음")) for t in refdigest._texts(book)]
    refdigest._save(book.id, RefDigestBook(items=items))


def test_syllable_classes():
    m = _script()
    assert all(m._coda(c) == 0 for c in m.SYLLABLES_OPEN)
    assert all(m._coda(c) == 1 for c in m.SYLLABLES_L)
    assert all(m._coda(c) == 2 for c in m.SYLLABLES_CLOSED)
    assert m._coda("a") == 0


def test_substitutes_and_mask():
    m = _script()
    names = ["김민수", "민수", "수진", "소라", "다솔", "Alex"]
    a = m.substitutes(names, random.Random("x"))
    assert a == m.substitutes(names, random.Random("x"))
    for n, s in a.items():
        assert len(s) == len(n) and m._coda(s[-1]) == m._coda(n[-1])
    assert a["김민수"][1:] == a["민수"]  # 3글자 이름과 뒤 2글자 이름의 관계
    assert len(set(a.values())) == len(a)
    text = "김민수가 민수에게 수진과 소라, 다솔은 Alex를 봤다."
    got, n = m.mask(text, a)
    assert n == 6 and got == f"{a['김민수']}가 {a['민수']}에게 {a['수진']}과 {a['소라']}, {a['다솔']}은 {a['Alex']}를 봤다."
    assert got.count(a["민수"]) == 2  # 김민수 는 통째로 한 번에 바뀌고 안쪽 민수 를 다시 바꾸지 않는다
    assert m.mask("글", {}) == ("글", 0)
    avoid = "".join(m.SYLLABLES_OPEN[:-1]) + "".join(m.SYLLABLES_CLOSED)
    b = m.substitutes(["소라"], random.Random("y"), avoid=avoid)
    assert b["소라"] not in avoid


def test_substitutes_same_for_both_texts():
    m = _script()
    mp = m.substitutes(["한채린", "채린"], random.Random("z"))
    r, _ = m.mask("한채린이 웃었다", mp)
    b, _ = m.mask("채린이 울었다", mp)
    assert r.startswith(mp["한채린"]) and b.startswith(mp["채린"]) and mp["한채린"].endswith(mp["채린"])


def test_fit():
    m = _script()
    ref, base = _ref("a"), _base("a")
    a, b = m.fit(ref, base)
    assert a.startswith("Ra_1_0") and b.startswith("Ba_1_0")  # 첫 문단은 쓰지 않고 둘째 문단에서 시작
    assert a.endswith(".") and b.endswith(".")
    assert "Ra_13_" not in a and "Ba_13_" not in b  # 마지막 문단은 쓰지 않는다
    assert len(a) >= m.MIN_CHARS and len(b) >= m.MIN_CHARS
    assert abs(len(a) - len(b)) <= m.TOL * max(len(a), len(b))
    assert ref.index(a) > 0 and a in ref and b in base
    assert m.fit("짧은 글.\n둘째.", base) is None  # 문단이 모자람
    assert m.fit(_ref("a", paras=4), base) is None  # 길이를 못 채움
    assert m.fit(ref, "한 줄뿐인 글.") is None


def test_ref_cast(home):
    m = _script()
    one = _book(1, _ref)
    _book(2, lambda t: _ref(t))
    _digest(one)
    ep2 = refdigest._texts(one)[1]["text"]
    work = hashlib.sha256(one.id.encode()).hexdigest()[:6]
    assert m.ref_cast({"ref": ep2[200:900], "work": work}) == CAST
    by_name = hashlib.sha256(one.name.encode()).hexdigest()[:6]
    assert m.ref_cast({"ref": ep2[200:900], "work": by_name}) == CAST
    assert m.ref_cast({"ref": ep2[200:900], "rid": one.id}) == CAST
    assert m.ref_cast({"ref": "없는 대목 " * 50, "rid": one.id}) is None
    assert m.ref_cast({"ref": ep2[200:900], "work": "zzzzzz"}) is None
    assert m.ref_cast({"ref": ep2[200:900], "rid": "deadbeef"}) is None
    two = refs.entries()[0] if refs.entries()[0].id != one.id else refs.entries()[1]
    assert m.ref_cast({"ref": refdigest._texts(two)[0]["text"][100:800], "rid": two.id}) is None  # 화 카드가 없음
    assert m.ref_cast({"ref": ep2}) is None


def test_project_names(home):
    from canon import store
    from canon.schema import Character, Meta, Project

    m = _script()
    c = Character(id="a", name="서도윤", role="주인공", aliases=["도윤 군", "윤"])
    store.save("demo", Project(meta=Meta(title="demo", genres=["mystery"]), characters=[c]))
    assert m.project_names(["demo"]) == ["서도윤", "도윤 군", "윤"]
    names, state = m.names_for({"ref": "x", "base": "y", "names": ["한채린"]}, m.project_names(["demo"]))
    assert state == "pair" and "서도윤" in names and "도윤" in names and "윤" not in names


def test_names_for(home):
    m = _script()
    names, state = m.names_for({"ref": "x", "base": "y", "names": ["김민수", "A", "김민수"]}, ["서도윤", "한"])
    assert state == "pair" and names == ["김민수", "민수", "서도윤", "도윤"]
    assert m.names_for({"ref": "x", "base": "y"}, ["서도윤"])[1] == "none"


def test_check_cut_name_left():
    m = _script()
    assert m._check_cut("김민수가 갔다", "나", ["김민수"], [], ((0, 1), (0, 1)), ("가", "나")) == "name_left"


def _pairs_files(home):
    one = _book(1, lambda t: _ref(f"W{t}"))
    _digest(one)
    ep = refdigest._texts(one)[0]["text"]
    work = hashlib.sha256(one.id.encode()).hexdigest()[:6]
    short = "한 줄.\n두 줄.\n세 줄."
    a = [
        {"ref": _ref("a1"), "base": _base("a1"), "names": CAST},
        {"ref": _ref("a2"), "base": _base("a2")},  # 이름 원천 없음
        {"ref": short, "base": short, "names": CAST},  # 모양을 못 맞춤
        {"ref": _ref("a4"), "base": _base("a4"), "names": CAST},  # 레퍼런스 쪽이 이미 읽은 묶음과 겹침
        {"ref": _ref("a5"), "base": _base("a5"), "names": CAST, "scene": "무시", "anchor": 1},
        {"ref": _ref("a6"), "base": _base("a6"), "names": CAST},  # canon 쪽이 겹침
    ]
    b = [{"ref": ep, "base": _base("b1"), "work": work}]
    fa, fb = home / "a.json", home / "b.json"
    fa.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    fb.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    seen = blindset.create("읽은 묶음", [{"text": _ref("a4")}, {"text": _base("a6")}])
    return [fa, fb], seen.id


def test_check_and_build(home, monkeypatch):
    m = _script()
    monkeypatch.setattr(m, "MASK_NAMES", True)
    files, seen = _pairs_files(home)
    s = m.check(files, exclude=[seen])
    assert (s["pairs_in"], s["pairs_ok"], s["pairs_used"]) == (7, 3, 3)
    assert s["dropped"] == {"no_ref_names": 1, "no_fit": 1, "name_left": 0, "ref_seen": 1, "base_seen": 1}
    assert [r["reason"] for r in s["rows"]] == ["", "no_ref_names", "no_fit", "ref_seen", "", "base_seen", ""]
    assert [r["file"] for r in s["rows"]] == [1, 1, 1, 1, 1, 1, 2]
    assert [r["ref_names_from"] for r in s["rows"]][::6] == ["pair", "cast"]
    assert s["rows"][1]["ref_names_from"] == "none" and s["rows"][0]["masked"] > 0
    assert s["len_diff_max"] <= m.TOL and s["chars"]["min"] >= m.MIN_CHARS
    assert s["items"] is None and s["key_sha256"] is None
    dump = json.dumps(s, ensure_ascii=False)
    assert not any(n in dump for n in [*CAST, "민수", "채린", NAME])
    assert list((home).glob("out*")) == []  # check 는 아무것도 쓰지 않는다
    assert m.check(files, exclude=[seen], max_pairs=2)["pairs_used"] == 2
    again = m.check(files, exclude=[seen])
    assert again == s

    out = home / "out"
    built = m.build(out, files, exclude=[seen])
    assert built["items"] == 3 * 2 + m.REPEATS and built["repeats"] == m.REPEATS
    summary = (out / "summary.json").read_text(encoding="utf-8")
    assert json.loads(summary) == built and not any(n in summary for n in [*CAST, "민수", "채린"])
    folder = out / "set1"
    got = blindset.import_folder(str(folder), mode="ident", answer_arm="ref")
    assert len(blindset.side_pairs(got)) == 3 + m.REPEATS
    assert not any(n in x.text for x in got.items for n in [*CAST, "민수", "채린"])
    assert len(got.items) == 9 and {k.arm for k in got.key} == {"ref", "base"}
    with pytest.raises(SystemExit):
        m.build(out, files, exclude=[seen])  # 비어 있지 않은 폴더


def test_check_and_build_keeps_names(home):
    m = _script()
    assert m.MASK_NAMES is False
    files, seen = _pairs_files(home)
    s = m.check(files, exclude=[seen])
    assert s["dropped"]["no_ref_names"] == 0 and s["dropped"]["name_left"] == 0
    assert all(r["ref_names_from"] == "off" and r["masked"] == 0 for r in s["rows"])
    assert [r["reason"] for r in s["rows"]] == ["", "", "no_fit", "ref_seen", "", "base_seen", ""]
    assert s["pairs_ok"] == 4
    out = home / "out"
    m.build(out, files, exclude=[seen])
    summary = (out / "summary.json").read_text(encoding="utf-8")
    assert not any(n in summary for n in CAST)
    got = blindset.import_folder(str(out / "set1"), mode="ident", answer_arm="ref")
    assert any(n in x.text for x in got.items for n in CAST)


def test_main(home, capsys):
    m = _script()
    files, seen = _pairs_files(home)
    args = [x for f in files for x in ("--pairs", str(f))]
    assert m.main(["check", *args, "--exclude-set", seen]) == 0
    assert json.loads(capsys.readouterr().out)["pairs_ok"] == 4  # 이름을 바꾸지 않으니 이름 원천이 없는 쌍도 통과
    assert m.main(["build", *args, "--exclude-set", seen, "--out", str(home / "o2")]) == 0
    assert "blind import" in capsys.readouterr().out.splitlines()[-1]


def test_bad_pairs_file(home):
    m = _script()
    f = home / "bad.json"
    f.write_text(json.dumps([{"ref": "가"}]), encoding="utf-8")
    with pytest.raises(SystemExit):
        m.check([f])
    f.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        m.check([f])
