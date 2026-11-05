"""서버 로그: 실패한 작업의 호출 경로, 취소하지 못한 배치."""
def test_failed_job_logs_traceback(caplog):
    from canon import jobs

    def boom(job):
        raise RuntimeError("터짐")

    with caplog.at_level("ERROR", logger="canon"):
        j = jobs.start("logtest", "suggest", None, "시험", boom)
        for _ in range(200):
            if not j.alive:
                break
            __import__("time").sleep(0.01)
    assert j.status == "error" and j.error == "터짐"
    assert any(r.exc_info and "작업 suggest" in r.getMessage() for r in caplog.records)


def test_cancel_batches_logs_failure(caplog, monkeypatch):
    from canon import autorun

    class Bad:
        def batch_cancel(self, name):
            raise RuntimeError("네트워크")

    monkeypatch.setattr(autorun, "get_llm", lambda stage: Bad())
    run = type("R", (), {"batches": {"3:write": "batches/abc"}})()
    with caplog.at_level("WARNING", logger="canon"):
        autorun._cancel_batches(run)
    assert run.batches == {} and any("batches/abc" in r.getMessage() for r in caplog.records)
