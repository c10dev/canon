"""자동 업데이트 드레인: 새 작업을 거절하고, 기한을 지키고, 작업 수를 잠금 안에서 센다."""
import threading

import pytest

from canon import jobs, web


@pytest.fixture(autouse=True)
def _clean():
    jobs.draining.clear()
    yield
    jobs.draining.clear()


def test_start_refuses_while_draining():
    jobs.draining.set()
    with pytest.raises(jobs.Draining) as e:
        jobs.start("drain-p", "write", 1, "본문", lambda j: None)
    assert "다시 시작" in str(e.value)
    assert isinstance(e.value, ValueError)  # 웹은 400 과 그 문구로 보인다
    assert not [j for j in jobs.listing("drain-p")]


def test_start_keeps_auto_while_draining():
    # 자동 집필은 첫 단계 전에 멈추고 다시 시작한 서버가 이어 가므로 받는다
    jobs.draining.set()
    gate = threading.Event()
    job = jobs.start("drain-auto", "auto", None, "자동 집필", lambda j: gate.wait(5))
    gate.set()
    assert job.kind == "auto"


def test_drain_stops_at_limit_with_running_job():
    gate = threading.Event()
    job = jobs.start("drain-q", "write", 1, "본문", lambda j: gate.wait(5))
    try:
        assert web._drain(lambda: False, limit=0, tick=0.01) is False
        assert jobs.draining.is_set()
    finally:
        gate.set()
    for _ in range(200):
        if job.status != "running":
            break
        threading.Event().wait(0.01)
    assert web._drain(lambda: False, limit=5, tick=0.01) is True


def test_drain_survives_count_error(monkeypatch):
    def boom():
        raise RuntimeError("dictionary changed size during iteration")
    monkeypatch.setattr(jobs, "running", boom)
    assert web._drain(lambda: False, limit=0, tick=0.01) is False


def test_running_counts_under_lock():
    # 다른 스레드가 작업을 더하는 동안에도 순회가 깨지지 않는다
    stop = threading.Event()
    errors = []

    def count():
        while not stop.is_set():
            try:
                jobs.running()
            except RuntimeError as e:
                errors.append(e)
                return

    t = threading.Thread(target=count)
    t.start()
    try:
        for i in range(300):
            jobs.start("drain-r", "write", 1000 + i, "본문", lambda j: None)
    finally:
        stop.set()
        t.join()
    assert not errors
