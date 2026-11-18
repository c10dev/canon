"""보는 눈(canon/charviews.py) 테스트: 옛 작품 읽힘, 저장 · 읽기, 되돌리기, live, 작품 전체 저장 보호. 실행: python -m pytest tests"""
from canon import charviews, features, pipeline, store
from canon.schema import CharView, Project

from .test_autorun import Policy, demo  # noqa: F401  (pytest fixture)
from .test_storylines import _short
from .test_timeline import _play


def _views(p):
    return [CharView(viewer="hero", target="ally", episode=1, verdict="믿음직"),
            CharView(viewer="ally", target="hero", episode=2, verdict="철없음", surface="대단해요", basis=["t1"]),
            CharView(viewer="hero", target="ally", episode=3, verdict="수상함"),
            CharView(viewer="ghost", target="hero", episode=1, verdict="x"),
            CharView(viewer="hero", target="ghost", episode=2, verdict="y")]


def test_old_project_reads_without_views():
    p = Project.model_validate({"meta": {"title": "x"}, "characters": [{"id": "a", "name": "A", "role": ""}]})
    assert p.views == []
    assert Project.model_validate(p.model_dump(mode="json")).views == []


def test_roundtrip():
    p = Project()
    p.views = [CharView(viewer="a", target="b", episode=2, verdict="v", surface="s", basis=["t"])]
    q = Project.model_validate(p.model_dump(mode="json"))
    assert q.views == p.views


def test_revert_and_live():
    p = _short(8)
    p.views = _views(p)
    assert [v.episode for v in charviews.live(p)] == [1, 2, 3]
    charviews.revert(p, 2)
    assert [(v.viewer, v.episode) for v in p.views] == [("hero", 1), ("ally", 2)]


def test_pipeline_revert_hook():
    assert any(h.__closure__ is not None and charviews.revert in [c.cell_contents for c in h.__closure__] for h in features.REVERT_LAST)
    p = _play(_short(8), 1, 3)
    p.views = _views(p)
    pipeline.revert(p, 2)
    assert [v.episode for v in p.views] == [1, 2]


def test_full_save_keeps_views(client):  # noqa: F811
    p = _play(_short(8), 1, 1)
    p.views = [CharView(viewer="hero", target="ally", episode=1, verdict="믿음직")]
    store.save("vw", p)
    out = client.get("/api/projects/vw").json()
    out["views"] = []
    out = client.put("/api/projects/vw", json=out).json()
    assert len(out["views"]) == 1
    assert len(store.load("vw").views) == 1
