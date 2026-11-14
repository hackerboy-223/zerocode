import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, ArrowLeft, ArrowUpRight, Bot, Brain, Check, ChevronDown, ChevronRight,
  CircleHelp, Code2, Copy, FileCode2, FileDiff, FileText, Folder, FolderOpen, GitBranch,
  History, ListTodo, Menu, MessageSquare, MessageSquarePlus, MoreHorizontal,
  PanelRightClose, PanelRightOpen, Plus, RefreshCw, RotateCcw, Search, Send,
  Settings2, ShieldCheck, Sparkles, StopCircle, Trash2, X
} from "lucide-react";
import { open } from "@tauri-apps/plugin-dialog";
import Lupus from "./components/Lupus";
import TerminalPanel from "./components/TerminalPanel";
import { desktopInvoke, isTauri, listen } from "./lib/desktop";
import type {
  AgentEvent,
  ChatMessage,
  DiffEntry,
  GitWorkspaceInfo,
  PermissionRequest,
  SessionSummary,
  TodoItem,
  ToolActivity,
  WorkspaceEntry,
  WorkspaceFilePreview
} from "./types";

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

function formatBytes(size: number) {
  if (size < 1024) return `${size} o`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} Ko`;
  return `${(size / (1024 * 1024)).toFixed(1)} Mo`;
}

function renderInlineMarkdown(text: string): ReactNode[] {
  const token = /(`[^`\n]+`|\*\*[^*]+\*\*|__[^_]+__|~~[^~]+~~|\*[^*\n]+\*|_[^_\n]+_|\[[^\]]+\]\(https?:\/\/[^\s)]+\))/g;
  return text.split(token).filter(Boolean).map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index} className="inline-code">{part.slice(1, -1)}</code>;
    }
    if ((part.startsWith("**") && part.endsWith("**")) || (part.startsWith("__") && part.endsWith("__"))) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("~~") && part.endsWith("~~")) {
      return <del key={index}>{part.slice(2, -2)}</del>;
    }
    if ((part.startsWith("*") && part.endsWith("*")) || (part.startsWith("_") && part.endsWith("_"))) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
    if (link) return <a key={index} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    return part;
  });
}

function FormattedMessage({ content, onCopy }: { content: string; onCopy: (text: string) => void }) {
  const rendered = useMemo(() => {
    const lines = content.replace(/\r\n/g, "\n").split("\n");
    const nodes: ReactNode[] = [];
    let i = 0;
    let key = 0;
    const isTableDivider = (line: string) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
    const isBlockStart = (line: string) => /^\s*(```|#{1,6}\s|>\s?|[-*+]\s|\d+[.)]\s|\|)/.test(line) || /^\s*([-*_]\s*){3,}$/.test(line);

    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }

      const fence = line.match(/^\s*```([\w+-]*)\s*$/);
      if (fence) {
        const lang = fence[1] || "code";
        const code: string[] = [];
        i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) code.push(lines[i++]);
        if (i < lines.length) i++;
        const value = code.join("\n");
        nodes.push(
          <div key={key++} className="code-block">
            <div className="code-block-header"><span>{lang}</span><button type="button" className="code-copy-btn" onClick={() => onCopy(value)} title="Copier le code"><Copy size={12} /> Copier</button></div>
            <pre><code>{value}</code></pre>
          </div>
        );
        continue;
      }

      const heading = line.match(/^\s*(#{1,6})\s+(.+)$/);
      if (heading) {
        const level = heading[1].length;
        const Heading = (["h1", "h2", "h3", "h4", "h5", "h6"] as const)[level - 1];
        nodes.push(<Heading key={key++} className="markdown-heading">{renderInlineMarkdown(heading[2])}</Heading>);
        i++;
        continue;
      }

      if (/^\s*([-*_]\s*){3,}$/.test(line)) {
        nodes.push(<hr key={key++} className="markdown-rule" />);
        i++;
        continue;
      }

      if (line.includes("|") && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
        const cells = (value: string) => value.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
        const headers = cells(line);
        i += 2;
        const rows: string[][] = [];
        while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
        nodes.push(<div key={key++} className="markdown-table-wrap"><table className="markdown-table"><thead><tr>{headers.map((cell, n) => <th key={n}>{renderInlineMarkdown(cell)}</th>)}</tr></thead><tbody>{rows.map((row, n) => <tr key={n}>{headers.map((_, col) => <td key={col}>{renderInlineMarkdown(row[col] || "")}</td>)}</tr>)}</tbody></table></div>);
        continue;
      }

      if (/^\s*>/.test(line)) {
        const quote: string[] = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ""));
        nodes.push(<blockquote key={key++}>{renderInlineMarkdown(quote.join(" "))}</blockquote>);
        continue;
      }

      if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
        const ordered = /^\s*\d+[.)]\s+/.test(line);
        const items: string[] = [];
        const pattern = ordered ? /^\s*\d+[.)]\s+/ : /^\s*[-*+]\s+/;
        while (i < lines.length && pattern.test(lines[i])) items.push(lines[i++].replace(pattern, ""));
        const List = ordered ? "ol" : "ul";
        nodes.push(<List key={key++} className="markdown-list">{items.map((item, n) => <li key={n}>{renderInlineMarkdown(item)}</li>)}</List>);
        continue;
      }

      const paragraph = [line];
      i++;
      while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) paragraph.push(lines[i++]);
      nodes.push(<p key={key++} className="markdown-paragraph">{paragraph.map((part, n) => <span key={n}>{n > 0 && <br />}{renderInlineMarkdown(part)}</span>)}</p>);
    }
    return nodes;
  }, [content, onCopy]);

  return <div className="formatted-body">{rendered}</div>;
}

export default function App() {
  const [workspace, setWorkspace] = useState<string | null>(() => localStorage.getItem("zerocode.workspace"));
  const [recentProjects, setRecentProjects] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("zerocode.recents") || "[]") as string[]; }
    catch { return []; }
  });
  const [agentId, setAgentId] = useState<string | null>(null);
  const [agentReady, setAgentReady] = useState(false);
  const [eventsReady, setEventsReady] = useState(false);
  const agentIdRef = useRef<string | null>(null);
  const pendingAgentEventsRef = useRef<Array<{ agentId: string; event: AgentEvent }>>([]);
  const pendingAgentStatusesRef = useRef<Array<{ agentId: string; status: string }>>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activities, setActivities] = useState<ToolActivity[]>([]);
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [diffs, setDiffs] = useState<DiffEntry[]>([]);
  const [checkpoints, setCheckpoints] = useState(0);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [contextTab, setContextTab] = useState<"overview" | "files" | "diffs">("overview");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mode, setMode] = useState("build");
  const [permissionsMode, setPermissionsMode] = useState("ask");
  const [thinkMode, setThinkMode] = useState("off");
  const [availableModels, setAvailableModels] = useState<string[]>(["auto"]);
  const [sessionId, setSessionId] = useState("");
  const [model, setModel] = useState("auto");
  const [provider, setProvider] = useState("");
  const [usage, setUsage] = useState(0);
  const [pending, setPending] = useState<PermissionRequest | null>(null);
  const [sudoPassword, setSudoPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => localStorage.getItem("zerocode.theme") === "dark" ? "dark" : "light");

  useEffect(() => { localStorage.setItem("zerocode.theme", theme); }, [theme]);
  const [customModelInput, setCustomModelInput] = useState("");
  const [sessionSearch, setSessionSearch] = useState("");
  const [expandedActivityId, setExpandedActivityId] = useState<string | null>(null);

  // Workspace File Explorer & Git state
  const [currentDir, setCurrentDir] = useState("");
  const [fileFilter, setFileFilter] = useState("");
  const [workspaceFiles, setWorkspaceFiles] = useState<WorkspaceEntry[]>([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [previewFile, setPreviewFile] = useState<WorkspaceFilePreview | null>(null);
  const [gitInfo, setGitInfo] = useState<GitWorkspaceInfo>({
    is_repo: false,
    branch: "local",
    dirty_count: 0,
    changed_files: []
  });

  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => { agentIdRef.current = agentId; }, [agentId]);

  const refreshGitInfo = useCallback(async (cwdPath?: string | null) => {
    const target = cwdPath ?? workspace;
    if (!target || !isTauri()) return;
    try {
      const info = await desktopInvoke<GitWorkspaceInfo>("workspace_git_info", { cwd: target });
      setGitInfo(info);
    } catch {
      // Ignore git errors silently
    }
  }, [workspace]);

  const loadDirectory = useCallback(async (dirPath: string, cwdPath?: string | null) => {
    const target = cwdPath ?? workspace;
    if (!target || !isTauri()) return;
    setFilesLoading(true);
    try {
      const entries = await desktopInvoke<WorkspaceEntry[]>("list_workspace_files", {
        cwd: target,
        relativeDir: dirPath
      });
      setWorkspaceFiles(entries);
      setCurrentDir(dirPath);
    } catch (error) {
      setNotice(String(error));
    } finally {
      setFilesLoading(false);
    }
  }, [workspace]);

  const openFilePreview = useCallback(async (relativePath: string) => {
    if (!workspace || !isTauri()) return;
    try {
      const preview = await desktopInvoke<WorkspaceFilePreview>("read_workspace_file", {
        cwd: workspace,
        relativePath
      });
      setPreviewFile(preview);
    } catch (error) {
      setNotice(String(error));
    }
  }, [workspace]);

  const copyText = useCallback((text: string) => {
    void navigator.clipboard?.writeText(text);
    setNotice("Copié dans le presse-papiers.");
  }, []);

  useEffect(() => {
    if (!workspace || !isTauri()) return;
    void refreshGitInfo(workspace);
    void loadDirectory("", workspace);
  }, [workspace, refreshGitInfo, loadDirectory]);

  useEffect(() => {
    if (!workspace || !isTauri() || !eventsReady) return;
    let cancelled = false;
    setNotice("");
    setAgentReady(false);
    pendingAgentStatusesRef.current = [];
    desktopInvoke<string>("start_agent", { cwd: workspace }).then((id) => {
      if (cancelled) {
        void desktopInvoke("stop_agent", { agentId: id }).catch(() => undefined);
        return;
      }
      agentIdRef.current = id;
      setAgentId(id);
      const stoppedBeforeRegistration = pendingAgentStatusesRef.current.some(
        (entry) => entry.agentId === id && entry.status === "stopped"
      );
      pendingAgentStatusesRef.current = pendingAgentStatusesRef.current.filter((entry) => entry.agentId !== id);
      const queued = pendingAgentEventsRef.current.filter((entry) => entry.agentId === id);
      pendingAgentEventsRef.current = [];
      queued.forEach((entry) => handleAgentEvent(entry.event));
      if (stoppedBeforeRegistration) {
        setAgentReady(false);
        setBusy(false);
        setPending(null);
        setNotice("Le processus ZeroCode s’est arrêté avant d’être prêt. Vérifiez le diagnostic de l’agent.");
      }
    }).catch((error) => {
      if (!cancelled) setNotice("Agent indisponible : " + String(error));
    });
    return () => {
      cancelled = true;
      const current = agentIdRef.current;
      if (current) void desktopInvoke("stop_agent", { agentId: current }).catch(() => undefined);
      setAgentId(null);
      setAgentReady(false);
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
        const { agent_id: id, status } = event.payload;
        if (agentIdRef.current === id && status === "stopped") {
          setAgentReady(false);
          setBusy(false);
          setPending(null);
          setNotice("Le processus ZeroCode s’est arrêté. Relancez l’application ou rouvrez le projet.");
        } else if (!agentIdRef.current) {
          pendingAgentStatusesRef.current.push({ agentId: id, status });
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
      case "ready": {
        setAgentReady(true);
        setSessionId(String(event.session_id || ""));
        const restoredMessages = Array.isArray(event.messages) ? event.messages as Array<{ role: string; content: string }> : [];
        setMessages(restoredMessages.map((message) => ({
          id: makeId(),
          role: message.role === "user" ? "user" : "assistant",
          content: message.content
        })));
        setSessions(Array.isArray(event.sessions) ? event.sessions as SessionSummary[] : []);
        setTodos(Array.isArray(event.todos) ? event.todos as TodoItem[] : []);
        setCheckpoints(Number(event.checkpoints || 0));
        if (Array.isArray(event.models) && event.models.length > 0) {
          setAvailableModels(event.models.map((item) => String(item)));
        }
        setModel(String(event.model || "auto"));
        setProvider(String(event.provider || ""));
        setMode(String(event.mode || "build"));
        setPermissionsMode(String(event.permissions || "ask"));
        setThinkMode(String(event.think || "off"));
        setNotice("");
        break;
      }
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
        setMessages((items) => {
          const next = [...items];
          const last = next[next.length - 1];
          const delta = String(event.delta || "");
          if (last?.role === "assistant") {
            next[next.length - 1] = { ...last, reasoning: (last.reasoning || "") + delta };
          } else {
            next.push({ id: makeId(), role: "assistant", content: "", reasoning: delta });
          }
          return next;
        });
        break;
      case "tool_start":
        setActivities((items) => [...items.slice(-15), {
          id: makeId(),
          name: String(event.name || "outil"),
          arguments: (event.arguments || {}) as Record<string, unknown>,
          status: "running"
        }]);
        break;
      case "tool_output":
        setActivities((items) => {
          const next = [...items];
          const index = [...next].reverse().findIndex((item) => item.name === String(event.name || "") && item.status === "running");
          if (index >= 0) {
            const actual = next.length - 1 - index;
            const prevOut = next[actual].output || "";
            next[actual] = { ...next[actual], output: (prevOut + String(event.chunk || "")).slice(-4000) };
          }
          return next;
        });
        break;
      case "tool_result":
        setActivities((items) => {
          const next = [...items];
          const index = [...next].reverse().findIndex((item) => item.name === String(event.name || ""));
          if (index >= 0) {
            const actual = next.length - 1 - index;
            const result = String(event.result || "");
            next[actual] = {
              ...next[actual],
              result,
              status: result.startsWith("ERREUR") || (result.includes("exit_code:") && !result.includes("exit_code: 0")) ? "error" : "success"
            };
          }
          return next;
        });
        void refreshGitInfo();
        break;
      case "diff":
        setDiffs((items) => [
          {
            id: makeId(),
            path: String(event.path || "fichier"),
            diff: String(event.diff || "")
          },
          ...items.slice(0, 19)
        ]);
        break;
      case "todos":
        setTodos(Array.isArray(event.todos) ? event.todos as TodoItem[] : []);
        break;
      case "checkpoints_changed":
        setCheckpoints(Number(event.checkpoints || 0));
        break;
      case "checkpoint_restored":
        setCheckpoints(Number(event.checkpoints || 0));
        setNotice(String(event.message || "Modification annulée."));
        void refreshGitInfo();
        void loadDirectory(currentDir);
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
        setAgentReady(true);
        setSessionId(String(event.session_id || ""));
        const restoredMessages = Array.isArray(event.messages) ? event.messages as Array<{ role: string; content: string }> : [];
        setMessages(restoredMessages.map((message) => ({
          id: makeId(),
          role: message.role === "user" ? "user" : "assistant",
          content: message.content
        })));
        setSessions(Array.isArray(event.sessions) ? event.sessions as SessionSummary[] : []);
        setTodos(Array.isArray(event.todos) ? event.todos as TodoItem[] : []);
        setCheckpoints(Number(event.checkpoints || 0));
        if (event.model) setModel(String(event.model));
        if (event.provider !== undefined) setProvider(String(event.provider || ""));
        setActivities([]);
        setDiffs([]);
        break;
      }
      case "sessions_changed":
        setSessions(Array.isArray(event.sessions) ? event.sessions as SessionSummary[] : []);
        break;
      case "mode_changed":
        setMode(String(event.mode || "build"));
        if (event.permissions) setPermissionsMode(String(event.permissions));
        if (event.think) setThinkMode(String(event.think));
        break;
      case "config_changed":
        if (event.model) setModel(String(event.model));
        if (event.provider !== undefined) setProvider(String(event.provider || ""));
        if (event.permissions) setPermissionsMode(String(event.permissions));
        if (event.think) setThinkMode(String(event.think));
        break;
      case "info":
      case "success":
      case "warning":
        setNotice(String(event.message || "Information"));
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
        void refreshGitInfo();
        void loadDirectory(currentDir);
        break;
      default:
        break;
    }
  }, [currentDir, loadDirectory, refreshGitInfo]);

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
    setTodos([]);
    setDiffs([]);
    setCheckpoints(0);
    setPreviewFile(null);
    setCurrentDir("");
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
    if (!text || !agentId || !agentReady || busy || pending) return;
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
  }, [agentId, agentReady, busy, draft, pending]);

  const changeMode = useCallback(async (next: string) => {
    if (!agentId || !agentReady || busy) return;
    if (next === "full-stack" && !window.confirm(
      "Full-stack autorise ZeroCode à modifier le projet et à lancer des commandes avec les droits de votre compte. Les actions sudo et les intégrations externes restent soumises à confirmation. Continuer ?"
    )) return;
    setMode(next);
    await desktopInvoke("send_agent_message", { agentId, message: { type: "set_mode", mode: next } }).catch((error) => setNotice(String(error)));
  }, [agentId, agentReady, busy]);

  const changeModel = useCallback(async (nextModel: string) => {
    const cleaned = nextModel.trim();
    if (!cleaned || !agentId || !agentReady || busy) return;
    await desktopInvoke("send_agent_message", {
      agentId,
      message: { type: "set_model", model: cleaned }
    }).catch((error) => setNotice(String(error)));
  }, [agentId, agentReady, busy]);

  const changePermissions = useCallback(async (nextPerm: string) => {
    if (!agentId || !agentReady || busy) return;
    if (nextPerm === "allow" && !window.confirm(
      "Le mode autonome autorise les modifications et les commandes ordinaires sans confirmation. Il utilise les droits de votre compte système. Continuer ?"
    )) return;
    setPermissionsMode(nextPerm);
    await desktopInvoke("send_agent_message", {
      agentId,
      message: { type: "set_permissions", permissions: nextPerm }
    }).catch((error) => setNotice(String(error)));
  }, [agentId, agentReady, busy]);

  const changeThink = useCallback(async (nextThink: string) => {
    if (!agentId || !agentReady || busy) return;
    setThinkMode(nextThink);
    await desktopInvoke("send_agent_message", {
      agentId,
      message: { type: "set_think", think: nextThink }
    }).catch((error) => setNotice(String(error)));
  }, [agentId, agentReady, busy]);

  const undoCheckpoint = useCallback(async () => {
    if (!agentId || !agentReady || busy || checkpoints <= 0) return;
    await desktopInvoke("send_agent_message", {
      agentId,
      message: { type: "undo_checkpoint" }
    }).catch((error) => setNotice(String(error)));
  }, [agentId, agentReady, busy, checkpoints]);

  const compactContext = useCallback(async () => {
    if (!agentId || !agentReady || busy) return;
    await desktopInvoke("send_agent_message", {
      agentId,
      message: { type: "compact_context" }
    }).catch((error) => setNotice(String(error)));
    setSettingsOpen(false);
  }, [agentId, agentReady, busy]);

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
    if (!agentId || !agentReady || busy) return;
    setMessages([]);
    setActivities([]);
    setTodos([]);
    setDiffs([]);
    setPending(null);
    void desktopInvoke("send_agent_message", { agentId, message: { type: "new_session" } }).catch((error) => setNotice(String(error)));
  }, [agentId, agentReady, busy]);

  const resumeSession = useCallback(async (id: string) => {
    if (!agentId || !agentReady || busy) return;
    await desktopInvoke("send_agent_message", {
      agentId,
      message: { type: "resume_session", session_id: id }
    }).catch((error) => setNotice(String(error)));
  }, [agentId, agentReady, busy]);

  const deleteSession = useCallback(async (id: string) => {
    if (!agentId || !agentReady || busy) return;
    await desktopInvoke("send_agent_message", {
      agentId,
      message: { type: "delete_session", session_id: id }
    }).catch((error) => setNotice(String(error)));
  }, [agentId, agentReady, busy]);

  const mentionFileInDraft = useCallback((relativePath: string) => {
    setDraft((prev) => {
      const prefix = prev.trim() ? `${prev.trimEnd()} ` : "";
      return `${prefix}@${relativePath} `;
    });
    setPreviewFile(null);
    composerRef.current?.focus();
  }, []);

  useEffect(() => {
    const onShortcut = (event: globalThis.KeyboardEvent) => {
      const modifier = event.metaKey || event.ctrlKey;
      if (modifier && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((prev) => !prev);
      } else if (modifier && event.key.toLowerCase() === "n") {
        event.preventDefault();
        newSession();
      } else if (modifier && event.key === ",") {
        event.preventDefault();
        setSettingsOpen((prev) => !prev);
      } else if (modifier && event.key === "`") {
        event.preventDefault();
        setTerminalOpen((prev) => !prev);
      } else if (event.key === "Escape") {
        setSearchOpen(false);
        setSettingsOpen(false);
        setPreviewFile(null);
      }
    };
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, [newSession]);

  const filteredRecents = useMemo(
    () => recentProjects.filter((item) => item.toLowerCase().includes(sessionSearch.toLowerCase())),
    [recentProjects, sessionSearch]
  );

  const filteredSessions = useMemo(
    () => sessions.filter((item) => item.title.toLowerCase().includes(sessionSearch.toLowerCase())),
    [sessions, sessionSearch]
  );

  const filteredFiles = useMemo(
    () => workspaceFiles.filter((item) => item.name.toLowerCase().includes(fileFilter.toLowerCase())),
    [workspaceFiles, fileFilter]
  );

  const completedTodosCount = useMemo(
    () => todos.filter((item) => item.status === "completed").length,
    [todos]
  );

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendPrompt();
    }
  };

  const navigateParentDir = () => {
    if (!currentDir) return;
    const parts = currentDir.split("/").filter(Boolean);
    parts.pop();
    void loadDirectory(parts.join("/"));
  };

  return (
    <div className={"app-shell theme-" + theme}>
      <aside className={"sidebar" + (sidebarOpen ? " sidebar-visible" : "")}>
        <div className="brand-row">
          <Lupus />
          <div className="brand-copy"><strong>ZeroCode</strong><span>DESKTOP</span></div>
          <button className="icon-button mobile-close" onClick={() => setSidebarOpen(false)} aria-label="Fermer le menu"><X size={17} /></button>
        </div>

        <button className="new-task-button" onClick={newSession} disabled={!agentId || !agentReady || busy}>
          <MessageSquarePlus size={16} /> <span>Nouvelle tâche</span> <kbd>Ctrl N</kbd>
        </button>

        <nav className="side-nav">
          <button className={searchOpen ? "nav-item active" : "nav-item"} onClick={() => setSearchOpen((value) => !value)}>
            <Search size={16} /><span>Palette & Recherche</span><kbd>Ctrl K</kbd>
          </button>
          <button className="nav-item" onClick={chooseWorkspace}>
            <FolderOpen size={16} /><span>Ouvrir un dossier</span>
          </button>
        </nav>

        <div className="sidebar-section">
          <div className="section-label"><span>ESPACES DE TRAVAIL</span><button className="tiny-icon" onClick={chooseWorkspace} title="Ajouter un projet"><Plus size={14} /></button></div>
          {workspace ? (
            <button className="project-item selected" onClick={() => setSidebarOpen(false)} title={workspace}>
              <Folder size={15} /><span>{shortPath(workspace)}</span><i />
            </button>
          ) : <div className="sidebar-empty">Aucun projet ouvert</div>}
          {recentProjects.filter((item) => item !== workspace).map((item) => (
            <button key={item} className="project-item" onClick={() => activateWorkspace(item)} title={item}>
              <Folder size={15} /><span>{shortPath(item)}</span>
            </button>
          ))}
        </div>

        {workspace && (
          <div className="sidebar-section conversation-section">
            <div className="section-label"><span>CONVERSATIONS</span><span className="session-count">{sessions.length}</span></div>
            {sessions.length === 0 ? (
              <div className="sidebar-empty">Vos conversations apparaîtront ici</div>
            ) : (
              <div className="session-list">
                {sessions.map((session) => (
                  <div
                    key={session.id}
                    className={"session-row" + (session.id === sessionId ? " session-selected" : "")}
                  >
                    <button
                      className="session-item"
                      onClick={() => void resumeSession(session.id)}
                      disabled={busy || session.id === sessionId}
                      title={session.title}
                    >
                      <MessageSquare size={14} />
                      <span>{session.title}</span>
                    </button>
                    <button
                      className="session-delete"
                      onClick={() => void deleteSession(session.id)}
                      disabled={busy}
                      title="Supprimer cette conversation"
                      aria-label="Supprimer cette conversation"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="sidebar-spacer" />
        <div className="sidebar-footer">
          <div className="local-card"><div className="local-icon"><ShieldCheck size={16} /></div><div><strong>Sur votre machine</strong><span>Fichiers & terminal locaux</span></div><i /></div>
          <button className={settingsOpen ? "nav-item footer-nav active" : "nav-item footer-nav"} onClick={() => setSettingsOpen(true)}>
            <Settings2 size={16} /><span>Préférences</span><kbd>Ctrl ,</kbd>
          </button>
          <div className="profile-row"><div className="profile-avatar">H</div><div><strong>H@CKERBOY</strong><span>Édition locale</span></div><MoreHorizontal size={18} /></div>
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button mobile-menu" onClick={() => setSidebarOpen(true)} aria-label="Ouvrir le menu"><Menu size={18} /></button>
            <button className="breadcrumb breadcrumb-button" onClick={chooseWorkspace} title={workspace || "Choisir un dossier de projet"}>
              <span>Projet</span><span className="slash">/</span><strong>{workspace ? shortPath(workspace) : "Aucun dossier"}</strong><ChevronDown size={14} />
            </button>
            <div className="local-pill"><span /> LOCAL</div>
            {gitInfo.is_repo && (
              <div className="git-pill" title={`${gitInfo.dirty_count} fichier(s) modifié(s)`}>
                <GitBranch size={12} />
                <span>{gitInfo.branch}</span>
                {gitInfo.dirty_count > 0 && <em>{gitInfo.dirty_count}</em>}
              </div>
            )}
          </div>
          <div className="topbar-right">
            {checkpoints > 0 && (
              <button
                className="undo-pill"
                onClick={() => void undoCheckpoint()}
                disabled={busy}
                title="Annuler la dernière modification de fichier (Checkpoint)"
              >
                <RotateCcw size={13} />
                <span>Annuler ({checkpoints})</span>
              </button>
            )}
            <div className="mode-switch" role="group" aria-label="Mode agent">
              <button className={mode === "build" ? "mode-active" : ""} onClick={() => void changeMode("build")} disabled={busy}>Build</button>
              <button className={mode === "plan" ? "mode-active" : ""} onClick={() => void changeMode("plan")} disabled={busy}>Plan</button>
              <button className={mode === "full-stack" ? "mode-active" : ""} onClick={() => void changeMode("full-stack")} disabled={busy}>Full-stack</button>
            </div>
            <button className="icon-button panel-toggle" onClick={() => setRightOpen((value) => !value)} title="Afficher l’inspecteur">
              {rightOpen ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}
            </button>
          </div>
        </header>

        {notice && (
          <motion.div className="notice-bar" initial={{ opacity: 0, y: -7 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <CircleHelp size={15} />
            <span>{notice}</span>
            <button onClick={() => setNotice("")} aria-label="Fermer la notification"><X size={14} /></button>
          </motion.div>
        )}

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
                        <div className="message-meta">
                          {message.role === "user" ? "Vous" : "ZeroCode"}{" "}
                          <span>{message.role === "assistant" ? "· agent local" : ""}</span>
                        </div>
                        {message.reasoning && (
                          <details className="reasoning-details">
                            <summary><Brain size={12} /> Raisonnement de l’agent</summary>
                            <pre className="reasoning-text">{message.reasoning}</pre>
                          </details>
                        )}
                        <div className="message-text">
                          {message.content ? (
                            <FormattedMessage content={message.content} onCopy={copyText} />
                          ) : (
                            busy && message.role === "assistant" ? <span className="typing-cursor" /> : ""
                          )}
                        </div>
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
                  placeholder={workspace ? "Décrivez ce que vous souhaitez construire (utilisez @fichier pour cibler un fichier)…" : "Ouvrez un dossier pour commencer…"}
                  rows={1}
                  disabled={!workspace || !agentId || !agentReady || busy || Boolean(pending)}
                />
                <div className="composer-bottom">
                  <div className="composer-tools">
                    <span className="composer-context"><Folder size={13} /> {workspace ? shortPath(workspace) : "Aucun contexte"}</span>
                    <button
                      type="button"
                      className="model-indicator model-indicator-btn"
                      onClick={() => setSettingsOpen(true)}
                      title="Configurer le modèle et le raisonnement"
                    >
                      <Bot size={13} /> {model}{provider ? " · " + provider : ""}{thinkMode !== "off" ? ` · think:${thinkMode}` : ""}
                    </button>
                  </div>
                  <div className="composer-actions">
                    {busy && <button className="stop-button" onClick={interrupt}><StopCircle size={15} /> Arrêter</button>}
                    <button className="send-button" onClick={() => void sendPrompt()} disabled={!draft.trim() || !agentId || !agentReady || busy || Boolean(pending)} title="Envoyer">
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
              <motion.aside className="context-panel" initial={{ width: 0, opacity: 0 }} animate={{ width: 300, opacity: 1 }} exit={{ width: 0, opacity: 0 }} transition={{ duration: 0.22, ease: "easeOut" }}>
                <div className="context-head">
                  <div className="context-tabs" role="tablist">
                    <button
                      type="button"
                      className={contextTab === "overview" ? "context-tab active" : "context-tab"}
                      onClick={() => setContextTab("overview")}
                    >
                      Aperçu
                    </button>
                    <button
                      type="button"
                      className={contextTab === "files" ? "context-tab active" : "context-tab"}
                      onClick={() => {
                        setContextTab("files");
                        void loadDirectory(currentDir);
                      }}
                    >
                      Fichiers
                    </button>
                    <button
                      type="button"
                      className={contextTab === "diffs" ? "context-tab active" : "context-tab"}
                      onClick={() => {
                        setContextTab("diffs");
                        void refreshGitInfo();
                      }}
                    >
                      Diffs {(diffs.length + gitInfo.dirty_count) > 0 ? `(${diffs.length || gitInfo.dirty_count})` : ""}
                    </button>
                  </div>
                  <button className="icon-button" onClick={() => setRightOpen(false)} aria-label="Fermer le panneau"><X size={15} /></button>
                </div>

                {contextTab === "overview" && (
                  <>
                    <div className="context-section">
                      <div className="context-label">ENVIRONNEMENT</div>
                      <div className="context-project"><div className="context-folder"><Folder size={17} /></div><div><strong>{workspace ? shortPath(workspace) : "Aucun projet"}</strong><span title={workspace || ""}>{workspace || "Sélectionnez un dossier"}</span></div></div>
                      <div className="context-line"><span>Exécution</span><strong><i className="status-live" /> locale</strong></div>
                      <div className="context-line"><span>Branche Git</span><strong>{gitInfo.is_repo ? gitInfo.branch : "non initialisé"}</strong></div>
                      <div className="context-line"><span>Fichiers modifiés</span><strong>{gitInfo.dirty_count}</strong></div>
                    </div>

                    <div className="context-section">
                      <div className="context-label">AGENT</div>
                      <div className="agent-status"><div className="agent-status-icon"><Bot size={17} /></div><div><strong>{busy ? "Travail en cours" : agentReady ? "Prêt" : agentId ? "Connexion…" : "En attente"}</strong><span>{mode === "full-stack" ? "Autonomie Full-stack" : mode === "plan" ? "Lecture seule" : "Construction"}</span></div><i className={busy ? "status-live pulse" : "status-live"} /></div>
                      <div className="context-line"><span>Modèle</span><strong>{model}</strong></div>
                      <div className="context-line"><span>Fournisseur</span><strong>{provider || "Auto"}</strong></div>
                      <div className="context-line"><span>Autorisations</span><strong>{permissionsMode}</strong></div>
                      <div className="context-line"><span>Raisonnement</span><strong>{thinkMode}</strong></div>
                      <div className="context-line"><span>Jetons</span><strong>{formatCount(usage)}</strong></div>
                      {checkpoints > 0 && (
                        <button className="context-action-btn" onClick={() => void undoCheckpoint()} disabled={busy}>
                          <RotateCcw size={13} /> Annuler la dernière modification ({checkpoints})
                        </button>
                      )}
                    </div>

                    {todos.length > 0 && (
                      <div className="context-section">
                        <div className="context-label">
                          <span>PLAN DE TRAVAIL</span>
                          <span>{completedTodosCount}/{todos.length}</span>
                        </div>
                        <div className="todo-list">
                          {todos.map((todo, idx) => (
                            <div key={idx} className={"todo-item todo-" + todo.status}>
                              <span className="todo-badge">
                                {todo.status === "completed" ? <Check size={11} /> : todo.status === "in_progress" ? <span className="mini-spinner" /> : "·"}
                              </span>
                              <span className="todo-text">{todo.content}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="context-section">
                      <div className="context-label">ACTIVITÉ RÉCENTE <span>{activities.length}</span></div>
                      {activities.length === 0 ? <p className="context-empty">Les appels d’outils et les modifications apparaîtront ici.</p> : (
                        <div className="activity-list">
                          {[...activities].reverse().slice(0, 10).map((item) => {
                            const isExpanded = expandedActivityId === item.id;
                            return (
                              <div className="activity-item-wrap" key={item.id}>
                                <button
                                  type="button"
                                  className="activity-item activity-item-btn"
                                  onClick={() => setExpandedActivityId(isExpanded ? null : item.id)}
                                >
                                  <span className={"activity-mark " + item.status}>{item.status === "running" ? "·" : item.status === "success" ? "✓" : "!"}</span>
                                  <div>
                                    <strong>{item.name}</strong>
                                    <span>{item.result ? item.result.split("\n")[0].slice(0, 72) : "Exécution…"}</span>
                                  </div>
                                  <ChevronRight size={13} className={isExpanded ? "chevron-rotated" : ""} />
                                </button>
                                {isExpanded && (
                                  <pre className="activity-details">
                                    {item.arguments && Object.keys(item.arguments).length > 0
                                      ? `Arguments:\n${JSON.stringify(item.arguments, null, 2)}\n\n`
                                      : ""}
                                    {item.output ? `Sortie:\n${item.output}\n\n` : ""}
                                    {item.result ? `Résultat:\n${item.result}` : "En cours…"}
                                  </pre>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </>
                )}

                {contextTab === "files" && (
                  <div className="context-section files-section">
                    <div className="files-toolbar">
                      {currentDir ? (
                        <button type="button" className="files-up-btn" onClick={navigateParentDir} title="Dossier parent">
                          <ArrowLeft size={13} /> <span>{currentDir}</span>
                        </button>
                      ) : (
                        <span className="files-root-label"><Folder size={13} /> {workspace ? shortPath(workspace) : "Racine"}</span>
                      )}
                      <button
                        type="button"
                        className="tiny-icon"
                        onClick={() => void loadDirectory(currentDir)}
                        title="Actualiser"
                      >
                        <RefreshCw size={13} />
                      </button>
                    </div>
                    <input
                      className="files-filter-input"
                      placeholder="Filtrer les fichiers…"
                      value={fileFilter}
                      onChange={(event) => setFileFilter(event.target.value)}
                    />
                    {filesLoading ? (
                      <p className="context-empty">Chargement des fichiers…</p>
                    ) : filteredFiles.length === 0 ? (
                      <p className="context-empty">Aucun fichier trouvé.</p>
                    ) : (
                      <div className="file-tree-list">
                        {filteredFiles.map((entry) => (
                          <button
                            type="button"
                            key={entry.path}
                            className="file-tree-item"
                            onClick={() => {
                              if (entry.kind === "dir") {
                                setFileFilter("");
                                void loadDirectory(entry.path);
                              } else {
                                void openFilePreview(entry.path);
                              }
                            }}
                            title={entry.path}
                          >
                            {entry.kind === "dir" ? <Folder size={14} className="dir-icon" /> : <FileText size={14} className="file-icon" />}
                            <span className="file-tree-name">{entry.name}</span>
                            <small className="file-tree-meta">{entry.kind === "dir" ? "dossier" : formatBytes(entry.size)}</small>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {contextTab === "diffs" && (
                  <div className="context-section diffs-section">
                    {gitInfo.changed_files.length > 0 && (
                      <div className="git-changes-box">
                        <div className="context-label">
                          <span>STATUT GIT ({gitInfo.branch})</span>
                          <span>{gitInfo.changed_files.length}</span>
                        </div>
                        <div className="git-file-list">
                          {gitInfo.changed_files.map((item) => (
                            <button
                              type="button"
                              key={item.path}
                              className="git-file-item"
                              onClick={() => void openFilePreview(item.path)}
                              title="Cliquer pour inspecter le fichier"
                            >
                              <span className={"git-badge git-" + item.status.replace(/[^A-Z?]/g, "")}>{item.status}</span>
                              <span className="git-file-path">{item.path}</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="context-label">
                      <span>DIFFS DE SESSION</span>
                      <span>{diffs.length}</span>
                    </div>
                    {diffs.length === 0 ? (
                      <p className="context-empty">Les modifications appliquées par ZeroCode s’afficheront ici avec leur diff complet.</p>
                    ) : (
                      <div className="diff-cards">
                        {diffs.map((item) => (
                          <div key={item.id} className="diff-card">
                            <div className="diff-card-header">
                              <FileDiff size={13} />
                              <strong>{item.path}</strong>
                            </div>
                            <pre className="diff-pre">
                              {item.diff.split("\n").map((line, index) => {
                                const cls = line.startsWith("+") && !line.startsWith("+++")
                                  ? "diff-add"
                                  : line.startsWith("-") && !line.startsWith("---")
                                  ? "diff-del"
                                  : line.startsWith("@@")
                                  ? "diff-hunk"
                                  : "";
                                return <div key={index} className={cls}>{line || " "}</div>;
                              })}
                            </pre>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="context-bottom"><ShieldCheck size={14} /><span>Les modifications nécessitent une autorisation selon le mode choisi.</span></div>
              </motion.aside>
            )}
          </AnimatePresence>
        </div>
        <footer className="statusbar">
          <div><span className="status-live" /> {agentId ? "Connecté à ZeroCode" : workspace ? "Connexion à l’agent…" : "Aucun dossier ouvert"}</div>
          <div>
            <GitBranch size={12} /> {gitInfo.is_repo ? gitInfo.branch : "local"}
            {gitInfo.dirty_count > 0 ? ` (${gitInfo.dirty_count} mod.)` : ""}
            <span className="status-separator">·</span>
            <History size={12} /> {sessionId ? sessionId.slice(0, 12) : "nouvelle session"}
            {todos.length > 0 && (
              <>
                <span className="status-separator">·</span>
                <ListTodo size={12} /> {completedTodosCount}/{todos.length} tâches
              </>
            )}
          </div>
          <div><ShieldCheck size={12} /> Fichiers et commandes sur cet appareil</div>
        </footer>
      </div>

      {sidebarOpen && <button className="mobile-scrim" onClick={() => setSidebarOpen(false)} aria-label="Fermer le menu" />}

      {previewFile && (
        <div className="search-overlay" onClick={() => setPreviewFile(null)}>
          <motion.div
            className="file-preview-dialog"
            onClick={(event) => event.stopPropagation()}
            initial={{ opacity: 0, y: 10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
          >
            <header className="file-preview-header">
              <div className="file-preview-title">
                <Code2 size={16} />
                <strong>{previewFile.path}</strong>
                <span>{previewFile.lines} lignes{previewFile.truncated ? " · tronqué" : ""}</span>
              </div>
              <div className="file-preview-actions">
                <button
                  type="button"
                  className="secondary-button small"
                  onClick={() => mentionFileInDraft(previewFile.path)}
                >
                  @ Mentionner dans le prompt
                </button>
                <button
                  type="button"
                  className="secondary-button small"
                  onClick={() => copyText(previewFile.content)}
                >
                  <Copy size={12} /> Copier
                </button>
                <button type="button" className="icon-button" onClick={() => setPreviewFile(null)} aria-label="Fermer">
                  <X size={16} />
                </button>
              </div>
            </header>
            <pre className="file-preview-body"><code>{previewFile.content}</code></pre>
          </motion.div>
        </div>
      )}

      {settingsOpen && (
        <div className="search-overlay" onClick={() => setSettingsOpen(false)}>
          <motion.div
            className="settings-dialog"
            onClick={(event) => event.stopPropagation()}
            initial={{ opacity: 0, y: -12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
          >
            <header className="settings-header">
              <div>
                <strong>Préférences ZeroCode Desktop</strong>
                <span>Configuration locale de l’agent et des autorisations</span>
              </div>
              <button type="button" className="icon-button" onClick={() => setSettingsOpen(false)} aria-label="Fermer">
                <X size={16} />
              </button>
            </header>

            <div className="settings-group">
              <label>Apparence</label>
              <div className="appearance-options" role="group" aria-label="Thème de l’application">
                <button type="button" className={theme === "light" ? "appearance-option active" : "appearance-option"} onClick={() => setTheme("light")}>Clair</button>
                <button type="button" className={theme === "dark" ? "appearance-option active" : "appearance-option"} onClick={() => setTheme("dark")}>Sombre</button>
              </div>
              <span className="settings-help">Le choix est conservé sur cet appareil.</span>
            </div>

            <div className="settings-group">
              <label>Modèle actif</label>
              <select
                value={availableModels.includes(model) ? model : "__custom__"}
                onChange={(event) => {
                  if (event.target.value !== "__custom__") {
                    void changeModel(event.target.value);
                  }
                }}
                disabled={!agentId || busy}
              >
                {availableModels.map((item) => (
                  <option key={item} value={item}>{item === "auto" ? "auto (Routage intelligent gratuit)" : item}</option>
                ))}
                {!availableModels.includes(model) && <option value="__custom__">{model}</option>}
              </select>
              <div className="settings-inline-input">
                <input
                  placeholder="Ou saisir un identifiant (ex: ollama/qwen2.5-coder, auto…)"
                  value={customModelInput}
                  onChange={(event) => setCustomModelInput(event.target.value)}
                />
                <button
                  type="button"
                  className="primary-button small"
                  disabled={!customModelInput.trim() || !agentId || busy}
                  onClick={() => {
                    void changeModel(customModelInput);
                    setCustomModelInput("");
                  }}
                >
                  Appliquer
                </button>
              </div>
            </div>

            <div className="settings-group">
              <label>Politique d’autorisation des outils</label>
              <div className="settings-pills">
                {[
                  { id: "ask", label: "Demander (ask)", desc: "Confirmation avant écriture ou commande" },
                  { id: "auto", label: "Auto-édition (auto)", desc: "Autorise les éditions sûres dans le projet" },
                  { id: "allow", label: "Autonome (allow)", desc: "Exécute sans interrompre (hors actions critiques)" }
                ].map((opt) => (
                  <button
                    type="button"
                    key={opt.id}
                    className={permissionsMode === opt.id ? "settings-choice active" : "settings-choice"}
                    onClick={() => void changePermissions(opt.id)}
                    disabled={!agentId || busy}
                  >
                    <strong>{opt.label}</strong>
                    <span>{opt.desc}</span>
                  </button>
                ))}
              </div>
              <p className="settings-warning">
                <ShieldCheck size={14} />
                <span><strong>À savoir :</strong> le mode autonome autorise l’agent à modifier les fichiers et lancer des commandes avec les droits de votre compte. Gardez « Demander » pour les projets sensibles. Le terminal intégré reste un terminal local classique.</span>
              </p>
            </div>

            <div className="settings-group">
              <label>Profondeur de raisonnement (Think)</label>
              <div className="mode-switch settings-think-switch">
                {(["off", "low", "high", "max"] as const).map((lvl) => (
                  <button
                    type="button"
                    key={lvl}
                    className={thinkMode === lvl ? "mode-active" : ""}
                    onClick={() => void changeThink(lvl)}
                    disabled={!agentId || busy}
                  >
                    {lvl.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            <footer className="settings-footer">
              <button
                type="button"
                className="secondary-button small"
                onClick={() => void compactContext()}
                disabled={!agentId || busy}
              >
                Compacter le contexte de session
              </button>
              <button
                type="button"
                className="text-button"
                onClick={() => {
                  localStorage.removeItem("zerocode.recents");
                  setRecentProjects(workspace ? [workspace] : []);
                  setNotice("Historique des projets récents nettoyé.");
                }}
              >
                Effacer les projets récents
              </button>
            </footer>
          </motion.div>
        </div>
      )}

      {searchOpen && (
        <div className="search-overlay" onClick={() => setSearchOpen(false)}>
          <motion.div className="search-dialog" onClick={(event) => event.stopPropagation()} initial={{ opacity: 0, y: -12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}>
            <Search size={17} />
            <input
              autoFocus
              placeholder="Rechercher un projet, une conversation ou une action…"
              value={sessionSearch}
              onChange={(event) => setSessionSearch(event.target.value)}
            />
            <kbd>Échap</kbd>

            <div className="palette-section-title">ACTIONS RAPIDES</div>
            <button onClick={() => { newSession(); setSearchOpen(false); }} disabled={!agentId || busy}>
              <MessageSquarePlus size={14} /> Nouvelle tâche <span>Ctrl N</span>
            </button>
            <button onClick={() => { setTerminalOpen((v) => !v); setSearchOpen(false); }}>
              <Code2 size={14} /> {terminalOpen ? "Masquer le terminal" : "Afficher le terminal"} <span>Ctrl `</span>
            </button>
            <button onClick={() => { setSettingsOpen(true); setSearchOpen(false); }}>
              <Settings2 size={14} /> Ouvrir les préférences (Modèle, Autorisations, Think) <span>Ctrl ,</span>
            </button>
            {checkpoints > 0 && (
              <button onClick={() => { void undoCheckpoint(); setSearchOpen(false); }} disabled={busy}>
                <RotateCcw size={14} /> Annuler la dernière modification ({checkpoints}) <span>Checkpoint</span>
              </button>
            )}

            {filteredSessions.length > 0 && (
              <>
                <div className="palette-section-title">CONVERSATIONS</div>
                {filteredSessions.slice(0, 5).map((item) => (
                  <button key={item.id} onClick={() => { void resumeSession(item.id); setSearchOpen(false); }}>
                    <MessageSquare size={14} /> {item.title} <span>{item.id.slice(0, 10)}</span>
                  </button>
                ))}
              </>
            )}

            {filteredRecents.length > 0 && (
              <>
                <div className="palette-section-title">ESPACES DE TRAVAIL RÉCENTS</div>
                {filteredRecents.map((item) => (
                  <button key={item} onClick={() => { activateWorkspace(item); setSearchOpen(false); }}>
                    <Folder size={15} /> {shortPath(item)} <span>{item}</span>
                  </button>
                ))}
              </>
            )}
          </motion.div>
        </div>
      )}
    </div>
  );
}
