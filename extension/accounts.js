// The Accounts list (Settings and the popup): each Vyral page, its site's logo, and whether this Chrome is signed
// into it on that site. You sign in yourself on the site's own page; the extension only reads who's shown as signed in.
const LOGIN_PAGES = {
  tiktok: "https://www.tiktok.com/login",
  instagram: "https://www.instagram.com/accounts/login/",
  youtube: "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fstudio.youtube.com%2F",
};
const SITE_NAMES = { tiktok: "TikTok", instagram: "Instagram", youtube: "YouTube" };
const LOGOS = {
  tiktok: '<svg viewBox="0 0 24 24" width="20" height="20"><rect width="24" height="24" rx="5" fill="#000"/><path d="M14 5v9.2a2.8 2.8 0 1 1-2.4-2.8V9a5.3 5.3 0 1 0 4.9 5.3V9.6a6 6 0 0 0 3 1V8.2A3.4 3.4 0 0 1 16.4 5z" fill="#fff"/><path d="M14 5h2.4" stroke="#25f4ee" stroke-width=".8"/></svg>',
  instagram: '<svg viewBox="0 0 24 24" width="20" height="20"><defs><linearGradient id="ig" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#feda75"/><stop offset=".5" stop-color="#d62976"/><stop offset="1" stop-color="#4f5bd5"/></linearGradient></defs><rect width="24" height="24" rx="6" fill="url(#ig)"/><rect x="5" y="5" width="14" height="14" rx="4" fill="none" stroke="#fff" stroke-width="1.8"/><circle cx="12" cy="12" r="3.3" fill="none" stroke="#fff" stroke-width="1.8"/><circle cx="16.3" cy="7.7" r="1" fill="#fff"/></svg>',
  youtube: '<svg viewBox="0 0 24 24" width="20" height="20"><rect y="4" width="24" height="16" rx="5" fill="#f00"/><path d="M10 8.5v7l6-3.5z" fill="#fff"/></svg>',
};

const norm = (s) => String(s || "").trim().replace(/^@/, "").toLowerCase();

// green: signed in as this page; amber: someone else, or can't tell; grey: not signed in.
function statusOf(acc, seen) {
  if (!seen || seen.signedIn === null || seen.signedIn === undefined) return { light: "amber", text: "Can't tell: open the site" };
  if (seen.signedIn === false) return { light: "grey", text: "Not signed in" };
  const shown = seen.handle || seen.name;
  if (!shown) return { light: "amber", text: "Signed in: open Studio to check the channel" };
  if ([norm(acc.handle), norm(acc.display_name)].includes(norm(shown))) return { light: "green", text: "Signed in, ready to post" };
  return { light: "amber", text: `Signed in as ${seen.handle || shown}: switch account` };
}

async function renderAccounts(box, compact) {
  box.textContent = "Checking…";
  const got = await chrome.runtime.sendMessage({ type: "accounts" });
  box.textContent = "";
  if (!got || got.error) { box.textContent = got?.error || "Can't reach Vyral"; return; }
  if (!got.accounts.length) { box.textContent = "No TikTok, Instagram or YouTube pages in Vyral yet (Destinations)."; return; }
  for (const acc of got.accounts) {
    const seen = got.status[acc.platform];
    const st = statusOf(acc, seen);
    const row = document.createElement("div");
    row.className = "acct";
    const logo = document.createElement("span");
    logo.className = "logo";
    logo.innerHTML = LOGOS[acc.platform]; // our own fixed SVG, nothing from the page
    logo.title = SITE_NAMES[acc.platform];
    const who = document.createElement("span");
    who.className = "who";
    const name = document.createElement("b");
    name.textContent = acc.display_name;
    const sub = document.createElement("span");
    sub.className = "sub";
    sub.textContent = `${acc.handle || ""} ${st.text}`.trim();
    sub.title = seen?.at ? `Checked ${new Date(seen.at).toLocaleString()}` : "Not checked yet";
    who.append(name, sub);
    const light = document.createElement("span");
    light.className = "light " + st.light;
    light.title = st.text;
    row.append(light, logo, who);
    if (st.light !== "green") {
      const b = document.createElement("button");
      b.textContent = st.light === "grey" ? "Sign in" : "Open";
      b.onclick = () => chrome.tabs.create({ url: st.light === "grey" ? LOGIN_PAGES[acc.platform] : acc.upload_page });
      row.append(b);
    }
    if (!compact) {
      const lab = document.createElement("label");
      lab.className = "open";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = got.openOnStart[acc.id] !== false;
      cb.onchange = async () => {
        const { openOnStart = {} } = await chrome.storage.local.get("openOnStart");
        await chrome.storage.local.set({ openOnStart: { ...openOnStart, [acc.id]: cb.checked } });
      };
      lab.append(cb, " open when the extension turns on");
      row.append(lab);
    }
    box.append(row);
  }
}

// Ask open site tabs who's signed in, then draw again when they answer.
function watchAccounts(box, compact) {
  renderAccounts(box, compact);
  chrome.runtime.sendMessage({ type: "refresh" });
  let t;
  chrome.storage.onChanged.addListener((c) => { if (c.status) { clearTimeout(t); t = setTimeout(() => renderAccounts(box, compact), 300); } });
}
