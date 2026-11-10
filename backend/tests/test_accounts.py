def test_creator_source_destination_crud(client):
    a = client.post("/api/creators", json={"name": "Streamer A"}).json()
    b = client.post("/api/creators", json={"name": "Streamer B", "color": "#f97316"}).json()
    assert client.post("/api/creators", json={"name": "streamer a"}).status_code == 409

    s1 = client.post("/api/sources", json={"input": "https://www.tiktok.com/@a.clips", "creator_id": a["id"]})
    assert s1.status_code == 201, s1.text
    s1 = s1.json()
    assert s1["username"] == "a.clips" and s1["creator"]["name"] == "Streamer A"
    assert s1["videos_discovered"] is None  # unavailable, not zero
    assert client.post("/api/sources", json={"input": "@A.Clips"}).status_code == 409
    assert client.post("/api/sources", json={"input": "https://vm.tiktok.com/x/"}).status_code == 422

    r = client.patch(f"/api/sources/{s1['id']}", json={"monitoring": "paused"})
    assert r.json()["monitoring"] == "paused"
    assert len(client.get("/api/sources", params={"monitoring": "paused"}).json()) == 1
    assert len(client.get("/api/sources", params={"q": "a.cl"}).json()) == 1
    assert len(client.get("/api/sources", params={"creator_id": b["id"]}).json()) == 0

    d = client.post("/api/destinations", json={"platform": "youtube", "display_name": "A YouTube", "creator_id": a["id"]}).json()
    assert d["status"] == "manual" and d["settings"]["format"]["fps"] == 60
    r = client.patch(f"/api/destinations/{d['id']}", json={"handle": "https://www.tiktok.com/@A.Page", "display_name": " Renamed ", "settings": {"hashtags": ["#a"], "format": {"fps": 60}}})
    assert r.json()["handle"] == "@A.Page" and r.json()["display_name"] == "Renamed"
    assert client.patch(f"/api/destinations/{d['id']}", json={"handle": "bad handle!"}).status_code == 422
    assert r.status_code == 200 and r.json()["settings"]["format"]["fps"] == 60
    assert r.json()["settings"]["format"]["aspect"] == "9:16"  # deep defaults kept
    assert client.patch(f"/api/destinations/{d['id']}", json={"settings": {"format": {"fps": 61}}}).status_code == 422
    assert client.patch(f"/api/destinations/{d['id']}", json={"settings": {"evil": 1}}).status_code == 422

    assert client.delete(f"/api/sources/{s1['id']}").status_code == 204
    assert client.get("/api/sources").json() == []


def test_import_csv_and_lines(client):
    csv_text = "username,creator,folder\n@one,Streamer A,Gaming\nhttps://www.tiktok.com/@two,Streamer A,\nbad name!,,\n@one,,\n"
    r = client.post("/api/sources/import", files={"file": ("s.csv", csv_text, "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == 2 and body["skipped_duplicates"] == 1 and len(body["errors"]) == 1
    assert body["errors"][0]["line"] == 4
    creators = client.get("/api/creators").json()
    assert creators[0]["name"] == "Streamer A" and creators[0]["sources"] == 2
    assert client.get("/api/folders").json()[0]["sources"] == 1

    r = client.post("/api/sources/import-text", json={"text": "three\n@four\nthree", "platform": "tiktok"})
    assert r.json()["added"] == 2 and r.json()["skipped_duplicates"] == 1


def _setup(client):
    a = client.post("/api/creators", json={"name": "A"}).json()["id"]
    b = client.post("/api/creators", json={"name": "B"}).json()["id"]
    sa = client.post("/api/sources", json={"input": "aclips", "creator_id": a}).json()["id"]
    sa2 = client.post("/api/sources", json={"input": "ahighlights", "creator_id": a}).json()["id"]
    sb = client.post("/api/sources", json={"input": "bclips", "creator_id": b}).json()["id"]
    dests = {}
    for name, plat, cr in [("A TikTok", "tiktok", a), ("A Insta", "instagram", a), ("A YT", "youtube", a), ("B TikTok", "tiktok", b)]:
        dests[name] = client.post("/api/destinations", json={"platform": plat, "display_name": name, "creator_id": cr}).json()["id"]
    return a, b, sa, sa2, sb, dests


def test_pages_take_their_streamers_clips(client):
    """A watched account's clips go to every enabled page that lists its streamer; a page listing none gets none."""
    a, b, sa, sa2, sb, d = _setup(client)
    counts = {x["id"]: x["page_count"] for x in client.get("/api/sources").json()}
    assert counts[sa] == counts[sa2] == 3 and counts[sb] == 1  # A has three pages, B one
    client.post("/api/destinations", json={"platform": "tiktok", "display_name": "Nobody yet"})  # no streamers: takes none
    assert next(x["page_count"] for x in client.get("/api/sources").json() if x["id"] == sb) == 1
    client.patch(f"/api/destinations/{d['A YT']}", json={"enabled": False})
    assert next(x["page_count"] for x in client.get("/api/sources").json() if x["id"] == sa) == 2  # A TikTok, A Insta


def test_settings_validation_and_persistence(client):
    s = client.get("/api/settings").json()
    assert s["intake"]["clipboard"] is True and "ai" not in s
    r = client.put("/api/settings", json={"monitoring": {"twitch_min_views": 40}})
    assert r.status_code == 200 and r.json()["monitoring"]["twitch_min_views"] == 40
    assert r.json()["monitoring"]["interval_minutes"] == 10  # other options in the section are kept
    assert client.put("/api/settings", json={"monitoring": {"twitch_min_views": -1}}).status_code == 422
    assert client.put("/api/settings", json={"bogus": {}}).status_code == 422
    assert client.get("/api/settings").json()["monitoring"]["twitch_min_views"] == 40


def test_dashboard_real_counts(client):
    _setup(client)
    d = client.get("/api/dashboard").json()
    assert d["accounts"]["sources_total"] == 3 and d["accounts"]["destinations_total"] == 4
    assert "connections" not in d and "destinations_connected" not in d["accounts"]  # account logins were removed
    assert d["pipeline"]["ready_to_upload"] == 0 and d["monitoring"]["watching"] == 3 and d["monitoring"]["retention_days"] == 30
    assert d["storage"]["used_bytes"] > 0
    assert len(client.get("/api/audit").json()) > 0
