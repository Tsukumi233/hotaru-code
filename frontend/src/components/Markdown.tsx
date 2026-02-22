import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import CodeBlock from "./CodeBlock";

type MarkdownProps = {
  content: string;
};

export default function Markdown({ content }: MarkdownProps) {
  return (
    <div className="markdown">
      <ReactMarkdown
        rehypePlugins={[rehypeHighlight]}
        components={{
          pre({ children }) {
            return <>{children}</>;
          },
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || "");
            const text = String(children).replace(/\n$/, "");
            if (match) {
              return <CodeBlock language={match[1]} code={text} className={className} />;
            }
            return (
              <code
                className="px-1.5 py-0.5 rounded-[var(--radius-sm)] bg-[var(--md-code-bg)] text-[var(--md-code-text)]
                  font-[var(--font-mono)] text-[0.9em]"
                {...props}
              >
                {children}
              </code>
            );
          },
          a({ href, children }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--md-link)] underline decoration-[var(--md-link)]/30 hover:decoration-[var(--md-link)]"
              >
                {children}
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
