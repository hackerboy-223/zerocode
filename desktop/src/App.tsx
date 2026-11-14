import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { Activity, ArrowDown, ArrowUp, Bot, ChevronDown, Command, FileCode2, Folder, FolderOpen, GitBranch, History, PanelLeftClose, Plus, Send, Settings2, ShieldCheck, Sparkles, SquareTerminal, X, Zap } from "lucide-react";

type EventPayload = { type?: string; delta?: string; name?: string; message?: string; arguments?: Record<string, unknown>; command?: string };
type Approval = { kind: "tool" | "sudo-confirm" | "sudo-password"; name: string; details: string };
type Message = { role: "assistant" | "user"; text: string };
type ProjectEntry = { path: string; is_dir: boolean };

function Lupus({ small = false }: { small?: boolean }) {
  return <motion.div className={small ? "lupus small" : "lupus"} animate={{ y: [0, -4, 0], rotate: [0, 1.5, 0, -1.5, 0] }} transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}>
    <svg viewBox="0 0 120 110" role="img" aria-label="LUPUS">
      <defs><linearGradient id="fur" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#d9e2ef"/><stop offset="1" stopColor="#7d91ad"/></linearGradient></defs>
      <path d="M21 39 13 8l30 18Q59 17 78 27L106 9l-5 39q7 24-10 40-13 14-32 13-22-1-34-19Q12 65 21 39Z" fill="url(#fur)" stroke="#64748b" strokeWidth="2.5"/>
      <path d="m25 31-5-14 18 12m44 0 17-12-3 18" fill="#9aaac0"/><path d="M28 47q12-15 29-8 17-8 31 8l-5 25q-9 18-27 18T31 72Z" fill="#e7edf5"/>
      <path d="M38 54q8-8 16 0m12 0q8-8 16 0" fill="none" stroke="#263449" strokeWidth="4" strokeLinecap="round"/><path d="M53 70q7-7 14 0l-7 7Z" fill="#263449"/><path d="M45 78q15 12 30 0" fill="none" stroke="#53657d" strokeWidth="2" strokeLinecap="round"/><circle cx="60" cy="14" r="4" fill="#91b9ff"/>
    </svg><span/>
  </motion.div>;
}

function LocalTerminal({ cwd, onReady }: { cwd: string; onReady: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const terminal = new Terminal({ cursorBlink: true, fontFamily: '"JetBrains Mono", monospace', fontSize: 12.5, lineHeight: 1.5, theme: { background: "#101216", foreground: "#d7dde8", cursor: "#9bbcff", selectionBackground: "#34445d" }, scrollback: 3000 });
    const fit = new FitAddon(); terminal.loadAddon(fit); terminal.open(host.current); requestAnimationFrame(() => fit.fit());
    let stop: (() => void) | undefined; let live = true;
    void listen<string>("terminal-output", event => { if (live) terminal.write(event.payload); }).then(fn => stop = fn);
    void invoke("terminal_start", { cwd }).then(onReady).catch(error => terminal.writeln("\r\n\x1b[31m" + String(error) + "\x1b[0m"));
    const input = terminal.onData(data => { void invoke("terminal_write", { data }).catch(() => undefined); });
    const observer = new ResizeObserver(() => { fit.fit(); void invoke("terminal_resize", { cols: terminal.cols, rows: terminal.rows }).catch(() => undefined); });
    observer.observe(host.current);
    return () => { live = false; stop?.(); observer.disconnect(); input.dispose(); terminal.dispose(); };
  }, [cwd, onReady]);
  return <div className="terminal-host" ref={host}/>;
}

export default function App() {
  const [cwd, setCwd] = useState(""); const [path, setPath] = useState("");
  const [terminalOpen, setTerminalOpen] = useState(true); const [auto, setAuto] = useState(false);
  const [busy, setBusy] = useState(false); const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<Message[]>([]); const [tab, setTab] = useState<"files" | "changes">("files"); const [files, setFiles] = useState<ProjectEntry[]>([]);
  const [status, setStatus] = useState("Prêt à travailler"); const [modal, setModal] = useState(false); const [approval, setApproval] = useState<Approval | null>(null); const [sudoPassword, setSudoPassword] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const onTerminalReady = useCallback(() => setStatus("Terminal local prêt"), []);

  useEffect(() => { void invoke<string>("default_workspace").then(value => { setCwd(value); setPath(value); }).catch(() => undefined); }, []);
  useEffect(() => {
    let stop: (() => void) | undefined;
    void listen<string>("agent-event", event => {
      let data: EventPayload; try { data = JSON.parse(event.payload) as EventPayload; } catch { return; }
      if (data.type === "text_delta" && data.delta) setMessages(old => { const next = [...old]; const last = next[next.length - 1]; if (last?.role === "assistant") next[next.length - 1] = { ...last, text: last.text + data.delta }; else next.push({ role: "assistant", text: data.delta ?? "" }); return next; });
      else if (data.type === "approval_required") { setApproval({ kind: "tool", name: data.name ?? "Action", details: JSON.stringify(data.arguments ?? {}, null, 2) }); setStatus("Autorisation requise"); }
      else if (data.type === "sudo_confirmation_required") { setApproval({ kind: "sudo-confirm", name: "Commande privilégiée", details: data.command ?? "" }); setStatus("Confirmation administrateur requise"); }
      else if (data.type === "sudo_password_required") { setApproval({ kind: "sudo-password", name: "Mot de passe sudo requis", details: data.command ?? "" }); setStatus("Authentification administrateur requise"); }
      else if (data.type === "tool_start") setStatus("Exécution : " + (data.name ?? "outil"));
      else if (data.type === "result" || data.type === "process_finished") { setBusy(false); setStatus("Tâche terminée"); }
      else if (data.type === "error" || data.type === "warning") setStatus(data.message ?? "Action à vérifier");
    }).then(fn => stop = fn);
    return () => stop?.();
  }, []);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);
  useEffect(() => { if (!cwd) return; void invoke<ProjectEntry[]>("list_project_files", { cwd }).then(setFiles).catch(() => setFiles([])); }, [cwd]);

  async function browseProject() { const selected = await open({ directory: true, multiple: false, defaultPath: cwd || undefined }); if (typeof selected === "string") setPath(selected); }
  async function openProject() {
    if (!path.trim()) return;
    try { await invoke("terminal_stop"); setCwd(path.trim()); setModal(false); }
    catch (error) { setStatus(String(error)); }
  }
  async function respondApproval(approved: boolean) { if (!approval) return; try { await invoke("agent_respond", { approved, password: approval.kind === "sudo-password" ? sudoPassword : null }); setApproval(null); setSudoPassword(""); setStatus(approved ? "Action autorisée" : "Action refusée"); } catch (error) { setStatus(String(error)); } }
  async function send() {
    const task = prompt.trim(); if (!task || busy || !cwd) return;
    setPrompt(""); setMessages(old => [...old, { role: "user", text: task }, { role: "assistant", text: "" }]);
    setBusy(true); setStatus(auto ? "Agent autonome en cours" : "Analyse en cours");
    try { await invoke("agent_run", { cwd, prompt: task, allowChanges: auto }); }
    catch (error) { setBusy(false); setStatus(String(error)); }
  }

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-icon"><Command size={17}/></div><div><b>ZeroCode</b><small>DESKTOP</small></div><button className="ghost push" title="Barre latérale"><PanelLeftClose size={16}/></button></div>
      <button className="new-task" onClick={() => setMessages([])}><Plus size={16}/> Nouvelle tâche <span>⌘ N</span></button>
      <label className="section">ESPACE DE TRAVAIL</label>
      <button className="nav active" onClick={() => setModal(true)}><FolderOpen size={16}/> Projet actuel</button>
      <button className="nav" onClick={() => setTab("changes")}><GitBranch size={16}/> Modifications</button>
      <label className="section">RÉCENT</label><button className="nav muted"><History size={15}/> Nouvelle session</button>
      <div className="grow"/>
      <div className="local-card"><ShieldCheck size={17}/><div><b>Exécution locale</b><small>Commandes sur cet appareil.</small></div></div>
      <div className="profile"><div className="avatar">H</div><div><b>H@CKERBOY</b><small>ZeroCode Engine</small></div><Settings2 size={16}/></div>
    </aside>
    <main className="work">
      <header className="topbar"><div className="crumb">Projets <span>/</span><button onClick={() => setModal(true)}>{cwd.split("/").filter(Boolean).at(-1) || "Choisir un dossier"} <ChevronDown size={13}/></button></div><div className="top-right"><i/> Moteur local <span className="divider"/><span className="model"><Sparkles size={13}/> Auto · Gratuit</span></div></header>
      <div className="grid">
        <section className="main-col">
          <div className="conversation">{messages.length === 0 ? <motion.div className="welcome" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .55 }}>
            <Lupus/><div className="eyebrow">— TON LABORATOIRE DE CODE —</div><h1>On construit<br/><span>quelque chose de grand.</span></h1>
            <p>Un agent senior, ton environnement, tes fichiers.<br/>Le travail s'effectue directement sur ta machine.</p>
            <div className="suggestions">
              <button onClick={() => setPrompt("Analyse ce projet et identifie les améliorations prioritaires.")}><Activity size={16}/><span><b>Auditer le projet</b><small>Architecture, bugs et sécurité</small></span></button>
              <button onClick={() => setPrompt("Explique-moi la structure de ce projet.")}><FileCode2 size={16}/><span><b>Explorer le code</b><small>Comprendre le dépôt</small></span></button>
              <button onClick={() => setPrompt("Ajoute une fonctionnalité utile et teste-la.")}><Zap size={16}/><span><b>Créer une fonctionnalité</b><small>Implémenter et vérifier</small></span></button>
              <button onClick={() => setTerminalOpen(true)}><SquareTerminal size={16}/><span><b>Ouvrir le terminal</b><small>Shell local intégré</small></span></button>
            </div>
          </motion.div> : <div className="messages">{messages.map((message, index) => <motion.div key={index} className={"message " + message.role} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>{message.role === "assistant" && <div className="bot-avatar"><Bot size={15}/></div>}<div><small>{message.role === "assistant" ? "ZeroCode" : "Vous"}</small><p>{message.text || (busy ? <span className="typing">•••</span> : "")}</p></div></motion.div>)}<div ref={bottom}/></div>}</div>
          <div className="composer-wrap"><div className="composer"><textarea value={prompt} onChange={event => setPrompt(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="Décris ce que tu veux construire…" rows={2}/><div className="composer-bottom"><span className="scope"><Folder size={12}/>{cwd.split("/").filter(Boolean).at(-1) || "Aucun projet"}</span><label className={"toggle " + (auto ? "enabled" : "")}><input type="checkbox" checked={auto} onChange={event => setAuto(event.target.checked)}/><ShieldCheck size={13}/>{auto ? "Autonome activé" : "Mode prudent"}</label><button className="send" disabled={!prompt.trim() || busy || !cwd} onClick={() => void send()}><Send size={15}/></button></div></div><div className="hint">{auto ? "Mode autonome : modifications et commandes autorisées." : "Mode prudent : les actions nécessitant une autorisation sont bloquées."}</div></div>
        </section>
        <aside className="inspector"><div className="tabs"><button className={tab === "files" ? "selected" : ""} onClick={() => setTab("files")}>Fichiers</button><button className={tab === "changes" ? "selected" : ""} onClick={() => setTab("changes")}>Modifications</button></div><div className="file-tree">{tab === "files" && files.length ? files.map(entry => <div className={"file-row " + (entry.is_dir ? "directory" : "")} key={entry.path} style={{ paddingLeft: 8 + (entry.path.split("/").length - 1) * 12 }}>{entry.is_dir ? <Folder size={13}/> : <FileCode2 size={13}/>}<span>{entry.path.split("/").at(-1)}</span></div>) : <div className="empty"><FolderOpen size={21}/><b>{tab === "files" ? "Espace de travail" : "Aucune modification"}</b><small>{tab === "files" ? "Choisis un projet pour explorer ses fichiers." : "Le suivi Git arrive dans la prochaine étape."}</small><button onClick={() => setModal(true)}>Choisir un dossier</button></div>}</div><div className="inspector-foot"><label>ACTIVITÉ</label><div className="activity"><i/>{status}</div><div className="lupus-card"><Lupus small/><div><b>LUPUS veille.</b><small>Observer avant d'agir.</small></div></div></div></aside>
      </div>
      <section className={"terminal " + (!terminalOpen ? "closed" : "")}><div className="terminal-head"><div><SquareTerminal size={14}/><b>Terminal</b><span className="local-tag"><i/> LOCAL</span></div><div className="terminal-controls"><span>{cwd}</span><button onClick={() => setTerminalOpen(false)} title="Réduire"><ArrowDown size={14}/></button><button onClick={() => setTerminalOpen(false)} title="Fermer"><X size={14}/></button></div></div>{cwd && <LocalTerminal cwd={cwd} onReady={onTerminalReady}/>}</section>
    </main>
    <AnimatePresence>{approval && <motion.div className="backdrop approval-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><motion.div className="modal approval-modal" initial={{ opacity: 0, y: 12, scale: .98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8 }}><div className="modal-head"><div><small>AUTORISATION ZEROCode</small><h2>{approval.name}</h2></div><ShieldCheck size={20}/></div><p>Le moteur demande ton accord avant de poursuivre cette opération sur ta machine.</p><pre>{approval.details}</pre>{approval.kind === "sudo-password" && <input className="sudo-input" type="password" autoComplete="current-password" value={sudoPassword} onChange={event => setSudoPassword(event.target.value)} placeholder="Mot de passe sudo"/>}<div className="modal-actions"><button onClick={() => void respondApproval(false)}>Refuser</button><button className="primary" disabled={approval.kind === "sudo-password" && !sudoPassword} onClick={() => void respondApproval(true)}>Autoriser <ArrowUp size={14}/></button></div></motion.div></motion.div>}</AnimatePresence>
    <AnimatePresence>{modal && <motion.div className="backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={event => { if (event.target === event.currentTarget) setModal(false); }}><motion.div className="modal" initial={{ opacity: 0, y: 12, scale: .98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8 }}>
      <div className="modal-head"><div><small>ESPACE DE TRAVAIL</small><h2>Ouvrir un projet</h2></div><button className="ghost" onClick={() => setModal(false)}><X size={17}/></button></div>
      <p>Indique le chemin d'un dossier sur cet ordinateur. Le terminal et l'agent travailleront dans ce répertoire.</p><label>CHEMIN LOCAL</label><div className="path-row"><input value={path} onChange={event => setPath(event.target.value)} onKeyDown={event => { if (event.key === "Enter") void openProject(); }} placeholder="/home/ton-nom/Projects/mon-app"/><button className="browse" onClick={() => void browseProject()}>Parcourir…</button></div>
      <div className="warning"><ShieldCheck size={15}/>Les commandes s'exécutent avec les droits de ton compte utilisateur.</div><div className="modal-actions"><button onClick={() => setModal(false)}>Annuler</button><button className="primary" onClick={() => void openProject()}>Ouvrir le projet <ArrowUp size={14}/></button></div>
    </motion.div></motion.div>}</AnimatePresence>
  </div>;
}