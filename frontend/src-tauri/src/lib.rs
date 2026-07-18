use serde_json::{json, Value};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::{
    env, fs,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::Mutex,
};
use tauri::{path::BaseDirectory, Manager};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;
#[cfg(windows)]
const FIXED_WEBVIEW_RUNTIME: &str = "Microsoft.WebView2.FixedVersionRuntime.150.0.4078.65.x64";

#[cfg(windows)]
fn prepare_fixed_webview_runtime() -> Result<(), String> {
    let executable =
        env::current_exe().map_err(|error| format!("Cannot locate TwinSyncAudio.exe: {error}"))?;
    let runtime = executable
        .parent()
        .ok_or_else(|| "Cannot locate the TwinSync application folder.".to_string())?
        .join(FIXED_WEBVIEW_RUNTIME);
    if !runtime.join("msedgewebview2.exe").exists() {
        return Err(format!(
            "Bundled WebView2 runtime is missing from {}.",
            runtime.display()
        ));
    }

    let marker = runtime.join(".twinsync-webview-acl-v1");
    if marker.exists() {
        return Ok(());
    }

    let mut command = Command::new("icacls.exe");
    command
        .arg(&runtime)
        .arg("/grant")
        .arg("*S-1-15-2-2:(OI)(CI)(RX)")
        .arg("*S-1-15-2-1:(OI)(CI)(RX)")
        .arg("/T")
        .arg("/C")
        .arg("/Q")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .creation_flags(CREATE_NO_WINDOW);
    let status = command
        .status()
        .map_err(|error| format!("Cannot prepare bundled WebView2 permissions: {error}"))?;
    if !status.success() {
        return Err(format!(
            "Cannot prepare bundled WebView2 permissions (exit {status})."
        ));
    }
    fs::write(
        marker,
        b"TwinSync Audio fixed WebView2 permissions prepared\n",
    )
    .map_err(|error| format!("Cannot save bundled WebView2 permission state: {error}"))?;
    Ok(())
}

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
        let mut guard = self
            .process
            .lock()
            .map_err(|_| "Backend lock is poisoned.".to_string())?;
        if guard.is_none() {
            *guard = Some(start_backend(self.bundled_backend.as_deref())?);
        }
        let process = guard
            .as_mut()
            .ok_or_else(|| "Backend process is not available.".to_string())?;
        process.next_id += 1;
        let request_id = process.next_id;
        let request = json!({ "id": request_id, "method": method, "params": params });
        writeln!(process.stdin, "{}", request).map_err(|err| err.to_string())?;
        process.stdin.flush().map_err(|err| err.to_string())?;

        let mut line = String::new();
        process
            .stdout
            .read_line(&mut line)
            .map_err(|err| err.to_string())?;
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
fn backend_request(
    state: tauri::State<BackendState>,
    method: String,
    params: Value,
) -> Result<Value, String> {
    state.request(method, params)
}

#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    const TRUSTED_LINKS: [&str; 3] = [
        "https://github.com/1SAMAY",
        "https://github.com/1SAMAY/TwinSync-Audio",
        "mailto:samay4932@gmail.com",
    ];
    if !TRUSTED_LINKS.contains(&url.as_str()) {
        return Err("Blocked untrusted external link.".to_string());
    }

    let mut command = Command::new("explorer.exe");
    command.arg(&url);
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    command
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Cannot open external link: {error}"))
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

    let root =
        find_project_root().ok_or_else(|| "TwinSync project root was not found.".to_string())?;
    let backend_dir = root.join("backend");
    let python = python_command(&root);
    let mut command = Command::new(python);
    command
        .arg("-m")
        .arg("twinsync_backend.ipc_server")
        .env("PYTHONPATH", backend_dir)
        .current_dir(root);
    let child =
        spawn_hidden(command).map_err(|err| format!("Failed to start Python backend: {err}"))?;
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
    let mut command = Command::new(path);
    if let Ok(executable) = env::current_exe() {
        if let Some(root) = executable
            .parent()
            .filter(|root| root.join("portable.flag").exists())
        {
            command
                .env("TWINSYNC_DATA_DIR", root.join("data"))
                .env("TWINSYNC_LOG_DIR", root.join("data").join("logs"))
                .current_dir(root);
        }
    }
    let child =
        spawn_hidden(command).map_err(|err| format!("Failed to start bundled backend: {err}"))?;
    build_process(child)
}

fn spawn_hidden(mut command: Command) -> std::io::Result<Child> {
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    command.spawn()
}

fn build_process(mut child: Child) -> Result<BackendProcess, String> {
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| "Backend stdin was not opened.".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "Backend stdout was not opened.".to_string())?;
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

pub fn run() -> Result<(), String> {
    #[cfg(windows)]
    prepare_fixed_webview_runtime()?;

    tauri::Builder::default()
        .setup(|app| {
            let bundled_backend = app
                .path()
                .resolve("backend/twinsync-backend.exe", BaseDirectory::Resource)
                .ok()
                .filter(|path| path.exists())
                .or_else(|| {
                    env::current_exe()
                        .ok()?
                        .parent()?
                        .join("backend")
                        .join("twinsync-backend.exe")
                        .canonicalize()
                        .ok()
                });
            app.manage(BackendState {
                process: Mutex::new(None),
                bundled_backend,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_request, open_external])
        .run(tauri::generate_context!())
        .map_err(|error| error.to_string())
}

impl Drop for BackendProcess {
    fn drop(&mut self) {
        let _ = self.child.kill();
    }
}
