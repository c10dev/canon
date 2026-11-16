"""주별 코드 건강 지표 표. 표 1 은 주말 시점 코드(크기 · 복잡도 · 경고 밀도), 표 2 는 주별 변경 크기.

python scripts/health_metrics.py            # 최근 8주
python scripts/health_metrics.py --weeks 4
python scripts/health_metrics.py --no-snapshots   # git log 만 쓰는 '변경' 표만 (빠름)
로그 글을 줄로 바꾸는 함수는 순수 함수다(tests/test_health_metrics.py). git · ruff 는 아래쪽 함수만 부른다.
"""
import argparse
import json
import re
import statistics
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX_WORDS = ("fix", "revert", "hotfix", "regression", "rollback", "수정", "되돌")
CODE_EXTS = (".py", ".js", ".html", ".css")
BIG_CHANGE = 400
BIG_FILE = 3000
VENDOR = "canon/static/vendor"
WIDE_SELECT = "E,F,W,B,C901,PLR0912,PLR0913,PLR0915"
_SCORE = re.compile(r"\((\d+) > \d+\)")

CHANGE_HEADER = ["주", "변경 수", "파일 수 중앙값", "줄 수 중앙값", "400줄 넘는 변경", "고침 · 되돌림", "추가 코드 줄"]
SNAP_HEADER = ["시점", "canon py 줄", "tests py 줄", "함수 수", "평균 복잡도", "최대 복잡도",
               "15 초과 함수", "넓은 규칙 경고", "경고/1,000줄", "3,000줄 넘는 파일"]


# ---- 순수 함수: git log 글 -> 표 ----

def parse_log(text: str) -> list[dict]:
    """`git log --first-parent -m --numstat --date=format:%G-W%V --format=@@%x01%ad%x01%s` 출력을 변경 목록으로 바꾼다.
    바이너리(numstat 의 '-')는 뺀다."""
    changes: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        if line.startswith("@@\x01"):
            _, week, subject = line.split("\x01", 2)
            cur = {"week": week, "subject": subject, "files": 0, "lines": 0, "code_added": 0}
            changes.append(cur)
        elif cur is not None and line.strip():
            parts = line.split("\t", 2)
            if len(parts) != 3 or parts[0] == "-" or parts[1] == "-":
                continue
            added, deleted, path = int(parts[0]), int(parts[1]), parts[2]
            cur["files"] += 1
            cur["lines"] += added + deleted
            if path.endswith(CODE_EXTS):
                cur["code_added"] += added
    return changes


def is_fix(subject: str) -> bool:
    low = subject.lower()
    return any(w in low for w in FIX_WORDS)


def _pct(n: int, total: int) -> str:
    return f"{n / total * 100:.0f}%" if total else "0%"


def _num(x: float) -> str:
    return str(int(x)) if x == int(x) else f"{x:.1f}"


def weekly_rows(changes: list[dict]) -> list[list[str]]:
    """ISO 주마다 한 줄 (오래된 주부터)."""
    by_week: dict[str, list[dict]] = {}
    for c in changes:
        by_week.setdefault(c["week"], []).append(c)
    rows = []
    for week in sorted(by_week):
        cs = by_week[week]
        n = len(cs)
        rows.append([
            week,
            str(n),
            _num(statistics.median(c["files"] for c in cs)),
            _num(statistics.median(c["lines"] for c in cs)),
            _pct(sum(c["lines"] > BIG_CHANGE for c in cs), n),
            _pct(sum(is_fix(c["subject"]) for c in cs), n),
            str(sum(c["code_added"] for c in cs)),
        ])
    return rows


def markdown_table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def week_ends(today: date, weeks: int) -> list[date]:
    """최근 weeks 개 ISO 주의 '다음 월요일' 날짜 (오래된 주부터). 마지막은 이번 주."""
    monday = today - timedelta(days=today.weekday())
    return [monday + timedelta(days=7 * (i + 1)) for i in range(-weeks + 1, 1)]


def complexity_stats(scores: list[int], limit: int = 15) -> tuple[int, str, int, int]:
    """(함수 수, 평균, 최대, limit 초과 수)."""
    if not scores:
        return 0, "0.00", 0, 0
    return len(scores), f"{sum(scores) / len(scores):.2f}", max(scores), sum(s > limit for s in scores)


# ---- git · ruff 를 부르는 부분 ----

def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def _ruff_json(cwd: Path, *args: str) -> list[dict]:
    cmd = [sys.executable, "-m", "ruff", "check", "canon", "--isolated", *args,
           "--no-cache", "--output-format", "json"]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"ruff 가 실패했어요: {proc.stderr}")
    return json.loads(proc.stdout or "[]")


def _count_lines(folder: Path, suffixes: tuple[str, ...]) -> tuple[int, list[int]]:
    total, sizes = 0, []
    for p in sorted(folder.rglob("*")):
        if p.suffix not in suffixes or not p.is_file() or VENDOR in p.as_posix():
            continue
        n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        total += n
        sizes.append(n)
    return total, sizes


def snapshot_row(rev: str, label: str, workdir: Path) -> list[str]:
    archive = subprocess.run(["git", "archive", rev, "canon", "tests"], cwd=ROOT, capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(workdir)], input=archive.stdout, check=True)
    canon_lines, _ = _count_lines(workdir / "canon", (".py",))
    tests_lines, _ = _count_lines(workdir / "tests", (".py",))
    _, sizes = _count_lines(workdir / "canon", (".py", ".js"))
    funcs = _ruff_json(workdir, "--select", "C901", "--config", "lint.mccabe.max-complexity=0",
                       "--extend-exclude", VENDOR)
    scores = [int(m.group(1)) for f in funcs if (m := _SCORE.search(f["message"]))]
    n, avg, mx, over = complexity_stats(scores)
    wide = len(_ruff_json(workdir, "--select", WIDE_SELECT, "--config", "lint.mccabe.max-complexity=15"))
    density = f"{wide / canon_lines * 1000:.1f}" if canon_lines else "0.0"
    return [label, str(canon_lines), str(tests_lines), str(n), avg, str(mx), str(over), str(wide), density,
            str(sum(s > BIG_FILE for s in sizes))]


def snapshot_rows(weeks: int) -> tuple[list[list[str]], int]:
    """(표 1 줄들, 기록이 있는 주 수). 오래된 시점부터, 마지막 줄은 HEAD. 기록이 없는 주는 건너뛰고, 같은 커밋은 한 줄로 합친다."""
    ends = week_ends(date.today(), weeks)
    revs: list[str] = []
    found = 0
    for i, end in enumerate(ends):
        if i == len(ends) - 1:
            rev = _git("rev-parse", "HEAD").strip()
        else:
            rev = _git("rev-list", "-1", "--first-parent", f"--before={end.isoformat()} 00:00", "HEAD").strip()
        if rev:
            found += 1
        if rev and rev not in revs:
            revs.append(rev)
    rows = []
    for rev in revs:
        when = _git("log", "-1", "--format=%cs", rev).strip()
        with tempfile.TemporaryDirectory() as tmp:
            rows.append(snapshot_row(rev, f"{when} {rev[:7]}", Path(tmp)))
    return rows, found


def change_rows(weeks: int) -> list[list[str]]:
    text = _git("log", "--first-parent", "-m", "--numstat", "--date=format:%G-W%V", "--format=@@%x01%ad%x01%s")
    return weekly_rows(parse_log(text))[-weeks:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="주별 코드 건강 지표 표")
    ap.add_argument("--weeks", type=int, default=8, help="볼 주 수 (기본 8)")
    ap.add_argument("--no-snapshots", action="store_true", help="git log 만 쓰는 '변경' 표만 찍어요")
    args = ap.parse_args(argv)
    if not args.no_snapshots:
        rows, found = snapshot_rows(args.weeks)
        print("## 주말 시점 코드\n")
        print(markdown_table(SNAP_HEADER, rows))
        print("\n넓은 규칙은 CI 의 `ruff check`(E9 · F)보다 넓어요. 추세만 봐요.")
        if found < args.weeks:
            print(f"\n기록이 {found}주뿐이에요")
        print()
    rows = change_rows(args.weeks)
    print("## 주별 변경\n")
    print(markdown_table(CHANGE_HEADER, rows))
    if len(rows) < args.weeks:
        print(f"\n기록이 {len(rows)}주뿐이에요")
    return 0


if __name__ == "__main__":
    sys.exit(main())
