use portable_pty::{native_pty_system, Child, CommandBuilder, MasterPty, PtySize, PtySystem};
use std::{env, io::{Read, Write}, path::PathBuf, process::{Child as ProcessChild, ChildStdin, Command, Stdio}, sync::{Arc, Mutex}, thread, time::Duration};
use tauri::{AppHandle, Emitter, State};

struct TerminalSession { writer: Box<dyn Write + Send>, master: Box<dyn MasterPty + Send>, child: Box<dyn Child + Send + Sync> }
impl Drop for TerminalSession { fn drop(&mut self) { let _ = self.child.kill(); } }
#[derive(Default)]
struct AppState { terminal: Mutex<Option<TerminalSession>>, agent_stdin: Arc<Mutex<Option<ChildStdin>>>, agent_child: Arc<Mutex<Option<ProcessChild>>> }

fn shell() -> String {
    if cfg!(target_os = "windows") { env::var("COMSPEC").unwrap_or_else(|_| "powershell.exe".into()) }
    else { env::var("SHELL").unwrap_or_else(|_| "/bin/bash".into()) }
}

#[tauri::command]
fn default_workspace() -> Result<String, String> {
    env::current_dir().map(|p| p.to_string_lossy().to_string()).map_err(|e| e.to_string())
}

#[tauri::command]
fn terminal_start(app: AppHandle, state: State<'_, AppState>, cwd: String) -> Result<(), String> {
    let path = PathBuf::from(cwd).canonicalize().map_err(|e| e.to_string())?;
    if !path.is_dir() { return Err("Le chemin n'est pas un dossier.".into()); }
    let pair = native_pty_system().openpty(PtySize { rows: 28, cols: 110, pixel_width: 0, pixel_height: 0 }).map_err(|e| e.to_string())?;
    let mut cmd = CommandBuilder::new(shell());
    cmd.cwd(path);
    if !cfg!(target_os = "windows") { cmd.arg("-l"); }
    let child = pair.slave.spawn_command(cmd).map_err(|e| e.to_string())?;
    let mut reader = pair.master.try_clone_reader().map_err(|e| e.to_string())?;
    let writer = pair.master.take_writer().map_err(|e| e.to_string())?;
    let master = pair.master;
    {
        let mut slot = state.terminal.lock().map_err(|_| "Verrou terminal indisponible.")?;
        if let Some(mut previous) = slot.take() { let _ = previous.child.kill(); let _ = previous.child.wait(); }
        *slot = Some(TerminalSession { writer, master, child });
    }
    thread::spawn(move || {
        let mut buffer = [0_u8; 8192];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(size) => {
                    if app.emit("terminal-output", String::from_utf8_lossy(&buffer[..size]).to_string()).is_err() { break; }
                }
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(_) => break,
            }
        }
    });
    Ok(())
}

#[tauri::command]
fn terminal_write(state: State<'_, AppState>, data: String) -> Result<(), String> {
    let mut slot = state.terminal.lock().map_err(|_| "Verrou terminal indisponible.")?;
    let session = slot.as_mut().ok_or("Terminal non démarré.")?;
    session.writer.write_all(data.as_bytes()).map_err(|e| e.to_string())?;
    session.writer.flush().map_err(|e| e.to_string())
}

#[tauri::command]
fn terminal_resize(state: State<'_, AppState>, cols: u16, rows: u16) -> Result<(), String> {
    let slot = state.terminal.lock().map_err(|_| "Verrou terminal indisponible.")?;
    let session = slot.as_ref().ok_or("Terminal non démarré.")?;
    session.master.resize(PtySize { rows: rows.max(2), cols: cols.max(10), pixel_width: 0, pixel_height: 0 }).map_err(|e| e.to_string())
}

#[tauri::command]
fn terminal_stop(state: State<'_, AppState>) -> Result<(), String> {
    let mut slot = state.terminal.lock().map_err(|_| "Verrou terminal indisponible.")?;
    if let Some(mut session) = slot.take() { let _ = session.child.kill(); let _ = session.child.wait(); }
    Ok(())
}

#[tauri::command]
fn agent_run(app: AppHandle, state: State<'_, AppState>, cwd: String, prompt: String, allow_changes: bool) -> Result<(), String> {
    let path = PathBuf::from(cwd).canonicalize().map_err(|e| e.to_string())?;
    if !path.is_dir() { return Err("Dossier de projet introuvable.".into()); }
    if prompt.trim().is_empty() { return Err("Demande vide.".into()); }

    let mut command = Command::new("zerocode");
    let mut search_paths = env::split_paths(&env::var_os("PATH").unwrap_or_default()).collect::<Vec<_>>();
    if let Some(home) = env::var_os("HOME") { let local_bin = PathBuf::from(home).join(".local/bin"); if !search_paths.contains(&local_bin) { search_paths.push(local_bin); } }
    let path_value = env::join_paths(search_paths).map_err(|e| e.to_string())?;
    command.env("PATH", path_value);
    command.arg("--json").arg("--desktop-protocol").arg("--continue").arg("--cwd").arg(&path).arg("--permissions")
        .arg(if allow_changes { "allow" } else { "ask" }).arg(prompt)
        .current_dir(&path).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn().map_err(|e| format!("Impossible de lancer zerocode : {e}"))?;
    let stdin = child.stdin.take().ok_or("Entrée agent indisponible.")?;
    let stdout = child.stdout.take().ok_or("Sortie de l'agent indisponible.")?;
    let stderr = child.stderr.take().ok_or("Erreurs de l'agent indisponibles.")?;
    let child_store = state.agent_child.clone();
    {
        let mut slot = child_store.lock().map_err(|_| "Verrou agent indisponible.")?;
        if let Some(mut previous) = slot.take() { let _ = previous.kill(); }
        *slot = Some(child);
    }
    {
        let mut slot = state.agent_stdin.lock().map_err(|_| "Verrou agent indisponible.")?;
        slot.take();
        *slot = Some(stdin);
    }
    let stdin_store = state.agent_stdin.clone();
    let handle = app.clone();
    thread::spawn(move || {
        let output_handle = handle.clone();
        let output_thread = thread::spawn(move || {
            let mut reader = std::io::BufReader::new(stdout);
            let mut line = String::new();
            loop {
                line.clear();
                match std::io::BufRead::read_line(&mut reader, &mut line) {
                    Ok(0) => break,
                    Ok(_) => {
                        let event = line.trim_end().to_string();
                        if !event.is_empty() { let _ = output_handle.emit("agent-event", event); }
                    }
                    Err(_) => break,
                }
            }
        });
        let error_handle = handle.clone();
        let error_thread = thread::spawn(move || {
            let mut reader = std::io::BufReader::new(stderr);
            let mut errors = String::new();
            let _ = reader.read_to_string(&mut errors);
            if !errors.trim().is_empty() {
                let event = serde_json::json!({"type":"error","message":errors.trim()});
                let _ = error_handle.emit("agent-event", event.to_string());
            }
        });
        let _ = output_thread.join();
        let _ = error_thread.join();
        let code = loop {
            let mut slot = match child_store.lock() { Ok(slot) => slot, Err(_) => break None };
            match slot.as_mut() {
                Some(process) => match process.try_wait() {
                    Ok(Some(status)) => { let code = status.code(); slot.take(); break code; }
                    Ok(None) => {}
                    Err(_) => { slot.take(); break None; }
                },
                None => break None,
            }
            drop(slot);
            thread::sleep(Duration::from_millis(120));
        };
        if let Ok(mut slot) = stdin_store.lock() { slot.take(); }
        let event = serde_json::json!({"type":"process_finished","exit_code":code});
        let _ = handle.emit("agent-event", event.to_string());
    });
    Ok(())
}



#[tauri::command]
fn agent_respond(state: State<'_, AppState>, approved: bool, password: Option<String>) -> Result<(), String> {
    let mut slot = state.agent_stdin.lock().map_err(|_| "Verrou agent indisponible.")?;
    let stdin = slot.as_mut().ok_or("Aucune demande d'autorisation en attente.")?;
    let response = serde_json::json!({"approved": approved, "password": password});
    writeln!(stdin, "{}", response).map_err(|e| e.to_string())?;
    stdin.flush().map_err(|e| e.to_string())
}

#[derive(serde::Serialize)]
struct ProjectEntry { path: String, is_dir: bool }

fn skip_project_entry(name: &str) -> bool {
    matches!(name, ".git" | "node_modules" | "vendor" | ".venv" | "venv" | ".next" | "dist" | "build" | "target" | "__pycache__" | ".idea" | ".vscode")
        || name.starts_with(".env")
        || name.ends_with(".pem")
        || name.ends_with(".key")
        || name.ends_with(".p12")
        || name == "id_rsa"
}

fn collect_project_entries(root: &std::path::Path, current: &std::path::Path, depth: usize, output: &mut Vec<ProjectEntry>) -> Result<(), String> {
    if depth > 4 || output.len() >= 300 { return Ok(()); }
    let mut items = std::fs::read_dir(current).map_err(|e| e.to_string())?
        .filter_map(Result::ok).collect::<Vec<_>>();
    items.sort_by_key(|entry| {
        let name = entry.file_name().to_string_lossy().to_string();
        let is_dir = entry.file_type().map(|kind| kind.is_dir()).unwrap_or(false);
        (!is_dir, name.to_lowercase())
    });
    for item in items {
        if output.len() >= 300 { break; }
        let name = item.file_name().to_string_lossy().to_string();
        if skip_project_entry(&name) { continue; }
        let metadata = item.file_type().map_err(|e| e.to_string())?;
        if metadata.is_symlink() { continue; }
        let is_dir = metadata.is_dir();
        let full_path = item.path();
        let relative = full_path.strip_prefix(root).map_err(|e| e.to_string())?;
        output.push(ProjectEntry { path: relative.to_string_lossy().replace('\\', "/"), is_dir });
        if is_dir { collect_project_entries(root, &full_path, depth + 1, output)?; }
    }
    Ok(())
}

#[tauri::command]
fn list_project_files(cwd: String) -> Result<Vec<ProjectEntry>, String> {
    let root = PathBuf::from(cwd).canonicalize().map_err(|e| e.to_string())?;
    if !root.is_dir() { return Err("Dossier de projet introuvable.".into()); }
    let mut output = Vec::new();
    collect_project_entries(&root, &root, 0, &mut output)?;
    Ok(output)
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![default_workspace, list_project_files, terminal_start, terminal_write, terminal_resize, terminal_stop, agent_run, agent_respond])
        .build(tauri::generate_context!())
        .expect("Erreur au démarrage de ZeroCode Desktop");

    app.run(|handle, event| {
        if let tauri::RunEvent::Exit = event {
            let state = handle.state::<AppState>();
            if let Ok(mut slot) = state.agent_stdin.lock() { slot.take(); }
            if let Ok(mut slot) = state.agent_child.lock() {
                if let Some(child) = slot.as_mut() { let _ = child.kill(); }
                slot.take();
            }
            if let Ok(mut slot) = state.terminal.lock() { slot.take(); }
        }
    });
}