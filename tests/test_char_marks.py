"""인물 표지 (canon/charmarks.py, docs/webnovel/specs/10-marks.md): 저장 · 읽기, 근거 구절 확인, 화 번호 옮기기,
화면 저장이 덮지 않음, 어떤 요청에도 들어가지 않음, 명령줄 · 웹 라우트."""
import inspect
import json

import pytest

from canon import cast, charmarks, echoes, llm, pipeline, prompts, renumber, store
from canon.schema import Character, CharMark, Project

from . import test_prompt_registry as reg
from .test_insert import _short as _insert_short

SENT_TEXT = "표지시험글ZQX"
SENT_QUOTE = "표지근거구절QZX"


def _with_marks(p: Project) -> Project:
    """모든 인물에 고유 표시를 넣은 표지를 붙인 사본."""
    q = p.model_copy(deep=True)
    for c in q.characters:
        c.marks = [CharMark(id="m1", kind="말버릇", text=SENT_TEXT, episode=1, quote=SENT_QUOTE)]
    return q


# ---------- 스키마 ----------

def test_old_project_reads_without_marks():
    c = Character.model_validate({"id": "a", "name": "가", "role": "주인공"})
    assert c.marks == []
    p = Project.model_validate({"characters": [{"id": "a", "name": "가", "role": "주인공"}]})
    assert p.characters[0].marks == []


def test_marks_stay_out_of_response_schema():
    assert "marks" not in json.dumps(Character.model_json_schema())
    assert "CharMark" not in json.dumps(Character.model_json_schema())


def test_prompt_dump_drops_marks_but_save_keeps_them():
    c = Character(id="a", name="가", role="주인공", marks=[CharMark(id="m1", text=SENT_TEXT, episode=1, quote=SENT_QUOTE)])
    assert SENT_TEXT not in llm.dump(c) and SENT_TEXT not in llm.dump([c])
    assert SENT_TEXT not in json.dumps(prompts.cast_view([c]), ensure_ascii=False)
    assert c.model_dump()["marks"][0]["text"] == SENT_TEXT
    assert Character.model_validate_json(c.model_dump_json()).marks[0].quote == SENT_QUOTE


# ---------- 요청에 새지 않음 (정할 것 15) ----------

@pytest.mark.parametrize("tag", ["short", "long"])
def test_marks_stay_out_of_every_request(tag):
    """표지를 붙인 시험 작품의 모든 요청 글이 스냅샷과 같고 표시가 없다 (test_frame 의 본보기)."""
    want = json.loads(reg.SNAPSHOT.read_text(encoding="utf-8"))
    p = _with_marks(reg._short() if tag == "short" else reg._long())
    texts = reg._requests(p)
    got = {f"{tag}:{k}": reg._h(v) for k, v in texts.items()}
    assert {k: v for k, v in got.items() if want.get(k) != v} == {}
    assert not [k for k, v in texts.items() if SENT_TEXT in v or SENT_QUOTE in v]


def _call_all(p: Project) -> dict[str, str]:
    """prompts 의 *_prompt 함수 가운데 (p, 정수 …) 로 부를 수 있는 것을 모두 부른다. 이 작품에서 못 만드는 것은 건너뛴다."""
    out = {}
    for name, f in sorted(vars(prompts).items()):
        if not (name.endswith("_prompt") and inspect.isfunction(f)):
            continue
        params = list(inspect.signature(f).parameters.values())
        if not params or params[0].name != "p":
            continue
        args = [p]
        for x in params[1:]:
            if x.default is not inspect.Parameter.empty:
                break
            ann = str(x.annotation)
            if "int" in ann:
                args.append(1 if x.name != "n" else 3)
            elif "str" in ann:
                args.append("hero" if x.name in ("cid", "a", "character", "who") else "요청")
            else:
                args = None
                break
        if args is None:
            continue
        try:
            out[name] = str(f(*args))
        except Exception:  # noqa: BLE001  이 작품 · 인자로 만들 수 없는 요청
            continue
    return out


def test_marks_stay_out_of_other_prompts():
    p = reg._short()
    q = _with_marks(p)
    plain, marked = _call_all(p), _call_all(q)
    assert len(marked) >= 30
    assert {k for k in marked if marked[k] != plain.get(k)} == set()
    assert not [k for k, v in marked.items() if SENT_TEXT in v or SENT_QUOTE in v]
    assert SENT_TEXT not in prompts.setup_chat_prompt(q, "말투를 바꿔 줘")
    assert SENT_TEXT not in prompts.state_prompt(q, 3)


def test_marks_do_not_count_as_canon_or_setting():
    """거둔 구절이 반복 검사의 '되풀이해도 되는 말'이나 인용 근거의 설정이 되지 않는다."""
    p = reg._short()
    q = _with_marks(p)
    assert echoes._canon_text(q) == echoes._canon_text(p)
    assert not pipeline._quoted(q, "설정", 1, SENT_QUOTE)


# ---------- 더하기 · 고치기 · 지우기 ----------

QUOTE = "서윤은 등대 앞에 섰다."


def test_add_from_finalized_episode():
    p = reg._short()
    m = charmarks.add(p, "hero", "버릇", "  등대 앞에 선다  ", 1, QUOTE)
    assert (m.kind, m.text, m.episode, m.quote) == ("버릇", "등대 앞에 선다", 1, QUOTE)
    assert p.characters[0].marks == [m] and charmarks.found(p, m)


def test_add_keeps_body_text_and_fills_empty_text():
    p = reg._short()
    e = p.episode(1)
    e.text = e.text.replace("서윤은 등대", "서윤은\n등대")
    m = charmarks.add(p, "hero", "말버릇", "", 1, QUOTE)  # 공백 차이는 봐주고 본문 글 그대로 저장
    assert m.quote == "서윤은\n등대 앞에 섰다." and m.quote in e.text
    assert m.text == "서윤은 등대 앞에 섰다."


@pytest.mark.parametrize("n,quote,kind,msg", [
    (4, QUOTE, "버릇", "반영한 화"),
    (1, "없는 구절이에요", "버릇", "본문에 없어요"),
    (1, "   ", "버릇", "골라 주세요"),
    (1, QUOTE, "성격", "갈래"),
    (1, "가" * 401, "버릇", "400자"),
])
def test_add_rejects(n, quote, kind, msg):
    p = reg._short()
    with pytest.raises(ValueError, match=msg):
        charmarks.add(p, "hero", kind, "", n, quote)
    assert all(not c.marks for c in p.characters)


def test_add_rejects_long_text_and_unknown_character():
    p = reg._short()
    with pytest.raises(ValueError, match="200자"):
        charmarks.add(p, "hero", "버릇", "가" * 201, 1, QUOTE)
    with pytest.raises(KeyError, match="인물이 없어요"):
        charmarks.add(p, "nobody", "버릇", "", 1, QUOTE)


def test_edit_and_remove():
    p = reg._short()
    m = charmarks.add(p, "hero", "버릇", "처음", 1, QUOTE)
    charmarks.edit(p, "hero", m.id, "외모", "고친 글")
    got = p.characters[0].marks[0]
    assert (got.kind, got.text, got.episode, got.quote) == ("외모", "고친 글", 1, QUOTE)
    with pytest.raises(ValueError, match="적어 주세요"):
        charmarks.edit(p, "hero", m.id, "외모", "  ")
    with pytest.raises(KeyError, match="표지가 없어요"):
        charmarks.remove(p, "hero", "m-none")
    charmarks.remove(p, "hero", m.id)
    assert p.characters[0].marks == []


def test_mark_stays_when_body_changes_or_episode_is_reverted():
    p = reg._short()
    m = charmarks.add(p, "hero", "버릇", "", 3, QUOTE)
    p.episode(3).text = "다른 본문"
    assert p.characters[0].marks and not charmarks.found(p, m)
    p.episode(3).text = QUOTE
    pipeline.delete_last(p, 3)  # 반영 취소 → 본문 비우기 → 화 빼기
    assert [x.id for x in p.characters[0].marks] == [m.id]
    assert not charmarks.found(p, p.characters[0].marks[0])


def test_reapplying_setup_keeps_marks():
    p = reg._short()
    charmarks.add(p, "hero", "버릇", "", 1, QUOTE)
    pipeline.apply_setup(p, pipeline.suggest_setup(reg.L, p))
    assert len(p.characters[0].marks) == 1


# ---------- 화 번호 옮기기 ----------

def test_move_points_moves_mark_episode_and_round_trips():
    p = _insert_short()
    p.characters[0].marks = [CharMark(id="m1", episode=7, quote="본문"), CharMark(id="m2", episode=3, quote="본문")]
    before = p.model_dump()
    counts = renumber.move_points(p, renumber.point_insert(6))
    assert [m.episode for m in p.characters[0].marks] == [8, 3] and counts["marks"] == 1
    counts = renumber.move_points(p, renumber.point_remove(6), gone=6)
    assert counts["marks"] == 1 and p.model_dump() == before


def test_insert_episode_note_names_marks():
    p = _insert_short()
    p.characters[0].marks = [CharMark(id="m1", episode=9, quote="본문")]  # 시험용: 옮길 수 있는 화를 가리키게 둔다
    notes = pipeline.insert_episode(p, 8, "외전")
    assert p.characters[0].marks[0].episode == 10
    assert any("인물 표지 1개" in x for x in notes)


def test_remove_episode_keeps_mark_pointing_at_gone_episode():
    p = _insert_short()
    p.characters[0].marks = [CharMark(id="m1", episode=8, quote="본문")]
    pipeline.remove_episode(p, 8)
    assert [m.episode for m in p.characters[0].marks] == [8]


# ---------- 화면 저장이 덮지 않음 ----------

def test_keep_restores_disk_marks():
    disk = reg._short()
    charmarks.add(disk, "hero", "버릇", "", 1, QUOTE)
    mine = disk.model_copy(deep=True)
    mine.characters[0].marks = []  # 옛 사본
    mine.characters[1].marks = [CharMark(id="x", text="화면이 지어낸 표지")]
    mine.characters.append(Character(id="new", name="새 인물", role="조연", marks=[CharMark(id="y")]))
    charmarks.keep(disk, mine)
    assert [m.text for m in mine.characters[0].marks] == ["서윤은 등대 앞에 섰다."]
    assert mine.characters[1].marks == [] and mine.characters[-1].marks == []


# ---------- 명령줄 ----------

def test_cast_describe_lists_marks():
    p = reg._short()
    assert "표지" not in cast.describe(p, "hero")
    m = charmarks.add(p, "hero", "말버릇", "말끝을 흐린다", 1, QUOTE)
    out = cast.describe(p, "hero")
    assert "  표지:\n    [말버릇] 말끝을 흐린다 (1화)" in out
    p.episode(1).text = "다른 본문"
    assert f"[{m.kind}] {m.text} (1화) (본문에서 못 찾음)" in cast.describe(p, "hero")


# ---------- 웹 ----------

def test_web_routes(client):
    p = reg._short()
    store.save("marks", p)
    base = "/api/projects/marks/characters/hero/marks"
    r = client.post(base, json={"kind": "말버릇", "text": "등대 앞", "episode": 1, "quote": QUOTE})
    assert r.status_code == 200, r.text
    mid = r.json()["characters"][0]["marks"][0]["id"]
    assert client.post(base, json={"kind": "버릇", "episode": 4, "quote": QUOTE}).status_code == 400
    assert client.post(base, json={"kind": "버릇", "episode": 1, "quote": "없는 글"}).status_code == 400
    r = client.put(f"{base}/{mid}", json={"kind": "외모", "text": "고침"})
    assert r.status_code == 200 and r.json()["characters"][0]["marks"][0]["text"] == "고침"
    # 화면 저장은 표지를 덮지 않는다 (표지를 지운 사본을 보내도)
    data = client.get("/api/projects/marks").json()
    data["characters"][0]["marks"] = []
    assert client.put("/api/projects/marks", json=data).status_code == 200
    assert [m.id for m in store.load("marks").characters[0].marks] == [mid]
    assert client.delete(f"{base}/{mid}").status_code == 200
    assert store.load("marks").characters[0].marks == []
    assert client.delete(f"{base}/{mid}").status_code == 400
    assert client.post("/api/projects/none/characters/hero/marks", json={}).status_code == 404


# ---------- 다른 길 (되돌리기 · 대화 에이전트) ----------

def test_revert_moves_added_character_to_candidates_with_marks():
    """반영 취소로 인물 후보에 돌아간 인물은 표지를 그대로 가진다. 화면 저장도 후보의 표지를 지킨다."""
    p = reg._short()
    new = Character(id="newbie", name="새얼굴", role="조연", first_ep=3)
    p.characters.append(new)
    p.history[-1].new_characters.append(new.model_copy())
    p.episode(4).plot.characters.append("newbie")  # 뒤 화 플롯에 나와 지우지 않고 후보로 돌린다
    charmarks.add(p, "newbie", "외모", "", 3, QUOTE)
    pipeline.revert(p, 2)
    back = next(c for c in p.cast_candidates if c.id == "newbie")
    assert len(back.marks) == 1 and all(c.id != "newbie" for c in p.characters)
    mine = p.model_copy(deep=True)
    for c in mine.cast_candidates:
        c.marks = []
    charmarks.keep(p, mine)
    assert len(next(c for c in mine.cast_candidates if c.id == "newbie").marks) == 1


def test_setup_chat_undo_keeps_marks():
    from canon import setupchat

    from .test_setup_chat import _ask, _project
    from .test_timeline import _play

    p = _project()
    _play(p, 1, 1)
    i, rev = _ask(p)
    setupchat.apply(p, i, setupchat.part_ids(rev))
    quote = p.episode(1).text.strip().split("\n")[0][:20].strip()
    m = charmarks.add(p, "hero", "버릇", "", 1, quote)
    setupchat.undo(p, i)
    assert p.characters[0].marks == [m]


def test_agent_read_cast_leaves_marks_out():
    from canon import agent

    q = _with_marks(reg._short())
    _, out = agent.read(q, "read_cast", {"ids": ""})
    assert SENT_TEXT not in out and SENT_QUOTE not in out and '"marks"' not in out
