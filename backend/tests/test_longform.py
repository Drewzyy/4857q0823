"""Long-form: the moment finder, and the whole path from a dropped-in file to graded clips."""
import numpy as np

from clippr import moments
from clippr.media.ffmpeg import run
from fakes import drain


def _quiet_with_bursts(seconds, bursts, rng=np.random.default_rng(3)):
    db = -32 + rng.normal(0, 1.2, int(seconds * 10))
    for t in bursts:
        db[int(t * 10):int((t + 3) * 10)] = -12
    return db


def test_loud_moments_become_candidates_with_setup_and_payoff():
    c = moments.candidates(_quiet_with_bursts(600, [100, 300, 480]), limit=5)
    peaks = sorted(round(m.peak) for m in c[:3])
    assert all(any(abs(p - t) < 5 for p in peaks) for t in (100, 300, 480)), peaks
    for m in c[:3]:
        assert moments.MIN_LEN <= m.end - m.start <= moments.MAX_LEN
        assert m.start < m.peak - 7  # opens with a setup before the moment


def test_most_replayed_parts_rank_first():
    db = _quiet_with_bursts(600, [100, 300])
    heat = np.zeros(len(db))
    heat[2950:3200] = 1.0  # viewers keep rewinding to 5:00
    best = moments.candidates(db, heat, limit=3)[0]
    assert abs(best.peak - 300) < 10 and "most replayed" in best.why[0]


def test_reaction_lines_add_points():
    m = moments.Moment(0, 30, 15, 50.0)
    moments.speech_bonus(m, [(0.2, 0.5, "no"), (0.5, 0.8, "way"), (0.9, 1.2, "bro"), (1.3, 1.6, "let's"), (1.6, 1.9, "go")])
    flat = moments.Moment(0, 30, 15, 50.0)
    moments.speech_bonus(flat, [(10, 10.5, "okay")])
    assert m.score > flat.score and "reaction lines" in " ".join(m.why)


def test_a_dropped_in_file_becomes_clips(env, tmp_path):
    ctx, c, fake = env
    video = tmp_path / "podcast.mp4"
    # 2 minutes of quiet room tone with three loud moments, over a test picture.
    run(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=120",
         "-f", "lavfi", "-i", "anoisesrc=a=0.01:d=120,volume='if(between(t,30,33)+between(t,70,73)+between(t,100,103),40,1)':eval=frame",
         "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(video)])
    c.post("/api/destinations", json={"platform": "tiktok", "display_name": "Any page"})
    r = c.post("/api/longform/upload", files={"file": ("podcast.mp4", video.read_bytes())}, data={"clips_wanted": "2"})
    assert r.status_code == 201, r.text
    assert c.post("/api/longform/upload", files={"file": ("notes.txt", b"x")}).status_code == 422
    assert c.post("/api/longform", json={"url": "not a link"}).status_code == 422
    drain(ctx)
    lf = c.get("/api/longform").json()[0]
    assert lf["status"] == "ready", lf["status_detail"]
    assert len(lf["moments"]) == 2 and all(m["clip_id"] for m in lf["moments"])
    clips = c.get("/api/clips").json()
    assert len(clips) == 2 and all(x["grade"] and x["outputs"] for x in clips)
    c.delete(f"/api/longform/{lf['id']}")
    assert c.get("/api/longform").json() == [] and len(c.get("/api/clips").json()) == 2  # clips stay


def test_a_pasted_link_uses_the_replay_graph_and_the_streamers_pages(env):
    ctx, c, fake = env
    cid = c.post("/api/creators", json={"name": "Streamer A", "clip_permission": True, "vod_channels": ["https://www.twitch.tv/streamera"]}).json()["id"]
    c.post("/api/destinations", json={"platform": "tiktok", "display_name": "A page", "creator_ids": [cid]})
    fake.heatmap = [{"start_time": 128, "end_time": 150, "value": 1.0}, {"start_time": 0, "end_time": 128, "value": 0.1}]
    r = c.post("/api/longform", json={"url": "https://www.youtube.com/watch?v=long1", "creator_id": cid, "clips_wanted": 1})
    assert r.status_code == 201
    drain(ctx)
    lf = c.get("/api/longform").json()[0]
    assert lf["status"] == "ready", lf["status_detail"]
    m = lf["moments"][0]
    assert m["start"] < 150 and m["end"] > 128, m  # the most-replayed stretch
    assert ("longform", "https://www.youtube.com/watch?v=long1") in fake.calls


def test_clips_start_and_end_on_whole_sentences():
    m = moments.Moment(start=100.0, end=130.0, peak=118.0, score=50)
    # Words from 94 s in the video: a sentence starts at 97.0 (after a pause) and one ends at 131.2.
    words = [(0.0, 0.4, "and"), (0.5, 1.0, "then."), (3.0, 3.4, "So"), (3.5, 4.0, "he"), (4.1, 30.0, "goes"),
             (30.1, 37.2, "crazy!"), (38.0, 38.5, "next")]
    moments.snap(m, words, offset=94.0)
    assert abs(m.start - (97.0 - 0.15)) < 0.01  # opens on "So", not mid-sentence
    assert abs(m.end - (131.2 + 0.3)) < 0.01  # ends after "crazy!"
