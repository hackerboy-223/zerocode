import { useEffect, useState } from "react";
import type { ReactNode } from "react";

export function Toggle({ checked, onChange, disabled, label }: {
  checked: boolean; onChange: (value: boolean) => void; disabled?: boolean; label: string;
}) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled}
      className={"switch" + (checked ? " on" : "")} onClick={() => onChange(!checked)}>
      <i />
    </button>
  );
}

export function Segmented<T extends string>({ value, options, onChange, disabled, label }: {
  value: T; options: ReadonlyArray<{ id: T; label: string; hint?: string }>;
  onChange: (value: T) => void; disabled?: boolean; label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button type="button" key={option.id} title={option.hint} disabled={disabled}
          className={option.id === value ? "active" : ""} onClick={() => onChange(option.id)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Row({ title, hint, children, stacked }: { title: string; hint?: string; children: ReactNode; stacked?: boolean }) {
  return (
    <div className={"setting-row" + (stacked ? " stacked" : "")}>
      <div className="setting-copy"><strong>{title}</strong>{hint && <span>{hint}</span>}</div>
      <div className="setting-control">{children}</div>
    </div>
  );
}

/** Champ numérique validé à la validation (blur/Entrée) pour éviter d'envoyer chaque frappe. */
export function NumberField({ value, min, max, step = 1, suffix, onCommit, disabled }: {
  value: number; min: number; max: number; step?: number; suffix?: string;
  onCommit: (value: number) => void; disabled?: boolean;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    const parsed = Number(text);
    if (!Number.isFinite(parsed)) { setText(String(value)); return; }
    const clamped = Math.min(max, Math.max(min, parsed));
    setText(String(clamped));
    if (clamped !== value) onCommit(clamped);
  };
  return (
    <span className="number-field">
      <input type="number" inputMode="decimal" value={text} min={min} max={max} step={step} disabled={disabled}
        onChange={(event) => setText(event.target.value)} onBlur={commit}
        onKeyDown={(event) => { if (event.key === "Enter") (event.target as HTMLInputElement).blur(); }} />
      {suffix && <em>{suffix}</em>}
    </span>
  );
}
