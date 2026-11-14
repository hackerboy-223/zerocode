import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export { listen, isTauri };

export async function desktopInvoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (!isTauri()) {
    throw new Error("Cette action nécessite l’application ZeroCode Desktop.");
  }
  return invoke<T>(command, args);
}
