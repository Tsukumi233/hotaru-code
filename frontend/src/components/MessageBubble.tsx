import type { Message } from "../types";
import MessagePart from "./MessagePart";

type MessageBubbleProps = {
  message: Message;
};

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div
      className={`rounded-[var(--radius-lg)] border px-4 py-3
        ${
          isUser
            ? "bg-[var(--bg-user)] border-[var(--border-user)]"
            : "bg-[var(--bg-assistant)] border-[var(--border-base)]"
        }`}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span
          className={`text-[var(--font-size-xs)] font-[var(--font-weight-medium)] uppercase tracking-wide
            ${isUser ? "text-[var(--accent-text)]" : "text-[var(--text-weak)]"}`}
        >
          {message.role}
        </span>
      </div>
      <div className="space-y-1">
        {message.parts.map((part, idx) => (
          <MessagePart key={String(part.id ?? `part-${idx}`)} part={part} />
        ))}
      </div>
    </div>
  );
}
