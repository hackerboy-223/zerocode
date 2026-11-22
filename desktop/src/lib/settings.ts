import { useCallback, useEffect, useState } from "react";
import type { RuntimeSettings } from "../types";

export type ThemePref = "system" | "light" | "dark";
export type Accent = "blue" | "violet" | "green" | "orange" | "rose";
export type ThinkLevel = "off" | "low" | "high" | "max";

export interface Settings {
  theme: ThemePref;
  accent: Accent;
  density: "comfortable" | "compact";
  fontSize: number;
  sendKey: "enter" | "mod-enter";
  autoScroll: boolean;
  showReasoning: boolean;
  showToolDetails: boolean;
  notifyOnDone: boolean;
  confirmRiskyModes: boolean;
  autoDelegate: boolean;
  defaultSubagentRole: string;
  /** Mode appliqué au démarrage. Full-stack n'est jamais restauré automatiquement. */
  defaultMode: "build" | "plan";
  preferredModel: string;
  preferredThink: ThinkLevel;
  /** Réglages d'exécution envoyés à l'agent à chaque démarrage. */
  runtime: Partial<RuntimeSettings>;
}

export const DEFAULT_SETTINGS: Settings = {
  theme: "system",
  accent: "blue",
  density: "comfortable",
  fontSize: 14,
  sendKey: "enter",
  autoScroll: true,
  showReasoning: true,
  showToolDetails: true,
  notifyOnDone: false,
  confirmRiskyModes: true,
  autoDelegate: false,
  defaultSubagentRole: "explorer",
  defaultMode: "build",
  preferredModel: "",
  preferredThink: "off",
  runtime: {}
};

export const DEFAULT_RUNTIME: RuntimeSettings = {
  max_steps: 40,
  command_timeout: 120,
  max_tokens: 8192,
  temperature: 0.2,
  compact_threshold: 0.75,
  auto_compact: true,
  task_routing: true,
  fallback: true,
  free_only: true,
  diff_view: true
};

const STORAGE_KEY = "zerocode.settings.v2";

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

function sanitize(raw: unknown): Settings {
  const source = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const flag = (key: keyof Settings, fallback: boolean) => (typeof source[key] === "boolean" ? (source[key] as boolean) : fallback);
  const size = Number(source.fontSize);
  const runtime: Partial<RuntimeSettings> = {};
  if (source.runtime && typeof source.runtime === "object") {
    for (const [key, value] of Object.entries(source.runtime as Record<string, unknown>)) {
      if (key in DEFAULT_RUNTIME && typeof value === typeof DEFAULT_RUNTIME[key as keyof RuntimeSettings]) {
        (runtime as Record<string, unknown>)[key] = value;
      }
    }
  }
  return {
    theme: oneOf(source.theme, ["system", "light", "dark"] as const, DEFAULT_SETTINGS.theme),
    accent: oneOf(source.accent, ["blue", "violet", "green", "orange", "rose"] as const, DEFAULT_SETTINGS.accent),
    density: oneOf(source.density, ["comfortable", "compact"] as const, DEFAULT_SETTINGS.density),
    fontSize: Number.isFinite(size) && size >= 12 && size <= 17 ? Math.round(size) : DEFAULT_SETTINGS.fontSize,
    sendKey: oneOf(source.sendKey, ["enter", "mod-enter"] as const, DEFAULT_SETTINGS.sendKey),
    autoScroll: flag("autoScroll", DEFAULT_SETTINGS.autoScroll),
    showReasoning: flag("showReasoning", DEFAULT_SETTINGS.showReasoning),
    showToolDetails: flag("showToolDetails", DEFAULT_SETTINGS.showToolDetails),
    notifyOnDone: flag("notifyOnDone", DEFAULT_SETTINGS.notifyOnDone),
    confirmRiskyModes: flag("confirmRiskyModes", DEFAULT_SETTINGS.confirmRiskyModes),
    autoDelegate: flag("autoDelegate", DEFAULT_SETTINGS.autoDelegate),
    defaultSubagentRole: typeof source.defaultSubagentRole === "string" && source.defaultSubagentRole
      ? source.defaultSubagentRole : DEFAULT_SETTINGS.defaultSubagentRole,
    defaultMode: oneOf(source.defaultMode, ["build", "plan"] as const, DEFAULT_SETTINGS.defaultMode),
    preferredModel: typeof source.preferredModel === "string" ? source.preferredModel.slice(0, 120) : "",
    preferredThink: oneOf(source.preferredThink, ["off", "low", "high", "max"] as const, DEFAULT_SETTINGS.preferredThink),
    runtime
  };
}

function load(): Settings {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return sanitize(JSON.parse(stored));
    // Migration de l'ancien réglage de thème.
    const legacy = localStorage.getItem("zerocode.theme");
    return sanitize(legacy === "light" || legacy === "dark" ? { theme: legacy } : {});
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(load);
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(settings)); } catch { /* stockage indisponible */ }
  }, [settings]);
  const update = useCallback((patch: Partial<Settings>) => setSettings((current) => ({ ...current, ...patch })), []);
  const reset = useCallback(() => setSettings({ ...DEFAULT_SETTINGS }), []);
  return { settings, update, reset };
}

export function useResolvedTheme(pref: ThemePref): "light" | "dark" {
  const query = "(prefers-color-scheme: dark)";
  const system = () => (typeof window !== "undefined" && window.matchMedia?.(query).matches ? "dark" : "light");
  const [systemTheme, setSystemTheme] = useState<"light" | "dark">(system);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const onChange = () => setSystemTheme(media.matches ? "dark" : "light");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return pref === "system" ? systemTheme : pref;
}
