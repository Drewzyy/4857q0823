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
    assert d["status"] == "draft" and d["settings"]["visibility"] == "private"
    r = client.patch(f"/api/destinations/{d['id']}", json={"settings": {"hashtags": ["#a"], "format": {"fps": 60}}})
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


def test_funnel_rules(client):
    a, b, sa, sa2, sb, d = _setup(client)
    r = client.post("/api/funnel/routes", json={"source_id": sa, "destination_id": d["A TikTok"]})
    assert r.status_code == 201
    dup = client.post("/api/funnel/routes", json={"source_id": sa, "destination_id": d["A TikTok"]})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "duplicate"

    cross = client.post("/api/funnel/routes", json={"source_id": sb, "destination_id": d["A TikTok"]})
    assert cross.status_code == 409 and cross.json()["error"]["code"] == "cross_creator"
    ok = client.post("/api/funnel/routes", json={"source_id": sb, "destination_id": d["A TikTok"], "allow_cross_creator": True})
    assert ok.status_code == 201 and ok.json()["allow_cross_creator"] is True

    created = client.post("/api/funnel/auto-route", json={"creator_id": a}).json()["created"]
    assert created == 5  # 2 A-sources x 3 A-destinations, minus the one already present
    assert client.post("/api/funnel/auto-route", json={}).json()["created"] == 1  # B -> B TikTok

    resolved = {x["display_name"] for x in client.get(f"/api/funnel/resolve/{sa}").json()}
    assert resolved == {"A TikTok", "A Insta", "A YT"}
    resolved_b = {x["display_name"] for x in client.get(f"/api/funnel/resolve/{sb}").json()}
    assert resolved_b == {"B TikTok", "A TikTok"}

    # Disabled route is excluded
    route_id = next(x for x in client.get("/api/funnel").json()["routes"] if x["source_id"] == sa and x["destination_id"] == d["A YT"])["id"]
    client.patch(f"/api/funnel/routes/{route_id}", json={"enabled": False})
    assert "A YT" not in {x["display_name"] for x in client.get(f"/api/funnel/resolve/{sa}").json()}

    # Reassigning a destination to another creator blocks unconfirmed routes instead of mixing silently
    client.patch(f"/api/destinations/{d['A Insta']}", json={"creator_id": b})
    assert "A Insta" not in {x["display_name"] for x in client.get(f"/api/funnel/resolve/{sa}").json()}
    assert any(x["blocked"] for x in client.get("/api/funnel").json()["routes"])

    # Layout persists
    client.put("/api/funnel/layout", json={"positions": {f"s-{sa}": {"x": 10, "y": 20}}})
    assert client.get("/api/funnel").json()["layout"][f"s-{sa}"] == {"x": 10.0, "y": 20.0}

    # Deleting a source cascades its routes
    client.delete(f"/api/sources/{sa}")
    assert all(x["source_id"] != sa for x in client.get("/api/funnel").json()["routes"])


def test_settings_validation_and_persistence(client):
    s = client.get("/api/settings").json()
    assert s["publishing"]["require_approval"] is True
    r = client.put("/api/settings", json={"ai": {"monthly_budget_usd": 40}})
    assert r.status_code == 200 and r.json()["ai"]["monthly_budget_usd"] == 40
    assert r.json()["ai"]["prefer_local_models"] is True
    assert client.put("/api/settings", json={"ai": {"monthly_budget_usd": -1}}).status_code == 422
    assert client.put("/api/settings", json={"bogus": {}}).status_code == 422
    assert client.get("/api/settings").json()["ai"]["monthly_budget_usd"] == 40


def test_dashboard_real_counts(client):
    _setup(client)
    d = client.get("/api/dashboard").json()
    assert d["accounts"]["sources_total"] == 3 and d["accounts"]["destinations_total"] == 4
    assert d["accounts"]["destinations_connected"] == 0
    assert d["pipeline"]["clips_published"] is None
    assert d["storage"]["used_bytes"] > 0
    assert len(client.get("/api/audit").json()) > 0
