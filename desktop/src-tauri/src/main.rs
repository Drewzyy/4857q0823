// AI Clipper desktop shell.
//
// Starts the bundled Python backend as a sidecar on a free loopback port, waits for it to be
// healthy, then points the main window at it. Closing the window hides it; the backend keeps
// running (token refresh, scheduled jobs) until the user picks Quit from the menu bar icon.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct Backend(Mutex<Option<CommandChild>>);

fn free_port() -> u16 {
    // Prefer the stable default so registered OAuth redirect URIs (Meta needs an exact one) keep working.
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

fn show_main(app: &tauri::AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.set_focus();
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app)))
        .plugin(tauri_plugin_shell::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("AI Clipper")
                .inner_size(1440.0, 900.0)
                .min_inner_size(1100.0, 700.0)
                .build()?;

            let port = free_port();
            let ui_dir = app.path().resource_dir()?.join("ui");
            let data_dir = app.path().app_data_dir()?;
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
                ])
                .env("CLIPPR_DESKTOP", "1")
                .spawn()?;
            *app.state::<Backend>().0.lock().unwrap() = Some(child);

            // Forward backend output to the shell's stderr for debugging; never parsed for secrets.
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
                while started.elapsed() < Duration::from_secs(45) {
                    if healthy(port) {
                        if let Ok(url) = Url::parse(&format!("http://127.0.0.1:{port}/")) {
                            let _ = win.navigate(url);
                        }
                        return;
                    }
                    std::thread::sleep(Duration::from_millis(250));
                }
                let _ = win.eval("document.body.innerHTML='<p style=\"padding:40px\">The AI Clipper background service did not start. Check ~/Library/Application Support/app.aiclipper.desktop/logs.</p>'");
            });

            let open = MenuItem::with_id(app, "open", "Open AI Clipper", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit AI Clipper", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &quit])?;
            TrayIconBuilder::new()
                .icon(app.default_window_icon().cloned().expect("app icon"))
                .tooltip("AI Clipper")
                .menu(&menu)
                .on_menu_event(|app, e| match e.id.as_ref() {
                    "open" => show_main(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Keep running in the menu bar when the window is closed.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build AI Clipper")
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
