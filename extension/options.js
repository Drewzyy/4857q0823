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
};
