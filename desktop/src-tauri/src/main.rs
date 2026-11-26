#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    collections::HashMap,
    env,
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Read, Write},
    path::{Path, PathBuf},
    process::{Child as ProcessChild, ChildStdin, Command as ProcessCommand, Stdio},
    sync::{Arc, Mutex},
    thread,
};

use portable_pty::{native_pty_system, Child as PtyChild, CommandBuilder, MasterPty, PtySize};
use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};
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
    terminals: Arc<Mutex<HashMap<String, TerminalSession>>>,
    agents: Arc<Mutex<HashMap<String, AgentProcess>>>,
}

#[derive(Clone, Serialize)]
struct TerminalOutput {
    id: String,
    data: Vec<u8>,
}

#[derive(Clone, Serialize)]
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
    let terminals_for_reader = Arc::clone(&state.terminals);
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
        let closed_id = reader_id.clone();
        let _ = app_for_reader.emit("terminal-closed", json!({ "id": reader_id }));
        if let Ok(mut terminals) = terminals_for_reader.lock() {
            terminals.remove(&closed_id);
        }
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
fn stop_terminal(state: State<'_, DesktopState>, terminal_id: String) -> Result<(), String> {
    let removed = state
        .terminals
        .lock()
        .map_err(|_| "État du terminal indisponible.".to_string())?
        .remove(&terminal_id);
    drop(removed);
    Ok(())
}

fn desktop_path() -> std::ffi::OsString {
    let mut paths: Vec<std::path::PathBuf> = env::var_os("PATH")
        .map(|value| env::split_paths(&value).collect())
        .unwrap_or_default();
    if let Some(home) = env::var_os("HOME").map(std::path::PathBuf::from) {
        for candidate in [
            home.join(".local").join("bin"),
            home.join(".cargo").join("bin"),
        ] {
            if candidate.is_dir() && !paths.contains(&candidate) {
                paths.push(candidate);
            }
        }
    }
    env::join_paths(paths).unwrap_or_else(|_| env::var_os("PATH").unwrap_or_default())
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

    for root in [
        Some(PathBuf::from(workspace)),
        Path::new(workspace).parent().map(PathBuf::from),
    ]
    .into_iter()
    .flatten()
    {
        for rel in [
            Path::new(".venv").join("bin").join("zerocode"),
            Path::new(".venv").join("Scripts").join("zerocode.exe"),
        ] {
            let candidate = root.join(rel);
            if candidate.is_file() {
                attempts.push((
                    candidate.to_string_lossy().into_owned(),
                    vec![
                        "desktop-bridge".to_string(),
                        "--cwd".to_string(),
                        workspace.to_string(),
                    ],
                ));
            }
        }
    }

    #[cfg(target_os = "windows")]
    let user_home = env::var_os("USERPROFILE").or_else(|| env::var_os("HOME"));
    #[cfg(not(target_os = "windows"))]
    let user_home = env::var_os("HOME");

    if let Some(home) = user_home.map(PathBuf::from) {
        #[cfg(target_os = "windows")]
        let pipx_entry = home.join(".local").join("bin").join("zerocode.exe");
        #[cfg(not(target_os = "windows"))]
        let pipx_entry = home.join(".local").join("bin").join("zerocode");

        #[cfg(target_os = "windows")]
        let pipx_venv = env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join("AppData").join("Local"))
            .join("pipx")
            .join("pipx")
            .join("venvs")
            .join("zerocode")
            .join("Scripts")
            .join("zerocode.exe");
        #[cfg(not(target_os = "windows"))]
        let pipx_venv = home
            .join(".local")
            .join("share")
            .join("pipx")
            .join("venvs")
            .join("zerocode")
            .join("bin")
            .join("zerocode");

        if pipx_entry.is_file() {
            attempts.push((
                pipx_entry.to_string_lossy().into_owned(),
                vec![
                    "desktop-bridge".to_string(),
                    "--cwd".to_string(),
                    workspace.to_string(),
                ],
            ));
        }
        if pipx_venv.is_file() {
            attempts.push((
                pipx_venv.to_string_lossy().into_owned(),
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
            .env("PATH", desktop_path())
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
    cwd: Option<String>,
) -> Result<String, String> {
    // Sans projet ouvert, l’agent démarre dans un espace isolé propre à l’application.
    // Cela permet la conversation libre sans lui donner accès au dossier personnel entier.
    let workspace = match cwd {
        Some(path) if !path.trim().is_empty() => resolve_workspace(&path)?,
        _ => {
            let scratch = app
                .path()
                .app_data_dir()
                .map_err(|error| format!("Dossier de données ZeroCode indisponible : {error}"))?
                .join("scratch");
            fs::create_dir_all(&scratch)
                .map_err(|error| format!("Espace de conversation impossible à créer : {error}"))?;
            resolve_workspace(&scratch.to_string_lossy())?
        }
    };
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
        .insert(agent_id.clone(), AgentProcess { input, child });

    let app_for_output = app.clone();
    let agents_for_output = Arc::clone(&state.agents);
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
        let finished_id = output_id.clone();
        let _ = app_for_output.emit(
            "agent-status",
            json!({ "agent_id": output_id, "status": "stopped" }),
        );
        if let Ok(mut agents) = agents_for_output.lock() {
            agents.remove(&finished_id);
        }
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
    let mut payload =
        serde_json::to_vec(&message).map_err(|error| format!("Message invalide : {error}"))?;
    payload.push(b'\n');
    process
        .input
        .write_all(&payload)
        .and_then(|_| process.input.flush())
        .map_err(|error| format!("Envoi vers ZeroCode impossible : {error}"))
}

#[tauri::command]
fn stop_agent(state: State<'_, DesktopState>, agent_id: String) -> Result<(), String> {
    let removed = state
        .agents
        .lock()
        .map_err(|_| "État de l’agent indisponible.".to_string())?
        .remove(&agent_id);
    drop(removed);
    Ok(())
}

#[derive(Serialize)]
struct WorkspaceEntry {
    name: String,
    path: String,
    kind: String,
    size: u64,
}

#[derive(Serialize)]
struct WorkspaceFilePreview {
    path: String,
    content: String,
    lines: usize,
    truncated: bool,
}

#[derive(Serialize)]
struct GitChangedFile {
    status: String,
    path: String,
    staged: bool,
}

#[derive(Serialize)]
struct GitWorkspaceInfo {
    is_repo: bool,
    branch: String,
    dirty_count: usize,
    changed_files: Vec<GitChangedFile>,
}

#[derive(Serialize)]
struct GitFileVersions {
    path: String,
    original: String,
    modified: String,
}

#[derive(Serialize)]
struct WorkspaceSearchMatch {
    path: String,
    line: usize,
    snippet: String,
    score: usize,
}

fn is_sensitive_path(path: &Path) -> bool {
    let name = path
        .file_name()
        .map(|value| value.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    if matches!(
        name.as_str(),
        ".env.example" | ".env.sample" | ".env.template" | ".env.dist"
    ) {
        return false;
    }
    if matches!(
        name.as_str(),
        ".env"
            | ".netrc"
            | ".npmrc"
            | ".pypirc"
            | ".git-credentials"
            | "credentials"
            | "credentials.json"
            | "id_rsa"
            | "id_dsa"
            | "id_ecdsa"
            | "id_ed25519"
    ) || name.starts_with(".env.")
    {
        return true;
    }
    if [".pem", ".key", ".p12", ".pfx", ".keystore", ".jks"]
        .iter()
        .any(|suffix| name.ends_with(suffix))
    {
        return true;
    }
    path.components().any(|comp| {
        let part = comp.as_os_str().to_string_lossy().to_lowercase();
        matches!(part.as_str(), ".ssh" | ".aws" | ".gnupg")
    })
}

fn resolve_inside_workspace(workspace: &str, relative: &str) -> Result<(PathBuf, PathBuf), String> {
    let root = Path::new(workspace)
        .canonicalize()
        .map_err(|error| format!("Dossier de travail inaccessible : {error}"))?;
    let trimmed = relative.trim().trim_start_matches(['/', '\\']);
    let candidate = if trimmed.is_empty() || trimmed == "." {
        root.clone()
    } else {
        root.join(trimmed)
    };
    let resolved = candidate
        .canonicalize()
        .map_err(|error| format!("Chemin introuvable : {error}"))?;
    if !resolved.starts_with(&root) {
        return Err("Accès hors du dossier de travail refusé.".to_string());
    }
    Ok((root, resolved))
}

#[tauri::command]
fn list_workspace_files(
    cwd: String,
    relative_dir: Option<String>,
) -> Result<Vec<WorkspaceEntry>, String> {
    let rel = relative_dir.unwrap_or_default();
    let (root, target_dir) = resolve_inside_workspace(&cwd, &rel)?;
    if !target_dir.is_dir() {
        return Err("Le chemin demandé n’est pas un dossier.".to_string());
    }
    let ignored_dirs = [
        ".git",
        "node_modules",
        "target",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "dist",
        "build",
    ];
    let entries = fs::read_dir(&target_dir)
        .map_err(|error| format!("Impossible de lire le dossier : {error}"))?;
    let mut items: Vec<WorkspaceEntry> = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();
        if name.is_empty() {
            continue;
        }
        let metadata = match entry.metadata() {
            Ok(meta) => meta,
            Err(_) => continue,
        };
        let is_dir = metadata.is_dir();
        if is_dir && ignored_dirs.contains(&name.as_str()) {
            continue;
        }
        let rel_path = path
            .strip_prefix(&root)
            .unwrap_or(&path)
            .to_string_lossy()
            .replace('\\', "/");
        items.push(WorkspaceEntry {
            name,
            path: rel_path,
            kind: if is_dir {
                "dir".to_string()
            } else {
                "file".to_string()
            },
            size: if is_dir { 0 } else { metadata.len() },
        });
    }
    items.sort_by(|a, b| match (a.kind.as_str(), b.kind.as_str()) {
        ("dir", "file") => std::cmp::Ordering::Less,
        ("file", "dir") => std::cmp::Ordering::Greater,
        _ => a.name.to_lowercase().cmp(&b.name.to_lowercase()),
    });
    if items.len() > 250 {
        items.truncate(250);
    }
    Ok(items)
}

#[tauri::command]
fn read_workspace_file(cwd: String, relative_path: String) -> Result<WorkspaceFilePreview, String> {
    let raw_path = Path::new(&relative_path);
    if raw_path.components().any(|component| {
        matches!(
            component,
            std::path::Component::ParentDir
                | std::path::Component::RootDir
                | std::path::Component::Prefix(_)
        )
    }) {
        return Err("Chemin de sauvegarde invalide.".to_string());
    }
    let workspace_root = resolve_workspace(&cwd)?;
    let mut cursor = PathBuf::from(&workspace_root);
    for component in raw_path.components() {
        if let std::path::Component::Normal(part) = component {
            cursor.push(part);
            if fs::symlink_metadata(&cursor)
                .map(|metadata| metadata.file_type().is_symlink())
                .unwrap_or(false)
            {
                return Err("La sauvegarde à travers un lien symbolique est refusée.".to_string());
            }
        }
    }
    let (root, target) = resolve_inside_workspace(&cwd, &relative_path)?;
    if !target.is_file() {
        return Err("Ce chemin n’est pas un fichier.".to_string());
    }
    if is_sensitive_path(&target) {
        return Err("Fichier de secrets protégé par ZeroCode.".to_string());
    }
    let mut file = fs::File::open(&target)
        .map_err(|error| format!("Ouverture du fichier impossible : {error}"))?;
    let max_bytes: usize = 120_000;
    let mut buffer = Vec::with_capacity(8192);
    let mut handle = (&mut file).take((max_bytes + 1) as u64);
    handle
        .read_to_end(&mut buffer)
        .map_err(|error| format!("Lecture du fichier impossible : {error}"))?;
    let truncated = buffer.len() > max_bytes;
    if truncated {
        buffer.truncate(max_bytes);
    }
    if buffer.iter().take(4096).any(|&byte| byte == 0) {
        return Err("Aperçu indisponible pour un fichier binaire.".to_string());
    }
    let content = String::from_utf8(buffer).map_err(|_| {
        "Fichier non UTF-8 : aperçu et édition refusés pour préserver les octets originaux."
            .to_string()
    })?;
    let lines = content.lines().count().max(1);
    let rel_path = target
        .strip_prefix(&root)
        .unwrap_or(&target)
        .to_string_lossy()
        .replace('\\', "/");
    Ok(WorkspaceFilePreview {
        path: rel_path,
        content,
        lines,
        truncated,
    })
}

#[tauri::command]
fn write_workspace_file(
    cwd: String,
    relative_path: String,
    content: String,
) -> Result<WorkspaceFilePreview, String> {
    const MAX_WRITE_BYTES: usize = 2_000_000;
    if content.len() > MAX_WRITE_BYTES {
        return Err("Le fichier dépasse la limite de sauvegarde de 2 Mo.".to_string());
    }
    if content.as_bytes().contains(&0) {
        return Err("Le contenu contient un octet nul : sauvegarde refusée.".to_string());
    }
    let (root, target) = resolve_inside_workspace(&cwd, &relative_path)?;
    if !target.is_file() {
        return Err("La sauvegarde ne peut viser qu’un fichier existant.".to_string());
    }
    if is_sensitive_path(&target) {
        return Err("Fichier de secrets protégé par ZeroCode.".to_string());
    }
    let metadata = fs::symlink_metadata(&target)
        .map_err(|error| format!("Métadonnées du fichier indisponibles : {error}"))?;
    if metadata.file_type().is_symlink() {
        return Err("La sauvegarde d’un lien symbolique est refusée.".to_string());
    }
    let parent = target
        .parent()
        .ok_or_else(|| "Dossier parent introuvable.".to_string())?
        .canonicalize()
        .map_err(|error| format!("Dossier parent inaccessible : {error}"))?;
    if !parent.starts_with(&root) {
        return Err("Écriture hors du workspace refusée.".to_string());
    }
    let temp_path = parent.join(format!(".zerocode-save-{}.tmp", Uuid::new_v4()));
    let write_result = (|| -> Result<(), String> {
        let mut temp_file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp_path)
            .map_err(|error| format!("Fichier temporaire impossible à créer : {error}"))?;
        temp_file
            .write_all(content.as_bytes())
            .map_err(|error| format!("Écriture temporaire impossible : {error}"))?;
        temp_file
            .sync_all()
            .map_err(|error| format!("Synchronisation du fichier impossible : {error}"))?;
        fs::set_permissions(&temp_path, metadata.permissions())
            .map_err(|error| format!("Conservation des permissions impossible : {error}"))?;
        fs::rename(&temp_path, &target)
            .map_err(|error| format!("Remplacement atomique du fichier impossible : {error}"))?;
        Ok(())
    })();
    if let Err(error) = write_result {
        let _ = fs::remove_file(&temp_path);
        return Err(error);
    }
    let saved = fs::read(&target)
        .map_err(|error| format!("Vérification après sauvegarde impossible : {error}"))?;
    let rendered = String::from_utf8(saved)
        .map_err(|_| "Le fichier sauvegardé n’est pas un texte UTF-8 valide.".to_string())?;
    let path = target
        .strip_prefix(&root)
        .unwrap_or(&target)
        .to_string_lossy()
        .replace('\\', "/");
    Ok(WorkspaceFilePreview {
        path,
        lines: rendered.lines().count().max(1),
        truncated: false,
        content: rendered,
    })
}

#[tauri::command]
fn create_workspace_file(
    cwd: String,
    relative_path: String,
) -> Result<WorkspaceFilePreview, String> {
    let raw_path = Path::new(&relative_path);
    if raw_path.as_os_str().is_empty()
        || raw_path.components().any(|component| {
            matches!(
                component,
                std::path::Component::ParentDir
                    | std::path::Component::RootDir
                    | std::path::Component::Prefix(_)
            )
        })
    {
        return Err("Chemin de création invalide.".to_string());
    }
    let root = PathBuf::from(resolve_workspace(&cwd)?);
    let file_name = raw_path
        .file_name()
        .ok_or_else(|| "Nom de fichier manquant.".to_string())?;
    let parent_relative = raw_path.parent().unwrap_or_else(|| Path::new(""));
    let mut parent_candidate = root.clone();
    for component in parent_relative.components() {
        if let std::path::Component::Normal(part) = component {
            parent_candidate.push(part);
            if fs::symlink_metadata(&parent_candidate)
                .map(|metadata| metadata.file_type().is_symlink())
                .unwrap_or(false)
            {
                return Err("Création à travers un lien symbolique refusée.".to_string());
            }
        }
    }
    let parent = parent_candidate
        .canonicalize()
        .map_err(|error| format!("Dossier parent inaccessible : {error}"))?;
    if !parent.starts_with(&root) || !parent.is_dir() {
        return Err("Le dossier parent doit rester dans le workspace.".to_string());
    }
    let target = parent.join(file_name);
    if is_sensitive_path(&target) {
        return Err("La création d’un fichier de secrets est refusée.".to_string());
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&target)
        .map_err(|error| format!("Création du fichier impossible : {error}"))?;
    file.flush()
        .map_err(|error| format!("Finalisation du fichier impossible : {error}"))?;
    let path = target
        .strip_prefix(&root)
        .unwrap_or(&target)
        .to_string_lossy()
        .replace('\\', "/");
    Ok(WorkspaceFilePreview {
        path,
        content: String::new(),
        lines: 1,
        truncated: false,
    })
}

#[tauri::command]
fn workspace_git_info(cwd: String) -> Result<GitWorkspaceInfo, String> {
    let workspace = resolve_workspace(&cwd)?;
    let inside = safe_git_command(&workspace)
        .args(["rev-parse", "--is-inside-work-tree"])
        .output();
    let is_repo = inside
        .map(|res| res.status.success() && String::from_utf8_lossy(&res.stdout).trim() == "true")
        .unwrap_or(false);
    if !is_repo {
        return Ok(GitWorkspaceInfo {
            is_repo: false,
            branch: "local".to_string(),
            dirty_count: 0,
            changed_files: Vec::new(),
        });
    }
    let branch = safe_git_command(&workspace)
        .args(["symbolic-ref", "--short", "HEAD"])
        .output()
        .ok()
        .filter(|res| res.status.success())
        .map(|res| String::from_utf8_lossy(&res.stdout).trim().to_string())
        .filter(|value| !value.is_empty())
        .or_else(|| {
            safe_git_command(&workspace)
                .args(["rev-parse", "--abbrev-ref", "HEAD"])
                .output()
                .ok()
                .filter(|res| res.status.success())
                .map(|res| String::from_utf8_lossy(&res.stdout).trim().to_string())
                .filter(|value| !value.is_empty())
        })
        .unwrap_or_else(|| "HEAD".to_string());
    // Git status can invoke repository-configured fsmonitor helpers and clean filters.
    // Workspace opening must never execute those helpers implicitly. Keep the
    // automatic overview read-only until Git inspection is explicitly approved.
    Ok(GitWorkspaceInfo {
        is_repo: true,
        branch,
        dirty_count: 0,
        changed_files: Vec::new(),
    })
}

fn safe_git_command(workspace: &str) -> ProcessCommand {
    let mut cmd = ProcessCommand::new("git");
    cmd.args([
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "diff.external=",
    ])
    .current_dir(workspace);
    cmd
}

fn validate_relative_git_path(relative: &str) -> Result<String, String> {
    let cleaned = relative.trim().replace('\\', "/");
    if cleaned.is_empty() || cleaned.starts_with('-') {
        return Err("Chemin Git invalide.".to_string());
    }
    let path = Path::new(&cleaned);
    if path.components().any(|component| {
        matches!(
            component,
            std::path::Component::ParentDir
                | std::path::Component::RootDir
                | std::path::Component::Prefix(_)
        )
    }) {
        return Err("Chemin Git hors du dépôt refusé.".to_string());
    }
    if is_sensitive_path(path) {
        return Err("Fichier de secrets protégé par ZeroCode.".to_string());
    }
    Ok(cleaned)
}

#[tauri::command]
fn workspace_git_status_explicit(cwd: String) -> Result<GitWorkspaceInfo, String> {
    let base = workspace_git_info(cwd.clone())?;
    if !base.is_repo {
        return Ok(base);
    }
    let workspace = resolve_workspace(&cwd)?;
    let out = safe_git_command(&workspace)
        .args(["status", "--porcelain=v1", "-uall"])
        .output()
        .map_err(|error| format!("Impossible d’exécuter git status : {error}"))?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).trim().to_string());
    }
    let mut changed_files: Vec<GitChangedFile> = Vec::new();
    for line in String::from_utf8_lossy(&out.stdout).lines() {
        if line.len() < 4 {
            continue;
        }
        let bytes = line.as_bytes();
        let x = bytes[0] as char;
        let y = bytes[1] as char;
        let raw_path = line[3..].trim().trim_matches('"');
        let path = raw_path
            .rsplit(" -> ")
            .next()
            .unwrap_or(raw_path)
            .to_string();
        if path.is_empty() {
            continue;
        }
        let staged = x != ' ' && x != '?';
        let code = format!("{x}{y}").trim().to_string();
        changed_files.push(GitChangedFile {
            status: if code.is_empty() {
                "M".to_string()
            } else {
                code
            },
            path,
            staged,
        });
    }
    let dirty_count = changed_files.len();
    if changed_files.len() > 100 {
        changed_files.truncate(100);
    }
    Ok(GitWorkspaceInfo {
        is_repo: true,
        branch: base.branch,
        dirty_count,
        changed_files,
    })
}

#[tauri::command]
fn workspace_git_file_versions(
    cwd: String,
    relative_path: String,
) -> Result<GitFileVersions, String> {
    let rel = validate_relative_git_path(&relative_path)?;
    let workspace = resolve_workspace(&cwd)?;
    let head_spec = format!("HEAD:{rel}");
    let head_out = safe_git_command(&workspace)
        .args(["show", &head_spec])
        .output()
        .map_err(|error| format!("Lecture HEAD impossible : {error}"))?;
    let original = if head_out.status.success() {
        if head_out.stdout.len() > 200_000 {
            return Err(
                "Version HEAD trop volumineuse pour la comparaison (> 200 Ko).".to_string(),
            );
        }
        if head_out.stdout.iter().take(4096).any(|&b| b == 0) {
            return Err("Comparaison indisponible pour un fichier binaire.".to_string());
        }
        String::from_utf8(head_out.stdout)
            .map_err(|_| "Version HEAD non UTF-8 : comparaison refusée.".to_string())?
    } else {
        String::new()
    };

    let candidate = PathBuf::from(&workspace).join(&rel);
    let modified = if candidate.exists() {
        read_workspace_file(cwd, rel.clone())?.content
    } else {
        String::new()
    };

    Ok(GitFileVersions {
        path: rel,
        original,
        modified,
    })
}

#[tauri::command]
fn workspace_git_stage(
    cwd: String,
    relative_path: String,
    unstage: bool,
) -> Result<GitWorkspaceInfo, String> {
    let rel = validate_relative_git_path(&relative_path)?;
    let workspace = resolve_workspace(&cwd)?;
    let mut cmd = safe_git_command(&workspace);
    if unstage {
        cmd.args(["reset", "HEAD", "--", &rel]);
    } else {
        cmd.args(["add", "--", &rel]);
    }
    let out = cmd
        .output()
        .map_err(|error| format!("Opération Git impossible : {error}"))?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr).trim().to_string();
        return Err(if err.is_empty() {
            "L’opération Git a échoué.".to_string()
        } else {
            err
        });
    }
    workspace_git_status_explicit(cwd)
}

#[tauri::command]
fn workspace_git_commit(cwd: String, message: String) -> Result<String, String> {
    let trimmed = message.trim();
    if trimmed.is_empty() {
        return Err("Le message de commit ne peut pas être vide.".to_string());
    }
    if trimmed.len() > 500 {
        return Err("Le message de commit ne doit pas dépasser 500 caractères.".to_string());
    }
    let workspace = resolve_workspace(&cwd)?;
    let out = safe_git_command(&workspace)
        .args(["commit", "--no-verify", "-m", trimmed])
        .output()
        .map_err(|error| format!("Commit Git impossible : {error}"))?;
    if !out.status.success() {
        let stderr = String::from_utf8_lossy(&out.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&out.stdout).trim().to_string();
        return Err(if !stderr.is_empty() {
            stderr
        } else if !stdout.is_empty() {
            stdout
        } else {
            "Rien à commiter (indexez d’abord au moins un fichier).".to_string()
        });
    }
    let summary = String::from_utf8_lossy(&out.stdout)
        .lines()
        .next()
        .unwrap_or("Commit créé.")
        .trim()
        .to_string();
    Ok(summary)
}

#[tauri::command]
fn search_workspace_files(
    cwd: String,
    query: String,
    limit: Option<usize>,
) -> Result<Vec<WorkspaceSearchMatch>, String> {
    let trimmed = query.trim();
    if trimmed.is_empty() {
        return Ok(Vec::new());
    }
    let workspace = resolve_workspace(&cwd)?;
    let root = PathBuf::from(&workspace);
    let max_results = limit.unwrap_or(50).clamp(1, 100);
    let needle = trimmed.to_lowercase();
    let terms: Vec<&str> = needle.split_whitespace().collect();
    if terms.is_empty() {
        return Ok(Vec::new());
    }

    const IGNORED_DIRS: &[&str] = &[
        ".git",
        ".ssh",
        ".aws",
        ".gnupg",
        "node_modules",
        ".venv",
        "venv",
        "target",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "dist",
        "build",
        ".next",
    ];
    const IGNORED_EXTS: &[&str] = &[
        "png", "jpg", "jpeg", "gif", "webp", "ico", "pdf", "zip", "gz", "tar", "lock", "sqlite",
        "db", "wasm", "mp4", "mp3", "woff", "woff2", "ttf", "otf", "exe", "dll", "so", "dylib",
    ];
    const MAX_FILES: usize = 4_000;
    const MAX_FILE_BYTES: u64 = 512_000;

    let mut queue = std::collections::VecDeque::new();
    queue.push_back((root.clone(), 0usize));
    let mut matches: Vec<WorkspaceSearchMatch> = Vec::new();
    let mut visited_files: usize = 0;

    while let Some((dir, depth)) = queue.pop_front() {
        if visited_files >= MAX_FILES || depth > 12 {
            break;
        }
        let Ok(entries) = fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            if visited_files >= MAX_FILES {
                break;
            }
            let path = entry.path();
            let Ok(meta) = fs::symlink_metadata(&path) else {
                continue;
            };
            if meta.file_type().is_symlink() {
                continue;
            }
            let name = entry.file_name().to_string_lossy().into_owned();
            if meta.is_dir() {
                if !IGNORED_DIRS.contains(&name.as_str()) {
                    queue.push_back((path, depth + 1));
                }
                continue;
            }
            if !meta.is_file() || meta.len() > MAX_FILE_BYTES || is_sensitive_path(&path) {
                continue;
            }
            if let Some(ext) = path.extension().and_then(|value| value.to_str()) {
                if IGNORED_EXTS.contains(&ext.to_lowercase().as_str()) {
                    continue;
                }
            }
            visited_files += 1;

            let rel_path = path
                .strip_prefix(&root)
                .unwrap_or(&path)
                .to_string_lossy()
                .replace('\\', "/");
            let rel_lower = rel_path.to_lowercase();
            let path_matches_all = terms.iter().all(|term| rel_lower.contains(term));

            let Ok(bytes) = fs::read(&path) else {
                continue;
            };
            if bytes.iter().take(4096).any(|&byte| byte == 0) {
                continue;
            }
            let Ok(content) = String::from_utf8(bytes) else {
                continue;
            };

            let mut file_hits = 0usize;
            for (idx, line) in content.lines().enumerate() {
                let line_lower = line.to_lowercase();
                let exact = line_lower.contains(&needle);
                let all_terms = exact || terms.iter().all(|term| line_lower.contains(term));
                if all_terms {
                    let mut score = if exact { 20 } else { 10 };
                    if path_matches_all {
                        score += 15;
                    }
                    let trimmed_line = line.trim();
                    let snippet: String = trimmed_line.chars().take(180).collect();
                    matches.push(WorkspaceSearchMatch {
                        path: rel_path.clone(),
                        line: idx + 1,
                        snippet,
                        score,
                    });
                    file_hits += 1;
                    if file_hits >= 3 {
                        break;
                    }
                }
            }

            if file_hits == 0 && path_matches_all {
                let first_line: String = content
                    .lines()
                    .find(|l| !l.trim().is_empty())
                    .unwrap_or("")
                    .trim()
                    .chars()
                    .take(160)
                    .collect();
                matches.push(WorkspaceSearchMatch {
                    path: rel_path,
                    line: 1,
                    snippet: first_line,
                    score: 18,
                });
            }
        }
    }

    matches.sort_by(|a, b| {
        b.score
            .cmp(&a.score)
            .then_with(|| a.path.cmp(&b.path))
            .then_with(|| a.line.cmp(&b.line))
    });
    matches.truncate(max_results);
    Ok(matches)
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
            stop_agent,
            list_workspace_files,
            read_workspace_file,
            write_workspace_file,
            create_workspace_file,
            search_workspace_files,
            workspace_git_info,
            workspace_git_status_explicit,
            workspace_git_file_versions,
            workspace_git_stage,
            workspace_git_commit
        ])
        .run(tauri::generate_context!())
        .expect("Erreur au lancement de ZeroCode Desktop");
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn make_temp_workspace(label: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = env::temp_dir().join(format!(
            "zerocode-rust-test-{label}-{}-{nanos}",
            std::process::id()
        ));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn sensitive_path_blocks_secrets_but_allows_examples() {
        assert!(is_sensitive_path(Path::new("/tmp/proj/.env")));
        assert!(is_sensitive_path(Path::new("/tmp/proj/.env.production")));
        assert!(is_sensitive_path(Path::new("/tmp/proj/cert.pem")));
        assert!(is_sensitive_path(Path::new("/tmp/proj/.ssh/id_rsa")));
        assert!(is_sensitive_path(Path::new("/tmp/proj/credentials.json")));
        assert!(!is_sensitive_path(Path::new("/tmp/proj/.env.example")));
        assert!(!is_sensitive_path(Path::new("/tmp/proj/src/main.rs")));
    }

    #[test]
    fn resolve_inside_workspace_rejects_parent_escape() {
        let dir = make_temp_workspace("resolve");
        let file = dir.join("hello.txt");
        fs::write(&file, "hello").unwrap();

        let ok = resolve_inside_workspace(dir.to_str().unwrap(), "hello.txt");
        assert!(ok.is_ok());

        let escaped = resolve_inside_workspace(dir.to_str().unwrap(), "../");
        assert!(escaped.is_err());

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn read_and_write_workspace_file_enforce_safety() {
        let dir = make_temp_workspace("rw");
        let cwd = dir.to_str().unwrap().to_string();

        fs::write(dir.join(".env"), "SECRET=1").unwrap();
        fs::write(dir.join("bin.dat"), [0u8, 1, 2, 3]).unwrap();
        fs::write(dir.join("bad.txt"), [0xffu8, 0xfe]).unwrap();

        assert!(read_workspace_file(cwd.clone(), ".env".into()).is_err());
        assert!(read_workspace_file(cwd.clone(), "../etc/passwd".into()).is_err());
        assert!(read_workspace_file(cwd.clone(), "bin.dat".into()).is_err());
        assert!(read_workspace_file(cwd.clone(), "bad.txt".into()).is_err());

        fs::create_dir_all(dir.join("notes")).unwrap();
        let created = create_workspace_file(cwd.clone(), "notes/todo.md".into()).unwrap();
        assert_eq!(created.path, "notes/todo.md");

        let written = write_workspace_file(
            cwd.clone(),
            "notes/todo.md".into(),
            "Ligne 1\nLigne 2".into(),
        )
        .unwrap();
        assert_eq!(written.lines, 2);

        let preview = read_workspace_file(cwd.clone(), "notes/todo.md".into()).unwrap();
        assert_eq!(preview.content, "Ligne 1\nLigne 2");

        assert!(write_workspace_file(cwd.clone(), "notes/todo.md".into(), "a\0b".into()).is_err());

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn search_workspace_files_finds_matches_and_skips_secrets_and_ignored() {
        let dir = make_temp_workspace("search");
        let cwd = dir.to_str().unwrap().to_string();

        fs::create_dir_all(dir.join("src")).unwrap();
        fs::create_dir_all(dir.join("node_modules/pkg")).unwrap();
        fs::write(
            dir.join("src/app.ts"),
            "export function greetUser() {\n  return 'ZeroCode Ready';\n}\n",
        )
        .unwrap();
        fs::write(dir.join(".env"), "API_KEY=ZeroCode Ready").unwrap();
        fs::write(dir.join("node_modules/pkg/index.js"), "ZeroCode Ready").unwrap();

        let results =
            search_workspace_files(cwd.clone(), "ZeroCode Ready".into(), Some(20)).unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].path, "src/app.ts");
        assert_eq!(results[0].line, 2);
        assert!(results[0].snippet.contains("ZeroCode Ready"));

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn workspace_git_info_handles_non_repo_safely() {
        let dir = make_temp_workspace("git");
        let info = workspace_git_info(dir.to_str().unwrap().to_string()).unwrap();
        assert!(!info.is_repo);
        assert_eq!(info.dirty_count, 0);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn validate_relative_git_path_blocks_flags_escape_and_secrets() {
        assert!(validate_relative_git_path("-f").is_err());
        assert!(validate_relative_git_path("../secret.txt").is_err());
        assert!(validate_relative_git_path(".env").is_err());
        assert!(validate_relative_git_path("src/main.rs").is_ok());
    }

    #[test]
    fn explicit_git_status_diff_stage_and_commit_flow() {
        let dir = make_temp_workspace("git-flow");
        let cwd = dir.to_str().unwrap().to_string();

        let init = ProcessCommand::new("git")
            .args(["init"])
            .current_dir(&dir)
            .output()
            .unwrap();
        assert!(init.status.success());
        ProcessCommand::new("git")
            .args(["config", "user.email", "test@example.com"])
            .current_dir(&dir)
            .output()
            .unwrap();
        ProcessCommand::new("git")
            .args(["config", "user.name", "Test User"])
            .current_dir(&dir)
            .output()
            .unwrap();

        fs::write(dir.join("hello.txt"), "v1\n").unwrap();
        let staged = workspace_git_stage(cwd.clone(), "hello.txt".into(), false).unwrap();
        assert_eq!(staged.dirty_count, 1);
        assert!(staged.changed_files[0].staged);
        let summary = workspace_git_commit(cwd.clone(), "Initial commit".into()).unwrap();
        assert!(summary.contains("Initial commit"));

        fs::write(dir.join("hello.txt"), "v2\n").unwrap();
        let dirty = workspace_git_status_explicit(cwd.clone()).unwrap();
        assert_eq!(dirty.dirty_count, 1);
        assert!(!dirty.changed_files[0].staged);

        let versions = workspace_git_file_versions(cwd.clone(), "hello.txt".into()).unwrap();
        assert_eq!(versions.original, "v1\n");
        assert_eq!(versions.modified, "v2\n");

        let _ = fs::remove_dir_all(&dir);
    }
}
