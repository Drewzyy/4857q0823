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

async function tick() {
  const cfg = await settings();
  if (!cfg.enabled || !cfg.token) return;
  const { job } = await chrome.storage.session.get("job");
  if (job) {
    if (Date.now() - job.started > LIMIT_MS) await finish(job, { posted: false, reason: "It didn't finish within 25 minutes" });
    return; // one post at a time
  }
  let next;
  try { next = (await call(cfg, "/companion/next")).job; } catch (e) { await note(`Can't reach Vyral: ${e.message}`); return; }
  if (!next) { await note("Nothing due right now"); return; }
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

async function schedule() {
  const cfg = await settings();
  chrome.alarms.create("tick", { periodInMinutes: Math.max(1, Number(cfg.every) || 5) });
}
chrome.runtime.onInstalled.addListener(schedule);
chrome.runtime.onStartup.addListener(schedule);
chrome.storage.onChanged.addListener((c) => { if (c.every) schedule(); });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "tick") tick(); });
