use serde::Serialize;
use xcap::Monitor;

#[derive(Debug, Serialize)]
pub struct PermissionsStatus {
    pub screen_recording: bool,
    pub accessibility: bool,
    pub message: String,
}

pub fn check_permissions() -> PermissionsStatus {
    let screen_recording = Monitor::all().is_ok();
    let accessibility = check_accessibility();
    let message = if screen_recording && accessibility {
        "Разрешения в норме".to_string()
    } else {
        "Нужны разрешения: Запись экрана и Универсальный доступ".to_string()
    };
    PermissionsStatus {
        screen_recording,
        accessibility,
        message,
    }
}

fn check_accessibility() -> bool {
    // EN kept: внутренний fallback — точная проверка требует системных API.
    // Здесь проверка упрощена: если можем создать Enigo, считаем доступ разрешён.
    enigo::Enigo::new(&enigo::Settings::default()).is_ok()
}
