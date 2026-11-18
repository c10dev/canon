"""인물 자취(canon/trails.py) 테스트: 옛 작품 읽힘, 저장 · 읽기, 되돌리기, live, next_id, 보는 눈 basis, 작품 전체 저장 보호. 실행: python -m pytest tests"""
from canon import charviews, features, pipeline, store, trails
from canon.schema import CharTrail, CharView, Project, TrailEcho

from .test_autorun import Policy, demo  # noqa: F401  (pytest fixture)
from .test_storylines import _short
from .test_timeline import _play


def _trails():
    return [CharTrail(id="tr-001-1", character="hero", episode=1, label="약속", witnesses=["ally", "ghost"],
                      echoes=[TrailEcho(episode=2, character="ally", meaning="기억"), TrailEcho(episode=3, character="hero"),
                              TrailEcho(episode=2, character="ghost")]),
            CharTrail(id="tr-002-1", character="ally", episode=2, kind="말", label="거짓말"),
            CharTrail(id="tr-003-1", character="hero", episode=3, kind="드러냄", label="과거"),
            CharTrail(id="tr-002-2", character="ghost", episode=2, label="사라짐")]


def test_old_project_reads_without_trails():
    p = Project.model_validate({"meta": {"title": "x"}, "characters": [{"id": "a", "name": "A", "role": ""}]})
    assert p.trails == []
    assert Project.model_validate(p.model_dump(mode="json")).trails == []


def test_roundtrip():
    p = Project()
    p.trails = _trails()
    q = Project.model_validate(p.model_dump(mode="json"))
    assert q.trails == p.trails


def test_revert_drops_later_episodes():
    p = _short(8)
    p.trails = _trails()[:3]
    trails.revert(p, 2)
    assert [t.id for t in p.trails] == ["tr-001-1", "tr-002-1"]
    assert [e.episode for e in p.trails[0].echoes] == [2]


def test_deleted_character():
    p = _short(8)
    p.trails = _trails()
    before = [t.model_dump() for t in p.trails]
    got = trails.live(p)
    assert [t.id for t in got] == ["tr-001-1", "tr-002-1", "tr-003-1"]
    assert got[0].witnesses == ["ally"]
    assert [e.character for e in got[0].echoes] == ["ally", "hero"]
    assert [t.model_dump() for t in p.trails] == before
    trails.revert(p, 9)
    assert p.trails == got


def test_next_id():
    p = Project()
    assert trails.next_id(p, 5) == "tr-005-1"
    p.trails = [CharTrail(id="tr-005-1", character="a", episode=5, label="x"), CharTrail(id="tr-005-2", character="a", episode=5, label="y"),
                CharTrail(id="tr-006-9", character="a", episode=6, label="z")]
    assert trails.next_id(p, 5) == "tr-005-3"


def test_views_basis_follows_trails():
    p = _short(8)
    p.trails = _trails()[:1]
    p.views = [CharView(viewer="hero", target="ally", episode=1, verdict="v", basis=["tr-001-1", "tr-009-1"])]
    got = charviews.live(p)
    assert got[0].basis == ["tr-001-1"]
    assert p.views[0].basis == ["tr-001-1", "tr-009-1"]
    charviews.revert(p, 5)
    assert len(p.views) == 1
    assert p.views[0].basis == ["tr-001-1"]


def test_revert_hook():
    names = [h.__closure__[0].cell_contents for h in features.REVERT_LAST if h.__closure__]
    assert trails.revert in names
    assert names.index(trails.revert) < names.index(charviews.revert)
    p = _play(_short(8), 1, 3)
    p.trails = _trails()[:3]
    p.views = [CharView(viewer="hero", target="ally", episode=2, verdict="v", basis=["tr-003-1", "tr-001-1"])]
    pipeline.revert(p, 2)
    assert [t.id for t in p.trails] == ["tr-001-1", "tr-002-1"]
    assert p.views[0].basis == ["tr-001-1"]


def test_full_save_keeps_trails(client):  # noqa: F811
    p = _play(_short(8), 1, 1)
    p.trails = [CharTrail(id="tr-001-1", character="hero", episode=1, label="약속")]
    store.save("tr", p)
    out = client.get("/api/projects/tr").json()
    out["trails"] = []
    out = client.put("/api/projects/tr", json=out).json()
    assert len(out["trails"]) == 1
    assert len(store.load("tr").trails) == 1
