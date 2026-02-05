#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bridge;
#[cfg(feature = "desktop-skills")]
mod autopilot;
#[cfg(feature = "desktop-skills")]
mod skills;

use rand::RngCore;
use tauri::{GlobalShortcutManager, Manager};

#[tauri::command]
fn get_or_create_session_token() -> Result<String, String> {
    // EN kept: идентификаторы keychain стабильны между версиями
    let entry = keyring::Entry::new("randarc-astra", "session_token").map_err(|e| e.to_string())?;
    if let Ok(token) = entry.get_password() {
        return Ok(token);
    }
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    let token = hex::encode(bytes);
    entry.set_password(&token).map_err(|e| e.to_string())?;
    Ok(token)
}

fn main() {
    bridge::start_bridge();
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_or_create_session_token, check_permissions])
        .setup(|app| {
            let handle = app.handle();
            let mut shortcut_manager = handle.global_shortcut_manager();
            let _ = shortcut_manager.register("Cmd+Shift+S", move || {
                let _ = handle.emit_all("autopilot_stop_hotkey", {});
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("ошибка при запуске tauri-приложения");
}

#[tauri::command]
fn check_permissions() -> Result<autopilot::permissions::PermissionsStatus, String> {
    #[cfg(feature = "desktop-skills")]
    {
        Ok(autopilot::permissions::check_permissions())
    }
    #[cfg(not(feature = "desktop-skills"))]
    {
        Err("Недоступно без desktop-skills".to_string())
    }
}
