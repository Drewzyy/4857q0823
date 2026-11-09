// Vyral desktop app (macOS + Windows).
//
// Starts the bundled background service (a ready-to-run folder in the app's resources) on a free
// loopback port, waits until it's healthy, then shows the UI it serves. If the service exits or
// never becomes healthy, the loading screen shows why, with the last log lines and the log path.
// Closing the window only hides it: Vyral keeps watching source accounts from the menu bar / tray,
// and starts at login (hidden). Quit from the tray icon stops everything.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::VecDeque;
use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

mod updates;

struct Backend(Mutex<Option<CommandChild>>);

const HIDDEN_ARG: &str = "--hidden";
const STARTUP_LIMIT: Duration = Duration::from_secs(150);

fn free_port() -> u16 {
    for port in [8765u16, 0] {
        if let Ok(l) = TcpListener::bind(("127.0.0.1", port)) {
            if let Ok(addr) = l.local_addr() {
                return addr.port();
            }
        }
    }
    8765
}

fn healthy(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut s) = TcpStream::connect_timeout(&addr, Duration::from_millis(300)) else { return false };
    let _ = s.set_read_timeout(Some(Duration::from_millis(1500)));
    let req = format!("GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
    if s.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = String::new();
    let _ = s.read_to_string(&mut buf);
    buf.starts_with("HTTP/1.1 200") && buf.contains("\"ok\":true")
}

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
}

/// Stops the background service (used before installing an update and on exit).
pub fn stop_service(app: &AppHandle) {
    if let Some(child) = app.state::<Backend>().0.lock().unwrap().take() {
        let _ = child.kill();
    }
}

fn new_token() -> String {
    let mut b = [0u8; 32];
    let _ = getrandom::fill(&mut b);
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn service_executable(app: &AppHandle) -> tauri::Result<PathBuf> {
    let name = if cfg!(windows) { "clippr-backend.exe" } else { "clippr-backend" };
    Ok(app.path().resource_dir()?.join("service").join(name))
}

/// Shows a failure on the loading screen (the window is still on the bundled splash page).
fn show_failure(win: &WebviewWindow, title: &str, recent: &Mutex<VecDeque<String>>, log_path: &str) {
    let details = recent.lock().map(|r| r.iter().cloned().collect::<Vec<_>>().join("\n")).unwrap_or_default();
    let js = format!(
        "window.vyralFailed && window.vyralFailed({}, {}, {})",
        serde_json::to_string(title).unwrap_or_default(),
        serde_json::to_string(&details).unwrap_or_default(),
        serde_json::to_string(log_path).unwrap_or_default()
    );
    let _ = win.show();
    let _ = win.eval(&js);
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app)))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, Some(vec![HIDDEN_ARG])))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Backend(Mutex::new(None)))
        .manage(updates::Pending(Mutex::new(None)))
        .setup(|app| {
            let started_hidden = std::env::args().any(|a| a == HIDDEN_ARG);
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Vyral")
                .inner_size(1440.0, 900.0)
                .min_inner_size(1100.0, 700.0)
                .visible(!started_hidden)
                .build()?;

            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(data_dir.join("logs"))?;
            let marker = data_dir.join(".autostart-initialized");
            if !marker.exists() {
                let _ = app.autolaunch().enable();
                let _ = std::fs::write(&marker, b"1");
            }

            // Everything the service prints goes to a log file, and the last lines are kept for the loading screen.
            let log_path = data_dir.join("logs").join("service-output.log");
            let log_display = log_path.to_string_lossy().into_owned();
            let log_file = OpenOptions::new().create(true).write(true).truncate(true).open(&log_path).ok().map(Mutex::new);
            let recent: Arc<Mutex<VecDeque<String>>> = Arc::new(Mutex::new(VecDeque::new()));
            let exited = Arc::new(AtomicBool::new(false));
            let exit_reason: Arc<Mutex<String>> = Arc::new(Mutex::new(String::new()));

            let port = free_port();
            // The shell and the service share the per-launch API token so the updater can report progress.
            let token = new_token();
            let ui_dir = app.path().resource_dir()?.join("ui");
            let exe = service_executable(app.handle())?;
            let spawned = app
                .shell()
                .command(exe.to_string_lossy().into_owned())
                .args([
                    "--port".to_string(),
                    port.to_string(),
                    "--frontend".to_string(),
                    ui_dir.to_string_lossy().into_owned(),
                    "--data-dir".to_string(),
                    data_dir.to_string_lossy().into_owned(),
                    // The service exits on its own if this app goes away, even after a crash or force-quit.
                    "--parent-pid".to_string(),
                    std::process::id().to_string(),
                ])
                .env("CLIPPR_DESKTOP", "1")
                .env("CLIPPR_API_TOKEN", token.clone())
                .spawn();

            match spawned {
                Ok((mut rx, child)) => {
                    *app.state::<Backend>().0.lock().unwrap() = Some(child);
                    let (recent2, exited2, reason2) = (recent.clone(), exited.clone(), exit_reason.clone());
                    tauri::async_runtime::spawn(async move {
                        while let Some(ev) = rx.recv().await {
                            let line = match ev {
                                CommandEvent::Stdout(l) | CommandEvent::Stderr(l) => String::from_utf8_lossy(&l).trim_end().to_string(),
                                CommandEvent::Error(e) => format!("error: {e}"),
                                CommandEvent::Terminated(p) => {
                                    *reason2.lock().unwrap() = format!("The background service stopped (exit code {:?}).", p.code);
                                    exited2.store(true, Ordering::SeqCst);
                                    format!("[service exited with code {:?}]", p.code)
                                }
                                _ => continue,
                            };
                            if let Some(f) = &log_file {
                                if let Ok(mut f) = f.lock() {
                                    let _ = writeln!(f, "{line}");
                                }
                            }
                            if let Ok(mut r) = recent2.lock() {
                                r.push_back(line);
                                while r.len() > 25 {
                                    r.pop_front();
                                }
                            }
                        }
                    });
                }
                Err(e) => {
                    *exit_reason.lock().unwrap() = format!("Couldn't start the background service: {e} ({})", exe.display());
                    exited.store(true, Ordering::SeqCst);
                }
            }

            let win = window.clone();
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let started = Instant::now();
                loop {
                    if healthy(port) {
                        if let Ok(url) = Url::parse(&format!("http://127.0.0.1:{port}/")) {
                            let _ = win.navigate(url);
                        }
                        updates::run(handle, port, token);
                        return;
                    }
                    if exited.load(Ordering::SeqCst) {
                        std::thread::sleep(Duration::from_millis(300)); // let the last output arrive
                        let reason = exit_reason.lock().map(|r| r.clone()).unwrap_or_default();
                        show_failure(&win, &reason, &recent, &log_display);
                        return;
                    }
                    if started.elapsed() > STARTUP_LIMIT {
                        show_failure(&win, "The background service didn't respond in time.", &recent, &log_display);
                        return;
                    }
                    std::thread::sleep(Duration::from_millis(300));
                }
            });

            let autostart_on = app.autolaunch().is_enabled().unwrap_or(false);
            let open = MenuItem::with_id(app, "open", "Open Vyral", true, None::<&str>)?;
            let login = CheckMenuItem::with_id(app, "login", "Start Vyral when computer starts", true, autostart_on, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Vyral (stops monitoring)", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &login, &sep, &quit])?;
            let login_item = login.clone();
            TrayIconBuilder::with_id("vyral")
                .icon(app.default_window_icon().cloned().expect("app icon"))
                .tooltip("Vyral is watching for new posts")
                .menu(&menu)
                .show_menu_on_left_click(cfg!(target_os = "macos"))
                .on_menu_event(move |app, e| match e.id.as_ref() {
                    "open" => show_main(app),
                    "login" => {
                        let al = app.autolaunch();
                        let enable = !al.is_enabled().unwrap_or(false);
                        let _ = if enable { al.enable() } else { al.disable() };
                        let _ = login_item.set_checked(al.is_enabled().unwrap_or(enable));
                    }
                    "quit" => {
                        // A downloaded update installs on the way out, so the next launch is the new version.
                        let _ = updates::install_pending(app); // failures are logged; quitting goes ahead either way
                        app.exit(0)
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                        if !cfg!(target_os = "macos") {
                            show_main(tray.app_handle());
                        }
                    }
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to start Vyral")
        .run(|app, event| match event {
            RunEvent::Exit => stop_service(app),
            #[cfg(target_os = "macos")]
            RunEvent::Reopen { .. } => show_main(app),
            _ => {}
        });
}
