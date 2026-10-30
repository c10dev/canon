"""쓰기 블록 시험(canon/blocktrial.py)과 설계 메모 옮김 지표 테스트 (mock LLM)."""
import os
import tempfile

os.environ.setdefault("CANON_HOME", tempfile.mkdtemp())  # store 를 먼저 불러와도 저장소의 projects/ 를 쓰지 않게

from canon import blocktrial, pipeline, prompts  # noqa: E402
from canon.mock import MockLLM  # noqa: E402
from canon.schema import BoardScene, Storyboard  # noqa: E402

from .test_statwin import _play  # noqa: E402
from .test_storylines import _short  # noqa: E402

LLM = MockLLM()


def _trial():
    return _play(_short(8), 1, 3)


def test_memo_copied_finds_moved_memo_sentences():
    p = _trial()
    ep = p.episode(2)
    ep.plot.emotional_shift = "서윤: 문을 걸어 잠그고 등을 돌린 채 한참을 서 있다"
    ep.storyboard = Storyboard(scenes=[BoardScene(goal="열쇠를 몰래 돌려받기", turn="창밖에서 낯선 발소리가 멈춘다")])
    text = "비가 왔다. 서윤은 문을 걸어 잠그고 등을 돌린 채 한참을 서 있었다. 그때 창밖에서 낯선 발소리가 멈춘다."
    moved = pipeline.memo_copied(p, 2, text)
    assert len(moved) == 2 and "비가 왔다." not in moved
    assert pipeline.memo_copied(p, 2, "비가 왔다. 서윤은 고개를 들었다.") == []
    ep.text = text
    _, warns = pipeline.style_drift(p, 2)
    assert any(w.startswith("설계 메모를 옮긴 문장 2개") for w in warns)


def test_variants_change_only_the_copy():
    p = _trial()
    p.style.sentence_rhythm = "짧은 문장과 긴 문장을 섞는다."
    base = blocktrial.before(p, 3)
    q, kw = blocktrial.variant(base, "no_profile")
    assert kw == {} and q.style.sentence_rhythm == "" and q.style.sample_passages == base.style.sample_passages
    assert base.style.sentence_rhythm  # 사본만 바꾼다
    assert len(prompts.episode_prompt(q, 3)) < len(prompts.episode_prompt(base, 3))
    assert blocktrial.variant(base, "no_board")[1] == {"use_board": False}
    q, _ = blocktrial.variant(base, "no_knows")
    assert all(not s.knows for s in q.states)
    try:
        blocktrial.variant(base, "nope")
        raise AssertionError("막혀야 한다")
    except ValueError:
        pass


def test_score_estimate_and_run_record():
    from canon import research, store

    p = _trial()
    assert blocktrial.candidates(p) == [1, 2, 3] and blocktrial.default_pick([1, 2, 3], 2) == [2, 3]
    s = blocktrial.score(blocktrial.before(p, 2), 2, "서윤은 숨을 내쉬었다. 그는 웃었다, 그리고 울었다.")
    assert s["cliche_per_1k"] > 0 and s["comma_ratio"] is not None and s["memo_copied"] == 0
    est = blocktrial.estimate(p, [2, 3], repeats=2, conditions=["base", "no_profile"])
    assert est["writes"] == 8 and all(r["input_tokens"] > 0 for r in est["rows"]) and est["priced"]
    store.save("bt", p)
    res = blocktrial.run("bt", store.load("bt"), LLM, [2], conditions=["base", "no_profile"])
    assert [s["condition"] for s in res["summary"]] == ["base", "no_profile"] and len(res["drafts"]) == 2
    assert research.history("bt")[0]["kind"] == "blocks"
    assert research.load_compare("bt", 2)["kind"] == "blocks"
    assert store.load("bt").model_dump() == p.model_dump()  # 작품은 바꾸지 않는다
    assert "스타일 프로필 글 빼기" in blocktrial.describe(res)
    for bad in ({"episodes": [9]}, {"episodes": [2], "conditions": ["nope"]}, {"episodes": [2], "repeats": 9}):
        try:
            blocktrial.run("bt", p, LLM, bad["episodes"], bad.get("repeats", 1), bad.get("conditions"))
            raise AssertionError("막혀야 한다")
        except ValueError:
            pass
