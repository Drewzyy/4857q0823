// Shared by the site scripts: asking for the job, waiting for the page, putting the video in, typing, and stopping
// for anything that needs a person (a captcha, a login, a check). Never works around any of them.
const Vyral = {
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),

  async job() {
    return chrome.runtime.sendMessage({ type: "job" });
  },

  // A captcha, a login or a "confirm it's you" check: stop and hand over to the person.
  blocked() {
    if (/\/(login|accounts\/login|signin)/i.test(location.pathname)) return "The site wants you to log in";
    if (document.querySelector('iframe[src*="captcha" i], [id*="captcha" i], [class*="captcha" i], iframe[src*="challenge" i]'))
      return "The site is showing a captcha";
    if (/confirm (it'?s|that it'?s) you|verify (it'?s|that) you|are you a robot|unusual activity|suspicious/i.test(document.body.innerText))
      return "The site wants to check it's you";
    return null;
  },

  async waitFor(find, ms = 60000, what = "the page") {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const stop = this.blocked();
      if (stop) throw new Error(stop);
      const got = find();
      if (got) return got;
      await this.sleep(500);
    }
    throw new Error(`Timed out waiting for ${what} (the site may have changed)`);
  },

  byText(re, selector = 'button, div[role="button"], a[role="button"], span[role="button"]', root = document) {
    return [...root.querySelectorAll(selector)].find((el) => re.test((el.innerText || el.textContent || "").trim()) &&
      !el.disabled && el.getAttribute("aria-disabled") !== "true");
  },

  // The page is https, so it can't reach Vyral on this computer itself (Chrome blocks that): the background page
  // fetches the video and streams it over in pieces.
  video(job) {
    return new Promise((resolve, reject) => {
      const parts = [];
      const port = chrome.runtime.connect({ name: "video" });
      port.onMessage.addListener((m) => {
        if (m.error) { reject(new Error(m.error)); port.disconnect(); }
        else if (m.chunk) parts.push(Uint8Array.from(atob(m.chunk), (c) => c.charCodeAt(0)));
        else if (m.done) { resolve(new File(parts, `vyral-${job.output_id}.mp4`, { type: "video/mp4" })); port.disconnect(); }
      });
      port.onDisconnect.addListener(() => reject(new Error("Couldn't get the video from Vyral (the connection dropped)")));
      port.postMessage({ video: job.video });
    });
  },

  putFile(input, file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  },

  // Typed the way the site's own editor expects (rich editors ignore a plain value change).
  type(el, text) {
    el.focus();
    document.execCommand("selectAll", false, null);
    document.execCommand("insertText", false, text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  },

  banner(text) {
    let b = document.getElementById("vyral-banner");
    if (!b) {
      b = document.createElement("div");
      b.id = "vyral-banner";
      b.style.cssText = "position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:2147483647;background:#111;color:#fff;" +
        "font:600 14px system-ui;padding:10px 16px;border-radius:10px;box-shadow:0 4px 20px rgba(0,0,0,.4);max-width:90vw";
      document.documentElement.appendChild(b);
    }
    b.textContent = "Vyral: " + text;
  },

  async press(button, job, ready, find) {
    if (job.auto) {
      button.click();
      return;
    }
    this.banner(ready + " (or tap Post it in the Discord ping on your phone)");
    chrome.runtime.sendMessage({ type: "attention", text: `${job.destination?.name || job.platform}: ${ready}` });
    // Posting from your phone: the Discord ping's link. Checked every few seconds while this page waits for you.
    (async () => {
      for (;;) {
        await this.sleep(3000);
        if (!document.contains(button) && !(find && find())) return; // posted by hand, or the page moved on
        if (await chrome.runtime.sendMessage({ type: "pressed" })) {
          const b = (find && find()) || button;
          this.banner("Post pressed from your phone: posting…");
          b.click();
          return;
        }
      }
    })();
  },

  report(result) {
    this.banner(result.posted ? "posted. Telling Vyral." : `stopped: ${result.reason}`);
    return chrome.runtime.sendMessage({ type: "result", result });
  },

  // Runs a site's steps for the job this tab was opened for; any stop is reported with why.
  async run(steps) {
    const got = await this.job();
    if (!got) return; // not a tab Vyral opened
    const { job } = got;
    this.banner(`posting to ${job.destination?.name || job.platform}…`);
    try {
      const url = await steps(job, got);
      await this.report({ posted: true, post_url: url || null });
    } catch (e) {
      const why = e.message || String(e);
      if (this.blocked()) await chrome.runtime.sendMessage({ type: "attention", stopped: true, text: why });
      await this.report({ posted: false, reason: why });
    }
  },
};
