//! Automatic updates from the public vyral-releases repo.
//!
//! Every update is signed with Vyral's private update key; the app only installs files whose
//! signature matches the public key built into it. The UI talks to the background service, not to
//! this shell, so progress and requests ("check now", "restart to update") travel through the
//! service's /api/app-update endpoints, which this loop polls.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri::{AppHandle, Manager, Url};
use tauri_plugin_updater::{Update, UpdaterExt};

const CHECK_EVERY: Duration = Duration::from_secs(4 * 3600);
const FIRST_CHECK_AFTER: Duration = Duration::from_secs(45);

/// A downloaded, signature-checked update waiting to be installed.
pub struct Pending(pub Mutex<Option<(Update, Vec<u8>)>>);

pub fn api(port: u16, token: &str, method: &str, path: &str, body: Option<&Value>) -> Option<Value> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut s = TcpStream::connect_timeout(&addr, Duration::from_millis(500)).ok()?;
    let _ = s.set_read_timeout(Some(Duration::from_secs(5)));
    let payload = body.map(|b| b.to_string()).unwrap_or_default();
    let req = format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-Clippr-Token: {token}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{payload}",
        payload.len()
    );
    s.write_all(req.as_bytes()).ok()?;
    let mut buf = String::new();
    let _ = s.read_to_string(&mut buf);
    let body = buf.split_once("\r\n\r\n")?.1;
    serde_json::from_str(body).ok()
}

fn report(port: u16, token: &str, v: Value) {
    let _ = api(port, token, "POST", "/api/app-update/report", Some(&v));
}

fn updater(app: &AppHandle) -> Result<tauri_plugin_updater::Updater, String> {
    let mut b = app.updater_builder();
    // Lets tests point the app at a local update server.
    if let Ok(u) = std::env::var("VYRAL_UPDATE_URL") {
        let url = Url::parse(&u).map_err(|e| e.to_string())?;
        b = b.endpoints(vec![url]).map_err(|e| e.to_string())?;
    }
    b.build().map_err(|e| e.to_string())
}

fn check_and_download(app: &AppHandle, port: u16, token: &str) {
    report(port, token, json!({"state": "checking"}));
    let up = match updater(app) {
        Ok(u) => u,
        Err(e) => return report(port, token, json!({"state": "error", "error": format!("Update check unavailable: {e}")})),
    };
    let found = tauri::async_runtime::block_on(up.check());
    let update = match found {
        Ok(Some(u)) => u,
        Ok(None) => return report(port, token, json!({"state": "none"})),
        Err(e) => return report(port, token, json!({"state": "error", "error": format!("Couldn't check for updates: {e}")})),
    };
    let version = update.version.clone();
    let notes = update.body.clone().unwrap_or_default();
    report(port, token, json!({"state": "downloading", "version": version, "notes": notes, "progress": 0.0}));
    let mut got: u64 = 0;
    let mut last = Instant::now();
    let result = tauri::async_runtime::block_on(update.download(
        |chunk, total| {
            got += chunk as u64;
            if let Some(t) = total {
                if last.elapsed() > Duration::from_secs(2) {
                    last = Instant::now();
                    report(port, token, json!({"state": "downloading", "version": version, "progress": (got as f64 / t as f64).min(1.0)}));
                }
            }
        },
        || {},
    ));
    match result {
        Ok(bytes) => {
            *app.state::<Pending>().0.lock().unwrap() = Some((update, bytes));
            report(port, token, json!({"state": "ready", "version": version, "notes": notes}));
        }
        Err(e) => report(port, token, json!({"state": "error", "version": version, "error": format!("Download failed: {e}")})),
    }
}

/// Installs a downloaded update. Stops the background service first so its files can be replaced.
/// Returns false if there was nothing to install.
pub fn install_pending(app: &AppHandle) -> bool {
    let pending = app.state::<Pending>().0.lock().unwrap().take();
    let Some((update, bytes)) = pending else { return false };
    crate::stop_service(app);
    std::thread::sleep(Duration::from_millis(1500));
    // On Windows this hands over to the installer, which closes and reopens Vyral.
    let _ = update.install(bytes);
    true
}

pub fn run(app: AppHandle, port: u16, token: String) {
    std::thread::spawn(move || {
        let started = Instant::now();
        let mut last_check: Option<Instant> = None;
        loop {
            std::thread::sleep(Duration::from_secs(3));
            let Some(st) = api(port, &token, "GET", "/api/app-update", None) else { continue };
            if st["install_requested"].as_bool() == Some(true) {
                report(port, &token, json!({"state": "installing"}));
                if install_pending(&app) {
                    app.restart();
                }
                report(port, &token, json!({"state": "error", "error": "The downloaded update was lost. Checking again."}));
                last_check = None;
                continue;
            }
            let due = match last_check {
                None => started.elapsed() >= FIRST_CHECK_AFTER,
                Some(t) => t.elapsed() >= CHECK_EVERY,
            };
            let ready = app.state::<Pending>().0.lock().unwrap().is_some();
            if (st["check_requested"].as_bool() == Some(true) || (due && !ready)) && st["state"] != "downloading" {
                last_check = Some(Instant::now());
                check_and_download(&app, port, &token);
            }
        }
    });
}
