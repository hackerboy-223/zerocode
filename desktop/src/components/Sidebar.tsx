import { useMemo, useState } from "react";
import { ChevronDown, Folder, FolderOpen, GitFork, MessageSquare, Pencil, Plus, Search, Settings2, Trash2 } from "lucide-react";
import Lupus from "./Lupus";
import type { SessionSummary } from "../types";

const shortPath = (path: string) => path.replace(/\/+$/, "").split(/[\\/]/).filter(Boolean).pop() || path;

function bucket(value: string): string {
  const time = Date.parse(value);
  if (Number.isNaN(time)) return "Plus ancien";
  const days = (Date.now() - time) / 86_400_000;
  if (days < 1) return "Aujourd’hui";
  if (days < 7) return "Cette semaine";
  return "Plus ancien";
}

export default function Sidebar({
  workspace, recents, sessions, sessionId, ready, busy,
  onNew, onChoose, onSelect, onFree, onResume, onRename, onFork, onDelete, onSettings, onPalette
}: {
  workspace: string | null; recents: string[]; sessions: SessionSummary[]; sessionId: string; ready: boolean; busy: boolean;
  onNew: () => void; onChoose: () => void; onSelect: (path: string) => void; onFree: () => void;
  onResume: (id: string) => void; onRename: (id: string, title: string) => void; onFork: (id: string) => void;
  onDelete: (id: string) => void; onSettings: () => void; onPalette: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const [filter, setFilter] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const order = ["Aujourd’hui", "Cette semaine", "Plus ancien"];
    const map = new Map<string, SessionSummary[]>();
    for (const session of sessions) {
      if (needle && !session.title.toLowerCase().includes(needle)) continue;
      const key = bucket(session.updated_at);
      map.set(key, [...(map.get(key) ?? []), session]);
    }
    return order.filter((key) => map.has(key)).map((key) => ({ key, items: map.get(key)! }));
  }, [sessions, filter]);

  const commitRename = (session: SessionSummary) => {
    const cleaned = editingTitle.trim();
    setEditingId(null);
    if (cleaned && cleaned !== session.title) onRename(session.id, cleaned);
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <Lupus />
        <strong>ZeroCode</strong>
        <button type="button" className="icon-btn" onClick={onPalette} title="Palette de commandes (Ctrl K)" aria-label="Palette de commandes"><Search size={15} /></button>
      </div>

      <div className="workspace-switcher">
        <button type="button" className="workspace-current" onClick={() => setMenu((value) => !value)} aria-expanded={menu} title={workspace ?? "Conversation libre"}>
          {workspace ? <Folder size={15} /> : <MessageSquare size={15} />}
          <span>{workspace ? shortPath(workspace) : "Conversation libre"}</span>
          <ChevronDown size={14} className={menu ? "turn" : ""} />
        </button>
        {menu && (
          <div className="menu">
            <button type="button" onClick={() => { setMenu(false); onChoose(); }}><FolderOpen size={14} /> Ouvrir un dossier…</button>
            {workspace && <button type="button" onClick={() => { setMenu(false); onFree(); }}><MessageSquare size={14} /> Conversation libre</button>}
            {recents.filter((item) => item !== workspace).length > 0 && <div className="menu-label">RÉCENTS</div>}
            {recents.filter((item) => item !== workspace).map((item) => (
              <button type="button" key={item} onClick={() => { setMenu(false); onSelect(item); }} title={item}><Folder size={14} /> {shortPath(item)}</button>
            ))}
          </div>
        )}
      </div>

      <button type="button" className="new-task" onClick={onNew} disabled={!ready || busy}>
        <Plus size={15} /> Nouvelle tâche <kbd>Ctrl N</kbd>
      </button>

      <div className="session-head">
        <span>CONVERSATIONS</span>
        {sessions.length > 4 && <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filtrer" aria-label="Filtrer les conversations" />}
      </div>
      <div className="session-scroll">
        {sessions.length === 0 && <div className="side-empty">Vos conversations apparaîtront ici.</div>}
        {groups.map((group) => (
          <div key={group.key}>
            <div className="group-label">{group.key}</div>
            {group.items.map((session) => (
              <div key={session.id} className={"session" + (session.id === sessionId ? " current" : "")}>
                {editingId === session.id ? (
                  <input autoFocus className="session-rename" value={editingTitle} maxLength={80}
                    onChange={(event) => setEditingTitle(event.target.value)}
                    onBlur={() => commitRename(session)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") commitRename(session);
                      else if (event.key === "Escape") setEditingId(null);
                    }} />
                ) : (
                  <>
                    <button type="button" onClick={() => onResume(session.id)} disabled={busy || session.id === sessionId} title={session.title}
                      onDoubleClick={() => { if (!busy) { setEditingId(session.id); setEditingTitle(session.title); } }}>
                      <span>{session.title}</span>
                    </button>
                    <div className="session-actions">
                      <button type="button" className="session-act" onClick={() => { setEditingId(session.id); setEditingTitle(session.title); }} disabled={busy} aria-label="Renommer" title="Renommer"><Pencil size={11} /></button>
                      <button type="button" className="session-act" onClick={() => onFork(session.id)} disabled={busy} aria-label="Dupliquer (fork)" title="Bifurquer (fork)"><GitFork size={11} /></button>
                      <button type="button" className="session-act del" onClick={() => onDelete(session.id)} disabled={busy} aria-label="Supprimer la conversation" title="Supprimer"><Trash2 size={11} /></button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="side-footer">
        <button type="button" onClick={onSettings}><Settings2 size={15} /> Préférences <kbd>Ctrl ,</kbd></button>
      </div>
    </aside>
  );
}
