"""함수 복잡도 게이트 (scripts/complexity_gate.py). 새로 복잡한 함수와 기준선 함수의 악화를 막는다."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (
    "함수를 나눠서 복잡도를 낮춰요. 나누기 어려우면 멈추고 사용자에게 알려요. "
    "기준선(tests/complexity_baseline.txt)을 올리는 변경은 사용자와 정해요."
)


def _gate():
    path = ROOT / "scripts" / "complexity_gate.py"
    spec = importlib.util.spec_from_file_location("complexity_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_new_or_worse_complex_functions():
    gate = _gate()
    problems, _ = gate.compare(gate.measure(), gate.read_baseline())
    assert not problems, "\n".join(problems) + "\n" + GUIDE


def test_baseline_file_shape():
    gate = _gate()
    keys = []
    for line in gate.BASELINE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, _, num = line.rpartition(" ")
        assert key and num.isdigit(), f"'키 정수' 꼴이 아니에요: {line!r}"
        assert int(num) > gate.LIMIT, f"값이 상한 {gate.LIMIT} 이하예요: {line!r}"
        keys.append(key)
    assert keys == sorted(keys), "키 차례로 정렬되어 있지 않아요"
    assert len(keys) == len(set(keys)), "중복 키가 있어요"


def test_compare_rules():
    gate = _gate()
    base = {"a.py::f": 20, "a.py::g": 30, "a.py::h": 25}
    now = {"a.py::f": 20, "a.py::g": 31, "a.py::h": 18, "b.py::new": 16}
    problems, cleanable = gate.compare(now, base)
    assert len(problems) == 2
    assert any("a.py::g" in p for p in problems)
    assert any("b.py::new" in p for p in problems)
    assert len(cleanable) == 1 and "a.py::h" in cleanable[0]
    problems, cleanable = gate.compare({"a.py::f": 20}, base)
    assert problems == []
    assert {k.split()[0] for k in cleanable} == {"a.py::g", "a.py::h"}
    assert gate.compare(base, base) == ([], [])


def test_tightened_never_adds_or_raises():
    gate = _gate()
    base = {"a.py::f": 20, "a.py::g": 30, "a.py::gone": 40}
    now = {"a.py::f": 18, "a.py::g": 35, "b.py::new": 99}
    assert gate.tightened(now, base) == {"a.py::f": 18, "a.py::g": 30}
