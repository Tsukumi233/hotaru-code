import type { Session } from "../types";
import StatusBadge from "./StatusBadge";

type SidebarProps = {
  sessions: Session[];
  active: string;
  status: string;
  onSwitch: (id: string) => void;
  onNew: () => void;
};

export default function Sidebar({ sessions, active, status, onSwitch, onNew }: SidebarProps) {
  return (
    <div className="flex flex-col h-full">
      <div
        className="flex items-center justify-between px-3 py-2.5 border-b border-[var(--border-weak)]
          text-[var(--font-size-sm)] font-[var(--font-weight-semibold)] text-[var(--text-strong)]"
      >
        <span>Sessions</span>
        <button
          type="button"
          onClick={onNew}
          className="flex items-center gap-1 px-2 py-0.5 text-[var(--font-size-xs)]
            bg-[var(--accent)] text-[var(--text-on-accent)] rounded-[var(--radius-md)]
            border-none cursor-pointer hover:bg-[var(--accent-hover)] transition-colors"
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M8 3v10M3 8h10" />
          </svg>
          New
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sessions.length === 0 && (
          <div className="px-3 py-6 text-center text-[var(--font-size-sm)] text-[var(--text-weaker)]">
            No sessions yet
          </div>
        )}
        {sessions.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onSwitch(item.id)}
            className={`w-full text-left px-3 py-2 rounded-[var(--radius-md)] border cursor-pointer
              transition-colors duration-[var(--transition-fast)] group
              ${
                item.id === active
                  ? "bg-[var(--accent-soft)] border-[var(--border-accent)] text-[var(--text-strong)]"
                  : "bg-transparent border-transparent text-[var(--text-base)] hover:bg-[var(--bg-hover)]"
              }`}
          >
            <div className="text-[var(--font-size-sm)] font-[var(--font-weight-medium)] truncate">
              {item.title || "Untitled"}
            </div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-[var(--font-size-xs)] text-[var(--text-weaker)] truncate">
                {item.id.slice(0, 8)}
              </span>
              {item.id === active && <StatusBadge status={status} />}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
