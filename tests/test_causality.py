"""인과율(이야기 요소와 영향 분석) 테스트 (mock LLM). 실행: python -m pytest tests"""
from canon import elements, prompts
from canon.schema import Episode, EpisodePlot, Project, StoryElement

from .test_web import _wait, client  # noqa: F401  (pytest fixture)


def _plot(n, chars=("hero",), summary="요약"):
    return EpisodePlot(number=n, act="기", title=f"{n}화", summary=summary, events=["사건"], characters=list(chars),
                       emotional_shift="", ending_hook="")


def _story() -> Project:
    p = Project()
    p.episodes = [
        Episode(plot=_plot(1), status="finalized", text="바람이 불었다. 서윤은 등대 앞에 섰다.\n\n아버지는 그 겨울 바다에서 돌아오지 않았다."),
        Episode(plot=_plot(2, ("ally",), "도현이 낡은 등대 열쇠를 찾는다"), status="confirmed"),
        Episode(plot=_plot(3, ("ally",)), status="draft"),
        Episode(plot=_plot(4, ("ally",)), status="draft"),
    ]
    return p


def test_links_find_mentions_characters_and_planned():
    p = _story()
    el = StoryElement(id="el-01", name="등대 열쇠", aliases=["열쇠", "섰"], characters=["hero"], episodes=[4])
    got = {lk.episode: lk for lk in elements.links(p, el)}
    assert set(got) == {1, 2, 4}
    assert got[1].characters == ["hero"] and got[1].where == []  # 한 글자 별칭은 찾지 않는다
    assert got[2].where == ["플롯"] and got[2].terms == ["등대 열쇠", "열쇠"] and "열쇠" in got[2].snippet
    assert got[4].planned


def test_episode_context_respects_timing_and_reveal():
    p = _story()
    p.elements = [
        StoryElement(id="a", kind="과거 사건", name="친부", description="만석은 서윤의 친부다", characters=["hero"], reveal_ep=3),
        StoryElement(id="b", kind="세계 규칙", name="통금", description="밤 9시 통금", since_ep=3, context="always"),
        StoryElement(id="c", name="숨김", description="넣지 않는다", context="off", characters=["hero"]),
    ]
    one = elements.episode_block(p, 1)
    assert "친부" in one and "드러내지 않는다" in one and "통금" not in one and "숨김" not in one
    assert "통금" in elements.episode_block(p, 3) and "친부" not in elements.episode_block(p, 3)  # 3화엔 hero 가 없다
    ctx = prompts.build_episode_context(p, 1)
    assert ctx.index("# 확정된 사실") < ctx.index("# 이야기 요소") < ctx.index("# 이번 화 등장 인물")
    assert "통금" in elements.plan_block(p) and "3화부터 생김" in elements.plan_block(p)
    assert "# 이야기 요소" not in prompts.build_episode_context(Project(episodes=[Episode(plot=_plot(1))]), 1)


def test_find_tolerates_whitespace():
    assert elements.find("가 나\n다", "가 나 다") == (0, 5)
    assert elements.find("가나다", "없음") is None


def _serial(client):
    meta = {"title": "등대", "target_episodes": 10}
    client.post("/api/projects", json={"name": "lh", "meta": meta})
    s = client.post("/api/projects/lh/suggest").json()
    p = client.post("/api/projects/lh/suggest/apply", json=s).json()
    p["arc"] = client.post("/api/projects/lh/arc").json()["acts"]
    client.put("/api/projects/lh", json=p)
    client.post("/api/projects/lh/plots", json={})
    for n in (1, 2, 3):
        client.post(f"/api/projects/lh/episodes/{n}/confirm")
    client.post("/api/projects/lh/episodes/1/write")
    return client.get("/api/projects/lh").json()


def test_impact_flow(client):
    p = _serial(client)
    p["elements"] = [{"id": "el-01", "kind": "과거 사건", "name": "등대지기", "description": "만석은 서윤의 친부다", "characters": ["hero"]}]
    p = client.put("/api/projects/lh", json=p).json()
    el = p["elements"][0]
    assert el["created_at"] and el["added_after"] == 1  # 1화를 쓴 뒤에 더했다

    links = client.get("/api/projects/lh/elements/links").json()["el-01"]
    assert links[0]["episode"] == 1 and links[0]["characters"] == ["hero"]

    assert client.post("/api/projects/lh/jobs", json={"kind": "impact", "element": "없음"}).status_code == 400
    j = _wait(client, client.post("/api/projects/lh/jobs", json={"kind": "impact", "element": "el-01"}).json()["id"])
    assert j["status"] == "done", j
    imp = client.get("/api/projects/lh").json()["elements"][0]["impact"]
    rep = imp["report"]
    assert [c["quote"] for c in rep["conflicts"]] == ["바람이 불었다"]  # 지어낸 인용은 빠진다
    assert "찾지 못한 지적 1개" in rep["summary"]
    assert [e["number"] for e in rep["episodes"]] == [2]  # 1화는 본문이 있어 플롯 변경에서 빠진다
    assert rep["patches"][0]["episode"] == 1

    # 분석 전 내용을 가진 화면이 저장해도 분석은 남는다
    client.put("/api/projects/lh", json=p)
    assert client.get("/api/projects/lh").json()["elements"][0]["impact"]["report"] == rep

    p = client.post("/api/projects/lh/elements/el-01/impact/apply", json={"episodes": [2], "patches": [0], "facts": [0]}).json()
    assert p["episodes"][0]["text"].startswith("바람이 불었다 등대지기이(가) 떠올랐다.")
    assert p["episodes"][1]["status"] == "draft" and "등대지기 이(가) 드러난다" in p["episodes"][1]["plot"]["events"]
    assert "등대지기: 만석은 서윤의 친부다" in p["facts"]
    assert p["elements"][0]["impact"]["applied"] == ["ep:2", "patch:0", "fact:0"]
    assert client.post("/api/projects/lh/elements/el-01/impact/apply", json={"facts": [0]}).status_code == 400


def test_patch_refuses_changed_text(client):
    p = _serial(client)
    p["elements"] = [{"id": "el-01", "name": "통금", "description": "밤에는 나갈 수 없다", "since_ep": 2}]
    client.put("/api/projects/lh", json=p)
    _wait(client, client.post("/api/projects/lh/jobs", json={"kind": "impact", "element": "el-01"}).json()["id"])
    client.put("/api/projects/lh/episodes/1/text", json={"text": "완전히 다른 본문"})
    r = client.post("/api/projects/lh/elements/el-01/impact/apply", json={"patches": [0]})
    assert r.status_code == 400 and "다시 분석" in r.json()["detail"]
    p = client.post("/api/projects/lh/elements/el-01/impact/dismiss").json()
    assert p["elements"][0]["impact"]["outcome"] == "dismissed"


def test_cli_add_and_impact(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANON_LLM", "mock")
    from canon import cli, store

    monkeypatch.setattr(store, "ROOT", tmp_path)
    p = _story()
    store.save("cl", p)
    cli.main(["causal", "cl", "add", "--kind", "과거사건", "--title", "등대", "--desc", "등대는 무너졌다", "--chars", "hero"])
    el = store.load("cl").elements[0]
    assert (el.kind, el.added_after, el.characters) == ("과거 사건", 1, ["hero"])
    cli.main(["causal", "cl", "impact", el.id, "-y"])
    q = store.load("cl")
    assert q.elements[0].impact.outcome == "applied" and "등대: 등대는 무너졌다" in q.facts
    assert "1화 본문 수정" in capsys.readouterr().out
