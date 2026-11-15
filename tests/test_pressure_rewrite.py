"""압력으로 다시 쓰기 제안(웹소설 일감 11b, docs/webnovel/specs/11-pressure.md): 글 계산 · 응답 정리 · 프롬프트 · 작업 · 기록 · 화면 카드."""
from __future__ import annotations

from pathlib import Path

from canon import pipeline, prompts, store
from canon import pressure as pr
from canon.mock import MockLLM
from canon.schema import Character, PressureProposal, PressureRewrite, Project

from .jsvm import needs_node, run_js
from .test_ai_jobs import FILES, _run, _saved
from .test_plot_chat import _project
from .test_storylines import _short
from .test_timeline import _play

L = MockLLM()


def _cut_lines(text: str) -> str:
    return pr.cut(text, pr.lines(text))


def _proj(**kw) -> Project:
    p = Project()
    p.meta.title = "등대"
    p.characters = [Character(id="hero", name="서윤", role="주인공", **kw)]
    return p


def test_lines_finds_examples_but_not_habit_or_title():
    a = '말버릇 "글쎄다"를 자주 쓴다. 예: "됐어."'
    assert [a[x:y] for x, y in pr.lines(a)] == ['"됐어."']
    b = "상대를 '선배'라고 부른다. \"뭐 해요?\""
    assert [b[x:y] for x, y in pr.lines(b)] == ['"뭐 해요?"']
    assert pr.lines("짧은 반말. 말끝을 흐린다.") == [] and pr.lines("") == []


def test_cut_examples():
    assert _cut_lines('짧은 반말. 상대를 성으로 부르고 질문에 질문으로 답한다. 예: "그걸 왜 나한테 물어?"') == "짧은 반말. 상대를 성으로 부르고 질문에 질문으로 답한다."
    assert _cut_lines('빠른 말투. "얼른 와."') == "빠른 말투."
    assert _cut_lines('느긋한 존댓말. "천천히 해요." 끝을 흐린다.') == "느긋한 존댓말. 끝을 흐린다."
    assert _cut_lines('짧은 반말("뭘 봐.", "됐어.")') == "짧은 반말"
    t = "말수가 적다. 화나면 손톱을 깨문다. 셈이 빠르다."
    a = t.index("화나면")
    assert pr.cut(t, [(a, a + len("화나면 손톱을 깨문다."))]) == "말수가 적다. 셈이 빠르다."
    assert pr.cut(" 그대로  둔다 ", []) == " 그대로  둔다 "


def test_proposal_drops_unfound_habits_and_keeps_before():
    c = Character(id="hero", name="서윤", role="주인공", personality="말수가 적다. 화나면 손톱을 깨문다. 셈이 빠르다.",
                  speech_style='짧은 반말. "됐어."', pressure="옛 압력")
    s = PressureRewrite(pressure=" 새 압력 ", habits=["화나면 손톱을 깨문다.", "없는 문장이다.", "화나면 손톱을"], note=" 근거 ")
    out = pr.proposal(c, s)
    assert out.habits == ["화나면 손톱을 깨문다."] and out.dropped == 1  # 겹친 셋째는 하나만 쓴다
    assert out.personality == "말수가 적다. 셈이 빠르다." and out.personality_before == c.personality
    assert out.speech_style == "짧은 반말." and out.speech_before == c.speech_style and out.lines == ['"됐어."']
    assert (out.pressure, out.pressure_before, out.note) == ("새 압력", "옛 압력", "근거")
    none = pr.proposal(c, PressureRewrite(habits=["없는 문장이다."]))
    assert none.personality == c.personality and none.dropped == 1 and none.pressure == ""


def test_schemas_have_no_dict_fields():
    for model in (PressureRewrite, PressureProposal):
        assert "additionalProperties" not in str(model.model_json_schema()), model.__name__


def test_suggest_pressure_does_not_change_project():
    p = _proj(personality="말수가 적다. 화나면 손톱을 깨문다.", speech_style='짧은 반말. "됐어."')
    before = p.model_dump()
    out = pipeline.suggest_pressure(L, p, "hero")
    assert p.model_dump() == before
    assert out.habits == ["화나면 손톱을 깨문다."] and out.lines == ['"됐어."']
    assert out.personality == "말수가 적다." and out.speech_style == "짧은 반말." and out.pressure
    try:
        pipeline.suggest_pressure(L, p, "nobody")
        raise AssertionError("없는 인물인데 통과했어요")
    except KeyError:
        pass


def test_prompt_text():
    p = _proj(personality="말수가 적다.", speech_style='짧은 반말. "됐어."')
    t = prompts.pressure_prompt(p, "hero")
    assert "무엇을 지키려 하는지, 흔들리면 어디로 가는지" in t and "글자 그대로" in t
    assert "뜻을 살려" not in t and '말투의 대사 예시: "됐어."' in t
    p.characters[0].pressure = "문을 지킨다."
    t = prompts.pressure_prompt(p, "hero")
    assert "문을 지킨다." in t and "뜻을 살려" in t
    assert "말투에 대사 예시 없음" in prompts.pressure_prompt(_proj(speech_style="짧은 반말."), "hero")


def test_job_returns_proposal_and_logs_author_edits(client):
    _project(client)
    before = _saved("lh")
    j = _run(client, "lh", {"kind": "char_pressure", "target": "ally"})
    assert j["target"] == "ally" and "pressure" in j["result"] and "dropped" in j["result"]
    assert _saved("lh") == before

    p = _play(_short(8), 1, 1)  # 1화를 반영한 작품
    c = p.characters[0]
    c.personality, c.speech_style = "말수가 적다. 화나면 손톱을 깨문다.", '짧은 반말. "됐어."'
    store.save("lh", p)
    out = _run(client, "lh", {"kind": "char_pressure", "target": c.id})["result"]
    assert out["habits"] and out["lines"]
    disk = client.get("/api/projects/lh").json()
    me = disk["characters"][0]
    me["pressure"], me["personality"], me["speech_style"] = out["pressure"], out["personality"], out["speech_style"]
    saved = client.put("/api/projects/lh", json=disk).json()
    got = {r["field"]: r["source"] for r in saved["setting_log"] if r["character_id"] == c.id}
    assert got == {"personality": "author", "speech_style": "author", "pressure": "author"}


def test_auto_and_cli_do_not_call_it():
    root = Path(pipeline.__file__).parent
    for f in ("autorun.py", "cli.py"):
        text = (root / f).read_text(encoding="utf-8")
        assert "suggest_pressure" not in text and "char_pressure" not in text, f


@needs_node
def test_js_card_has_no_checked_and_disables_edited_rows():
    sug = {"pressure": "새 압력", "pressure_before": "", "personality": "말수가 적다.", "personality_before": "말수가 적다. 손톱을 깨문다.",
           "habits": ["손톱을 깨문다."], "speech_style": "짧은 반말.", "speech_before": '짧은 반말. "됐어."', "lines": ['"됐어."'],
           "dropped": 2, "note": "근거"}
    c = {"id": "hero", "pressure": "", "personality": "작가가 그 사이 고침", "speech_style": '짧은 반말. "됐어."'}
    got = run_js(FILES, """(() => {
      S.pressureSug = { hero: data.sug };
      const html = castPressureCard(data.c);
      return [html, castPressureCan(data.c), castPressureCan({ personality: '', speech_style: '짧은 반말.' }), (S.pressureSug.x = null, castPressureCard({ id: 'x' }))];
    })()""", {"sug": sug, "c": c})
    html = got[0]
    assert "checked" not in html and "그 뒤 고친 칸이라 적용하지 않아요" in html and "2개는 성격 칸에서 찾지 못해 뺐어요" in html
    boxes = [x for x in html.split("<input")[1:]]
    flags = {("pressure" if 'value="pressure"' in b else "personality" if 'value="personality"' in b else "speech_style"): " disabled" in b.split(">")[0] for b in boxes}
    assert flags == {"pressure": False, "personality": True, "speech_style": False}
    assert got[1] is True and got[2] is False and got[3] == ""
