#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bridge;
#[cfg(feature = "desktop-skills")]
mod autopilot;
#[cfg(feature = "desktop-skills")]
mod skills;

use tauri::{GlobalShortcutManager, Manager, WindowBuilder, WindowUrl};

#[tauri::command]
fn open_settings_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_window("settings") {
        let _ = win.show();
        let _ = win.set_focus();
        return Ok(());
    }
    WindowBuilder::new(
        &app,
        "settings",
        WindowUrl::App("index.html?view=settings".into()),
    )
    .title("Astra • Настройки")
    .inner_size(980.0, 700.0)
    .min_inner_size(820.0, 520.0)
    .resizable(true)
    .decorations(true)
    .transparent(true)
    .always_on_top(false)
    .build()
    .map(|_| ())
    .map_err(|e| e.to_string())
}

fn main() {
    bridge::start_bridge();
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![open_settings_window, check_permissions])
        .setup(|app| {
            let handle = app.handle();
            let mut shortcut_manager = handle.global_shortcut_manager();
            let _ = shortcut_manager.register("Cmd+Shift+S", move || {
                let _ = handle.emit_all("autopilot_stop_hotkey", {});
            });
            let handle_toggle = app.handle();
            let _ = shortcut_manager.register("Cmd+Shift+O", move || {
                let _ = handle_toggle.emit_all("toggle_hud_mode", {});
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
