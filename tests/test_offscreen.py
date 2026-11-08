"""화면 밖 근황(canon/offscreen.py): 공백 인물 고르기, 제안 정리 · 저장, 쓰기 · 다음 아크 기획 프롬프트, 다시 나온 화 반영 때 비우기,
응답 형식 · 저장 모양, 웹 라우트와 화면 (mock LLM). 실행: python -m pytest tests"""
import json
import re
from pathlib import Path

import pytest

from canon import context, offscreen, pipeline, prompts, web
from canon.mock_offscreen import MOCK_AWAY
from canon.schema import Character, CharacterState, OffscreenLine, OffscreenSet, StateDelta, StateDeltaAI

from .jsvm import dump, needs_node, run_js
from .test_named_cast import SMITH
from .test_serial import LLM, _plan_arc, _serial

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"
FILES = re.findall(r'src="/static/([a-z0-9-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


def _project():
    """1화부터 아크 끝까지 쓰고 반영한 장편. 대장장이는 2화 본문에만 나온다."""
    p = _serial()
    a = _plan_arc(p)
    p.characters.append(SMITH.model_copy())
    p.states.append(CharacterState(character_id="smith", location="북문 대장간", notes="왼손잡이"))
    for n in range(a.start_ep, a.end_ep + 1):
        e = p.episode(n)
        e.text, e.status, e.summary = f"{n}화 본문. 서윤은 길을 걸었다.", "finalized", f"{n}화 요약. 서윤이 길을 걸었다."
    p.episode(2).text = "마르타 부인이 검을 받았다."
    p.episode(2).summary = "서윤이 길을 떠났다. 마르타 부인이 서윤의 검을 맡아 두었다."
    assert a.end_ep + 1 - 2 >= context.RETURN_GAP
    return p, a


def test_targets_pick_long_absent_cast():
    p, a = _project()
    want, cut = offscreen.targets(p)
    assert want.get("smith") == 2 and cut == 0
    assert offscreen.start(p) == a.end_ep + 1
    assert "smith" not in offscreen.targets(p, 2 + context.RETURN_GAP - 1)[0]  # 공백이 짧으면 묻지 않는다
    p.characters[-1].context = "off"
    assert "smith" not in offscreen.targets(p)[0]  # '넣지 않음' 인물은 뺀다
    p.characters[-1].context = "auto"
    p.episode(a.end_ep).text = ""
    p.episode(a.end_ep).plot.characters.append("smith")
    assert "smith" not in offscreen.targets(p)[0]  # 이미 기획한 화(본문 없음)에 든 인물은 화면 밖이 아니다


def test_targets_cap_and_order():
    p, a = _project()
    for i in range(offscreen.OFFSCREEN_MAX + 2):
        p.characters.append(Character(id=f"m{i}", name=f"단역{i}호", role="", tier="minor"))
        p.episode(1).text += f" 단역{i}호가 지나갔다."
    want, cut = offscreen.targets(p)
    assert len(want) == offscreen.OFFSCREEN_MAX and cut >= 2
    assert list(want)[0] == "smith"  # 조연이 단역보다 먼저


def test_plan_clean_apply_and_prompts():
    p, a = _project()
    s = pipeline.plan_offscreen(LLM, p)
    assert [(x.character_id, x.text) for x in s.lines if x.character_id == "smith"] == [("smith", MOCK_AWAY)]
    assert "nobody" not in {x.character_id for x in s.lines}  # 묻지 않은 인물은 정리가 뺀다
    ask = prompts.offscreen_prompt(p, {"smith": 2})
    assert "마르타 부인 (smith" in ask and "북문 대장간" in ask and "2화 요약: 마르타 부인이 서윤의 검을 맡아 두었다." in ask
    assert offscreen.apply(p, OffscreenSet(lines=[x for x in s.lines if x.character_id == "smith"])) == 1
    st = p.state_of("smith")
    assert st.offscreen == MOCK_AWAY and st.offscreen_ep == a.end_ep and st.notes == "왼손잡이"
    n = a.end_ep + 1
    rows = prompts.return_lines(p, {"smith"}, n)
    assert rows == [f"- 마르타 부인: 마지막으로 나온 화 2화 ({n - 2}화 전). 2화 요약: 마르타 부인이 서윤의 검을 맡아 두었다. "
                    f"화면 밖 근황 ({a.end_ep}화 끝 시점, 작가가 정함): {MOCK_AWAY}"]
    assert "적힌 화 끝 시점의 것입니다" in prompts.return_block(p, {"smith"}, n)
    plan = prompts.next_arc_prompt(p, n, 0, "")
    assert f"- 마르타 부인 (smith, {a.end_ep}화 끝 시점): {MOCK_AWAY}" in plan and "그 근황에서 이어지게" in plan
    assert plan.index("[오래 나오지 않은 인물의 화면 밖 근황") > plan.index("[조연 · 최근 인물 현재 상태")
    assert "offscreen" not in prompts.dump(p.states)  # 상태 칸 직렬화에는 근황 칸이 없다


def test_no_offscreen_keeps_prompts():
    p, a = _project()
    n = a.end_ep + 1
    assert "화면 밖 근황" not in prompts.return_block(p, {"smith"}, n)
    plan = prompts.next_arc_prompt(p, n, 0, "")
    assert "화면 밖 근황" not in plan
    assert "offscreen" not in json.loads(p.model_dump_json())["states"][-1]  # 빈 근황은 저장하지 않는다


def test_listed_cap_note():
    p, a = _project()
    for i in range(offscreen.OFFSCREEN_MAX + 1):
        p.characters.append(Character(id=f"m{i}", name=f"단역{i}호", role="", tier="minor"))
        p.states.append(CharacterState(character_id=f"m{i}", offscreen=f"근황 {i}", offscreen_ep=i))
    rows, cut = offscreen.listed(p)
    assert len(rows) == offscreen.OFFSCREEN_MAX and cut == 1 and rows[0].character_id == f"m{offscreen.OFFSCREEN_MAX}"
    assert "(그 밖에 1명은 뺐습니다)" in prompts.offscreen_block(p)


def test_reappearance_clears_and_absence_keeps():
    p, a = _project()
    offscreen.apply(p, OffscreenSet(lines=[OffscreenLine(character_id="smith", text="대장간을 지켰다")]))
    pipeline.apply_delta(p, StateDelta(episode=5, summary="5화 요약"))
    assert p.state_of("smith").offscreen == "대장간을 지켰다"  # 나오지 않은 화는 그대로
    p.episode(6).text = "마르타 부인이 돌아왔다."
    pipeline.apply_delta(p, StateDelta(episode=6, summary="6화 요약"))
    st = p.state_of("smith")
    assert st.offscreen == "" and st.offscreen_ep == 0


def test_revert_drops_offscreen_saved_after_snapshot():
    p = _serial()
    a = _plan_arc(p)
    for n in range(a.start_ep, a.end_ep + 1):
        p.episode(n).text = f"{n}화 본문"
        pipeline.apply_delta(p, StateDelta(episode=n, summary=f"{n}화 요약"))
    offscreen.apply(p, OffscreenSet(lines=[OffscreenLine(character_id="hero", text="근황")]))
    pipeline.revert(p, a.end_ep - 1)  # 스냅샷은 근황을 저장하기 전 상태다
    assert p.state_of("hero").offscreen == ""


def test_short_and_empty_raise():
    p, a = _project()
    p.meta.form = "short"
    with pytest.raises(ValueError, match="장편"):
        pipeline.plan_offscreen(LLM, p)
    q = _serial()
    _plan_arc(q)
    with pytest.raises(ValueError, match="나오지 않은 인물이 없어요"):
        pipeline.plan_offscreen(LLM, q)


def test_response_schemas_skip_offscreen():
    for m in (StateDelta, StateDeltaAI):
        assert "offscreen" not in json.dumps(m.model_json_schema(), ensure_ascii=False)


def test_job_maker_and_web_routes(client):  # noqa: F811
    from canon import store as st

    assert web.JOB_MAKERS["offscreen"].__name__ == "_job_offscreen" and "offscreen" in web.PENDING_KINDS
    p, a = _project()
    st.save("ofs", p)
    body = {"lines": [{"character_id": "smith", "text": " 대장간을 지켰다 ", "kind": "daily"}]}
    out = client.post("/api/projects/ofs/offscreen", json=body).json()
    smith = next(s for s in out["states"] if s["character_id"] == "smith")
    assert smith["offscreen"] == "대장간을 지켰다" and smith["offscreen_ep"] == a.end_ep
    out = client.delete("/api/projects/ofs/offscreen/smith").json()
    assert "offscreen" not in next(s for s in out["states"] if s["character_id"] == "smith")
    assert client.delete("/api/projects/ofs/offscreen/smith").status_code == 400
    assert client.post("/api/projects/ofs/offscreen", json={"lines": []}).status_code == 400


def test_js_gap_matches_context():
    src = (STATIC / "offscreen.js").read_text(encoding="utf-8")
    assert int(re.search(r"const RETURN_GAP = (\d+);", src).group(1)) == context.RETURN_GAP


@needs_node
def test_next_arc_panel_shows_saved_and_draft():
    p, a = _project()
    offscreen.apply(p, OffscreenSet(lines=[OffscreenLine(character_id="smith", text="대장간을 지켰다")]))
    got = run_js(FILES, """(() => {
      S.project = data; S.name = 't';
      const saved = nextArcPanel(data.story_arcs[0].end_ep + 1);
      S.offscreenDraft = { lines: [{ character_id: 'smith', text: '새 근황', kind: 'hook', on: true }, { character_id: 'hero', text: '  ', kind: 'daily', on: true }] };
      const draft = nextArcPanel(data.story_arcs[0].end_ep + 1);
      return { saved, draft, picked: offscreenPicked(S.offscreenDraft) };
    })()""", dump(p))
    assert "화면 밖 근황" in got["saved"] and f"{a.end_ep}화 끝 시점" in got["saved"] and "대장간을 지켰다" in got["saved"]
    assert 'data-action="clearOffscreen" data-arg="smith"' in got["saved"] and 'data-action="planOffscreen"' in got["saved"]
    assert "복귀 고리" in got["draft"] and 'data-action="applyOffscreen"' in got["draft"]
    assert got["picked"] == {"lines": [{"character_id": "smith", "text": "새 근황", "kind": "hook"}]}  # 빈 근황은 보내지 않는다
