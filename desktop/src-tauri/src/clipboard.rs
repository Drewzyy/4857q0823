//! Clipboard pickup: when the user copies a TikTok or YouTube Shorts video link (on this computer, or
//! on an iPhone through Universal Clipboard), hand it to the background service, which makes the clip.
//!
//! Only text that is a single video link is ever sent; anything else on the clipboard is ignored and
//! never leaves this process. The service decides whether pickup is switched on (Settings).

use std::time::Duration;

use serde_json::json;
use tauri::AppHandle;
use tauri_plugin_clipboard_manager::ClipboardExt;

const POLL: Duration = Duration::from_millis(1500);

/// A TikTok video (full or short share link) or a YouTube Short, and nothing else.
fn video_link(text: &str) -> Option<&str> {
    let t = text.trim();
    if t.len() > 300 || t.contains(char::is_whitespace) {
        return None;
    }
    let rest = t.strip_prefix("https://")?;
    let host = rest.split('/').next().unwrap_or("");
    let path = &rest[host.len()..];
    let tiktok = matches!(host, "www.tiktok.com" | "tiktok.com" | "m.tiktok.com")
        && (path.contains("/video/") || (path.starts_with("/t/") && path.len() > 3));
    let tiktok_short = matches!(host, "vm.tiktok.com" | "vt.tiktok.com") && rest.len() > host.len() + 1;
    let short = matches!(host, "www.youtube.com" | "youtube.com" | "m.youtube.com") && rest.contains("/shorts/");
    (tiktok || tiktok_short || short).then_some(t)
}

pub fn run(app: AppHandle, port: u16, token: String) {
    std::thread::spawn(move || {
        // Whatever is on the clipboard at launch was copied earlier; only new copies count.
        let mut last = app.clipboard().read_text().unwrap_or_default();
        loop {
            std::thread::sleep(POLL);
            let Ok(text) = app.clipboard().read_text() else { continue };
            if text == last {
                continue;
            }
            last = text;
            if let Some(url) = video_link(&last) {
                let _ = crate::updates::api(port, &token, "POST", "/api/intake", Some(&json!({"urls": [url], "from_clipboard": true})));
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::video_link;

    #[test]
    fn only_single_video_links_count() {
        assert!(video_link("https://www.tiktok.com/@clips/video/7351234567890").is_some());
        assert!(video_link(" https://vm.tiktok.com/ZMabc123/ ").is_some());
        assert!(video_link("https://www.tiktok.com/t/ZT8abc123/").is_some()); // what the TikTok app's Copy link gives
        assert!(video_link("https://www.youtube.com/shorts/abc123").is_some());
        assert!(video_link("https://www.tiktok.com/@clips").is_none()); // a profile, not a video
        assert!(video_link("https://www.youtube.com/watch?v=abc").is_none()); // regular videos are left alone
        assert!(video_link("check this https://www.tiktok.com/@a/video/1").is_none()); // only a bare link
        assert!(video_link("http://www.tiktok.com/@a/video/1").is_none());
        assert!(video_link("my password is hunter2").is_none());
    }
}
