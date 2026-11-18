import { useEffect, useMemo, useState } from "react";
import Editor, { loader } from "@monaco-editor/react";
import { Code2, Copy, FileCode2, Save, X } from "lucide-react";
import type { WorkspaceFilePreview } from "../types";

loader.config({ paths: { vs: `${import.meta.env.BASE_URL}vs` } });

type EditorTab = { path: string; content: string; savedContent: string; truncated: boolean };

function languageForPath(path: string) {
  const name = path.split("/").pop() || path;
  const ext = name.includes(".") ? name.split(".").pop()?.toLowerCase() : "";
  const languages: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    mjs: "javascript", cjs: "javascript", py: "python", rs: "rust",
    html: "html", css: "css", scss: "scss", json: "json", md: "markdown",
    yml: "yaml", yaml: "yaml", toml: "ini", sh: "shell", bash: "shell",
    sql: "sql", php: "php", go: "go", java: "java", c: "c", cpp: "cpp",
    h: "c", hpp: "cpp", xml: "xml", svg: "xml"
  };
  if (name.toLowerCase() === "dockerfile") return "dockerfile";
  return languages[ext || ""] || "plaintext";
}

export default function EditorWorkspace({ file, onSave, onMention, onClose }: {
  file: WorkspaceFilePreview | null;
  onSave: (path: string, content: string) => Promise<void>;
  onMention: (path: string) => void;
  onClose: () => void;
}) {
  const [tabs, setTabs] = useState<EditorTab[]>([]);
  const [activePath, setActivePath] = useState("");
  const [saving, setSaving] = useState(false);
  const active = tabs.find((tab) => tab.path === activePath) || null;
  const dirtyCount = tabs.filter((tab) => tab.content !== tab.savedContent).length;

  useEffect(() => {
    if (!file) return;
    setTabs((current) => {
      const existing = current.find((tab) => tab.path === file.path);
      if (existing) return current.map((tab) => tab.path === file.path && tab.content === tab.savedContent
        ? { ...tab, content: file.content, savedContent: file.content, truncated: file.truncated } : tab);
      return [...current, { path: file.path, content: file.content, savedContent: file.content, truncated: file.truncated }];
    });
    setActivePath(file.path);
  }, [file]);

  const language = useMemo(() => active ? languageForPath(active.path) : "plaintext", [active]);
  const updateContent = (value?: string) => {
    if (!active) return;
    setTabs((current) => current.map((tab) => tab.path === active.path ? { ...tab, content: value ?? "" } : tab));
  };
  const saveActive = async () => {
    if (!active || active.truncated || active.content === active.savedContent || saving) return;
    setSaving(true);
    try {
      await onSave(active.path, active.content);
      setTabs((current) => current.map((tab) => tab.path === active.path ? { ...tab, savedContent: tab.content } : tab));
    } finally { setSaving(false); }
  };
  const closeTab = (path: string) => {
    const tab = tabs.find((item) => item.path === path);
    if (tab && tab.content !== tab.savedContent && !window.confirm(`Abandonner les modifications non enregistrées de ${path} ?`)) return;
    const next = tabs.filter((item) => item.path !== path);
    setTabs(next);
    if (activePath === path) setActivePath(next.at(-1)?.path || "");
    if (next.length === 0) onClose();
  };

  return <section className="ide-editor">
    <div className="ide-editor-toolbar">
      <div className="ide-editor-tabs" role="tablist" aria-label="Fichiers ouverts">
        {tabs.map((tab) => <button type="button" role="tab" aria-selected={activePath === tab.path}
          key={tab.path} className={activePath === tab.path ? "ide-editor-tab active" : "ide-editor-tab"}
          onClick={() => setActivePath(tab.path)} title={tab.path}>
          <FileCode2 size={13} /><span>{tab.path.split("/").pop()}</span>
          {tab.content !== tab.savedContent && <i className="editor-dirty-dot" />}
          <span role="button" tabIndex={0} className="editor-tab-close" aria-label={`Fermer ${tab.path}`}
            onClick={(event) => { event.stopPropagation(); closeTab(tab.path); }}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.stopPropagation(); closeTab(tab.path); } }}><X size={12} /></span>
        </button>)}
      </div>
      <div className="ide-editor-actions">
        {active && <span className="editor-language">{language}</span>}
        <button type="button" className="tiny-icon" disabled={!active} onClick={() => active && onMention(active.path)} title="Ajouter au contexte"><Code2 size={14} /></button>
        <button type="button" className="tiny-icon" disabled={!active} onClick={() => active && void navigator.clipboard.writeText(active.content)} title="Copier"><Copy size={14} /></button>
        <button type="button" className="primary-button small editor-save" disabled={!active || active.content === active.savedContent || active.truncated || saving} onClick={() => void saveActive()}>{saving ? "Sauvegarde…" : <><Save size={13} /> Enregistrer</>}</button>
      </div>
    </div>
    {active ? <>
      {active.truncated && <div className="editor-warning">Fichier tronqué à la lecture : l’édition est désactivée pour éviter d’écraser son contenu.</div>}
      <div className="ide-monaco-wrap"><Editor height="100%" path={active.path} language={language} value={active.content}
        onChange={updateContent} theme="vs-dark" loading={<div className="editor-loading">Chargement de Monaco…</div>}
        options={{ automaticLayout: true, minimap: { enabled: true }, fontSize: 13,
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace", fontLigatures: true,
          lineNumbers: "on", renderLineHighlight: "all", scrollBeyondLastLine: false,
          smoothScrolling: true, cursorSmoothCaretAnimation: "on", padding: { top: 14, bottom: 14 },
          wordWrap: "off", tabSize: 2, insertSpaces: true, bracketPairColorization: { enabled: true },
          guides: { indentation: true, bracketPairs: true }, readOnly: active.truncated }} /></div>
      <footer className="ide-editor-footer"><span>{active.path}</span><span>{active.content.split("\n").length} lignes · {active.content.length.toLocaleString("fr-FR")} caractères</span>{dirtyCount > 0 && <strong>{dirtyCount} fichier(s) non enregistré(s)</strong>}</footer>
    </> : <div className="editor-empty"><Code2 size={28} /><strong>Votre espace de code</strong><span>Ouvrez un fichier depuis l’explorateur pour commencer.</span></div>}
  </section>;
}
