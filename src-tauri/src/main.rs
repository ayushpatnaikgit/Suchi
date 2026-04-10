// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

// Holds the child process handle for the Python sidecar.
// Wrapped in Mutex<Option<...>> so we can take ownership when killing it.
struct PythonServer(Mutex<Option<CommandChild>>);

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            // Start the bundled PyInstaller-packaged Python backend as a sidecar.
            // The binary is registered as an externalBin in tauri.conf.json and
            // bundled with the app at a platform-specific path — Tauri resolves
            // this automatically via Command::sidecar.
            let sidecar_command = app
                .shell()
                .sidecar("suchi-server")
                .expect("failed to create sidecar command");

            let (mut rx, child) = sidecar_command
                .spawn()
                .expect("failed to spawn suchi-server sidecar");

            // Log sidecar output to the Tauri console for debugging.
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            eprintln!("[suchi-server] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprintln!("[suchi-server err] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[suchi-server] terminated: code={:?}", payload.code);
                            break;
                        }
                        _ => {}
                    }
                }
            });

            app.manage(PythonServer(Mutex::new(Some(child))));
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
                if let Some(child) = guard.take() {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running suchi");
}
