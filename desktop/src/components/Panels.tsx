import { ArrowLeft, Check, Code2, FileDiff, FileText, Folder, Plus, RefreshCw, RotateCcw } from "lucide-react";
import type { DiffEntry, GitWorkspaceInfo, TodoItem, WorkspaceEntry } from "../types";

const shortPath = (path: string) => path.replace(/\/+$/, "").split(/[\\/]/).filter(Boolean).pop() || path;

function formatBytes(size: number) {
  if (size < 1024) return `${size} o`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} Ko`;
  return `${(size / (1024 * 1024)).toFixed(1)} Mo`;
}

export function OverviewPanel({ workspace, git, agentState, mode, model, provider, permissions, think, usage, todos, checkpoints, busy, onUndo, onTerminal }: {
  workspace: string | null; git: GitWorkspaceInfo; agentState: string; mode: string; model: string; provider: string;
  permissions: string; think: string; usage: number; todos: TodoItem[]; checkpoints: number; busy: boolean;
  onUndo: () => void; onTerminal: () => void;
}) {
  const done = todos.filter((todo) => todo.status === "completed").length;
  const modeLabel = mode === "full-stack" ? "Autonomie Full-stack" : mode === "plan" ? "Lecture seule" : "Construction";
  return (
    <div className="panel">
      <div className="panel-section">
        <div className="panel-label">PROJET</div>
        <div className="kv"><span>Dossier</span><strong title={workspace ?? ""}>{workspace ? shortPath(workspace) : "Aucun"}</strong></div>
        <div className="kv"><span>Branche</span><strong>{git.is_repo ? git.branch : "non versionné"}</strong></div>
        <div className="kv"><span>Fichiers modifiés</span><strong>{git.dirty_count}</strong></div>
        {workspace && <button type="button" className="btn small full" onClick={onTerminal}>Ouvrir le terminal</button>}
      </div>
      <div className="panel-section">
        <div className="panel-label">AGENT</div>
        <div className="kv"><span>État</span><strong className={"state " + agentState}>{agentState === "busy" ? "Travail en cours" : agentState === "ready" ? "Prêt" : "Connexion…"}</strong></div>
        <div className="kv"><span>Mode</span><strong>{modeLabel}</strong></div>
        <div className="kv"><span>Modèle</span><strong>{model}</strong></div>
        <div className="kv"><span>Fournisseur</span><strong>{provider || "auto"}</strong></div>
        <div className="kv"><span>Autorisations</span><strong>{permissions}</strong></div>
        <div className="kv"><span>Raisonnement</span><strong>{think}</strong></div>
        <div className="kv"><span>Jetons</span><strong>{new Intl.NumberFormat("fr-FR").format(usage)}</strong></div>
        {checkpoints > 0 && <button type="button" className="btn small full" onClick={onUndo} disabled={busy}><RotateCcw size={12} /> Annuler la dernière modification ({checkpoints})</button>}
      </div>
      {todos.length > 0 && (
        <div className="panel-section">
          <div className="panel-label">PLAN <span>{done}/{todos.length}</span></div>
          <div className="progress"><i style={{ width: `${(done / todos.length) * 100}%` }} /></div>
          <div className="todo-list">
            {todos.map((todo, index) => (
              <div key={index} className={"todo " + todo.status}>
                <span className="todo-mark">{todo.status === "completed" ? <Check size={10} /> : todo.status === "in_progress" ? <span className="spinner small" /> : null}</span>
                <span>{todo.content}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function FilesPanel({ workspace, currentDir, entries, loading, filter, onFilter, onOpenEntry, onUp, onRefresh, onNew }: {
  workspace: string | null; currentDir: string; entries: WorkspaceEntry[]; loading: boolean; filter: string;
  onFilter: (value: string) => void; onOpenEntry: (entry: WorkspaceEntry) => void; onUp: () => void; onRefresh: () => void; onNew: () => void;
}) {
  if (!workspace) return <div className="panel"><div className="empty-block"><Folder size={22} /><span>Ouvrez un projet pour explorer ses fichiers.</span></div></div>;
  return (
    <div className="panel files-panel">
      <div className="files-toolbar">
        {currentDir ? <button type="button" className="crumb" onClick={onUp}><ArrowLeft size={13} /> {currentDir}</button> : <span className="crumb static"><Folder size={13} /> {shortPath(workspace)}</span>}
        <button type="button" className="icon-btn" onClick={onRefresh} title="Actualiser"><RefreshCw size={13} /></button>
        <button type="button" className="icon-btn" onClick={onNew} title="Nouveau fichier"><Plus size={14} /></button>
      </div>
      <input className="text-input" placeholder="Filtrer…" value={filter} onChange={(event) => onFilter(event.target.value)} />
      {loading ? <p className="muted-note">Chargement…</p> : entries.length === 0 ? <p className="muted-note">Aucun fichier.</p> : (
        <div className="file-list">
          {entries.map((entry) => (
            <button type="button" key={entry.path} className="file-item" onClick={() => onOpenEntry(entry)} title={entry.path}>
              {entry.kind === "dir" ? <Folder size={14} className="dir" /> : <FileText size={14} />}
              <span>{entry.name}</span>
              <small>{entry.kind === "dir" ? "" : formatBytes(entry.size)}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function ChangesPanel({ git, diffs, checkpoints, busy, onOpenFile, onUndo }: {
  git: GitWorkspaceInfo; diffs: DiffEntry[]; checkpoints: number; busy: boolean; onOpenFile: (path: string) => void; onUndo: () => void;
}) {
  return (
    <div className="panel">
      {git.changed_files.length > 0 && (
        <div className="panel-section">
          <div className="panel-label">GIT · {git.branch} <span>{git.changed_files.length}</span></div>
          <div className="file-list">
            {git.changed_files.map((item) => (
              <button type="button" key={item.path} className="file-item" onClick={() => onOpenFile(item.path)} title={item.path}>
                <b className={"git-badge s-" + item.status.replace(/[^A-Z?]/g, "")}>{item.status.trim() || "?"}</b>
                <span>{item.path}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="panel-section">
        <div className="panel-label">MODIFICATIONS DE LA SESSION <span>{diffs.length}</span></div>
        {checkpoints > 0 && <button type="button" className="btn small full" onClick={onUndo} disabled={busy}><RotateCcw size={12} /> Annuler la dernière modification ({checkpoints})</button>}
        {diffs.length === 0 ? <div className="empty-block"><FileDiff size={22} /><span>Les modifications de l’agent apparaîtront ici avec leur diff.</span></div> : diffs.map((item) => (
          <div key={item.id} className="diff-card">
            <div className="diff-head"><FileDiff size={13} /><strong>{item.path}</strong><button type="button" className="icon-btn" onClick={() => onOpenFile(item.path)} title="Ouvrir dans l’éditeur"><Code2 size={13} /></button></div>
            <pre className="diff-body">
              {item.diff.split("\n").map((line, index) => {
                const cls = line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : line.startsWith("@@") ? "hunk" : "";
                return <div key={index} className={cls}>{line || " "}</div>;
              })}
            </pre>
          </div>
        ))}
      </div>
    </div>
  );
}
