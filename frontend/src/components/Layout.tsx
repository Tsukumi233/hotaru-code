import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import type { LocalPty } from "../types";
import TerminalPanel from "../TerminalPanel";
import ResizeHandle from "./ResizeHandle";

type LayoutProps = {
  sidebar: ReactNode;
  header: ReactNode;
  children: ReactNode;
  termOpen: boolean;
  terminals: LocalPty[];
  activeTerm: string;
  onSelectTerm: (id: string) => void;
  onCreateTerm: () => void;
  onCloseTerm: (id: string) => void;
  onPersistTerm: (pty: LocalPty) => void;
  sidebarOpen: boolean;
  onCloseSidebar: () => void;
};

export default function Layout({
  sidebar,
  header,
  children,
  termOpen,
  terminals,
  activeTerm,
  onSelectTerm,
  onCreateTerm,
  onCloseTerm,
  onPersistTerm,
  sidebarOpen,
  onCloseSidebar,
}: LayoutProps) {
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const [termHeight, setTermHeight] = useState(300);

  const onSidebarResize = useCallback((delta: number) => {
    setSidebarWidth((w) => Math.max(200, Math.min(400, w + delta)));
  }, []);

  const onTermResize = useCallback((delta: number) => {
    setTermHeight((h) => Math.max(120, Math.min(600, h - delta)));
  }, []);

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[var(--bg-base)]">
      {header}
      <div className="flex flex-1 min-h-0">
        {/* Mobile sidebar overlay */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-40 bg-[var(--bg-overlay)] md:hidden"
            onClick={onCloseSidebar}
          />
        )}

        {/* Sidebar */}
        <aside
          className={`
            flex-shrink-0 bg-[var(--bg-surface)] border-r border-[var(--border-base)]
            flex flex-col
            max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-50 max-md:w-[280px]
            max-md:shadow-lg max-md:transition-transform max-md:duration-200
            ${sidebarOpen ? "max-md:translate-x-0" : "max-md:-translate-x-full"}
          `}
          style={{ width: sidebarWidth }}
        >
          {sidebar}
        </aside>

        {/* Sidebar resize handle (desktop only) */}
        <div className="hidden md:block">
          <ResizeHandle direction="horizontal" onResize={onSidebarResize} />
        </div>

        {/* Main content area */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          {children}

          {/* Terminal panel */}
          {termOpen && (
            <>
              <ResizeHandle direction="vertical" onResize={onTermResize} />
              <div style={{ height: termHeight }} className="flex-shrink-0">
                <TerminalPanel
                  terminals={terminals}
                  active={activeTerm}
                  onSelect={onSelectTerm}
                  onCreate={onCreateTerm}
                  onClose={onCloseTerm}
                  onPersist={onPersistTerm}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
