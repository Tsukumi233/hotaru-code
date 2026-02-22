import { useState, useCallback } from "react";

type CodeBlockProps = {
  language: string;
  code: string;
  className?: string;
};

export default function CodeBlock({ language, code, className }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const onCopy = useCallback(() => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [code]);

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--md-block-border)] bg-[var(--md-block-bg)] overflow-hidden my-2">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-[var(--md-block-border)] bg-[var(--md-code-bg)]">
        <span className="text-[var(--font-size-xs)] text-[var(--text-weaker)] font-[var(--font-mono)]">
          {language}
        </span>
        <button
          type="button"
          onClick={onCopy}
          className="flex items-center gap-1 px-1.5 py-0.5 text-[var(--font-size-xs)] text-[var(--text-weak)]
            bg-transparent border-none cursor-pointer hover:text-[var(--text-base)] transition-colors"
        >
          {copied ? (
            <>
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="var(--success)" strokeWidth="2">
                <path d="M3 8.5l3 3 7-7" />
              </svg>
              Copied
            </>
          ) : (
            <>
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                <rect x="5" y="5" width="8" height="8" rx="1" />
                <path d="M3 11V3h8" />
              </svg>
              Copy
            </>
          )}
        </button>
      </div>
      <div className="overflow-x-auto">
        <pre className="m-0 p-3 bg-[var(--md-code-bg)]">
          <code className={`${className ?? ""} font-[var(--font-mono)] text-[var(--font-size-sm)] leading-relaxed`}>
            {code}
          </code>
        </pre>
      </div>
    </div>
  );
}
