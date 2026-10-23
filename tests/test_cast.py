"""인물 화면(canon/cast.py) 테스트 (mock LLM): 화별 관계 프레임, 지워진 스냅샷 채우기, 등장, 타임라인, CLI, 웹. 실행: python -m pytest tests"""
import importlib

from fastapi.testclient import TestClient

from canon import cast, cli, pipeline, store
from canon.llm import get_llm
from canon.schema import Secret, StoryEvent

from .test_storylines import _short


def _played(n_eps=4):
    p = _short(8)
    p.episode(3).plot.pov = "ally"
    for n in range(1, n_eps + 1):
        pipeline.confirm_plot(p, n)
        p.episode(n).text = pipeline.write_episode(get_llm("write"), p, n)
        p.episode(n).status = "written"
        d = pipeline.extract_state(get_llm("state"), p, n)
        if n == 2:
            d.events.append(StoryEvent(episode=2, actor="hero", target="ally", kind="모욕", intensity=3, quote="꺼져."))
            d.secrets_added.append(Secret(id="sec-x", owner="ally", content="편지를 숨겼다", hidden_from=["hero"]))
        pipeline.apply_delta(p, d)
    return p


def test_frames_follow_snapshots():
    p = _played()
    fs = cast.frames(p)
    assert [f["episode"] for f in fs] == [0, 1, 2, 3, 4]
    for f in fs:
        snap = p.snapshot(f["episode"])
        assert {(t["source"], t["target"], t["stage"]) for t in f["ties"]} == {(t.source, t.target, t.stage) for t in snap.ties}
    last = fs[-1]
    t = next(t for t in last["ties"] if t["source"] == "ally" and t["target"] == "hero")
    tie = next(x for x in p.ties if x.source == "ally" and x.target == "hero")
    assert t["warmth"] == round(tie.warmth, 3) and t["warmth_word"]
    pair = last["pairs"][0]
    assert {pair["a"], pair["b"]} == {"hero", "ally"} and 0 <= pair["tension"] <= 10 and pair["tension_word"]
    assert any(s["id"] == "sec-x" for s in last["secrets"]) and not any(s["id"] == "sec-x" for s in fs[1]["secrets"])


def test_pruned_snapshots_are_replayed():
    p = _played()
    full = cast.frames(p)
    p.snapshots = [s for s in p.snapshots if s.episode in (0, 3)]  # 장편이 오래된 스냅샷을 지운 경우
    gap = cast.frames(p)
    assert [f["episode"] for f in gap] == [0, 1, 2, 3, 4]
    for a, b in zip(full, gap):
        assert a["ties"] == b["ties"] and a["states"] == b["states"] and a["secrets"] == b["secrets"], a["episode"]


def test_no_finalized_episode_shows_start():
    p = _short(6)
    p.ties = []
    fs = cast.frames(p)
    assert [f["episode"] for f in fs] == [0] and fs[0]["ties"]  # 설정 화면 관계로 시작 간선을 만든다
    assert not p.ties  # 원본은 건드리지 않는다


def test_appearances_and_timeline():
    p = _played()
    apps = cast.appearances(p)
    ally = {a["n"]: a for a in apps["ally"]}
    assert ally[3]["pov"] and not ally.get(1, {"pov": False})["pov"]
    assert {a["status"] for a in apps["hero"]} >= {"finalized", "draft"}
    tl = cast.timeline(p, "hero")
    two = next(r for r in tl if r["n"] == 2)
    assert any(e["kind"] == "모욕" for e in two["events"]) and two["changes"].get("emotional_state")
    assert "2화 단서" in two["changes"]["knows"] and "1화 단서" not in two["changes"]["knows"]  # 새로 안 것만
    assert next(r for r in cast.timeline(p, "ally") if r["n"] == 2)["secrets"] == ["편지를 숨겼다"]


def test_cli_cast(capsys):
    p = _played(2)
    store.save("castdemo", p)
    cli.main(["cast", "castdemo"])
    out = capsys.readouterr().out
    assert "서윤 (hero)" in out and "등장" in out
    cli.main(["cast", "castdemo", "도현", "--numbers"])
    out = capsys.readouterr().out
    assert "도현 → 서윤: 온기" in out and "2화" in out and "시점" not in out.split("화별")[0].split("등장")[0]


def test_web_cast(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    from canon import store as st, web

    importlib.reload(st)
    importlib.reload(web)
    st.save("w", _played(2))
    r = TestClient(web.app).get("/api/projects/w/cast").json()
    assert [f["episode"] for f in r["frames"]] == [0, 1, 2]
    assert set(r["timelines"]) == {"hero", "ally", "innkeeper"} and r["appearances"]["hero"]
