"""기본 문체 규칙의 '이 화' 줄(늘려 쓰기)은 화 하나를 통째로 쓰는 호출에만 넣는다 (prompts.prose_rules 의 whole).
문단 연습장 · 본문 부분 수정 · 검수 고침안 · 플레이 장면은 뺀다. 실행: python -m pytest tests"""
from canon import mock, play, promptlab, prompts, promptset
from canon.schema import PromptSetChange

from .test_restate import _two_done
from .test_style_prompts import _project

WHOLE = prompts._WHOLE_ONLY


def test_partial_drops_only_the_whole_episode_line():
    for kw in ({}, {"styled": True}, {"split": True}):
        full, part = prompts.prose_rules(**kw), prompts.prose_rules(**kw, whole=False)
        assert WHOLE in full and WHOLE not in part, kw
        kept = [x for x in full.splitlines() if not x.startswith(f"- {WHOLE}")]
        assert part.splitlines() == kept, kw  # 나머지 줄은 글자까지 같다
        assert len(full.splitlines()) - len(part.splitlines()) == 1, kw


def test_whole_episode_calls_keep_the_line():
    p = _project()
    assert WHOLE in prompts.writer_system(p) and WHOLE in prompts.SYSTEM_WRITER


def test_partial_calls_drop_the_line():
    p = _project()
    for system in (prompts.paragraph_system(p), prompts.reviser_system(p), prompts.SYSTEM_REVISER):
        assert WHOLE not in system
        assert prompts.prose_rules(whole=False) in system


def test_play_scene_drops_the_line(client, monkeypatch):
    _two_done(client)
    p, info = play.start("lh", "pl", player="hero", seed=7)
    seen = []
    real = prompts.play_scene_prompt
    monkeypatch.setattr(prompts, "play_scene_prompt", lambda *a, **k: seen.append(real(*a, **k)) or seen[-1])
    play.scene(mock.MockLLM(), p, info, "")
    assert seen and "[문체 기본 규칙]" in seen[0] and WHOLE not in seen[0]


def test_piece_text_matches_partial_kinds():
    """프롬프트 보기 · 프롬프트 세트가 찾는 조각 글은 그 갈래의 시스템 글에 글자 그대로 있다."""
    p = _project()
    for kind in prompts.PARTIAL_KINDS:
        text = prompts.piece_text(p, 1, "prose_rules", kind)
        assert WHOLE not in text, kind
    assert prompts.piece_text(p, 1, "prose_rules", "passage") in prompts.reviser_system(p)
    assert prompts.piece_text(p, 1, "prose_rules", "paragraph") in prompts.paragraph_system(p)
    assert WHOLE in prompts.piece_text(p, 1, "prose_rules", "episode")


def test_promptset_swaps_prose_rules_in_passage(tmp_path, monkeypatch):
    """본문 부분 수정 갈래에서도 실험 판의 문체 기본 규칙이 끼워진다 (견본 글이 시스템 글과 같아야 찾는다)."""
    monkeypatch.setenv("CANON_PROMPTSETS", str(tmp_path / "sets"))
    p = promptlab.example_project()
    n = max(e.plot.number for e in p.episodes if e.text)
    system, prompt, _ = prompts.view_request(p, n, "passage")
    ps = promptset.create("규칙 바꾸기", "passage")
    ps = promptset.update(ps.id, ps.name, "passage", [PromptSetChange(piece="prose_rules", text="[바꾼 규칙] ")], "")
    s2, _, rows = promptset.apply(p, n, "passage", system, prompt, ps)
    assert rows[0]["state"] == "applied" and "[바꾼 규칙] " in s2 and WHOLE not in system
