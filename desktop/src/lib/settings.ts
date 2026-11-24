import { useCallback, useEffect, useState } from "react";
import {
  DEFAULT_RUNTIME,
  DEFAULT_SETTINGS,
  sanitizeSettings,
  type Accent,
  type Settings,
  type ThemePref,
  type ThinkLevel
} from "./settingsCore";

export {
  DEFAULT_RUNTIME,
  DEFAULT_SETTINGS,
  sanitizeSettings,
  type Accent,
  type Settings,
  type ThemePref,
  type ThinkLevel
};

const STORAGE_KEY = "zerocode.settings.v2";

function load(): Settings {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return sanitizeSettings(JSON.parse(stored));
    // Migration de l'ancien réglage de thème.
    const legacy = localStorage.getItem("zerocode.theme");
    return sanitizeSettings(legacy === "light" || legacy === "dark" ? { theme: legacy } : {});
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
