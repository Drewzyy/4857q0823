from clippr.jobs import JobQueue, PermanentJobError
from clippr.models import Job


def test_retry_backoff_and_failure(ctx):
    q = JobQueue(ctx.db)
    calls = {"n": 0}

    def flaky(jc, payload):
        calls["n"] += 1
        raise RuntimeError("boom")

    q.register("flaky", flaky)
    jid = q.enqueue("flaky", max_attempts=2)
    assert q.run_one()
    with ctx.db.session() as s:
        j = s.get(Job, jid)
        assert j.status == "queued" and j.attempts == 1 and j.run_after is not None
        j.run_after = j.created_at  # skip the backoff wait
    assert q.run_one()
    with ctx.db.session() as s:
        assert s.get(Job, jid).status == "failed"
    assert calls["n"] == 2


def test_idempotency_and_cancel_and_permanent(ctx):
    q = JobQueue(ctx.db)
    q.register("ok", lambda jc, p: {"echo": p["v"]})
    q.register("perm", lambda jc, p: (_ for _ in ()).throw(PermanentJobError("no")))
    a = q.enqueue("ok", {"v": 1}, idempotency_key="k1")
    assert q.enqueue("ok", {"v": 2}, idempotency_key="k1") is None
    b = q.enqueue("ok", {"v": 3})
    assert q.cancel(b)
    p = q.enqueue("perm")
    while q.run_one():
        pass
    with ctx.db.session() as s:
        assert s.get(Job, a).status == "succeeded" and s.get(Job, a).result == {"echo": 1}
        assert s.get(Job, b).status == "cancelled"
        assert s.get(Job, p).status == "failed" and s.get(Job, p).attempts == 1
    assert q.retry(b)


def test_crash_recovery_requeues_running(ctx):
    q = JobQueue(ctx.db)
    q.register("ok", lambda jc, p: None)
    jid = q.enqueue("ok")
    with ctx.db.session() as s:
        s.get(Job, jid).status = "running"  # simulate a crash mid-job
    assert q.recover() == 1
    assert q.run_one()
    with ctx.db.session() as s:
        assert s.get(Job, jid).status == "succeeded"


def test_worker_can_restart_after_stop(ctx):
    import time

    q = JobQueue(ctx.db)
    q.register("ok", lambda jc, p: None)
    q.start(1)
    q.stop()
    jid = q.enqueue("ok")
    q.start(1)
    for _ in range(50):
        with ctx.db.session() as s:
            if s.get(Job, jid).status == "succeeded":
                break
        time.sleep(0.1)
    q.stop()
    with ctx.db.session() as s:
        assert s.get(Job, jid).status == "succeeded"
