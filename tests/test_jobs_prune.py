"""끝난 작업 정리(jobs._prune): 멈췄지만 아직 AI 응답을 기다리는 작업은 오래돼도 목록에 남긴다."""
import threading
import time

from canon import jobs


def _wait_until(cond, limit=5.0):
    end = time.time() + limit
    while not cond() and time.time() < end:
        time.sleep(0.01)
    return cond()


def test_stopped_job_waiting_on_ai_stays_listed():
    gate = threading.Event()
    job = jobs.start("prune-p", "write", 3, "본문", lambda j: gate.wait(5))
    assert _wait_until(lambda: job.alive)
    jobs.stop(job.id)
    job.finished -= jobs.KEEP_SECONDS + 1
    jobs.start("prune-q", "check", 1, "검수", lambda j: None)  # 새 작업을 시작할 때 정리한다
    assert jobs.waiting_on("prune-p", 3) is job and jobs.lingering("prune-p", "write", 3) is job
    gate.set()
    assert _wait_until(lambda: not job.alive)
    jobs.start("prune-q", "check", 2, "검수", lambda j: None)
    assert jobs.get(job.id) is None  # 응답이 끝나면 그때 정리한다
