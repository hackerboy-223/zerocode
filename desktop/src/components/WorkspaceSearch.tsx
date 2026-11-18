import { useMemo, useState } from "react";
import { FileSearch, LoaderCircle, Search, Sparkles } from "lucide-react";
import { desktopInvoke } from "../lib/desktop";
import type { WorkspaceEntry, WorkspaceFilePreview } from "../types";

type Document = { path: string; content: string; lower: string };
const ignoredNames = new Set([".env", ".npmrc", ".netrc", ".pypirc", ".git-credentials", "credentials", "credentials.json", "id_rsa", "id_ed25519"]);
const ignoredExtensions = new Set(["png","jpg","jpeg","gif","webp","ico","pdf","zip","gz","lock","sqlite","db","wasm","mp4","mp3","woff","woff2","ttf","otf"]);
const isSafe = (entry: WorkspaceEntry) => {
  const parts = entry.path.toLowerCase().split("/"); const name = parts.at(-1) || "";
  const ext = name.includes(".") ? name.split(".").pop() || "" : "";
  return !parts.some((part) => [".git",".ssh",".aws",".gnupg","node_modules",".venv","target","dist"].includes(part))
    && !ignoredNames.has(name) && !name.startsWith(".env.") && ![".pem",".key",".p12",".pfx",".jks"].some((suffix) => name.endsWith(suffix))
    && !ignoredExtensions.has(ext) && entry.size <= 256_000;
};
export default function WorkspaceSearch({ workspace, onOpen, onMention }: { workspace: string; onOpen: (path: string) => void; onMention: (path: string) => void }) {
  const [documents, setDocuments] = useState<Document[]>([]); const [query, setQuery] = useState("");
  const [indexing, setIndexing] = useState(false); const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [indexedAt, setIndexedAt] = useState(""); const [error, setError] = useState("");
  const buildIndex = async () => {
    setIndexing(true); setError(""); setDocuments([]); setProgress({ done: 0, total: 0 });
    try {
      const queue = [""]; const seen = new Set<string>(); const files: WorkspaceEntry[] = [];
      while (queue.length && files.length < 600) {
        const dir = queue.shift()!; if (seen.has(dir)) continue; seen.add(dir);
        const entries = await desktopInvoke<WorkspaceEntry[]>("list_workspace_files", { cwd: workspace, relativeDir: dir });
        for (const entry of entries) {
          if (entry.kind === "dir") { if (dir.split("/").length < 8) queue.push(entry.path); }
          else if (isSafe(entry)) files.push(entry);
          if (files.length >= 600) break;
        }
      }
      setProgress({ done: 0, total: files.length }); const docs: Document[] = []; let cursor = 0;
      const workers = Array.from({ length: 4 }, async () => {
        while (cursor < files.length) {
          const current = files[cursor++];
          try {
            const preview = await desktopInvoke<WorkspaceFilePreview>("read_workspace_file", { cwd: workspace, relativePath: current.path });
            if (!preview.truncated && preview.content.trim()) docs.push({ path: current.path, content: preview.content, lower: (current.path + "\n" + preview.content).toLowerCase() });
          } catch { /* Binary, inaccessible and protected files are intentionally skipped. */ }
          setProgress((value) => ({ ...value, done: Math.min(value.total, value.done + 1) }));
        }
      });
      await Promise.all(workers); setDocuments(docs); setIndexedAt(new Date().toLocaleTimeString("fr-FR"));
    } catch (reason) { setError(String(reason)); }
    finally { setIndexing(false); }
  };
  const results = useMemo(() => {
    const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean); if (!terms.length) return [];
    return documents.map((doc) => {
      let score = 0;
      for (const term of terms) {
        const pathHits = doc.path.toLowerCase().split("/").join(" ").split(term).length - 1;
        const contentHits = doc.lower.split(term).length - 1;
        if (pathHits + contentHits === 0) return null;
        score += pathHits * 8 + Math.min(contentHits, 40);
      }
      const at = doc.lower.indexOf(terms[0]);
      const snippet = at < 0 ? doc.content.slice(0, 180) : doc.content.slice(Math.max(0, at - 80), Math.min(doc.content.length, at + 160)).replace(/\s+/g, " ");
      return { ...doc, score, snippet };
    }).filter((item): item is NonNullable<typeof item> => item !== null).sort((a, b) => b.score - a.score).slice(0, 40);
  }, [documents, query]);
  return <div className="workspace-search">
    <header className="workspace-search-head"><div><span className="context-label">CONTEXT ENGINE</span><h3>Recherche dans le projet</h3><p>Index lexical local, sans envoyer le code à un service externe.</p></div><Sparkles size={18} /></header>
    <button type="button" className="index-build-btn" disabled={indexing} onClick={() => void buildIndex()}>{indexing ? <><LoaderCircle size={14} className="spin" /> Indexation {progress.done}/{progress.total || "…"}</> : <><FileSearch size={14} /> {documents.length ? "Reconstruire l’index" : "Indexer le workspace"}</>}</button>
    {indexedAt && <div className="index-meta">{documents.length} fichiers indexés · dernière indexation à {indexedAt}</div>}
    {indexing && <div className="index-progress"><i style={{ width: `${progress.total ? progress.done / progress.total * 100 : 4}%` }} /></div>}
    <label className="workspace-search-input"><Search size={14} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher une fonction, un composant…" /></label>
    {error && <p className="mcp-error">{error}</p>}
    {!documents.length && !indexing ? <div className="mcp-empty"><Search size={24} /><strong>Votre projet, sous la loupe</strong><span>Lancez l’indexation pour rechercher dans les fichiers du workspace.</span></div> :
      <div className="workspace-search-results">{query.trim() && results.length === 0 && <p className="context-empty">Aucun résultat pour cette recherche.</p>}
        {results.map((result) => <article key={result.path} className="workspace-result">
          <button type="button" className="workspace-result-open" onClick={() => onOpen(result.path)}><strong>{result.path}</strong><span>{result.snippet}</span></button>
          <button type="button" className="tiny-icon" onClick={() => onMention(result.path)} title="Ajouter au contexte">@</button>
        </article>)}
        {!query.trim() && <p className="context-empty">Saisissez un terme pour explorer les {documents.length} fichiers indexés.</p>}
      </div>}
    <p className="index-footnote">Limites : 600 fichiers, 256 Ko par fichier. Les secrets, binaires et dépendances sont exclus. Réindexez après des changements importants.</p>
  </div>;
}
