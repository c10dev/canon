"""상태 반영 전제 테스트 (mock LLM): 웹 · 명령줄 update · 플레이 · 자동 집필이 같은 pipeline.check_applicable 을 쓰고,
명령줄 update 가 반영 완료한 화를 다시 반영하거나 앞 화를 건너뛰지 않으며, 관계 단계와 반대인 관계 바뀜은 따로 묻는다(기본 아니오).
실행: python -m pytest tests"""
import contextlib
import io

import pytest

from canon import cli, store
from canon.pipeline import check_applicable
from canon.schema import Relationship, StateDelta

from .test_pace import _set
from .test_storylines import _short
from .test_timeline import _play


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setattr(store, "ROOT", tmp_path)
    return tmp_path


def _run(args, answers=()):
    out = io.StringIO()
    it = iter(answers)
    with contextlib.redirect_stdout(out), pytest.MonkeyPatch.context() as m:
        m.setattr("builtins.input", lambda q="": (print(q), next(it))[1])
        cli.main(args)
    return out.getvalue()


def test_check_applicable():
    p = _short(4)
    with pytest.raises(ValueError, match="본문이 작성된 상태가 아니에요"):
        check_applicable(p, 1)
    _play(p, 1, 1)
    with pytest.raises(ValueError, match="이미 상태를 반영했어요"):
        check_applicable(p, 1)
    p.episode(3).status = "written"
    with pytest.raises(ValueError, match=r"이전 화\(2화\)"):
        check_applicable(p, 3)
    p.episode(2).status = "written"
    check_applicable(p, 2)


def test_cli_update_refuses_finalized(home):
    p = _play(_short(4), 1, 1)
    store.save("g", p)
    out = _run(["update", "g", "1", "-y"])
    assert "이미 상태를 반영했어요" in out and "revert g 1" in out
    assert len(store.load("g").history) == len(p.history)


def test_cli_update_refuses_skipping(home):
    p = _play(_short(4), 1, 1)
    p.episode(3).text, p.episode(3).status = "본문", "written"
    store.save("g", p)
    out = _run(["update", "g", "3", "-y"])
    assert "이전 화(2화)" in out
    assert store.load("g").episode(3).status == "written"


def _flagged(home):
    p = _play(_short(4), 1, 1)
    _set(p, "적대", -0.6)
    p.episode(2).text, p.episode(2).status = "본문", "written"
    store.save("g", p)
    f = home / "d.json"
    f.write_text(StateDelta(episode=2, summary="2화", relationship_updates=[Relationship(a="hero", b="ally", type="서로 믿는 친구")])
                 .model_dump_json(), encoding="utf-8")
    return str(f)


def test_cli_update_asks_flagged_default_no(home):
    f = _flagged(home)
    out = _run(["update", "g", "2", "--from-json", f], ["y", ""])
    assert "기본으로 빼 둔 관계 바뀜" in out and "서로 믿는 친구" in out
    q = store.load("g")
    assert q.episode(2).status == "finalized"
    assert next(r for r in q.relationships if {r.a, r.b} == {"hero", "ally"}).type != "서로 믿는 친구"
    assert [r.type for r in q.history[-1].dismissed.relationship_updates] == ["서로 믿는 친구"]


def test_cli_update_flagged_yes_applies(home):
    f = _flagged(home)
    _run(["update", "g", "2", "--from-json", f], ["y", "y"])
    q = store.load("g")
    assert next(r for r in q.relationships if {r.a, r.b} == {"hero", "ally"}).type == "서로 믿는 친구"
