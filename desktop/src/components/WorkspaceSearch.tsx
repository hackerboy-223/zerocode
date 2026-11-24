import { useEffect, useState } from "react";
import { LoaderCircle, Search, Sparkles } from "lucide-react";
import { desktopInvoke, isTauri } from "../lib/desktop";
import type { WorkspaceSearchMatch } from "../types";

export default function WorkspaceSearch({ workspace, onOpen, onMention }: {
  workspace: string;
  onOpen: (path: string) => void;
  onMention: (path: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<WorkspaceSearchMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setError("");
      setLoading(false);
      return;
    }
    if (!isTauri()) {
      setError("La recherche native nécessite l’application ZeroCode Desktop.");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    const timer = window.setTimeout(() => {
      desktopInvoke<WorkspaceSearchMatch[]>("search_workspace_files", {
        cwd: workspace,
        query: trimmed,
        limit: 60
      })
        .then((matches) => {
          if (!cancelled) setResults(matches);
        })
        .catch((reason) => {
          if (!cancelled) setError(String(reason));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [workspace, query]);

  return (
    <div className="workspace-search">
      <header className="workspace-search-head">
        <div>
          <span className="context-label">RECHERCHE NATIVE</span>
          <h3>Explorer le projet</h3>
          <p>Recherche instantanée côté Rust, sans envoyer le code à l’extérieur.</p>
        </div>
        <Sparkles size={17} />
      </header>

      <label className="workspace-search-input">
        {loading ? <LoaderCircle size={14} className="spin" /> : <Search size={14} />}
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Fonction, symbole, nom de fichier…"
          autoFocus
        />
      </label>

      {error && <p className="mcp-error">{error}</p>}

      {!query.trim() ? (
        <div className="mcp-empty">
          <Search size={24} />
          <strong>Recherche instantanée</strong>
          <span>Saisissez un mot-clé pour fouiller jusqu’à 4 000 fichiers du projet.</span>
        </div>
      ) : (
        <div className="workspace-search-results">
          {!loading && results.length === 0 && (
            <p className="context-empty">Aucun résultat pour « {query.trim()} ».</p>
          )}
          {results.map((result, idx) => (
            <article key={`${result.path}:${result.line}:${idx}`} className="workspace-result">
              <button
                type="button"
                className="workspace-result-open"
                onClick={() => onOpen(result.path)}
              >
                <strong>
                  {result.path}
                  <em className="result-line">:{result.line}</em>
                </strong>
                <span>{result.snippet || "(correspondance sur le chemin)"}</span>
              </button>
              <button
                type="button"
                className="tiny-icon"
                onClick={() => onMention(result.path)}
                title="Ajouter au contexte (@)"
              >
                @
              </button>
            </article>
          ))}
        </div>
      )}
      <p className="index-footnote">
        Les secrets (.env, clés), liens symboliques, binaires et dossiers générés (node_modules, .git, target) sont exclus.
      </p>
    </div>
  );
}
