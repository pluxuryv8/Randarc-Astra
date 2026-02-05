use std::env;
use std::io::Read;
use std::thread;

use serde::{Deserialize, Serialize};
use tiny_http::{Response, Server};

#[cfg(feature = "desktop-skills")]
use crate::skills::{computer::ComputerControl, computer::ComputerAction, shell::BashExecutor};
#[cfg(feature = "desktop-skills")]
use crate::autopilot::{input::{AutopilotAction, AutopilotExecutor}, screen, permissions};

#[derive(Debug, Deserialize)]
// EN kept: контракт JSON для действий компьютера
struct ComputerActionDto {
    action: String,
    coordinate: Option<[i32; 2]>,
    start_coordinate: Option<[i32; 2]>,
    text: Option<String>,
    scroll_direction: Option<String>,
    scroll_amount: Option<i32>,
    key: Option<String>,
    region: Option<[i32; 4]>,
}

#[derive(Debug, Deserialize)]
struct ComputerRequest {
    actions: Vec<ComputerActionDto>,
}

#[derive(Debug, Serialize)]
// EN kept: имена полей ответа — часть контракта bridge
struct ComputerResponse {
    summary: String,
    results: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct ShellRequest {
    command: String,
}

#[derive(Debug, Serialize)]
struct ShellResponse {
    output: String,
}

#[derive(Debug, Deserialize)]
struct AutopilotCaptureRequest {
    max_width: Option<u32>,
    quality: Option<u8>,
}

#[derive(Debug, Serialize)]
struct AutopilotCaptureResponse {
    image_base64: String,
    width: u32,
    height: u32,
    screen_width: u32,
    screen_height: u32,
    format: String,
}

#[derive(Debug, Deserialize)]
struct AutopilotActRequest {
    action: AutopilotAction,
    image_width: u32,
    image_height: u32,
}


pub fn start_bridge() {
    let port = env::var("ASTRA_DESKTOP_BRIDGE_PORT").unwrap_or_else(|_| "43124".to_string());
    let addr = format!("127.0.0.1:{}", port);
    thread::spawn(move || {
        let server = Server::http(&addr).expect("не удалось запустить bridge-сервер");
        for mut request in server.incoming_requests() {
            let mut body = String::new();
            let _ = request.as_reader().read_to_string(&mut body);
            let path = request.url().to_string();

            let response = match (request.method().as_str(), path.as_str()) {
                // EN kept: стабильные пути API для desktop-bridge
                ("POST", "/computer/preview") => handle_computer_preview(&body),
                ("POST", "/computer/execute") => handle_computer_execute(&body),
                ("POST", "/shell/preview") => handle_shell_preview(&body),
                ("POST", "/shell/execute") => handle_shell_execute(&body),
                ("POST", "/autopilot/capture") => handle_autopilot_capture(&body),
                ("POST", "/autopilot/act") => handle_autopilot_act(&body),
                ("GET", "/autopilot/permissions") => handle_autopilot_permissions(),
                _ => Response::from_string("не найдено").with_status_code(404),
            };
            let _ = request.respond(response);
        }
    });
}

fn handle_computer_preview(body: &str) -> Response<std::io::Cursor<Vec<u8>>> {
    let parsed: Result<ComputerRequest, _> = serde_json::from_str(body);
    match parsed {
        Ok(req) => {
            let summary = format!("{} действий", req.actions.len());
            let resp = ComputerResponse { summary, results: vec![] };
            Response::from_string(serde_json::to_string(&resp).unwrap()).with_status_code(200)
        }
        Err(_) => Response::from_string("некорректный запрос").with_status_code(400),
    }
}

fn handle_computer_execute(body: &str) -> Response<std::io::Cursor<Vec<u8>>> {
    let parsed: Result<ComputerRequest, _> = serde_json::from_str(body);
    match parsed {
        Ok(req) => {
            #[cfg(feature = "desktop-skills")]
            {
                let control = ComputerControl::new().map_err(|_| "не удалось инициализировать").ok();
                if let Some(control) = control {
                    let actions: Vec<ComputerAction> = req
                        .actions
                        .iter()
                        .map(|a| ComputerAction {
                            action: a.action.clone(),
                            coordinate: a.coordinate,
                            start_coordinate: a.start_coordinate,
                            text: a.text.clone(),
                            scroll_direction: a.scroll_direction.clone(),
                            scroll_amount: a.scroll_amount,
                            key: a.key.clone(),
                            region: a.region,
                        })
                        .collect();

                    let mut results = Vec::new();
                    for action in actions.iter() {
                        match control.perform_action(action) {
                            Ok(output) => results.push(output.unwrap_or_default()),
                            Err(e) => results.push(format!("ошибка: {}", e)),
                        }
                    }
                    let resp = ComputerResponse { summary: format!("{} действий", actions.len()), results };
                    return Response::from_string(serde_json::to_string(&resp).unwrap()).with_status_code(200);
                }
            }
            Response::from_string("НЕДОСТУПНО").with_status_code(503)
        }
        Err(_) => Response::from_string("некорректный запрос").with_status_code(400),
    }
}

fn handle_shell_preview(body: &str) -> Response<std::io::Cursor<Vec<u8>>> {
    let parsed: Result<ShellRequest, _> = serde_json::from_str(body);
    match parsed {
        Ok(req) => Response::from_string(serde_json::to_string(&ShellResponse { output: req.command }).unwrap()).with_status_code(200),
        Err(_) => Response::from_string("некорректный запрос").with_status_code(400),
    }
}

fn handle_shell_execute(body: &str) -> Response<std::io::Cursor<Vec<u8>>> {
    let parsed: Result<ShellRequest, _> = serde_json::from_str(body);
    match parsed {
        Ok(req) => {
            #[cfg(feature = "desktop-skills")]
            {
                let executor = BashExecutor::new();
                let output = executor.execute(&req.command);
                if let Ok(out) = output {
                    let resp = ShellResponse { output: out.to_string() };
                    return Response::from_string(serde_json::to_string(&resp).unwrap()).with_status_code(200);
                }
            }
            Response::from_string("НЕДОСТУПНО").with_status_code(503)
        }
        Err(_) => Response::from_string("некорректный запрос").with_status_code(400),
    }
}

fn handle_autopilot_capture(body: &str) -> Response<std::io::Cursor<Vec<u8>>> {
    let parsed: Result<AutopilotCaptureRequest, _> = serde_json::from_str(body);
    match parsed {
        Ok(req) => {
            #[cfg(feature = "desktop-skills")]
            {
                let max_width = req.max_width.unwrap_or(1280);
                let quality = req.quality.unwrap_or(60);
                match screen::capture_screen(max_width, quality) {
                    Ok(capture) => {
                        let resp = AutopilotCaptureResponse {
                            image_base64: capture.image_base64,
                            width: capture.width,
                            height: capture.height,
                            screen_width: capture.screen_width,
                            screen_height: capture.screen_height,
                            format: "jpeg".to_string(),
                        };
                        return Response::from_string(serde_json::to_string(&resp).unwrap()).with_status_code(200);
                    }
                    Err(err) => return Response::from_string(err).with_status_code(500),
                }
            }
            Response::from_string("НЕДОСТУПНО").with_status_code(503)
        }
        Err(_) => Response::from_string("некорректный запрос").with_status_code(400),
    }
}

fn handle_autopilot_act(body: &str) -> Response<std::io::Cursor<Vec<u8>>> {
    let parsed: Result<AutopilotActRequest, _> = serde_json::from_str(body);
    match parsed {
        Ok(req) => {
            #[cfg(feature = "desktop-skills")]
            {
                if let Ok(executor) = AutopilotExecutor::new() {
                    match executor.execute(&req.action, req.image_width, req.image_height) {
                        Ok(summary) => {
                            return Response::from_string(format!("{{\"status\":\"ok\",\"summary\":\"{}\"}}", summary)).with_status_code(200);
                        }
                        Err(err) => return Response::from_string(err).with_status_code(500),
                    }
                }
            }
            Response::from_string("НЕДОСТУПНО").with_status_code(503)
        }
        Err(_) => Response::from_string("некорректный запрос").with_status_code(400),
    }
}

fn handle_autopilot_permissions() -> Response<std::io::Cursor<Vec<u8>>> {
    #[cfg(feature = "desktop-skills")]
    {
        let status = permissions::check_permissions();
        return Response::from_string(serde_json::to_string(&status).unwrap()).with_status_code(200);
    }
    Response::from_string("НЕДОСТУПНО").with_status_code(503)
}
