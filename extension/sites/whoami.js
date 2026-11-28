// Who's signed in on this site, read from what the page shows (a profile link or the channel name). Never reads
// cookies, passwords or anything else: just the visible account name, so the Accounts list can show a green light.
(() => {
  const host = location.hostname;
  const platform = /tiktok\.com$/.test(host) ? "tiktok" : /instagram\.com$/.test(host) ? "instagram" : /youtube\.com$/.test(host) ? "youtube" : null;
  if (!platform) return;
  const text = (el) => (el?.innerText || el?.textContent || "").trim();
  const handleFrom = (href) => (href || "").match(/^(?:https?:\/\/[^/]+)?\/(@[\w.-]+)\/?$/)?.[1] || null;

  function look() {
    // Returns { signedIn: true, handle, name } | { signedIn: false } | { signedIn: null } (can't tell)
    if (platform === "tiktok") {
      const nav = document.querySelector('a[data-e2e="nav-profile"], a[data-e2e="profile-icon"]');
      if (nav && handleFrom(nav.getAttribute("href"))) return { signedIn: true, handle: handleFrom(nav.getAttribute("href")) };
      if (/^\/tiktokstudio/.test(location.pathname)) { // Studio shows your @handle near your avatar
        const at = [...document.querySelectorAll("header *, [class*='header' i] *, [class*='user' i] *")]
          .map(text).find((t) => /^@[\w.]{2,24}$/.test(t));
        if (at) return { signedIn: true, handle: at };
      }
      if (/^\/login/.test(location.pathname) || document.querySelector('[data-e2e="top-login-button"], [data-e2e="nav-login-button"]'))
        return { signedIn: false };
      return { signedIn: null };
    }
    if (platform === "instagram") {
      const img = [...document.querySelectorAll('a[href^="/"] img[alt$="profile picture" i]')].find((i) => /'s profile picture$/i.test(i.alt));
      if (img) return { signedIn: true, handle: "@" + img.alt.replace(/'s profile picture$/i, "") };
      if (/^\/accounts\/login/.test(location.pathname) || document.querySelector('a[href^="/accounts/login"]')) return { signedIn: false };
      return { signedIn: null };
    }
    // YouTube: Studio shows the channel's name in the side menu; youtube.com shows a Sign in button when signed out.
    const name = text(document.querySelector("ytcp-navigation-drawer #entity-name, #entity-name"));
    if (host === "studio.youtube.com" && name) return { signedIn: true, name };
    if (document.querySelector('a[href*="accounts.google.com/ServiceLogin"], ytd-button-renderer a[aria-label="Sign in" i]')) return { signedIn: false };
    if (document.querySelector("ytd-topbar-menu-button-renderer #avatar-btn, button#avatar-btn")) return { signedIn: true }; // signed in, but which channel isn't shown here
    return { signedIn: null };
  }

  let sent = "";
  async function report() {
    const seen = look();
    const key = JSON.stringify(seen);
    if (key === sent) return;
    sent = key;
    try { await chrome.runtime.sendMessage({ type: "whoami", platform, seen }); } catch { /* the extension was reloaded */ }
  }
  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (msg.type === "whoami?") { sent = ""; report(); reply(true); }
  });
  // The page fills in after loading: look a few times, then settle.
  [0, 2000, 5000, 10000, 20000].forEach((ms) => setTimeout(report, ms));
})();
