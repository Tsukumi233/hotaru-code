import Terminal from "./Terminal";
import type { LocalPty } from "./types";

type TerminalPanelProps = {
  terminals: LocalPty[];
  active: string;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onClose: (id: string) => void;
  onPersist: (pty: LocalPty) => void;
};

export default function TerminalPanel({ terminals, active, onSelect, onCreate, onClose, onPersist }: TerminalPanelProps) {
  const current = terminals.find((t) => t.id === active);

  return (
    <div className="h-full flex flex-col bg-[var(--terminal-bg)] border-t border-[var(--terminal-border)]">
      {/* Tab bar */}
      <div className="flex items-center bg-[var(--terminal-tab-bg)] h-9 px-1 gap-0.5 flex-shrink-0">
        {terminals.map((t, idx) => (
          <button
            key={t.id}
            type="button"
            onClick={() => onSelect(t.id)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-t-[var(--radius-sm)] border-none cursor-pointer
              text-[var(--font-size-sm)] font-[var(--font-mono)] transition-colors
              ${
                t.id === active
                  ? "bg-[var(--terminal-tab-active)] text-[var(--terminal-tab-text-active)]"
                  : "bg-transparent text-[var(--terminal-tab-text)] hover:text-[var(--terminal-tab-text-active)]"
              }`}
          >
            <span>{t.title || `Terminal ${idx + 1}`}</span>
            <span
              onClick={(e) => {
                e.stopPropagation();
                onClose(t.id);
              }}
              className="text-[var(--font-size-xs)] opacity-50 hover:opacity-100 cursor-pointer ml-1"
            >
              ✕
            </span>
          </button>
        ))}
        <button
          type="button"
          onClick={onCreate}
          className="border-none bg-transparent text-[var(--terminal-tab-text)] text-base px-2.5 py-1 cursor-pointer
            hover:text-[var(--terminal-tab-text-active)] transition-colors"
        >
          +
        </button>
      </div>

      {/* Terminal content */}
      <div className="flex-1 min-h-0 relative">
        {current && <Terminal key={active} pty={current} onPersist={onPersist} />}
      </div>
    </div>
  );
}
