"""주별 지표 스크립트(scripts/health_metrics.py)의 순수 함수. git · ruff 를 부르지 않는다."""
import importlib.util
from datetime import date
from pathlib import Path


def _mod():
    path = Path(__file__).resolve().parents[1] / "scripts" / "health_metrics.py"
    spec = importlib.util.spec_from_file_location("health_metrics", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _log(*commits):
    out = []
    for week, subject, files in commits:
        out.append(f"@@\x01{week}\x01{subject}")
        out.append("")
        out += [f"{a}\t{d}\t{p}" for a, d, p in files]
    return "\n".join(out) + "\n"


LOG = _log(
    ("2026-W46", "Fix crash", [("10", "2", "canon/a.py"), ("1", "1", "docs/x.md")]),
    ("2026-W46", "Add feature", [("500", "0", "canon/b.js"), ("-", "-", "canon/img.png")]),
    ("2026-W46", "Revert feature", [("3", "3", "canon/c.html")]),
    ("2026-W47", "되돌림 정리", [("4", "0", "canon/d.css")]),
)


def test_parse_log_skips_binary_and_counts():
    ch = _mod().parse_log(LOG)
    assert [c["files"] for c in ch] == [2, 1, 1, 1]
    assert [c["lines"] for c in ch] == [14, 500, 6, 4]
    assert [c["code_added"] for c in ch] == [10, 500, 3, 4]


def test_weekly_rows_group_median_and_ratios():
    rows = _mod().weekly_rows(_mod().parse_log(LOG))
    assert [r[0] for r in rows] == ["2026-W46", "2026-W47"]
    w46 = rows[0]
    assert w46[1] == "3"
    assert w46[2] == "1"  # 파일 수 [2, 1, 1] 의 중앙값
    assert w46[3] == "14"  # 줄 수 [14, 500, 6] 의 중앙값
    assert w46[4] == "33%"  # 400줄 넘는 변경 1/3
    assert w46[5] == "67%"  # fix, revert 2/3
    assert w46[6] == "513"
    assert rows[1][5] == "100%"  # '되돌' 한글 낱말


def test_median_half_value():
    ch = _mod().parse_log(_log(("2026-W01", "a", [("1", "0", "x.py")]), ("2026-W01", "b", [("2", "0", "x.py")])))
    assert _mod().weekly_rows(ch)[0][3] == "1.5"


def test_week_ends_and_stats():
    m = _mod()
    ends = m.week_ends(date(2026, 11, 18), 3)  # 수요일, 이번 주 월요일은 11-16
    assert ends == [date(2026, 11, 9), date(2026, 11, 16), date(2026, 11, 23)]
    assert m.complexity_stats([2, 4, 20]) == (3, "8.67", 20, 1)
    assert m.complexity_stats([]) == (0, "0.00", 0, 0)


def test_markdown_table_shape():
    t = _mod().markdown_table(["a", "b"], [["1", "2"]])
    assert t.splitlines() == ["| a | b |", "|---|---|", "| 1 | 2 |"]
