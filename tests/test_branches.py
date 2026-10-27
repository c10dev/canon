"""갈래 테스트 (mock LLM): n화부터 갈래 만들기(clear · keep), 원본 그대로, 갈래 집안 계산(diverge, promote, remove),
함께 쓰는 앞 화 고침 알아보기, 두 갈래 비교. 실행: python -m pytest tests"""
import pytest

from canon import branches, store
from canon.schema import BranchInfo, Part, StoryArc

from .test_restate import _two_done
from .test_web import client  # noqa: F401  (pytest fixture)


def test_make_clear_keeps_source(client):
    _two_done(client)
    src_file = store.project_dir("lh") / "project.json"
    before = src_file.read_bytes()
    assert store.load_branch("lh") is None  # 갈래 정보가 없는 옛 작품

    q, info = branches.make("lh", "lh-b", 2, "clear", " B안 ")
    assert src_file.read_bytes() == before  # 원본 project.json 은 그대로다
    main = store.load_branch("lh")
    assert main is not None and main.parent == "" and main.family == main.id
    assert info.family == main.family and info.parent == main.id and info.from_ep == 2 and info.label == "B안"
    assert store.load_branch("lh-b") == info

    q = store.load("lh-b")
    e1, e2 = q.episode(1), q.episode(2)
    assert e1.status == "finalized" and e1.text
    assert e2.status == "confirmed" and e2.text == "" and e2.issues == []
    assert e2.versions[-1].kind == "previous" and e2.versions[-1].text == "2화 본문."
    assert max(s.episode for s in q.snapshots) == 1 and all(h.episode <= 1 for h in q.history)
    assert not (store.project_dir("lh-b") / "episodes" / "02.md").exists()
    assert (store.project_dir("lh-b") / "episodes" / "01.md").exists()
    assert not (store.project_dir("lh-b") / "pending.json").exists()


def test_make_keep_and_limits(client):
    _two_done(client)
    branches.make("lh", "lh-k", 2, "keep")
    e2 = store.load("lh-k").episode(2)
    assert e2.status == "written" and e2.text == "2화 본문."  # 본문을 남기고 상태 승인을 다시 한다

    # 반영한 화 다음 화까지만, 같은 이름은 안 된다. 원본에 이미 갈래 정보가 있으면 그대로 쓴다
    main = store.load_branch("lh")
    with pytest.raises(ValueError):
        branches.make("lh", "lh-x", 4)
    with pytest.raises(ValueError):
        branches.make("lh", "lh-k", 1)
    assert not store.exists("lh-x")
    _, info = branches.make("lh", "lh-c", 3)  # 3화부터: 되돌릴 반영이 없다
    assert store.load_branch("lh") == main and info.parent == main.id
    assert store.load("lh-c").episode(2).status == "finalized"


def test_fork_clears_later_arc_summaries(client):
    _two_done(client)
    p = store.load("lh")
    p.story_arcs = [StoryArc(number=1, title="첫", start_ep=1, end_ep=1, goal="", summary="아크 1 요약"),
                    StoryArc(number=2, title="둘", start_ep=2, end_ep=3, goal="", summary="아크 2 요약")]
    p.parts = [Part(number=1, title="1부", start_ep=1, end_ep=3, goal="", summary="1부 요약")]
    branches.fork(p, 2)
    assert [a.summary for a in p.story_arcs] == ["아크 1 요약", ""] and p.parts[0].summary == ""


def test_shared_edited(client):
    _two_done(client)
    _, info = branches.make("lh", "lh-b", 2)
    src, q = store.load("lh"), store.load("lh-b")
    assert not branches.shared_edited(src, info) and not branches.shared_edited(q, info)
    q.episode(1).text += "\n\n갈래에서 덧붙임."
    assert branches.shared_edited(q, info) and not branches.shared_edited(src, info)
    q.episode(2).text = "2화는 함께 쓰지 않는다."
    src.episode(2).text = "원본 2화를 고쳐도 상관없다."
    assert not branches.shared_edited(src, info)
    assert not branches.shared_edited(src, BranchInfo(id="m", family="m"))  # 본편 자신은 비교할 갈래가 아니다


def _fam():
    """본편 M ← A(5화) ← B(8화), M ← C(3화)."""
    return {"M": BranchInfo(id="m", family="f"),
            "A": BranchInfo(id="a", family="f", parent="m", from_ep=5, base="ha"),
            "B": BranchInfo(id="b", family="f", parent="a", from_ep=8, base="hb"),
            "C": BranchInfo(id="c", family="f", parent="m", from_ep=3, base="hc"),
            "X": BranchInfo(id="x", family="other")}


def _pairs(fam):
    names = sorted(fam)
    return {(a, b): branches.diverge(fam, a, b) for a in names for b in names}


def test_family_and_diverge():
    fam = branches.family(_fam(), "B")
    assert sorted(fam) == ["A", "B", "C", "M"] and branches.main_of(fam) == "M"
    assert branches.family(_fam(), "없음") == {}
    assert branches.path_up(fam, "B") == ["B", "A", "M"]
    assert sorted(branches.children(fam, "M")) == ["A", "C"]
    assert branches.diverge(fam, "B", "A") == 8 and branches.diverge(fam, "B", "M") == 5
    assert branches.diverge(fam, "B", "C") == 3 and branches.diverge(fam, "A", "A") == 0
    assert branches.diverge(_fam(), "B", "X") == 1


def test_promote_keeps_divergence():
    fam = branches.family(_fam(), "M")
    out = branches.promote(fam, "B")
    assert sorted(out) == ["A", "B", "M"]
    new = {**fam, **out}
    assert branches.main_of(new) == "B" and new["B"].from_ep == 0 and new["B"].base == ""
    assert (new["A"].parent, new["A"].from_ep, new["A"].base) == ("b", 8, "hb")
    assert (new["M"].parent, new["M"].from_ep, new["M"].base) == ("a", 5, "ha")
    assert _pairs(new) == _pairs(fam)  # 누가 본편이든 두 작품이 몇 화부터 다른지는 같다
    assert branches.promote(fam, "M") == {}


def test_remove_reparents():
    fam = branches.family(_fam(), "M")
    out = branches.remove(fam, "A")  # B 는 M 에 붙고, 5화부터 다르다
    assert sorted(out) == ["B"] and (out["B"].parent, out["B"].from_ep, out["B"].base) == ("m", 5, "ha")

    out = branches.remove(fam, "M")  # 본편을 빼면 가장 늦게 갈라진 자식 A 가 본편이 된다
    new = {k: v for k, v in {**fam, **out}.items() if k != "M"}
    assert "M" not in out and branches.main_of(new) == "A"
    assert (new["C"].parent, new["C"].from_ep) == ("a", 3) and (new["B"].parent, new["B"].from_ep) == ("a", 8)
    left = {k: v for k, v in _pairs(fam).items() if "M" not in k}
    assert {k: branches.diverge(new, *k) for k in left} == left

    assert branches.remove({"M": fam["M"]}, "M") == {}


def test_compare(client):
    _two_done(client)
    branches.make("lh", "lh-b", 2, "keep")
    d = client.post("/api/projects/lh-b/episodes/2/state").json()
    d["new_facts"] = d["new_facts"] + ["갈래에서만 등대가 무너졌다"]
    ups = d["character_updates"]
    if ups:
        ups[0]["emotional_state"] = "갈래 감정"
    assert client.post("/api/projects/lh-b/episodes/2/apply", json=d).status_code == 200

    a, b = store.load("lh"), store.load("lh-b")
    diff = branches.compare(a, b, 2, 2)
    assert diff.ready_a and diff.ready_b and [e.number for e in diff.episodes][0] == 2
    assert diff.episodes[0].a.status == diff.episodes[0].b.status == "finalized"
    assert diff.text_a == a.episode(2).text and diff.text_b == b.episode(2).text
    assert any(r.kind == "fact" and r.b == "갈래에서만 등대가 무너졌다" and r.a == "" for r in diff.rows)
    if ups:
        assert any(r.kind == "character" and r.field == "감정" and r.b == "갈래 감정" for r in diff.rows)
    assert branches.compare(a, a, 2, 2).rows == []  # 같으면 다른 칸이 없다

    diff = branches.compare(a, b, 2, 3)  # 3화는 어느 쪽도 반영 전이라 상태 차이를 비운다
    assert not diff.ready_a and diff.rows == []


# ---------- 웹 엔드포인트 ----------

def test_web_make_list_compare(client):
    _two_done(client)
    r = client.post("/api/projects/lh/branch", json={"to": "lh-b", "from_ep": 2, "label": "B안"})
    assert r.status_code == 200
    m = r.json()
    assert m["name"] == "lh-b" and m["parent_name"] == "lh" and m["depth"] == 1 and m["info"]["from_ep"] == 2
    assert m["finalized"] == 1 and not m["shared_edited"] and not m["parent_edited"]
    assert client.post("/api/projects/lh/branch", json={"to": "lh-b", "from_ep": 2}).status_code == 409
    assert client.post("/api/projects/lh/branch", json={"to": "a/b", "from_ep": 2}).status_code == 400
    assert client.post("/api/projects/lh/branch", json={"to": "lh-x", "from_ep": 9}).status_code == 400
    assert client.post("/api/projects/없음/branch", json={"to": "lh-y", "from_ep": 1}).status_code == 404

    fam = client.get("/api/projects/lh-b/branches").json()
    assert fam["main"] == "lh" and [x["name"] for x in fam["members"]] == ["lh", "lh-b"]
    cards = {c["name"]: c for c in client.get("/api/projects").json()}
    assert cards["lh"]["branch"]["parent"] == "" and cards["lh-b"]["branch"]["parent"] == cards["lh"]["branch"]["id"]

    # 1화는 lh-b 에서 반영했고 2화는 lh 에서만 반영했다: 기본으로 2화를 견주고 lh-b 는 아직 반영 전이다
    d = client.get("/api/projects/lh/compare/lh-b").json()
    assert d["from_ep"] == 2 and d["episode"] == 2 and d["ready_a"] and not d["ready_b"] and d["rows"] == []
    assert d["episodes"][0]["b"]["status"] == "confirmed"
    assert client.get("/api/projects/lh/compare/lh-b?ep=1").json()["rows"] == []
    assert client.get("/api/projects/lh/compare/lh").status_code == 400

    # 복제는 갈래 정보를 옮기지 않는다
    client.post("/api/projects/lh/duplicate", json={"name": "lh-copy"})
    assert store.load_branch("lh-copy") is None and client.get("/api/projects/lh-copy/branches").json()["members"] == []
    assert client.get("/api/projects/lh/compare/lh-copy").status_code == 400

    # 함께 쓰는 1화를 갈래에서 고치면 알린다
    client.put("/api/projects/lh-b/episodes/1/text", json={"text": "갈래에서 고친 1화."})
    m = next(x for x in client.get("/api/projects/lh/branches").json()["members"] if x["name"] == "lh-b")
    assert m["shared_edited"] and not m["parent_edited"]


def test_web_promote_detach_delete(client):
    _two_done(client)
    client.post("/api/projects/lh/branch", json={"to": "lh-b", "from_ep": 2})
    client.post("/api/projects/lh/branch", json={"to": "lh-c", "from_ep": 1, "mode": "keep"})
    before = (store.project_dir("lh") / "project.json").read_bytes()

    fam = client.post("/api/projects/lh-b/promote").json()  # 폴더 이름과 작품 데이터는 그대로다
    assert fam["main"] == "lh-b" and [(x["name"], x["depth"]) for x in fam["members"]] == [("lh-b", 0), ("lh", 1), ("lh-c", 2)]
    assert (store.project_dir("lh") / "project.json").read_bytes() == before
    assert client.post("/api/projects/lh-copy/promote").status_code == 404

    fam = client.post("/api/projects/lh/detach").json()  # lh 를 끊으면 lh-c 는 lh-b 에 1화부터 갈라진 갈래로 붙는다
    assert fam["members"] == [] and store.load_branch("lh") is None
    fam = client.get("/api/projects/lh-b/branches").json()
    assert [(x["name"], x["parent_name"], x["info"]["from_ep"]) for x in fam["members"]] == [("lh-b", "", 0), ("lh-c", "lh-b", 1)]
    assert client.post("/api/projects/lh/detach").status_code == 400

    assert client.delete("/api/projects/lh-b").status_code == 200  # 본편을 지우면 혼자 남은 lh-c 는 갈래가 없는 작품이 된다
    assert store.load_branch("lh-c") is None and client.get("/api/projects/lh-c/branches").json()["members"] == []


# ---------- 명령줄 ----------

def test_cli(client, capsys):
    from canon import cli

    _two_done(client)
    cli.main(["branches", "lh"])
    assert "갈래가 없어요" in capsys.readouterr().out

    cli.main(["branch", "lh", "2", "lh-b", "--label", "B안"])
    out = capsys.readouterr().out
    assert "갈래를 만들었어요: lh-b (B안, 2화부터)" in out and "write lh-b 2" in out
    cli.main(["branch", "lh", "2", "lh-k", "--keep"])
    assert "update lh-k 2" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["branch", "lh", "9", "lh-x"])

    cli.main(["branches", "lh-b"])
    out = capsys.readouterr().out.splitlines()
    assert out[0].endswith("(lh) · 본편 · 2 / 10화 반영")
    assert out[1] == "  └ B안 (lh-b) · 2화부터 · 1 / 10화 반영  ← 지금" and out[2].startswith("  └ lh-k · 2화부터")

    cli.main(["branch-compare", "lh", "lh-b", "--text"])
    out = capsys.readouterr().out
    assert "lh · lh-b: 2화부터 달라요 (1화는 함께 써요)" in out
    assert "lh-b에서 2화를 아직 반영하지 않아 상태는 견줄 수 없어요" in out and "[lh · 2화 본문]\n2화 본문." in out
    cli.main(["branch-compare", "lh", "lh-k", "--ep", "1"])
    assert "[1화 반영 직후 상태]\n같아요" in capsys.readouterr().out

    cli.main(["promote", "lh-b", "-y"])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "본편으로 올렸어요" and out[1].startswith("B안 (lh-b) · 본편")
