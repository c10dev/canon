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
from canon.schema import Cue, CueLine, CueSheetDraft, RevAI, RevCue, RevEpisodeDraft, RevLab, RevLineSet

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


MANY = "\n".join(f"{i + 1}화\n본문" for i in range(32))


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


def _objects(node):
    """JSON 스키마 안의 object 노드를 모두."""
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            yield node
        for v in node.values():
            yield from _objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from _objects(v)


def test_response_fields_are_all_required():
    """기본값이 있는 칸은 선택 칸이 되어 Gemini 가 빼먹는다 (실측: 출력 36토큰, title 만). Gemini 에 보내는 스키마 그대로 본다."""
    from canon.llm import _inline_refs

    for m in (RevEpisodeDraft, RevLineSet):
        objs = list(_objects(_inline_refs(m.model_json_schema())))
        assert len(objs) >= 2
        for o in objs:
            assert sorted(o.get("required", [])) == sorted(o["properties"]), o.get("title")


class _Seq:
    """정한 응답을 차례로 돌려주는 LLM. 받은 요청을 남긴다."""

    def __init__(self, *outs):
        self.outs, self.prompts = list(outs), []

    def json(self, system, prompt, schema, hint=None):
        self.prompts.append(prompt)
        return self.outs.pop(0)


def _empty_draft():
    from canon.schema import RevTime
    return RevEpisodeDraft(title="1화", summary="", events=[], cast=[], emotional_shift="", ending_hook="", opening="", time="",
                           threads=[], setting="", facts=[], ties=[], addresses=[], scenes=[], board_time=RevTime(after=0, part="", days=1, end_part=""), handover=[],
                           key="", cadence="half", cues=[])


def test_empty_response_retries_once_then_refuses(home):
    from canon import pipeline

    lab = revlab.create("등대", STORY)
    good = MockLLM().json(prompts.SYSTEM_REVERSE, prompts.rev_prompt(lab, 1), RevEpisodeDraft, hint={"episode": 1})
    llm = _Seq(_empty_draft(), good)
    assert pipeline.reverse_episode(llm, lab, 1) is good
    assert llm.prompts[1] == llm.prompts[0] + "\n\n" + prompts.REV_EMPTY_RETRY  # 앞부분은 같고 맨 뒤에 덧붙인다
    with pytest.raises(ValueError, match="응답이 비었어요"):
        revlab.run_parse(lab.id, _Seq(_empty_draft(), _empty_draft()), [1])
    assert revlab.load(lab.id).episodes[0].sheet is None  # 빈 결과는 저장하지 않는다


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
    t = e.takes[0]
    assert t.no == 1 and sorted(t.blind.order) == ["original", "rewrite"] and t.sheet_basis == cue.basis(e.sheet) and t.provider == "mock"
    v = revlab.view(revlab.load(lab.id))["items"][1]
    assert v["takes"][0]["blind"] == {"state": "wait", "seen": 0} and "text" not in v["takes"][0]  # 고르기 전에는 알리지 않는다
    assert v["blind_no"] == 1 and sorted(v["blind_texts"]) == sorted([e.text, t.text]) and v["next_take"] == 2
    assert [s["condition"] for s in v["scores"]] == ["original"]
    assert v["scores"][0]["rows"] and v["scores"][0]["lines_hit"] == v["scores"][0]["lines_total"]  # 원문은 큐 경계로 나눠 잰다
    lab = revlab.load(lab.id)
    with pytest.raises(ValueError, match="판 1"):
        revlab.pick(lab, 2, 2, no=5)  # 낡은 화면이 다른 판을 고르지 않게
    assert revlab.pick(lab, 2, 2, no=1) == t.blind.order[1]
    revlab.save(lab)
    v = revlab.view(revlab.load(lab.id))["items"][1]
    b = v["takes"][0]["blind"]
    assert b["state"] == "done" and b["order"] == t.blind.order and b["seen"] == 0 and v["takes"][0]["text"] == t.text
    assert [s["label"] for s in v["scores"]] == ["원문", "판 1"] and v["scores"][1]["take"] == 1 and v["blind_texts"] == []
    with pytest.raises(ValueError):
        revlab.pick(lab, 1, 1)  # 1화는 되돌려 쓴 판이 없다


def test_takes_are_kept_per_model_and_capped(home, monkeypatch):
    lab = _parsed(home)
    for _ in range(3):
        revlab.run_write(lab.id, MockLLM(), 1)
    lab = revlab.load(lab.id)
    e = lab.episodes[0]
    assert [t.no for t in e.takes] == [1, 2, 3] and revlab.pending(e).no == 1  # 다시 써도 앞 판은 남고, 오래된 판부터 가려 읽는다
    revlab.pick(lab, 1, 1)
    revlab.pick(lab, 1, 0)
    assert [t.blind.seen for t in e.takes[:2]] == [0, 1] and revlab.pending(e).no == 3  # 원문을 본 뒤의 고르기는 seen 으로 센다
    revlab.drop_take(lab, 1, 3)
    revlab.save(lab)
    e = revlab.run_write(lab.id, MockLLM(), 1)
    assert [t.no for t in e.takes] == [1, 2, 4]  # 지운 번호는 다시 쓰지 않는다
    with pytest.raises(ValueError, match="판 9"):
        revlab.drop_take(revlab.load(lab.id), 1, 9)
    lab = revlab.load(lab.id)
    sheet = lab.episodes[0].sheet.model_dump()
    revlab.apply_episode(lab, 1, revlab.pipeline.reverse_episode(MockLLM(), lab, 1))
    assert len(lab.episodes[0].takes) == 3  # 다시 역설계해도 판은 남는다
    lab.episodes[0].sheet.key = "바뀐 조성"
    v = revlab._ep_view(lab, lab.episodes[0])
    assert all(t["stale"] for t in v["takes"]) and sheet  # 쓸 때 시트와 달라 '시트 바뀜'
    revlab.save(lab)
    monkeypatch.setattr(revlab, "MAX_TAKES", 3)
    with pytest.raises(ValueError, match="지울 판"):
        revlab.run_write(lab.id, MockLLM(), 1)
    with pytest.raises(ValueError, match="지울 판"):
        revlab.estimate(revlab.load(lab.id), "write", [1])


def test_guess_and_change_first_number(home):
    assert revlab.guess_first("x", STORY) == 1  # 제목 줄이 이긴다
    assert revlab.guess_first("러브 코미디를 망가뜨리는 법-33화", "제목 줄 없는 글") == 33
    assert revlab.guess_first("〈 32화 〉 미유키의 정성", "글") == 32 and revlab.guess_first("", "글") == 1
    lab = revlab.create("러브 코미디 33화", "제목 줄 없는 글 " * 30)
    assert [e.number for e in lab.episodes] == [33]
    assert revlab.create("x", "글 " * 120, first=51).episodes[0].number == 51
    with pytest.raises(ValueError, match="1~9999"):
        revlab.create("x", "글 " * 120, first=10000)
    lab = _parsed(home)
    revlab.renumber(lab, 40)
    assert [(e.number, e.plot.number) for e in lab.episodes] == [(40, 40), (41, 41)] and lab.lines[0].branch_ep == 41
    assert "초반 규칙" not in prompts.cue_score_prompt(revlab.world(lab, 41), 41, lab.episodes[1].sheet)


def test_context_goes_into_rewrite(home):
    lab = _parsed(home)
    e = lab.episodes[0]
    assert e.setting == "바닷가 마을의 등대" and e.facts == ["1화 전에 등대지기가 사라졌다"]  # 빈 사실은 뺀다
    assert [(t.a, t.b, t.type) for t in e.ties] == [("서윤", "도현", "동료")]  # 실험 인물 밖은 뺀다
    assert [(a.speaker, a.listener, a.calls) for a in e.addresses] == [("서윤", "도현", "도현")]  # 자기 자신은 뺀다
    assert lab.cast[0].personality == "말보다 손이 먼저 나간다"
    q = revlab.world(lab, 2)
    assert q.world.setting == "바닷가 마을의 등대" and q.facts == ["1화 전에 등대지기가 사라졌다", "2화 전에 등대지기가 사라졌다"]
    assert q.characters[0].personality and q.relationships[0].description == "오래 함께 등대를 지켰다"
    p = prompts.cue_score_prompt(q, 2, lab.episodes[1].sheet)
    for x in ("바닷가 마을의 등대", "말보다 손이 먼저 나간다", "오래 함께 등대를 지켰다", "해체(반말)", "2화 전에 등대지기가 사라졌다"):
        assert x in p, x
    assert revlab.context_upto(lab, 1)["facts"] == ["1화 전에 등대지기가 사라졌다"]  # 뒤 화에서 읽은 것은 앞 화 사본에 넣지 않는다


def test_style_profile_and_two_takes(home):
    lab = _parsed(home)
    with pytest.raises(ValueError, match="문체 프로필을 먼저"):
        revlab.world(lab, 1, use_style=True)
    est = revlab.estimate(lab, "style")
    assert [r["label"] for r in est["rows"]] == ["문체 프로필"]
    asks = []

    class Asking(MockLLM):
        def json(self, system, prompt, schema, hint=None):
            asks.append(prompt)
            return super().json(system, prompt, schema, hint)
    prof = revlab.run_style(lab.id, Asking())
    assert "sample_passages 는 빈 목록으로" in asks[0] and "문단 2~4개" not in asks[0]  # 버릴 대표 문단은 묻지 않는다
    lab = revlab.load(lab.id)
    assert lab.style is not None and lab.style.sample_passages == [] and prof.sample_passages == []
    q = revlab.world(lab, 1, use_style=True)
    assert q.style.sample_passages == [] and q.style.model_dump(exclude={"sample_passages"}) == lab.style.model_dump(exclude={"sample_passages"})
    assert revlab.world(lab, 1).style.narration_pov == ""  # 고르지 않으면 넣지 않는다
    assert revlab.estimate(lab, "write", [1], use_style=True)["rows"][0]["input_tokens"] >= revlab.estimate(lab, "write", [1])["rows"][0]["input_tokens"]
    revlab.run_write(lab.id, MockLLM(), 1)
    lab = revlab.load(lab.id)
    revlab.pick(lab, 1, 1)
    revlab.save(lab)
    e = revlab.run_write(lab.id, MockLLM(), 1, use_style=True)
    assert [(t.no, t.style) for t in e.takes] == [(1, False), (2, True)]
    v = revlab.view(revlab.load(lab.id))["items"][0]
    assert "text" in v["takes"][0] and "text" not in v["takes"][1]  # 가려 읽기가 남은 판만 감춘다
    assert [s["condition"] for s in v["scores"]] == ["original", "t1"] and v["blind_no"] == 2
    lab = revlab.load(lab.id)
    revlab.pick(lab, 1, 0)
    v = revlab.view(lab)["items"][0]
    assert [s["condition"] for s in v["scores"]] == ["original", "t1", "t2"] and v["takes"][1]["blind"]["seen"] == 1
    assert revlab.view(lab)["style"] and "sample_passages" not in revlab.view(lab)["style"]


def test_style_profile_is_checked_and_reaches_writer(home):
    """mock 프로필의 표지 · 장치 중 시험 원문에 있는 것만 남아 문체 넣은 판의 쓰기 요청에 들어간다 (styled 경로)."""
    lab = _parsed(home)
    revlab.run_style(lab.id, MockLLM())
    lab = revlab.load(lab.id)
    assert [m.text for m in lab.style.markers] == ["있었다"] and lab.style.markers[0].per_1k > 0  # '다' · 인물 이름 '서윤은' · 없는 표지는 빠진다
    assert [(d.cues, d.example) for d in lab.style.devices] == [(["대답"], "대답은 없었다."), ([], "")]  # 지어낸 예시는 비운다
    q = revlab.world(lab, 2, use_style=True)
    assert prompts.styled(q) and not prompts.styled(revlab.world(lab, 2))
    sys, ctx = prompts.writer_system(q), prompts.static_context(q)
    assert "쉼표가 둘 이상" not in sys and "쉼표가 둘 이상" in prompts.writer_system(revlab.world(lab, 2))  # 기본 규칙이 바뀐다
    assert "# 문체 표지" in ctx and "'있었다'" in ctx
    assert "대답 없는 침묵" in prompts.cue_score_prompt(q, 2, lab.episodes[1].sheet)


def test_compare_style_columns(home):
    lab = _parsed(home)
    revlab.run_style(lab.id, MockLLM())
    revlab.run_write(lab.id, MockLLM(), 1)
    lab = revlab.load(lab.id)
    rows = revlab.compare(lab, lab.episodes[0])
    o, t = rows
    assert o["style_distance"] is None and "문체 거리 기준을 만들지 않았어요" in o["style_note"]  # 시험 원문은 6,000자보다 짧다
    assert isinstance(o["comma_ratio"], float) and isinstance(o["marker_warns"], list) and o["copied"] is None
    assert isinstance(t["copied"], list) and t["copied_examples"] is not None
    lab.episodes[0].takes[0].text = lab.episodes[0].text  # 원문을 그대로 옮긴 판
    assert revlab.compare(lab, lab.episodes[0])[1]["copied"]


def _prose(ending: str, n: int, seed: int) -> str:
    """지어낸 서술 글: 같은 낱말에 어미만 ending 판으로."""
    import random as r
    g = r.Random(seed)
    subj = ["그는", "바람이", "서윤이", "파도가", "불빛이", "문이", "배가", "도현이", "손끝이", "등대가"]
    verb = {"past": ["멈췄다", "흔들렸다", "돌아섰다", "떨렸다", "꺼졌다", "울렸다", "젖었다", "닫혔다"],
            "polite": ["멈춰요", "흔들려요", "돌아서요", "떨려요", "꺼져요", "울려요", "젖어요", "닫혀요"]}[ending]
    adv = ["천천히", "다시", "조용히", "갑자기", "한참", "끝내", "가만히", "멀리서"]
    paras = []
    while sum(map(len, paras)) < n:
        paras.append(" ".join(f"{g.choice(subj)} {g.choice(adv)} {g.choice(verb)}." for _ in range(6)))
    return "\n\n".join(paras)


def test_style_distance_orders_by_ending():
    """원문(과거형 '-다')을 뺀 기준에서, 같은 어미 글이 다른 어미(해요체) 글보다 가깝다."""
    from canon.schema import RevEpisode, RevLab
    lab = RevLab(id=1, episodes=[RevEpisode(number=i, text=_prose("past", 3000, i)) for i in range(1, 5)])
    base, why = revlab.style_base(lab, 4)
    assert base and not why and base.style_centroid
    from canon import metrics
    same, other = metrics.style_distance(base, _prose("past", 3000, 99)), metrics.style_distance(base, _prose("polite", 3000, 99))
    assert same < other
    assert revlab.style_base(RevLab(id=2, episodes=lab.episodes[:2]), 1)[0] is None  # 한 화(3,000자)만 남으면 기준을 만들지 않는다


def test_old_lab_file_still_loads(home):
    """맥락 칸을 넣기 전 파일 (인물에 성격 칸 없음, 판 목록 대신 take 하나와 화의 가려 읽기 칸)."""
    lab = _parsed(home)
    revlab.run_write(lab.id, MockLLM(), 1)
    raw = json.loads((home / ".revlab" / f"{lab.id}.json").read_text(encoding="utf-8"))
    for c in raw["cast"]:
        c.pop("personality")
    for e in raw["episodes"]:
        for k in ("setting", "facts", "ties", "addresses", "last_take"):
            e.pop(k)
        takes = e.pop("takes")
        if takes:
            t = takes[0]
            e["blind"], e["picked"] = t.pop("blind")["order"], ""
            for k in ("no", "provider"):
                t.pop(k)
            e["take"] = t
    for k in ("styles", "style_id", "style_next"):
        raw.pop(k)
    (home / ".revlab" / f"{lab.id}.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    old = revlab.load(lab.id)
    v = revlab.view(old)["items"][0]
    assert old.cast[0].personality == "" and [t["no"] for t in v["takes"]] == [1] and v["blind_no"] == 1 and v["blind_texts"]
    old_two = {"number": 3, "take": {"text": "가", "at": "2026-10-30T02"}, "take_style": {"text": "나", "style": True, "at": "2026-10-30T01"},
               "blind_take": "plain", "blind": ["rewrite", "original"], "picked": "original"}
    e = revlab.RevEpisode.model_validate(old_two)
    assert [(t.no, t.text, t.blind.picked) for t in e.takes] == [(1, "나", ""), (2, "가", "original")]  # 쓴 때 차례로, 가려 읽기는 그 판에


def _two_styles(home, monkeypatch):
    """문체를 두 번 역설계한 실험 (두 번째는 시점이 다르다). 1번 프로필로 '문체 넣고' 판 1을 쓴 뒤 2번을 만든다."""
    from canon import pipeline
    from canon.schema import StyleProfile

    lab = _parsed(home)
    seen = []

    def fake(llm, sample, names=None, **kw):
        seen.append(sample)
        return StyleProfile(narration_pov="1인칭" if len(seen) == 1 else "3인칭 제한", tense="과거형")
    monkeypatch.setattr(pipeline, "analyze_style", fake)
    revlab.run_style(lab.id, MockLLM())
    revlab.run_write(lab.id, MockLLM(), 1, use_style=True)
    revlab.run_style(lab.id, MockLLM())
    return revlab.load(lab.id)


def test_style_history_keeps_old_and_links_takes(home, monkeypatch):
    lab = _two_styles(home, monkeypatch)
    assert [x.id for x in lab.styles] == [1, 2] and lab.style_id == 2 and lab.style.narration_pov == "3인칭 제한"
    assert lab.styles[0].profile.narration_pov == "1인칭" and lab.styles[0].basis and lab.styles[0].chars > 0
    e = lab.episodes[0]
    assert e.takes[0].style_id == 1
    row = next(r for r in revlab.compare(lab, e) if r["condition"] == "t1")
    assert row["style_id"] == 1 and row["style_old"] and not row["style_gone"]
    revlab.run_write(lab.id, MockLLM(), 1)
    lab = revlab.load(lab.id)
    plain = next(r for r in revlab.compare(lab, lab.episodes[0]) if r["condition"] == "t2")
    assert "style_id" not in plain  # 문체를 넣지 않은 판
    v = revlab.view(lab)
    assert [x["id"] for x in v["style_list"]] == [2, 1] and v["style_list"][1]["takes"] == 1 and v["style_list"][0]["current"]
    take = v["items"][0]["takes"][0]
    assert take["style_old"] and take["style_id"] == 1 and "text" not in take  # 가려 읽기가 남은 판의 본문은 여전히 감춘다
    assert revlab.summary(lab)["styles"] == 2 and revlab.summary(lab)["style_id"] == 2
    changes = revlab.style_view(lab, 1)["changes"]
    assert [(c["key"], c["before"], c["after"]) for c in changes] == [("narration_pov", "3인칭 제한", "1인칭")]
    assert revlab.style_diff(lab, 1, 1) == []


def test_style_same_profile_selects_existing(home, monkeypatch):
    lab = _two_styles(home, monkeypatch)
    revlab.add_style(lab, lab.styles[0].profile.model_copy(deep=True), "m", "글")
    assert len(lab.styles) == 2 and lab.style_id == 1


def test_style_select_changes_world_and_take(home, monkeypatch):
    lab = _two_styles(home, monkeypatch)
    revlab.with_lock(lab.id, lambda x: revlab.select_style(x, 1))
    lab = revlab.load(lab.id)
    assert revlab.world(lab, 1, use_style=True).style.narration_pov == "1인칭"
    assert not next(r for r in revlab.compare(lab, lab.episodes[0]) if r["condition"] == "t1")["style_old"]
    with pytest.raises(KeyError, match="9번"):
        revlab.select_style(lab, 9)


def test_style_drop(home, monkeypatch):
    lab = _two_styles(home, monkeypatch)
    with pytest.raises(ValueError, match="지금 쓰는 프로필"):
        revlab.drop_style(lab, 2)
    revlab.drop_style(lab, 1)
    assert next(r for r in revlab.compare(lab, lab.episodes[0]) if r["condition"] == "t1")["style_gone"]
    assert [x.id for x in lab.styles] == [2]
    revlab.drop_style(lab, 2)
    assert lab.styles == [] and lab.style_id == 0 and lab.style is None and lab.style_next == 3
    with pytest.raises(ValueError, match="먼저 역설계하세요"):
        revlab.world(lab, 1, use_style=True)


def test_style_keep_limit(home, monkeypatch):
    from canon.schema import StyleProfile

    lab = _two_styles(home, monkeypatch)  # 1번은 판 1이 가리킨다
    monkeypatch.setattr(revlab, "STYLE_KEEP", 3)
    for i in range(3):
        revlab.add_style(lab, StyleProfile(tense=f"t{i}"), "m", "글")
    assert [x.id for x in lab.styles] == [1, 4, 5]  # 판이 가리키는 1번과 지금 프로필은 남고 오래된 2 · 3번이 빠진다
    t = lab.episodes[0].takes[0]
    lab.episodes[0].takes += [t.model_copy(update={"no": 2, "style_id": 4})]
    with pytest.raises(ValueError, match="3개까지"):
        revlab.check_style_room(lab)


def test_replace_and_append_keep_styles(home, monkeypatch):
    lab = _two_styles(home, monkeypatch)
    assert all(x["basis_ok"] for x in revlab.style_items(lab))
    revlab.append_text(lab, APPEND)  # 앞 30,000자 안이라 넣을 글이 바뀐다
    assert not any(x["basis_ok"] for x in revlab.style_items(lab)) and lab.style_id == 2
    revlab.replace_text(lab, "새 글", "다시 넣은 글 " * 40)
    assert len(lab.styles) == 2 and lab.style_id == 0 and lab.style is None
    assert not any(x["basis_ok"] for x in revlab.style_items(lab))


def test_old_style_file_moves_to_history(home):
    lab = _parsed(home)
    revlab.run_style(lab.id, MockLLM())
    revlab.run_write(lab.id, MockLLM(), 1, use_style=True)
    revlab.run_write(lab.id, MockLLM(), 2, use_style=True)
    path = home / ".revlab" / f"{lab.id}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    cur = raw.pop("styles")[0]
    for k in ("style_id", "style_next"):
        raw.pop(k)
    raw.update(style=cur["profile"], style_model="gemini:x", style_at="2026-10-30T10:00:00")
    raw["episodes"][0]["takes"][0].pop("style_id")
    t = raw["episodes"][1].pop("takes")[0]  # 판 목록 전 파일: take_style 하나
    t.pop("style_id"), t.pop("no"), t.pop("blind")
    raw["episodes"][1]["take_style"] = t
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    old = revlab.load(lab.id)
    assert [(x.id, x.model, x.basis) for x in old.styles] == [(1, "gemini:x", "")] and old.style_id == 1 and old.style_next == 2
    assert [t.style_id for e in old.episodes for t in e.takes] == [1, 1] and revlab.style_items(old)[0]["basis_ok"]
    revlab.save(old)
    again = json.loads(path.read_text(encoding="utf-8"))
    assert "style_model" not in again and "style" not in again and again["style_id"] == 1


def test_web_styles(home, monkeypatch):
    from canon import web

    lab = _two_styles(home, monkeypatch)
    c = TestClient(web.app)
    v = c.get(f"/api/revlab/{lab.id}").json()
    assert [x["id"] for x in v["style_list"]] == [2, 1] and v["style_model"] and v["style"]["narration_pov"] == "3인칭 제한"
    x = c.get(f"/api/revlab/{lab.id}/styles/1").json()
    assert x["profile"]["narration_pov"] == "1인칭" and x["against"] == 2 and x["changes"][0]["key"] == "narration_pov"
    assert c.get(f"/api/revlab/{lab.id}/styles/1", params={"against": 1}).json()["changes"] == []
    assert c.get(f"/api/revlab/{lab.id}/styles/9").status_code == 400
    v = c.put(f"/api/revlab/{lab.id}/styles/1", json={"note": " 첫 판 "}).json()
    assert v["style_list"][1]["note"] == "첫 판"
    v = c.post(f"/api/revlab/{lab.id}/styles/1/select").json()
    assert v["style_id"] == 1 and v["style"]["narration_pov"] == "1인칭"
    assert c.delete(f"/api/revlab/{lab.id}/styles/1").status_code == 400
    v = c.delete(f"/api/revlab/{lab.id}/styles/2").json()
    assert [x["id"] for x in v["style_list"]] == [1]
    busy = jobs.Job(id="x", project=revlab.JOBS, kind="rev_style", ep=lab.id, label="문체 역설계")
    monkeypatch.setattr(jobs, "listing", lambda project=None: [busy])
    r = c.post(f"/api/revlab/{lab.id}/styles/1/select")
    assert r.status_code == 409 and "문체를 역설계하는 동안" in r.text
    busy.kind = "rev_write"
    assert c.post(f"/api/revlab/{lab.id}/styles/1/select").status_code == 200  # 되돌려 쓰는 동안에는 고를 수 있다


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


def _real_ai(monkeypatch):
    """mock 이 아닌 설정 (단계 환경 변수는 지운다). 실제 AI 는 부르지 않는다."""
    monkeypatch.setenv("CANON_LLM", "gemini")
    for k in ("CANON_MODEL", "CANON_LLM_PLAN", "CANON_LLM_WRITE", "CANON_MODEL_PLAN", "CANON_MODEL_WRITE"):
        monkeypatch.delenv(k, raising=False)


def test_ai_choice_follows_settings_preset_or_lab(home, monkeypatch):
    lab = revlab.create("등대", STORY)
    assert revlab.ai_choice(lab, "write") == {"provider": "mock", "model": "", "source": "mock"}  # mock 설정이면 모든 작업이 mock
    assert revlab.llm_for(lab, "style").stage == "plan"
    _real_ai(monkeypatch)
    assert revlab.ai_choice(lab, "plan") == {"provider": "gemini", "model": "", "source": "settings"}
    revlab.set_ai(lab, "write", provider="Claude", model=" claude-opus-5-5 ")
    assert revlab.ai_choice(lab, "write") == {"provider": "claude", "model": "claude-opus-5-5", "source": "lab"}
    assert revlab.ai_choice(lab, "plan")["source"] == "settings"  # 단계마다 따로 고른다
    revlab.set_ai(lab, "plan", preset="anthropic")
    assert revlab.ai_choice(lab, "plan") == {"provider": "claude-api", "model": "claude-opus-5-5", "source": "preset"}
    est = revlab.estimate(lab, "parse")
    assert est["provider"] == "claude-api" and est["model"] == "claude-opus-5-5"
    revlab.set_ai(lab, "write")
    assert lab.ai.write == RevAI()  # 모두 비우면 설정을 따른다
    with pytest.raises(ValueError, match="프리셋"):
        revlab.set_ai(lab, "plan", preset="nope")
    with pytest.raises(ValueError, match="고를 수 없는"):
        revlab.set_ai(lab, "plan", provider="mock")
    with pytest.raises(ValueError, match="모르는 단계"):
        revlab.set_ai(lab, "check", provider="gemini")
    lab.ai.plan = RevAI(preset="gone", provider="claude")
    assert revlab.ai_choice(lab, "plan")["source"] == "gone"  # 지워진 프리셋은 직접 고른 값이 아니라 설정을 따른다
    v = revlab.ai_view(lab)
    assert [x["stage"] for x in v["stages"]] == ["plan", "write"] and v["custom"]
    assert v["stages"][1]["use"] == {"provider": "gemini", "model": "", "source": "settings", "default": "gemini-4-argon"}
    assert {"id": "anthropic", "name": "Anthropic (Claude API 키)"} in v["presets"]
    assert RevLab.model_validate({"id": 3}).ai.plan == RevAI()  # 옛 실험 파일도 읽힌다


def test_web_ai_pick(home, monkeypatch):
    from canon import web

    c = TestClient(web.app)
    lab_id = c.post("/api/revlab", json={"title": "등대", "text": STORY}).json()["id"]
    v = c.put(f"/api/revlab/{lab_id}/ai", json={"stage": "write", "provider": "claude-api", "model": "claude-sonnet-5-5"}).json()
    assert v["ai"]["stages"][1]["provider"] == "claude-api" and revlab.load(lab_id).ai.write.model == "claude-sonnet-5-5"
    assert c.put(f"/api/revlab/{lab_id}/ai", json={"stage": "plan", "preset": "nope"}).status_code == 400
    seen = []

    def fake(lab, kind):
        seen.append((lab.ai.write.provider, kind))
        return MockLLM()
    monkeypatch.setattr(revlab, "llm_for", fake)
    j = _wait(c, c.post(f"/api/revlab/{lab_id}/jobs", json={"kind": "parse", "episodes": [1]}).json()["id"])
    assert j["status"] == "done" and seen == [("claude-api", "parse")]  # 작업은 실험이 고른 AI 로 돈다


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
    r = c.post(f"/api/revlab/{lab_id}/jobs", json={"kind": "parse"})
    assert r.status_code == 200, r.text
    assert r.json()["pending"] == [1, 2] and r.json()["total"] == 3  # 화면이 화마다 진행 줄을 그린다 (revRunRows)
    j = _wait(c, r.json()["id"])
    assert j["status"] == "done" and j["result"]["episodes"] == 2 and j["project"] == revlab.JOBS and j["kind"] == "rev_parse", j
    assert c.post("/api/projects/demo/jobs", json={"kind": "rev_parse", "ep": lab_id}).status_code == 400  # 작품 작업으로는 돌지 않는다
    v = c.get(f"/api/revlab/{lab_id}").json()
    assert v["done"] == 2 and v["lines"] and v["items"][0]["sheet"]["cues"]
    sheet = v["items"][0]["sheet"]
    sheet["key"] = "작가가 고친 조성"
    v = c.put(f"/api/revlab/{lab_id}/episodes/1/sheet", json=sheet).json()
    assert v["items"][0]["sheet"]["key"] == "작가가 고친 조성" and v["items"][0]["bounds_ok"]
    assert c.post(f"/api/revlab/{lab_id}/jobs", json={"kind": "write"}).status_code == 400  # 화를 하나 골라야 한다
    r = c.post(f"/api/revlab/{lab_id}/jobs", json={"kind": "write", "episodes": [1]})
    assert _wait(c, r.json()["id"])["status"] == "done"
    j = c.get(f"/api/jobs/{r.json()['id']}").json()
    assert j["result"]["take"] == 1
    assert c.post(f"/api/revlab/{lab_id}/episodes/1/pick", json={"choice": 0, "take": 2}).status_code == 400  # 낡은 화면
    v = c.post(f"/api/revlab/{lab_id}/episodes/1/pick", json={"choice": 0, "take": 1}).json()
    assert v["items"][0]["takes"][0]["blind"]["picked"] == "skip" and len(v["items"][0]["scores"]) == 2
    r = c.post(f"/api/revlab/{lab_id}/jobs", json={"kind": "write", "episodes": [1]})
    assert _wait(c, r.json()["id"])["result"]["take"] == 2  # 다시 써도 앞 판은 남는다
    v = c.delete(f"/api/revlab/{lab_id}/episodes/1/takes/2").json()
    assert [t["no"] for t in v["items"][0]["takes"]] == [1] and v["items"][0]["next_take"] == 3
    assert c.delete(f"/api/revlab/{lab_id}/episodes/1/takes/2").status_code == 400
    bad = c.post(f"/api/revlab/{lab_id}/jobs", json={"kind": "write", "episodes": [1], "style": True})
    assert bad.status_code == 400 and "문체 프로필을 먼저" in bad.text
    assert c.post(f"/api/revlab/{lab_id}/estimate", json={"kind": "style"}).json()["calls"] == 1
    r = c.post(f"/api/revlab/{lab_id}/jobs", json={"kind": "style"})
    assert _wait(c, r.json()["id"])["status"] == "done" and c.get(f"/api/revlab/{lab_id}").json()["style"]
    r = c.post(f"/api/revlab/{lab_id}/jobs", json={"kind": "write", "episodes": [1], "style": True})
    j = _wait(c, r.json()["id"])
    assert j["status"] == "done" and j["result"]["style"] and "문체 넣음" in j["label"], j
    assert c.put(f"/api/revlab/{lab_id}", json={"title": "등대", "first": 30}).json()["items"][0]["number"] == 30
    assert c.post("/api/revlab", json={"title": "33화 실험", "text": "제목 줄 없는 글 " * 30}).json()["first"] == 33
    v = c.put(f"/api/revlab/{lab_id}", json={"title": "새 이름"}).json()
    assert v["title"] == "새 이름" and v["done"] == 2 and v["first"] == 30  # 글을 주지 않으면 결과는 그대로
    v = c.put(f"/api/revlab/{lab_id}", json={"title": "새 이름", "text": "다시 넣은 글 " * 40}).json()
    assert v["episodes"] == 1 and v["done"] == 0 and v["lines"] == []
    assert any(x["title"] == "새 이름" for x in c.get("/api/revlab").json()["labs"])
    assert c.delete(f"/api/revlab/{lab_id}").json() == {"ok": True} and lab_id not in revlab.ids()
    assert (home / "demo" / "project.json").read_text(encoding="utf-8") == before  # 작품은 그대로


def test_job_runs_outside_projects(home, monkeypatch):
    """작품을 열지 않고 돈다: 사용량 범위에 작품이 없고(작품 프리셋을 쓰지 않음), 작업 목록에는 revlab.JOBS 로 보인다."""
    from canon import settings, usage, web
    from canon.schema import StyleProfile

    seen = []

    def fake(lab_id, llm):
        seen.append((usage.context(), settings.project_preset()))
        return StyleProfile()
    monkeypatch.setattr(revlab, "run_style", fake)
    lab = revlab.create("등대", STORY)
    c = TestClient(web.app)
    j = _wait(c, c.post(f"/api/revlab/{lab.id}/jobs", json={"kind": "style"}).json()["id"])
    assert j["status"] == "done" and j["project"] == revlab.JOBS
    ctx, preset = seen[0]
    assert not ctx.get("project") and ctx["task"] == "rev_style" and preset is None
    again = c.post(f"/api/revlab/{lab.id}/jobs", json={"kind": "write", "episodes": [1]})
    assert again.status_code == 400 and "역설계하세요" in again.text


def _light(text: str) -> dict:
    """화면이 받는 나누기 값 (POST /api/revlab/split): 화 글 대신 글자 수."""
    from canon import web
    return web.rev_split(web.RevSplitIn(text=text))


@needs_node
def test_js_guess_first_matches_python():
    cases = [["x", STORY], ["러브 코미디-33화", "제목 줄 없는 글"], ["〈 32화 〉 미유키", "글"], ["", "글"], ["7화", "# 12화 비\n본문"]]
    got = run_js(FILES, "data.map(([t, x, s]) => revGuessFirst(t, x, s))", [[t, x, _light(x)] for t, x in cases])
    assert got == [revlab.guess_first(t, x) for t, x in cases] == [1, 33, 32, 1, 12]


def test_split_endpoint_gives_counts_not_text():
    v = _light(STORY)
    assert v["how"] == "heading" and [e["chars"] for e in v["episodes"]] == [len(e["text"]) for e in revlab.split(STORY)["episodes"]]
    assert all(set(e) == {"head", "chars"} for e in v["episodes"])


@needs_node
def test_js_preview_waits_for_server():
    got = run_js(FILES, "revPreview('1화\\n본문', { max_chars: 10, max_episodes: 30, min_chars: 1 })", {})
    assert got["pending"] and not got["errs"]


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
      S.project = null; S.name = null; S.route = ['revlab'];
      S.rev = data.home; S.cue = data.home; S.revLab = null;
      S.revDraft = { title: '', text: data.story };
      const home = viewRev();
      const prev = revPreview(data.story, data.home, null, data.split);
      const tooMany = revPreview(data.manyText, data.home, null, data.many);
      S.revLab = data.lab; S.revEp = 1; S.revPick = new Set([2]); S.revSel = 2; S.revTab = 'text';
      S.revEsts = { 'write:2': { usd: 0.04, calls: 1, rows: [], model: 'm', note: '' } };
      const lab = viewRev();
      S.revTab = 'write';
      const write = viewRev();
      S.revEp = 2; S.revTab = 'text';
      const two = viewRev();
      S.revTab = 'write';
      const twoWrite = viewRev();
      const panes = {};
      for (const k of ['overview', 'cast', 'style', 'lines', 'metrics']) { S.revPane = k; panes[k] = viewRev(); }
      S.revRedo = true; S.revPane = 'overview';
      const redo = viewRev();
      S.revRedo = false;
      S.rev = Object.assign({}, data.home, { labs: [] }); S.revLab = null; S.revDraft = { title: '', text: '' };
      const empty = viewRev();
      S.rev = data.home; S.revLab = data.lab;
      S.revPane = null; S.revEdit = true;
      const edit = viewRev();
      S.revEdit = false; S.revFrom = { name: '등대 일지', title: '등대의 <밤>' };
      const from = viewRev();
      S.revLab = null;
      const fromHome = viewRev();
      S.revFrom = null; S.revLab = data.lab;
      const e = data.lab.items[1];
      return { home, prev, tooMany: tooMany.errs, lab, write, two, twoWrite, panes, edit, redo, empty, from, fromHome, segs: revSegments(e.text, e.bounds),
               gap: revSegments('abcdef', [{ start: 2, end: 4, found: true }, { start: 4, end: 4, found: false }]) };
    })()""", {"home": labels, "lab": view, "story": STORY, "split": _light(STORY), "manyText": MANY, "many": _light(MANY)})
    assert "새 실험" in got["home"] and "이어 하기" in got["home"] and 'class="card rev-lab"' in got["home"]
    assert 'id="rev-new"' in got["home"] and "btn on" in got["home"]  # 붙여 넣은 글이 있으면 새 실험 카드를 펴 둔다
    assert got["prev"]["how"] == "heading" and [e["n"] for e in got["prev"]["eps"]] == [1, 2] and not got["prev"]["errs"]
    assert got["prev"]["notes"]  # 앞머리 안내
    assert got["tooMany"] and "30화까지" in got["tooMany"][0]
    lab = got["lab"]
    assert 'aria-label="실험 목차"' in lab and "되돌려 쓰기" in lab and "가려 읽기" in lab  # 목차의 단계
    assert "1번이 더 읽고 싶어요" not in lab  # 원문 · 큐 탭에는 가려 읽기가 없다
    assert 'id="rev-cue-2"' in lab and "rev-seg sel" in lab and "cue-bars" in lab and "큐 시트 고치기" in lab
    assert 'aria-selected="true"' in lab and "원문 · 큐" in lab and "플롯 · 스토리보드" in lab
    assert 'data-action="revGo" data-arg="1|write"' in lab and "1화 가려 읽기" in lab  # 머리 주 버튼: 지금 화에 남은 가려 읽기
    w = got["write"]
    assert "1번이 더 읽고 싶어요" in w and "원문</td>" not in w  # 1화: 고르기 전에는 지표에 되돌려 쓴 글이 없다
    assert "시작 문장을 원문에서 못 찾았어요" in got["two"]
    assert "판 1 쓰기" in got["twoWrite"] and "약 0.04달러" in got["twoWrite"] and "비용 재는 중" not in got["twoWrite"]  # 추정이 있으면 버튼에 비용
    assert 'data-action="revWrite" data-arg="2"' in got["twoWrite"]
    p = got["panes"]
    assert "인물 · 관계 · 배경" in p["cast"] and "말보다 손이 먼저 나간다" in p["cast"] and "오래 함께 등대를 지켰다" in p["cast"]
    assert "도현 → " not in p["cast"] and "서윤 → 도현" in p["cast"]
    assert "문체 역설계 시작" in p["style"] and "두 사람의 관계" in p["lines"]
    assert "화별 진행" in p["overview"] and "역설계할 화" not in p["overview"] and 'href="#/revlab/1/cast"' in p["overview"]  # 다 푼 실험의 개요
    assert "다시 역설계할 화" in got["redo"] and got["redo"].count("btn primary") == 1 and "고른 1화 다시 역설계" in got["redo"]
    assert 'id="rev-new"' in got["empty"] and "이어 하기" not in got["empty"] and "revNewToggle" not in got["empty"]  # 실험이 없으면 바로 새 실험
    assert "지표 모아 보기" in p["metrics"] and "가려 읽기를 마친 판" in p["metrics"]  # 아직 고르지 않아 견줄 판이 없다
    assert "초반 규칙" in got["edit"] and "글 · 이름 고치기" in got["edit"]
    assert got["edit"].count("btn primary") == 1 and got["lab"].count("btn primary") == 1  # 주 버튼은 한 화면에 하나
    # 작품 목록은 작품 밖 사이드바에 있다. 머리에는 작품에서 들어왔을 때만 그 작품으로 가는 버튼
    for k in ("home", "lab", "empty", "from", "fromHome"):
        assert '<a class="btn" href="#/">작품 목록</a>' not in got[k], k
    assert "‹ " not in got["home"] and "‹ " not in got["lab"]
    for k in ("from", "fromHome"):
        assert '<a class="btn" href="#/p/%EB%93%B1%EB%8C%80%20%EC%9D%BC%EC%A7%80">‹ 등대의 &lt;밤&gt;</a>' in got[k], k
    assert got["from"].count("btn primary") == 1
    e = view["items"][1]
    assert [s["cue"] for s in got["segs"]] == [i + 1 for i, b in enumerate(e["bounds"]) if b["found"] and b["end"] > b["start"]]
    assert "".join(e["text"][s["start"]:s["end"]] for s in got["segs"]) == e["text"]  # 빈틈없이 덮는다
    assert got["gap"] == [{"cue": 0, "start": 0, "end": 2}, {"cue": 1, "start": 2, "end": 4}, {"cue": 0, "start": 4, "end": 6}]


def _item(n, chars=500, sheet=False, takes=0, blind=False, head=""):
    """화면 값 한 화. blind 면 마지막 판이 가려 읽기가 남은 판, 앞 판들은 고른 판."""
    ts = [{"no": i + 1, "blind": {"state": "wait" if blind and i == takes - 1 else "done", "picked": "original", "seen": i}} for i in range(takes)]
    return {"number": n, "head": head, "chars": chars, "sheet": {"cues": [{}] * 3} if sheet else None,
            "takes": ts, "blind_texts": ["a", "b"] if blind else []}


@needs_node
def test_js_steps_next_and_toc():
    """단계 다섯 · 다음 할 일 · 목차의 화 줄 (revSteps · revNext · revTocEps · revEpTitle)."""
    labs = {
        "fresh": {"items": [_item(1), _item(2), _item(3, chars=50)], "style": None},
        "parsed": {"items": [_item(1, sheet=True), _item(2, sheet=True), _item(3, chars=50)], "style": None},
        "blind": {"items": [_item(1, sheet=True, takes=1), _item(2, sheet=True, takes=1, blind=True), _item(3, sheet=True)], "style": {"tense": "과거"}},
        "done": {"items": [_item(1, sheet=True, takes=2)], "style": {}},
    }
    got = run_js(FILES, """Object.assign(Object.fromEntries(Object.entries(data.labs).map(([k, L]) => [k, {
        steps: revSteps(L, 200).map((s) => `${s.id}:${s.state}:${s.right}`),
        running: revSteps(L, 200, ['rev_parse']).map((s) => s.state),
        share: revStepShare(revSteps(L, 200)),
        next1: revNext(L, 1, 200), next3: revNext(L, 3, 200),
        toc: revTocEps(L.items, 200).map((x) => `${x.n}:${x.state}:${x.right}`),
      }])), { titles: data.heads.map((h) => revEpTitle({ head: h })) })""", {"labs": labs, "heads": ["12화 젖은 필름", "# 제 3화: 비", "3화", "", "프롤로그"]})
    f = got["fresh"]
    assert f["steps"] == ["split:ok:3화", "parse:now:0/2", "style:todo:고르면", "write:todo:0/0", "pick:todo:0/0"]
    assert f["running"][1] == "run" and f["running"][3] == "now"  # 역설계가 도는 동안 '지금'은 다음 단계로
    assert f["share"] == 0.25 and f["next1"] == {"kind": "parse", "eps": [1, 2]}  # 짧은 3화는 풀지 않는다
    assert f["toc"] == ["1:raw:500자", "2:raw:500자", "3:short:짧음"]
    p = got["parsed"]
    assert p["steps"][1] == "parse:ok:2/2" and p["steps"][3] == "write:now:0/2"
    assert p["next1"] == {"kind": "write", "n": 1} and p["next3"] == {"kind": "write", "n": 1}  # 3화(짧음)에서는 돌아서 1화
    assert p["toc"][0] == "1:parsed:큐 3"
    b = got["blind"]
    assert b["steps"] == ["split:ok:3화", "parse:ok:3/3", "style:ok:있음", "write:now:2/3", "pick:todo:1/2"]
    assert b["next1"] == {"kind": "pick", "n": 2} and b["next3"] == {"kind": "write", "n": 3}  # 지금 화를 먼저
    assert b["toc"][:2] == ["1:wrote:1판", "2:wrote:가려 읽기"]
    d = got["done"]
    assert all(x.endswith(("3화", "1화")) or ":ok:" in x for x in d["steps"]) and d["share"] == 1 and d["next1"] is None
    assert got["titles"] == ["젖은 필름", "비", "", "", "프롤로그"]


@needs_node
def test_js_run_rows_and_metric_rows():
    """역설계 진행 줄(revRunRows)과 지표를 지표마다 한 줄로(revMetricRows)."""
    items = [_item(4, head="4화 눈"), _item(5), _item(6)]
    jobs = [{"pending": [4, 5, 6], "done": 1, "total": 4}, {"pending": [5], "done": 1, "total": 2}, {"pending": [4, 5], "done": 0, "total": 2}]
    o = {"condition": "original", "label": "원문", "chars": 1000, "lines_total": 0, "lines_hit": 0, "dialogue_ratio": 0.1, "sentence_len": 20,
         "mattr": 0.9, "short_endings": 0, "repeats": [], "ai_patterns": 0, "rows": [{}], "tempo_order": True,
         "style_distance": None, "style_note": "기준이 짧아요", "comma_ratio": 0.1, "marker_warns": [], "copied": None, "copied_examples": None}
    t = {**o, "condition": "plain", "label": "되돌려 쓴 글", "chars": 1500, "lines_total": 4, "lines_hit": 3, "dialogue_ratio": 0.12,
         "sentence_len": 11, "mattr": None, "repeats": ["x"], "ai_patterns": 2, "rows": [], "stale": True,
         "comma_ratio": 0.5, "marker_warns": ["'있었다' 9회 (원문 빈도면 2회 안팎)"], "copied": ["대답은 없었다."], "copied_examples": []}
    got = run_js(FILES, "({ rows: data.jobs.map((j) => revRunRows(j, data.items)), m: revMetricRows(data.scores) })",
                 {"items": items, "jobs": jobs, "scores": [o, t]})
    assert got["rows"][0] == [{"n": 4, "title": "눈", "state": "done"}, {"n": 5, "title": "", "state": "run"},
                              {"n": 6, "title": "", "state": "wait"}, {"n": 0, "title": "이야기 줄기", "state": "wait"}]
    assert got["rows"][1][-1] == {"n": 0, "title": "이야기 줄기", "state": "run"}  # 화를 다 풀고 줄기를 묻는 중
    assert [r["state"] for r in got["rows"][2]] == ["run", "wait"]  # 줄기를 묻지 않는 작업
    m = got["m"]
    assert m["heads"] == [{"label": "원문", "stale": False}, {"label": "되돌려 쓴 글", "stale": True}]
    row = {r["label"]: [(c["text"], c["far"]) for c in r["cells"]] for r in m["rows"]}
    assert row["글자"] == [("1,000", False), ("1,500", True)]  # 4할 넘게 다르면 표시
    assert row["대사 비율"] == [("10%", False), ("12%", False)]
    assert row["문장 길이"] == [("20", False), ("11", True)]
    assert row["핵심 대사 들어감"] == [("-", False), ("3/4", False)]
    assert row["어휘 다양도"] == [("0.9", False), ("-", False)]
    assert row["되풀이 문장"] == [("0", False), ("1", True)] and row["쇠맛 경고"] == [("0", False), ("2", True)]  # 원문이 0이면 하나라도 표시
    assert row["템포 (원문 큐 경계)"] == [("맞음", False), ("-", False)]
    assert row["문체 거리 (원문 다른 화 1.0)"] == [("-", False), ("-", False)]
    assert row["쉼표 문장"] == [("10%", False), ("50%", True)] and row["표지 빈도 경고"] == [("0", False), ("1", True)]
    assert row["원문 옮김"] == [("-", False), ("1", True)] and row["장치 예시 옮김"] == [("-", False), ("0", False)]  # 하나라도 옮기면 표시
    assert m["notes"] == ["기준이 짧아요", "되돌려 쓴 글 표지: '있었다' 9회 (원문 빈도면 2회 안팎)", "되돌려 쓴 글 옮긴 문장: “대답은 없었다.”"]



@needs_node
def test_js_style_tag():
    cases = [{}, {"style_id": 2, "style_old": False}, {"style_id": 2, "style_old": True}, {"style_id": 2, "style_old": True, "style_gone": True},
             {"style_id": 0, "style_old": True}]
    assert run_js(FILES, "data.map(revStyleTag)", cases) == ["", "", "2번 프로필", "지운 프로필", "지운 프로필"]


@needs_node
def test_js_home_card_and_overview_row():
    """처음 화면 카드(revLabLite · revHomeCard)와 개요 줄(revOverviewRow)."""
    def st(n, sheet=False, takes=0, blind=0, picks=None, chars=500):
        return {"number": n, "head": "", "chars": chars, "sheet": sheet, "takes": takes, "blind": blind,
                "picks": {"original": 0, "rewrite": 0, "skip": 0, **(picks or {})}}
    labs = [
        {"done": 0, "has_style": False, "steps": [st(1), st(2)]},
        {"done": 2, "has_style": True, "steps": [st(1, True, 1, picks={"original": 1}), st(2, True)]},
        {"done": 2, "has_style": False, "steps": [st(1, True, 1, blind=1), st(2, True, 2, picks={"rewrite": 2})]},
        {"done": 1, "has_style": False, "steps": [st(1, True, 2, picks={"original": 1, "skip": 1}), st(2, chars=10)]},
    ]
    o = {"condition": "original", "dialogue_ratio": 0.1, "lines_total": 0, "lines_hit": 0}
    t1 = {"condition": "t1", "take": 1, "dialogue_ratio": 0.11, "lines_total": 4, "lines_hit": 2}
    t2 = {"condition": "t2", "take": 2, "dialogue_ratio": 0.3, "lines_total": 4, "lines_hit": 3}
    done = lambda no, picked, seen, model="m": {"no": no, "model": model, "blind": {"state": "done", "picked": picked, "seen": seen}}
    eps = [
        {"number": 7, "head": "7화 눈", "chars": 900, "sheet": {"cues": [{}, {}]}, "storyboard": {"scenes": [{}]}, "missing": [2],
         "takes": [done(1, "original", 0), done(2, "rewrite", 1, "n"), {"no": 3, "model": "n", "blind": {"state": "wait", "seen": 2}}],
         "blind_texts": ["a", "b"], "scores": [o, t1, t2]},
        {"number": 8, "head": "", "chars": 900, "sheet": None, "missing": [], "takes": [], "blind_texts": [], "scores": []},
        {"number": 9, "head": "", "chars": 50, "sheet": None, "missing": [], "takes": [], "blind_texts": [], "scores": []},
        {"number": 10, "head": "", "chars": 900, "sheet": {"cues": [{}]}, "missing": [], "takes": [done(1, "original", 0)], "blind_texts": [], "scores": [o, t1]},
    ]
    got = run_js(FILES, "({ cards: data.labs.map((x) => revHomeCard(x, 200)), rows: data.eps.map((e) => revOverviewRow(e, 200)) })",
                 {"labs": labs, "eps": eps})
    c = got["cards"]
    assert c[0]["chip"] == {"text": "역설계 전", "cls": ""} and c[0]["next"] == "2화 역설계" and c[0]["states"][:2] == ["ok", "now"]
    assert c[1]["chip"]["text"] == "되돌려 쓰기 1/2" and c[1]["next"] == "2화 되돌려 쓰기" and c[1]["picks"]["original"] == 1
    assert c[3]["picks"] == {"original": 1, "rewrite": 0, "skip": 1} and c[2]["picks"]["rewrite"] == 2  # 판마다 센다
    assert c[2]["next"] == "1화 가려 읽기" and c[2]["chip"]["text"] == "가려 읽기 1/2"
    assert c[3]["chip"] == {"text": "다 견줌", "cls": "ok"} and c[3]["next"] == "" and c[3]["share"] == 1  # 짧은 화는 풀지 않는다
    r = got["rows"]
    assert r[0] == {"n": 7, "title": "눈", "state": "parsed", "cues": 2, "scenes": 1, "missing": 1, "takes": 3, "models": 2,
                    "picks": {"original": 1, "rewrite": 1, "skip": 0, "wait": 1, "first": {"original": 1, "rewrite": 0}},
                    "lines": "3/4", "dlg": ["10%", "11%~30%"], "far": True}  # 핵심 대사는 최근 판, 대사 비율은 판들의 범위
    assert r[1]["state"] == "raw" and r[1]["dlg"] is None and r[1]["takes"] == 0
    assert r[2]["state"] == "short"
    assert r[3]["dlg"] == ["10%", "11%"] and r[3]["far"] is False and r[3]["lines"] == "2/4"


def test_listing_summary_for_home(home):
    """처음 화면 카드에 드는 목록 값: 최근에 고친 차례, 화마다 단계 값(원문 없음)."""
    a = revlab.create("앞", STORY)
    b = _parsed(home)
    revlab.run_write(b.id, MockLLM(), 1)
    labs = revlab.listing()
    assert [x["id"] for x in labs][:2] == [b.id, a.id]  # b 를 나중에 고쳤다 (같은 초면 번호가 큰 쪽)
    x = next(x for x in labs if x["id"] == b.id)
    assert x["updated"] and x["cast_count"] == len(revlab.load(b.id).cast) and x["has_style"] is False
    s1 = x["steps"][0]
    assert s1["sheet"] is True and s1["takes"] == 1 and s1["blind"] == 1 and s1["picks"] == {"original": 0, "rewrite": 0, "skip": 0} and "text" not in s1
    assert next(x for x in labs if x["id"] == a.id)["steps"][0]["sheet"] is False

def _cue_labels():
    from canon import web
    return web._cue_labels()


def test_dump_roundtrip(home):
    lab = _parsed(home)
    again = revlab.load(lab.id)
    assert dump(again) == dump(lab)


APPEND = "등대지기의 밤\n\n7화 아침\n" + "아침이 왔다. 서윤은 창고 열쇠를 도현에게 돌려주었다. " * 8 + "\n\n8화\n" + "도현은 열쇠를 받고 오래 말이 없었다. " * 10


def test_append_keeps_results_and_asks_lines_again(home):
    lab = _parsed(home)
    before = [e.model_dump() for e in lab.episodes]
    cast, lines, preface = [c.name for c in lab.cast], [x.id for x in lab.lines], lab.preface
    assert revlab.append_text(lab, APPEND) == [3, 4]  # 제목 줄 번호(7화)와 상관없이 마지막 화 다음부터
    revlab.save(lab)
    lab = revlab.load(lab.id)
    assert [e.model_dump() for e in lab.episodes[:2]] == before and [c.name for c in lab.cast] == cast and [x.id for x in lab.lines] == lines
    assert [(e.number, e.head, e.sheet) for e in lab.episodes[2:]] == [(3, "7화 아침", None), (4, "8화", None)]
    assert lab.preface == preface and "등대지기의 밤" not in lab.episodes[2].text  # 이은 글의 앞머리 줄은 넣지 않고, 실험 앞머리는 그대로
    p = prompts.rev_prompt(lab, 3)
    assert "직전 화(2화)" in p and "서윤" in p  # 새 화 요청에 앞 화 인물 · 직전 화가 들어간다
    assert revlab.wants_lines(lab, [3, 4]) and not revlab.wants_lines(lab, [3])
    assert revlab.run_parse(lab.id, MockLLM(), [3, 4])["lines"] is not None  # 새 화까지 풀면 이야기 줄기를 다시 묻는다


def test_append_limits(home, monkeypatch):
    lab = revlab.create("등대", STORY)
    with pytest.raises(ValueError, match="비었어요"):
        revlab.append_text(lab, "  ")
    monkeypatch.setattr(revlab, "MAX_EPISODES", 3)
    with pytest.raises(ValueError, match="이으면 4화예요"):
        revlab.append_text(lab, APPEND)
    monkeypatch.setattr(revlab, "MAX_EPISODES", 30)
    monkeypatch.setattr(revlab, "MAX_CHARS", sum(len(e.text) for e in lab.episodes) + 100)
    with pytest.raises(ValueError, match="자까지 넣을 수 있어요"):
        revlab.append_text(lab, APPEND)
    assert len(lab.episodes) == 2  # 막히면 그대로


def test_web_append(home):
    from canon import web

    c = TestClient(web.app)
    lab_id = c.post("/api/revlab", json={"title": "등대", "text": STORY}).json()["id"]
    v = c.post(f"/api/revlab/{lab_id}/episodes", json={"text": APPEND}).json()
    assert [e["number"] for e in v["items"]] == [1, 2, 3, 4] and v["episodes"] == 4
    assert c.post(f"/api/revlab/{lab_id}/episodes", json={"text": ""}).status_code == 400
    assert c.post("/api/revlab/99/episodes", json={"text": APPEND}).status_code == 404


@needs_node
def test_js_append_preview_matches_python(home):
    lim = revlab.labels()
    lab = revlab.create("등대", STORY)
    have = {"next": 3, "episodes": 2, "chars": sum(len(e.text) for e in lab.episodes)}
    texts = [APPEND, " ", "그냥 한 화 " * 50]
    got = run_js(FILES, "data.texts.map((t, i) => revAppendPreview(t, data.lim, data.have, data.splits[i]))",
                 {"texts": texts, "lim": lim, "have": have, "splits": [_light(t) for t in texts]})
    nums = revlab.append_text(lab, APPEND)
    assert [e["n"] for e in got[0]["eps"]] == nums and not got[0]["errs"]
    assert any("7화부터지만 마지막 화 다음인 3화" in x for x in got[0]["notes"]) and any("넣지 않아요" in x for x in got[0]["notes"])
    assert got[1]["errs"] and got[2]["how"] == "one" and [e["n"] for e in got[2]["eps"]] == [3]
    many = run_js(FILES, "revAppendPreview(data.t, data.lim, data.have, data.s)", {"t": APPEND, "lim": {**lim, "max_episodes": 3}, "have": have, "s": _light(APPEND)})
    assert many["errs"] == ["이으면 4화예요. 한 실험에 3화까지 넣을 수 있어요."]


def _four(home):
    """역설계를 마친 1~2화 뒤에 3~4화를 이은 실험."""
    lab = _parsed(home)
    revlab.append_text(lab, APPEND)
    revlab.save(lab)
    revlab.run_parse(lab.id, MockLLM(), [3, 4])
    return revlab.load(lab.id)


def test_edit_episode_clears_only_that_episode(home):
    lab = _parsed(home)
    revlab.run_write(lab.id, MockLLM(), 1)
    lab = revlab.load(lab.id)
    ep2, cast, lines = lab.episodes[1].model_dump(), len(lab.cast), len(lab.lines)
    assert revlab.edit_episode(lab, 1, " 새 제목 ", lab.episodes[0].text) is False  # 제목 줄만 바꾸면 결과는 그대로
    assert lab.episodes[0].head == "새 제목" and lab.episodes[0].sheet and lab.episodes[0].takes
    assert revlab.edit_episode(lab, 1, "새 제목", "고친 글이에요.\r\n" * 30) is True
    e = lab.episodes[0]
    assert (e.number, e.head, e.plot, e.sheet, e.takes, e.bounds) == (1, "새 제목", None, None, [], [])
    assert "\r" not in e.text and lab.episodes[1].model_dump() == ep2 and len(lab.cast) == cast and len(lab.lines) == lines
    assert revlab.edit_episode(lab, 2, "", "다시 고친 글 " * 30) is True
    assert revlab.edit_episode(lab, 2, "", "다시 고친 글 " * 30) is False  # 같은 글이면 아무것도 지우지 않는다
    with pytest.raises(ValueError, match="비었어요"):
        revlab.edit_episode(lab, 1, "", "  ")
    with pytest.raises(KeyError):
        revlab.edit_episode(lab, 9, "", "글")


def test_drop_episode_renumbers_later_ones(home):
    lab = _four(home)
    lab.lines[0].branch_ep, lab.lines[0].join_ep = 3, 4
    keep = [(e.text, e.plot.summary) for e in lab.episodes]
    revlab.drop_episode(lab, 2)
    assert [(e.number, e.plot.number) for e in lab.episodes] == [(1, 1), (2, 2), (3, 3)]
    assert [(e.text, e.plot.summary) for e in lab.episodes] == [keep[0], keep[2], keep[3]]  # 3 · 4화가 2 · 3화로 당겨진다
    assert (lab.lines[0].branch_ep, lab.lines[0].join_ep) == (2, 3)
    revlab.drop_episode(lab, 3)  # 마지막 화: 줄기가 가리키던 번호는 남은 마지막 화로
    assert [e.number for e in lab.episodes] == [1, 2] and lab.lines[0].join_ep == 2
    revlab.drop_episode(lab, 1)
    assert [e.number for e in lab.episodes] == [1] and lab.lines[0].branch_ep == 1
    with pytest.raises(ValueError, match="남은 화가 하나라"):
        revlab.drop_episode(lab, 1)


def test_web_edit_and_drop_episode(home, monkeypatch):
    from canon import web

    c = TestClient(web.app)
    lab_id = c.post("/api/revlab", json={"title": "등대", "text": STORY}).json()["id"]
    v = c.put(f"/api/revlab/{lab_id}/episodes/2", json={"head": "2화 고침", "text": "고친 둘째 화 " * 30}).json()
    assert v["items"][1]["head"] == "2화 고침" and v["items"][1]["text"].startswith("고친 둘째 화")
    assert c.put(f"/api/revlab/{lab_id}/episodes/2", json={"head": "", "text": " "}).status_code == 400
    assert c.put(f"/api/revlab/{lab_id}/episodes/9", json={"head": "", "text": "글"}).status_code == 400
    v = c.delete(f"/api/revlab/{lab_id}/episodes/1").json()
    assert [(e["number"], e["head"]) for e in v["items"]] == [(1, "2화 고침")]
    assert c.delete(f"/api/revlab/{lab_id}/episodes/1").status_code == 400
    assert c.delete(f"/api/revlab/99/episodes/1").status_code == 404
    busy = jobs.Job(id="x", project=revlab.JOBS, kind="rev_parse", ep=lab_id, label="역설계")
    monkeypatch.setattr(jobs, "listing", lambda project=None: [busy])
    r = c.put(f"/api/revlab/{lab_id}/episodes/1", json={"head": "", "text": "작업 중 고침 " * 30})
    assert r.status_code == 409 and "작업이 끝난 뒤" in r.text


@needs_node
def test_js_ai_text_and_made():
    done = lambda no, picked, seen, model, provider="claude", style=False: {"no": no, "model": model, "provider": provider, "style": style,
                                                                            "blind": {"state": "done", "picked": picked, "seen": seen}}
    items = [{"number": 1, "sheet": {}, "model": "gemini-4-argon",
              "takes": [done(1, "original", 0, "claude-opus-5-5"), done(2, "rewrite", 1, "claude-opus-5-5", style=True),
                        {"no": 3, "model": "gemini-4-argon", "provider": "gemini", "blind": {"state": "wait", "seen": 2}}]},
             {"number": 2, "sheet": {}, "model": "gemini-4-argon", "takes": [done(1, "rewrite", 0, "claude-opus-5-5")]},
             {"number": 3, "sheet": None, "model": "", "takes": []},
             {"number": 5, "sheet": {}, "model": "gemini-4-argon", "takes": [{"no": 1, "model": "", "blind": {"state": "none"}}]}]
    got = run_js(FILES, """({
      text: [revAiText({ provider: 'claude', model: 'claude-opus-5-5' }), revAiText({ provider: 'gemini', model: '', default: 'gemini-4-argon' }),
        revAiText({ provider: 'local', model: '', default: '' }), revAiText({ provider: 'mock', model: '' }), revAiText(null)],
      range: [revEpRange([3, 1, 2, 5, 7, 8]), revEpRange([4]), revEpRange([])],
      made: revAiMade(data, 'gemini-4-argon'),
    })""", items)
    assert got["text"] == ["claude-opus-5-5 · Claude 구독", "gemini-4-argon · Gemini", "로컬", "mock", ""]
    assert got["range"] == ["1~3 · 5 · 7~8화", "4화", ""]
    assert got["made"]["plan"] == [{"what": "1~2 · 5화 역설계", "model": "gemini-4-argon"}, {"what": "문체 프로필", "model": "gemini-4-argon"}]
    opus, gem = got["made"]["write"]  # 백엔드 · 모델마다 한 줄, 모델을 모르는 판은 뺀다
    assert (opus["provider"], opus["model"], opus["eps"], opus["n"], opus["style"]) == ("claude", "claude-opus-5-5", [1, 2], 3, 1)
    assert opus["picks"]["original"] == 1 and opus["picks"]["rewrite"] == 2 and opus["picks"]["first"] == {"original": 1, "rewrite": 1}
    assert gem["picks"]["wait"] == 1 and gem["n"] == 1
