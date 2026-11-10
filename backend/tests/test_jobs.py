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


def test_a_stuck_job_is_given_up_on_and_the_queue_keeps_moving(ctx):
    import threading, time
    from datetime import datetime, timedelta, timezone
    db = ctx.db
    q = JobQueue(db)
    release, done, told = threading.Event(), [], []
    q.register("slow", lambda jc, pl: release.wait(30) and {})
    q.register("quick", lambda jc, pl: done.append(1) or {})
    q.heavy, q.heavy_limit = {"slow"}, lambda: 1
    q.time_limits, q.on_timeout = {"slow": 60}, {"slow": lambda pl: told.append(pl)}
    q._threads = []
    stuck_id = q.enqueue("slow", {"n": 1})
    q._workers = 1
    t = threading.Thread(target=q.run_one, daemon=True); t.start(); q._threads.append(t)
    time.sleep(0.3)
    with db.session() as s:  # pretend it has been running for two minutes
        s.get(Job, stuck_id).started_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    q._reap_stuck()
    with db.session() as s:
        j = s.get(Job, stuck_id)
        assert j.status == "failed" and "no progress for 1 minutes" in j.error
    assert told == [{"n": 1}]
    q.enqueue("quick", {})
    deadline = time.time() + 5
    while not done and time.time() < deadline:
        time.sleep(0.1)
    assert done  # a replacement worker picked up the next job while the stuck one is still inside its handler
    q._stop.set(); release.set()


def test_a_long_job_that_keeps_making_progress_is_left_alone(ctx):
    import threading
    from datetime import datetime, timedelta, timezone
    q = JobQueue(ctx.db)
    release, beats = threading.Event(), threading.Event()

    def long_job(jc, pl):
        q._local.beat_at = 0  # let the beat through right away
        q.beat()
        beats.set()
        release.wait(30)
        return {}
    q.register("long", long_job)
    q.time_limits = {"long": 60}
    jid = q.enqueue("long", {})
    t = threading.Thread(target=q.run_one, daemon=True)
    t.start()
    assert beats.wait(5)
    with ctx.db.session() as s:  # started two hours ago, but it just reported progress
        s.get(Job, jid).started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    q._reap_stuck()
    with ctx.db.session() as s:
        assert s.get(Job, jid).status == "running"
    release.set()
    t.join(5)
    with ctx.db.session() as s:
        assert s.get(Job, jid).status == "succeeded"
