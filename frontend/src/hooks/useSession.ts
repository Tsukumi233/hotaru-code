import { useState } from "react";
import type { Session } from "../types";
import * as api from "../api";

const PROJECT_ID = "default";

export function useSession() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [active, setActive] = useState("");

  async function loadSessions(): Promise<void> {
    const list = await api.sessions.list(PROJECT_ID);
    setSessions([...list].sort((a, b) => Number(b.time?.updated ?? 0) - Number(a.time?.updated ?? 0)));
  }

  async function switchSession(id: string, loadMessages: (id: string) => Promise<void>, loadPending: (sid: string) => Promise<void>): Promise<void> {
    setActive(id);
    await Promise.all([loadMessages(id), loadPending(id)]);
  }

  async function createSession(agent: string, modelRef: string, loadMessages: (id: string) => Promise<void>, loadPending: (sid: string) => Promise<void>): Promise<string> {
    if (active) return active;
    const payload: Record<string, unknown> = { project_id: PROJECT_ID };
    if (agent) payload.agent = agent;
    if (modelRef) payload.model = modelRef;
    const created = await api.sessions.create(payload);
    await loadSessions();
    await switchSession(created.id, loadMessages, loadPending);
    return created.id;
  }

  return { sessions, active, setActive, loadSessions, switchSession, createSession };
}
