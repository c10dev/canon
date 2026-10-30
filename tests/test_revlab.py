"""역설계 실험 (canon/revlab.py, prompts.rev_*, pipeline.reverse_episode · reverse_lines, 웹, static/revlab.js).
시험 글(fixtures/revlab_story.txt)은 이 시험을 위해 지은 짧은 글이다."""
import contextlib
import io
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from canon import autorun, cue, jobs, prompts, revlab, store
from canon.cli import main
from canon.mock import MockLLM
from canon.mock_revlab import FAKE_LINE
from canon.schema import Cue, CueLine, CueSheetDraft, RevCue, RevEpisodeDraft, RevLineSet

from .jsvm import STATIC, dump, needs_node, run_js
from .test_web import _wait

FILES = re.findall(r'src="/static/([a-z-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))
STORY = (Path(__file__).parent / "fixtures" / "revlab_story.txt").read_text(encoding="utf-8")
LONG_PREFACE = "작가의 말. " * 40  # 200자 넘는 앞머리는 화 하나

SPLIT_CASES = {
    "heading": STORY,
    "heading_long_preface": LONG_PREFACE + "\n\n제3화: 시작\n본문 셋\n\n4화\n본문 넷",
    "not_heading": "3화가 끝나고 서윤은 잠들었다.\n그다음 날이었다.",
    "mark": "첫 화 본문\n===\n\n둘째 화 본문\n  =====  \n\n===\n셋째",
    "blank": "하나\n\n\n\n둘\n \n\t\n\n셋\n\n두 줄만 빈 곳",
    "one": "﻿그냥 한 덩어리 글\r\n둘째 줄",
    "markdown_head": "# 12화 비\n비가 왔다\n## 13화\n그쳤다",
}


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(autorun, "_controls", {})
    yield tmp_path
    jobs.draining.clear()


def _parsed(home):
    lab = revlab.create("등대", STORY)
    revlab.run_parse(lab.id, MockLLM())
    return revlab.load(lab.id)


def test_schemas_have_no_dict():
    for m in (RevEpisodeDraft, RevLineSet):
        assert "additionalProperties" not in json.dumps(m.model_json_schema())  # Gemini 구조화 출력
    assert "length" not in RevCue.model_json_schema()["properties"]  # 글자 수는 AI 가 적지 않는다


def test_split_rules():
    s = revlab.split(STORY)
    assert s["how"] == "heading" and s["first"] == 1 and s["preface"] == "등대지기의 밤\n글 · 시험용"
    assert [e["head"] for e in s["episodes"]] == ["1화 꺼진 불", "2화 창고"]
    assert s["episodes"][0]["text"].startswith("서윤은 계단") and s["episodes"][1]["text"].endswith("돌이킬 수 없어.\"")
    s = revlab.split(SPLIT_CASES["heading_long_preface"])
    assert s["first"] == 2 and s["preface"] == "" and len(s["episodes"]) == 3 and s["episodes"][0]["head"] == ""
    assert revlab.split(SPLIT_CASES["not_heading"])["how"] == "one"  # '3화가' 는 제목 줄이 아니다
    s = revlab.split(SPLIT_CASES["mark"])
    assert s["how"] == "mark" and [e["text"] for e in s["episodes"]] == ["첫 화 본문", "둘째 화 본문", "셋째"]  # 빈 화는 뺀다
    s = revlab.split(SPLIT_CASES["blank"])
    assert s["how"] == "blank" and [e["text"] for e in s["episodes"]] == ["하나", "둘", "셋\n\n두 줄만 빈 곳"]
    s = revlab.split(SPLIT_CASES["one"])
    assert s["how"] == "one" and s["episodes"][0]["text"] == "그냥 한 덩어리 글\n둘째 줄"
    s = revlab.split(SPLIT_CASES["markdown_head"])
    assert s["first"] == 12 and [e["text"] for e in s["episodes"]] == ["비가 왔다", "그쳤다"]


def test_check_text_limits():
    with pytest.raises(ValueError, match="비었어요"):
        revlab.check_text("  \n ")
    with pytest.raises(ValueError, match="30화까지"):
        revlab.check_text("\n".join(f"{i}화\n본문" for i in range(1, 33)))
    with pytest.raises(ValueError, match="너무 길어요"):
        revlab.check_text("가" * (revlab.MAX_CHARS + 1))


def test_locate_measures_cue_lengths_from_quotes():
    text = "첫 문장이다. 바람이 불었다.\n\n“그거  내가 걸었어.” 도현이 말했다.\n\n마지막 문단이 여기 있다."
    b = revlab.locate(text, ["아무거나 (첫 큐는 처음)", '"그거 내가 걸었어."', "원문에 없는 시작", "마지막 문단이…"])
    assert [x.found for x in b] == [True, True, False, True]
    assert b[0].start == 0 and b[1].start == text.index("“그거") and b[3].start == text.index("마지막")
    assert b[1].end == b[2].start == b[2].end == b[3].start  # 못 찾은 큐는 길이 0, 앞 큐가 다음 큐까지 늘어난다
    assert b[-1].end == len(text)
    # 같은 인용이 두 번 나와도 차례대로 다음 것을 찾는다
    b = revlab.locate("가나다 끝. 가나다 끝. 가나다 끝.", ["x", "가나다", "가나다"])
    assert [x.start for x in b] == [0, 7, 14]


def test_keep_lines_checks_source():
    keep, drop = revlab.keep_lines("“괜찮아?” 그가 물었다. \"응, 괜찮아.\"", [
        CueLine(speaker="서윤", text="괜찮아?"), CueLine(speaker="도현", text="“응,  괜찮아”"), CueLine(text="안 한 말"), CueLine(text=" ")])
    assert [x.text for x in keep] == ["괜찮아?", "응,  괜찮아"] and drop == ["안 한 말"]


def test_parse_flow_measures_and_drops(home):
    lab = revlab.create("등대", STORY)
    assert (home / ".revlab" / f"{lab.id}.json").exists() and not list(home.glob("*/project.json"))  # 작품 밖에 둔다
    assert revlab.create("둘째", "다른 글 " * 50).id == lab.id + 1
    res = revlab.run_parse(lab.id, MockLLM())
    assert res == {"episodes": 2, "cues": 8, "lines": 1}
    lab = revlab.load(lab.id)
    for e in lab.episodes:
        assert len(e.bounds) == len(e.sheet.cues) == 4
        assert [c.length for c in e.sheet.cues] == [revlab.measured(e.text, b) for b in e.bounds]  # 글자 수는 원문 경계로 잰다
        assert FAKE_LINE in e.dropped and all(FAKE_LINE != x.text for c in e.sheet.cues for x in c.lines)
        assert all(cue._flat(x.text) in cue._flat(e.text) for c in e.sheet.cues for x in c.lines)
        assert e.plot.characters == ["서윤", "도현"] and e.storyboard.made_by == "ai"
    ep2 = lab.episodes[1]
    assert all(b.found for b in ep2.bounds)  # 셋째 큐는 «"왜?"» 처럼 짧은 문단에서 시작한다
    assert ep2.storyboard.handover  # 둘째 화 요청에는 직전 화 끝이 들어간다
    assert [c.name for c in lab.cast] == ["서윤", "도현"] and lab.cast[0].speech == "짧게 끊는 말투"
    assert lab.main and [(x.id, x.branch_ep, x.join_ep) for x in lab.lines] == [("sl-01", 2, 0)]  # 실험에 없는 99화는 뺀다
    assert ep2.plot.storyline == "sl-01" and lab.episodes[0].plot.storyline == ""


def test_short_start_quote_is_found(home):
    text = "첫 문단이 조금 길게 이어진다.\n\n\"왜?\"\n\n대답이 없었다."
    b = revlab.locate(text, ["첫 문단", "\"왜?\"", "대답이 없었다."])
    assert all(x.found for x in b) and b[1].start == text.index('"왜?"')


def test_prompt_order_fixed_rules_first(home):
    lab = _parsed(home)
    one, two = prompts.rev_prompt(lab, 1), prompts.rev_prompt(lab, 2)
    rules = prompts.rev_rules()
    assert one.startswith(rules) and two.startswith(rules)  # 화 사이에 같은 앞부분
    assert two.index("# 직전 화 끝") < two.index("# 원문 (2화")
    assert two.rstrip().endswith("JSON 으로 적습니다.") and lab.episodes[1].text in two
    assert "# 직전 화 끝" not in one
    assert "1화" in prompts.rev_lines_prompt(lab) and "2화" in prompts.rev_lines_prompt(lab)


def test_author_sheet_edit_keeps_or_clears_bounds(home):
    lab = _parsed(home)
    d = CueSheetDraft(**lab.episodes[0].sheet.model_dump(include=set(CueSheetDraft.model_fields)))
    d.cues[0].tension = 9
    e = revlab.set_sheet(lab, 1, d)
    assert len(e.bounds) == 4 and e.sheet.made_by == "both" and e.sheet.cues[0].tension == 5
    d.cues.append(Cue(beat="새 큐"))
    e = revlab.set_sheet(lab, 1, d)
    assert e.bounds == [] and revlab.parts(e) == []
    assert revlab.view(lab)["items"][0]["bounds_ok"] is False
    with pytest.raises(ValueError):
        revlab.set_sheet(lab, 1, CueSheetDraft(cues=[]))


def test_round_trip_and_blind(home):
    lab = _parsed(home)
    q = revlab.world(lab, 2)
    assert [e.status for e in q.episodes] == ["finalized", "confirmed"] and q.episodes[0].text == lab.episodes[0].text
    assert q.episodes[1].text == "" and q.style.sample_passages == []  # 원문 문장은 주지 않는다
    assert lab.episodes[1].text not in prompts.cue_score_prompt(q, 2, lab.episodes[1].sheet)
    e = revlab.run_write(lab.id, MockLLM(), 2)
    assert sorted(e.blind) == ["original", "rewrite"] and e.take.sheet_basis == cue.basis(e.sheet)
    v = revlab.view(revlab.load(lab.id))["items"][1]
    assert "blind" not in v and v["take"] and "text" not in v["take"]  # 고르기 전에는 어느 쪽인지 알리지 않는다
    assert sorted(v["blind_texts"]) == sorted([e.text, e.take.text])
    assert [s["condition"] for s in v["scores"]] == ["original"]
    assert v["scores"][0]["rows"] and v["scores"][0]["lines_hit"] == v["scores"][0]["lines_total"]  # 원문은 큐 경계로 나눠 잰다
    lab = revlab.load(lab.id)
    assert revlab.pick(lab, 2, 2) == e.blind[1]
    revlab.save(lab)
    v = revlab.view(revlab.load(lab.id))["items"][1]
    assert v["blind"] == e.blind and v["take"]["text"] == e.take.text and [s["label"] for s in v["scores"]] == ["원문", "되돌려 쓴 글"]
    with pytest.raises(ValueError):
        revlab.pick(lab, 1, 1)  # 1화는 되돌려 쓴 글이 없다


def test_estimate(home):
    lab = revlab.create("등대", STORY)
    est = revlab.estimate(lab, "parse")
    assert [r["label"] for r in est["rows"]] == ["1화", "2화", "이야기 줄기"] and est["usd"] is not None
    assert [r["label"] for r in revlab.estimate(lab, "parse", [2])["rows"]] == ["2화"]  # 1화가 아직이면 줄기는 묻지 않는다
    with pytest.raises(ValueError, match="역설계하세요"):
        revlab.estimate(lab, "write", [1])
    revlab.run_parse(lab.id, MockLLM(), [1])
    lab = revlab.load(lab.id)
    assert lab.episodes[1].sheet is None and lab.lines_at == ""
    w = revlab.estimate(lab, "write", [1])
    assert w["kind"] == "write" and w["rows"][0]["output_tokens"] == round(len(lab.episodes[0].text) / revlab.CHARS_PER_TOKEN)
    with pytest.raises(ValueError, match="없는 화"):
        revlab.estimate(lab, "parse", [7])


def test_web_flow(home):
    from canon import web

    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
    before = (home / "demo" / "project.json").read_text(encoding="utf-8")
    c = TestClient(web.app)
    h = c.get("/api/revlab").json()
    assert h["labs"] == [] and [x["key"] for x in h["functions"]] == ["T", "S", "D"] and h["max_episodes"] == revlab.MAX_EPISODES
    assert c.post("/api/revlab/split", json={"text": STORY}).json()["how"] == "heading"
    assert c.post("/api/revlab", json={"title": "x", "text": " "}).status_code == 400
    v = c.post("/api/revlab", json={"title": "등대", "text": STORY}).json()
    lab_id = v["id"]
    assert [e["number"] for e in v["items"]] == [1, 2] and v["done"] == 0
    assert c.get("/api/revlab/99").status_code == 404
    est = c.post(f"/api/revlab/{lab_id}/estimate", json={"kind": "parse"}).json()
    assert est["calls"] == 3
    r = c.post("/api/projects/demo/jobs", json={"kind": "rev_parse", "ep": lab_id})
    assert r.status_code == 200, r.text
    j = _wait(c, r.json()["id"])
    assert j["status"] == "done" and j["result"]["episodes"] == 2, j
    v = c.get(f"/api/revlab/{lab_id}").json()
    assert v["done"] == 2 and v["lines"] and v["items"][0]["sheet"]["cues"]
    sheet = v["items"][0]["sheet"]
    sheet["key"] = "작가가 고친 조성"
    v = c.put(f"/api/revlab/{lab_id}/episodes/1/sheet", json=sheet).json()
    assert v["items"][0]["sheet"]["key"] == "작가가 고친 조성" and v["items"][0]["bounds_ok"]
    assert c.post("/api/projects/demo/jobs", json={"kind": "rev_write", "ep": lab_id}).status_code == 400  # 화를 하나 골라야 한다
    r = c.post("/api/projects/demo/jobs", json={"kind": "rev_write", "ep": lab_id, "episodes": [1]})
    assert _wait(c, r.json()["id"])["status"] == "done"
    v = c.post(f"/api/revlab/{lab_id}/episodes/1/pick", json={"choice": 0}).json()
    assert v["items"][0]["picked"] == "skip" and len(v["items"][0]["scores"]) == 2
    v = c.put(f"/api/revlab/{lab_id}", json={"title": "새 이름"}).json()
    assert v["title"] == "새 이름" and v["done"] == 2  # 글을 주지 않으면 결과는 그대로
    v = c.put(f"/api/revlab/{lab_id}", json={"title": "새 이름", "text": "다시 넣은 글 " * 40}).json()
    assert v["episodes"] == 1 and v["done"] == 0 and v["lines"] == []
    assert c.get("/api/revlab").json()["labs"][0]["title"] == "새 이름"
    assert c.delete(f"/api/revlab/{lab_id}").json() == {"ok": True} and revlab.ids() == []
    assert (home / "demo" / "project.json").read_text(encoding="utf-8") == before  # 작품은 그대로


@needs_node
def test_js_split_matches_python():
    got = run_js(FILES, "Object.fromEntries(Object.entries(data).map(([k, t]) => [k, revSplit(t)]))", SPLIT_CASES)
    for k, t in SPLIT_CASES.items():
        assert got[k] == revlab.split(t), k


@needs_node
def test_js_helpers_and_view(home):
    lab = _parsed(home)
    revlab.run_write(lab.id, MockLLM(), 1)
    lab = revlab.load(lab.id)
    b = lab.episodes[1].bounds
    b[1].end = b[2].start = b[2].end = b[3].start  # 2화 셋째 큐 시작을 못 찾은 것으로 둔다
    b[2].found = False
    view = revlab.view(lab)
    labels = {**revlab.labels(), **_cue_labels(), "labs": revlab.listing()}
    got = run_js(FILES, """(() => {
      S.project = { meta: { form: 'short' }, characters: [], episodes: [], settings: {} }; S.name = 'demo';
      S.rev = data.home; S.cue = data.home; S.revLab = null;
      S.revDraft = { title: '', text: data.story };
      const home = viewRev();
      const prev = revPreview(data.story, data.home);
      const tooMany = revPreview(Array.from({ length: 32 }, (_, i) => `${i + 1}화\\n본문`).join('\\n'), data.home);
      S.revLab = data.lab; S.revEp = 1; S.revPick = new Set([2]); S.revSel = 2;
      const lab = viewRev();
      S.revEp = 2;
      const two = viewRev();
      const e = data.lab.items[1];
      return { home, prev, tooMany: tooMany.errs, lab, two, segs: revSegments(e.text, e.bounds),
               gap: revSegments('abcdef', [{ start: 2, end: 4, found: true }, { start: 4, end: 4, found: false }]) };
    })()""", {"home": labels, "lab": view, "story": STORY})
    assert "새 실험" in got["home"] and "지난 실험" in got["home"]
    assert got["prev"]["how"] == "heading" and [e["n"] for e in got["prev"]["eps"]] == [1, 2] and not got["prev"]["errs"]
    assert got["prev"]["notes"]  # 앞머리 안내
    assert got["tooMany"] and "30화까지" in got["tooMany"][0]
    lab = got["lab"]
    assert "가려 읽기" in lab and "1번이 더 읽고 싶어요" in lab and "원문</td>" not in lab  # 1화: 고르기 전에는 지표에 되돌려 쓴 글이 없다
    assert 'id="rev-cue-2"' in lab and "rev-seg sel" in lab and "cue-bars" in lab and "큐 시트 고치기" in lab
    assert "이야기 줄기" in lab and "두 사람의 관계" in lab
    assert "시작 문장을 원문에서 못 찾았어요" in got["two"] and "되돌려 쓰기 시작" in got["two"]
    e = view["items"][1]
    assert [s["cue"] for s in got["segs"]] == [i + 1 for i, b in enumerate(e["bounds"]) if b["found"] and b["end"] > b["start"]]
    assert "".join(e["text"][s["start"]:s["end"]] for s in got["segs"]) == e["text"]  # 빈틈없이 덮는다
    assert got["gap"] == [{"cue": 0, "start": 0, "end": 2}, {"cue": 1, "start": 2, "end": 4}, {"cue": 0, "start": 4, "end": 6}]


def _cue_labels():
    from canon import web
    return web._cue_labels()


def test_dump_roundtrip(home):
    lab = _parsed(home)
    again = revlab.load(lab.id)
    assert dump(again) == dump(lab)
