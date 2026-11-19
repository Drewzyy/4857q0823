"""Performance numbers for docs/mcp-bridge.md. Usage: python scripts/bench_perf.py backend <scratch dir>
Prints app start time, the Ready to Upload list time with 200 clips, a 60 s render, and how fast the app answers
while two clips render."""
import os, sys, time, subprocess, statistics, tempfile, json
backend, work = sys.argv[1], sys.argv[2]
sys.path.insert(0, backend); sys.path.insert(0, os.path.join(backend, "tests"))
os.makedirs(work, exist_ok=True)
# 1. startup: a fresh process imports the app, builds it and answers /api/health
t = []
for _ in range(3):
    t0 = time.perf_counter()
    subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r)\nfrom pathlib import Path\nfrom clippr.config import Config\nfrom clippr.app import create_app\nfrom clippr.secrets_store import MemoryStore\nfrom clippr.app import build_context\nfrom fastapi.testclient import TestClient\nimport tempfile\nd=tempfile.mkdtemp()\napp=create_app(ctx=build_context(Config(data_dir=Path(d), port=8765, api_token='x', run_worker=False, secret_backend='memory'), secrets=MemoryStore()))\nTestClient(app).get('/api/health')" % backend], check=True)
    t.append(time.perf_counter() - t0)
print(json.dumps({"startup_s": round(statistics.median(t), 2)}))
# 2. clip list with 200 clips x 3 pages
from pathlib import Path
from clippr.config import Config
from clippr.app import build_context, create_app
from clippr.secrets_store import MemoryStore
from clippr.models import Clip, ClipOutput, Creator, DestinationAccount
from fastapi.testclient import TestClient
d = tempfile.mkdtemp(dir=work)
ctx = build_context(Config(data_dir=Path(d), port=8765, api_token="x", run_worker=False, secret_backend="memory"), secrets=MemoryStore())
c = TestClient(create_app(ctx=ctx)); c.headers["X-Clippr-Token"] = "x"
with ctx.db.session() as s:
    cr = Creator(name="A", clip_permission=True); s.add(cr); s.flush()
    pages = [DestinationAccount(platform="tiktok", external_id=f"p{i}", display_name=f"P{i}", creator_id=cr.id) for i in range(3)]
    s.add_all(pages); s.flush()
    words = [{"start": i * 0.4, "end": i * 0.4 + 0.3, "text": "word"} for i in range(80)]
    for n in range(200):
        cl = Clip(creator_id=cr.id, title=f"clip {n}", edit={"start": 0, "end": 30}, words=words, source_path="/x", status="ready",
                  grade={"score": 60, "tier": "B", "parts": [], "tips": []}, expires_at=__import__("datetime").datetime(2030, 1, 1, tzinfo=__import__("datetime").timezone.utc))
        s.add(cl); s.flush()
        for p in pages:
            s.add(ClipOutput(clip_id=cl.id, destination_id=p.id, platform="tiktok", title="t", description="d", file_path=f"/nope/{n}.mp4", overlay={}, format={}))
times = []
for _ in range(5):
    t0 = time.perf_counter(); r = c.get("/api/clips?status=ready"); times.append(time.perf_counter() - t0)
    assert r.status_code == 200 and len(r.json()) == 200, r.text[:200]
print(json.dumps({"clip_list_200_ms": round(statistics.median(times) * 1000)}))
# 3. render a 60 s clip to 1080x1920 with captions (processor encoder: no GPU in this container)
from clippr.media.ffmpeg import run
from clippr.media import overlay
from clippr.media.overlay import Word
from clippr.media.render import OutputFormat, render
from clippr.schemas import OverlaySettings
src = Path(work) / "src60.mp4"
if not src.exists():
    run(["-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=60", "-f", "lavfi", "-i", "sine=f=220:d=60",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)])
ov = OverlaySettings().model_dump(); od = Path(tempfile.mkdtemp(dir=work))
overlay.prepare(od, overlay.build_ass(1080, 1920, ov, "A headline", [Word(i * 0.4, i * 0.4 + 0.3, "word") for i in range(140)], 60))
t0 = time.perf_counter()
render(src, Path(work) / "out.mp4", OutputFormat(1080, 1920, 30), duration=60, overlay_dir=od, use_hardware=False)
print(json.dumps({"render_60s_s": round(time.perf_counter() - t0, 1)}))
# 4. how fast the app answers while two renders run (what you feel as lag)
import threading
jobs = [threading.Thread(target=render, args=(src, Path(work) / f"bg{i}.mp4", OutputFormat(1080, 1920, 30)),
                         kwargs={"duration": 60, "overlay_dir": od, "use_hardware": False}) for i in range(2)]
[j.start() for j in jobs]
time.sleep(3)
times = []
while any(j.is_alive() for j in jobs) and len(times) < 15:
    t0 = time.perf_counter(); c.get("/api/clips?status=ready"); times.append(time.perf_counter() - t0); time.sleep(0.5)
[j.join() for j in jobs]
print(json.dumps({"clip_list_during_2_renders_ms_median": round(statistics.median(times) * 1000), "worst_ms": round(max(times) * 1000), "cpus": os.cpu_count()}))
