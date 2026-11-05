"""서버 오류 문구(static/app.js fmtErr): 검증 오류를 영어 원문 대신 한국어로 쓰고, 사유표가 web.py 와 같은지. node 가 있을 때만 돈다."""
from canon import web
from tests.jsvm import needs_node, run_js


@needs_node
def test_validation_reasons_match_server():
    assert run_js(["app.js"], "VALIDATION_REASON", {}) == web._VALIDATION_REASON


@needs_node
def test_fmterr_validation_is_korean():
    detail = [
        {"type": "string_type", "loc": ["body", "episodes", 3, "plot", "title"], "msg": "Input should be a valid string"},
        {"type": "string_type", "loc": ["body", "episodes", 4, "plot", "title"], "msg": "Input should be a valid string"},
        {"type": "weird_new_type", "loc": ["body", "foo"], "msg": "Something odd"},
    ]
    out = run_js(["app.js"], "fmtErr({ detail: data.detail }, 422)", {"detail": detail})
    assert out == ("입력 형식이 맞지 않아요: '제목' 칸이 글자여야 해요. 고친 뒤 다시 해 보세요\n"
                   "입력 형식이 맞지 않아요: 'foo' 칸이 형식에 맞지 않아요. 고친 뒤 다시 해 보세요")
    assert "Input should" not in out


@needs_node
def test_fmterr_plain_detail():
    assert run_js(["app.js"], "fmtErr({ detail: '작품을 찾을 수 없어요' }, 404)", {}) == "작품을 찾을 수 없어요"
    assert "500" in run_js(["app.js"], "fmtErr({}, 500)", {})
