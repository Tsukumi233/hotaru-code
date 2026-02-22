import { type FormEvent, useRef } from "react";

type ComposerProps = {
  input: string;
  onInputChange: (value: string) => void;
  onSend: (e: FormEvent) => void;
  onInterrupt: () => void;
  busy: boolean;
  active: boolean;
};

export default function Composer({ input, onInputChange, onSend, onInterrupt, busy, active }: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!busy && input.trim()) {
        onSend(e as unknown as FormEvent);
      }
    }
  }

  return (
    <form
      onSubmit={onSend}
      className="border-t border-[var(--border-base)] bg-[var(--bg-surface)] p-3"
    >
      <div className="flex gap-2 items-end">
        <textarea
          ref={ref}
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={onKeyDown}
          rows={3}
          placeholder="Type your message... (Enter to send, Shift+Enter for newline)"
          className="flex-1 resize-none rounded-[var(--radius-md)] border border-[var(--border-base)]
            bg-[var(--bg-raised)] text-[var(--text-base)] px-3 py-2
            font-[var(--font-sans)] text-[var(--font-size-base)]
            placeholder:text-[var(--text-weaker)]
            focus:outline-none focus:border-[var(--border-accent)] focus:ring-1 focus:ring-[var(--border-accent)]
            transition-colors"
        />
        <div className="flex flex-col gap-1.5">
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="px-4 py-2 rounded-[var(--radius-md)] font-[var(--font-weight-medium)] text-[var(--font-size-sm)]
              bg-[var(--accent)] text-[var(--text-on-accent)] border-none cursor-pointer
              hover:bg-[var(--accent-hover)] disabled:opacity-50 disabled:cursor-default transition-colors"
          >
            {busy ? "Sending..." : "Send"}
          </button>
          <button
            type="button"
            disabled={!active}
            onClick={onInterrupt}
            className="px-4 py-2 rounded-[var(--radius-md)] font-[var(--font-weight-medium)] text-[var(--font-size-sm)]
              bg-transparent text-[var(--error-text)] border border-[var(--error)]/30 cursor-pointer
              hover:bg-[var(--error-soft)] disabled:opacity-50 disabled:cursor-default transition-colors"
          >
            Interrupt
          </button>
        </div>
      </div>
    </form>
  );
}
