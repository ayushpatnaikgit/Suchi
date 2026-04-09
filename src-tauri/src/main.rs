// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;
use std::process::{Command, Child};
use std::sync::Mutex;

struct PythonServer(Mutex<Option<Child>>);

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Start the Python backend server as a sidecar process
            let sidecar_path = app
                .path()
                .resource_dir()
                .expect("failed to resolve resource dir")
                .join("sidecar")
                .join("suchi-server");

            let child = if sidecar_path.exists() {
                // Production: use bundled PyInstaller binary
                match Command::new(&sidecar_path).spawn() {
                    Ok(child) => Some(child),
                    Err(e) => {
                        eprintln!("Failed to start bundled suchi-server: {}", e);
                        None
                    }
                }
            } else {
                // Development: start uvicorn directly
                match Command::new("python3")
                    .args(["-m", "uvicorn", "suchi.api:app", "--host", "127.0.0.1", "--port", "9876"])
                    .spawn()
                {
                    Ok(child) => Some(child),
                    Err(e) => {
                        eprintln!("Failed to start dev suchi server: {}", e);
                        None
                    }
                }
            };

            app.manage(PythonServer(Mutex::new(child)));
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Kill the Python server when the app closes
                let state = window.state::<PythonServer>();
                let mut guard = match state.0.lock() {
                    Ok(g) => g,
                    Err(_) => return,
                };
                if let Some(ref mut child) = *guard {
                    let _ = child.kill();
                }
                drop(guard);
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running suchi");
}
