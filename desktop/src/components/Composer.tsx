import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import type { ClipboardEvent, DragEvent, KeyboardEvent } from "react";
import { ArrowUp, AtSign, Bot, Brain, Gauge, ImagePlus, Square, Users, X } from "lucide-react";
import type { AttachedImage, SubagentRole } from "../types";

export interface SlashCommand {
  name: string;
  args?: string;
  description: string;
}

export interface ComposerHandle { focus: () => void }

type Suggestion = { key: string; label: string; detail?: string; apply: () => void };

const MAX_IMAGES = 4;
const MAX_IMAGE_BYTES = 5_500_000;
const ACCEPTED_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

function formatTokens(value: number) {
  if (value >= 1_000_000) return (value / 1_000_000).toFixed(1) + " M";
  if (value >= 1000) return (value / 1000).toFixed(1) + " k";
  return String(value);
}

function readImageFile(file: File): Promise<AttachedImage> {
  return new Promise((resolve, reject) => {
    if (!ACCEPTED_TYPES.has(file.type)) {
      reject(new Error("Formats acceptés : PNG, JPEG, WebP ou GIF."));
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      reject(new Error(`Image trop lourde (${(file.size / (1024 * 1024)).toFixed(1)} Mo, max 5,5 Mo).`));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        resolve({
          id: Math.random().toString(36).slice(2, 10),
          name: file.name || "image.png",
          dataUrl: reader.result
        });
      } else {
        reject(new Error("Lecture de l’image impossible."));
      }
    };
    reader.onerror = () => reject(new Error("Lecture de l’image impossible."));
    reader.readAsDataURL(file);
  });
}

const Composer = forwardRef<ComposerHandle, {
  draft: string;
  setDraft: (value: string) => void;
  images: AttachedImage[];
  onAddImages: (items: AttachedImage[]) => void;
  onRemoveImage: (id: string) => void;
  onError: (message: string) => void;
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
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [active, setActive] = useState(0);
  const [dismissed, setDismissed] = useState("");
  const [dragging, setDragging] = useState(false);
  useImperativeHandle(ref, () => ({ focus: () => areaRef.current?.focus() }), []);

  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = Math.min(area.scrollHeight, 220) + "px";
  }, [props.draft]);

  const ingestFiles = async (fileList: FileList | File[]) => {
    const incoming = Array.from(fileList).filter((file) => file.type.startsWith("image/"));
    if (incoming.length === 0) return;
    const room = MAX_IMAGES - props.images.length;
    if (room <= 0) {
      props.onError(`Maximum ${MAX_IMAGES} images par message.`);
      return;
    }
    const added: AttachedImage[] = [];
    for (const file of incoming.slice(0, room)) {
      try {
        added.push(await readImageFile(file));
      } catch (reason) {
        props.onError(reason instanceof Error ? reason.message : String(reason));
      }
    }
    if (added.length > 0) props.onAddImages(added);
  };

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const items = Array.from(event.clipboardData?.items ?? []);
    const files = items
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    if (files.length > 0) {
      event.preventDefault();
      void ingestFiles(files);
    }
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer?.files?.length) void ingestFiles(event.dataTransfer.files);
  };

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
  const canSend = (props.draft.trim().length > 0 || props.images.length > 0) && !disabled;

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
      <div
        className={"composer" + (props.busy ? " working" : "") + (dragging ? " dragging" : "")}
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        {props.images.length > 0 && (
          <div className="composer-images" aria-label="Images jointes">
            {props.images.map((image) => (
              <div className="composer-thumb" key={image.id} title={image.name}>
                <img src={image.dataUrl} alt={image.name} />
                <button type="button" onClick={() => props.onRemoveImage(image.id)} aria-label={`Retirer ${image.name}`}><X size={11} /></button>
              </div>
            ))}
          </div>
        )}
        <textarea ref={areaRef} rows={1} value={props.draft} disabled={!props.ready || props.blocked}
          placeholder={props.ready ? props.placeholder : "Connexion à l’agent…"}
          onChange={(event) => { props.setDraft(event.target.value); setDismissed(""); }}
          onKeyDown={onKeyDown}
          onPaste={onPaste} />
        <input ref={fileInputRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden
          onChange={(event) => { if (event.target.files) void ingestFiles(event.target.files); event.target.value = ""; }} />
        <div className="composer-bar">
          <div className="composer-left">
            <button type="button" className="tool-btn" title="Joindre une image (ou coller / glisser-déposer)"
              disabled={!props.ready || props.images.length >= MAX_IMAGES}
              onClick={() => fileInputRef.current?.click()}>
              <ImagePlus size={14} />
            </button>
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
        <span>/ commandes · @ fichiers · images acceptées</span>
      </div>
    </div>
  );
});

export default Composer;
