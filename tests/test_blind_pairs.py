"""가려 읽기 묶음 스크립트 (scripts/blind_pairs.py). 지어낸 자료만 쓴다."""
import importlib.util
import json
from pathlib import Path

import pytest

from canon import blindset, revlab
from canon.schema import RevBlind, RevEpisode, RevLab, RevTake

TITLE = "TITLE_SECRET_ZZ"


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "blind_pairs.py"
    spec = importlib.util.spec_from_file_location("blind_pairs", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _body(mark: str) -> str:
    para = "문장입니다. " * 100
    return f"{mark} {para.strip()}\n\n{para.strip()}\n\n{para.strip()}\n\n{para.strip()}"


def _ep(lab: int, n: int, picked: bool = False, takes: list[RevTake] | None = None) -> RevEpisode:
    take = RevTake(no=1, text="제1화\n\n" + _body(f"MARK_AI_{lab}_{n}"), model=f"m{lab}",
                   blind=RevBlind(picked="original" if picked else ""))
    return RevEpisode(number=n, head="짧은 제목", text=f"제{n}화\n짧은 제목\n\n" + _body(f"MARK_SRC_{lab}_{n}"), takes=takes if takes is not None else [take])


def _labs(counts=(25, 20), prior=10) -> None:
    for lab, c in enumerate(counts, 1):
        eps = [_ep(lab, n, picked=lab == 1 and n <= prior) for n in range(1, c + 1)]
        revlab.save(RevLab(id=lab, title=TITLE, episodes=eps))


def test_strip_head(client):
    m = _script()
    text, dropped = m.strip_head("제3화\n짧은 제목\n\n서윤은 문을 열었다.\n다음 줄.", ("짧은 제목",))
    assert text == "서윤은 문을 열었다.\n다음 줄." and dropped == [3, 5]
    text, dropped = m.strip_head("# 3화\n\n**작품 이름**\n\n본문이 시작한다.", ("", "작품 이름"))
    assert text == "본문이 시작한다." and dropped == [4, 9]
    short = "짧은 첫 줄\n다음 줄."  # heads 와 다른 짧은 줄은 문장 끝 부호가 없어도 빼지 않는다
    assert m.strip_head(short, ("다른 제목",)) == (short, [])
    assert m.strip_head(short) == (short, [])
    assert m.strip_head("12화 시작\n본문이 이어진다.")[1] == [6]


def test_cut(client):
    m = _script()
    short = "가" * 1_800
    assert m.cut(short) == short
    a = "가" * 1_900 + "\n \n" + "나" * 1_000
    assert m.cut(a) == "가" * 1_900
    b = "가" * 2_450 + "다. 이어지는 글" 
    assert m.cut(b) == "가" * 2_450 + "다."
    c = "가" * 2_000 + "\n\n" + "나" * 500 + "\n\n끝."
    assert m.cut(c) == "가" * 2_000  # CUT_MIN 뒤 첫 빈 줄이 CUT_MAX 안이라 거기서 자른다


def test_pool(client):
    m = _script()
    revlab.save(RevLab(id=1, title=TITLE, episodes=[
        _ep(1, 1, picked=True),
        _ep(1, 2, takes=[RevTake(no=1, text="멈춘 글", stopped=True), RevTake(no=2, text="  ")]),
        _ep(1, 3, takes=[RevTake(no=1, text="a 글", model="x"), RevTake(no=2, text="b 글", model="y"), RevTake(no=3, text="c 글")]),
    ]))
    revlab.save(RevLab(id=2, title=TITLE, episodes=[_ep(2, 1)]))
    eps, counts = m.pool([])
    assert [e["piece"] for e in eps] == ["L1-E1", "L1-E3", "L2-E1"]
    assert counts == {"labs": 2, "episodes": 3, "excluded": 0, "prior_read": 1}
    assert [e["prior_read"] for e in eps] == [True, False, False]
    again, _ = m.pool([])
    assert [e["ai"] for e in again] == [e["ai"] for e in eps]
    assert eps[1]["ai"] in ("a 글", "b 글", "c 글")
    assert eps[2]["model"] == "m2"


def test_pool_exclude(client):
    m = _script()
    _labs((3, 2), prior=0)
    src = revlab.load(1).episodes[1].text
    pilot = blindset.create("t", [{"text": "  ".join(src.split()[3:30])}, {"text": "다른 글"}],
                            [{"no": "01", "arm": "원문", "piece": "p"}, {"no": "02", "arm": "m1", "piece": "p"}])
    eps, counts = m.pool([pilot.id])
    assert counts["excluded"] == 1 and counts["episodes"] == 5
    assert "L1-E2" not in [e["piece"] for e in eps] and len(eps) == 4


def test_select(client):
    m = _script()
    _labs()
    eps, _ = m.pool([])
    a = m.select(eps)
    assert len(a) == 40
    assert [e["piece"] for e in a] == [e["piece"] for e in m.select(eps)]
    assert not any(e["prior_read"] for e in a[:35]) and sum(e["prior_read"] for e in a) == 5


def test_build(client, tmp_path):
    m = _script()
    _labs()
    out = tmp_path / "out"
    s = m.build(out, [])
    assert s["selected"] == 40 and s["pool"] == {"labs": 2, "episodes": 45, "excluded": 0, "prior_read": 10}
    assert [x["folder"] for x in s["sets"]] == ["set1", "set2"]
    assert all(x["items"] == 42 and x["duels"] == 22 and x["repeats"] == 2 for x in s["sets"])
    assert not any(x["adjacent_left"] for x in s["sets"])
    got = blindset.import_folder(str(out / "set1"))
    assert len(blindset.duel_pairs(got)) == 22
    assert {k.arm for k in got.key} <= {"원문", "m1", "m2"} and "원문" in {k.arm for k in got.key}
    text = (out / "summary.json").read_text(encoding="utf-8")
    assert "MARK_" not in text and TITLE not in text and "문장입니다" not in text
    assert json.loads(text)["episodes"][0]["source_chars"] > 1_800
    assert "제" not in (out / "set1" / "01.txt").read_text(encoding="utf-8")[:1]


def test_build_refuses_nonempty(client, tmp_path):
    m = _script()
    _labs((3,), prior=0)
    out = tmp_path / "out"
    out.mkdir()
    (out / "x.txt").write_text("a", encoding="utf-8")
    with pytest.raises(SystemExit):
        m.build(out, [])
    assert [p.name for p in out.iterdir()] == ["x.txt"]
