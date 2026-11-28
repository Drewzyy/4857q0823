"""Long-form: the moment finder, and the whole path from a dropped-in file to graded clips."""
from dataclasses import replace

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
    assert m.score > flat.score and "awe" in " ".join(m.why)


def test_a_dropped_in_file_becomes_clips(env, tmp_path, screen_passes):
    ctx, c, fake = env
    # The fake speech model says the same 25 words everywhere, which would count as one moment repeated; give each
    # candidate its own words so only the sound decides which moments are picked.
    said = ctx.transcriber.words
    ctx.transcriber.words = lambda *a, **k: [replace(w, text=f"{'abcdefghijklmnopqrstuvwxyz'[ctx.transcriber.calls % 26] * 3}{w.text}")
                                             for w in said(*a, **k)]
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
    assert all(not x.get("captions_note") for x in clips), [x.get("captions_note") for x in clips]
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


def test_a_reaction_word_at_the_peak_beats_the_same_word_elsewhere():
    near = moments.Moment(0, 30, 15, 50.0)
    moments.speech_bonus(near, [(14.5, 15.0, "no"), (15.0, 15.4, "way")])
    far = moments.Moment(0, 30, 15, 50.0)
    moments.speech_bonus(far, [(1.0, 1.5, "no"), (1.5, 1.9, "way")])
    assert near.score > far.score and "right at the peak" in " ".join(near.why)


def test_pitch_lift_hears_a_raised_voice():
    from clippr.grade import pitch_lift
    sr = 8000
    t = np.arange(sr * 4) / sr
    calm = 0.3 * np.sin(2 * np.pi * 120 * t)
    yell = np.concatenate([calm[: sr * 2], 0.3 * np.sin(2 * np.pi * 220 * t[: sr * 2])])  # half the time pitched way up
    assert pitch_lift(calm.astype(np.float32), sr) < 0.05
    assert pitch_lift(yell.astype(np.float32), sr) > 0.3


def test_a_steady_talker_still_gives_candidates():
    rng = np.random.default_rng(5)
    db = -24 + rng.normal(0, 0.8, 6000)
    db[3000:3030] = -21  # a laugh only 3 dB up
    assert moments.candidates(db, limit=3)


def test_hooks_beat_mid_thought_openings():
    hook, dangling = moments.Moment(0, 30, 15, 50.0), moments.Moment(0, 30, 15, 50.0)
    moments.speech_bonus(hook, [(0.1, 0.4, "the"), (0.4, 0.8, "craziest"), (0.8, 1.0, "thing")])
    moments.speech_bonus(dangling, [(0.1, 0.4, "and"), (0.4, 0.8, "then"), (0.8, 1.0, "thing")])
    assert hook.score > dangling.score and "opens on a hook" in hook.why


def test_pick_spreads_out_and_skips_repeats():
    line = "we just won the whole tournament against the best team ever and chat cannot believe what happened tonight"
    ms = [moments.Moment(100, 130, 115, 90, text=line), moments.Moment(1000, 1030, 1015, 88, text=line),  # replayed
          moments.Moment(140, 170, 155, 80), moments.Moment(2000, 2030, 2015, 70), moments.Moment(120, 150, 135, 85)]
    got = moments.pick(ms, 2)
    assert [m.start for m in got] == [100, 2000], [m.start for m in got]  # 140 is close to 100; 120 overlaps; 1000 repeats


def _chat(spike_at=None, seconds=600):
    """A steady chat (a message a second) with, optionally, a KEKW flood a few seconds after `spike_at`."""
    msgs = [(float(t), "ok") for t in range(seconds)]
    if spike_at is not None:
        msgs += [(spike_at + moments.CHAT_LAG + i / 10, "KEKW KEKW") for i in range(80)]
    return msgs, [(0.0, float(seconds))]


def test_chat_spikes_are_scored_and_can_change_the_pick():
    msgs, covered = _chat(300)
    curve = moments.chat_curve(msgs, covered, 6000)
    assert curve is not None and abs(np.nanargmax(curve) / 10 - 300) < 5 and float(np.nanmedian(curve)) == 0
    assert np.nanmax(moments.chat_curve(*_chat(), 6000)) == 0  # steady chat: no spike anywhere
    assert moments.chat_curve(msgs[:10], covered, 6000) is None  # too little chat to tell
    part = moments.chat_curve(msgs, [(250.0, 350.0)], 6000)
    assert np.isnan(part[:2000]).all() and not np.isnan(part[2600:3400]).any()  # only what was read counts
    db = _quiet_with_bursts(600, [100, 300])
    db[3000:3030] = -17  # 5:00 is quieter than 1:40
    assert abs(moments.pick(moments.candidates(db, limit=5), 1)[0].peak - 100) < 5
    best = moments.pick(moments.candidates(db, limit=5, chat=curve), 1)[0]
    assert abs(best.peak - 300) < 8 and "chat blew up" in best.why[0]  # chat flooded over 5:00


def test_youtube_and_twitch_chat_replays_are_read(monkeypatch):
    import httpx
    import respx
    from clippr import fetch
    line = {"replayChatItemAction": {"videoOffsetTimeMsec": "12500", "actions": [{"addChatItemAction": {"item": {
        "liveChatTextMessageRenderer": {"message": {"runs": [{"text": "clip it"}, {"emoji": {"shortcuts": [":kekw:"]}}]}}}}}]}}
    assert fetch._youtube_message(line) == [(12.5, "clip it kekw")]
    assert fetch._youtube_message({"addChatItemAction": {}}) == []
    monkeypatch.setattr(fetch, "TWITCH_PAUSE", 0)

    def page(ts, more):
        return {"data": {"video": {"comments": {"edges": [{"cursor": f"c{t}", "node": {"contentOffsetSeconds": t,
                "message": {"fragments": [{"text": "LUL"}]}}} for t in ts], "pageInfo": {"hasNextPage": more}}}}}
    with respx.mock:
        route = respx.post("https://gql.twitch.tv/gql").mock(side_effect=[
            httpx.Response(200, json=page([100, 101], True)), httpx.Response(200, json=page([102, 131], True)),
            httpx.Response(429)])
        msgs, covered = fetch.YtDlpFetcher().chat_replay("https://www.twitch.tv/videos/42", [(100, 130), (500, 560)], 30)
        assert [t for t, _ in msgs] == [100, 101, 102, 131] and covered == [(100, 130)]  # rate limited at the second window: stop
        assert route.calls[1].request.read().find(b'"c":"c101"') > 0 and route.calls[0].request.headers["Client-ID"] != "u"
    assert fetch.YtDlpFetcher().chat_replay("https://kick.com/video/abc", [(0, 10)], 5) == ([], [])


def test_without_chat_moments_are_found_as_before(env):
    ctx, c, fake = env
    cid = c.post("/api/creators", json={"name": "Streamer A", "clip_permission": True, "vod_channels": ["https://www.twitch.tv/streamera"]}).json()["id"]
    c.post("/api/destinations", json={"platform": "tiktok", "display_name": "A page", "creator_ids": [cid]})
    fake.chat = TimeoutError("chat took too long")
    assert ctx.pipeline._chat("https://www.twitch.tv/videos/2", [moments.Moment(100, 130, 115, 50)], 2400) is None
    fake.chat = None
    assert ctx.pipeline._chat("https://www.twitch.tv/videos/2", [moments.Moment(100, 130, 115, 50)], 2400) is None  # no chat
    fake.chat = TimeoutError("chat took too long")
    c.post("/api/longform", json={"url": "https://www.youtube.com/watch?v=long1", "creator_id": cid, "clips_wanted": 1})
    drain(ctx)
    lf = c.get("/api/longform").json()[0]
    assert lf["status"] == "ready", lf["status_detail"]
    assert ("chat", "https://www.youtube.com/watch?v=long1") in fake.calls
