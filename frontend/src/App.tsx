import { FormEvent, useEffect, useMemo, useState } from "react";

type SessionTime = {
  updated?: number;
};

type Session = {
  id: string;
  title?: string;
  agent?: string;
  time?: SessionTime;
};

type PartState = {
  status?: string;
};

type Part = {
  id?: string;
  type?: string;
  text?: string;
  tool?: string;
  state?: PartState;
  session_id?: string;
  message_id?: string;
};

type Message = {
  id: string;
  role: string;
  info?: Record<string, unknown>;
  parts: Part[];
};

type ProviderModel = {
  id: string;
  name?: string;
};

type Provider = {
  id: string;
  name?: string;
  models: ProviderModel[];
};

type Agent = {
  name: string;
};

type Permission = {
  id: string;
  session_id?: string;
  permission?: string;
};

type Question = {
  id: string;
  session_id?: string;
  questions?: Array<{ question?: string }>;
};

type EventEnvelope = {
  type: string;
  data: Record<string, unknown>;
};

const PROJECT_ID = "default";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return (await res.json()) as T;
}

function normalizeMessage(item: Record<string, unknown>): Message {
  const info = (item.info as Record<string, unknown> | undefined) ?? {};
  const id = String(item.id ?? info.id ?? "");
  const role = String(item.role ?? info.role ?? "assistant");
  const parts = Array.isArray(item.parts) ? (item.parts as Part[]) : [];
  return { id, role, info, parts };
}

function upsertMessage(list: Message[], next: Message): Message[] {
  const idx = list.findIndex((item) => item.id === next.id);
  if (idx < 0) {
    return [...list, next];
  }
  const out = [...list];
  out[idx] = { ...out[idx], ...next, parts: out[idx].parts.length ? out[idx].parts : next.parts };
  return out;
}

function upsertPart(msg: Message, part: Part): Message {
  const id = String(part.id ?? "");
  if (!id) {
    return { ...msg, parts: [...msg.parts, part] };
  }
  const idx = msg.parts.findIndex((item) => String(item.id ?? "") === id);
  if (idx < 0) {
    return { ...msg, parts: [...msg.parts, part] };
  }
  const out = [...msg.parts];
  out[idx] = { ...out[idx], ...part };
  return { ...msg, parts: out };
}

function listModels(item: Provider): ProviderModel[] {
  return item.models;
}

export default function App() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [active, setActive] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState("idle");
  const [busy, setBusy] = useState(false);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [providerId, setProviderId] = useState("");
  const [modelId, setModelId] = useState("");
  const [agent, setAgent] = useState("build");
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [error, setError] = useState("");

  const modelRef = useMemo(() => {
    if (!providerId || !modelId) {
      return "";
    }
    return `${providerId}/${modelId}`;
  }, [providerId, modelId]);

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    if (!active) {
      return;
    }
    const stream = new EventSource(`/v1/event?session_id=${encodeURIComponent(active)}`);
    stream.onmessage = (msg) => {
      let env: EventEnvelope;
      try {
        env = JSON.parse(msg.data) as EventEnvelope;
      } catch {
        return;
      }
      applyEvent(env);
    };
    stream.onerror = () => {
      setStatus("reconnecting");
    };
    return () => stream.close();
  }, [active]);

  async function bootstrap(): Promise<void> {
    setError("");
    await Promise.all([loadProviders(), loadAgents(), loadSessions(false), loadPending(false)]);
  }

  async function loadSessions(selectFirst: boolean): Promise<void> {
    const list = await requestJson<Session[]>(`/v1/session?project_id=${encodeURIComponent(PROJECT_ID)}`);
    const sorted = [...list].sort((a, b) => Number(b.time?.updated ?? 0) - Number(a.time?.updated ?? 0));
    setSessions(sorted);
    if (selectFirst && sorted.length > 0) {
      await switchSession(sorted[0].id);
    }
  }

  async function loadProviders(): Promise<void> {
    const base = await requestJson<Array<Record<string, unknown>>>("/v1/provider");
    const result = await Promise.all(
      base.map(async (item) => {
        const id = String(item.id ?? "");
        if (!id) {
          return null;
        }
        const models = await requestJson<ProviderModel[]>(`/v1/provider/${encodeURIComponent(id)}/model`);
        return {
          id,
          name: String(item.name ?? id),
          models: models.map((model) => ({ id: String(model.id), name: String(model.name ?? model.id) }))
        } satisfies Provider;
      })
    );
    const clean = result.filter((item): item is Provider => item !== null);
    setProviders(clean);
    if (clean.length === 0) {
      return;
    }
    setProviderId((curr) => curr || clean[0].id);
    const first = clean[0].models[0];
    if (first) {
      setModelId((curr) => curr || first.id);
    }
  }

  async function loadAgents(): Promise<void> {
    const list = await requestJson<Agent[]>("/v1/agent");
    setAgents(list);
    if (list.length === 0) {
      return;
    }
    setAgent((curr) => curr || list[0].name);
  }

  async function loadMessages(sessionId: string): Promise<void> {
    const list = await requestJson<Array<Record<string, unknown>>>(`/v1/session/${encodeURIComponent(sessionId)}/message`);
    setMessages(list.map((item) => normalizeMessage(item)).sort((a, b) => a.id.localeCompare(b.id)));
  }

  async function switchSession(sessionId: string): Promise<void> {
    setActive(sessionId);
    await Promise.all([loadMessages(sessionId), loadPending(true, sessionId)]);
  }

  async function ensureSession(): Promise<string> {
    if (active) {
      return active;
    }
    const payload: Record<string, unknown> = { project_id: PROJECT_ID };
    if (agent) {
      payload.agent = agent;
    }
    if (modelRef) {
      payload.model = modelRef;
    }
    const created = await requestJson<Session>("/v1/session", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    await loadSessions(false);
    await switchSession(created.id);
    return created.id;
  }

  async function onSend(evt: FormEvent): Promise<void> {
    evt.preventDefault();
    const content = input.trim();
    if (!content) {
      return;
    }
    setError("");
    setBusy(true);
    setStatus("working");
    try {
      const sessionId = await ensureSession();
      const payload: Record<string, unknown> = { content };
      if (agent) {
        payload.agent = agent;
      }
      if (modelRef) {
        payload.model = modelRef;
      }
      await requestJson(`/v1/session/${encodeURIComponent(sessionId)}/message`, {
        method: "POST",
        body: JSON.stringify(payload)
      });
      setInput("");
      await Promise.all([loadSessions(false), loadMessages(sessionId), loadPending(true, sessionId)]);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onInterrupt(): Promise<void> {
    if (!active) {
      return;
    }
    await requestJson(`/v1/session/${encodeURIComponent(active)}/interrupt`, { method: "POST" });
    setStatus("interrupted");
  }

  async function loadPending(useFilter: boolean, sessionId?: string): Promise<void> {
    const [perms, asks] = await Promise.all([
      requestJson<Permission[]>("/v1/permission"),
      requestJson<Question[]>("/v1/question")
    ]);

    if (!useFilter || !sessionId) {
      setPermissions(perms);
      setQuestions(asks);
      return;
    }

    setPermissions(perms.filter((item) => String(item.session_id ?? "") === sessionId));
    setQuestions(asks.filter((item) => String(item.session_id ?? "") === sessionId));
  }

  async function replyPermission(id: string, reply: string): Promise<void> {
    await requestJson(`/v1/permission/${encodeURIComponent(id)}/reply`, {
      method: "POST",
      body: JSON.stringify({ reply })
    });
    await loadPending(Boolean(active), active || undefined);
  }

  async function replyQuestion(id: string, answers: string[][]): Promise<void> {
    await requestJson(`/v1/question/${encodeURIComponent(id)}/reply`, {
      method: "POST",
      body: JSON.stringify({ answers })
    });
    await loadPending(Boolean(active), active || undefined);
  }

  async function rejectQuestion(id: string): Promise<void> {
    await requestJson(`/v1/question/${encodeURIComponent(id)}/reject`, {
      method: "POST"
    });
    await loadPending(Boolean(active), active || undefined);
  }

  function applyEvent(env: EventEnvelope): void {
    if (env.type === "session.status") {
      const state = env.data.status as Record<string, unknown> | undefined;
      if (state) {
        setStatus(String(state.type ?? "idle"));
      }
      return;
    }

    if (env.type === "message.updated") {
      const info = env.data.info as Record<string, unknown> | undefined;
      if (!info) {
        return;
      }
      const msg = normalizeMessage({ id: info.id, role: info.role, info, parts: [] });
      setMessages((prev) => upsertMessage(prev, msg));
      return;
    }

    if (env.type === "message.part.updated") {
      const part = env.data.part as Part | undefined;
      if (!part) {
        return;
      }
      const msgId = String(part.message_id ?? "");
      if (!msgId) {
        return;
      }
      setMessages((prev) => {
        const idx = prev.findIndex((item) => item.id === msgId);
        if (idx < 0) {
          const next = upsertPart({ id: msgId, role: "assistant", parts: [] }, part);
          return [...prev, next];
        }
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
      if (!msgId || !partId || !delta) {
        return;
      }
      setMessages((prev) =>
        prev.map((item) => {
          if (item.id !== msgId) {
            return item;
          }
          const parts = item.parts.map((part) => {
            if (String(part.id ?? "") !== partId) {
              return part;
            }
            const text = String(part.text ?? "");
            return { ...part, text: text + delta };
          });
          return { ...item, parts };
        })
      );
      return;
    }

    if (env.type.startsWith("permission.") || env.type.startsWith("question.")) {
      void loadPending(Boolean(active), active || undefined);
    }
  }

  function currentModels(): ProviderModel[] {
    const hit = providers.find((item) => item.id === providerId);
    if (!hit) {
      return [];
    }
    return listModels(hit);
  }

  return (
    <div className="app">
      <header className="top">
        <div className="brand">hotaru webui</div>
        <div className="controls">
          <label>
            Agent
            <select value={agent} onChange={(evt) => setAgent(evt.target.value)}>
              {agents.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Provider
            <select
              value={providerId}
              onChange={(evt) => {
                const next = evt.target.value;
                setProviderId(next);
                const head = providers.find((item) => item.id === next)?.models[0]?.id ?? "";
                setModelId(head);
              }}
            >
              {providers.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name ?? item.id}
                </option>
              ))}
            </select>
          </label>
          <label>
            Model
            <select value={modelId} onChange={(evt) => setModelId(evt.target.value)}>
              {currentModels().map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name ?? item.id}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>

      <main className="main">
        <aside className="pane sessions">
          <div className="pane-title">
            Sessions
            <button type="button" onClick={() => void ensureSession()}>
              New
            </button>
          </div>
          <div className="list">
            {sessions.map((item) => (
              <button
                key={item.id}
                type="button"
                className={item.id === active ? "session active" : "session"}
                onClick={() => void switchSession(item.id)}
              >
                <div>{item.title || "Untitled"}</div>
                <div className="sub">{item.id}</div>
              </button>
            ))}
          </div>
        </aside>

        <section className="pane chat">
          <div className="pane-title">
            <span>{active ? `Session ${active}` : "No session selected"}</span>
            <span className="sub">status: {status}</span>
          </div>
          <div className="messages">
            {messages.map((item) => (
              <div key={item.id} className={item.role === "user" ? "msg user" : "msg assistant"}>
                <div className="meta">
                  {item.role} · {item.id}
                </div>
                <div className="body">
                  {item.parts.map((part, idx) => (
                    <div key={String(part.id ?? `part-${idx}`)} className="part">
                      {part.type === "tool" ? (
                        <code>
                          {part.tool} [{part.state?.status ?? "pending"}]
                        </code>
                      ) : (
                        <span>{part.text || ""}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <form className="composer" onSubmit={(evt) => void onSend(evt)}>
            <textarea
              value={input}
              onChange={(evt) => setInput(evt.target.value)}
              rows={4}
              placeholder="Type your message..."
            />
            <div className="actions">
              <button type="submit" disabled={busy}>
                {busy ? "Sending..." : "Send"}
              </button>
              <button type="button" disabled={!active} onClick={() => void onInterrupt()}>
                Interrupt
              </button>
            </div>
          </form>
          {error ? <div className="err">{error}</div> : null}
        </section>

        <aside className="pane side">
          <div className="pane-title">Pending Permission</div>
          <div className="list">
            {permissions.map((item) => (
              <div key={item.id} className="card">
                <div>
                  {item.permission} · {item.id}
                </div>
                <div className="actions">
                  <button type="button" onClick={() => void replyPermission(item.id, "once")}>
                    once
                  </button>
                  <button type="button" onClick={() => void replyPermission(item.id, "always")}>
                    always
                  </button>
                  <button type="button" onClick={() => void replyPermission(item.id, "reject")}>
                    reject
                  </button>
                </div>
              </div>
            ))}
          </div>
          <div className="pane-title">Pending Question</div>
          <div className="list">
            {questions.map((item) => (
              <div key={item.id} className="card">
                <div>{item.questions?.[0]?.question || item.id}</div>
                <div className="actions">
                  <button type="button" onClick={() => void replyQuestion(item.id, [["Yes"]])}>
                    yes
                  </button>
                  <button type="button" onClick={() => void rejectQuestion(item.id)}>
                    reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </aside>
      </main>
    </div>
  );
}
