"""관계가 가 닿을 곳(Relationship.destination): 기획 프롬프트에만 들어가고 쓰기 · 검수 · 상태에는 들어가지 않는다,
설정 대화로 다듬기가 비운 값으로 지우지 않는다, 설정 화면이 목적지가 섞인 '어떤 사이'를 알린다. 실행: python -m pytest tests"""
from canon import prompts, setupchat
from canon.schema import Relationship, SetupRevision

from .jsvm import needs_node, run_js
from .test_serial import _plan_arc, _serial
from .test_storylines import _short
from .test_timeline import _play

DEST = "서로의 목숨을 맡기는 연인"


def _with_dest(p):
    r = next(r for r in p.relationships if {r.a, r.b} == {"hero", "ally"})
    r.destination = DEST
    return p


def test_old_file_reads():
    assert Relationship.model_validate({"a": "x", "b": "y", "type": "앙숙"}).destination == ""


def test_rels_plan_only():
    p = _with_dest(_short(8))
    assert DEST in prompts.rels(p) and DEST not in prompts.rels(p, plan=False)
    bare = _short(8)
    assert '"destination"' not in prompts.rels(bare)  # 적지 않았으면 칸도 넣지 않는다 (예전 프롬프트 그대로)


def test_short_prompts():
    p = _with_dest(_play(_short(8), 1, 2))
    assert DEST in prompts.plot_prompt(p, 3, 8) and DEST in prompts.arc_prompt(p)
    for text in (prompts.episode_prompt(p, 3), prompts.check_prompt(p, 2), prompts.state_prompt(p, 2)):
        assert DEST not in text


def test_serial_prompts():
    p = _serial(40)
    a = _plan_arc(p)
    r = p.relationships[0]
    r.destination = DEST
    assert DEST in prompts.serial_plot_prompt(p, a.start_ep, a.end_ep)
    block = prompts.destination_block(p)
    assert block.startswith("\n[관계가 가 닿을 곳") and DEST in block
    assert prompts.destination_block(p, {"nobody"}) == ""


def test_setup_chat_keeps_destination_when_empty():
    p = _with_dest(_short(8))
    r = next(r for r in p.relationships if {r.a, r.b} == {"hero", "ally"})
    rev = SetupRevision(reply="관계를 다듬었어요",
                        relationships=[Relationship(a=r.a, b=r.b, type="서로 의심하는 동료", description="")])
    out = setupchat.clean(p, rev)
    assert out.relationships and out.relationships[0].destination == DEST  # 비운 값은 지우는 제안이 아니다
    rev = SetupRevision(reply="방향을 바꿨어요", relationships=[Relationship(a=r.a, b=r.b, type=r.type, destination="원수")])
    assert setupchat.clean(p, rev).relationships[0].destination == "원수"


def test_setup_prompt_rule():
    p = _short(8)
    assert "destination 에 따로 적습니다" in prompts.setup_prompt(p)


@needs_node
def test_setup_screen_dest_note():
    got = run_js(["app.js", "home.js", "setup.js"],
                 "data.map((t) => relDestNote({type: t}) !== '')", ["앙숙에서 연인으로", "적에서 동료로", "오빠의 친구", "연인"])
    assert got == [True, True, False, False]
