"""설정 도우미 대화(canon/setupchat.py) 테스트 (mock LLM): 변경안 정리, 고른 것만 적용, 적용 취소, 1화 반영 뒤 기록,
방향 여러 안, 프롬프트, 웹 · 명령줄. 실행: python -m pytest tests"""
import contextlib
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from canon import archetypes, logline, pipeline, prompts, setupchat, store
from canon.cli import main
from canon.schema import ArchetypePick, Character, CharacterEdit, Relationship, SetupEdit, SetupRevision

from .test_storylines import _short
from .test_timeline import LLM, _play
from .test_web import client  # noqa: F401  (pytest fixture)


def _project():
    p = _short(8)
    p.meta.logline_parts.who = "말 없는 소녀"
    p.meta.logline_parts.goal = "오빠를 찾는다"
    p.meta.logline = logline.compose(p.meta.logline_parts)
    return p


def _ask(p, text="주인공 약점을 더 어둡게", mode=""):
    rev = pipeline.revise_setup(LLM, p, text, mode)
    setupchat.record(p, text, mode, rev)
    return len(p.chat("setup").messages) - 1, rev


def test_clean_drops_same_empty_unknown_and_fixes_ids():
    p = _project()
    hero = p.characters[0]
    rev = SetupRevision(reply="고침", edits=[
        SetupEdit(key="tone", text=f" {p.meta.tone} "),                        # 지금과 같다
        SetupEdit(key="theme", text=""),                                         # 칸을 비우지 않는다
        SetupEdit(key="world.rules", items=[" 바다는 차갑다 ", "바다는 차갑다", ""]),
        SetupEdit(key="logline.block", text="처음 안"),
        SetupEdit(key="logline.block", text="마을 사람들"),                       # 같은 칸은 뒤의 것
    ], characters=[
        CharacterEdit(id="ghost", field="goal", text="x"),
        CharacterEdit(id=hero.id, field="goal", text=hero.goal),
        CharacterEdit(id=hero.id, field="secrets", items=[" 편지 ", "편지"], text="섞인 값"),
    ], new_characters=[
        Character(id="Hero", name="새얼굴", role="조연", narration_voice="x", first_ep=3),
        Character(id="dup", name=hero.name, role="조연"),
    ], relationships=[
        Relationship(a="ally", b="hero", type="동료", a_view=["믿는다", "모름"], b_view=["경계한다"]),  # 지금 관계(hero, ally)와 방향을 맞춘다
        Relationship(a="hero", b="nobody", type="원수"),
        Relationship(a="Hero", b="ally", type="친구"),
    ])
    setupchat.clean(p, rev)
    assert [e.key for e in rev.edits] == ["logline.block", "world.rules"]  # 칸 순서
    assert rev.edits[0].text == "마을 사람들" and rev.edits[1].items == ["바다는 차갑다"]
    assert [(x.field, x.items, x.text) for x in rev.characters] == [("secrets", ["편지"], "")]
    new = rev.new_characters
    assert [(c.id, c.narration_voice, c.first_ep) for c in new] == [("hero2", "", 0)]  # 같은 이름은 이미 있는 인물
    old = p.relationships[0]
    by = {setupchat.rel_id(r): r for r in rev.relationships}
    assert set(by) == {f"r:{old.a}:{old.b}", "r:hero2:ally"}
    r = by[f"r:{old.a}:{old.b}"]
    assert (r.a_view, r.b_view) == (["경계한다"], ["믿는다"]) and (r.affinity, r.tension) == (old.affinity, old.tension)
    assert "nobody" not in str(by) and "ghost" in rev.reply and "관계 1개" in rev.reply


def test_apply_picked_and_undo():
    p = _project()
    i, rev = _ask(p)
    ids = setupchat.part_ids(rev)
    assert ids == ["logline.block", "theme", "world.rules", "c:hero:wound", "new:mentor", "r:hero:mentor"]  # 톤은 같아 빠진다
    try:
        setupchat.apply(p, i, ["r:hero:mentor"])
        raise AssertionError("고르지 않은 새 인물과의 관계")
    except ValueError:
        pass
    assert setupchat.apply(p, i, ["logline.block", "c:hero:wound", "new:mentor", "r:hero:mentor"]) == \
        ["logline.block", "c:hero:wound", "new:mentor", "r:hero:mentor"]
    assert p.meta.logline == "말 없는 소녀가 오빠를 찾는다. 하지만 바다를 지키는 마을 사람들."  # 칸으로 만든 문장은 다시 합친다
    assert p.characters[0].wound.startswith("버려질까") and p.characters[-1].id == "mentor"
    assert any(s.character_id == "mentor" for s in p.states) and any(t.source == "mentor" for t in p.ties)
    assert p.setting_log == []  # 1화 반영 전에는 기록하지 않는다
    msg = p.chat("setup").messages[i]
    assert msg.outcome == "applied" and msg.setup_before.characters[0].wound != p.characters[0].wound
    try:
        setupchat.apply(p, i, ["theme"])
        raise AssertionError("이미 처리한 변경안")
    except ValueError:
        pass

    p.characters[0].wound = "작가가 다시 고침"
    p.cast_archetypes.append(ArchetypePick(character_id="mentor", archetype=archetypes.CATALOG[0].id))
    done, kept = setupchat.undo(p, i)
    assert p.cast_archetypes == []  # 지운 새 인물의 원형 기록도 지운다
    assert done == ["logline.block", "new:mentor", "r:hero:mentor"] and kept == ["c:hero:wound"]
    assert p.meta.logline == "말 없는 소녀가 오빠를 찾는다." and p.meta.logline_parts.block == ""
    assert [c.id for c in p.characters] == ["hero", "ally"] and not any(t.source == "mentor" for t in p.ties)
    assert p.characters[0].wound == "작가가 다시 고침" and msg.outcome == "" and msg.setup_before is None


def test_legacy_logline_kept_and_used_character_kept():
    p = _short(8)
    p.meta.logline = "옛 문장만 있는 로그라인"
    i, rev = _ask(p)
    setupchat.apply(p, i, setupchat.part_ids(rev))
    assert p.meta.logline == "옛 문장만 있는 로그라인"  # 칸 없이 문장만 있던 작품은 덮지 않는다
    p.episode(3).plot.characters.append("mentor")
    done, kept = setupchat.undo(p, i)
    assert kept == ["new:mentor"] and any(c.id == "mentor" for c in p.characters)


def test_after_first_episode_logs_author_and_keeps_start_relations():
    p = _project()
    _play(p, 1, 1)
    old = p.relationships[0].model_copy(deep=True)
    rev = SetupRevision(reply="고침", characters=[CharacterEdit(id="hero", field="speech_style", text="짧은 존댓말. \"네.\"")],
                        relationships=[Relationship(a=old.a, b=old.b, type="옛 동료", a_view=["미워한다"], b_view=["미워한다"])])
    setupchat.clean(p, rev)
    r = rev.relationships[0]
    assert (r.a_view, r.b_view, r.type) == (old.a_view, old.b_view, "옛 동료")  # 첫 반영 뒤에는 시작 관계를 바꾸지 않는다
    setupchat.record(p, "말투를 바꿔", "", rev)
    i = len(p.chat("setup").messages) - 1
    ties = [t.model_copy() for t in p.ties]
    setupchat.apply(p, i, setupchat.part_ids(rev))
    assert p.ties == ties  # 지금 관계는 본문 사건이 만든 것 그대로
    assert [(x.field, x.source, x.episode) for x in p.setting_log] == [("speech_style", "author", 1)]
    setupchat.undo(p, i)
    assert p.setting_log == [] and p.relationships[0].type == old.type

    text = prompts.setup_chat_prompt(p, "다음")
    assert "a_view, b_view 는 비웁니다" in text and "[이미 쓴 화]" in text and "\"a_view\"" not in text.split("[관계]")[1].split("[")[0]


def test_options_and_prompt():
    p = _project()
    i, rev = _ask(p, "방향 보여 줘", "options")
    assert len(rev.options) == 3 and not rev.has_changes()
    msgs = p.chat("setup").messages
    assert msgs[i - 1].mode == "options" and msgs[i].setup.options
    try:
        setupchat.message(p, i)
        raise AssertionError("방향 안은 적용하는 변경안이 아니다")
    except KeyError:
        pass
    j, q = _ask(p, "지금 주인공은 어때?")
    assert p.chat("setup").messages[j].setup is None  # 질문에는 변경안이 없다

    text = prompts.setup_chat_prompt(p, "2안으로")
    assert "작가 [방향 여러 안 요청]: 방향 보여 줘" in text and "(방향 안: 1. 복수 / 2. 구원 / 3. 비밀)" in text
    assert text.index("[인물]") < text.index("[이름·지명 후보]") < text.index("[지금까지의 대화]") < text.index("[작가의 새 말]")
    assert "a_view(a 가 b 를 보는 방식)" in text and "[이미 쓴 화]" not in text
    assert "options 에 서로 분명히 다른 방향" in prompts.setup_chat_prompt(p, "방향", "options")


def test_web_send_apply_undo(client):  # noqa: F811
    p = _project()
    store.save("등대", p)
    r = client.post("/api/projects/등대/chat/setup", json={"message": "주인공 약점을 더 어둡게"})
    assert r.status_code == 200, r.text
    msgs = r.json()["chats"][-1]["messages"]
    i = len(msgs) - 1
    assert msgs[i]["setup"]["new_characters"][0]["id"] == "mentor"
    r = client.post(f"/api/projects/등대/chat/setup/{i}/apply", json={"fields": ["theme", "new:mentor"]})
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["theme"].startswith("잃은 것을") and r.json()["characters"][-1]["id"] == "mentor"
    r = client.post(f"/api/projects/등대/chat/setup/{i}/undo")
    assert r.json()["restored"] == ["theme", "new:mentor"] and r.json()["project"]["characters"][-1]["id"] == "ally"
    assert client.post(f"/api/projects/등대/chat/setup/{i}/dismiss").status_code == 200
    assert client.post(f"/api/projects/등대/chat/setup/{i}/reopen").status_code == 200
    r = client.post(f"/api/projects/등대/chat/setup/{i}/apply", json={"fields": []})
    assert r.status_code == 400 and "고르세요" in r.json()["detail"]
    r = client.post("/api/projects/등대/chat/setup", json={"message": "방향", "mode": "options"})
    assert len(r.json()["chats"][-1]["messages"][-1]["setup"]["options"]) == 3


def test_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_LLM", "mock")
    monkeypatch.setenv("CANON_HOME", str(tmp_path))
    store.save("등대", _project())
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["setupchat", "등대", "주인공 약점을 더 어둡게", "--pick", "2,5,6"])
    text = out.getvalue()
    assert "[서윤 두려운 것 · 약점]" in text and "적용했어요: 주제, 새 인물 한결, 관계 서윤 ↔ 한결" in text
    assert store.load("등대").characters[-1].id == "mentor"
    with contextlib.redirect_stdout(io.StringIO()) as out:
        main(["setupchat", "등대", "--undo", "1"])
    assert "되돌렸어요: 주제, 새 인물 한결, 관계 서윤 ↔ 한결" in out.getvalue()
    assert store.load("등대").characters[-1].id == "ally"


SETUP_JS = Path(__file__).resolve().parent.parent / "canon" / "static" / "setupchat.js"


@pytest.mark.skipif(not shutil.which("node"), reason="node 가 없다")
def test_js_labels_match_server():
    """화면(setupchat.js)의 칸 이름이 서버 KEY_LABELS · CHAR_LABELS 와 같다. 인물 말투는 인물 카드와 같은 '말투 (대사)'."""
    harness = """
const vm = require('vm');
const fs = require('fs');
const ctx = { CHAT_TOPICS: {}, actions: {}, document: { addEventListener() {} } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + ';globalThis.out = { keys: SETUP_KEYS, chars: SETUP_CHAR_LABEL };', ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""
    out = json.loads(subprocess.run(["node", "-e", harness, str(SETUP_JS)], capture_output=True, text=True, check=True).stdout)
    assert dict(out["keys"]) == setupchat.KEY_LABELS
    assert [k for k, _ in out["keys"]] == list(setupchat.KEY_LABELS)
    assert out["chars"] == setupchat.CHAR_LABELS
    assert setupchat.CHAR_LABELS["speech_style"] == "말투 (대사)"
