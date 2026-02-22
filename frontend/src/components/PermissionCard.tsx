import type { Permission } from "../types";

type PermissionCardProps = {
  permission: Permission;
  onReply: (id: string, reply: string) => void;
};

export default function PermissionCard({ permission, onReply }: PermissionCardProps) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--warning)]/30 bg-[var(--warning-soft)] p-4 my-2">
      <div className="flex items-center gap-2 mb-2">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="var(--warning)" strokeWidth="1.5">
          <path d="M8 1L1 14h14L8 1zM8 6v4M8 12h.01" />
        </svg>
        <span className="text-[var(--font-size-sm)] font-[var(--font-weight-semibold)] text-[var(--warning-text)]">
          Permission Required
        </span>
      </div>
      <div className="text-[var(--font-size-sm)] text-[var(--text-base)] mb-3 font-[var(--font-mono)]">
        {permission.permission}
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onReply(permission.id, "once")}
          className="px-3 py-1.5 text-[var(--font-size-sm)] rounded-[var(--radius-md)]
            bg-[var(--accent)] text-[var(--text-on-accent)] border-none cursor-pointer
            hover:bg-[var(--accent-hover)] transition-colors"
        >
          Allow Once
        </button>
        <button
          type="button"
          onClick={() => onReply(permission.id, "always")}
          className="px-3 py-1.5 text-[var(--font-size-sm)] rounded-[var(--radius-md)]
            bg-[var(--success)] text-[var(--text-on-accent)] border-none cursor-pointer
            hover:bg-[var(--success)]/80 transition-colors"
        >
          Always
        </button>
        <button
          type="button"
          onClick={() => onReply(permission.id, "reject")}
          className="px-3 py-1.5 text-[var(--font-size-sm)] rounded-[var(--radius-md)]
            bg-transparent text-[var(--error-text)] border border-[var(--error)]/30 cursor-pointer
            hover:bg-[var(--error-soft)] transition-colors"
        >
          Reject
        </button>
      </div>
    </div>
  );
}
