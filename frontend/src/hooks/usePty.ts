import { useState } from "react";
import type { LocalPty } from "../types";
import * as api from "../api";

export function usePty() {
  const [terminals, setTerminals] = useState<LocalPty[]>([]);
  const [activeTerm, setActiveTerm] = useState("");
  const [termOpen, setTermOpen] = useState(false);

  async function createPty(): Promise<void> {
    const result = await api.pty.create();
    setTerminals((prev) => [...prev, { id: result.id, title: "" }]);
    setActiveTerm(result.id);
  }

  async function closePty(id: string): Promise<void> {
    await api.pty.close(id);
    setTerminals((prev) => {
      const next = prev.filter((t) => t.id !== id);
      if (activeTerm === id) setActiveTerm(next.length > 0 ? next[next.length - 1].id : "");
      if (next.length === 0) setTermOpen(false);
      return next;
    });
  }

  function persistPty(pty: LocalPty): void {
    setTerminals((prev) =>
      prev.map((t) =>
        t.id === pty.id ? { ...t, buffer: pty.buffer, cursor: pty.cursor, rows: pty.rows, cols: pty.cols } : t,
      ),
    );
  }

  async function toggleTerminal(): Promise<void> {
    if (termOpen) {
      setTermOpen(false);
      return;
    }
    setTermOpen(true);
    if (terminals.length === 0) await createPty();
  }

  function removePty(id: string): void {
    setTerminals((prev) => {
      const next = prev.filter((t) => t.id !== id);
      if (activeTerm === id) setActiveTerm(next.length > 0 ? next[next.length - 1].id : "");
      if (next.length === 0) setTermOpen(false);
      return next;
    });
  }

  return { terminals, activeTerm, termOpen, setActiveTerm, setTermOpen, createPty, closePty, persistPty, toggleTerminal, removePty };
}
