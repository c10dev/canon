"""화면 스크립트 묶음: index.html 의 스크립트 태그를 하나로 바꾸고, 묶음은 파일을 차례대로 잇는다."""
import re

from .jsvm import STATIC
from .test_web import client  # noqa: F401  (pytest fixture)

FILES = re.findall(r'src="/static/([A-Za-z0-9_./-]+\.js)"', (STATIC / "index.html").read_text(encoding="utf-8"))


def test_index_has_one_bundle(client):  # noqa: F811
    html = client.get("/").text
    tags = re.findall(r'<script src="([^"]+)"', html)
    assert len(FILES) > 50 and len(tags) == 1 and tags[0].startswith("/bundle/")
    r = client.get(tags[0])
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    pos = [r.text.index(f"/* ---------- {f} ---------- */") for f in FILES]
    assert pos == sorted(pos)
    assert (STATIC / "app.js").read_text(encoding="utf-8")[:200] in r.text
    old = client.get("/bundle/0000.js")
    assert old.status_code == 200 and old.headers["cache-control"] == "no-cache" and old.text == r.text


def test_bundle_can_be_turned_off(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CANON_NO_BUNDLE", "1")
    tags = re.findall(r'<script src="([^"]+)"', client.get("/").text)
    assert len(tags) == len(FILES)


def test_bundle_parses_as_one_script(client):  # noqa: F811
    import shutil
    import subprocess

    import pytest
    if not shutil.which("node"):
        pytest.skip("node 없음")
    src = client.get(re.findall(r'<script src="([^"]+)"', client.get("/").text)[0]).text
    r = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0, 'utf8'))"], input=src, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]
