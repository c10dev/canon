"""화면마다 늘 보이는 안내 문장 수를 센다 (UX 일감 09 · 13).

mock LLM 서버를 임시 CANON_HOME 에 띄우고, Playwright 로 화면을 열어 센다.
작품은 복사본만 쓴다. 원본 작품 폴더는 바꾸지 않는다.

    pip install playwright && python -m playwright install chromium
    python scripts/count_copy.py --project projects/demo
    python scripts/count_copy.py --project projects/demo --shots /tmp/copy-before --json

세는 것
- 작품 화면의 본문 칸(`main.main`) 안에서 지금 보이는 글만 센다.
- 사이드바, 대화 에이전트 패널, 알림은 세지 않는다.
- 버튼 · 입력칸 · 본문 원고 · 제목 · 칩 · 표 안의 글은 세지 않는다.
- 빈 상태(`.empty`)의 글은 세지 않는다. 그 칸에 무엇이 생기면 사라지는 글이라 늘 보이는 글이 아니다.
- 닫힌 `<details>` 안, 툴팁(`title`), 입력칸 예시 글(placeholder)은 보이지 않으므로 세지 않는다.
- 남은 글을 문장으로 나눠 '요'로 끝나는 문장(해요체 안내)을 센다.

화면을 더할 때는 SCREENS 에 (이름, 주소 뒤쪽) 한 줄을 더한다.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (화면 이름, 작품 주소 뒤에 붙는 경로). 빈 경로는 작품 홈이다.
SCREENS: list[tuple[str, str]] = [
    ("작품 홈", ""),
    ("설정 도우미", "/setup"),
    ("문체 레퍼런스", "/style"),
    ("기승전결 · 플롯", "/arc"),
    ("집필", "/write/1"),
]

# 세지 않는 자리. 버튼과 입력칸, 작가의 원고와 데이터, 제목, 그리고 이 화면 밖의 칸이다.
SKIP = ", ".join([
    "button", "a.btn", "input", "textarea", "select", "option",
    "h1", "h2", "h3", "h4", "[contenteditable]", ".prose", ".chip", "table", "svg", ".empty",
    ".sidebar", ".chat-dock", "#toasts", "script", "style",
])

# 브라우저 안에서 보이는 글 조각을 블록 단위로 모은다.
COLLECT = """(skip) => {
  const main = document.querySelector('main.main');
  if (!main) return [];
  const blocks = new Map();
  const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
  for (let t = walker.nextNode(); t; t = walker.nextNode()) {
    const s = t.nodeValue.trim();
    if (!s) continue;
    const el = t.parentElement;
    if (!el || el.closest(skip)) continue;
    if (el.checkVisibility && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
    if (!el.getClientRects().length) continue;
    const block = el.closest('p, li, div, dd, dt, blockquote, figcaption, section, span.hint') || el;
    blocks.set(block, (blocks.get(block) || '') + ' ' + s);
  }
  return [...blocks.values()].map((s) => s.replace(/\\s+/g, ' ').trim());
}"""


def sentences(text: str) -> list[str]:
    """글 조각을 문장으로 나누고 '요'로 끝나는 문장만 돌려준다."""
    out, cur = [], ""
    for ch in text:
        cur += ch
        if ch in ".?!" and cur.rstrip(".?! )").endswith("요"):
            out.append(cur.strip())
            cur = ""
    tail = cur.strip()
    if tail.rstrip(".?! )").endswith("요"):
        out.append(tail)
    return out


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(home: Path, port: int) -> subprocess.Popen:
    env = {**os.environ, "CANON_HOME": str(home), "CANON_LLM": "mock", "CANON_NO_BROWSER": "1",
           "CANON_CONFIG": str(home / "config.json")}
    for k in ("CANON_USAGE", "CANON_STYLES", "CANON_RULES", "CANON_REFS", "CANON_STUDIO", "CANON_PROMPTLAB"):
        env.pop(k, None)
    proc = subprocess.Popen([sys.executable, "-m", "canon", "serve", "--port", str(port), "--no-update"],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/"
    for _ in range(100):
        try:
            urllib.request.urlopen(url, timeout=1)
            return proc
        except OSError:
            if proc.poll() is not None:
                raise SystemExit("서버가 시작하지 않았어요")
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("서버가 20초 안에 열리지 않았어요")


def count(base: str, name: str, shots: Path | None, width: int) -> dict:
    from playwright.sync_api import sync_playwright

    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 1000})
        for label, path in SCREENS:
            page.goto(f"{base}#/p/{name}{path}")
            page.wait_for_selector("main.main", timeout=15000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(600)
            found = [s for block in page.evaluate(COLLECT, SKIP) for s in sentences(block)]
            out[label] = found
            if shots:
                safe = label.replace(" · ", "-").replace(" ", "-")
                page.screenshot(path=str(shots / f"{safe}.png"), full_page=True)
        browser.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default="projects/demo", help="세어 볼 작품 폴더 (복사해서 쓴다)")
    ap.add_argument("--shots", default="", help="화면 캡처를 둘 폴더 (저장소 밖을 권함)")
    ap.add_argument("--width", type=int, default=1440, help="창 폭(px)")
    ap.add_argument("--json", action="store_true", help="찾은 문장까지 JSON 으로 찍기")
    a = ap.parse_args()

    src = Path(a.project).resolve()
    if not (src / "project.json").exists():
        raise SystemExit(f"{src} 에 project.json 이 없어요")
    shots = Path(a.shots).resolve() if a.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        shutil.copytree(src, home / src.name, ignore=shutil.ignore_patterns("backups"))
        port = free_port()
        proc = start_server(home, port)
        try:
            found = count(f"http://127.0.0.1:{port}/", src.name, shots, a.width)
        finally:
            proc.terminate()
            proc.wait(timeout=10)
    if a.json:
        print(json.dumps(found, ensure_ascii=False, indent=2))
        return
    for label, lines in found.items():
        print(f"{label}\t{len(lines)}")


if __name__ == "__main__":
    main()
