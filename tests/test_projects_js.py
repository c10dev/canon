"""작품 목록 계산(static/home.js plStatus · plRows)을 node 로 맞춰 본다. node 가 있을 때만 돈다."""
from .jsvm import needs_node, run_js

FILES = ["app.js", "home.js", "branches.js"]


def card(name, title="", fin=0, eps=12, planned=12, genre="판타지", branch=None, play=None):
    return {"name": name, "title": title or name, "genre": genre, "form": "short", "episodes": eps, "finalized": fin,
            "planned": planned, "open_ep": 0 if fin >= eps or not planned else fin + 1, "open_status": "" if fin >= eps or not planned else "confirmed",
            "updated_at": "", "branch": branch, "play": play}


def branch(id, parent="", from_ep=0, label=""):
    return {"id": id, "family": "fam", "parent": parent, "from_ep": from_ep, "label": label}


def play(world, title):
    return {"world": world, "title": title, "player": "서린", "origin": "random", "ending": "", "turns": 3, "decisions": 2, "days": 4, "waiting": True}


LIST = [
    card("sea", "검은 바다", fin=3, eps=120, branch=branch("a")),
    card("glass", "유리 정원", fin=0, eps=16, genre="로맨스"),
    card("sea-b", "검은 바다 B", fin=5, eps=120, branch=branch("b", "a", 4, "떠나는 길")),
    card("fog", "안개 고양이", fin=10, eps=10, planned=10, genre="일상"),
    card("sea-play", "", fin=0, eps=120, play=play("sea", "서린의 삶")),
    card("lost-play", "", play=play("gone", "옛 삶")),
    card("blank", "빈 작품", fin=0, eps=12, planned=0),
]


def rows(**opt):
    expr = """(() => { const r = plRows(data.list, data.opt);
      return { names: r.groups.map((g) => g.card.name), counts: r.counts, lost: r.lost.map((x) => x.name),
               kids: r.groups.map((g) => [g.branches.map((b) => b.card.name), g.plays.map((y) => y.name)]) }; })()"""
    return run_js(FILES, expr, {"list": LIST, "opt": opt})


@needs_node
def test_status_matches_project_next():
    got = run_js(FILES, "data.list.map((x) => [plStatus(x), projectNext(x)])", {"list": LIST[:4] + [LIST[6]]})
    assert got == [["writing", "4화 쓰기 대기"], ["fresh", "1화 쓰기 대기"], ["writing", "6화 쓰기 대기"], ["done", "완결"], ["fresh", "플롯 없음"]]


@needs_node
def test_rows_group_branches_and_plays():
    r = rows()
    assert r["names"] == ["sea", "glass", "fog", "blank"]
    assert r["kids"][0] == [["sea-b"], ["sea-play"]]
    assert r["lost"] == ["lost-play"]
    assert r["counts"] == {"all": 4, "writing": 1, "fresh": 2, "done": 1}


@needs_node
def test_rows_find_filter_sort():
    # 찾기는 갈래 · 플레이 이름도 보고, 낱말마다 맞아야 한다. 수는 찾기만 거친 값
    assert rows(q="떠나는")["names"] == ["sea"]
    assert rows(q="서린의")["names"] == ["sea"]
    assert rows(q="로맨스 유리")["names"] == ["glass"]
    assert rows(q="없는말")["names"] == []
    r = rows(q="정원", filter="done")
    assert (r["names"], r["counts"]["fresh"]) == ([], 1)
    assert rows(filter="fresh")["names"] == ["glass", "blank"]
    assert rows(sort="title")["names"] == ["sea", "blank", "fog", "glass"]
    assert rows(sort="progress")["names"][:2] == ["fog", "sea"]
