# What makes a clip do well: the research behind Vyral's grader and long-form moment finder

Gathered November 2026. Most sources are clipping-tool vendors and creator blogs; the platforms don't publish
their ranking, and there is no peer-reviewed study of gaming clips specifically. Numbers below are treated as
direction, not law. Vyral's weights should be re-tuned on the user's own posted-clip results once there are enough.

## What the evidence agrees on

| Finding | Strength | Where Vyral uses it |
|---|---|---|
| Real viewer behaviour beats any prediction: YouTube's "most replayed" graph, views and engagement of the original, viewers clipping a stream moment | Strong (measured on real viewers) | Long-form pass 1 weights the replay graph highest; grader "Proof people care" (30 pts) |
| Most drop-off happens in the first 1 to 3 seconds; the first frame should already be interesting | Consistent across all sources | Grader "Hook" (20) and "Visual pace" (5); moment finder starts where there's already sound |
| A setup and a payoff: stakes, then the reaction | Consistent (practitioner) | Moment finder opens 8 to 25 s before the peak and ends after it settles; grader "Ends on the payoff" |
| Gaming clips under ~20 s lack setup; over ~45 s lose viewers before the reaction | Vendor guidance | Moment finder targets 20 to 45 s (cap 60); grader full marks for 20 to 45 s |
| The most-viewed clips are the fastest, not the best looking | Vendor analysis of 44,000 clips | Grader "Visual pace"; dead air cutting |
| Faster speech is linked to more shares | Peer-reviewed field study of 2,511 TikTok videos | Grader "Pacing" rewards up to ~4.5 words a second |
| Clips should start and end on a complete thought | Clipping tools using the replay graph | Long-form snaps start/end to sentence boundaries |
| Funny fails, reactions and personality beat pure skill | Practitioner consensus | Reaction phrases and loudness peaks score; laughter counted via loud bursts |
| Captions and vertical framing are table stakes | Consensus | On by default; grader counts them but weights them low (5) |
| High-arousal emotions (awe, amusement, anger, anxiety) get shared most, whatever their sign; sadness lowers sharing | Peer-reviewed (Berger & Milkman 2012, ~7,000 NYT articles plus experiments) | Grader "Energy and emotion" and the moment finder look for words of each emotion |
| Excitement shows as louder and higher-pitched voices; a loud spike with a reaction word at it is a highlight | Sports and esports highlight research (Interspeech 2010, CVPR 2018 workshop, 2025-26 papers) | Voice pitch lift in grader and moment finder; reaction word within 3 s of the peak scores highest |
| A question or "watch this" opens a curiosity gap viewers stay to close (Loewenstein's information-gap theory) | Established theory, practitioner use; no controlled clip study | Grader hook counts a curious opening |
| Platforms weight completion and rewatches most, then shares; follower count isn't a direct input | Third-party summaries of platform guidance | Length and hook weights; tips to cut lead-ins and end on the payoff |
| Faces on screen in the first seconds | Weak: unverified marketing figures only | Not scored (the facecam layout keeps faces visible anyway) |
| "Virality scores" from commercial tools are ranking aids, not predictions (in one test the best performer scored 64, the worst 87) | Independent reviews | Vyral's grade is labelled a prediction; S means every signal is strong, never a guarantee |

## Not used yet, and why

- Twitch chat replay (chat spikes are a known highlight signal in research): not readable for past broadcasts
  without signing in, which Vyral doesn't do.
- A dedicated laughter detector: the best open models are research-only licensed or untested on game audio;
  loud bursts already catch most laughs.
- Trends and posting time: change weekly and differ by audience; better learned from the user's own results.

## Sources

- OpusClip virality score reviews: bigvu.tv/blog/opus-clips-worth-the-hype, bigvu.tv/blog/opus-clip-tested-2026-where-ai-wins-40-percent-discard, scalereach.ai/blog/opus-clip-review
- Engagement prediction research: arxiv.org/html/2410.00289, arxiv.org/pdf/2508.02516; TikTok audiovisual features (Journal of Business Research 2025); short-form ad engagement field study (Internet Research, Emerald)
- Twitch highlights from chat: Liaw et al., "Live Stream Highlight Detection Using Chat Messages" (MDM 2020)
- Most replayed: Headliner "Most Replayed" clipping; opus.pro "clip the moments viewers rewatch most"
- Gaming clip practice: autoclip.dev/blog/why-clips-go-viral-what-clippers-get-wrong, clipflip.io/resources/how-to-make-viral-clips, dev.to/clamper_ai/how-to-clip-twitch-streams-for-tiktok-youtube-shorts-and-reels-2pjp
- Retention benchmarks: grow-it.se/en/resources/short-form-video-retention-benchmarks, opus.pro/blog/ideal-youtube-shorts-length-format-retention, fanpagekarma.com/insights/optimal-tiktok-video-length
- Laughter detection: github.com/jrgillick/laughter-detection
- Arousal and sharing: Berger & Milkman, "What Makes Online Content Viral?", Journal of Marketing Research 2012 (faculty.wharton.upenn.edu/wp-content/uploads/2011/11/Virality.pdf)
- Excitement in sports audio: Interspeech 2010 sports highlights (personal.utdallas.edu/~hynek/pdfs/Interspeech10_SportsHighlights.pdf); Merler et al., "The Excitement of Sports" (CVPR 2018 workshops); arxiv.org/html/2501.16100v2
- Platform signals: blog.hootsuite.com/tiktok-algorithm; YouTube Shorts "viewed vs swiped away" (contentstudio.io/blog/youtube-shorts-analytics-guide)
- Curiosity loops: creatorlanehq.com/blog/science-of-curiosity-open-loops-without-clickbait-2026

## Open-source projects reviewed (November 2026)

Projects over 1,000 GitHub stars doing similar work, and what Vyral took as inspiration (ideas only; no code
copied):

| Project | Stars | Idea | In Vyral |
|---|---|---|---|
| Anil-matcha/AI-Youtube-Shorts-Generator (MIT) | 5.9k | Vertical crop that follows the speaker's face; score + reason per clip | Zoomed-in framing keeps the main person in the crop; every clip already has a grade with reasons |
| xixihhhh/hotclip (AGPL, livestream replay clipper) | <1k | Steady framing: lock one position per shot instead of chasing faces; chat heat with per-user caps; several signals agreeing before trusting a peak; flag weak clips | Steady single framing per clip; D-tier clips marked "skip?" |
| ClipsAI/clipsai (MIT) | 565 | Reframe on the active speaker | Same idea as above |
| jipraks/yt-short-clipper (MIT) | 1.0k | Use the video's own subtitles instead of transcribing | Not yet: a speed-up for long-form YouTube links |
| xenova/chat-downloader (MIT) | 1.2k | Read Twitch and YouTube chat replays without signing in | Not yet: chat spikes as a long-form signal (needs a real Twitch connection to test) |
| WyattBlue/auto-editor, Breakthrough/PySceneDetect, m-bain/whisperX | 5.8k / 5.4k / 25k | Silence cutting, scene cuts, word timing | Vyral has its own versions of each |

## Eight clips over 200k views (November 2026)

Eight streamer clips from clip pages, each past 200k views, studied frame by frame and by ear. What they share, and
what Vyral's pre-edit (backend/clippr/preedit.py) does about it:

| What the clips do | Count | Pre-edit |
|---|---|---|
| 18 to 28 seconds long (the eighth is 109 s, a story) | 7 of 8 | Clips over 30 s are trimmed to the strongest 26 s, ending just after the loudest moment |
| Sound starts in the first quarter second | 7 of 8 | A silent opening is cut |
| One headline for the whole clip, at the top, dark text on a white box, sentence case, ends on 1 or 2 emoji | 8 of 8 | Same headline box, from the source post's own caption or the clip's line with the streamer's name |
| Headline is third person and names the streamer ("Lacy couldn't believe...") | 7 of 8 | The source post's line is used as is; otherwise "Name: “line”" |
| Word-by-word captions burned in | 0 of 8 | Left to the page's setting (they help silent viewing; the evidence here doesn't say either way) |
| Cuts | 1 to 5 in a short clip | No extra cuts beyond quiet pauses and "um"s |
| Added music, sound effects or zooms | 0 of 8 | None added |
| Facecam on top, gameplay under it, headline on the seam | 2 of 2 gaming clips | Stacked layout now puts the facecam on top (it was underneath) |
| Loudness | -17 LUFS typical | Clips are normalized to -14 LUFS (TikTok's target), a little louder |
