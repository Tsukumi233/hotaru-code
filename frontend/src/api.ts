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
  list: (projectId: string) =>
    requestJson<Session[]>(`/v1/session?project_id=${encodeURIComponent(projectId)}`),
  create: (payload: Record<string, unknown>) =>
    requestJson<Session>("/v1/session", { method: "POST", body: JSON.stringify(payload) }),
  messages: (id: string) =>
    requestJson<Array<Record<string, unknown>>>(`/v1/session/${encodeURIComponent(id)}/message`),
  send: (id: string, payload: Record<string, unknown>) =>
    requestJson(`/v1/session/${encodeURIComponent(id)}/message`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  interrupt: (id: string) =>
    requestJson(`/v1/session/${encodeURIComponent(id)}/interrupt`, { method: "POST" }),
};

export const providers = {
  list: () => requestJson<Array<Record<string, unknown>>>("/v1/provider"),
  models: (id: string) =>
    requestJson<ProviderModel[]>(`/v1/provider/${encodeURIComponent(id)}/model`),
};

export const agents = {
  list: () => requestJson<Agent[]>("/v1/agent"),
};

export const permissions = {
  list: () => requestJson<Permission[]>("/v1/permission"),
  reply: (id: string, reply: string) =>
    requestJson(`/v1/permission/${encodeURIComponent(id)}/reply`, {
      method: "POST",
      body: JSON.stringify({ reply }),
    }),
};

export const questions = {
  list: () => requestJson<Question[]>("/v1/question"),
  reply: (id: string, answers: string[][]) =>
    requestJson(`/v1/question/${encodeURIComponent(id)}/reply`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),
  reject: (id: string) =>
    requestJson(`/v1/question/${encodeURIComponent(id)}/reject`, { method: "POST" }),
};

export const pty = {
  create: () => requestJson<{ id: string }>("/v1/pty", { method: "POST", body: JSON.stringify({}) }),
  close: (id: string) =>
    requestJson(`/v1/pty/${encodeURIComponent(id)}`, { method: "DELETE" }).catch(() => {}),
  resize: (id: string, cols: number, rows: number) =>
    fetch(`/v1/pty/${id}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ cols, rows }),
    }).catch(() => {}),
};
