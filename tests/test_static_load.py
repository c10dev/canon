"""화면 파일을 index.html 차례대로 한 vm 에 모두 읽어, 전역 이름이 겹치거나 문법이 깨진 파일이 없는지 본다.
브라우저는 겹친 이름(let · const · class)에서 그 파일 전체를 버려 화면이 뜨지 않는다. node 가 있을 때만 돈다."""
import re

from tests.jsvm import STATIC, needs_node, run_js


@needs_node
def test_all_static_scripts_load_together():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    files = [m for m in re.findall(r'src="/static/([^"]+\.js)"', html)]
    assert "app.js" in files and len(files) > 20
    assert run_js(files, "typeof S === 'object' && typeof render === 'function'", {}) is True
