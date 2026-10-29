"""큐 시트 집필 실험 (canon/cue.py, prompts.cue_*, pipeline.make_cue_sheet · write_scored · play_cues, 웹, static/cue.js)."""
import contextlib
import io
import json
import re

import pytest
from fastapi.testclient import TestClient

from canon import autorun, cue, jobs, pipeline, prompts, research, store
from canon.cli import main
from canon.mock import MockLLM
from canon.schema import Cue, CueLine, CueSheet, CueSheetDraft, CueTake, StoryTime

from .jsvm import STATIC, dump, needs_node, run_js
from .test_web import _wait

FILES = re.findall(r'src="/static/([a-z-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    """단편 6화 작품, 플롯 모두 확정."""
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(autorun, "_controls", {})
    with contextlib.redirect_stdout(io.StringIO()):
        main(["new", "demo", "--title", "등대", "--genre", "미스터리", "--logline", "x", "--episodes", "6", "-y"])
        main(["arc", "demo", "-y"])
        main(["plot", "demo"])
        main(["confirm", "demo", "all"])
    yield "demo"
    jobs.draining.clear()


def _sheet(k=4, size=1000):
    cues = [Cue(function="TSDD"[i % 4], tension=i + 2 if i < 4 else 5, tempo=["slow", "mid", "fast", "fast"][i % 4], beat=f"일 {i + 1}",
                lines=[CueLine(speaker="hero", text="문을 연 건 내가 아니야")] if i == k - 1 else [], exit=f"끝 {i + 1}", length=size)
            for i in range(k)]
    return CueSheet(key="불안", cadence="half", cues=cues, made_at="t1")


def test_schema_has_no_dict_and_hides_store_fields():
    schema = CueSheetDraft.model_json_schema()
    assert "additionalProperties" not in json.dumps(schema)  # Gemini 구조화 출력
    assert not {"made_at", "made_by"} & set(CueSheet.model_json_schema()["properties"])


def test_from_board_follows_plot_events_without_storyboard(demo):
    p = store.load(demo)
    s = cue.from_board(p, 1)
    assert len(s.cues) == len(p.episode(1).plot.events)
    assert [c.beat for c in s.cues] == p.episode(1).plot.events
    assert s.cues[-1].function == "D" and s.cadence == "half" and s.made_by == "board"
    assert [c.tension for c in s.cues] == sorted(c.tension for c in s.cues)  # 오르기만 한다
    assert sum(c.length for c in s.cues) == pytest.approx(p.meta.words_per_episode, abs=len(s.cues))


def test_from_board_uses_storyboard_scenes(demo):
    p = store.load(demo)
    pipeline.set_storyboard(p, 1, pipeline.make_storyboard(MockLLM(), p, 1), by="ai")
    s = cue.from_board(p, 1)
    assert [c.scene for c in s.cues] == list(range(1, len(p.episode(1).storyboard.scenes) + 1))
    assert s.cues[0].beat == "장면 1의 목표 → 장면 1의 전환" and s.cues[0].exit == "장면 1이 끝난 자리"


def test_clean_rescales_and_clamps(demo):
    p = store.load(demo)
    d = CueSheetDraft(cues=[Cue(beat="a", tension=9, length=10, lines=[CueLine(speaker="x", text="\"따옴표\""), CueLine(text=" ")]),
                            Cue(beat="", lines=[]), Cue(beat="b", tension=0, length=10)])
    d = cue.clean(p, d)
    assert len(d.cues) == 2 and [c.tension for c in d.cues] == [5, 1]
    assert d.cues[0].lines == [CueLine(speaker="x", text="따옴표")]
    assert sum(c.length for c in d.cues) == p.meta.words_per_episode  # 합이 크게 어긋나면 화 분량에 맞춘다


def test_prompts_share_prefix_and_extend(demo):
    p = store.load(demo)
    s = _sheet()
    base = prompts.episode_prompt(p, 1)
    assert prompts.cue_score_prompt(p, 1, s).startswith(base)
    assert "«문을 연 건 내가 아니야»" in prompts.cue_sheet_block(p, s)
    outs = ["첫 큐 본문.", "둘째 큐 본문.", "셋째 큐 본문."]
    prev = prompts.cue_play_prompt(p, 1, s, [])
    assert prev.startswith(prompts.cue_head(p, 1, s)) and prev.startswith(base)
    for k in range(1, 4):
        nxt = prompts.cue_play_prompt(p, 1, s, outs[:k])
        assert nxt.startswith(prev + "\n## 큐 " + str(k) + " 본문\n" + outs[k - 1])  # 앞 요청과 응답을 통째로 품는다
        prev = nxt
    assert prev.rstrip().endswith("큐 4 본문만 씁니다.")
    assert "마지막 큐입니다" in prompts.cue_step(p, s, 4) and "마지막 큐입니다" not in prompts.cue_step(p, s, 3)
    assert "1150자를 넘지 않습니다" in prompts.cue_step(p, s, 1)  # 목표 1,000자의 1.15배
    assert "정지 장면" in prompts.cue_head(p, 1, s) and "줄표(——)" in prompts.cue_head(p, 1, s) and "약 4000자를 넘지 않게" in prompts.cue_score_prompt(p, 1, s)


def test_scoring_without_llm():
    s = _sheet()
    assert cue.line_hits(s, "그가 말했다. “문을 연 건, 내가 아니야!”") == (1, 1, [])
    assert cue.line_hits(s, "아무 말도 없었다.")[2] == ["문을 연 건 내가 아니야"]
    parts = ["바람이 불었다. 서윤은 등대 문 앞에서 숨을 골랐다.", "서윤은 등대 문 앞에서 숨을 골랐다. 그리고 망설임 없이 계단 쪽으로 걸어 들어갔다.",
             "계단은 길었다. 위에서 소리가 났다. 고요했다.", "\"문을 연 건 내가 아니야.\" 그녀가 말했다."]
    seams = cue.seams(parts)
    assert [x["repeat"] for x in seams] == [True, False, False]
    assert cue.closing(parts) == [3]  # 마지막 큐가 아닌데 짧은 끝 문장
    ends = ["바람이 불었다. 여자는 렌치를 고쳐 쥐고 서 있었다.", "문이 열렸다. 그녀는 창문 틈 너머로 나를 내려다보고 있었다.",
            "나는 시동을 걸었다. 쪽문 앞을 버티고 선 이예은을 똑바로 바라보았다.", "그가 말했다. “그만 보고 있었다고요.”",
            "나는 핸들을 꺾으며 말을 이었다. “그러니까 지금", "마지막 큐."]
    assert cue.still(ends) == [1, 2, 3]  # 대사로 끝나거나 말 한가운데서 끊은 큐는 아니다
    assert cue.cut(["“돌아가세요. 여긴——”", "당장 내밀 수 있는 건——", "그녀의 허리춤에서…", "문장을 맺었다.", "마지막——"]) == [1, 2, 3]
    assert cue.repeats("같은 문장이 또 나온다. 다른 말. 같은 문장이 또 나온다.") == ["같은 문장이 또 나온다."]
    rows = cue.cue_rows(s, ["가" * 30 + ". " + "나" * 30 + ".", "짧다. 짧다.", "짧다. 짧다.", "짧다. 짧다."])
    assert cue.tempo_order(rows) is True and rows[0]["fit"] == round(rows[0]["chars"] / 1000, 2)
    t = CueTake(condition="cues", text="\n\n".join(parts), parts=parts, calls=4, sheet_basis="old")
    sc = cue.score(store_project_stub(), s, t)
    assert sc["stale"] and sc["lines_hit"] == 1 and len(sc["rows"]) == 4


def store_project_stub():
    from canon.schema import Meta, Project
    return Project(meta=Meta(title="t", target_episodes=3))


def test_run_on_finalized_episode_keeps_project(demo):
    p = store.load(demo)
    llm = MockLLM()
    with contextlib.redirect_stdout(io.StringIO()):
        main(["write", demo, "1"])
        main(["update", demo, "1", "-y"])
    p = store.load(demo)
    assert p.episode(1).status == "finalized"
    before_json = (store.project_dir(demo) / "project.json").read_text(encoding="utf-8")
    assert 1 in {c["episode"] for c in cue.candidates(p)} and 2 in {c["episode"] for c in cue.candidates(p)}
    with pytest.raises(ValueError, match="큐 시트"):
        cue.run(demo, p, llm, 1, ["cues"])
    sheet = pipeline.make_cue_sheet(llm, cue.before(p, 1), 1)
    cue.with_lock(demo, 1, lambda lab: cue.set_sheet(lab, sheet, p, by="ai"))
    rec = cue.run(demo, p, llm, 1)
    assert [r["condition"] for r in rec["summary"]] == ["oneshot", "score", "cues"]
    assert rec["summary"][1]["lines_hit"] == rec["summary"][1]["lines_total"] == 2
    lab = store.load_cuelab(demo, 1)
    take = lab.takes[2]
    assert take.calls == len(sheet.cues) == len(take.parts) and take.text == "\n\n".join(take.parts)
    assert take.sheet_basis == cue.basis(lab.sheet) and lab.model == "mock"
    assert (store.project_dir(demo) / "project.json").read_text(encoding="utf-8") == before_json  # 작품은 그대로
    assert research.load_compare(demo, 1)["kind"] == "cue"
    assert research.history(demo)[0]["kind"] == "cue"
    # 같은 조건을 다시 쓰면 그 조건의 본문만 바뀐다
    cue.run(demo, p, llm, 1, ["oneshot"])
    assert [t.condition for t in store.load_cuelab(demo, 1).takes] == ["oneshot", "score", "cues"]
    # 고치지 않고 다시 저장하면 낡지 않고, 시트를 고치면 낡은 본문 표시
    cue.with_lock(demo, 1, lambda lab: cue.set_sheet(lab, sheet, p))
    assert not any(t["score"]["stale"] for t in cue.view(demo, p, 1)["takes"])
    sheet.cues[0].beat = "작가가 고친 일"
    cue.with_lock(demo, 1, lambda lab: cue.set_sheet(lab, sheet, p))
    v = cue.view(demo, p, 1)
    assert v["sheet"]["made_by"] == "both"
    assert [t["score"]["stale"] for t in v["takes"]] == [False, True, True]


def test_estimate_counts_cue_calls(demo):
    p = store.load(demo)
    s = _sheet(k=5)
    est = cue.estimate(p, 1, s)
    rows = {r["condition"]: r for r in est["rows"]}
    assert rows["cues"]["calls"] == 5 and est["calls"] == 7
    assert rows["cues"]["input_tokens"] > 4 * rows["oneshot"]["input_tokens"]  # 큐마다 앞부분을 다시 보낸다
    with pytest.raises(ValueError, match="조건"):
        cue.estimate(p, 1, s, ["x"])
    with pytest.raises(ValueError, match="시험할 수 없어요"):
        cue.estimate(p, 3, s)  # 앞 화가 반영되지 않았다


def test_web_flow(demo):
    from canon import web

    c = TestClient(web.app)
    home = c.get(f"/api/projects/{demo}/cue").json()
    assert [x["episode"] for x in home["candidates"]] == [1] and home["labs"] == []
    assert [x["key"] for x in home["functions"]] == ["T", "S", "D"]
    v = c.post(f"/api/projects/{demo}/cue/1/sheet/board").json()
    assert v["sheet"]["made_by"] == "board" and store.cuelab_episodes(demo) == [1]
    body = v["sheet"]
    body["cues"][0]["lines"] = [{"speaker": "hero", "text": "작가가 넣은 대사"}]
    v = c.put(f"/api/projects/{demo}/cue/1/sheet", json=body).json()
    assert v["sheet"]["made_by"] == "both" and v["sheet"]["cues"][0]["lines"][0]["text"] == "작가가 넣은 대사"
    est = c.post(f"/api/projects/{demo}/cue/1/estimate", json={"conditions": ["oneshot", "cues"]}).json()
    assert [r["condition"] for r in est["rows"]] == ["oneshot", "cues"]
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "cue_sheet", "ep": 1})
    assert r.status_code == 200, r.text
    assert _wait(c, r.json()["id"])["status"] == "done"
    assert store.load_cuelab(demo, 1).sheet.made_by == "ai"
    r = c.post(f"/api/projects/{demo}/jobs", json={"kind": "cue_run", "ep": 1, "conditions": ["score", "cues"]})
    assert r.status_code == 200, r.text
    j = _wait(c, r.json()["id"])
    assert j["status"] == "done", j
    v = c.get(f"/api/projects/{demo}/cue/1").json()
    assert [t["condition"] for t in v["takes"]] == ["score", "cues"]
    assert v["takes"][1]["score"]["rows"] and v["takes"][0]["score"]["lines_hit"] == v["takes"][0]["score"]["lines_total"]
    assert c.post(f"/api/projects/{demo}/jobs", json={"kind": "cue_run", "ep": 4}).status_code == 400


@needs_node
def test_js_helpers_and_view(demo):
    p = store.load(demo)
    sheet = cue.from_board(p, 1)
    sheet.cues[1].lines = [CueLine(speaker="hero", text="대사")]
    got = run_js(FILES, """(() => {
      S.project = data.p; S.name = 'demo'; S.route = ['p', 'demo', 'cue', '1'];
      S.cue = data.home; S.cueConds = new Set(['oneshot', 'score', 'cues']);
      S.cueLab = data.lab; S.cueDraft = structuredClone(data.lab.sheet);
      const flat = { ...data.lab.sheet, cues: data.lab.sheet.cues.map((c) => ({ ...c, tension: 3, function: 'S' })) };
      return {
        parse: cueLinesParse('hero: «안녕»\\n그냥 말\\n\\n a：b \\nx: 넷째', 3),
        text: cueLinesText([{ speaker: 'hero', text: '안녕' }, { speaker: '', text: '그냥 말' }]),
        bars: cueBars(data.lab.sheet).map((b) => [b.fn, b.h]),
        width: Math.round(cueBars(data.lab.sheet).reduce((a, b) => a + b.w, 0)),
        flat: cueCurveOk(flat).length,
        html: viewCue(),
      };
    })()""", {"p": dump(p), "home": {"candidates": cue.candidates(p), "labs": [1], "runs": [], **_labels()},
              "lab": {"episode": 1, "title": "t", "board": False, "sheet": dump(sheet), "takes": [], "model": "", "run_at": ""}})
    assert got["parse"] == [{"speaker": "hero", "text": "안녕"}, {"speaker": "", "text": "그냥 말"}, {"speaker": "a", "text": "b"}]
    assert got["text"] == "hero: 안녕\n그냥 말"
    assert got["bars"] == [[c.function, c.tension * 20] for c in sheet.cues]
    assert got["width"] == 100
    assert got["flat"] >= 2  # 앞쪽 정점 · 평평한 긴장 (큐가 넷 넘으면 같은 기능 넷도)
    assert "큐 시트 집필 실험" in got["html"] and "cue-bars" in got["html"] and "hero: 대사" in got["html"]


def _labels():
    from canon import web
    return web._cue_labels()


def test_run_keeps_finished_conditions_when_later_fails(demo):
    """뒤 조건(큐마다 쓰기)이 도중에 실패해도 앞 조건의 본문은 실험 파일에 남는다 (실제 모델 한도 초과에서 나온 일)."""
    class Quota(MockLLM):
        def text(self, system, prompt):
            if prompt.rstrip().endswith("큐 3 본문만 씁니다."):
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return super().text(system, prompt)

    p = store.load(demo)
    cue.with_lock(demo, 1, lambda lab: cue.set_sheet(lab, pipeline.make_cue_sheet(MockLLM(), p, 1), p, by="ai"))
    with pytest.raises(RuntimeError):
        cue.run(demo, p, Quota(), 1, ["oneshot", "score", "cues"])
    assert [t.condition for t in store.load_cuelab(demo, 1).takes] == ["oneshot", "score"]
