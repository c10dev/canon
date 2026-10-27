"""원형 도감 화면(static/archetypes.js)의 dexMatch · dexRemember 가 archetypes.match · remember 와 같은지. node 가 있을 때만 돈다."""
from canon import archetypes, genres
from canon.schema import Project

from .jsvm import dump, needs_node, run_js

GENRE_PICKS = [[], ["romance"], ["fantasy", "mystery"], ["office", "sports", "bl"], ["없는 장르"], [g.id for g in genres.CATALOG]]

# (인물, 원형, 비틀기) 를 차례로 남긴다
STEPS = [
    ("c1", "a1", ""),
    ("c2", "a2", "겁이 많다"),
    ("c2", "a2", ""),           # 비틀기를 새로 고르지 않으면 전 것을 둔다
    ("c2", "a2", "말이 없다"),   # 새로 고르면 바꾼다
    ("c2", "a3", ""),           # 원형을 바꾸면 전 비틀기는 지운다
    ("c1", "a4", "웃음이 많다"),
    ("c1", "a4", ""),
    ("c3", "a1", "x"),
]


@needs_node
def test_dex_match_matches_server():
    catalog = [dump(a) for a in archetypes.CATALOG]
    expr = """data.picks.map((gs) => { S.project = data.project; P().meta.genres = gs; S.dex = { archetypes: data.catalog };
      return [dexMatch(false).map((a) => a.id), dexMatch(true).length]; })"""
    got = run_js(["app.js", "archetypes.js"], expr, {"picks": GENRE_PICKS, "catalog": catalog, "project": dump(Project())})
    for gs, (ids, everything) in zip(GENRE_PICKS, got):
        assert ids == [a.id for a in archetypes.match(gs)], gs
        assert everything == len(archetypes.CATALOG)
    assert len({tuple(ids) for ids, _ in got}) == len(GENRE_PICKS)  # 고른 장르마다 결과가 다르다


@needs_node
def test_dex_remember_matches_server():
    expr = """data.steps.map((upto) => { S.project = structuredClone(data.project);
      upto.forEach(([c, a, t]) => dexRemember(c, a, t)); return S.project.cast_archetypes; })"""
    prefixes = [STEPS[:i] for i in range(1, len(STEPS) + 1)]
    got = run_js(["app.js", "archetypes.js"], expr, {"steps": prefixes, "project": dump(Project())})
    for steps, picks in zip(prefixes, got):
        p = Project()
        for c, a, t in steps:
            archetypes.remember(p, c, a, t)
        assert picks == [dump(x) for x in p.cast_archetypes], steps
