#!/bin/sh
# macOS Finder 에서 더블클릭하면 Canon 웹 UI 를 띄우고 브라우저를 연다.
# 이미 켜져 있으면 브라우저만 연다. 터미널 창을 닫거나 Ctrl+C 로 끈다.
cd "$(dirname "$0")/.." || exit 1
PORT="${CANON_PORT:-8000}"
if curl -fs -o /dev/null "http://127.0.0.1:$PORT/"; then
  open "http://127.0.0.1:$PORT/"
  exit 0
fi
[ -f .venv/bin/activate ] && . .venv/bin/activate
exec python -m canon serve --port "$PORT"
