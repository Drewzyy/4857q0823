const KEYS = { address: "http://127.0.0.1:47821", token: "", every: 5, enabled: false };

chrome.storage.local.get(Object.keys(KEYS)).then((v) => {
  const s = { ...KEYS, ...v };
  for (const k of ["address", "token", "every"]) document.getElementById(k).value = s[k];
  document.getElementById("enabled").checked = !!s.enabled;
});

document.getElementById("save").onclick = async () => {
  const address = document.getElementById("address").value.trim().replace(/\/$/, "") || KEYS.address;
  if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(address)) {
    // The upload pages fetch the video straight from Vyral; a secure site may only do that from this same computer.
    document.getElementById("saved").textContent = "Use Vyral on this computer: http://127.0.0.1:47821 (the port is in Vyral's Settings).";
    return;
  }
  await chrome.storage.local.set({ address, token: document.getElementById("token").value.trim(),
    every: Math.min(60, Math.max(1, Number(document.getElementById("every").value) || 5)), enabled: document.getElementById("enabled").checked });
  document.getElementById("saved").textContent = "Saved";
  renderAccounts(document.getElementById("accounts"), false);
};

watchAccounts(document.getElementById("accounts"), false);
document.getElementById("recheck").onclick = () => watchAccounts(document.getElementById("accounts"), false);

// Tells apart the three ways setup goes wrong: nothing answering at the address, a wrong token, or not Vyral there.
async function testConnection(address, token) {
  const where = "Vyral › Settings › Muse & posting";
  let r;
  try {
    r = await fetch(address + "/companion/ping", { cache: "no-store" });
  } catch (e) {
    return `Can't open ${address} (${e.message}). Is Vyral open? In ${where}, is the bridge on, and is ${address.split(":").pop()} its port?`;
  }
  if (r.status === 421) return `Vyral refused the address ${address}: use http://127.0.0.1 and the bridge port.`;
  const pong = await r.json().catch(() => null);
  if (!r.ok || !pong || pong.app !== "vyral") return `Something else answers at ${address} (not Vyral). Check the port in ${where}.`;
  if (!token) return "Vyral is reachable. Now paste the bridge token from " + where + ".";
  const a = await fetch(address + "/companion/accounts", { headers: { Authorization: "Bearer " + token } }).catch(() => null);
  if (a && a.status === 401) return `Wrong token: copy the bridge token from ${where} (not the Discord, Dropbox or any other token) and Save.`;
  if (!a || !a.ok) return `Vyral is reachable but answered ${a ? a.status : "nothing"}; try again.`;
  return "Connected to Vyral. Save if you changed anything.";
}

document.getElementById("test").onclick = async () => {
  const out = document.getElementById("tested");
  out.textContent = "Testing…";
  const address = document.getElementById("address").value.trim().replace(/\/$/, "") || KEYS.address;
  out.textContent = await testConnection(address, document.getElementById("token").value.trim());
};
