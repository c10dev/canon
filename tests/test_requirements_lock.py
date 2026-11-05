"""requirements.txt 의 패키지가 모두 requirements.lock 에 버전과 함께 있는지 본다 (의존성을 더하고 잠금을 다시 만들지 않은 경우)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_lock_pins_every_requirement():
    wanted = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            wanted.add(_norm(re.split(r"[<>=!~\[; ]", line)[0]))
    pinned = {_norm(m.group(1)) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==", (ROOT / "requirements.lock").read_text(encoding="utf-8"), re.M)}
    assert wanted - pinned == set(), "requirements.lock 을 다시 만드세요 (AGENTS.md '개발 명령')"
