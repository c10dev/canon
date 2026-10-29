"""three.js 들이기 (static/vendor/three, docs/stage/3d/specs/06-three.md): 파일 · 크기 · sha256 이 README 와 같은지,
addon 의 import 경로, 평소 화면이 three.js 를 읽지 않는지, 로더 경로, 서버가 ES 모듈 MIME 으로 주는지. 실행: python -m pytest tests"""
import hashlib
import re
from pathlib import Path

from .test_web import client  # noqa: F401  (pytest fixture)

STATIC = Path(__file__).resolve().parent.parent / "canon" / "static"
VENDOR = STATIC / "vendor" / "three"
FILES = ["three.module.min.js", "OrbitControls.js", "CSS2DRenderer.js", "LICENSE"]


def _table() -> dict[str, tuple[int, str]]:
    rows = re.findall(r"^\| `([^`]+)` \| `[^`]+` \| (\d+) \| `([0-9a-f]{64})` \|$",
                      (VENDOR / "README.md").read_text(encoding="utf-8"), re.M)
    return {name: (int(size), sha) for name, size, sha in rows}


def test_files_match_readme():
    table = _table()
    assert sorted(table) == sorted(FILES)
    for name in FILES:
        data = (VENDOR / name).read_bytes()
        assert (len(data), hashlib.sha256(data).hexdigest()) == table[name], name


def test_addons_import_local_build():
    for name in ["OrbitControls.js", "CSS2DRenderer.js"]:
        src = (VENDOR / name).read_text(encoding="utf-8")
        assert "from 'three'" not in src and 'from "three"' not in src
        assert "from './three.module.min.js'" in src
    assert "MIT License" in (VENDOR / "LICENSE").read_text(encoding="utf-8")


def test_index_does_not_load_three():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "vendor/" not in html and "three.module" not in html
    assert '<script src="/static/stage3d-load.js"></script>' in html


def test_loader_points_at_vendor():
    src = (STATIC / "stage3d-load.js").read_text(encoding="utf-8")
    base = re.search(r"THREE_DIR = '([^']+)'", src).group(1)
    names = re.findall(r"'([^']+\.js)'", re.search(r"THREE_FILES = \[([^\]]+)\]", src).group(1))
    assert base == "/static/vendor/three/"
    assert names == FILES[:3]
    assert all((VENDOR / n).is_file() for n in names)
    assert "import(" in src and not re.search(r"^\s*import\s", src, re.M)


def test_served_as_javascript(client):
    for name in FILES[:3]:
        r = client.get(f"/static/vendor/three/{name}")
        assert r.status_code == 200
        assert r.headers["content-type"].split(";")[0] in ("text/javascript", "application/javascript")
        assert len(r.content) == (VENDOR / name).stat().st_size
