"""에이전트 안내 문서(AGENTS.md, docs/modules/)의 모양을 본다.

- AGENTS.md 는 모든 작업에 실리는 입구라 Codex 가 기본으로 합치는 32 KiB 안에 둔다.
- docs/modules/ 는 모듈 지도다. canon/ 의 파일마다 이름이 어딘가에 있어야 한다.
- 여러 PR 이 같은 줄을 고쳐 충돌하지 않게 한 줄에 사실 하나(300자 이하), 줄 끝에 잇는 문장부호 없음, 절은 경로 차례.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "AGENTS.md"
MODULES = ROOT / "docs" / "modules"
LINE_MAX = 300


def _module_docs():
    return sorted(MODULES.glob("*.md"))


def test_agents_md_fits_codex_budget():
    assert AGENTS.stat().st_size <= 32 * 1024, "AGENTS.md 가 32 KiB 를 넘었어요. 자세한 내용은 docs/modules/ 로 옮겨요"


def test_agents_md_links_exist():
    text = AGENTS.read_text(encoding="utf-8")
    for link in re.findall(r"\]\(([^)#]+)\)", text):
        assert (ROOT / link).exists(), link
    for doc in _module_docs():
        assert f"docs/modules/{doc.name}" in text, f"AGENTS.md 의 '언제 무엇을 읽나'에 {doc.name} 이 없어요"


def test_every_canon_file_is_mapped():
    text = "\n".join(p.read_text(encoding="utf-8") for p in _module_docs())
    files = [p for p in (ROOT / "canon").glob("*.py") if p.name not in ("__init__.py", "__main__.py")]
    static = ROOT / "canon" / "static"
    files += [p for p in static.iterdir() if p.suffix in (".js", ".css", ".html")]
    missing = sorted(p.name for p in files if not re.search(rf"(?<![\w-]){re.escape(p.name)}\b", text))
    assert not missing, f"docs/modules/ 에 설명이 없는 파일: {missing}"


def test_module_doc_lines():
    for doc in _module_docs():
        heads = []
        for n, line in enumerate(doc.read_text(encoding="utf-8").split("\n"), 1):
            where = f"{doc.name}:{n}"
            assert len(line) <= LINE_MAX, f"{where} 줄이 {len(line)}자예요. 사실마다 줄을 나눠요"
            if line.lstrip().startswith("- "):
                assert not re.search(r"[,·;]\s*$", line), f"{where} 줄 끝에 잇는 문장부호가 있어요"
            if line.startswith("### "):
                heads.append(line)
        assert heads == sorted(heads), f"{doc.name} 의 절(### 경로)이 차례대로가 아니에요"
        assert len(heads) == len(set(heads)), f"{doc.name} 에 같은 절이 둘 있어요"
