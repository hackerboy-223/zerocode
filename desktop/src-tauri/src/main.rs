#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    collections::HashMap,
    env,
    io::{BufRead, BufReader, Read, Write},
    path::Path,
    process::{Child as ProcessChild, ChildStdin, Command as ProcessCommand, Stdio},
    sync::Mutex,
    thread,
};

use portable_pty::{
    native_pty_system, Child as PtyChild, CommandBuilder, MasterPty, PtySize, PtySystem,
};
use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, State};
use uuid::Uuid;

struct TerminalSession {
    master: Box<dyn MasterPty + Send>,
    writer: Box<dyn Write + Send>,
    child: Box<dyn PtyChild + Send>,
}

impl Drop for TerminalSession {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

struct AgentProcess {
    input: ChildStdin,
    child: ProcessChild,
}

impl Drop for AgentProcess {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[derive(Default)]
struct DesktopState {
    terminals: Mutex<HashMap<String, TerminalSession>>,
    agents: Mutex<HashMap<String, AgentProcess>>,
}

#[derive(Serialize)]
struct TerminalOutput {
    id: String,
    data: Vec<u8>,
}

#[derive(Serialize)]
struct AgentEnvelope {
    agent_id: String,
    event: Value,
}

fn resolve_workspace(raw: &str) -> Result<String, String> {
    let path = Path::new(raw)
        .canonicalize()
        .map_err(|error| format!("Dossier inaccessible : {error}"))?;
    if !path.is_dir() {
        return Err("Le chemin choisi n’est pas un dossier.".to_string());
    }
    Ok(path.to_string_lossy().into_owned())
}

fn default_shell() -> String {
    #[cfg(target_os = "windows")]
    {
        return env::var("COMSPEC").unwrap_or_else(|_| "powershell.exe".to_string());
    }
    #[cfg(not(target_os = "windows"))]
    {
        let candidate = env::var("SHELL").unwrap_or_else(|_| "/bin/bash".to_string());
        if Path::new(&candidate).is_file() {
            candidate
        } else if Path::new("/bin/bash").is_file() {
            "/bin/bash".to_string()
        } else {
            "/bin/sh".to_string()
        }
    }
}

#[tauri::command]
fn start_terminal(
    app: AppHandle,
    state: State<'_, DesktopState>,
    cwd: String,
) -> Result<String, String> {
    let workspace = resolve_workspace(&cwd)?;
    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows: 24,
            cols: 96,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|error| format!("Impossible d’ouvrir un PTY : {error}"))?;

    let mut command = CommandBuilder::new(default_shell());
    command.cwd(&workspace);
    command.env("TERM", "xterm-256color");
    command.env("COLORTERM", "truecolor");

    let child = pair
        .slave
        .spawn_command(command)
        .map_err(|error| format!("Impossible de démarrer le shell local : {error}"))?;
    let mut reader = pair
        .master
        .try_clone_reader()
        .map_err(|error| format!("Impossible de lire le terminal : {error}"))?;
    let writer = pair
        .master
        .take_writer()
        .map_err(|error| format!("Impossible d’écrire dans le terminal : {error}"))?;
    let master = pair.master;
    let terminal_id = Uuid::new_v4().to_string();

    state
        .terminals
        .lock()
        .map_err(|_| "État du terminal indisponible.".to_string())?
        .insert(
            terminal_id.clone(),
            TerminalSession {
                master,
                writer,
                child,
            },
        );

    let app_for_reader = app.clone();
    let reader_id = terminal_id.clone();
    thread::spawn(move || {
        let mut buffer = [0_u8; 8192];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(size) => {
                    let payload = TerminalOutput {
                        id: reader_id.clone(),
                        data: buffer[..size].to_vec(),
                    };
                    let _ = app_for_reader.emit("terminal-output", payload);
                }
                Err(_) => break,
            }
        }
        let _ = app_for_reader.emit(
            "terminal-closed",
            json!({ "id": reader_id }),
        );
    });

    Ok(terminal_id)
}

#[tauri::command]
fn write_terminal(
    state: State<'_, DesktopState>,
    terminal_id: String,
    data: String,
) -> Result<(), String> {
    let mut terminals = state
        .terminals
        .lock()
        .map_err(|_| "État du terminal indisponible.".to_string())?;
    let session = terminals
        .get_mut(&terminal_id)
        .ok_or_else(|| "Session de terminal introuvable.".to_string())?;
    session
        .writer
        .write_all(data.as_bytes())
        .and_then(|_| session.writer.flush())
        .map_err(|error| format!("Écriture dans le terminal impossible : {error}"))
}

#[tauri::command]
fn resize_terminal(
    state: State<'_, DesktopState>,
    terminal_id: String,
    cols: u16,
    rows: u16,
) -> Result<(), String> {
    if !(2..=500).contains(&cols) || !(2..=300).contains(&rows) {
        return Err("Dimensions de terminal invalides.".to_string());
    }
    let terminals = state
        .terminals
        .lock()
        .map_err(|_| "État du terminal indisponible.".to_string())?;
    let session = terminals
        .get(&terminal_id)
        .ok_or_else(|| "Session de terminal introuvable.".to_string())?;
    session
        .master
        .resize(PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|error| format!("Redimensionnement impossible : {error}"))
}

#[tauri::command]
fn stop_terminal(
    state: State<'_, DesktopState>,
    terminal_id: String,
) -> Result<(), String> {
    let removed = state
        .terminals
        .lock()
        .map_err(|_| "État du terminal indisponible.".to_string())?
        .remove(&terminal_id);
    drop(removed);
    Ok(())
}

fn spawn_agent_process(workspace: &str) -> Result<ProcessChild, String> {
    let mut attempts: Vec<(String, Vec<String>)> = Vec::new();

    if let Ok(executable) = env::var("ZEROCODE_EXECUTABLE") {
        if !executable.trim().is_empty() {
            attempts.push((
                executable,
                vec![
                    "desktop-bridge".to_string(),
                    "--cwd".to_string(),
                    workspace.to_string(),
                ],
            ));
        }
    }

    attempts.push((
        "zerocode".to_string(),
        vec![
            "desktop-bridge".to_string(),
            "--cwd".to_string(),
            workspace.to_string(),
        ],
    ));

    #[cfg(target_os = "windows")]
    attempts.push((
        "py".to_string(),
        vec![
            "-3".to_string(),
            "-m".to_string(),
            "zerocode".to_string(),
            "desktop-bridge".to_string(),
            "--cwd".to_string(),
            workspace.to_string(),
        ],
    ));

    #[cfg(not(target_os = "windows"))]
    attempts.push((
        "python3".to_string(),
        vec![
            "-m".to_string(),
            "zerocode".to_string(),
            "desktop-bridge".to_string(),
            "--cwd".to_string(),
            workspace.to_string(),
        ],
    ));

    attempts.push((
        "python".to_string(),
        vec![
            "-m".to_string(),
            "zerocode".to_string(),
            "desktop-bridge".to_string(),
            "--cwd".to_string(),
            workspace.to_string(),
        ],
    ));

    let mut last_error = None;
    for (program, arguments) in attempts {
        let mut command = ProcessCommand::new(&program);
        command
            .args(&arguments)
            .current_dir(workspace)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        match command.spawn() {
            Ok(child) => return Ok(child),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                last_error = Some(format!("{program} : {error}"));
            }
            Err(error) => return Err(format!("Démarrage de ZeroCode impossible : {error}")),
        }
    }

    Err(format!(
        "ZeroCode CLI introuvable. Installe le moteur Python du projet ou configure ZEROCODE_EXECUTABLE. {}",
        last_error.unwrap_or_default()
    ))
}

#[tauri::command]
fn start_agent(
    app: AppHandle,
    state: State<'_, DesktopState>,
    cwd: String,
) -> Result<String, String> {
    let workspace = resolve_workspace(&cwd)?;
    let mut child = spawn_agent_process(&workspace)?;
    let input = child
        .stdin
        .take()
        .ok_or_else(|| "Entrée du processus ZeroCode indisponible.".to_string())?;
    let output = child
        .stdout
        .take()
        .ok_or_else(|| "Sortie du processus ZeroCode indisponible.".to_string())?;
    let errors = child.stderr.take();
    let agent_id = Uuid::new_v4().to_string();

    state
        .agents
        .lock()
        .map_err(|_| "État de l’agent indisponible.".to_string())?
        .insert(
            agent_id.clone(),
            AgentProcess {
                input,
                child,
            },
        );

    let app_for_output = app.clone();
    let output_id = agent_id.clone();
    thread::spawn(move || {
        for line in BufReader::new(output).lines() {
            let Ok(line) = line else { break };
            if line.trim().is_empty() {
                continue;
            }
            let event = serde_json::from_str::<Value>(&line)
                .unwrap_or_else(|_| json!({ "type": "log", "message": line }));
            let _ = app_for_output.emit(
                "agent-event",
                AgentEnvelope {
                    agent_id: output_id.clone(),
                    event,
                },
            );
        }
        let _ = app_for_output.emit(
            "agent-status",
            json!({ "agent_id": output_id, "status": "stopped" }),
        );
    });

    if let Some(stderr) = errors {
        let app_for_errors = app.clone();
        let error_id = agent_id.clone();
        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().flatten() {
                if !line.trim().is_empty() {
                    let _ = app_for_errors.emit(
                        "agent-log",
                        json!({ "agent_id": error_id, "message": line }),
                    );
                }
            }
        });
    }

    Ok(agent_id)
}

#[tauri::command]
fn send_agent_message(
    state: State<'_, DesktopState>,
    agent_id: String,
    message: Value,
) -> Result<(), String> {
    let mut agents = state
        .agents
        .lock()
        .map_err(|_| "État de l’agent indisponible.".to_string())?;
    let process = agents
        .get_mut(&agent_id)
        .ok_or_else(|| "Processus ZeroCode introuvable.".to_string())?;
    let mut payload = serde_json::to_vec(&message)
        .map_err(|error| format!("Message invalide : {error}"))?;
    payload.push(b'\n');
    process
        .input
        .write_all(&payload)
        .and_then(|_| process.input.flush())
        .map_err(|error| format!("Envoi vers ZeroCode impossible : {error}"))
}

#[tauri::command]
fn stop_agent(
    state: State<'_, DesktopState>,
    agent_id: String,
) -> Result<(), String> {
    let removed = state
        .agents
        .lock()
        .map_err(|_| "État de l’agent indisponible.".to_string())?
        .remove(&agent_id);
    drop(removed);
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(DesktopState::default())
        .invoke_handler(tauri::generate_handler![
            start_terminal,
            write_terminal,
            resize_terminal,
            stop_terminal,
            start_agent,
            send_agent_message,
            stop_agent
        ])
        .run(tauri::generate_context!())
        .expect("Erreur au lancement de ZeroCode Desktop");
}
