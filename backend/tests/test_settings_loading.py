from clippr.models import Setting
from clippr.schemas import AppSettings, DestinationSettings, lenient

OLD = {  # as saved by an earlier Vyral, with options since removed and one value no longer allowed
    "monitoring": {"enabled": False, "interval_minutes": 25, "streams_to_search": 999},
    "ai": {"monthly_budget_usd": 25}, "publishing": {"require_approval": True}, "storage": {"retention_days": 14, "max_cache_gb": 50},
}


def test_one_bad_or_retired_option_never_resets_the_rest():
    s = lenient(AppSettings, OLD)
    assert s.monitoring.enabled is False and s.monitoring.interval_minutes == 25
    assert s.monitoring.streams_to_search == 4  # the bad value alone falls back to its default
    assert s.storage.retention_days == 14
    assert lenient(AppSettings, None) == AppSettings() and lenient(AppSettings, "garbage") == AppSettings()
    d = lenient(DestinationSettings, {"hashtags": ["#a"], "visibility": "public", "branding": {"watermark_text": "x"}})
    assert d.hashtags == ["#a"]


def test_saved_settings_from_an_older_version_still_load_and_save(client, ctx):
    with ctx.db.session() as s:
        s.add(Setting(key="app", value=OLD))
    got = client.get("/api/settings").json()
    assert got["monitoring"]["interval_minutes"] == 25 and got["storage"]["retention_days"] == 14 and "ai" not in got
    r = client.put("/api/settings", json={"monitoring": {"interval_minutes": 30}})
    assert r.status_code == 200 and r.json()["monitoring"]["enabled"] is False
    assert client.put("/api/settings", json={"monitoring": {"interval_minutes": 1}}).status_code == 422  # input stays strict


def test_a_page_with_retired_options_can_still_be_edited(client, ctx):
    from clippr.models import DestinationAccount

    did = client.post("/api/destinations", json={"platform": "tiktok", "display_name": "Old page"}).json()["id"]
    with ctx.db.session() as s:
        d = s.get(DestinationAccount, did)
        d.settings = {**d.settings, "visibility": "public", "schedule": [], "title_style": "funny"}
    r = client.patch(f"/api/destinations/{did}", json={"settings": {"hashtags": ["#core"]}})
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["hashtags"] == ["#core"] and "visibility" not in r.json()["settings"]
