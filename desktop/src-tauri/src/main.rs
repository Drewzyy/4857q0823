// Vyral desktop app (macOS + Windows).
//
// Starts the bundled background service on a free loopback port, waits until it's healthy,
// then shows the UI it serves. Closing the window only hides it: Vyral keeps watching source
// accounts and making clips from the menu bar / system tray. It starts at login (hidden) so
// monitoring runs whenever the computer is on. Quit from the tray icon stops everything.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct Backend(Mutex<Option<CommandChild>>);

const HIDDEN_ARG: &str = "--hidden";

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
    let _ = s.set_read_timeout(Some(Duration::from_millis(800)));
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

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app)))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, Some(vec![HIDDEN_ARG])))
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let started_hidden = std::env::args().any(|a| a == HIDDEN_ARG);
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Vyral")
                .inner_size(1440.0, 900.0)
                .min_inner_size(1100.0, 700.0)
                .visible(!started_hidden)
                .build()?;

            // Start at login by default the first time Vyral runs, so monitoring survives restarts.
            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            let marker = data_dir.join(".autostart-initialized");
            if !marker.exists() {
                let _ = app.autolaunch().enable();
                let _ = std::fs::write(&marker, b"1");
            }

            let port = free_port();
            let ui_dir = app.path().resource_dir()?.join("ui");
            let (mut rx, child) = app
                .shell()
                .sidecar("clippr-backend")?
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
                .spawn()?;
            *app.state::<Backend>().0.lock().unwrap() = Some(child);

            tauri::async_runtime::spawn(async move {
                while let Some(ev) = rx.recv().await {
                    if let CommandEvent::Stderr(line) | CommandEvent::Stdout(line) = ev {
                        eprintln!("[backend] {}", String::from_utf8_lossy(&line).trim_end());
                    }
                }
            });

            let win = window.clone();
            std::thread::spawn(move || {
                let started = Instant::now();
                // First launch unpacks the bundled service, which can take a little while.
                while started.elapsed() < Duration::from_secs(90) {
                    if healthy(port) {
                        if let Ok(url) = Url::parse(&format!("http://127.0.0.1:{port}/")) {
                            let _ = win.navigate(url);
                        }
                        return;
                    }
                    std::thread::sleep(Duration::from_millis(300));
                }
                let _ = win.eval("document.body.innerHTML='<p style=\"padding:40px;font-family:sans-serif;color:#ccc\">Vyral\\'s background service did not start. Quit Vyral from the tray icon and open it again.</p>'");
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
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    // Windows convention: left-click the tray icon to bring the window back.
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
            RunEvent::Exit => {
                if let Some(child) = app.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
            #[cfg(target_os = "macos")]
            RunEvent::Reopen { .. } => show_main(app),
            _ => {}
        });
}
