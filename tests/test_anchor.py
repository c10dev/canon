"""작품 정착 문체 (canon/anchor.py): 고르기 · 재기 · 흐름 경고 · 프롬프트 · 자동 집필 정책 · 화 번호 옮기기 · 큐 실현도."""
import random

import pytest

from canon import anchor, autorun, cue, library, metrics, pipeline, prompts, renumber
from canon.mock import _plot
from canon.schema import Character, Cue, CueSheet, Episode, Meta, Project, StateDelta, StyleMarker, StyleProfile

_WHO = ["그는", "나는", "그녀가", "노인이", "아이가", "형사가", "고양이가", "사내는", "누군가", "우리는"]
_WHERE = ["골목에서", "창가에서", "계단 아래서", "부엌에서", "빗속에서", "역 앞에서", "다리 위에서", "책상 앞에서"]
_DO = [("문을 열", "었다", "어요"), ("숨을 고르", "았다", "아요"), ("고개를 들", "었다", "어요"), ("편지를 읽", "었다", "어요"),
       ("불을 끄", "었다", "어요"), ("손을 흔들", "었다", "어요"), ("가방을 챙기", "었다", "어요"), ("시계를 보", "았다", "아요"),
       ("길을 건너", "었다", "어요"), ("물을 마시", "었다", "어요")]
_SAY = ["어디 가?", "괜찮아.", "늦었네.", "정말이야?", "그만해.", "기다려."]


def _text(polite: bool, seed: int, chars: int = 3200) -> str:
    """같은 문체(과거형 서술 또는 해요체 서술)의 글. 낱말을 섞어 원문 조각끼리도 적당히 흩어지게 한다."""
    rnd = random.Random(seed)
    paras, n = [], 0
    while n < chars:
        sents = []
        for _ in range(rnd.randint(2, 4)):
            stem, past, yo = rnd.choice(_DO)
            sents.append(f"{rnd.choice(_WHO)} {rnd.choice(_WHERE)} {stem}{yo if polite else past}.")
        para = " ".join(sents)
        if rnd.random() < 0.3:
            para += f' "{rnd.choice(_SAY)}"'
        paras.append(para)
        n += len(para) + 2
    return "\n\n".join(paras)


# 만든 글은 낱말이 적어 같은 문체끼리도 거리가 실제 원고(0.5~1.05)보다 크다. 문턱 값 자체는 실측으로 정했으니
# (reports/문체 흐름 실측 2026-11-02.md) 시험은 같은 문체(2 안팎)와 해요체(40 안팎) 사이 값으로 흐름 셈만 본다.
SYNTH_WARN = 5.0


def _project(plain: int = 8, polite: int = 0) -> Project:
    p = Project(meta=Meta(title="등대", genre="미스터리", logline="x", target_episodes=plain + polite, words_per_episode=3000))
    p.style = StyleProfile(markers=[StyleMarker(text="었다", per_1k=1.0)], sample_passages=["레퍼런스 문단이다. 바다가 보였다."])
    for i in range(1, plain + polite + 1):
        p.episodes.append(Episode(plot=_plot(i, "기"), status="finalized", text=_text(i > plain, i)))
    return p


def test_usable_and_suggest_skip_voiced_and_unfinished():
    p = _project(8)
    p.characters = [Character(id="hero", name="하나", role="주인공", narration_voice="~요 체로 말한다")]
    p.episodes[1].plot.pov = "hero"
    p.episodes[3].status = "written"
    assert anchor.usable(p) == [1, 3, 5, 6, 7, 8]
    assert anchor.suggest(p) == [1, 3, 5, 6, 7]
    with pytest.raises(ValueError, match="고를 수 없어요"):
        anchor.measure(p, [1, 2])


def test_measure_needs_enough_text_and_real_passages():
    p = _project(8)
    with pytest.raises(ValueError, match="자예요"):
        anchor.measure(p, [1])
    with pytest.raises(ValueError, match="그대로 가져와야"):
        anchor.measure(p, [1, 2, 3], ["이 글은 본문에 없는 문단이다. " * 10])
    para = p.episodes[0].text.split("\n\n")
    quote = "\n\n".join(para[:4])
    assert anchor.PASSAGE_MIN <= len(quote) <= anchor.PASSAGE_MAX
    a = anchor.set_anchor(p, [3, 1, 2], [quote])
    assert a.episodes == [1, 2, 3] and a.passages == [quote]
    assert a.metrics.chars >= anchor.MIN_CHARS and a.metrics.style_centroid
    assert a.markers[0].text == "었다" and a.markers[0].per_1k > 1.0  # 정착 화에서 다시 셌다
    assert a.later is not None and a.later < SYNTH_WARN  # 뒤 화도 같은 문체
    assert not anchor.stale(p)


def test_baseline_markers_and_prompt_use_anchor():
    p = _project(8)
    ref = pipeline.style_baseline(p)
    quote = "\n\n".join(p.episodes[0].text.split("\n\n")[:4])
    anchor.set_anchor(p, [1, 2, 3], [quote])
    assert pipeline.style_baseline(p) is p.anchor.metrics and pipeline.style_baseline(p) != ref
    assert anchor.markers(p)[0].per_1k == p.anchor.markers[0].per_1k
    ctx = prompts.static_context(p)
    assert quote in ctx and "레퍼런스 문단이다" not in ctx  # 섞지 않는다
    assert "이 작품이 지금까지 써 온 문체" in ctx and "이 작품의 정착 문체에서 센 빈도" in ctx
    p.anchor.passages = []
    ctx = prompts.static_context(p)
    assert "레퍼런스 문단이다" in ctx and "이 작품이 지금까지" not in ctx


def test_drift_warning_after_window_moves_away(monkeypatch):
    monkeypatch.setattr(anchor, "DRIFT_WARN", SYNTH_WARN)
    p = _project(plain=8, polite=6)
    anchor.set_anchor(p, [1, 2, 3])
    assert anchor.warning(p, 8) == ""
    near = anchor.rolling(p, 8)
    assert near is not None and near < anchor.DRIFT_WARN
    far = anchor.rolling(p, 14)
    assert far > anchor.DRIFT_WARN
    w = anchor.warning(p, 14)
    assert w.startswith("정착 문체에서 멀어짐")
    assert w in pipeline.style_drift(p, 14)[1]
    t = anchor.trend(p)
    assert [x["n"] for x in t] == list(range(1, 15)) and t[0]["anchor"] and not t[5]["anchor"]


def test_no_anchor_keeps_old_behavior():
    p = _project(4)
    assert anchor.rolling(p, 4) is None and anchor.warning(p, 4) == "" and anchor.distance(p, 4) is None
    assert pipeline.style_baseline(p) == metrics.measure("\n\n".join(p.style.sample_passages))
    v = anchor.view(p)
    assert v["anchor"] is None and v["suggest"] == [1, 2, 3, 4]


def test_stale_when_anchor_text_changes_and_renumber_keeps_basis():
    p = _project(8)
    anchor.set_anchor(p, [2, 3, 4])
    renumber.move_points(p, lambda x: x + 1)  # 화 번호도 함께 옮긴다
    assert p.anchor.episodes == [3, 4, 5] and [e.plot.number for e in p.episodes] == list(range(2, 10))
    assert not anchor.stale(p)  # 번호만 옮기면 그대로
    p.episode(4).text += "\n\n고친 문단."
    assert anchor.stale(p)
    renumber.move_points(p, lambda x: x, gone=5)
    assert p.anchor.episodes == [3, 4] and anchor.stale(p)


def test_candidates_come_from_picked_episodes():
    p = _project(8)
    got = anchor.candidates(p, [1, 2, 3])
    assert got and len(got) <= 6
    flat = anchor._norm(anchor.joined(p, [1, 2, 3]))
    assert all(anchor._norm(x) in flat for x in got)
    anchor.measure(p, [1, 2, 3], got[:2])  # 후보는 그대로 저장할 수 있다


def test_library_push_does_not_carry_anchor(tmp_path, monkeypatch):
    monkeypatch.setenv("CANON_STYLES", str(tmp_path))
    p = _project(8)
    quote = "\n\n".join(p.episodes[0].text.split("\n\n")[:4])
    e = library.from_project(p, "등대 문체")
    anchor.set_anchor(p, [1, 2, 3], [quote])
    library.push_project(p)
    assert quote not in library.load(e.id).profile.sample_passages
    assert library.link_state(p)["state"] == "same"


def test_autorun_policy_stops_on_style_distance():
    p = _project(plain=8, polite=6)
    anchor.set_anchor(p, [1, 2, 3])
    d = StateDelta(episode=14, summary="요약")
    assert not any("정착 문체" in r for r in autorun.review_reasons(p, d, None, autorun.Policy(check=False)))
    reasons = autorun.review_reasons(p, d, None, autorun.Policy(check=False, max_style_distance=SYNTH_WARN))
    assert any(r.startswith("정착 문체에서 멀어졌어요") for r in reasons)
    near = autorun.review_reasons(p, StateDelta(episode=8, summary="요약"), None, autorun.Policy(check=False, max_style_distance=SYNTH_WARN))
    assert not any("정착 문체" in r for r in near)


def test_stamp_and_replace_text():
    p = _project(3)
    anchor.stamp(p, 2)
    first = p.episode(2).style_basis
    assert first == anchor.style_basis(p)
    p.style.dos = ["짧게 쓴다"]
    assert anchor.style_basis(p) != first
    pipeline.replace_text(p.episode(2), "새 본문이다.")
    assert p.episode(2).style_basis == ""  # 고른 판은 쓸 때 문체를 모른다
    anchor.stamp(p, 3)
    p.episode(1).style_basis = first
    t = anchor.trend(p)
    assert [x["changed"] for x in t] == [False, False, True]


def test_cue_realized_rows_and_curve():
    talk = "\n\n".join(f'"{i}번째 말이야?" "그래." "정말?"' for i in range(30))
    slow = "\n\n".join("긴 서술이 이어지고 바람이 골목을 따라 천천히 흘러 내려가 창문을 두드렸다. 그는 오래 기다렸다." for _ in range(15))
    fast = "\n\n".join("뛰었다. 넘어졌다. 일어났다." for _ in range(30))
    text = "\n\n".join([talk, slow, fast])
    sheet = CueSheet(cues=[Cue(voice="dialogue", tempo="mid", length=len(talk)), Cue(voice="description", tempo="slow", length=len(slow)),
                           Cue(voice="action", tempo="fast", length=len(fast))])
    rows = cue.realized(sheet, text)
    assert [r["voice_ok"] for r in rows] == [True, True, None]
    assert [r["tempo_ok"] for r in rows] == [None, True, True]
    assert rows[0]["start"] == 0 and rows[-1]["end"] == len(text)
    assert all(text[r["start"]:r["start"] + 1] in ("\n", text[0]) for r in rows)  # 문단 경계에서 자른다
    curve = metrics.tempo_curve(text)
    assert len(curve) >= 3 and curve[0]["dialogue_ratio"] > curve[-1]["dialogue_ratio"]
    assert all(text[c["at"]:c["at"] + 1].strip() for c in curve)
