# Vyral MCP bridge for Muse

Vyral runs a small MCP server on this computer so Muse can see your clips, review and fix them, approve them,
and post them itself, without you downloading, captioning and uploading by hand. Vyral posts nothing: Muse does,
then tells Vyral where it went.

```
Twitch / Kick / Discord link
  -> Vyral: find the moment, cut, caption, pre-edit (hook, trims, punch-in, sound)
  -> safety check (quarantine on fail)  -> virality grade (held back if under the minimum)
  -> review queue  <- Muse via MCP: review_clip, update_clip (re-render), approve_clip / reject_clip
  -> Muse posts it (get_posting_package)  -> mark_posted: post URL back on the clip  -> Analytics
```

## Turn it on

Settings > **Muse & posting**:

| Setting | Default | What it does |
|---|---|---|
| MCP bridge on | **on** | Starts with Vyral. Listens on 127.0.0.1 only. |
| Port | **47821** | Fixed. If something else has it, the bridge stays off and the reason shows in Settings and in the log (`MCP server not started: Port 47821 is already in use`). It never moves to another port by itself. Change the port, press Save. |
| Token | made on first run | Kept in the file `mcp-token` in Vyral's data folder, readable by your user only (not the keychain: macOS asks for permission again after every update and that hung startup). **Copy token** puts it on your clipboard. It's never written to the database, the log or git. |
| Kill switch | off | On: nothing posts by itself, whatever each page's Auto-post says. |
| Minimum virality score | 50 | Clips scoring lower never reach review. |
| Safety blocklist | empty | Banned words, banned scenes (phrases), banned games. A match quarantines the clip. |

Per page (Destinations > a page > settings): **Kinds of clips**, **Auto-post** (off, tells Muse whether it may post an approved clip without asking you first) and **Daily cap** (3).

## Connecting Muse

Primary path: **MCP Streamable HTTP**.

- URL: `http://127.0.0.1:47821/mcp`
- Header: `Authorization: Bearer <token>`
- Plain request and response (JSON). No server-initiated messages: `GET /mcp` answers 405, which MCP clients treat as "no stream".

stdio is not built: Vyral is a running desktop app with its own database and job workers, and a second process
speaking stdio would either duplicate them or have to call this same HTTP endpoint anyway. If Muse can only start
stdio servers, use a stdio-to-HTTP bridge such as `npx mcp-remote http://127.0.0.1:47821/mcp --header "Authorization: Bearer <token>"`.

Check it with MCP Inspector: `npx @modelcontextprotocol/inspector`, transport "Streamable HTTP", the URL above,
and the Authorization header. It lists 15 tools.

### Muse on another device (Tailscale)

Settings > Muse & posting > **Listen on**: "My Tailscale address", then enter this computer's Tailscale address
(Tailscale app > this device, e.g. `100.115.250.79`). Muse then connects to `http://100.115.250.79:47821/mcp` with the
same token. Only Tailscale's private range (100.64.0.0 to 100.127.255.255) or this computer (127.0.0.1) is accepted:
never every network (0.0.0.0) or a home network address, so the bridge is never on the open internet. If Tailscale
isn't running, the bridge can't start on that address and Settings says so.

## Tools

Read-only unless noted. Each write is recorded in the audit log with `"by": "muse"`. No tool deletes anything,
and none returns a token, key or password.

| Tool | Input | What it does |
|---|---|---|
| `list_ready_clips` | none | Clips with finished videos: clip id, title, source channel, streamer, duration, created, each page's output (file path, caption, render state, review, post URL), virality score, safety status. Quarantined clips, streamers without clip permission and low scorers are left out. |
| `list_clips_for_review` | none | Same fields, only pages waiting for review. |
| `get_clip` | `clip_id` | Everything about one clip, including why it's held back if it is. |
| `review_clip` | `clip_id` | Videos, transcript with word times, headline (hook text), hook, trim, grade with reasons, safety result. |
| `get_safety_check` | `clip_id` | Runs the safety check now: flagged categories, confidence, the moment (seconds), what can't be machine-checked. |
| `list_quarantined_clips` | none | Clips the safety check failed, with why and when. |
| `list_sources` | none | Watched accounts: platform, handle, streamers, monitoring on or off. |
| `list_destinations` | none | Pages: platform, handle, streamers, kinds, enabled, Auto-post. |
| `list_funnel_routes` | none | Which streamer's clips go to which page, and whether that route is on. |
| `update_clip` (write) | `clip_id`, any of `caption` (+ `destination_id` for one page), `hook_text`, `hook` `[start, end]` or null, `trim_start`, `trim_end`, `destination_ids` | Changes the clip. Video changes re-render through the jobs queue; the transcript is reused, never re-done. A changed video or caption needs approving again. |
| `approve_clip` (write) | `clip_id`, `destination_id`, `watched: true`, optional `caption`, `scheduled_at` | Approves one page's video. Doesn't post. Refused for quarantined clips, streamers without clip permission, low scorers, or if `watched` isn't true. |
| `reject_clip` (write) | `clip_id`, `reason`, optional `destination_id` | Rejects one page or all of them. |
| `get_posting_package` | `clip_id`, `destination_id` | For an approved video: file path, `dropbox_path` once the verified copy is in Dropbox, final caption, page handle, aspect ratio, duration, schedule. Muse posts it with this. |
| `mark_posted` (write) | `clip_id`, `destination_id`, `post_url` | After Muse posted the approved video: stores the link (https, on that page's platform: TikTok, Instagram, YouTube, Facebook or X), marks the video uploaded, so Analytics and campaigns pick it up. Refused unless the video is approved. Audit entry says Muse did it. |

Every clip's outputs in `list_ready_clips` and `get_clip` also carry `dropbox_status` (queued, uploading, uploaded, failed, or null) and `dropbox_path` (set only once the upload is verified). Use that path to fetch the video from Dropbox.

The flow is `approve_clip` -> `get_posting_package` -> Muse posts the video -> `mark_posted`. There is deliberately no `post_to_tiktok` or `post_to_instagram` in Vyral: posting is Muse's job, after approval.

Example (curl):

```sh
TOKEN=...   # Settings > Muse & posting > Copy token
curl -s http://127.0.0.1:47821/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_clips_for_review","arguments":{}}}'

curl -s http://127.0.0.1:47821/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"update_clip","arguments":{"clip_id":12,"destination_id":3,"caption":"Lacy couldnt believe what Kai did #lacy #kaicenat #streamer","hook_text":"Lacy couldnt believe what Kai did"}}}'

curl -s http://127.0.0.1:47821/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"approve_clip","arguments":{"clip_id":12,"destination_id":3,"watched":true}}}'

curl -s http://127.0.0.1:47821/mcp -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"mark_posted","arguments":{"clip_id":12,"destination_id":3,"post_url":"https://www.tiktok.com/@vyralclips19/video/9"}}}'
```

## Approval and Auto-post

- Default: Muse asks you first. It approves (after sending you the exact video and caption on your phone, which Muse
  does on its side), posts the video itself, then calls `mark_posted` with the link.
- **Auto-post** is per page, off by default, never turned on by code. The app refuses to turn it on until 5 reviewed
  posts on that page were posted. Vyral doesn't post anything itself: Muse reads this setting (`list_destinations`) to
  know it may post an approved video without asking you first. That holds only if its safety check is a clean pass
  (never a "review" or uncertain result), the page's daily cap isn't reached, and the kill switch is off. Vyral doesn't enforce those: Muse does.
- Re-rendering a video, or changing its caption, puts an approved video that isn't posted yet back to waiting.

## Routing for your four pages

Each page lists the streamers it takes and the **kinds** of clips it takes. Each streamer is regular, gaming or podcast
(Source Accounts > streamer > Kind of clips). Pages added with these handles get these kinds by default; change them any time:

| Page | Platform | Takes |
|---|---|---|
| @vyralclips19 | TikTok | regular |
| @vyralclipr | Instagram | regular |
| @vyralgames7 | TikTok | gaming |
| @vyralpods | Instagram | podcast |

So a podcast streamer's clips go to @vyralpods only, a gaming streamer's to @vyralgames7, and everyone else's to
@vyralclips19 and @vyralclipr. A clip still only goes to pages that list its streamer. (The old "funnel routes" table was
replaced by this in migration 0010; `list_funnel_routes` reports the routes this produces.)

## Safety check

Runs on every clip after every render or edit, before review and before posting. It comes before the virality score.

Results: **fail** (quarantined: never reviewed, never posted, stays failed through edits, re-renders and page changes;
logged as `clip.quarantined` with the reasons), **review** (borderline or uncertain: only you or Muse can approve it,
never auto-posted) or **pass**.

Checked on this computer: clip permission (off: out); what's said (the transcript, with the second it's said) and
the headline, titles and captions, against categories built from the guidelines below and your blocklist; the game
(GTA, Red Dead, Cyberpunk and similar are high risk: strip clubs, torture, executions and drugs mentioned in them quarantine
the clip, and every clip from them needs a look); re-uploads with no captions or headline added.

**Not machine-checked, so a person or Muse must watch before approving** (approve_clip requires `watched: true`):
the picture itself (nudity, gore, weapons on screen) and copyrighted music. These need image and audio-recognition models
Vyral doesn't ship. Slurs aren't built in either: add any you want caught to Banned words.

Guidelines this follows (checked November 2026 through search results; the official pages couldn't be opened from
the build environment, so read them yourself before relying on the mapping):
- TikTok Community Guidelines, https://www.tiktok.com/community-guidelines/en : Safety and Civility (violent and hateful
  behavior, harassment), Mental and Behavioral Health (suicide and self-harm), Sensitive and Mature Themes (sexual activity and
  nudity, shocking and graphic content), Regulated Goods and Commercial Activities (drugs, weapons), Integrity and
  Authenticity (intellectual property, unoriginal content), and For You feed eligibility.
- Instagram Community Guidelines, https://help.instagram.com/477434105621119 , and Recommendations Guidelines,
  https://help.instagram.com/313829416281232 (content lowered in Feed and Reels).
- Meta Community Standards, https://transparency.meta.com/policies/community-standards/

Keeping it current: TikTok revised its guidelines twice in 2026 (April and August). Re-read both pages every quarter
and when either platform announces changes; put new terms in the blocklist straight away (it applies to every new clip
with no update needed), and change the built-in categories in `backend/clippr/safety.py` with a test.

## Virality: the edit and the score

Every new clip gets (Settings > Monitoring & storage > Viral pre-edit):
- **Hook first:** the strongest 3 to 6 seconds play first, then the clip from its start (only when the opening isn't
  already the best part). The headline uses the source post's own line or a quote of what was said, never invented words.
- **Trims:** a silent opening is cut; quiet pauses over 0.4 s are tightened (not loud ones: that's the reaction);
  "um" and "uh" are cut; clips over 45 s are cut to the strongest 34 s, ending just after the peak.
- **Captions:** word-timed from faster-whisper, centered in the lower third, bold with a thick outline, kept inside the frame.
- **Punch-in:** 8% closer for about 1.5 s on the peak only, hard cut in and out.
- **Ending:** a hard cut on the payoff, no fade, no trailing silence.
- **Caption for posting:** the headline plus 3 to 5 specific hashtags (generic ones like #fyp are dropped).

The grade (0 to 100, S to D) scores proof people care, the hook in the first 3 seconds, energy and emotion, pacing,
length (15 to 45 s), visual pace, the headline (a full who-and-what sentence or a quote) and the ending. Each part
comes with the reason and the top fixes. Under the minimum score (Settings), a clip doesn't reach review.

## Performance

Measured in the build environment (4-core Linux, processor encoder, no GPU), before (`971c64e`) and after this work,
with `scripts/bench_perf.py` (a fresh app start, 200 clips with 3 pages each, a 60 s 1080x1920 render with captions):

| | Before | After |
|---|---|---|
| App start to first answer | 0.98 s | 0.85 s |
| Ready to Upload list (200 clips) | 141 ms | 83 ms |
| **App response while 2 clips render** | **420 ms (worst 804 ms)** | **107 ms (worst 193 ms)** |
| Render a 60 s clip | 18.0 s | 18.0 s |
| Link to ready clip (test run, local stand-in files) | 20.6 s | 20.6 s |

Render speed is unchanged on purpose: rendering now runs below normal priority, so it yields the processor
whenever the app needs it. That is the lag fix.

What changed:
- FFmpeg, ffprobe and the scoring decoders run at low priority (`nice 10` on Mac, `BELOW_NORMAL_PRIORITY_CLASS` on Windows,
  and with no console window on Windows, which three scoring calls used to flash).
- faster-whisper uses half the cores; OpenCV face finding two threads.
- Ready to Upload: video players load only when you press play; cards don't redraw when other clips change; new clips
  wait behind a "new clips" button instead of moving the page; polling every 15 s (5 s while re-rendering), not on window focus;
  what you're typing in a caption is never overwritten by a refresh.
- The clip list is one query per page load instead of one per clip; the disk-usage scan is cached for 2 minutes; the database
  isn't locked while FFmpeg reads finished videos.
- Heavy work (downloads, transcription, rendering, Discord polling) already ran in background jobs, never on the UI thread.
  The renders that run at once are capped in Settings ("Clips rendered at the same time"); the rest wait, and Activity shows each one's place in line.
- Nothing is transcribed twice: a clip's transcript is kept with it and every re-render (editor, Muse, pre-edit) reuses it.

Hardware encoding (Settings > Render with: Graphics card), exact FFmpeg flags:
- Mac (Apple Silicon): `-c:v h264_videotoolbox -b:v <page bitrate>M -maxrate <1.5x>M -allow_sw 1 -bf 0` (HEVC: `hevc_videotoolbox ... -tag:v hvc1`)
- Windows: `h264_nvenc -preset p5 -rc vbr -cq 19`, else `h264_qsv -preset medium -global_quality 20`, else `h264_amf -quality quality -rc vbr_peak`, all with `-maxrate` and `-bf 0`
- Fallback (or Processor only): `libx264 -crf 16 -profile:v high -preset faster -bf 0`
- `-bf 0` everywhere: B-frames made some players start the sound ahead of the picture.

The Mac and Windows numbers will differ from these. To measure on your machine: `python scripts/bench_perf.py backend /tmp/vyral-bench`.

## Acceptance checklist

Automated (`cd backend && python -m pytest -q tests/test_mcp.py`): all 15 tools listed over MCP; real clips from the
database with files that exist; approve shows in the app with an audit entry saying Muse; the posting package's file plays and
has the right page and caption; `mark_posted` refused unless approved or for a link on the wrong platform, and shows in the app;
re-render after update_clip without re-transcribing; quarantined clips never offered or approvable; Auto-post locked;
port in use fails loudly; no token in any tool output.

By hand, once:
1. Settings > Muse & posting: copy the token into Muse.
2. In MCP Inspector or Muse: `list_clips_for_review`, `approve_clip` with `watched: true`, `get_posting_package`.
3. Post the video, then `mark_posted` with its link. Check it shows as uploaded in the app.
