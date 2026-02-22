import { useEffect } from "react";
import type { EventEnvelope, LocalPty } from "../types";

type UseEventsProps = {
  active: string;
  applyEvent: (env: EventEnvelope, loadPending: () => void) => void;
  loadPending: () => void;
  setStatus: (status: string) => void;
  onPtyRemoved: (id: string) => void;
};

export function useEvents({ active, applyEvent, loadPending, setStatus, onPtyRemoved }: UseEventsProps) {
  useEffect(() => {
    if (!active) return;
    const stream = new EventSource(`/v1/event?session_id=${encodeURIComponent(active)}`);
    stream.onmessage = (msg) => {
      let env: EventEnvelope;
      try {
        env = JSON.parse(msg.data) as EventEnvelope;
      } catch {
        return;
      }

      if (env.type === "pty.exited" || env.type === "pty.deleted") {
        const id = String(env.data.id ?? "");
        if (id) onPtyRemoved(id);
        return;
      }

      applyEvent(env, loadPending);
    };
    stream.onerror = () => setStatus("reconnecting");
    return () => stream.close();
  }, [active]);
}
