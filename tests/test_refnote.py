"""참고 메모 (canon/refnote.py): 레퍼런스 원고에서 설정 메모를 만들어 작가가 넣으면 설정 도우미 프롬프트에 [참고 구조] 로 들어간다.
원고는 tests/fixtures/refs_story.txt (직접 지은 글)."""
import re
import time
from pathlib import Path

import pytest

from canon import context, pipeline, prompts, refdigest, refnote, refs, store
from canon.llm import get_llm
from canon.schema import Meta, Project, RefCut, RefNote, RefSetupDraft

from .jsvm import STATIC, needs_node, run_js

STORY = (Path(__file__).parent / "fixtures" / "refs_story.txt").read_text(encoding="utf-8")
JS_FILES = re.findall(r'src="/static/([a-z0-9-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


def _book():
    d = refs.preview(STORY, repeats=[])
    cuts = [RefCut(**{k: c[k] for k in ("line", "body", "head", "label", "title", "kind")}) for c in d["cuts"] if c["on"]]
    return refs.create("등대", STORY, cuts, rights=True)


def _work(name="work"):
    store.save(name, Project(meta=Meta(title="내 작품", logline="한 줄")))
    return name


def _wait(client, j):
    end = time.time() + 10
    while time.time() < end:
        cur = next(x for x in client.get("/api/jobs").json() if x["id"] == j["id"])
        if cur["status"] != "running":
            return cur
        time.sleep(0.02)
    raise AssertionError("작업이 끝나지 않았어요")


def test_material_sends_raw_text_until_every_picked_episode_has_a_card(client, monkeypatch):
    b = _book()
    m = refnote.material(b.id, [1, 2, 3])
    assert m["mode"] == "text" and m["sent"] == 3 and m["body"].startswith("## 프롤로그\n") and not m["folded"]
    # 상한을 넘으면 앞 화부터 채우고 넘는 화부터는 보내지 않는다. 첫 화는 잘라서라도 보낸다
    monkeypatch.setattr(refnote, "SETUP_NOTE_MAX", 700)
    m = refnote.material(b.id, [1, 2, 3])
    assert m["sent"] == 2 and "## 2화" not in m["body"] and len(m["body"]) <= 700
    monkeypatch.setattr(refnote, "SETUP_NOTE_MAX", 100)
    m = refnote.material(b.id, [1, 2, 3])
    assert m["sent"] == 1 and len(m["body"]) <= 100
    monkeypatch.setattr(refnote, "SETUP_NOTE_MAX", 30_000)
    # 고른 화가 모두 읽혀 있으면 원문 대신 화 카드를 보낸다
    refdigest.run(b.id, refdigest.llm_for(b.id))
    m = refnote.material(b.id, [1, 2, 3])
    assert m["mode"] == "cards" and "## 1번 · 프롤로그" in m["body"] and "사건: " in m["body"] and m["names"] == ["서윤"]
    assert STORY.split("\n")[3] not in m["body"] or "(가짜)" in m["body"]
    # 예산을 넘으면 화마다 줄이고 줄였다고 적는다
    monkeypatch.setattr(refnote, "NOTE_DIGEST_BUDGET", 300)
    m = refnote.material(b.id, [1, 2, 3])
    assert m["folded"] and "화마다 첫 사건" in m["fold"] and "사건: " not in m["body"]
    est = refnote.estimate(b.id, [1, 2, 3])
    assert est["mode"] == "cards" and est["folded"] and est["usd"] == 0.0 and est["provider"] == "mock"
    with pytest.raises(ValueError, match="고른 화가 없어요"):
        refnote.material(b.id, [99])


def test_prompt_tells_the_model_to_keep_names_and_plot_out():
    cards = prompts.ref_setup_note_prompt("## 1번 · 1화 [대화 · 긴장 3]\n사건: 서윤이 등대에 올랐다", "cards", ["서윤"], "")
    assert "이름 대신 역할로" in cards and "사건 줄거리와 반전" in cards and "원문 문장. 한 구절도" in cards
    assert "세부(누가 했는지, 차례)가 틀릴 수 있습니다" in cards and "여러 화에 걸쳐 되풀이되는 구도" in cards
    assert "# 화 카드의 인물 이름 (메모에 쓰지 않습니다)\n서윤" in cards and cards.rstrip().endswith("사건: 서윤이 등대에 올랐다")
    text = prompts.ref_setup_note_prompt("원문 글", "text")
    assert "# 원문\n원문 글" in text and "화 카드" not in text and "이름 대신 역할로" in text


def test_text_of_joins_labelled_lines_and_skips_empty_fields():
    d = RefSetupDraft(logline_shape=" 몰락한 가문의 장남이  복수한다 ", world_rules=["힘에 대가가 있다", " "], cast=[], relations=["삼각 구도"], conflict="", tone="건조함")
    assert refnote.text_of(d) == "로그라인 꼴: 몰락한 가문의 장남이 복수한다\n세계 규칙:\n- 힘에 대가가 있다\n관계 구도:\n- 삼각 구도\n톤: 건조함"


def test_overlap_marks_quotes_and_names():
    src = ["서윤은 계단을 올랐다. 꼭대기 문은 반쯤 열려 있었고 바람이 기름 냄새를 실어 날랐다.", "도현이 속삭였다."]
    note = "인물 배치:\n- 꼭대기 문은 반쯤 열려 있었고 바람이 기름 냄새를 맡는 관찰자\n- 서윤을 돕는 조력자"
    marks = refs.overlap(note, src, ["서윤", "도현", "가"])
    quote = next(m for m in marks if m["kind"] == "quote")
    assert quote["text"] == "꼭대기 문은 반쯤 열려 있었고 바람이 기름 냄새를" and note[quote["start"]:quote["end"]] == quote["text"]
    assert [m["text"] for m in marks if m["kind"] == "name"] == ["서윤"]
    assert refs.overlap("주인공을 시험하는 스승형 조력자", src, ["서윤"]) == []
    assert refs.overlap("짧게 겹침: 서윤은 계단을 올랐다.", src) == []  # 20자가 안 되는 겹침은 표시하지 않는다


def test_card_cast_words_that_are_titles_are_not_names():
    words = ["강주혁", "하은", "매니저", "이사님", "언니", "코디 언니", "편의점 알바", "서술자", "나카자와 히나미", "점원", "가"]
    assert [w for w in words if refnote.is_name(w)] == ["강주혁", "하은", "나카자와 히나미"]


def test_proper_words_guesses_frequent_names_without_ai():
    eps = ["서윤은 걸었다. 서윤이 웃었다. 서윤을 불렀다. 그녀는 갔다. 그녀는 왔다. 그녀는 섰다.", "서윤은 봤다. 서윤의 손. 서윤과 함께. 도현이 왔다.", "아무도 없었다."]
    assert refs.proper_words(eps) == ["서윤"]


def test_note_job_returns_a_preview_and_saves_nothing(client, monkeypatch):
    b = _book()
    name = _work()
    refdigest.run(b.id, refdigest.llm_for(b.id))
    est = client.post(f"/api/refs/{b.id}/note/estimate", json={"eps": [1, 2, 3]}).json()
    assert est["mode"] == "cards" and est["sent"] == 3
    j = client.post(f"/api/refs/{b.id}/note", json={"eps": [1, 2, 3], "project": name}).json()
    assert j["kind"] == "ref_note" and j["target"] == b.id
    r = _wait(client, j)["result"]
    assert r["mode"] == "cards" and r["project"] == name and r["from_name"] == "등대" and r["kind"] == "setup" and r["use"] == "setup"
    assert r["text"].startswith("로그라인 꼴: (가짜)") and "인물 배치:\n- " in r["text"] and r["marks"] == [] and "화 카드로 만듦" in r["text"]
    assert store.load(name).ref_notes == [] and refs.load(b.id).made == []  # 넣기를 누르기 전에는 아무것도 저장하지 않는다
    assert client.post(f"/api/refs/{b.id}/note", json={"eps": [99], "project": name}).status_code == 400
    assert client.post(f"/api/refs/{b.id}/note", json={"eps": [1], "project": "없는작품"}).status_code == 404
    # 초안에 원고의 이름과 원문 구절이 들면 표시한다 (넣기를 막지는 않는다)
    leak = RefSetupDraft(logline_shape="서윤이 진실을 찾는다", world_rules=[], cast=[], relations=[], conflict=refs.pick(refs.load(b.id), [2])[0]["text"][:40].replace("\n", " "), tone="")
    monkeypatch.setattr(pipeline, "ref_setup_note", lambda *a, **k: leak)
    r = refnote.run(b.id, [1, 2, 3], get_llm("plan"))
    assert {m["kind"] for m in r["marks"]} == {"name", "quote"}
    again = client.post(f"/api/refs/{b.id}/note/marks", json={"eps": [1, 2, 3], "text": "진실을 좇는 외지인"}).json()
    assert again == {"marks": []}


def test_author_adds_edits_and_removes_a_note(client):
    b = _book()
    name = _work()
    url = f"/api/projects/{name}/ref-notes"
    assert client.get(url).json() == {"notes": [], "dropped": [], "budget": 4000, "max": 2000, "budgets": {"setup": 4000, "write": 3000, "plot": 3000}}
    v = client.post(url, json={"text": " 세계 규칙:\n- 힘에 대가가 있다 ", "ref": b.id, "from_name": "등대", "from_eps": "1~3화"}).json()
    note = v["notes"][0]
    assert note["text"] == "세계 규칙:\n- 힘에 대가가 있다" and note["on"] and note["kind"] == "setup" and note["use"] == "setup" and v["id"] == note["id"]
    made = refs.load(b.id).made
    assert [(m.kind, m.id, m.eps) for m in made] == [("note", f"{name}/{note['id']}", "1~3화")]
    assert client.post(url, json={"text": " "}).status_code == 400
    assert client.post(url, json={"text": "가" * 2001}).status_code == 400
    assert client.post(url, json={"text": "박자", "kind": "beats", "use": "setup"}).status_code == 400  # 박자 메모는 집필 · 플롯 초안에만
    assert client.post(url, json={"text": "구도", "kind": "setup", "use": "write"}).status_code == 400
    v = client.put(f"{url}/{note['id']}", json={"on": False}).json()
    assert not v["notes"][0]["on"] and v["notes"][0]["text"] == note["text"]
    v = client.put(f"{url}/{note['id']}", json={"text": "고친 글"}).json()
    assert v["notes"][0]["text"] == "고친 글" and not v["notes"][0]["on"]
    assert client.put(f"{url}/없음", json={"on": True}).status_code == 404
    # 작품 화면이 통째로 저장해도 참고 메모는 그대로다 (메모는 이 주소로만 바뀐다)
    p = client.get(f"/api/projects/{name}").json()
    p["ref_notes"] = []
    p["meta"]["title"] = "바꾼 제목"
    assert client.put(f"/api/projects/{name}", json=p).status_code == 200
    q = store.load(name)
    assert q.meta.title == "바꾼 제목" and [n.text for n in q.ref_notes] == ["고친 글"]
    assert client.delete(f"{url}/{note['id']}").json()["notes"] == []
    assert client.delete(f"{url}/{note['id']}").status_code == 404


def _note(i, text, on=True, use="setup"):
    return RefNote(id=f"n{i}", from_name="등대", from_eps=f"{i}화", text=text, on=on, use=use)


def _beat(i, text, use="write", on=True):
    return RefNote(id=f"b{i}", from_name="등대", from_eps=f"{i}화", kind="beats", text=text, on=on, use=use)


def test_setup_prompts_are_unchanged_without_notes_and_start_with_the_block_with_them(monkeypatch):
    from canon import naming

    monkeypatch.setattr(naming, "prompt_block", lambda p: "(이름 후보)")  # 후보는 부를 때마다 다르게 뽑힌다
    p = Project(meta=Meta(title="내 작품", logline="한 줄"))
    chat, sug = prompts.setup_chat_prompt(p, "다듬어 줘"), prompts.setup_prompt(p)
    assert chat.startswith("[작품]\n") and sug.startswith("아래는 작가가 입력한 기본 설정입니다.") and "참고 구조" not in chat + sug
    off = p.model_copy(update={"ref_notes": [_note(1, "꺼 둔 메모", on=False), _note(2, "집필용", use="write"), _note(3, " ")]})
    assert prompts.setup_chat_prompt(off, "다듬어 줘") == chat and prompts.setup_prompt(off) == sug  # 켠 설정 메모가 없으면 글자 하나 다르지 않다
    on = p.model_copy(update={"ref_notes": [_note(1, "세계 규칙:\n- 힘에 대가가 있다"), _note(2, "꺼 둠", on=False)]})
    block = prompts.ref_notes_block(on)
    assert block.startswith("[참고 구조]\n(참고 구조는 다른 작품의 구도입니다. 이름 · 지명 · 사건 · 고유 설정을 옮기지 않습니다.")
    assert "## 등대 1화\n세계 규칙:\n- 힘에 대가가 있다" in block and "꺼 둠" not in block and "뺐어요" not in block and block.endswith("\n\n")
    assert prompts.setup_chat_prompt(on, "다듬어 줘") == block + chat and prompts.setup_prompt(on) == block + sug  # 바뀌지 않는 블록이라 맨 앞
    assert prompts.setup_chat_prompt(on, "방향", "options").startswith(block)


def test_notes_over_the_budget_are_dropped_and_counted():
    p = Project(ref_notes=[_note(1, "가" * 1900), _note(2, "나" * 1900), _note(3, "다" * 1900), _note(4, "라" * 100)])
    block = prompts.ref_notes_block(p)
    assert "가" * 1900 in block and "나" * 1900 in block and "다다다" not in block and "라" * 100 in block  # 넣은 차례대로, 넘는 메모만 뺀다
    assert block.rstrip().endswith("(참고 메모 1개는 길어서 뺐어요)") and len(block) <= context.BUDGET["ref_notes"] + 300
    assert refnote.dropped(p) == ["n3"] and refnote.view(p)["dropped"] == ["n3"]


@needs_node
def test_js_dropped_notes_and_preview_lines_match_python():
    p = Project(ref_notes=[_note(1, "가" * 1900), _note(2, "나" * 1900, on=False), _note(3, "다" * 1900), _note(4, "라" * 1900), _note(5, "마" * 100),
                           _beat(6, "바" * 1900), _beat(7, "사" * 1900), _beat(8, "아" * 1900, "plot")])
    notes = [n.model_dump() for n in p.ref_notes]
    budgets = {use: context.BUDGET[key] for use, key in prompts.REF_NOTE_BUDGET.items()}
    assert run_js(JS_FILES, "[refNotesDropped(data), REF_NOTES_BUDGET, REF_NOTE_MAX]", notes) == [refnote.dropped(p), budgets, refnote.NOTE_MAX]
    got = run_js(JS_FILES, "[refNoteSent(data.a), refNoteSent(data.b), refNoteSent(data.c), refNoteWarn(data.m), refMadeHref({kind: 'note', id: '내 작품/n1'})]",
                 {"a": {"mode": "cards", "sent": 30, "episodes": 30, "folded": False}, "b": {"mode": "cards", "sent": 222, "episodes": 222, "folded": True},
                  "c": {"mode": "text", "sent": 6, "episodes": 30}, "m": [{"kind": "name", "text": "서윤"}, {"kind": "name", "text": "서윤"}, {"kind": "quote", "text": "긴 구절"}]})
    assert got[0] == "화 카드 30화를 보내요. 원문은 보내지 않아요." and "화마다 첫 사건과 끝만" in got[1] and got[2] == "읽히지 않은 화가 있어 원문을 보내요 (길어서 앞 6화까지만)."
    assert got[3] == ["원문 문장이 들어 있어요: ‘긴 구절’", "원고의 이름이 들어 있어요: 서윤"] and got[4] == "#/p/%EB%82%B4%20%EC%9E%91%ED%92%88/setup"


def test_old_project_without_ref_notes_still_loads():
    raw = Project(meta=Meta(title="옛 작품")).model_dump()
    raw.pop("ref_notes")
    assert Project.model_validate(raw).ref_notes == []


def test_setup_chat_brief_carries_the_block_and_episode_brief_does_not(client):
    from canon import promptlab

    name = _work()
    client.post(f"/api/projects/{name}/ref-notes", json={"text": "세계 규칙:\n- 힘에 대가가 있다", "from_name": "등대", "from_eps": "1~3화"})
    s = promptlab.load_prompt(promptlab.create(), "setup_chat", name)
    assert "[참고 구조]\n" in s.prompt and "## 등대 1~3화\n세계 규칙:" in s.prompt and s.prompt.index("[참고 구조]") < s.prompt.index("[작품]")  # 작업지시서 · 조립 보기도 같은 프롬프트
    from canon.schema import Episode, EpisodePlot

    p = store.load(name)
    p.episodes = [Episode(plot=EpisodePlot(number=1, act="기", title="첫 화", summary="등대에 오른다", events=["계단을 오른다"], characters=[], emotional_shift="망설임에서 결심으로", ending_hook="문이 열려 있다"))]
    q = p.model_copy(update={"ref_notes": []})
    for fn in (prompts.episode_brief, prompts.check_brief, prompts.state_brief):  # 설정 메모는 집필 · 검수 · 상태 요청에 들어가지 않는다
        assert "참고 구조" not in fn(p, 1) and fn(p, 1) == fn(q, 1)


# ---------- 박자 메모 (쓰임 집필 · 플롯 초안) ----------

def _story(serial=False):
    """본문 쓰기 요청을 조립할 수 있는 작은 작품 (2화까지 플롯, 1화 본문)."""
    from canon.schema import Act, Character, Episode, EpisodePlot, StoryArc

    plot = lambda n: EpisodePlot(number=n, act="기", title=f"{n}화", summary="등대에 오른다", events=["계단을 오른다"], characters=["a"],  # noqa: E731
                                 emotional_shift="망설임에서 결심으로", ending_hook="문이 열려 있다")
    p = Project(meta=Meta(title="내 작품", logline="한 줄", target_episodes=10, form="serial" if serial else "short"),
                characters=[Character(id="a", name="가람", role="주인공")],
                arc=[Act(name=k, start_ep=s, end_ep=e, goal="목표") for k, s, e in (("기", 1, 2), ("승", 3, 5), ("전", 6, 8), ("결", 9, 10))],
                episodes=[Episode(plot=plot(1), text="첫 화 본문.", status="finalized"), Episode(plot=plot(2))])
    if serial:
        from canon.schema import Part
        p.parts = [Part(number=1, title="1부", start_ep=1, end_ep=10, goal="목표")]
        p.story_arcs = [StoryArc(number=1, title="첫 아크", start_ep=1, end_ep=10, goal="목표", acts=p.arc)]
    return p


@pytest.fixture
def fixed_names(monkeypatch):
    from canon import naming

    monkeypatch.setattr(naming, "prompt_block", lambda p: "(이름 후보)")  # 후보는 부를 때마다 다르게 뽑힌다
    monkeypatch.setattr(naming, "new_cast_hint", lambda *a, **k: "(새 인물 이름 후보)")


@pytest.mark.parametrize("serial", [False, True])
def test_write_and_plot_requests_are_unchanged_without_beat_notes(serial, fixed_names):
    p = _story(serial)
    base = {"write": prompts.build_episode_context(p, 2, write=True), "brief": prompts.episode_brief(p, 2), "check": prompts.check_brief(p, 1),
            "plot": (prompts.serial_plot_prompt if serial else prompts.plot_prompt)(p, 3, 5)}
    off = p.model_copy(update={"ref_notes": [_beat(1, "꺼 둔 박자", on=False), _note(2, "설정 메모"), _beat(3, " ")]})
    got = {"write": prompts.build_episode_context(off, 2, write=True), "brief": prompts.episode_brief(off, 2), "check": prompts.check_brief(off, 1),
           "plot": (prompts.serial_plot_prompt if serial else prompts.plot_prompt)(off, 3, 5)}
    assert got == base and "참고 구조" not in "".join(base.values())  # 켠 박자 메모가 없으면 단편 · 장편 모두 글자 하나 다르지 않다


@pytest.mark.parametrize("serial", [False, True])
def test_beat_notes_go_after_the_static_context_and_before_episode_blocks(serial):
    p = _story(serial)
    p.ref_notes = [_beat(1, "박자:\n- 낯선 흔적으로 연다"), _beat(2, "플롯용 박자", "plot"), _note(3, "설정 메모")]
    ctx = prompts.build_episode_context(p, 2, write=True)
    block = "\n\n# 참고 구조 (작가가 넣은 참고 메모)\n" + prompts.REF_BEATS_RULE + "\n## 등대 1화\n박자:\n- 낯선 흔적으로 연다"
    assert ctx.startswith(prompts.static_context(p) + block) and "플롯용 박자" not in ctx and "설정 메모" not in ctx  # 바뀌지 않는 블록 바로 뒤
    assert ctx.index("# 참고 구조") < ctx.index("# 확정된 사실") < ctx.index("# 이번 화 플롯")
    assert block in prompts.episode_brief(p, 2)  # 작업지시서도 같은 프롬프트
    assert "참고 구조" not in prompts.check_brief(p, 1) and "참고 구조" not in prompts.state_brief(p, 1)  # 검수 · 상태 변경안에는 넣지 않는다
    plot = (prompts.serial_plot_prompt if serial else prompts.plot_prompt)(p, 3, 5)
    assert "화별 플롯을 작성하세요.\n\n[참고 구조]\n(" + prompts.REF_BEATS_RULE + ")\n## 등대 2화\n플롯용 박자\n\n[작품]\n" in plot and "낯선 흔적" not in plot
    parts = prompts.context_parts(p, 2, write=True)
    assert [x.id for x in parts].index("ref_notes") == [x.id for x in parts].index("characters") + 1


def test_beat_notes_over_the_budget_are_dropped_and_traced():
    from canon import context as ctx

    p = _story(True)
    p.ref_notes = [_beat(1, "가" * 1900), _beat(2, "나" * 1900), _beat(3, "라" * 100)]
    trace = ctx.Trace()
    text = prompts.join_parts(prompts.context_parts(p, 2, write=True, trace=trace))
    assert "가" * 1900 in text and "나" * 1900 not in text and "라" * 100 in text and "(참고 메모 1개는 길어서 뺐어요)" in text
    assert [x[0] for x in trace.items["ref_notes"]] == ["등대 1화", "등대 3화"] and trace.dropped["ref_notes"] == [("등대 2화", ctx.DROP_BUDGET)]
    assert refnote.dropped(p) == ["b2"]
    # 글이 같은 메모 둘 가운데 뒤 것만 빠져도 차례로 가린다
    same = Project(ref_notes=[RefNote(id="x1", from_name="등대", from_eps="1화", kind="beats", use="write", text="가" * 1900),
                              RefNote(id="x2", from_name="등대", from_eps="1화", kind="beats", use="write", text="가" * 1900)])
    used, kept, cut = prompts.ref_notes_fit(same, "write")
    assert [n.id for n in used] == ["x1"] and len(kept) == 1 and cut == 1 and refnote.dropped(same) == ["x2"]
    # 장편은 작품 블록 설정으로 끌 수 있다
    from canon.schema import BlockSetting
    p.settings.blocks = [BlockSetting(id="ref_notes", on=False)]
    assert "참고 구조" not in prompts.build_episode_context(p, 2, write=True)


def test_beat_note_job_and_prompt(client):
    b = _book()
    name = _work()
    refdigest.run(b.id, refdigest.llm_for(b.id))
    est = client.post(f"/api/refs/{b.id}/note/estimate", json={"eps": [1, 2, 3], "use": "write"}).json()
    assert est["mode"] == "cards" and client.post(f"/api/refs/{b.id}/note/estimate", json={"eps": [1], "use": "모름"}).status_code == 400
    r = _wait(client, client.post(f"/api/refs/{b.id}/note", json={"eps": [1, 2, 3], "project": name, "use": "write"}).json())["result"]
    assert (r["kind"], r["use"]) == ("beats", "write") and r["text"].startswith("한 화의 꼴: (가짜)") and "박자:\n- " in r["text"] and "끝을 끊는 방식:\n- " in r["text"]
    assert store.load(name).ref_notes == []
    v = client.post(f"/api/projects/{name}/ref-notes", json={"text": r["text"], "ref": b.id, "from_name": r["from_name"], "from_eps": r["from_eps"], "kind": "beats", "use": "write"}).json()
    assert v["notes"][0]["kind"] == "beats" and v["notes"][0]["use"] == "write" and v["dropped"] == []
    ask = prompts.ref_beats_note_prompt("## 1번 · 1화 [대화 · 긴장 3]\n사건: 서윤이 등대에 올랐다", "cards", ["서윤"], "")
    assert "그 대목이 하는 일로" in ask and "이름 대신 역할로" in ask and "되풀이되는 꼴로 판단합니다" in ask and "# 화 카드의 인물 이름 (메모에 쓰지 않습니다)\n서윤" in ask
    assert "장면이 바뀌는 곳을 세어" in prompts.ref_beats_note_prompt("원문", "text")
