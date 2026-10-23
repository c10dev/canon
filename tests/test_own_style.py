"""나만의 문체: 라이브러리 버전, 수정 기록에서 규칙 배우기, 가끔 쓰는 장치. 실행: python -m pytest tests"""
import json

from canon import library, metrics, pipeline, prompts
from canon.mock import MockLLM
from canon.schema import Episode, EpisodePlot, Project, Selection, StyleDevice, StyleProfile

from .test_library import SAMPLE, client  # noqa: F401  (pytest fixture)

MANIA = "씻고 온다는 건 온다는 거지? 온다는 건 싫어하지 않았다는 거겠지?"


def _plot(n):
    return EpisodePlot(number=n, act="기", title=f"{n}화", summary="", events=[], characters=[],
                       emotional_shift="", ending_hook="")


def test_versions_diff_and_restore(client):
    prof = client.post("/api/styles/analyze", json={"text": SAMPLE}).json()
    e = client.post("/api/styles", json={"name": "건조체", "sample": SAMPLE, "profile": prof}).json()
    assert e["version"] == 1 and e["versions"][0]["note"] == "처음 만듦"

    # 이름만 바꾸면 버전이 늘지 않는다
    same = client.put(f"/api/styles/{e['id']}", json={"name": "건조체!", "sample": SAMPLE, "profile": prof}).json()
    assert same["version"] == 1

    changed = dict(prof, tense="현재형", dos=prof["dos"] + ["대사는 짧게"])
    v2 = client.put(f"/api/styles/{e['id']}", json={"name": "건조체", "sample": SAMPLE, "profile": changed}).json()
    assert v2["version"] == 2 and "시제" in v2["versions"][-1]["note"] and "지킬 것" in v2["versions"][-1]["note"]
    v3 = client.put(f"/api/styles/{e['id']}", json={"name": "건조체", "sample": SAMPLE, "note": "대사 규칙 뺌",
                                                    "profile": dict(changed, dos=prof["dos"])}).json()
    assert v3["versions"][-1]["note"] == "대사 규칙 뺌"

    vs = client.get(f"/api/styles/{e['id']}/versions").json()
    assert [v["number"] for v in vs] == [3, 2, 1] and vs[0]["current"]
    ch = {c["key"]: c for c in vs[1]["changes"]}
    assert ch["tense"]["after"] == "현재형" and ch["dos"]["added"] == ["대사는 짧게"]

    r = client.post(f"/api/styles/{e['id']}/versions/1/restore").json()
    assert r["version"] == 4 and r["profile"]["tense"] == prof["tense"] and r["versions"][-1]["note"] == "1번 버전으로 되돌림"
    assert client.post(f"/api/styles/{e['id']}/versions/4/restore").status_code == 400  # 지금과 같다
    assert client.post(f"/api/styles/{e['id']}/versions/99/restore").status_code == 400


def test_project_version_link_and_legacy_entry(client, tmp_path):
    prof = client.post("/api/styles/analyze", json={"text": SAMPLE}).json()
    e = client.post("/api/styles", json={"name": "건조체", "sample": SAMPLE, "profile": prof}).json()
    client.post("/api/projects", json={"name": "a", "meta": {"title": "등대", "target_episodes": 10}, "style_id": e["id"]})
    assert client.get("/api/projects/a").json()["style_version"] == 1
    a = client.get("/api/projects/a").json()
    a["style"]["donts"] = ["부사 남발"]
    client.put("/api/projects/a", json=a)
    r = client.post("/api/projects/a/style/library", json={"update": True}).json()
    assert r["entry"]["version"] == 2 and r["project"]["style_version"] == 2
    assert client.get("/api/projects/a").json()["style_version"] == 2  # 작품에도 저장됐다
    link = client.get("/api/projects/a/style/link").json()
    assert (link["state"], link["version"], link["applied"]) == ("same", 2, 2)
    note = client.get(f"/api/styles/{e['id']}/versions").json()[0]["note"]
    assert "등대" in note

    # 버전 기록 전에 저장된 항목도 읽히고, 첫 저장에서 원래 상태가 1번으로 남는다
    path = tmp_path / ".styles" / f"{e['id']}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("versions"), raw.pop("version")
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    old = client.get(f"/api/styles/{e['id']}").json()
    assert old["version"] == 1 and len(old["versions"]) == 1
    up = client.put(f"/api/styles/{e['id']}", json={"name": "건조체", "sample": SAMPLE, "profile": dict(prof, tense="현재형")}).json()
    assert [v["number"] for v in up["versions"]] == [1, 2] and up["versions"][0]["profile"]["donts"] == ["부사 남발"]


def _edited_project() -> Project:
    """1~3화 본문이 있고 작가가 '묘한' 을 두 번, 망상 연쇄를 두 번 지운 작품."""
    p = Project()
    p.meta.title = "등대"
    texts = {
        1: f"묘한 기분이 들었다. 그는 문을 열었다.\n\n{MANIA}",
        2: f"묘한 바람이 불었다. 그녀는 웃었다.\n\n{MANIA}",
        3: "그는 길게 이어지는 문장으로 오래도록 생각했고 그러다 잠들었다. 바다가 보였다.",
    }
    for n, t in texts.items():
        p.episodes.append(Episode(plot=_plot(n), status="written", text=t))
    pipeline.edit_text(p, 1, Selection(start=0, text="묘한 기분이 들었다."), "기분이 가라앉았다.")
    pipeline.edit_text(p, 2, Selection(start=0, text="묘한 바람이 불었다."), "바람이 불었다.")
    for n in (1, 2):
        t = p.episode(n).text
        pipeline.edit_text(p, n, Selection(start=t.index(MANIA), text=MANIA), "씻고 온다고 했다.")
    t = p.episode(3).text
    sel = "그는 길게 이어지는 문장으로 오래도록 생각했고 그러다 잠들었다."
    pipeline.edit_text(p, 3, Selection(start=0, text=sel), "그는 생각했다. 그러다 잠들었다.")
    # 학습에서 빠지는 것: 되돌린 수정, 동선 맞추기
    e = pipeline.edit_text(p, 3, Selection(start=t.index("바다"), text="바다가 보였다."), "바다.")
    pipeline.undo_edit(p, 3, e.id)
    pipeline.edit_text(p, 3, Selection(start=t.index("바다"), text="바다가 보였다."), "창밖으로 바다가 보였다.", preset="blocking")
    return p


def test_learnable_edits_and_minimum():
    p = _edited_project()
    refs = [r for r, _ in pipeline.learnable_edits(p)]
    assert refs == ["1:e1", "1:e2", "2:e1", "2:e2", "3:e1"]
    assert pipeline.edit_stats(p)["usable"] == 5 and pipeline.edit_stats(p)["total"] == 7
    q = Project()
    q.episodes.append(Episode(plot=_plot(1), status="written", text="가나다라."))
    try:
        pipeline.learn_style(MockLLM(), q)
        raise AssertionError("수정이 적으면 돌리지 않아야 한다")
    except ValueError as err:
        assert "0건" in str(err)


def test_learn_checks_evidence_and_applies():
    p = _edited_project()
    prompt = prompts.learn_prompt(p, pipeline.learnable_edits(p))
    assert "[1:e1]" in prompt and "고치기 전: «묘한 기분이 들었다.»" in prompt
    r = pipeline.learn_style(MockLLM(), p)
    kinds = {s.kind: s for s in r.suggestions}
    assert "marker" not in kinds  # 근거 수정이 없는 후보는 빠진다
    assert kinds["banned"].text == "묘한" and kinds["banned"].evidence == ["1:e1", "2:e1"]
    assert kinds["banned"].pairs[0].before == "묘한 기분이 들었다."
    dev = kinds["device"]
    assert dev.cues == ["다는 건"] and dev.every == 5 and dev.evidence == ["1:e2", "2:e2"]
    assert r.edits_used == 5 and r.at

    p.style_learning = r
    idx = [i for i, s in enumerate(r.suggestions) if s.kind in ("banned", "device", "do")]
    done, notes = pipeline.apply_learning(p, idx)
    assert len(done) == 3 and not notes
    assert "묘한" in p.style.banned_phrases and "짧은 문장으로 끊어 쓴다" in p.style.dos
    assert p.style.devices[0].name == "자문자답 망상" and p.style.devices[0].when == "설렐 때"
    assert all(s.applied for s in r.suggestions if s.kind in ("banned", "device", "do"))
    assert pipeline.apply_learning(p, idx)[0] == []  # 이미 넣은 후보는 다시 넣지 않는다

    # 다시 배우면 지금 규칙과 같은 후보는 빠진다
    again = pipeline.learn_style(MockLLM(), p)
    assert not [s for s in again.suggestions if s.kind in ("banned", "device", "do")]


def test_learn_api(client):
    p = _edited_project()
    client.post("/api/projects", json={"name": "b", "meta": {"title": "등대", "target_episodes": 10}})
    cur = client.get("/api/projects/b").json()
    cur["episodes"] = [json.loads(e.model_dump_json()) for e in p.episodes]
    client.put("/api/projects/b", json=cur)
    assert client.get("/api/projects/b/style/edits").json()["usable"] >= 5
    q = client.post("/api/projects/b/style/learn").json()
    assert q["style_learning"]["suggestions"] and q["style"]["banned_phrases"] == []  # 찾기만 하고 바꾸지 않는다
    assert client.post("/api/projects/b/style/learn/apply", json={"picks": []}).status_code == 400
    r = client.post("/api/projects/b/style/learn/apply", json={"picks": [0], "push": True}).json()
    assert r["applied"] == 1 and r["entry"] is None  # 라이브러리에 연결 안 된 작품
    assert r["project"]["style_learning"]["suggestions"][0]["applied"]
    assert client.post("/api/projects/b/style/learn/dismiss").json()["style_learning"] is None


def test_device_block_and_warning():
    p = Project()
    p.style.devices = [StyleDevice(name="자문자답 망상", when="상대 반응에 설렐 때", cues=["다는 건"], every=3, example=MANIA)]
    for n, t in ((1, MANIA), (2, "평범한 화."), (3, "")):
        p.episodes.append(Episode(plot=_plot(n), status="written" if t else "confirmed", text=t))
    block = prompts.device_block(p, 3)
    assert "이번 화에는 쓰지 않습니다 (1화에 썼고 3화에 한 번까지)" in block and "예:" not in block
    block = prompts.device_block(p, 4)
    assert "상대 반응에 설렐 때, 이런 상황에서만 한 번까지" in block and "마지막으로 쓴 화 1화" in block and "예: " in block
    assert "자문자답 망상" in prompts.build_episode_context(p, 3)
    assert "devices" not in prompts.static_context(p)  # 화마다 바뀌는 블록은 앞쪽(캐시)에 두지 않는다

    p.episode(3).text = MANIA
    assert metrics.device_warnings(p.style.devices, p.episodes, 3, MANIA) == ["'자문자답 망상' 1화에 이어 또 씀 (3화에 한 번까지)"]
    assert metrics.device_warnings(p.style.devices, p.episodes, 6, MANIA) == []
    assert not metrics.device_used("온다는 건 좋다.", ["다는 건"])  # 한 번은 장치로 보지 않는다


def test_analysis_keeps_device_cues_in_sample():
    prof = StyleProfile(devices=[StyleDevice(name="망상", cues=["않았다", "원문에없는글자"], every=-1)])
    pipeline.count_markers(prof, SAMPLE)
    assert prof.devices[0].cues == (["않았다"] if "않았다" in SAMPLE else []) and prof.devices[0].every == 0


def test_diff_shows_devices():
    a = StyleProfile()
    b = StyleProfile(devices=[StyleDevice(name="자문자답 망상", when="설렐 때", cues=["다는 건"], every=5)])
    assert library.diff(a, b) == [{"key": "devices", "label": "가끔 쓰는 장치", "added": ["자문자답 망상 (설렐 때, 5화에 한 번, 다는 건)"], "removed": []}]
