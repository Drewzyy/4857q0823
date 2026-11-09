//! Automatic updates from the public vyral-releases repo.
//!
//! Every update is signed with Vyral's private update key; the app only installs files whose
//! signature matches the public key built into it. The UI talks to the background service, not to
//! this shell, so progress and requests ("check now", "restart to update") travel through the
//! service's /api/app-update endpoints, which this loop polls.

use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use tauri::{AppHandle, Manager};
use tauri_plugin_updater::{Update, UpdaterExt};

const CHECK_EVERY: Duration = Duration::from_secs(3600);
const FIRST_CHECK_AFTER: Duration = Duration::from_secs(45);
const RETRY_AFTER_ERROR: Duration = Duration::from_secs(600);
/// Names the version whose automatic install failed; that version then waits for the user's click.
const AUTO_FAILED: &str = ".auto-update-failed";
/// Tells the next launch to stay in the background, so an app that updated while hidden stays hidden.
pub const START_HIDDEN: &str = ".start-hidden";

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

fn data_file(app: &AppHandle, name: &str) -> Option<PathBuf> {
    app.path().app_data_dir().ok().map(|d| d.join(name))
}

/// The user is looking at Vyral right now, so it shouldn't restart under them.
fn in_use(app: &AppHandle) -> bool {
    app.get_webview_window("main")
        .is_some_and(|w| w.is_visible().unwrap_or(false) && w.is_focused().unwrap_or(false))
}

fn window_hidden(app: &AppHandle) -> bool {
    app.get_webview_window("main").is_some_and(|w| !w.is_visible().unwrap_or(true))
}

fn auto_failed(app: &AppHandle, version: &str) -> bool {
    data_file(app, AUTO_FAILED).and_then(|p| std::fs::read_to_string(p).ok()).is_some_and(|v| v.trim() == version)
}

/// Appends a line to logs/updater.log, so a failed update leaves a trace even after a restart.
fn log(app: &AppHandle, msg: &str) {
    let Ok(dir) = app.path().app_data_dir() else { return };
    let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(dir.join("logs").join("updater.log")) {
        let _ = writeln!(f, "[{secs}] {msg}");
    }
}

fn report(port: u16, token: &str, v: Value) {
    let _ = api(port, token, "POST", "/api/app-update/report", Some(&v));
}

/// Returns false if the check or download failed (worth retrying sooner than the next hourly check).
fn check_and_download(app: &AppHandle, port: u16, token: &str) -> bool {
    report(port, token, json!({"state": "checking"}));
    let up = match app.updater() {
        Ok(u) => u,
        Err(e) => {
            fail(app, port, token, format!("Update check unavailable: {e}"));
            return false;
        }
    };
    let found = tauri::async_runtime::block_on(up.check());
    let update = match found {
        Ok(Some(u)) => u,
        Ok(None) => {
            report(port, token, json!({"state": "none"}));
            return true;
        }
        Err(e) => {
            fail(app, port, token, format!("Couldn't check for updates: {e}"));
            return false;
        }
    };
    let version = update.version.clone();
    log(app, &format!("downloading {version}"));
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
            log(app, &format!("{version} downloaded and verified"));
            report(port, token, json!({"state": "ready", "version": version, "notes": notes}));
            true
        }
        Err(e) => {
            fail(app, port, token, format!("Download of {version} failed: {e}"));
            false
        }
    }
}

fn fail(app: &AppHandle, port: u16, token: &str, error: String) {
    log(app, &error);
    report(port, token, json!({"state": "error", "error": error}));
}

/// Installs a downloaded update. Ok(false) means nothing was waiting to be installed.
///
/// Windows' installer replaces files the background service has open, so the service stops first
/// (and on success the installer takes over and this process exits inside `install`). On macOS the
/// app bundle is swapped in one step while everything keeps running, so a failed install leaves
/// the app fully working and able to show the error; the service only stops once the swap worked.
pub fn install_pending(app: &AppHandle) -> Result<bool, String> {
    let pending = app.state::<Pending>().0.lock().unwrap().take();
    let Some((update, bytes)) = pending else { return Ok(false) };
    log(app, &format!("installing {}", update.version));
    if cfg!(windows) {
        crate::stop_service(app);
        std::thread::sleep(Duration::from_millis(1500));
    }
    if let Err(e) = update.install(bytes) {
        let msg = format!("Couldn't install {}: {e}", update.version);
        log(app, &msg);
        if let Some(p) = data_file(app, AUTO_FAILED) {
            let _ = std::fs::write(p, &update.version);
        }
        return Err(msg);
    }
    crate::stop_service(app);
    log(app, "installed, restarting");
    Ok(true)
}

pub fn run(app: AppHandle, port: u16, token: String) {
    std::thread::spawn(move || {
        let started = Instant::now();
        let mut last_check: Option<Instant> = None;
        loop {
            std::thread::sleep(Duration::from_secs(3));
            let Some(st) = api(port, &token, "GET", "/api/app-update", None) else { continue };
            let waiting = app.state::<Pending>().0.lock().unwrap().as_ref().map(|(u, _)| u.version.clone());
            let asked = st["install_requested"].as_bool() == Some(true);
            // Installs by itself once nobody is using the window and no clip is rendering, unless
            // installing this version already failed once (then it waits for the user's click).
            let auto = waiting.as_deref().is_some_and(|v| st["busy"].as_bool() == Some(false) && !in_use(&app) && !auto_failed(&app, v));
            if asked || auto {
                log(&app, if asked { "install requested" } else { "installing automatically" });
                report(port, &token, json!({"state": "installing"}));
                let hidden_marker = data_file(&app, START_HIDDEN).filter(|_| window_hidden(&app));
                if let Some(p) = &hidden_marker {
                    let _ = std::fs::write(p, b"1");
                }
                match install_pending(&app) {
                    Ok(true) => app.restart(),
                    // On Windows the service is already stopped; restarting brings it back.
                    Err(_) if cfg!(windows) => app.restart(),
                    Err(e) => {
                        if let Some(p) = &hidden_marker {
                            let _ = std::fs::remove_file(p);
                        }
                        fail(&app, port, &token, format!("{e}. Your current version keeps running."));
                        last_check = Some(Instant::now());
                    }
                    Ok(false) => {
                        fail(&app, port, &token, "The downloaded update was lost. Checking again.".into());
                        last_check = None;
                    }
                }
                continue;
            }
            let due = match last_check {
                None => started.elapsed() >= FIRST_CHECK_AFTER,
                Some(t) => t.elapsed() >= CHECK_EVERY,
            };
            if (st["check_requested"].as_bool() == Some(true) || (due && waiting.is_none())) && st["state"] != "downloading" {
                let ok = check_and_download(&app, port, &token);
                // After a failure, check again in 10 minutes rather than an hour.
                let now = Instant::now();
                last_check = Some(if ok { now } else { now.checked_sub(CHECK_EVERY - RETRY_AFTER_ERROR).unwrap_or(now) });
            }
        }
    });
}
