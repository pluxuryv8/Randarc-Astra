// FROM computer-agent:src-tauri/src/bash.rs
// EN kept: обязательное указание источника донорского кода
use std::process::{Command, Stdio};
use thiserror::Error;

#[derive(Error, Debug)]
pub enum BashError {
    #[error("Команда заблокирована: {0}")]
    Blocked(String),
    #[error("Ошибка выполнения: {0}")]
    Execution(String),
}

// опасные команды/паттерны, которые блокируются
// EN kept: системные команды оболочки фиксированы и не переводятся
const BLOCKED_PATTERNS: &[&str] = &[
    // разрушительные
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf $HOME",
    ":(){:|:&};:",  // fork-бомба
    "mkfs",
    "dd if=",
    "> /dev/sd",
    "chmod -R 777 /",

    // модификация системы
    "sudo rm",
    "sudo mkfs",
    "sudo dd",

    // сетевые атаки
    "nc -l",  // прослушка netcat
    "nmap",

    // кража учётных данных
    "curl.*|.*sh",
    "wget.*|.*sh",

    // отключение защиты
    "csrutil disable",
    "SIP",
];

// команды, требующие повышенного внимания
const WARN_PATTERNS: &[&str] = &[
    "sudo",
    "rm -rf",
    "chmod",
    "chown",
    "kill -9",
    "pkill",
    "shutdown",
    "reboot",
];

pub struct BashExecutor {
    working_dir: Option<String>,
}

impl BashExecutor {
    pub fn new() -> Self {
        Self {
            working_dir: None,
        }
    }

    fn is_blocked(&self, command: &str) -> Option<String> {
        let cmd_lower = command.to_lowercase();

        for pattern in BLOCKED_PATTERNS {
            if cmd_lower.contains(&pattern.to_lowercase()) {
                return Some(format!("Команда содержит запрещённый шаблон: {}", pattern));
            }
        }
        None
    }

    fn has_warning(&self, command: &str) -> Option<String> {
        let cmd_lower = command.to_lowercase();

        for pattern in WARN_PATTERNS {
            if cmd_lower.contains(&pattern.to_lowercase()) {
                return Some(format!("Внимание: команда использует {}", pattern));
            }
        }
        None
    }

    pub fn execute(&self, command: &str) -> Result<BashOutput, BashError> {
        // проверяем блокировку
        if let Some(reason) = self.is_blocked(command) {
            return Err(BashError::Blocked(reason));
        }

        // лог предупреждения, если применимо
        if let Some(warning) = self.has_warning(command) {
            println!("[оболочка] {}", warning);
        }

        println!("[оболочка] Выполнение: {}", command);

        let mut cmd = Command::new("bash");
        cmd.arg("-c")
            .arg(command)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        if let Some(ref dir) = self.working_dir {
            cmd.current_dir(dir);
        }

        let output = cmd
            .output()
            .map_err(|e| BashError::Execution(e.to_string()))?;

        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let exit_code = output.status.code().unwrap_or(-1);

        // усечение длинного вывода
        let stdout = truncate_output(&stdout, 5000);
        let stderr = truncate_output(&stderr, 2000);

        Ok(BashOutput {
            stdout,
            stderr,
            exit_code,
        })
    }

    pub fn restart(&mut self) {
        self.working_dir = None;
        println!("[оболочка] Сеанс перезапущен");
    }
}

#[derive(Debug, Clone)]
pub struct BashOutput {
    pub stdout: String,
    pub stderr: String,
    pub exit_code: i32,
}

impl BashOutput {
    pub fn to_string(&self) -> String {
        let mut result = String::new();

        if !self.stdout.is_empty() {
            result.push_str(&self.stdout);
        }

        if !self.stderr.is_empty() {
            if !result.is_empty() {
                result.push_str("\n");
            }
            result.push_str("ошибка: ");
            result.push_str(&self.stderr);
        }

        if self.exit_code != 0 {
            // добавляем код возврата, чтобы фронтенд мог распарсить
            result = format!("код возврата: {}\n{}", self.exit_code, result);
        }

        if result.is_empty() {
            result = "нет вывода".to_string();
        }

        result
    }
}

fn truncate_output(s: &str, max_chars: usize) -> String {
    if s.len() <= max_chars {
        s.to_string()
    } else {
        format!(
            "{}...\n[усечено, всего {} символов]",
            &s[..max_chars],
            s.len()
        )
    }
}
