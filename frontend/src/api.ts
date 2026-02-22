import type { Session, Provider, ProviderModel, Agent, Permission, Question, Message } from "./types";

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as T;
}

export const sessions = {
  list: (projectId?: string) =>
    requestJson<Session[]>(
      projectId ? `/v1/sessions?project_id=${encodeURIComponent(projectId)}` : "/v1/sessions"
    ),
  create: (payload: Record<string, unknown>) =>
    requestJson<Session>("/v1/sessions", { method: "POST", body: JSON.stringify(payload) }),
  messages: (id: string) =>
    requestJson<Array<Record<string, unknown>>>(`/v1/sessions/${encodeURIComponent(id)}/messages`),
  send: (id: string, payload: Record<string, unknown>) =>
    requestJson(`/v1/sessions/${encodeURIComponent(id)}/messages`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  interrupt: (id: string) =>
    requestJson(`/v1/sessions/${encodeURIComponent(id)}/interrupt`, { method: "POST" }),
};

export const providers = {
  list: () => requestJson<Array<Record<string, unknown>>>("/v1/providers"),
  models: (id: string) =>
    requestJson<ProviderModel[]>(`/v1/providers/${encodeURIComponent(id)}/models`),
};

export const agents = {
  list: () => requestJson<Agent[]>("/v1/agents"),
};

export const preferences = {
  current: () =>
    requestJson<{ agent?: string; provider_id?: string; model_id?: string }>("/v1/preferences/current"),
  update: (payload: { agent?: string; provider_id?: string; model_id?: string }) =>
    requestJson<{ agent?: string; provider_id?: string; model_id?: string }>("/v1/preferences/current", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
};

export const permissions = {
  list: () => requestJson<Permission[]>("/v1/permissions"),
  reply: (id: string, reply: string) =>
    requestJson(`/v1/permissions/${encodeURIComponent(id)}/reply`, {
      method: "POST",
      body: JSON.stringify({ reply }),
    }),
};

export const questions = {
  list: () => requestJson<Question[]>("/v1/questions"),
  reply: (id: string, answers: string[][]) =>
    requestJson(`/v1/questions/${encodeURIComponent(id)}/reply`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),
  reject: (id: string) =>
    requestJson(`/v1/questions/${encodeURIComponent(id)}/reject`, { method: "POST" }),
};

export const pty = {
  create: () => requestJson<{ id: string }>("/v1/ptys", { method: "POST", body: JSON.stringify({}) }),
  close: (id: string) =>
    requestJson(`/v1/ptys/${encodeURIComponent(id)}`, { method: "DELETE" }).catch(() => {}),
  resize: (id: string, cols: number, rows: number) =>
    fetch(`/v1/ptys/${id}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ size: { cols, rows } }),
    }).catch(() => {}),
};
