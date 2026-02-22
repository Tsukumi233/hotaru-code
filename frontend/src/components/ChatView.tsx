import type { FormEvent } from "react";
import type { Message, Permission, Question } from "../types";
import { useAutoScroll } from "../hooks/useAutoScroll";
import MessageBubble from "./MessageBubble";
import PermissionCard from "./PermissionCard";
import QuestionCard from "./QuestionCard";
import Composer from "./Composer";

type ChatViewProps = {
  messages: Message[];
  permissions: Permission[];
  questions: Question[];
  input: string;
  onInputChange: (value: string) => void;
  onSend: (e: FormEvent) => void;
  onInterrupt: () => void;
  busy: boolean;
  active: boolean;
  status: string;
  error: string;
  onReplyPermission: (id: string, reply: string) => void;
  onReplyQuestion: (id: string, answers: string[][]) => void;
  onRejectQuestion: (id: string) => void;
};

export default function ChatView({
  messages,
  permissions,
  questions,
  input,
  onInputChange,
  onSend,
  onInterrupt,
  busy,
  active,
  status,
  error,
  onReplyPermission,
  onReplyQuestion,
  onRejectQuestion,
}: ChatViewProps) {
  const { ref, pinned, scrollToBottom } = useAutoScroll([messages, permissions, questions]);

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-[var(--bg-surface)]">
      {/* Messages area */}
      <div ref={ref} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.length === 0 && !active && (
          <div className="flex flex-col items-center justify-center h-full text-[var(--text-weaker)]">
            <div className="text-[var(--font-size-xl)] font-[var(--font-weight-semibold)] text-[var(--text-weak)] mb-2">
              Hotaru
            </div>
            <div className="text-[var(--font-size-sm)]">Select a session or create a new one to get started</div>
          </div>
        )}
        {messages.length === 0 && active && (
          <div className="flex flex-col items-center justify-center h-full text-[var(--text-weaker)]">
            <div className="text-[var(--font-size-sm)]">Send a message to start the conversation</div>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {/* Inline permissions */}
        {permissions.map((perm) => (
          <PermissionCard key={perm.id} permission={perm} onReply={onReplyPermission} />
        ))}

        {/* Inline questions */}
        {questions.map((q) => (
          <QuestionCard key={q.id} question={q} onReply={onReplyQuestion} onReject={onRejectQuestion} />
        ))}
      </div>

      {/* Scroll to bottom button */}
      {!pinned && (
        <div className="flex justify-center -mt-10 relative z-10">
          <button
            type="button"
            onClick={scrollToBottom}
            className="px-3 py-1.5 rounded-full bg-[var(--bg-surface)] border border-[var(--border-base)]
              text-[var(--font-size-xs)] text-[var(--text-weak)] cursor-pointer
              shadow-[var(--shadow-md)] hover:bg-[var(--bg-hover)] transition-colors"
          >
            Scroll to bottom
          </button>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="px-4 py-2 text-[var(--font-size-sm)] text-[var(--error-text)] bg-[var(--error-soft)] border-t border-[var(--error)]/20">
          {error}
        </div>
      )}

      {/* Composer */}
      <Composer
        input={input}
        onInputChange={onInputChange}
        onSend={onSend}
        onInterrupt={onInterrupt}
        busy={busy}
        active={active}
      />
    </div>
  );
}
