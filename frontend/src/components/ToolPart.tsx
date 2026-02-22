import { useState } from "react";
import type { Part } from "../types";

type ToolPartProps = {
  part: Part;
};

const STATUS_ICON: Record<string, { icon: string; color: string; spin?: boolean }> = {
  running: { icon: "\u25CF", color: "var(--accent)", spin: true },
  completed: { icon: "\u2713", color: "var(--success)" },
  error: { icon: "\u2717", color: "var(--error)" },
  pending: { icon: "\u25CB", color: "var(--text-weaker)" },
};

export default function ToolPart({ part }: ToolPartProps) {
  const [expanded, setExpanded] = useState(false);
  const status = part.state?.status ?? "pending";
  const config = STATUS_ICON[status] ?? STATUS_ICON.pending;

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-base)] bg-[var(--bg-inline)] overflow-hidden my-1">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-transparent border-none cursor-pointer
          text-left text-[var(--font-size-sm)] text-[var(--text-base)] hover:bg-[var(--bg-hover)] transition-colors"
      >
        <span className={config.spin ? "animate-pulse" : ""} style={{ color: config.color }}>
          {config.icon}
        </span>
        <span className="font-[var(--font-mono)] text-[var(--font-size-sm)] font-[var(--font-weight-medium)]">
          {part.tool}
        </span>
        <span className="text-[var(--font-size-xs)] text-[var(--text-weaker)]">{status}</span>
        <span className="ml-auto text-[var(--font-size-xs)] text-[var(--text-weaker)]">
          {expanded ? "\u25B2" : "\u25BC"}
        </span>
      </button>
      {expanded && part.text && (
        <div className="px-3 py-2 border-t border-[var(--border-weak)] bg-[var(--md-code-bg)]">
          <pre className="m-0 text-[var(--font-size-sm)] font-[var(--font-mono)] text-[var(--text-base)] whitespace-pre-wrap break-words overflow-x-auto max-h-64 overflow-y-auto">
            {part.text}
          </pre>
        </div>
      )}
    </div>
  );
}
