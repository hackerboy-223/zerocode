import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { ChevronDown, ChevronUp, Maximize2, SquareTerminal } from "lucide-react";
import { desktopInvoke, isTauri, listen } from "../lib/desktop";

import "@xterm/xterm/css/xterm.css";

interface TerminalPanelProps {
  cwd: string | null;
  open: boolean;
  onToggle: () => void;
}

interface OutputEvent {
  id: string;
  data: number[];
}

export default function TerminalPanel({ cwd, open, onToggle }: TerminalPanelProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const sessionRef = useRef<string | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !cwd) return;

    const terminal = new Terminal({
      cursorBlink: true,
      fontFamily: '"SFMono-Regular", "Cascadia Code", "JetBrains Mono", monospace',
      fontSize: 12.5,
      lineHeight: 1.42,
      scrollback: 4000,
      convertEol: true,
      theme: {
        background: "#11151c",
        foreground: "#d8e0eb",
        cursor: "#78baff",
        selectionBackground: "#31557a80",
        black: "#1b2029",
        red: "#ed7c80",
        green: "#8bcf9a",
        yellow: "#e6bd74",
        blue: "#78baff",
        magenta: "#c8a5ef",
        cyan: "#7fc9d5",
        white: "#d8e0eb",
        brightBlack: "#657184",
        brightWhite: "#f5f7fb"
      }
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.loadAddon(new WebLinksAddon());
    terminal.open(host);
    terminalRef.current = terminal;
    fitRef.current = fit;

    let unlisten: (() => void) | undefined;
    let observer: ResizeObserver | undefined;
    let alive = true;

    const connect = async () => {
      if (!isTauri()) {
        terminal.writeln("\x1b[90mLe terminal local est disponible dans l’application native.\x1b[0m");
        return;
      }
      try {
        unlisten = await listen<OutputEvent>("terminal-output", (event) => {
          if (event.payload.id === sessionRef.current && terminalRef.current) {
            terminalRef.current.write(Uint8Array.from(event.payload.data));
          }
        });
        const id = await desktopInvoke<string>("start_terminal", { cwd });
        if (!alive) {
          await desktopInvoke("stop_terminal", { terminalId: id }).catch(() => undefined);
          return;
        }
        sessionRef.current = id;
        setConnected(true);
        fit.fit();
        await desktopInvoke("resize_terminal", {
          terminalId: id,
          cols: terminal.cols,
          rows: terminal.rows
        });
        terminal.onData((data) => {
          desktopInvoke("write_terminal", { terminalId: id, data }).catch(() => undefined);
        });
        observer = new ResizeObserver(() => {
          fit.fit();
          desktopInvoke("resize_terminal", {
            terminalId: id,
            cols: terminal.cols,
            rows: terminal.rows
          }).catch(() => undefined);
        });
        observer.observe(host);
      } catch (error) {
        terminal.writeln("\x1b[31mImpossible de démarrer le terminal local.\x1b[0m");
        terminal.writeln(String(error));
      }
    };

    void connect();
    return () => {
      alive = false;
      observer?.disconnect();
      unlisten?.();
      const id = sessionRef.current;
      sessionRef.current = null;
      if (id && isTauri()) void desktopInvoke("stop_terminal", { terminalId: id }).catch(() => undefined);
      terminal.dispose();
      terminalRef.current = null;
      fitRef.current = null;
      setConnected(false);
    };
  }, [cwd]);

  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => {
      fitRef.current?.fit();
    });
    return () => cancelAnimationFrame(frame);
  }, [open]);

  return (
    <section className={"terminal-panel" + (open ? " terminal-open" : " terminal-closed")}>
      <header className="terminal-header">
        <div className="terminal-title">
          <SquareTerminal size={15} />
          <span>Terminal</span>
          <i className={connected ? "connection-dot is-connected" : "connection-dot"} />
          <small>{connected ? "session locale" : cwd ? "initialisation" : "en attente"}</small>
        </div>
        <div className="terminal-actions">
          <button className="icon-button terminal-expand" title="Agrandir le terminal" onClick={onToggle}>
            <Maximize2 size={14} />
          </button>
          <button className="icon-button" title={open ? "Réduire" : "Afficher"} onClick={onToggle}>
            {open ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
          </button>
        </div>
      </header>
      <div className="terminal-body" ref={hostRef} />
    </section>
  );
}
