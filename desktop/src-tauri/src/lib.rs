use portable_pty::{native_pty_system, CommandBuilder, MasterPty, PtySize, PtySystem};
use std::{env, io::{Read, Write}, path::PathBuf, process::{Command, Stdio}, thread};
use tauri::{AppHandle, Emitter, State};

struct TerminalSession { writer: Box<dyn Write + Send>, master: Box<dyn MasterPty + Send> }
#[derive(Default)]
struct AppState { terminal: std::sync::Mutex<Option<TerminalSession>> }

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
        slot.take();
        *slot = Some(TerminalSession { writer, master });
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
        drop(child);
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
    slot.take();
    Ok(())
}

#[tauri::command]
fn agent_run(app: AppHandle, cwd: String, prompt: String, allow_changes: bool) -> Result<(), String> {
    let path = PathBuf::from(cwd).canonicalize().map_err(|e| e.to_string())?;
    if !path.is_dir() { return Err("Dossier de projet introuvable.".into()); }
    if prompt.trim().is_empty() { return Err("Demande vide.".into()); }

    let mut command = Command::new("zerocode");
    command.arg("--json").arg("--cwd").arg(&path).arg("--permissions")
        .arg(if allow_changes { "allow" } else { "ask" }).arg(prompt)
        .current_dir(&path).stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn().map_err(|e| format!("Commande zerocode introuvable dans PATH. Installe le moteur avant de lancer l'agent : {e}"))?;
    let stdout = child.stdout.take().ok_or("Sortie de l'agent indisponible.")?;
    let stderr = child.stderr.take().ok_or("Erreurs de l'agent indisponibles.")?;
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
        let code = child.wait().ok().and_then(|status| status.code());
        let event = serde_json::json!({"type":"process_finished","exit_code":code});
        let _ = handle.emit("agent-event", event.to_string());
    });
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![default_workspace, terminal_start, terminal_write, terminal_resize, terminal_stop, agent_run])
        .run(tauri::generate_context!())
        .expect("Erreur au démarrage de ZeroCode Desktop");
}