import { useCallback, useState } from "react";
import type { Message, Part, EventEnvelope } from "../types";
import { normalizeMessage, upsertMessage, upsertPart } from "../utils/messages";
import * as api from "../api";

export function useMessages() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState("idle");

  async function loadMessages(sessionId: string): Promise<void> {
    const list = await api.sessions.messages(sessionId);
    setMessages(list.map((item) => normalizeMessage(item)).sort((a, b) => a.id.localeCompare(b.id)));
  }

  const applyEvent = useCallback((env: EventEnvelope, loadPending: () => void) => {
    if (env.type === "session.status") {
      const state = env.data.status as Record<string, unknown> | undefined;
      if (state) setStatus(String(state.type ?? "idle"));
      return;
    }

    if (env.type === "message.updated") {
      const info = env.data.info as Record<string, unknown> | undefined;
      if (!info) return;
      setMessages((prev) => upsertMessage(prev, normalizeMessage({ id: info.id, role: info.role, info, parts: [] })));
      return;
    }

    if (env.type === "message.part.updated") {
      const part = env.data.part as Part | undefined;
      if (!part) return;
      const msgId = String(part.message_id ?? "");
      if (!msgId) return;
      setMessages((prev) => {
        const idx = prev.findIndex((item) => item.id === msgId);
        if (idx < 0) return [...prev, upsertPart({ id: msgId, role: "assistant", parts: [] }, part)];
        const out = [...prev];
        out[idx] = upsertPart(out[idx], part);
        return out;
      });
      return;
    }

    if (env.type === "message.part.delta") {
      const msgId = String(env.data.message_id ?? "");
      const partId = String(env.data.part_id ?? "");
      const delta = String(env.data.delta ?? "");
      if (!msgId || !partId || !delta) return;
      setMessages((prev) =>
        prev.map((item) => {
          if (item.id !== msgId) return item;
          return {
            ...item,
            parts: item.parts.map((part) => {
              if (String(part.id ?? "") !== partId) return part;
              return { ...part, text: String(part.text ?? "") + delta };
            }),
          };
        }),
      );
      return;
    }

    if (env.type.startsWith("permission.") || env.type.startsWith("question.")) {
      loadPending();
    }
  }, []);

  return { messages, status, setStatus, setMessages, loadMessages, applyEvent };
}
