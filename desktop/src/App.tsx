import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, ArrowUpRight, Bot, Check, ChevronDown, CircleHelp, FileCode2, Folder, MessageSquare,
  FolderOpen, GitBranch, History, Menu, MessageSquarePlus, MoreHorizontal,
  PanelRightClose, PanelRightOpen, Plus, Search, Send, Settings2, ShieldCheck,
  Sparkles, SquareTerminal, StopCircle, X
} from "lucide-react";
import { open } from "@tauri-apps/plugin-dialog";
import Lupus from "./components/Lupus";
import TerminalPanel from "./components/TerminalPanel";
import { desktopInvoke, isTauri, listen } from "./lib/desktop";
import type { AgentEvent, ChatMessage, PermissionRequest, SessionSummary, ToolActivity } from "./types";

const starterIdeas = [
  { title: "Comprendre le projet", prompt: "Cartographie ce projet, explique son architecture et repère les priorités." },
  { title: "Corriger un bug", prompt: "Analyse le projet, identifie le bug le plus probable, corrige-le et vérifie le résultat." },
  { title: "Construire une fonctionnalité", prompt: "Étudie les conventions du projet puis implémente une fonctionnalité complète et testée." }
];

const shortPath = (path: string) => path.replace(/\/+$/, "").split(/[\\/]/).filter(Boolean).pop() || path;

function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

function formatCount(value: number) {
  return new Intl.NumberFormat("fr-FR").format(value);
}

export default function App() {
  const [workspace, setWorkspace] = useState<string | null>(() => localStorage.getItem("zerocode.workspace"));
  const [recentProjects, setRecentProjects] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("zerocode.recents") || "[]") as string[]; }
    catch { return []; }
  });
  const [agentId, setAgentId] = useState<string | null>(null);
  const [eventsReady, setEventsReady] = useState(false);
  const agentIdRef = useRef<string | null>(null);
  const pendingAgentEventsRef = useRef<Array<{ agentId: string; event: AgentEvent }>>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activities, setActivities] = useState<ToolActivity[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mode, setMode] = useState("build");
  const [sessionId, setSessionId] = useState("");
  const [model, setModel] = useState("auto");
  const [provider, setProvider] = useState("");
  const [usage, setUsage] = useState(0);
  const [pending, setPending] = useState<PermissionRequest | null>(null);
  const [sudoPassword, setSudoPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [sessionSearch, setSessionSearch] = useState("");
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => { agentIdRef.current = agentId; }, [agentId]);

  useEffect(() => {
    if (!workspace || !isTauri() || !eventsReady) return;
    let cancelled = false;
    setNotice("");
    desktopInvoke<string>("start_agent", { cwd: workspace }).then((id) => {
      if (cancelled) {
        void desktopInvoke("stop_agent", { agentId: id }).catch(() => undefined);
        return;
      }
      agentIdRef.current = id;
      setAgentId(id);
      const queued = pendingAgentEventsRef.current.filter((entry) => entry.agentId === id);
      pendingAgentEventsRef.current = [];
      queued.forEach((entry) => handleAgentEvent(entry.event));
    }).catch((error) => {
      if (!cancelled) setNotice("Agent indisponible : " + String(error));
    });
    return () => {
      cancelled = true;
      const current = agentIdRef.current;
      if (current) void desktopInvoke("stop_agent", { agentId: current }).catch(() => undefined);
      setAgentId(null);
      agentIdRef.current = null;
    };
  }, [workspace, eventsReady]);

  useEffect(() => {
    let unlisten: Array<() => void> = [];
    let alive = true;
    const attach = async () => {
      const routeEvent = (id: string, event: AgentEvent) => {
        if (agentIdRef.current === id) {
          handleAgentEvent(event);
        } else if (!agentIdRef.current) {
          pendingAgentEventsRef.current.push({ agentId: id, event });
        }
      };
      const offAgent = await listen<{ agent_id: string; event: AgentEvent }>("agent-event", (event) => {
        routeEvent(event.payload.agent_id, event.payload.event);
      });
      const offLog = await listen<{ agent_id: string; message: string }>("agent-log", (event) => {
        if (!agentIdRef.current || agentIdRef.current === event.payload.agent_id) {
          setNotice(event.payload.message);
        }
      });
      const offStatus = await listen<{ agent_id: string; status: string }>("agent-status", (event) => {
        if (agentIdRef.current === event.payload.agent_id && event.payload.status === "stopped") {
          setBusy(false);
        }
      });
      if (!alive) {
        offAgent(); offLog(); offStatus();
      } else {
        unlisten = [offAgent, offLog, offStatus];
        setEventsReady(true);
      }
    };
    if (isTauri()) void attach();
    return () => { alive = false; unlisten.forEach((off) => off()); };
  }, []);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, activities]);

  const handleAgentEvent = useCallback((event: AgentEvent) => {
    switch (event.type) {
      case "ready":
        setSessionId(String(event.session_id || ""));
        const restoredMessages = Array.isArray(event.messages) ? event.messages as Array<{role: string; content: string}> : [];
        setMessages(restoredMessages.map((message) => ({
          id: makeId(),
          role: message.role === "user" ? "user" : "assistant",
          content: message.content
        })));
        setSessions(Array.isArray(event.sessions) ? event.sessions as SessionSummary[] : []);
        setModel(String(event.model || "auto"));
        setProvider(String(event.provider || ""));
        setMode("build");
        setNotice("");
        break;
      case "assistant_start":
        setMessages((items) => [...items, { id: makeId(), role: "assistant", content: "" }]);
        break;
      case "text_delta":
        setMessages((items) => {
          const next = [...items];
          const last = next[next.length - 1];
          if (last?.role === "assistant") next[next.length - 1] = { ...last, content: last.content + String(event.delta || "") };
          else next.push({ id: makeId(), role: "assistant", content: String(event.delta || "") });
          return next;
        });
        break;
      case "reasoning_delta":
        break;
      case "tool_start":
        setActivities((items) => [...items.slice(-11), {
          id: makeId(), name: String(event.name || "outil"),
          arguments: (event.arguments || {}) as Record<string, unknown>, status: "running"
        }]);
        break;
      case "tool_result":
        setActivities((items) => {
          const next = [...items];
          const index = [...next].reverse().findIndex((item) => item.name === String(event.name || ""));
          if (index >= 0) {
            const actual = next.length - 1 - index;
            const result = String(event.result || "");
            next[actual] = { ...next[actual], result, status: result.startsWith("ERREUR") || result.includes("exit_code:") && !result.includes("exit_code: 0") ? "error" : "success" };
          }
          return next;
        });
        break;
      case "permission_request":
      case "sudo_confirmation_request":
      case "sudo_password_request":
        setPending({
          request_id: String(event.request_id || ""),
          type: event.type,
          tool: String(event.tool || ""),
          arguments: (event.arguments || {}) as Record<string, unknown>,
          command: String(event.command || "")
        });
        break;
      case "usage":
        setUsage(Number((event.usage as { total_tokens?: number } | undefined)?.total_tokens || 0));
        if (event.model) setModel(String(event.model));
        if (event.provider) setProvider(String(event.provider));
        break;
      case "session_changed": {
        setSessionId(String(event.session_id || ""));
        const restoredMessages = Array.isArray(event.messages) ? event.messages as Array<{role: string; content: string}> : [];
        setMessages(restoredMessages.map((message) => ({
          id: makeId(),
          role: message.role === "user" ? "user" : "assistant",
          content: message.content
        })));
        setSessions(Array.isArray(event.sessions) ? event.sessions as SessionSummary[] : []);
        setActivities([]);
        break;
      }
      case "sessions_changed":
        setSessions(Array.isArray(event.sessions) ? event.sessions as SessionSummary[] : []);
        break;
      case "mode_changed":
        setMode(String(event.mode || "build"));
        break;
      case "warning":
        setNotice(String(event.message || "Attention"));
        break;
      case "error":
        setNotice(String(event.message || "Une erreur est survenue."));
        setBusy(false);
        break;
      case "result":
        if (event.session_id) setSessionId(String(event.session_id));
        break;
      case "turn_started":
        setBusy(true);
        setNotice("");
        break;
      case "turn_complete":
        setBusy(false);
        setPending(null);
        setSudoPassword("");
        break;
      default:
        break;
    }
  }, []);

  const activateWorkspace = useCallback((path: string) => {
    setWorkspace(path);
    localStorage.setItem("zerocode.workspace", path);
    setRecentProjects((items) => {
      const next = [path, ...items.filter((item) => item !== path)].slice(0, 8);
      localStorage.setItem("zerocode.recents", JSON.stringify(next));
      return next;
    });
    setMessages([]);
    setActivities([]);
    setSessionId("");
    setNotice("");
    setSidebarOpen(false);
  }, []);

  const chooseWorkspace = useCallback(async () => {
    if (!isTauri()) {
      setNotice("L’ouverture d’un dossier nécessite l’application native.");
      return;
    }
    const selected = await open({ directory: true, multiple: false, title: "Ouvrir un dossier de projet" });
    if (typeof selected === "string") activateWorkspace(selected);
  }, [activateWorkspace]);

  const sendPrompt = useCallback(async (value?: string) => {
    const text = (value ?? draft).trim();
    if (!text || !agentId || busy || pending) return;
    setMessages((items) => [...items, { id: makeId(), role: "user", content: text }]);
    setDraft("");
    if (composerRef.current) composerRef.current.style.height = "auto";
    setBusy(true);
    try {
      await desktopInvoke("send_agent_message", { agentId, message: { type: "prompt", text } });
    } catch (error) {
      setBusy(false);
      setNotice(String(error));
    }
  }, [agentId, busy, draft, pending]);

  const changeMode = useCallback(async (next: string) => {
    if (!agentId || busy) return;
    setMode(next);
    await desktopInvoke("send_agent_message", { agentId, message: { type: "set_mode", mode: next } }).catch((error) => setNotice(String(error)));
  }, [agentId, busy]);

  const answerPermission = useCallback(async (allowed: boolean) => {
    if (!agentId || !pending) return;
    if (pending.type === "sudo_password_request") {
      await desktopInvoke("send_agent_message", {
        agentId,
        message: { type: "sudo_password_response", request_id: pending.request_id, password: allowed ? sudoPassword : null }
      }).catch((error) => setNotice(String(error)));
    } else {
      const type = pending.type === "sudo_confirmation_request" ? "sudo_confirmation_response" : "permission_response";
      await desktopInvoke("send_agent_message", {
        agentId,
        message: { type, request_id: pending.request_id, allowed }
      }).catch((error) => setNotice(String(error)));
    }
    setPending(null);
    setSudoPassword("");
  }, [agentId, pending, sudoPassword]);

  const interrupt = useCallback(() => {
    if (!agentId) return;
    void desktopInvoke("send_agent_message", { agentId, message: { type: "interrupt" } }).catch(() => undefined);
  }, [agentId]);

  const newSession = useCallback(() => {
    if (!agentId || busy) return;
    setMessages([]);
    setActivities([]);
    setPending(null);
    void desktopInvoke("send_agent_message", { agentId, message: { type: "new_session" } }).catch((error) => setNotice(String(error)));
  }, [agentId, busy]);

  const resumeSession = useCallback(async (id: string) => {
    if (!agentId || busy) return;
    await desktopInvoke("send_agent_message", {
      agentId,
      message: { type: "resume_session", session_id: id }
    }).catch((error) => setNotice(String(error)));
  }, [agentId, busy]);

  const filteredRecents = useMemo(
    () => recentProjects.filter((item) => item.toLowerCase().includes(sessionSearch.toLowerCase())),
    [recentProjects, sessionSearch]
  );

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendPrompt();
    }
  };

  return (
    <div className="app-shell">
      <aside className={"sidebar" + (sidebarOpen ? " sidebar-visible" : "")}>
        <div className="brand-row">
          <Lupus />
          <div className="brand-copy"><strong>ZeroCode</strong><span>DESKTOP</span></div>
          <button className="icon-button mobile-close" onClick={() => setSidebarOpen(false)} aria-label="Fermer le menu"><X size={17} /></button>
        </div>

        <button className="new-task-button" onClick={newSession} disabled={!agentId || busy}>
          <MessageSquarePlus size={16} /> <span>Nouvelle tâche</span> <kbd>⌘ N</kbd>
        </button>

        <nav className="side-nav">
          <button className={searchOpen ? "nav-item active" : "nav-item"} onClick={() => setSearchOpen((value) => !value)}>
            <Search size={16} /><span>Rechercher</span><kbd>⌘ K</kbd>
          </button>
          <button className="nav-item" onClick={chooseWorkspace}>
            <FolderOpen size={16} /><span>Ouvrir un dossier</span>
          </button>
        </nav>

        <div className="sidebar-section">
          <div className="section-label"><span>ESPACES DE TRAVAIL</span><button className="tiny-icon" onClick={chooseWorkspace} title="Ajouter un projet"><Plus size={14} /></button></div>
          {workspace ? (
            <button className="project-item selected" onClick={() => setSidebarOpen(false)}>
              <Folder size={15} /><span>{shortPath(workspace)}</span><i />
            </button>
          ) : <div className="sidebar-empty">Aucun projet ouvert</div>}
          {recentProjects.filter((item) => item !== workspace).map((item) => (
            <button key={item} className="project-item" onClick={() => activateWorkspace(item)}>
              <Folder size={15} /><span>{shortPath(item)}</span>
            </button>
          ))}
        </div>

        {workspace && (
          <div className="sidebar-section conversation-section">
            <div className="section-label"><span>CONVERSATIONS</span><span className="session-count">{sessions.length}</span></div>
            {sessions.length === 0 ? (
              <div className="sidebar-empty">Vos conversations apparaîtront ici</div>
            ) : sessions.map((session) => (
              <button
                key={session.id}
                className={"session-item" + (session.id === sessionId ? " session-selected" : "")}
                onClick={() => void resumeSession(session.id)}
                disabled={busy || session.id === sessionId}
                title={session.title}
              >
                <MessageSquare size={14} />
                <span>{session.title}</span>
              </button>
            ))}
          </div>
        )}

        <div className="sidebar-spacer" />
        <div className="sidebar-footer">
          <div className="local-card"><div className="local-icon"><ShieldCheck size={16} /></div><div><strong>Sur votre machine</strong><span>Fichiers & terminal locaux</span></div><i /></div>
          <button className="nav-item footer-nav"><Settings2 size={16} /><span>Préférences</span></button>
          <div className="profile-row"><div className="profile-avatar">H</div><div><strong>H@CKERBOY</strong><span>Édition locale</span></div><MoreHorizontal size={18} /></div>
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="Ouvrir le menu"><Menu size={18} /></button>
            <div className="breadcrumb"><span>Projet</span><span className="slash">/</span><strong>{workspace ? shortPath(workspace) : "Aucun dossier"}</strong><ChevronDown size={14} /></div>
            <div className="local-pill"><span /> LOCAL</div>
          </div>
          <div className="topbar-right">
            <div className="mode-switch" role="group" aria-label="Mode agent">
              <button className={mode === "build" ? "mode-active" : ""} onClick={() => changeMode("build")} disabled={busy}>Build</button>
              <button className={mode === "plan" ? "mode-active" : ""} onClick={() => changeMode("plan")} disabled={busy}>Plan</button>
              <button className={mode === "full-stack" ? "mode-active" : ""} onClick={() => changeMode("full-stack")} disabled={busy}>Full-stack</button>
            </div>
            <button className="icon-button panel-toggle" onClick={() => setRightOpen((value) => !value)} title="Afficher le contexte">
              {rightOpen ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}
            </button>
          </div>
        </header>

        {notice && <motion.div className="notice-bar" initial={{ opacity: 0, y: -7 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}><CircleHelp size={15} /><span>{notice}</span><button onClick={() => setNotice("")}><X size={14} /></button></motion.div>}

        <div className="workspace-layout">
          <main className="chat-column">
            <div className="chat-scroll" ref={scrollRef}>
              {!workspace ? (
                <motion.div className="welcome-screen" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}>
                  <Lupus size="large" />
                  <p className="eyebrow">VOTRE ENVIRONNEMENT DE DÉVELOPPEMENT</p>
                  <h1>Un agent. Votre machine.<br /><em>Vos règles.</em></h1>
                  <p className="welcome-copy">ZeroCode travaille directement dans vos dossiers et votre terminal. Rien n’est exécuté sur un serveur distant.</p>
                  <button className="primary-button" onClick={chooseWorkspace}><FolderOpen size={17} /> Ouvrir un dossier local</button>
                  <div className="welcome-foot"><ShieldCheck size={14} /> Les commandes restent sur votre ordinateur. Les requêtes au modèle peuvent utiliser un fournisseur distant.</div>
                </motion.div>
              ) : messages.length === 0 ? (
                <motion.div className="empty-chat" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
                  <div className="greeting-row"><Lupus size="large" /><div><span className="eyebrow">LUPUS · LE VEILLEUR</span><h1>Prêt à construire.</h1><p>Le projet <strong>{shortPath(workspace)}</strong> est ouvert sur votre machine.</p></div></div>
                  <div className="suggestion-grid">
                    {starterIdeas.map((idea, index) => (
                      <motion.button key={idea.title} className="suggestion-card" onClick={() => void sendPrompt(idea.prompt)} whileHover={{ y: -3 }} whileTap={{ scale: 0.985 }} transition={{ duration: 0.18 }}>
                        <span className="suggestion-icon">{index === 0 ? <FileCode2 size={17} /> : index === 1 ? <Activity size={17} /> : <Sparkles size={17} />}</span>
                        <strong>{idea.title}</strong><p>{idea.prompt}</p><ArrowUpRight />
                      </motion.button>
                    ))}
                  </div>
                </motion.div>
              ) : (
                <div className="conversation">
                  {messages.map((message) => (
                    <motion.article key={message.id} className={"message message-" + message.role} initial={{ opacity: 0, y: 9 }} animate={{ opacity: 1, y: 0 }}>
                      {message.role === "assistant" && <div className="message-avatar"><Lupus /></div>}
                      <div className="message-content">
                        <div className="message-meta">{message.role === "user" ? "Vous" : "ZeroCode"} <span>{message.role === "assistant" ? "· agent local" : ""}</span></div>
                        <div className="message-text">{message.content || (busy && message.role === "assistant" ? <span className="typing-cursor" /> : "")}</div>
                      </div>
                    </motion.article>
                  ))}
                  {activities.length > 0 && (
                    <div className="activity-inline">
                      {activities.slice(-4).map((item) => (
                        <div className={"activity-chip activity-" + item.status} key={item.id}>
                          {item.status === "running" ? <span className="mini-spinner" /> : item.status === "success" ? <Check size={13} /> : <X size={13} />}
                          <strong>{item.name}</strong>
                          <span>{item.status === "running" ? "en cours" : item.status === "success" ? "terminé" : "à vérifier"}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {pending && (
              <AnimatePresence>
                <motion.div className="permission-card" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 10 }}>
                  <div className="permission-heading"><ShieldCheck size={18} /><div><strong>{pending.type === "sudo_password_request" ? "Authentification système" : "Autorisation requise"}</strong><span>{pending.tool || pending.command || "ZeroCode souhaite effectuer une action."}</span></div></div>
                  {pending.type === "sudo_password_request" ? (
                    <form className="sudo-form" onSubmit={(event) => { event.preventDefault(); void answerPermission(true); }}>
                      <input type="password" value={sudoPassword} onChange={(event) => setSudoPassword(event.target.value)} placeholder="Mot de passe sudo" autoComplete="current-password" />
                      <button className="primary-button small" type="submit" disabled={!sudoPassword}>Envoyer</button>
                      <button className="text-button" type="button" onClick={() => void answerPermission(false)}>Annuler</button>
                    </form>
                  ) : (
                    <div className="permission-actions"><button className="text-button" onClick={() => void answerPermission(false)}>Refuser</button><button className="primary-button small" onClick={() => void answerPermission(true)}><Check size={14} /> Autoriser</button></div>
                  )}
                  {pending.arguments && <pre className="permission-preview">{JSON.stringify(pending.arguments, null, 2)}</pre>}
                  {pending.command && <pre className="permission-preview">{pending.command}</pre>}
                </motion.div>
              </AnimatePresence>
            )}

            <div className="composer-wrap">
              <div className="composer">
                <textarea
                  ref={composerRef}
                  value={draft}
                  onChange={(event) => {
                    setDraft(event.target.value);
                    event.target.style.height = "auto";
                    event.target.style.height = Math.min(event.target.scrollHeight, 160) + "px";
                  }}
                  onKeyDown={onComposerKeyDown}
                  placeholder={workspace ? "Décrivez ce que vous souhaitez construire…" : "Ouvrez un dossier pour commencer…"}
                  rows={1}
                  disabled={!workspace || !agentId || busy || Boolean(pending)}
                />
                <div className="composer-bottom">
                  <div className="composer-tools">
                    <span className="composer-context"><Folder size={13} /> {workspace ? shortPath(workspace) : "Aucun contexte"}</span>
                    <span className="model-indicator"><Bot size={13} /> {model}{provider ? " · " + provider : ""}</span>
                  </div>
                  <div className="composer-actions">
                    {busy && <button className="stop-button" onClick={interrupt}><StopCircle size={15} /> Arrêter</button>}
                    <button className="send-button" onClick={() => void sendPrompt()} disabled={!draft.trim() || !agentId || busy || Boolean(pending)} title="Envoyer">
                      {busy ? <span className="mini-spinner" /> : <Send size={16} />}
                    </button>
                  </div>
                </div>
              </div>
              <div className="composer-hint"><span>Entrée pour envoyer</span><span>Maj + Entrée pour une nouvelle ligne</span><span className="hint-secure"><ShieldCheck size={12} /> Exécution locale</span></div>
            </div>

            <TerminalPanel cwd={workspace} open={terminalOpen} onToggle={() => setTerminalOpen((value) => !value)} />
          </main>

          <AnimatePresence initial={false}>
            {rightOpen && (
              <motion.aside className="context-panel" initial={{ width: 0, opacity: 0 }} animate={{ width: 276, opacity: 1 }} exit={{ width: 0, opacity: 0 }} transition={{ duration: 0.22, ease: "easeOut" }}>
                <div className="context-head"><span>CONTEXTE</span><button className="icon-button" onClick={() => setRightOpen(false)}><X size={15} /></button></div>
                <div className="context-section">
                  <div className="context-label">ENVIRONNEMENT</div>
                  <div className="context-project"><div className="context-folder"><Folder size={17} /></div><div><strong>{workspace ? shortPath(workspace) : "Aucun projet"}</strong><span>{workspace || "Sélectionnez un dossier"}</span></div></div>
                  <div className="context-line"><span>Exécution</span><strong><i className="status-live" /> locale</strong></div>
                  <div className="context-line"><span>Terminal</span><strong>PTY natif</strong></div>
                </div>
                <div className="context-section">
                  <div className="context-label">AGENT</div>
                  <div className="agent-status"><div className="agent-status-icon"><Bot size={17} /></div><div><strong>{busy ? "Travail en cours" : agentId ? "Prêt" : "En attente"}</strong><span>{mode === "full-stack" ? "Autonomie Full-stack" : mode === "plan" ? "Lecture seule" : "Construction"}</span></div><i className={busy ? "status-live pulse" : "status-live"} /></div>
                  <div className="context-line"><span>Modèle</span><strong>{model}</strong></div>
                  <div className="context-line"><span>Fournisseur</span><strong>{provider || "Auto"}</strong></div>
                  <div className="context-line"><span>Jetons</span><strong>{formatCount(usage)}</strong></div>
                </div>
                <div className="context-section">
                  <div className="context-label">ACTIVITÉ RÉCENTE <span>{activities.length}</span></div>
                  {activities.length === 0 ? <p className="context-empty">Les appels d’outils et les modifications apparaîtront ici.</p> : (
                    <div className="activity-list">
                      {[...activities].reverse().slice(0, 8).map((item) => (
                        <div className="activity-item" key={item.id}>
                          <span className={"activity-mark " + item.status}>{item.status === "running" ? "·" : item.status === "success" ? "✓" : "!"}</span>
                          <div><strong>{item.name}</strong><span>{item.result ? item.result.split("\n")[0].slice(0, 72) : "Exécution…"}</span></div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="context-bottom"><ShieldCheck size={14} /><span>Les modifications nécessitent une autorisation selon le mode choisi.</span></div>
              </motion.aside>
            )}
          </AnimatePresence>
        </div>
        <footer className="statusbar">
          <div><span className="status-live" /> {agentId ? "Connecté à ZeroCode" : workspace ? "Connexion à l’agent…" : "Aucun dossier ouvert"}</div>
          <div><GitBranch size={12} /> local <span className="status-separator">·</span> <History size={12} /> {sessionId ? sessionId.slice(0, 12) : "nouvelle session"}</div>
          <div><ShieldCheck size={12} /> Fichiers et commandes sur cet appareil</div>
        </footer>
      </div>

      {sidebarOpen && <button className="mobile-scrim" onClick={() => setSidebarOpen(false)} aria-label="Fermer le menu" />}
      {searchOpen && (
        <div className="search-overlay" onClick={() => setSearchOpen(false)}>
          <motion.div className="search-dialog" onClick={(event) => event.stopPropagation()} initial={{ opacity: 0, y: -12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}>
            <Search size={17} /><input autoFocus placeholder="Rechercher un espace de travail…" value={sessionSearch} onChange={(event) => setSessionSearch(event.target.value)} />
            <kbd>Échap</kbd>
            {filteredRecents.map((item) => <button key={item} onClick={() => { activateWorkspace(item); setSearchOpen(false); }}><Folder size={15} /> {shortPath(item)} <span>{item}</span></button>)}
          </motion.div>
        </div>
      )}
    </div>
  );
}
