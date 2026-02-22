import { useEffect, useRef } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { SerializeAddon } from "@xterm/addon-serialize";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import type { LocalPty } from "./types";

type TerminalProps = {
  pty: LocalPty;
  onPersist?: (pty: LocalPty) => void;
};

export default function Terminal({ pty, onPersist }: TerminalProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const style = getComputedStyle(document.documentElement);
    const term = new XTerm({
      theme: {
        background: style.getPropertyValue("--terminal-bg").trim() || "#1a1a2e",
        foreground: style.getPropertyValue("--terminal-fg").trim() || "#d4d4d8",
        cursor: style.getPropertyValue("--terminal-cursor").trim() || "#d4d4d8",
        selectionBackground: style.getPropertyValue("--terminal-selection").trim() || "#3b82f6cc",
      },
      fontFamily: '"IBM Plex Mono", "Consolas", monospace',
      fontSize: 14,
      scrollback: 10000,
      cursorBlink: true,
    });

    const fit = new FitAddon();
    const serialize = new SerializeAddon();
    term.loadAddon(fit);
    term.loadAddon(serialize);
    term.loadAddon(new WebLinksAddon());

    term.open(ref.current);
    fit.fit();

    if (pty.buffer) {
      term.write(pty.buffer);
    }

    const start = pty.cursor ?? 0;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/v1/ptys/${pty.id}/connect?cursor=${start}`);
    ws.binaryType = "arraybuffer";

    ws.onmessage = (evt) => {
      const bytes = new Uint8Array(evt.data as ArrayBuffer);
      if (bytes.length === 0) return;
      if (bytes[0] === 0x00) {
        const json = new TextDecoder().decode(bytes.slice(1));
        try {
          const ctrl = JSON.parse(json) as { cursor?: number };
          if (ctrl.cursor !== undefined) pty.cursor = ctrl.cursor;
        } catch {
          // ignore malformed control frames
        }
        return;
      }
      term.write(bytes);
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data);
    });

    let resizeTimer: ReturnType<typeof setTimeout> | undefined;
    term.onResize(({ cols, rows }) => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        fetch(`/v1/ptys/${pty.id}`, {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ size: { cols, rows } }),
        }).catch(() => {});
      }, 100);
    });

    const observer = new ResizeObserver(() => fit.fit());
    observer.observe(ref.current);

    return () => {
      observer.disconnect();
      clearTimeout(resizeTimer);
      if (onPersist) {
        try {
          onPersist({ ...pty, buffer: serialize.serialize(), rows: term.rows, cols: term.cols });
        } catch {
          // serialize may fail if terminal is disposed
        }
      }
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
      term.dispose();
    };
  }, [pty.id]);

  return <div ref={ref} className="w-full h-full p-1" />;
}
