use serde_json::{json, Value};
use std::{
    env,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::Mutex,
};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use tauri::{path::BaseDirectory, Manager};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

struct BackendProcess {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    next_id: u64,
}

struct BackendState {
    process: Mutex<Option<BackendProcess>>,
    bundled_backend: Option<PathBuf>,
}

impl BackendState {
    fn request(&self, method: String, params: Value) -> Result<Value, String> {
        let mut guard = self.process.lock().map_err(|_| "Backend lock is poisoned.".to_string())?;
        if guard.is_none() {
            *guard = Some(start_backend(self.bundled_backend.as_deref())?);
        }
        let process = guard.as_mut().ok_or_else(|| "Backend process is not available.".to_string())?;
        process.next_id += 1;
        let request_id = process.next_id;
        let request = json!({ "id": request_id, "method": method, "params": params });
        writeln!(process.stdin, "{}", request).map_err(|err| err.to_string())?;
        process.stdin.flush().map_err(|err| err.to_string())?;

        let mut line = String::new();
        process.stdout.read_line(&mut line).map_err(|err| err.to_string())?;
        if line.trim().is_empty() {
            return Err("Backend returned an empty response.".to_string());
        }
        let response: Value = serde_json::from_str(&line).map_err(|err| err.to_string())?;
        if response.get("ok").and_then(Value::as_bool) == Some(true) {
            Ok(response.get("result").cloned().unwrap_or(Value::Null))
        } else {
            let message = response
                .get("error")
                .and_then(|error| error.get("message"))
                .and_then(Value::as_str)
                .unwrap_or("Backend request failed.");
            Err(message.to_string())
        }
    }
}

#[tauri::command]
fn backend_request(state: tauri::State<BackendState>, method: String, params: Value) -> Result<Value, String> {
    state.request(method, params)
}

fn start_backend(bundled_backend: Option<&Path>) -> Result<BackendProcess, String> {
    if let Ok(exe) = env::var("TWINSYNC_BACKEND_EXE") {
        return spawn_backend_exe(PathBuf::from(exe));
    }
    if let Some(path) = bundled_backend {
        if path.exists() {
            return spawn_backend_exe(path.to_path_buf());
        }
    }

    let root = find_project_root().ok_or_else(|| "TwinSync project root was not found.".to_string())?;
    let backend_dir = root.join("backend");
    let python = python_command(&root);
    let mut command = Command::new(python);
    command
        .arg("-m")
        .arg("twinsync_backend.ipc_server")
        .env("PYTHONPATH", backend_dir)
        .current_dir(root);
    let child = spawn_hidden(command).map_err(|err| format!("Failed to start Python backend: {err}"))?;
    build_process(child)
}

fn python_command(root: &Path) -> PathBuf {
    if let Ok(configured) = env::var("TWINSYNC_PYTHON") {
        let path = PathBuf::from(configured);
        if path.is_absolute() {
            return path;
        }
        for candidate in [root.join(&path), root.join("frontend").join(&path)] {
            if candidate.exists() {
                return candidate;
            }
        }
        return path;
    }

    let project_venv = root.join(".venv").join("Scripts").join("python.exe");
    if project_venv.exists() {
        return project_venv;
    }
    PathBuf::from("python")
}

fn spawn_backend_exe(path: PathBuf) -> Result<BackendProcess, String> {
    let command = Command::new(path);
    let child = spawn_hidden(command).map_err(|err| format!("Failed to start bundled backend: {err}"))?;
    build_process(child)
}

fn spawn_hidden(mut command: Command) -> std::io::Result<Child> {
    command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    command.spawn()
}

fn build_process(mut child: Child) -> Result<BackendProcess, String> {
    let stdin = child.stdin.take().ok_or_else(|| "Backend stdin was not opened.".to_string())?;
    let stdout = child.stdout.take().ok_or_else(|| "Backend stdout was not opened.".to_string())?;
    Ok(BackendProcess {
        child,
        stdin,
        stdout: BufReader::new(stdout),
        next_id: 0,
    })
}

fn find_project_root() -> Option<PathBuf> {
    let cwd = env::current_dir().ok()?;
    let mut candidates = Vec::new();
    candidates.push(cwd.clone());
    for ancestor in cwd.ancestors() {
        candidates.push(ancestor.to_path_buf());
    }
    for candidate in candidates {
        if is_project_root(&candidate) {
            return Some(candidate);
        }
        if let Some(parent) = candidate.parent() {
            if is_project_root(parent) {
                return Some(parent.to_path_buf());
            }
        }
    }
    None
}

fn is_project_root(path: &Path) -> bool {
    path.join("backend").join("twinsync_backend").exists() && path.join("frontend").exists()
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let bundled_backend = app
                .path()
                .resolve("backend/twinsync-backend.exe", BaseDirectory::Resource)
                .ok()
                .filter(|path| path.exists());
            app.manage(BackendState {
                process: Mutex::new(None),
                bundled_backend,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_request])
        .run(tauri::generate_context!())
        .expect("failed to run TwinSync Audio");
}

impl Drop for BackendProcess {
    fn drop(&mut self) {
        let _ = self.child.kill();
    }
}
