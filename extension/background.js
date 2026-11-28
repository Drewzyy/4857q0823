// Vyral Companion: asks Vyral for the next approved video that's due, opens the site's upload page, and reports
// back what happened. The page itself (common.js + sites/*.js) puts the video in and fills in the caption.
const DEFAULTS = { address: "http://127.0.0.1:47821", token: "", enabled: false, every: 5 };
const LIMIT_MS = 25 * 60 * 1000; // a post that hasn't finished in 25 minutes is given up on (it waits an hour in Vyral)

async function settings() {
  return { ...DEFAULTS, ...(await chrome.storage.local.get(Object.keys(DEFAULTS))) };
}

async function call(cfg, path, init = {}) {
  const r = await fetch(cfg.address.replace(/\/$/, "") + path, {
    ...init, headers: { Authorization: "Bearer " + cfg.token, "Content-Type": "application/json", ...(init.headers || {}) } });
  if (!r.ok) throw new Error(`Vyral said ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

async function note(text) {
  await chrome.storage.local.set({ last: { text, at: new Date().toISOString() } });
}

function notify(title, message) {
  chrome.notifications.create({ type: "basic", iconUrl: "icon.png", title, message, priority: 2 });
}

// Tells Vyral the extension is here: its version, whether posting is on, and who each site showed as signed in
// (only what accounts.js shows: signed in or not, and the visible handle or channel name). Vyral answers with the
// version it carries; when that's newer and nothing is posting, the extension reloads to pick up the new files
// Vyral copied into the folder Chrome loads it from.
async function heartbeat() {
  const cfg = await settings();
  if (!cfg.token) return;
  const { status = {} } = await chrome.storage.local.get("status");
  const version = chrome.runtime.getManifest().version;
  let bundled;
  try {
    ({ bundled_version: bundled } = await call(cfg, "/companion/status", { method: "POST",
      body: JSON.stringify({ version, enabled: !!cfg.enabled, every: Number(cfg.every) || 5, seen: status }) }));
  } catch { return; } // tick() says when Vyral can't be reached
  const { job } = await chrome.storage.session.get("job");
  if (bundled && newer(bundled, version) && !job) {
    const { reloadedFor } = await chrome.storage.local.get("reloadedFor");
    if (reloadedFor === bundled) { // reloaded once already and still old: Chrome loads it from another folder
      await note(`Vyral has version ${bundled}: load the extension from the folder shown in Vyral's Settings`);
      return;
    }
    await chrome.storage.local.set({ reloadedFor: bundled });
    await note(`Updating to ${bundled}`);
    chrome.runtime.reload();
  }
}

function newer(a, b) {
  const x = String(a).split(".").map(Number), y = String(b).split(".").map(Number);
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
}

async function tick() {
  await heartbeat();
  const cfg = await settings();
  if (!cfg.enabled || !cfg.token) return;
  const { job } = await chrome.storage.session.get("job");
  if (job) {
    if (Date.now() - job.started > LIMIT_MS) await finish(job, { posted: false, reason: "It didn't finish within 25 minutes" });
    return; // one post at a time
  }
  let next, why;
  try { ({ job: next, why } = await call(cfg, "/companion/next")); } catch (e) { await note(`Can't reach Vyral: ${e.message}`); return; }
  if (!next) { await note(`Nothing due right now${why ? ": " + why : ""}`); return; }
  const tab = await chrome.tabs.create({ url: next.upload_page, active: true });
  await chrome.storage.session.set({ job: { ...next, tab: tab.id, started: Date.now() } });
  await note(`Posting to ${next.destination?.name || next.platform}${next.auto ? " (Auto-post)" : ": fill-in, you press Post"}`);
}

async function finish(job, result) {
  const cfg = await settings();
  await chrome.storage.session.remove("job");
  try {
    await call(cfg, "/companion/result", { method: "POST", body: JSON.stringify({ output_id: job.output_id, ...result }) });
  } catch (e) { await note(`Couldn't tell Vyral: ${e.message}`); }
  if (result.posted) {
    await note(`Posted to ${job.destination?.name || job.platform}`);
  } else {
    await note(`Not posted: ${result.reason}`);
    notify("Vyral Companion: not posted", `${job.destination?.name || job.platform}: ${result.reason}`);
  }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    const { job } = await chrome.storage.session.get("job");
    if (msg.type === "job") { // a site page asks whether it has work: only the tab opened for it does
      const cfg = await settings();
      reply(job && sender.tab && sender.tab.id === job.tab ? { job, address: cfg.address, token: cfg.token } : null);
    } else if (msg.type === "result" && job && sender.tab && sender.tab.id === job.tab) {
      await finish(job, msg.result);
      reply(true);
    } else if (msg.type === "attention" && job) { // a captcha, a login, or waiting for you to press Post
      notify("Vyral Companion needs you", msg.text);
      try { // and a Discord ping from Vyral, so it reaches your phone
        await call(await settings(), "/companion/result", { method: "POST",
          body: JSON.stringify({ output_id: job.output_id, attention: true, stopped: !!msg.stopped, text: msg.text }) });
      } catch (e) { await note(`Couldn't tell Vyral: ${e.message}`); }
      reply(true);
    } else if (msg.type === "pressed" && job && sender.tab && sender.tab.id === job.tab) { // Post tapped on your phone?
      try { reply((await call(await settings(), `/companion/pressed/${job.output_id}`)).pressed); } catch { reply(false); }
    } else if (msg.type === "whoami" && sender.tab && SITES.includes(msg.platform)) { // a site page says who's signed in
      const { status = {} } = await chrome.storage.local.get("status");
      const seen = { signedIn: msg.seen?.signedIn ?? null, handle: String(msg.seen?.handle || "").slice(0, 60) || null,
        name: String(msg.seen?.name || "").slice(0, 100) || null, at: new Date().toISOString() };
      const changed = JSON.stringify({ ...status[msg.platform], at: 0 }) !== JSON.stringify({ ...seen, at: 0 });
      await chrome.storage.local.set({ status: { ...status, [msg.platform]: seen } });
      if (changed) heartbeat(); // Vyral's Settings shows the new light right away
      reply(true);
    } else if (msg.type === "accounts") {
      reply(await accounts());
    } else if (msg.type === "refresh") {
      await refresh();
      reply(true);
    } else if (msg.type === "now") {
      await tick();
      reply(true);
    } else reply(null);
  })();
  return true;
});

// The video for the upload tab, in base64 pieces: only the tab opened for the job may ask, and only for its video.
chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "video") return;
  port.onMessage.addListener(async (msg) => {
    try {
      const { job } = await chrome.storage.session.get("job");
      if (!job || !port.sender.tab || port.sender.tab.id !== job.tab || msg.video !== job.video) throw new Error("Not the video for this post");
      const cfg = await settings();
      const r = await fetch(cfg.address.replace(/\/$/, "") + job.video, { headers: { Authorization: "Bearer " + cfg.token } });
      if (!r.ok) throw new Error(`Couldn't get the video from Vyral (${r.status})`);
      const reader = r.body.getReader();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        let bin = "";
        for (let i = 0; i < value.length; i += 0x8000) bin += String.fromCharCode(...value.subarray(i, i + 0x8000));
        port.postMessage({ chunk: btoa(bin) });
      }
      port.postMessage({ done: true });
    } catch (e) { port.postMessage({ error: e.message || String(e) }); }
  });
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const { job } = await chrome.storage.session.get("job");
  if (job && job.tab === tabId) await finish(job, { posted: false, reason: "The upload tab was closed" });
});

// ---- Accounts: your Vyral pages, and who's signed in on each site in this Chrome (sites/whoami.js reads it off the page) ----
const SITES = ["tiktok", "instagram", "youtube"];
const SITE_TABS = ["https://www.tiktok.com/*", "https://www.instagram.com/*", "https://studio.youtube.com/*", "https://www.youtube.com/*"];

async function accounts() {
  const cfg = await settings();
  const { status = {}, openOnStart = {}, accountsCache = [] } = await chrome.storage.local.get(["status", "openOnStart", "accountsCache"]);
  if (!cfg.token) return { error: "Not set up: paste Vyral's bridge token above and Save." };
  try {
    const { accounts: list } = await call(cfg, "/companion/accounts");
    await chrome.storage.local.set({ accountsCache: list });
    return { accounts: list, status, openOnStart };
  } catch (e) {
    return accountsCache.length ? { accounts: accountsCache, status, openOnStart } : { error: `Can't reach Vyral: ${e.message}` };
  }
}

async function refresh() { // the open site tabs look again and report (no new tabs opened)
  for (const tab of await chrome.tabs.query({ url: SITE_TABS })) {
    try { await chrome.tabs.sendMessage(tab.id, { type: "whoami?" }); } catch { /* the page hasn't loaded the script yet */ }
  }
}

async function openAccounts() { // when it's turned on: the upload page of each site with a page ticked, one tab per site
  const got = await accounts();
  if (got.error) { await note(got.error); return; }
  const pages = [...new Set(got.accounts.filter((a) => got.openOnStart[a.id] !== false).map((a) => a.upload_page))];
  const open = (await chrome.tabs.query({ url: SITE_TABS })).map((t) => { try { return new URL(t.url).hostname; } catch { return ""; } });
  const site = (h) => h.replace(/^(www|studio)\./, ""); // youtube.com and studio.youtube.com are one site
  for (const url of pages) { // Vyral opens these at startup too: a site already open isn't opened again
    if (!open.some((h) => site(h) === site(new URL(url).hostname))) await chrome.tabs.create({ url, active: false });
  }
}

chrome.storage.onChanged.addListener((c, area) => {
  if (area === "local" && c.enabled && c.enabled.newValue && !c.enabled.oldValue) openAccounts();
});

async function schedule() {
  const cfg = await settings();
  chrome.alarms.create("tick", { periodInMinutes: Math.max(1, Number(cfg.every) || 5) });
}
chrome.runtime.onInstalled.addListener(schedule);
chrome.runtime.onStartup.addListener(schedule);
chrome.runtime.onStartup.addListener(heartbeat);
chrome.storage.onChanged.addListener((c) => { if (c.every) schedule(); });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "tick") tick(); });
