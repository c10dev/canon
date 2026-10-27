"""설정 도우미(static/setup.js)의 josa · composeLogline · loglineChecks · toneText 가 logline.josa · compose · checks · tone_text 와 같은지.
node 가 있을 때만 돈다. Swift 앱(FeatureSetup/Logline.swift)은 여기서 보지 않는다."""
import itertools

import pytest

from canon import logline
from canon.schema import LoglineParts, ToneDials

from .jsvm import dump, needs_node, run_js

WORDS = ["서윤", "서진이", "손님2", "손님3", "벽10", "AI", "로봇 X", "  도현  ", "", "   ", "강", "가", "힣", "각",
         "R2-D2", "007", "주인공(17)", "🗡️", "１", "ㄱ", *(f"방{d}" for d in "0123456789")]
JOSA = [("이", "가"), ("을", "를"), ("은", "는"), ("과", "와"), ("으로", "로")]

PARTS = [
    LoglineParts(),
    LoglineParts(who="서윤"),
    LoglineParts(who="겁 많은 견습 마법사 서윤", why="스승이 사라지자", goal="금지된 탑에 오른다.",
                 block="탑을 지키는 옛 동료가 길을 막는다...", stake="실패하면 마을이 잠긴다"),
    LoglineParts(why="  편지를 받고 ", goal="고향으로 돌아간다"),
    LoglineParts(block="왕국 전체"),
    LoglineParts(stake="목숨."),
    LoglineParts(who="  ", goal="결혼식을 막는다", block="신부"),
    LoglineParts(who="퇴역 형사 X", why="딸이 납치되자", goal="범인을 쫓지만", block="경찰이 막는다", stake="딸의 목숨"),
    LoglineParts(who="A B", why="1", goal="다" * 40, block="b"),
    LoglineParts(who="한" * 60, why="두" * 60, goal="세" * 30 + "다"),
]


@needs_node
def test_josa_matches_server():
    cases = [[w, a, b] for w, (a, b) in itertools.product(WORDS, JOSA)]
    got = run_js(["app.js", "setup.js"], "data.map(([w, a, b]) => josa(w, a, b))", cases)
    assert got == [logline.josa(w, a, b) for w, a, b in cases]


@needs_node
def test_compose_and_checks_match_server():
    expr = "data.map((p) => [composeLogline(p), loglineChecks(p)])"
    got = run_js(["app.js", "setup.js"], expr, [dump(p) for p in PARTS])
    for p, (line, checks) in zip(PARTS, got):
        assert line == logline.compose(p), p
        assert [tuple(c) for c in checks] == logline.checks(p), p
    assert {len(line) >= 40 for line, _ in got} == {True, False}


@needs_node
def test_tone_text_matches_server():
    dials = [ToneDials(dark=d, serious=s, slow=w) for d, s, w in itertools.product([0, 1, 2, 3, 4, 5], [0, 2, 4], [0, 1, 3, -1])]
    got = run_js(["app.js", "setup.js"], "data.map(toneText)", [dump(d) for d in dials])
    assert got == [logline.tone_text(d) for d in dials]


@needs_node
@pytest.mark.xfail(strict=True, reason="어긋남: JS trim 은 BOM(U+FEFF)을 지우고 NEL(U+0085)은 두며 Python strip 은 그 반대다. "
                   "JS length 는 UTF-16 단위라 이모지를 두 글자로 센다")
def test_edge_whitespace_and_length_match_server():
    parts = [LoglineParts(who="﻿서윤"), LoglineParts(who="서윤\x85"),
             LoglineParts(who="검객", why="🗡️" * 10, goal="싸운다", block="적")]
    got = run_js(["app.js", "setup.js"], "data.map((p) => [composeLogline(p), loglineChecks(p).map((c) => c[0])])", [dump(p) for p in parts])
    assert got == [[logline.compose(p), [ok for ok, _ in logline.checks(p)]] for p in parts]
