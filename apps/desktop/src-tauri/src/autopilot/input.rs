use enigo::{Axis, Button, Coordinate, Direction, Enigo, Key, Keyboard, Mouse, Settings};
use serde::Deserialize;
use xcap::Monitor;

#[derive(Debug, Deserialize, Clone)]
pub struct AutopilotAction {
    #[serde(rename = "type")]
    pub action_type: String,
    pub x: Option<i32>,
    pub y: Option<i32>,
    pub button: Option<String>,
    pub start_x: Option<i32>,
    pub start_y: Option<i32>,
    pub end_x: Option<i32>,
    pub end_y: Option<i32>,
    pub text: Option<String>,
    pub keys: Option<Vec<String>>,
    pub dy: Option<i32>,
}

pub struct AutopilotExecutor {
    screen_width: u32,
    screen_height: u32,
}

impl AutopilotExecutor {
    pub fn new() -> Result<Self, String> {
        let monitor = Monitor::all()
            .map_err(|e| e.to_string())?
            .into_iter()
            .next()
            .ok_or_else(|| "Монитор не найден".to_string())?;

        Ok(Self {
            screen_width: monitor.width().map_err(|e| e.to_string())?,
            screen_height: monitor.height().map_err(|e| e.to_string())?,
        })
    }

    pub fn execute(&self, action: &AutopilotAction, image_width: u32, image_height: u32) -> Result<String, String> {
        let mut enigo = Enigo::new(&Settings::default()).map_err(|e| e.to_string())?;
        let action_type = action.action_type.as_str();

        match action_type {
            "move_mouse" => {
                if let (Some(x), Some(y)) = (action.x, action.y) {
                    let (sx, sy) = self.map_coords(x, y, image_width, image_height);
                    enigo.move_mouse(sx, sy, Coordinate::Abs).map_err(|e| e.to_string())?;
                }
                Ok("move_mouse".to_string())
            }
            "click" => {
                if let (Some(x), Some(y)) = (action.x, action.y) {
                    let (sx, sy) = self.map_coords(x, y, image_width, image_height);
                    enigo.move_mouse(sx, sy, Coordinate::Abs).map_err(|e| e.to_string())?;
                }
                let button = match action.button.as_deref() {
                    Some("right") => Button::Right,
                    Some("middle") => Button::Middle,
                    _ => Button::Left,
                };
                enigo.button(button, Direction::Click).map_err(|e| e.to_string())?;
                Ok("click".to_string())
            }
            "double_click" => {
                if let (Some(x), Some(y)) = (action.x, action.y) {
                    let (sx, sy) = self.map_coords(x, y, image_width, image_height);
                    enigo.move_mouse(sx, sy, Coordinate::Abs).map_err(|e| e.to_string())?;
                }
                for _ in 0..2 {
                    enigo.button(Button::Left, Direction::Click).map_err(|e| e.to_string())?;
                }
                Ok("double_click".to_string())
            }
            "drag" => {
                if let (Some(sx), Some(sy), Some(ex), Some(ey)) = (action.start_x, action.start_y, action.end_x, action.end_y) {
                    let (sx, sy) = self.map_coords(sx, sy, image_width, image_height);
                    let (ex, ey) = self.map_coords(ex, ey, image_width, image_height);
                    enigo.move_mouse(sx, sy, Coordinate::Abs).map_err(|e| e.to_string())?;
                    enigo.button(Button::Left, Direction::Press).map_err(|e| e.to_string())?;
                    enigo.move_mouse(ex, ey, Coordinate::Abs).map_err(|e| e.to_string())?;
                    enigo.button(Button::Left, Direction::Release).map_err(|e| e.to_string())?;
                }
                Ok("drag".to_string())
            }
            "type" => {
                if let Some(text) = &action.text {
                    enigo.text(text).map_err(|e| e.to_string())?;
                }
                Ok("type".to_string())
            }
            "key" => {
                if let Some(keys) = &action.keys {
                    self.press_keys(&mut enigo, keys)?;
                }
                Ok("key".to_string())
            }
            "scroll" => {
                let amount = action.dy.unwrap_or(0);
                if amount != 0 {
                    enigo.scroll(amount, Axis::Vertical).map_err(|e| e.to_string())?;
                }
                Ok("scroll".to_string())
            }
            _ => Err("неизвестное действие".to_string()),
        }
    }

    fn map_coords(&self, x: i32, y: i32, image_width: u32, image_height: u32) -> (i32, i32) {
        if image_width == 0 || image_height == 0 {
            return (x, y);
        }
        let sx = (x as f32 / image_width as f32) * self.screen_width as f32;
        let sy = (y as f32 / image_height as f32) * self.screen_height as f32;
        (sx.round() as i32, sy.round() as i32)
    }

    fn press_keys(&self, enigo: &mut Enigo, keys: &[String]) -> Result<(), String> {
        if keys.is_empty() {
            return Ok(());
        }
        let mut modifiers: Vec<Key> = Vec::new();
        let mut main_key: Option<Key> = None;

        for key in keys {
            if let Some(mapped) = map_key(key) {
                if is_modifier(key) {
                    modifiers.push(mapped);
                } else {
                    main_key = Some(mapped);
                }
            }
        }

        for modifier in &modifiers {
            enigo.key(*modifier, Direction::Press).map_err(|e| e.to_string())?;
        }

        if let Some(key) = main_key {
            enigo.key(key, Direction::Click).map_err(|e| e.to_string())?;
        }

        for modifier in modifiers.iter().rev() {
            enigo.key(*modifier, Direction::Release).map_err(|e| e.to_string())?;
        }

        Ok(())
    }
}

fn is_modifier(key: &str) -> bool {
    matches!(key.to_uppercase().as_str(), "CMD" | "COMMAND" | "META" | "CTRL" | "CONTROL" | "ALT" | "OPTION" | "SHIFT")
}

fn map_key(key: &str) -> Option<Key> {
    match key.to_uppercase().as_str() {
        "CMD" | "COMMAND" | "META" => Some(Key::Meta),
        "CTRL" | "CONTROL" => Some(Key::Control),
        "ALT" | "OPTION" => Some(Key::Alt),
        "SHIFT" => Some(Key::Shift),
        "ENTER" | "RETURN" => Some(Key::Return),
        "TAB" => Some(Key::Tab),
        "ESC" | "ESCAPE" => Some(Key::Escape),
        "BACKSPACE" => Some(Key::Backspace),
        "DELETE" => Some(Key::Delete),
        "SPACE" => Some(Key::Space),
        "UP" | "ARROW_UP" => Some(Key::UpArrow),
        "DOWN" | "ARROW_DOWN" => Some(Key::DownArrow),
        "LEFT" | "ARROW_LEFT" => Some(Key::LeftArrow),
        "RIGHT" | "ARROW_RIGHT" => Some(Key::RightArrow),
        _ => {
            if key.len() == 1 {
                return key.chars().next().map(Key::Unicode);
            }
            None
        }
    }
}
