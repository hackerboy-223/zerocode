import { useState, type FormEvent } from "react";
import { Check, Plus, RefreshCw, Server, ShieldCheck, Trash2, X } from "lucide-react";

export type McpServer = { name: string; command: string; args: string[]; cwd?: string; enabled: boolean; trusted: boolean; timeout: number; env_keys: string[] };

export default function McpManager({ servers, onRefresh, onSave, onRemove, restartRequired, onRestart }: {
  servers: McpServer[]; onRefresh: () => void;
  onSave: (name: string, server: Record<string, unknown>) => Promise<void>;
  onRemove: (name: string) => Promise<void>; restartRequired: boolean; onRestart: () => void;
}) {
  const [editing, setEditing] = useState(false); const [name, setName] = useState("");
  const [command, setCommand] = useState(""); const [args, setArgs] = useState("[]");
  const [cwd, setCwd] = useState(""); const [env, setEnv] = useState(""); const [editingExisting, setEditingExisting] = useState(false);
  const [trusted, setTrusted] = useState(false); const [enabled, setEnabled] = useState(true);
  const [timeout, setTimeoutValue] = useState(30); const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  const reset = () => { setName(""); setCommand(""); setArgs("[]"); setCwd(""); setEnv(""); setTrusted(false); setEnabled(true); setTimeoutValue(30); setError(""); setEditing(false); setEditingExisting(false); };
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError("");
    try {
      const parsedArgs: unknown = JSON.parse(args); const parsedEnv: unknown = env.trim() ? JSON.parse(env) : undefined;
      if (!Array.isArray(parsedArgs) || parsedArgs.some((value) => typeof value !== "string")) throw new Error("Les arguments doivent être un tableau JSON de chaînes.");
      if (parsedEnv !== undefined && (!parsedEnv || Array.isArray(parsedEnv) || typeof parsedEnv !== "object" || Object.values(parsedEnv).some((value) => typeof value !== "string"))) throw new Error("Les variables d’environnement doivent être un objet JSON de chaînes.");
      setSaving(true);
      await onSave(name.trim(), { command: command.trim(), args: parsedArgs, ...(cwd.trim() ? { cwd: cwd.trim() } : {}), ...(parsedEnv ? { env: parsedEnv } : {}), enabled, trusted, timeout });
      reset();
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setSaving(false); }
  };
  return <div className="mcp-manager">
    <header className="mcp-manager-head"><div><span className="context-label">ÉCOSYSTÈME MCP</span><h3>Serveurs & outils</h3><p>Connectez des outils locaux à l’agent ZeroCode.</p></div><button className="tiny-icon" type="button" onClick={onRefresh} title="Actualiser"><RefreshCw size={14} /></button></header>
    {restartRequired && <div className="mcp-restart-banner"><span>Configuration enregistrée. Redémarrez l’agent pour charger les changements.</span><button type="button" className="primary-button small" onClick={onRestart}>Redémarrer</button></div>}
    {servers.length === 0 ? <div className="mcp-empty"><Server size={26} /><strong>Aucun serveur MCP configuré</strong><span>Ajoutez un serveur local pour exposer ses outils à l’agent.</span></div> :
      <div className="mcp-server-list">{servers.map((server) => <article className="mcp-server-card" key={server.name}>
        <div className="mcp-server-title"><div className="mcp-server-icon"><Server size={15} /></div><div><strong>{server.name}</strong><span>{server.command} {server.args.join(" ")}</span></div><i className={server.enabled ? "status-live" : "status-idle"} /></div>
        <div className="mcp-server-meta"><span>{server.enabled ? "Activé" : "Désactivé"}</span><span>{server.trusted ? <><ShieldCheck size={11} /> Approuvé</> : "Confirmation requise"}</span><span>{server.timeout}s</span></div>
        {server.env_keys.length > 0 && <div className="mcp-env-keys">Variables : {server.env_keys.join(", ")}</div>}
        <div className="mcp-card-actions">
          <button type="button" className="mcp-edit-btn" onClick={() => { setName(server.name); setCommand(server.command); setArgs(JSON.stringify(server.args, null, 2)); setCwd(server.cwd || ""); setEnv(""); setTrusted(server.trusted); setEnabled(server.enabled); setTimeoutValue(server.timeout); setEditingExisting(true); setEditing(true); }}><span>Modifier</span></button>
          <button type="button" className="mcp-remove-btn" onClick={() => { if (window.confirm(`Supprimer le serveur ${server.name} de la configuration globale ?`)) void onRemove(server.name); }}><Trash2 size={12} /> Supprimer</button>
        </div>
      </article>)}</div>}
    {!editing ? <button type="button" className="mcp-add-btn" onClick={() => setEditing(true)}><Plus size={15} /> Ajouter un serveur MCP</button> :
      <form className="mcp-form" onSubmit={(event) => void submit(event)}>
        <div className="mcp-form-title"><strong>{editingExisting ? "Modifier le serveur MCP" : "Nouveau serveur MCP"}</strong><button type="button" className="tiny-icon" onClick={reset}><X size={14} /></button></div>
        <label>Identifiant<input required maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9._-]*" readOnly={editingExisting} value={name} onChange={(e) => setName(e.target.value)} placeholder="filesystem" /></label>
        <label>Commande locale<input required value={command} onChange={(e) => setCommand(e.target.value)} placeholder="npx" /></label>
        <label>Arguments (JSON)<textarea rows={2} value={args} onChange={(e) => setArgs(e.target.value)} spellCheck={false} /></label>
        <label>Répertoire de lancement<input value={cwd} onChange={(e) => setCwd(e.target.value)} placeholder="~/Projects/mon-projet" /></label>
        <label>Variables d’environnement (JSON, laisser vide pour conserver les valeurs existantes)<textarea rows={3} value={env} onChange={(e) => setEnv(e.target.value)} spellCheck={false} /></label>
        <label>Délai maximum (secondes)<input type="number" min={1} max={3600} value={timeout} onChange={(e) => setTimeoutValue(Number(e.target.value))} /></label>
        <label className="mcp-check"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Activer ce serveur</label>
        <label className="mcp-check"><input type="checkbox" checked={trusted} onChange={(e) => setTrusted(e.target.checked)} /> Faire confiance aux outils de ce serveur (serveurs vérifiés uniquement)</label>
        {error && <p className="mcp-error">{error}</p>}
        <div className="mcp-form-actions"><button type="button" className="secondary-button small" onClick={reset}>Annuler</button><button type="submit" className="primary-button small" disabled={saving}>{saving ? "Enregistrement…" : <><Check size={13} /> Enregistrer</>}</button></div>
        <p className="mcp-security-note">Les commandes MCP sont des exécutables locaux. Vérifiez leur provenance avant activation. Les valeurs des variables ne sont jamais réaffichées.</p>
      </form>}
  </div>;
}
