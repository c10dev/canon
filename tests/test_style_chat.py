"""대화로 문체 다듬기와 이 문체로 쓴 예시 (mock LLM). 실행: python -m pytest tests"""
from canon import pipeline, prompts, store
from canon.mock import MockLLM
from canon.schema import Episode, EpisodePlot, Project, StyleEdit, StyleMarker, StyleProfile, StyleRevision

from .test_library import SAMPLE, client  # noqa: F401  (pytest fixture)

TEXT = "바람이 불었다. 그는 문을 열었다.\n\n\"왔어?\" 그녀가 물었다. 그는 대답하지 않고 오래 창밖을 보았다."


def _plot(n):
    return EpisodePlot(number=n, act="기", title=f"{n}화", summary="", events=[], characters=[],
                       emotional_shift="", ending_hook="")


def _project() -> Project:
    p = Project()
    p.meta.title = "등대"
    p.style = StyleProfile(tense="과거형", sentence_rhythm="긴 문장", dos=["감정은 행동으로"],
                           markers=[StyleMarker(text="것이었다", per_1k=1.5)], sample_passages=["원문 문단."])
    p.episodes.append(Episode(plot=_plot(1), status="written", text=TEXT))
    return p


def test_clean_drops_same_and_normalizes():
    p = _project()
    rev = StyleRevision(reply="고침", edits=[
        StyleEdit(key="tense", text=" 과거형 "),                       # 지금과 같다
        StyleEdit(key="dos", items=["감정은 행동으로", " 대사는 짧게 ", "대사는 짧게", ""], text="섞인 값"),
        StyleEdit(key="markers", markers=[StyleMarker(text="'것이었다'", per_1k=9), StyleMarker(text="하더라", per_1k=4)]),
        StyleEdit(key="banned_phrases", items=["“묘한”"]),
        StyleEdit(key="sentence_rhythm", text="처음 안"),
        StyleEdit(key="sentence_rhythm", text="짧은 문장 위주"),        # 같은 칸은 뒤의 것
    ], preview_source="없는 대목", preview="새 글")
    pipeline.clean_style_revision(p, rev, TEXT)
    by = {e.key: e for e in rev.edits}
    assert list(by) == ["sentence_rhythm", "dos", "banned_phrases", "markers"]  # 프로필 칸 순서
    assert by["dos"].items == ["감정은 행동으로", "대사는 짧게"] and by["dos"].text == ""
    assert [(m.text, m.per_1k) for m in by["markers"].markers] == [("것이었다", 1.5), ("하더라", 0)]
    assert by["banned_phrases"].items == ["묘한"] and by["sentence_rhythm"].text == "짧은 문장 위주"
    assert rev.preview_source == "" and rev.preview == "새 글"  # 참고한 화에 없는 대목은 비운다

    same = StyleRevision(reply="그대로", edits=[StyleEdit(key="tense", text="과거형")], preview="글")
    assert pipeline.clean_style_revision(p, same).edits == [] and same.preview == ""


def test_prompt_has_profile_recent_ref_and_history():
    p = _project()
    pipeline.record_style_chat(p, "대사를 줄여 줘", 0, pipeline.revise_style(MockLLM(), p, "대사를 줄여 줘"))
    text = prompts.style_chat_prompt(p, "더 짧게", 1, pipeline.style_chat_recent(p))
    assert "\"sentence_rhythm\": \"긴 문장\"" in text and "원문 문단." in text
    assert "1화: 문장 평균" in text and "[작가가 참고하라고 고른 1화 본문]" in text and TEXT in text
    assert "작가: 대사를 줄여 줘" in text and "변경안: 문장 리듬, 지킬 것 / 아직 결정 전" in text
    assert text.index("[지금 스타일 프로필]") < text.index("[최근 화 문체 지표]") < text.index("[작가의 새 말]")


def test_revise_apply_undo():
    p = _project()
    try:
        pipeline.revise_style(MockLLM(), p, "더 짧게", 5)
        raise AssertionError("본문이 없는 화는 참고할 수 없다")
    except ValueError:
        pass
    rev = pipeline.revise_style(MockLLM(), p, "더 짧게", 1)
    assert [e.key for e in rev.edits] == ["sentence_rhythm", "dos"]  # 시제는 지금과 같아 빠진다
    assert rev.preview_source and rev.preview_source in TEXT
    pipeline.record_style_chat(p, "더 짧게", 1, rev)
    msgs = p.chat("style").messages
    assert msgs[0].episode == 1 and msgs[0].where == "1화 참고" and msgs[1].style is rev

    # 질문에는 변경안이 붙지 않는다
    pipeline.record_style_chat(p, "지금 리듬은 어때?", 0, pipeline.revise_style(MockLLM(), p, "지금 리듬은 어때?"))
    assert p.chat("style").messages[3].style is None

    assert pipeline.apply_style_chat(p, 1, ["dos"]) == ["dos"]
    assert p.style.dos[-1] == "대사는 한 줄을 넘기지 않는다" and p.style.sentence_rhythm == "긴 문장"
    assert msgs[1].style_before.dos == ["감정은 행동으로"] and p.style_example is None  # 일부만 적용하면 예시로 옮기지 않는다
    try:
        pipeline.apply_style_chat(p, 1, ["sentence_rhythm"])
        raise AssertionError("이미 처리한 변경안")
    except ValueError:
        pass

    done, kept = pipeline.undo_style_chat(p, 1)
    assert done == ["dos"] and not kept and p.style.dos == ["감정은 행동으로"] and msgs[1].outcome == ""

    # 모두 적용하면 시험 문단이 예시 칸으로 간다. 그 뒤 작가가 다시 고친 칸은 취소해도 그대로 둔다
    pipeline.apply_style_chat(p, 1, ["dos", "sentence_rhythm"])
    assert p.style_example.by == "chat" and p.style_example.episode == 1 and p.style_example.profile == p.style
    p.style.sentence_rhythm = "작가가 다시 고침"
    done, kept = pipeline.undo_style_chat(p, 1)
    assert done == ["dos"] and kept == ["sentence_rhythm"] and p.style.sentence_rhythm == "작가가 다시 고침"


def test_new_marker_rate_counted_on_apply():
    p = _project()
    rev = StyleRevision(reply="표지", edits=[StyleEdit(key="markers", markers=[
        StyleMarker(text="것이었다", note="", per_1k=0), StyleMarker(text="물었다", per_1k=0)])])
    pipeline.clean_style_revision(p, rev)
    pipeline.record_style_chat(p, "표지 더해 줘", 0, rev)
    pipeline.apply_style_chat(p, 1, ["markers"])
    rates = {m.text: m.per_1k for m in p.style.markers}
    assert rates["것이었다"] == 1.5 and rates["물었다"] > 0  # 새 표지는 이 작품 본문에서 센다


def test_example_prompt_and_pipeline():
    p = _project()
    text = prompts.style_example_prompt(p, "비 오는 날", 1)
    assert text.startswith("# 작품 정보") and TEXT in text and "작가가 바라는 장면: 비 오는 날" in text
    assert "600~900자" in prompts.style_example_prompt(p)
    ex = pipeline.style_example(MockLLM(), p, "비 오는 날", 1)
    assert ex.text and ex.source and ex.source in TEXT and ex.episode == 1 and ex.profile == p.style
    try:
        pipeline.style_example(MockLLM(), Project())
        raise AssertionError("빈 문체는 예시를 쓰지 않는다")
    except ValueError as err:
        assert "비어" in str(err)


def test_style_chat_api(client):
    prof = client.post("/api/styles/analyze", json={"text": SAMPLE}).json()
    e = client.post("/api/styles", json={"name": "건조체", "sample": SAMPLE, "profile": prof}).json()
    client.post("/api/projects", json={"name": "a", "meta": {"title": "등대", "target_episodes": 10}, "style_id": e["id"]})

    # 옛 문체 대화 기록: 보내기는 04e 에서 지웠으므로 기록은 pipeline 으로 만든다. 적용 · 적용 취소 · 버림은 옛 엔드포인트가 그대로 받는다
    assert client.post("/api/projects/a/chat/style", json={"message": "대사를 짧게"}).status_code == 404
    q = store.load("a")
    pipeline.record_style_chat(q, "대사를 짧게", 0, pipeline.revise_style(MockLLM(), q, "대사를 짧게"))
    store.save("a", q)
    m = client.get("/api/projects/a").json()["chats"][0]["messages"][1]
    assert m["style"]["edits"] and m["style"]["preview"]
    assert client.post("/api/projects/a/chat/style/1/apply", json={"fields": []}).status_code == 400

    keys = [x["key"] for x in m["style"]["edits"]]
    p = client.post("/api/projects/a/chat/style/1/apply", json={"fields": keys, "push": True}).json()
    assert p["chats"][0]["messages"][1]["outcome"] == "applied" and p["style_version"] == 2
    assert p["style_example"]["by"] == "chat"
    link = client.get("/api/projects/a/style/link").json()
    assert link["state"] == "same" and link["version"] == 2
    assert "대화로 다듬음: 대사를 짧게" in client.get(f"/api/styles/{e['id']}/versions").json()[0]["note"]

    u = client.post("/api/projects/a/chat/style/1/undo", json={"push": True}).json()
    assert sorted(u["restored"]) == sorted(keys) and u["project"]["style"]["dos"] == prof["dos"]
    assert u["project"]["style_version"] == 3
    assert client.post("/api/projects/a/chat/style/1/undo", json={}).status_code == 400
    assert client.post("/api/projects/a/chat/style/1/dismiss").json()["chats"][0]["messages"][1]["outcome"] == "dismissed"

    ex = client.post("/api/projects/a/style/example", json={"scene": "다툼"}).json()["style_example"]
    assert ex["by"] == "example" and "다툼" in ex["text"]
    assert client.delete("/api/projects/a/style/example").json()["style_example"] is None


def test_strip_meta_keeps_text_after_the_last_note():
    assert pipeline.strip_meta("버린 초안 [Wait: clean description below]알림이 뜰 때") == "알림이 뜰 때"
    assert pipeline.strip_meta("첫 안][Wait - keep string clean]둘째 안 [wait, again] 셋째 안") == "셋째 안"
    assert pipeline.strip_meta("앞 글만 있음 [Note: retry]") == "앞 글만 있음"       # 뒤가 비면 가까운 앞 글
    assert pipeline.strip_meta("닫지 않음 [Hmm, let me redo this") == "닫지 않음"
    assert pipeline.strip_meta("[Wait: nothing]") == ""
    for kept in ("화면에 [관리자 권한 승인] 창이 뜰 때", "[Note 앱 알림]이 울릴 때", "[Waiter] 명찰을 볼 때", "과거형"):
        assert pipeline.strip_meta(kept) == kept                                   # 상태창 글, 한글이 든 대괄호, 다른 낱말
    once = pipeline.strip_meta("가 [Wait: x] 나")
    assert pipeline.strip_meta(once) == once == "나"


def _junk_revision() -> StyleRevision:
    from canon.schema import StyleDevice
    return StyleRevision(reply="고침", preview="버린 문단. [Wait: rewrite]\n새 문단.", edits=[
        StyleEdit(key="pacing", text="느리게 [Wait: clean below]장면마다 한 가지 일만", why="[Note: ok] 작가의 말대로"),
        StyleEdit(key="vocabulary", text="[Wait: nothing left]"),                    # 지우면 비는 칸은 뺀다
        StyleEdit(key="dos", items=["초안 [Wait - redo]대사는 짧게", "[Wait: x]"]),
        StyleEdit(key="banned_phrases", items=["[Wait: 원문 그대로]"]),
        StyleEdit(key="markers", markers=[StyleMarker(text="하더라", note="버림 [Wait: fix] 회상할 때")]),
        StyleEdit(key="devices", devices=[StyleDevice(
            name="알림 창", when="초안 (cues: '[관리자') [Wait: clean description below]알림이 뜰 때",
            cues=["[관리자 권한", "[Wait: 원문]"], example="[Wait: 원문 예시]")]),
    ])


def test_clean_strips_model_notes_from_written_fields():
    p = _project()
    rev = pipeline.clean_style_revision(p, _junk_revision())
    by = {e.key: e for e in rev.edits}
    assert "vocabulary" not in by
    assert by["pacing"].text == "장면마다 한 가지 일만" and by["pacing"].why == "작가의 말대로"
    assert by["dos"].items == ["대사는 짧게"] and by["markers"].markers[0].note == "회상할 때"
    d = by["devices"].devices[0]
    assert d.when == "알림이 뜰 때" and d.name == "알림 창"
    # 원문을 그대로 옮기는 값은 건드리지 않는다
    assert d.cues == ["[관리자 권한", "[Wait: 원문]"] and d.example == "[Wait: 원문 예시]"
    assert by["banned_phrases"].items == ["[Wait: 원문 그대로]"]
    assert rev.preview == "새 문단."
    again = pipeline.clean_style_revision(p, rev.model_copy(deep=True))             # 대화 에이전트는 두 번 거른다
    assert again.model_dump() == rev.model_dump()


def test_apply_strips_notes_of_a_stored_revision_and_undo_restores():
    p = _project()
    rev = _junk_revision()                                                          # 거르기 전에 남은 옛 변경안
    pipeline.record_style_chat(p, "고쳐 줘", 0, rev)
    assert pipeline.apply_style_chat(p, 1, ["pacing", "vocabulary", "devices"]) == ["pacing", "devices"]
    assert p.style.pacing == "장면마다 한 가지 일만" and p.style.vocabulary == ""
    assert p.style.devices[0].when == "알림이 뜰 때"
    done, kept = pipeline.undo_style_chat(p, 1)
    assert done == ["pacing", "devices"] and not kept and p.style.pacing == "" and p.style.devices == []

    # 모든 칸을 적용하면 시험 문단이 예시 칸으로 간다. 그 글도 거른다
    left = [e.key for e in rev.edits if e.key != "vocabulary"]
    rev.edits = [e for e in rev.edits if e.key != "vocabulary"]
    pipeline.apply_style_chat(p, 1, left)
    assert p.style_example.text == "새 문단."
