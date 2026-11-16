"""함수 복잡도 상한 게이트. canon/ 에서 ruff C901(상한 15)을 넘는 함수를 재서 tests/complexity_baseline.txt 와 견준다.

python scripts/complexity_gate.py                   # 견주기. 문제가 있으면 종료 코드 1
python scripts/complexity_gate.py --tighten         # 점수가 내려간 만큼 기준선을 낮춤 (항목을 더하거나 올리지 않음)
python scripts/complexity_gate.py --raise-baseline  # 지금 측정값 전체로 기준선을 다시 씀 (사용자와 정한 뒤에만)
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "complexity_baseline.txt"
LIMIT = 15  # ruff lint.mccabe.max-complexity

_MESSAGE = re.compile(r"`([^`]+)`.*\((\d+) > \d+\)")
_HEADER = (
    "# canon/ 에서 복잡도(ruff C901)가 상한 15를 넘는 함수의 기준선. 형식은 '파일::함수 점수'.\n"
    "# 낮추는 명령: python scripts/complexity_gate.py --tighten\n"
    "# 항목을 더하거나 값을 올리는 변경(--raise-baseline)은 사용자와 정한다.\n"
)


def measure(limit: int = LIMIT, root: Path = ROOT) -> dict[str, int]:
    """canon/ 에서 limit 을 넘는 함수의 {키: 점수}. 키는 '저장소 기준 경로::함수 이름'."""
    cmd = [
        sys.executable, "-m", "ruff", "check", "canon", "--isolated", "--select", "C901",
        "--config", f"lint.mccabe.max-complexity={limit}", "--output-format", "json",
        "--no-cache", "--extend-exclude", "canon/static/vendor",
    ]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"ruff 가 실패했어요 (종료 코드 {proc.returncode}): {proc.stderr}")
    scores: dict[str, int] = {}
    for item in json.loads(proc.stdout or "[]"):
        m = _MESSAGE.search(item["message"])
        if not m:
            continue
        rel = Path(item["filename"]).resolve().relative_to(Path(root).resolve()).as_posix()
        key = f"{rel}::{m.group(1)}"
        scores[key] = max(scores.get(key, 0), int(m.group(2)))
    return scores


def read_baseline(path: Path = BASELINE) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, num = line.rpartition(" ")
        out[key] = int(num)
    return out


def write_baseline(scores: dict[str, int], path: Path = BASELINE) -> None:
    body = "".join(f"{k} {scores[k]}\n" for k in sorted(scores))
    path.write_text(_HEADER + body, encoding="utf-8")


def compare(now: dict[str, int], base: dict[str, int]) -> tuple[list[str], list[str]]:
    """(문제 줄, 정리할 수 있는 줄). 문제 줄이 비면 통과."""
    problems: list[str] = []
    cleanable: list[str] = []
    for key in sorted(now):
        if key not in base:
            problems.append(f"새로 복잡해진 함수예요: {key} {now[key]} (상한 {LIMIT})")
        elif now[key] > base[key]:
            problems.append(f"복잡도가 올랐어요: {key} {base[key]} -> {now[key]}")
        elif now[key] < base[key]:
            cleanable.append(f"{key} {base[key]} -> {now[key]}")
    for key in sorted(base):
        if key not in now:
            cleanable.append(f"{key} {base[key]} -> 상한 아래거나 사라졌어요")
    return problems, cleanable


def tightened(now: dict[str, int], base: dict[str, int]) -> dict[str, int]:
    """기준선을 낮추기만 한 결과. base 에 있는 키만 남기고 값은 min(base, now). now 에 없는 키는 뺀다."""
    return {k: min(v, now[k]) for k, v in base.items() if k in now}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="함수 복잡도 상한 게이트")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--tighten", action="store_true", help="기준선을 낮추기만 해요")
    g.add_argument("--raise-baseline", action="store_true", help="지금 측정값 전체로 기준선을 다시 써요")
    args = ap.parse_args(argv)
    now = measure()
    if args.raise_baseline:
        print("기준선을 올리는 변경은 사용자와 정해요", file=sys.stderr)
        write_baseline(now)
        print(f"기준선을 다시 썼어요 ({len(now)}개).")
        return 0
    base = read_baseline()
    if args.tighten:
        new = tightened(now, base)
        write_baseline(new)
        print(f"기준선을 낮췄어요 ({len(base)}개 -> {len(new)}개).")
        return 0
    problems, cleanable = compare(now, base)
    for line in problems:
        print(f"문제: {line}")
    if cleanable:
        print("정리할 수 있어요 (python scripts/complexity_gate.py --tighten):")
        for line in cleanable:
            print(f"  {line}")
    if problems:
        return 1
    print("복잡도 게이트를 통과했어요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
