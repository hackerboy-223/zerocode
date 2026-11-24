import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Brain, Check, ChevronRight, Clipboard, RotateCcw, Users, X } from "lucide-react";
import Lupus from "./Lupus";
import { FormattedMessage } from "../lib/markdown";
import type { ChatMessage, SubagentRun, ToolActivity } from "../types";

type Entry =
  | { kind: "message"; seq: number; message: ChatMessage }
  | { kind: "tools"; seq: number; items: ToolActivity[] }
  | { kind: "subagent"; seq: number; run: SubagentRun };

function argSummary(args?: Record<string, unknown>) {
  if (!args) return "";
  for (const key of ["path", "command", "pattern", "query", "url", "task", "file"]) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) return value.replace(/\s+/g, " ").slice(0, 90);
  }
  return "";
}

function ToolGroup({ items, details }: { items: ToolActivity[]; details: boolean }) {
  const [open, setOpen] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const running = items.some((item) => item.status === "running");
  const failed = items.filter((item) => item.status === "error").length;
  const summary = running ? `${items.length} action${items.length > 1 ? "s" : ""} en cours…`
    : `${items.length} action${items.length > 1 ? "s" : ""}${failed ? ` · ${failed} à vérifier` : ""}`;
  return (
    <div className={"tool-group" + (running ? " running" : "") + (failed ? " has-error" : "")}>
      <button type="button" className="tool-group-head" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        {running ? <span className="spinner" /> : failed ? <X size={13} /> : <Check size={13} />}
        <span>{summary}</span>
        <em>{items.slice(-3).map((item) => item.name).join(" · ")}</em>
        <ChevronRight size={13} className={open ? "turn" : ""} />
      </button>
      {(open || running) && (
        <div className="tool-rows">
          {items.map((item) => {
            const expanded = openId === item.id && details;
            return (
              <div key={item.id} className={"tool-row " + item.status}>
                <button type="button" onClick={() => details && setOpenId(expanded ? null : item.id)} disabled={!details}>
                  <span className="tool-mark">{item.status === "running" ? <span className="spinner small" /> : item.status === "success" ? <Check size={11} /> : <X size={11} />}</span>
                  <strong>{item.name}</strong>
                  <span className="tool-arg">{argSummary(item.arguments)}</span>
                </button>
                {expanded && (
                  <pre className="tool-detail">
                    {item.arguments && Object.keys(item.arguments).length > 0 ? `Arguments\n${JSON.stringify(item.arguments, null, 2)}\n\n` : ""}
                    {item.output ? `Sortie\n${item.output}\n\n` : ""}
                    {item.result ? `Résultat\n${item.result}` : "En cours…"}
                  </pre>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SubagentCard({ run, onOpen }: { run: SubagentRun; onOpen: (id: string) => void }) {
  return (
    <button type="button" className={"subagent-card " + run.status} onClick={() => onOpen(run.id)} title="Voir dans le panneau Agents">
      <span className="subagent-icon">{run.status === "running" ? <span className="spinner" /> : run.status === "done" ? <Users size={14} /> : <X size={14} />}</span>
      <span className="subagent-copy">
        <strong>Sous-agent · {run.role}</strong>
        <em>{run.task}</em>
      </span>
      <small>{run.status === "running" ? `${run.tools.length} outil(s)` : run.status === "done" ? "terminé" : run.status === "stopped" ? "interrompu" : "échec"}</small>
    </button>
  );
}

export default function ChatView({ messages, activities, subagents, busy, ready, workspaceName, autoScroll, showReasoning, showToolDetails, suggestions, onSuggestion, onCopy, onRetry, onOpenRun }: {
  messages: ChatMessage[]; activities: ToolActivity[]; subagents: SubagentRun[]; busy: boolean; ready: boolean;
  workspaceName: string | null; autoScroll: boolean; showReasoning: boolean; showToolDetails: boolean;
  suggestions: Array<{ title: string; prompt: string }>; onSuggestion: (prompt: string) => void;
  onCopy: (text: string) => void; onRetry: () => void; onOpenRun: (id: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const stickRef = useRef(true);

  const entries = useMemo<Entry[]>(() => {
    const raw: Entry[] = [
      ...messages.map((message) => ({ kind: "message" as const, seq: message.seq, message })),
      ...activities.filter((item) => item.name !== "subagent").map((item) => ({ kind: "tools" as const, seq: item.seq, items: [item] })),
      ...subagents.map((run) => ({ kind: "subagent" as const, seq: run.seq, run }))
    ].sort((a, b) => a.seq - b.seq);
    const merged: Entry[] = [];
    for (const entry of raw) {
      const last = merged[merged.length - 1];
      if (entry.kind === "tools" && last?.kind === "tools") last.items.push(...entry.items);
      else merged.push(entry.kind === "tools" ? { ...entry, items: [...entry.items] } : entry);
    }
    return merged;
  }, [messages, activities, subagents]);

  const lastText = messages[messages.length - 1]?.content.length ?? 0;
  useEffect(() => {
    const node = scrollRef.current;
    if (node && autoScroll && stickRef.current) node.scrollTop = node.scrollHeight;
  }, [entries.length, lastText, autoScroll]);

  const lastAssistantId = [...messages].reverse().find((message) => message.role === "assistant" && message.content)?.id;
  const hasUser = messages.some((message) => message.role === "user");

  if (messages.length === 0 && subagents.length === 0 && activities.length === 0) {
    return (
      <div className="chat-scroll" ref={scrollRef}>
        <motion.div className="empty-state" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
          <Lupus size="large" calm />
          <h1>{ready ? (workspaceName ? "Que construit-on ?" : "Comment puis-je aider ?") : "Connexion à ZeroCode…"}</h1>
          <p>{workspaceName ? <>Projet <strong>{workspaceName}</strong> · tout reste sur votre machine.</> : "Aucun projet requis. Ouvrez un dossier pour que l’agent lise, modifie et teste votre code."}</p>
          <div className="starter-grid">
            {suggestions.map((idea) => (
              <button type="button" key={idea.title} className="starter" disabled={!ready || busy} onClick={() => onSuggestion(idea.prompt)}>
                <strong>{idea.title}</strong><span>{idea.prompt}</span>
              </button>
            ))}
          </div>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="chat-scroll" ref={scrollRef} onScroll={(event) => {
      const node = event.currentTarget;
      stickRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 140;
    }}>
      <div className="thread">
        {entries.map((entry) => {
          if (entry.kind === "tools") return <ToolGroup key={"t" + entry.seq} items={entry.items} details={showToolDetails} />;
          if (entry.kind === "subagent") return <SubagentCard key={"s" + entry.run.id} run={entry.run} onOpen={onOpenRun} />;
          const { message } = entry;
          if (message.role === "user") {
            return (
              <motion.article key={message.id} className="msg user" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
                <div className="bubble">
                  {message.images && message.images.length > 0 && (
                    <div className="msg-images">
                      {message.images.map((src, index) => <img key={index} src={src} alt={`Image jointe ${index + 1}`} />)}
                    </div>
                  )}
                  {message.content}
                </div>
              </motion.article>
            );
          }
          const empty = !message.content && !message.reasoning;
          if (empty && !busy) return null;
          return (
            <article key={message.id} className="msg assistant">
              {showReasoning && message.reasoning && (
                <details className="reasoning">
                  <summary><Brain size={12} /> Raisonnement</summary>
                  <pre>{message.reasoning}</pre>
                </details>
              )}
              {message.content ? <FormattedMessage content={message.content} onCopy={onCopy} /> : busy && <span className="typing" aria-label="L’agent réfléchit"><i /><i /><i /></span>}
              {message.content && (
                <div className="msg-actions">
                  <button type="button" onClick={() => onCopy(message.content)} title="Copier"><Clipboard size={12} /></button>
                  {message.id === lastAssistantId && hasUser && !busy && <button type="button" onClick={onRetry} title="Régénérer la réponse"><RotateCcw size={12} /></button>}
                </div>
              )}
            </article>
          );
        })}
        {busy && messages[messages.length - 1]?.role === "user" && <article className="msg assistant"><span className="typing"><i /><i /><i /></span></article>}
      </div>
    </div>
  );
}
