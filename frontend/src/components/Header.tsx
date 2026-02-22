import type { Provider, ProviderModel, Agent, Theme } from "../types";

type HeaderProps = {
  agent: string;
  agents: Agent[];
  onAgentChange: (value: string) => void;
  providerId: string;
  providers: Provider[];
  onProviderChange: (value: string) => void;
  modelId: string;
  models: ProviderModel[];
  onModelChange: (value: string) => void;
  termOpen: boolean;
  onTermToggle: () => void;
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  onMenuToggle: () => void;
};

const THEME_ICONS: Record<Theme, string> = {
  system: "\u25D0",
  light: "\u2600",
  dark: "\u263E",
};

const THEME_CYCLE: Record<Theme, Theme> = {
  system: "light",
  light: "dark",
  dark: "system",
};

export default function Header({
  agent,
  agents,
  onAgentChange,
  providerId,
  providers,
  onProviderChange,
  modelId,
  models,
  onModelChange,
  termOpen,
  onTermToggle,
  theme,
  onThemeChange,
  onMenuToggle,
}: HeaderProps) {
  return (
    <header
      className="flex items-center gap-3 px-4 h-[var(--header-height)] flex-shrink-0
        bg-[var(--bg-surface)] border-b border-[var(--border-base)]"
    >
      {/* Mobile menu button */}
      <button
        type="button"
        onClick={onMenuToggle}
        className="md:hidden flex items-center justify-center w-8 h-8 rounded-[var(--radius-md)]
          bg-transparent border border-[var(--border-base)] text-[var(--text-base)]
          hover:bg-[var(--bg-hover)] cursor-pointer"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M2 4h12M2 8h12M2 12h12" />
        </svg>
      </button>

      {/* Brand */}
      <div className="font-[var(--font-mono)] text-[var(--font-size-sm)] tracking-wider uppercase text-[var(--text-strong)] font-medium">
        hotaru
      </div>

      <div className="flex-1" />

      {/* Controls */}
      <div className="flex items-center gap-2">
        <Select label="Agent" value={agent} onChange={onAgentChange}>
          {agents.map((a) => (
            <option key={a.name} value={a.name}>
              {a.name}
            </option>
          ))}
        </Select>

        <Select label="Provider" value={providerId} onChange={onProviderChange}>
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name ?? p.id}
            </option>
          ))}
        </Select>

        <Select label="Model" value={modelId} onChange={onModelChange}>
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name ?? m.id}
            </option>
          ))}
        </Select>

        <button
          type="button"
          onClick={onTermToggle}
          className={`flex items-center gap-1.5 px-2.5 py-1 text-[var(--font-size-sm)] rounded-[var(--radius-md)] border cursor-pointer transition-colors duration-[var(--transition-fast)]
            ${
              termOpen
                ? "bg-[var(--accent)] text-[var(--text-on-accent)] border-[var(--accent)]"
                : "bg-transparent text-[var(--text-base)] border-[var(--border-base)] hover:bg-[var(--bg-hover)]"
            }`}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="1" y="3" width="14" height="10" rx="1.5" />
            <path d="M4 7l2 2-2 2M8.5 11H11" />
          </svg>
          <span className="max-sm:hidden">Terminal</span>
        </button>

        <button
          type="button"
          onClick={() => onThemeChange(THEME_CYCLE[theme])}
          className="flex items-center justify-center w-8 h-8 rounded-[var(--radius-md)]
            bg-transparent border border-[var(--border-base)] text-[var(--text-base)]
            hover:bg-[var(--bg-hover)] cursor-pointer text-base"
          title={`Theme: ${theme}`}
        >
          {THEME_ICONS[theme]}
        </button>
      </div>
    </header>
  );
}

function Select({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="max-sm:hidden flex items-center gap-1.5 text-[var(--font-size-xs)] text-[var(--text-weak)]">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-[var(--bg-surface)] text-[var(--text-base)] text-[var(--font-size-sm)]
          border border-[var(--border-base)] rounded-[var(--radius-md)] px-2 py-1
          focus:outline-none focus:border-[var(--border-accent)]
          cursor-pointer"
      >
        {children}
      </select>
    </label>
  );
}
