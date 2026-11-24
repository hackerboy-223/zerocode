import { useEffect, useState } from "react";
import { Check, Clipboard, CornerDownLeft, Play, Users, X } from "lucide-react";
import { FormattedMessage } from "../lib/markdown";
import type { SubagentRole, SubagentRun } from "../types";

export const agentPresets = [
  {
    id: "review",
    title: "Revue complète",
    hint: "reviewer · security · tester",
    prompt: "Fais une revue complète des changements récents du projet. Lance en parallèle des sous-agents `reviewer`, `security` et `tester` (un appel `subagent` par rôle), puis synthétise leurs conclusions par gravité avec les chemins concernés."
  },
  {
    id: "audit",
    title: "Audit sécurité",
    hint: "security · researcher",
    prompt: "Réalise un audit de sécurité du projet. Utilise un sous-agent `security` pour les frontières de confiance et les secrets, et un sous-agent `researcher` pour vérifier les dépendances sensibles. Rends un rapport priorisé."
  },
  {
    id: "architecture",
    title: "Plan d’architecture",
    hint: "explorer · architect",
    prompt: "Explore le projet avec un sous-agent `explorer`, puis demande à un sous-agent `architect` de proposer un plan d’évolution minimal et cohérent. Présente le plan sans modifier de fichier."
  },
  {
    id: "performance",
    title: "Chasse aux lenteurs",
    hint: "performance · explorer",
    prompt: "Cherche les goulots d’étranglement probables avec un sous-agent `performance` et un sous-agent `explorer`. Ne propose que des optimisations mesurables et à faible risque."
  }
];

const statusLabel: Record<SubagentRun["status"], string> = {
  running: "en cours", done: "terminé", error: "échec", stopped: "interrompu"
};

function duration(ms?: number) {
  if (ms === undefined) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export default function AgentsPanel({ roles, runs, ready, busy, defaultRole, onRun, onPreset, onUseResult, onCopy }: {
  roles: SubagentRole[]; runs: SubagentRun[]; ready: boolean; busy: boolean; defaultRole: string;
  onRun: (role: string, task: string) => void; onPreset: (prompt: string) => void;
  onUseResult: (run: SubagentRun) => void; onCopy: (text: string) => void;
}) {
  const [role, setRole] = useState(defaultRole);
  const [task, setTask] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  useEffect(() => setRole(defaultRole), [defaultRole]);
  const runningCount = runs.filter((run) => run.status === "running").length;
  const canLaunchSubagent = ready && runningCount < 4;
  const lockedPreset = !ready || busy;
  const current = roles.find((item) => item.id === role);
  const ordered = [...runs].sort((a, b) => b.seq - a.seq);

  return (
    <div className="panel agents-panel">
      <div className="panel-section">
        <div className="panel-label">LANCER UN SPÉCIALISTE {runningCount > 0 && <span>{runningCount}/4 actifs</span>}</div>
        <div className="role-chips">
          {roles.map((item) => (
            <button type="button" key={item.id} className={item.id === role ? "chip active" : "chip"} onClick={() => setRole(item.id)} title={item.description}>{item.id}</button>
          ))}
        </div>
        {current && <p className="muted-note">{current.description}</p>}
        <textarea className="task-input" rows={3} value={task} onChange={(event) => setTask(event.target.value)}
          placeholder="Que doit analyser ce spécialiste ? (fichiers, question, périmètre…)"
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && task.trim() && canLaunchSubagent) { onRun(role, task.trim()); setTask(""); }
          }} />
        <button type="button" className="btn primary full" disabled={!canLaunchSubagent || !task.trim()} onClick={() => { onRun(role, task.trim()); setTask(""); }}>
          <Play size={13} /> Lancer <small>Ctrl ↵</small>
        </button>
        <p className="muted-note">Lecture seule · jusqu’à 4 spécialistes peuvent tourner en parallèle.</p>
      </div>

      <div className="panel-section">
        <div className="panel-label">ORCHESTRATIONS</div>
        <div className="preset-list">
          {agentPresets.map((preset) => (
            <button type="button" key={preset.id} className="preset" disabled={lockedPreset} onClick={() => onPreset(preset.prompt)}>
              <strong>{preset.title}</strong><span>{preset.hint}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="panel-section">
        <div className="panel-label">EXÉCUTIONS <span>{runs.length}</span></div>
        {ordered.length === 0 ? (
          <div className="empty-block"><Users size={22} /><span>Les sous-agents lancés par vous ou par l’agent principal apparaîtront ici.</span></div>
        ) : ordered.map((run) => {
          const expanded = openId === run.id;
          return (
            <article key={run.id} className={"run-card run-" + run.status}>
              <button type="button" className="run-head" onClick={() => setOpenId(expanded ? null : run.id)}>
                <span className="run-status">{run.status === "running" ? <span className="spinner" /> : run.status === "done" ? <Check size={13} /> : <X size={13} />}</span>
                <span className="run-title"><strong>{run.role}</strong><em>{run.task}</em></span>
                <small>{run.status === "running" ? `${run.tools.length} outil(s)` : duration(run.durationMs)}</small>
              </button>
              {run.status === "running" && run.tools.length > 0 && <div className="run-tools">{run.tools.slice(-6).map((name, index) => <code key={index}>{name}</code>)}</div>}
              {expanded && (
                <div className="run-body">
                  <div className="run-meta"><span>{statusLabel[run.status]}</span><span>{run.tools.length} outil(s)</span>{run.durationMs !== undefined && <span>{duration(run.durationMs)}</span>}</div>
                  {run.result ? <FormattedMessage content={run.result} onCopy={onCopy} /> : run.error ? <p className="error-text">{run.error}</p> : <p className="muted-note">Analyse en cours…</p>}
                  {run.result && (
                    <div className="run-actions">
                      <button type="button" className="btn small" onClick={() => onCopy(run.result || "")}><Clipboard size={12} /> Copier</button>
                      <button type="button" className="btn small" onClick={() => onUseResult(run)}><CornerDownLeft size={12} /> Utiliser dans le chat</button>
                    </div>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
