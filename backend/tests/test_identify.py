from clippr.identify import channel_handle, mention_score, rank_candidates

CORE = (1, "The Core", ["https://www.twitch.tv/stableronaldo", "https://www.twitch.tv/jasontheween", "https://kick.com/lacy"])
OTHER = (2, "Kai Cenat", ["https://www.twitch.tv/kaicenat"])


def test_channel_handles():
    assert channel_handle("https://www.twitch.tv/jasontheween") == "jasontheween"
    assert channel_handle("https://kick.com/lacy/videos") == "lacy"
    assert channel_handle("https://www.youtube.com/@KaiCenatLive") == "KaiCenatLive"
    assert channel_handle("https://www.twitch.tv/videos/123") == ""


def test_mentions():
    assert mention_score("jasontheween", "bro what #jasontheween #fyp") == 3
    assert mention_score("Kai Cenat", "kai cenat moment") == 1  # name split over words still counts, just weaker
    assert mention_score("lacy", "lacy is crazy") == 3
    assert mention_score("lacy", "fallacy") == 0  # short names only count as whole words
    assert mention_score("", "anything") == 0


def test_named_streamer_and_group_member_go_first():
    ranked = rank_candidates([OTHER, CORE], "jason did NOT just do that 😭 #jasontheween #thecore")
    assert ranked[0][0] == 1 and ranked[0][2][0] == "https://www.twitch.tv/jasontheween"
    assert ranked[1][0] == 2
    # Nothing named: original order, nothing dropped.
    assert rank_candidates([OTHER, CORE], "crazy moment #fyp") == [OTHER, CORE]
