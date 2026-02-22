import { type FormEvent, useState, useCallback } from "react";
import { useTheme } from "./hooks/useTheme";
import { useProviders } from "./hooks/useProviders";
import { useSession } from "./hooks/useSession";
import { useMessages } from "./hooks/useMessages";
import { useEvents } from "./hooks/useEvents";
import { usePermissions } from "./hooks/usePermissions";
import { usePty } from "./hooks/usePty";
import * as api from "./api";
import Layout from "./components/Layout";
import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";

export default function App() {
  const { theme, setTheme } = useTheme();
  const { providers, agents, providerId, modelId, modelRef, agent, setAgent, setModelId, selectProvider, currentModels } = useProviders();
  const { sessions, active, loadSessions, switchSession, createSession } = useSession();
  const { messages, status, setStatus, loadMessages, applyEvent } = useMessages();
  const { permissions, questions, loadPending, replyPermission, replyQuestion, rejectQuestion } = usePermissions();
  const { terminals, activeTerm, termOpen, setActiveTerm, createPty, closePty, persistPty, toggleTerminal, removePty } = usePty();

  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const loadPendingForActive = useCallback(() => {
    void loadPending(active || undefined);
  }, [active, loadPending]);

  const loadMessagesWrapped = useCallback(async (id: string) => loadMessages(id), [loadMessages]);
  const loadPendingWrapped = useCallback(async (id: string) => loadPending(id), [loadPending]);

  useEvents({
    active,
    applyEvent,
    loadPending: loadPendingForActive,
    setStatus,
    onPtyRemoved: removePty,
  });

  // Bootstrap on mount
  useState(() => {
    void Promise.all([loadSessions(), loadPending()]);
  });

  async function onSend(evt: FormEvent): Promise<void> {
    evt.preventDefault();
    const content = input.trim();
    if (!content) return;
    setError("");
    setBusy(true);
    setStatus("working");
    try {
      const sessionId = await createSession(agent, modelRef, loadMessagesWrapped, loadPendingWrapped);
      await api.sessions.send(sessionId, { content, agent: agent || undefined, model: modelRef || undefined });
      setInput("");
      await Promise.all([loadSessions(), loadMessages(sessionId), loadPending(sessionId)]);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onInterrupt(): Promise<void> {
    if (!active) return;
    await api.sessions.interrupt(active);
    setStatus("interrupted");
  }

  function handleSwitch(id: string) {
    setSidebarOpen(false);
    void switchSession(id, loadMessagesWrapped, loadPendingWrapped);
  }

  function handleNew() {
    void createSession(agent, modelRef, loadMessagesWrapped, loadPendingWrapped);
  }

  return (
    <Layout
      sidebarOpen={sidebarOpen}
      onCloseSidebar={() => setSidebarOpen(false)}
      header={
        <Header
          agent={agent}
          agents={agents}
          onAgentChange={setAgent}
          providerId={providerId}
          providers={providers}
          onProviderChange={selectProvider}
          modelId={modelId}
          models={currentModels()}
          onModelChange={setModelId}
          termOpen={termOpen}
          onTermToggle={() => void toggleTerminal()}
          theme={theme}
          onThemeChange={setTheme}
          onMenuToggle={() => setSidebarOpen((prev) => !prev)}
        />
      }
      sidebar={
        <Sidebar
          sessions={sessions}
          active={active}
          status={status}
          onSwitch={handleSwitch}
          onNew={handleNew}
        />
      }
      termOpen={termOpen}
      terminals={terminals}
      activeTerm={activeTerm}
      onSelectTerm={setActiveTerm}
      onCreateTerm={() => void createPty()}
      onCloseTerm={(id) => void closePty(id)}
      onPersistTerm={persistPty}
    >
      <ChatView
        messages={messages}
        permissions={permissions}
        questions={questions}
        input={input}
        onInputChange={setInput}
        onSend={(e) => void onSend(e)}
        onInterrupt={() => void onInterrupt()}
        busy={busy}
        active={Boolean(active)}
        status={status}
        error={error}
        onReplyPermission={(id, reply) => void replyPermission(id, reply, active || undefined)}
        onReplyQuestion={(id, answers) => void replyQuestion(id, answers, active || undefined)}
        onRejectQuestion={(id) => void rejectQuestion(id, active || undefined)}
      />
    </Layout>
  );
}
