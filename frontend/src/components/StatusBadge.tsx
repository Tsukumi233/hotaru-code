type StatusBadgeProps = {
  status: string;
};

const STATUS_CONFIG: Record<string, { color: string; label: string; pulse?: boolean }> = {
  idle: { color: "var(--text-weaker)", label: "idle" },
  working: { color: "var(--accent)", label: "working", pulse: true },
  sending: { color: "var(--accent)", label: "sending", pulse: true },
  reconnecting: { color: "var(--warning)", label: "reconnecting", pulse: true },
  interrupted: { color: "var(--error)", label: "interrupted" },
  error: { color: "var(--error)", label: "error" },
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? { color: "var(--text-weaker)", label: status };
  return (
    <span className="inline-flex items-center gap-1 text-[var(--font-size-xs)]" style={{ color: config.color }}>
      <span
        className={`inline-block w-1.5 h-1.5 rounded-full ${config.pulse ? "animate-pulse" : ""}`}
        style={{ backgroundColor: config.color }}
      />
      {config.label}
    </span>
  );
}
