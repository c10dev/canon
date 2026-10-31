"""반영할 때 본문에 나온 인물을 그 화 등장 인물에 붙이기 (cast.cast_to_add · apply_delta · revert, features 훅) (mock LLM).
플롯 인물 목록에 없는 조연이 본문에 나오면 등장 화 · 기획 인물에서 빠졌다. 이름만 나온 회상 · 언급은 붙이지 않는다."""
import json
import shutil
import subprocess

import pytest

from canon import cast, features, pipeline
from canon.schema import Character, CharacterState, StateDelta, StoryEvent
from tests.test_delta_count import APP, EDIT_HARNESS
from tests.test_serial import _plan_arc, _serial

SMITH = Character(id="smith", name="마르타 부인", role="대장장이", tier="support")
TOM = Character(id="tom", name="톰", role="농부", tier="minor")


def _project():
    """1~(끝-1)화를 반영한 장편. 마지막 화는 본문만 있고, 대장장이 · 톰은 어느 화 플롯 인물 목록에도 없다."""
    p = _serial()
    a = _plan_arc(p)
    p.characters += [SMITH.model_copy(), TOM.model_copy()]
    for n in range(a.start_ep, a.end_ep + 1):
        e = p.episode(n)
        e.text, e.status = f"{n}화 본문. 서윤은 길을 걸었다.", "written"
        if n < a.end_ep:
            pipeline.apply_delta(p, StateDelta(episode=n, summary=f"{n}화 요약"))
    return p, a.end_ep


def _delta(n, **kw) -> StateDelta:
    return StateDelta(episode=n, summary="요약", **kw)


def test_attach_needs_name_in_text_and_delta_involvement():
    p, n = _project()
    p.episode(n).text = "마르타 부인이 망치를 내려놓았다. 서윤은 고개를 숙였다."
    upd = [CharacterState(character_id="smith", emotional_state="흐뭇함")]
    assert cast.cast_to_add(p, _delta(n, character_updates=upd)) == ["smith"]
    assert cast.cast_to_add(p, _delta(n)) == []  # 이름만 나오고 변경안이 다루지 않음: 회상 · 언급
    assert cast.cast_to_add(p, _delta(n, character_updates=[CharacterState(character_id="smith")])) == []  # 빈 상태 변경은 다룬 것이 아니다
    ev = [StoryEvent(episode=n, actor="hero", target="smith", kind="도움", intensity=1)]
    assert cast.cast_to_add(p, _delta(n, events=ev)) == ["smith"]  # 관계 사건의 받은 인물
    p.episode(n).text = "서윤은 대장간 앞을 지났다."
    assert cast.cast_to_add(p, _delta(n, character_updates=upd)) == []  # 다뤘어도 본문에 이름이 없으면 붙이지 않는다


def test_attach_skips_off_candidates_existing_and_single_short_name():
    p, n = _project()
    upd = lambda *ids: [CharacterState(character_id=i, location="마을") for i in ids]  # noqa: E731
    p.episode(n).text = "톰이 웃었다. 마르타 부인과 도현이 왔다."
    p.cast_candidates.append(Character(id="guest", name="나그네", role="", tier="minor"))
    p.episode(n).text += " 나그네가 쉬었다."
    got = cast.cast_to_add(p, _delta(n, character_updates=upd("tom", "smith", "ally", "guest")))
    assert got == ["smith"]  # 톰은 한 글자 이름이 한 번, 도현은 이미 등장 인물, 나그네는 후보
    p.episode(n).text += " 톰은 다시 밭으로 갔다."
    assert cast.cast_to_add(p, _delta(n, character_updates=upd("tom"))) == ["tom"]  # 한 글자 이름은 두 번이면 붙인다
    next(c for c in p.characters if c.id == "smith").context = "off"
    assert cast.cast_to_add(p, _delta(n, character_updates=upd("smith"))) == []  # '넣지 않음' 인물


def test_clean_recounts_and_apply_records_and_revert_removes():
    p, n = _project()
    p.episode(n).text = "마르타 부인이 망치를 내려놓았다."
    d = _delta(n, character_updates=[CharacterState(character_id="smith", emotional_state="흐뭇함")], cast_added=["ally", "nobody"])
    features.clean(p, d)
    assert d.cast_added == ["smith"]  # 받은 값은 버리고 다시 센다
    before = list(p.episode(n).plot.characters)
    pipeline.apply_delta(p, d)
    assert p.episode(n).plot.characters == before + ["smith"]
    assert p.history[-1].cast_added == ["smith"]

    pipeline.revert(p, n - 1)
    assert p.episode(n).plot.characters == before  # 붙인 인물만 뺀다 (원래 등장 인물은 그대로)


def test_apply_keeps_only_what_author_left():
    p, n = _project()
    p.episode(n).text = "마르타 부인이 망치를 내려놓았다."
    before = list(p.episode(n).plot.characters)
    d = _delta(n, character_updates=[CharacterState(character_id="smith", emotional_state="흐뭇함")])
    features.clean(p, d)
    d.cast_added = []  # 상태 승인 화면에서 체크를 풀었다
    pipeline.apply_delta(p, d)
    assert p.episode(n).plot.characters == before and p.history[-1].cast_added == []
    d2 = _delta(n - 1, cast_added=["ally", "ghost"])  # 이미 등장 인물 · 없는 인물은 붙이지 않고 기록에도 남기지 않는다
    cast.apply_delta(p, d2)
    assert d2.cast_added == []


def test_cast_added_is_hidden_from_ai_schema():
    from canon.llm import _inline_refs
    schema = json.dumps(_inline_refs(StateDelta.model_json_schema()), ensure_ascii=False)
    assert "cast_added" not in schema


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_review_picks_cast_added_by_default_and_drops_unchecked():
    head = EDIT_HARNESS.split("const d = {")[0]
    js = head + """
const d = { summary: '', character_updates: [], events: [], secrets_added: [], relationship_updates: [], new_facts: [],
  foreshadow_planted: [], foreshadow_resolved: [], warnings: [], cast_added: ['a', 'b'] };
vm.runInContext('setDelta(1, ' + JSON.stringify(d) + ')', ctx);
const on = vm.runInContext('pickedDelta(1).cast_added', ctx);
vm.runInContext("S.picks.a1 = false", ctx);
process.stdout.write(JSON.stringify({ on, off: vm.runInContext('pickedDelta(1).cast_added', ctx), n: vm.runInContext('deltaCount(S.deltas[1])', ctx) }));
"""
    run = subprocess.run(["node", "-e", js, str(APP)], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {"on": ["a", "b"], "off": ["a"], "n": 2}
