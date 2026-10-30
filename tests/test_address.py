"""호칭 · 말씨(canon/address.py) 테스트 (mock LLM): 옛 작품 읽힘, 작가가 정하기 · 기록, 바뀜 제안 정리 · 반영 · 남겨 두기 · 되돌리기,
쓰기 · 검수 · 상태 변경안 프롬프트와 장편 예산, 웹 라우트 · 화면 저장 보호, 상태 승인 화면 체크. 실행: python -m pytest tests"""
import contextlib
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from canon import address, autorun, context, features, pipeline, prompts, store
from canon.cli import main
from canon.mock import MOCK_CALLS
from canon.schema import AddressChange, AddressForm, Project, StateDelta

from .test_autorun import Policy, demo  # noqa: F401  (pytest fixture)
from .test_delta_count import APP, EDIT_HARNESS
from .test_serial import _plan_arc, _serial
from .test_storylines import _short
from .test_timeline import LLM, _play
from .test_web import client  # noqa: F401  (pytest fixture)

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"


def _written(p, n):
    pipeline.confirm_plot(p, n)
    p.episode(n).text = pipeline.write_episode(LLM, p, n)
    p.episode(n).status = "written"


def test_old_project_reads_without_address():
    p = Project.model_validate({"meta": {"title": "x"}, "characters": [{"id": "a", "name": "A", "role": ""}],
                                "relationships": [{"a": "a", "b": "a2", "type": "친구"}]})
    assert p.address_forms == [] and p.address_log == [] and p.address_held == []
    assert StateDelta(episode=1, summary="").address_changes == []


def test_set_form_records_after_first_apply():
    p = _short(8)
    address.set_form(p, "hero", "ally", "도현 씨", "해요체")
    assert [(f.speaker, f.listener, f.calls, f.speech) for f in p.address_forms] == [("hero", "ally", "도현 씨", "해요체")]
    assert p.address_log == []  # 1화 반영 전에는 설정을 짜는 중이라 기록하지 않는다
    _play(p, 1, 1)
    address.set_form(p, "hero", "ally", "도현아", "해요체")
    address.set_form(p, "hero", "ally", "도현이", "해요체")  # 같은 화 뒤에 같은 칸을 또 고치면 한 기록
    assert [(r.episode, r.field, r.before, r.after, r.source) for r in p.address_log] == [(1, "calls", "도현 씨", "도현이", "author")]
    address.set_form(p, "hero", "ally", "도현 씨", "해요체")  # 처음 값으로 돌아오면 기록을 지운다
    assert p.address_log == []
    address.set_form(p, "hero", "ally", "", "")
    assert p.address_forms == [] and len(p.address_log) == 2  # 두 칸이 모두 비면 그 방향을 지운다
    with pytest.raises(KeyError):
        address.set_form(p, "hero", "nobody", "x", "")
    with pytest.raises(ValueError):
        address.set_form(p, "hero", "hero", "x", "")


def test_clean_keeps_only_real_changes():
    p = _short(8)
    p.address_forms = [AddressForm(speaker="ally", listener="hero", calls="서윤 씨", speech="해요체")]
    d = StateDelta(episode=2, summary="", address_changes=[
        AddressChange(speaker="ally", listener="hero", calls="서윤 씨", speech=" 해체(반말) "),  # 부르는 말은 그대로라 비운다
        AddressChange(speaker="hero", listener="hero", calls="나"),
        AddressChange(speaker="hero", listener="ghost", calls="유령"),
        AddressChange(speaker="hero", listener="ally", calls="", speech=""),
        AddressChange(speaker="hero", listener="ally", calls="오빠"),
        AddressChange(speaker="hero", listener="ally", calls="도현 오빠"),  # 같은 방향은 뒤의 것
    ])
    features.clean(p, d)
    assert [(x.speaker, x.listener, x.calls, x.speech, x.episode) for x in d.address_changes] == [
        ("ally", "hero", "", "해체(반말)", 2), ("hero", "ally", "도현 오빠", "", 2)]
    assert any("ghost" in w for w in d.warnings)


def test_mock_proposal_review_apply_and_revert():
    p = _play(_short(8), 1, 2)
    _written(p, 3)
    d = pipeline.extract_state(LLM, p, 3)
    assert [(x.speaker, x.listener, x.calls, x.speech) for x in d.address_changes] == [("ally", "hero", MOCK_CALLS, "해체(반말)")]
    pipeline.apply_delta(p, d)
    f = address.find(p, "ally", "hero")
    assert (f.calls, f.speech) == (MOCK_CALLS, "해체(반말)")
    assert [(r.episode, r.field, r.before, r.after, r.source) for r in p.address_log] == [
        (3, "calls", "", MOCK_CALLS, "ai"), (3, "speech", "", "해체(반말)", "ai")]
    address.set_form(p, "hero", "ally", "도현아", "")  # 3화 뒤 작가가 정한 것은 되돌리기에도 남는다
    pipeline.revert(p, 2)
    assert address.find(p, "ally", "hero") is None
    assert address.find(p, "hero", "ally").calls == "도현아"
    assert [(r.episode, r.source) for r in p.address_log] == [(2, "author")]


def test_revert_keeps_author_value_over_ai():
    p = _play(_short(8), 1, 2)
    _written(p, 3)
    pipeline.apply_delta(p, pipeline.extract_state(LLM, p, 3))
    address.set_form(p, "ally", "hero", "서윤 씨", "해체(반말)")  # 반영 뒤 작가가 부르는 말을 고쳤다
    pipeline.revert(p, 2)
    f = address.find(p, "ally", "hero")
    assert f.calls == "서윤 씨" and f.speech == ""  # 작가가 고친 칸은 두고, AI 가 바꾼 그대로인 칸만 돌린다


def test_autorun_and_cli_hold(demo):  # noqa: F811
    run = autorun.start(demo, 3, False, Policy(check=False), foreground=True)
    assert run.status == "done"
    p = store.load(demo)
    assert p.address_forms == [] and [(x.episode, x.calls) for x in p.address_held] == [(3, MOCK_CALLS)]
    assert any("호칭 제안" in e.message for e in run.log)
    address.take_held(p, 0)
    assert address.find(p, "ally", "hero").calls == MOCK_CALLS and p.address_held == []
    assert p.address_log[0].episode == 3
    pipeline.revert(p, 2)
    assert p.address_forms == [] and p.address_log == []


def test_cli_yes_holds_address(demo):  # noqa: F811
    with contextlib.redirect_stdout(io.StringIO()) as out:
        main(["run", "demo", "-y"])
    p = store.load(demo)
    assert p.address_forms == [] and len(p.address_held) == 1
    assert "호칭 · 말씨 바뀜 제안 (지금 → 바꾼 뒤)" in out.getvalue()


def test_features_hold_counts_both():
    p = _short(8)
    from canon.schema import SettingChange
    d = StateDelta(episode=2, summary="", setting_changes=[SettingChange(character_id="hero", field="age", value="20세")],
                   address_changes=[AddressChange(speaker="hero", listener="ally", calls="오빠")])
    assert features.hold(p, d) == 2 and d.setting_changes == [] and d.address_changes == []
    assert len(p.setting_held) == 1 and len(p.address_held) == 1


def test_write_check_state_prompts_use_episode_pairs():
    p = _play(_short(8), 1, 1)
    p.characters.append(p.characters[1].model_copy(update={"id": "far", "name": "먼사람", "tier": "support"}))
    p.address_forms = [AddressForm(speaker="hero", listener="ally", calls="도현 씨", speech="해요체"),
                       AddressForm(speaker="ally", listener="far", calls="형님", speech="하십시오체")]
    pipeline.confirm_plot(p, 2)
    ctx = prompts.build_episode_context(p, 2)
    assert "서윤 → 도현: '도현 씨'라고 부름, 말씨 해요체" in ctx and "형님" not in ctx  # 이번 화 인물끼리만
    assert ctx.index("# 호칭 · 말씨") > ctx.index("# 관계 현재 상태")  # 화마다 바뀌는 블록 쪽
    p.episode(2).text, p.episode(2).status = "서윤은 도현을 불렀다.", "written"
    check = prompts.check_prompt(p, 2)
    assert "'도현 씨'라고 부름" in check and "- 호칭 · 말씨:" in check
    state = prompts.state_prompt(p, 2)
    assert "[호칭 · 말씨]" in state and "address_changes" in state
    p.address_forms = []
    assert "# 호칭 · 말씨" not in prompts.build_episode_context(p, 2) and "- 호칭 · 말씨:" not in prompts.check_prompt(p, 2)
    assert "address_changes" in prompts.state_prompt(p, 2)  # 상태 규칙은 늘 붙는다


def test_serial_block_budget_notes_cut():
    p = _serial()
    _plan_arc(p)
    p.address_forms = [AddressForm(speaker="hero", listener="ally", calls="도현" + "가" * 60, speech="해요체"),
                       AddressForm(speaker="ally", listener="hero", calls="서윤" + "나" * 60, speech="해체(반말)")]
    budget = context.BUDGET["address"]
    context.BUDGET["address"] = 100
    try:
        text = address.block(p, {"hero", "ally"})
    finally:
        context.BUDGET["address"] = budget
    assert "1줄은 예산을 넘어 뺐습니다" in text and text.count("\n- ") == 1


def test_speech_levels_match_js():
    src = (STATIC / "address.js").read_text(encoding="utf-8")
    js = re.findall(r"'([^']+)'", re.search(r"const ADDRESS_LEVELS = \[(.*?)\];", src).group(1))
    assert js == list(address.SPEECH_LEVELS)


def test_web_routes_and_full_save_keeps_address(client):  # noqa: F811
    from canon import store as st

    p = _play(_short(8), 1, 1)
    st.save("ad", p)
    out = client.put("/api/projects/ad/address", json={"speaker": "hero", "listener": "ally", "calls": "도현 씨", "speech": "해요체"}).json()
    assert out["address_forms"] == [{"speaker": "hero", "listener": "ally", "calls": "도현 씨", "speech": "해요체"}]
    assert out["address_log"][0]["source"] == "author"
    out["address_forms"] = []  # 화면의 작품 전체 저장은 호칭을 고치지 않는다 (옛 사본이 덮지 않게)
    out = client.put("/api/projects/ad", json=out).json()
    assert len(out["address_forms"]) == 1
    q = st.load("ad")
    q.address_held = [AddressChange(speaker="ally", listener="hero", calls="서윤아", episode=1),
                      AddressChange(speaker="hero", listener="ally", speech="해체(반말)", episode=1)]
    st.save("ad", q)
    out = client.delete("/api/projects/ad/address-held/1").json()
    assert len(out["address_held"]) == 1
    out = client.post("/api/projects/ad/address-held/0").json()
    assert {(f["speaker"], f["calls"]) for f in out["address_forms"]} == {("hero", "도현 씨"), ("ally", "서윤아")}
    assert client.post("/api/projects/ad/address-held/0").status_code == 400


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_review_leaves_address_unchecked():
    head = EDIT_HARNESS.split("const d = {")[0]
    js = head + """
const d = { summary: '', character_updates: [], events: [], secrets_added: [], relationship_updates: [], new_facts: [],
  foreshadow_planted: [], foreshadow_resolved: [], warnings: [], address_changes: [{ speaker: 'a', listener: 'b', calls: '형', speech: '' }] };
vm.runInContext('setDelta(1, ' + JSON.stringify(d) + ')', ctx);
const off = vm.runInContext('pickedDelta(1).address_changes', ctx);
vm.runInContext("S.picks.h0 = true", ctx);
process.stdout.write(JSON.stringify({ off, on: vm.runInContext('pickedDelta(1).address_changes.length', ctx) }));
"""
    run = subprocess.run(["node", "-e", js, str(APP)], capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {"off": [], "on": 1}
