async function show() {
  const { enabled, token, last } = await chrome.storage.local.get(["enabled", "token", "last"]);
  const { job } = await chrome.storage.session.get("job");
  document.getElementById("state").textContent = !token ? "Not set up: open Settings and paste Vyral's bridge token."
    : !enabled ? "Off: turn it on in Settings." : job ? `Posting to ${job.destination?.name || job.platform} now.` : "On: checks for due videos.";
  document.getElementById("last").textContent = last ? `${last.text} (${new Date(last.at).toLocaleTimeString()})` : "";
}
document.getElementById("now").onclick = async () => { await chrome.runtime.sendMessage({ type: "now" }); show(); };
document.getElementById("options").onclick = () => chrome.runtime.openOptionsPage();
show();
watchAccounts(document.getElementById("accounts"), true);
