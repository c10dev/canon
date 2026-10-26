"""대화로 문체 다듬기와 이 문체로 쓴 예시 (mock LLM). 실행: python -m pytest tests"""
from canon import pipeline, prompts
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

    r = client.post("/api/projects/a/chat/style", json={"message": "대사를 짧게"})
    assert r.status_code == 200
    m = r.json()["chats"][0]["messages"][1]
    assert m["style"]["edits"] and m["style"]["preview"]
    assert client.post("/api/projects/a/chat/style", json={"message": "x", "episode": 3}).status_code == 400
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
