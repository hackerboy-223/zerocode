import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { ArrowUp, AtSign, Bot, Brain, Gauge, Square, Users } from "lucide-react";
import type { SubagentRole } from "../types";

export interface SlashCommand {
  name: string;
  args?: string;
  description: string;
}

export interface ComposerHandle { focus: () => void }

type Suggestion = { key: string; label: string; detail?: string; apply: () => void };

function formatTokens(value: number) {
  if (value >= 1_000_000) return (value / 1_000_000).toFixed(1) + " M";
  if (value >= 1000) return (value / 1000).toFixed(1) + " k";
  return String(value);
}

const Composer = forwardRef<ComposerHandle, {
  draft: string;
  setDraft: (value: string) => void;
  onSend: () => void;
  onInterrupt: () => void;
  busy: boolean;
  ready: boolean;
  blocked: boolean;
  placeholder: string;
  sendKey: "enter" | "mod-enter";
  commands: SlashCommand[];
  files: string[];
  roles: SubagentRole[];
  model: string;
  provider: string;
  thinkMode: string;
  mode: string;
  usage: number;
  onOpenModel: () => void;
  onPickRole: (role: string) => void;
}>(function Composer(props, ref) {
  const areaRef = useRef<HTMLTextAreaElement | null>(null);
  const [active, setActive] = useState(0);
  const [dismissed, setDismissed] = useState("");
  useImperativeHandle(ref, () => ({ focus: () => areaRef.current?.focus() }), []);

  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = Math.min(area.scrollHeight, 220) + "px";
  }, [props.draft]);

  const suggestions = useMemo<Suggestion[]>(() => {
    if (dismissed === props.draft) return [];
    const slash = props.draft.match(/^\/(\S*)$/);
    if (slash) {
      const query = slash[1].toLowerCase();
      return props.commands
        .filter((command) => command.name.startsWith(query))
        .map((command) => ({
          key: command.name,
          label: "/" + command.name + (command.args ? " " + command.args : ""),
          detail: command.description,
          apply: () => props.setDraft("/" + command.name + (command.args ? " " : ""))
        }));
    }
    const mention = props.draft.match(/(^|\s)@([^\s]*)$/);
    if (mention) {
      const fragment = mention[2].toLowerCase();
      return props.files
        .filter((path) => path.toLowerCase().includes(fragment))
        .slice(0, 8)
        .map((path) => ({
          key: path,
          label: path,
          apply: () => props.setDraft(props.draft.replace(/@([^\s]*)$/, "@" + path + " "))
        }));
    }
    return [];
  }, [props.draft, props.commands, props.files, props.setDraft, dismissed]);

  useEffect(() => setActive(0), [props.draft]);

  const disabled = !props.ready || props.busy || props.blocked;
  const canSend = props.draft.trim().length > 0 && !disabled;

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (suggestions.length > 0) {
      if (event.key === "ArrowDown") { event.preventDefault(); setActive((value) => (value + 1) % suggestions.length); return; }
      if (event.key === "ArrowUp") { event.preventDefault(); setActive((value) => (value - 1 + suggestions.length) % suggestions.length); return; }
      const partialSlash = /^\/\S*$/.test(props.draft) && !props.commands.some((command) => "/" + command.name === props.draft.trim());
      const plainEnter = event.key === "Enter" && !event.shiftKey && !event.ctrlKey && !event.metaKey;
      if (event.key === "Tab" || (plainEnter && (partialSlash || /@[^\s]*$/.test(props.draft)))) {
        event.preventDefault(); suggestions[active]?.apply(); return;
      }
      if (event.key === "Escape") { event.preventDefault(); setDismissed(props.draft); return; }
    }
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    const modifier = event.ctrlKey || event.metaKey;
    if (props.sendKey === "enter" ? !modifier : modifier) {
      event.preventDefault();
      if (canSend) props.onSend();
    }
  };

  return (
    <div className="composer-wrap">
      {suggestions.length > 0 && (
        <div className="suggest-menu" role="listbox">
          {suggestions.map((item, index) => (
            <button type="button" role="option" aria-selected={index === active} key={item.key}
              className={index === active ? "suggest active" : "suggest"}
              onMouseEnter={() => setActive(index)} onMouseDown={(event) => { event.preventDefault(); item.apply(); areaRef.current?.focus(); }}>
              <code>{item.label}</code>{item.detail && <span>{item.detail}</span>}
            </button>
          ))}
        </div>
      )}
      <div className={"composer" + (props.busy ? " working" : "")}>
        <textarea ref={areaRef} rows={1} value={props.draft} disabled={!props.ready || props.blocked}
          placeholder={props.ready ? props.placeholder : "Connexion à l’agent…"}
          onChange={(event) => { props.setDraft(event.target.value); setDismissed(""); }} onKeyDown={onKeyDown} />
        <div className="composer-bar">
          <div className="composer-left">
            <button type="button" className="tool-btn" title="Mentionner un fichier (@)" onClick={() => { props.setDraft(props.draft + (props.draft && !props.draft.endsWith(" ") ? " @" : "@")); areaRef.current?.focus(); }}>
              <AtSign size={14} />
            </button>
            <label className="tool-btn role-picker" title="Déléguer à un sous-agent">
              <Users size={14} />
              <select value="" aria-label="Déléguer à un sous-agent" onChange={(event) => { if (event.target.value) props.onPickRole(event.target.value); }}>
                <option value="">Agent</option>
                {props.roles.map((role) => <option key={role.id} value={role.id}>{role.id}</option>)}
              </select>
            </label>
            <button type="button" className="tool-btn pill" onClick={props.onOpenModel} title="Modèle et raisonnement">
              <Bot size={13} /> <span>{props.model}</span>
              {props.provider && <em>{props.provider}</em>}
            </button>
            {props.thinkMode !== "off" && <span className="tool-btn pill static"><Brain size={13} /> {props.thinkMode}</span>}
            {props.mode !== "build" && <span className={"tool-btn pill static mode-" + props.mode}>{props.mode === "plan" ? "Plan" : "Full-stack"}</span>}
          </div>
          <div className="composer-right">
            {props.usage > 0 && <span className="usage" title="Jetons consommés dans cette session"><Gauge size={12} /> {formatTokens(props.usage)}</span>}
            {props.busy ? (
              <button type="button" className="send stop" onClick={props.onInterrupt} title="Arrêter" aria-label="Arrêter"><Square size={13} fill="currentColor" /></button>
            ) : (
              <button type="button" className="send" onClick={props.onSend} disabled={!canSend} title="Envoyer" aria-label="Envoyer"><ArrowUp size={16} /></button>
            )}
          </div>
        </div>
      </div>
      <div className="composer-hint">
        <span>{props.sendKey === "enter" ? "↵ envoyer · ⇧↵ ligne" : "Ctrl ↵ envoyer · ↵ ligne"}</span>
        <span>/ commandes · @ fichiers</span>
      </div>
    </div>
  );
});

export default Composer;
